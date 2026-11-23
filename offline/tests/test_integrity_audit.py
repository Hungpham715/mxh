"""Unit tests for the full-graph integrity invariants (src/graph/integrity.py).

Each test mutates one property of an otherwise-clean fixture graph and asserts the specific
check fires — the same code path the live audit CLI runs over every node and edge.
"""
from __future__ import annotations

import copy

import pytest

from src.common import SCOPE_ID
from src.data.fixtures import fixture_tables
from src.graph.derive import derive_edges, topic_nodes
from src.graph.integrity import (
    AuditErrors,
    build_context,
    check_edge,
    check_node,
    check_snapshot_node_coverage,
    finalize_edge_checks,
    new_edge_state,
    write_error_csvs,
)

TABLE_LABELS = {
    "papers.jsonl": "Paper",
    "authors.jsonl": "Author",
    "institutions.jsonl": "Institution",
    "venues.jsonl": "Venue",
}


def _fixture_graph():
    """Build (ctx, node_rows, edge_rows) simulating a clean live DB from the fixture snapshot."""
    rows = fixture_tables()
    ctx = build_context(rows, (2023, 2025))

    node_rows = []
    for table, label in TABLE_LABELS.items():
        for record in rows[table]:
            props = dict(record)
            props["scope_id"] = SCOPE_ID
            node_rows.append({"id": record["id"], "labels": [label], "props": props})
    for topic in topic_nodes("topics-v1.0"):
        props = dict(topic)
        props["scope_id"] = SCOPE_ID
        node_rows.append({"id": topic["id"], "labels": ["Topic"], "props": props})

    # The integrity audit does not need rejection artifacts. This module-scoped fixture is
    # set up before the function-scoped isolation fixture in conftest.py, so opt out here
    # explicitly instead of relying on the redirected REJECTED path.
    edges = derive_edges(rows, write_rejections=False)
    edge_rows = []
    for rel_type, edge_list in edges.items():
        for edge in edge_list:
            props = {k: v for k, v in edge.items() if k not in {"type", "from", "to"}}
            props["scope_id"] = SCOPE_ID
            edge_rows.append({"type": rel_type, "from": edge["from"], "to": edge["to"], "props": props})
    return ctx, node_rows, edge_rows


def _run_audit(ctx, node_rows, edge_rows) -> AuditErrors:
    errors = AuditErrors()
    state = new_edge_state()
    for node in node_rows:
        check_node(node, ctx, errors)
    for edge in edge_rows:
        check_edge(edge, ctx, errors, state)
    live_keys = {(node["labels"][0], str(node["id"])) for node in node_rows if node["labels"]}
    check_snapshot_node_coverage(live_keys, ctx, errors)
    finalize_edge_checks(state, ctx, errors)
    return errors


def _checks(errors: AuditErrors) -> set[str]:
    return {e["check"] for e in errors.node_errors} | {e["check"] for e in errors.edge_errors}


@pytest.fixture(scope="module")
def clean_graph():
    return _fixture_graph()


def test_clean_fixture_graph_passes(clean_graph):
    ctx, node_rows, edge_rows = clean_graph
    errors = _run_audit(ctx, copy.deepcopy(node_rows), copy.deepcopy(edge_rows))
    assert errors.total == 0, errors.node_errors + errors.edge_errors


def test_error_csvs_use_repository_stable_lf_line_endings(tmp_path):
    node_path, edge_path = write_error_csvs(tmp_path, AuditErrors())
    assert node_path.read_bytes() == b"check,id,detail\n"
    assert edge_path.read_bytes() == b"check,type,from,to,detail\n"


def test_build_context_does_not_rewrite_rejection_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr("src.graph.derive.REJECTED", tmp_path)
    build_context(fixture_tables(), (2023, 2025))
    assert not (tmp_path / "large_author_papers.jsonl").exists()


def _mutated(clean_graph):
    ctx, node_rows, edge_rows = clean_graph
    return ctx, copy.deepcopy(node_rows), copy.deepcopy(edge_rows)


