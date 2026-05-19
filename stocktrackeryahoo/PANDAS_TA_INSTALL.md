# pandas_ta Installation Guide

## Current Status

The code now uses a **custom ADX implementation with Wilder's Smoothing** that matches Futu's broker app. This is automatically used when pandas_ta is not available.

## If You Want to Use pandas_ta

The code is structured to automatically use pandas_ta if it's installed. To install pandas_ta:

### Option 1: Install from GitHub (Recommended)

```bash
pip3 install git+https://github.com/twopirllc/pandas-ta.git
```

### Option 2: Manual Installation

1. Clone the repository:
```bash
git clone https://github.com/twopirllc/pandas-ta.git
cd pandas-ta
```

2. Install:
```bash
pip3 install .
```

### Option 3: Use the Custom Implementation (Current)

The current custom ADX implementation uses **Wilder's Smoothing** which matches Futu's calculation method. This is already working and doesn't require pandas_ta.

## How It Works

The code automatically:
1. Tries to import pandas_ta
2. If available, uses `df.ta.adx(length=14, append=True)`
3. If not available, uses the custom Wilder's smoothing implementation

Both methods should produce similar results, but the custom implementation is specifically tuned to match Futu's ADX calculation.

## Verification

After installation, run the script and you should see:
- If pandas_ta is available: No warning message
- If pandas_ta is not available: "⚠️ pandas_ta not available. Using custom ADX implementation with Wilder's smoothing."

Both will work correctly!
