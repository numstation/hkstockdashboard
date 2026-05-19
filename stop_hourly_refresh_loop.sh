#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/.hourly_refresh.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No PID file found. Loop is not running."
  exit 0
fi

PID="$(cat "$PID_FILE" || true)"
if [[ -z "$PID" ]]; then
  rm -f "$PID_FILE"
  echo "Empty PID file removed."
  exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped dashboard refresh loop (pid=$PID)"
else
  echo "Process $PID not running; cleaning stale PID file."
fi
rm -f "$PID_FILE"
