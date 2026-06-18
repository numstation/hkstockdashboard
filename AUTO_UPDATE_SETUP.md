# Make the website auto-update (Cloudflare)

Live site: **https://hkstockdashboard.chrislau.workers.dev/frontend/**

The site does **not** update by itself until GitHub Actions can **scan** and **deploy to Cloudflare**. Follow this checklist once.

---

## 頂部宏觀走馬燈（HSI · 上證 · 10Y · DXY · VIX · 北水）

`macro_snapshot.json` 內有 **`ticker_bar`**（頂部捲動列）與 **`southbound_connect`**（港股通北水淨額，億人民幣，來自東方財富 API，與舊版 Stock Analysis 相同邏輯）。每次 CI **`macro-only`** 匯出會一併更新；**大佬三原色**分頁的「資金溫度計」亦會顯示北水。

---

## 大佬三原色 / `macro_snapshot.json` looks stale

The Macro tab reads **`macro_snapshot.json`** (`last_updated` at the top). If the date is days old while the stock scan updates:

1. **CI used to skip macro on half the runs** (only at **:00 UTC**, not **:30**). That is fixed: **`scripts/ci_refresh.sh`** now runs **`python3 run_scan_export_json.py --macro-only`** on **every** refresh, then **`scripts/sync_frontend_data.sh`** before deploy.
2. If Yahoo/rate limits fail, the log shows **`::warning:: macro_snapshot export failed`** and the site keeps the last good file — re-run Actions or run locally:
   ```bash
   python3 run_scan_export_json.py --macro-only
   bash scripts/sync_frontend_data.sh
   bash scripts/deploy_cloudflare.sh
   ```
3. Hard-refresh the dashboard (**Cmd+Shift+R**). Check live JSON:  
   `https://hkstockdashboard.chrislau.workers.dev/frontend/data/macro_snapshot.json` → **`last_updated`** should match today after a green deploy.

---

## Breadth chart missing days (e.g. only 18–22 May + today)

**Cause:** GitHub Actions checks out **`breadth_daily_history.json`** / **`signals_history.json`** from git, which often lag by many days. Each scheduled deploy copies that sparse file to Cloudflare and only appends **today’s** scan — so dates that were fixed manually but **never committed** disappear on the next auto run.

**Fix in repo:** `scripts/merge_live_dashboard_json.py` runs at the start of **`ci_refresh.sh`** and before HK deploy, merging live `/frontend/data/*.json` into the workspace. After changing this, run one full local scan + deploy, and **commit** updated history JSON (or keep running merge + scan until git catches up).

**Quick check:**  
`curl -s …/breadth_daily_history.json | jq '[.days[].date]|unique'` — should include each trading day in the last 7 sessions.

**Backfill one missing day** (scores + breadth, fixes 連續性 when a session was lost):

```bash
.venv-scan/bin/python scripts/backfill_trading_day.py --date 2026-05-27
bash scripts/sync_frontend_data.sh
DEPLOY_MARKET=hk bash scripts/deploy_cloudflare.sh
```

US breadth uses **`breadth_daily_history_us.json`** (separate file). Manual deploy should use **`DEPLOY_MARKET=both`** so HK history is not replaced by stale live JSON when only updating US.

---

## HK / US deploy loop (one market wipes the other)

**Symptom:** HK loses 25–28 May after a US deploy; US breadth shows one bar only.

**Cause:** `DEPLOY_MARKET=us` used to **pull HK JSON from live** (already sparse) and redeploy it. Scheduled HK CI then deploys stale git checkout again. US **`breadth_daily_history_us.json`** was never on live (404) → chart fell back to today only.

**Fix in repo:** `deploy_cloudflare.sh` now **always merge live + repo then sync** for HK; US uses repo + merge. Use **`DEPLOY_MARKET=both`** for local deploys. Push `scripts/merge_live_dashboard_json.py` + deploy script changes to **`main`** so CI keeps the union.

