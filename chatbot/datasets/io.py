"""Small JSONL helpers with line-aware validation errors."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel


def read_models[ModelType: BaseModel](
    path: Path,
    model_type: type[ModelType],
) -> list[ModelType]:
    rows: list[ModelType] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(model_type.model_validate_json(line))
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def write_models(path: Path, rows: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")
            count += 1
    return count


def write_dicts(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count
