import pytest

from graphrag.intent_parser import IntentParser
from graphrag.llm.base import LLMResponse
from graphrag.models import EntityMention, IntentName, QueryIntent


class MalformedProvider:
    name = "malformed"

    async def generate(self, messages, *, temperature, max_tokens, json_mode):
        _ = messages, temperature, max_tokens, json_mode
        return LLMResponse(content="not-json", model="broken", provider=self.name)

    async def health(self):
        return True, "test"

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_malformed_json_retries_once_then_uses_certain_rule() -> None:
    parser = IntentParser(MalformedProvider())
    intent, calls = await parser.parse('Bài báo của "An Nguyen"')
    assert calls == 2
    assert intent.intent == IntentName.AUTHOR_PAPERS
    assert intent.parse_source == "rules_fallback"


@pytest.mark.asyncio
async def test_malformed_json_without_certain_rule_errors() -> None:
    parser = IntentParser(MalformedProvider())
    with pytest.raises(ValueError, match="after one retry"):
        await parser.parse("xin chào")


class ScriptedProvider:
    """Returns a fixed model output so we can test the deterministic reconcile layer."""

    name = "scripted"

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def generate(self, messages, *, temperature, max_tokens, json_mode):
        _ = messages, temperature, max_tokens, json_mode
        return LLMResponse(content=self.payload, model="scripted", provider=self.name)

    async def health(self):
        return True, "test"

    async def close(self):
        return None


class SequenceProvider(ScriptedProvider):
    """Returns a sequence of outputs so a correction retry can be verified."""

    def __init__(self, payloads: list[str]) -> None:
        self.payloads = list(payloads)

    async def generate(self, messages, *, temperature, max_tokens, json_mode):
        _ = messages, temperature, max_tokens, json_mode
        return LLMResponse(content=self.payloads.pop(0), model="scripted", provider=self.name)


_CONTRACT = (
    '"filters":{"year_from":null,"year_to":null,"topic_id":null,"citation_direction":"both"},'
    '"requested_fields":[],"history_refs":[],"unsupported":false,"parse_source":"llm"'
)


