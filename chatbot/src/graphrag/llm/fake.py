"""Deterministic provider for tests and the clearly labelled local demo."""

from __future__ import annotations

import json
import re

from graphrag.llm.base import LLMResponse


class FakeLLMProvider:
    name = "fake"

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        _ = temperature, max_tokens, json_mode
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""

        if "TASK=PARSE" in system:
            content = json.dumps(self._parse(user), ensure_ascii=False)
        elif "TASK=ANSWER" in system:
            content = self._answer(user)
        else:
            content = json.dumps({"sufficient": True, "reason_code": "enough"})

        return LLMResponse(content=content, model="deterministic-fixture-v1", provider=self.name)

    async def health(self) -> tuple[bool, str]:
        return True, "deterministic fake provider ready"

    async def close(self) -> None:
        return None

    def _parse(self, text: str) -> dict[str, object]:
        question = text.split("QUESTION:", 1)[-1].strip()
        normalized = question.casefold()
        intent = self._detect_intent(normalized)
        entities = self._extract_entities(question, intent)
        years = [int(year) for year in re.findall(r"\b(20\d{2})\b", question)]
        requested_fields: list[str] = []
        if "tổng quan" in normalized or "overview" in normalized:
            requested_fields = ["papers", "affiliations"]

        direction = "both"
        if "trích dẫn bởi" in normalized or "citing" in normalized:
            direction = "incoming"
        elif "trích dẫn" in normalized or "cites" in normalized:
            direction = "outgoing"

        return {
            "intent": intent,
            "entities": entities,
            "filters": {
                "year_from": min(years) if years else None,
                "year_to": max(years) if years else None,
                "topic_id": None,
                "citation_direction": direction,
            },
            "requested_fields": requested_fields,
            "unsupported": intent == "unknown",
            "parse_source": "llm",
        }

    @staticmethod
    def _detect_intent(question: str) -> str:
        rules = [
            (("đường", "path", "kết nối"), "author_path"),
            (("xếp hạng", "top", "nhiều đồng tác giả"), "network_top"),
            (("tổ chức hợp tác", "institution collaboration"), "org_collaborations"),
            (("trích dẫn", "citation", "cites", "citing"), "paper_citations"),
            (("venue", "hội nghị", "đăng ở"), "paper_venue"),
            (("chủ đề", "topic"), "topic_papers"),
            (("đồng tác giả", "coauthor"), "coauthors"),
            (("tác giả của", "paper authors", "ai viết"), "paper_authors"),
            (("tổ chức của đồng tác giả", "coauthor affiliation"), "coauthor_affiliations"),
            (("tổ chức", "affiliation", "cơ quan"), "author_affiliations"),
            (("bài chung", "shared paper", "cùng viết"), "shared_papers"),
            (("bài báo", "papers", "công bố", "tổng quan", "overview"), "author_papers"),
        ]
        for keywords, intent in rules:
            if any(keyword in question for keyword in keywords):
                return intent
        return "unknown"

    @staticmethod
    def _extract_entities(question: str, intent: str) -> list[dict[str, str]]:
        known = [
            ("An Nguyen", "Author"),
            ("Binh Tran", "Author"),
            ("Linh Nguyen", "Author"),
            ("Graph Evidence for NLP", "Paper"),
            ("Safe Language Models", "Paper"),
            ("Neural Translation Paths", "Paper"),
            ("Solo Parsing Study", "Paper"),
            ("Hanoi University of Science and Technology", "Institution"),
            ("Vietnam National University", "Institution"),
            ("Retrieval and RAG", "Topic"),
            ("Safety and LLM evaluation", "Topic"),
        ]
        entities: list[dict[str, str]] = []
        lowered = question.casefold()
        for name, label in known:
            if name.casefold() in lowered:
                entities.append({"text": name, "type": label})

        if intent == "network_top":
            return []
        return entities

    @staticmethod
    def _answer(user: str) -> str:
        marker = "VERIFIED_FACTS:"
        facts_text = user.split(marker, 1)[-1].strip()
        try:
            facts = json.loads(facts_text)
        except json.JSONDecodeError:
            return "Không thể định dạng câu trả lời từ bằng chứng đã xác minh."
        if not facts:
            return "Không tìm thấy dữ liệu phù hợp trong corpus NLP được lấy mẫu."

        statements: list[str] = []
        for fact in facts[:12]:
            value = fact.get("value")
            predicate = fact.get("predicate", "liên quan")
            subject = fact.get("subject_id", "thực thể")
            if isinstance(value, dict):
                display = value.get("name") or value.get("title") or value.get("metric_value") or value
            else:
                display = value or fact.get("object_id")
            statements.append(f"{subject} — {predicate}: {display}")
        return "Theo corpus NLP 2023–2025 được lấy mẫu:\n- " + "\n- ".join(statements)
