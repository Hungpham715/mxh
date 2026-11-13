# Operations

## Local development

```bash
cp .env.example .env
bash scripts/setup.sh
bash scripts/check_env.sh
bash scripts/dev.sh
```

API: `http://127.0.0.1:8000`; UI: `http://127.0.0.1:5173`. Stop both with Ctrl+C. Conversation history is
browser localStorage only and is capped at 30 conversations; the server does not claim persistent memory.

## Troubleshooting

- Ollama unreachable: run `ollama serve`, then `ollama pull qwen3:0.6b`.
- Aura TLS/connect timeout: verify URI, database, rotated password, outbound network, and read-only role.
- Model memory shortage: keep the 0.6B baseline, reduce generation limits, or return to fake mode; do not silently fallback.
- Adapter error: validate `adapter_config.json` and weights with `training/smoke_adapter.py` before enabling it.
- Data mismatch: compare live scoped label/relation inventory with `offline/output/neo4j/import_report_latest.json`.
- Port conflict: set `API_PORT`/`WEB_PORT`; the smoke uses `SMOKE_API_PORT=8011` by default.

## Safety

The live repository executes only catalog templates and never performs schema/data mutations. Do not grant the
chatbot write privileges. Never commit `.env`, model weights, review exports containing private data, or nested
external repositories.

