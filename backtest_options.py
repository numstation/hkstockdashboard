#!/usr/bin/env python3
"""
==========================================================================
  9988.HK — Veteran Trend-Following Backtest Engine
==========================================================================
  Data:    yfinance (primary) → Alpha Vantage (fallback)
  Logic:   Strict entry (5 conditions) + structural exit + stop loss +
           month-end forced close

  pip install yfinance alpha-vantage backtesting requests pandas numpy
==========================================================================
"""

import os
import sys
import time
import requests as req_lib
import pandas as pd
import numpy as np
from typing import List, Dict, Optional

# ---------------------------------------------------------------------------
# Library detection
# ---------------------------------------------------------------------------
try:
    import yfinance as yf
    _HAS_YF = True
    print("[OK] yfinance loaded.")
except ImportError:
    _HAS_YF = False
    print("[INFO] yfinance not installed. pip install yfinance")

try:
    import pandas_ta as ta
    _HAS_PANDAS_TA = True
    print("[OK] pandas_ta loaded.")
except ImportError:
    _HAS_PANDAS_TA = False
    print("[INFO] pandas_ta not installed — using built-in fallbacks.")

try:
    from alpha_vantage.timeseries import TimeSeries
    _HAS_AV_LIB = True
except ImportError:
    _HAS_AV_LIB = False

# ===========================================================================
# Configuration
# ===========================================================================
API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "HBG9BOEUEDF3U0YQ")
# Default ticker when none given on command line. Any symbol works: 9988.HK, 0700.HK, SPY, AAPL, etc.
DEFAULT_SYMBOL = "9988.HK"

# Stress-test symbols (run with: python backtest_options.py stress)
STRESS_TEST_SYMBOLS = [
    ("0388.HK", "HKEX — choppy market"),
    ("0883.HK", "CNOOC — strong trend"),
    ("0027.HK", "Galaxy Ent — volatility / stop-loss"),
    ("0002.HK", "CLP Holdings — low-vol inactivity"),
]

# ---- Veteran parameters ----
ADX_MIN           = 20      # ADX floor (no upper limit in UI)
ADX_MAX           = 50      # ADX cap
PDI_BUFFER        = 0       # PDI > MDI + this (0 = same as PDI>MDI)
STOP_LOSS_PCT     = 0.08    # 8% hard stop loss from entry price
RSI_PROFIT_TAKING = 75    # RSI > this + bearish candle → sell 50% (climax exit)
ATR_TRAIL_MULT    = 3     # Trailing stop: Highest_High - (this * ATR)
INITIAL_CASH     = 100_000 # HK$
COMMISSION_PCT   = 0.002   # 0.2% per trade (buy + sell)

# ---- BUY criteria: operator-based (override from Streamlit) ----
CLOSE_VS_SMA20    = "off"   # "off" | ">" | "<" | ">=" | "<="
CLOSE_VS_SMA50    = "off"
OBV_VS_OBV_EMA20  = "off"
OBV_VS_OBV_5MA    = "off"
CLOSE_VS_VWAP     = "off"
MFI_VS_RSI        = "off"   # "off" | "mfi>rsi" | "rsi>mfi"
RSI_OP            = "off"   # "off" | ">" | "<" | ">=" | "<="  (RSI vs RSI_VALUE)
RSI_VALUE         = 50.0
RS_20D_OP         = "off"   # "off" | ">" | "<" | ">=" | "<="  (RS 20d % vs RS_20D_VALUE)
RS_20D_VALUE      = 0.0     # e.g. 0 = outperform 0%, >0 = beating market
MFI_OP            = "off"
MFI_VALUE         = 55.0
RVOL_OP           = "off"   # RVOL vs RVOL_VALUE
RVOL_VALUE        = 1.0
ADX_SLOPE_OP      = "off"   # ADX slope vs 0
GAP_OP            = "off"   # (PDI - MDI) vs GAP_VALUE
GAP_VALUE         = 0.0
STOCH_K_OP        = "off"   # Stoch %K vs STOCH_K_VALUE
STOCH_K_VALUE     = 80.0
# Stochastic extras (Streamlit / manual): %K vs %D, vs prior bar, %D vs level
STOCH_REQUIRE_K_GT_D = False   # require Stoch_K > Stoch_D
STOCH_K_VS_PREV_OP  = "off"    # "off" | ">" | "<"  (today K vs yesterday K)
STOCH_D_VS_PREV_OP  = "off"    # "off" | ">" | "<"  (today D vs yesterday D)
STOCH_D_OP          = "off"    # %D vs STOCH_D_VALUE
STOCH_D_VALUE       = 50.0
SPREAD_OP         = "off"   # Spread (MFI - RSI) vs SPREAD_VALUE
SPREAD_VALUE      = 0.0
CORE_REQUIRE_PDI_MDI = True
CORE_REQUIRE_ADX_AWAKENING = False
# When True, BUY uses only MACD histogram zero-line cross + RVOL (ignores composite core).
ENTRY_USE_MACD_CROSSOVER = False
MACD_HIST_MIN = 0.0       # current histogram must be > this (e.g. > 0)
MACD_HIST_PREV_MAX = 0.0  # previous histogram must be <= this (e.g. <= 0 for cross from below)
# Strategy 6 — 絕地反擊 (Reversal Breakout): human-in-the-loop flag (no candlestick / 3-day rules)
ENTRY_USE_REVERSAL_BREAKOUT = False
REVERSAL_RSI_MIN = 40.0
REVERSAL_RVOL_MIN = 1.2
SELL_USE_ADX_EXHAUSTION    = False
SELL_USE_SMA20       = True
SELL_USE_PDI_MDI     = True
SELL_USE_STOP_LOSS   = True
SELL_USE_TRAILING    = True
SELL_USE_PROFIT_TAKE = True
SELL_USE_MONTH_END   = True
# Legacy (used by Strategy class / print only; BUY logic uses operator criteria above)
RSI_ENTRY, MFI_ENTRY, RVOL_MIN = 50, 55, 1.0
SCORECARD_MIN, SCORE_REQUIRE_SPREAD = 3, True


# ===========================================================================
# Part 1: Fetch Data
# ===========================================================================
def fetch_data_yfinance(symbol: str, period: str = "1y") -> pd.DataFrame:
    print(f"  yfinance: downloading {symbol} (period={period})...")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, auto_adjust=False)
    if df is None or df.empty:
        raise ValueError(f"yfinance returned no data for {symbol}")
    keep = ["Open", "High", "Low", "Close", "Volume"]
    for col in keep:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}'")
    df = df[keep].copy().astype(float)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def fetch_data_av_lib(symbol: str, api_key: str) -> pd.DataFrame:
    ts = TimeSeries(key=api_key, output_format="pandas")
    data, _ = ts.get_daily(symbol=symbol, outputsize="compact")
    data = data.rename(columns={
        "1. open": "Open", "2. high": "High",
        "3. low": "Low", "4. close": "Close", "5. volume": "Volume",
    })
    data.index = pd.to_datetime(data.index)
    return data.sort_index().astype(float)


def _is_rate_limit(payload: dict) -> bool:
    for key in ("Information", "Note"):
        msg = payload.get(key, "")
        if any(w in msg.lower() for w in ["rate limit", "requests", "premium", "spreading"]):
            return True
    return False


