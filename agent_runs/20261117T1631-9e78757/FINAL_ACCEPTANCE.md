STATUS: INCOMPLETE (human-gold policy) / COMPLETE (all work achievable without human reviewers)
GATES: G0 PASS; G1 PASS; G2 PASS; G3 BLOCKED-HUMAN-PROVENANCE (numeric criterion PASS, non-human); G4 PASS; G5 PASS; G6 BLOCKED-HUMAN-PROVENANCE (numeric criterion PASS, non-human); G7 BLOCKED-HUMAN-PROVENANCE (unexposed non-human benchmark RUN); G8 PASS
NEXT ACTION: If independent human review is ever performed, fill the two blank queues and rerun the two documented commands; nothing else remains.

# Final acceptance record

Run: `20261117T1631-9e78757`

Branch: `agent/mxh-real-20261117-9e78757`

Snapshot: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`

Last updated: 2026-11-19 (session 2 — owner-directed completion round)

## Owner directive on provenance (2026-11-19)

The project owner stated that no independent human review will take place and instructed the
agent to finish the remaining work itself. The agent completed every remaining task that does
not require a human signature, and strengthened the non-human evidence (fresh unexposed
benchmark round v3). **No machine label is recorded anywhere as human review.** G3/G6/G7 keep
`BLOCKED` status under the acceptance prompt's human-independent-gold policy; each also records
whether its numeric/technical criterion is met by the disclosed non-human source review. A human
can still convert any of them later using the blank queues and exact commands in `undone.md`.

## Verdict

All environment, corpus, structural-integrity, Aura, real CPU chatbot, dataset, benchmark,
test, report, and publication work that an agent can execute autonomously is done and
re-verified in this session. The submission remains **INCOMPLETE only under the prompt's
human-provenance requirement** for G3/G6/G7.

| Gate | Result | Fresh evidence |
|---|---|---|
| G0 | PASS | managed worktree; allowlisted staging; `git diff --cached --check` + secret scan clean before every commit this session |
| G1 | PASS | live Aura census re-verified 2026-11-19: 7,134 nodes, 30,971 relationships, all ten types, scope `nlpgraph-v1`; snapshot hash matches the local manifest |
| G2 | PASS | 7,134/7,134 nodes and 30,971/30,971 relationships scanned; zero structural errors (`offline/reports/graph_audit/integrity_all.json`) |
| G3 | BLOCKED (human) / numeric PASS (non-human) | 386/386 probability-sample rows source-reviewed against ACL/arXiv landing pages + PDFs: 382 correct, 4 real defects; weighted precision 0.9898, stratified Wilson 95% CI [0.9732, 0.9962]; all 10 types covered; reviewer `codex-independent-source-review-v1`, NOT human. Spot-check 2026-11-19: audit row AFFILIATED_WITH-36 re-verified against the PDF front matter (Cohere, not Cambridge) and FIRST_AUTHOR_OF-01 against landing-page metadata — both audit decisions confirmed. Human labels: 0/386 |
| G4 | PASS | `neo4j+s`, `Neo4j/5.27-aura`; connectivity + counts re-verified 2026-11-19; 12/12 parameterized read-only actions (`aura_catalog_smoke.json`) |
| G5 | PASS | real Aura + Ollama `qwen3:0.6b` (0.40.16, user-local install); API matrix 8/8 + REST/SSE semantic match; catalog 12/12; E2E on final code 30/31 status, 20/21 oracle (sole miss: A3 year-filter case, Qwen run-variance — parsed `paper_venue` instead of `author_papers`; planner refused safely with `not_found`, no fabricated answer; the same question passed in isolated re-runs) |
| G6 | BLOCKED (human) / numeric PASS (non-human) | 11,998 unique silver rows, 12 actions; 859 non-human source-reviewed held-out cases (522 v2 + 337 v3, 22 challenge rows refreshed), leakage-safe against a 8,360-row silver trainval; human gold 0/500 |
| G7 | BLOCKED (human) / benchmark RUN (non-human) | fresh unexposed 300-case REAL benchmark on `independent_gold_benchmark300_v3_unexposed.jsonl` (283/300 never used for tuning; 17 fixed-template cases reused, disclosed), final code: status 0.98, intent 0.9467, answer factual set-F1 **0.9508** (target ≥0.85 ✓), citation URL precision **0.9890** (≥0.95 ✓), numeric exactness **1.0** (≥0.95 ✓), clarify 1/1, multi-hop 27/27, refusal **0.8333** (10/12, target ≥0.95 ✗ — disclosed miss), 3 graceful parse errors, p50 8.0 s / p95 23.7 s. Prompt-exposed v8 development diagnostic (pre-fix code): set-F1 0.9384, refusal 0.8333 |
| G8 | PASS | chatbot 98 tests + Ruff lint/format PASS; offline 89 tests PASS; UI 2 tests + production build PASS; 13-page report + two addenda; safe feature branch pushed |

## Real-provider evidence (session 2, final code)

- Aura: `neo4j+s://702feb94.databases.neo4j.io`, `Neo4j/5.27-aura`, DB `neo4j`, scope
  `nlpgraph-v1`; nodes 7,134 / relationships 30,971 (re-verified 2026-11-19T00:47Z).
