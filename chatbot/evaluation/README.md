# Evaluation workflow

1. Generate candidates from fake or read-only Neo4j.
2. Export CSV, review every label, import approved rows, and create entity-connected splits.
3. Train only on approved train/validation rows; keep test untouched.
4. Run B0 with `--max-iterations 1`, B1 with `--max-iterations 5`, and B2 only when a local adapter exists.
5. Open `summary.md` and `comparison.csv`; inspect per-case `predictions.jsonl` before drawing conclusions.

`--synthetic-smoke` validates plumbing only and writes an explicit non-benchmark banner. Metrics that lack
human labels are `not_measured`; this project does not manufacture factuality or hallucination scores.
