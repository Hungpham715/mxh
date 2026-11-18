# Preflight — run 20261118T0710Z-9e78757

Recorded 2026-11-18 (UTC+7 local). No secret values are written here.

## Workspace and Git
| Item | Value | Tag |
|---|---|---|
| Repo root | `C:/Users/ADMIN/Downloads/cc/GraphRAG` | OBSERVED_LIVE |
| Remote `origin` | `github.com/Hungpham715/mxh` (no token in URL) | OBSERVED_LIVE |
| Start branch / SHA | `main` @ `9e78757086fc281ba5d9f5f1ab28cc1f31ab5d8a` | OBSERVED_LIVE |
| Work branch | `agent/mxh-real-20261118-9e78757` (created, `main` untouched) | OBSERVED_LIVE |
| Pre-existing uncommitted changes | file-mode-only diffs in `chatbot/scripts/*.sh`, `scripts/sync_agent_docs.py`; deleted `online/` placeholder; untracked `prompt.md`. Left untouched, not staged. | OBSERVED_LIVE |

## Runtime
| Tool | Version | Notes |
|---|---|---|
| OS | Windows 11 Home 10.0.26300 | Git Bash shell |
| CPU | 20 logical cores | long jobs capped at 10 threads (`OLLAMA_NUM_THREAD=10`) |
| Disk free | 12 GB at start → 17 GB after cleanup | downloads kept under `.tools/` (git-ignored) |
| Python | 3.13 (uv-managed, per-project `.venv`) | no system Python changes |
| uv | 0.11.1 | |
| Node / npm | 24.18.0 / 11.16.0 | `npm ci` inside `chatbot/ui` only |
| neo4j driver / FastAPI / Pydantic | 6.4.1 / 0.162.5 / 2.14.3 | from `chatbot/uv.lock` |
| Ollama | 0.40.16 portable, CPU libs only, official GitHub release zip, SHA-256 verified against the release `sha256sum.txt` (`50fcf5ad…a64e`); served on `127.0.0.1:11434` from `.tools/ollama` | user-space, no installer, no service |
| Model | `qwen3:0.6b` (Q4_K_M, 523 MB, digest `7df6b6e0…a435`) pulled without login | |
| GPU | not used (out of scope) | |

## External services
| Service | Result | Tag |
|---|---|---|
| Neo4j AuraDB (`NEO4J_URI` from `chatbot/.env`, same host as `offline/.env`) | DNS resolves; TLS handshake verifies, then the server resets the connection (`errno 10054`) on every attempt (3/3, sandboxed and unsandboxed); driver: `ServiceUnavailable: Unable to retrieve routing information`. Pattern matches a paused/stopped Aura instance. Resuming requires the owner's Aura console login → **BLOCKED** | OBSERVED_LIVE |
| OpenAlex API | HTTP 200 | OBSERVED_LIVE |
| GitHub API | anonymous rate limit exceeded (release lookup only) | OBSERVED_LIVE |

## Credentials policy applied
- Only `.env` files already present in the project were read, and only key names / host hash were printed.
- No credential was copied, created, rotated or tested by guessing. The owner should rotate any credential that was ever shared publicly.
- `LANGSMITH_TRACING=false` respected; no telemetry added.

## Actions that were refused by the local permission classifier (not worked around)
- Setting an initial password on, and starting, a portable local Neo4j Community 5.26.16 (downloaded + SHA-256 verified) to execute the Cypher catalog against real data. Left unconfigured in `.tools/` (git-ignored). Needs explicit owner permission.