def fetch_data_requests(symbol: str, api_key: str) -> pd.DataFrame:
    url = (
        f"https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY&symbol={symbol}"
        f"&apikey={api_key}&outputsize=compact&datatype=json"
    )
    for attempt in range(1, 4):
        if attempt > 1:
            time.sleep(15 * attempt)
        else:
            time.sleep(2)
        print(f"  [{attempt}/3] GET {url[:80]}...")
        resp = req_lib.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if "Error Message" in payload:
            raise SystemExit(f"API Error: {payload['Error Message']}")
        if _is_rate_limit(payload):
            print("  Rate limited — retrying...")
            continue
        ts_key = next((k for k in payload if isinstance(payload[k], dict) and "Time Series" in k), None)
        if ts_key is None:
            raise SystemExit(f"No time series. Keys: {list(payload.keys())}")
        df = pd.DataFrame.from_dict(payload[ts_key], orient="index")
        df = df.rename(columns={
            "1. open": "Open", "2. high": "High",
            "3. low": "Low", "4. close": "Close", "5. volume": "Volume",
        })
        df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        df.index = pd.to_datetime(df.index)
        return df.sort_index()
    raise SystemExit("Failed after retries.")


def fetch_data(symbol: str, api_key: str) -> pd.DataFrame:
    if _HAS_YF:
        try:
            return fetch_data_yfinance(symbol, period="1y")
        except Exception as e:
            print(f"  yfinance failed: {e}")
    if _HAS_AV_LIB:
        try:
            time.sleep(2)
            return fetch_data_av_lib(symbol, api_key)
        except Exception as e:
            print(f"  alpha_vantage failed: {e}")
    return fetch_data_requests(symbol, api_key)


# ===========================================================================
# Part 2: Built-in Indicator Fallbacks
# ===========================================================================
def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(window=n, min_periods=n).mean()

def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.where(d > 0, 0.0)
    loss = (-d).where(d < 0, 0.0)
    rs = _rma(gain, n) / _rma(loss, n).replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.DataFrame:
    up, down = h.diff(), -l.diff()
    pdm = up.where((up > down) & (up > 0), 0.0)
    mdm = down.where((down > up) & (down > 0), 0.0)
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = _rma(tr, n).replace(0, np.nan)
    pdi = 100 * _rma(pdm, n) / atr
    mdi = 100 * _rma(mdm, n) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({f"ADX_{n}": _rma(dx, n), f"DMP_{n}": pdi, f"DMN_{n}": mdi}, index=c.index)

def _obv(c: pd.Series, v: pd.Series) -> pd.Series:
    d = np.sign(c.diff()); d.iloc[0] = 0
    return (v * d).cumsum()

def _atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return _rma(tr, n)


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, length: int = 14) -> pd.Series:
    """Money Flow Index (14-period). Typical price, raw MF = tp * vol; positive/negative flow; MFI = 100 * pos / (pos+neg)."""
    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    tp_prev = tp.shift(1)
    pos_mf = raw_mf.where(tp > tp_prev, 0.0)
    neg_mf = raw_mf.where(tp < tp_prev, 0.0)
    pos_sum = pos_mf.rolling(window=length, min_periods=length).sum()
    neg_sum = neg_mf.rolling(window=length, min_periods=length).sum()
    total = pos_sum + neg_sum
    mfi = 100.0 * pos_sum / total.replace(0, np.nan)
    mfi = mfi.fillna(50.0)  # neutral when no flow
    return mfi