def test_node_scope_violation_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    node_rows[0]["props"]["scope_id"] = "other-scope"
    assert "scope_id" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_paper_year_out_of_scope_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    paper = next(n for n in node_rows if n["labels"] == ["Paper"])
    paper["props"]["year"] = 2019
    assert "year_out_of_scope" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_doi_syntax_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    paper = next(n for n in node_rows if n["labels"] == ["Paper"])
    paper["props"]["doi"] = "doi-10.0000-bad"
    assert "doi_syntax" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_missing_node_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    node_rows.pop()
    checks = _checks(_run_audit(ctx, node_rows, edge_rows))
    assert "missing_from_db" in checks


def test_self_loop_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    cites = next(e for e in edge_rows if e["type"] == "CITES")
    bad = copy.deepcopy(cites)
    bad["to"] = bad["from"]
    edge_rows.append(bad)
    assert "self_loop" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_duplicate_edge_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    edge_rows.append(copy.deepcopy(edge_rows[0]))
    assert "duplicate_edge" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_non_canonical_symmetric_edge_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    co = next(e for e in edge_rows if e["type"] == "COAUTHORED_WITH")
    co["from"], co["to"] = co["to"], co["from"]
    assert "canonical_direction" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_first_author_position_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    first = next(e for e in edge_rows if e["type"] == "FIRST_AUTHOR_OF")
    first["props"]["position"] = 3
    checks = _checks(_run_audit(ctx, node_rows, edge_rows))
    assert "first_author_position" in checks


def test_evidence_count_mismatch_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    aff = next(e for e in edge_rows if e["type"] == "AFFILIATED_WITH")
    aff["props"]["evidence_count"] = 99
    assert "evidence_count_mismatch" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_affiliation_without_authorship_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    aff = next(
        e for e in edge_rows
        if e["type"] == "AFFILIATED_WITH" and e["from"] == "oa:AFIX1" and e["to"] == "oa:IFIX1"
    )
    # WFIX4 is authored only by src:oa:WFIX4#1 — AFIX1 has no authorship evidence there.
    aff["props"]["evidence_paper_ids"] = aff["props"]["evidence_paper_ids"] + ["oa:WFIX4"]
    aff["props"]["evidence_count"] = len(aff["props"]["evidence_paper_ids"])
    assert "affiliation_without_authorship" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_topic_evidence_span_missing_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    topic_edge = next(e for e in edge_rows if e["type"] == "HAS_TOPIC")
    topic_edge["props"]["evidence_span"] = "  "
    assert "topic_evidence_span_missing" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_inferred_relation_threshold_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    researches = next(e for e in edge_rows if e["type"] == "RESEARCHES")
    researches["props"]["evidence_count"] = 1
    assert "inferred_relation_threshold" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_citation_without_source_row_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    cites = next(e for e in edge_rows if e["type"] == "CITES")
    bad = copy.deepcopy(cites)
    bad["from"], bad["to"] = "oa:WFIX5", "oa:WFIX4"
    bad["props"]["evidence_paper_ids"] = ["oa:WFIX5"]
    bad["props"]["evidence_count"] = 1
    edge_rows.append(bad)
    assert "citation_without_source_row" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_missing_edge_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    edge_rows.pop()
    assert "missing_from_db" in _checks(_run_audit(ctx, node_rows, edge_rows))


def test_appears_in_cardinality_per_paper_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    appears = next(e for e in edge_rows if e["type"] == "APPEARS_IN")
    second_venue = copy.deepcopy(appears)
    second_venue["to"] = "venue:arxiv:cs.CL" if appears["to"] != "venue:arxiv:cs.CL" else "venue:acl:fix-main"
    edge_rows.append(second_venue)
    checks = _checks(_run_audit(ctx, node_rows, edge_rows))
    assert "appears_in_cardinality" in checks


def test_endpoint_label_mismatch_detected(clean_graph):
    ctx, node_rows, edge_rows = _mutated(clean_graph)
    first = next(e for e in edge_rows if e["type"] == "FIRST_AUTHOR_OF")
    first["from"] = "oa:WFIX1"  # a Paper id where an Author belongs
    assert "endpoint_label" in _checks(_run_audit(ctx, node_rows, edge_rows))
