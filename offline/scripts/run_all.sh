#!/usr/bin/env bash
# End-to-end pipeline with checkpoints. Safe to re-run: fetch is cached, import is idempotent MERGE.
# Cloud import runs only when NEO4J_* credentials are present (in .env or the environment).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="uv run python -m src.cli"
mkdir -p logs

step() { echo; echo "=== $* ==="; }

step "tests";     uv run pytest -q
step "fetch";     $PY fetch --config configs/scope.yaml      # cached: re-runs are cheap
step "prepare";   $PY prepare --config configs/topics.yaml
step "validate";  $PY validate --data data/processed
step "dry-run";   $PY import --data data/processed --dry-run

if grep -qs '^NEO4J_PASSWORD=.\+' .env || [ -n "${NEO4J_PASSWORD:-}" ]; then
  step "preflight"; $PY preflight
  if [ "${FORCE_IMPORT:-0}" = "1" ] || [ ! -f output/neo4j/import_report_latest.json ]; then
    step "import";      $PY import --data data/processed
    step "idempotency"; $PY idempotency --data data/processed
  else
    echo "import already done (set FORCE_IMPORT=1 to re-import)"
  fi
  step "queries";   $PY queries
  step "analyze";   $PY analyze --out output/analysis --source neo4j
else
  echo "NEO4J credentials missing: skipping cloud steps (see NEEDS_CREDENTIALS.md)"
  step "analyze";   $PY analyze --out output/analysis
fi

step "sample";    $PY sample --per-type 20 --seed 20261107 --tag prefix
step "score";     $PY score --labels evaluation/labels.csv --tag prefix
step "audits";    uv run python -m src.evaluation.audits
step "report";    $PY report --out report/final.pdf
