"""Ollama adapter for the local qwen3:0.6b CPU baseline."""

from __future__ import annotations

import httpx

from graphrag.llm.base import LLMResponse


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            response = await self.client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Ollama is unavailable at {self.base_url}; run `ollama serve` and `ollama pull {self.model}`"
            ) from error

        data = response.json()
        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama returned an empty or invalid chat response")
        return LLMResponse(
            content=content,
            model=str(data.get("model", self.model)),
            provider=self.name,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )

    async def health(self) -> tuple[bool, str]:
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError) as error:
            return False, f"Ollama unreachable: {type(error).__name__}"

        names = {str(item.get("name", "")) for item in models}
        if self.model not in names and not any(name.startswith(f"{self.model}:") for name in names):
            return False, f"model missing; run `ollama pull {self.model}`"
        return True, "Ollama and selected model ready"

    async def close(self) -> None:
        await self.client.aclose()
