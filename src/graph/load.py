"""Neo4j (AuraDB) schema + idempotent loader. Never deletes data; only MERGEs project-owned items."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from src.common import BUILD_VERSION, OUTPUT, REJECTED, SCOPE_ID, env, log, read_json, scrub, write_json, write_jsonl
from src.data.contracts import ContractError, load_dataset
from src.graph.derive import REL_SCHEMA, REL_TYPES, derive_edges, topic_nodes, write_derived

LABELS = ("Author", "Paper", "Institution", "Venue", "Topic")
NODE_FIELDS = {
    "Author": ("id", "name", "orcid", "openalex_id", "acl_author_id", "identity_status"),
    "Paper": ("id", "title", "year", "abstract", "doi", "acl_id", "arxiv_id", "source_kind", "source_url",
              "venue_id", "openalex_id", "abstract_origin"),
    "Institution": ("id", "name", "ror", "country_code", "source_url"),
    "Venue": ("id", "name", "kind", "year", "source_url"),
    "Topic": ("id", "topic_key", "name", "description", "rule_version"),
}
EDGE_PROPS = ("source_kind", "source_url", "evidence_paper_ids", "evidence_count", "first_year", "last_year",
              "years", "build_version", "position", "author_position", "shared_count", "rule_id",
              "evidence_span", "confidence_band")

# Static, whitelisted Cypher per relationship type: no string interpolation of untrusted input.
_REL_CYPHER = {
    t: (f"UNWIND $rows AS row "
        f"MATCH (a:{fl} {{id: row.from}}) MATCH (b:{tl} {{id: row.to}}) "
        f"MERGE (a)-[r:{t}]->(b) SET r += row.props, r.scope_id = $scope "
        f"RETURN count(r) AS n")
    for t, (fl, tl, _u) in REL_SCHEMA.items()
}
_NODE_CYPHER = {
    lbl: (f"UNWIND $rows AS row MERGE (n:{lbl} {{id: row.id}}) "
          f"SET n += row.props, n.scope_id = $scope, n.build_version = $build RETURN count(n) AS n")
    for lbl in LABELS
}


def connect():
    from neo4j import GraphDatabase
    uri = env("NEO4J_URI")
    user = env("NEO4J_USERNAME", "NEO4J_USER")
    pwd = env("NEO4J_PASSWORD")
    missing = [k for k, v in (("NEO4J_URI", uri), ("NEO4J_USERNAME", user), ("NEO4J_PASSWORD", pwd)) if not v]
    if missing:
        raise RuntimeError(f"missing environment variables: {', '.join(missing)} (see .env.example)")
    assert uri is not None
    if not uri.startswith(("neo4j+s://", "neo4j+ssc://", "bolt+s://")):
        log.warning("NEO4J_URI is not a TLS (neo4j+s://) URI")
    driver = GraphDatabase.driver(uri, auth=(user, pwd), connection_timeout=30, max_connection_lifetime=600)
    driver.verify_connectivity()
    return driver


def database() -> str:
    return env("NEO4J_DATABASE", default="neo4j") or "neo4j"


def _run(session, query: str, **params) -> list[dict[str, Any]]:
    return [r.data() for r in session.run(query, **params)]


def _retry(fn: Callable[[], Any], what: str, attempts: int = 5) -> Any:
    from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
    delay = 2.0
    for i in range(1, attempts + 1):
        try:
            return fn()
        except (TransientError, ServiceUnavailable, SessionExpired) as exc:
            if i == attempts:
                raise
            log.warning("%s: transient error (%s), retry %d in %.0fs", what, scrub(type(exc).__name__), i, delay)
            time.sleep(delay)
            delay *= 2


def inventory(session) -> dict[str, Any]:
    labels = _run(session, "CALL db.labels() YIELD label RETURN collect(label) AS l")[0]["l"]
    rtypes = _run(session, "CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS t")[0]["t"]
    total_n = _run(session, "MATCH (n) RETURN count(n) AS c")[0]["c"]
    total_r = _run(session, "MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    own_n = _run(session, "MATCH (n) WHERE n.scope_id = $s RETURN count(n) AS c", s=SCOPE_ID)[0]["c"]
    own_r = _run(session, "MATCH ()-[r]->() WHERE r.scope_id = $s RETURN count(r) AS c", s=SCOPE_ID)[0]["c"]
    cons = _run(session, "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties, type RETURN name, labelsOrTypes, properties, type")
    return {"labels": labels, "relationship_types": rtypes, "total_nodes": total_n, "total_relationships": total_r,
            "project_nodes": own_n, "project_relationships": own_r, "foreign_nodes": total_n - own_n,
            "foreign_relationships": total_r - own_r, "constraints": cons}


def preflight() -> int:
    driver = connect()
    try:
        info = driver.get_server_info()
        with driver.session(database=database()) as s:
            one = _run(s, "RETURN 1 AS ok")[0]["ok"]
            inv = inventory(s)
            comps = _run(s, "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition")
        rep = {"return_1": one, "server_agent": info.agent, "protocol": list(info.protocol_version),
               "components": comps, **inv}
        write_json(OUTPUT / "neo4j" / "preflight.json", rep)
        print({k: v for k, v in rep.items() if k != "constraints"})
        return 0
    finally:
        driver.close()


def ensure_schema(session) -> None:
    for lbl in LABELS:
        name = f"nlpgraph_{lbl.lower()}_id_unique"
        _run(session, f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.id IS UNIQUE")
    _run(session, "CREATE INDEX nlpgraph_paper_scope IF NOT EXISTS FOR (n:Paper) ON (n.scope_id)")
    _run(session, "CREATE INDEX nlpgraph_author_scope IF NOT EXISTS FOR (n:Author) ON (n.scope_id)")


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if v is not None and v != []}


def build_payload(rows: dict[str, list[dict[str, Any]]], rule_version: str):
    nodes = {
        "Paper": rows["papers.jsonl"], "Author": rows["authors.jsonl"],
        "Institution": rows["institutions.jsonl"], "Venue": rows["venues.jsonl"],
        "Topic": topic_nodes(rule_version),
    }
    node_rows = {lbl: [{"id": r["id"], "props": _clean({k: r.get(k) for k in NODE_FIELDS[lbl]})} for r in rs]
                 for lbl, rs in nodes.items()}
    ids = {lbl: {r["id"] for r in rs} for lbl, rs in nodes.items()}
    edges = derive_edges(rows)
    write_derived(edges)
    edge_rows: dict[str, list[dict[str, Any]]] = {}
    rejected = []
    for t in REL_TYPES:
        fl, tl, _ = REL_SCHEMA[t]
        good = []
        for e in edges[t]:
            if e["from"] not in ids[fl] or e["to"] not in ids[tl]:
                rejected.append({**e, "reject_reason": "dangling endpoint"})
                continue
            good.append({"from": e["from"], "to": e["to"], "props": _clean({k: e.get(k) for k in EDGE_PROPS})})
        edge_rows[t] = good
    write_jsonl(REJECTED / "edges.jsonl", rejected)
    return node_rows, edge_rows, rejected


def check_conflicts(session, node_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Nodes with our ids that exist but are NOT owned by this project -> refuse to overwrite."""
    conflicts = []
    for lbl, rs in node_rows.items():
        ids = [r["id"] for r in rs]
        for i in range(0, len(ids), 2000):
            res = _run(session, f"UNWIND $ids AS id MATCH (n:{lbl} {{id: id}}) "
                                f"WHERE coalesce(n.scope_id, '') <> $s RETURN n.id AS id LIMIT 20",
                       ids=ids[i:i + 2000], s=SCOPE_ID)
            conflicts += [{"label": lbl, "id": r["id"]} for r in res]
    return conflicts


