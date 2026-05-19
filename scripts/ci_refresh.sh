#!/usr/bin/env bash
# Used by GitHub Actions: 133-stock scan + triggers; macro only on the hour (UTC).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[$(date -Iseconds)] CI refresh start"
python run_scan_export_json.py --sleep 0.15 --skip-macro
python scripts/export_triggers_from_scan.py

# Mirror JSON beside index.html so GitHub Pages fetches work (frontend/data/*.json).
mkdir -p frontend/data
for f in daily_scan.json daily_scan_sell_put.json daily_scan_buy_stock.json daily_scan_buy_put.json \
  macro_snapshot.json signals_history.json breadth_daily_history.json score_daily_history.json future_log.json; do
  if [ -f "$ROOT/$f" ]; then
    cp "$ROOT/$f" "$ROOT/frontend/data/$f"
  fi
done
echo "Copied JSON → frontend/data/"

MIN_UTC="$(date -u +%M)"
if [ "$MIN_UTC" = "00" ] || [ "${REFRESH_MACRO:-}" = "1" ]; then
  echo "Running macro_snapshot export (hourly / forced)"
  python run_scan_export_json.py --macro-only
else
  echo "Skip macro this run (next at :00 UTC)"
fi

echo "[$(date -Iseconds)] CI refresh done"
