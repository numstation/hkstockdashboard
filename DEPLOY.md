# Deploy dashboard (free: GitHub Pages + Actions)

Your dashboard is **static HTML + JSON**. GitHub runs the scan every ~30 minutes (weekdays) and publishes the site for free.

## What you get

| Item | Free service |
|------|----------------|
| Website | **GitHub Pages** → `https://<user>.github.io/<repo>/` |
| Data refresh | **GitHub Actions** cron (133 stocks, ~30m on HK weekdays) |
| Cost | **$0** on public repo |

---

## Step 1 — Create a GitHub repository

1. Open [https://github.com/new](https://github.com/new)
2. Repository name: e.g. `hk-stock-dashboard`
3. Visibility: **Public** (required for unlimited free Actions minutes)
4. Do **not** add README / .gitignore (we already have files)
5. Click **Create repository**

---

## Step 2 — Push this project from your Mac

Open Terminal:

```bash
cd /Users/chrislau/Documents/IT/backtest

git init
git add .
git status   # should show frontend/, daily_scanner.py, .github/, etc. — NOT .venv/

git commit -m "Initial dashboard for GitHub Pages"

git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/hk-stock-dashboard.git
git push -u origin main
```

Replace `YOUR_USERNAME` and repo name with yours.

If `git init` says the folder is already inside another repo, run `git init` only inside `backtest` (this folder should be its own repo).

---

## Step 3 — Enable GitHub Pages

1. On GitHub: repo → **Settings** → **Pages**
2. **Build and deployment** → Source: **GitHub Actions**
3. Save (no custom domain needed for now)

---

## Step 4 — First workflow run

1. Repo → **Actions** → workflow **Dashboard refresh & Pages deploy**
2. Click **Run workflow** → Run (check “refresh macro” if 大佬三原色 is empty)
3. Wait ~10–20 minutes (first run installs deps + scans 133×3 models)
4. When green ✓, open the URL from the job summary (**github-pages** link)

Your dashboard:

- `https://YOUR_USERNAME.github.io/hk-stock-dashboard/`
- or `.../frontend/index.html`

---

## Step 5 — Automatic 30-minute updates

Already configured in `.github/workflows/dashboard.yml`:

- **When:** Mon–Fri, every 30 minutes (UTC 01:00–08:30 ≈ HK 09:00–16:30)
- **What:** Full scan (133 names, 3 models) + trigger history
- **Macro (大佬三原色):** Once per hour on the hour (UTC); full macro on manual “Run workflow”

No Mac needs to stay on; GitHub’s servers run the scan.

---

## Local 30-minute refresh (optional)

If your Mac is on during the day:

```bash
crontab -e
```

Add:

```cron
0,30 9-16 * * 1-5 /Users/chrislau/Documents/IT/backtest/hourly_dashboard_refresh.sh >> /Users/chrislau/Documents/IT/backtest/logs/hourly_refresh.log 2>&1
0 * * * 1-5 /Users/chrislau/Documents/IT/backtest/.venv/bin/python /Users/chrislau/Documents/IT/backtest/run_scan_export_json.py --macro-only >> /Users/chrislau/Documents/IT/backtest/logs/hourly_refresh.log 2>&1
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Actions tab empty | Push `main` branch with `.github/workflows/dashboard.yml` |
| Workflow fails on Yahoo | Re-run workflow; Yahoo sometimes rate-limits |
| 大佬三原色 empty | Actions → Run workflow → enable **refresh macro** |
| Page 404 | Settings → Pages → Source must be **GitHub Actions** |
| Old data on site | Wait for next scheduled run or Run workflow |

---

## Disclaimer (recommended on site)

Add a line on the dashboard: data from Yahoo Finance, delayed, not investment advice.
