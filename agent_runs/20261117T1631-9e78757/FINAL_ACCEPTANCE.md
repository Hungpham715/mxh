STATUS: INCOMPLETE
GATES: G0 PASS; G1 PASS; G2 PASS; G3 BLOCKED; G4 PASS; G5 PASS; G6 BLOCKED; G7 BLOCKED; G8 PASS
NEXT ACTION: Independent reviewers must complete the 386-edge truth queue and 500-case held-out QA queue; then rerun the official >=300-case gold benchmark.

# Final acceptance record

Run: `20261117T1631-9e78757`

Branch: `agent/mxh-real-20261117-9e78757`

Snapshot: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`

## Verdict

All environment, corpus, structural-integrity, Aura, real CPU chatbot, test, report,
and publication work that the agent can execute autonomously now passes. The
submission remains **INCOMPLETE** only because the prompt requires independent human
labels for graph truth and the official held-out benchmark. Those queues contain
0/386 and 0/500 labels; automated or same-pipeline labels are not promoted to gold.

| Gate | Result | Fresh evidence |
|---|---|---|
| G0 | PASS | managed worktree; allowlisted staging; diff/secret scans before publication |
| G1 | PASS | live Aura census: 7,134 nodes, 30,971 relationships, all ten types, scope `nlpgraph-v1`; snapshot hash matches the local manifest |
| G2 | PASS | 7,134/7,134 nodes and 30,971/30,971 relationships scanned; zero structural errors |
| G3 | BLOCKED | independent human n=0/386; automated diagnostic 0.8802, 95% CI [0.8548, 0.9017], is not gold and misses threshold |
| G4 | PASS | `neo4j+s`, `Neo4j/5.27-aura`; live counts match; 12/12 parameterized read-only actions return records |
| G5 | PASS | real Aura + Ollama `qwen3:0.6b`; API matrix 8/8, POST/SSE match, E2E status 31/31 and oracle 21/21 |
| G6 | BLOCKED | 11,998 unique graph-revalidated silver rows cover 12 actions; independent human gold n=0/500 |
| G7 | BLOCKED | real Aura diagnostic is 31/31 status and 21/21 oracle, but the required >=300-case independent gold benchmark does not exist |
| G8 | PASS | backend/offline/UI gates pass; 13-page report plus addendum; safe feature branch pushed without force |

## Real-provider evidence

- Aura target: `neo4j+s`, host suffix `databases.neo4j.io`, server
  `Neo4j/5.27-aura`, database `neo4j`, scope `nlpgraph-v1`.
- Live inventory: Author 5,430; Paper 1,091; Institution 600; Venue 7; Topic 6;
  30,971 relationships across ten non-empty types.
- Catalog smoke: 12/12 actions returned records, SHA-256
  `5baef40d08e5c7f4101d9db07c1634a503c3536758e0313c61ccbc0a017d5a07`.
- E2E: 31/31 expected statuses and 21/21 checked oracles; p50 10,087 ms,
  p95 25,760 ms; SHA-256
  `c9cd1229f885b88de8f480aab81aa78b380bf72e651ecdd87be232185c1a981e`.
- FastAPI: eight-route matrix 8/8; REST/SSE semantic match; health confirms real
  Aura and Ollama; SHA-256
  `915889be663effa88a6f9b5da113d04a6720a221e40d9ecc054c60fa879b7af0`.
- UI: Vite serves `NLP Graph Atlas` at `http://127.0.0.1:5173`; its `/api/health`
  proxy reports both real providers ready.

Fake mode remains a deterministic regression fixture only. It is not counted as G4
or G5 evidence.

## Dataset evidence

- candidates: 11,998 unique questions, SHA-256
  `7a4ce5e5dc38be154d76fd66537cc4655855ad8dae90442a3011063131d77840`
- silver: 11,998 separately graph-requeried rows, not human gold
- split: train 8,402 / validation 1,808 / test 1,788, leakage PASS, SHA-256
  `6d2ec25136288a1657a3fe9eb37f9bc1b09bfe6c8f781ebba2d5d99978851094`
- SFT: 16,744 messages-format samples, dry-run schema valid, SHA-256
  `75f59644a5ee5e4f8dcd17d26bc1f2b29346cb8017edddf54c8bc50505aaf21c`
- independent graph truth: 0/386 labelled
- independent held-out QA gold: 0/500 labelled

## Verification outcomes

```text
chatbot: Ruff lint PASS; Ruff format PASS; 81 pytest tests PASS
offline: 89 pytest tests PASS
UI: 2 Vitest tests PASS; TypeScript/Vite production build PASS
Aura catalog: 12/12 actions PASS
Aura E2E: 31/31 status; 21/21 oracle
Aura API: 8/8 route matrix; POST/SSE semantic match PASS
```

## Evidence index

- `agent_runs/20261117T1631-9e78757/aura_catalog_smoke.json`
- `agent_runs/20261117T1631-9e78757/e2e_aura_results.json`
- `agent_runs/20261117T1631-9e78757/api_aura_smoke.json`
- `offline/reports/graph_audit/integrity_all.json`
- `offline/reports/graph_audit/quality_report.md`
- `offline/evaluation/manual_review_template_truth_v2.csv`
- `chatbot/data/generated/human_gold_review_v2.csv`
- `chatbot/data/splits/manifest_v2.json`
- `offline/report/final.pdf` and `offline/report/submission_addendum_20261118.md`
- exact remaining human work and resume commands: `undone.md`

Re-running automated labels cannot clear G3, G6, or G7. Those gates require a
genuinely independent reviewer as specified by the acceptance prompt.
