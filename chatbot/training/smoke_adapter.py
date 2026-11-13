"""Adapter metadata smoke with optional real CPU load/inference."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from graphrag.llm.hf_cpu import HFCPUProvider
from training.export_adapter import validate_adapter


async def load_and_generate(model_id: str, adapter: Path) -> str:
    provider = HFCPUProvider(model_id, str(adapter), use_adapter=True)
    try:
        response = await provider.generate(
            [{"role": "user", "content": "Trả lời đúng một từ: OK"}],
            temperature=0,
            max_tokens=16,
            json_mode=False,
        )
        return response.content
    finally:
        await provider.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--model-id", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--load-model", action="store_true")
    args = parser.parse_args()
    metadata = validate_adapter(args.adapter)
    print(f"adapter metadata valid; weights={metadata['weights']}")
    if not args.load_model:
        print("CPU model load SKIPPED; add --load-model when base weights and sufficient RAM are available")
        return
    print(asyncio.run(load_and_generate(args.model_id, args.adapter)))


if __name__ == "__main__":
    main()
