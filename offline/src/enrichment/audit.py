"""Deterministic non-human source-grounding audit for enrichment edges.

This audit checks provenance and verbatim evidence against the real processed corpus.  It is
not semantic gold and therefore never reports entity/relation precision, recall, or F1.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.common import read_jsonl, write_json
from src.enrichment.schema import ENRICH_REL_SCHEMA

SEED = 20261120


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _sample_by_type(data_dir: Path, per_type: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    selected = []
    for relation_type in ENRICH_REL_SCHEMA:
        path = data_dir / f"edges_{relation_type}.jsonl"
        rows = read_jsonl(path) if path.is_file() else []
        rows = sorted(rows, key=lambda row: (row["from"], row["to"]))
        selected.extend(rng.sample(rows, min(per_type, len(rows))))
    return sorted(selected, key=lambda row: (row["type"], row["from"], row["to"]))


def audit_enrichment(
    data_dir: Path, processed_dir: Path, out_dir: Path, *, per_type: int = 30, seed: int = SEED
) -> dict[str, Any]:
    papers = {row["id"]: row for row in read_jsonl(processed_dir / "papers.jsonl")}
    rows = _sample_by_type(data_dir, per_type, seed)
    audited = []
    for edge in rows:
        evidence_checks = []
        for item in edge.get("evidence", []):
            paper = papers.get(item.get("paper_id"))
            text = str(item.get("evidence_text") or "")
            grounded = bool(paper and text and _normalized(text) in _normalized(paper.get("abstract") or ""))
            evidence_checks.append(
                {
                    "paper_id": item.get("paper_id"),
                    "evidence_text": text,
                    "paper_exists": paper is not None,
                    "verbatim_in_abstract": grounded,
                }
            )
        provenance_complete = all(
            edge.get(key)
            for key in (
                "source_kind",
                "extractors",
                "confidence_band",
                "verification_status",
                "build_version",
            )
        )
        # Edge provenance keeps every supporting paper id while the evidence payload is
        # deliberately capped (MAX_EVIDENCE_PER_EDGE) to keep graph properties bounded.
        # Therefore cited papers must be a non-empty subset of the declared provenance;
        # equality would incorrectly fail popular edges supported by more than the cap.
        declared_papers = set(edge.get("evidence_paper_ids", []))
        cited_papers = {item["paper_id"] for item in evidence_checks if item["paper_id"]}
        evidence_papers_match = bool(cited_papers) and cited_papers.issubset(declared_papers)
        provenance_papers_exist = bool(declared_papers) and declared_papers.issubset(papers)
        schema_valid = edge.get("type") in ENRICH_REL_SCHEMA
        passed = bool(
            evidence_checks
            and all(item["verbatim_in_abstract"] for item in evidence_checks)
            and provenance_complete
            and evidence_papers_match
            and provenance_papers_exist
            and schema_valid
        )
        audited.append(
            {
                "audit_kind": "deterministic_nonhuman_source_grounding",
                "relation_type": edge.get("type"),
                "from": edge.get("from"),
                "to": edge.get("to"),
                "source_kind": edge.get("source_kind"),
                "confidence_band": edge.get("confidence_band"),
                "checks": {
                    "schema_valid": schema_valid,
                    "provenance_complete": provenance_complete,
                    "evidence_papers_match": evidence_papers_match,
                    "provenance_papers_exist": provenance_papers_exist,
                    "all_evidence_verbatim": bool(evidence_checks)
                    and all(item["verbatim_in_abstract"] for item in evidence_checks),
                },
                "evidence": evidence_checks,
                "verdict": "pass" if passed else "fail",
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "audit_rows.jsonl", "w", encoding="utf-8") as handle:
        for row in audited:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    passed = sum(row["verdict"] == "pass" for row in audited)
    summary = {
        "schema_version": "enrichment-source-audit-v1",
        "audit_kind": "deterministic_nonhuman_source_grounding",
        "provenance": {
            "edge_source": str(data_dir),
            "paper_source": str(processed_dir / "papers.jsonl"),
            "seed": seed,
            "sample_per_relation_type": per_type,
            "reviewer": "offline/src/enrichment/audit.py",
            "human_review": False,
        },
        "audited_edges": len(audited),
        "passed_edges": passed,
        "failed_edges": len(audited) - passed,
        "source_grounding_pass_rate": round(passed / len(audited), 4) if audited else None,
        "sampled_by_relation_type": dict(sorted(Counter(row["relation_type"] for row in audited).items())),
        "verdicts_by_source_kind": {
            kind: dict(
                sorted(Counter(row["verdict"] for row in audited if row["source_kind"] == kind).items())
            )
            for kind in sorted({row["source_kind"] for row in audited})
        },
        "claims_not_supported": [
            "This audit does not estimate semantic entity precision, recall, or F1.",
            "This audit does not estimate semantic relation precision, recall, or F1.",
            "Extractor agreement is not independent human gold.",
        ],
        "human_gold_protocol": (
            "Freeze unseen papers, have two independent annotators label spans and relations, "
            "adjudicate disagreements, then compute exact/overlap entity and relation micro/macro P/R/F1."
        ),
    }
    write_json(out_dir / "summary.json", summary)
    return summary
