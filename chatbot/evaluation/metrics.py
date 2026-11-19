"""Transparent metrics; unavailable labels are reported as not_measured.

Honesty rules (per evaluation design):
- Nothing is hardcoded. Every rate is computed from per-case rows produced by a real run.
- Metrics that require labels the dataset does not carry return NOT_MEASURED.
- `label_level` states what the expected values are: "human_gold", "nonhuman_source_review"
  (explicitly not official independent gold), "silver" (source-validated by the pipeline),
  or "synthetic" (fixture smoke, never a benchmark).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from statistics import median
from typing import Any

NOT_MEASURED = "not_measured"

GOLD_LEVELS = {"human_gold", "nonhuman_source_review", "silver"}


def safe_divide(numerator: float, denominator: float) -> float | str:
    if denominator == 0:
        return NOT_MEASURED
    return numerator / denominator


def precision_recall_f1(predicted: set[str], expected: set[str]) -> dict[str, float]:
    true_positive = len(predicted & expected)
    precision = safe_divide(true_positive, len(predicted)) if predicted else 1.0
    recall = safe_divide(true_positive, len(expected)) if expected else 1.0
    if isinstance(precision, str) or isinstance(recall, str):  # pragma: no cover - defensive
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    f1 = safe_divide(2 * precision * recall, precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1 if not isinstance(f1, str) else 0.0}


def token_f1(prediction: str, expected: str) -> float:
    predicted_tokens = re.findall(r"\w+", prediction.casefold())
    expected_tokens = re.findall(r"\w+", expected.casefold())
    if not predicted_tokens and not expected_tokens:
        return 1.0
    overlap = sum((Counter(predicted_tokens) & Counter(expected_tokens)).values())
    precision = safe_divide(overlap, len(predicted_tokens))
    recall = safe_divide(overlap, len(expected_tokens))
    f1 = safe_divide(2 * precision * recall, precision + recall)
    if isinstance(precision, str) or isinstance(recall, str) or isinstance(f1, str):
        return 0.0
    return f1


def factual_value_set(text: str) -> set[str]:
    """Parse the evaluator's canonical semicolon/newline-separated answer-value contract."""
    values: set[str] = set()
    for item in re.split(r"[;\n]+", text or ""):
        normalized = unicodedata.normalize("NFKC", item).casefold()
        normalized = re.sub(r"\s+", " ", normalized).strip(" \t\r\n-•*._'\"“”")
        if normalized:
            values.add(normalized)
    return values


def factual_set_score(prediction: str, expected: str) -> dict[str, float]:
    """Exact set P/R/F1 over canonical factual values, independent of word frequency."""
    return precision_recall_f1(factual_value_set(prediction), factual_value_set(expected))


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _entity_set(mentions: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(str(item.get("text", "")).casefold().strip(), str(item.get("type", ""))) for item in mentions}


def _route_match(row: dict[str, Any]) -> bool:
    expected_route = row.get("expected_route")
    if expected_route is None:
        expected_status = row.get("expected_status")
        expected_route = "out_of_scope" if expected_status == "out_of_scope" else "graph_qa"
    return row["prediction"].get("route") == expected_route


def _first_integer(text: str) -> int | None:
    match = re.search(r"\b(\d+)\b", text or "")
    return int(match.group(1)) if match else None


