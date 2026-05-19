#!/usr/bin/env bash
# Used by GitHub Actions: 133-stock scan + triggers; macro only on the hour (UTC).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[$(date -Iseconds)] CI refresh start"
python run_scan_export_json.py --sleep 0.15 --skip-macro
python scripts/export_triggers_from_scan.py

MIN_UTC="$(date -u +%M)"
if [ "$MIN_UTC" = "00" ] || [ "${REFRESH_MACRO:-}" = "1" ]; then
  echo "Running macro_snapshot export (hourly / forced)"
  python run_scan_export_json.py --macro-only
else
  echo "Skip macro this run (next at :00 UTC)"
fi

echo "[$(date -Iseconds)] CI refresh done"
