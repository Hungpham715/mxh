import pytest

from graphrag.intent_parser import IntentParser
from graphrag.llm.base import LLMResponse
from graphrag.models import EntityMention, IntentName


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
