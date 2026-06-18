# 9988.HK (Alibaba) Backtesting Engine

Backtest a **trend-following** strategy on **9988.HK** (Alibaba HK) using **yfinance** daily data (Alpha Vantage optional fallback).

## Setup

```bash
pip install -r requirements.txt
```

Optional — Alpha Vantage fallback when yfinance fails (free key at [alphavantage.co](https://www.alphavantage.co/support/#api-key)):

```bash
export ALPHA_VANTAGE_API_KEY=your_key
```

**pandas_ta** (optional): requires Python >= 3.12. If unavailable, built-in fallback indicators are used.

## Run

```bash
python backtest_options.py
```

The script will:
1. Fetch ~1 year of daily data for **9988.HK** from yfinance (Alpha Vantage if configured and yfinance fails).
2. Print `df.head()` and `df.tail()` to confirm data.
3. Compute indicators: SMA20, RSI14, ADX/PDI/MDI, OBV, VWAP, RVOL.
4. Run the backtest via `backtesting.py`.
5. Print performance stats and save an interactive chart to `backtest_9988HK.html`.

## Strategy

| Condition | Buy | Sell |
|-----------|-----|------|
| Trend     | Close > SMA20 | Close < SMA20 |
| Momentum  | RSI14 > 50    | RSI14 < 45    |
| Direction | PDI > MDI     | —              |
| Volume    | OBV rising    | OBV falling   |
| Strength  | ADX > 20      | —              |

Parameters can be tuned in the `AlibabaStrategy` class.

## Files

- `backtest_options.py` — Main script (data + indicators + strategy + backtest).
- `requirements.txt` — Dependencies.
- `backtest_9988HK.html` — Interactive chart (generated after running).
