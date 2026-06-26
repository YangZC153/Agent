#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if command -v hermes >/dev/null 2>&1; then
  DEFAULT_HERMES_BIN="$(command -v hermes)"
else
  PYTHON_PATH="$(command -v "$PYTHON_BIN" 2>/dev/null || printf '%s' "$PYTHON_BIN")"
  DEFAULT_HERMES_BIN="$(dirname "$PYTHON_PATH")/hermes"
fi

cd "$PROJECT_DIR"
export DAILY_RUN_DIRECT_SEND="${DAILY_RUN_DIRECT_SEND:-1}"
export DAILY_RUN_SEND_TARGET="${DAILY_RUN_SEND_TARGET:-feishu}"
export HERMES_BIN="${HERMES_BIN:-$DEFAULT_HERMES_BIN}"
exec "$PYTHON_BIN" daily_run.py