### Anti-loop (history keeps disappearing)

Three scripts run on **every CI refresh and deploy**:

| Script | Role |
|--------|------|
| `merge_live_dashboard_json.py` | Union live + repo + `frontend/data` — **never drop** a breadth date |
| `ensure_recent_breadth.py` | Yahoo backfill for **missing weekdays** in last 10 sessions (fixes 25–28 May when git never had them) |
| `guard_deploy_history.py` | **Aborts deploy** if bundled JSON would have **fewer** breadth dates than live |

HK and US workflows deploy with **`DEPLOY_MARKET=hk`** / **`DEPLOY_MARKET=us`** so one market’s deploy cannot wipe the other.

---

## Hard refresh on Mac (when Cmd+Shift+R does nothing)

JSON loads already use `?ts=` cache-bust — stale UI is usually **old HTML**, not cached JSON.

| Browser | Try |
|---------|-----|
| **Safari** | Enable **Develop** menu (Safari → Settings → Advanced → “Show Develop”). Then **Develop → Empty Caches**, then **Cmd+R**. |
| **Chrome** | **View → Developer → Empty Cache and Hard Reload** (DevTools open), or hold **Shift** and click the reload button. |
| **Any** | Open dashboard in a **Private / Incognito** window once to confirm. |

---

## Full Market History: **Buy Put** tab empty

The history tab reads **`signals_history.json`**, filtered by **`score_model=buy_put`** and **`action=BUY_PUT`**.

If **Sell Put / Buy Stock** show rows but **Buy Put** does not, the usual cause was Python **`evaluate_trade_trigger`** not implementing **buy_put** (only sell_put / buy_stock were logged). That is fixed in **`daily_scanner.py`**; the next scan or **`python3 scripts/export_triggers_from_scan.py`** backfills from **`daily_scan_buy_put.json`**.

---

## Schema version shows `1.3` instead of `4.0`

Old files used `"schema_version": "1.3"`. If the site still shows **1.3**, the live Worker is often serving **stale JSON** (old commit or deploy without a new scan).

**Fix in this repo:** `schema_versioning` now applies a **minimum of `4.0`** on every export, and `schema_version_meta.json` is pegged so CI starts from **≥ 4.0**. Push to `main`, run Actions once, then hard-refresh the dashboard.

Disable the floor locally (only if needed):

```bash
export DASHBOARD_SCHEMA_MIN_VERSION=
```

---

## Actions shows **exit code 127** (“command not found”)

**Common causes:**

1. **Scan step** — script used **`python`** instead of **`python3`**. Fixed: **`scripts/ci_refresh.sh`** + **`python3 -m pip`** in workflows.
2. **Deploy to Cloudflare** — **`npx wrangler`** can fail if **`npx`** isn’t on `PATH`. Fixed: **`deploy_cloudflare.sh`** runs **`cloudflare/node_modules/.bin/wrangler deploy`** after **`npm ci`**.

Pull latest **`main`**, push, then re-run **Cloudflare auto update**.

---

## Actions shows **exit code 1** (`scan-and-artifact` / **Refresh** / **Deploy**)

**Code 1** means a step **actually failed** (unlike the **Node.js 20** line, which is only a **deprecation warning** until GitHub switches defaults).

Open the failed run, expand the **first red step**, and match it here:

| Step | Typical cause |
|------|----------------|
| **Refresh dashboard JSON** | `run_scan_export_json.py` crashed (network, yfinance, missing deps). Read the Python traceback in the log. |
| **Deploy to Cloudflare** | `scripts/validate_scan_json.py` exited 1: not enough `data_ok` rows — Yahoo rate limits in CI. Workflows set **`SCAN_VALIDATE_MIN_OK=40`** for automated runs; raise/remove that env on the job if you want the strict **50** bar. |
| **Upload refreshed site as artifact** | Rare; usually upstream step failed (`always()` still runs). |

