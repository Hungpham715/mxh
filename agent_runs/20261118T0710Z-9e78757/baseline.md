# Baseline audit (Phase A) — HEAD 9e78757

Tags: OBSERVED_LIVE = measured in this run; FROM_REPO_ARTIFACT = read from a committed file; NOT_VERIFIED.

## Baseline tests at HEAD (before any change)
| Suite | Command | Result | Log |
|---|---|---|---|
| offline | `cd offline && uv run python -m pytest -o addopts=''` | 72 passed | `baseline_offline_tests.log` |
| chatbot | `cd chatbot && uv run pytest -q && uv run ruff check .` | 53 passed, ruff clean | `baseline_chatbot_tests.log` |
| UI | `cd chatbot/ui && npm ci && npm run test && npm run build` | 2 tests passed, build OK | `baseline_ui.log` |

## Graph counts: recorded vs measured
| Source | Nodes | Relationships | Types | Tag |
|---|---|---|---|---|
| `offline/data/processed/manifest.json` + re-derived edges (this run) | 7,134 | 30,971 | 10/10 | OBSERVED_LIVE (local snapshot) |
| `offline/evaluation/sampling/sampling_meta.json` (Aura counts, 2026-11-03) | 7,134 | 30,971 | 10/10 | FROM_REPO_ARTIFACT |
| Live AuraDB today | — | — | — | NOT_VERIFIED (instance unreachable) |

## Findings at HEAD (verified against code, not copied from the prompt)
| # | Finding | Status at HEAD | Tag |
|---|---|---|---|
| 1 | Committed `offline/data/derived/edges_*.jsonl` contained **fixture** edges (3 CITES, 4 COAUTHORED…) instead of the real 30,971 edges: the offline tests wrote into the real `data/derived` and `data/rejected` folders. | Bug (fixed in this run) | OBSERVED_LIVE |
| 2 | Workflow executed a fixed plan (max 2 steps), no observation-driven replanning. | Confirmed (fixed) | OBSERVED_LIVE |
| 3 | `truncated = len(records) >= limit`; exactly 20 rows were reported truncated and 21+ rows silently cut; no total count; `complete` ignored truncation. | Confirmed (fixed: N+1 fetch + COUNT) | OBSERVED_LIVE |
| 4 | UI kept history in localStorage only; API accepted `history` but never used it. | Confirmed (fixed) | OBSERVED_LIVE |
| 5 | SSE replayed trace events after `workflow.run` had finished. | Confirmed (fixed: live queue) | OBSERVED_LIVE |
| 6 | `evaluation/metrics.py` hardcoded `json_validity=1.0`; most metrics `not_measured`. | Confirmed (fixed) | OBSERVED_LIVE |
| 7 | Only 12 synthetic candidates; no large dataset. | Confirmed (10,619 candidates now) | OBSERVED_LIVE |
| 8 | Notebook/trainer schema `prompt/completion` vs `messages`. | **Already fixed at HEAD** (trainer and notebook use `messages`); PARSE user message did not match runtime (fixed) | OBSERVED_LIVE |
| 9 | G3 review sheets (150 + 30 rows, 3 edge types) unlabeled; `scores_postfix.json` ≈ 0.8895 is an automated estimate. | Confirmed; new 10-type blind sheet created; still no human labels | OBSERVED_LIVE |
| 10 | `ChatRequest.history` accepted arbitrary roles (system spoofing). | Fixed: only `user`/`assistant` | OBSERVED_LIVE |

## Scope decision
Kept the declared scope unchanged (`offline/configs/scope.yaml`: 2023–2025, six ACL/EMNLP main volumes × 140 systematic sample + arXiv cs.CL 7/month). No re-crawl was needed for G1 counts; the selected-subset vs eligible-universe coverage is reported in `reports/data_coverage.md`.
