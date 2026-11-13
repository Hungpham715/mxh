"""Minimal provider protocol used by parse, decision, and answer tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    name: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse: ...

    async def health(self) -> tuple[bool, str]: ...

    async def close(self) -> None: ...
