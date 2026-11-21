"""Exact semantic NER/RE evaluation against a frozen, reviewed reference slice.

The source-grounding audit is intentionally not a semantic evaluation.  This module
evaluates canonical entity IDs and relation triples against an explicit JSONL gold
file.  The gold file carries abstract hashes so a changed corpus cannot silently
invalidate the score.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from src.common import read_jsonl, write_json


def _f1(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "support": tp + fn,
        "predicted": tp + fp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _bootstrap_micro_ci(
    gold_by_paper: dict[str, set[tuple[Any, ...]]],
    pred_by_paper: dict[str, set[tuple[Any, ...]]],
    *,
    seed: int = 20261121,
    replicates: int = 10_000,
) -> dict[str, Any]:
    """Paper-level percentile bootstrap intervals for micro precision/recall/F1."""
    paper_ids = sorted(gold_by_paper)
    if not paper_ids:
        return {"unit": "paper", "replicates": replicates, "seed": seed}
    rng = random.Random(seed)
    values = {"precision": [], "recall": [], "f1": []}
    for _ in range(replicates):
        tp = fp = fn = 0
        for paper_id in rng.choices(paper_ids, k=len(paper_ids)):
            gold = gold_by_paper[paper_id]
            predicted = pred_by_paper.get(paper_id, set())
            tp += len(gold & predicted)
            fp += len(predicted - gold)
            fn += len(gold - predicted)
        metrics = _f1(tp, fp, fn)
        for name in values:
            values[name].append(float(metrics[name]))

    def percentile(rows: list[float], probability: float) -> float:
        ordered = sorted(rows)
        index = round((len(ordered) - 1) * probability)
        return round(ordered[index], 4)

    return {
        "unit": "paper",
        "replicates": replicates,
        "seed": seed,
        "precision": [percentile(values["precision"], 0.025), percentile(values["precision"], 0.975)],
        "recall": [percentile(values["recall"], 0.025), percentile(values["recall"], 0.975)],
        "f1": [percentile(values["f1"], 0.025), percentile(values["f1"], 0.975)],
    }


def _abstract_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_predictions(data_dir: Path) -> tuple[dict[str, set[tuple[str, str]]], dict[str, set[tuple[str, str, str]]]]:
    entities: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in read_jsonl(data_dir / "entities.jsonl"):
        entity_type = str(row["entity_type"]).lower()
        # New snapshots carry the complete paper-membership contract. Fall back to bounded
        # evidence only for legacy fixtures/snapshots, where recall may be underestimated.
        paper_ids = row.get("evidence_paper_ids")
        if paper_ids is None:
            paper_ids = [
                evidence.get("paper_id")
                for evidence in row.get("evidence", [])
                if evidence.get("paper_id")
            ]
        for paper_id in paper_ids:
            entities[str(paper_id)].add((entity_type, row["id"]))

    relations: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    paper_relation_entity_type = {
        "USES_METHOD": "method",
        "EVALUATED_ON": "dataset",
        "ADDRESSES_TASK": "task",
    }
    for path in sorted(data_dir.glob("edges_*.jsonl")):
        for row in read_jsonl(path):
            triple = (str(row["type"]), str(row["from"]), str(row["to"]))
            for paper_id in row.get("evidence_paper_ids", []):
                relations[paper_id].add(triple)
                # Paper-anchored edges are emitted only after entity extraction and retain the
                # complete paper set even in legacy snapshots whose entity evidence preview was
                # truncated. Unioning this proof repairs legacy NER membership without changing
                # any predicted canonical ID.
                entity_type = paper_relation_entity_type.get(str(row["type"]))
                if entity_type and str(row["from"]) == str(paper_id):
                    entities[str(paper_id)].add((entity_type, str(row["to"])))
    return entities, relations


def _score_by_type(
    gold: Iterable[tuple[Any, ...]], pred: Iterable[tuple[Any, ...]], type_index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    gold_set, pred_set = set(gold), set(pred)
    types = sorted({str(row[type_index]) for row in gold_set | pred_set})
    per_type: dict[str, Any] = {}
    totals = [0, 0, 0]
    for kind in types:
        g = {row for row in gold_set if str(row[type_index]) == kind}
        p = {row for row in pred_set if str(row[type_index]) == kind}
        tp = len(g & p)
        fp = len(p - g)
        fn = len(g - p)
        per_type[kind] = _f1(tp, fp, fn)
        totals[0] += tp
        totals[1] += fp
        totals[2] += fn
    micro = _f1(*totals)
    macro_f1 = round(sum(row["f1"] for row in per_type.values()) / len(per_type), 4) if per_type else 0.0
    return {"micro": micro, "macro_f1": macro_f1, "per_type": per_type}, {
        "gold": gold_set,
        "predicted": pred_set,
    }


def evaluate_semantic(
    data_dir: Path, processed_dir: Path, gold_path: Path, out_path: Path
) -> dict[str, Any]:
    papers = {row["id"]: row for row in read_jsonl(processed_dir / "papers.jsonl")}
    gold_rows = read_jsonl(gold_path)
    pred_entities, pred_relations = _load_predictions(data_dir)
    gold_entities: dict[str, set[tuple[str, str]]] = {}
    gold_relations: dict[str, set[tuple[str, str, str]]] = {}
    errors: list[dict[str, Any]] = []

    for row in gold_rows:
        paper_id = row["paper_id"]
        paper = papers.get(paper_id)
        if paper is None:
            raise ValueError(f"gold paper is absent from processed corpus: {paper_id}")
        expected_hash = row.get("abstract_sha256")
        actual_hash = _abstract_sha256(str(paper.get("abstract") or ""))
        if expected_hash != actual_hash:
            raise ValueError(f"abstract hash mismatch for {paper_id}: gold={expected_hash} actual={actual_hash}")
        ents = {(str(item["type"]).lower(), str(item["id"])) for item in row.get("entities", [])}
        rels = {(str(item["type"]), str(item["from"]), str(item["to"])) for item in row.get("relations", [])}
        gold_entities[paper_id] = ents
        gold_relations[paper_id] = rels
        pred_e = pred_entities.get(paper_id, set())
        pred_r = pred_relations.get(paper_id, set())
        errors.append({
            "paper_id": paper_id,
            "entity_fp": sorted(pred_e - ents),
            "entity_fn": sorted(ents - pred_e),
            "relation_fp": sorted(pred_r - rels),
            "relation_fn": sorted(rels - pred_r),
        })

    all_gold_e = [item for rows in gold_entities.values() for item in rows]
    all_pred_e = [item for paper_id in gold_entities for item in pred_entities.get(paper_id, set())]
    all_gold_r = [item for rows in gold_relations.values() for item in rows]
    all_pred_r = [item for paper_id in gold_relations for item in pred_relations.get(paper_id, set())]
    entity_scores, _ = _score_by_type(all_gold_e, all_pred_e, 0)
    relation_scores, _ = _score_by_type(all_gold_r, all_pred_r, 0)
    entity_scores["bootstrap_95_ci"] = _bootstrap_micro_ci(gold_entities, pred_entities)
    relation_scores["bootstrap_95_ci"] = _bootstrap_micro_ci(gold_relations, pred_relations)
    result = {
        "schema_version": "enrichment-semantic-eval-v1",
        "evaluation_kind": "exact_canonical_id_semantic_ner_re",
        "provenance": {
            "gold_file": str(gold_path),
            "processed_papers": str(processed_dir / "papers.jsonl"),
            "data_dir": str(data_dir),
            "papers_evaluated": len(gold_rows),
            "annotation_protocol": "developer_manual_review_of_abstract_text_v1",
            "annotators": 1,
            "independent_human_gold": False,
            "status": "nonhuman_reference_slice; do not generalize to the full corpus",
        },
        "entity": entity_scores,
        "relation": relation_scores,
        "errors": errors,
    }
    write_json(out_path, result)
    return result


def run_semantic_eval(data_dir: Path, processed_dir: Path, gold_path: Path, out_path: Path) -> int:
    result = evaluate_semantic(data_dir, processed_dir, gold_path, out_path)
    print(json.dumps({"entity_micro": result["entity"]["micro"], "relation_micro": result["relation"]["micro"]}, ensure_ascii=False))
    return 0
