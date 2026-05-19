# FutuOpenD Setup Guide

## What You Have vs What You Need

✅ **What you have:** `FTAPI4Python_9.6.5608` folder (Python SDK source code)  
❌ **What you need:** FutuOpenD (Desktop Application)

**Good news:** We already installed the Python SDK via `pip install futu-api`, so you don't need the folder for the script to work!

---

## Step 1: Download FutuOpenD

FutuOpenD is a **separate desktop application** that acts as a gateway between your Python script and Futu's servers.

1. **Visit the download page:**
   - Go to: https://www.futunn.com/download/openAPI
   - Or: https://www.futunn.com/en/download/OpenAPI

2. **Download FutuOpenD for macOS:**
   - Look for "FutuOpenD" (not the Python SDK)
   - Download the macOS version (.dmg file)

3. **Install FutuOpenD:**
   - Open the downloaded .dmg file
   - Drag FutuOpenD to your Applications folder
   - Or double-click to install

---

## Step 2: Launch FutuOpenD

1. **Open FutuOpenD:**
   - Go to Applications folder
   - Double-click "FutuOpenD" to launch
   - You may need to allow it in System Preferences > Security & Privacy

2. **Login:**
   - Enter your Futu account credentials (Futu ID + Password)
   - The application should show it's running and listening on port 11111

3. **Verify it's running:**
   - You should see the FutuOpenD window/icon in your menu bar
   - It should show status as "Connected" or "Running"

---

## Step 3: Test the Connection

Once FutuOpenD is running, test your script:

```bash
cd /Users/chrislau/Documents/IT/stocktracker
python3 hk_rangebot.py
```

You should see:
- ✅ Connected to FutuOpenD
- 📊 Fetching daily K-line data...
- And then the trading signals!

---

## Troubleshooting

### "Connection Refused" Error
- Make sure FutuOpenD is actually running (check Applications or menu bar)
- Verify it's listening on port 11111 (default)
- Try restarting FutuOpenD

### "Login Failed"
- Check your Futu account credentials
- Make sure you have API access enabled on your Futu account
- Some accounts may need to enable API access in account settings

### Version Mismatch
- Your Python SDK is version 9.6.5608
- Make sure FutuOpenD version is compatible (ideally 9.6.5608 or newer)
- Check version in FutuOpenD's About menu

---

## Quick Reference

- **FutuOpenD Download:** https://www.futunn.com/download/openAPI
- **Default Port:** 11111
- **Default Host:** 127.0.0.1 (localhost)
- **Python SDK:** Already installed via pip ✅

---

## What About the FTAPI4Python_9.6.5608 Folder?

You can:
- **Keep it** if you want to modify the SDK source code
- **Delete it** if you don't need it (we're using the pip-installed version)
- **Move it** somewhere else for reference

The folder is not needed for your script to run since we installed `futu-api` via pip.