def summarize(rows: list[dict[str, Any]], label_level: str) -> dict[str, Any]:
    """Aggregate per-case rows. `label_level` gates metrics that need reviewed expectations."""
    if label_level not in {"human_gold", "nonhuman_source_review", "silver", "synthetic"}:
        raise ValueError(f"unknown label_level: {label_level}")
    has_labels = label_level in GOLD_LEVELS
    n = len(rows)

    latencies = [float(row["latency_ms"]) for row in rows]
    iterations = [int(row["prediction"]["iterations_used"]) for row in rows]

    json_valid = [
        row["prediction"].get("parse_source") == "llm"
        and not str(row["prediction"]["stop_reason"]).startswith("intent_parse_error")
        for row in rows
    ]

    entity_scores = []
    for row in rows:
        gold = row.get("expected_entity_mentions")
        if gold is None:
            continue
        predicted = _entity_set(row["prediction"].get("parsed_entities") or [])
        expected = _entity_set(gold)
        entity_scores.append(precision_recall_f1(predicted, expected))

    link_rows = [row for row in rows if row.get("expected_entity_ids")]
    link_top1 = [
        bool(
            row["prediction"].get("linked_entities")
            and row["prediction"]["linked_entities"][0].get("id") in set(row["expected_entity_ids"])
        )
        for row in link_rows
    ]
    link_set = [
        {entity["id"] for entity in row["prediction"].get("linked_entities") or []}
        == set(row["expected_entity_ids"])
        for row in link_rows
    ]

    citation_scores = (
        [precision_recall_f1(set(row["predicted_paper_ids"]), set(row["expected_paper_ids"])) for row in rows]
        if has_labels
        else []
    )

    url_rows = [row for row in rows if row.get("expected_source_urls")] if has_labels else []
    url_precision = []
    for row in url_rows:
        expected_urls = {str(url) for url in row["expected_source_urls"]}
        predicted_sources = row["prediction"].get("sources") or []
        if not predicted_sources:
            url_precision.append(1.0 if not expected_urls else 0.0)
            continue
        good = sum(1 for source in predicted_sources if source.get("url") in expected_urls)
        url_precision.append(good / len(predicted_sources))

    source_supported = (
        [set(row["predicted_paper_ids"]) <= set(row["expected_paper_ids"]) for row in rows]
        if has_labels
        else []
    )

    answer_scores = [row["answer_token_f1"] for row in rows if row["answer_token_f1"] is not None]
    factual_scores = [
        factual_set_score(row["prediction"].get("answer") or "", row.get("expected_answer") or "")
        for row in rows
        if row.get("expected_answer") and not str(row.get("template_id", "")).endswith("_count")
    ]

    count_rows = [row for row in rows if str(row.get("template_id", "")).endswith("_count")]
    count_exact = []
    for row in count_rows:
        expected_number = _first_integer(row.get("expected_answer") or "")
        predicted_number = _first_integer(row["prediction"].get("answer") or "")
        if expected_number is not None:
            count_exact.append(int(predicted_number == expected_number))

    def status_group_accuracy(expected_status: str) -> float | str:
        group = [row for row in rows if row.get("expected_status") == expected_status]
        if not group:
            return NOT_MEASURED
        return sum(row["status_match"] for row in group) / len(group)

    multi_hop_rows = [
        row
        for row in rows
        if row.get("expected_intent") == "author_path" or int(row["prediction"]["iterations_used"]) >= 2
    ]

    summary: dict[str, Any] = {
        "cases": n,
        "label_level": label_level,
        "json_validity": safe_divide(sum(json_valid), n),
        "route_accuracy": safe_divide(sum(_route_match(row) for row in rows), n),
        "intent_accuracy": safe_divide(
            sum(row["prediction"].get("parsed_intent") == row.get("expected_intent") for row in rows),
            n,
        ),
        "entity_extraction_precision": (
            safe_divide(sum(score["precision"] for score in entity_scores), len(entity_scores))
            if entity_scores
            else NOT_MEASURED
        ),
        "entity_extraction_recall": (
            safe_divide(sum(score["recall"] for score in entity_scores), len(entity_scores))
            if entity_scores
            else NOT_MEASURED
        ),
        "entity_extraction_f1": (
            safe_divide(sum(score["f1"] for score in entity_scores), len(entity_scores))
            if entity_scores
            else NOT_MEASURED
        ),
        "entity_link_top1": safe_divide(sum(link_top1), len(link_top1)),
        "entity_link_set_accuracy": safe_divide(sum(link_set), len(link_set)),
        "query_template_accuracy": safe_divide(sum(row["query_template_match"] for row in rows), n),
        "query_execution_success": safe_divide(
            sum(row["prediction"]["status"] != "error" for row in rows), n
        ),
        "evidence_precision": (
            safe_divide(sum(score["precision"] for score in citation_scores), len(citation_scores))
            if citation_scores
            else NOT_MEASURED
        ),
        "evidence_recall": (
            safe_divide(sum(score["recall"] for score in citation_scores), len(citation_scores))
            if citation_scores
            else NOT_MEASURED
        ),
        "answer_exact_match": (
            safe_divide(sum(row["answer_exact_match"] for row in rows), n) if has_labels else NOT_MEASURED
        ),
        "answer_token_f1": (
            safe_divide(sum(answer_scores), len(answer_scores))
            if has_labels and answer_scores
            else NOT_MEASURED
        ),
        "answer_factual_set_precision": (
            safe_divide(sum(score["precision"] for score in factual_scores), len(factual_scores))
            if has_labels and factual_scores
            else NOT_MEASURED
        ),
        "answer_factual_set_recall": (
            safe_divide(sum(score["recall"] for score in factual_scores), len(factual_scores))
            if has_labels and factual_scores
            else NOT_MEASURED
        ),
        "answer_factual_set_f1": (
            safe_divide(sum(score["f1"] for score in factual_scores), len(factual_scores))
            if has_labels and factual_scores
            else NOT_MEASURED
        ),
        "numeric_exactness": safe_divide(sum(count_exact), len(count_exact)) if count_exact else NOT_MEASURED,
        "citation_id_precision": (
            safe_divide(sum(score["precision"] for score in citation_scores), len(citation_scores))
            if citation_scores
            else NOT_MEASURED
        ),
        "citation_url_precision": (
            safe_divide(sum(url_precision), len(url_precision)) if url_precision else NOT_MEASURED
        ),
        "source_supported_rate": (
            safe_divide(sum(source_supported), len(source_supported)) if source_supported else NOT_MEASURED
        ),
        "refusal_accuracy": status_group_accuracy("out_of_scope"),
        "not_found_accuracy": status_group_accuracy("not_found"),
        "clarify_accuracy": (
            status_group_accuracy("clarify")
            if any(row.get("expected_status") == "clarify" for row in rows)
            else status_group_accuracy("ambiguous")
        ),
        "status_accuracy": safe_divide(sum(row["status_match"] for row in rows), n),
        "multi_hop_cases": len(multi_hop_rows),
        "multi_hop_success": (
            safe_divide(sum(row["status_match"] for row in multi_hop_rows), len(multi_hop_rows))
            if multi_hop_rows
            else NOT_MEASURED
        ),
        "premature_stop_rate": safe_divide(
            sum(
                row["prediction"]["status"] == "partial" and row["expected_status"] == "answered"
                for row in rows
            ),
            n,
        ),
        "truncated_rows": sum(bool(row["prediction"].get("truncated")) for row in rows),
        "iterations_avg": safe_divide(sum(iterations), len(iterations)),
        "iterations_p95": percentile([float(value) for value in iterations], 0.95),
        "latency_median_ms": median(latencies) if latencies else 0,
        "latency_p95_ms": percentile(latencies, 0.95),
        "timeout_count": sum("timeout" in row["prediction"]["stop_reason"] for row in rows),
        "error_count": sum(row["prediction"]["status"] == "error" for row in rows),
        "factual_correctness_llm_judge": NOT_MEASURED,
        "hallucination_rate_llm_judge": NOT_MEASURED,
    }
    return summary