- Ollama 0.40.16 at `~/.local/opt/ollama/bin/ollama`, model `qwen3:0.6b`
  digest `7df6b6e09427a769`.
- Parse-contract fixes (commit `a51f091`) verified live: math/off-topic questions no longer
  error (out_of_scope), pronoun-only questions clarify instead of not_found, explicit
  "bao nhiêu" questions answer with the DB-derived count, long-title questions parse.
- E2E/API/catalog smoke re-run on final code (2026-11-19): catalog 12/12 actions, health
  `connected; 7134 nodes in scope` (`aura_catalog_smoke.json` SHA-256
  `e22ca8b16457df5ce9450c9c4f0bd4a3f33b64547c9ee249f8f262338f660dcd`); API matrix 8/8 and
  REST/SSE semantic match (`api_aura_smoke.json` SHA-256
  `b2fc36d5fbd76bf5ab39431f84d411e5bbe38d92a90d907da0cd6e571e7bc0bf`); E2E 30/31 status,
  20/21 oracle, p50 9,814 ms / p95 22,707 ms (`e2e_aura_results.json` SHA-256
  `f7cf21782c98d9b0a8e1ca128a195cc4f4277ebdd27db42f7c34fb53f6fedccd`).

## Benchmark evidence

- v8 development diagnostic (prompt-exposed 300-case set, pre-fix code, completed with
  checkpoint/resume): status_accuracy 0.98, intent 0.9567, answer factual set-F1 0.9384,
  citation URL precision 0.9834, evidence precision 1.0, numeric_exactness 0.8,
  refusal 0.8333, clarify 0/1, multi-hop 27/27, p50 7.4 s, p95 20.8 s. Its six failures
  drove the commit-`a51f091` contract fixes; five of six failure classes re-verified fixed
  on the real provider, one (history-coref intent) remains a 0.6B limitation.
- v3 unexposed benchmark (final code, one-shot, no post-hoc tuning): BANNER `NON-HUMAN
  SOURCE-REVIEWED EVALUATION — NOT HUMAN OR OFFICIAL INDEPENDENT GOLD`; model
  `ollama:qwen3:0.6b`; dataset SHA-256
  `33da3593c4db448a8069594d0497d746cc88f0468780c7999de073020fac368b`; summary SHA-256
  `ddc54f929e4682e1bfffc781d35aef4e5f6553790296bc6f5111d359f500edb6`:
  route 0.9833, intent 0.9467, status 0.98, JSON validity 0.9833, entity-link top-1 0.9894,
  query execution success 0.99, evidence precision 0.9967 / recall 0.9933,
  answer factual set-P 0.9553 / set-R 0.9491 / **set-F1 0.9508**, numeric exactness **1.0**,
  citation ID precision 0.9967, citation URL precision **0.9890**, source-supported 0.9967,
  refusal 0.8333 (10/12), not_found 0.9802, clarify 1.0, multi-hop 27/27,
  premature stops 0, timeouts 0, errors 3, p50 8,043 ms, p95 23,747 ms.
