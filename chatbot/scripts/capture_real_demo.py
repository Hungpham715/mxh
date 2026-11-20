"""Capture a reproducible Aura + Ollama demo trace without exposing credentials."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from graphrag.api import create_app
from graphrag.settings import Settings

CASES = [
    {
        "case_id": "direct_1hop",
        "kind": "direct",
        "question": "Xipeng Qiu có những bài báo nào?",
        "expected": "author-to-paper facts with paper citations",
    },
    {
        "case_id": "author_path_2hop",
        "kind": "multi_hop",
        "question": "Đường kết nối đồng tác giả giữa Xipeng Qiu và Tao Gui là gì?",
        "expected": "2-hop author path with evidence for each collaboration edge",
    },
    {
        "case_id": "multi_query_profile",
        "kind": "multi_query",
        "question": "Liệt kê các bài báo của Xipeng Qiu, đồng thời cho biết affiliations của tác giả.",
        "expected": "successive author_papers and author_affiliations catalog queries",
    },
    {
        "case_id": "coauthor_affiliations",
        "kind": "multi_relation",
        "question": "Cho biết affiliations của coauthors của Xipeng Qiu.",
        "expected": "coauthor and affiliation traversal with evidence papers",
    },
    {
        "case_id": "missing_entity_refusal",
        "kind": "missing_data",
        "question": "Nguyen Van Khong Ton Tai có những bài báo nào?",
        "expected": "explicit not-found or clarification; no invented papers",
    },
]


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _contract_error(case_id: str, payload: dict[str, Any]) -> str | None:
    actions = [step.get("action") for step in payload.get("trace") or []]
    if payload.get("watermark"):
        return "fake watermark present"
    if case_id == "direct_1hop" and actions != ["author_papers"]:
        return f"expected one author_papers query, got {actions}"
    if case_id == "author_path_2hop":
        path_ok = actions == ["author_path"] and payload.get("status") == "answered"
        if not path_ok or len(payload.get("sources", [])) < 2:
            return "expected an answered author_path with evidence for multiple hops"
    if case_id == "multi_query_profile" and actions[:2] != ["author_papers", "author_affiliations"]:
        return f"expected successive author_papers and author_affiliations queries, got {actions}"
    if case_id == "coauthor_affiliations" and actions != ["coauthor_affiliations"]:
        return f"expected one coauthor_affiliations query, got {actions}"
    if case_id == "missing_entity_refusal":
        clean_refusal = (
            payload.get("status") == "not_found"
            and payload.get("facts_count") == 0
            and not payload.get("sources")
        )
        if not clean_refusal:
            return "missing entity case did not refuse cleanly"
    return None


def verify_existing(output_dir: Path) -> int:
    """Re-check a saved trace without contacting Aura or Ollama."""
    trace_path = output_dir / "real_trace.jsonl"
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line]
    for record in records:
        contract_error = _contract_error(record["case_id"], record["response"])
        record["contract_pass"] = contract_error is None
        record["contract_error"] = contract_error
    with open(trace_path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["contract_pass"] = all(record["contract_pass"] for record in records)
    summary["contract_errors"] = {
        record["case_id"]: record["contract_error"]
        for record in records
        if record["contract_error"] is not None
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["contract_pass"] else 1


async def capture(output_dir: Path, case_ids: set[str] | None = None) -> int:
    settings = Settings.from_env()
    if settings.app_mode != "real" or settings.graph_provider != "neo4j" or settings.llm_provider != "ollama":
        raise RuntimeError("capture requires APP_MODE=real, GRAPH_PROVIDER=neo4j, LLM_PROVIDER=ollama")

    app = create_app(settings)
    records: list[dict[str, Any]] = []
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as client:
            health = (await client.get("/api/health")).json()
            if health.get("status") != "ok":
                raise RuntimeError(f"real providers not ready: {health}")
            selected_cases = [case for case in CASES if not case_ids or case["case_id"] in case_ids]
            if not selected_cases:
                raise RuntimeError("no matching demo cases")
            for case in selected_cases:
                started = time.perf_counter()
                response = await client.post("/api/chat", json={"question": case["question"], "debug": True})
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                payload = response.json()
                if response.status_code != 200 or payload.get("watermark"):
                    raise RuntimeError(f"{case['case_id']} did not return a real response")
                contract_error = _contract_error(case["case_id"], payload)
                records.append(
                    {
                        **case,
                        "http_status": response.status_code,
                        "elapsed_ms": elapsed_ms,
                        "contract_pass": contract_error is None,
                        "contract_error": contract_error,
                        "response": payload,
                    }
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "real_trace.jsonl"
    with open(trace_path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    latencies = [record["elapsed_ms"] for record in records]
    summary = {
        "schema_version": "real-demo-trace-v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "chat_mode": settings.app_mode,
            "graph_provider": settings.graph_provider,
            "llm_provider": settings.llm_provider,
            "model": settings.ollama_model,
            "scope_id": settings.neo4j_scope_id,
            "credential_values_recorded": False,
        },
        "cases": len(records),
        "contract_pass": all(record["contract_pass"] for record in records),
        "contract_errors": {
            record["case_id"]: record["contract_error"]
            for record in records
            if record["contract_error"] is not None
        },
        "statuses": {record["case_id"]: record["response"].get("status") for record in records},
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "samples": latencies,
        },
        "trace_file": trace_path.name,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["contract_pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("reports/demo"))
    parser.add_argument("--case", action="append", choices=[case["case_id"] for case in CASES])
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args()
    if args.verify_existing:
        return verify_existing(args.out)
    return asyncio.run(capture(args.out, set(args.case or [])))


if __name__ == "__main__":
    raise SystemExit(main())
