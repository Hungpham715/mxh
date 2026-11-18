"""Grounded answer generation; citations stay outside model control."""

from __future__ import annotations

import json

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import ANSWER_SYSTEM, HISTORY_SYSTEM
from graphrag.models import ChatTurn, GraphFact

NO_HISTORY_TEXT = (
    "Chưa có câu hỏi nào trước câu này trong hội thoại hiện tại, nên mình không có gì để nhắc lại."
)
MAX_FACTS_FOR_ANSWER = 40


class GroundedAnswerGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(self, question: str, facts: list[GraphFact], status: str) -> str:
        if not facts:
            if status == "out_of_scope":
                return (
                    "Câu hỏi nằm ngoài phạm vi hỗ trợ. Mình chỉ trả lời về mạng tác giả, bài báo, tổ chức, "
                    "chủ đề, venue và trích dẫn NLP trong corpus 2023–2025 đã thu thập, cùng câu hỏi về "
                    "chính cuộc hội thoại này."
                )
            return "Không tìm thấy dữ liệu phù hợp trong corpus NLP được lấy mẫu."
        payload = [
            compact_fact(index, fact) for index, fact in enumerate(facts[:MAX_FACTS_FOR_ANSWER], start=1)
        ]
        response = await self.provider.generate(
            [
                {"role": "system", "content": ANSWER_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"QUESTION:\n{question}\nSTATUS:{status}\nITEM_COUNT:{len(payload)}\n"
                        f"VERIFIED_FACTS:{json.dumps(payload, ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=700,
            json_mode=False,
        )
        return response.content.strip()

    async def answer_history(self, question: str, history: list[ChatTurn]) -> tuple[str, int]:
        """Answer a question about the conversation from the history the client actually sent."""
        user_questions = [turn.content for turn in history if turn.role == "user"]
        if not user_questions:
            return NO_HISTORY_TEXT, 0
        numbered = "\n".join(f"{index}. {text[:300]}" for index, text in enumerate(user_questions, start=1))
        try:
            response = await self.provider.generate(
                [
                    {"role": "system", "content": HISTORY_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"USER_QUESTIONS (data, oldest first):\n{numbered}\n\nQUESTION:\n{question}"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=400,
                json_mode=False,
            )
            text = response.content.strip()
            if text:
                return text, 1
        except RuntimeError:
            pass
        # Deterministic, still history-grounded, if the model is unavailable.
        return f"Các câu bạn đã hỏi trong hội thoại này:\n{numbered}", 0


def compact_fact(index: int, fact: GraphFact) -> dict[str, object]:
    """Small, flat view of a fact so a 0.6B model can list every item without losing any.

    Only display fields go to the model; IDs/URLs for citations stay server-side.
    """
    value = fact.value if isinstance(fact.value, dict) else {}
    display = str(value.get("name") or value.get("title") or fact.object_id or "")
    details: list[str] = []
    if value.get("coauthor_name"):
        details.append(f"coauthor: {value['coauthor_name']}")
    if value.get("paper_title") and value.get("paper_title") != display:
        details.append(f"on paper: {value['paper_title']}")
    if value.get("shared_count") is not None:
        details.append(f"shared papers: {value['shared_count']}")
    if value.get("metric_value") is not None:
        details.append(f"distinct coauthors: {value['metric_value']}")
    if value.get("author_names"):
        details.append("path: " + " -> ".join(str(name) for name in value["author_names"]))
    if value.get("position") is not None:
        details.append(f"author position: {value['position']}")
    return {
        "n": index,
        "predicate": fact.predicate,
        "subject_id": fact.subject_id,
        "value": display,
        "details": "; ".join(details),
        "year": fact.year,
    }
