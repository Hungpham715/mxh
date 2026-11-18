"""G3 scorer: conservative, rejects automated reviewers, needs every stratum labelled."""
import csv
import json

from src.evaluation.truth_audit import REL_TYPES, SHEET_FIELDS, allocation, score


def _write(tmp_path, label_for, reviewer="reviewer_a", n=50):
    populations = {t: 1000 for t in REL_TYPES}
    meta = {"populations": populations, "allocation": {t: n for t in REL_TYPES}}
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with (tmp_path / "sheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for t in REL_TYPES:
            for i in range(n):
                row = {f: "" for f in SHEET_FIELDS}
                row.update(review_id=f"{t}-{i}", edge_type=t, label=label_for(i), reviewer=reviewer)
                writer.writerow(row)
    return tmp_path / "sheet.csv", tmp_path / "meta.json", tmp_path / "out.json"


def test_all_correct_human_labels_pass(tmp_path):
    sheet, meta, out = _write(tmp_path, lambda i: "correct")
    assert score(sheet, meta, out) == 0
    assert json.loads(out.read_text())["verdict"] == "PASS"


def test_unverifiable_counts_against_precision(tmp_path):
    sheet, meta, out = _write(tmp_path, lambda i: "unverifiable" if i % 5 == 0 else "correct")
    score(sheet, meta, out)
    report = json.loads(out.read_text())
    assert report["per_type"]["CITES"]["conservative_precision"] == 0.8
    assert report["verdict"] == "FAIL_OR_INCOMPLETE"


def test_automated_reviewer_is_not_gold(tmp_path):
    sheet, meta, out = _write(tmp_path, lambda i: "correct", reviewer="llm")
    assert score(sheet, meta, out) != 0
    assert json.loads(out.read_text())["verdict"] == "BLOCKED_NO_INDEPENDENT_LABELS"


def test_small_strata_become_census():
    alloc = allocation({"A": 26, "B": 30000})
    assert alloc["A"] == 26
    assert alloc["B"] >= 40
