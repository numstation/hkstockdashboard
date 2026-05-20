# Make the website auto-update (Cloudflare)

Live site: **https://hkstockdashboard.chrislau.workers.dev/frontend/**

The site does **not** update by itself until GitHub Actions can **scan** and **deploy to Cloudflare**. Follow this checklist once.

---

## Schema version shows `1.3` instead of `4.0`

Old files used `"schema_version": "1.3"`. If the site still shows **1.3**, the live Worker is often serving **stale JSON** (old commit or deploy without a new scan).

**Fix in this repo:** `schema_versioning` now applies a **minimum of `4.0`** on every export, and `schema_version_meta.json` is pegged so CI starts from **≥ 4.0**. Push to `main`, run Actions once, then hard-refresh the dashboard.

Disable the floor locally (only if needed):

```bash
export DASHBOARD_SCHEMA_MIN_VERSION=
```

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

Ensure `.github/workflows/cloudflare-auto.yml` is on your `main` branch (commit + push).

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
| **Mon–Fri** every **30 min** (HK ~09:00–16:30) | Scan 133 stocks → validate → deploy Cloudflare |
| **You push** code | Old workflow may also run (Pages + Cloudflare if token set) |
| **Manual** | Actions → **Cloudflare auto update** → Run workflow |

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

**Auto-update = GitHub secret `CLOUDFLARE_API_TOKEN` + workflow `cloudflare-auto.yml` running on schedule.**

Without the token, only manual `bash scripts/deploy_cloudflare.sh` updates Cloudflare.
