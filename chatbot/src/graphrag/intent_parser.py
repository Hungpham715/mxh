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
import unicodedata

from pydantic import ValidationError

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import REQUESTED_FIELDS_SYSTEM, ROUTE_PARSE_SYSTEM, build_parse_user
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

# Explicit quantity interrogatives. Same closed list as the ANSWER_MODE_SYSTEM prompt contract:
# when one of these appears verbatim, the answer shape is a code-owned "count" decision and the
# shape classifier is not consulted (Qwen 0.6B was observed answering "values" for "bao nhiêu").
QUANTITY_QUESTION_MARKERS = ("bao nhiêu", "số lượng", "how many", "number of")

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


def grounding_form(value: str) -> str:
    """Diacritic-/case-insensitive text used to check that a mention is a verbatim input span."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.casefold()).strip()


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
                # Drop hallucinated/translated spans first (deterministic sanitization), then
                # give the model one retry only for contract violations it can still resolve.
                intent = self._drop_ungrounded_mentions(intent, question, history)
                contract_error = self._entity_contract_error(intent) or self._clarify_contract_error(intent)
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
        """Ask the LLM once to verify a parse using exact catalog entities.

        The model still decides semantics. Code only supplies server-derived entity names/types
        and accepts a graph intent when its required entity contract can be satisfied entirely
        from those exact catalog mentions. This focused pass is also useful when the first parse
        chose the wrong relationship between intents that require the same entity type.
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
        previous_required = INTENT_ENTITY_REQUIREMENTS.get(previous.intent)
        previous_contract_is_satisfied = False
        if previous_required is not None:
            previous_label, previous_count = previous_required
            previous_contract_is_satisfied = (
                sum(mention.type == previous_label for mention in catalog_mentions) >= previous_count
            )
        prior_context = (
            f"PRIOR_INTENT_TO_VERIFY={previous.intent.value}"
            if previous_contract_is_satisfied
            else f"INVALID_PRIOR_INTENT_DO_NOT_USE={previous.intent.value}"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "TASK=CATALOG_INTENT_VERIFY. Select the single intent that matches the "
                    "question's requested relationship. Catalog entity names and types are "
                    "authoritative. Select by the object the user wants returned, not merely the "
                    "entity type or the prior answer. Distinguish these pairs exactly: "
                    "author_papers returns papers written by one author; coauthors returns people "
                    "who wrote with one author; author_affiliations returns that author's own "
                    "paper-specific institutions; coauthor_affiliations returns institutions of "
                    "the other authors on shared papers. shared_papers returns papers jointly "
                    "written by two named authors; author_path returns a chain/path connecting two "
                    "authors through coauthor edges. paper_authors returns people who wrote a "
                    "paper; paper_venue returns its venue; paper_citations returns cited/citing "
                    "papers. org_collaborations returns partner institutions. Return only JSON: "
                    '{"intent":"one allowed key"}. Generic examples: '
                    '"Theo bằng chứng trên bài, Alice khai báo các cơ quan nào?" => '
                    '{"intent":"author_affiliations"}; '
                    '"Các đồng tác giả của Alice thuộc cơ quan nào trên đúng bài viết chung?" => '
                    '{"intent":"coauthor_affiliations"}; '
                    '"Đồng tác giả của Alice là ai?" => '
                    '{"intent":"coauthors"}; '
                    '"Tìm đường nối Alice với Bob qua cạnh đồng tác giả" => '
                    '{"intent":"author_path"}; '
                    '"Alice và Bob có bài chung nào?" => '
                    '{"intent":"shared_papers"}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"QUESTION={json.dumps(question, ensure_ascii=False)}\n"
                    f"HISTORY={json.dumps(history, ensure_ascii=False)}\n"
                    f"CATALOG_ENTITIES={json.dumps(candidates, ensure_ascii=False)}\n"
                    f"ALLOWED_INTENTS={json.dumps(options, ensure_ascii=False)}\n"
                    f"{prior_context}\n"
                    "Choose by relationship direction: an author's institutions are "
                    "author_affiliations; an institution's partner institutions are "
                    "org_collaborations; authors of a paper are paper_authors; papers of an "
                    "author are author_papers; people who wrote with an author are coauthors; "
                    "institutions of those people are coauthor_affiliations; a connecting chain "
                    "between two authors is author_path, while their joint papers are "
                    "shared_papers. Return only the JSON object."
                ),
            },
        ]
        for attempt in range(2):
            response = await self.provider.generate(
                messages,
                temperature=0,
                max_tokens=80,
                json_mode=True,
            )
            try:
                payload = json.loads(response.content)
                chosen = IntentName(str(payload["intent"]).casefold())
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                chosen = None

            if chosen == IntentName.UNKNOWN:
                return None, attempt + 1
            required = INTENT_ENTITY_REQUIREMENTS.get(chosen) if chosen is not None else None
            valid_choice = chosen in allowed and required is not None
            if valid_choice and required is not None:
                # A focused verification pass may refine a one-entity parse into a two-entity
                # relation, but it must not discard a catalog-satisfied entity from an already
                # valid two-entity parse. This is an arity contract, not keyword routing.
                if (
                    previous_required is not None
                    and previous_contract_is_satisfied
                    and required[1] < previous_count
                ):
                    return previous, attempt + 1
                label, count = required
                trusted = [mention for mention in catalog_mentions if mention.type == label]
                if len(trusted) >= count:
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
                        attempt + 1,
                    )
            if attempt == 0:
                messages.extend(
                    [
                        {"role": "assistant", "content": response.content},
                        {
                            "role": "user",
                            "content": (
                                "That choice violates ALLOWED_INTENTS or its catalog entity "
                                "contract. Re-evaluate once and return exactly one allowed intent."
                            ),
                        },
                    ]
                )
        return None, 2

    async def choose_between_intents(
        self,
        question: str,
        first: IntentName,
        candidate: IntentName,
    ) -> tuple[IntentName, int]:
        """Let the LLM arbitrate a same-contract semantic disagreement once."""
        descriptions = {intent_name: INTENT_DESCRIPTIONS[intent_name] for intent_name in (first, candidate)}
        messages = [
            {
                "role": "system",
                "content": (
                    "TASK=RELATION_TIE_BREAK. Choose which candidate relationship directly "
                    "answers the QUESTION. Choose by the values the user wants returned, not by "
                    'the named entity type. Return JSON only: {"choice":"A"} or {"choice":"B"}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"QUESTION={json.dumps(question, ensure_ascii=False)}\n"
                    f"A={first.value}: {descriptions[first]}\n"
                    f"B={candidate.value}: {descriptions[candidate]}"
                ),
            },
        ]
        try:
            response = await self.provider.generate(
                messages,
                temperature=0,
                max_tokens=30,
                json_mode=True,
            )
            choice = json.loads(response.content).get("choice")
        except (json.JSONDecodeError, TypeError, ValueError):
            return first, 1
        return (candidate if choice == "B" else first), 1

    async def classify_requested_fields(
        self, question: str, intent_name: str | None = None
    ) -> tuple[list[str], int]:
        """Use a separate narrow LLM decision for extra fields plus a strict count contract.

        Keeping this out of the relationship classifier avoids small-model label anchoring. Any
        malformed or uncertain response safely defaults to values, never an invented count.
        An explicit quantity interrogative from QUANTITY_QUESTION_MARKERS is decided in code
        without an LLM call: it is the same closed list the ANSWER_MODE_SYSTEM prompt defines
        as quantity, and the count itself always comes from the database result set.
        """
        normalized = question.casefold()
        fields = ["count"] if any(marker in normalized for marker in QUANTITY_QUESTION_MARKERS) else []
        # "affiliations" is the only extra semantic field this classifier can add and it is
        # only meaningful when the primary query is author_papers. Avoid an unnecessary model
        # call for paths, coauthors, venues, etc.; this does not decide their route or intent.
        if intent_name != "author_papers":
            return fields, 0
        try:
            response = await self.provider.generate(
                [
                    {"role": "system", "content": REQUESTED_FIELDS_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"intent": intent_name or "unknown", "question": question},
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=60,
                json_mode=True,
            )
            payload = json.loads(response.content)
        except (json.JSONDecodeError, TypeError, ValueError):
            return fields, 1
        requested = payload.get("fields")
        if isinstance(requested, list) and "affiliations" in requested:
            fields.append("affiliations")
        return list(dict.fromkeys(fields)), 1

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

    @staticmethod
    def _clarify_contract_error(intent: QueryIntent) -> str | None:
        """A clarify route must say what is missing; an unknown-intent clarify says nothing.

        This is a schema-contract check, not semantic routing: the model still decides between
        clarify (naming the missing field) and out_of_scope on the retry.
        """
        if intent.route != RouteName.CLARIFY:
            return None
        if intent.intent != IntentName.UNKNOWN or intent.missing_fields:
            return None
        return (
            "route clarify requires missing_fields; if the question is unrelated to the "
            "academic NLP graph and to the conversation, use route out_of_scope instead"
        )

    @staticmethod
    def _ungrounded_mentions(
        intent: QueryIntent, question: str, history: list[dict[str, str]]
    ) -> list[EntityMention]:
        """Mentions whose text is not a verbatim (diacritic-insensitive) span of the input.

        The parse contract allows entities only from the question/history; Qwen 0.6B was
        observed translating spans ("tác giả đó" -> "that author") or inventing generic ones.
        """
        haystack = grounding_form(question)
        for message in history:
            haystack += " " + grounding_form(str(message.get("content", "")))
        ungrounded: list[EntityMention] = []
        for mention in intent.entities:
            needle = grounding_form(mention.text)
            if not needle or needle not in haystack:
                ungrounded.append(mention)
        return ungrounded

    @classmethod
    def _drop_ungrounded_mentions(
        cls, intent: QueryIntent, question: str, history: list[dict[str, str]]
    ) -> QueryIntent:
        ungrounded = cls._ungrounded_mentions(intent, question, history)
        if not ungrounded:
            return intent
        kept = [mention for mention in intent.entities if mention not in ungrounded]
        return intent.model_copy(update={"entities": kept})

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
        if intent.intent == IntentName.NETWORK_TOP and intent.entities:
            # Entity-free catalog action: discard model-added generic spans such as "tác giả".
            intent = intent.model_copy(update={"entities": []})
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
