# NEEDS_CREDENTIALS (RESOLVED 2026-11-03: .env present, AuraDB import done)

Status: Neo4j AuraDB steps are BLOCKED until a local `.env` exists. Everything else ran on real data.

Create `D:\nlp-collab-graph\.env` yourself (copy `.env.example`) with these variable names:

    NEO4J_URI=neo4j+s://<instance>.databases.neo4j.io
    NEO4J_USERNAME=neo4j
    NEO4J_PASSWORD=<secret>
    NEO4J_DATABASE=neo4j
    AURA_INSTANCEID=<optional>
    AURA_INSTANCENAME=<optional>
    OPENALEX_API_KEY=<secret>        # optional: the corpus was already fetched without a key and is cached
    OPENALEX_BASE_URL=https://api.openalex.org

Then run (read-only check first, then the import):

    uv run python -m src.cli preflight
    uv run python -m src.cli import --data data/processed
    uv run python -m src.cli idempotency --data data/processed
    uv run python -m src.cli queries
    uv run python -m src.cli analyze --source neo4j
    uv run python -m src.cli report --out report/final.pdf

`.env` is in `.gitignore`. Secrets are never printed: logs pass through `scrub()` and the loader only reads them via
`os.environ`. If credentials were ever pasted into a chat or a file, rotate them first.
