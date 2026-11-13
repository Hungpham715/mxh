"""Neo4j repository that executes only the reviewed read-only catalog."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from graphrag.cypher_templates import get_template
from graphrag.graph.base import EntityRecord, GraphQueryResult
from graphrag.models import QueryStep


class Neo4jReadOnlyRepository:
    name = "neo4j"

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str,
        scope_id: str,
        cache_ttl_seconds: int,
        timeout_seconds: float,
    ) -> None:
        try:
            import neo4j
            from neo4j import AsyncGraphDatabase
        except ImportError as error:
            raise RuntimeError("Install the Neo4j driver with `uv sync`") from error
        self._neo4j = neo4j
        self.driver = AsyncGraphDatabase.driver(uri, auth=(username, password), connection_timeout=30)
        self.database = database
        self.scope_id = scope_id
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._catalog: list[EntityRecord] = []
        self._catalog_loaded_at = 0.0
        self._catalog_lock = asyncio.Lock()

    async def entity_catalog(self, *, force_refresh: bool = False) -> list[EntityRecord]:
        is_fresh = time.monotonic() - self._catalog_loaded_at < self.cache_ttl_seconds
        if self._catalog and is_fresh and not force_refresh:
            return list(self._catalog)

        async with self._catalog_lock:
            is_fresh = time.monotonic() - self._catalog_loaded_at < self.cache_ttl_seconds
            if self._catalog and is_fresh and not force_refresh:
                return list(self._catalog)
            query = """
            MATCH (n) WHERE n.scope_id = $scope
              AND any(label IN labels(n) WHERE label IN ['Author','Paper','Institution','Venue','Topic'])
            RETURN n.id AS id, labels(n)[0] AS label,
              coalesce(n.name, n.title, n.id) AS name, n.identity_status AS identity_status
            ORDER BY label, name, id
            """
            records = await self._read(query, {"scope": self.scope_id})
            self._catalog = [
                EntityRecord(
                    id=str(record["id"]),
                    label=str(record["label"]),
                    name=str(record["name"]),
                    identity_status=record.get("identity_status"),
                )
                for record in records
            ]
            self._catalog_loaded_at = time.monotonic()
            return list(self._catalog)

    async def execute(self, step: QueryStep) -> GraphQueryResult:
        template = get_template(step.action)
        missing = template.required_params - step.params.keys()
        if missing:
            raise ValueError(f"missing parameters for {step.action}: {sorted(missing)}")
        params = {
            **step.params,
            "scope": self.scope_id,
            "limit": min(step.limit, 100),
            "year_from": step.params.get("year_from"),
            "year_to": step.params.get("year_to"),
            "direction": step.params.get("direction", "both"),
        }
        records = await self._read(template.cypher, params)
        return GraphQueryResult(records=records, truncated=len(records) >= step.limit)

    async def _read(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        @self._neo4j.unit_of_work(timeout=self.timeout_seconds, metadata={"app": "mxh-graphrag"})
        async def run_query(transaction: Any) -> list[dict[str, Any]]:
            result = await transaction.run(query, params)
            return [dict(record) async for record in result]

        async with self.driver.session(
            database=self.database,
            default_access_mode=self._neo4j.READ_ACCESS,
        ) as session:
            return await session.execute_read(run_query)

    async def health(self) -> tuple[bool, str]:
        try:
            await self.driver.verify_connectivity()
            records = await self._read(
                "MATCH (n) WHERE n.scope_id = $scope RETURN count(n) AS count",
                {"scope": self.scope_id},
            )
        except Exception as error:
            return False, f"Neo4j unavailable: {type(error).__name__}"
        count = records[0]["count"] if records else 0
        return True, f"connected; {count} nodes in scope"

    async def preview(self) -> dict[str, Any]:
        label_rows = await self._read(
            "MATCH (n) WHERE n.scope_id = $scope "
            "UNWIND labels(n) AS label "
            "RETURN label, count(*) AS count ORDER BY label",
            {"scope": self.scope_id},
        )
        relation_rows = await self._read(
            "MATCH ()-[r]->() WHERE r.scope_id = $scope "
            "RETURN type(r) AS type, count(*) AS count ORDER BY type",
            {"scope": self.scope_id},
        )
        return {
            "nodes": {row["label"]: row["count"] for row in label_rows},
            "relationships": {row["type"]: row["count"] for row in relation_rows},
            "scope_id": self.scope_id,
        }

    async def close(self) -> None:
        await self.driver.close()
