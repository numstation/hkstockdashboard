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

  if [[ "$DEPLOY_MARKET" == "hk" || "$DEPLOY_MARKET" == "both" ]]; then
    echo "==> HK JSON: ensure recent breadth → merge live+repo → sync"
    python3 "$ROOT/scripts/ensure_recent_breadth.py" --market HK --days 10 --sleep 0.05 \
      || echo "::warning:: ensure_recent_breadth HK failed"
    python3 "$ROOT/scripts/merge_live_dashboard_json.py" \
      || echo "::warning:: merge_live_dashboard_json failed — continuing with repo files"
    bash "$ROOT/scripts/sync_frontend_data.sh"
  else
    echo "==> HK JSON: pull from live (US-only deploy must not downgrade HK scans)"
    _pull_live_market_data "hk" "$data_dir" "1"
  fi
}

_ensure_us_data_files() {
  local data_dir="$1"
  local -a extra=(us_stock_names.json)
  local -a files=("${US_JSON_FILES[@]}" "${extra[@]}")
  local filled=0

  for f in "${files[@]}"; do
    if [[ -f "${data_dir}/${f}" ]] && _is_valid_json "${data_dir}/${f}"; then
      continue
    fi
    if [[ -f "${ROOT}/${f}" ]] && _is_valid_json "${ROOT}/${f}"; then
      cp "${ROOT}/${f}" "${data_dir}/${f}"
      filled=$((filled + 1))
      echo "    restored US from repo root: ${f}"
      continue
    fi
    if [[ -f "${ROOT}/frontend-us/data/${f}" ]] && _is_valid_json "${ROOT}/frontend-us/data/${f}"; then
      cp "${ROOT}/frontend-us/data/${f}" "${data_dir}/${f}"
      filled=$((filled + 1))
      echo "    restored US from frontend-us/data: ${f}"
      continue
    fi
    if _fetch_live_json "/frontend-us/data/${f}" "${data_dir}/${f}"; then
      filled=$((filled + 1))
      echo "    restored US from live: ${f}"
    fi
  done
  echo "    US backfill total: ${filled} file(s)"
}

_verify_us_scan_in_bundle() {
  local primary="${PUBLIC}/frontend-us/data/daily_scan_us_sell_put.json"
  if [[ ! -f "$primary" ]] || ! _is_valid_json "$primary"; then
    echo "::error:: US scan missing from deploy bundle (${primary})."
    echo "         Commit daily_scan_us*.json to git or run: python3 run_scan_export_json.py US --skip-macro"
    exit 1
  fi
  local n
  n=$(python3 - <<PY
import json
d = json.load(open("${primary}", encoding="utf-8"))
print(len(d.get("stocks") or []))
PY
)
  if [[ "${n:-0}" -lt 50 ]]; then
    echo "::error:: US scan bundle has only ${n} stocks — aborting deploy (would break US page)."
    exit 1
  fi
  echo "==> US scan bundle OK (${n} stocks in daily_scan_us_sell_put.json)"
}

_merge_us_scan_file() {
  local name="$1"
  local data_dir="$2"
  local live_tmp="${data_dir}/${name}.live.tmp"
  local repo_a="${ROOT}/${name}"
  local repo_b="${ROOT}/frontend-us/data/${name}"
  local dest="${data_dir}/${name}"

  rm -f "$live_tmp" || true
  if _fetch_live_json "/frontend-us/data/${name}" "$live_tmp"; then
    if [[ -f "$repo_a" ]] && _is_valid_json "$repo_a"; then
      python3 "$ROOT/scripts/pick_newer_json.py" "$dest" "$live_tmp" "$repo_a" || cp "$live_tmp" "$dest"
    elif [[ -f "$repo_b" ]] && _is_valid_json "$repo_b"; then
      python3 "$ROOT/scripts/pick_newer_json.py" "$dest" "$live_tmp" "$repo_b" || cp "$live_tmp" "$dest"
    else
      mv "$live_tmp" "$dest"
    fi
    rm -f "$live_tmp" || true
  elif [[ -f "$repo_a" ]] && _is_valid_json "$repo_a"; then
    cp "$repo_a" "$dest"
  elif [[ -f "$repo_b" ]] && _is_valid_json "$repo_b"; then
    cp "$repo_b" "$dest"
  fi
}

_prepare_us_data() {
  local data_dir="$ROOT/frontend-us/data"
  mkdir -p "$data_dir"

  if [[ "$DEPLOY_MARKET" == "us" ]]; then
    echo "==> US JSON: fresh scan → merge live+repo → sync"
    python3 "$ROOT/scripts/ensure_recent_breadth.py" --market US --days 10 --sleep 0.05 \
      || echo "::warning:: ensure_recent_breadth US failed"
    python3 "$ROOT/scripts/merge_live_dashboard_json.py" \
      || echo "::warning:: merge_live_dashboard_json failed before US sync"
    bash "$ROOT/scripts/sync_frontend_us_data.sh"
  elif [[ "$DEPLOY_MARKET" == "both" ]]; then
    echo "==> US JSON: manual/both — workspace + merge + sync"
    python3 "$ROOT/scripts/ensure_recent_breadth.py" --market US --days 10 --sleep 0.05 \
      || echo "::warning:: ensure_recent_breadth US failed"
    python3 "$ROOT/scripts/merge_live_dashboard_json.py" \
      || echo "::warning:: merge_live_dashboard_json failed before US sync"
    bash "$ROOT/scripts/sync_frontend_us_data.sh"
    _ensure_us_data_files "$data_dir"
  else
    echo "==> US JSON: preserve live site (HK deploy — never copy stale git over newer US scans)"
    if [[ -f "$ROOT/us_top300.txt" || -f "$ROOT/us_top200.txt" ]]; then
      python3 "$ROOT/scripts/export_us_stock_names.py" || true
    fi
    for f in daily_scan_us.json daily_scan_us_sell_put.json daily_scan_us_buy_stock.json daily_scan_us_buy_put.json; do
      _merge_us_scan_file "$f" "$data_dir"
    done
    _pull_live_market_data "us" "$data_dir" "0"
    _ensure_us_data_files "$data_dir"
  fi

  echo "==> US JSON: backfill any missing files"
  _ensure_us_data_files "$data_dir"
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

_verify_us_scan_in_bundle

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
