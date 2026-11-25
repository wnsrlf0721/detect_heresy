#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-10000}"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log &
backend_pid=$!
env -u DATABASE_URL -u ANTHROPIC_API_KEY -u VOYAGE_API_KEY -u OPENAI_API_KEY \
    node /app/frontend/server.js &
frontend_pid=$!

stop_services() {
    kill -TERM "$backend_pid" "$frontend_pid" 2>/dev/null || true
    wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
}

trap 'stop_services; exit 0' TERM INT
exit_code=0
wait -n "$backend_pid" "$frontend_pid" || exit_code=$?
stop_services
exit "$exit_code"
