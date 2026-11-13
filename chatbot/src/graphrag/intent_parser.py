"""One-retry JSON parser with a narrow deterministic fallback."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from graphrag.llm.base import LLMProvider
from graphrag.llm.prompts import PARSE_SYSTEM
from graphrag.models import EntityMention, IntentName, QueryFilters, QueryIntent


class IntentParser:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def parse(self, question: str) -> tuple[QueryIntent, int]:
        messages = [
            {"role": "system", "content": PARSE_SYSTEM},
            {"role": "user", "content": f"QUESTION:\n{question}"},
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            if attempt == 1:
                messages.append(
                    {"role": "user", "content": "Your prior output was invalid. Return only valid JSON."}
                )
            response = await self.provider.generate(
                messages,
                temperature=0,
                max_tokens=500,
                json_mode=True,
            )
            try:
                payload = json.loads(response.content)
                return QueryIntent.model_validate(payload), attempt + 1
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = error

        fallback = self._rules_fallback(question)
        if fallback is not None:
            return fallback, 2
        raise ValueError(f"model returned invalid intent JSON after one retry: {type(last_error).__name__}")

    @staticmethod
    def _rules_fallback(question: str) -> QueryIntent | None:
        normalized = question.casefold()
        intent = IntentName.UNKNOWN
        label = "Unknown"
        if "đồng tác giả" in normalized or "coauthor" in normalized:
            intent, label = IntentName.COAUTHORS, "Author"
        elif "bài báo" in normalized or "papers" in normalized:
            intent, label = IntentName.AUTHOR_PAPERS, "Author"
        elif "xếp hạng" in normalized or normalized.startswith("top "):
            return QueryIntent(
                intent=IntentName.NETWORK_TOP,
                entities=[],
                filters=QueryFilters(),
                parse_source="rules_fallback",
            )
        else:
            return None

        quoted = re.findall(r"[\"“](.*?)[\"”]", question)
        if not quoted:
            return None
        return QueryIntent(
            intent=intent,
            entities=[EntityMention(text=quoted[0], type=label)],
            filters=QueryFilters(),
            parse_source="rules_fallback",
        )
