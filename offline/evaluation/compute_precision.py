"""Compute precision from MANUAL review sheets for AFFILIATED_WITH, ORG_COAUTHORED_WITH, ACTIVE_IN.

Usage:
    uv run python evaluation/compute_precision.py --round 1
    uv run python evaluation/compute_precision.py --round 2          # pools round 1 + round 2 for round-2 types
    uv run python evaluation/compute_precision.py --round 1 --sheet1 path.csv --overlap path.csv --out-dir dir

Stops with exit code 2 and the offending rows if any label is missing/invalid. Never fills labels itself.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Allow this standalone script (run as `python evaluation/compute_precision.py`) to import the
# shared, vendored KG-accuracy estimators from the `src` package at the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.kg_accuracy import WILSON, proportion_ci  # noqa: E402

EVAL = Path(__file__).resolve().parent
TYPES = ("AFFILIATED_WITH", "ORG_COAUTHORED_WITH", "ACTIVE_IN")
LABELS = ("correct", "incorrect", "unverifiable")
ERROR_TYPES = ("wrong_org", "wrong_author", "entity_merge_error", "evidence_mismatch", "other")
PASS_LOWER = 0.90
FAIL_POINT = 0.85

SUGGESTIONS = {
    "wrong_org": "OpenAlex institution assignment: require agreement with the ACL-printed / PDF affiliation, drop "
                 "OpenAlex-only affiliations or extract affiliations from the PDF header (e.g. GROBID).",
    "wrong_author": "Author alignment by position: add stricter name matching, re-check papers whose source and "
                    "OpenAlex author lists differ, keep mismatches as source_only.",
    "entity_merge_error": "Institution/author entity resolution: map OpenAlex child/parent institutions via ROR "
                          "relationships; do not merge same-name authors; review institution lineage.",
    "evidence_mismatch": "Derivation rule: ORG_COAUTHORED_WITH must require two different authors per institution; "
                         "ACTIVE_IN must recount papers after topic/affiliation fixes; revisit the topic rules.",
    "other": "Read the reviewer notes for this type and classify the failure before changing the pipeline.",
}


# ------------------------------------------------------------------------------------------------ io
class LabelError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s)")
        self.problems = problems


def read_sheet(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes().decode("utf-8-sig")
    first = raw.splitlines()[0] if raw else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    rows = list(csv.DictReader(raw.splitlines(keepends=True), delimiter=delim))
    for r in rows:
        for k in list(r):
            r[k] = (r[k] or "").strip()
    return rows


def norm(v: str) -> str:
    return (v or "").strip().lower()


def validate(rows: list[dict[str, str]], name: str, require_adjudication: bool = False) -> list[str]:
    probs = []
    need = {"review_id", "edge_type", "label", "error_type", "reviewer", "note"}
    if rows and need - set(rows[0]):
        return [f"{name}: missing columns {sorted(need - set(rows[0]))}"]
    for i, r in enumerate(rows, start=2):           # line 1 is the header
        rid = r.get("review_id") or f"line {i}"
        lab, et = norm(r["label"]), norm(r["error_type"])
        where = f"{name} line {i} ({rid})"
        if r["edge_type"] not in TYPES:
            probs.append(f"{where}: unknown edge_type {r['edge_type']!r}")
        if not lab:
            probs.append(f"{where}: label is empty")
        elif lab not in LABELS:
            probs.append(f"{where}: invalid label {r['label']!r} (allowed: {', '.join(LABELS)})")
        if not r["reviewer"]:
            probs.append(f"{where}: reviewer is empty")
        if lab == "incorrect" and et not in ERROR_TYPES:
            probs.append(f"{where}: label=incorrect needs error_type in {ERROR_TYPES} (got {r['error_type']!r})")
        if lab in ("correct", "unverifiable") and et:
            probs.append(f"{where}: error_type must be empty when label={lab}")
        if lab == "unverifiable" and not r["note"]:
            probs.append(f"{where}: label=unverifiable requires a note")
        adj = norm(r.get("adjudicated_label", ""))
        if adj and adj not in LABELS:
            probs.append(f"{where}: invalid adjudicated_label {r['adjudicated_label']!r}")
    ids = [r.get("review_id") for r in rows]
    for k, n in Counter(ids).items():
        if n > 1:
            probs.append(f"{name}: duplicate review_id {k}")
    return probs


# ------------------------------------------------------------------------------------------------ statistics
def wilson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson 95% CI from the shared reliable-kg-estimation estimators (exact bounds near 0/n)."""
    return proportion_ci(k, n, alpha=alpha, method=WILSON)


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    if not a or len(a) != len(b):
        return None
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return 1.0 if po == 1 else None
    return (po - pe) / (1 - pe)


