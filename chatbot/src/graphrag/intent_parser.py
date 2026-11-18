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

INTENT_DESCRIPTIONS: dict[IntentName, str] = {
    IntentName.AUTHOR_PAPERS: "các bài báo/công bố do một tác giả viết",
    IntentName.COAUTHORS: "những người đồng tác giả của một tác giả",
    IntentName.SHARED_PAPERS: "bài báo chung của hai tác giả",
    IntentName.AUTHOR_AFFILIATIONS: "cơ quan/tổ chức/affiliation của một tác giả theo bài báo",
    IntentName.COAUTHOR_AFFILIATIONS: "cơ quan của các đồng tác giả của một tác giả",
    IntentName.PAPER_AUTHORS: "danh sách tác giả đã viết một bài báo",
    IntentName.TOPIC_PAPERS: "các bài báo thuộc một chủ đề",
    IntentName.PAPER_VENUE: "venue nơi một bài báo xuất hiện",
    IntentName.PAPER_CITATIONS: "trích dẫn đi/đến của một bài báo",
    IntentName.ORG_COLLABORATIONS: "các tổ chức khác hợp tác với một tổ chức",
    IntentName.AUTHOR_PATH: "đường đồng tác giả giữa hai tác giả",
    IntentName.NETWORK_TOP: "network-wide author ranking without a named entity",
    IntentName.UNKNOWN: "unsupported or unclear graph request",
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

    async def repair_with_catalog_context(
        self,
        question: str,
        history: list[dict[str, str]],
        previous: QueryIntent,
        catalog_mentions: list[EntityMention],
    ) -> tuple[QueryIntent | None, int]:
        """Ask the LLM once to repair a parse that conflicts with exact catalog entities.

        The model still decides semantics. Code only supplies server-derived entity names/types
        and accepts a graph intent when its required entity contract can be satisfied entirely
        from those exact catalog mentions.
        """
        candidates = [mention.model_dump(mode="json") for mention in catalog_mentions]
        allowed: list[IntentName] = []
        for intent_name, (label, count) in INTENT_ENTITY_REQUIREMENTS.items():
            if sum(mention.type == label for mention in catalog_mentions) >= count:
                allowed.append(intent_name)
        if not allowed:
            return None, 0
        # The model may keep the original refusal when a catalog name is only incidental
        # (for example, a weather question mentioning a university).
        allowed.append(IntentName.UNKNOWN)
        options = {intent_name.value: INTENT_DESCRIPTIONS[intent_name] for intent_name in allowed}
        messages = [
            {
                "role": "system",
                "content": (
                    "TASK=CATALOG_INTENT_REPAIR. Select the single intent that matches the "
                    "question's requested relationship. Catalog entity names and types are "
                    "authoritative. Phân loại theo thứ người dùng muốn nhận về, không chỉ theo "
                    "loại entity. Ví dụ: 'Bài báo của Alice?' -> author_papers; 'Alice viết với "
                    "ai?' -> coauthors; 'Alice gắn với tổ chức/cơ quan nào?' -> "
                    "author_affiliations; 'Cơ quan của đồng tác giả Alice?' -> "
                    "coauthor_affiliations; 'Ai viết bài Paper X?' -> paper_authors. Return only "
                    'JSON: {"intent":"one allowed key"}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"QUESTION={json.dumps(question, ensure_ascii=False)}\n"
                    f"HISTORY={json.dumps(history, ensure_ascii=False)}\n"
                    f"CATALOG_ENTITIES={json.dumps(candidates, ensure_ascii=False)}\n"
                    f"ALLOWED_INTENTS={json.dumps(options, ensure_ascii=False)}\n"
                    f"REJECTED_PRIOR_INTENT={previous.intent.value}\n"
                    "Choose by relationship direction: an author's institutions are "
                    "author_affiliations; an institution's partner institutions are "
                    "org_collaborations; authors of a paper are paper_authors; papers of an "
                    "author are author_papers. Return only the one-key JSON object."
                ),
            },
        ]
        try:
            response = await self.provider.generate(
                messages,
                temperature=0,
                max_tokens=80,
                json_mode=True,
            )
            payload = json.loads(response.content)
            chosen = IntentName(str(payload["intent"]).casefold())
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None, 1

        if chosen not in allowed:
            return None, 1
        required = INTENT_ENTITY_REQUIREMENTS.get(chosen)
        if required is None:
            return None, 1
        label, count = required
        trusted = [mention for mention in catalog_mentions if mention.type == label]
        if len(trusted) < count:
            return None, 1
        return (
            previous.model_copy(
                update={
                    "intent": chosen,
                    "entities": trusted[:count],
                    "route": RouteName.GRAPH_QA,
                    "missing_fields": [],
                    "unsupported": False,
                }
            ),
            1,
        )

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
