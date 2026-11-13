"""Tests for evaluation/compute_precision.py using SYNTHETIC labels only (never the real review sheets)."""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compute_precision", ROOT / "evaluation" / "compute_precision.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

COLS = ["review_id", "round", "is_overlap", "edge_type", "source_id", "target_id", "label", "error_type",
        "reviewer", "note", "adjudicated_label"]


def row(i, t, label, et="", reviewer="R1", note="", rnd="1", ov="0", adj=""):
    return {"review_id": f"R{rnd}-{i:03d}", "round": rnd, "is_overlap": ov, "edge_type": t, "source_id": f"s{i}",
            "target_id": f"t{i}", "label": label, "error_type": et, "reviewer": reviewer, "note": note,
            "adjudicated_label": adj}


def write(path, rows, bom=True, delim=","):
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, delimiter=delim)
        w.writeheader()
        w.writerows(rows)
    return path


def block(t, n_correct, n_incorrect, n_unver, start=1, rnd="1", et="wrong_org"):
    rows, i = [], start
    for _ in range(n_correct):
        rows.append(row(i, t, "correct", rnd=rnd)); i += 1
    for _ in range(n_incorrect):
        rows.append(row(i, t, "incorrect", et, rnd=rnd)); i += 1
    for _ in range(n_unver):
        rows.append(row(i, t, "unverifiable", note="pdf 404", rnd=rnd)); i += 1
    return rows


def prebuilt(tmp_path):
    rows = []
    for k, t in enumerate(cp.TYPES):
        rows += block(t, 50, 0, 0, start=1000 + 100 * k, rnd="2")
    for r in rows:
        r["label"] = ""
    return write(tmp_path / "prebuilt.csv", rows)


def run1(tmp_path, rows, overlap=None):
    s1 = write(tmp_path / "s1.csv", rows)
    ov = write(tmp_path / "ov.csv", overlap) if overlap else tmp_path / "none.csv"
    rc = cp.run(1, s1, ov, None, tmp_path / "out", prebuilt(tmp_path), tmp_path / "round2.csv")
    res = json.loads((tmp_path / "out" / "precision_round1.json").read_text(encoding="utf-8")) if rc == 0 else None
    return rc, res


def test_wilson_reference_values():
    lo, hi = cp.wilson(19, 20)
    # reliable-kg-estimation Wilson: exact chi-square upper bound near the ceiling (was 0.991 pre-replacement).
    assert round(lo, 3) == 0.764 and round(hi, 3) == 0.997
    lo, hi = cp.wilson(50, 50)
    assert round(lo, 3) == 0.929


def test_kappa_reference():
    a = ["correct"] * 20 + ["incorrect"] * 5 + ["correct"] * 5
    b = ["correct"] * 20 + ["incorrect"] * 5 + ["incorrect"] * 5
    # po = 25/30, pe = (25*20 + 5*10)/900 = 550/900
    assert abs(cp.cohen_kappa(a, b) - ((25 / 30 - 550 / 900) / (1 - 550 / 900))) < 1e-12
    assert cp.cohen_kappa(["correct"] * 5, ["correct"] * 5) == 1.0


@pytest.mark.parametrize("bad,needle", [
    (dict(label=""), "label is empty"),
    (dict(label="Correctt"), "invalid label"),
    (dict(label="incorrect", error_type=""), "needs error_type"),
    (dict(label="incorrect", error_type="typo"), "needs error_type"),
    (dict(label="correct", error_type="wrong_org"), "must be empty"),
    (dict(label="unverifiable", note=""), "requires a note"),
    (dict(reviewer=""), "reviewer is empty"),
])
def test_invalid_rows_stop_with_line_numbers(tmp_path, capsys, bad, needle):
    rows = block("AFFILIATED_WITH", 5, 0, 0)
    rows[2].update(bad)
    rc, _ = run1(tmp_path, rows)
    out = capsys.readouterr().out
    assert rc == 2 and needle in out and "line 4" in out          # header = line 1, rows[2] = line 4
    assert not (tmp_path / "out").exists()


def test_case_and_whitespace_tolerated_and_semicolon_csv(tmp_path):
    rows = block("ACTIVE_IN", 3, 0, 0)
    rows[0]["label"] = "  Correct "
    s1 = write(tmp_path / "s1.csv", rows, delim=";")
    rc = cp.run(1, s1, tmp_path / "none.csv", None, tmp_path / "out", prebuilt(tmp_path), tmp_path / "r2.csv")
    assert rc == 0


def test_decisions_and_round2_sheet_only_for_needed_types(tmp_path):
    rows = (block("AFFILIATED_WITH", 50, 0, 0, start=1)                     # 50/50 -> lower 0.929 -> PASS
            + block("ORG_COAUTHORED_WITH", 40, 8, 2, start=100)             # 0.80 -> FAIL
            + block("ACTIVE_IN", 46, 2, 2, start=200, et="wrong_author"))   # 0.92, lower < .90 -> NEEDS_ROUND_2
    rc, res = run1(tmp_path, rows)
    assert rc == 0
    d = {t: s["decision"] for t, s in res["types"].items()}
    assert d == {"AFFILIATED_WITH": "PASS", "ORG_COAUTHORED_WITH": "FAIL", "ACTIVE_IN": "NEEDS_ROUND_2"}
    assert res["types"]["ORG_COAUTHORED_WITH"]["suggestions"][0]["error_type"] == "wrong_org"
    assert res["round2_types"] == ["ACTIVE_IN"]
    r2 = list(csv.DictReader(open(tmp_path / "round2.csv", encoding="utf-8-sig")))
    assert len(r2) == 50 and {r["edge_type"] for r in r2} == {"ACTIVE_IN"}
    assert (tmp_path / "round2.csv").read_bytes()[:3] == b"\xef\xbb\xbf"


