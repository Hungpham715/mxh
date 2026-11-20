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

        if "TASK=ROUTE/PARSE" in system:
            content = json.dumps(self._parse(user), ensure_ascii=False)
        elif "TASK=REQUESTED_FIELDS" in system:
            content = json.dumps(self._requested_fields(user), ensure_ascii=False)
        elif "TASK=HISTORY" in system:
            content = self._history_answer(user)
        elif "TASK=ANSWER" in system:
            content = self._answer(user)
        else:
            content = json.dumps({"sufficient": True, "reason_code": "enough"})

        return LLMResponse(content=content, model="deterministic-fixture-v1", provider=self.name)

    @staticmethod
    def _requested_fields(user: str) -> dict[str, list[str]]:
        normalized = user.casefold()
        fields = ["affiliations"] if "tổng quan" in normalized or "overview" in normalized else []
        return {"fields": fields}

    async def health(self) -> tuple[bool, str]:
        return True, "deterministic fake provider ready"

    async def close(self) -> None:
        return None

    def _parse(self, text: str) -> dict[str, object]:
        history, question = self._split_history_question(text)
        normalized = question.casefold()
        base = {
            "filters": {
                "year_from": None,
                "year_to": None,
                "topic_id": None,
                "citation_direction": "both",
            },
            "requested_fields": [],
            "missing_fields": [],
            "history_refs": [],
            "parse_source": "llm",
        }

        if self._is_history_question(normalized):
            return {
                **base,
                "route": "chat_history",
                "intent": "unknown",
                "entities": [],
                "unsupported": False,
            }
        if self._is_out_of_scope(normalized):
            return {**base, "route": "out_of_scope", "intent": "unknown", "entities": [], "unsupported": True}

        intent = self._detect_intent(normalized)
        years = [int(year) for year in re.findall(r"\b(20\d{2})\b", question)]
        base["filters"] = {
            **base["filters"],
            "year_from": min(years) if years else None,
            "year_to": max(years) if years else None,
        }
        requested_fields: list[str] = []
        if "tổng quan" in normalized or "overview" in normalized:
            requested_fields = ["papers", "affiliations"]
        base["requested_fields"] = requested_fields

        direction = "both"
        if "trích dẫn bởi" in normalized or "citing" in normalized:
            direction = "incoming"
        elif "trích dẫn" in normalized or "cites" in normalized:
            direction = "outgoing"
        base["filters"] = {**base["filters"], "citation_direction": direction}

        entities = self._extract_entities(question, intent)
        if not entities and self._has_pronoun_reference(normalized):
            resolved = self._resolve_from_history(history)
            if resolved is not None:
                entities = [resolved]
                base["history_refs"] = [resolved["text"]]
            elif intent != "network_top":
                return {
                    **base,
                    "route": "clarify",
                    "intent": intent,
                    "entities": [],
                    "missing_fields": ["author_reference"],
                    "unsupported": False,
                }

        return {
            **base,
            "route": "graph_qa",
            "intent": intent,
            "entities": entities,
            "unsupported": intent == "unknown",
        }

    @staticmethod
    def _split_history_question(text: str) -> tuple[list[dict[str, str]], str]:
        history: list[dict[str, str]] = []
        question = text
        if "QUESTION:" in text:
            history_part, question = text.split("QUESTION:", 1)
            question = question.strip()
            if "HISTORY:" in history_part:
                raw = history_part.split("HISTORY:", 1)[1].strip()
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        history = [item for item in parsed if isinstance(item, dict)]
                except json.JSONDecodeError:
                    history = []
        return history, question

    @staticmethod
    def _is_history_question(normalized: str) -> bool:
        markers = (
            "câu đầu tiên",
            "câu hỏi đầu",
            "tóm tắt hội thoại",
            "đã hỏi",
            "lịch sử hội thoại",
            "những gì tôi đã hỏi",
            "trước đó tôi",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _is_out_of_scope(normalized: str) -> bool:
        markers = (
            "đặt phòng",
            "thời tiết",
            "nấu",
            "bóng đá",
            "bài thơ",
            "cổ phiếu",
            "netflix",
            "chuyến bay",
            "diện tích hình tròn",
            "tổng thống",
            "booking",
            "weather",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _has_pronoun_reference(normalized: str) -> bool:
        markers = (
            "người đó",
            "tác giả đó",
            "tác giả này",
            "ông ấy",
            "bà ấy",
            "người này",
            "bài đó",
            "bài báo đó",
            "that author",
            "the author",
        )
        return any(marker in normalized for marker in markers)

    def _resolve_from_history(self, history: list[dict[str, str]]) -> dict[str, str] | None:
        known = [(name, label) for name, label, _ in self._known_entities()]
        for message in reversed(history):
            content = str(message.get("content", ""))
            lowered = content.casefold()
            for name, label in known:
                if name.casefold() in lowered:
                    return {"text": name, "type": label}
        return None

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
    def _known_entities() -> list[tuple[str, str, str]]:
        return [
            ("An Nguyen", "Author", "author"),
            ("Binh Tran", "Author", "author"),
            ("Linh Nguyen", "Author", "author"),
            ("Graph Evidence for NLP", "Paper", "paper"),
            ("Safe Language Models", "Paper", "paper"),
            ("Neural Translation Paths", "Paper", "paper"),
            ("Solo Parsing Study", "Paper", "paper"),
            ("Hanoi University of Science and Technology", "Institution", "institution"),
            ("Vietnam National University", "Institution", "institution"),
            ("Retrieval and RAG", "Topic", "topic"),
            ("Safety and LLM evaluation", "Topic", "topic"),
        ]

    @classmethod
    def _extract_entities(cls, question: str, intent: str) -> list[dict[str, str]]:
        entities: list[dict[str, str]] = []
        lowered = question.casefold()
        for name, label, _ in cls._known_entities():
            if name.casefold() in lowered:
                entities.append({"text": name, "type": label})

        if intent == "network_top":
            return []
        return entities

    @staticmethod
    def _history_answer(user: str) -> str:
        marker = "HISTORY:"
        if marker not in user:
            return "Không có lịch sử hội thoại để trả lời."
        raw = user.split(marker, 1)[1].split("QUESTION:", 1)[0].strip()
        try:
            history = json.loads(raw)
        except json.JSONDecodeError:
            history = []
        user_turns = [str(item.get("content", "")) for item in history if item.get("role") == "user"]
        if not user_turns:
            return "Hiện chưa có câu hỏi nào trước đó trong hội thoại này."
        listing = "\n".join(f"- {turn}" for turn in user_turns)
        return f"Theo lịch sử hội thoại, bạn đã hỏi:\n{listing}"

    @staticmethod
    def _answer(user: str) -> str:
        marker = "VERIFIED_FACTS:"
        facts_text = user.split(marker, 1)[-1].strip()
        truncated = "RESULTS_TRUNCATED:true" in user
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
        answer = "Theo corpus NLP 2023–2025 được lấy mẫu:\n- " + "\n- ".join(statements)
        if truncated:
            answer += "\n(Lưu ý: kết quả bị giới hạn, vẫn còn dữ liệu chưa hiển thị.)"
        return answer
