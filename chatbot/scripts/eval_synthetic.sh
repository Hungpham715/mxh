#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/synthetic
uv run python -m datasets.generate_from_graph \
  --provider fake \
  --limit 20 \
  --out data/synthetic/candidates.jsonl
uv run python -m evaluation.run_eval \
  --dataset data/synthetic/candidates.jsonl \
  --provider fake \
  --graph fake \
  --max-iterations 5 \
  --output-dir reports/eval/synthetic \
  --synthetic-smoke
