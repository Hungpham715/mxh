"""Precision per type, macro, graph-count-weighted micro, Wilson 95% CI."""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.common import EVAL, log, write_json
from src.graph.derive import REL_TYPES


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def score_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "correct": 0, "incorrect": 0, "unverifiable": 0,
                                                         "graph_count": 0, "errors": defaultdict(int)})
    for r in rows:
        t = r["type"]
        lab = (r.get("label") or "").strip().lower()
        if lab not in ("correct", "incorrect", "unverifiable"):
            continue
        d = by[t]
        d["n"] += 1
        d[lab] += 1
        d["graph_count"] = int(r.get("graph_count_type") or 0)
        if lab != "correct":
            d["errors"][(r.get("error_reason") or lab).split(":")[0]] += 1
    per_type = {}
    for t in REL_TYPES:
        d = by.get(t)
        if not d or d["n"] == 0:
            per_type[t] = {"n": 0, "precision": None}
            continue
        p = d["correct"] / d["n"]   # unverifiable counted as not-correct (conservative)
        lo, hi = wilson(d["correct"], d["n"])
        per_type[t] = {"n": d["n"], "correct": d["correct"], "incorrect": d["incorrect"],
                       "unverifiable": d["unverifiable"], "graph_count": d["graph_count"],
                       "precision": round(p, 4), "wilson95": [round(lo, 4), round(hi, 4)],
                       "errors": dict(d["errors"]),
                       "precision_excluding_unverifiable": round(d["correct"] / (d["n"] - d["unverifiable"]), 4)
                       if d["n"] > d["unverifiable"] else None}
    scored = {t: v for t, v in per_type.items() if v["n"]}
    macro = sum(v["precision"] for v in scored.values()) / len(scored) if scored else None
    W = sum(v["graph_count"] for v in scored.values())
    micro = sum(v["graph_count"] * v["precision"] for v in scored.values()) / W if W else None
    # CI for the stratified (weighted) estimator: normal approx using per-stratum variance with FPC
    var = 0.0
    for v in scored.values():
        w = v["graph_count"] / W
        n, N, p = v["n"], v["graph_count"], v["precision"]
        fpc = (N - n) / (N - 1) if N > 1 else 0.0
        var += (w ** 2) * (p * (1 - p) / n) * fpc
    se = math.sqrt(var)
    return {"per_type": per_type, "macro_precision": round(macro, 4) if macro is not None else None,
            "micro_precision_weighted": round(micro, 4) if micro is not None else None,
            "micro_ci95_stratified_normal": [round(max(0, micro - 1.96 * se), 4), round(min(1, micro + 1.96 * se), 4)]
            if micro is not None else None,
            "types_meeting_0.90_point_estimate": sum(1 for v in scored.values() if v["precision"] >= 0.9),
            "types_with_wilson_lower_ge_0.90": sum(1 for v in scored.values() if v["wilson95"][0] >= 0.9),
            "n_total": sum(v["n"] for v in scored.values())}


def run_score(labels: Path, auto_path: Path | None = None, tag: str = "") -> int:
    out: dict[str, Any] = {}
    if labels.exists():
        with open(labels, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        human = [r for r in rows if (r.get("label_origin") or "human") == "human" and r.get("label")]
        if human:
            out["human"] = {"label_origin": "human", **score_rows(human)}
    else:
        log.warning("%s not found: no human labels -> human precision NOT MEASURED", labels)
    auto_path = auto_path or (EVAL / f"automated_labels{tag}.csv")
    if auto_path.exists():
        with open(auto_path, encoding="utf-8") as fh:
            out["automated_preliminary"] = {
                "label_origin": "automated_preliminary",
                "disclaimer": "Automated re-verification against cached raw source records; NOT independent human annotation.",
                **score_rows(list(csv.DictReader(fh)))}
    out["status"] = "human_scored" if "human" in out else "PENDING_HUMAN_REVIEW (automated preliminary only)"
    write_json(EVAL / f"scores{tag}.json", out)
    a = out.get("automated_preliminary", {})
    print(f"status: {out['status']}")
    if a:
        print(f"automated micro (weighted) = {a['micro_precision_weighted']}  CI {a['micro_ci95_stratified_normal']}  "
              f"macro = {a['macro_precision']}  n = {a['n_total']}")
        for t, v in a["per_type"].items():
            print(f"  {t:22s} n={v['n']:3d} p={v.get('precision')} wilson={v.get('wilson95')} unverif={v.get('unverifiable', 0)}")
    return 0
