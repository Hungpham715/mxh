# Semantic NER/RE evaluation

Exact-ID semantic evaluation of the enrichment extractors (gazetteer rules + sub-1B local
LLM) against frozen reference slices. Entity matching is exact on `(entity_type,
canonical_id)`; relation matching is exact on `(relation_type, from_id, to_id)`. Micro
counts are computed over globally deduplicated canonical IDs (the same canonical entity
predicted correctly in two papers counts once for NER, while paper-anchored relation
triples are unique per paper). Each gold row stores the abstract SHA-256 so a changed
corpus cannot silently invalidate a score.

## Frozen production configuration

All headline numbers below measure this exact configuration (extractor file hashes are
recorded in each slice manifest):

- Rules: gazetteer v1.1 (`configs/gazetteer.yaml`) + dynamic scientific-name patterns in
  `extract_rules.py`; full paper-membership provenance (`evidence_paper_ids`).
- LLM: **Qwen3.5-0.8B-Q8_0** (752,393,024 parameters — satisfies the ≤1B constraint),
  served by Ollama **CPU-only** (`num_gpu=0`, verified `size_vram: 0`, llamacpp runner),
  prompt/extractor version `sub1b-ollama-v2.1`, JSON-Schema-constrained output,
  temperature 0, verbatim-grounding validation (every surface and evidence must be a
  substring of the abstract; violations are dropped and counted, never kept).
- Throughput on the 20-core laptop CPU: ≈17 s/paper at workers=1 (12-paper holdout run:
  208.7 s, 0 failures). Both candidate models (Qwen3-0.6B, Qwen3.5-0.8B) run comfortably
  on CPU; the 0.8B was selected on development slices **before** opening the holdout.

## Slice protocol and leakage status

Three 12-paper slices, each frozen (labels + extractor hashes) before first scoring.
Selection is deterministic (sha256 ordering) over cue-eligible papers per year 2023–2025.

| Slice | File | Role | Leakage status |
|---|---|---|---|
| dev12 | `semantic_gold_nonhuman.jsonl` | original development slice | **tuned on** (gazetteer v1.1 was expanded from its false negatives → resubstitution, optimistic) |
| cross-check12 | `semantic_validation_nonhuman_v2.jsonl` | second slice | **partially tuned** (canonicalization rules were adjusted from its errors; prompt v2.1 frozen on it) |
| holdout v3 | `semantic_holdout_nonhuman_v3.jsonl` | final untouched slice | **never used for any tuning**; scored exactly once per configuration, then consumed |

Annotation is a single nonhuman source reviewer (`codex_nonhuman_source_review`) — not
independent human gold, no inter-annotator agreement.

## Results (micro P/R/F1, %)

Frozen hybrid configuration (rules + Qwen3.5-0.8B v2.1) versus rules-only:

| Slice | Config | NER P | NER R | NER F1 | RE P | RE R | RE F1 |
|---|---|---|---|---|---|---|---|
| **holdout v3** | rules-only | 66.67 | 12.12 | **20.51** | 52.94 | 13.24 | **21.18** |
| **holdout v3** | hybrid (frozen) | 34.43 | 31.82 | **33.07** | 33.33 | 32.35 | **32.84** |
| cross-check12 | rules-only | 66.67 | 22.22 | 33.33 | 57.89 | 20.00 | 29.73 |
| cross-check12 | hybrid v2.1 | 51.02 | 46.30 | 48.54 | 47.06 | 43.64 | 45.28 |
| dev12 | rules-only | 100.00 | 85.42 | 92.13 | 93.75 | 86.54 | 90.00 |
| dev12 | hybrid v2.1 | 70.00 | 87.50 | 77.78 | 68.66 | 88.46 | 77.31 |

Headline honest estimate (holdout v3, frozen config, paper-level bootstrap 95% CI,
10,000 replicates):

- **NER F1 33.07%**, CI [18.57, 46.45] — P 34.43 [17.74, 50.77], R 31.82 [19.35, 43.59]
- **RE F1 32.84%**, CI [18.57, 46.45] — P 33.33 [17.74, 50.77], R 32.35 [19.35, 43.59]

(Entity and relation CIs coincide because this gold annotates one paper-anchored relation
per entity, so per-paper resampling counts are identical; verified with two seeds.)

Per-type F1 on holdout v3 (hybrid): method 43%, task 20%, dataset 0% (3 gold datasets —
see error analysis). USES_METHOD 42%, ADDRESSES_TASK 20%, EVALUATED_ON 0%.

