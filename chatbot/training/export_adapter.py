"""Validate and copy a local PEFT adapter to an explicit destination."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

WEIGHT_NAMES = {"adapter_model.safetensors", "adapter_model.bin"}


def validate_adapter(path: Path) -> dict:
    config_path = path / "adapter_config.json"
    if not config_path.is_file():
        raise ValueError("adapter_config.json is missing")
    weights = [name for name in WEIGHT_NAMES if (path / name).is_file()]
    if not weights:
        raise ValueError("adapter weights are missing")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return {"config": config, "weights": weights}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    metadata = validate_adapter(args.source)
    if args.out.exists():
        raise SystemExit("output already exists; refusing to overwrite adapter")
    shutil.copytree(args.source, args.out)
    print(f"exported local adapter to {args.out}; weights={metadata['weights']}")


if __name__ == "__main__":
    main()
