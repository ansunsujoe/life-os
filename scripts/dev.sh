#!/usr/bin/env bash
# Run the LifeOS API (127.0.0.1:8765) and web UI (127.0.0.1:3000) together for development.
# Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

(cd "$ROOT/backend" && uv sync -q && uv run uvicorn lifeos.main:app --host 127.0.0.1 --port 8765 --reload) &
API_PID=$!
(cd "$ROOT/frontend" && { [ -d node_modules ] || pnpm install; } && pnpm run dev) &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null' EXIT INT TERM
echo "LifeOS: http://localhost:3000   API: http://127.0.0.1:8765/docs"
wait
