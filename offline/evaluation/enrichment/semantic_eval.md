# Semantic NER/RE evaluation

This report evaluates the graph-enrichment extractors with exact canonical IDs. An entity
is correct only when `(entity_type, canonical_id)` matches; a relation is correct only when
`(relation_type, from_id, to_id)` matches. Each gold row also stores the abstract SHA-256,
so corpus drift cannot silently change a score.

## Retained configuration

- Rules: gazetteer **v1.2** plus the existing dynamic scientific-name patterns.
- LLM: **Qwen3.5-0.8B-Q8_0**, 752,393,024 parameters, Ollama CPU-only
  (`num_gpu=0`; live `/api/ps` reported `size_vram: 0`).
- Extractor: `sub1b-ollama-v2.1`, JSON-Schema output, temperature 0, verbatim surface and
  evidence validation. Hallucinated text is dropped rather than merged.
- Canonicalization: exact whole-surface gazetteer resolution. This fixes the previous
  substring collapse, such as `GPT-3.5-turbo` becoming `GPT-3.5` and `machine translation
  evaluation` becoming `machine translation`. Explicit adjacent acronyms remain supported.

The hashes in `semantic_holdout_v4_manifest.json` match the retained extractor and
gazetteer files. The committed full-corpus enrichment was regenerated with this exact
configuration from the compatible per-paper cache: **4,181 entities and 6,092 edges** over
1,091 papers. Four of the six previous invalid-JSON failures were recovered by bounded
validated retries; two remain explicit in `llm_failures.jsonl`, giving 1,089/1,091 (99.82%)
LLM coverage. A deterministic 120-edge source-grounding audit passed 120/120, but that audit
does not estimate semantic precision or recall. The refreshed artifact has not been imported
into Aura because the current loader is MERGE-only and would leave stale v1.1 residuals in
the same scope.

## Frozen slices and leakage status

All slices use deterministic SHA-256 selection over cue-eligible 2023–2025 papers. Labels
were frozen before reading predictions. Annotation is a single nonhuman source review, not
independent human gold, and has no inter-annotator agreement.

| Slice | Papers | Role | Status |
|---|---:|---|---|
| dev12 | 12 | development | tuned on; optimistic |
| cross-check12 | 12 | development | partly tuned on; optimistic |
| holdout v3 | 12 | first holdout | consumed while developing v1.2 |
| **holdout v4** | **12** | one-shot test of retained v1.2 | **untouched before first score** |
| holdout v5 | 12 | negative audit of discarded v1.3 | untouched before first score, then consumed |
| holdout v6 | 12 | protocol-corrected measurement of retained v1.2 | untouched before first score; surface-first gold |
| holdout v7 | 12 | one-shot gate for the generic-surface stoplist candidate | untouched before first score; gate failed, candidate rejected |

## Primary result: untouched holdout v4

Exact micro precision/recall/F1:

| Configuration | NER P | NER R | NER F1 | RE P | RE R | RE F1 |
|---|---:|---:|---:|---:|---:|---:|
| Rules only, v1.2 | 62.07 | 32.14 | 42.35 | 58.06 | 32.14 | 41.38 |
| **Rules + Qwen3.5 0.8B, v1.2** | **41.18** | **50.00** | **45.16** | **40.00** | **50.00** | **44.44** |

The hybrid adds recall and improves F1 over rules-only by **+2.81 NER points** and
**+3.06 RE points**, while reducing precision. Paper-bootstrap 95% CIs (10,000 replicates)
are wide because this is only 12 papers: NER and RE F1 both [25.45, 60.69]. Per-type NER
F1 is 55.26% method, 46.15% dataset, and 22.86% task; long and variably phrased task names
remain the largest weakness.

This is a real improvement over the earlier untouched-v3 hybrid result (NER 33.07%, RE
32.84%), but it is still a small, cue-enriched, nonhuman slice. It is not a corpus-wide
precision estimate and does not satisfy an independent-human evaluation gate.

## Protocol-corrected measurement: holdout v6

The v5 post-score audit showed that hand-assigned gold IDs can disagree with the frozen
canonicalization contract. A read-only audit of v4 (`v4_gold_contract_audit.json`) confirms
this: **18/56 v4 gold entity IDs are not mechanically reproducible from verbatim abstract
surfaces** under the frozen `_canonicalize_llm` + gazetteer v1.2 contract (3 policy
mismatches such as `method:full-fine-tuning` versus the contract's `method:fft`, and 15
paraphrase surfaces confirmed by spot-checks). 17 of the 28 v4 false negatives carry such
IDs; one is provably recoverable. v4 remains the retained one-shot gate result, unchanged.

