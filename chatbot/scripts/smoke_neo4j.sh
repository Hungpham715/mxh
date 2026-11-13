#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python - <<'PY'
import asyncio
from graphrag.factory import build_dependencies
from graphrag.settings import Settings

async def main():
    settings = Settings.from_env()
    if settings.graph_provider != "neo4j":
        print("NEO4J NOT RUN: configure the real Neo4j profile in chatbot/.env")
        raise SystemExit(2)
    llm, repository, _ = build_dependencies(settings)
    try:
        ok, detail = await repository.health()
        print({"ready": ok, "detail": detail})
        if not ok:
            raise SystemExit(2)
        print(await repository.preview())
    finally:
        await repository.close()
        await llm.close()

asyncio.run(main())
PY