def test_two_unverifiable_treatments(tmp_path):
    rc, res = run1(tmp_path, block("AFFILIATED_WITH", 45, 0, 5))
    s = res["types"]["AFFILIATED_WITH"]
    assert s["a_exclude_unverifiable"]["precision"] == 1.0 and s["a_exclude_unverifiable"]["n"] == 45
    assert s["b_unverifiable_as_wrong"]["precision"] == 0.9 and s["b_unverifiable_as_wrong"]["n"] == 50
    assert s["decision"] == "NEEDS_ROUND_2"   # decision uses (b): 0.90 point, lower < 0.90


def test_error_type_counts(tmp_path):
    rows = block("ORG_COAUTHORED_WITH", 10, 0, 0)
    rows += [row(50, "ORG_COAUTHORED_WITH", "incorrect", "evidence_mismatch"),
             row(51, "ORG_COAUTHORED_WITH", "incorrect", "evidence_mismatch"),
             row(52, "ORG_COAUTHORED_WITH", "incorrect", "entity_merge_error")]
    rc, res = run1(tmp_path, rows)
    assert res["types"]["ORG_COAUTHORED_WITH"]["error_types"] == {"evidence_mismatch": 2, "entity_merge_error": 1}


def test_single_reviewer_no_kappa(tmp_path):
    rc, res = run1(tmp_path, block("ACTIVE_IN", 10, 0, 0))
    assert res["kappa"]["status"] == "not_computed" and "one reviewer" in res["kappa"]["reason"]


def test_kappa_with_two_reviewers_and_adjudication(tmp_path):
    main = block("AFFILIATED_WITH", 10, 0, 0)
    for r in main[:4]:
        r["is_overlap"] = "1"
    main[0].update(adjudicated_label="incorrect")       # adjudication does not change kappa input
    ov = [dict(r, reviewer="R2") for r in main[:4]]
    ov[0].update(label="incorrect", error_type="wrong_org")
    rc, res = run1(tmp_path, main, overlap=ov)
    k = res["kappa"]
    assert k["status"] == "computed" and k["n_pairs"] == 4 and k["raw_agreement"] == 0.75
    assert res["types"]["AFFILIATED_WITH"]["correct"] == 9   # adjudicated label used for precision


def test_kappa_refused_when_same_reviewer(tmp_path):
    main = block("AFFILIATED_WITH", 4, 0, 0)
    for r in main:
        r["is_overlap"] = "1"
    rc, res = run1(tmp_path, main, overlap=[dict(r) for r in main])
    assert res["kappa"]["status"] == "not_computed" and "same reviewer" in res["kappa"]["reason"]


def test_round2_pooling_never_passes_below_lower_bound(tmp_path):
    r1 = block("ACTIVE_IN", 46, 2, 2, start=1)
    s1 = write(tmp_path / "s1.csv", r1)
    r2 = block("ACTIVE_IN", 45, 3, 2, start=1, rnd="2")      # pooled 91/100 = .91, lower ~ .838
    s2 = write(tmp_path / "s2.csv", r2)
    rc = cp.run(2, s1, tmp_path / "none.csv", s2, tmp_path / "out", prebuilt(tmp_path), tmp_path / "x.csv")
    res = json.loads((tmp_path / "out" / "precision_round2.json").read_text(encoding="utf-8"))
    s = res["types"]["ACTIVE_IN"]
    assert rc == 0 and s["n"] == 100 and s["rounds_pooled"] == ["1", "2"]
    assert s["decision"] == "NOT_ESTABLISHED"
    assert any("optimistic" in x for x in res["limitations"])


def test_round2_pass_when_lower_bound_reached(tmp_path):
    s1 = write(tmp_path / "s1.csv", block("ACTIVE_IN", 48, 1, 1, start=1))
    s2 = write(tmp_path / "s2.csv", block("ACTIVE_IN", 50, 0, 0, start=1, rnd="2"))   # 98/100, lower ~.93
    cp.run(2, s1, tmp_path / "none.csv", s2, tmp_path / "out", prebuilt(tmp_path), tmp_path / "x.csv")
    res = json.loads((tmp_path / "out" / "precision_round2.json").read_text(encoding="utf-8"))
    assert res["types"]["ACTIVE_IN"]["decision"] == "PASS"


def test_real_round1_sheet_is_unlabelled_and_fails_validation_cleanly(capsys):
    """Script must refuse the real (blank) sheet rather than compute anything; read-only, writes nothing."""
    s1 = ROOT / "evaluation" / "review_sheet_round1.csv"
    if not s1.exists():
        pytest.skip("review sheet not generated")
    rows = cp.read_sheet(s1)
    probs = cp.validate(rows, s1.name)
    assert len(rows) == 150 and any("label is empty" in p for p in probs)
