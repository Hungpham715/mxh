# Agent scope: `offline/src/evaluation`

This file applies to the established offline graph pipeline at `offline/src/evaluation` and all descendants unless a nearer `AGENTS.md` overrides it.

- Inherit the repository rules in `/AGENTS.md`.
- Preserve its contracts and generated-data boundaries; run offline tests for any code change here.
- Preserve unrelated and ignored local work; never print, commit, or invent secrets.
- Keep changes minimal, validate the narrow scope, and report skipped external gates as `NOT RUN`.
- Graph-accuracy confidence intervals come from `kg_accuracy.py` — a vendored, self-contained port of the
  `reliable-kg-estimation` framework (Wilson / continuity-corrected Wilson / Agresti-Coull, plus a stratified
  effective-sample-size estimator). The external repo under `references/external/` is git-ignored, so do not
  import from it; extend `kg_accuracy.py` instead. `score.py` reports per-type Wilson and a population-weighted
  stratified micro estimate (replacing the former normal-approximation interval). Re-scoring existing labels
  (`cli score`) needs no re-run of fetch/prepare/import/sample — those are upstream of scoring.
