# MXH — Undone / Deferred / Blocked
Last updated: 2026-11-18T13:53:06Z
Run ID: 20261117T1631-9e78757 | Git branch: `agent/mxh-real-20261117-9e78757` | Graph snapshot hash: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`
Overall status: INCOMPLETE

## Gate status
| Gate | PASS/FAIL/BLOCKED/DEFERRED | Evidence path | Blocker |
|---|---|---|---|
| G0 | PASS | `agent_runs/20261117T1631-9e78757/preflight.md`; staged diff/secret scan | Unrelated `online/` deletions and `prompt.md` remain outside commits |
| G1 | PASS | `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json` | Live Aura has 7,134 nodes, 30,971 relationships and all ten relationship types |
| G2 | PASS | `offline/reports/graph_audit/integrity_all.json` | 100% structural census, zero errors |
| G3 | BLOCKED | `offline/evaluation/manual_review_template_truth_v2.csv`; `offline/reports/graph_audit/quality_report.md` | Independent human labels 0/386; automated diagnostic is not gold and is below threshold |
| G4 | PASS | `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json` | `Neo4j/5.27-aura`; live counts match; 12/12 read-only actions PASS |
| G5 | PASS | `api_aura_smoke.json`; `e2e_aura_results.json` | Real Aura/Ollama: API matrix 8/8, POST/SSE match, E2E 31/31 status and 21/21 oracle |
| G6 | BLOCKED | `chatbot/data/splits/manifest_v2.json`; `chatbot/data/generated/human_gold_review_v2.csv` | 11,998 silver rows are complete; independent human gold remains 0/500 |
| G7 | BLOCKED | `agent_runs/20261117T1631-9e78757/e2e_aura_results.json` | 31-case diagnostic passes, but official >=300-case independent gold benchmark cannot run without G6 labels |
| G8 | PASS | `offline/report/final.pdf`; addendum; test/build evidence; pushed feature branch | — |

## Work remaining (ordered by dependency)

### G3-GOLD Independent graph-truth review
- Status: NEEDS_HUMAN_REVIEW
- Why not done: the 386 decisions are intentionally blank; the prompt forbids same-pipeline automated labels from being represented as independent gold.
- Input available: `offline/evaluation/manual_review_template_truth_v2.csv`, guideline, seed/strata manifest and scorer; automated diagnostic 0.8802 [0.8548, 0.9017].
- Exact next command/action: an independent reviewer fills the template without inspecting auto labels, then runs `cd offline && uv run python -m src.cli score --labels evaluation/manual_review_template_truth_v2.csv --tag truth_v2`.
- Acceptance test required: all ten relationship types covered; weighted point estimate >0.90 and lower 95% confidence bound >0.90; reviewer, UTC timestamp, source URL and decision present.
- Can proceed without it? No for G3 or a verified `>90%` graph-truth claim.
- Attempts/retry-at: one reproducible 386-row probability sample generated with seed 20261118; automatic retry does not create independent evidence.
- Owner action, only if genuinely unavoidable: assign a reviewer who did not build the graph derivation/evaluation pipeline.

### G6-GOLD Independent held-out QA review
- Status: NEEDS_HUMAN_REVIEW
- Why not done: production-scale silver data is complete, but all 500 held-out review labels are blank.
- Input available: `chatbot/data/generated/human_gold_review_v2.csv`; 11,998 unique silver rows; split SHA-256 `6d2ec25136288a1657a3fe9eb37f9bc1b09bfe6c8f781ebba2d5d99978851094`.
- Exact next command/action: reviewers fill the 500-row CSV, then run `cd chatbot && uv run python -m datasets.import_review --source data/generated/live_candidates_v2.jsonl --csv data/generated/human_gold_review_v2.csv --out data/reviewed/human_gold_v2.jsonl --rejected data/reviewed/human_gold_v2_rejected.jsonl --status-on-yes approved` and rebuild leakage-safe splits.
- Acceptance test required: 300–500 independently reviewed held-out cases; supported actions represented; zero leakage into train/validation.
- Can proceed without it? No for G6 or the official G7 benchmark.
- Attempts/retry-at: deterministic 500-row queue exists; automatic labels remain silver and cannot clear this gate.
- Owner action, only if genuinely unavoidable: provide independent QA reviewers.

### G7-REAL Official independent-gold benchmark
- Status: BLOCKED_ENV
- Why not done: Aura and the chatbot now pass the 31-case real diagnostic, but no independently labelled >=300-case benchmark exists.
- Input available: `e2e_aura_results.json` has 31/31 expected statuses, 21/21 oracles, p50 10,087 ms and p95 25,760 ms; real API matrix is 8/8.
- Exact next command/action: after G6 review/import, run `cd chatbot && uv run python -m evaluation.run_eval --provider ollama --graph neo4j --dataset data/reviewed/human_gold_v2.jsonl --max-iterations 5 --output-dir reports/eval/aura_gold_v2`.
- Acceptance test required: >=300 unseen human-gold cases; factual set-F1 >=0.85, citation precision >=0.95, exact-count accuracy >=0.95, refusal >=0.95, no severe security issue; report p50/p95 and every failed case.
- Can proceed without it? No for G7.
- Attempts/retry-at: seven bounded engineering diagnostics; latest real Aura run completed 2026-11-18T13:51:16Z and passed all checked cases.
- Owner action, only if genuinely unavoidable: complete G6 independent review; all remaining execution after import is automated.

## Resolved since the previous checkpoint
- Aura resumed without credential changes: `neo4j+s`, `Neo4j/5.27-aura`; live inventory matches the immutable snapshot.
- All 12 catalog actions return real records from Aura.
- Catalog-guided LLM repair fixes weak Qwen routing without a fake fallback or benchmark-name hardcoding.
- Real Aura E2E improved from 25/31 and 15/21 to 31/31 and 21/21.
- Real FastAPI route matrix is 8/8; REST/SSE results match; UI proxy health is ready.

## Intentionally excluded from THIS RUN
- GPU SFT / LoRA actual training: not run. Prepared input is `chatbot/data/splits/sft_v2.jsonl` (16,744 rows, SHA-256 `75f59644a5ee5e4f8dcd17d26bc1f2b29346cb8017edddf54c8bc50505aaf21c`).
- Hugging Face authentication/upload: not run; adapter repository status is NOT VERIFIED.
- No account credential, password, payment, destructive database operation or main-branch merge was performed.

## Verified deliverables
- `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json` | `5baef40d08e5c7f4101d9db07c1634a503c3536758e0313c61ccbc0a017d5a07` | live Aura 12-action smoke | PASS 12/12
- `agent_runs/20261117T1631-9e78757/e2e_aura_results.json` | `c9cd1229f885b88de8f480aab81aa78b380bf72e651ecdd87be232185c1a981e` | Aura + Ollama workflow | PASS 31/31 status, 21/21 oracle
- `agent_runs/20261117T1631-9e78757/api_aura_smoke.json` | `915889be663effa88a6f9b5da113d04a6720a221e40d9ecc054c60fa879b7af0` | FastAPI matrix and REST/SSE | PASS 8/8 and semantic match
- chatbot suite | current branch | `cd chatbot && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` | PASS, 81 tests
- offline suite | current branch | `cd offline && uv run python -m pytest -o addopts='' -q` | PASS, 89 tests
- UI suite/build | current branch | `cd chatbot/ui && npm run test -- --run && npm run build` | PASS, 2 tests and production build
