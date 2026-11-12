"""Post-import Neo4j checks: idempotency (re-import + compare) and example Cypher queries with real results."""
from __future__ import annotations

from pathlib import Path

from src.common import OUTPUT, SCOPE_ID, read_json, write_json
from src.graph.load import connect, database, run_import, verify_counts

QUERIES = [
    ("Đếm quan hệ theo loại (chỉ dữ liệu của dự án)",
     "MATCH ()-[r]->() WHERE r.scope_id = $s RETURN type(r) AS relation, count(r) AS total ORDER BY total DESC"),
    ("Cặp đồng tác giả viết chung nhiều bài nhất, kèm paper chứng cứ",
     "MATCH (a:Author)-[c:COAUTHORED_WITH]->(b:Author) WHERE c.scope_id = $s "
     "RETURN a.name AS author_a, b.name AS author_b, c.shared_count AS shared, c.evidence_paper_ids AS papers "
     "ORDER BY shared DESC, author_a LIMIT 5"),
    ("Truy ngược: hai tác giả viết chung bài nào, mỗi người khai báo tổ chức nào trên bài đó, bài thuộc topic gì",
     "MATCH (a:Author)-[c:COAUTHORED_WITH]->(b:Author) WHERE c.scope_id = $s AND c.shared_count >= 2 "
     "WITH a, b, c ORDER BY c.shared_count DESC, a.id LIMIT 1 "
     "UNWIND c.evidence_paper_ids AS pid MATCH (p:Paper {id: pid}) "
     "OPTIONAL MATCH (a)-[fa:AFFILIATED_WITH]->(ia:Institution) WHERE pid IN fa.evidence_paper_ids "
     "OPTIONAL MATCH (b)-[fb:AFFILIATED_WITH]->(ib:Institution) WHERE pid IN fb.evidence_paper_ids "
     "OPTIONAL MATCH (p)-[:HAS_TOPIC]->(t:Topic) "
     "RETURN a.name AS a, b.name AS b, p.title AS paper, p.source_url AS url, collect(DISTINCT ia.name) AS inst_a, "
     "collect(DISTINCT ib.name) AS inst_b, collect(DISTINCT t.topic_key) AS topics"),
    ("Trích dẫn nội bộ corpus (X CITES Y)",
     "MATCH (p:Paper)-[c:CITES]->(q:Paper) WHERE c.scope_id = $s RETURN p.title AS citing, q.title AS cited, "
     "c.source_url AS evidence ORDER BY citing LIMIT 5"),
    ("Tổ chức hoạt động nhiều nhất theo topic (ACTIVE_IN)",
     "MATCH (i:Institution)-[r:ACTIVE_IN]->(t:Topic) WHERE r.scope_id = $s RETURN i.name AS institution, "
     "t.topic_key AS topic, r.evidence_count AS papers ORDER BY papers DESC, institution LIMIT 8"),
]


def example_queries() -> int:
    drv = connect()
    out = []
    try:
        with drv.session(database=database()) as s:
            for title, q in QUERIES:
                rows = [r.data() for r in s.run(q, s=SCOPE_ID)]
                out.append({"title": title, "cypher": q.replace("$s", f"'{SCOPE_ID}'"), "rows": rows})
                print(f"== {title}: {len(rows)} rows")
                for r in rows[:5]:
                    print("  ", str(r)[:220])
    finally:
        drv.close()
    write_json(OUTPUT / "neo4j" / "example_queries.json", out)
    return 0


def idempotency_check(data_dir: Path, batch_size: int = 300) -> int:
    drv = connect()
    try:
        with drv.session(database=database()) as s:
            first = verify_counts(s)
    finally:
        drv.close()
    rc = run_import(data_dir, batch_size=batch_size)
    second = read_json(OUTPUT / "neo4j" / "import_report_latest.json")["verified"]
    same = first == second
    write_json(OUTPUT / "neo4j" / "idempotency_check.json", {"identical": same, "first": first, "second": second,
                                                            "reimport_exit_code": rc})
    print("IDEMPOTENT" if same else "COUNTS CHANGED", first["project_nodes"], first["project_relationships"], "->",
          second["project_nodes"], second["project_relationships"])
    return 0 if same and rc == 0 else 5
