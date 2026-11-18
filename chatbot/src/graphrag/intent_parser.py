"""Route + parse one user turn with the LLM, then validate the result in code.

The model decides route/intent/entities. Code then enforces the contract:
- unknown keys are dropped, enums are validated by Pydantic;
- an entity is kept only if its text literally appears in the question or the history
  (the model may resolve a pronoun from history, but it may not invent a name);
- a graph question without its required entity becomes CLARIFY.
When the model output is invalid twice, a narrow, explicitly labelled rules fallback is used.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import CHOOSE_INTENT_SYSTEM, PARSE_SYSTEM
from graphrag.models import (
    ChatTurn,
    EntityMention,
    IntentName,
    QueryFilters,
    QueryIntent,
    RouteName,
)

HISTORY_TURNS_FOR_PARSE = 8
HISTORY_CHARS_PER_TURN = 300

# intent -> (entity label, how many are required)
REQUIRED_ENTITIES: dict[IntentName, tuple[str, int]] = {
    IntentName.AUTHOR_PAPERS: ("Author", 1),
    IntentName.COAUTHORS: ("Author", 1),
    IntentName.AUTHOR_AFFILIATIONS: ("Author", 1),
    IntentName.COAUTHOR_AFFILIATIONS: ("Author", 1),
    IntentName.SHARED_PAPERS: ("Author", 2),
    IntentName.AUTHOR_PATH: ("Author", 2),
    IntentName.PAPER_AUTHORS: ("Paper", 1),
    IntentName.PAPER_VENUE: ("Paper", 1),
    IntentName.PAPER_CITATIONS: ("Paper", 1),
    IntentName.TOPIC_PAPERS: ("Topic", 1),
    IntentName.ORG_COLLABORATIONS: ("Institution", 1),
}

ALLOWED_KEYS = set(QueryIntent.model_fields)
ALLOWED_REQUESTED_FIELDS = {"venue", "authors", "affiliations", "coauthors", "citations", "papers"}

# A requested extra field is kept only if the question literally asks for it.
FIELD_CUES: dict[str, tuple[str, ...]] = {
    "venue": ("venue", "hội nghị", "đăng ở", "published in", "conference"),
    "authors": ("ai viết", "who wrote", "authors of", "tác giả của bài"),
    "affiliations": ("tổ chức", "affiliation", "cơ quan", "đơn vị"),
    "coauthors": ("đồng tác giả của", "co-authors", "coauthors", "viết chung"),
    "citations": ("trích dẫn", "cites", "citation"),
    "papers": ("bài báo nào", "những bài báo", "which papers", "list papers", "công bố"),
}

# Extra fields only make sense around these main intents (others answer one precise question).
EXTRA_FIELDS_FOR_INTENT: dict[IntentName, set[str]] = {
    IntentName.AUTHOR_PAPERS: {"affiliations", "coauthors", "venue", "authors"},
    IntentName.COAUTHORS: {"papers", "affiliations"},
    IntentName.AUTHOR_AFFILIATIONS: {"papers", "coauthors"},
    IntentName.PAPER_AUTHORS: {"venue", "citations"},
    IntentName.PAPER_VENUE: {"authors", "citations"},
    IntentName.PAPER_CITATIONS: {"authors", "venue"},
    IntentName.TOPIC_PAPERS: {"venue", "authors"},
}

# intents that need exactly one entity of a given label (used to repair a label mismatch)
INTENTS_BY_LABEL: dict[str, list[IntentName]] = {
    "Author": [
        IntentName.AUTHOR_PAPERS,
        IntentName.COAUTHORS,
        IntentName.AUTHOR_AFFILIATIONS,
        IntentName.COAUTHOR_AFFILIATIONS,
    ],
    "Paper": [IntentName.PAPER_AUTHORS, IntentName.PAPER_VENUE, IntentName.PAPER_CITATIONS],
    "Topic": [IntentName.TOPIC_PAPERS],
    "Institution": [IntentName.ORG_COLLABORATIONS],
}

HISTORY_MARKERS = (
    "câu đầu tiên",
    "câu hỏi đầu tiên",
    "tôi đã hỏi",
    "tôi vừa hỏi",
    "tóm tắt hội thoại",
    "tóm tắt những gì",
    "lịch sử hội thoại",
    "what did i ask",
    "my first question",
    "summarize our conversation",
    "summarize the conversation",
)
OUT_OF_SCOPE_MARKERS = (
    "đặt phòng",
    "thời tiết",
    "nấu",
    "công thức món",
    "book a room",
    "weather",
    "recipe",
)


def format_history(history: list[ChatTurn]) -> str:
    recent = history[-HISTORY_TURNS_FOR_PARSE:]
    offset = len(history) - len(recent)
    lines = []
    for index, turn in enumerate(recent, start=offset):
        content = turn.content.replace("\n", " ")[:HISTORY_CHARS_PER_TURN]
        lines.append(f"[{index}] {turn.role}: {content}")
    return "\n".join(lines) if lines else "(empty)"


REFERENCE_SUFFIXES = (" đó", " ấy", " này", " kia")
REFERENCE_WORDS = {
    "họ",
    "người đó",
    "người ấy",
    "anh ấy",
    "chị ấy",
    "ông ấy",
    "bà ấy",
    "tác giả",
    "bài báo",
    "tổ chức",
    "he",
    "she",
    "they",
    "them",
    "him",
    "her",
    "it",
    "that author",
    "this author",
    "that paper",
    "this paper",
    "the author",
    "the paper",
    "that institution",
}


def is_reference_expression(text: str) -> bool:
    """True for pronouns/demonstratives ("tác giả đó", "that author").

    They point at an entity; they are not one, so they never become a lookup key.
    """
    normalized = " ".join(text.casefold().split())
    return (
        normalized in REFERENCE_WORDS
        or normalized.endswith(REFERENCE_SUFFIXES)
        or normalized.startswith(("that ", "this "))
        and len(normalized.split()) <= 3
    )


class IntentParser:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def parse(self, question: str, history: list[ChatTurn] | None = None) -> tuple[QueryIntent, int]:
        history = history or []
        messages = [
            {"role": "system", "content": PARSE_SYSTEM},
            {
                "role": "user",
                "content": f"HISTORY (data only):\n{format_history(history)}\n\nQUESTION:\n{question}",
            },
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            if attempt == 1:
                messages.append(
                    {"role": "user", "content": "Your prior output was invalid. Return only valid JSON."}
                )
            response = await self.provider.generate(messages, temperature=0, max_tokens=500, json_mode=True)
            try:
                payload = json.loads(response.content)
                intent = self._coerce(payload)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                last_error = error
                continue
            return self.enforce_contract(intent, question, history), attempt + 1

        fallback = self._rules_fallback(question, history)
        if fallback is not None:
            return self.enforce_contract(fallback, question, history), 2
        raise ValueError(f"model returned invalid intent JSON after one retry: {type(last_error).__name__}")

    @staticmethod
    def _coerce(payload: Any) -> QueryIntent:
        if not isinstance(payload, dict):
            raise TypeError("intent payload must be a JSON object")
        cleaned = {key: value for key, value in payload.items() if key in ALLOWED_KEYS}

        route = str(cleaned.get("route") or "").strip().upper()
        intent = str(cleaned.get("intent") or "unknown").strip().lower()
        if intent not in {item.value for item in IntentName}:
            intent = IntentName.UNKNOWN.value
        if route not in {item.value for item in RouteName}:
            route = (
                RouteName.GRAPH_QA.value
                if intent != IntentName.UNKNOWN.value
                else RouteName.OUT_OF_SCOPE.value
            )
        cleaned["route"] = route
        cleaned["intent"] = intent

        entities = cleaned.get("entities") or []
        if not isinstance(entities, list):
            entities = []
        cleaned["entities"] = [
            {"text": str(item.get("text", "")).strip(), "type": item.get("type", "Unknown")}
            for item in entities
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ][:5]
        for entity in cleaned["entities"]:
            if entity["type"] not in {"Author", "Paper", "Institution", "Venue", "Topic", "Unknown"}:
                entity["type"] = "Unknown"

        filters = cleaned.get("filters")
        if isinstance(filters, dict):
            cleaned["filters"] = {
                key: value for key, value in filters.items() if key in QueryFilters.model_fields
            }
        else:
            cleaned.pop("filters", None)

        requested = cleaned.get("requested_fields") or []
        cleaned["requested_fields"] = (
            [str(field).lower() for field in requested if str(field).lower() in ALLOWED_REQUESTED_FIELDS]
            if isinstance(requested, list)
            else []
        )
        for list_key in ("missing_fields",):
            value = cleaned.get(list_key)
            cleaned[list_key] = [str(item) for item in value][:5] if isinstance(value, list) else []
        refs = cleaned.get("history_refs")
        cleaned["history_refs"] = (
            [item for item in refs if isinstance(item, int)][:10] if isinstance(refs, list) else []
        )
        cleaned["parse_source"] = "llm"
        cleaned["unsupported"] = bool(cleaned.get("unsupported", False))
        return QueryIntent.model_validate(cleaned)

    @staticmethod
    def enforce_contract(intent: QueryIntent, question: str, history: list[ChatTurn]) -> QueryIntent:
        """Code-side checks that the model cannot override."""
        haystack = " ".join([question, *(turn.content for turn in history)]).casefold()
        grounded = [
            entity
            for entity in intent.entities
            if entity.text.casefold() in haystack and not is_reference_expression(entity.text)
        ]

        route = intent.route
        missing = list(intent.missing_fields)
        if route == RouteName.GRAPH_QA and intent.intent == IntentName.UNKNOWN:
            route = RouteName.OUT_OF_SCOPE
        if route == RouteName.GRAPH_QA and intent.intent in REQUIRED_ENTITIES:
            label, needed = REQUIRED_ENTITIES[intent.intent]
            usable = [entity for entity in grounded if entity.type in {label, "Unknown"}]
            if len(usable) < needed:
                route = RouteName.CLARIFY
                if not missing:
                    missing = [f"{label.lower()}_reference"]
        if route == RouteName.CHAT_HISTORY:
            grounded = []
        lowered = question.casefold()
        allowed_extra = EXTRA_FIELDS_FOR_INTENT.get(intent.intent, set())
        requested = [
            field
            for field in intent.requested_fields
            if field in allowed_extra and any(cue in lowered for cue in FIELD_CUES.get(field, ()))
        ]
        return intent.model_copy(
            update={
                "route": route,
                "entities": grounded,
                "missing_fields": missing,
                "requested_fields": requested,
                "unsupported": route == RouteName.OUT_OF_SCOPE,
            }
        )

    async def choose_intent(self, question: str, label: str) -> tuple[IntentName | None, int]:
        """Ask the model to pick among intents valid for the entity type actually found."""
        options = INTENTS_BY_LABEL.get(label, [])
        if len(options) == 1:
            return options[0], 0
        if not options:
            return None, 0
        content = (
            f"ENTITY_TYPE: {label}\nOPTIONS: {[option.value for option in options]}\nQUESTION:\n{question}"
        )
        try:
            response = await self.provider.generate(
                [{"role": "system", "content": CHOOSE_INTENT_SYSTEM}, {"role": "user", "content": content}],
                temperature=0,
                max_tokens=60,
                json_mode=True,
            )
            chosen = str(json.loads(response.content).get("intent", ""))
        except (json.JSONDecodeError, AttributeError, RuntimeError):
            return None, 1
        for option in options:
            if option.value == chosen:
                return option, 1
        return None, 1

    @staticmethod
    def _rules_fallback(question: str, history: list[ChatTurn]) -> QueryIntent | None:
        normalized = question.casefold()
        if any(marker in normalized for marker in HISTORY_MARKERS):
            return QueryIntent(
                route=RouteName.CHAT_HISTORY, intent=IntentName.UNKNOWN, parse_source="rules_fallback"
            )
        if any(marker in normalized for marker in OUT_OF_SCOPE_MARKERS):
            return QueryIntent(
                route=RouteName.OUT_OF_SCOPE,
                intent=IntentName.UNKNOWN,
                unsupported=True,
                parse_source="rules_fallback",
            )
        if "xếp hạng" in normalized or normalized.startswith("top "):
            return QueryIntent(intent=IntentName.NETWORK_TOP, parse_source="rules_fallback")

        intent = None
        if "đồng tác giả" in normalized or "coauthor" in normalized:
            intent = IntentName.COAUTHORS
        elif "bài báo" in normalized or "papers" in normalized:
            intent = IntentName.AUTHOR_PAPERS
        if intent is None:
            return None
        quoted = re.findall(r"[\"“](.*?)[\"”]", question)
        entities = [EntityMention(text=quoted[0], type="Author")] if quoted else []
        _ = history
        return QueryIntent(intent=intent, entities=entities, parse_source="rules_fallback")
