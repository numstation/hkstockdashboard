# Deploy HK Stock Hunter Pro API to Railway

The Cloudflare dashboard **HK Stock Hunter Pro** tab calls `POST /api/stock/analyze` on the Worker, which proxies to this Flask API.

## Prerequisites

- Code on GitHub: [numstation/hkstockdashboard](https://github.com/numstation/hkstockdashboard)
- A [Railway](https://railway.app) account

## 1. Create Railway service

1. **New Project** → **Deploy from GitHub repo** → select `hkstockdashboard`.
2. **Root directory:** leave blank (repo root has `Procfile`).
3. **Build command:**
   ```bash
   pip install -r stocktrackeryahoo/requirements.txt
   ```
4. **Start command:** leave empty — root `Procfile` runs:
   ```bash
   gunicorn --chdir stocktrackeryahoo -w 1 -b 0.0.0.0:$PORT --timeout 180 app:app
   ```
5. **Networking** → **Generate domain** → copy base URL (e.g. `https://xxx.up.railway.app`).

## 2. Verify API

```bash
curl -s -X POST "https://YOUR-APP.up.railway.app/api/v1/stock/analyze" \
  -H "Content-Type: application/json" \
  -d '{"stock_code":"700"}' | head -c 500
```

Expect JSON with `"ok": true`, `"factors"`, `"risk"`, `"ai_report"`.

Health check: `GET https://YOUR-APP.up.railway.app/health`

## 3. Wire Cloudflare Worker

Set Worker secret **`ANALYSIS_API_URL`** to the Railway base URL (no trailing slash):

```bash
cd cloudflare
npx wrangler secret put ANALYSIS_API_URL
# paste: https://YOUR-APP.up.railway.app
```

Or export before deploy:

```bash
export ANALYSIS_API_URL=https://YOUR-APP.up.railway.app
bash scripts/deploy_cloudflare.sh
```

## 4. Deploy dashboard UI

Commit and push Hunter Pro changes, then run the HK deploy workflow (or `bash scripts/deploy_cloudflare.sh`).

Open: https://hkstockdashboard.chrislau.workers.dev/frontend/ → tab **HK Stock Hunter Pro**.

## Notes

- First analysis per ticker may take 30–60s (yfinance + indicators). Gunicorn timeout is 180s.
- `ANALYSIS_API_URL` is set in `cloudflare/wrangler.toml` [vars] (Railway base URL). Override via GitHub secret or `wrangler secret put` if the domain changes.
- Optional env on Railway: `ALPHA_VANTAGE_API_KEY` if yfinance fails for some symbols.

## Cloudflare secret (choose one method)

**Dashboard often fails** with *“Variables cannot be added to a Worker that only has static assets”* — use **Wrangler CLI** or **GitHub Actions secret** instead.

### Method A — GitHub Actions (easiest if you already use CI deploy)

1. GitHub → repo **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. Name: `ANALYSIS_API_URL`
3. Value: `https://YOUR-APP.up.railway.app` (no trailing slash)
4. Run workflow **Cloudflare auto update** (Actions tab → Run workflow)

The deploy script runs `wrangler secret put ANALYSIS_API_URL` automatically.

### Method B — Wrangler CLI (Mac Terminal)

```bash
cd cloudflare
npx wrangler login
printf 'https://YOUR-APP.up.railway.app' | npx wrangler secret put ANALYSIS_API_URL --config wrangler.toml
```

Do **not** use the Cloudflare dashboard **Static assets** page — secrets attach to the **Worker script** (`hkstockdashboard`), not the assets-only UI.

## Updating

Push to `main` → Railway redeploys automatically. Re-run Cloudflare deploy only when `frontend/` or `cloudflare/` changes.
