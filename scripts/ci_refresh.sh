#!/usr/bin/env bash
# Used by GitHub Actions: HK scan + triggers + macro (大佬三原色) every run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[$(date -Iseconds)] CI refresh start"

echo "==> Merge live history into repo (union — never shrink)"
python3 "$ROOT/scripts/merge_live_dashboard_json.py" || echo "::warning:: merge_live_dashboard_json failed — continuing"

echo "==> Self-heal missing weekday breadth (before scan)"
python3 "$ROOT/scripts/ensure_recent_breadth.py" --market HK --days 10 --sleep 0.08 || echo "::warning:: ensure_recent_breadth HK failed"

python3 run_scan_export_json.py --sleep 0.15 --skip-macro
python3 scripts/export_triggers_from_scan.py

echo "Running macro_snapshot export (大佬三原色 / VIX·DXY·市寬)"
if python3 run_scan_export_json.py --macro-only; then
  echo "macro_snapshot.json updated"
else
  echo "::warning:: macro_snapshot export failed — deploy keeps previous macro_snapshot.json if present"
fi

echo "==> Market catalysts (HK macro + filtered Yahoo RSS)"
if python3 "$ROOT/scripts/export_market_catalysts_hk.py" --sleep 0.12; then
  echo "market_catalysts_hk.json updated"
else
  echo "::warning:: market catalysts export failed — deploy keeps previous file if present"
fi

echo "==> Self-heal missing weekday breadth (last 10 sessions)"
python3 "$ROOT/scripts/ensure_recent_breadth.py" --market HK --days 10 --sleep 0.08 || echo "::warning:: ensure_recent_breadth HK failed"

echo "==> Merge again after scan + backfill"
python3 "$ROOT/scripts/merge_live_dashboard_json.py" || echo "::warning:: post-scan merge failed"

bash "$ROOT/scripts/sync_frontend_data.sh"

echo "[$(date -Iseconds)] CI refresh done (HK)"
