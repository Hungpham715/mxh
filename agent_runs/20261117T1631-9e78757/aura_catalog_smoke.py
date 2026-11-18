"""Execute every catalogued read-only action against the configured Aura scope."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from neo4j import AsyncGraphDatabase

from graphrag.factory import build_dependencies
from graphrag.models import QueryAction, QueryStep
from graphrag.planner import EXPECTED_FIELDS
from graphrag.settings import Settings

RUN_DIR = Path(__file__).resolve().parent


def build_steps(entities: dict) -> list[QueryStep]:
    affiliation_author_id = entities["affil_author"][0]["id"]
    connected_author_id = entities["big_coauthor_author"][0]["id"]
    pair = entities["coauthor_pair"][0]
    paper_id = entities["venue_paper"][0]["id"]
    return [
        QueryStep(
            action=QueryAction.AUTHOR_PAPERS,
            params={"author_id": connected_author_id, "year_from": None, "year_to": None},
            expected_fields=EXPECTED_FIELDS[QueryAction.AUTHOR_PAPERS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.COAUTHORS,
            params={"author_id": connected_author_id},
            expected_fields=EXPECTED_FIELDS[QueryAction.COAUTHORS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.SHARED_PAPERS,
            params={"author_id": pair["aid"], "other_author_id": pair["bid"]},
            expected_fields=EXPECTED_FIELDS[QueryAction.SHARED_PAPERS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.AUTHOR_AFFILIATIONS,
            params={"author_id": affiliation_author_id},
            expected_fields=EXPECTED_FIELDS[QueryAction.AUTHOR_AFFILIATIONS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.COAUTHOR_AFFILIATIONS,
            params={"author_id": connected_author_id},
            expected_fields=EXPECTED_FIELDS[QueryAction.COAUTHOR_AFFILIATIONS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.PAPER_AUTHORS,
            params={"paper_id": paper_id},
            expected_fields=EXPECTED_FIELDS[QueryAction.PAPER_AUTHORS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.TOPIC_PAPERS,
            params={
                "topic_id": entities["topics"][0]["id"],
                "year_from": None,
                "year_to": None,
            },
            expected_fields=EXPECTED_FIELDS[QueryAction.TOPIC_PAPERS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.PAPER_VENUE,
            params={"paper_id": paper_id},
            expected_fields=EXPECTED_FIELDS[QueryAction.PAPER_VENUE],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.PAPER_CITATIONS,
            params={"paper_id": entities["cited_paper"][0]["id"], "direction": "both"},
            expected_fields=EXPECTED_FIELDS[QueryAction.PAPER_CITATIONS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.ORG_COLLABORATIONS,
            params={"institution_id": entities["top_org"][0]["id"]},
            expected_fields=EXPECTED_FIELDS[QueryAction.ORG_COLLABORATIONS],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.AUTHOR_PATH,
            params={"author_id": pair["aid"], "other_author_id": pair["bid"]},
            expected_fields=EXPECTED_FIELDS[QueryAction.AUTHOR_PATH],
            limit=5,
        ),
        QueryStep(
            action=QueryAction.NETWORK_TOP,
            params={},
            expected_fields=EXPECTED_FIELDS[QueryAction.NETWORK_TOP],
            limit=5,
        ),
    ]


async def main() -> None:
    settings = Settings.from_env()
    parsed = urlparse(settings.neo4j_uri or "")
    host = parsed.hostname or "unknown"
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password)
    )
    try:
        server_info = await driver.get_server_info()
    finally:
        await driver.close()

    entities_path = RUN_DIR / "live_entities.json"
    entities = json.loads(entities_path.read_text(encoding="utf-8"))
    llm, repository, _ = build_dependencies(settings)
    results: list[dict] = []
    try:
        ready, health_detail = await repository.health()
        preview = await repository.preview()
        for step in build_steps(entities):
            query_result = await repository.execute(step)
            first = query_result.records[0] if query_result.records else {}
            results.append(
                {
                    "action": step.action.value,
                    "records": len(query_result.records),
                    "truncated": query_result.truncated,
                    "first_predicate": first.get("predicate"),
                    "first_paper_ids": first.get("paper_ids", []),
                    "first_source_url": first.get("source_url"),
                    "pass": bool(query_result.records),
                }
            )
    finally:
        await repository.close()
        await llm.close()

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "profile": {
            "mode": settings.app_mode,
            "graph": settings.graph_provider,
            "neo4j_scheme": parsed.scheme,
            "neo4j_host_suffix": ".".join(host.split(".")[-3:]),
            "server_agent": server_info.agent,
            "database": settings.neo4j_database,
            "scope_id": settings.neo4j_scope_id,
        },
        "entities_input_sha256": hashlib.sha256(entities_path.read_bytes()).hexdigest(),
        "health": {"ready": ready, "detail": health_detail},
        "preview": preview,
        "actions": results,
        "actions_passed": sum(row["pass"] for row in results),
        "actions_total": len(results),
        "pass": ready and len(results) == len(QueryAction) and all(row["pass"] for row in results),
    }
    output_path = RUN_DIR / "aura_catalog_smoke.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
