#!/usr/bin/env bash
# GitHub Actions: US universe scan only (us_top200) → daily_scan_us*.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[$(date -Iseconds)] CI US refresh start"
if python3 run_scan_export_json.py US --sleep 0.2 --skip-macro --scan-prefix us; then
  echo "daily_scan_us.json updated"
else
  echo "::warning:: US scan export failed — deploy keeps previous frontend-us/data if present"
  exit 1
fi
bash "$ROOT/scripts/sync_frontend_us_data.sh"
echo "[$(date -Iseconds)] CI US refresh done"
