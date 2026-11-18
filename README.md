# MXH — NLP author/institution network (graph) + GraphRAG chatbot

Course project “Mạng lưới các tác giả và tổ chức nghiên cứu về NLP quốc tế”.
GitHub: https://github.com/Hungpham715/mxh

| Folder | What it is |
|---|---|
| `offline/` | Crawl ACL Anthology + arXiv cs.CL + OpenAlex → 8 JSONL tables → 10 relation types → Neo4j (scoped `nlpgraph-v1`), analysis, quality audits, PDF report |
| `chatbot/` | FastAPI + React GraphRAG chatbot (Qwen3-0.6B on CPU via Ollama, 12 read-only Cypher actions) + QA dataset + evaluation |
| `reports/` | Generated audit reports (`graph_audit/`, `data_coverage.md`) |
| `agent_runs/<run>/` | Evidence of each verification run (preflight, baseline, state, final acceptance) |
| `undone.md` | What is still blocked/deferred, with exact next commands |

Current status and gates: see [`undone.md`](undone.md) and the latest `agent_runs/*/FINAL_ACCEPTANCE.md`.

## 1. Setup (clean machine, no admin rights)

Requirements: Python ≥ 3.12 via [uv](https://docs.astral.sh/uv/), Node ≥ 20, Git. Optional: Ollama (CPU) and a
Neo4j/AuraDB instance.

```bash
cd offline && uv sync && uv run python -m pytest -q -o addopts='' && cd ..
cd chatbot && uv sync && uv run pytest -q && uv run ruff check . && cd ..
cd chatbot/ui && npm ci && npm run test && npm run build && cd ../..
```

## 2. Environment (values stay local; never commit `.env`)

Copy `chatbot/.env.example` → `chatbot/.env` and `offline/.env.example` → `offline/.env`. Keys only:
`APP_MODE, GRAPH_PROVIDER, LLM_PROVIDER, OLLAMA_BASE_URL, OLLAMA_MODEL, NEO4J_URI, NEO4J_USERNAME,
NEO4J_PASSWORD, NEO4J_DATABASE, NEO4J_SCOPE_ID=nlpgraph-v1, LANGSMITH_TRACING=false`. Use a read-only Neo4j user
for the chatbot. Rotate any credential that was ever pasted in a chat or document.

## 3. Launch and ask real questions

```bash
ollama pull qwen3:0.6b          # public model, no login
cd chatbot
bash scripts/check_env.sh && bash scripts/smoke_neo4j.sh && bash scripts/smoke_ollama.sh
bash scripts/dev.sh             # API 127.0.0.1:8000, UI http://localhost:5173
uv run python scripts/ask.py "Maosong Sun có những bài báo nào trong corpus?"
```

If Aura is unreachable, `APP_MODE=snapshot GRAPH_PROVIDER=snapshot LLM_PROVIDER=ollama` runs the real model over
the verified local JSONL snapshot (watermarked `LOCAL SNAPSHOT`; not evidence about Aura).

## 4. Evaluate the graph

```bash
cd offline
uv run python -m src.cli validate                 # contract + checksums
uv run python -m src.cli import --dry-run         # re-derive the 10 edge types, no DB writes
uv run python -m src.cli integrity                # census: every node and edge (reports/graph_audit/)
uv run python -m src.cli coverage                 # selected-subset vs eligible-universe coverage
uv run python -m src.cli truth-sample             # blind stratified review sheet over all 10 edge types
# reviewers fill reports/graph_audit/g3_review_sheet_blind.csv (label, reviewer, reviewed_at_utc, ...)
uv run python -m src.cli truth-score              # weighted accuracy + 95% CI; PASS needs lower bound > 0.90
```

## 5. QA benchmark

See `chatbot/README.md` (“Large silver dataset + real evaluation”). Reports land in `chatbot/reports/eval/*`
(`summary.md`, `summary.json`, per-case `predictions.jsonl`).

## 6. Resume an interrupted run

```bash
bash scripts/agent_resume.sh            # all phases; finished evaluation cases are skipped
bash scripts/agent_resume.sh eval-b1    # one phase
```

## Troubleshooting

- **Ollama on CPU** — first call loads the model (~2 s). Limit threads on shared machines with
  `OLLAMA_NUM_THREAD=<half your cores>`. `llama-server binary not found` means the `lib/ollama` folder of the
  release zip was not extracted next to `ollama.exe`.
- **Aura TLS / routing** — `ServiceUnavailable: Unable to retrieve routing information` right after a successful TLS
  handshake usually means the AuraDB instance is paused: resume it in the Aura console (owner login), then rerun
  `uv run python scripts/aura_inventory.py`. Use `neo4j+s://` URIs; do not disable certificate checks.
- **Ubuntu** — same commands; install uv with your package manager or `pipx install uv`; Ollama provides a Linux
  tarball that runs from a user directory (`ollama serve` on `127.0.0.1`).
- **Windows console encoding** — set `PYTHONIOENCODING=utf-8` before scripts that print Vietnamese text.