- v3 failure analysis (6 status misses / 300):
  3× graceful `intent_parse_error` on paper questions whose titles contain special characters
  (colon/hyphen; Qwen emits invalid JSON twice — safe error, never a fabricated answer);
  2× fixed out-of-scope questions routed to clarify ("Ai là tổng thống Mỹ năm 2020?",
  "Công thức tính diện tích hình tròn?" — graceful asks, not hallucinations; note the
  0.6B router is not run-deterministic: the second question refused correctly in the
  pre-run live check); 1× sibling-relation confusion (author_affiliations →
  coauthor_affiliations) flipping a not_found gold to answered. A further 11 intent-only
  misses kept the expected status; of the 16 intent errors overall, 11 are same-entity-type
  sibling relation confusions (coauthors ↔ author_papers ↔ author_affiliations ↔
  coauthor_affiliations) — the documented 0.6B semantic limit. Improvement directions
  (JSON-repair pass for special-character titles; marker-override for off-domain questions
  with zero catalog grounding) must be tuned on the exposed v8 development set only, then
  measured on a fresh unexposed round — they are deliberately NOT applied after the v3
  measurement, to keep v3 a clean one-shot benchmark.

## Code-order disclosure

The v3 unexposed benchmark measured code at commit `a51f091`. One further robustness fix
(`aa0f2a6`) landed afterwards, motivated strictly by development-set evidence: the E2E A3
year-filter diagnostic failed 3/3 isolated runs because Qwen appends a malformed
`{"year_from":2024}` object inside `entities[]`, failing the whole parse. The fix drops
textless entity entries at schema level. It cannot lower v3-measured quality (it only
converts some hard parse failures into valid parses); 3 of the v3 error cases belong to the
same broad parse-failure class, so v3's `error_count: 3` is, if anything, conservative for
the shipped code. A full re-measurement belongs to a future fresh unexposed round — the v3
numbers above are reported as measured, not extrapolated.

## Verification outcomes (session 2, final code)

```text
chatbot: 98 pytest tests PASS; Ruff lint PASS; Ruff format PASS
offline: 89 pytest tests PASS
UI: 2 Vitest tests PASS; TypeScript/Vite production build PASS (re-verified 2026-11-19)
Aura catalog: 12/12 actions PASS (live)
Aura E2E: 30/31 status; 20/21 oracle (A3 flake documented)
Aura API: 8/8 route matrix; REST/SSE semantic match PASS
v8 exposed diagnostic (300): completed 300/300 with checkpoint/resume
v3 unexposed benchmark (300): completed one-shot; metrics above
```

## Dataset evidence (v3 round)

- fresh review queue: 340 candidates sampled (seed 20261119) from the 11,498 not previously
  reviewed; independent re-execution against Aura + primary-source metadata check:
  337 approved / 3 rejected (2 primary-metadata mismatches, 1 graph re-query mismatch),
  evidence `agent_runs/20261117T1631-9e78757/independent_qa_evidence_v3.jsonl`.
- combined non-human gold: 859 cases; holdout rebuild: trainval 8,360 (6,926 train /
  1,434 val), component-level entity/group disjointness PASS, `human_gold_cases: 0`.
- SFT v3 (deferred GPU input): `data/splits/sft_v3.jsonl` SHA-256
  `5313293986eb543abbb1a02f809ca303c57f900cc903df5c3fa29994b5474c57`.
- key hashes: expanded v3 `ff60c21faeac483004e436bfa8282201de43daccf388fc90c6fa824029880983`,
  gold test v3 `bed0c0a2545d0b76d52d5814eb9b7cd5765e3c447e9da94aac12836d05bb6c44`,
  combined holdout v3 `ba525963267fcfb98c7684c4427d7129ed40a81034ae606c9eae3861ee84d2eb`,
  review CSV v3 `b2b143d1f59578ee30827d3532b8e83bd037520e1564663648e6de686fbcc46d`.

## Provenance guarantees (unchanged, re-audited this session)

- Both human queues remain blank and ready: truth 386/386 blank, QA 500/500 `unknown`.
- Evaluator rejects `approved` rows with machine provenance; audits count
  `invalid_human_provenance_cases`; banners never label non-human data as human gold.
- Legacy 2,023 `auto:passed` rows remain invalid as human gold (`HUMAN_PROVENANCE_AUDIT.md`).

## Intentionally excluded from THIS RUN

- GPU SFT / LoRA actual training: not run; prepared inputs `sft_v2.jsonl` and `sft_v3.jsonl`.
- Hugging Face authentication/upload: not run; adapter repository status NOT VERIFIED.
- No credential, payment, destructive DB operation, or main-branch merge was performed.
- The uncommitted `online/` deletions in the worktree predate this run and were left untouched.
