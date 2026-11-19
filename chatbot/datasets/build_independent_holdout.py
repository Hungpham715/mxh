"""Build leakage-safe train/validation data around a non-human source-review queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from datasets.io import read_models, write_models
from datasets.schema import QuestionCase, ReviewStatus
from datasets.split import assert_no_entity_leakage
from graphrag.models import QueryAction


def _keys(case: QuestionCase) -> set[str]:
    return {f"group:{case.group_id}", *(f"entity:{value}" for value in case.expected_query.entity_ids)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_holdout(
    silver_split: list[QuestionCase], source_review: list[QuestionCase]
) -> tuple[list[QuestionCase], list[QuestionCase], dict[str, object]]:
    if not source_review:
        raise ValueError("non-human source-review set is empty")
    invalid_gold = [
        case.case_id for case in source_review if case.review_status != ReviewStatus.INDEPENDENT_APPROVED
    ]
    if invalid_gold:
        raise ValueError(f"source-review rows are not independent_approved: {invalid_gold[:5]}")

    gold = [case.model_copy(update={"split": "test"}) for case in source_review]
    gold_ids = {case.case_id for case in gold}
    blocked_keys = set().union(*(_keys(case) for case in gold))

    # Compute the complete entity/group connected component around the gold queue. This is stricter
    # than deleting only matching case IDs: no train/validation row can share an entity indirectly.
    removed_ids = set(gold_ids)
    changed = True
    while changed:
        changed = False
        for case in silver_split:
            if case.case_id in removed_ids:
                continue
            keys = _keys(case)
            if keys & blocked_keys:
                removed_ids.add(case.case_id)
                blocked_keys.update(keys)
                changed = True

    trainval = [
        case for case in silver_split if case.split in {"train", "val"} and case.case_id not in removed_ids
    ]
    if any(case.review_status != ReviewStatus.SILVER_APPROVED for case in trainval):
        raise ValueError("train/validation set contains non-silver rows")

    combined = [*trainval, *gold]
    assert_no_entity_leakage(combined)
    duplicate_ids = [key for key, count in Counter(case.case_id for case in combined).items() if count > 1]
    if duplicate_ids:
        raise ValueError(f"duplicate case IDs after holdout build: {duplicate_ids[:5]}")

    expected_actions = {action.value for action in QueryAction}
    gold_actions = {case.expected_query.intent for case in gold}
    manifest: dict[str, object] = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "pass",
        "nonhuman_source_review_cases": len(gold),
        "source_review_status": ReviewStatus.INDEPENDENT_APPROVED.value,
        "source_review_actions": sorted(gold_actions),
        "source_review_missing_actions": sorted(expected_actions - gold_actions),
        "silver_trainval_cases": len(trainval),
        "silver_train_cases": sum(case.split == "train" for case in trainval),
        "silver_val_cases": sum(case.split == "val" for case in trainval),
        "silver_rows_removed_by_gold_component": len(silver_split) - len(trainval),
        "combined_cases": len(combined),
        "entity_and_group_leakage": "pass",
        "human_gold_cases": 0,
        "label_boundary": (
            "non-human source review is development evidence, not human or official independent gold; "
            "silver remains separate"
        ),
    }
    if len(gold) < 300 or expected_actions - gold_actions or len(trainval) < 6000:
        manifest["status"] = "fail"
    return trainval, gold, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--silver-split", type=Path, required=True)
    parser.add_argument("--source-review", type=Path, required=True)
    parser.add_argument("--silver-trainval-out", type=Path, required=True)
    parser.add_argument("--gold-test-out", type=Path, required=True)
    parser.add_argument("--combined-out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    trainval, gold, manifest = build_holdout(
        read_models(args.silver_split, QuestionCase),
        read_models(args.source_review, QuestionCase),
    )
    args.silver_trainval_out.parent.mkdir(parents=True, exist_ok=True)
    write_models(args.silver_trainval_out, trainval)
    write_models(args.gold_test_out, gold)
    write_models(args.combined_out, [*trainval, *gold])
    manifest.update(
        {
            "silver_trainval_sha256": _sha256(args.silver_trainval_out),
            "gold_test_sha256": _sha256(args.gold_test_out),
            "combined_sha256": _sha256(args.combined_out),
        }
    )
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    if manifest["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
