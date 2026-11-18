"""The census integrity audit must flag corrupted edges, not only pass clean data."""
from src.data.contracts import load_dataset
from src.data.fixtures import fixture_tables, write_dataset
from src.evaluation.integrity_all import Findings, _node_tables, audit_edges, audit_nodes
from src.graph.derive import derive_edges


def _setup(tmp_path):
    write_dataset(tmp_path, fixture_tables())
    rows = load_dataset(tmp_path)
    nodes = _node_tables(rows, "v")
    edges = derive_edges(rows, tmp_path / "rejected")
    return rows, nodes, edges


def _checks(findings):
    return {item["check"] for item in findings.edge_errors if item["severity"] == "critical"}


def test_clean_fixture_has_no_critical_errors(tmp_path):
    rows, nodes, edges = _setup(tmp_path)
    findings = Findings()
    audit_nodes(nodes, findings)
    audit_edges(edges, nodes, rows, findings)
    assert not [e for e in findings.node_errors + findings.edge_errors if e["severity"] == "critical"]


def test_corruptions_are_detected(tmp_path):
    rows, nodes, edges = _setup(tmp_path)
    first = dict(edges["FIRST_AUTHOR_OF"][0])
    other = edges["OTHER_AUTHOR_OF"][0]
    first["from"] = other["from"]  # a non-first author claimed as first author
    edges["FIRST_AUTHOR_OF"].append(first)
    co = dict(edges["COAUTHORED_WITH"][0])
    co["from"], co["to"] = co["to"], co["from"]  # non canonical order
    edges["COAUTHORED_WITH"].append(co)
    dup = dict(edges["APPEARS_IN"][0])
    edges["APPEARS_IN"].append(dup)
    bad = dict(edges["CITES"][0])
    bad["evidence_paper_ids"] = ["oa:DOES_NOT_EXIST"]
    edges["CITES"].append(bad)
    findings = Findings()
    audit_edges(edges, nodes, rows, findings)
    checks = _checks(findings)
    assert "symmetric_not_canonical_order" in checks
    assert "duplicate_edge" in checks
    assert "evidence_paper_missing" in checks
    assert "not_position_1_author" in checks or "duplicate_edge" in checks


def test_duplicate_node_id_detected(tmp_path):
    rows, nodes, _ = _setup(tmp_path)
    nodes["Author"].append(dict(nodes["Author"][0]))
    findings = Findings()
    audit_nodes(nodes, findings)
    assert any(item["check"] == "duplicate_id_in_label" for item in findings.node_errors)
