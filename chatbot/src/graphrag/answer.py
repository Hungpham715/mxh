"""Grounded answer generation; citations stay outside model control."""

from __future__ import annotations

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import ANSWER_SYSTEM, HISTORY_SYSTEM, build_answer_user, build_history_user
from graphrag.models import GraphFact


class GroundedAnswerGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(
        self,
        question: str,
        facts: list[GraphFact],
        status: str,
        truncated: bool = False,
    ) -> str:
        if not facts:
            if status == "out_of_scope":
                return (
                    "Câu hỏi nằm ngoài mạng tác giả, bài báo, tổ chức, chủ đề, "
                    "venue và trích dẫn NLP trong corpus. Tôi có thể giúp tra cứu tác giả, "
                    "bài báo, đồng tác giả, tổ chức, chủ đề, venue và trích dẫn trong corpus NLP 2023–2025."
                )
            return "Không tìm thấy dữ liệu phù hợp trong corpus NLP được lấy mẫu."
        payload = [fact.model_dump(mode="json") for fact in facts]
        response = await self.provider.generate(
            [
                {"role": "system", "content": ANSWER_SYSTEM},
                {
                    "role": "user",
                    "content": build_answer_user(
                        question, status, payload, truncated=truncated, shown_count=len(payload)
                    ),
                },
            ],
            temperature=0,
            max_tokens=700,
            json_mode=False,
        )
        return response.content.strip()

    async def generate_from_history(self, question: str, history: list[dict[str, str]]) -> str:
        """Answer a conversation meta-question strictly from the provided history."""
        if not history:
            return "Hiện chưa có lượt hội thoại nào trước câu hỏi này, nên tôi không có gì để tóm tắt."
        response = await self.provider.generate(
            [
                {"role": "system", "content": HISTORY_SYSTEM},
                {"role": "user", "content": build_history_user(question, history)},
            ],
            temperature=0,
            max_tokens=500,
            json_mode=False,
        )
        return response.content.strip()
