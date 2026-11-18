"""Evaluate the actual chatbot pipeline (parse -> link -> loop -> answer) on a QA split.

Label tiers are explicit and printed in every report:
- gold:      human/independent reviewed test cases (the only tier valid for gate G7);
- silver:    oracle-validated, not human reviewed (diagnostic benchmark only);
- synthetic: fixture smoke, never a benchmark.

Per-case rows are appended to predictions.jsonl as they finish, so `--resume` continues an
interrupted run without re-asking finished cases. Expected sets come from the snapshot
oracle with the case's own params; predicted sets re-execute the *predicted* params.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import random
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datasets.io import read_models
from datasets.schema import QuestionCase, ReviewStatus
from evaluation.metrics import normalize_text, precision_recall_f1, summarize
from graphrag.factory import build_dependencies
from graphrag.graph.snapshot_graph import SnapshotGraphRepository
from graphrag.llm.prompts import ANSWER_SYSTEM, NEXT_STEP_SYSTEM, PARSE_SYSTEM
from graphrag.models import ChatRequest, QueryAction
from graphrag.settings import Settings

PAGE = 20
ID_PARAMS = ("author_id", "other_author_id", "paper_id", "topic_id", "institution_id")


def expected_route(case: QuestionCase) -> str:
    if case.expected_status == "out_of_scope":
        return "OUT_OF_SCOPE"
    if case.expected_status == "clarify":
        return "CLARIFY"
    return "GRAPH_QA"


def stratified_sample(cases: list[QuestionCase], limit: int, seed: int) -> list[QuestionCase]:
    """Round-robin over (intent, expected_status) strata so small strata are represented."""
    if limit <= 0 or limit >= len(cases):
        return cases
    rng = random.Random(seed)
    strata: dict[str, list[QuestionCase]] = defaultdict(list)
    for case in cases:
        strata[f"{case.expected_query.intent}|{case.expected_status}"].append(case)
    for bucket in strata.values():
        rng.shuffle(bucket)
    chosen: list[QuestionCase] = []
    keys = sorted(strata)
    while len(chosen) < limit and any(strata[key] for key in keys):
        for key in keys:
            if strata[key] and len(chosen) < limit:
                chosen.append(strata[key].pop())
    return sorted(chosen, key=lambda case: case.case_id)


def _names(rows: list[dict[str, Any]], action: QueryAction) -> list[str]:
    names = []
    for row in rows[:PAGE]:
        value = row.get("value") or {}
        if action == QueryAction.NETWORK_TOP:
            names.append(str(value.get("name", "")))
        elif action == QueryAction.COAUTHOR_AFFILIATIONS:
            names.append(str(value.get("coauthor_name", "")))
        else:
            names.append(str(value.get("name") or value.get("title") or ""))
    return [name for name in dict.fromkeys(names) if name]


def _mentioned(name: str, answer: str) -> bool:
    name_norm = normalize_text(name)
    if len(name_norm.split()) > 6:  # long titles: accept the first six words
        name_norm = " ".join(name_norm.split()[:6])
    return name_norm in answer


def score_case(
    case: QuestionCase, prediction: dict[str, Any], oracle: SnapshotGraphRepository
) -> dict[str, Any]:
    route = expected_route(case)
    status = prediction["status"]
    trace = prediction.get("trace") or []
    first = trace[0] if trace else None
    answer_norm = normalize_text(prediction["answer"])
    row: dict[str, Any] = {
        "route_match": prediction.get("route") == route,
        "status_match": status == case.expected_status,
        "parse_valid_json": prediction.get("parse_source") == "llm" if status != "error" else False,
        "refusal_correct": (status == "out_of_scope") if route == "OUT_OF_SCOPE" else None,
        "false_refusal": (status == "out_of_scope") if route != "OUT_OF_SCOPE" else None,
        "clarify_correct": (status == "clarify") if case.expected_status == "clarify" else None,
        "ambiguity_correct": (status == "ambiguous") if case.expected_status == "ambiguous" else None,
        "not_found_correct": (status == "not_found") if case.expected_status == "not_found" else None,
        "intent_match": None,
        "entity_ids_match": None,
        "params_match": None,
        "result_set_f1": None,
        "answer_name_recall": None,
        "count_exact": None,
        "citation_precision": None,
        "citation_urls_valid": None,
        "multi_hop_success": None,
        "complete_flag_honest": None,
    }
    positive = case.expected_status in {"answered", "partial"}
    if positive:
        action = QueryAction(case.expected_query.intent)
        expected_params = case.expected_query.params
        expected_rows = oracle.rows(action, expected_params)
        row["intent_match"] = bool(first) and first["action"] == action.value
        predicted_params = (first or {}).get("params") or {}
        expected_ids = {key: expected_params.get(key) for key in ID_PARAMS if key in expected_params}
        predicted_ids = {key: predicted_params.get(key) for key in ID_PARAMS if key in predicted_params}
        row["entity_ids_match"] = bool(first) and set(expected_ids.values()) == set(predicted_ids.values())
        comparable = {key: value for key, value in expected_params.items() if key != "direction"}
        row["params_match"] = (
            bool(first)
            and row["intent_match"]
            and all(predicted_params.get(key) == value for key, value in comparable.items())
        )
        if first:
            try:
                predicted_rows = oracle.rows(QueryAction(first["action"]), predicted_params)
            except (KeyError, ValueError):
                predicted_rows = []
            row["result_set_f1"] = precision_recall_f1(
                {r["object_id"] for r in predicted_rows[:PAGE]},
                {r["object_id"] for r in expected_rows[:PAGE]},
            )["f1"]
        else:
            row["result_set_f1"] = 0.0
        names = _names(expected_rows, action)[:10]
        if names:
            row["answer_name_recall"] = sum(_mentioned(name, answer_norm) for name in names) / len(names)
        if case.expected_status == "partial":
            total = len(expected_rows)
            row["count_exact"] = (
                prediction.get("total_results") == total and str(total) in prediction["answer"]
            )
            row["complete_flag_honest"] = prediction.get("complete") is False
        else:
            row["complete_flag_honest"] = True
        allowed_papers: set[str] = set()
        for expected_row in expected_rows:
            allowed_papers.update(expected_row.get("paper_ids") or [])
            for source in (expected_row.get("value") or {}).get("sources", []):
                allowed_papers.add(source.get("paper_id"))
        sources = prediction.get("sources") or []
        if sources:
            row["citation_precision"] = sum(src["paper_id"] in allowed_papers for src in sources) / len(
                sources
            )
            row["citation_urls_valid"] = all(
                src["paper_id"] in oracle.papers
                and src["url"] == oracle.papers[src["paper_id"]]["source_url"]
                for src in sources
            )
        if action == QueryAction.AUTHOR_PATH:
            row["multi_hop_success"] = bool(row["params_match"]) and status in {"answered", "partial"}
    row["error_category"] = _error_category(row, route, prediction)
    return row


def _error_category(row: dict[str, Any], route: str, prediction: dict[str, Any]) -> str | None:
    if prediction["status"] == "error":
        return "infrastructure_or_parse"
    if not row["route_match"]:
        return "routing"
    if (
        row["status_match"]
        and row["result_set_f1"] in (None, 1.0)
        and row["citation_precision"] in (None, 1.0)
    ):
        return None
    if row["intent_match"] is False:
        return "intent"
    if row["entity_ids_match"] is False:
        return "entity_linking"
    if row["params_match"] is False or (row["result_set_f1"] is not None and row["result_set_f1"] < 1.0):
        return "query"
    if row["citation_precision"] is not None and row["citation_precision"] < 1.0:
        return "evidence"
    if not row["status_match"]:
        return "status"
    _ = route
    return None


async def evaluate(args) -> dict[str, Any]:
    cases = read_models(args.dataset, QuestionCase)
    tier_checks = {
        "gold": lambda case: case.review_status == ReviewStatus.APPROVED,
        "silver": lambda case: case.review_status in {ReviewStatus.SILVER_VALIDATED, ReviewStatus.APPROVED},
        "synthetic": lambda case: True,
    }
    if not all(tier_checks[args.label_tier](case) for case in cases):
        raise ValueError(f"dataset contains cases that do not qualify for label tier {args.label_tier!r}")
    required_split = "val" if getattr(args, "dev", False) else "test"
    if args.label_tier != "synthetic" and any(case.split != required_split for case in cases):
        raise ValueError(f"this evaluation mode accepts split={required_split!r} cases only")
    burned: set[str] = set()
    for path in args.exclude_from or []:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                burned.add(json.loads(line)["case_id"])
    cases = [case for case in cases if case.case_id not in burned]
    cases = stratified_sample(cases, args.limit, args.seed)

    settings = _settings(args)
    llm, repository, workflow = build_dependencies(settings)
    oracle = SnapshotGraphRepository()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = args.output_dir / "predictions.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if args.resume and predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["case_id"]] = record
    elif predictions_path.exists():
        predictions_path.unlink()

    try:
        with predictions_path.open("a", encoding="utf-8", newline="\n") as handle:
            for index, case in enumerate(cases, start=1):
                if case.case_id in done:
                    continue
                started = time.perf_counter()
                try:
                    response = await asyncio.wait_for(
                        workflow.run(ChatRequest(question=case.question, debug=True)),
                        timeout=settings.request_timeout_seconds,
                    )
                    prediction = response.model_dump(mode="json")
                except TimeoutError:
                    prediction = {
                        "status": "error",
                        "stop_reason": "timeout",
                        "answer": "",
                        "trace": [],
                        "iterations_used": 0,
                        "sources": [],
                    }
                latency_ms = (time.perf_counter() - started) * 1000
                record = {
                    "case_id": case.case_id,
                    "question": case.question,
                    "intent": case.expected_query.intent,
                    "expected_status": case.expected_status,
                    "expected_params": case.expected_query.params,
                    "prediction": prediction,
                    "latency_ms": round(latency_ms, 1),
                    **score_case(case, prediction, oracle),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                done[case.case_id] = record
                if index % 10 == 0:
                    print(f"[{index}/{len(cases)}] last={case.case_id} {latency_ms:.0f}ms", flush=True)
    finally:
        await repository.close()
        await llm.close()

    rows = [done[case.case_id] for case in cases if case.case_id in done]
    banner = {
        "gold": "HELD-OUT HUMAN-REVIEWED EVALUATION",
        "silver": "SILVER BENCHMARK — oracle-validated labels, NOT human gold (diagnostic, not G7)",
        "synthetic": "SYNTHETIC SMOKE ONLY — NOT A BENCHMARK",
    }[args.label_tier]
    if getattr(args, "dev", False):
        banner = "DEV REGRESSION on the validation split — used for tuning, not a reported benchmark"
    prompt_hash = hashlib.sha256((PARSE_SYSTEM + NEXT_STEP_SYSTEM + ANSWER_SYSTEM).encode()).hexdigest()[:16]
    return {
        "banner": banner,
        "label_tier": args.label_tier,
        "provider": settings.llm_provider,
        "model": settings.ollama_model if settings.llm_provider == "ollama" else settings.llm_provider,
        "graph": settings.graph_provider,
        "app_mode": settings.app_mode,
        "variant": "B0_one_step" if args.max_iterations == 1 else "B1_iterative",
        "max_iterations": args.max_iterations,
        "seed": args.seed,
        "dataset": str(args.dataset).replace("\\", "/"),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "excluded_burned_cases": len(burned),
        "sampled_case_ids_sha256": hashlib.sha256("|".join(c.case_id for c in cases).encode()).hexdigest(),
        "graph_snapshot": cases[0].snapshot_version if cases else "empty",
        "prompt_sha256_16": prompt_hash,
        "run_timestamp": datetime.now(UTC).isoformat(),
        "metrics": summarize(rows, args.label_tier),
    }


def _settings(args) -> Settings:
    if args.graph == "fake":
        return Settings(max_iterations=args.max_iterations)
    settings = Settings.from_env()
    if settings.llm_provider != args.provider or settings.graph_provider != args.graph:
        raise ValueError("CLI provider/graph must match the configured environment profile")
    return settings.model_copy(update={"max_iterations": args.max_iterations})


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value", "n", "ci95"])
        for key, value in summary["metrics"].items():
            if isinstance(value, dict) and "value" in value:
                writer.writerow([key, value["value"], value["n"], value.get("ci95")])
            else:
                writer.writerow([key, json.dumps(value, ensure_ascii=False), "", ""])
    lines = [f"# {summary['banner']}", ""]
    for key in ("variant", "model", "graph", "app_mode", "dataset_sha256", "graph_snapshot", "run_timestamp"):
        lines.append(f"- {key}: `{summary[key]}`")
    lines += ["", "| Metric | Value | n | 95% CI |", "|---|---:|---:|---|"]
    for key, value in summary["metrics"].items():
        if isinstance(value, dict) and "value" in value:
            lines.append(f"| {key} | {value['value']} | {value['n']} | {value.get('ci95') or ''} |")
        else:
            lines.append(f"| {key} | {value} | | |")
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["fake", "ollama", "hf_cpu"], required=True)
    parser.add_argument("--graph", choices=["fake", "neo4j", "snapshot"], required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--label-tier", choices=["gold", "silver", "synthetic"], required=True)
    parser.add_argument("--max-iterations", type=int, choices=[1, 5], default=5)
    parser.add_argument("--limit", type=int, default=0, help="stratified sample size (0 = all)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dev", action="store_true", help="validation split; allowed for tuning")
    parser.add_argument(
        "--exclude-from",
        type=Path,
        action="append",
        help="predictions.jsonl of an earlier run whose cases were used for tuning (never reused)",
    )
    args = parser.parse_args()
    summary = asyncio.run(evaluate(args))
    write_report(args.output_dir, summary)
    print(summary["banner"])
    print(json.dumps(summary["metrics"], ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
