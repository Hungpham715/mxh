"""Full-graph integrity audit CLI (gate G2): scan 100% of in-scope nodes and edges.

Read-only. Streams rows per label / relationship type (bounded memory), runs every invariant
from src.graph.integrity, cross-checks the live graph against the deterministic snapshot
(processed JSONL + derive_edges), and writes:

  <out>/integrity_all.json   summary, per-label/type counts, errors by check, PASS/FAIL
  <out>/node_errors.csv      every failing node row
  <out>/edge_errors.csv      every failing edge row

Usage (from offline/):
  uv run python scripts/graph_integrity_audit.py [--data data/processed] [--out reports/graph_audit]

Env: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE (same as the importer).
Exit codes: 0 = PASS, 2 = FAIL, 1 = runtime error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common import SCOPE_ID, env, load_env, log, read_json, scrub, write_json  # noqa: E402
from src.data.contracts import ContractError, load_dataset  # noqa: E402
from src.graph.derive import REL_TYPES  # noqa: E402
from src.graph.integrity import (  # noqa: E402
    LABELS,
    AuditErrors,
    build_context,
    check_edge,
    check_node,
    check_snapshot_node_coverage,
    finalize_edge_checks,
    new_edge_state,
    write_error_csvs,
    build_report,
)
from src.graph.load import connect, database  # noqa: E402


def sanitized_database_label(uri: str) -> str:
    host = urlparse(uri).hostname or "unknown"
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "local-loopback"
    return f"remote:{host[:6]}***"


def fetch_counts(session) -> dict[str, int]:
    one = lambda q, **p: session.run(q, **p).single()[0]  # noqa: E731
    return {
        "total_nodes": one("MATCH (n) RETURN count(n)"),
        "total_edges": one("MATCH ()-[r]->() RETURN count(r)"),
        "scoped_nodes": one("MATCH (n) WHERE n.scope_id = $s RETURN count(n)", s=SCOPE_ID),
        "scoped_edges": one("MATCH ()-[r]->() WHERE r.scope_id = $s RETURN count(r)", s=SCOPE_ID),
    }


def scan_nodes(session, errors: AuditErrors, ctx) -> tuple[int, dict[str, int], set]:
    scanned = 0
    by_label: dict[str, int] = {}
    live_keys: set[tuple[str, str]] = set()
    for label in LABELS:
        result = session.run(
            f"MATCH (n:{label}) WHERE n.scope_id = $s "
            "RETURN n.id AS id, labels(n) AS labels, properties(n) AS props",
            s=SCOPE_ID,
        )
        count = 0
        for record in result:
            node = {"id": record["id"], "labels": list(record["labels"]), "props": dict(record["props"])}
            check_node(node, ctx, errors)
            known = [l for l in node["labels"] if l in LABELS]
            if len(known) == 1:
                live_keys.add((known[0], str(node["id"])))
            count += 1
        by_label[label] = count
        scanned += count
        log.info("scanned %-12s %6d nodes", label, count)
    return scanned, by_label, live_keys


def scan_edges(session, errors: AuditErrors, ctx, state: dict) -> int:
    rel_types = [r[0] for r in session.run(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")]
    scanned = 0
    for rel_type in sorted(set(rel_types) | set(REL_TYPES)):
        result = session.run(
            f"MATCH (a)-[r:{rel_type}]->(b) WHERE r.scope_id = $s "
            "RETURN type(r) AS type, a.id AS src, b.id AS dst, properties(r) AS props",
            s=SCOPE_ID,
        )
        count = 0
        for record in result:
            edge = {
                "type": record["type"],
                "from": record["src"],
                "to": record["dst"],
                "props": dict(record["props"]),
            }
            check_edge(edge, ctx, errors, state)
            count += 1
        scanned += count
        log.info("scanned %-22s %6d edges", rel_type, count)
    return scanned


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(ROOT / "data" / "processed"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "graph_audit"))
    args = parser.parse_args(argv)

    try:
        rows = load_dataset(Path(args.data))
    except ContractError as exc:
        log.error("snapshot failed validation (%d errors); refusing to audit", len(exc.errors))
        return 2

    scope_years = (2023, 2025)
    scope_cfg = ROOT / "configs" / "scope.yaml"
    if scope_cfg.exists():
        import yaml
        years = (yaml.safe_load(scope_cfg.read_text(encoding="utf-8")) or {}).get("years")
        if isinstance(years, list) and len(years) == 2:
            scope_years = (int(min(years)), int(max(years)))

    ctx = build_context(rows, scope_years)
    errors = AuditErrors()
    state = new_edge_state()

    driver = connect()
    try:
        with driver.session(database=database()) as session:
            live_counts = fetch_counts(session)
            nodes_scanned, nodes_by_label, live_keys = scan_nodes(session, errors, ctx)
            edges_scanned = scan_edges(session, errors, ctx, state)
            check_snapshot_node_coverage(live_keys, ctx, errors)
            finalize_edge_checks(state, ctx, errors)
        db_label = sanitized_database_label(env("NEO4J_URI") or "")
        report = build_report(
            live_counts=live_counts,
            scanned={"nodes": nodes_scanned, "edges": edges_scanned},
            nodes_by_label=nodes_by_label,
            state=state,
            errors=errors,
            database_label=db_label,
        )
    finally:
        driver.close()

    out_dir = Path(args.out)
    node_csv, edge_csv = write_error_csvs(out_dir, errors)
    write_json(out_dir / "integrity_all.json", report)
    print(scrub(
        f"RESULT={report['result']} scanned nodes={nodes_scanned}/{live_counts['scoped_nodes']} "
        f"edges={edges_scanned}/{live_counts['scoped_edges']} "
        f"node_errors={len(errors.node_errors)} edge_errors={len(errors.edge_errors)}\n"
        f"report={out_dir / 'integrity_all.json'}\nnode_csv={node_csv}\nedge_csv={edge_csv}"
    ))
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