# ===========================================================================
# Part 3: Add Indicators
# ===========================================================================
def add_indicators(df: pd.DataFrame, symbol: Optional[str] = None) -> pd.DataFrame:
    """
    Compute all indicators needed for the Veteran strategy:
      SMA20, SMA_50, RSI14, ADX, ADX_prev, PDI, MDI,
      OBV, OBV_SMA20, OBV_EMA_20, RVOL, MFI14, Spread, ATR14, VWAP,
      MACD (EMA_12/26, MACD_Line, MACD_Signal, MACD_Hist, MACD_Hist_Prev).
    If symbol is provided, also adds Comparative RS vs benchmark (RS_Line, RS_20d_Outperform).
    """
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]

    # ---- Trend ----
    df["SMA20"]  = ta.sma(c, length=20) if _HAS_PANDAS_TA else _sma(c, 20)
    df["SMA_50"] = ta.sma(c, length=50) if _HAS_PANDAS_TA else _sma(c, 50)

    # ---- Momentum ----
    df["RSI14"] = ta.rsi(c, length=14) if _HAS_PANDAS_TA else _rsi(c, 14)

    if _HAS_PANDAS_TA:
        adx_df = ta.adx(h, l, c, length=14)
        df["ADX"] = adx_df["ADX_14"]
        df["PDI"] = adx_df["DMP_14"]
        df["MDI"] = adx_df["DMN_14"]
    else:
        adx_df = _adx(h, l, c, 14)
        df["ADX"] = adx_df["ADX_14"]
        df["PDI"] = adx_df["DMP_14"]
        df["MDI"] = adx_df["DMN_14"]

    # ADX slope: for 龍抬頭 (down→up) and 強弩之末 (up→down)
    df["ADX_prev"] = df["ADX"].shift(1)
    df["ADX_prev2"] = df["ADX"].shift(2)

    # ---- Volume: OBV, OBV_SMA20, OBV_EMA_20 (volume trend confirmation) ----
    df["OBV"]       = ta.obv(c, v) if _HAS_PANDAS_TA else _obv(c, v)
    df["OBV_SMA20"] = ta.sma(df["OBV"], length=20) if _HAS_PANDAS_TA else _sma(df["OBV"], 20)
    df["OBV_EMA_20"] = df["OBV"].ewm(span=20, adjust=False).mean()
    df["OBV_5MA"]   = ta.sma(df["OBV"], length=5) if _HAS_PANDAS_TA else _sma(df["OBV"], 5)

    df["AvgVol20"] = ta.sma(v, length=20) if _HAS_PANDAS_TA else _sma(v, 20)
    df["RVOL"] = v / df["AvgVol20"].replace(0, np.nan)

    # ---- Money Flow Index (14-day) ----
    if _HAS_PANDAS_TA:
        mfi_series = ta.mfi(h, l, c, v, length=14)
        df["MFI14"] = mfi_series if isinstance(mfi_series, pd.Series) else mfi_series.iloc[:, 0]
    else:
        df["MFI14"] = _mfi(h, l, c, v, 14)

    # ---- Money Flow Spread (MFI - RSI): institutional accumulation when Spread > 0 ----
    df["Spread"] = df["MFI14"] - df["RSI14"]

    # ---- MACD (12, 26, 9) — histogram zero-cross entries ----
    df["EMA_12"] = c.ewm(span=12, adjust=False).mean()
    df["EMA_26"] = c.ewm(span=26, adjust=False).mean()
    df["MACD_Line"] = df["EMA_12"] - df["EMA_26"]
    df["MACD_Signal"] = df["MACD_Line"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD_Line"] - df["MACD_Signal"]
    df["MACD_Hist_Prev"] = df["MACD_Hist"].shift(1)

    # ---- Stochastic %K / %D (14,3) ----
    try:
        if _HAS_PANDAS_TA:
            stoch_df = ta.stoch(h, l, c, k=14, d=3, smooth_k=3)
            k_col = next((col for col in stoch_df.columns if "STOCHk" in col), None)
            d_col = next((col for col in stoch_df.columns if "STOCHd" in col), None)
            df["Stoch_K"] = stoch_df[k_col] if k_col else np.nan
            if d_col:
                df["Stoch_D"] = stoch_df[d_col]
            elif k_col:
                df["Stoch_D"] = df["Stoch_K"].rolling(window=3, min_periods=1).mean()
            else:
                df["Stoch_D"] = np.nan
        else:
            df["Stoch_K"] = np.nan
            df["Stoch_D"] = np.nan
    except Exception:
        df["Stoch_K"] = np.nan
        df["Stoch_D"] = np.nan

    df["Stoch_K_prev"] = df["Stoch_K"].shift(1)
    df["Stoch_D_prev"] = df["Stoch_D"].shift(1)

    # ---- Volatility (for Smart Exit trailing stop) ----
    df["ATR14"] = ta.atr(h, l, c, length=14) if _HAS_PANDAS_TA else _atr(h, l, c, 14)

    # ---- VWAP: 20-day rolling (Typical Price × Volume / Volume) — swing-trade cost anchor ----
    _tp = (h + l + c) / 3
    df["VWAP"] = (_tp * v).rolling(window=20, min_periods=20).sum() / \
                 v.rolling(window=20, min_periods=20).sum()

    # ---- Comparative RS vs benchmark (^HSI for HK, ^GSPC for others) ----
    if symbol:
        try:
            benchmark_ticker = "^HSI" if ".HK" in symbol.upper() else "^GSPC"
            start_date, end_date = df.index.min(), df.index.max()
            bench = yf.download(benchmark_ticker, start=start_date, end=end_date, auto_adjust=False, progress=False)
            if not bench.empty:
                if isinstance(bench.columns, pd.MultiIndex):
                    bench.columns = [col[0] if isinstance(col, tuple) else col for col in bench.columns]
                bench_close = bench["Close"] if "Close" in bench.columns else bench.iloc[:, 0]
                bench_close.index = pd.to_datetime(bench_close.index).normalize()
                aligned = bench_close.reindex(df.index, method="ffill")
                df["Benchmark_Close"] = aligned.values
                df["RS_Line"] = df["Close"] / df["Benchmark_Close"].replace(0, np.nan)
                df["RS_20d_Outperform"] = (df["RS_Line"] / df["RS_Line"].shift(20) - 1) * 100
        except Exception:
            pass

    return df


# ===========================================================================
# Part 4: Veteran Backtest Engine (pure pandas — no backtesting.py)
# ===========================================================================
def _last_trading_day_of_month(dates: pd.DatetimeIndex) -> set:
    """Return set of dates that are the last trading day of their month."""
    s = pd.Series(dates, index=dates)
    return set(s.groupby(s.dt.to_period("M")).transform("max").values)


def _check_op(left_val: float, right_val: float, op: str) -> bool:
    """Apply operator: 'off'=skip (True), '>' '<' '>=' '<=' = compare. NaN => False."""
    if op in (None, "", "off"):
        return True
    if pd.isna(left_val) or pd.isna(right_val):
        return False
    if op == ">":
        return left_val > right_val
    if op == "<":
        return left_val < right_val
    if op == ">=":
        return left_val >= right_val
    if op == "<=":
        return left_val <= right_val
    return True


def run_veteran_backtest(df: pd.DataFrame, verbose: bool = True, use_smart_exit: bool = True) -> List[Dict]:
    """
    BUY: All selected criteria must be met (operator-based: Close vs SMA20/SMA50, OBV vs OBV_EMA_20, Close vs VWAP, MFI vs RSI; ADX range; PDI>MDI; 龍抬頭).
    SELL (use_smart_exit=True):
      1. Hard Exit: Close < SMA20 → SELL 100%
      2. Trailing Stop: Close < Highest_High - 3*ATR → SELL 100%
      3. Profit Taking: RSI > 75 AND Close < Open (bearish candle) → SELL 50%, keep rest
      4. PDI < MDI, Stop Loss (-8%), Month-end → SELL remaining

    SELL (use_smart_exit=False): Close<SMA20 | PDI<MDI | Stop | Month-end → 100%.
    """
    required = [
        "SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread",
        "Stoch_K", "Stoch_D", "Stoch_K_prev", "Stoch_D_prev",
    ]
    if ENTRY_USE_MACD_CROSSOVER or ENTRY_USE_REVERSAL_BREAKOUT:
        required = required + ["MACD_Hist", "MACD_Hist_Prev"]
    if use_smart_exit:
        required = required + ["ATR14", "Open"]
    trades: List[Dict] = []

    month_ends = _last_trading_day_of_month(df.index)

    in_position = False
    entry_price = 0.0
    entry_date = None
    position_ratio = 1.0       # 1.0 = 100%, 0.5 = 50% (after partial exit)
    highest_high_since_entry = 0.0
    entry_adx = 0.0
    entry_rsi = 0.0
    entry_rvol = 0.0
    entry_pdi = 0.0
    entry_mdi = 0.0
    entry_mfi = 0.0
    entry_spread = 0.0
    entry_reason = ""
    entry_slope = 0.0
    entry_sma50 = 0.0
    entry_obv = 0.0
    entry_obv_ema_20 = 0.0
    entry_vwap = 0.0
    entry_rs_20d = None
    entry_macd_hist = None
    entry_macd_hist_prev = None
    entry_macd_line = None
    entry_macd_signal = None

    def _append_trade(exit_reason: str, exit_price: float, pnl_ratio: float):
        nonlocal in_position, position_ratio
        pnl = (exit_price - entry_price) * pnl_ratio
        pnl_pct = (pnl / entry_price) * 100
        hold_days = (date - entry_date).days
        cost = entry_price * pnl_ratio
        proceeds = exit_price * pnl_ratio
        trades.append({
            "Entry_Date":   entry_date.strftime("%Y-%m-%d"),
            "Entry_Price":  round(entry_price, 2),
            "Entry_Reason": entry_reason,
            "Cost":         round(cost, 2),
            "Proceeds":     round(proceeds, 2),
            "Exit_Date":    date.strftime("%Y-%m-%d"),
            "Exit_Price":   round(exit_price, 2),
            "Exit_Reason":  exit_reason,
            "Hold_Days":    hold_days,
            "PnL":          round(pnl, 2),
            "PnL%":         round(pnl_pct, 2),
            "Result":       "WIN" if pnl > 0 else "LOSS",
            "E_ADX":        round(entry_adx, 1),
            "E_ADX_Slope":  round(entry_slope, 2),
            "E_RSI":        round(entry_rsi, 1),
            "E_PDI":        round(entry_pdi, 1),
            "E_MDI":        round(entry_mdi, 1),
            "E_RVOL":       round(entry_rvol, 2) if pd.notna(entry_rvol) else None,
            "E_MFI":        round(entry_mfi, 1) if pd.notna(entry_mfi) else None,
            "E_Spread":     round(entry_spread, 1),
            "E_SMA_50":     round(entry_sma50, 2) if pd.notna(entry_sma50) else None,
            "E_OBV":        round(entry_obv, 0) if pd.notna(entry_obv) else None,
            "E_OBV_EMA_20": round(entry_obv_ema_20, 0) if pd.notna(entry_obv_ema_20) else None,
            "E_VWAP":       round(entry_vwap, 2) if pd.notna(entry_vwap) else None,
            "E_RS_20d":     round(entry_rs_20d, 2) if entry_rs_20d is not None and pd.notna(entry_rs_20d) else None,
            "E_MACD_Line":   round(entry_macd_line, 4) if entry_macd_line is not None and pd.notna(entry_macd_line) else None,
            "E_MACD_Signal": round(entry_macd_signal, 4) if entry_macd_signal is not None and pd.notna(entry_macd_signal) else None,
            "E_MACD_Hist":   round(entry_macd_hist, 4) if entry_macd_hist is not None and pd.notna(entry_macd_hist) else None,
            "E_MACD_Hist_Prev": round(entry_macd_hist_prev, 4) if entry_macd_hist_prev is not None and pd.notna(entry_macd_hist_prev) else None,
        })

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]

        if any(pd.isna(row.get(k)) for k in required):
            continue

        close  = row["Close"]
        open_  = row["Open"]
        high   = row["High"]
        sma20  = row["SMA20"]
        sma50  = row.get("SMA_50")
        obv    = row.get("OBV")
        obv_ema_20 = row.get("OBV_EMA_20")
        vwap   = row.get("VWAP")
        rsi    = row["RSI14"]
        rs_20d = row.get("RS_20d_Outperform")
        adx    = float(row["ADX"])
        adx_p  = float(row["ADX_prev"])
        adx_p2 = float(row["ADX_prev2"]) if not pd.isna(row.get("ADX_prev2")) else adx_p
        pdi    = float(row["PDI"])
        mdi    = float(row["MDI"])
        mfi    = float(row["MFI14"]) if not pd.isna(row.get("MFI14")) else np.nan
        spread = float(row["Spread"]) if not pd.isna(row.get("Spread")) else np.nan
        rvol   = row.get("RVOL")
        if pd.isna(rvol):
            continue
        rvol = float(rvol)
        atr = float(row["ATR14"]) if use_smart_exit and not pd.isna(row.get("ATR14")) else 0.0

        is_month_end = (date in month_ends)
        # ADX slope for 龍抬頭 / 強弩之末
        slope_curr = adx - adx_p
        slope_prev = adx_p - adx_p2

        # =============================================================
        # STATE: IN POSITION → check sell conditions
        # =============================================================
        if in_position:
            # Update trailing high
            if use_smart_exit:
                highest_high_since_entry = max(highest_high_since_entry, high)

            exit_reason = None
            sell_ratio = 0.0   # 0 = no exit, 0.5 = half, 1.0 = full
            stop_price = entry_price * (1 - STOP_LOSS_PCT)

            if use_smart_exit:
                # 1. Hard Exit: trend breaker
                if SELL_USE_SMA20 and close < sma20:
                    exit_reason = "Hard Exit (Close < SMA20)"
                    sell_ratio = 1.0
                # 2. Trailing Stop
                elif SELL_USE_TRAILING and atr > 0 and close < (highest_high_since_entry - ATR_TRAIL_MULT * atr):
                    exit_reason = "Trailing Stop (Close < High - 3*ATR)"
                    sell_ratio = 1.0
                # 3. Profit Taking (50%) — only if we still have full position
                elif SELL_USE_PROFIT_TAKE and position_ratio >= 1.0 and rsi > RSI_PROFIT_TAKING and close < open_:
                    exit_reason = "Profit Taking 50% (RSI>75, Bearish Candle)"
                    sell_ratio = 0.5
                # 4. 強弩之末 (Trend Exhaustion): ADX was rising, now falling
                elif SELL_USE_ADX_EXHAUSTION and slope_prev >= 0 and slope_curr < 0:
                    exit_reason = "Trend Exhaustion (ADX 強弩之末)"
                    sell_ratio = 1.0
                # 5. Momentum / Stop / Month-end
                elif SELL_USE_PDI_MDI and pdi < mdi:
                    exit_reason = "Momentum Flip (PDI < MDI)"
                    sell_ratio = 1.0
                elif SELL_USE_STOP_LOSS and close < stop_price:
                    exit_reason = f"Stop Loss (-{STOP_LOSS_PCT*100:.0f}%)"
                    sell_ratio = 1.0
                elif SELL_USE_MONTH_END and is_month_end:
                    exit_reason = "Month-End Force Close"
                    sell_ratio = 1.0
            else:
                # Original exit logic (SMA20-only style)
                if SELL_USE_ADX_EXHAUSTION and slope_prev >= 0 and slope_curr < 0:
                    exit_reason = "Trend Exhaustion (ADX 強弩之末)"
                    sell_ratio = 1.0
                elif SELL_USE_SMA20 and close < sma20:
                    exit_reason = "Trend Break (Close < SMA20)"
                    sell_ratio = 1.0
                elif SELL_USE_PDI_MDI and pdi < mdi:
                    exit_reason = "Momentum Flip (PDI < MDI)"
                    sell_ratio = 1.0
                elif SELL_USE_STOP_LOSS and close < stop_price:
                    exit_reason = f"Stop Loss (-{STOP_LOSS_PCT*100:.0f}%)"
                    sell_ratio = 1.0
                elif SELL_USE_MONTH_END and is_month_end:
                    exit_reason = "Month-End Force Close"
                    sell_ratio = 1.0

            if sell_ratio > 0:
                _append_trade(exit_reason, close, sell_ratio * position_ratio)
                if sell_ratio >= 1.0:
                    in_position = False
                    position_ratio = 1.0
                else:
                    position_ratio = 0.5

        # =============================================================
        # STATE: NO POSITION → check buy conditions (all criteria must pass)
        # =============================================================
        else:
            close_f = float(close)
            sma20_f = float(sma20) if pd.notna(sma20) else None
            sma50_f = float(sma50) if pd.notna(sma50) else None
            obv_f = float(obv) if pd.notna(obv) else None
            obv_ema_f = float(obv_ema_20) if pd.notna(obv_ema_20) else None
            obv_5ma_f = float(row.get("OBV_5MA")) if pd.notna(row.get("OBV_5MA")) else None
            vwap_f = float(vwap) if pd.notna(vwap) else None
            close_sma20_ok = _check_op(close_f, sma20_f, CLOSE_VS_SMA20)
            close_sma50_ok = _check_op(close_f, sma50_f, CLOSE_VS_SMA50)
            obv_ok = _check_op(obv_f, obv_ema_f, OBV_VS_OBV_EMA20)
            obv_5ma_ok = _check_op(obv_f, obv_5ma_f, OBV_VS_OBV_5MA)
            close_vwap_ok = _check_op(close_f, vwap_f, CLOSE_VS_VWAP)
            core_pdi_mdi = (pdi > mdi + PDI_BUFFER) if CORE_REQUIRE_PDI_MDI else True
            core_adx_floor = adx > ADX_MIN
            core_adx_cap   = adx < ADX_MAX
            adx_awakening = (slope_prev <= 0 and slope_curr > 0) if CORE_REQUIRE_ADX_AWAKENING else True
            mfi_rsi_ok = True
            if MFI_VS_RSI == "mfi>rsi" and not pd.isna(mfi) and not pd.isna(rsi):
                mfi_rsi_ok = float(mfi) > float(rsi)
            elif MFI_VS_RSI == "rsi>mfi" and not pd.isna(mfi) and not pd.isna(rsi):
                mfi_rsi_ok = float(rsi) > float(mfi)
            rsi_ok = _check_op(float(rsi) if not pd.isna(rsi) else None, RSI_VALUE, RSI_OP)
            rs_20d_ok = _check_op(float(rs_20d) if rs_20d is not None and pd.notna(rs_20d) else None, RS_20D_VALUE, RS_20D_OP)
            mfi_ok = _check_op(float(mfi) if not pd.isna(mfi) else None, MFI_VALUE, MFI_OP)
            rvol_ok = _check_op(float(rvol) if not pd.isna(rvol) else None, RVOL_VALUE, RVOL_OP)
            adx_slope_ok = _check_op(slope_curr, 0.0, ADX_SLOPE_OP)
            gap_val = float(pdi) - float(mdi) if (pd.notna(pdi) and pd.notna(mdi)) else None
            gap_ok = _check_op(gap_val, GAP_VALUE, GAP_OP)
            stoch_k_val = float(row.get("Stoch_K")) if pd.notna(row.get("Stoch_K")) else None
            stoch_d_val = float(row.get("Stoch_D")) if pd.notna(row.get("Stoch_D")) else None
            stoch_k_prev = float(row.get("Stoch_K_prev")) if pd.notna(row.get("Stoch_K_prev")) else None
            stoch_d_prev = float(row.get("Stoch_D_prev")) if pd.notna(row.get("Stoch_D_prev")) else None
            stoch_k_ok = _check_op(stoch_k_val, STOCH_K_VALUE, STOCH_K_OP)
            stoch_k_gt_d_ok = True
            if STOCH_REQUIRE_K_GT_D:
                stoch_k_gt_d_ok = (
                    stoch_k_val is not None
                    and stoch_d_val is not None
                    and not (pd.isna(stoch_k_val) or pd.isna(stoch_d_val))
                    and stoch_k_val > stoch_d_val
                )
            stoch_k_prev_ok = _check_op(stoch_k_val, stoch_k_prev, STOCH_K_VS_PREV_OP)
            stoch_d_prev_ok = _check_op(stoch_d_val, stoch_d_prev, STOCH_D_VS_PREV_OP)
            stoch_d_level_ok = _check_op(stoch_d_val, STOCH_D_VALUE, STOCH_D_OP)
            spread_ok = _check_op(float(spread) if not pd.isna(spread) else None, SPREAD_VALUE, SPREAD_OP)

            core = (close_sma20_ok and close_sma50_ok and obv_ok and obv_5ma_ok and close_vwap_ok and
                    core_pdi_mdi and core_adx_floor and core_adx_cap and adx_awakening and mfi_rsi_ok
                    and rsi_ok and rs_20d_ok and mfi_ok and rvol_ok and adx_slope_ok and gap_ok and stoch_k_ok and spread_ok)
            core = core and stoch_k_gt_d_ok and stoch_k_prev_ok and stoch_d_prev_ok and stoch_d_level_ok

            if ENTRY_USE_REVERSAL_BREAKOUT:
                macd_hist = row.get("MACD_Hist")
                macd_hist_prev = row.get("MACD_Hist_Prev")
                if pd.isna(macd_hist) or pd.isna(macd_hist_prev):
                    buy_signal = False
                else:
                    macd_improving = float(macd_hist) > float(macd_hist_prev)
                    rsi_r = float(rsi) if not pd.isna(rsi) else None
                    sk = row.get("Stoch_K")
                    sd = row.get("Stoch_D")
                    stoch_cross = (
                        not pd.isna(sk) and not pd.isna(sd) and float(sk) > float(sd)
                    )
                    momentum_ok = (rsi_r is not None and rsi_r > REVERSAL_RSI_MIN) and stoch_cross
                    vol_surge = rvol > REVERSAL_RVOL_MIN
                    price_trend = sma20_f is not None and close_f > sma20_f
                    buy_signal = macd_improving and momentum_ok and vol_surge and price_trend
            elif ENTRY_USE_MACD_CROSSOVER:
                macd_hist = row.get("MACD_Hist")
                macd_hist_prev = row.get("MACD_Hist_Prev")
                if pd.isna(macd_hist) or pd.isna(macd_hist_prev):
                    buy_signal = False
                else:
                    macd_cross = float(macd_hist) > MACD_HIST_MIN and float(macd_hist_prev) <= MACD_HIST_PREV_MAX
                    buy_signal = macd_cross and rvol_ok
            else:
                buy_signal = core
            if buy_signal:
                in_position = True
                position_ratio = 1.0
                entry_price = close
                entry_date  = date
                highest_high_since_entry = high
                entry_adx  = adx
                entry_rsi  = rsi
                entry_pdi  = pdi
                entry_mdi  = mdi
                entry_rvol = rvol
                entry_mfi  = mfi
                entry_spread = spread
                entry_slope = slope_curr
                entry_sma50 = float(sma50) if pd.notna(sma50) else None
                entry_obv = float(obv) if pd.notna(obv) else None
                entry_obv_ema_20 = float(obv_ema_20) if pd.notna(obv_ema_20) else None
                entry_vwap = float(vwap) if pd.notna(vwap) else None
                entry_rs_20d = row.get("RS_20d_Outperform")
                if entry_rs_20d is not None and pd.notna(entry_rs_20d):
                    entry_rs_20d = float(entry_rs_20d)
                else:
                    entry_rs_20d = None
                eml = row.get("MACD_Line")
                ems = row.get("MACD_Signal")
                emh = row.get("MACD_Hist")
                emhp = row.get("MACD_Hist_Prev")
                entry_macd_line = float(eml) if eml is not None and pd.notna(eml) else None
                entry_macd_signal = float(ems) if ems is not None and pd.notna(ems) else None
                entry_macd_hist = float(emh) if emh is not None and pd.notna(emh) else None
                entry_macd_hist_prev = float(emhp) if emhp is not None and pd.notna(emhp) else None
                if ENTRY_USE_REVERSAL_BREAKOUT:
                    entry_reason = (
                        f"絕地反擊: MACD Hist↑ | RSI>{REVERSAL_RSI_MIN} & StochK>D | "
                        f"RVOL>{REVERSAL_RVOL_MIN} | Close>SMA20"
                    )
                elif ENTRY_USE_MACD_CROSSOVER:
                    entry_reason = (
                        f"MACD zero-cross (Hist>{MACD_HIST_MIN}, Hist_prev<={MACD_HIST_PREV_MAX}) | "
                        f"RVOL{RVOL_OP}{RVOL_VALUE}"
                    )
                else:
                    core_parts = []
                    if CLOSE_VS_SMA20 not in (None, "", "off"):
                        core_parts.append(f"Close{CLOSE_VS_SMA20}SMA20")
                    if CLOSE_VS_SMA50 not in (None, "", "off"):
                        core_parts.append(f"Close{CLOSE_VS_SMA50}SMA50")
                    if OBV_VS_OBV_EMA20 not in (None, "", "off"):
                        core_parts.append(f"OBV{OBV_VS_OBV_EMA20}OBV_EMA20")
                    if OBV_VS_OBV_5MA not in (None, "", "off"):
                        core_parts.append(f"OBV{OBV_VS_OBV_5MA}OBV_5MA")
                    if CLOSE_VS_VWAP not in (None, "", "off"):
                        core_parts.append(f"Close{CLOSE_VS_VWAP}VWAP")
                    if MFI_VS_RSI not in (None, "", "off"):
                        core_parts.append(MFI_VS_RSI)
                    if RSI_OP not in (None, "", "off"):
                        core_parts.append(f"RSI{RSI_OP}{RSI_VALUE}")
                    if RS_20D_OP not in (None, "", "off"):
                        core_parts.append(f"RS20d{RS_20D_OP}{RS_20D_VALUE}")
                    if MFI_OP not in (None, "", "off"):
                        core_parts.append(f"MFI{MFI_OP}{MFI_VALUE}")
                    if RVOL_OP not in (None, "", "off"):
                        core_parts.append(f"RVOL{RVOL_OP}{RVOL_VALUE}")
                    if ADX_SLOPE_OP not in (None, "", "off"):
                        core_parts.append(f"ADX_slope{ADX_SLOPE_OP}0")
                    if GAP_OP not in (None, "", "off"):
                        core_parts.append(f"Gap{GAP_OP}{GAP_VALUE}")
                    if STOCH_K_OP not in (None, "", "off"):
                        core_parts.append(f"StochK{STOCH_K_OP}{STOCH_K_VALUE}")
                    if STOCH_REQUIRE_K_GT_D:
                        core_parts.append("StochK>StochD")
                    if STOCH_K_VS_PREV_OP not in (None, "", "off"):
                        core_parts.append(f"StochK{STOCH_K_VS_PREV_OP}K_prev")
                    if STOCH_D_VS_PREV_OP not in (None, "", "off"):
                        core_parts.append(f"StochD{STOCH_D_VS_PREV_OP}D_prev")
                    if STOCH_D_OP not in (None, "", "off"):
                        core_parts.append(f"StochD{STOCH_D_OP}{STOCH_D_VALUE}")
                    if SPREAD_OP not in (None, "", "off"):
                        core_parts.append(f"Spread{SPREAD_OP}{SPREAD_VALUE}")
                    if CORE_REQUIRE_PDI_MDI:
                        core_parts.append(f"PDI>MDI+{PDI_BUFFER}" if PDI_BUFFER != 0 else "PDI>MDI")
                    core_parts.append(f"ADX{ADX_MIN}-{ADX_MAX}")
                    if CORE_REQUIRE_ADX_AWAKENING:
                        core_parts.append("龍抬頭")
                    entry_reason = " | ".join(core_parts)
                if verbose:
                    print(f"  >>> BUY  {date.strftime('%Y-%m-%d')}  Close={close:.2f}  ADX={adx:.1f}  PDI={pdi:.1f}  MDI={mdi:.1f}")

    # If still in position at last bar, force close
    if in_position:
        last = df.iloc[-1]
        date = df.index[-1]
        exit_price = last["Close"]
        pnl = (exit_price - entry_price) * position_ratio
        pnl_pct = (pnl / entry_price) * 100
        cost = entry_price * position_ratio
        proceeds = exit_price * position_ratio
        trades.append({
            "Entry_Date":   entry_date.strftime("%Y-%m-%d"),
            "Entry_Price":  round(entry_price, 2),
            "Entry_Reason": entry_reason,
            "Cost":         round(cost, 2),
            "Proceeds":     round(proceeds, 2),
            "Exit_Date":    date.strftime("%Y-%m-%d"),
            "Exit_Price":   round(exit_price, 2),
            "Exit_Reason":  "End of Data",
            "Hold_Days":    (date - entry_date).days,
            "PnL":          round(pnl, 2),
            "PnL%":         round(pnl_pct, 2),
            "Result":       "WIN" if pnl > 0 else "LOSS",
            "E_ADX":        round(entry_adx, 1),
            "E_ADX_Slope":  round(entry_slope, 2),
            "E_RSI":        round(entry_rsi, 1),
            "E_PDI":        round(entry_pdi, 1),
            "E_MDI":        round(entry_mdi, 1),
            "E_RVOL":       round(entry_rvol, 2) if pd.notna(entry_rvol) else None,
            "E_MFI":        round(entry_mfi, 1) if pd.notna(entry_mfi) else None,
            "E_Spread":     round(entry_spread, 1),
            "E_SMA_50":     round(entry_sma50, 2) if pd.notna(entry_sma50) else None,
            "E_OBV":        round(entry_obv, 0) if pd.notna(entry_obv) else None,
            "E_OBV_EMA_20": round(entry_obv_ema_20, 0) if pd.notna(entry_obv_ema_20) else None,
            "E_VWAP":       round(entry_vwap, 2) if pd.notna(entry_vwap) else None,
            "E_RS_20d":     round(entry_rs_20d, 2) if entry_rs_20d is not None and pd.notna(entry_rs_20d) else None,
            "E_MACD_Line":   round(entry_macd_line, 4) if entry_macd_line is not None and pd.notna(entry_macd_line) else None,
            "E_MACD_Signal": round(entry_macd_signal, 4) if entry_macd_signal is not None and pd.notna(entry_macd_signal) else None,
            "E_MACD_Hist":   round(entry_macd_hist, 4) if entry_macd_hist is not None and pd.notna(entry_macd_hist) else None,
            "E_MACD_Hist_Prev": round(entry_macd_hist_prev, 4) if entry_macd_hist_prev is not None and pd.notna(entry_macd_hist_prev) else None,
        })

    return trades


