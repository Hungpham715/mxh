#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_MODE=fake
export GRAPH_PROVIDER=fake
export LLM_PROVIDER=fake
smoke_port="${SMOKE_API_PORT:-8011}"
uv run uvicorn graphrag.api:app --host 127.0.0.1 --port "$smoke_port" > /tmp/mxh-graphrag-smoke.log 2>&1 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${smoke_port}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
curl -fsS "http://127.0.0.1:${smoke_port}/api/health" | uv run python -m json.tool
questions=(
  'An Nguyen có những bài báo nào?'
  'Đồng tác giả của An Nguyen là ai?'
  'An Nguyen và Binh Tran có bài chung nào?'
  'Ai viết Graph Evidence for NLP?'
  'Đường kết nối giữa An Nguyen và Binh Tran?'
  'Top tác giả có nhiều đồng tác giả nhất'
)
for question in "${questions[@]}"; do
  payload=$(uv run python -c 'import json,sys; print(json.dumps({"question":sys.argv[1],"debug":True}))' "$question")
  curl -fsS -H 'Content-Type: application/json' -d "$payload" "http://127.0.0.1:${smoke_port}/api/chat" >/dev/null
done
echo "FAKE_SMOKE_PASS: health + ${#questions[@]} chat requests"

