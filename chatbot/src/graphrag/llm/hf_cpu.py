"""Lazy CPU Transformers + optional local PEFT adapter provider."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from graphrag.llm.base import LLMResponse


class HFCPUProvider:
    name = "hf_cpu"

    def __init__(self, model_id: str, adapter_path: str | None, use_adapter: bool) -> None:
        self.model_id = model_id
        self.adapter_path = adapter_path
        self.use_adapter = use_adapter
        self._model: Any = None
        self._tokenizer: Any = None
        self._load_lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> None:
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError("Install the optional HF stack with `uv sync --extra hf`") from error

        tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            device_map="cpu",
            torch_dtype="auto",
            low_cpu_mem_usage=True,
        )
        if self.use_adapter:
            if not self.adapter_path or not Path(self.adapter_path).is_dir():
                raise RuntimeError("MODEL_ADAPTER_PATH is missing or not a directory")
            try:
                from peft import PeftModel
            except ImportError as error:
                raise RuntimeError("PEFT is required to load a local adapter") from error
            model = PeftModel.from_pretrained(model, self.adapter_path)
        model.eval()
        self._tokenizer = tokenizer
        self._model = model

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        await self._ensure_loaded()
        content = await asyncio.to_thread(
            self._generate_sync,
            messages,
            temperature,
            max_tokens,
            json_mode,
        )
        return LLMResponse(content=content, model=self.model_id, provider=self.name)

    def _generate_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        _ = json_mode
        prompt = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self._tokenizer([prompt], return_tensors="pt")
        generation = self._model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=temperature > 0,
            temperature=max(temperature, 0.01),
            pad_token_id=self._tokenizer.eos_token_id,
        )
        output_ids = generation[0][inputs.input_ids.shape[1] :]
        content = self._tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        if not content:
            raise RuntimeError("HF CPU provider generated an empty response")
        if json_mode:
            json.loads(content)
        return content

    async def health(self) -> tuple[bool, str]:
        if self.use_adapter and (not self.adapter_path or not Path(self.adapter_path).is_dir()):
            return False, "local adapter path is not configured"
        return True, "configured; model loads lazily on first request"

    async def close(self) -> None:
        self._model = None
        self._tokenizer = None
