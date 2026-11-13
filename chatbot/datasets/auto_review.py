"""Programmatic quality gate that labels generated candidates for import_review.

The chatbot dataset is generated deterministically from the live read-only graph, so the gold
answer/facts are graph truth. This module plays the reviewer role with explicit, strict gates
(the user delegated dataset curation): a candidate is labelled ``yes`` only when its gold PARSE
target is structurally valid and, for answered cases, it actually has grounded facts.

Output is a CSV in the same column format as ``export_review`` so ``import_review`` can consume
it unchanged (import_review preserves the runtime-aligned fields from the source case).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from datasets.export_review import FIELDS
from datasets.io import read_models
from datasets.schema import QuestionCase

# Minimum entity mentions of the required type for each intent's gold PARSE target.
REQUIRED_MENTIONS: dict[str, tuple[str, int]] = {
    "author_papers": ("Author", 1),
    "coauthors": ("Author", 1),
    "author_affiliations": ("Author", 1),
    "coauthor_affiliations": ("Author", 1),
    "shared_papers": ("Author", 2),
    "author_path": ("Author", 2),
    "paper_authors": ("Paper", 1),
    "paper_venue": ("Paper", 1),
    "paper_citations": ("Paper", 1),
    "topic_papers": ("Topic", 1),
    "org_collaborations": ("Institution", 1),
    "network_top": ("", 0),
    "unknown": ("", 0),
}

VALID_INTENTS = set(REQUIRED_MENTIONS)


def gate(case: QuestionCase) -> tuple[bool, str]:
    """Return (label_valid, reason). Strict structural checks only; no graph re-query."""
    if not case.question.strip():
        return False, "empty_question"

    intent = case.expected_query.intent
    if intent not in VALID_INTENTS:
        return False, f"unknown_intent:{intent}"

    required_type, required_count = REQUIRED_MENTIONS[intent]
    if required_count == 0:
        if case.entity_mentions:
            return False, "unexpected_mentions_for_intent"
    else:
        matching = [m for m in case.entity_mentions if m.type == required_type and m.text.strip()]
        if len(matching) < required_count:
            return False, f"needs_{required_count}_{required_type}_mentions"

    # Answered/partial cases must be groundable: facts present and a non-empty gold answer.
    if case.expected_status in {"answered", "partial"}:
        if not case.verified_facts:
            return False, "answered_without_verified_facts"
        if not case.expected_facts.answer.strip():
            return False, "answered_without_answer"

    # Negative cases (not_found/out_of_scope/ambiguous) are kept for refusal training; they
    # need a valid intent and, except out_of_scope, correct entity mentions (checked above).
    return True, "passed"


def label_cases(cases: list[QuestionCase]) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows: list[dict[str, str]] = []
    stats: dict[str, int] = {"yes": 0, "no": 0}
    for case in cases:
        valid, reason = gate(case)
        label = "yes" if valid else "no"
        stats[label] += 1
        rows.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "expected_answer": case.expected_facts.answer,
                "expected_entities": json.dumps(case.expected_query.entity_ids, ensure_ascii=False),
                "expected_paper_ids": json.dumps(case.expected_citations.paper_ids, ensure_ascii=False),
                "source_urls": json.dumps(case.expected_citations.source_urls, ensure_ascii=False),
                "label_valid": label,
                "reviewer_note": f"auto:{reason}",
            }
        )
    return rows, stats


def write_review_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = read_models(args.input, QuestionCase)
    rows, stats = label_cases(cases)
    write_review_csv(rows, args.out)
    print(f"auto-reviewed {len(cases)} candidates -> {args.out} (yes={stats['yes']} no={stats['no']})")


if __name__ == "__main__":
    main()
