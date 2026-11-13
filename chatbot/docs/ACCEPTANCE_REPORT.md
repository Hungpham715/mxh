# Acceptance report — 2026-11-13

## Outcome

The local fake product is **PASS**. Live Aura/Ollama, local PEFT adapter inference, and SFT training are
**NOT RUN** because their required external service, credentials, adapter, or approved training data are not
present. No fake result is counted as a live result.

## Commands actually run

| Gate | Command | Exit | Evidence |
|---|---|---:|---|
| Backend format/lint/test | `cd chatbot && uv run ruff format . && uv run ruff check . && uv run pytest` | 0 | `All checks passed`; final run `50 passed in 0.35s` |
| Fake environment | `cd chatbot && bash scripts/check_env.sh` | 0 | Python 3.13.12, uv/node/npm configured, profile `fake/fake/fake`; external values optional |
| Fake HTTP smoke | `cd chatbot && bash scripts/smoke_fake.sh` | 0 | health `ok`; `FAKE_SMOKE_PASS: health + 6 chat requests` |
| Frontend tests | `cd chatbot/ui && npm run test` | 0 | 1 test file, 2 tests passed |
| Frontend build | `cd chatbot/ui && npm run build` | 0 | TypeScript passed; Vite transformed 2,250 modules and built successfully |
| Local UI/API | `bash scripts/dev.sh`, then HTTP probes | 0 | UI 200 (849 bytes), API 200; all eight documented SSE event types observed |
| Browser smoke | headless Chrome 153 against `http://127.0.0.1:5173` | 0 | 90,887-byte screenshot; no browser `ERROR`/`SEVERE` log; fake watermark and connected state visible |
| Synthetic generation/eval | `cd chatbot && bash scripts/eval_synthetic.sh` | 0 | 12 candidate cases; report banner `SYNTHETIC SMOKE ONLY — NOT A BENCHMARK` |
| SFT dry-run | `uv run python training/train_sft.py --dry-run --config training/config_sft.yaml` | 0 | config valid; zero data; no torch/CUDA, weights, or optimizer used |
| Offline regression | `cd offline && uv run python -m pytest -o addopts=''` | 0 | 65 collected, 65 passed in 0.41s |
| Agent-document coverage | `python3 scripts/sync_agent_docs.py` plus filesystem validation | 0 | 59/59 current project-owned directories contain `AGENTS.md`; zero missing |
| Diff whitespace | `git diff --check` | 0 | no whitespace errors |
| Secret-pattern scan | scoped `rg` excluding local `.env` and vendor/generated trees | 0 | placeholder values only; no token/password value found |

Generated synthetic results reported query-template accuracy 0.75 and refusal accuracy 0.9167. These numbers are
fixture smoke diagnostics, not a quality claim; human-reviewed held-out evaluation remains required.

## Repaired issues found during acceptance

- Direct dataset entrypoints could not resolve the local package. Commands and notebooks now use
  `python -m datasets...` / `python -m evaluation...`.
- SSE now exposes `start`, `parse`, `linked`, `query_start`, `query_result`, `decision`, `answer`, and `done`.
- `offline/.venv/bin/pytest` has a stale absolute shebang from `/home/hung/Downloads/nlp-collab-graph`.
  The venv itself is valid; `uv run python -m pytest` avoids the stale launcher without deleting user state.
- The first raw `python3 scripts/check_env.py` probe lacked project dependencies. The documented and verified
  command is `bash scripts/check_env.sh`, which invokes the uv environment.

## Optional live gates

| Gate | Status | Evidence / exact next action |
|---|---|---|
| Aura Neo4j | NOT RUN | `.env` is the fake profile. Configure Profile B with a read-only user, then run `bash scripts/smoke_neo4j.sh`. |
| Ollama Qwen3 0.6B | NOT RUN | `ollama` is not installed. Install Ollama, run `ollama pull qwen3:0.6b`, start `ollama serve`, then run `bash scripts/smoke_ollama.sh`. |
| B2 local PEFT | NOT RUN | No `MODEL_ADAPTER_PATH` is configured. Set Profile C and run `uv run --extra hf python training/smoke_adapter.py`. |
| SFT train | NOT RUN | No human-approved train/val SFT file and no training environment dependencies. Review/split first, then use the Colab notebook or explicitly gated CLI. |

The laptop reports an RTX 5060 with 8,151 MiB, but hardware presence does not authorize training or replace
approved data. The dry-run intentionally reports torch/CUDA unavailable in the base chatbot environment.

## Produced deliverables

- Runtime: `src/graphrag/`, 12 read-only query templates, fake/Neo4j repositories, fake/Ollama/HF CPU providers,
  iterative workflow, evidence/citations, FastAPI JSON and POST-SSE endpoints.
- UI: local React/Vite/TypeScript chat, history, evidence, trace, dark/mobile modes, typed SSE client, sanitized
  Markdown, cancel and non-stream fallback.
- Data/evaluation/training: candidate/negative generation, CSV review round-trip, leakage-safe split, SFT export,
  executable evaluation/compare tools, shared guarded LoRA CLI, and two valid notebooks.
- Operations/docs: setup/dev/smoke scripts, environment checker, architecture/decisions/limitations/runbook,
  external repository audit, and this acceptance report.
- Agent instructions: per-directory `AGENTS.md` files and `scripts/sync_agent_docs.py`. Git metadata,
  tool caches, virtualenvs, `node_modules`, `dist`, and inspection-only external clones are deliberately excluded.

## Reproduce the passing local profile

```bash
cd /home/hung/YEAR_4/MXH/GraphRAG/chatbot
cp .env.example .env                 # only if no local .env exists
bash scripts/setup.sh
bash scripts/check_env.sh
bash scripts/smoke_fake.sh
uv run ruff check .
uv run pytest
npm --prefix ui run test
npm --prefix ui run build
bash scripts/eval_synthetic.sh
uv run python training/train_sft.py --dry-run --config training/config_sft.yaml
bash scripts/dev.sh
```

Open `http://127.0.0.1:5173`. Keep the visible `SIMULATED — no real LLM/DB` watermark when using this profile.
