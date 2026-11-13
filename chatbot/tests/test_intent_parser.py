import pytest

from graphrag.intent_parser import IntentParser
from graphrag.llm.base import LLMResponse
from graphrag.models import IntentName


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