def _batches(rows: list[Any], size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def run_import(data_dir: Path, dry_run: bool = False, batch_size: int = 300) -> int:
    try:
        rows = load_dataset(data_dir)
    except ContractError as exc:
        log.error("refusing import: snapshot failed validation (%d errors), e.g. %s", len(exc.errors), exc.errors[:3])
        return 2
    manifest = read_json(data_dir / "manifest.json")
    node_rows, edge_rows, rejected = build_payload(rows, manifest.get("topic_rule_version", "topics-v1.0"))
    plan = {"scope_id": SCOPE_ID, "build_version": BUILD_VERSION,
            "nodes": {k: len(v) for k, v in node_rows.items()},
            "relationships": {k: len(v) for k, v in edge_rows.items()},
            "rejected_edges": len(rejected), "batch_size": batch_size}
    plan["total_nodes"] = sum(plan["nodes"].values())
    plan["total_relationships"] = sum(plan["relationships"].values())
    abstract_bytes = sum(len((p.get("abstract") or "").encode()) for p in rows["papers.jsonl"])
    evid_items = sum(len(r["props"].get("evidence_paper_ids", [])) for v in edge_rows.values() for r in v)
    plan["storage_estimate"] = {"abstract_bytes": abstract_bytes, "evidence_id_items": evid_items,
                                "approx_mb": round((abstract_bytes + evid_items * 16 + plan["total_relationships"] * 120
                                                    + plan["total_nodes"] * 200) / 1e6, 1)}
    write_json(OUTPUT / "neo4j" / ("import_plan_dry_run.json" if dry_run else "import_plan.json"), plan)
    print(plan)
    if dry_run:
        log.info("dry run: nothing written to Neo4j")
        return 0

    driver = connect()
    try:
        with driver.session(database=database()) as s:
            before = inventory(s)
            conflicts = check_conflicts(s, node_rows)
            if conflicts:
                write_json(OUTPUT / "neo4j" / "conflicts.json", conflicts)
                log.error("BLOCKED: %d existing nodes with project ids but foreign ownership; not overwriting", len(conflicts))
                return 3
            ensure_schema(s)
            t0 = time.time()
            for lbl in LABELS:
                n = 0
                for b in _batches(node_rows[lbl], batch_size):
                    n += _retry(lambda b=b: s.execute_write(
                        lambda tx: tx.run(_NODE_CYPHER[lbl], rows=b, scope=SCOPE_ID, build=BUILD_VERSION).single()["n"]),
                        f"nodes {lbl}")
                log.info("nodes %-12s merged %d", lbl, n)
            for t in REL_TYPES:
                n = 0
                for b in _batches(edge_rows[t], batch_size):
                    n += _retry(lambda b=b: s.execute_write(
                        lambda tx: tx.run(_REL_CYPHER[t], rows=b, scope=SCOPE_ID).single()["n"]), f"rels {t}")
                if n != len(edge_rows[t]):
                    log.error("%s: wrote %d of %d (missing endpoints in DB?)", t, n, len(edge_rows[t]))
                log.info("rels  %-20s merged %d", t, n)
            after = inventory(s)
            counts = verify_counts(s)
        rep = {"plan": plan, "before": {k: v for k, v in before.items() if k != "constraints"},
               "after": {k: v for k, v in after.items() if k != "constraints"}, "verified": counts,
               "seconds": round(time.time() - t0, 1), "finished_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        write_json(OUTPUT / "neo4j" / f"import_report_{stamp}.json", rep)
        write_json(OUTPUT / "neo4j" / "import_report_latest.json", rep)
        ok = counts["nodes_by_label"] == plan["nodes"] and counts["relationships_by_type"] == plan["relationships"]
        log.info("import %s; project nodes=%d rels=%d", "VERIFIED" if ok else "COUNT MISMATCH",
                 counts["project_nodes"], counts["project_relationships"])
        return 0 if ok else 4
    finally:
        driver.close()


def verify_counts(session) -> dict[str, Any]:
    by_label = {}
    for lbl in LABELS:
        by_label[lbl] = _run(session, f"MATCH (n:{lbl}) WHERE n.scope_id = $s RETURN count(n) AS c", s=SCOPE_ID)[0]["c"]
    by_type = {}
    for t in REL_TYPES:
        by_type[t] = _run(session, f"MATCH ()-[r:{t}]->() WHERE r.scope_id = $s RETURN count(r) AS c", s=SCOPE_ID)[0]["c"]
    dup = _run(session, "MATCH (a)-[r]->(b) WHERE r.scope_id = $s WITH a, b, type(r) AS t, count(r) AS c "
                        "WHERE c > 1 RETURN count(*) AS d", s=SCOPE_ID)[0]["d"]
    orphans = _run(session, "MATCH (n) WHERE n.scope_id = $s AND NOT (n)--() RETURN labels(n)[0] AS l, count(*) AS c",
                   s=SCOPE_ID)
    no_evid = _run(session, "MATCH ()-[r]->() WHERE r.scope_id = $s AND (r.evidence_paper_ids IS NULL OR size(r.evidence_paper_ids) = 0) "
                            "RETURN count(r) AS c", s=SCOPE_ID)[0]["c"]
    return {"nodes_by_label": by_label, "relationships_by_type": by_type,
            "project_nodes": sum(by_label.values()), "project_relationships": sum(by_type.values()),
            "populated_types": sum(1 for v in by_type.values() if v > 0),
            "parallel_duplicate_pairs": dup, "orphans_by_label": {o["l"]: o["c"] for o in orphans},
            "relationships_without_evidence": no_evid}