v6 therefore freezes a new 12-paper slice (all 60 consumed papers excluded) under protocol
`surface_first_frozen_contract_v2`: the annotator records verbatim surfaces first, and gold
IDs are derived with the same frozen `_canonicalize_llm` contract before any prediction is
opened. The slice measures extraction under the shared frozen normalization contract; it
does not measure canonicalizer correctness itself. The configuration is unchanged
(v2.1 + gazetteer v1.2); a slice-level cross-check confirmed the current code plus the
retained LLM cache reproduces `data/enriched` predictions **identically** for all 12 papers.

| Configuration | NER P | NER R | NER F1 | RE P | RE R | RE F1 |
|---|---:|---:|---:|---:|---:|---:|
| Rules only, v1.2 | 76.47 | 24.53 | 37.14 | 62.50 | 26.79 | 37.50 |
| **Rules + Qwen3.5 0.8B, v1.2** | **41.54** | **50.94** | **45.76** | **40.28** | **51.79** | **45.31** |

Paper-bootstrap 95% CIs (10,000 replicates): NER F1 [34.19, 59.20], RE F1 [33.57, 58.73].
Per-type NER F1: dataset 83.33%, method 51.43%, task 22.22% — long, variably phrased task
names remain the largest weakness, exactly as on v4. The hybrid advantage over rules-only
is larger here (+8.62 NER, +7.81 RE) than on v4 (+2.81/+3.06) because rules-only recall is
lower on this slice.

Provenance notes:

- 55 annotated entity mentions reduce to 53 unique `(type, id)` pairs in the micro score
  because the retained evaluator counts globally unique pairs (`fine-tuning` and `ChatGPT`
  each appear in two papers). Relations stay at 56 because they are paper-anchored.
- The v5 manifest's `schema.py` hash captured a transient gazetteer-v1.3 experimental state.
  The committed `schema.py` (unchanged since the original enrichment commit) is what the
  retained snapshot and v6 use; the identical cross-check above verifies this end-to-end.
- v6 uses a different annotation protocol from v4/v5. The similar F1 magnitude (45.76/45.31
  versus 45.16/44.44) is a confirmation under a cleaner protocol, **not** a model
  improvement, and the two slices are not directly comparable as a delta.

v6 error decomposition (hybrid): of 38 entity false positives, roughly 27 are generic or
descriptive LLM spans (`reasoning`, `planning`, `prompt`, `perplexity`, `embeddings`,
`bias`, `toxicity`, ...), and roughly 11 are normalization/type/granularity mismatches
paired with a false negative (`cod` vs `chain-of-dictionary-prompting`, `ppe` vs
`prior-prompt-engineering-ppe`, `task:rft` vs `method:rft`, `nllb` vs `nllb-3-3b`).
About 15 of 26 false negatives are true misses of long or novel names. The cheapest
domain-general lever is therefore precision on generic surfaces; any such change must be
gated on a NEW untouched slice (v7) with this same surface-first protocol, never on v6.

## v7 gate: generic-surface stoplist candidate rejected

The candidate extended `schema.py::GENERIC_SLUGS` with domain-general bare capability nouns
(`reasoning`, `planning`, `prompt`, `embeddings`, `bias`, `toxicity`, ...), metric names
(`perplexity`, `accuracy`, `rouge`, ...), and research-activity terms (`human-evaluation`,
`reward-shaping`, `data-curation`, ...). Gazetteer and extractor were unchanged. Development
sanity used paired re-merges from the retained cache on consumed slices (same gold, same
snapshots):

| Slice | Retained NER/RE F1 | Candidate NER/RE F1 |
|---|---|---|
| dev12 | 73.39 / 73.33 | 74.77 / 74.58 |
| cross-check12 | 50.49 / 47.17 | 50.49 / 47.17 |
| holdout v3 | 69.63 / 69.50 | 69.63 / 69.50 |
| holdout v6 (diagnostic) | 45.76 / 45.31 | 50.94 / 50.00 |

No consumed slice regressed and v6 improved, so the candidate went to the predeclared v7
gate: both micro F1 >= 0.50 on the first untouched v7 score AND candidate >= retained on
both metrics on the same slice. v7 froze 12 new papers (72 consumed papers excluded) under
the same surface-first protocol before any prediction was opened.

**Gate result: FAIL.** Candidate scored NER 43.24 / RE 41.38 on v7 — below the 0.50 bar —
and was *identical* to retained on v7: the extended stoplist drops nothing on these papers.
The v6 gain came from surfaces specific to that slice; v7's false positives are different
(multi-word descriptive spans and type disagreements), so the change did not transfer. The
candidate is rejected, `schema.py` was reverted, and the reverted hash was verified equal to
the retained committed blob. No post-score tuning was done on v7.

