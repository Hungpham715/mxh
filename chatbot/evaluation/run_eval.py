"""Evaluate the actual chatbot pipeline on reviewed test data or synthetic smoke.

Label levels (printed on every report, never mixed):
- human_gold: every case independently reviewed and APPROVED by a human -> official benchmark.
- nonhuman_source_review: every case source-reviewed by an explicitly identified non-human
  process. This is a development diagnostic, never human or official independent gold.
- silver: every case at least source-validated by the pipeline (Cypher oracle + provenance).
  Requires --allow-silver; the report banner states it is NOT a human-gold benchmark.
- synthetic: fixture smoke only (--synthetic-smoke); never a benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from datasets.io import read_models, write_dicts
from datasets.schema import QuestionCase, ReviewStatus
from evaluation.metrics import summarize, token_f1
from graphrag.factory import build_dependencies
from graphrag.models import ChatRequest, HistoryMessage
from graphrag.settings import Settings

BANNERS = {
    "human_gold": "HELD-OUT HUMAN-REVIEWED EVALUATION",
    "nonhuman_source_review": (
        "NON-HUMAN SOURCE-REVIEWED EVALUATION — NOT HUMAN OR OFFICIAL INDEPENDENT GOLD"
    ),
    "silver": "SILVER (SOURCE-VALIDATED) EVALUATION — NOT HUMAN GOLD",
    "synthetic": "SYNTHETIC SMOKE ONLY — NOT A BENCHMARK",
}


def _label_level(cases: list[QuestionCase], synthetic_smoke: bool) -> str:
    if synthetic_smoke:
        return "synthetic"
    statuses = {case.review_status for case in cases}
    if not statuses:
        raise ValueError("empty dataset")
    if statuses <= {ReviewStatus.APPROVED}:
        invalid = [
            case.case_id
            for case in cases
            if case.reviewer_note.casefold().startswith(("auto:", "silver_auto:", "independent_"))
        ]
        if invalid:
            raise ValueError(
                f"approved rows contain machine-review provenance and cannot be human gold: {invalid[:5]}"
            )
        return "human_gold"
    if statuses <= {ReviewStatus.INDEPENDENT_APPROVED}:
        invalid = [
            case.case_id for case in cases if not case.reviewer_note.casefold().startswith("independent_")
        ]
        if invalid:
            raise ValueError(
                f"independent_approved rows require explicit independent reviewer provenance: {invalid[:5]}"
            )
        return "nonhuman_source_review"
    if statuses <= {
        ReviewStatus.APPROVED,
        ReviewStatus.INDEPENDENT_APPROVED,
        ReviewStatus.SILVER_APPROVED,
    }:
        return "silver"
    raise ValueError(
        f"dataset contains unreviewed cases (statuses: {sorted(str(s) for s in statuses)}); "
        "complete review before evaluation"
    )


def collect_model_identity(settings: Settings) -> str:
    """Record which model actually answered, without contacting any service that needs login."""
    if settings.llm_provider == "fake":
        return "deterministic-fixture-v1"
    if settings.llm_provider == "ollama":
        try:
            response = httpx.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/show",
                json={"name": settings.ollama_model},
                timeout=10,
            )
            response.raise_for_status()
            digest = response.json().get("digest", "")
            if not digest:
                return f"ollama:{settings.ollama_model}"
            return f"ollama:{settings.ollama_model}@{digest[:16]}"
        except (httpx.HTTPError, ValueError):
            return f"ollama:{settings.ollama_model}@digest_unavailable"
    if settings.use_adapter and settings.model_adapter_path:
        adapter_file = Path(settings.model_adapter_path) / "adapter_model.safetensors"
        if adapter_file.exists():
            digest = hashlib.sha256(adapter_file.read_bytes()).hexdigest()[:16]
            return f"hf_cpu:{settings.hf_model_id}+adapter@{digest}"
    return f"hf_cpu:{settings.hf_model_id}"


async def evaluate(args) -> tuple[dict, list[dict]]:
    cases = read_models(args.dataset, QuestionCase)
    label_level = _label_level(cases, args.synthetic_smoke)
    if label_level == "silver" and not args.allow_silver:
        raise ValueError(
            "dataset is silver (auto source-validated), not human gold; "
            "re-run with --allow-silver to accept a non-official benchmark"
        )
    if not args.synthetic_smoke and any(case.split != "test" for case in cases):
        raise ValueError("official evaluation accepts held-out test cases only")

    dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    output_dir = getattr(args, "output_dir", args.dataset.parent / ".eval-checkpoint")
    resume = bool(getattr(args, "resume", False))
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.jsonl"
    checkpoint_meta_path = output_dir / "checkpoint.meta.json"
    rows: list[dict] = []
    if resume:
        if not checkpoint_path.exists() or not checkpoint_meta_path.exists():
            raise ValueError("--resume requires checkpoint.jsonl and checkpoint.meta.json")
        checkpoint_meta = json.loads(checkpoint_meta_path.read_text(encoding="utf-8"))
        if checkpoint_meta.get("dataset_sha256") != dataset_hash:
            raise ValueError("checkpoint dataset hash does not match the requested dataset")
        rows = [json.loads(line) for line in checkpoint_path.read_text().splitlines() if line]
    else:
        checkpoint_path.write_text("", encoding="utf-8")
        checkpoint_meta_path.write_text(
            json.dumps(
                {"dataset": str(args.dataset), "dataset_sha256": dataset_hash},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    completed_ids = {row["case_id"] for row in rows}
    if len(completed_ids) != len(rows):
        raise ValueError("checkpoint contains duplicate case IDs")
    valid_ids = {case.case_id for case in cases}
    unknown_checkpoint_ids = completed_ids - valid_ids
    if unknown_checkpoint_ids:
        raise ValueError(f"checkpoint contains unknown case IDs: {sorted(unknown_checkpoint_ids)[:5]}")

    settings = _settings(args)
    llm, repository, workflow = build_dependencies(settings)
    try:
        for index, case in enumerate(cases, start=1):
            if case.case_id in completed_ids:
                continue
            started = time.perf_counter()
            request = ChatRequest(
                question=case.question,
                history=[HistoryMessage(**message.model_dump()) for message in case.history],
                page_size=int(getattr(args, "page_size", 100)),
                debug=True,
            )
            response = await workflow.run(request)
            latency_ms = (time.perf_counter() - started) * 1000
            prediction = response.model_dump(mode="json")
            predicted_paper_ids = [source["paper_id"] for source in prediction["sources"]]
            expected_answer = case.expected_facts.answer
            trace_actions = [step["action"] for step in (prediction.get("trace") or [])]
            row = {
                "case_id": case.case_id,
                "question": case.question,
                "template_id": case.template_id,
                "prediction": prediction,
                "expected_status": case.expected_status,
                "expected_route": case.expected_route,
                "expected_intent": case.expected_query.intent,
                "expected_entity_mentions": [mention.model_dump() for mention in case.entity_mentions],
                "expected_entity_ids": case.expected_query.entity_ids,
                "expected_paper_ids": case.expected_citations.paper_ids,
                "expected_source_urls": case.expected_citations.source_urls,
                "expected_answer": expected_answer,
                "predicted_paper_ids": predicted_paper_ids,
                "status_match": response.status == case.expected_status,
                "query_template_match": case.expected_query.intent in trace_actions,
                "answer_exact_match": bool(expected_answer)
                and response.answer.strip().casefold() == expected_answer.strip().casefold(),
                "answer_token_f1": (token_f1(response.answer, expected_answer) if expected_answer else None),
                "latency_ms": round(latency_ms, 3),
            }
            rows.append(row)
            with checkpoint_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if index % 10 == 0 or index == len(cases):
                print(f"checkpoint: {len(rows)}/{len(cases)} cases", flush=True)
    finally:
        await repository.close()
        await llm.close()

    metrics = summarize(rows, label_level=label_level)
    development_diagnostic = bool(getattr(args, "development_diagnostic", False))
    banner = BANNERS[label_level]
    if development_diagnostic:
        banner = f"DEVELOPMENT DIAGNOSTIC — PROMPT-EXPOSED, NOT HELD OUT — {banner}"
    summary = {
        "banner": banner,
        "label_level": label_level,
        "development_diagnostic": development_diagnostic,
        "synthetic_smoke_only": bool(args.synthetic_smoke),
        "provider": args.provider,
        "graph": args.graph,
        "max_iterations": args.max_iterations,
        "page_size": int(getattr(args, "page_size", 100)),
        "seed": args.seed,
        "dataset": str(args.dataset),
        "dataset_sha256": dataset_hash,
        "graph_snapshot": cases[0].snapshot_version if cases else "empty",
        "run_timestamp": datetime.now(UTC).isoformat(),
        "model_identity": collect_model_identity(settings),
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
    markdown = [
        f"# {summary['banner']}",
        "",
        f"Model: {summary['model_identity']}",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    markdown.extend(f"| {key} | {value} |" for key, value in summary["metrics"].items())
    (output_dir / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["fake", "ollama", "hf_cpu"], required=True)
    parser.add_argument("--graph", choices=["fake", "neo4j"], required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, choices=[1, 5], default=5)
    parser.add_argument("--page-size", type=int, choices=range(1, 101), default=100)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--synthetic-smoke", action="store_true")
    parser.add_argument(
        "--development-diagnostic",
        action="store_true",
        help="mark a prompt-exposed dataset as development-only rather than held-out evidence",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume from output-dir/checkpoint.jsonl after validating the dataset hash",
    )
    parser.add_argument(
        "--allow-silver",
        action="store_true",
        help="permit evaluation on source-validated silver data (report is labelled non-gold)",
    )
    args = parser.parse_args()
    summary, rows = asyncio.run(evaluate(args))
    write_report(args.output_dir, summary, rows)
    print(summary["banner"])
    print(f"model: {summary['model_identity']}")
    print(f"wrote evaluation artifacts to {args.output_dir}")


if __name__ == "__main__":
    main()
