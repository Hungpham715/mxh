"""Grounded answer generation; citations stay outside model control."""

from __future__ import annotations

import re

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
        requested_fields: list[str] | None = None,
    ) -> str:
        if not facts:
            if status == "out_of_scope":
                return (
                    "Câu hỏi nằm ngoài mạng tác giả, bài báo, tổ chức, chủ đề, venue, trích dẫn "
                    "và dữ liệu làm giàu NLP trong corpus. Tôi có thể giúp tra cứu tác giả, bài báo, "
                    "đồng tác giả, tổ chức, chủ đề, phương pháp, bộ dữ liệu và bài toán trong corpus "
                    "NLP 2023–2025."
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
            max_tokens=256,
            json_mode=False,
        )
        model_answer = response.content.strip()
        # Qwen 0.6B can copy internal IDs, repeat facts, or omit list members even with a strict
        # prompt. For complete, non-truncated graph answers, enforce the server-owned value
        # contract after the LLM call. This is a formatting/grounding guard, not a semantic
        # router: every emitted value comes directly from the executed Cypher result.
        if status in {"answered", "partial"}:
            values = self._canonical_values(facts)
            if values:
                if requested_fields and "count" in requested_fields:
                    return str(len(values))
                answer = "; ".join(values)
                if truncated:
                    answer += "\nKết quả bị giới hạn; vẫn còn dữ liệu chưa hiển thị."
                return answer
        return model_answer

    @staticmethod
    def _canonical_values(facts: list[GraphFact]) -> list[str]:
        """Extract ordered answer values from normalized graph facts without model invention."""
        values: list[str] = []
        seen: set[str] = set()
        for fact in facts:
            raw_values: list[object] = []
            if isinstance(fact.value, dict):
                if fact.predicate == "COAUTHOR_PATH":
                    names = fact.value.get("author_names")
                    if isinstance(names, list) and names:
                        raw_values = [" → ".join(str(name) for name in names)]
                if fact.predicate == "RANKED_METHOD_BY_PAPER_COUNT":
                    name = fact.value.get("name")
                    count = fact.value.get("metric_value")
                    if name is not None and count is not None:
                        raw_values = [f"{name} ({count} bài)"]
                if not raw_values and fact.value.get("name") is not None:
                    raw_values = [fact.value["name"]]
            elif fact.value is not None:
                raw_values = [fact.value]
            for raw in raw_values:
                value = str(raw).strip()
                key = value.casefold()
                if value and key not in seen:
                    seen.add(key)
                    values.append(value)
        return values

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
        answer = response.content.strip()
        # If a weak model merely echoes the current meta-question, it did not use HISTORY.
        # Recover the earliest validated user turn directly from the same server-owned history.
        normalized_answer = re.sub(r"[\s?.!]+$", "", answer.casefold()).strip()
        normalized_question = re.sub(r"[\s?.!]+$", "", question.casefold()).strip()
        if normalized_answer == normalized_question:
            first_user = next(
                (str(item["content"]) for item in history if item.get("role") == "user"),
                None,
            )
            if first_user:
                return first_user
        return answer