v7 therefore also stands as a third untouched measurement of the retained configuration:

| Configuration | NER P | NER R | NER F1 | RE P | RE R | RE F1 |
|---|---:|---:|---:|---:|---:|---:|
| Rules only, v1.2 | 35.29 | 12.50 | 18.46 | 30.00 | 12.00 | 17.14 |
| **Rules + Qwen3.5 0.8B, v1.2** | **38.10** | **50.00** | **43.24** | **36.36** | **48.00** | **41.38** |

Bootstrap 95% F1 CIs: NER [28.26, 54.19], RE [27.91, 51.09]. v7 is novel-name-heavy (few
gazetteer-known entities), which is why rules-only recall collapses to 12.5% and the hybrid
adds **+24.78 NER / +24.24 RE** — the largest hybrid advantage measured on any slice. The
three untouched measurements of the retained configuration (v4 45.16/44.44, v6 45.76/45.31,
v7 43.24/41.38) are consistent in magnitude; slice difficulty, not configuration drift,
explains the spread. All remain small, cue-enriched, single-nonhuman-reviewer results.

## Negative results and retention decision

The failed experiments are part of the result, not hidden selection attempts:

| Experiment | Evaluation use | NER F1 | RE F1 | Decision |
|---|---|---:|---:|---|
| Prompt v2.2, Qwen3.5 0.8B | consumed dev/cross/v3 | lower on every slice | lower/similar | reject; restore v2.1 |
| GLiNER small v2.1 + rules + Qwen | consumed 36-paper matrix | 35.82 | 35.21 | reject; weak cross-slice robustness and heavy dependency |
| Gazetteer v1.3 | untouched v5 | 37.41 | 35.46 | reject; missed the predeclared 50/50 gate |
| Gemma 3 1B + v1.3 | consumed v5 diagnostic | 36.36 | 34.25 | reject; worse than Qwen and 1/12 extraction failures |

Gemma was 999.89M parameters (Q4_K_M), ran with `size_vram: 0`, and took 290.4 seconds
for 12 serial papers. The GLiNER trial used `urchade/gliner_small-v2.1` (152,648,704
parameters) in an isolated temporary CPU environment; no repository dependency was added.

Gazetteer v1.3 was tuned after opening v4 and produced high resubstitution scores there,
but it failed the fresh v5 gate. It is therefore not retained. The repository keeps v1.2,
the last configuration with an untouched one-shot improvement.

The post-score v5 audit also found canonical-ID annotation inconsistencies (for example
`dataset:ptb` versus the frozen ontology's `dataset:penn-treebank`). The original v5 labels
and failed score remain unchanged for provenance. A future evaluation should freeze raw
mention surfaces and derive gold IDs with the same frozen canonicalization contract before
any prediction is opened.

## Historical context

The older numbers (NER 84.62/22.92/36.07 and RE 76.67/44.23/56.10) are not comparable.
They used a development slice and an evaluator that truncated entity membership evidence,
undercounting true positives for dense entities. Exact-ID scoring with full paper provenance
is the current contract.

## Reproduce

Create a 12-paper `papers.jsonl` subset from the manifest IDs, then run:

```bash
CUDA_VISIBLE_DEVICES=-1 uv run python -m src.cli enrich \
  --data <slice>/processed --out <slice>/hybrid --extractors rules,llm \
  --model qwen3.5:0.8b-q8_0 --num-gpu 0 --workers 1

uv run python -m src.cli evaluate-enrichment-semantic \
  --data <slice>/hybrid --processed <slice>/processed \
  --gold evaluation/enrichment/semantic_holdout_nonhuman_v4.jsonl \
  --out evaluation/enrichment/semantic_holdout_v4_hybrid_scores.json
```

The cache namespace includes model and extractor version, preventing silent reuse across
model/prompt changes. `semantic_holdout_v4_manifest.json` records label and code hashes;
the paired rules and hybrid score JSON files contain full counts, per-type metrics, errors,
and bootstrap intervals.

For v6, build the slice from `semantic_holdout_v6_manifest.json` IDs, copy the retained
namespaced cache entries (`data/enriched/llm_cache/qwen3.5_0.8b-q8_0/sub1b-ollama-v2.1/`)
into the slice's `hybrid/llm_cache/` tree, and score with the protocol label:

```bash
uv run python -m src.cli evaluate-enrichment-semantic \
  --data <slice>/hybrid --processed <slice>/processed \
  --gold evaluation/enrichment/semantic_holdout_nonhuman_v6.jsonl \
  --out evaluation/enrichment/semantic_holdout_v6_hybrid_scores.json \
  --annotation-protocol surface_first_frozen_contract_v2
```
