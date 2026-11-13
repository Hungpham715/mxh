#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v ollama >/dev/null; then
  echo 'OLLAMA NOT RUN: install Ollama, then run `ollama pull qwen3:0.6b`.'
  exit 2
fi
curl -fsS "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}/api/tags" >/dev/null || {
  echo 'OLLAMA NOT RUN: start `ollama serve`.'
  exit 2
}
uv run python scripts/check_env.py

