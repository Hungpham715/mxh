"""Build a reproducible quality manifest for a question dataset.

The manifest reports what is actually present. It never upgrades silver rows to human gold and
never treats a structurally valid JSONL file as evidence that its scientific claims are true.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datasets.io import read_models
from datasets.schema import QuestionCase, ReviewStatus
from datasets.split import assert_no_entity_leakage
from graphrag.models import QueryAction


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def build_manifest(cases: list[QuestionCase], input_path: Path) -> dict[str, Any]:
    case_ids = [case.case_id for case in cases]
    normalized_questions = [" ".join(case.question.casefold().split()) for case in cases]
    duplicate_case_ids = sorted(key for key, count in Counter(case_ids).items() if count > 1)
    duplicate_questions = sorted(key for key, count in Counter(normalized_questions).items() if count > 1)

    split_values = [case.split for case in cases if case.split is not None]
    leakage_status = "not_applicable"
    leakage_error: str | None = None
    if split_values and len(split_values) == len(cases):
        try:
            assert_no_entity_leakage(cases)
            leakage_status = "pass"
        except ValueError as error:
            leakage_status = "fail"
            leakage_error = str(error)
    elif split_values:
        leakage_status = "fail"
        leakage_error = "dataset mixes assigned and unassigned split rows"

    intents_present = {case.expected_query.intent for case in cases}
    actions = {action.value for action in QueryAction}
    missing_actions = sorted(actions - intents_present)
    review_counts = _counts(case.review_status.value for case in cases)
    invalid_human_provenance = [
        case.case_id
        for case in cases
        if case.review_status == ReviewStatus.APPROVED
        and case.reviewer_note.casefold().startswith(("auto:", "silver_auto:", "independent_"))
    ]

    manifest: dict[str, Any] = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "cases": len(cases),
        "unique_case_ids": len(set(case_ids)),
        "unique_normalized_questions": len(set(normalized_questions)),
        "duplicate_case_ids": duplicate_case_ids,
        "duplicate_normalized_question_count": len(duplicate_questions),
        "by_intent": _counts(case.expected_query.intent for case in cases),
        "by_status": _counts(case.expected_status for case in cases),
        "by_review_status": review_counts,
        "by_split": _counts(case.split or "unassigned" for case in cases),
        "by_snapshot": _counts(case.snapshot_version for case in cases),
        "actions_present": sorted(actions & intents_present),
        "missing_actions": missing_actions,
        "silver_cases": review_counts.get(ReviewStatus.SILVER_APPROVED.value, 0),
        "human_gold_cases": review_counts.get(ReviewStatus.APPROVED.value, 0) - len(invalid_human_provenance),
        "nonhuman_source_review_cases": review_counts.get(ReviewStatus.INDEPENDENT_APPROVED.value, 0),
        "invalid_human_provenance_cases": len(invalid_human_provenance),
        "invalid_human_provenance_case_ids": invalid_human_provenance,
        "answered_or_partial_with_facts": sum(
            case.expected_status in {"answered", "partial"} and bool(case.verified_facts) for case in cases
        ),
        "cases_with_source_urls": sum(bool(case.expected_citations.source_urls) for case in cases),
        "leakage_check": leakage_status,
        "leakage_error": leakage_error,
    }
    manifest["quality_status"] = (
        "pass"
        if not duplicate_case_ids
        and not missing_actions
        and leakage_status != "fail"
        and not invalid_human_provenance
        else "fail"
    )
    manifest["label_disclaimer"] = (
        "approved is human-only; independent_approved is non-human source review, not official gold; "
        "silver_approved is pipeline graph re-query and does not prove graph truth"
    )
    return manifest


def write_report(manifest: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Dataset quality audit",
        "",
        f"Status: **{manifest['quality_status'].upper()}**",
        f"Cases: {manifest['cases']} | SHA-256: `{manifest['input_sha256']}`",
        (
            f"Silver: {manifest['silver_cases']} | Non-human source review: "
            f"{manifest['nonhuman_source_review_cases']} | Human gold: {manifest['human_gold_cases']}"
        ),
        f"Leakage check: {manifest['leakage_check']}",
        "",
        "## Intent distribution",
        "",
        "| Intent | Cases |",
        "|---|---:|",
    ]
    lines.extend(f"| {intent} | {count} |" for intent, count in manifest["by_intent"].items())
    lines.extend(
        [
            "",
            "## Label boundary",
            "",
            manifest["label_disclaimer"],
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    cases = read_models(args.input, QuestionCase)
    manifest = build_manifest(cases, args.input)
    write_report(manifest, args.json, args.markdown)
    print(
        f"dataset audit {manifest['quality_status']}: cases={manifest['cases']} "
        f"silver={manifest['silver_cases']} human_gold={manifest['human_gold_cases']}"
    )


if __name__ == "__main__":
    main()
