#!/usr/bin/env bash
# Run HK universe scan + JSON export for the dashboard.
# Install once for automation (macOS example, 17:30 HKT weekdays):
#   crontab -e
#   30 17 * * 1-5 /Users/chrislau/Documents/IT/backtest/scripts/run_daily_scan.sh >> /Users/chrislau/Documents/IT/backtest/scan_cron.log 2>&1

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

ulimit -n 4096 2>/dev/null || true

echo "[$(date -Iseconds)] daily scan start"
python3 run_scan_export_json.py --sleep 0.2 "$@"
python3 scripts/export_triggers_from_scan.py
bash "$ROOT/scripts/sync_frontend_data.sh"
echo "[$(date -Iseconds)] daily scan done"