Workflows pin **`actions/checkout`**, **`setup-python`**, **`setup-node`**, and **`upload-artifact`** to current majors (**v6 / v7**) that **target Node.js 24** natively, so you should not see the old “Node 20 / forced to Node 24” noise after **`main`** includes those files.

---

## Deploy: **`Asset too large`** / `workerd` (~80–100 MiB)

Wrangler reported the assets directory included **`node_modules/workerd/...`**. That happens if a config sets **`assets.directory`** to **`.`** (repo root): the whole repository—including **`cloudflare/node_modules`**—is uploaded as static files.

**Fix in this repo:** only **`cloudflare/wrangler.toml`** defines assets (`./public` copied by **`scripts/deploy_cloudflare.sh`**). Do **not** add a root **`wrangler.jsonc`** with **`"assets": { "directory": "." }`**. **`deploy_cloudflare.sh`** calls **`wrangler deploy --config cloudflare/wrangler.toml`** so the correct bundle is always used.

---

## If Actions failed with `Get Pages site failed` / HttpError Not Found

The old **Dashboard refresh** workflow tried to use **GitHub Pages** (`configure-pages`). That call returns **404** until you enable Pages in **Settings → Pages → Build: GitHub Actions**.

**You can ignore GitHub Pages** if you only use Cloudflare — this repo has a **`dashboard.yml` that does not use Pages**. If Actions still prints `configure-pages` / **job `refresh-and-deploy`**, then **GitHub’s `main` does not contain that fixed file yet** (push/sync problem).

Check the file on GitHub (replace if it still shows `configure-pages`):

`https://github.com/numstation/hkstockdashboard/blob/main/.github/workflows/dashboard.yml`

After a successful update, the workflow name is **“Dashboard refresh (scan + artifact)”** and the job is **`scan-and-artifact`** (not `refresh-and-deploy`).

---

## Checklist (one time, ~10 minutes)

### 1. GitHub Actions must be ON

1. Open your repo on GitHub → **Settings** → **Actions** → **General**
2. Under **Actions permissions**, choose **Allow all actions**
3. Save

(Private repos: free accounts get limited minutes/month; that is usually enough for ~30 min scans on weekdays.)

### 2. Add Cloudflare API token to GitHub

1. [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens) → **Create Token**
2. Template: **Edit Cloudflare Workers** → Continue → Create
3. Copy the token (shown once)
4. GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
   - Name: `CLOUDFLARE_API_TOKEN` (exact spelling)
   - Value: paste token

### 3. Push this project (or enable the workflow file)

Ensure both workflow files are on `main`:
- `.github/workflows/cloudflare-auto.yml` (HK)
- `.github/workflows/cloudflare-auto-us.yml` (US)

### 4. Test manually once

1. GitHub → **Actions** → **Cloudflare auto update**
2. **Run workflow** → Run
3. Wait ~15–25 minutes until green ✓
4. Open: https://hkstockdashboard.chrislau.workers.dev/frontend/data/daily_scan.json  
   - Check `last_updated` is recent  
   - Open site → **Cmd+Shift+R**

If step 4 fails with `Missing CLOUDFLARE_API_TOKEN`, repeat step 2.

---

## What runs automatically after setup

| When | What happens |
|------|----------------|
| **Mon–Fri** every **30 min** (HK ~09:00–**17:30**) | **HK** scan → `daily_scan.json` → deploy (`cloudflare-auto.yml`) |
| **Mon–Fri** every **30 min** (HKT **21:40–04:40**) | **US** scan → `daily_scan_us.json` → deploy (`cloudflare-auto-us.yml`) |
| **You push** code | Dashboard workflow may also run (HK scan + deploy if token set) |
| **Manual** | Actions → **Cloudflare auto update** or **Cloudflare auto update (US)** → Run workflow |
| **Dashboard button** | **Scan only** → `POST /api/refresh` → same GitHub workflow (see below) |

