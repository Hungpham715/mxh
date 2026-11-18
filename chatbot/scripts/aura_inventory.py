"""Read-only live Aura inventory for the configured scope (no secrets printed)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from graphrag.graph.neo4j_readonly import Neo4jReadOnlyRepository
from graphrag.settings import Settings


async def main(out_path: Path | None) -> int:
    settings = Settings.from_env()
    if settings.graph_provider != "neo4j":
        print("GRAPH_PROVIDER must be neo4j", file=sys.stderr)
        return 2
    repo = Neo4jReadOnlyRepository(
        uri=settings.neo4j_uri or "",
        username=settings.neo4j_username or "",
        password=settings.neo4j_password or "",
        database=settings.neo4j_database,
        scope_id=settings.neo4j_scope_id,
        cache_ttl_seconds=settings.entity_cache_ttl_seconds,
        timeout_seconds=settings.request_timeout_seconds,
    )
    try:
        await repo.driver.verify_connectivity()
        server = await repo.driver.get_server_info()
        ping = await repo._read("RETURN 1 AS ok", {})
        components = await repo._read(
            "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition", {}
        )
        preview = await repo.preview()
        scopes = await repo._read(
            "MATCH (n) RETURN n.scope_id AS scope, count(*) AS count ORDER BY count DESC", {}
        )
    finally:
        await repo.close()
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "verify_connectivity": True,
        "return_1": ping[0]["ok"] if ping else None,
        "server_agent": server.agent,
        "protocol_version": list(server.protocol_version),
        "components": components,
        "database": settings.neo4j_database,
        "scope_id": settings.neo4j_scope_id,
        "all_scopes_node_counts": scopes,
        "scoped_nodes": preview["nodes"],
        "scoped_relationships": preview["relationships"],
        "total_scoped_nodes": sum(preview["nodes"].values()),
        "total_scoped_relationships": sum(preview["relationships"].values()),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    print(text)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(asyncio.run(main(target)))
