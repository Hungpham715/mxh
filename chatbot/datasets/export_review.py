"""Export candidate JSONL to a spreadsheet-friendly review CSV."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from datasets.io import read_models
from datasets.schema import QuestionCase

FIELDS = [
    "case_id",
    "question",
    "expected_answer",
    "expected_entities",
    "expected_paper_ids",
    "source_urls",
    "label_valid",
    "reviewer_note",
]


def export_review(cases: list[QuestionCase], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_id": case.case_id,
                    "question": case.question,
                    "expected_answer": case.expected_facts.answer,
                    "expected_entities": json.dumps(case.expected_query.entity_ids, ensure_ascii=False),
                    "expected_paper_ids": json.dumps(case.expected_citations.paper_ids, ensure_ascii=False),
                    "source_urls": json.dumps(case.expected_citations.source_urls, ensure_ascii=False),
                    "label_valid": "unknown",
                    "reviewer_note": case.reviewer_note,
                }
            )
    return len(cases)


def select_review_cases(
    cases: list[QuestionCase], split: str | None, limit: int | None, seed: int
) -> list[QuestionCase]:
    """Select a reproducible, intent-diverse review queue from an optional held-out split."""
    selected = [case for case in cases if split is None or case.split == split]
    if limit is None or len(selected) <= limit:
        return selected

    by_intent: dict[str, list[QuestionCase]] = defaultdict(list)
    for case in selected:
        by_intent[case.expected_query.intent].append(case)

    rng = random.Random(seed)
    for intent_cases in by_intent.values():
        rng.shuffle(intent_cases)

    output: list[QuestionCase] = []
    intent_names = sorted(by_intent)
    while len(output) < limit:
        made_progress = False
        for intent_name in intent_names:
            intent_cases = by_intent[intent_name]
            if not intent_cases:
                continue
            output.append(intent_cases.pop())
            made_progress = True
            if len(output) == limit:
                break
        if not made_progress:
            break
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=["train", "val", "test"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    cases = read_models(args.input, QuestionCase)
    selected = select_review_cases(cases, args.split, args.limit, args.seed)
    print(f"exported {export_review(selected, args.out)} rows for human review")


if __name__ == "__main__":
    main()