US and HK use **different GitHub cron windows** because US cash session is evening–early-morning in Hong Kong (not the same as HKEX 09:00–16:30). US runs start **21:40 HKT** (10 minutes after US open ≈ 21:30 HKT in EDT) and repeat **every 30 minutes** through **04:40 HKT** (after US cash close). HK and US deploys use separate `DEPLOY_MARKET` scopes so neither overwrites the other’s JSON.

You do **not** need to run Terminal commands when this works.

---

## If it still does not update

| Symptom | Fix |
|--------|-----|
| Actions tab empty / disabled | Enable Actions (step 1); private repo may need billing |
| Red X on **Validate scan** | Yahoo failed (all `fetch_failed`); re-run workflow later |
| Red X on **Deploy** | Wrong or missing `CLOUDFLARE_API_TOKEN` |
| Cloudflare old time, Actions green | Hard refresh browser; check JSON URL `last_updated` |
| No runs on schedule | Repo default branch must be `main` or `master`; cron is UTC |
| US page stale after ~4:30pm HKT | Normal until evening US cron; HK deploy no longer clears US JSON |
| HK page goes stale after US deploy | Fixed: US workflow sets `DEPLOY_MARKET=us` and pulls HK JSON from live |
| **Scan only** → `GITHUB_PAT not configured` | Add repo secret **`DASHBOARD_GITHUB_PAT`**, then run **Cloudflare auto update** |
| **Scan only** → API 未部署 | Push/deploy failed — check Actions log for wrangler error |
| **Scan only** → cooldown / already running | Wait 10 min or until the in-progress Actions run finishes |

---

## On-demand refresh (**Scan only**)

The dashboard can trigger a **new scan + deploy** from the browser (not just reload cached JSON).

| Button | What it does |
|--------|----------------|
| **Reload Data** | Fetch latest JSON already on Cloudflare (instant) |
| **Scan only** | Queue GitHub Actions scan → deploy → auto-reload when `last_updated` is newer |

### One-time setup (private repo) — simple guide

**Skip SSO** — if you don't see "Configure SSO" anywhere, ignore it. Most accounts don't need it.

You need a **classic** GitHub password-for-apps called a **token**. It must start with **`ghp_`** (not `github_pat_`).

---

#### Part 1 — Create the token (5 minutes)

1. Open this link in your browser:  
   **https://github.com/settings/tokens/new**

2. You should see **"New personal access token (classic)"** at the top.  
   If you see "Fine-grained" instead, click **"Personal access tokens"** → **"Tokens (classic)"** → **"Generate new token (classic)"**.

3. Fill in:
   - **Note:** type `dashboard-scan`
   - **Expiration:** pick 90 days (or No expiration if you prefer)

4. Under **Select scopes**, tick **only these two**:
   - ☑ **repo** — click the main **repo** checkbox (all sub-boxes under it tick automatically)
   - ☑ **workflow**

5. Scroll down → click green **Generate token**

6. GitHub shows a green box with a long code starting with **`ghp_`**.  
   Click **Copy** (or select all and copy).  
   **Save it in Notes app** — you won't see it again.

---

#### Part 2 — Save token in GitHub (repo secret)

1. Open:
   **https://github.com/numstation/hkstockdashboard/settings/secrets/actions**

2. You should see a heading **Repository secrets** and a green button **New repository secret**.

3. **If `DASHBOARD_GITHUB_PAT` is already in the list** (you already have this):
   - Find the row **`DASHBOARD_GITHUB_PAT`**
   - On the **right side of that row**, click the **pencil icon** ✏️ (GitHub does **not** show a button called "Update")
   - You get a page titled **Update secret**
   - Paste your new **`ghp_…`** into the **Value** box
   - Click green **Update secret**

   **Can't find the pencil?** Delete and recreate instead:
   - Click the **trash** icon 🗑 on that row → confirm delete
   - Click **New repository secret**
   - Name: `DASHBOARD_GITHUB_PAT`
   - Value: paste **`ghp_…`**
   - Click **Add secret**

