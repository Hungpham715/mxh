STATUS: INCOMPLETE
GATES: G0 PASS; G1 BLOCKED; G2 PASS; G3 BLOCKED; G4 BLOCKED; G5 BLOCKED; G6 BLOCKED; G7 BLOCKED; G8 PENDING_PUSH
NEXT ACTION: Resume AuraDB, then obtain independent graph-truth and 500-row QA review before rerunning the official real benchmark.

# Final acceptance record

Run: `20261117T1631-9e78757`

Branch: `agent/mxh-real-20261117-9e78757`

Base: `9e78757086fc281ba5d9f5f1ab28cc1f31ab5d8a`

Snapshot: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`

## Verdict

The implementation, local real-provider validation, full structural graph census,
production-scale silver dataset, tests, and report addendum are complete. The
submission is still **INCOMPLETE** because Aura was unavailable, graph truth has no
independent reviewer, the held-out QA queue has no human gold, and the bounded local
diagnostic is below the official benchmark requirements.

| Gate | Result | Fresh evidence |
|---|---|---|
| G0 | PASS | workspace preflight; allowlisted staging; `git diff --check`; added-content secret scan |
| G1 | BLOCKED | immutable local snapshot meets 7,134 nodes/30,971 edges/10 types; direct Aura census unavailable |
| G2 | PASS | 7,134/7,134 nodes and 30,971/30,971 edges scanned; zero structural errors |
| G3 | BLOCKED | human n=0; automated diagnostic 0.8802, 95% CI [0.8548, 0.9017], n=386, not gold |
| G4 | BLOCKED | fresh Aura probe failed with routing-unavailable error |
| G5 | BLOCKED | local real REST/SSE smoke passed; Aura unavailable and local diagnostic misses acceptance |
| G6 | BLOCKED | 11,998 unique graph-revalidated silver rows and 12 actions; human gold n=0 |
| G7 | BLOCKED | local real n=31: status 25, oracle 15/21, p50 5,911 ms, p95 17,392 ms; no >=300 gold |
| G8 | PENDING_PUSH | backend/offline/UI gates and 13-page report plus addendum pass; commit/push pending |

## Real, synthetic, and not run

- **REAL LOCAL:** Neo4j Community imported from the immutable scoped snapshot and
  Ollama `qwen3:0.6b`; used for candidate generation, REST/SSE smoke, and E2E.
- **SYNTHETIC_SMOKE:** deterministic fake-provider tests remain in the regression
  suite only and are not used as G4/G5 evidence.
- **NOT RUN:** Aura queries, official human-gold benchmark, GPU SFT/LoRA, Colab,
  Hugging Face login/upload, and any account-login action.

## Dataset evidence

- candidates: 11,998 unique questions, SHA-256
  `7a4ce5e5dc38be154d76fd66537cc4655855ad8dae90442a3011063131d77840`
- silver: 11,998 separately graph-requeried rows, not human gold
- split: train 8,402 / validation 1,808 / test 1,788, leakage PASS, SHA-256
  `6d2ec25136288a1657a3fe9eb37f9bc1b09bfe6c8f781ebba2d5d99978851094`
- SFT: 16,744 messages-format samples, dry-run schema valid, SHA-256
  `75f59644a5ee5e4f8dcd17d26bc1f2b29346cb8017edddf54c8bc50505aaf21c`
- independent human gold: 0/500 labelled

## Verification commands and outcomes

```text
cd chatbot && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
PASS: Ruff clean, format clean, 78 tests passed

cd offline && uv run python -m pytest -o addopts='' -q
PASS: 89 tests passed

cd chatbot/ui && npm run test -- --run && npm run build
PASS: 2 tests passed; TypeScript/Vite production build passed

cd chatbot && uv run python ../agent_runs/20261117T1631-9e78757/api_real_smoke.py
PASS: real local health ready; REST/SSE semantic_match=true
```

## Evidence index

- graph quality: `offline/reports/graph_audit/quality_report.md`
- integrity machine output: `offline/reports/graph_audit/integrity_all.json`
- review queue: `offline/evaluation/manual_review_template_truth_v2.csv`
- dataset manifest: `chatbot/data/splits/manifest_v2.json`
- local real API smoke: `agent_runs/20261117T1631-9e78757/api_real_smoke.json`
- local real E2E: `agent_runs/20261117T1631-9e78757/e2e_real_results.json`
- Aura probe: `agent_runs/20261117T1631-9e78757/aura_probe_20261118.log`
- report: `offline/report/final.pdf` (13 pages) and
  `offline/report/submission_addendum_20261118.md`
- exact blockers and resume commands: `undone.md`

The only valid resume sequence is: resume Aura, complete the two independent review
queues, import the reviewed gold, and run the official benchmark command recorded in
`undone.md`. Re-running the same automated labels cannot clear G3, G6, or G7.
