#!/usr/bin/env bash
# GitHub Actions: US universe scan only (us_top300.txt) → daily_scan_us*.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[$(date -Iseconds)] CI US refresh start"

echo "==> Merge live history into repo"
python3 "$ROOT/scripts/merge_live_dashboard_json.py" || echo "::warning:: merge failed"

if python3 run_scan_export_json.py US --sleep 0.2 --skip-macro; then
  echo "daily_scan_us.json updated"
else
  echo "::warning:: US scan export failed"
  exit 1
fi

echo "==> Self-heal missing US weekday breadth"
python3 "$ROOT/scripts/ensure_recent_breadth.py" --market US --days 10 --sleep 0.05 || echo "::warning:: ensure_recent_breadth US failed"

python3 "$ROOT/scripts/merge_live_dashboard_json.py" || echo "::warning:: post-scan merge failed"

bash "$ROOT/scripts/sync_frontend_us_data.sh"
echo "[$(date -Iseconds)] CI US refresh done"
