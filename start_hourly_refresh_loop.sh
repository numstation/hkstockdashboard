#!/usr/bin/env bash
# Fallback refresher (every 30 minutes) started from interactive shell (works in protected folders like Documents).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/logs"
PID_FILE="$ROOT/.hourly_refresh.pid"
LOOP_LOG="$LOG_DIR/hourly_refresh.loop.log"
mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Dashboard refresh loop already running (pid=$OLD_PID)"
    exit 0
  fi
fi

nohup bash -lc "
while true; do
  echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] refresh start\"
  \"$ROOT/hourly_dashboard_refresh.sh\"
  echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] refresh done\"
  sleep 1800
done
" >> "$LOOP_LOG" 2>&1 &

echo $! > "$PID_FILE"
echo "Started dashboard refresh loop every 30m (pid=$(cat "$PID_FILE"))"
echo "log: $LOOP_LOG"
