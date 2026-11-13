"""Reproducible entity-connected group split with leakage validation."""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from pathlib import Path

from datasets.io import read_models, write_models
from datasets.schema import QuestionCase


def assign_splits(cases: list[QuestionCase], seed: int = 42) -> list[QuestionCase]:
    components = _entity_components(cases)
    rng = random.Random(seed)
    rng.shuffle(components)
    targets = (0.7, 0.15)
    total = len(cases)
    assigned = {"train": 0, "val": 0, "test": 0}
    output: list[QuestionCase] = []

    for component in components:
        train_ratio = assigned["train"] / total if total else 0
        val_ratio = assigned["val"] / total if total else 0
        if train_ratio < targets[0]:
            split_name = "train"
        elif val_ratio < targets[1]:
            split_name = "val"
        else:
            split_name = "test"
        for case in component:
            output.append(case.model_copy(update={"split": split_name}))
            assigned[split_name] += 1

    assert_no_entity_leakage(output)
    return sorted(output, key=lambda case: case.case_id)


def _entity_components(cases: list[QuestionCase]) -> list[list[QuestionCase]]:
    parent = list(range(len(cases)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owner_by_key: dict[str, int] = {}
    for index, case in enumerate(cases):
        keys = {case.group_id, *case.expected_query.entity_ids}
        for key in keys:
            if key in owner_by_key:
                union(index, owner_by_key[key])
            else:
                owner_by_key[key] = index

    grouped: dict[int, list[QuestionCase]] = defaultdict(list)
    for index, case in enumerate(cases):
        grouped[find(index)].append(case)
    return list(grouped.values())


def assert_no_entity_leakage(cases: list[QuestionCase]) -> None:
    entity_splits: dict[str, set[str]] = defaultdict(set)
    group_splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        if case.split is None:
            raise ValueError(f"case {case.case_id} has no split")
        group_splits[case.group_id].add(case.split)
        for entity_id in case.expected_query.entity_ids:
            entity_splits[entity_id].add(case.split)
    leaked_groups = {key: value for key, value in group_splits.items() if len(value) > 1}
    leaked_entities = {key: value for key, value in entity_splits.items() if len(value) > 1}
    if leaked_groups or leaked_entities:
        raise ValueError(f"split leakage: groups={leaked_groups}, entities={leaked_entities}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    cases = read_models(args.input, QuestionCase)
    output = assign_splits(cases, args.seed)
    print(f"wrote {write_models(args.out, output)} leakage-checked split cases")


if __name__ == "__main__":
    main()
