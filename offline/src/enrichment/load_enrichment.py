"""Idempotent Neo4j loader for the enrichment scope (nlpgraph-enrich-v1).

Safety contract (mirrors src/graph/load.py):
- Only MERGE; never DELETE/DROP/overwrite. v1 nodes are never modified: enrichment edges
  MATCH existing Paper nodes (scope nlpgraph-v1) but SET properties only on the new
  relationship and on Method/Dataset/Task nodes owned by the enrichment scope.
- Refuses to run when an id we want to write is already owned by a FOREIGN scope.
- Verifies counts after import and writes a report under output/neo4j/.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.common import DATA, OUTPUT, SCOPE_ID, log, read_jsonl, write_json
from src.enrichment.schema import ENRICH_REL_SCHEMA, ENRICH_REL_TYPES, ENRICH_SCOPE_ID, ENRICH_VERSION, ENTITY_TYPE_TO_LABEL
from src.graph.load import _batches, _retry, _run, connect, database

ENRICH_LABELS = ("Method", "Dataset", "Task")
NODE_FIELDS = ("name", "entity_type", "resolved_by", "mention_count", "n_papers", "aliases",
               "extractors", "build_version")
EDGE_FIELDS = ("source_kind", "confidence_band", "verification_status", "extractors",
               "evidence_paper_ids", "evidence_count", "evidence_texts", "first_year", "last_year",
               "build_version")

_LABEL_OF_TYPE = {v: k for k, v in ENTITY_TYPE_TO_LABEL.items()}  # "Method" -> "method"

# Static whitelisted Cypher (no interpolation of untrusted values), same style as load.py.
_NODE_CYPHER = {
    label: (f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) "
            f"SET n += row.props, n.scope_id = $scope RETURN count(n) AS n")
    for label in ENRICH_LABELS
}
_EDGE_CYPHER = {
    rel_type: (
        f"UNWIND $rows AS row "
        f"MATCH (a:{fl} {{id: row.from}}) MATCH (b:{tl} {{id: row.to}}) "
        + (f"WHERE a.scope_id = $paper_scope AND b.scope_id = $scope " if fl == "Paper"
           else f"WHERE a.scope_id = $scope AND b.scope_id = $scope ")
        + f"MERGE (a)-[r:{rel_type}]->(b) SET r += row.props, r.scope_id = $scope RETURN count(r) AS n")
    for rel_type, (fl, tl) in ENRICH_REL_SCHEMA.items()
}


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if v is not None and v != []}


def load_enriched(enriched_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Read entities/edges from disk, group by label/type, reject dangling endpoints."""
    entities = read_jsonl(enriched_dir / "entities.jsonl")
    node_rows: dict[str, list[dict[str, Any]]] = {label: [] for label in ENRICH_LABELS}
    entity_ids: set[str] = set()
    for entity in entities:
        label = ENTITY_TYPE_TO_LABEL[entity["entity_type"]]
        entity_ids.add(entity["id"])
        props = _clean({k: entity.get(k) for k in NODE_FIELDS})
        node_rows[label].append({"id": entity["id"], "props": props})

    paper_ids = {p["id"] for p in read_jsonl(DATA / "processed" / "papers.jsonl")}
    edge_rows: dict[str, list[dict[str, Any]]] = {t: [] for t in ENRICH_REL_TYPES}
    rejected: list[dict[str, Any]] = []
    for rel_type in ENRICH_REL_TYPES:
        path = enriched_dir / f"edges_{rel_type}.jsonl"
        if not path.exists():
            continue
        from_label, to_label = ENRICH_REL_SCHEMA[rel_type]
        for edge in read_jsonl(path):
            from_ok = edge["from"] in paper_ids if from_label == "Paper" else edge["from"] in entity_ids
            to_ok = edge["to"] in paper_ids if to_label == "Paper" else edge["to"] in entity_ids
            if not (from_ok and to_ok):
                rejected.append({**edge, "reject_reason": "dangling endpoint"})
                continue
            props = dict(_clean({k: edge.get(k) for k in EDGE_FIELDS}))
            props["evidence_texts"] = [e.get("evidence_text", "") for e in edge.get("evidence", [])][:3]
            edge_rows[rel_type].append({"from": edge["from"], "to": edge["to"], "props": _clean(props)})
    return node_rows, edge_rows, rejected