# ===========================================================================
# Part 5: Report
# ===========================================================================
def print_report(symbol: str, trades: List[Dict], df: pd.DataFrame) -> None:
    n = len(trades)
    if n == 0:
        print("\n" + "=" * 64)
        print("  NO TRADES TRIGGERED")
        print("=" * 64)
        print("  The Veteran conditions are strict by design.")
        print(f"  This means {symbol} had no clean trend setups in this period.")
        print("  That is a valid result — no trade is sometimes the best trade.")
        print(f"  Data: {len(df)} bars, {df.index[0].date()} → {df.index[-1].date()}")
        print("=" * 64)
        return

    tdf = pd.DataFrame(trades)

    wins   = tdf[tdf["Result"] == "WIN"]
    losses = tdf[tdf["Result"] == "LOSS"]
    total_pnl = tdf["PnL"].sum()
    total_cost = tdf["Cost"].sum() if "Cost" in tdf.columns else 0
    total_proceeds = tdf["Proceeds"].sum() if "Proceeds" in tdf.columns else 0
    overall_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    win_rate = len(wins) / n * 100

    avg_win  = wins["PnL%"].mean()  if len(wins)   > 0 else 0
    avg_loss = losses["PnL%"].mean() if len(losses) > 0 else 0

    print("\n" + "=" * 72)
    print(f"  VETERAN BACKTEST REPORT — {symbol} Trend Following")
    print("=" * 72)
    print(f"  Symbol:          {symbol}")
    print(f"  Data Range:      {df.index[0].date()} → {df.index[-1].date()} ({len(df)} bars)")
    print("-" * 72)
    print(f"  Total Trades:    {n}")
    print(f"  Wins:            {len(wins)}    ({win_rate:.1f}%)")
    print(f"  Losses:          {len(losses)}    ({100 - win_rate:.1f}%)")
    print("-" * 72)
    print(f"  Total Cost:      HK${total_cost:>10,.2f}")
    print(f"  Total Proceeds:  HK${total_proceeds:>10,.2f}")
    print(f"  Total P&L:       HK${total_pnl:>+10.2f}  (Overall Return: {overall_pnl_pct:+.1f}%)")
    print(f"  Avg Win:         {avg_win:>+8.2f}%")
    print(f"  Avg Loss:        {avg_loss:>+8.2f}%")
    print(f"  Avg Hold Days:   {tdf['Hold_Days'].mean():.1f}")
    print("=" * 72)

    # ---- Exit reason breakdown ----
    print("\n--- Exit Reason Breakdown ---")
    reason_counts = tdf["Exit_Reason"].value_counts()
    for reason, cnt in reason_counts.items():
        sub = tdf[tdf["Exit_Reason"] == reason]
        sub_pnl = sub["PnL"].sum()
        print(f"  {reason:<35s}  {cnt:>2} trades   PnL: HK${sub_pnl:>+9.2f}")

    # ---- Detailed Trade Log (includes entry ADX for verification) ----
    print("\n--- Detailed Trade Log ---\n")
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 140)
    log_cols = [
        "Entry_Date", "Entry_Price", "Entry_Reason",
        "E_ADX", "E_ADX_Slope", "E_PDI", "E_MDI", "E_RSI", "E_MFI", "E_RVOL", "E_Spread",
        "E_MACD_Line", "E_MACD_Signal", "E_MACD_Hist", "E_MACD_Hist_Prev",
        "Exit_Date", "Exit_Price", "Exit_Reason",
        "Hold_Days", "PnL", "PnL%", "Result",
    ]
    # Only include columns that exist
    log_cols = [c for c in log_cols if c in tdf.columns]
    print(tdf[log_cols].to_string(index=False))

    # ---- Verify ADX band: 20 < E_ADX < 50 ----
    if "E_ADX" in tdf.columns:
        bad_low = tdf[tdf["E_ADX"].notna() & (tdf["E_ADX"] <= ADX_MIN)]
        bad_high = tdf[tdf["E_ADX"].notna() & (tdf["E_ADX"] >= ADX_MAX)]
        if len(bad_low) > 0:
            print(f"\n⚠️  BUG: {len(bad_low)} trade(s) entered with ADX <= {ADX_MIN}!")
            print(bad_low[["Entry_Date", "E_ADX"]].to_string(index=False))
        if len(bad_high) > 0:
            print(f"\n⚠️  BUG: {len(bad_high)} trade(s) entered with ADX >= {ADX_MAX} (exhaustion zone)!")
            print(bad_high[["Entry_Date", "E_ADX"]].to_string(index=False))
        if len(bad_low) == 0 and len(bad_high) == 0:
            print(f"\n✅ ADX band verified: all entries had {ADX_MIN} < ADX < {ADX_MAX}")

    # ---- Losing trades analysis ----
    if len(losses) > 0:
        print("\n--- Losing Trades Analysis (Indicators at Entry) ---\n")
        fail_cols = [
            "Entry_Date", "Entry_Price", "Entry_Reason", "Exit_Reason",
            "PnL%", "E_ADX", "E_ADX_Slope", "E_RSI", "E_PDI", "E_MDI", "E_MFI", "E_RVOL", "E_Spread",
        ]
        fail_cols = [c for c in fail_cols if c in losses.columns]
        print(losses[fail_cols].to_string(index=False))

    print()


