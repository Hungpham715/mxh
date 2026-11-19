# Graph quality audit — 2026-11-18

Scope: `nlpgraph-v1`

Processed snapshot manifest SHA-256: `c2c3f94e79086dc28592bc2188c3e023f2bd7bf062a75a977f9029ba824732f1`

## Integrity census (G2)

`PASS` for structural integrity on the local Neo4j import of the processed snapshot:

- Nodes scanned: 7,134 / 7,134
- Relationships scanned: 30,971 / 30,971
- Node errors: 0
- Relationship errors: 0
- Evidence: `integrity_all.json`, `node_errors.csv`, `edge_errors.csv`
- Command: `uv run python scripts/graph_integrity_audit.py --data data/processed --out reports/graph_audit`

This is a 100% structural/invariant audit. It is not a claim that every relationship was independently fact-checked.

## Truth semantics (G3)

`BLOCKED — NOT VERIFIED` because no independent human labels exist yet.

A probability sample was drawn before human review with seed `20261118`: 40 rows from each relationship type,
except `CITES`, whose complete population has only 26 rows. The resulting queue has 386 rows and covers all 10
relationship types. Reviewers must use `evaluation/labeling_guideline.md` and must not inspect automated labels
before finishing their independent decisions.

- Review queue: `evaluation/manual_review_template_truth_v2.csv`
- Sampling manifest: `evaluation/sample_meta_truth_v2.json`
- Blank human labels: 386 / 386
- Required labels: `correct`, `incorrect`, or conservative `unverifiable`
- Required provenance: reviewer ID and UTC review timestamp

Two automated/non-human diagnostics are retained with explicit provenance:

- The original metadata cross-check reports a population-weighted point estimate `0.8802`, stratified Wilson
  95% CI `[0.8548, 0.9017]`, with 70 conservative `unverifiable` rows.
- A later Codex source inspection downloaded 335 ACL/arXiv landing pages and the required PDFs, then reviewed all
  386 sampled rows against source text. It labelled 382 correct and 4 incorrect, for population-weighted precision
  `0.9898`, stratified Wilson 95% CI `[0.9732, 0.9962]`; the four detected errors are two
  `AFFILIATED_WITH` and two `ORG_COAUTHORED_WITH` edges. Evidence is in
  `evaluation/independent_review_truth_v2.csv` and `evaluation/scores_independent_v2.json`.

The second result clears the numeric threshold as a useful source audit, but it was produced by Codex in the same
delivery workflow. It is **not human annotation** and does not satisfy the prompt's independent-review provenance.
Neither diagnostic is promoted to human gold; G3 remains blocked pending the pre-registered human queue.

After independent review, run:

```bash
uv run python -m src.cli score \
  --labels evaluation/manual_review_template_truth_v2.csv \
  --tag truth_v2
```

G3 passes only if the population-weighted point estimate is greater than 0.90, the lower 95% confidence bound is
greater than 0.90, and every relationship type has human coverage. If it fails, fix the source/derivation and use a
fresh holdout sample; do not change the seed or discard `unverifiable` rows after seeing results.
