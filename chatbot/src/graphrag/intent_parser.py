"""One-retry JSON parser with a narrow deterministic fallback.

The LLM owns semantics (route/intent/entities). Two code-owned, deterministic layers sit on
top and never invent meaning:

1. `_normalize_route`: resolves *self-contradiction* in the model's own output. If the model
   emitted a concrete graph intent AND the entity mentions that intent needs (or an entity-free
   intent like network_top) yet also said route=clarify with nothing missing, the clarify label
   contradicts the rest of the same object, so we trust the concrete signal.
2. `_rules_fallback`: a narrow net for *entity-free* routing only (conversation meta-questions,
   off-domain refusals, network-wide ranking). It never fabricates entities; entity-bearing
   questions the base model fails to extract stay failures and are reported honestly.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import ROUTE_PARSE_SYSTEM, build_parse_user
from graphrag.models import EntityMention, IntentName, QueryFilters, QueryIntent, RouteName

# Deterministic markers for entity-free routes. Kept intentionally narrow: these decide routing
# only when the LLM gave up (intent=unknown) or produced malformed JSON, never entity extraction.
CHAT_HISTORY_MARKERS = (
    "câu đầu tiên",
    "câu hỏi đầu",
    "tóm tắt hội thoại",
    "tóm tắt những gì tôi",
    "lịch sử hội thoại",
    "những gì tôi đã hỏi",
    "trước đó tôi",
    "tôi đã hỏi",
)
OUT_OF_SCOPE_MARKERS = (
    "đặt phòng",
    "thời tiết",
    "nấu",
    "bóng đá",
    "bài thơ",
    "cổ phiếu",
    "netflix",
    "chuyến bay",
    "tổng thống",
    "booking",
    "weather",
)
RANKING_MARKERS = ("xếp hạng", "top tác giả", "top author", "nhiều đồng tác giả nhất")

INTENT_ENTITY_REQUIREMENTS: dict[IntentName, tuple[str, int]] = {
    IntentName.AUTHOR_PAPERS: ("Author", 1),
    IntentName.COAUTHORS: ("Author", 1),
    IntentName.SHARED_PAPERS: ("Author", 2),
    IntentName.AUTHOR_AFFILIATIONS: ("Author", 1),
    IntentName.COAUTHOR_AFFILIATIONS: ("Author", 1),
    IntentName.PAPER_AUTHORS: ("Paper", 1),
    IntentName.TOPIC_PAPERS: ("Topic", 1),
    IntentName.PAPER_VENUE: ("Paper", 1),
    IntentName.PAPER_CITATIONS: ("Paper", 1),
    IntentName.ORG_COLLABORATIONS: ("Institution", 1),
    IntentName.AUTHOR_PATH: ("Author", 2),
}


class IntentParser:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def parse(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> tuple[QueryIntent, int]:
        history = history or []
        messages = [
            {"role": "system", "content": ROUTE_PARSE_SYSTEM},
            {"role": "user", "content": build_parse_user(question, history)},
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            if attempt == 1:
                messages.append(
                    {"role": "user", "content": "Your prior output was invalid. Return only valid JSON."}
                )
            response = await self.provider.generate(
                messages,
                temperature=0,
                max_tokens=500,
                json_mode=True,
            )
            try:
                payload = json.loads(response.content)
                intent = QueryIntent.model_validate(payload)
                contract_error = self._entity_contract_error(intent)
                if contract_error is not None and attempt == 0:
                    messages.extend(
                        [
                            {"role": "assistant", "content": response.content},
                            {
                                "role": "user",
                                "content": (
                                    f"Your JSON is inconsistent: {contract_error}. "
                                    "Re-evaluate the route, intent, and entity types. Return only JSON."
                                ),
                            },
                        ]
                    )
                    continue
                return self._reconcile(intent, question), attempt + 1
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = error

        fallback = self._rules_fallback(question)
        if fallback is not None:
            return fallback, 2
        raise ValueError(f"model returned invalid intent JSON after one retry: {type(last_error).__name__}")

    @staticmethod
    def _entity_contract_error(intent: QueryIntent) -> str | None:
        """Explain a graph intent/entity mismatch so the model can correct itself once."""
        if intent.route != RouteName.GRAPH_QA:
            return None
        required = INTENT_ENTITY_REQUIREMENTS.get(intent.intent)
        if required is None:
            return None
        label, count = required
        matching_count = sum(entity.type in {label, "Unknown"} for entity in intent.entities)
        if matching_count >= count:
            return None
        return f"intent {intent.intent.value} requires {count} {label} entity mention(s)"

    def _reconcile(self, intent: QueryIntent, question: str) -> QueryIntent:
        """Apply the two deterministic layers to a valid model decision."""
        intent = self._normalize_route(intent)
        if intent.intent == IntentName.UNKNOWN and intent.route in {
            RouteName.GRAPH_QA,
            RouteName.CLARIFY,
        }:
            fallback = self._rules_fallback(question)
            if fallback is not None:
                return fallback
        return intent

    @staticmethod
    def _normalize_route(intent: QueryIntent) -> QueryIntent:
        """Resolve a self-contradictory clarify label using the model's own concrete signals."""
        if intent.route != RouteName.CLARIFY:
            return intent
        if intent.intent == IntentName.UNKNOWN:
            return intent
        if intent.missing_fields:
            return intent
        needs_entity = intent.intent != IntentName.NETWORK_TOP
        has_usable_signal = (not needs_entity) or bool(intent.entities)
        if has_usable_signal:
            return intent.model_copy(update={"route": RouteName.GRAPH_QA})
        return intent

    @staticmethod
    def _rules_fallback(question: str) -> QueryIntent | None:
        normalized = question.casefold()
        base = QueryFilters()

        # Conversation meta-question -> answer from history (entity-free).
        if any(marker in normalized for marker in CHAT_HISTORY_MARKERS):
            return QueryIntent(
                route=RouteName.CHAT_HISTORY,
                intent=IntentName.UNKNOWN,
                filters=base,
                parse_source="rules_fallback",
            )

        # Off-domain -> refuse (entity-free).
        if any(marker in normalized for marker in OUT_OF_SCOPE_MARKERS):
            return QueryIntent(
                route=RouteName.OUT_OF_SCOPE,
                intent=IntentName.UNKNOWN,
                filters=base,
                unsupported=True,
                parse_source="rules_fallback",
            )

        # Network-wide ranking -> no entity to link (entity-free).
        if any(marker in normalized for marker in RANKING_MARKERS) or normalized.startswith("top "):
            return QueryIntent(
                route=RouteName.GRAPH_QA,
                intent=IntentName.NETWORK_TOP,
                filters=base,
                parse_source="rules_fallback",
            )

        # Narrow net for quoted-entity questions (only fires on malformed JSON with a clear
        # quoted name). Never fabricates an entity from free text.
        intent = IntentName.UNKNOWN
        label = "Unknown"
        if "đồng tác giả" in normalized or "coauthor" in normalized:
            intent, label = IntentName.COAUTHORS, "Author"
        elif "bài báo" in normalized or "papers" in normalized:
            intent, label = IntentName.AUTHOR_PAPERS, "Author"
        else:
            return None
        quoted = re.findall(r"[\"“](.*?)[\"”]", question)
        if not quoted:
            return None
        return QueryIntent(
            route=RouteName.GRAPH_QA,
            intent=intent,
            entities=[EntityMention(text=quoted[0], type=label)],
            filters=base,
            parse_source="rules_fallback",
        )
