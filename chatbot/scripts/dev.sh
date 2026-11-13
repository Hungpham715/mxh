#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run uvicorn graphrag.api:app --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-8000}" &
api_pid=$!
npm --prefix ui run dev -- --port "${WEB_PORT:-5173}" &
web_pid=$!
trap 'kill "$api_pid" "$web_pid" 2>/dev/null || true' EXIT INT TERM
wait "$api_pid" "$web_pid"