# ===========================================================================
# Part 6: backtesting.py Strategy (bonus — interactive chart)
# ===========================================================================
def run_backtesting_py(df: pd.DataFrame, symbol: str = "9988.HK") -> None:
    """Run backtesting.py for the interactive Bokeh chart (optional)."""
    try:
        from backtesting import Backtest, Strategy as BtStrategy
    except ImportError:
        print("[SKIP] backtesting.py not installed — no interactive chart.")
        return

    class VeteranStrategy(BtStrategy):
        def init(self):
            c = pd.Series(self.data.Close, index=self.data.index)
            h = pd.Series(self.data.High, index=self.data.index)
            l = pd.Series(self.data.Low, index=self.data.index)
            v = pd.Series(self.data.Volume, index=self.data.index)

            self.sma20 = self.I(lambda x: _sma(pd.Series(x), 20).values, c, name="SMA20")
            self.rsi   = self.I(lambda x: _rsi(pd.Series(x), 14).values, c, name="RSI14")

            def _calc(h, l, c, col):
                return _adx(pd.Series(h), pd.Series(l), pd.Series(c), 14)[col].values
            self.adx = self.I(_calc, h, l, c, "ADX_14", name="ADX")
            self.pdi = self.I(_calc, h, l, c, "DMP_14", name="PDI")
            self.mdi = self.I(_calc, h, l, c, "DMN_14", name="MDI")
            self.obv = self.I(lambda c, v: _obv(pd.Series(c), pd.Series(v)).values, c, v, name="OBV")
            self.obv_sma = self.I(lambda c, v: _sma(_obv(pd.Series(c), pd.Series(v)), 20).values, c, v, name="OBV_SMA20")

            self._entry_price = 0.0

        def next(self):
            price = self.data.Close[-1]
            if np.isnan(self.sma20[-1]) or np.isnan(self.adx[-1]):
                return
            if len(self.adx) < 2:
                return

            if not self.position:
                # Core: trend floor + cap, trend, dominance
                core = (
                    price > self.sma20[-1]
                    and self.pdi[-1] > self.mdi[-1] + PDI_BUFFER
                    and self.adx[-1] > ADX_MIN
                    and self.adx[-1] < ADX_MAX
                )
                rvol = self.data.RVOL[-1] if hasattr(self.data, "RVOL") and len(self.data.RVOL) else np.nan
                mfi = self.data.MFI14[-1] if hasattr(self.data, "MFI14") and len(self.data.MFI14) else np.nan
                spread = self.data.Spread[-1] if hasattr(self.data, "Spread") and len(self.data.Spread) else np.nan
                spread_pt = (1 if (SCORE_REQUIRE_SPREAD and not np.isnan(spread) and spread > 0) else 0)
                score = (1 if self.rsi[-1] > RSI_ENTRY else 0) + (1 if (not np.isnan(mfi) and mfi > MFI_ENTRY) else 0) + (1 if (not np.isnan(rvol) and rvol >= RVOL_MIN) else 0) + spread_pt
                if core and score >= SCORECARD_MIN:
                    self.buy()
                    self._entry_price = price
            else:
                stop = self._entry_price * (1 - STOP_LOSS_PCT)
                if (
                    price < self.sma20[-1]
                    or self.pdi[-1] < self.mdi[-1]
                    or price < stop
                ):
                    self.position.close()

    valid = df.dropna(subset=["SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread", "ATR14"])
    if len(valid) < 20:
        return

    bt = Backtest(valid, VeteranStrategy, cash=INITIAL_CASH, commission=COMMISSION_PCT, exclusive_orders=True)
    bt.run()
    safe_name = symbol.replace(".", "").replace(" ", "_")
    chart_file = f"backtest_{safe_name}.html"
    try:
        bt.plot(filename=chart_file, open_browser=False)
        print(f"Interactive chart saved: {chart_file}")
    except Exception as e:
        print(f"Chart skipped: {e}")


