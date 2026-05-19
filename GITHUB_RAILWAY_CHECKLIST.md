# Checklist: New Page / Stock Analysis Not Showing on Railway

## 1. What must be on GitHub

For the **new "Stock Analysis of the app"** mode to work, **all** of these must be in your repo and pushed:

| Item | Why |
|------|-----|
| **`scanner_streamlit.py`** (updated) | Contains the 3-way Mode selector: Scanner, Backtest, Stock Analysis of the app. Without it, you still see only 2 modes. |
| **`requirements.txt`** (updated) | Must include `plotly` and `pytz` for Stock Analysis. |
| **`stocktrackeryahoo/` folder** | The whole folder must be in the repo. The app looks for `stocktrackeryahoo/streamlit_app.py` next to `scanner_streamlit.py`. |
| **`stocktrackeryahoo/streamlit_app.py`** | Required; the embedded page runs this. |

If you only pushed the “three edited files” and not the **folder**, the new mode can appear but will show: *“Stock Analysis folder not found”*.

---

## 2. Push the folder (not just one file)

From your **backtest** project folder (same folder as `scanner_streamlit.py`):

```bash
cd /Users/chrislau/Documents/IT/backtest

# See what Git is tracking
git status

# Add everything (including the folder)
git add scanner_streamlit.py requirements.txt stocktrackeryahoo/
git status   # should list stocktrackeryahoo/ and files inside it

git commit -m "Add Stock Analysis page and stocktrackeryahoo folder"
git push origin main
```

If `stocktrackeryahoo/` was never added, it won’t be on GitHub and Railway won’t have it.

---

## 3. Confirm on GitHub

1. Open your repo on **github.com**.
2. Check:
   - Root has **`scanner_streamlit.py`** and **`requirements.txt`**.
   - There is a **`stocktrackeryahoo`** folder.
   - Inside it there is **`streamlit_app.py`**.

If the folder or `streamlit_app.py` is missing, add and push them (step 2).

---

## 4. Railway: redeploy and build

1. In **Railway** → your project → **Deployments**.
2. Confirm there is a **new deployment** after your latest push (e.g. “Deployed from commit …”).
3. If there is no new deployment, trigger one: **Deploy** → **Redeploy** (or push an empty commit: `git commit --allow-empty -m "Trigger redeploy"` then `git push`).
4. Open the **latest deployment** → **View logs** (or **Build** / **Deploy** logs).
5. Check that the build finished **successfully** (no errors during `pip install -r requirements.txt` or `streamlit run`).

If the build fails, the old version may still be running (no new page).

---

## 5. Hard refresh the site

- **Chrome/Edge:** `Ctrl+Shift+R` (Windows) or `Cmd+Shift+R` (Mac).  
- Or open the Railway app URL in an **incognito/private** window.

Sometimes the browser shows a cached version of the app.

---

## 6. What you should see

- **Mode selector** in the sidebar: **Scanner** | **Backtest** | **Stock Analysis of the app**.
- If you click **Stock Analysis of the app**:
  - **Folder present:** Stock Analysis (交易數據分析器) content loads.
  - **Folder missing:** A warning: *“Stock Analysis folder not found”*.

If you still only see **Scanner** and **Backtest**, the updated `scanner_streamlit.py` is not what Railway is running (push/rebuild issue). If you see the third mode but an error when opening it, check logs and the folder/content as above.