@pytest.mark.asyncio
async def test_entity_type_mismatch_gets_one_model_correction_retry() -> None:
    wrong = (
        '{"route":"graph_qa","intent":"org_collaborations",'
        '"entities":[{"text":"Maosong Sun","type":"Author"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    corrected = (
        '{"route":"graph_qa","intent":"author_affiliations",'
        '"entities":[{"text":"Maosong Sun","type":"Author"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    parser = IntentParser(SequenceProvider([wrong, corrected]))
    intent, calls = await parser.parse("Cơ quan của Maosong Sun theo từng bài báo?")
    assert calls == 2
    assert intent.intent == IntentName.AUTHOR_AFFILIATIONS


@pytest.mark.asyncio
async def test_contradictory_clarify_with_entity_is_promoted_to_graph_qa() -> None:
    payload = (
        '{"route":"clarify","intent":"coauthors","entities":[{"text":"Junjie Ye","type":"Author"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, _ = await parser.parse("Đồng tác giả của Junjie Ye là ai?")
    assert intent.route.value == "graph_qa"
    assert intent.intent == IntentName.COAUTHORS


@pytest.mark.asyncio
async def test_genuine_clarify_without_entity_is_preserved() -> None:
    payload = (
        '{"route":"clarify","intent":"author_papers","entities":[],'
        f'"missing_fields":["author_reference"],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, _ = await parser.parse("Các bài báo của tác giả đó?")
    assert intent.route.value == "clarify"


@pytest.mark.asyncio
async def test_unknown_intent_ranking_rescued_by_rules_fallback() -> None:
    payload = (
        '{"route":"clarify","intent":"unknown","entities":[],'
        f'"missing_fields":["author_reference"],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, _ = await parser.parse("Top tác giả theo số đồng tác giả riêng biệt là ai?")
    assert intent.intent == IntentName.NETWORK_TOP
    assert intent.parse_source == "rules_fallback"


@pytest.mark.asyncio
async def test_history_meta_question_rescued_by_rules_fallback() -> None:
    payload = f'{{"route":"graph_qa","intent":"unknown","entities":[],"missing_fields":[],{_CONTRACT}}}'
    parser = IntentParser(ScriptedProvider(payload))
    intent, _ = await parser.parse("Câu hỏi đầu tiên tôi hỏi bạn là gì?")
    assert intent.route.value == "chat_history"
    assert intent.parse_source == "rules_fallback"


@pytest.mark.asyncio
async def test_network_top_discards_model_added_generic_entity() -> None:
    payload = (
        '{"route":"graph_qa","intent":"network_top",'
        '"entities":[{"text":"tác giả","type":"Author"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, _ = await parser.parse("Top tác giả theo số đồng tác giả riêng biệt là ai?")
    assert intent.intent == IntentName.NETWORK_TOP
    assert intent.entities == []


@pytest.mark.asyncio
async def test_catalog_context_repair_keeps_llm_semantics_but_enforces_trusted_entity_type() -> None:
    wrong = (
        '{"route":"graph_qa","intent":"org_collaborations",'
        '"entities":[{"text":"An Nguyen","type":"Institution"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    corrected = '{"intent":"author_affiliations"}'
    parser = IntentParser(SequenceProvider([wrong, corrected]))
    intent, _ = await parser.parse("Tổ chức của An Nguyen theo từng bài báo?")
    repaired, calls = await parser.repair_with_catalog_context(
        "Tổ chức của An Nguyen theo từng bài báo?",
        [],
        intent,
        [EntityMention(text="An Nguyen", type="Author")],
    )
    assert calls == 1
    assert repaired is not None
    assert repaired.intent == IntentName.AUTHOR_AFFILIATIONS
    assert repaired.entities == [EntityMention(text="An Nguyen", type="Author")]


@pytest.mark.asyncio
async def test_catalog_context_repair_can_preserve_out_of_scope_decision() -> None:
    prior = f'{{"route":"out_of_scope","intent":"unknown","entities":[],"missing_fields":[],{_CONTRACT}}}'
    parser = IntentParser(SequenceProvider([prior, '{"intent":"unknown"}']))
    intent, _ = await parser.parse("Thời tiết ở nơi An Nguyen làm việc?")
    repaired, calls = await parser.repair_with_catalog_context(
        "Thời tiết ở nơi An Nguyen làm việc?",
        [],
        intent,
        [EntityMention(text="An Nguyen", type="Author")],
    )
    assert calls == 1
    assert repaired is None


@pytest.mark.asyncio
async def test_catalog_verifier_cannot_drop_satisfied_two_entity_contract() -> None:
    parser = IntentParser(ScriptedProvider('{"intent":"coauthors"}'))
    prior = QueryIntent(
        intent=IntentName.AUTHOR_PATH,
        entities=[
            EntityMention(text="Alice", type="Author"),
            EntityMention(text="Bob", type="Author"),
        ],
    )
    repaired, calls = await parser.repair_with_catalog_context(
        "Đường đồng tác giả giữa Alice và Bob là gì?",
        [],
        prior,
        [
            EntityMention(text="Alice", type="Author"),
            EntityMention(text="Bob", type="Author"),
        ],
    )
    assert calls == 1
    assert repaired == prior


@pytest.mark.asyncio
async def test_answer_mode_classifier_defaults_to_values_and_accepts_explicit_quantity() -> None:
    # Explicit quantity interrogatives are decided in code (same list as ANSWER_MODE_SYSTEM):
    # no LLM call, and a weak-model "values" answer can never downgrade them.
    quantity = IntentParser(ScriptedProvider('{"mode":"values"}'))
    fields, calls = await quantity.classify_requested_fields("Alice có bao nhiêu bài báo?")
    assert calls == 0
    assert fields == ["count"]

    values = IntentParser(ScriptedProvider('{"values":["Alice"]}'))
    fields, calls = await values.classify_requested_fields("Đồng tác giả của Alice là ai?")
    assert calls == 1
    assert fields == []


@pytest.mark.asyncio
async def test_out_of_vocabulary_entity_type_is_coerced_to_unknown() -> None:
    payload = (
        '{"route":"clarify","intent":"unknown","entities":[{"text":"1","type":"number"}],'
        f'"missing_fields":["amount"],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, _ = await parser.parse("1 cộng 1 bằng mấy?")
    assert intent.entities[0].type == "Unknown"


@pytest.mark.asyncio
async def test_ungrounded_entity_mentions_get_one_retry_then_are_dropped() -> None:
    payload = (
        '{"route":"graph_qa","intent":"author_papers","entities":[{"text":"that author","type":"Author"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, calls = await parser.parse("Các bài báo của tác giả đó?")
    assert calls == 2
    assert intent.entities == []


@pytest.mark.asyncio
async def test_grounded_mentions_survive_diacritic_and_case_differences() -> None:
    payload = (
        '{"route":"graph_qa","intent":"author_papers","entities":[{"text":"MAOSONG SUN","type":"Author"}],'
        f'"missing_fields":[],{_CONTRACT}}}'
    )
    parser = IntentParser(ScriptedProvider(payload))
    intent, calls = await parser.parse("Cơ quan của Maosong Sun theo từng bài báo?")
    assert calls == 1
    assert [mention.text for mention in intent.entities] == ["MAOSONG SUN"]


@pytest.mark.asyncio
async def test_clarify_without_missing_fields_gets_one_contract_retry() -> None:
    contradictory = f'{{"route":"clarify","intent":"unknown","entities":[],"missing_fields":[],{_CONTRACT}}}'
    corrected = f'{{"route":"out_of_scope","intent":"unknown","entities":[],"missing_fields":[],{_CONTRACT}}}'
    parser = IntentParser(SequenceProvider([contradictory, corrected]))
    intent, calls = await parser.parse("Công thức tính diện tích hình tròn?")
    assert calls == 2
    assert intent.route.value == "out_of_scope"


@pytest.mark.asyncio
async def test_relationship_tie_break_can_keep_first_or_accept_candidate() -> None:
    keep = IntentParser(ScriptedProvider('{"choice":"A"}'))
    chosen, calls = await keep.choose_between_intents(
        "Các công trình của Alice?", IntentName.AUTHOR_PAPERS, IntentName.AUTHOR_AFFILIATIONS
    )
    assert calls == 1
    assert chosen == IntentName.AUTHOR_PAPERS

    accept = IntentParser(ScriptedProvider('{"choice":"B"}'))
    chosen, _ = await accept.choose_between_intents(
        "Đồng tác giả của Alice?", IntentName.AUTHOR_PAPERS, IntentName.COAUTHORS
    )
    assert chosen == IntentName.COAUTHORS


@pytest.mark.asyncio
async def test_catalog_repair_retries_choice_that_violates_entity_arity() -> None:
    parser = IntentParser(SequenceProvider(['{"intent":"shared_papers"}', '{"intent":"coauthors"}']))
    prior = QueryIntent(
        intent=IntentName.SHARED_PAPERS,
        entities=[
            EntityMention(text="Alice", type="Author"),
            EntityMention(text="unknown", type="Unknown"),
        ],
    )
    repaired, calls = await parser.repair_with_catalog_context(
        "Alice đã viết bài cùng những ai?",
        [],
        prior,
        [EntityMention(text="Alice", type="Author")],
    )
    assert calls == 2
    assert repaired is not None
    assert repaired.intent == IntentName.COAUTHORS