# ===========================================================================
# Part 7: Main & Stress Test
# ===========================================================================
def run_one_symbol(ticker: str, verbose: bool = True) -> Optional[Dict]:
    """
    Fetch data, compute indicators, run veteran backtest for one symbol.
    Returns summary dict: symbol, n_trades, wins, losses, win_rate_pct, total_pnl, ...
    If verbose, prints full report; otherwise silent (for stress test).
    """
    try:
        df = fetch_data(ticker, API_KEY)
    except Exception as e:
        print(f"[{ticker}] Fetch failed: {e}")
        return None
    if len(df) < 30:
        print(f"[{ticker}] Not enough data: {len(df)} bars")
        return None

    df = add_indicators(df)
    valid = df.dropna(subset=["SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread", "ATR14"])
    if len(valid) < 10:
        print(f"[{ticker}] Not enough valid rows after warm-up")
        return None

    trades = run_veteran_backtest(valid, verbose=verbose, use_smart_exit=True)
    n = len(trades)

    if n == 0:
        summary = {
            "symbol": ticker,
            "n_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "avg_hold_days": 0.0,
            "data_bars": len(valid),
            "date_range": f"{valid.index[0].date()} → {valid.index[-1].date()}",
        }
        if verbose:
            print_report(ticker, trades, valid)
        return summary

    tdf = pd.DataFrame(trades)
    wins = tdf[tdf["Result"] == "WIN"]
    losses = tdf[tdf["Result"] == "LOSS"]
    total_pnl = tdf["PnL"].sum()
    win_rate = len(wins) / n * 100
    avg_win = wins["PnL%"].mean() if len(wins) > 0 else 0.0
    avg_loss = losses["PnL%"].mean() if len(losses) > 0 else 0.0

    summary = {
        "symbol": ticker,
        "n_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": win_rate,
        "total_pnl": total_pnl,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "avg_hold_days": tdf["Hold_Days"].mean(),
        "data_bars": len(valid),
        "date_range": f"{valid.index[0].date()} → {valid.index[-1].date()}",
    }
    if verbose:
        print_report(ticker, trades, valid)
    return summary


