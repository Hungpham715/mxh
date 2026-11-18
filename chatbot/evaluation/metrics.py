"""Transparent chatbot metrics computed from real predictions and traces.

Nothing is hardcoded: every metric is a ratio over the rows where it applies, reported with
its denominator `n`. A metric with no applicable rows is `not_measured`. Metrics that need a
human/LLM judge (free-text factual precision, hallucination) stay `not_measured`.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from statistics import median
from typing import Any

NOT_MEASURED = "not_measured"


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def precision_recall_f1(predicted: set[str], expected: set[str]) -> dict[str, float]:
    if not predicted and not expected:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
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


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", value).strip()


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total == 0:
        return None
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _ratio(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | str:
    """Mean of a boolean/float column over rows where it is not None, with n and Wilson CI."""
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return NOT_MEASURED
    total = sum(float(value) for value in values)
    result: dict[str, Any] = {"value": round(total / len(values), 4), "n": len(values)}
    if all(isinstance(value, bool) for value in values):
        interval = wilson_interval(int(total), len(values))
        result["ci95"] = [round(interval[0], 4), round(interval[1], 4)] if interval else None
    return result


def summarize(rows: list[dict[str, Any]], label_tier: str) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in rows]
    iterations = [int(row["prediction"]["iterations_used"]) for row in rows]
    llm_calls = [int(row["prediction"].get("llm_calls", 0)) for row in rows]
    return {
        "cases": len(rows),
        "label_tier": label_tier,
        "json_parse_validity": _ratio(rows, "parse_valid_json"),
        "route_accuracy": _ratio(rows, "route_match"),
        "status_accuracy": _ratio(rows, "status_match"),
        "intent_accuracy": _ratio(rows, "intent_match"),
        "entity_link_accuracy": _ratio(rows, "entity_ids_match"),
        "query_params_exact": _ratio(rows, "params_match"),
        "query_result_set_f1": _ratio(rows, "result_set_f1"),
        "answer_name_recall": _ratio(rows, "answer_name_recall"),
        "count_exactness": _ratio(rows, "count_exact"),
        "citation_precision": _ratio(rows, "citation_precision"),
        "citation_url_valid": _ratio(rows, "citation_urls_valid"),
        "out_of_scope_refusal": _ratio(rows, "refusal_correct"),
        "false_refusal": _ratio(rows, "false_refusal"),
        "clarify_accuracy": _ratio(rows, "clarify_correct"),
        "ambiguity_detection": _ratio(rows, "ambiguity_correct"),
        "not_found_accuracy": _ratio(rows, "not_found_correct"),
        "multi_hop_query_success": _ratio(rows, "multi_hop_success"),
        "complete_flag_honest": _ratio(rows, "complete_flag_honest"),
        "iterations_avg": round(safe_divide(sum(iterations), len(iterations)), 3),
        "iterations_max": max(iterations) if iterations else 0,
        "llm_calls_avg": round(safe_divide(sum(llm_calls), len(llm_calls)), 3),
        "latency_p50_ms": round(median(latencies), 1) if latencies else 0,
        "latency_p95_ms": round(percentile(latencies, 0.95), 1),
        "timeout_count": sum("timeout" in row["prediction"]["stop_reason"] for row in rows),
        "error_count": sum(row["prediction"]["status"] == "error" for row in rows),
        "error_categories": dict(Counter(row["error_category"] for row in rows if row["error_category"])),
        "factual_precision_llm_judge": NOT_MEASURED,
        "hallucination_rate_llm_judge": NOT_MEASURED,
    }
