"""Export normalised entities + topic labels into the 8 JSONL contract files and manifest.json."""
from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any

from src.common import BUILD_VERSION, PROCESSED, REJECTED, SCOPE_ID, log, sha256_file, write_json, write_jsonl
from src.data.contracts import FILES, SCHEMA_VERSION
from src.data.topics import TopicClassifier


def label_topics(papers: list[dict[str, Any]], clf: TopicClassifier) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, audit = [], []
    for p in sorted(papers, key=lambda r: r["id"]):
        res = clf.classify(p["title"], p.get("abstract"))
        for t in res.topics:
            rows.append({"paper_id": p["id"], "topic_id": t["topic_id"], "rule_id": t["rule_id"],
                         "evidence_span": t["evidence_span"], "confidence_band": t["confidence_band"]})
        audit.append({"paper_id": p["id"], "status": res.status, "scores": res.scores,
                      "assigned": [t["topic_id"] for t in res.topics], "has_abstract": bool(p.get("abstract"))})
    return rows, audit


SORT_KEYS = {
    "papers.jsonl": ("id",), "authors.jsonl": ("id",), "institutions.jsonl": ("id",), "venues.jsonl": ("id",),
    "paper_authors.jsonl": ("paper_id", "position"), "affiliations.jsonl": ("paper_id", "author_id", "institution_id"),
    "citations.jsonl": ("citing_paper_id", "cited_paper_id"), "paper_topics.jsonl": ("paper_id", "topic_id"),
}


def export(entities: dict[str, list[dict[str, Any]]], clf: TopicClassifier, input_counts: dict[str, Any],
           source_versions: dict[str, Any], extra_stats: dict[str, Any], out_dir: Path = PROCESSED) -> dict[str, Any]:
    topic_rows, audit = label_topics(entities["papers"], clf)
    write_jsonl(REJECTED.parent / "derived" / "topic_audit.jsonl", audit)
    tables = {
        "papers.jsonl": entities["papers"], "authors.jsonl": entities["authors"],
        "institutions.jsonl": entities["institutions"], "venues.jsonl": entities["venues"],
        "paper_authors.jsonl": entities["paper_authors"], "affiliations.jsonl": entities["affiliations"],
        "citations.jsonl": entities["citations"], "paper_topics.jsonl": topic_rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()  # manifest is written last; absence signals an incomplete export
    counts, checksums = {}, {}
    for fname in FILES:
        rows = sorted(tables[fname], key=lambda r: tuple(str(r.get(k)) if not isinstance(r.get(k), int)
                                                         else f"{r.get(k):08d}" for k in SORT_KEYS[fname]))
        counts[fname] = write_jsonl(out_dir / fname, rows)
        checksums[fname] = sha256_file(out_dir / fname)
    status = Counter(a["status"] for a in audit)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scope_id": SCOPE_ID,
        "build_version": BUILD_VERSION,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_versions": source_versions,
        "input_counts": input_counts,
        "output_counts": counts,
        "unmatched_openalex_count": sum(1 for p in entities["papers"] if not p["openalex_id"]),
        "topic_rule_version": clf.rule_version,
        "topic_status_counts": dict(status),
        "normalize_stats": extra_stats,
        "checksums": checksums,
    }
    write_json(manifest_path, manifest)
    log.info("export done: %s", counts)
    return manifest
