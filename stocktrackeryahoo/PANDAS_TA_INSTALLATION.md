# pandas_ta Installation Instructions

## ⚠️ REQUIRED: pandas_ta Library

The updated code **requires** `pandas_ta` library to calculate Standard ADX (14, 14) that matches your trading app.

## Installation Methods

### Method 1: Install from GitHub (Recommended)

```bash
pip3 install git+https://github.com/twopirllc/pandas-ta.git
```

### Method 2: Manual Installation

1. **Clone the repository:**
```bash
cd ~/Downloads  # or any directory
git clone https://github.com/twopirllc/pandas-ta.git
cd pandas-ta
```

2. **Install:**
```bash
pip3 install .
```

### Method 3: Download ZIP and Install

1. Download ZIP from: https://github.com/twopirllc/pandas-ta/archive/refs/heads/master.zip
2. Extract the ZIP file
3. Navigate to the extracted folder
4. Run: `pip3 install .`

## Verification

After installation, verify it works:

```python
python3 -c "import pandas_ta as ta; print('pandas_ta installed successfully!')"
```

## If Installation Fails

If you encounter issues installing pandas_ta, the script will exit with an error message showing installation instructions.

## Why pandas_ta?

- Uses Standard ADX (14, 14) calculation
- Matches values from trading apps like Futu
- Industry-standard implementation
- Proper warm-up period handling

## Current Code Changes

- ✅ Fetches **1000 days** of data (was 500)
- ✅ Uses `df.ta.adx(length=14, append=True)` syntax
- ✅ Prints ADX and ADX Slope clearly
- ✅ Removed custom ADX implementation
