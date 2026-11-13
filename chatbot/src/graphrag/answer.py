"""Grounded answer generation; citations stay outside model control."""

from __future__ import annotations

import json

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import ANSWER_SYSTEM
from graphrag.models import GraphFact


class GroundedAnswerGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(self, question: str, facts: list[GraphFact], status: str) -> str:
        if not facts:
            if status == "out_of_scope":
                return (
                    "Câu hỏi nằm ngoài mạng tác giả, bài báo, tổ chức, chủ đề, "
                    "venue và trích dẫn NLP trong corpus."
                )
            return "Không tìm thấy dữ liệu phù hợp trong corpus NLP được lấy mẫu."
        payload = [fact.model_dump(mode="json") for fact in facts]
        response = await self.provider.generate(
            [
                {"role": "system", "content": ANSWER_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"QUESTION:\n{question}\nSTATUS:{status}\n"
                        f"VERIFIED_FACTS:{json.dumps(payload, ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=700,
            json_mode=False,
        )
        return response.content.strip()
