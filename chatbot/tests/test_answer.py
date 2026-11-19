import pytest

from graphrag.answer import GroundedAnswerGenerator
from graphrag.llm.base import LLMResponse


class EchoProvider:
    async def generate(self, messages, *, temperature, max_tokens, json_mode):
        _ = temperature, max_tokens, json_mode
        return LLMResponse(
            content=messages[-1]["content"].split("QUESTION:\n", 1)[-1],
            model="echo",
            provider="test",
        )


@pytest.mark.asyncio
async def test_history_echo_is_replaced_by_first_validated_user_turn() -> None:
    generator = GroundedAnswerGenerator(EchoProvider())
    answer = await generator.generate_from_history(
        "Câu hỏi đầu tiên tôi hỏi bạn là gì?",
        [
            {"role": "user", "content": "Các bài báo của Antoine Simoulin?"},
            {"role": "assistant", "content": "Đã tìm thấy."},
        ],
    )
    assert answer == "Các bài báo của Antoine Simoulin?"
