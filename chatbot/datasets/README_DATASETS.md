# Dataset lifecycle

- `data/synthetic/`: tiny deterministic fixtures for plumbing tests only.
- `data/generated/`: candidate questions generated from an existing graph; not gold.
- `data/reviewed/`: human-approved labels only.
- `data/splits/`: entity-connected train/validation/test splits.
- `data/models/`: local adapters; ignored by Git.

Run candidate generation, export CSV, review `label_valid`, import, split, then build SFT. Generated or
augmented rows always remain `needs_review` until a person marks them valid. Never report synthetic smoke
metrics as a production benchmark.

