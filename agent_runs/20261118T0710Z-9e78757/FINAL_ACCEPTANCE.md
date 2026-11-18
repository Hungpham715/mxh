# FINAL ACCEPTANCE — run 20261118T0710Z-9e78757

STATUS: INCOMPLETE
GATES: G0 PASS · G1 PASS(snapshot)/Aura NOT VERIFIED · G2 PASS(snapshot census) · G3 BLOCKED · G4 BLOCKED · G5 PARTIAL(real Qwen, snapshot graph) · G6 BLOCKED(gold=0) · G7 BLOCKED(silver only) · G8 PASS except push (see below)
NEXT ACTION: owner resumes AuraDB (and rotates its password) → `cd chatbot && uv run python scripts/aura_inventory.py`; reviewers label `reports/graph_audit/g3_review_sheet_blind.csv`.

## Graph
- Snapshot: 7,134 nodes (Paper 1,091 · Author 5,430 · Institution 600 · Venue 7 · Topic 6), 30,971 relationships, 10/10 types (FIRST_AUTHOR_OF 1,091 · OTHER_AUTHOR_OF 5,007 · COAUTHORED_WITH 16,754 · AFFILIATED_WITH 4,306 · APPEARS_IN 1,091 · HAS_TOPIC 451 · CITES 26 · ORG_COAUTHORED_WITH 2,001 · RESEARCHES 105 · ACTIVE_IN 139). Manifest sha256 `c2c3f94e…32f1`.
- Live Aura counts: NOT VERIFIED (unreachable). The 2026-11-03 artefact `offline/evaluation/sampling/sampling_meta.json` recorded identical Aura counts (FROM_REPO_ARTIFACT, not re-verified).
- Integrity census: 0 critical, 2 warnings (in-corpus citation of a newer paper).
- Graph truth (>90%): **NOT VERIFIED** — point estimate / CI / labels: none (0 independent labels). The old automated 88.95% is not evidence.

## Chatbot (REAL vs SYNTHETIC vs NOT RUN)
| Item | Kind | Result |
|---|---|---|
| Qwen3-0.6B via Ollama 0.40.16 on CPU | REAL | working; p50 ≈ 4.7 s/question |
| Neo4j/Aura queries | NOT RUN | Aura unreachable; Cypher templates unit-tested only |
| B1 iterative, 300 silver test cases, snapshot graph | REAL LLM + LOCAL SNAPSHOT | status 0.960, route 0.973, intent 0.884, entity link 0.961, result set-F1 0.908, citation precision 0.991, count exact 0.923 (n=13), OOS refusal 1.0 (n=4), false refusal 0.007, ambiguity 1.0 (n=86), complete-flag honest 1.0, p50/p95 4.7/10.9 s, 0 errors |
| B0 one-step, same 300 cases | REAL LLM + LOCAL SNAPSHOT | ≈ B1 (single-action questions); p95 8.8 s |
| API E2E (POST + SSE + 4-turn conversation + more + cancel) | REAL LLM + LOCAL SNAPSHOT | 28/28 after one fix found on this set (pronoun phrase treated as an entity) — integration evidence, not a benchmark |
| B2 SFT | NOT RUN (GPU deferred) | — |
| Fake/synthetic smoke | SYNTHETIC | tests only, never counted |

## Tests / lint / build (this run, after all changes)
- offline: 80 passed (`final_offline_tests.log`)
- chatbot: 71 passed, ruff check + format clean (`final_chatbot_tests.log`)
- UI: 4 tests passed, `tsc -b && vite build` OK (`final_ui.log`)

## Files
- Commits on `agent/mxh-real-20261118-9e78757`: offline phase, chatbot phase, docs/evidence phase (`git log main..HEAD`).
- Key new files: `offline/src/evaluation/integrity_all.py`, `truth_audit.py`, `offline/src/analysis/coverage.py`, `chatbot/src/graphrag/graph/snapshot_graph.py`, `chatbot/datasets/build_large.py`, `chatbot/scripts/e2e_api.py`, `chatbot/scripts/aura_inventory.py`, `scripts/agent_resume.sh`, `README.md`, `undone.md`.
- Report: `offline/report/final.pdf` (15 pages; chapters 8–9 added from artefacts). The member work split in the report was not changed (no confirmation available in this run).

## Resume
`bash scripts/agent_resume.sh`
