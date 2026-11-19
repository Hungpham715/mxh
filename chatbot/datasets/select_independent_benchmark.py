"""Select a deterministic 300-case non-human source-review development benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from datasets.io import read_models, write_models
from datasets.schema import QuestionCase, ReviewStatus
from graphrag.models import QueryAction


def select(cases: list[QuestionCase], size: int, seed: int) -> list[QuestionCase]:
    challenges = [case for case in cases if case.case_id.startswith(("independent-", "oos-"))]
    base = [case for case in cases if case not in challenges]
    if size < len(challenges):
        raise ValueError("benchmark size is smaller than the required challenge set")
    target_base = size - len(challenges)
    by_action: dict[str, list[QuestionCase]] = defaultdict(list)
    for case in base:
        by_action[case.expected_query.intent].append(case)
    rng = random.Random(seed)
    selected: list[QuestionCase] = []
    leftovers: list[QuestionCase] = []
    for action in sorted(by_action):
        group = by_action[action]
        rng.shuffle(group)
        quota = max(2, int(target_base * len(group) / len(base)))
        quota = min(quota, len(group))
        selected.extend(group[:quota])
        leftovers.extend(group[quota:])
    rng.shuffle(leftovers)
    if len(selected) > target_base:
        raise ValueError("minimum per-action quotas exceed target benchmark size")
    selected.extend(leftovers[: target_base - len(selected)])
    selected.extend(challenges)
    rng.shuffle(selected)
    if len(selected) != size:
        raise ValueError(f"selected {len(selected)} cases, expected {size}")
    expected_actions = {action.value for action in QueryAction}
    observed_actions = {case.expected_query.intent for case in selected}
    missing = expected_actions - observed_actions
    if missing:
        raise ValueError(f"benchmark misses actions: {sorted(missing)}")
    if any(case.review_status != ReviewStatus.INDEPENDENT_APPROVED for case in selected):
        raise ValueError("benchmark contains rows outside the non-human source-review status")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--size", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    selected = select(read_models(args.input, QuestionCase), args.size, args.seed)
    write_models(args.out, selected)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "pass",
        "seed": args.seed,
        "cases": len(selected),
        "input": str(args.input),
        "output": str(args.out),
        "output_sha256": digest,
        "by_intent": dict(sorted(Counter(case.expected_query.intent for case in selected).items())),
        "by_status": dict(sorted(Counter(case.expected_status for case in selected).items())),
        "by_route": dict(sorted(Counter(case.expected_route for case in selected).items())),
        "challenge_cases": sum(case.case_id.startswith(("independent-", "oos-")) for case in selected),
        "human_gold_cases": 0,
        "nonhuman_source_review_cases": len(selected),
        "official_independent_gold_cases": 0,
        "label_boundary": "development-only; not human or official independent gold",
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
