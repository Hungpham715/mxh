#!/usr/bin/env bash
# Resume the MXH agent run from its checkpoint, inside this repository only.
# Every step is idempotent or resumable: finished evaluation cases are skipped (--resume),
# integrity/coverage/G3-sampling are deterministic (fixed seeds), nothing writes to Aura.
#
# Usage: bash scripts/agent_resume.sh [phase]
#   phases: integrity | dataset | eval-b1 | eval-b0 | g3-score | report | all (default: all)
# Real-LLM evaluation needs a running Ollama with qwen3:0.6b on 127.0.0.1:11434.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ID="$(cat "$ROOT/agent_runs/CURRENT")"
STATE="$ROOT/agent_runs/$RUN_ID/state.json"
PHASE="${1:-all}"
echo "run: $RUN_ID  state: $STATE  phase: $PHASE"

run_offline() { (cd "$ROOT/offline" && uv run python -m src.cli "$@"); }
run_eval() {
  local variant="$1" iterations="$2"
  (cd "$ROOT/chatbot" && \
    APP_MODE=snapshot GRAPH_PROVIDER=snapshot LLM_PROVIDER=ollama OLLAMA_NUM_THREAD="${OLLAMA_NUM_THREAD:-10}" \
    PYTHONIOENCODING=utf-8 uv run python -m evaluation.run_eval --provider ollama --graph snapshot \
      --dataset data/splits/test.jsonl --label-tier silver --max-iterations "$iterations" --limit 300 \
      --seed 42 --output-dir "reports/eval/${variant}_silver_snapshot" --resume)
}

case "$PHASE" in
  integrity|all) run_offline validate; run_offline integrity; run_offline coverage ;;&
  dataset|all) (cd "$ROOT/chatbot" && PYTHONIOENCODING=utf-8 uv run python -m datasets.build_large --out-dir data) ;;&
  eval-b1|all) run_eval B1 5 ;;&
  eval-b0|all) run_eval B0 1 ;;&
  g3-score|all) run_offline truth-score || echo "G3 still blocked: no independent human labels" ;;&
  report|all) run_offline report --out report/final.pdf ;;
  *) ;;
esac
echo "done; update $STATE and undone.md with the new evidence paths"