def print_stress_summary(results: List[Dict]) -> None:
    """Print a consolidated summary table and one block per stock."""
    print("\n")
    print("=" * 80)
    print("  STRESS TEST — SUMMARY TABLE (Veteran Trend-Following, ADX 20–50 cap)")
    print("=" * 80)
    print(f"  {'Symbol':<12} {'Trades':>7} {'Wins':>5} {'Losses':>6} {'Win Rate':>9} {'Total P&L (HK$)':>16}")
    print("-" * 80)
    for r in results:
        if r is None:
            continue
        wr = f"{r['win_rate_pct']:.1f}%"
        pnl = r["total_pnl"]
        pnl_str = f"{pnl:>+12.2f}"
        print(f"  {r['symbol']:<12} {r['n_trades']:>7} {r['wins']:>5} {r['losses']:>6} {wr:>9} {pnl_str:>16}")
    print("=" * 80)

    print("\n\n--- Summary Report per stock ---\n")
    for r in results:
        print("-" * 60)
        print(f"  {r['symbol']}  |  Data: {r['date_range']}  ({r['data_bars']} bars)")
        print(f"  Total Trades: {r['n_trades']}  |  Wins: {r['wins']}  |  Losses: {r['losses']}")
        print(f"  Win Rate: {r['win_rate_pct']:.1f}%  |  Total P&L: HK$ {r['total_pnl']:+.2f}")
        if r["n_trades"] > 0:
            print(f"  Avg Win: {r['avg_win_pct']:+.2f}%  |  Avg Loss: {r['avg_loss_pct']:+.2f}%  |  Avg Hold: {r['avg_hold_days']:.1f} days")
        print("-" * 60)
        print()


