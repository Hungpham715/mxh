"""Import review decisions without silently accepting malformed edits."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from datasets.io import read_models, write_dicts, write_models
from datasets.schema import ExpectedCitations, ExpectedFacts, QuestionCase, ReviewStatus


def import_review(
    source_cases: list[QuestionCase],
    csv_path: Path,
    status_on_yes: ReviewStatus = ReviewStatus.APPROVED,
) -> tuple[list[QuestionCase], list[dict[str, str]]]:
    """Apply review decisions.

    `status_on_yes` distinguishes review provenance: human review CSVs import as APPROVED
    (human gold); machine/auto review CSVs must import as SILVER_APPROVED so silver labels
    can never masquerade as human gold downstream (eval gating, SFT reporting).
    """
    if status_on_yes not in {ReviewStatus.APPROVED, ReviewStatus.SILVER_APPROVED}:
        raise ValueError("status_on_yes must be approved or silver_approved")
    by_id = {case.case_id: case for case in source_cases}
    accepted: list[QuestionCase] = []
    rejected: list[dict[str, str]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            try:
                case_id = row["case_id"].strip()
                decision = row["label_valid"].strip().casefold()
                if case_id not in by_id:
                    raise ValueError("unknown case_id")
                if decision not in {"yes", "no", "unknown"}:
                    raise ValueError("label_valid must be yes, no, or unknown")
                if decision != "yes":
                    continue
                entity_ids = json.loads(row["expected_entities"])
                paper_ids = json.loads(row["expected_paper_ids"])
                source_urls = json.loads(row["source_urls"])
                if not all(isinstance(item, str) for item in entity_ids + paper_ids + source_urls):
                    raise ValueError("expected lists must contain strings")
                original = by_id[case_id]
                query = original.expected_query.model_copy(update={"entity_ids": entity_ids})
                facts = ExpectedFacts(
                    predicates=original.expected_facts.predicates,
                    object_ids=original.expected_facts.object_ids,
                    answer=row["expected_answer"].strip(),
                )
                citations = ExpectedCitations(paper_ids=paper_ids, source_urls=source_urls)
                accepted.append(
                    original.model_copy(
                        update={
                            "question": row["question"].strip(),
                            "expected_query": query,
                            "expected_facts": facts,
                            "expected_citations": citations,
                            "review_status": status_on_yes,
                            "reviewer_note": row["reviewer_note"].strip(),
                        }
                    )
                )
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
                rejected.append({"row": str(row_number), "error": str(error)})
    return accepted, rejected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rejected", type=Path, required=True)
    parser.add_argument(
        "--status-on-yes",
        choices=["approved", "silver_approved"],
        default="approved",
        help="use silver_approved for machine-generated (auto_review) CSVs; approved only for human review",
    )
    args = parser.parse_args()
    source_cases = read_models(args.source, QuestionCase)
    accepted, rejected = import_review(source_cases, args.csv, ReviewStatus(args.status_on_yes))
    write_models(args.out, accepted)
    write_dicts(args.rejected, rejected)
    print(f"approved={len(accepted)} (status={args.status_on_yes}) rejected_rows={len(rejected)}")


if __name__ == "__main__":
    main()
