# MXH — Undone / Deferred / Blocked
Last updated: 2026-11-19T03:35:00Z
Run ID: 20261117T1631-9e78757 | Git branch: `agent/mxh-real-20261117-9e78757` | Graph snapshot hash: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`
Overall status: INCOMPLETE — solely due to the human-independent-gold provenance requirement of G3/G6/G7. Every task achievable without a human reviewer is COMPLETE, including a fresh unexposed 300-case REAL benchmark round (v3) built after the owner confirmed on 2026-11-19 that no human review will occur. No machine decision is labelled human anywhere.

## Gate status
| Gate | PASS/FAIL/BLOCKED/DEFERRED | Evidence path | Blocker |
|---|---|---|---|
| G0 | PASS | `agent_runs/20261117T1631-9e78757/preflight.md`; per-commit staged diff + secret scans | Unrelated `online/` deletions and `prompt.md` intentionally left outside commits |
| G1 | PASS | `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json` | Live Aura re-verified 2026-11-19: 7,134 nodes, 30,971 relationships, all ten types |
| G2 | PASS | `offline/reports/graph_audit/integrity_all.json` | 100% structural census, zero errors |
| G3 | BLOCKED (human provenance) — numeric criterion PASS (non-human) | `offline/evaluation/independent_review_truth_v2.csv`; `offline/reports/graph_audit/quality_report.md` | 386/386 source-reviewed: 382 correct / 4 incorrect, weighted 0.9898, Wilson 95% [0.9732, 0.9962], 10/10 types; audit rows independently spot-checked against PDF/landing page on 2026-11-19; human labels remain 0/386 |
| G4 | PASS | `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json` | `Neo4j/5.27-aura`; live counts match; 12/12 read-only actions PASS |
| G5 | PASS | `api_aura_smoke.json`; `e2e_aura_results.json` | Real Aura/Ollama `qwen3:0.6b` re-verified on final code 2026-11-19: API 8/8 + REST/SSE match; catalog 12/12; E2E 30/31 status, 20/21 oracle (A3 year-filter Qwen run-variance, safe not_found — documented, not hidden) |
| G6 | BLOCKED (human provenance) — numeric criterion PASS (non-human) | `chatbot/data/splits/independent_holdout_v3.manifest.json`; `chatbot/data/generated/human_gold_review_v2.csv` | 859 non-human source-reviewed held-out cases (v2 522 + v3 337); 11,998 silver; leakage-safe trainval 8,360; independent human gold remains 0/500 |
| G7 | BLOCKED (human provenance) — unexposed non-human benchmark RUN | `chatbot/reports/eval/aura_nonhuman_unexposed_v1/`; dataset `data/splits/independent_gold_benchmark300_v3_unexposed.jsonl` | 300-case REAL one-shot benchmark on a fresh set (seed 20261119; 283/300 never seen during tuning; 17 fixed-template cases reused and disclosed): set-F1 0.9508 ✓, citation 0.9890 ✓, numeric 1.0 ✓, refusal 0.8333 ✗ (disclosed); no human-gold benchmark exists |
| G8 | PASS | `offline/report/final.pdf`; addenda 2026-11-18/19; test/build evidence; pushed feature branch | — |

## Work remaining (ordered by dependency)

### G3-GOLD Independent graph-truth review
- Status: NEEDS_HUMAN_REVIEW
- Why not done: the pre-registered human queue is intentionally still blank; the prompt forbids agent/same-delivery labels from being represented as independent human gold, and the owner confirmed no human reviewer will be assigned.
- Input available: `offline/evaluation/manual_review_template_truth_v2.csv` (386/386 blank), guideline, seed/strata manifest and scorer. Complete non-human source audit available separately: 382 correct / 4 incorrect, weighted precision 0.9898, stratified Wilson 95% CI [0.9732, 0.9962], explicitly `NOT human annotation`; two of its rows were re-verified against primary sources by a second agent pass on 2026-11-19 (both confirmed).
- Exact next command/action: an independent reviewer fills the template without inspecting auto labels, then runs `cd offline && uv run python -m src.cli score --labels evaluation/manual_review_template_truth_v2.csv --tag truth_v2`.
- Acceptance test required: all ten relationship types covered; weighted point estimate >0.90 and lower 95% confidence bound >0.90; reviewer, UTC timestamp, source URL and decision present.
- Can proceed without it? No for G3 under the human-gold policy; the numeric >90% criterion is already met by the disclosed non-human audit.
- Attempts/retry-at: one reproducible 386-row probability sample (seed 20261118); 335 ACL/arXiv landing pages plus required PDFs checked; four real defects identified; automatic/non-human retry cannot create independent human evidence.
- Owner action, only if genuinely unavoidable: assign a reviewer who did not build the graph derivation/evaluation pipeline (the project owner qualifies and can use the blank queue as-is).

### G6-GOLD Independent held-out QA review
- Status: NEEDS_HUMAN_REVIEW
- Why not done: production-scale silver data is complete and two non-human review rounds exist (v2: 500+22 cases; v3: 340 queued, 337 approved / 3 rejected with evidence), but all official human-review labels remain blank by owner decision.
- Input available: `chatbot/data/generated/human_gold_review_v2.csv` (500/500 `unknown`); 11,998 unique silver rows; 859 non-human source-reviewed rows; leakage-safe holdout v3 (trainval 8,360 rows, component-disjoint, leakage PASS).
- Exact next command/action: reviewers fill the 500-row CSV, then run `cd chatbot && uv run python -m datasets.import_review --source data/generated/live_candidates_v2.jsonl --csv data/generated/human_gold_review_v2.csv --out data/reviewed/human_gold_v2.jsonl --rejected data/reviewed/human_gold_v2_rejected.jsonl --status-on-yes approved` and rebuild leakage-safe splits with `datasets.build_independent_holdout`.
- Acceptance test required: 300–500 independently reviewed held-out cases; supported actions represented; zero leakage into train/validation.
- Can proceed without it? No for G6 under the human-gold policy; scale/leakage/coverage criteria are met by the non-human set.
- Attempts/retry-at: deterministic queues exist for both rounds; provenance guards reject the legacy 2,023 `approved` rows whose notes say `auto:passed`; non-human rows use separate internal statuses and cannot clear this gate.
- Owner action, only if genuinely unavoidable: provide independent QA reviewers.

### G7-REAL Official independent-gold benchmark
- Status: NEEDS_HUMAN_REVIEW (benchmark engineering complete and re-run unexposed)
- Why not done: no independently human-labelled unseen >=300-case benchmark exists. The 300-case v3 set is unexposed to tuning but non-human reviewed; the v2 300-case set is prompt-exposed and permanently banner-marked as a development diagnostic.
- Input available: `data/splits/independent_gold_benchmark300_v3_unexposed.jsonl` SHA-256 `33da3593c4db448a8069594d0497d746cc88f0468780c7999de073020fac368b` (300 cases: 283 fresh content, 17 disclosed fixed-template reuses — 12 out-of-scope, 3 entity-negative, 2 network_top whose generator space is exhausted); v3 REAL run in `chatbot/reports/eval/aura_nonhuman_unexposed_v1/`; exposed-set diagnostic in `.../aura_nonhuman_source_review_development_v8/` (set-F1 0.9384, citation URL precision 0.9834, status 0.98).
- Exact next command/action: after a human G6 review/import, run `cd chatbot && uv run python -m evaluation.run_eval --provider ollama --graph neo4j --dataset data/reviewed/human_gold_v2.jsonl --max-iterations 5 --page-size 100 --output-dir reports/eval/aura_gold_v2`.
- Acceptance test required: >=300 unseen human-gold cases; factual set-F1 >=0.85, citation precision >=0.95, exact-count accuracy >=0.95, refusal >=0.95, no severe security issue; report p50/p95 and every failed case.
- Can proceed without it? No for G7 under the human-gold policy; the unexposed non-human run provides the strongest available substitute and is reported with its provenance banner.
- Attempts/retry-at: v8 exposed diagnostic completed 300/300 with checkpoint/resume; its 6 failures were fixed at contract level (commit `a51f091`) and re-verified live; v3 unexposed round executed on final code.
- Owner action, only if genuinely unavoidable: complete G6 independent review; all remaining execution after import is automated.

## Resolved since the previous checkpoint (session 2, 2026-11-19)
- Ollama restored (user-local 0.40.16 + `qwen3:0.6b`); Aura re-verified live (7,134/30,971).
- v8 300-case exposed diagnostic COMPLETED via checkpoint/resume (116→300): status 0.98, intent 0.9567, answer factual set-F1 0.9384, citation URL precision 0.9834, numeric 0.8, refusal 0.8333, multi-hop 27/27, p50 7.4 s / p95 20.8 s.
- Its failure classes fixed at contract level and re-verified on the real provider: out-of-vocabulary entity types no longer crash parsing; ungrounded/translated entity spans are dropped; clarify-without-missing-fields gets one contract retry (off-topic questions now refuse instead of clarify/error); pronoun-only questions clarify instead of not_found; explicit "bao nhiêu" questions always answer with the DB-derived count; history-rescued follow-ups get one intent-verification turn. Known remaining limitation: the history-coref follow-up can still pick a sibling relation (coauthor_affiliations vs coauthors) — 0.6B semantic limit, documented in failure analysis.
- Fresh v3 review round: 340 new candidates sampled (seed 20261119) from the 11,498 previously unreviewed; independent Aura re-execution + primary-source metadata check → 337 approved / 3 rejected with evidence; combined non-human gold now 859 cases.
- Leakage-safe holdout v3 rebuilt (trainval 8,360; component-level disjointness PASS); audits PASS; SFT v3 regenerated for the deferred GPU step.
- Fresh unexposed 300-case benchmark v3 built and executed one-shot on final code: status 0.98, intent 0.9467, answer factual set-F1 0.9508, citation URL precision 0.9890, numeric exactness 1.0, clarify 1/1, multi-hop 27/27, refusal 0.8333 (10/12 — below the 0.95 target, disclosed), 3 graceful parse errors on special-character titles, p50 8.0 s / p95 23.7 s; summary SHA-256 `ddc54f929e4682e1bfffc781d35aef4e5f6553790296bc6f5111d359f500edb6`. No post-hoc tuning was applied after this measurement.
- Truth-audit spot-check: AFFILIATED_WITH-36 (Cohere vs Cambridge, PDF front matter) and FIRST_AUTHOR_OF-01 (landing-page metadata) independently re-verified — audit decisions confirmed.
- Post-benchmark robustness fix (commit `aa0f2a6`, dev-evidence only): Qwen sometimes appends a malformed `{"year_from":2024}` object inside `entities[]`, which failed the whole parse; textless entity entries are now dropped at schema level. Disclosed code-order: the v3 unexposed numbers were measured at `a51f091`, before this strictly-failure-reducing fix; no v3 re-measurement was done, keeping v3 a clean one-shot.
- Real-provider smokes re-run on final code: catalog 12/12; API matrix 8/8 + REST/SSE semantic match; E2E 30/31 status, 20/21 oracle, p50 9.8 s / p95 22.7 s. E2E/API scripts' list-category expectations were aligned with the intended truncated→partial contract (large lists at the 20-row default page are `partial` with full DB values preserved in the answer).
- Test suites re-verified on final code: chatbot 98 pytest + Ruff lint/format PASS; offline 89 pytest PASS; UI 2 tests + production build PASS.

## Intentionally excluded from THIS RUN
- GPU SFT / LoRA actual training: not run. Prepared inputs: `chatbot/data/splits/sft_v2.jsonl` (16,744 rows, SHA-256 `75f59644a5ee5e4f8dcd17d26bc1f2b29346cb8017edddf54c8bc50505aaf21c`) and `chatbot/data/splits/sft_v3.jsonl` (disjoint from all 859 reviewed cases, SHA-256 `5313293986eb543abbb1a02f809ca303c57f900cc903df5c3fa29994b5474c57`).
- Hugging Face authentication/upload: not run; adapter repository status is NOT VERIFIED.
- No account credential, password, payment, destructive database operation or main-branch merge was performed.
- The worktree's unrelated `online/` deletions were left uncommitted (not this run's change).

## Verified deliverables
- `agent_runs/20261117T1631-9e78757/e2e_aura_results.json` | `f7cf21782c98d9b0a8e1ca128a195cc4f4277ebdd27db42f7c34fb53f6fedccd` | Aura + Ollama workflow on final code | PASS 30/31 status, 20/21 oracle (A3 year-filter flake documented; safe not_found, no fabricated answer)
- `agent_runs/20261117T1631-9e78757/api_aura_smoke.json` | `b2fc36d5fbd76bf5ab39431f84d411e5bbe38d92a90d907da0cd6e571e7bc0bf` | FastAPI matrix and REST/SSE on final code | PASS 8/8 and semantic match
- `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json` (session-2 rerun) | `e22ca8b16457df5ce9450c9c4f0bd4a3f33b64547c9ee249f8f262338f660dcd` | live Aura 12-action catalog smoke | PASS 12/12, health `connected; 7134 nodes in scope`
- `chatbot/reports/eval/aura_nonhuman_unexposed_v1/summary.json` | `ddc54f929e4682e1bfffc781d35aef4e5f6553790296bc6f5111d359f500edb6` | fresh unexposed 300-case REAL benchmark | set-F1 0.9508, citation 0.9890, numeric 1.0, refusal 0.8333 (disclosed miss)
- `chatbot/data/splits/independent_gold_benchmark300_v3_unexposed.jsonl` | `33da3593c4db448a8069594d0497d746cc88f0468780c7999de073020fac368b` | fresh unexposed benchmark set | PASS selection contract
- `chatbot/data/splits/independent_gold_test_v3.jsonl` | `bed0c0a2545d0b76d52d5814eb9b7cd5765e3c447e9da94aac12836d05bb6c44` | 859-case non-human holdout | PASS
- `chatbot/data/splits/combined_independent_holdout_v3.jsonl` | `ba525963267fcfb98c7684c4427d7129ed40a81034ae606c9eae3861ee84d2eb` | combined holdout, leakage PASS | PASS
- `agent_runs/20261117T1631-9e78757/independent_qa_evidence_v3.jsonl` | `765e8459f8606e1926153c83bd3ae63d29813396834465ffab7589650b067819` | v3 review evidence (340 cases) | PASS
- chatbot suite | current branch | `cd chatbot && uv run ruff check . && uv run ruff format --check . && uv run pytest -q` | PASS, 98 tests
- offline suite | current branch | `cd offline && uv run python -m pytest -o addopts='' -q` | PASS, 89 tests
- UI suite/build | current branch | `cd chatbot/ui && npm run test -- --run && npm run build` | PASS re-verified 2026-11-19, 2 tests and production build
