#!/usr/bin/env bash
# Copy US scan JSON into frontend-us/data/ for static hosting.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/frontend-us/data"
if [[ -f "$ROOT/us_top200.txt" ]]; then
  python3 "$ROOT/scripts/export_us_stock_names.py"
fi
for f in daily_scan_us.json daily_scan_us_sell_put.json daily_scan_us_buy_stock.json daily_scan_us_buy_put.json; do
  if [[ -f "$ROOT/$f" ]]; then
    cp "$ROOT/$f" "$ROOT/frontend-us/data/$f"
  fi
done
echo "Synced US JSON → frontend-us/data/ ($(date -Iseconds))"
