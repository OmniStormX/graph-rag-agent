#!/usr/bin/env bash

set -euo pipefail

# 统一清理子进程，避免容器退出后残留僵尸进程。
cleanup() {
  local exit_code="${1:-0}"
  if [[ -n "${BACKEND_PID:-}" ]]; then kill "${BACKEND_PID}" 2>/dev/null || true; fi
  if [[ -n "${CHAT_PID:-}" ]]; then kill "${CHAT_PID}" 2>/dev/null || true; fi
  if [[ -n "${ADMIN_PID:-}" ]]; then kill "${ADMIN_PID}" 2>/dev/null || true; fi
  wait 2>/dev/null || true
  exit "${exit_code}"
}

trap 'cleanup 0' SIGTERM SIGINT

# 容器内统一使用本地回环地址互通，避免宿主机网络差异带来不稳定性。
export FRONTEND_API_URL="${FRONTEND_API_URL:-http://127.0.0.1:8000}"
export ADMIN_FRONTEND_API_URL="${ADMIN_FRONTEND_API_URL:-http://127.0.0.1:8000}"
export SERVER_HOST="${SERVER_HOST:-0.0.0.0}"
export SERVER_PORT="${SERVER_PORT:-8000}"
export SERVER_WORKERS="${SERVER_WORKERS:-1}"
export FASTAPI_WORKERS="${FASTAPI_WORKERS:-1}"
export PYTHONPATH="${PYTHONPATH:-/app:/app/server:/app/frontend}"

cd /app

python -m uvicorn server.main:app --host "${SERVER_HOST}" --port "${SERVER_PORT}" --workers "${SERVER_WORKERS}" &
BACKEND_PID=$!

streamlit run frontend/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.fileWatcherType none &
CHAT_PID=$!

streamlit run frontend/admin_app.py \
  --server.address 0.0.0.0 \
  --server.port 8502 \
  --server.fileWatcherType none &
ADMIN_PID=$!

# 任一关键进程退出都视为容器异常，统一拉起由编排层负责。
set +e
wait -n "${BACKEND_PID}" "${CHAT_PID}" "${ADMIN_PID}"
EXIT_CODE=$?
set -e

cleanup "${EXIT_CODE}"
