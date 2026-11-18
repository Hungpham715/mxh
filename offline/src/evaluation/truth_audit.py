"""G3 truth audit: probability sample over all 10 relation types + conservative scorer.

Design (fixed in code BEFORE any label is seen):
- Sampling frame: every edge of the snapshot, re-derived deterministically, one stratum per type.
- Allocation: n_h = min(N_h, max(MIN_PER_TYPE, round(TARGET_TOTAL * N_h / N))). Small strata
  (e.g. CITES) become a census.
- Selection: simple random sample without replacement inside each stratum, seed SEED.
- Review sheet is *blind*: no automated scores or predictions are included.

Scoring (`score`): only rows with a non-empty human `reviewer` and a label in
{correct, incorrect, unverifiable} count. `unverifiable` is treated as NOT confirmed
(conservative). The overall estimate is population weighted with a Wilson CI on the
effective sample size (see kg_accuracy.stratified_estimate). PASS requires the point
estimate AND the lower 95% bound to exceed 0.90, every stratum labelled, and at least
one reviewer that is not an automated identity.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common import PROCESSED
from src.data.contracts import load_dataset
from src.evaluation.kg_accuracy import Stratum, proportion_ci, stratified_estimate
from src.graph.derive import REL_TYPES, derive_edges

SEED = 20261118
TARGET_TOTAL = 500
MIN_PER_TYPE = 40
THRESHOLD = 0.90
LABELS = {"correct", "incorrect", "unverifiable"}
AUTOMATED_REVIEWERS = {"auto", "automated", "llm", "qwen", "pipeline", "agent", "claude", "codex", "silver_auto"}

SHEET_FIELDS = [
    "review_id", "edge_type", "source_id", "source_name", "target_id", "target_name",
    "evidence_paper_ids", "evidence_titles", "evidence_urls", "years", "claim",
    "label", "error_type", "reviewer", "reviewed_at_utc", "evidence_url_checked", "note",
]

CLAIMS = {
    "FIRST_AUTHOR_OF": "{s} is the FIRST listed author of paper {t}.",
    "OTHER_AUTHOR_OF": "{s} is a listed (non-first) author of paper {t}.",
    "COAUTHORED_WITH": "{s} and {t} are both listed authors on every evidence paper.",
    "AFFILIATED_WITH": "On every evidence paper, {s} is printed with affiliation {t} (paper-level, not current job).",
    "APPEARS_IN": "Paper {s} was published in venue {t}.",
    "HAS_TOPIC": "Paper {s} is about topic {t} (title/abstract supports the topic).",
    "CITES": "Paper {s} cites paper {t} in its reference list.",
    "ORG_COAUTHORED_WITH": "Institutions {s} and {t} both appear as author affiliations on every evidence paper.",
    "RESEARCHES": "Author {s} wrote >=2 evidence papers that are each about topic {t}.",
    "ACTIVE_IN": "Institution {s} has affiliated authors on >=2 evidence papers each about topic {t}.",
}


def allocation(populations: dict[str, int]) -> dict[str, int]:
    total = sum(populations.values())
    alloc = {}
    for etype, size in populations.items():
        proportional = round(TARGET_TOTAL * size / total) if total else 0
        alloc[etype] = min(size, max(MIN_PER_TYPE, proportional))
    return alloc


def _names(rows: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for table, field in (("papers.jsonl", "title"), ("authors.jsonl", "name"),
                         ("institutions.jsonl", "name"), ("venues.jsonl", "name")):
        for record in rows[table]:
            names[record["id"]] = record.get(field) or record["id"]
    return names


def build_sample(data_dir: Path, out_dir: Path) -> int:
    rows = load_dataset(data_dir)
    edges = derive_edges(rows, out_dir / "_rejected_tmp")
    papers = {paper["id"]: paper for paper in rows["papers.jsonl"]}
    names = _names(rows)
    populations = {etype: len(edges[etype]) for etype in REL_TYPES}
    alloc = allocation(populations)

    rng = random.Random(SEED)
    sheet: list[dict[str, Any]] = []
    frame_digest = hashlib.sha256()
    for etype in REL_TYPES:
        frame = sorted(edges[etype], key=lambda e: (e["from"], e["to"]))
        for edge in frame:
            frame_digest.update(f"{etype}|{edge['from']}|{edge['to']}\n".encode())
        chosen = sorted(rng.sample(range(len(frame)), alloc[etype]))
        for position, index in enumerate(chosen, start=1):
            edge = frame[index]
            evidence = edge["evidence_paper_ids"]
            src_name = names.get(edge["from"], edge["from"])
            dst_name = names.get(edge["to"], edge["to"])
            sheet.append({
                "review_id": f"G3-{etype}-{position:03d}",
                "edge_type": etype,
                "source_id": edge["from"],
                "source_name": src_name,
                "target_id": edge["to"],
                "target_name": dst_name,
                "evidence_paper_ids": " | ".join(evidence),
                "evidence_titles": " | ".join(papers[pid]["title"] for pid in evidence if pid in papers),
                "evidence_urls": " | ".join(papers[pid]["source_url"] for pid in evidence if pid in papers),
                "years": " | ".join(str(year) for year in edge.get("years", [])),
                "claim": CLAIMS[etype].format(s=src_name, t=dst_name),
                "label": "", "error_type": "", "reviewer": "", "reviewed_at_utc": "",
                "evidence_url_checked": "", "note": "",
            })
    for leftover in (out_dir / "_rejected_tmp").glob("*"):
        leftover.unlink()
    if (out_dir / "_rejected_tmp").exists():
        (out_dir / "_rejected_tmp").rmdir()

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / "g3_review_sheet_blind.csv"
    with sheet_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sheet)

    # Power check: if every stratum were 95% correct, would the lower bound clear 0.90?
    power_strata = [Stratum(correct=round(0.95 * alloc[t]), n=alloc[t], population=populations[t])
                    for t in REL_TYPES if alloc[t]]
    power = stratified_estimate(power_strata)
    meta = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "target_total": TARGET_TOTAL,
        "min_per_type": MIN_PER_TYPE,
        "populations": populations,
        "allocation": alloc,
        "sample_size": len(sheet),
        "frame_sha256": frame_digest.hexdigest(),
        "sheet_sha256": hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
        "power_check_if_all_strata_95pct": {"estimate": power["estimate"], "ci": power["ci"]},
        "rule": "design fixed before labels; do not reseed or resample after seeing labels",
    }
    (out_dir / "g3_sampling_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("sample_size", "allocation", "power_check_if_all_strata_95pct")}))
    return 0


def score(sheet_path: Path, meta_path: Path, out_path: Path) -> int:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    per_type: dict[str, Counter[str]] = {t: Counter() for t in REL_TYPES}
    reviewers: Counter[str] = Counter()
    rejected_automated = 0
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        reviewer = (row.get("reviewer") or "").strip()
        if label not in LABELS or not reviewer:
            per_type[row["edge_type"]]["unlabelled"] += 1
            continue
        if reviewer.casefold() in AUTOMATED_REVIEWERS:
            rejected_automated += 1
            per_type[row["edge_type"]]["unlabelled"] += 1
            continue
        reviewers[reviewer] += 1
        per_type[row["edge_type"]][label] += 1

    strata = []
    per_type_report = {}
    for etype in REL_TYPES:
        counts = per_type[etype]
        labelled = counts["correct"] + counts["incorrect"] + counts["unverifiable"]
        lower, upper = proportion_ci(counts["correct"], labelled) if labelled else (None, None)
        per_type_report[etype] = {
            "population": meta["populations"][etype],
            "sampled": meta["allocation"][etype],
            "labelled": labelled,
            "unlabelled": counts["unlabelled"],
            "correct": counts["correct"],
            "incorrect": counts["incorrect"],
            "unverifiable": counts["unverifiable"],
            "conservative_precision": counts["correct"] / labelled if labelled else None,
            "wilson_95": [lower, upper],
        }
        if labelled:
            strata.append(Stratum(correct=counts["correct"], n=labelled, population=meta["populations"][etype]))

    overall = stratified_estimate(strata) if strata else {"estimate": None, "ci": None}
    all_types_labelled = all(per_type_report[t]["labelled"] > 0 for t in REL_TYPES)
    fully_labelled = all(per_type_report[t]["unlabelled"] == 0 for t in REL_TYPES)
    estimate = overall.get("estimate")
    ci = overall.get("ci")
    passed = bool(
        reviewers and all_types_labelled and fully_labelled and estimate is not None and ci is not None
        and estimate > THRESHOLD and ci[0] > THRESHOLD
    )
    if not reviewers:
        verdict = "BLOCKED_NO_INDEPENDENT_LABELS"
    elif passed:
        verdict = "PASS"
    else:
        verdict = "FAIL_OR_INCOMPLETE"
    report = {
        "scored_at_utc": datetime.now(UTC).isoformat(),
        "sheet_sha256": hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
        "unverifiable_treatment": "counted as NOT correct (conservative)",
        "reviewers": dict(reviewers),
        "rows_rejected_automated_reviewer": rejected_automated,
        "per_type": per_type_report,
        "overall_weighted_estimate": estimate,
        "overall_ci95": ci,
        "threshold": THRESHOLD,
        "verdict": verdict,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "estimate": estimate, "ci95": ci, "reviewers": dict(reviewers)}))
    return 0 if verdict == "PASS" else 6


def default_paths(root: Path) -> dict[str, Path]:
    base = root / "reports" / "graph_audit"
    return {
        "data": PROCESSED,
        "out": base,
        "sheet": base / "g3_review_sheet_blind.csv",
        "meta": base / "g3_sampling_meta.json",
        "score": base / "g3_truth_scores.json",
    }
