# Streamlit Cloud Deployment Guide

## Files for Streamlit Cloud

The app has been converted to Streamlit and is ready for deployment on Streamlit Cloud.

### Main Files:
- **`streamlit_app.py`** - Main Streamlit application (this is what Streamlit Cloud will run)
- **`requirements.txt`** - Python dependencies
- **`adx_ewm.py`** - ADX calculation module (required)

### Deployment Steps:

1. **Push to GitHub**
   - Make sure all files are committed and pushed to your GitHub repository

2. **Connect to Streamlit Cloud**
   - Go to https://share.streamlit.io
   - Sign in with GitHub
   - Click "New app"
   - Select your repository
   - **Main file path**: `streamlit_app.py`
   - Click "Deploy"

3. **Wait for Deployment**
   - Streamlit Cloud will install dependencies from `requirements.txt`
   - The app will be available at: `https://your-app-name.streamlit.app`

### Important Notes:

- ✅ The app uses **Yahoo Finance** (no Futu OpenD required)
- ✅ All calculation logic is preserved
- ✅ UI converted to Streamlit components
- ✅ Charts use Plotly (included in requirements.txt)

### If You Get Errors:

1. **Import errors**: Make sure `adx_ewm.py` is in the root directory
2. **Missing dependencies**: Check `requirements.txt` includes all packages
3. **File not found**: Ensure `streamlit_app.py` is in the repository root

### Testing Locally:

Before deploying, test locally:
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open http://localhost:8501 in your browser.
