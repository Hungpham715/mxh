"""Orchestrate enrichment extraction over the processed snapshot and write data/enriched/.

Outputs (all deterministic given the same inputs and LLM cache):
- entities.jsonl          canonical Method/Dataset/Task nodes with provenance + evidence
- edges_<TYPE>.jsonl      one file per enrichment relation type (v1 naming convention)
- enrichment_stats.json   counts, agreement rates, drop reasons, before/after graph totals
- llm_failures.jsonl      papers where the LLM extractor exhausted its retries (usually empty)
- llm_cache/<paper>.json  raw per-paper LLM results (resume cache; safe to delete to re-run)
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.common import DATA, OUTPUT, PROCESSED, ROOT, log, read_json, read_jsonl, write_json, write_jsonl
from src.enrichment import extract_rules
from src.enrichment.extract_llm import DEFAULT_BASE_URL, DEFAULT_MODEL, extract_paper_llm
from src.enrichment.gazetteer import Gazetteer
from src.enrichment.merge import merge_all
from src.enrichment.schema import ENRICH_REL_TYPES, ENRICH_SCOPE_ID, ENRICH_VERSION


def _before_after(stats: dict[str, Any]) -> dict[str, Any]:
    """Compare graph totals before/after enrichment using the committed v1 analysis output."""
    counts_path = OUTPUT / "analysis" / "graph_counts.json"
    if not counts_path.exists():
        return {"note": "run `cli analyze` first to produce graph_counts.json"}
    before = read_json(counts_path)
    new_nodes = stats["entities_by_type"]
    label_adds = {"Method": new_nodes.get("method", 0), "Dataset": new_nodes.get("dataset", 0),
                  "Task": new_nodes.get("task", 0)}
    after_nodes = dict(before["nodes"])
    after_nodes.update({label: after_nodes.get(label, 0) + n for label, n in label_adds.items()})
    after_rels = dict(before["relationships"])
    for rel_type, n in stats["edges_by_type"].items():
        after_rels[rel_type] = n
    return {
        "scope_note": f"v1 graph ({before.get('total_nodes')} nodes / {before.get('total_relationships')} rels) is untouched; "
                      f"enrichment lives in scope {ENRICH_SCOPE_ID}",
        "before": {"total_nodes": before.get("total_nodes"), "total_relationships": before.get("total_relationships")},
        "added_nodes": label_adds,
        "added_relationships": dict(stats["edges_by_type"]),
        "after_if_imported": {"total_nodes": sum(after_nodes.values()),
                              "total_relationships": sum(after_rels.values())},
    }


def run_enrichment(data_dir: Path = PROCESSED, out: Path | None = None,
                   extractors: tuple[str, ...] = ("rules", "llm"), limit: int | None = None,
                   workers: int = 4, ollama_url: str = DEFAULT_BASE_URL,
                   model: str = DEFAULT_MODEL, num_gpu: int = 0) -> int:
    out = out or (DATA / "enriched")
    out.mkdir(parents=True, exist_ok=True)

    papers = read_jsonl(data_dir / "papers.jsonl")
    papers = sorted(papers, key=lambda p: p["id"])  # deterministic processing order
    if limit is not None:
        papers = papers[:limit]
    log.info("enrichment: %d papers, extractors=%s", len(papers), ",".join(extractors))

    gazetteer = Gazetteer.from_file(ROOT / "configs" / "gazetteer.yaml")
    rules_version = f"rules-{gazetteer.version}"

    rules_results: list[dict[str, Any]] = []
    if "rules" in extractors:
        started = time.perf_counter()
        for paper in papers:
            rules_results.append(extract_rules.extract_paper(paper, gazetteer, rules_version))
        log.info("rules extractor: %d papers in %.1fs", len(papers), time.perf_counter() - started)

    llm_results: list[dict[str, Any]] = []
    if "llm" in extractors:
        cache_dir = out / "llm_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    extract_paper_llm,
                    paper,
                    cache_dir,
                    base_url=ollama_url,
                    model=model,
                    num_gpu=num_gpu,
                ): paper["id"]
                       for paper in papers}
            for future in as_completed(futures):
                llm_results.append(future.result())
                done += 1
                if done % 50 == 0:
                    elapsed = time.perf_counter() - started
                    rate = done / elapsed if elapsed > 0 else 0
                    remaining = (len(papers) - done) / rate if rate > 0 else 0
                    log.info("llm extractor: %d/%d papers (%.1f/s, ETA %.0fs)", done, len(papers), rate, remaining)
        llm_results.sort(key=lambda r: r["paper_id"])
        failures = [r for r in llm_results if r.get("error")]
        if failures:
            write_jsonl(out / "llm_failures.jsonl", failures)
        log.info("llm extractor: %d papers in %.1fs (%d failures)",
                 len(papers), time.perf_counter() - started, len(failures))

    entities, edges_by_type, stats = merge_all(papers, rules_results, llm_results, gazetteer)
    stats["gazetteer_version"] = gazetteer.version
    stats["llm_model"] = model if "llm" in extractors else None
    stats["enrich_version"] = ENRICH_VERSION
    stats["scope_id"] = ENRICH_SCOPE_ID
    stats["before_after"] = _before_after(stats)

    write_jsonl(out / "entities.jsonl", entities)
    for rel_type in ENRICH_REL_TYPES:
        write_jsonl(out / f"edges_{rel_type}.jsonl", edges_by_type[rel_type])
    write_json(out / "enrichment_stats.json", stats)
    log.info("enrichment written to %s: %d entities, %d edges %s",
             out, stats["entities_total"], stats["edges_total"], stats["edges_by_type"])
    return 0