4. **If `DASHBOARD_GITHUB_PAT` is NOT in the list:**
   - Click **New repository secret**
   - Name: `DASHBOARD_GITHUB_PAT`
   - Value: paste **`ghp_…`**
   - Click **Add secret**

5. Back on the list, **`DASHBOARD_GITHUB_PAT`** should show **Last updated** = today (e.g. a few seconds ago).

**Wrong page?** Make sure the URL ends with **`/settings/secrets/actions`** — not "Codespaces secrets" or "Dependabot secrets".

---

#### Part 3 — Copy token to Cloudflare (important — do this too)

GitHub secret alone is not enough until deploy runs. This step puts the token directly on the live website server:

1. Open: **https://dash.cloudflare.com** → log in

2. Left menu → **Workers & Pages**

3. Click **`hkstockdashboard`**

4. Tab **Settings** → section **Variables and Secrets**

5. Under **Secrets**, click **Add**

6. **Name:** `GITHUB_PAT` (exactly — not DASHBOARD_GITHUB_PAT)

7. **Value:** paste the **same** `ghp_…` code again

8. **Save**

---

#### Part 4 — Run deploy (sync everything)

1. Open:  
   **https://github.com/numstation/hkstockdashboard/actions/workflows/cloudflare-auto.yml**

2. Click **Run workflow** (right side) → **Run workflow**

3. Wait until the row shows a **green tick** (~5 minutes)

---

#### Part 5 — Test Scan only

1. Open your dashboard:  
   **https://hkstockdashboard.chrislau.workers.dev/frontend/**

2. Hard refresh: **Cmd + Shift + R**

3. Click **Scan only**

4. You should see **「掃描已排隊」** or **「掃描中（約 5 分鐘）…」** — not a red error.

---

#### Still broken?

| Check | What to verify |
|-------|----------------|
| Token type | Must start with **`ghp_`**, not `github_pat_` |
| Scopes | Both **repo** and **workflow** were ticked |
| Cloudflare secret name | Must be **`GITHUB_PAT`** on Workers page |
| GitHub secret name | Must be **`DASHBOARD_GITHUB_PAT`** |
| Deploy | Green ✓ on **Cloudflare auto update** **after** you saved the token |

### Behaviour

- **Cooldown:** 10 minutes between triggers (Worker var `REFRESH_COOLDOWN_MIN`)
- **Blocks** if a scan is already `queued` / `in_progress`
- HK button → `cloudflare-auto.yml`; US button → `cloudflare-auto-us.yml`
- Polls up to ~8 minutes, then reloads tables when deploy completes

### Test

```bash
curl -s https://hkstockdashboard.chrislau.workers.dev/api/refresh/status?market=hk | python3 -m json.tool
# POST (add -H "X-Refresh-Key: YOUR_SECRET" if REFRESH_SECRET is set):
curl -s -X POST https://hkstockdashboard.chrislau.workers.dev/api/refresh \
  -H "Content-Type: application/json" \
  -d '{"market":"hk"}'
```

---

## Optional: Mac cron (backup)

If GitHub Actions is off, on your Mac:

```bash
crontab -e
```

Add (weekdays 9:15 AM HK ≈ adjust for your timezone):

```cron
15 1 * * 1-5 cd /Users/chrislau/Documents/IT/backtest && python3 run_scan_export_json.py --skip-macro && bash scripts/deploy_cloudflare.sh
```

---

## Summary

**Auto-update = GitHub secret `CLOUDFLARE_API_TOKEN` + HK/US workflows on schedule.**

- HK: https://hkstockdashboard.chrislau.workers.dev/frontend/
- US: https://hkstockdashboard.chrislau.workers.dev/frontend-us/

Without the token, only manual `bash scripts/deploy_cloudflare.sh` updates Cloudflare.
