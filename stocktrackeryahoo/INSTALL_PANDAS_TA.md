# How to Install pandas_ta - Step by Step

## Quick Installation Guide

Since the git installation isn't working, here's how to install pandas_ta manually:

### Method 1: Download ZIP and Install (Easiest)

1. **Download pandas_ta:**
   - Go to: https://github.com/twopirllc/pandas-ta
   - Click the green "Code" button
   - Click "Download ZIP"
   - Save the ZIP file to your Downloads folder

2. **Extract the ZIP:**
   - Double-click the ZIP file to extract it
   - You should get a folder named `pandas-ta-master` or `pandas-ta-main`

3. **Install it:**
   Open Terminal and run:
   ```bash
   cd ~/Downloads/pandas-ta-master  # or pandas-ta-main
   pip3 install .
   ```

### Method 2: Using Terminal (If you have git configured)

```bash
cd ~/Downloads
git clone https://github.com/twopirllc/pandas-ta.git
cd pandas-ta
pip3 install .
```

### Method 3: Install to Current Project Directory

If you want to install it locally in your project:

```bash
cd ~/Downloads
# Download and extract pandas-ta ZIP manually first
cd pandas-ta-master  # or whatever the folder name is
pip3 install . --user
```

## Verify Installation

After installation, verify it works:

```bash
python3 -c "import pandas_ta as ta; print('✅ pandas_ta installed successfully!')"
```

## If Installation Still Fails

If you get permission errors, try:

```bash
pip3 install . --user
```

Or if you need to use sudo (not recommended but sometimes necessary):

```bash
sudo pip3 install .
```

## After Installation

1. **Restart the web app:**
   ```bash
   cd /Users/chrislau/Documents/IT/stocktracker
   python3 app.py
   ```

2. **Test it:**
   - Go to http://127.0.0.1:5000
   - Enter a stock code (e.g., HK.00700)
   - Click "Analyze Stock"
   - It should work now!

## Troubleshooting

**Error: "No module named 'pandas_ta'"**
- Make sure you ran `pip3 install .` from inside the pandas-ta folder
- Try: `python3 -m pip install .`

**Error: "Permission denied"**
- Use: `pip3 install . --user`
- Or create a virtual environment

**Still not working?**
- Check Python version: `python3 --version` (should be 3.7+)
- Make sure you're using the same Python that runs the app