def ensure_enrich_schema(session) -> None:
    for label in ENRICH_LABELS:
        name = f"nlpgraph_{label.lower()}_id_unique"
        _run(session, f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")


def check_conflicts(session, node_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    conflicts = []
    for label, rows in node_rows.items():
        ids = [r["id"] for r in rows]
        for i in range(0, len(ids), 2000):
            res = _run(session, f"UNWIND $ids AS id MATCH (n:{label} {{id: id}}) "
                                f"WHERE coalesce(n.scope_id, '') <> $s RETURN n.id AS id LIMIT 20",
                       ids=ids[i:i + 2000], s=ENRICH_SCOPE_ID)
            conflicts += [{"label": label, "id": r["id"]} for r in res]
    return conflicts


def _scope_counts(session) -> dict[str, Any]:
    by_label = {label: _run(session, f"MATCH (n:{label}) WHERE n.scope_id = $s RETURN count(n) AS c",
                            s=ENRICH_SCOPE_ID)[0]["c"] for label in ENRICH_LABELS}
    by_type = {t: _run(session, f"MATCH ()-[r:{t}]->() WHERE r.scope_id = $s RETURN count(r) AS c",
                       s=ENRICH_SCOPE_ID)[0]["c"] for t in ENRICH_REL_TYPES}
    return {"nodes_by_label": by_label, "relationships_by_type": by_type,
            "nodes": sum(by_label.values()), "relationships": sum(by_type.values())}


def run_import_enrichment(enriched_dir: Path = DATA / "enriched", dry_run: bool = False,
                          batch_size: int = 300) -> int:
    node_rows, edge_rows, rejected = load_enriched(enriched_dir)
    plan = {
        "scope_id": ENRICH_SCOPE_ID, "enrich_version": ENRICH_VERSION,
        "nodes": {label: len(rows) for label, rows in node_rows.items()},
        "relationships": {t: len(rows) for t, rows in edge_rows.items()},
        "rejected_edges": len(rejected), "batch_size": batch_size,
        "paper_scope_referenced": SCOPE_ID,
    }
    out_dir = OUTPUT / "neo4j"
    write_json(out_dir / ("import_enrichment_plan_dry_run.json" if dry_run else "import_enrichment_plan.json"), plan)
    print(plan)
    if dry_run:
        log.info("dry run: nothing written to Neo4j")
        return 0

    driver = connect()
    try:
        with driver.session(database=database()) as s:
            before = _scope_counts(s)
            conflicts = check_conflicts(s, node_rows)
            if conflicts:
                write_json(out_dir / "enrichment_conflicts.json", conflicts)
                log.error("BLOCKED: %d enrichment ids already owned by a foreign scope", len(conflicts))
                return 3
            ensure_enrich_schema(s)
            t0 = time.time()
            for label in ENRICH_LABELS:
                n = 0
                for b in _batches(node_rows[label], batch_size):
                    n += _retry(lambda b=b, label=label: s.execute_write(
                        lambda tx: tx.run(_NODE_CYPHER[label], rows=b, scope=ENRICH_SCOPE_ID).single()["n"]),
                        f"enrich nodes {label}")
                log.info("enrich nodes %-8s merged %d", label, n)
            for rel_type in ENRICH_REL_TYPES:
                rows = edge_rows[rel_type]
                if not rows:
                    continue
                n = 0
                for b in _batches(rows, batch_size):
                    n += _retry(lambda b=b, rel_type=rel_type: s.execute_write(
                        lambda tx: tx.run(_EDGE_CYPHER[rel_type], rows=b, scope=ENRICH_SCOPE_ID,
                                          paper_scope=SCOPE_ID).single()["n"]),
                        f"enrich rels {rel_type}")
                if n != len(rows):
                    log.error("%s: wrote %d of %d (missing endpoints in DB?)", rel_type, n, len(rows))
                log.info("enrich rels  %-20s merged %d", rel_type, n)
            after = _scope_counts(s)
        report = {"plan": plan, "before": before, "after": after, "rejected_edges": rejected[:20],
                  "seconds": round(time.time() - t0, 1),
                  "finished_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        write_json(out_dir / "import_enrichment_report_latest.json", report)
        ok = (after["nodes_by_label"] == plan["nodes"] and after["relationships_by_type"] == plan["relationships"])
        log.info("enrichment import %s; scope nodes=%d rels=%d",
                 "VERIFIED" if ok else "COUNT MISMATCH", after["nodes"], after["relationships"])
        return 0 if ok else 4
    finally:
        driver.close()
