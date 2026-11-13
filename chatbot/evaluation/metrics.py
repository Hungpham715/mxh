"""Transparent metrics; unavailable labels are reported as not_measured."""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import median
from typing import Any

NOT_MEASURED = "not_measured"


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def precision_recall_f1(predicted: set[str], expected: set[str]) -> dict[str, float]:
    true_positive = len(predicted & expected)
    precision = safe_divide(true_positive, len(predicted))
    recall = safe_divide(true_positive, len(expected))
    f1 = safe_divide(2 * precision * recall, precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def token_f1(prediction: str, expected: str) -> float:
    predicted_tokens = re.findall(r"\w+", prediction.casefold())
    expected_tokens = re.findall(r"\w+", expected.casefold())
    if not predicted_tokens and not expected_tokens:
        return 1.0
    overlap = sum((Counter(predicted_tokens) & Counter(expected_tokens)).values())
    precision = safe_divide(overlap, len(predicted_tokens))
    recall = safe_divide(overlap, len(expected_tokens))
    return safe_divide(2 * precision * recall, precision + recall)


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def summarize(rows: list[dict[str, Any]], reviewed_gold: bool) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in rows]
    iterations = [int(row["prediction"]["iterations_used"]) for row in rows]
    citation_scores = [
        precision_recall_f1(
            set(row["predicted_paper_ids"]),
            set(row["expected_paper_ids"]),
        )
        for row in rows
    ]
    answer_scores = [row["answer_token_f1"] for row in rows if row["answer_token_f1"] is not None]
    query_matches = [row["query_template_match"] for row in rows]
    status_matches = [row["status_match"] for row in rows]
    return {
        "cases": len(rows),
        "json_validity": 1.0,
        "intent_accuracy": NOT_MEASURED,
        "entity_extraction_precision": NOT_MEASURED,
        "entity_extraction_recall": NOT_MEASURED,
        "entity_extraction_f1": NOT_MEASURED,
        "entity_link_top1": NOT_MEASURED,
        "query_template_accuracy": safe_divide(sum(query_matches), len(query_matches)),
        "query_execution_success": safe_divide(
            sum(row["prediction"]["status"] != "error" for row in rows),
            len(rows),
        ),
        "evidence_precision": (
            safe_divide(sum(score["precision"] for score in citation_scores), len(citation_scores))
            if reviewed_gold
            else NOT_MEASURED
        ),
        "evidence_recall": (
            safe_divide(sum(score["recall"] for score in citation_scores), len(citation_scores))
            if reviewed_gold
            else NOT_MEASURED
        ),
        "answer_exact_match": (
            safe_divide(sum(row["answer_exact_match"] for row in rows), len(rows))
            if reviewed_gold
            else NOT_MEASURED
        ),
        "answer_token_f1": (
            safe_divide(sum(answer_scores), len(answer_scores))
            if reviewed_gold and answer_scores
            else NOT_MEASURED
        ),
        "numeric_exactness": NOT_MEASURED,
        "citation_id_precision": (
            safe_divide(sum(score["precision"] for score in citation_scores), len(citation_scores))
            if reviewed_gold
            else NOT_MEASURED
        ),
        "citation_url_precision": NOT_MEASURED,
        "source_supported_rate": NOT_MEASURED,
        "refusal_accuracy": safe_divide(sum(status_matches), len(status_matches)),
        "multi_hop_success": safe_divide(
            sum(row["status_match"] for row in rows if len(row["expected_entity_ids"]) >= 2),
            sum(len(row["expected_entity_ids"]) >= 2 for row in rows),
        ),
        "premature_stop_rate": safe_divide(
            sum(
                row["prediction"]["status"] == "partial" and row["expected_status"] == "answered"
                for row in rows
            ),
            len(rows),
        ),
        "iterations_avg": safe_divide(sum(iterations), len(iterations)),
        "iterations_p95": percentile([float(value) for value in iterations], 0.95),
        "latency_median_ms": median(latencies) if latencies else 0,
        "latency_p95_ms": percentile(latencies, 0.95),
        "timeout_count": sum("timeout" in row["prediction"]["stop_reason"] for row in rows),
        "error_count": sum(row["prediction"]["status"] == "error" for row in rows),
        "factual_correctness_llm_judge": NOT_MEASURED,
        "hallucination_rate_llm_judge": NOT_MEASURED,
    }
