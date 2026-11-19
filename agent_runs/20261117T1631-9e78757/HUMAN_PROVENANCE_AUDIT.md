# Human-review provenance audit

Audit date: 2026-11-18 (Asia/Ho_Chi_Minh)

## Finding

The legacy files below are **not human-reviewed**, despite carrying `review_status=approved`:

| Artifact | Rows | Observed provenance | Decision |
|---|---:|---|---|
| `chatbot/data/reviewed/approved.jsonl` | 2,023 | every row has `reviewer_note=auto:passed`; 2,007 rows use `snapshot_version=live-readonly`, 16 use `synthetic-v1` | INVALID as human gold |
| `chatbot/data/splits/reviewed.jsonl` | 2,023 | same auto provenance; split 1,418 train / 305 val / 300 test | INVALID as human gold |
| `chatbot/reports/eval/B1_sft/summary.json` | 300 evaluated cases | banner says `HELD-OUT HUMAN-REVIEWED EVALUATION`, but its source split has auto provenance | historical diagnostic only; banner claim is invalid |

Checksums observed during the audit:

- `approved.jsonl`: `d0b99c705f3690826d4722a49ec63aacb147ccf652b549cac97368cb56fc2a93`
- `splits/reviewed.jsonl`: `a6130b680ab6b5d9728a66f8638b1b4ee0fd4029a947f8854866363804b2234a`

## Protection added

The evaluator now rejects `approved` rows whose reviewer note starts with known machine-review provenance
(`auto:`, `silver_auto:`, or `independent_`). The dataset audit reports these as
`invalid_human_provenance_cases`, subtracts them from `human_gold_cases`, and fails the quality status.

The new review path uses the internal status `independent_approved` but reports it as
`nonhuman_source_review` with an explicit `NOT HUMAN OR OFFICIAL INDEPENDENT GOLD` banner. It
never upgrades Codex or automated review to human or official independent-review provenance.
