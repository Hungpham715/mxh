"""Evaluate the actual chatbot pipeline on reviewed test data or synthetic smoke."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from datasets.io import read_models, write_dicts
from datasets.schema import QuestionCase, ReviewStatus
from evaluation.metrics import summarize, token_f1
from graphrag.factory import build_dependencies
from graphrag.models import ChatRequest
from graphrag.settings import Settings


async def evaluate(args) -> tuple[dict, list[dict]]:
    cases = read_models(args.dataset, QuestionCase)
    reviewed_gold = all(case.review_status == ReviewStatus.APPROVED for case in cases)
    if not args.synthetic_smoke:
        if not reviewed_gold:
            raise ValueError("official evaluation requires every case to be human-approved")
        if any(case.split != "test" for case in cases):
            raise ValueError("official evaluation accepts held-out test cases only")

    settings = _settings(args)
    llm, repository, workflow = build_dependencies(settings)
    rows: list[dict] = []
    try:
        for case in cases:
            started = time.perf_counter()
            response = await workflow.run(ChatRequest(question=case.question, debug=True))
            latency_ms = (time.perf_counter() - started) * 1000
            prediction = response.model_dump(mode="json")
            predicted_paper_ids = [source["paper_id"] for source in prediction["sources"]]
            expected_answer = case.expected_facts.answer
            trace_actions = [step["action"] for step in (prediction.get("trace") or [])]
            rows.append(
                {
                    "case_id": case.case_id,
                    "question": case.question,
                    "prediction": prediction,
                    "expected_status": case.expected_status,
                    "status_match": response.status == case.expected_status,
                    "expected_entity_ids": case.expected_query.entity_ids,
                    "expected_paper_ids": case.expected_citations.paper_ids,
                    "predicted_paper_ids": predicted_paper_ids,
                    "query_template_match": case.expected_query.intent in trace_actions,
                    "answer_exact_match": bool(expected_answer)
                    and response.answer.strip().casefold() == expected_answer.strip().casefold(),
                    "answer_token_f1": (
                        token_f1(response.answer, expected_answer) if expected_answer else None
                    ),
                    "latency_ms": round(latency_ms, 3),
                }
            )
    finally:
        await repository.close()
        await llm.close()

    metrics = summarize(rows, reviewed_gold=reviewed_gold)
    dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    summary = {
        "banner": (
            "SYNTHETIC SMOKE ONLY — NOT A BENCHMARK"
            if args.synthetic_smoke
            else "HELD-OUT HUMAN-REVIEWED EVALUATION"
        ),
        "synthetic_smoke_only": bool(args.synthetic_smoke),
        "provider": args.provider,
        "graph": args.graph,
        "max_iterations": args.max_iterations,
        "seed": args.seed,
        "dataset": str(args.dataset),
        "dataset_sha256": dataset_hash,
        "graph_snapshot": cases[0].snapshot_version if cases else "empty",
        "run_timestamp": datetime.now(UTC).isoformat(),
        "model_hash": "deterministic-fixture-v1" if args.provider == "fake" else "not_collected",
        "metrics": metrics,
    }
    return summary, rows


def _settings(args) -> Settings:
    if args.provider == "fake" and args.graph == "fake":
        return Settings(max_iterations=args.max_iterations)
    settings = Settings.from_env()
    if settings.llm_provider != args.provider or settings.graph_provider != args.graph:
        raise ValueError("CLI provider/graph must match the configured real environment profile")
    return settings.model_copy(update={"max_iterations": args.max_iterations})


def write_report(output_dir: Path, summary: dict, rows: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_dicts(output_dir / "predictions.jsonl", rows)
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for key, value in summary["metrics"].items():
            writer.writerow([key, value])
    markdown = [f"# {summary['banner']}", "", "| Metric | Value |", "|---|---:|"]
    markdown.extend(f"| {key} | {value} |" for key, value in summary["metrics"].items())
    (output_dir / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["fake", "ollama", "hf_cpu"], required=True)
    parser.add_argument("--graph", choices=["fake", "neo4j"], required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, choices=[1, 5], default=5)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--synthetic-smoke", action="store_true")
    args = parser.parse_args()
    summary, rows = asyncio.run(evaluate(args))
    write_report(args.output_dir, summary, rows)
    print(summary["banner"])
    print(f"wrote evaluation artifacts to {args.output_dir}")


if __name__ == "__main__":
    main()
