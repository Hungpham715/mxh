# MXH — Undone / Deferred / Blocked
Last updated: 2026-11-18T09:05Z
Run ID: 20261118T0710Z-9e78757 | Git branch: agent/mxh-real-20261118-9e78757 (from main @ 9e78757) | Graph snapshot hash: manifest sha256 c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1
Overall status: INCOMPLETE

## Gate status
| Gate | Status | Evidence path | Blocker |
|---|---|---|---|
| G0 Safe environment | PASS | `agent_runs/20261118T0710Z-9e78757/preflight.md`; staged-diff secret scan 0 hits per commit | — |
| G1 Corpus & graph | PASS on local snapshot / Aura NOT VERIFIED | `reports/data_coverage.md`, `offline/output/neo4j/import_plan_dry_run.json` (7,134 nodes, 30,971 edges, 10/10 types) | Live Aura counts could not be read (instance unreachable) |
| G2 Integrity of all graph | PASS on local snapshot (census, 0 critical) / live NOT VERIFIED | `reports/graph_audit/integrity_all.json`, `node_errors.csv`, `edge_errors.csv` | “scanned = live count” needs Aura |
| G3 Truth > 90% | BLOCKED | `reports/graph_audit/g3_sampling_meta.json`, `g3_review_sheet_blind.csv`, `g3_truth_scores.json` (`BLOCKED_NO_INDEPENDENT_LABELS`) | No independent human reviewer |
| G4 AuraDB REAL | BLOCKED | `preflight.md` (TLS ok → connection reset ×3) | Aura instance paused/unreachable; owner login needed |
| G5 Qwen CPU chatbot REAL | PARTIAL — real Qwen3-0.6B via Ollama verified end-to-end on the local snapshot; not on Aura | `agent_runs/.../e2e_api.jsonl` + `.summary.json` (28/28), `eval/B1_silver_snapshot` | Depends on G4 |
| G6 Dataset quality & scale | BLOCKED (silver targets met, gold = 0) | `reports/dataset/manifest.json` (10,619 candidates, 10,619 silver, leakage PASS) | ≥300–500 human/independent gold needed |
| G7 Real chatbot benchmark | BLOCKED (silver diagnostic only) | `agent_runs/.../eval/B1_silver_snapshot`, `B0_silver_snapshot`, `compare_silver` | Needs gold test + Aura |
| G8 Submit & share | see FINAL_ACCEPTANCE.md (tests/lint/build PASS, report 15 pages regenerated, branch commits) | `agent_runs/.../final_*_tests.log`, `offline/report/final.pdf` | Push result recorded in FINAL_ACCEPTANCE.md |

## Work remaining (ordered by dependency)

### T1 Resume AuraDB and verify live
- Status: BLOCKED_ENV
- Why not done: DNS + TLS verify OK, then `errno 10054` reset on Bolt and HTTPS timeout, 3/3 attempts; driver `ServiceUnavailable: Unable to retrieve routing information`. Typical of a paused Aura instance.
- Input available: `chatbot/.env`, `offline/.env` (same host); `chatbot/scripts/aura_inventory.py`.
- Exact next command/action: owner resumes the instance in the Aura console (and rotates the password if it was ever shared), then `cd chatbot && uv run python scripts/aura_inventory.py ../agent_runs/<run>/aura_inventory.json` and `cd ../offline && uv run python -m src.cli preflight`.
- Acceptance test required: `verify_connectivity` OK; scoped counts = 7,134 nodes / 30,971 rels, 10 types (match `import_plan_dry_run.json`).
- Can proceed without it? yes for G2/G3/G6 work; no for G4/G5/G7.
- Attempts/retry-at: 3 (2026-11-18T07:12Z); no automatic retry (auth/console action, not transient).
- Owner action, only if genuinely unavoidable: resume/rotate the Aura instance; create a read-only user for the chatbot.

### T2 Live Cypher validation (after T1)
- Status: BLOCKED_ENV
- Why not done: the 12 templates now use `SKIP $skip LIMIT $limit` and a `CALL () { … } RETURN count(*)` total wrapper; they were unit-tested on fake/snapshot providers but never executed by Neo4j in this run. A portable local Neo4j 5.26.16 was downloaded and checksum-verified, but starting it was refused by the local permission policy.
- Exact next command/action: `cd chatbot && APP_MODE=real GRAPH_PROVIDER=neo4j LLM_PROVIDER=ollama uv run python scripts/e2e_api.py --out ../agent_runs/<run>/e2e_api_aura.jsonl`, then the B1 command below with `--graph neo4j`.
- Acceptance test required: 28/28 E2E; each action's rows equal `SnapshotGraphRepository.rows` (oracle) for the same params.
- Can proceed without it? no for G4.