On the untouched slice the hybrid **triples recall** over rules-only (12.12→31.82 NER,
13.24→32.35 RE) at roughly half the precision, netting **+12.6 NER F1 / +11.7 RE F1**.
The dev12 numbers are resubstitution (rules were tuned on that slice) and the
cross-check numbers are semi-optimistic (canonicalization was tuned there); the v3 row is
the defensible generalization estimate. v3 gold is also denser (66 entities/68 relations
vs 54/55 on cross-check), which lowers all configurations somewhat.

### Why the previously reported numbers are not comparable

The originally reported figures (NER P/R/F1 84.62/22.92/36.07, RE 76.67/44.23/56.10)
came from (a) an evaluator that undercounted true positives because entity evidence was
truncated to 3 papers corpus-wide — correct extractions on dense entities were scored as
false negatives — and (b) the dev12 slice before any tuning, with the old Qwen3-0.6B
precision-first prompt. After the provenance-contract fix, scores on the same dev12 slice
rose sharply; the v3 holdout under the fixed evaluator is the number to quote for
generalization, and dev12/cross-check rows are quoted only as development diagnostics.

## Error analysis (holdout v3 hybrid, 46 entity FN / 44 entity FP)

1. **Surface-variant canonicalization (~40–50% of FPs)**: the same concept extracted with
   a different surface → different canonical ID → penalized twice (FP + FN). Examples:
   `method:sft` ↔ gold `method:supervised-fine-tuning`; `method:gpt-3-5` ↔
   `method:gpt-3-5-turbo`; `task:structure-generations` ↔ `task:structure-generation`;
   `dataset:scenario-based` ↔ `dataset:scenario-based-dataset`;
   `task:semeval-24-competition-task-8` ↔ gold `dataset:semeval-2024-task-8` (type
   disagreement). Dataset F1 = 0 is driven almost entirely by this class plus one type
   error, not by missing dataset mentions outright. An alias-normalized secondary
   evaluation would roughly double the exact-match F1; exact-ID matching is kept as the
   headline because it is the strict, assumption-free metric.
2. **Annotation-protocol divergence on generic technical terms**: gold includes broad
   methods (`distillation`, `attention-mechanism`, `probing`, `supervised-fine-tuning`)
   that the frozen prompt explicitly instructs the model *not* to extract ("do not label
   generic phrases"). These are systematic FNs by design disagreement, not model misses.
3. **Long descriptive task names**: the 0.8B model misses or truncates multi-word task
   NPs (`situated-language-understanding-agent-evaluation`,
   `human-machine-mixed-text-detection`), which dominates the task-type recall gap.

Genuine hallucination is rare: the verbatim-grounding guard drops any surface not present
in the abstract, and the run recorded 0 extraction failures on all 12 papers.

## Limitations and discipline

- Single nonhuman annotator; cue-enriched selection (abstract ≥300 chars + extraction
  cue) — not a prevalence estimate for all 1,091 papers. Do not present any slice score
  as a corpus-wide quality claim.
- **Holdout v3 is consumed.** Any future extractor/canonicalizer change (e.g. alias
  normalization, the clear next lever) must be validated on a freshly frozen v4 slice;
  never re-tune and re-score v3.
- The deterministic source-grounding audit (`summary.json`, `audit_rows.jsonl`) is a
  separate provenance check and must not be combined with these semantic scores.

## Files

- `semantic_gold_nonhuman.jsonl` — dev12 labels (frozen; tuned on).
- `semantic_validation_nonhuman_v2.jsonl` + `semantic_validation_v2_manifest.json` —
  cross-check12 labels + freeze record; `semantic_validation_v2_rules_scores.json` —
  rules-only baseline there.
- `semantic_holdout_nonhuman_v3.jsonl` + `semantic_holdout_v3_manifest.json` — holdout
  labels + freeze record (extractor hashes); `semantic_holdout_v3_rules_scores.json`,
  `semantic_holdout_v3_hybrid_scores.json` — the one-shot final measurements.
- `semantic_scores.json` — historical dev12 score under the previous evaluator (kept for
  provenance; superseded by the table above).

## Reproduce

Slice runs build a 12-paper `processed/papers.jsonl` subset, run enrichment into a fresh
output dir (fresh `llm_cache/<model>/<version>/` — predictions are never silently reused
across model/prompt versions), then score:

```bash
uv run python -m src.cli enrich --data <slice>/processed --out <slice>/hybrid \
    --extractors rules,llm --model qwen3.5:0.8b-q8_0 --num-gpu 0 --workers 1
uv run python -m src.cli evaluate-enrichment-semantic \
    --data <slice>/hybrid --processed data/processed \
    --gold evaluation/enrichment/semantic_holdout_nonhuman_v3.jsonl \
    --out evaluation/enrichment/semantic_holdout_v3_hybrid_scores.json
```
