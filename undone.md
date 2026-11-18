# MXH — Undone / Deferred / Blocked
Last updated: 2026-11-18T00:44:48Z
Run ID: 20261117T1631-9e78757 | Git commit/branch: `36df078`, pushed branch `agent/mxh-real-20261117-9e78757` | Graph snapshot hash: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`
Overall status: INCOMPLETE

## Gate status
| Gate | PASS/FAIL/BLOCKED/DEFERRED | Evidence path | Blocker |
|---|---|---|---|
| G0 | PASS | `agent_runs/20261117T1631-9e78757/preflight.md`; staged diff/secret scan recorded in final acceptance | Unrelated pre-existing `online/` deletions and untracked `prompt.md` intentionally not staged |
| G1 | BLOCKED | `offline/output/neo4j/preflight.json`; `offline/output/analysis/graph_counts.json` | Local snapshot meets size/type requirements, but required direct Aura counts could not be obtained |
| G2 | PASS | `offline/reports/graph_audit/integrity_all.json`; `node_errors.csv`; `edge_errors.csv` | 7,134/7,134 nodes and 30,971/30,971 relationships scanned; zero structural errors |
| G3 | BLOCKED | `offline/reports/graph_audit/quality_report.md`; `offline/evaluation/manual_review_template_truth_v2.csv` | 0 independent human labels; automated diagnostic 0.8802, 95% CI [0.8548, 0.9017], n=386, is not gold and misses threshold |
| G4 | BLOCKED | `agent_runs/20261117T1631-9e78757/aura_probe_20261118.log` | Aura returned `Unable to retrieve routing information`; no live Aura query evidence |
| G5 | BLOCKED | `agent_runs/20261117T1631-9e78757/api_real_smoke.json`; `e2e_real_results.json` | Real local Neo4j + Ollama worked, but Aura requirement is unmet and 31-case quality is below acceptance |
| G6 | BLOCKED | `chatbot/data/splits/manifest_v2.json`; `chatbot/data/review/human_gold_review_v2.csv` | 11,998 silver cases cover 12 actions, but held-out human gold is 0/500 labelled |
| G7 | BLOCKED | `agent_runs/20261117T1631-9e78757/e2e_real_results.json` | Only 31 local-real cases: status 25/31, oracle 15/21; no >=300 independent gold benchmark or Aura run |
| G8 | PASS | `offline/report/final.pdf`; `offline/report/submission_addendum_20261118.md`; commit `36df078`; `origin/agent/mxh-real-20261117-9e78757` | — |

## Work remaining (ordered by dependency)

### B-AURA Resume and verify AuraDB
- Status: BLOCKED_ENV
- Why not done: current credentials reached the service endpoint but `verify_connectivity` failed with `Unable to retrieve routing information`; the agent cannot log into the Aura console.
- Input available: processed snapshot hash above; local scoped inventory is 7,134 nodes, 30,971 relationships, ten types; `.env` key presence was checked without printing values.
- Exact next command/action: owner resumes the configured instance in the Aura console, then run `cd chatbot && bash scripts/smoke_neo4j.sh` and `cd ../offline && uv run python -m src.cli preflight`.
- Acceptance test required: driver connectivity succeeds; live Aura scope counts match the immutable snapshot; all 12 parameterized read-only actions return expected real evidence.
- Can proceed without it? No for G1, G4, G5, and the official G7 run; yes for independent review and local regression.
- Attempts/retry-at: probed again at 2026-11-18T00:02Z; retry after owner confirms the instance is running.
- Owner action, only if genuinely unavoidable: authenticate to Aura Console and resume/repair the instance; rotate any credential that was ever pasted publicly.

### G3-GOLD Independent graph-truth review
- Status: NEEDS_HUMAN_REVIEW
- Why not done: all 386 review decisions are intentionally blank; automated source re-checks are diagnostic silver evidence only.
- Input available: `offline/evaluation/manual_review_template_truth_v2.csv`, guideline, seed/strata manifest, scoring tool; automated diagnostic 0.8802 [0.8548, 0.9017].
- Exact next command/action: an independent reviewer fills the template without reading auto labels, then runs `cd offline && uv run python -m src.cli score --labels evaluation/manual_review_template_truth_v2.csv --tag truth_v2`.
- Acceptance test required: all ten relation types covered; weighted point estimate >0.90 and lower 95% confidence bound >0.90; reviewer ID, timestamp, URL, and decision present.
- Can proceed without it? No for G3 and for any official graph-quality claim.
- Attempts/retry-at: one 386-row queue generated with seed 20261118; no automatic retry applies.
- Owner action, only if genuinely unavoidable: assign an independent reviewer who did not build the derivation pipeline.

### G6-GOLD Label held-out QA benchmark
- Status: NEEDS_HUMAN_REVIEW
- Why not done: production-scale silver data is complete, but 0/500 held-out rows have independent labels.
- Input available: `chatbot/data/review/human_gold_review_v2.csv`; 11,998 unique silver records; split SHA-256 `6d2ec25136288a1657a3fe9eb37f9bc1b09bfe6c8f781ebba2d5d99978851094`.
- Exact next command/action: reviewers label the 500-row queue, import it with `cd chatbot && uv run python -m datasets.import_review --review-csv data/review/human_gold_review_v2.csv --candidates data/generated/live_candidates_v2.jsonl --out data/reviewed/human_gold_v2.jsonl --required-label human_approved`, then rebuild leakage-safe splits.
- Acceptance test required: 300–500 independently reviewed held-out cases, all 12 supported actions represented where graph support exists, zero train/validation leakage.
- Can proceed without it? No for G6/G7; yes for silver-only training preparation.
- Attempts/retry-at: one deterministic 500-row queue exported; no automatic retry applies.
- Owner action, only if genuinely unavoidable: provide independent QA reviewers.

### G7-REAL Run the official benchmark
- Status: FAILED_QUALITY
- Why not done: the local 31-case diagnostic reached expected status on 25/31 and oracle match on 15/21, below the official size and quality requirements; Aura and gold are also missing.
- Input available: `agent_runs/20261117T1631-9e78757/e2e_real_results.json`, failure traces, real Ollama `qwen3:0.6b` path.
- Exact next command/action: after Aura and gold are ready, run `cd chatbot && uv run python -m evaluation.run_eval --dataset data/reviewed/human_gold_v2.jsonl --provider ollama --execute --out data/eval/real_gold_v2.jsonl`.
- Acceptance test required: >=300 unseen gold cases; factual set-F1 >=0.85, citation precision >=0.95, exact-count accuracy >=0.95, refusal >=0.95, no severe security error; report p50/p95 and every failed case.
- Can proceed without it? No for G7.
- Attempts/retry-at: five bounded 31-case diagnostic iterations; latest completed 2026-11-18T00:36:48Z.
- Owner action, only if genuinely unavoidable: only Aura resume and independent labels; code iteration remains agent-work after those inputs exist.

## Intentionally excluded from THIS RUN
- GPU SFT / LoRA actual training: not run. Prepared input is `chatbot/data/splits/sft_v2.jsonl` (16,744 records, SHA-256 `75f59644a5ee5e4f8dcd17d26bc1f2b29346cb8017edddf54c8bc50505aaf21c`); validate/use `chatbot/training/notebooks/qwen3_06b_sft_colab.ipynb` on an approved GPU host after human-gold review.
- Hugging Face authentication/upload: not run. Adapter repository status is NOT VERIFIED in this run; authenticate only with a current private credential after training and review.
- Other login-required actions: Aura Console resume and any optional pull-request creation were not performed or claimed.

## Verified deliverables
- `offline/reports/graph_audit/integrity_all.json` | structural census | `cd offline && uv run python scripts/graph_integrity_audit.py --data data/processed --out reports/graph_audit` | PASS, zero errors
- `offline/evaluation/scores_truth_v2.json` | automated diagnostic only | `cd offline && uv run python -m src.cli score --labels evaluation/automated_labels_truth_v2.csv --tag truth_v2` | 0.8802, 95% CI [0.8548, 0.9017], NOT human gold
- `chatbot/data/generated/live_candidates_v2.jsonl` | `7a4ce5e5dc38be154d76fd66537cc4655855ad8dae90442a3011063131d77840` | dataset audit | 11,998 unique candidates
- `chatbot/data/splits/silver_v2.jsonl` | `6d2ec25136288a1657a3fe9eb37f9bc1b09bfe6c8f781ebba2d5d99978851094` | `uv run python -m datasets.audit_dataset ...` | 11,998 silver, leakage PASS
- `agent_runs/20261117T1631-9e78757/api_real_smoke.json` | `6b021b5e61709e165e981244fbc269409422c5268d0f9447a4515f3350f5d5b8` | local real REST/SSE smoke | PASS, semantically identical
- `agent_runs/20261117T1631-9e78757/e2e_real_results.json` | `b43dc313b93a744fc3aaf2412dac5d46378740844a7396a0fd01eca72fa387af` | bounded local real E2E | 25/31 status, 15/21 oracle, p50/p95 5,911/17,392 ms
- chatbot suite | current worktree | `cd chatbot && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` | PASS, 78 tests
- offline suite | current worktree | `cd offline && uv run python -m pytest -o addopts='' -q` | PASS, 89 tests
- UI suite/build | current worktree | `cd chatbot/ui && npm run test -- --run && npm run build` | PASS, 2 tests and production build
- safe Git publication | `36df0784de28d23c7916135f3f1cca0185d88517` | `git push -u origin agent/mxh-real-20261117-9e78757` | PASS, no force
