# Preflight — run 20261117T1631-9e78757

UTC: 2026-11-17T16:46Z | Host workspace: /home/hung/YEAR_4/MXH/GraphRAG | Branch: agent/mxh-real-20261117-9e78757 | Base SHA: 9e78757086fc281ba5d9f5f1ab28cc1f31ab5d8a

## Machine (OBSERVED_LIVE)

- CPU: 20 logical cores. Policy: max ~10-12 cores for long jobs.
- RAM: 15Gi total, ~6.3Gi available at start.
- Disk: /home (nvme0n1p5) 238G total, **4.5G free (99% used) — tight**; / (nvme0n1p7, holds /tmp) **16G free** → large downloads go to /tmp, extracted artifacts sized before moving to /home.
- OS: Linux 7.0.0-43-generic, Ubuntu user `hung` (repo owner's machine; no sudo used or needed).

## Runtimes (OBSERVED_LIVE)

- Python 3.12.3 (system), uv 0.11.1 (~/.local/bin/uv), Node v22.22.2 (nvm), npm 10.9.7, git 2.43.0, Java 21.0.12 (system, /usr/bin/java).
- Project venvs present and in sync: offline/.venv (Python 3.13.12 via uv), chatbot/.venv (Python 3.13.12), chatbot/ui/node_modules present.
- **Ollama: NOT installed**, no ~/.ollama, port 11434 down (OBSERVED_LIVE).
- HF cache (~/.cache/huggingface, 4.7G) contains `models--Qwen--Qwen3-0.6B`. Trained LoRA adapter present at `chatbot/data/models/qwen3-06b-graphrag-lora` (431M, adapter_config.json + adapter_model.safetensors + tokenizer) (OBSERVED_LIVE).
- uv cache 9.7G (owner's; not touched).

## Git state (OBSERVED_LIVE)

- origin = https://github.com/Hungpham715/mxh.git (token-free URL), HEAD 9e78757, was on `main`; created and switched to `agent/mxh-real-20261117-9e78757`.
- Pre-existing uncommitted changes NOT made by this run: `D online/.gitkeep`, `D online/AGENTS.md` (deleted, unstaged), `?? prompt.md`. Left untouched (no reset/clean/stash).
- No `.env` tracked in git (git ls-files check = 0). `.gitignore` covers chatbot/.env, offline/.gitignore covers offline/.env, and chatbot data/generated|reviewed|splits|models, reports.

## Credentials (presence only — values never printed)

- chatbot/.env: APP_MODE=real, GRAPH_PROVIDER=neo4j, LLM_PROVIDER=ollama, OLLAMA_MODEL len 10 (qwen3:0.6b), NEO4J_URI/USERNAME/PASSWORD/DATABASE all SET, LANGSMITH_API_KEY SET, HUGGING_FACE_TOKEN SET. **NEO4J_SCOPE_ID absent from .env** → Settings default `nlpgraph-v1` applies (verified in settings.py:36).
- offline/.env: NEO4J_* SET, OPENALEX_API_KEY SET, OPENALEX_BASE_URL SET.
- Per prompt policy these are treated as owner-provided; nothing copied anywhere, nothing echoed.

## Network probes (OBSERVED_LIVE 16:33-16:44Z)

- api.openalex.org: HTTP 200 (internet OK).
- AuraDB (neo4j+s, instance 702feb94…): TCP 7687 OPEN (LB answers) but **routing retrieval fails**; bolt+s gets ConnectionReset after TLS. 6 verify_connectivity attempts over ~5.5 min (backoff 20/30/60/90/120s, connection_timeout 60-90s) all `ServiceUnavailable: Unable to retrieve routing information`. Pattern = **Aura Free instance auto-paused/stopped** (last known live use 2026-11-13/14 per repo artifacts; Free tier pauses after ~3 days idle). Resume requires owner login at console.neo4j.io → **G4 BLOCKED (owner action)**, no fake fallback.

## Disk-safety decisions

- Ollama user-space install: attempt via /tmp download + selective extract (bin + CPU runners only, no CUDA libs). Abort if /home free < 1.2G at any step.
- Neo4j local Community: feasible (Java 21 present, tarball ~140MB) as a clearly-labelled NOT-Aura real graph target for chatbot E2E/dataset generation while Aura is paused.
- No crawling of new bulk sources unless remaining phases prove the snapshot insufficient for G6; /home budget reserved for evidence/artifacts.
