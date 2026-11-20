# Semantic NER/RE evaluation

`semantic_gold_nonhuman.jsonl` is a frozen 12-paper reference slice. Each row was
reviewed against the abstract, and stores the abstract SHA-256 so a changed source
cannot silently reuse the labels. Entity matching is exact on `(entity_type,
canonical_id)`; relation matching is exact on `(relation_type, from_id, to_id)`.
The evaluator reports entity and relation micro P/R/F1, macro-F1 by type, and
paper-level false positives/false negatives.

This is a developer/manual nonhuman reference slice with one annotator. It is a
measured semantic check, but it is **not independent human gold**, has no inter-rater
agreement, and must not be presented as a 1,091-paper corpus estimate. The existing
`summary.json` remains the separate deterministic source-grounding audit and must not
be combined with these semantic scores.

Reproduce:

```bash
uv run python -m src.cli evaluate-enrichment-semantic
```
