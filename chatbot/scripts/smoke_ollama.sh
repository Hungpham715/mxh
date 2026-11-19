#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
curl -fsS "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null || {
  if command -v ollama >/dev/null; then
    echo 'OLLAMA NOT RUN: start `ollama serve`.'
  else
    echo 'OLLAMA NOT RUN: service unreachable and `ollama` is not on PATH.'
  fi
  exit 2
}
uv run python scripts/check_env.py