def final_label(r: dict[str, str]) -> str:
    return norm(r.get("adjudicated_label", "")) or norm(r["label"])


def type_stats(rows: list[dict[str, str]]) -> dict[str, Any]:
    labs = Counter(final_label(r) for r in rows)
    c, i, u = labs["correct"], labs["incorrect"], labs["unverifiable"]
    n = c + i + u
    lo_a, hi_a = wilson(c, c + i)
    lo_b, hi_b = wilson(c, n)
    errs = Counter(norm(r["error_type"]) for r in rows if final_label(r) == "incorrect")
    return {"n": n, "correct": c, "incorrect": i, "unverifiable": u,
            "a_exclude_unverifiable": {"n": c + i, "precision": c / (c + i) if c + i else None, "wilson95": [lo_a, hi_a]},
            "b_unverifiable_as_wrong": {"n": n, "precision": c / n if n else None, "wilson95": [lo_b, hi_b]},
            "error_types": dict(errs)}


def decide(st: dict[str, Any], round_no: int) -> tuple[str, str]:
    """Decision uses the conservative variant (b): unverifiable counted as wrong."""
    b = st["b_unverifiable_as_wrong"]
    if not b["n"]:
        return "NO_DATA", "no labelled rows"
    p, lo = b["precision"], b["wilson95"][0]
    if lo >= PASS_LOWER:
        return "PASS", f"Wilson lower bound {lo:.3f} >= {PASS_LOWER}"
    if p < FAIL_POINT:
        return "FAIL", f"sample precision {p:.3f} < {FAIL_POINT}"
    if round_no == 1:
        return "NEEDS_ROUND_2", f"precision {p:.3f} >= {FAIL_POINT} but lower bound {lo:.3f} < {PASS_LOWER}"
    return ("NOT_ESTABLISHED", f"after round 2: sample precision {p:.3f}, Wilson lower bound {lo:.3f} < {PASS_LOWER}; "
            ">=90% cannot be claimed")


def kappa_report(main: list[dict[str, str]], overlap: list[dict[str, str]] | None) -> dict[str, Any]:
    if not overlap:
        return {"status": "not_computed", "reason": "only one reviewer (no second-reviewer overlap sheet with labels)"}
    m = {r["review_id"]: r for r in main if r.get("is_overlap") == "1"}
    pairs = [(m[o["review_id"]], o) for o in overlap if o["review_id"] in m]
    if not pairs:
        return {"status": "not_computed", "reason": "overlap sheet has no review_id in common with the main sheet"}
    same = [(a, b) for a, b in pairs if a["reviewer"].lower() == b["reviewer"].lower()]
    if same:
        return {"status": "not_computed", "reason": f"{len(same)} overlap row(s) labelled by the same reviewer in both sheets "
                                                    "- kappa needs two different reviewers"}
    out: dict[str, Any] = {"status": "computed", "n_pairs": len(pairs),
                           "reviewers": sorted({a["reviewer"] for a, _ in pairs} | {b["reviewer"] for _, b in pairs}),
                           "note": "computed on labels BEFORE adjudication"}
    a, b = [norm(x["label"]) for x, _ in pairs], [norm(y["label"]) for _, y in pairs]
    out["kappa_overall"] = cohen_kappa(a, b)
    out["raw_agreement"] = sum(x == y for x, y in zip(a, b)) / len(a)
    out["by_type"] = {}
    for t in TYPES:
        sub = [(norm(x["label"]), norm(y["label"])) for x, y in pairs if x["edge_type"] == t]
        if sub:
            out["by_type"][t] = {"n": len(sub), "kappa": cohen_kappa([s[0] for s in sub], [s[1] for s in sub]),
                                 "raw_agreement": sum(x == y for x, y in sub) / len(sub)}
    out["disagreements_without_adjudication"] = [x["review_id"] for x, y in pairs
                                                 if norm(x["label"]) != norm(y["label"]) and not x.get("adjudicated_label")]
    return out


