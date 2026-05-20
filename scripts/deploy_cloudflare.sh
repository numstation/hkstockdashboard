#!/usr/bin/env bash
# Sync latest JSON + frontend, then deploy to Cloudflare Worker (hkstockdashboard).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CF="$ROOT/cloudflare"
PUBLIC="$CF/public"

echo "==> 1/4 Sync JSON from repo root → frontend/data/"
bash "$ROOT/scripts/sync_frontend_data.sh"

echo "==> 2/4 Copy frontend/ → cloudflare/public/frontend/"
rm -rf "$PUBLIC"
mkdir -p "$PUBLIC"
cp -R "$ROOT/frontend" "$PUBLIC/frontend"

# Optional: redirect site root to dashboard
cat > "$PUBLIC/index.html" <<'EOF'
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=/frontend/index.html">
  <title>Redirecting…</title>
</head>
<body>
  <p><a href="/frontend/index.html">Open 技術掃描 Dashboard</a></p>
</body>
</html>
EOF

echo "==> 3/4 Install npm deps (Wrangler)"
cd "$CF"
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

echo "==> 4/4 Deploy to Cloudflare (worker name: hkstockdashboard)"
# Always use cloudflare/wrangler.toml — a stray repo-root wrangler.jsonc with assets "."
# would upload the whole tree (including node_modules/workerd) and hit the 25 MiB limit.
if [[ -x "$CF/node_modules/.bin/wrangler" ]]; then
  "$CF/node_modules/.bin/wrangler" deploy --config "$CF/wrangler.toml"
else
  ( cd "$CF" && npx wrangler deploy --config wrangler.toml )
fi

echo ""
echo "Done. Open: https://hkstockdashboard.chrislau.workers.dev/frontend/"
echo "Check JSON: https://hkstockdashboard.chrislau.workers.dev/frontend/data/daily_scan.json"
echo "Hard-refresh browser: Cmd+Shift+R"
