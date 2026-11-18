# Submission addendum — real CPU validation on 2026-11-18

This addendum records evidence produced after the 13-page `final.pdf`. It does not
rewrite the historical PDF and does not upgrade automated or silver labels to human
gold.

## Execution profile and scope

- Graph scope: `nlpgraph-v1`
- Processed snapshot manifest SHA-256:
  `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`
- Verified local snapshot and live Aura scope: 7,134 nodes and 30,971 relationships
- Real CPU model: Ollama `qwen3:0.6b`
- AuraDB: `neo4j+s`, `Neo4j/5.27-aura`, database `neo4j`; connectivity and
  read-only queries verified at 2026-11-18T12:43Z

Aura live counts match the immutable local snapshot. All 12 parameterized catalog
actions returned records from Aura. Fake mode was retained only for deterministic
regression tests and was not used as acceptance evidence.

## Graph construction and integrity

The scoped snapshot has 1,091 `Paper`, 5,430 `Author`, 600 `Institution`, 7
`Venue`, and 6 `Topic` nodes. Its ten non-empty relationship types are:

| Relationship | Count |
|---|---:|
| `FIRST_AUTHOR_OF` | 1,091 |
| `OTHER_AUTHOR_OF` | 5,007 |
| `COAUTHORED_WITH` | 16,754 |
| `AFFILIATED_WITH` | 4,306 |
| `APPEARS_IN` | 1,091 |
| `HAS_TOPIC` | 451 |
| `CITES` | 26 |
| `ORG_COAUTHORED_WITH` | 2,001 |
| `RESEARCHES` | 105 |
| `ACTIVE_IN` | 139 |

The full structural census scanned 7,134/7,134 nodes and 30,971/30,971
relationships, with zero node errors and zero relationship errors. This establishes
schema, endpoint, identifier, duplicate, provenance, and referential invariants for
the processed snapshot. It does not mean that every edge was independently
fact-checked.

## Truth audit

The new probability sample uses seed `20261118`, covers every relationship type,
and contains 386 rows (40 per type except the complete 26-edge `CITES`
population). All 386 human-review decisions remain blank.

An automated source-record diagnostic reports a population-weighted point estimate
of 0.8802 with stratified Wilson 95% interval [0.8548, 0.9017], macro precision
0.825, and 70 unverifiable rows. It is neither independent nor above the required
threshold. Therefore graph truth is **NOT VERIFIED** and G3 is **BLOCKED** until an
independent reviewer completes the queue and both the point estimate and the lower
95% confidence bound exceed 0.90.

## Dataset and training preparation

Generation from the immutable local snapshot produced 11,998 unique QA candidates
covering all 12 catalogued actions. A separate graph re-query matched 11,998/11,998
records, which are labelled `silver_approved`, not human gold. The leakage-safe
split contains 8,402 train, 1,808 validation, and 1,788 held-out test records; there
are no duplicate normalized questions across splits. The SFT conversion contains
16,744 messages-format records and passes CPU schema/dry-run validation. A
reproducible 500-row held-out human-review queue was exported, but 0/500 rows have
independent labels. G6 therefore remains **BLOCKED**.

## Real chatbot validation

The REST endpoint and SSE endpoint were exercised against Aura and real Ollama. They
returned the same route, status, facts, and source paper IDs for the smoke question.
An eight-route API matrix covering affiliation, paper authors, organization,
unknown/missing entities, out-of-scope, history and ambiguity passed 8/8. The
31-case real-provider Aura E2E run obtained:

- expected status: 31/31
- checked factual oracle: 21/21
- latency p50: 10,087 ms
- latency p95: 25,760 ms
- maximum database iterations: 5 by workflow contract

This clears the Aura and real-chatbot engineering gates G4/G5. It is still a bounded
engineering diagnostic, not the official benchmark: it has only 31 cases and no
independent human-gold labels. G7 therefore remains **BLOCKED** until the 500-row
review queue yields at least 300 unseen independent-gold cases.

## Reproducibility and limitations

The final run passed 81 chatbot tests, 89 offline tests, 2 UI tests, Ruff lint and
format checks, and the production UI build. The detailed acceptance record is in
`agent_runs/20261117T1631-9e78757/FINAL_ACCEPTANCE.md`; ordered blockers and exact
resume actions are in root `undone.md`.

Actual GPU SFT/LoRA training, Colab execution, Hugging Face authentication/upload,
and account-login actions were explicitly excluded. No claim is made that an
adapter was trained or uploaded in this run.
