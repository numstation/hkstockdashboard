#!/usr/bin/env bash
# Copy repo-root JSON into frontend/data/ for static hosting (GitHub Pages + local http.server).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/frontend/data"
if [[ -f "$ROOT/hkstocklist.csv" ]]; then
  python3 "$ROOT/scripts/export_hk_stock_names.py"
  python3 "$ROOT/scripts/export_hk_index_membership.py"
fi
for f in daily_scan.json daily_scan_sell_put.json daily_scan_buy_stock.json daily_scan_buy_put.json \
  macro_snapshot.json market_catalysts_hk.json market_catalysts_earnings_hk.json \
  signals_history.json breadth_daily_history.json score_daily_history.json future_log.json \
  closed_transactions.json; do
  if [[ -f "$ROOT/$f" ]]; then
    cp "$ROOT/$f" "$ROOT/frontend/data/$f"
  fi
done
echo "Synced JSON → frontend/data/ ($(date -Iseconds))"
