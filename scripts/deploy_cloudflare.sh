#!/usr/bin/env bash
# Build Cloudflare static bundle and deploy.
#
# DEPLOY_MARKET controls which scan JSON is refreshed from the repo workspace:
#   hk   — HK workflow: fresh HK JSON + keep US JSON from live site
#   us   — US workflow: fresh US JSON + keep HK JSON from live site
#   both — local/manual: sync both from repo (fallback to live if missing)
#
# HK and US workflows share one Worker asset bundle; without this split each
# deploy overwrote the other market with stale git checkout files.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CF="$ROOT/cloudflare"
PUBLIC="$CF/public"
BASE_URL="${DASHBOARD_BASE_URL:-https://hkstockdashboard.chrislau.workers.dev}"
DEPLOY_MARKET="${DEPLOY_MARKET:-both}"

HK_JSON_FILES=(
  daily_scan.json
  daily_scan_sell_put.json
  daily_scan_buy_stock.json
  daily_scan_buy_put.json
  macro_snapshot.json
  signals_history.json
  breadth_daily_history.json
  score_daily_history.json
  future_log.json
)

US_JSON_FILES=(
  daily_scan_us.json
  daily_scan_us_sell_put.json
  daily_scan_us_buy_stock.json
  daily_scan_us_buy_put.json
  breadth_daily_history_us.json
  signals_history_us.json
  closed_transactions_us.json
)

_is_valid_json() {
  local path="$1"
  python3 - <<PY
import json, sys
try:
    json.load(open("$path", "r", encoding="utf-8"))
except Exception:
    sys.exit(1)
PY
}

_fetch_live_json() {
  local url_path="$1"
  local dst="$2"
  local tmp="${dst}.tmp"

  rm -f "$tmp" || true
  if ! curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 90 \
    --user-agent "Mozilla/5.0 (compatible; backtest-dashboard/1.0)" \
    "${BASE_URL}${url_path}" > "$tmp"; then
    rm -f "$tmp" || true
    echo "::warning:: live fetch failed: ${url_path}"
    return 1
  fi
  if ! _is_valid_json "$tmp"; then
    rm -f "$tmp" || true
    echo "::warning:: live fetch not JSON (missing asset?): ${url_path}"
    return 1
  fi
  mv "$tmp" "$dst"
  return 0
}

_pull_live_market_data() {
  local market="$1"
  local data_dir="$2"
  local required="${3:-0}"
  local -a files
  local url_prefix

  mkdir -p "$data_dir"

  if [[ "$market" == "hk" ]]; then
    url_prefix="/frontend/data"
    files=("${HK_JSON_FILES[@]}")
  else
    url_prefix="/frontend-us/data"
    files=("${US_JSON_FILES[@]}")
  fi

  echo "==> Pull ${market} JSON from live (${BASE_URL})"
  local ok=0
  for f in "${files[@]}"; do
    if _fetch_live_json "${url_prefix}/${f}" "${data_dir}/${f}"; then
      ok=$((ok + 1))
    fi
  done
  echo "    fetched ${ok}/${#files[@]} files"

  local primary=""
  if [[ "$market" == "hk" ]]; then primary="daily_scan.json"; else primary="daily_scan_us.json"; fi
  if [[ ! -f "${data_dir}/${primary}" ]]; then
    if [[ "$required" == "1" ]]; then
      echo "::error:: Could not fetch live ${market} ${primary} — aborting deploy."
      exit 1
    fi
    echo "::warning:: live ${market} ${primary} missing — deploy continues with partial ${market} data."
  fi
}

_prepare_hk_data() {
  local data_dir="$ROOT/frontend/data"
  mkdir -p "$data_dir"

  echo "==> HK JSON: ensure recent breadth → merge live+repo → sync"
  python3 "$ROOT/scripts/ensure_recent_breadth.py" --market HK --days 10 --sleep 0.05 \
    || echo "::warning:: ensure_recent_breadth HK failed"
  python3 "$ROOT/scripts/merge_live_dashboard_json.py" \
    || echo "::warning:: merge_live_dashboard_json failed — continuing with repo files"
  bash "$ROOT/scripts/sync_frontend_data.sh"
}

_prepare_us_data() {
  local data_dir="$ROOT/frontend-us/data"
  mkdir -p "$data_dir"

  if [[ "$DEPLOY_MARKET" == "us" || "$DEPLOY_MARKET" == "both" ]]; then
    echo "==> US JSON: ensure recent breadth → merge live+repo → sync"
    python3 "$ROOT/scripts/ensure_recent_breadth.py" --market US --days 10 --sleep 0.05 \
      || echo "::warning:: ensure_recent_breadth US failed"
    python3 "$ROOT/scripts/merge_live_dashboard_json.py" \
      || echo "::warning:: merge_live_dashboard_json failed before US sync"
    bash "$ROOT/scripts/sync_frontend_us_data.sh"
  else
    echo "==> US JSON: copy from repo (HK-only deploy — no live pull)"
    bash "$ROOT/scripts/sync_frontend_us_data.sh" 2>/dev/null || true
    for f in daily_scan_us.json daily_scan_us_sell_put.json daily_scan_us_buy_stock.json \
      daily_scan_us_buy_put.json breadth_daily_history_us.json signals_history_us.json \
      closed_transactions_us.json; do
      if [[ -f "$ROOT/$f" ]]; then
        cp "$ROOT/$f" "$data_dir/$f"
      fi
    done
  fi
}

echo "==> Deploy market scope: ${DEPLOY_MARKET}"
_prepare_hk_data
_prepare_us_data

echo "==> Copy static UI → cloudflare/public/"
rm -rf "$PUBLIC"
mkdir -p "$PUBLIC/frontend" "$PUBLIC/frontend-us"
cp "$ROOT/frontend/index.html" "$PUBLIC/frontend/index.html"
cp "$ROOT/frontend-us/index.html" "$PUBLIC/frontend-us/index.html"
cp -R "$ROOT/frontend/data" "$PUBLIC/frontend/data"
cp -R "$ROOT/frontend-us/data" "$PUBLIC/frontend-us/data"

cat > "$PUBLIC/index.html" <<'EOF'
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=/frontend/index.html">
  <title>Redirecting…</title>
</head>
<body>
  <p><a href="/frontend/index.html">HK 技術掃描</a> · <a href="/frontend-us/index.html">US 技術掃描</a></p>
</body>
</html>
EOF

echo "==> Guard: block deploy if history would shrink vs live"
python3 "$ROOT/scripts/guard_deploy_history.py"

echo "==> Install npm deps (Wrangler)"
cd "$CF"
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

echo "==> Deploy to Cloudflare (worker name: hkstockdashboard)"
if [[ -x "$CF/node_modules/.bin/wrangler" ]]; then
  "$CF/node_modules/.bin/wrangler" deploy --config "$CF/wrangler.toml"
else
  ( cd "$CF" && npx wrangler deploy --config wrangler.toml )
fi

echo "Done (${DEPLOY_MARKET}). Open:"
echo "  HK: https://hkstockdashboard.chrislau.workers.dev/frontend/"
echo "  US: https://hkstockdashboard.chrislau.workers.dev/frontend-us/"
echo "Hard-refresh browser: Safari Develop→Empty Caches then reload; Chrome hold Shift+click Reload"
