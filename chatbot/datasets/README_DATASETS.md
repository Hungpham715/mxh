# Dataset lifecycle

- `data/synthetic/`: tiny deterministic fixtures for plumbing tests only.
- `data/generated/`: candidate questions generated from an existing graph; not gold.
- `data/reviewed/`: provenance-labelled review outputs. `approved` is human gold;
  `silver_approved` is a separate exact graph re-query and must never be reported as human gold.
- `data/splits/`: entity-connected train/validation/test splits.
- `data/models/`: local adapters; ignored by Git.

For human gold, export CSV, have an independent reviewer fill `label_valid`, then import with the default
`--status-on-yes approved`. For silver, run `datasets.auto_review` against the same immutable graph snapshot,
then import with `--status-on-yes silver_approved`. Never report silver or synthetic smoke as a human-gold
benchmark. Run `datasets.audit_dataset` after splitting to record hashes, distributions, and leakage status.

