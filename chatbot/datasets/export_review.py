"""Export candidate JSONL to a spreadsheet-friendly review CSV."""

from __future__ import annotations

import argparse
import csv
import json
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = read_models(args.input, QuestionCase)
    print(f"exported {export_review(cases, args.out)} rows for human review")


if __name__ == "__main__":
    main()
