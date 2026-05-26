#!/usr/bin/env bash
# Used by GitHub Actions: HK scan + triggers + macro (大佬三原色) every run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[$(date -Iseconds)] CI refresh start"
python3 run_scan_export_json.py --sleep 0.15 --skip-macro
python3 scripts/export_triggers_from_scan.py

echo "Running macro_snapshot export (大佬三原色 / VIX·DXY·市寬)"
if python3 run_scan_export_json.py --macro-only; then
  echo "macro_snapshot.json updated"
else
  echo "::warning:: macro_snapshot export failed — deploy keeps previous macro_snapshot.json if present"
fi

bash "$ROOT/scripts/sync_frontend_data.sh"

echo "==> US scan (us_top200) → daily_scan_us*.json"
if python3 run_scan_export_json.py US --sleep 0.2 --skip-macro --scan-prefix us; then
  echo "daily_scan_us.json updated"
else
  echo "::warning:: US scan export failed — deploy keeps previous frontend-us/data if present"
fi
bash "$ROOT/scripts/sync_frontend_us_data.sh"

echo "[$(date -Iseconds)] CI refresh done"