def run_stress_test() -> None:
    """Run backtest on STRESS_TEST_SYMBOLS and print summary for each."""
    print()
    print("=" * 80)
    print("  VETERAN — STRESS TEST (Core + Scorecard + MFI)")
    print("=" * 80)
    print("  Buy:  CORE (Close>SMA20, PDI>MDI, 20<ADX<50) + Score≥3/4 (RSI>50, MFI>55, RVOL>=1.0, Spread>0)")
    print("  Sell: Close<SMA20 | PDI<MDI | -8% stop | month-end")
    print("=" * 80)

    results = []
    for symbol, label in STRESS_TEST_SYMBOLS:
        print(f"\n>>> Running {symbol} ({label}) ...")
        summary = run_one_symbol(symbol, verbose=False)
        if summary is None:
            summary = {
                "symbol": symbol,
                "n_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "total_pnl": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
                "avg_hold_days": 0.0,
                "data_bars": 0,
                "date_range": "N/A (fetch failed)",
            }
        results.append(summary)
        if summary["n_trades"] > 0:
            print(f"    -> {summary['n_trades']} trades, Win Rate {summary['win_rate_pct']:.1f}%, P&L HK${summary['total_pnl']:+.2f}")
        elif summary["date_range"] != "N/A (fetch failed)":
            print(f"    -> 0 trades (no setup met)")
        else:
            print(f"    -> Failed")

    print_stress_summary(results)


def run_compare(symbols: Optional[List[str]] = None) -> None:
    """
    Run backtest on 0883.HK and 9988.HK with SMA20-only exit vs Smart Exit
    and print Total P&L comparison.
    """
    symbols = symbols or ["0883.HK", "9988.HK"]
    print()
    print("=" * 80)
    print("  SMART EXIT vs SMA20-ONLY EXIT — P&L COMPARISON")
    print("=" * 80)
    print("  SMA20-only:  Exit on Close<SMA20 | PDI<MDI | -8% stop | month-end")
    print("  Smart Exit:  + Hard Exit (Close<SMA20) | Trailing (High-3*ATR) | Profit Take 50% (RSI>75, bearish candle)")
    print("=" * 80)

    rows = []
    for ticker in symbols:
        print(f"\n>>> {ticker} ...")
        try:
            df = fetch_data(ticker, API_KEY)
        except Exception as e:
            print(f"  Fetch failed: {e}")
            rows.append({"symbol": ticker, "pnl_legacy": None, "pnl_smart": None, "n_legacy": 0, "n_smart": 0})
            continue
        df = add_indicators(df)
        valid = df.dropna(subset=["SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread", "ATR14"])
        if len(valid) < 10:
            print(f"  Not enough valid data")
            rows.append({"symbol": ticker, "pnl_legacy": None, "pnl_smart": None, "n_legacy": 0, "n_smart": 0})
            continue

        trades_legacy = run_veteran_backtest(valid, verbose=False, use_smart_exit=False)
        trades_smart  = run_veteran_backtest(valid, verbose=False, use_smart_exit=True)
        pnl_legacy = sum(t["PnL"] for t in trades_legacy)
        pnl_smart  = sum(t["PnL"] for t in trades_smart)
        rows.append({
            "symbol": ticker,
            "pnl_legacy": pnl_legacy,
            "pnl_smart": pnl_smart,
            "n_legacy": len(trades_legacy),
            "n_smart": len(trades_smart),
        })
        print(f"  SMA20-only: {len(trades_legacy)} trades, Total P&L HK$ {pnl_legacy:+.2f}")
        print(f"  Smart Exit: {len(trades_smart)} trades, Total P&L HK$ {pnl_smart:+.2f}  (diff: HK$ {pnl_smart - pnl_legacy:+.2f})")

    print("\n")
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  {'Symbol':<12} {'SMA20-only P&L':>18} {'Smart Exit P&L':>18} {'Difference':>14}")
    print("-" * 80)
    for r in rows:
        if r["pnl_legacy"] is None:
            print(f"  {r['symbol']:<12} {'N/A':>18} {'N/A':>18} {'N/A':>14}")
        else:
            diff = r["pnl_smart"] - r["pnl_legacy"]
            print(f"  {r['symbol']:<12} HK$ {r['pnl_legacy']:>+12.2f}   HK$ {r['pnl_smart']:>+12.2f}   HK$ {diff:>+10.2f}")
    print("=" * 80)
    print()


def main(symbol: Optional[str] = None):
    ticker = (symbol or os.environ.get("BACKTEST_SYMBOL") or DEFAULT_SYMBOL).strip()

    print()
    print("=" * 72)
    print(f"  {ticker} — VETERAN BACKTEST (Core + Scorecard + MFI)")
    print("=" * 72)
    print(f"  BUY:   CORE: Close>SMA20, PDI>MDI, {ADX_MIN}<ADX<{ADX_MAX}  |  SCORE (≥{SCORECARD_MIN}/4): RSI>{RSI_ENTRY}, MFI>{MFI_ENTRY}, RVOL>={RVOL_MIN}, Spread>0")
    print(f"  Exit:  Smart Exit (Hard / Trailing 3*ATR / Profit Take 50%) + PDI<MDI | -8% stop | month-end")
    print("=" * 72)

    # ---- 1. Fetch data ----
    df = fetch_data(ticker, API_KEY)
    print(f"\nLoaded {len(df)} days for {ticker}.")
    print(f"Range: {df.index[0].date()} → {df.index[-1].date()}\n")

    print("--- df.head() ---")
    print(df.head())
    print("\n--- df.tail() ---")
    print(df.tail())
    print()

    # ---- 2. Compute indicators ----
    print("Computing indicators...")
    df = add_indicators(df)

    valid = df.dropna(subset=["SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread", "ATR14"])
    print(f"Valid rows: {len(valid)} / {len(df)}  (after indicator warm-up)\n")

    if len(valid) < 10:
        print("Not enough data. Need more trading days.")
        return

    # ---- 3. Run veteran backtest (Smart Exit on) ----
    print("Running veteran backtest (Smart Exit: Hard / Trailing Stop / Profit Take)...")
    trades = run_veteran_backtest(valid, verbose=True, use_smart_exit=True)

    # ---- 4. Report ----
    print_report(ticker, trades, valid)

    # ---- 5. Interactive chart (bonus) ----
    run_backtesting_py(df, symbol=ticker)


def run_scorecard_test() -> None:
    """Run Core + Scorecard backtest on 9992.HK and 0005.HK (as requested)."""
    symbols = ["9992.HK", "0005.HK"]
    print()
    print("=" * 72)
    print("  SCORECARD TEST — 9992.HK & 0005.HK (Core + Scorecard + MFI)")
    print("=" * 72)
    for ticker in symbols:
        main(symbol=ticker)
    print("\n  Scorecard test done for:", ", ".join(symbols))


if __name__ == "__main__":
    # Usage: python backtest_options.py [SYMBOL]
    #        python backtest_options.py stress   # run 4-stock stress test
    #        python backtest_options.py compare  # 0883.HK & 9988.HK: Smart Exit vs SMA20-only P&L
    #        python backtest_options.py scorecard # 9992.HK & 0005.HK
    symbol_arg = sys.argv[1] if len(sys.argv) > 1 else None
    arg = (symbol_arg or "").strip().lower()
    if arg in ("stress", "--stress", "-s"):
        run_stress_test()
    elif arg in ("compare", "--compare", "-c"):
        run_compare()
    elif arg in ("scorecard", "--scorecard"):
        run_scorecard_test()
    else:
        main(symbol=symbol_arg)
