# Web App Access Fix

## ✅ Issue Resolved

The web app is now running and accessible at:
```
http://127.0.0.1:5000
```

## What Was Fixed

1. **App now starts even without pandas_ta** - Shows a warning but doesn't crash
2. **Better error handling** - Will show clear error messages if pandas_ta is missing when analyzing stocks

## How to Access

1. **Open your web browser**
2. **Go to**: `http://127.0.0.1:5000`
3. You should see the HK-RangeBot interface

## If You Still Get "Access Denied"

Try these steps:

1. **Check if the app is running:**
   ```bash
   lsof -i :5000
   ```

2. **If not running, start it manually:**
   ```bash
   cd /Users/chrislau/Documents/IT/stocktracker
   python3 app.py
   ```

3. **Try a different browser** or clear browser cache

4. **Check firewall settings** - Make sure localhost connections are allowed

## Important: pandas_ta Installation

⚠️ **The app will start, but stock analysis requires pandas_ta:**

To install pandas_ta (required for ADX calculation):

**Option 1: Manual Download**
1. Go to: https://github.com/twopirllc/pandas-ta
2. Click "Code" → "Download ZIP"
3. Extract the ZIP file
4. Open Terminal in the extracted folder
5. Run: `pip3 install .`

**Option 2: Use Git (if you have it configured)**
```bash
pip3 install git+https://github.com/twopirllc/pandas-ta.git
```

## Current Status

- ✅ Web app is running on port 5000
- ✅ Interface is accessible
- ⚠️ Stock analysis requires pandas_ta to be installed

## Testing

1. Open: http://127.0.0.1:5000
2. You should see the HK-RangeBot interface
3. Try entering a stock code (e.g., HK.00700)
4. If pandas_ta is not installed, you'll see an error message with installation instructions
