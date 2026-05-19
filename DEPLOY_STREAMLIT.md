# Deploy Veteran Scanner to the Web (Streamlit Community Cloud)

So you can browse the app at a **public URL** (not only localhost), use **Streamlit Community Cloud** (free).

---

## 1. Push your code to GitHub

From your project folder:

```bash
cd /Users/chrislau/Documents/IT/backtest
git init
git add scanner_streamlit.py daily_scanner.py requirements.txt
git commit -m "Add Streamlit scanner"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Make sure the repo is **public** (Streamlit Cloud free tier needs a public repo).

These files must be in the **repo root** (or in the same folder you set as “Root directory” in step 3):

- `scanner_streamlit.py`
- `daily_scanner.py`
- `requirements.txt`

---

## 2. Go to Streamlit Community Cloud

1. Open: **https://share.streamlit.io**
2. Sign in with your **GitHub** account and authorize Streamlit.

---

## 3. Create a new app

1. Click **“New app”**.
2. **Repository:** choose your GitHub repo (e.g. `YOUR_USERNAME/backtest`).
3. **Branch:** `main` (or the branch you use).
4. **Main file path:** `scanner_streamlit.py`
5. **Advanced settings** (optional):
   - **Root directory:** leave blank if `scanner_streamlit.py` and `daily_scanner.py` are in the repo root. If they’re in a subfolder (e.g. `backtest/`), set **Root directory** to `backtest`.
6. Click **Deploy**.

---

## 4. Wait and open the URL

- Streamlit will install dependencies from `requirements.txt` and start the app.
- When it’s ready, you get a URL like:  
  `https://YOUR_APP_NAME.streamlit.app`
- Open that URL in any browser to use the scanner on the web.

---

## 5. “You do not have access to this app or it does not exist”

This message usually means one of the following.

### A. You’re not the app owner / wrong account
- You must be logged into the **same Streamlit Cloud account** that created the app.
- Go to **https://share.streamlit.io** and check **“My apps”**. If the app isn’t there, you’re on the wrong account or the app was never created there.

### B. You don’t have admin access to the GitHub repo
- Streamlit Cloud needs **admin (or owner) access** to the GitHub repo.
- If the repo is under an **organization**, the org may need to approve Streamlit’s access (GitHub → Settings → Third-party access).
- Fix: Use a repo you own, or get admin rights, or **fork** the repo to your account and deploy from your fork.

### C. The app was never deployed or was deleted
- If you only pushed to GitHub but never clicked **“Deploy”** on share.streamlit.io, the app doesn’t exist.
- Fix: Go to share.streamlit.io → **New app** → pick repo, branch, `scanner_streamlit.py` → **Deploy**.
- If you (or someone) removed the app, create it again the same way.

### D. Wrong or old URL
- The URL might be a typo or from an old deployment.
- Fix: On share.streamlit.io, open **“My apps”**, click your app, and use the URL shown there.

### E. Reconnect GitHub
- Sometimes Streamlit loses permission to your repo.
- Fix: On share.streamlit.io go to **Settings** (or your profile) and **reconnect / re-authorize** your GitHub account, then try opening the app again.

---

## 6. Other issues

- **Build fails:** Check the build log on Streamlit Cloud. Often it’s a missing or wrong dependency in `requirements.txt`.
- **“Module not found” (e.g. `daily_scanner`):** Ensure `daily_scanner.py` is in the same directory as `scanner_streamlit.py` (or that **Root directory** points to the folder that contains both).
- **App is slow:** The app fetches data from Yahoo Finance on each “Run scan”; that’s normal. First load after deploy can be slower.

---

## Optional: Slim `requirements.txt` for Streamlit only

Streamlit Cloud installs everything in `requirements.txt`. If you want a minimal set for the scanner app only, you can use a separate file for deploy (e.g. `requirements-streamlit.txt`) and point Streamlit to it in Advanced settings. For most cases, your current `requirements.txt` is fine.

---

**Summary:** Push repo to GitHub (public) → share.streamlit.io → New app → pick repo, branch, `scanner_streamlit.py` → Deploy → use the given URL in the browser.
