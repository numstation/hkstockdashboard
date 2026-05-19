# Deploy HK Stock Hunter Pro to Railway

## Prerequisites
- A [GitHub](https://github.com) account
- A [Railway](https://railway.app) account (sign up with GitHub)

---

## Step 1: Put your code on GitHub

Yes, you need your code on GitHub so Railway can pull and deploy it.

### Option A: You don’t have a repo yet

1. **Create a new repo on GitHub**
   - Go to [github.com/new](https://github.com/new)
   - Name it (e.g. `hk-stock-hunter` or `backtest`)
   - Choose **Public**, leave “Add a README” unchecked if your folder already has files
   - Click **Create repository**

2. **Push your local project**
   In your terminal, from your project folder (e.g. `backtest/`):

   ```bash
   cd /path/to/backtest
   git init
   git add .
   git commit -m "Initial commit: HK Stock Hunter Pro"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```
   Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and repo name.

### Option B: You already have a repo

From your project folder:

```bash
cd /path/to/backtest
git add .
git commit -m "Add Railway deploy: Procfile, Streamlit config, UI facelift"
git push origin main
```

---

## Step 2: Create a project on Railway

1. Go to [railway.app](https://railway.app) and sign in with **GitHub**.
2. Click **“New Project”**.
3. Choose **“Deploy from GitHub repo”**.
4. Select the repo that contains your `backtest` app (e.g. the one you pushed in Step 1).
5. If asked which branch, pick **main** (or your default branch).

Railway will create a project and try to detect how to run the app.

---

## Step 3: Configure the service for Streamlit

1. In the project, click the **service** (the box that represents your app).
2. Open the **Settings** tab (or **Variables** if you only see that).
3. **Root directory (if your app is in a subfolder)**  
   If your repo root is the repo and the app lives in a folder (e.g. `backtest/`):
   - Find **“Root Directory”** or **“Source”**.
   - Set it to that folder, e.g. `backtest`.
   - If your repo root **is** the app (all files like `scanner_streamlit.py`, `Procfile` are at root), leave this blank.
4. **Build command (optional)**  
   Railway often auto-detects. If you use a `requirements.txt` in that root/subfolder, it should run something like:
   - `pip install -r requirements.txt`  
   You can set **Build Command** to:
   ```bash
   pip install -r requirements.txt
   ```
   if you want to be explicit.
5. **Start command**  
   Set **Start Command** to:
   ```bash
   streamlit run scanner_streamlit.py --server.port=$PORT --server.address=0.0.0.0
   ```
   If you added a **Procfile** with the same line, Railway may pick it up and you can leave Start Command empty.
6. **Port**  
   Leave **Port** empty so Railway uses `$PORT` (your Procfile/start command already use it).

Save / deploy if the UI asks for it.

---

## Step 4: Deploy and get the URL

1. Trigger a deploy:
   - **“Deploy”** or **“Redeploy”** in the dashboard, or
   - Push a new commit to the same branch: `git push origin main`.
2. Wait for the build and run to finish (logs appear in the **Deployments** or **Logs** tab).
3. **Generate a public URL:**
   - Open the **Settings** tab for the service.
   - Find **“Networking”** or **“Public Networking”**.
   - Click **“Generate domain”** (or “Add domain”).
   - Copy the URL (e.g. `https://your-app.up.railway.app`).

Open that URL in a browser; you should see **HK Stock Hunter Pro** (Streamlit, dark theme).

---

## Step 5: Updating the app later

Whenever you change the code:

1. Commit and push to the same branch Railway watches (usually `main`):
   ```bash
   git add .
   git commit -m "Your change description"
   git push origin main
   ```
2. Railway will detect the push and start a new deploy. No need to touch GitHub separately for “updating Railway” — push to GitHub is enough.

---

## Do I need to update GitHub?

- **To deploy or redeploy on Railway:** Yes. Railway builds from your GitHub repo, so your code must be on GitHub (and pushed) for Railway to see it.
- **After you’ve already pushed once:** Any time you want a new deploy, update the code on GitHub (commit + push). Railway will redeploy from the updated repo.

**Summary:** Put code on GitHub first (Step 1). Connect Railway to that repo (Step 2). Configure build/start (Step 3). Generate domain and open the app (Step 4). For future updates, push to GitHub and Railway will redeploy (Step 5).
