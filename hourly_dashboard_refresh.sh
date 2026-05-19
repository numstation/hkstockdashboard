#!/usr/bin/env bash
# Refresh JSON artifacts for the static dashboard (all tickers + technical scores).
# Schedule every 30 minutes via cron, for example:
#   */30 * * * * /path/to/backtest/hourly_dashboard_refresh.sh >> /path/to/backtest/logs/hourly_refresh.log 2>&1
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "python3 not found" >&2
  exit 1
fi
# Fast path: skip macro (run `python run_scan_export_json.py --macro-only` on the hour if needed).
exec "$PY" "$ROOT/run_scan_export_json.py" --sleep 0.15 --skip-macro "$@"