### T3 Human truth review of the graph (G3)
- Status: NEEDS_HUMAN_REVIEW
- Why not done: no independent reviewer in this run; automated/LLM labels are rejected by the scorer by design.
- Input available: `reports/graph_audit/g3_review_sheet_blind.csv` (687 edges, 10 types, seed 20261118, sheet sha in `g3_sampling_meta.json`), guideline `offline/evaluation/labeling_guideline.md` (covers 3 types; extend for the other 7 before labelling).
- Exact next command/action: two reviewers fill `label`, `error_type`, `reviewer`, `reviewed_at_utc`, `evidence_url_checked`, `note` (10% overlap adjudicated) → `cd offline && uv run python -m src.cli truth-score`.
- Acceptance test required: weighted estimate > 0.90 AND lower 95% bound > 0.90, all 10 strata labelled, unverifiable counted as incorrect.
- Can proceed without it? yes (all other work), but the course requirement “>90%” stays unproven.

### T4 Gold QA set (G6/G7)
- Status: NEEDS_HUMAN_REVIEW
- Why not done: gold requires a person checking each case against the source/Cypher oracle.
- Input available: `chatbot/data/splits/test.jsonl` (1,340 silver test cases; regenerate with `uv run python -m datasets.build_large --out-dir data`, deterministic), `datasets/export_review.py` / `import_review.py`.
- Exact next command/action: export ≥300 test cases (exclude case_ids in `agent_runs/.../eval/diagnostic_v1_test_prompt_v1` and the B0/B1 samples if they were inspected), review, import as `approved`, then `uv run python -m evaluation.run_eval --label-tier gold --provider ollama --graph neo4j --dataset <gold_test.jsonl> --max-iterations 5 --output-dir reports/eval/B1_gold`.
- Acceptance test required: set-F1 ≥ 0.85, citation precision ≥ 0.95, count exactness ≥ 0.95, OOS refusal ≥ 0.95 (with n shown).

### T5 Weak spots measured on silver (fix on dev, re-test on a new held-out sample)
- Status: FAILED_QUALITY (targets not met on silver)
- Why not done / evidence (B1, n in brackets): intent 0.884 (181), query params exact 0.873 (181), answer name recall 0.66 (181), clarify 0.5 (2), OOS refusal n only 4. Main confusions: author_affiliations ↔ coauthor_affiliations, coauthors → author_papers (Qwen 0.6B).
- Exact next command/action: improve on `--dev` (validation split) only, then evaluate a fresh test sample with `--exclude-from` every previously inspected predictions file.
- Note: B0 ≈ B1 on this silver set because its questions are single-action; multi-step value shows on composite questions (E2E “Tổng quan …” case) — add composite cases to the gold set.

## Intentionally excluded from THIS RUN
- GPU SFT / LoRA actual training: not run. Inputs ready: `chatbot/data/splits/sft_silver.jsonl` (9,279 PARSE samples, train 7,887 / val 1,392, `messages` schema matching the runtime prompt; dry-run valid), config `chatbot/training/config_sft.yaml`. Next (GPU machine): `uv run python training/train_sft.py --train --dataset data/splits/sft_silver.jsonl --config training/config_sft.yaml` — prefer human-approved data (`build_sft` without `--include-silver`) for an official adapter.
- Hugging Face authentication/upload: not run; adapter repository status NOT VERIFIED.
- Other login-required actions (Aura console, LangSmith, OpenAlex key): not run; no success claimed.

## Verified deliverables
- `offline/data/derived/edges_*.jsonl` | regenerated, deterministic (integrity `derived_files_match_fresh_derivation=true`) | `uv run python -m src.cli import --dry-run` | PASS
- `reports/graph_audit/integrity_all.json` | 0 critical / 2 warnings over 7,134 + 30,971 | `uv run python -m src.cli integrity` | PASS (snapshot)
- `reports/data_coverage.md` | selected 1092/1092 (100%), ACL eligible 840/7501 (11.2%) | `uv run python -m src.cli coverage` | PASS
- `reports/graph_audit/g3_review_sheet_blind.csv` | 687 rows | `uv run python -m src.cli truth-sample` | READY FOR REVIEW
- `reports/dataset/manifest.json` | 10,619 silver, leakage PASS | `uv run python -m datasets.build_large --out-dir data` | SILVER ONLY
- `agent_runs/20261118T0710Z-9e78757/eval/B1_silver_snapshot/summary.md` | real Qwen, 300 cases | see chatbot/README | DIAGNOSTIC (silver)
- `agent_runs/20261118T0710Z-9e78757/e2e_api.summary.json` | 28/28, more + cancel OK | `uv run python scripts/e2e_api.py` | PASS (snapshot)
- Tests: offline 80 passed; chatbot 71 passed + ruff clean; UI 4 tests + build | logs `agent_runs/.../final_*` | PASS
- `offline/report/final.pdf` | 15 pages, chapters 8–9 from artefacts | `uv run python -m src.cli report` | UPDATED

## Resume
`bash scripts/agent_resume.sh` (phases: integrity | dataset | eval-b1 | eval-b0 | g3-score | report | all). Needs Ollama with `qwen3:0.6b` on 127.0.0.1:11434 for eval phases.