# ------------------------------------------------------------------------------------------------ round 2 sheet
def make_round2_sheet(types: list[str], prebuilt: Path, out: Path) -> int:
    if not types:
        return 0
    if out.exists():
        print(f"NOTE: {out} already exists; not overwritten")
        return -1
    raw = prebuilt.read_bytes().decode("utf-8-sig")
    rows = list(csv.DictReader(raw.splitlines(keepends=True)))
    keep = [r for r in rows if r["edge_type"] in types]
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(keep)
    return len(keep)


# ------------------------------------------------------------------------------------------------ main
def fmt(x: float | None) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def run(round_no: int, sheet1: Path, overlap: Path | None, sheet2: Path | None, out_dir: Path,
        prebuilt2: Path, round2_out: Path) -> int:
    rows1 = read_sheet(sheet1)
    probs = validate(rows1, sheet1.name)
    ov = None
    if overlap and overlap.exists():
        ov_rows = read_sheet(overlap)
        filled = [r for r in ov_rows if r.get("label")]
        if filled:                                   # second reviewer started -> must be complete
            probs += validate(ov_rows, overlap.name)
            ov = ov_rows
    rows = list(rows1)
    if round_no == 2:
        if not sheet2 or not sheet2.exists():
            print(f"ERROR: round 2 requested but {sheet2} does not exist")
            return 2
        rows2 = read_sheet(sheet2)
        probs += validate(rows2, sheet2.name)
        rows += rows2
    if probs:
        print("LABELS INCOMPLETE OR INVALID - nothing computed:")
        for p in probs[:200]:
            print("  -", p)
        if len(probs) > 200:
            print(f"  ... and {len(probs) - 200} more")
        return 2

    r2_types = sorted({r["edge_type"] for r in rows if r.get("round") == "2"})
    result: dict[str, Any] = {"round": round_no, "decision_rule": {
        "variant_used_for_decision": "b (unverifiable counted as wrong)",
        "PASS": f"Wilson 95% lower bound >= {PASS_LOWER}", "FAIL": f"sample precision < {FAIL_POINT}",
        "NEEDS_ROUND_2": "otherwise (round 1 only)"}, "types": {}}
    for t in TYPES:
        # round 2 sheet only holds round-2 types, so pooling = all rows of the type across both sheets
        sub = [r for r in rows if r["edge_type"] == t]
        st = type_stats(sub)
        st["rounds_pooled"] = sorted({r.get("round", "1") for r in sub})
        st["decision"], st["reason"] = decide(st, 2 if t in r2_types else 1)
        if st["decision"] == "FAIL":
            st["suggestions"] = [{"error_type": e, "count": n, "suggestion": SUGGESTIONS[e]}
                                 for e, n in Counter(st["error_types"]).most_common()]
        result["types"][t] = st
    result["kappa"] = kappa_report(rows1, ov)
    result["limitations"] = [
        "Two-stage sampling with a data-dependent stop: the reported Wilson intervals do not account for the decision to "
        "continue, so they are somewhat optimistic (slightly too narrow).",
        "Rows are stratified samples (institution frequency x evidence source) drawn with proportional allocation; the "
        "pooled precision is an unweighted sample estimate, close to but not exactly the population precision.",
        "Labels reflect the reviewer's reading of the paper; with one reviewer there is no agreement measure.",
    ]
    if round_no == 1:
        need = [t for t, s in result["types"].items() if s["decision"] == "NEEDS_ROUND_2"]
        result["round2_types"] = need
        n = make_round2_sheet(need, prebuilt2, round2_out)
        result["round2_sheet"] = str(round2_out) if need else None
        result["round2_rows_written"] = n

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"precision_round{round_no}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_markdown(result)
    (out_dir / f"precision_round{round_no}.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def to_markdown(res: dict[str, Any]) -> str:
    L = [f"# Manual precision - round {res['round']}", "",
         "| edge type | n | correct | incorrect | unverifiable | (a) excl. unverifiable [Wilson95] | "
         "(b) unverifiable = wrong [Wilson95] | decision |", "|---|---|---|---|---|---|---|---|"]
    for t, s in res["types"].items():
        a, b = s["a_exclude_unverifiable"], s["b_unverifiable_as_wrong"]
        L.append(f"| {t} | {s['n']} | {s['correct']} | {s['incorrect']} | {s['unverifiable']} | "
                 f"{fmt(a['precision'])} [{fmt(a['wilson95'][0])}, {fmt(a['wilson95'][1])}] | "
                 f"{fmt(b['precision'])} [{fmt(b['wilson95'][0])}, {fmt(b['wilson95'][1])}] | {s['decision']} |")
    L += ["", "Decision rule (variant b): PASS if Wilson lower bound >= 0.90; FAIL if precision < 0.85; otherwise round 2.",
          "After round 2 a type is never declared PASS unless its lower bound >= 0.90 (NOT_ESTABLISHED otherwise).", ""]
    for t, s in res["types"].items():
        L.append(f"- {t}: {s['reason']}; rounds pooled {s['rounds_pooled']}; error types {s['error_types'] or '{}'}")
        for sug in s.get("suggestions", []):
            L.append(f"    - fix ({sug['error_type']} x{sug['count']}): {sug['suggestion']}")
    k = res["kappa"]
    L.append("")
    if k["status"] == "computed":
        L.append(f"Cohen's kappa (overlap, before adjudication): {fmt(k['kappa_overall'])} on {k['n_pairs']} pairs, "
                 f"raw agreement {fmt(k['raw_agreement'])}; by type: " +
                 ", ".join(f"{t} {fmt(v['kappa'])} (n={v['n']})" for t, v in k["by_type"].items()))
        if k["disagreements_without_adjudication"]:
            L.append(f"Unadjudicated disagreements: {', '.join(k['disagreements_without_adjudication'])}")
    else:
        L.append(f"Cohen's kappa: NOT computed - {k['reason']}.")
    if res["round"] == 1:
        L.append("")
        L.append(f"Round 2 needed for: {res['round2_types'] or 'none'}" +
                 (f" -> sheet {res['round2_sheet']} ({res['round2_rows_written']} rows)" if res["round2_types"] else ""))
    L += ["", "Limitations:"] + [f"- {x}" for x in res["limitations"]]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", type=int, choices=(1, 2), default=1)
    ap.add_argument("--sheet1", type=Path, default=EVAL / "review_sheet_round1.csv")
    ap.add_argument("--overlap", type=Path, default=EVAL / "review_sheet_round1_overlap_reviewer2.csv")
    ap.add_argument("--sheet2", type=Path, default=EVAL / "review_sheet_round2.csv")
    ap.add_argument("--prebuilt2", type=Path, default=EVAL / "sampling" / "round2_prebuilt_DO_NOT_REVIEW.csv")
    ap.add_argument("--round2-out", type=Path, default=EVAL / "review_sheet_round2.csv")
    ap.add_argument("--out-dir", type=Path, default=EVAL / "manual_results")
    a = ap.parse_args(argv)
    return run(a.round, a.sheet1, a.overlap, a.sheet2, a.out_dir, a.prebuilt2, a.round2_out)


if __name__ == "__main__":
    sys.exit(main())
