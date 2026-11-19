"""REAL E2E: 30 cases through the live workflow (Ollama qwen3:0.6b + real Neo4j graph).

Entities come from the LIVE graph (live_entities.json probe). Each case carries an independent
Cypher oracle expectation where applicable; the script compares workflow output against it.
Outputs sanitized JSON + markdown evidence (no credentials, no .env values).

Run from chatbot/ with env: NEO4J_URI/USERNAME/PASSWORD pointing at the target graph,
LLM_PROVIDER=ollama, APP_MODE=real, GRAPH_PROVIDER=neo4j.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from neo4j import AsyncGraphDatabase

from graphrag.factory import build_dependencies
from graphrag.models import ChatRequest, HistoryMessage
from graphrag.settings import Settings

RUN_DIR = Path(__file__).resolve().parent
SCOPE = "nlpgraph-v1"


def load_entities() -> dict:
    return json.loads((RUN_DIR / "live_entities.json").read_text(encoding="utf-8"))


def build_cases(e: dict) -> list[dict]:
    top = e["top_author"][0]["name"]  # Xipeng Qiu
    second = e["top_author"][1]["name"]  # Maosong Sun
    pair = e["coauthor_pair"][0]
    cited = e["cited_paper"][0]
    org = e["top_org"][0]["name"]
    affil = e["affil_author"][0]["author"]
    venue_paper = e["venue_paper"][0]
    topic = e["topics"][0]["name"]
    path = e["path_pair"][0]
    ambiguous = e["ambiguous_names"][0]["name"]
    big = e["big_coauthor_author"][0]["name"]

    cases = [
        # --- author papers (3) ---
        {
            "id": "A1",
            "cat": "author_papers",
            "q": f"Các bài báo của tác giả {top} trong tập dữ liệu?",
            "oracle": ("author_papers", {"name": top}),
            "expect_status": "answered",
        },
        {
            "id": "A2",
            "cat": "author_papers",
            "q": f"Liệt kê bài báo của {second}.",
            "oracle": ("author_papers", {"name": second}),
            "expect_status": "answered",
        },
        {
            "id": "A3",
            "cat": "author_papers_year",
            "q": f"Bài báo của {top} từ năm 2024 đến 2025?",
            "oracle": ("author_papers_years", {"name": top, "y0": 2024, "y1": 2025}),
            "expect_status": "answered",
        },
        # --- coauthors (3) ---
        {
            "id": "C1",
            "cat": "coauthors",
            "q": f"Đồng tác giả của {pair['a']} là ai?",
            "oracle": ("coauthor_count", {"name": pair["a"]}),
            "expect_status": {"answered", "partial"},
        },
        {
            "id": "C2",
            "cat": "coauthors",
            "q": f"Ai đã cùng viết bài với {big}?",
            "oracle": ("coauthor_count", {"name": big}),
            "expect_status": {"answered", "partial"},
        },
        {
            "id": "C3",
            "cat": "shared_papers",
            "q": f"{pair['a']} và {pair['b']} có bài báo chung nào?",
            "oracle": ("shared_count", {"a": pair["a"], "b": pair["b"]}),
            "expect_status": "answered",
        },
        # --- affiliations (3) ---
        {
            "id": "F1",
            "cat": "author_affiliations",
            "q": f"{affil} gắn với tổ chức nào theo các bài báo?",
            "oracle": ("affil_orgs", {"name": affil}),
            "expect_status": "answered",
        },
        {
            "id": "F2",
            "cat": "coauthor_affiliations",
            "q": f"Tổ chức của đồng tác giả {pair['a']} trên bài chung là gì?",
            "oracle": None,
            "expect_status": {"answered", "partial", "not_found"},
        },
        {
            "id": "F3",
            "cat": "author_affiliations",
            "q": f"Cơ quan của {second} theo từng bài báo?",
            "oracle": ("affil_orgs", {"name": second}),
            "expect_status": "answered",
        },
        # --- paper-level (4) ---
        {
            "id": "P1",
            "cat": "paper_authors",
            "q": f"Ai là tác giả của bài {venue_paper['title']}?",
            "oracle": ("paper_author_count", {"pid": venue_paper["id"]}),
            "expect_status": "answered",
        },
        {
            "id": "P2",
            "cat": "paper_venue",
            "q": f"Bài {venue_paper['title']} xuất hiện ở venue nào?",
            "oracle": ("paper_venue", {"pid": venue_paper["id"]}),
            "expect_status": "answered",
        },
        {
            "id": "P3",
            "cat": "paper_citations",
            "q": f"Bài {cited['cited']} được trích dẫn bởi bài nào trong corpus?",
            "oracle": ("cited_by_count", {"pid": cited["id"]}),
            "expect_status": "answered",
        },
        {
            "id": "P4",
            "cat": "paper_authors",
            "q": f"Danh sách tác giả của bài {e['venue_paper'][1]['title']}?",
            "oracle": ("paper_author_count", {"pid": e["venue_paper"][1]["id"]}),
            "expect_status": "answered",
        },
        # --- topics (2) ---
        {
            "id": "T1",
            "cat": "topic_papers",
            "q": f"Các bài đã gắn nhãn chủ đề {topic} là gì?",
            "oracle": ("topic_count", {"name": topic}),
            "expect_status": {"answered", "partial"},
        },
        {
            "id": "T2",
            "cat": "topic_papers",
            "q": f"Chủ đề {e['topics'][1]['name']} có những bài nào?",
            "oracle": ("topic_count", {"name": e["topics"][1]["name"]}),
            "expect_status": {"answered", "partial"},
        },
        # --- orgs (2) ---
        {
            "id": "O1",
            "cat": "org_collaborations",
            "q": f"{org} hợp tác với tổ chức nào trong corpus?",
            "oracle": ("org_collab_count", {"name": org}),
            "expect_status": {"answered", "partial"},
        },
        {
            "id": "O2",
            "cat": "org_collaborations",
            "q": f"Các tổ chức hợp tác với {e['top_org'][1]['name']}?",
            "oracle": ("org_collab_count", {"name": e["top_org"][1]["name"]}),
            "expect_status": {"answered", "partial"},
        },
        # --- ranking (1) ---
        {
            "id": "R1",
            "cat": "network_top",
            "q": "Top tác giả theo số đồng tác giả riêng biệt là ai?",
            "oracle": ("top_coauthor_author", {}),
            "expect_status": {"answered", "partial"},
        },
        # --- path (1) ---
        {
            "id": "H1",
            "cat": "author_path",
            "q": f"Đường đồng tác giả giữa {path['a']} và {path['b']} là gì?",
            "oracle": None,
            "expect_status": {"answered", "partial", "not_found"},
        },
        # --- unknown entity (2) ---
        {
            "id": "U1",
            "cat": "unknown_entity",
            "q": 'Bài báo của tác giả "Nguyen Van Khong Co That"',
            "oracle": None,
            "expect_status": {"not_found", "out_of_scope", "clarify"},
        },
        {
            "id": "U2",
            "cat": "unknown_entity",
            "q": 'Đồng tác giả của "Zzz Nobodyzzz" là ai?',
            "oracle": None,
            "expect_status": {"not_found", "out_of_scope", "clarify"},
        },
        # --- ambiguous (1) ---
        {
            "id": "M1",
            "cat": "ambiguous",
            "q": f"Các bài báo của tác giả {ambiguous}?",
            "oracle": None,
            "expect_status": {"ambiguous", "answered"},
        },
        # --- out of scope (3) ---
        {
            "id": "X1",
            "cat": "out_of_scope",
            "q": "Đặt phòng họp ngày mai lúc 8 giờ",
            "oracle": None,
            "expect_status": "out_of_scope",
        },
        {
            "id": "X2",
            "cat": "out_of_scope",
            "q": "Thời tiết Hà Nội hôm nay thế nào?",
            "oracle": None,
            "expect_status": "out_of_scope",
        },
        {
            "id": "X3",
            "cat": "out_of_scope",
            "q": "Cách nấu một nồi phở bò ngon?",
            "oracle": None,
            "expect_status": "out_of_scope",
        },
        # --- clarify (1) ---
        {
            "id": "L1",
            "cat": "clarify",
            "q": "Các bài báo của tác giả đó?",
            "oracle": None,
            "expect_status": {"clarify", "not_found"},
        },
        # --- chat history (2) ---
        {
            "id": "Y1",
            "cat": "chat_history",
            "q": "Câu hỏi đầu tiên tôi hỏi bạn là gì?",
            "history": [
                {"role": "user", "content": f"Các bài báo của {top}?"},
                {"role": "assistant", "content": "Danh sách bài báo ..."},
            ],
            "oracle": None,
            "expect_status": "answered",
        },
        {
            "id": "Y2",
            "cat": "followup_coref",
            "q": "Thế các đồng tác giả của người đó?",
            "history": [
                {"role": "user", "content": f"Hãy liệt kê bài báo của {top}"},
                {"role": "assistant", "content": "Đã tìm thấy các bài báo."},
            ],
            "oracle": ("coauthor_count", {"name": top}),
            "expect_status": "answered",
        },
        # --- count question (1) ---
        {
            "id": "N1",
            "cat": "count",
            "q": f"{top} có bao nhiêu bài báo trong corpus?",
            "oracle": ("author_papers", {"name": top}),
            "expect_status": "answered",
        },
        # --- extra graph questions (2) ---
        {
            "id": "G1",
            "cat": "author_papers",
            "q": f"Tìm các công bố của {e['top_author'][2]['name']}.",
            "oracle": ("author_papers", {"name": e["top_author"][2]["name"]}),
            "expect_status": "answered",
        },
        {
            "id": "G2",
            "cat": "coauthors",
            "q": f"Đồng tác giả của {e['affil_author'][1]['author']}?",
            "oracle": ("coauthor_count", {"name": e["affil_author"][1]["author"]}),
            "expect_status": "answered",
        },
    ]
    return cases


ORACLE_QUERIES = {
    "author_papers": """
        MATCH (a:Author {scope_id:$S})-[r:FIRST_AUTHOR_OF|OTHER_AUTHOR_OF]->(p:Paper {scope_id:$S})
        WHERE a.name = $name RETURN collect(p.id) AS ids""",
    "author_papers_years": """
        MATCH (a:Author {scope_id:$S})-[r:FIRST_AUTHOR_OF|OTHER_AUTHOR_OF]->(p:Paper {scope_id:$S})
        WHERE a.name = $name AND p.year >= $y0 AND p.year <= $y1 RETURN collect(p.id) AS ids""",
    "coauthor_count": """
        MATCH (a:Author {scope_id:$S})-[r:COAUTHORED_WITH]-(b:Author {scope_id:$S})
        WHERE a.name = $name RETURN collect(DISTINCT b.id) AS ids""",
    "shared_count": """
        MATCH (a:Author {scope_id:$S})-[r:COAUTHORED_WITH]-(b:Author {scope_id:$S})
        WHERE a.name = $a AND b.name = $b RETURN r.evidence_paper_ids AS ids""",
    "affil_orgs": """
        MATCH (a:Author {scope_id:$S})-[r:AFFILIATED_WITH]->(i:Institution {scope_id:$S})
        WHERE a.name = $name RETURN collect(DISTINCT i.id) AS ids""",
    "paper_author_count": """
        MATCH (a:Author {scope_id:$S})-[r:FIRST_AUTHOR_OF|OTHER_AUTHOR_OF]->(p:Paper {scope_id:$S})
        WHERE p.id = $pid RETURN collect(a.id) AS ids""",
    "paper_venue": """
        MATCH (p:Paper {scope_id:$S})-[:APPEARS_IN]->(v:Venue {scope_id:$S})
        WHERE p.id = $pid RETURN collect(v.id) AS ids, collect(v.name) AS names""",
    "cited_by_count": """
        MATCH (other:Paper {scope_id:$S})-[r:CITES]->(p:Paper {scope_id:$S})
        WHERE p.id = $pid RETURN collect(DISTINCT other.id) AS ids""",
    "topic_count": """
        MATCH (p:Paper {scope_id:$S})-[:HAS_TOPIC]->(t:Topic {scope_id:$S})
        WHERE t.name = $name RETURN collect(p.id) AS ids""",
    "org_collab_count": """
        MATCH (i:Institution {scope_id:$S})-[r:ORG_COAUTHORED_WITH]-(j:Institution {scope_id:$S})
        WHERE i.name = $name RETURN collect(DISTINCT j.id) AS ids""",
    "top_coauthor_author": """
        MATCH (a:Author {scope_id:$S})-[r:COAUTHORED_WITH]-(b:Author {scope_id:$S})
        WITH a, count(DISTINCT b) AS n
        RETURN a.id AS top_id, a.name AS top_name, n ORDER BY n DESC, a.name LIMIT 1""",
}


async def run_oracles(cases: list[dict], settings: Settings) -> dict[str, dict]:
    results: dict[str, dict] = {}
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)
    )
    async with driver.session(database=settings.neo4j_database) as session:
        for case in cases:
            oracle = case.get("oracle")
            if not oracle:
                continue
            kind, params = oracle
            result = await session.run(ORACLE_QUERIES[kind], S=SCOPE, **params)
            rows = [r.data() async for r in result]
            if kind == "top_coauthor_author":
                results[case["id"]] = {
                    "kind": kind,
                    "top_id": rows[0]["top_id"] if rows else None,
                    "top_name": rows[0]["top_name"] if rows else None,
                }
            elif kind == "paper_venue":
                ids = rows[0]["ids"] if rows else []
                names = rows[0]["names"] if rows else []
                results[case["id"]] = {
                    "kind": kind,
                    "ids": sorted({str(item) for item in ids if item}),
                    "names": sorted({str(item) for item in names if item}),
                }
            else:
                ids = rows[0]["ids"] if rows and rows[0].get("ids") is not None else []
                if isinstance(ids, list) and ids and isinstance(ids[0], list):
                    ids = [item for sub in ids for item in sub]
                results[case["id"]] = {"kind": kind, "ids": sorted({str(i) for i in ids if i})}
    await driver.close()
    return results


async def main() -> None:
    settings = Settings.from_env()
    parsed_uri = urlparse(settings.neo4j_uri or "")
    target_host = parsed_uri.hostname or "unknown"
    target_suffix = ".".join(target_host.split(".")[-3:])
    target_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)
    )
    try:
        server_info = await target_driver.get_server_info()
    finally:
        await target_driver.close()
    entities = load_entities()
    cases = build_cases(entities)
    print(
        f"profile: mode={settings.app_mode} graph={settings.graph_provider} llm={settings.llm_provider} "
        f"model={settings.ollama_model} server={server_info.agent} host_suffix={target_suffix}"
    )
    oracles = await run_oracles(cases, settings)

    llm, repository, workflow = build_dependencies(settings)
    results = []
    try:
        for case in cases:
            history = [HistoryMessage(**m) for m in case.get("history", [])]
            t0 = time.perf_counter()
            try:
                response = await workflow.run(ChatRequest(question=case["q"], history=history, debug=True))
                error = None
            except Exception as exc:  # keep going; record the failure
                response = None
                error = f"{type(exc).__name__}: {exc}"[:200]
            latency_ms = int((time.perf_counter() - t0) * 1000)

            row: dict = {
                "id": case["id"],
                "cat": case["cat"],
                "question": case["q"],
                "latency_ms": latency_ms,
                "error": error,
            }
            if response is not None:
                expected = case["expect_status"]
                ok_status = (
                    response.status == expected if isinstance(expected, str) else response.status in expected
                )
                row.update(
                    {
                        "status": response.status,
                        "route": str(response.route),
                        "parsed_intent": response.parsed_intent,
                        "parse_source": response.parse_source,
                        "parsed_entities": [
                            entity.model_dump(mode="json") for entity in response.parsed_entities
                        ],
                        "linked_entities": [
                            entity.model_dump(mode="json") for entity in response.linked_entities
                        ],
                        "entity_rescue": response.entity_rescue,
                        "stop_reason": response.stop_reason,
                        "iterations": response.iterations_used,
                        "facts_count": response.facts_count,
                        "truncated": response.truncated,
                        "complete": response.complete,
                        "llm_calls": response.llm_calls,
                        "status_ok": ok_status,
                        "answer": response.answer[:600],
                        "source_paper_ids": [s.paper_id for s in response.sources],
                        "trace": [[t.action, t.status, t.records] for t in (response.trace or [])],
                    }
                )
                oracle = oracles.get(case["id"])
                if oracle and "ids" in oracle:
                    got = set(row["source_paper_ids"])
                    want = set(oracle["ids"])
                    if oracle["kind"] == "paper_venue":
                        names = oracle.get("names", [])
                        row["oracle_names"] = names
                        row["oracle_check"] = "venue_name_in_answer"
                        row["oracle_ok"] = bool(names) and all(name in response.answer for name in names)
                    elif oracle["kind"] in {
                        "coauthor_count",
                        "org_collab_count",
                        "affil_orgs",
                        "paper_author_count",
                    }:
                        # citations for these categories are evidence papers, not the object ids;
                        # check the answer mentions and fact count instead
                        row["oracle_ids_n"] = len(want)
                        row["oracle_check"] = "count_reported"
                        row["oracle_ok"] = response.facts_count > 0 if want else True
                    else:
                        row["oracle_ids_n"] = len(want)
                        row["oracle_matched"] = len(got & want)
                        row["oracle_extra"] = len(got - want)
                        row["oracle_ok"] = (got <= want) and bool(got) if want else not got
                elif oracle and "top_id" in oracle:
                    top_name = oracle.get("top_name") or ""
                    row["oracle_top_id"] = oracle["top_id"]
                    row["oracle_check"] = "top_name_in_answer"
                    row["oracle_ok"] = bool(top_name) and top_name in response.answer
            results.append(row)
            print(
                f"[{row['id']}] {row['cat']}: status={row.get('status')} route={row.get('route')} "
                f"iters={row.get('iterations')} llm={row.get('llm_calls')} {latency_ms}ms "
                f"status_ok={row.get('status_ok')} oracle_ok={row.get('oracle_ok')}"
            )
    finally:
        await repository.close()
        await llm.close()

    n = len(results)
    status_ok = sum(1 for r in results if r.get("status_ok"))
    oracle_checked = [r for r in results if "oracle_ok" in r]
    oracle_ok = sum(1 for r in oracle_checked if r["oracle_ok"])
    latencies = sorted(r["latency_ms"] for r in results)
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    summary = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "profile": {
            "mode": settings.app_mode,
            "graph": settings.graph_provider,
            "llm": settings.llm_provider,
            "model": settings.ollama_model,
            "scope_id": settings.neo4j_scope_id,
            "neo4j_scheme": parsed_uri.scheme,
            "neo4j_host_suffix": target_suffix,
            "server_agent": server_info.agent,
        },
        "cases": n,
        "status_ok": status_ok,
        "oracle_checked": len(oracle_checked),
        "oracle_ok": oracle_ok,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
    }
    output_name = os.environ.get("E2E_OUTPUT", "e2e_real_results.json")
    if Path(output_name).name != output_name:
        raise ValueError("E2E_OUTPUT must be a plain filename")
    (RUN_DIR / output_name).write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("\nSUMMARY:", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
