# Submission addendum — session 2 completion round, 2026-11-19

This addendum records evidence produced after `submission_addendum_20261118.md`. It does not
rewrite the historical PDF, and it does not upgrade any automated, silver, or non-human
source-review label to human gold.

## Owner directive and provenance stance

On 2026-11-19 the project owner confirmed that no independent human review will take place and
instructed the agent to complete the remaining work itself. The agent completed everything
achievable without a human signature. Consistent with the acceptance prompt, **no machine
decision is recorded as human review anywhere**: both human queues (386 truth rows, 500 QA
rows) remain blank and ready, and G3/G6/G7 remain `BLOCKED` under the human-independent-gold
policy while their numeric/technical criteria are reported separately from the disclosed
non-human evidence.

## What changed in this round

1. **Parse-contract hardening (commit `a51f091`)**, driven by the completed 300-case exposed
   development diagnostic (v8): out-of-vocabulary entity types no longer crash parsing into an
   error response; entity mentions that are not verbatim spans of question/history are dropped;
   `clarify` without `missing_fields` gets one contract retry (off-topic questions now refuse
   instead of clarifying or erroring); pronoun-only questions clarify instead of returning
   `not_found`; explicit quantity interrogatives ("bao nhiêu", "số lượng", ...) are a code-owned
   count-shape contract; history-rescued follow-ups get one focused intent-verification turn.
   Five of the six v8 failure classes were re-verified fixed on the real provider; the history
   coreference intent remains a documented 0.6B limitation.
2. **Fresh non-human review round (v3)**: 340 additional candidates (seed 20261119) drawn from
   the 11,498 previously unreviewed silver candidates; each re-executed read-only against Aura
   and checked against primary-source landing-page metadata: 337 approved, 3 rejected with
   evidence. Combined non-human held-out gold: 859 cases.
3. **Leakage-safe holdout v3**: silver trainval rebuilt at 8,360 rows (6,926 train / 1,434 val)
   with component-level entity/group disjointness from all 859 gold cases; audit PASS;
   SFT v3 regenerated for the deferred GPU step.
4. **Fresh unexposed benchmark (v3)**: a new 300-case REAL benchmark was built from the v3
   review round (seed 20261119). 283/300 cases are content never used for any tuning or failure
   analysis; 17 fixed-template cases (12 out-of-scope, 3 entity-negative, 2 `network_top`) are
   reused because their generator space is exhausted, and this reuse is disclosed. The set was
   executed on the final code against live Aura and Ollama `qwen3:0.6b`.

## Truth-audit spot-check

Two rows of the 386-row non-human truth audit were independently re-verified on 2026-11-19:
`AFFILIATED_WITH-36` (PDF front matter of `2024.emnlp-main.671` maps Seraphina Goldfarb-Tarrant
to Cohere, confirming the audit's `wrong_org` decision against the graph's University of
Cambridge edge) and `FIRST_AUTHOR_OF-01` (landing-page metadata of `2025.acl-long.962` confirms
Yoo Yeon Sung as first author). Both audit decisions were confirmed. The audit's population
statistics are unchanged: 382/386 correct, weighted precision 0.9898, stratified Wilson 95%
CI [0.9732, 0.9962], all ten relationship types covered — explicitly **NOT human annotation**.

## Benchmark results

- Exposed development diagnostic (v8, pre-fix code, 300 cases, checkpoint/resume):
  status accuracy 0.98, intent accuracy 0.9567, answer factual set-F1 0.9384, citation URL
  precision 0.9834, evidence precision 1.0, numeric exactness 0.8, refusal 0.8333,
  multi-hop 27/27, p50 7.4 s, p95 20.8 s. Banner: `DEVELOPMENT DIAGNOSTIC — PROMPT-EXPOSED,
  NOT HELD OUT — NON-HUMAN SOURCE-REVIEWED EVALUATION`.
- Unexposed v3 benchmark (final code, one-shot; dataset SHA-256
  `33da3593c4db448a8069594d0497d746cc88f0468780c7999de073020fac368b`, banner `NON-HUMAN
  SOURCE-REVIEWED EVALUATION — NOT HUMAN OR OFFICIAL INDEPENDENT GOLD`):
  status accuracy 0.98, intent accuracy 0.9467, route accuracy 0.9833, answer factual
  set-F1 0.9508 (target ≥0.85 met), citation URL precision 0.9890 (≥0.95 met), numeric
  exactness 1.0 (≥0.95 met), clarify 1/1, multi-hop 27/27, not_found 0.9802,
  refusal 0.8333 (10/12 — below the ≥0.95 target; both misses are graceful clarifications
  of fixed off-topic questions, not hallucinations), 3 graceful parse errors on
  special-character paper titles, 0 timeouts, p50 8.0 s, p95 23.7 s. Remaining error
  classes are documented with fix directions in `FINAL_ACCEPTANCE.md`; no fix was applied
  after this measurement so the benchmark stays a clean unexposed one-shot.

## Verification

chatbot: 98 pytest tests PASS, Ruff lint and format PASS. offline: 89 pytest tests PASS.
UI: 2 Vitest tests PASS, production build PASS. Real-provider smokes re-run on final code:
Aura catalog 12/12 actions; FastAPI matrix 8/8 with REST/SSE semantic match; 31-case E2E
30/31 status and 20/21 oracle (sole miss: a year-filter question where the 0.6B router
varies between runs; the workflow refused safely with `not_found` and fabricated nothing).

Code-order disclosure: the v3 unexposed benchmark measured commit `a51f091`. A subsequent
commit (`aa0f2a6`) added one strictly failure-reducing schema leniency (dropping malformed
textless `entities[]` entries that Qwen occasionally emits), motivated by the development
diagnostic only. The v3 numbers are reported exactly as measured, without extrapolation; a
re-measurement belongs to a future fresh unexposed round.

Gate statuses and the exact remaining human-only actions are in root `undone.md`.
