#!/usr/bin/env python3
"""
==========================================================================
  Veteran v4.0 — Automated Daily Scanner (HK & US)
==========================================================================
  Logic: Core (Close>SMA20, 20<ADX<50, PDI>MDI) + Score 3/4 (RSI>50, MFI>55, RVOL>=1.0, Spread>0)
  Run:   python daily_scanner.py                    # start scheduler (HK 17:00, US 08:30)
         python daily_scanner.py HK                 # run HK list once
         python daily_scanner.py US                 # run US list once
         python daily_scanner.py 0700.HK 9988.HK    # scan these tickers only (custom)
  Deps:  pip install yfinance pandas ta schedule
==========================================================================
"""

import csv
import gc
import math
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import yfinance as yf
    import pandas as pd
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import ADXIndicator, SMAIndicator
    from ta.volatility import AverageTrueRange
    from ta.volume import MFIIndicator
except ImportError as e:
    print(f"[ERROR] Missing module: {e}")
    print("Install with: pip install yfinance pandas ta")
    sys.exit(1)

try:
    import yfinance_bootstrap

    yfinance_bootstrap.enable()
except Exception:
    pass

try:
    import schedule
except ImportError:
    schedule = None  # Optional: only needed for scheduler mode

# --- 1. TICKER LISTS ---
# Normalize: stocklist.txt uses 5-digit codes (e.g. 09988.HK); we use 4-digit (9988.HK)
def _norm_code(raw: str) -> str:
    """Strip leading 0 from XXXXX.HK -> XXXX.HK"""
    s = raw.strip().upper()
    if not s.endswith(".HK"):
        return s
    prefix = s[:-3]
    if len(prefix) == 5 and prefix.startswith("0"):
        return prefix[1:] + ".HK"
    return s

# Tech stocks (from stocklist.txt)
TECH_TICKERS = [
    _norm_code(c) for c in
    ["00020.HK", "00241.HK", "00268.HK", "00285.HK", "00300.HK", "00700.HK", "00780.HK",
     "00981.HK", "00992.HK", "01024.HK", "01211.HK", "01347.HK", "01698.HK", "01810.HK",
     "02015.HK", "02382.HK", "03690.HK", "03888.HK", "06618.HK", "06690.HK", "09618.HK",
     "09626.HK", "09660.HK", "09863.HK", "09866.HK", "09868.HK", "09888.HK", "09961.HK",
     "09988.HK", "09999.HK"]
]

try:
    from hk_index_data import HKCEI_TICKERS, HSI_TICKERS, hk_index_membership
except ImportError:
    HSI_TICKERS: list[str] = []
    HKCEI_TICKERS: list[str] = []

    def hk_index_membership(ticker: str) -> str:  # type: ignore[misc]
        return "N/A"


# Default: Tech list when no args
DEFAULT_TICKERS = TECH_TICKERS.copy()

# HK = all three lists combined, deduplicated (for CLI: python daily_scanner.py HK)
HK_TICKERS = list(dict.fromkeys(TECH_TICKERS + HSI_TICKERS + HKCEI_TICKERS))

US_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AMD",
    "PLTR", "COIN", "MSTR", "SMCI", "AVGO", "COST", "NFLX", "JPM",
    "INTC", "WMT", "HOOD", "APP", "SNDK", "LITE", "CRWV", "BKNG",
    "MNDY", "BIDU", "BABA", "FUTU", "INTU", "SHOP", "PEP", "TXN",
    "GS", "IBM", "JNJ", "V", "JPM", "KO", "MRK", "NKE",
]


def _norm_us_ticker(sym: str) -> str:
    """Yahoo Finance class shares use hyphen (BRK.B → BRK-B)."""
    s = sym.strip().upper()
    if len(s) >= 3 and s[-2] == "." and s[-1].isalpha():
        return f"{s[:-2]}-{s[-1]}"
    return s


def _load_tickers_from_repo_file(filename: str, *, hk_norm: bool = False) -> list[str]:
    """Load one ticker per line from repo root file; supports # comments."""
    path = Path(__file__).resolve().parent / filename
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip().upper()
        if not s:
            continue
        if hk_norm:
            out.append(_norm_code(s))
        else:
            out.append(_norm_us_ticker(s))
    return list(dict.fromkeys(out))


def _load_hk_tickers_from_csv(filename: str) -> list[str]:
    """Load hkstocklist.csv: each row is numeric HKEX code, comma, name. Maps to Yahoo XXXX.HK."""
    path = Path(__file__).resolve().parent / filename
    if not path.is_file():
        return []
    out: list[str] = []

    def _parse_code_cell(cell: str) -> int | None:
        s = str(cell).replace("\ufeff", "").replace("\u00a0", " ").strip()
        digits = "".join(ch for ch in s if ch.isdigit())
        if not digits:
            return None
        try:
            n = int(digits, 10)
        except ValueError:
            return None
        return n if n > 0 else None

    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or not str(row[0]).strip():
                    continue
                key = str(row[0]).strip()
                if key.lower() == "code":
                    continue
                code = _parse_code_cell(key)
                if code is None:
                    try:
                        code = int(key, 10)
                    except ValueError:
                        continue
                if code <= 0:
                    continue
                sym = f"{code:04d}.HK" if code < 100_000 else f"{code}.HK"
                out.append(_norm_code(sym))
    except OSError:
        return []
    return list(dict.fromkeys(out))


def _short_stock_name(full: str) -> str:
    """Compact display name from hkstocklist.csv (drop legal suffix noise)."""
    s = str(full or "").strip()
    if not s:
        return ""
    for suf in (
        " Holdings Limited",
        " Holding Limited",
        " Holdings Ltd.",
        " Holdings Ltd",
        " Holdings Plc.",
        " Holdings Plc",
        " Holdings",
        " Limited",
        " Ltd.",
        " Ltd",
        " Plc.",
        " Plc",
        " Inc.",
        " Inc",
        " Corporation",
        " Corp.",
        " Corp",
        " Co. Ltd.",
        " Co., Ltd.",
        " Company Limited",
        " Group Limited",
        " Group Ltd.",
        " Group Inc.",
        " Group",
    ):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    s = s.replace("  ", " ").strip()
    if len(s) > 40:
        s = s[:37].rstrip() + "…"
    return s


def _load_hk_name_map_from_csv(filename: str) -> dict[str, str]:
    """Map normalized XXXX.HK ticker → short company name."""
    path = Path(__file__).resolve().parent / filename
    if not path.is_file():
        return {}
    out: dict[str, str] = {}

    def _parse_code_cell(cell: str) -> int | None:
        s = str(cell).replace("\ufeff", "").replace("\u00a0", " ").strip()
        digits = "".join(ch for ch in s if ch.isdigit())
        if not digits:
            return None
        try:
            n = int(digits, 10)
        except ValueError:
            return None
        return n if n > 0 else None

    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or not str(row[0]).strip():
                    continue
                key = str(row[0]).strip()
                if key.lower() == "code":
                    continue
                code = _parse_code_cell(key)
                if code is None:
                    try:
                        code = int(key, 10)
                    except ValueError:
                        continue
                if code <= 0:
                    continue
                sym = _norm_code(f"{code:04d}.HK" if code < 100_000 else f"{code}.HK")
                raw_name = row[1].strip() if len(row) > 1 else ""
                short = _short_stock_name(raw_name)
                if short:
                    out[sym] = short
    except OSError:
        return {}
    return out


def stock_name_for_ticker(ticker: str) -> str:
    return HK_STOCK_NAME_MAP.get(_norm_code(str(ticker or "").strip().upper()), "")


# HK universe: hkstocklist.csv overrides hk_top200.txt, else Tech+HSI+HKCEI.
HK_UNIVERSE_TAG = "Tech+HSI+HKCEI"
HK_FROM_STOCKLIST_CSV = _load_hk_tickers_from_csv("hkstocklist.csv")
HK_STOCK_NAME_MAP = _load_hk_name_map_from_csv("hkstocklist.csv")
HK_TOP200_TICKERS = _load_tickers_from_repo_file("hk_top200.txt", hk_norm=True)
US_TOP300_TICKERS = _load_tickers_from_repo_file("us_top300.txt", hk_norm=False)
US_TOP200_TICKERS = _load_tickers_from_repo_file("us_top200.txt", hk_norm=False)
US_UNIVERSE_TICKERS = US_TOP300_TICKERS or US_TOP200_TICKERS
US_UNIVERSE_TAG = (
    "us_top300.txt"
    if US_TOP300_TICKERS
    else ("us_top200.txt" if US_TOP200_TICKERS else "preset list")
)
if HK_FROM_STOCKLIST_CSV:
    HK_TICKERS = HK_FROM_STOCKLIST_CSV
    HK_UNIVERSE_TAG = "hkstocklist.csv"
elif HK_TOP200_TICKERS:
    HK_TICKERS = HK_TOP200_TICKERS
    HK_UNIVERSE_TAG = "hk_top200.txt"
if US_UNIVERSE_TICKERS:
    US_TICKERS = US_UNIVERSE_TICKERS


def get_tickers(market: str) -> list:
    """Return ticker list for market: Tech, HSI, HKCEI, HK (all), GREEDY_HK, or US."""
    if market == "TECH":
        print(f" Loaded {len(TECH_TICKERS)} Tech tickers.")
        return TECH_TICKERS.copy()
    if market == "HSI":
        print(f" Loaded {len(HSI_TICKERS)} HSI tickers.")
        return HSI_TICKERS.copy()
    if market == "HKCEI":
        print(f" Loaded {len(HKCEI_TICKERS)} HKCEI tickers.")
        return HKCEI_TICKERS.copy()
    if market == "HK":
        print(f" Loaded {len(HK_TICKERS)} HK tickers ({HK_UNIVERSE_TAG}).")
        return HK_TICKERS.copy()
    if market == "GREEDY_HK":
        tickers = greedy_hk_universe()
        print(f" Loaded {len(tickers)} HK tickers (greedy: HK list + hk_universe_extra.txt).")
        return tickers
    if market == "US":
        print(f" Loaded {len(US_TICKERS)} US tickers ({US_UNIVERSE_TAG}).")
        return US_TICKERS.copy()
    return []


# Minimum daily OHLCV rows before running the indicator stack. The old floor was 50,
# which marked many valid HK names as NO DATA: Yahoo may list only 20–40 sessions
# after IPO while `ta` ADXIndicator(14) needs ~28 rows for a stable last-bar ADX.
MIN_OHLCV_BARS = 28


# --- 2. VETERAN v4.0 SIGNAL (Core + Score 3/4) ---
def _normalize_ohlcv_df(df: pd.DataFrame | None, *, min_rows: int = MIN_OHLCV_BARS) -> pd.DataFrame | None:
    if df is None or len(df) < min_rows:
        return None
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [c[0] if isinstance(c, tuple) else c for c in out.columns]
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    need = ["Open", "High", "Low", "Close", "Volume"]
    for col in need:
        if col not in out.columns:
            return None
    return out[need].astype(float).sort_index()


# Benchmark closes cached for whole scan (^HSI / ^GSPC) — avoids hundreds of duplicate downloads.
_BENCH_CLOSE_CACHE: dict[str, pd.Series] = {}


def reset_scan_fetch_caches() -> None:
    """Clear in-memory benchmark cache between model passes (optional)."""
    _BENCH_CLOSE_CACHE.clear()
    gc.collect()


def _benchmark_close_series(benchmark_ticker: str) -> pd.Series | None:
    """One long download per benchmark per scan; slice when aligning to each stock."""
    key = str(benchmark_ticker).strip().upper()
    if key in _BENCH_CLOSE_CACHE:
        return _BENCH_CLOSE_CACHE[key]
    series: pd.Series | None = None
    for period in ("2y", "1y", "6mo"):
        try:
            raw = yf.download(
                key, period=period, interval="1d", auto_adjust=False, progress=False, threads=False
            )
            if raw is None or raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw = raw.copy()
                raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
            if "Close" in raw.columns:
                s = raw["Close"].copy()
            else:
                s = raw.iloc[:, 0].copy()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            series = s.sort_index()
            if len(series) >= 30:
                break
        except Exception:
            continue
    _BENCH_CLOSE_CACHE[key] = series
    return series


def _fetch_ohlcv(ticker: str, period: str = "6mo") -> pd.DataFrame | None:
    """Fetch OHLCV; minimal Yahoo calls to avoid SQLite / file-descriptor exhaustion."""
    periods: list[str] = []
    for p in (period, "1y", "2y"):
        if p and p not in periods:
            periods.append(p)

    best: pd.DataFrame | None = None

    def _consider(raw: pd.DataFrame | None) -> None:
        nonlocal best
        norm = _normalize_ohlcv_df(raw)
        if norm is not None and (best is None or len(norm) > len(best)):
            best = norm

    for p in periods:
        try:
            _consider(yf.Ticker(ticker).history(period=p, auto_adjust=False))
        except Exception:
            pass
        if best is not None and len(best) >= MIN_OHLCV_BARS:
            break
        if best is None:
            try:
                _consider(
                    yf.download(
                        ticker, period=p, interval="1d", auto_adjust=False, progress=False, threads=False
                    )
                )
            except Exception:
                pass
        if best is not None and len(best) >= 252:
            break

    return best


def get_indicator_df(ticker: str, *, period: str = "6mo") -> pd.DataFrame | None:
    """
    Fetch OHLCV and compute indicators needed for scanner strategies.
    Returns a dataframe with columns: Close, PDI, MDI, ADX, ATR, VWAP, RSI, MFI, RVOL,
    SMA20, OBV, OBV_5MA, RS_20d_Outperform, Stoch_K (where available).
    """
    df = _fetch_ohlcv(ticker, period=period)
    if df is None or len(df) < MIN_OHLCV_BARS:
        return None

    h, l, c, v = df["High"], df["Low"], df["Close"], df["Volume"]

    df["SMA20"] = SMAIndicator(close=c, window=20).sma_indicator()
    df["RSI"] = RSIIndicator(close=c, window=14).rsi()
    df["MFI"] = MFIIndicator(high=h, low=l, close=c, volume=v, window=14).money_flow_index()
    adx_ind = ADXIndicator(high=h, low=l, close=c, window=14)
    df["ADX"] = adx_ind.adx()
    df["PDI"] = adx_ind.adx_pos()
    df["MDI"] = adx_ind.adx_neg()
    df["ATR"] = AverageTrueRange(high=h, low=l, close=c, window=14).average_true_range()
    vol_sma = v.rolling(window=20, min_periods=1).mean().replace(0, float("nan"))
    df["RVOL"] = v / vol_sma

    diff = c.diff()
    obv_direction = (diff > 0).astype(float) - (diff < 0).astype(float)
    df["OBV"] = (obv_direction.fillna(0) * v).cumsum()
    df["OBV_5MA"] = df["OBV"].rolling(window=5).mean()

    try:
        stoch = StochasticOscillator(high=df["High"], low=df["Low"], close=df["Close"], window=14, smooth_window=3)
        df["Stoch_K"] = stoch.stoch()
        df["Stoch_D"] = stoch.stoch_signal()
    except Exception:
        df["Stoch_K"] = float("nan")
        df["Stoch_D"] = float("nan")

    df["Stoch_K_prev"] = df["Stoch_K"].shift(1)
    df["Stoch_D_prev"] = df["Stoch_D"].shift(1)

    typical = (h + l + c) / 3
    df["VWAP"] = (typical * v).rolling(window=20, min_periods=20).sum() / v.rolling(window=20, min_periods=20).sum()

    try:
        benchmark_ticker = "^HSI" if ".HK" in ticker.upper() else "^GSPC"
        bench_close = _benchmark_close_series(benchmark_ticker)
        if bench_close is not None and not bench_close.empty:
            aligned = bench_close.reindex(df.index, method="ffill")
            df["Benchmark_Close"] = aligned.values
            df["RS_Line"] = df["Close"] / df["Benchmark_Close"].replace(0, float("nan"))
            df["RS_20d_Outperform"] = (df["RS_Line"] / df["RS_Line"].shift(20) - 1) * 100
        else:
            df["RS_20d_Outperform"] = float("nan")
    except Exception:
        df["RS_20d_Outperform"] = float("nan")

    df["SMA_50"] = SMAIndicator(close=c, window=50).sma_indicator()
    df["Spread"] = df["MFI"] - df["RSI"]
    df["OBV_EMA_20"] = df["OBV"].ewm(span=20, adjust=False).mean()

    df["EMA_12"] = c.ewm(span=12, adjust=False).mean()
    df["EMA_26"] = c.ewm(span=26, adjust=False).mean()
    df["MACD_Line"] = df["EMA_12"] - df["EMA_26"]
    df["MACD_Signal"] = df["MACD_Line"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD_Line"] - df["MACD_Signal"]
    df["MACD_Hist_Prev"] = df["MACD_Hist"].shift(1)
    df["ADX_prev"] = df["ADX"].shift(1)
    df["ADX_prev2"] = df["ADX"].shift(2)

    return df


def load_extra_tickers_from_file(path: str | Path) -> list[str]:
    """One ticker per line; # comments; blank lines skipped."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        out.append(_norm_code(s) if s.upper().endswith(".HK") else s.strip())
    return out


def greedy_hk_universe(repo_root: str | Path | None = None) -> list[str]:
    """
    HK tech + HSI + HKCEI plus optional `hk_universe_extra.txt` (one symbol per line) in repo root.
    Deduplicated; order preserved (base first, then extras).
    """
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parent
    merged = list(dict.fromkeys(HK_TICKERS + load_extra_tickers_from_file(root / "hk_universe_extra.txt")))
    return merged


def _rs_points(rs20: float | None) -> float:
    """RS alpha core: outperforming market gets full 25 points."""
    if rs20 is None or (isinstance(rs20, float) and math.isnan(rs20)):
        return 0.0
    return 25.0 if float(rs20) > 0 else 0.0


def _adx_points(adx: float | None) -> float:
    """Trend strength bucket contribution (0..15)."""
    if adx is None or (isinstance(adx, float) and math.isnan(adx)):
        return 0.0
    a = float(adx)
    if a <= 15:
        return 0.0
    if a >= 45:
        return 15.0
    return (a - 15.0) / (45.0 - 15.0) * 15.0


def _dmi_points(pdi: float | None, mdi: float | None) -> float:
    """Directional conviction by +DI/-DI gap (0..10)."""
    if (
        pdi is None
        or mdi is None
        or (isinstance(pdi, float) and math.isnan(pdi))
        or (isinstance(mdi, float) and math.isnan(mdi))
    ):
        return 0.0
    gap = float(pdi) - float(mdi)
    if gap <= 0:
        return 0.0
    if gap >= 20:
        return 10.0
    return gap / 20.0 * 10.0


def _macd_points(mh: float | None, mhp: float | None) -> float:
    """Momentum turn quality from MACD histogram (0..15)."""
    if mh is None or (isinstance(mh, float) and math.isnan(mh)):
        return 0.0
    mhf = float(mh)
    p = float(mhp) if mhp is not None and not (isinstance(mhp, float) and math.isnan(mhp)) else float("nan")
    if mhf > 0 and (math.isnan(p) or p <= 0):
        return 15.0  # zero crossover
    if mhf <= 0 and not math.isnan(p) and mhf > p:
        return 13.0  # bottoming / shrinking red bars
    if mhf > 0 and not math.isnan(p) and mhf > p:
        return 11.0  # bullish expansion above zero
    if mhf > 0:
        return 8.0
    return 2.0


def _mfi_points(mfi: float | None) -> float:
    """Money flow score: linear 40->0, 80->15, capped."""
    if mfi is None or (isinstance(mfi, float) and math.isnan(mfi)):
        return 0.0
    m = float(mfi)
    if m <= 40:
        return 0.0
    if m >= 80:
        return 15.0
    return (m - 40.0) / (80.0 - 40.0) * 15.0


def _rvol_points(rvol: float | None) -> float:
    """Liquidity base score: RVOL <1 => 0, RVOL >=2 => 20, linear in-between."""
    if rvol is None or (isinstance(rvol, float) and math.isnan(rvol)):
        return 0.0
    x = float(rvol)
    if x <= 1.0:
        return 0.0
    if x >= 2.0:
        return 20.0
    return (x - 1.0) * 20.0


def _vwap_extended(close: float | None, vwap: float | None) -> bool:
    """True when price is >8% away from VWAP."""
    if (
        close is None
        or vwap is None
        or (isinstance(close, float) and math.isnan(close))
        or (isinstance(vwap, float) and math.isnan(vwap))
        or float(vwap) == 0.0
    ):
        return False
    dist = abs(float(close) - float(vwap)) / abs(float(vwap))
    return dist > 0.08


def _buy_rs_points(rs20: float | None) -> float:
    """
    Buy Stock: RS vs market (RS_20d_Outperform, already in percent e.g. 5.0 = 5%).
    Linear 0..30 pts; full credit at RS >= 5%; zero or negative RS => 0.
    """
    if rs20 is None or (isinstance(rs20, float) and math.isnan(rs20)):
        return 0.0
    RS = float(rs20)
    if RS <= 0:
        return 0.0
    if RS >= 5.0:
        return 30.0
    return (RS / 5.0) * 30.0


def _buy_rvol_points(rvol: float | None, close: float | None, open_: float | None, sma20: float | None) -> float:
    """Buy Stock 極限爆發模式: dry-up rally + surge scaling (max 36)."""
    if rvol is None or (isinstance(rvol, float) and math.isnan(rvol)):
        return 0.0
    x = float(rvol)
    if (
        x < 1.0
        and close is not None
        and open_ is not None
        and sma20 is not None
        and not (isinstance(close, float) and math.isnan(close))
        and not (isinstance(open_, float) and math.isnan(open_))
        and not (isinstance(sma20, float) and math.isnan(sma20))
        and float(close) > float(open_)
        and float(close) > float(sma20)
    ):
        return 18.0
    if x <= 1.2:
        return 0.0
    if x >= 3.5:
        return 36.0
    return min(36.0, max(0.0, (x - 1.2) / (3.5 - 1.2) * 36.0))


def _buy_adx_points(adx: float | None, adx_slope: float | None, close: float | None, vwap: float | None) -> float:
    """Buy Stock 極限爆發模式: ADX base + slope + aggressive >50 handling."""
    if adx is None or (isinstance(adx, float) and math.isnan(adx)):
        return 0.0
    a = float(adx)
    if a < 14:
        base = 3.0
    elif a < 20:
        base = 8.0 + (a - 14) * 1.2
    elif a <= 44:
        base = 18.0 + (a - 20) * 0.72
    elif a <= 58:
        base = 36.0 - (a - 44) * 0.55
    else:
        base = 18.0
    bonus = 0.0
    if adx_slope is not None and not (isinstance(adx_slope, float) and math.isnan(adx_slope)):
        s = float(adx_slope)
        if 16 <= a <= 50 and s > 0.1:
            bonus = min(9.0, s * 2.8)
    score = min(42.0, base + bonus)
    if (
        a > 50
        and close is not None
        and vwap is not None
        and not (isinstance(close, float) and math.isnan(close))
        and not (isinstance(vwap, float) and math.isnan(vwap))
    ):
        if float(close) > float(vwap):
            score += 10.0
        elif float(close) < float(vwap):
            score -= 15.0
    return max(0.0, score)


def _buy_macd_points(mh: float | None, mhp: float | None, macd_line: float | None) -> float:
    """
    Buy Stock / breakout model: reward green histogram; nerfed shrinking-red (Sell Put style).
    macd_line is accepted for call-site compatibility but not used in this rubric.
    """
    _ = macd_line
    if mh is None or (isinstance(mh, float) and math.isnan(mh)):
        return 0.0
    mhf = float(mh)
    has_p = mhp is not None and not (isinstance(mhp, float) and math.isnan(mhp))
    pf = float(mhp) if has_p else float("nan")
    if mhf > 0 and (not has_p or pf <= 0):
        return 25.0  # best: cross above zero / momentum shift
    if mhf > 0 and has_p and mhf > pf:
        return 20.0  # green bars growing
    if mhf > 0:
        return 12.0  # green but shrinking or flat vs prior
    if mhf <= 0 and has_p and mhf > pf:
        return 8.0  # red bars shrinking — weak buy signal; do not over-score
    return 0.0


def _buy_put_rs_points(rs20: float | None) -> float:
    """Bearish model: reward negative RS (underperformance vs benchmark), percent scale."""
    if rs20 is None or (isinstance(rs20, float) and math.isnan(rs20)):
        return 0.0
    RS = float(rs20)
    if RS >= 0:
        return 0.0
    if RS <= -5.0:
        return 30.0
    return (abs(RS) / 5.0) * 30.0


def _buy_put_adx_linear(adx: float | None) -> float:
    if adx is None or (isinstance(adx, float) and math.isnan(adx)):
        return 0.0
    a = float(adx)
    return 20.0 if a > 25 else max(0.0, (a / 25.0) * 20.0)


def _buy_put_dmi_bear_points(pdi: float | None, mdi: float | None) -> float:
    """Reward -DI > +DI; capped so trend bucket stays interpretable."""
    if pdi is None or mdi is None or (isinstance(pdi, float) and math.isnan(pdi)) or (isinstance(mdi, float) and math.isnan(mdi)):
        return 0.0
    gap = float(mdi) - float(pdi)
    if gap <= 0:
        return 0.0
    if gap >= 20:
        return 12.0
    return (gap / 20.0) * 12.0


def _buy_put_macd_points(mh: float | None, mhp: float | None) -> float:
    """Reward expanding red bars (hist < 0 and more negative than prior)."""
    if mh is None or (isinstance(mh, float) and math.isnan(mh)):
        return 0.0
    mhf = float(mh)
    has_p = mhp is not None and not (isinstance(mhp, float) and math.isnan(mhp))
    pf = float(mhp) if has_p else float("nan")
    if mhf < 0 and (not has_p or mhf < pf):
        return 20.0
    if mhf < 0 and has_p and mhf > pf:
        return 8.0
    if mhf > 0:
        return 0.0
    return 0.0


def _buy_put_mfi_points(mfi: float | None) -> float:
    if mfi is None or (isinstance(mfi, float) and math.isnan(mfi)):
        return 0.0
    return 10.0 if float(mfi) < 40 else 0.0


def macd_histogram_status(curr) -> str:
    """Human-readable MACD histogram state (繁體中文 labels)."""
    mh = curr.get("MACD_Hist")
    mhp = curr.get("MACD_Hist_Prev")
    if mh is None or (isinstance(mh, float) and pd.isna(mh)):
        return "資料不足"
    mh = float(mh)
    has_p = mhp is not None and pd.notna(mhp)
    p = float(mhp) if has_p else float("nan")
    if mh > 0 and (not has_p or p <= 0):
        return "柱體翻正（動能轉強）"
    if mh > 0 and has_p and mh > p:
        return "多頭柱體擴張"
    if mh > 0:
        return "多頭柱體收斂"
    if mh <= 0 and has_p and p > 0:
        return "柱體翻負"
    if mh <= 0 and has_p and mh > p:
        return "空頭柱體收斂"
    return "空頭柱體擴張"


def macd_status_from_row(row: dict) -> str:
    """Extract MACD histogram status text from a scanner row."""
    raw = row.get("macd_histogram_status") or row.get("macd_status")
    if raw is not None and str(raw).strip() not in ("", "—", "N/A", "nan", "None"):
        return str(raw).strip()
    why = str(row.get("Why") or row.get("reason") or "")
    if "macd=" in why:
        return why.split("macd=")[-1].split(";")[0].strip()
    return ""


def vwap_ext_from_row(row: dict) -> str | None:
    """Return 'Y' / 'N' when price is extended above VWAP, else None if unknown."""
    raw = row.get("vwap_ext", row.get("VWAP_Ext"))
    if raw is not None:
        s = str(raw).strip().upper()
        if s in ("Y", "N"):
            return s
    why = str(row.get("Why") or row.get("reason") or "")
    if "vwap_ext=" in why:
        token = why.split("vwap_ext=")[-1].split(")")[0].split(",")[0].strip().upper()
        if token in ("Y", "N"):
            return token
    return None


def _score_arc_flat_or_improving(row: dict) -> bool:
    """
    Optional Sell Put filter: 3-day score path flat or improving when data exists.
    Passes when delta >= 0, or arc pattern is non-deteriorating; unknown data does not block.
    """
    pat = str(row.get("score_arc_pattern") or "").strip().lower()
    if pat in ("erratic", "steady_fall", "fall", "single_down"):
        return False
    delta = row.get("tech_score_delta")
    if delta is not None and str(delta).strip().lower() not in ("", "n/a", "nan", "none"):
        try:
            return int(round(float(delta))) >= 0
        except (TypeError, ValueError):
            pass
    d0 = row.get("tech_score")
    d1 = row.get("tech_score_d1", row.get("tech_score_prev"))
    if d0 is not None and d1 is not None:
        try:
            return int(round(float(d0))) >= int(round(float(d1)))
        except (TypeError, ValueError):
            pass
    if pat in ("perfect_accel", "rise", "flat", "single_up", "mixed", ""):
        return True
    return True


def sell_put_trigger_scenario(row: dict) -> str | None:
    """
    Dual-track Sell Put entry: Scenario A (bottom-fishing) OR Scenario B (trend riding).
    Returns 'A', 'B', or None.
    """
    macd = macd_status_from_row(row)
    if not macd:
        return None
    ts = row.get("tech_score")
    if ts is None or str(ts).strip().lower() in ("", "n/a", "nan", "none"):
        return None
    try:
        score = int(round(float(ts)))
    except (TypeError, ValueError):
        return None

    # Scenario A: classic reversal (shrinking red bars)
    if score >= 65 and "空頭柱體收斂" in macd and _score_arc_flat_or_improving(row):
        return "A"

    # Scenario B: deep OTM put on strong breakout (expanding green / zero cross, not overextended)
    vwap_ok = vwap_ext_from_row(row) == "N"
    macd_b = "多頭柱體擴張" in macd or "柱體翻正" in macd
    if score >= 80 and macd_b and vwap_ok:
        return "B"

    return None


def _row_float(row: dict, *keys: str) -> float | None:
    for key in keys:
        raw = row.get(key)
        if raw is None:
            continue
        s = str(raw).strip().replace("—", "").replace("%", "").replace("x", "")
        if s.lower() in ("", "n/a", "nan", "none"):
            continue
        try:
            return float(s)
        except (TypeError, ValueError):
            continue
    return None


def buy_put_trigger_from_row(row: dict) -> bool:
    """
    Buy Put 恐慌破底 (matches dashboard Full Market History rules):
    score>=70, MACD 空頭柱體擴張, MACD negative, RVOL>=1.3, close < VWAP, RS<=0.
    """
    if not row or not bool(row.get("data_ok", True)):
        return False
    macd = macd_status_from_row(row)
    if not macd or "空頭柱體擴張" not in macd:
        return False
    ms = str(row.get("macd_sign", row.get("MACD_Sign", ""))).strip().lower()
    if ms != "negative" and "空頭" not in macd:
        return False
    ts = row.get("tech_score")
    if ts is None or str(ts).strip().lower() in ("", "n/a", "nan", "none"):
        return False
    try:
        score = int(round(float(ts)))
    except (TypeError, ValueError):
        return False
    if score < 70:
        return False
    rvol = _row_float(row, "rvol", "RVOL")
    if rvol is None or rvol < 1.3:
        return False
    close = _row_float(row, "close", "Close", "Price")
    vwap = _row_float(row, "vwap", "VWAP")
    if close is None or vwap is None or close >= vwap:
        return False
    rs = _row_float(row, "rs_20d", "RS_20d", "RS_20d_Outperform")
    if rs is not None and rs > 0:
        return False
    return True


def evaluate_trade_trigger(row: dict, score_model: str) -> str | None:
    """
    Return trade action slug when entry rules fire, else None.
    BUY_CALL (buy_stock): score>=80, rvol>=1.2, MACD 翻正 or 多頭擴張
    SELL_PUT (sell_put): Scenario A OR B via sell_put_trigger_scenario()
    BUY_PUT (buy_put): panic breakdown via buy_put_trigger_from_row()
    """
    if not row or not bool(row.get("data_ok", True)):
        return None
    model = str(score_model or row.get("score_model") or "sell_put").strip().lower()
    macd = macd_status_from_row(row)
    if not macd:
        return None

    ts = row.get("tech_score")
    if ts is None or str(ts).strip().lower() in ("", "n/a", "nan", "none"):
        return None
    try:
        score = int(round(float(ts)))
    except (TypeError, ValueError):
        return None

    rvol_raw = row.get("RVOL", row.get("rvol"))
    try:
        rvol_s = str(rvol_raw).strip().replace("—", "").replace("x", "")
        rvol = float(rvol_s) if rvol_s not in ("", "nan", "N/A") else None
    except (TypeError, ValueError):
        rvol = None

    if model in ("buy_stock", "buy", "aggressive", "extreme_breakout"):
        if score >= 80 and rvol is not None and rvol >= 1.2:
            if "柱體翻正" in macd or "多頭柱體擴張" in macd:
                return "BUY_CALL"
        return None

    if model in ("sell_put", "sell", "收租"):
        if sell_put_trigger_scenario(row):
            return "SELL_PUT"
        return None

    if model in ("buy_put", "bear_put", "short_put", "panic_breakdown"):
        if buy_put_trigger_from_row(row):
            return "BUY_PUT"
        return None

    return None


def macd_sign_label(macd_hist: float | None) -> str:
    """Simple MACD histogram sign for dashboard users."""
    if macd_hist is None or (isinstance(macd_hist, float) and pd.isna(macd_hist)):
        return "N/A"
    return "Positive" if float(macd_hist) >= 0 else "Negative"


def adx_strength_label(adx: float | None, adx_slope: float | None) -> str:
    if adx is None or (isinstance(adx, float) and pd.isna(adx)):
        return "—"
    a = float(adx)
    slope = 0.0
    if adx_slope is not None and pd.notna(adx_slope):
        slope = float(adx_slope)
    if a < 16:
        return "極弱（盤整）"
    if a < 22:
        return "偏弱"
    if a < 28:
        tag = "趨勢升溫"
    elif a <= 45:
        tag = "趨勢明確"
    else:
        tag = "極強（注意過熱）"
    if slope > 0.35 and 18 <= a <= 48:
        return f"{tag} · ADX 上升"
    return tag


def _signal_band_from_score(score: int, trading_mode: str) -> str:
    """
    Separate band mapping by trading mode.
    - 穩健收租 (Sell Put): stricter thresholds
    - 極限爆發 (Buy Stock/Call): lower breakout thresholds
    - 恐慌破底 (Buy Put): same numeric cutoffs, bearish option labels
    """
    tm = str(trading_mode or "").strip()
    if tm == "穩健收租 (Sell Put)":
        if score >= 80:
            return "🔥 STRONG (Sell Put)"
        if score >= 60:
            return "👀 WATCH (Potential)"
        return "⚠️ CAUTION (No Action)"

    if tm == "恐慌破底 (Buy Put / Short)":
        if score >= 75:
            return "🔥 STRONG (Buy Put)"
        if score >= 55:
            return "👀 WATCH (Fade / Hedge)"
        return "⚠️ CAUTION (No Short)"

    if score >= 75:
        return "🔥 STRONG (Buy)"
    if score >= 55:
        return "👀 WATCH (Can try)"
    return "⚠️ CAUTION (Cash is King)"


def _rule_based_ai_strategy(
    *,
    ticker: str,
    score: int,
    band: str,
    rvol: float | None,
    adx_lbl: str,
    macd_lbl: str,
    pdi: float | None,
    mdi: float | None,
    trading_mode: str | None = None,
) -> str:
    """
    Deterministic narrative (繁體中文) for the dashboard.
    Replaceable later with an LLM call using the same feature bundle.
    """
    tm = str(trading_mode or "").strip()
    bear_put = ("Buy Put" in str(band)) or ("恐慌破底" in tm) or ("buy_put" in tm.lower())

    bits: list[str] = []
    bits.append(f"「{ticker}」技術評分 {score}/100（{band}）。")
    if bear_put:
        if rvol is not None and not (isinstance(rvol, float) and pd.isna(rvol)):
            rv = float(rvol)
            if rv >= 1.35:
                bits.append("放量下殺，恐慌拋售意味濃，做淡需留意波動與引伸波幅。")
            elif rv >= 1.05:
                bits.append("量能略高於均量，下殺有資金參與，仍須確認趨勢延續。")
            elif rv < 0.85:
                bits.append("量能偏淡，缺乏恐慌拋售量；追沽或買 Put 宜保守，可等待放量再評估。")
        if "升溫" in adx_lbl or "明確" in adx_lbl or "極強" in adx_lbl:
            bits.append(f"ADX 解讀：{adx_lbl}；趨勢偏強時造淡須嚴守停損、注意軋空風險。")
        elif "偏弱" in adx_lbl or "極弱" in adx_lbl:
            bits.append("趨勢強度一般，下殺動能未必延續，宜小倉或觀望。")
        bits.append(f"MACD 柱體：{macd_lbl}。")
        if pdi is not None and mdi is not None and pd.notna(pdi) and pd.notna(mdi):
            if float(mdi) > float(pdi) + 1.0:
                bits.append("-DI 高於 +DI，空方結構暫占優。")
            elif float(pdi) > float(mdi) + 1.0:
                bits.append("+DI 高於 -DI，多方反撲風險仍在，造淡須謹慎。")
        band_u = str(band).upper()
        if "CAUTION" in band_u:
            bits.append("綜合屬觀望／不適合積極造淡；若操作務必嚴格風控。")
        elif "STRONG" in band_u:
            bits.append("綜合屬高勝率造淡觀察區；仍須配合大盤與事件，控制槓桿與到期日。")
        else:
            bits.append("綜合屬中性，可等待更明確的破底放量或 MACD 空頭擴張再加碼。")
    else:
        if rvol is not None and not (isinstance(rvol, float) and pd.isna(rvol)):
            rv = float(rvol)
            if rv >= 1.35:
                bits.append("量能明顯高於 20 日均量，短線參與度偏高，適合關注突破／延續訊號。")
            elif rv >= 1.05:
                bits.append("量能略高於均量，動能尚屬健康。")
            elif rv < 0.85:
                bits.append("量能偏淡，突破需更大成交量確認。")
        if "升溫" in adx_lbl or "明確" in adx_lbl or "極強" in adx_lbl:
            bits.append(f"ADX 解讀：{adx_lbl}；順勢操作權重可提高，但仍需配合 MACD 與量能。")
        elif "偏弱" in adx_lbl or "極弱" in adx_lbl:
            bits.append("趨勢強度一般，宜降低槓桿、偏區間或觀望。")
        bits.append(f"MACD 柱體：{macd_lbl}。")
        if pdi is not None and mdi is not None and pd.notna(pdi) and pd.notna(mdi):
            if float(pdi) > float(mdi) + 1.0:
                bits.append("+DI 高於 -DI，短期多方力道佔優。")
            elif float(mdi) > float(pdi) + 1.0:
                bits.append("-DI 高於 +DI，空方力道暫占上風。")
        band_u = str(band).upper()
        if "CAUTION" in band_u:
            bits.append("綜合屬保守區；若接實盤，建議嚴格停損與小倉試單。")
        elif "STRONG" in band_u:
            bits.append("綜合屬進攻區；仍須留意大盤與個股波動，分批進場較穩。")
        else:
            bits.append("綜合屬中性觀察區，可等待更明確結構再加碼。")
    return "".join(bits)


def _format_score_arc(s0: int | None, s1: int | None, s2: int | None) -> str:
    parts = []
    for v in (s0, s1, s2):
        parts.append("—" if v is None else str(int(v)))
    return " → ".join(parts)


def _classify_score_arc(s0: int | None, s1: int | None, s2: int | None) -> tuple[str, str]:
    if s2 is None:
        return "—", "insufficient"
    if s1 is None:
        return "—", "insufficient"
    if s0 is None:
        d = s2 - s1
        if d >= 8:
            return "單日急升", "single_up"
        if d <= -8:
            return "單日急跌", "single_down"
        return "橫行", "flat"
    if s0 < s1 < s2:
        return "完美加速", "perfect_accel"
    if s0 > s1 > s2:
        return "連續走弱", "steady_fall"
    span = max(s0, s1, s2) - min(s0, s1, s2)
    if span >= 25 and ((s1 < s0 and s2 > s1) or (s1 > s0 and s2 < s1)):
        return "神經刀", "erratic"
    if s0 <= s1 <= s2 and (s2 - s0) >= 12:
        return "緩步上升", "rise"
    if s0 >= s1 >= s2 and (s0 - s2) >= 12:
        return "緩步下跌", "fall"
    if span <= 8:
        return "橫行", "flat"
    if (s1 < s0 and s2 > s1) or (s1 > s0 and s2 < s1):
        return "震盪", "volatile"
    return "分化", "mixed"


def _tech_score_from_bar(df: pd.DataFrame, bar_index: int, score_model: str) -> int | None:
    """Compute tech_score as of one daily bar (uses that bar's indicators vs prior bar)."""
    if bar_index < 2 or bar_index >= len(df):
        return None
    curr = df.iloc[bar_index]
    adx = float(curr["ADX"]) if pd.notna(curr.get("ADX")) else None
    pdi = float(curr["PDI"]) if pd.notna(curr.get("PDI")) else None
    mdi = float(curr["MDI"]) if pd.notna(curr.get("MDI")) else None
    if adx is None or pdi is None or mdi is None:
        return None
    adx_prev = curr.get("ADX_prev")
    slope = float(adx - adx_prev) if pd.notna(adx_prev) else 0.0
    rvol_f = float(curr["RVOL"]) if pd.notna(curr.get("RVOL")) else None
    rs20_f = float(curr["RS_20d_Outperform"]) if pd.notna(curr.get("RS_20d_Outperform")) else None
    mfi_f = float(curr["MFI"]) if pd.notna(curr.get("MFI")) else None
    vwap_f = float(curr["VWAP"]) if pd.notna(curr.get("VWAP")) else None
    close_f = float(curr["Close"]) if pd.notna(curr.get("Close")) else None
    mh = curr.get("MACD_Hist")
    mhp = curr.get("MACD_Hist_Prev")
    model = str(score_model or "sell_put").strip().lower()

    if model in ("buy_put", "bear_put", "short_put", "panic_breakdown"):
        rs_p = _buy_put_rs_points(rs20_f)
        ad_p = _buy_put_adx_linear(adx)
        dmi_p = _buy_put_dmi_bear_points(pdi, mdi)
        trend_score = min(50.0, max(0.0, rs_p + ad_p + dmi_p))
        mc_p = _buy_put_macd_points(
            float(mh) if mh is not None and pd.notna(mh) else None,
            float(mhp) if mhp is not None and pd.notna(mhp) else None,
        )
        mfi_p = _buy_put_mfi_points(mfi_f)
        momentum_score = min(30.0, max(0.0, mc_p + mfi_p))
        rvol_raw = (
            min(20.0, float(rvol_f) * 10.0)
            if rvol_f is not None and not (isinstance(rvol_f, float) and math.isnan(rvol_f))
            else 0.0
        )
        vwap_pen = 0.0
        if (
            close_f is not None
            and vwap_f is not None
            and pd.notna(close_f)
            and pd.notna(vwap_f)
            and float(close_f) > float(vwap_f)
        ):
            vwap_pen = 20.0
        pattern_score = max(0.0, min(20.0, rvol_raw - vwap_pen))
        total_score = trend_score + momentum_score + pattern_score
    elif model in ("buy_stock", "buy", "aggressive", "extreme_breakout"):
        open_f = float(curr["Open"]) if pd.notna(curr.get("Open")) else None
        sma20_f = float(curr["SMA20"]) if pd.notna(curr.get("SMA20")) else None
        macd_line_f = float(curr["MACD_Line"]) if pd.notna(curr.get("MACD_Line")) else None
        rs_p = _buy_rs_points(rs20_f)
        rv_p = _buy_rvol_points(rvol_f, close_f, open_f, sma20_f)
        ad_p = _buy_adx_points(adx, slope, close_f, vwap_f)
        dmi_p = _dmi_points(pdi, mdi)
        mfi_p = _mfi_points(mfi_f)
        mc_p = _buy_macd_points(
            float(mh) if mh is not None and pd.notna(mh) else None,
            float(mhp) if mhp is not None and pd.notna(mhp) else None,
            macd_line_f,
        )
        vwap_ext = _vwap_extended(close_f, vwap_f)
        raw_pattern = float(rv_p) - (float(rv_p) if vwap_ext else 0.0)
        trend_score = min(50.0, max(0.0, rs_p + ad_p + dmi_p))
        momentum_score = min(30.0, max(0.0, mc_p + mfi_p))
        pattern_score = max(0.0, min(20.0, raw_pattern))
        total_score = trend_score + momentum_score + pattern_score
    else:
        rs_p = _rs_points(rs20_f)
        ad_p = _adx_points(adx)
        dmi_p = _dmi_points(pdi, mdi)
        trend_score = min(50.0, max(0.0, rs_p + ad_p + dmi_p))
        mc_p = _macd_points(
            float(mh) if mh is not None and pd.notna(mh) else None,
            float(mhp) if mhp is not None and pd.notna(mhp) else None,
        )
        mfi_p = _mfi_points(mfi_f)
        momentum_score = min(30.0, max(0.0, mc_p + mfi_p))
        pattern_score = _rvol_points(rvol_f)
        if _vwap_extended(close_f, vwap_f):
            pattern_score = 0.0
        pattern_score = min(20.0, max(0.0, pattern_score))
        total_score = trend_score + momentum_score + pattern_score

    return int(round(min(100.0, max(0.0, total_score))))


def _trading_day_score_arc(df: pd.DataFrame, score_model: str) -> dict:
    """Last 3 trading sessions' scores from one OHLCV series (no multi-day export needed)."""
    n = len(df)
    out: dict = {}
    if n < MIN_OHLCV_BARS:
        return out
    indices = [n - 3, n - 2, n - 1]
    scores: list[int | None] = []
    dates: list[str | None] = []
    for bi in indices:
        if bi < 2:
            scores.append(None)
            dates.append(None)
            continue
        sc = _tech_score_from_bar(df, bi, score_model)
        scores.append(sc)
        try:
            dates.append(pd.Timestamp(df.index[bi]).strftime("%Y-%m-%d"))
        except Exception:
            dates.append(None)
    d2, d1, cur = (scores + [None, None, None])[:3]
    label, pattern = _classify_score_arc(d2, d1, cur)
    out["tech_score_d2"] = d2
    out["tech_score_d1"] = d1
    out["score_arc"] = _format_score_arc(d2, d1, cur)
    out["score_arc_label"] = label
    out["score_arc_pattern"] = pattern
    out["score_d2_trade_date"] = dates[0] if len(dates) > 0 else None
    out["score_d1_trade_date"] = dates[1] if len(dates) > 1 else None
    out["score_today_trade_date"] = dates[2] if len(dates) > 2 else None
    if cur is not None and d1 is not None:
        out["tech_score_delta"] = int(cur) - int(d1)
    return out


def technical_universe_row(ticker: str, *, period: str = "6mo", score_model: str = "sell_put") -> dict:
    """
    One row per symbol: always returns a dict (no None) for SSG / greedy dashboards.
    Includes tech_score and AI-style strategy text (rule-based, JSON-serializable).
    """
    err: dict = {
        "Ticker": ticker,
        "Price": "N/A",
        "Signal": "NO DATA",
        "Why": "fetch_failed",
        "scan_mode": "universe",
        "tech_score": None,
        "RVOL": "—",
        "ADX": "—",
        "adx_strength": "—",
        "macd_histogram_status": "—",
        "MACD_Hist": "—",
        "MACD_Hist_Prev": "—",
        "MACD_Sign": "N/A",
        "RS_20d": "—",
        "VWAP": "—",
        "RSI": "—",
        "ai_strategy_comment": "無法取得報價或歷史不足（Yahoo 日線不足約 28 根，或報價源暫無資料）。",
        "data_ok": False,
        "HS_Index": hk_index_membership(ticker),
    }
    try:
        df = get_indicator_df(ticker, period=period)
        if df is None or len(df) < MIN_OHLCV_BARS:
            return err
        curr = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else None
        adx = float(curr["ADX"]) if pd.notna(curr.get("ADX")) else None
        pdi = float(curr["PDI"]) if pd.notna(curr.get("PDI")) else None
        mdi = float(curr["MDI"]) if pd.notna(curr.get("MDI")) else None
        if adx is None or pdi is None or mdi is None:
            return err

        adx_prev = curr.get("ADX_prev")
        slope = float(adx - adx_prev) if pd.notna(adx_prev) else 0.0

        rvol_f = float(curr["RVOL"]) if pd.notna(curr.get("RVOL")) else None
        rs20_f = float(curr["RS_20d_Outperform"]) if pd.notna(curr.get("RS_20d_Outperform")) else None
        mfi_f = float(curr["MFI"]) if pd.notna(curr.get("MFI")) else None
        vwap_f = float(curr["VWAP"]) if pd.notna(curr.get("VWAP")) else None
        close_f = float(curr["Close"]) if pd.notna(curr.get("Close")) else None
        mh = curr.get("MACD_Hist")
        mhp = curr.get("MACD_Hist_Prev")

        model = str(score_model or "sell_put").strip().lower()

        if model in ("buy_put", "bear_put", "short_put", "panic_breakdown"):
            rs_p = _buy_put_rs_points(rs20_f)
            ad_p = _buy_put_adx_linear(adx)
            dmi_p = _buy_put_dmi_bear_points(pdi, mdi)
            raw_trend = rs_p + ad_p + dmi_p
            trend_score = min(50.0, max(0.0, raw_trend))
            mc_p = _buy_put_macd_points(
                float(mh) if mh is not None and pd.notna(mh) else None,
                float(mhp) if mhp is not None and pd.notna(mhp) else None,
            )
            mfi_p = _buy_put_mfi_points(mfi_f)
            raw_momentum = mc_p + mfi_p
            momentum_score = min(30.0, max(0.0, raw_momentum))
            rvol_raw = (
                min(20.0, float(rvol_f) * 10.0)
                if rvol_f is not None and not (isinstance(rvol_f, float) and math.isnan(rvol_f))
                else 0.0
            )
            vwap_pen = 0.0
            if (
                close_f is not None
                and vwap_f is not None
                and pd.notna(close_f)
                and pd.notna(vwap_f)
                and float(close_f) > float(vwap_f)
            ):
                vwap_pen = 20.0
            rv_p = rvol_raw
            raw_pattern = rvol_raw - vwap_pen
            pattern_score = max(0.0, min(20.0, raw_pattern))
            total_score = trend_score + momentum_score + pattern_score
            model_name = "buy_put"
            trading_mode_name = "恐慌破底 (Buy Put / Short)"
        elif model in ("buy_stock", "buy", "aggressive", "extreme_breakout"):
            open_f = float(curr["Open"]) if pd.notna(curr.get("Open")) else None
            sma20_f = float(curr["SMA20"]) if pd.notna(curr.get("SMA20")) else None
            macd_line_f = float(curr["MACD_Line"]) if pd.notna(curr.get("MACD_Line")) else None
            rs_p = _buy_rs_points(rs20_f)
            rv_p = _buy_rvol_points(rvol_f, close_f, open_f, sma20_f)
            ad_p = _buy_adx_points(adx, slope, close_f, vwap_f)
            dmi_p = _dmi_points(pdi, mdi)
            mfi_p = _mfi_points(mfi_f)
            mc_p = _buy_macd_points(
                float(mh) if mh is not None and pd.notna(mh) else None,
                float(mhp) if mhp is not None and pd.notna(mhp) else None,
                macd_line_f,
            )
            # Same 50 / 30 / 20 bucket caps as sell_put: raw sums can exceed limits from aggressive rubrics.
            vwap_ext = _vwap_extended(close_f, vwap_f)
            vwap_penalty = float(rv_p) if vwap_ext else 0.0
            raw_pattern = float(rv_p) - vwap_penalty
            raw_trend = rs_p + ad_p + dmi_p
            trend_score = min(50.0, max(0.0, raw_trend))
            raw_momentum = mc_p + mfi_p
            momentum_score = min(30.0, max(0.0, raw_momentum))
            pattern_score = max(0.0, min(20.0, raw_pattern))
            total_score = trend_score + momentum_score + pattern_score
            # Breakdown for 規則引擎摘要: capped buckets sum to total_score; rs/ad/dmi/macd/mfi/rvol are raw rubric points.
            model_name = "buy_stock"
            trading_mode_name = "極限爆發 (Buy Stock/Call)"
        else:
            # Sell Put 穩健收租模式
            rs_p = _rs_points(rs20_f)
            ad_p = _adx_points(adx)
            dmi_p = _dmi_points(pdi, mdi)
            trend_score = min(50.0, max(0.0, rs_p + ad_p + dmi_p))
            mc_p = _macd_points(
                float(mh) if mh is not None and pd.notna(mh) else None,
                float(mhp) if mhp is not None and pd.notna(mhp) else None,
            )
            mfi_p = _mfi_points(mfi_f)
            momentum_score = min(30.0, max(0.0, mc_p + mfi_p))
            rv_p = _rvol_points(rvol_f)
            pattern_score = rv_p
            if _vwap_extended(close_f, vwap_f):
                pattern_score = 0.0
            pattern_score = min(20.0, max(0.0, pattern_score))
            total_score = trend_score + momentum_score + pattern_score
            model_name = "sell_put"
            trading_mode_name = "穩健收租 (Sell Put)"

        raw = int(round(min(100.0, max(0.0, total_score))))
        macd_lbl = macd_histogram_status(curr)
        adx_lbl = adx_strength_label(adx, slope)
        band = _signal_band_from_score(raw, trading_mode_name)
        strat = _rule_based_ai_strategy(
            ticker=ticker,
            score=raw,
            band=band,
            rvol=rvol_f,
            adx_lbl=adx_lbl,
            macd_lbl=macd_lbl,
            pdi=pdi,
            mdi=mdi,
            trading_mode=trading_mode_name,
        )
        prev_close = float(prev["Close"]) if prev is not None else close_f
        daily_return = ((close_f - prev_close) / prev_close * 100.0) if prev_close else 0.0

        def _fmt_hist(x) -> str:
            if x is None or pd.isna(x):
                return "—"
            return f"{float(x):.4f}"

        if model_name == "buy_put":
            vwap_above_y = (
                close_f is not None
                and vwap_f is not None
                and pd.notna(close_f)
                and pd.notna(vwap_f)
                and float(close_f) > float(vwap_f)
            )
            _why_pattern = (
                f"pattern={pattern_score:.1f}(rvol={rv_p:.1f},vwap_pen={vwap_pen:.0f},vwap_above={'Y' if vwap_above_y else 'N'})"
            )
        else:
            _why_pattern = (
                f"pattern={pattern_score:.1f}(rvol={rv_p:.1f},vwap_ext={'Y' if _vwap_extended(close_f, vwap_f) else 'N'})"
            )
        _why = (
            f"score={raw};model={model_name};trend={trend_score:.1f}(rs={rs_p:.1f},adx={ad_p:.1f},dmi={dmi_p:.1f});"
            f"momentum={momentum_score:.1f}(macd={mc_p:.1f},mfi={mfi_p:.1f});"
            f"{_why_pattern};macd={macd_lbl};adx={adx_lbl}"
        )

        arc_fields = _trading_day_score_arc(df, model)
        vwap_ext_flag = "Y" if _vwap_extended(close_f, vwap_f) else "N"
        row_out = {
            "Ticker": ticker,
            "Price": f"{close_f:.2f}",
            "Close": f"{close_f:.2f}",
            "Signal": band,
            "Why": _why,
            "vwap_ext": vwap_ext_flag,
            "tech_score": raw,
            "score_model": model_name,
            "scan_mode": "universe",
            "RVOL": f"{rvol_f:.2f}" if rvol_f is not None else "—",
            "ADX": f"{adx:.1f}",
            "ATR": f"{float(curr['ATR']):.4f}" if pd.notna(curr.get("ATR")) else "—",
            "ADX_Slope": f"{slope:.2f}",
            "PDI": f"{pdi:.1f}",
            "MDI": f"{mdi:.1f}",
            "DMI_Gap": f"{(pdi - mdi):.1f}",
            "RSI": f"{float(curr['RSI']):.1f}" if pd.notna(curr.get("RSI")) else "—",
            "MFI": f"{float(curr['MFI']):.1f}" if pd.notna(curr.get("MFI")) else "—",
            "MACD_Hist": _fmt_hist(mh),
            "MACD_Hist_Prev": _fmt_hist(mhp),
            "MACD_Sign": macd_sign_label(float(mh) if mh is not None and pd.notna(mh) else None),
            "RS_20d": f"{rs20_f:.2f}%" if rs20_f is not None else "—",
            "VWAP": f"{vwap_f:.2f}" if vwap_f is not None else "—",
            "adx_strength": adx_lbl,
            "macd_histogram_status": macd_lbl,
            "ai_strategy_comment": strat,
            "daily_return": round(daily_return, 2),
            "data_ok": True,
            "HS_Index": hk_index_membership(ticker),
        }
        sn = stock_name_for_ticker(ticker)
        if sn:
            row_out["stock_name"] = sn
        row_out.update(arc_fields)
        return row_out
    except Exception:
        return err


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


def _stoch_extras_pass(
    sk, sd, sk_prev, sd_prev,
    require_k_gt_d: bool,
    k_vs_prev_op: str,
    d_vs_prev_op: str,
    d_op: str,
    d_val: float,
) -> bool:
    """Extra stochastic rules: K>D, K vs prior K, D vs prior D, D vs level."""
    if require_k_gt_d:
        if sk is None or sd is None or pd.isna(sk) or pd.isna(sd):
            return False
        if not (float(sk) > float(sd)):
            return False
    if not _check_op(
        float(sk) if sk is not None and not pd.isna(sk) else None,
        float(sk_prev) if sk_prev is not None and not pd.isna(sk_prev) else None,
        k_vs_prev_op,
    ):
        return False
    if not _check_op(
        float(sd) if sd is not None and not pd.isna(sd) else None,
        float(sd_prev) if sd_prev is not None and not pd.isna(sd_prev) else None,
        d_vs_prev_op,
    ):
        return False
    if not _check_op(
        float(sd) if sd is not None and not pd.isna(sd) else None,
        float(d_val),
        d_op,
    ):
        return False
    return True


def analyze_stock(
    ticker: str,
    *,
    period: str = "6mo",
    close_vs_sma20: str = "off",
    close_vs_sma50: str = "off",
    obv_vs_obv_ema20: str = "off",
    obv_vs_obv_5ma: str = "off",
    close_vs_vwap: str = "off",
    mfi_vs_rsi: str = "off",
    rsi_op: str = "off",
    rsi_value: float = 50.0,
    rs_20d_op: str = "off",
    rs_20d_value: float = 0.0,
    mfi_op: str = "off",
    mfi_value: float = 55.0,
    rvol_op: str = "off",
    rvol_value: float = 1.0,
    adx_slope_op: str = "off",
    gap_op: str = "off",
    gap_value: float = 0.0,
    stoch_k_op: str = "off",
    stoch_k_value: float = 80.0,
    stoch_require_k_gt_d: bool = False,
    stoch_k_vs_prev_op: str = "off",
    stoch_d_vs_prev_op: str = "off",
    stoch_d_op: str = "off",
    stoch_d_value: float = 50.0,
    spread_op: str = "off",
    spread_value: float = 0.0,
    core_require_pdi_mdi: bool = True,
    pdi_buffer: float = 0.0,
    adx_min: int = 20,
    adx_max: int = 50,
    core_require_adx_awakening: bool = False,
    rsi_profit_take: int = 75,
    sell_use_sma20: bool = True,
    sell_use_pdi_mdi: bool = True,
    sell_use_adx_exhaustion: bool = False,
    sell_use_profit_take: bool = True,
    strategy_mode: str = "",
) -> dict | None:
    """
    One stock: download 6mo, compute indicators with ta library, apply Veteran v4.0.
    Returns a result dict if there is an actionable signal, else None.
    All criteria params are optional; defaults match Veteran v4.0.
    """
    try:
        df = _fetch_ohlcv(ticker, period=period)
        if df is None or len(df) < MIN_OHLCV_BARS:
            return None

        h, l, c, v = df["High"], df["Low"], df["Close"], df["Volume"]

        # Indicators using ta library (no pandas_ta / numba)
        df["SMA20"] = SMAIndicator(close=c, window=20).sma_indicator()
        df["SMA_50"] = SMAIndicator(close=c, window=50).sma_indicator()
        df["RSI"] = RSIIndicator(close=c, window=14).rsi()
        df["MFI"] = MFIIndicator(high=h, low=l, close=c, volume=v, window=14).money_flow_index()
        adx_ind = ADXIndicator(high=h, low=l, close=c, window=14)
        df["ADX"] = adx_ind.adx()
        df["PDI"] = adx_ind.adx_pos()   # +DI
        df["MDI"] = adx_ind.adx_neg()   # -DI
        vol_sma = v.rolling(window=20, min_periods=1).mean().replace(0, float("nan"))
        df["RVOL"] = v / vol_sma
        df["Spread"] = df["MFI"] - df["RSI"]
        df["EMA_12"] = c.ewm(span=12, adjust=False).mean()
        df["EMA_26"] = c.ewm(span=26, adjust=False).mean()
        df["MACD_Line"] = df["EMA_12"] - df["EMA_26"]
        df["MACD_Signal"] = df["MACD_Line"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD_Line"] - df["MACD_Signal"]
        df["MACD_Hist_Prev"] = df["MACD_Hist"].shift(1)
        df["ADX_prev"] = df["ADX"].shift(1)
        df["ADX_prev2"] = df["ADX"].shift(2)
        # OBV: if Close > prev Close add Volume, else subtract
        diff = c.diff()
        obv_direction = (diff > 0).astype(float) - (diff < 0).astype(float)
        df["OBV"] = (obv_direction.fillna(0) * v).cumsum()
        df["OBV_EMA_20"] = df["OBV"].ewm(span=20, adjust=False).mean()
        df["OBV_5MA"] = df["OBV"].rolling(window=5).mean()
        # Stochastic %K / %D (14,3)
        try:
            stoch = StochasticOscillator(high=df["High"], low=df["Low"], close=df["Close"], window=14, smooth_window=3)
            df["Stoch_K"] = stoch.stoch()
            df["Stoch_D"] = stoch.stoch_signal()
        except Exception:
            df["Stoch_K"] = float("nan")
            df["Stoch_D"] = float("nan")
        df["Stoch_K_prev"] = df["Stoch_K"].shift(1)
        df["Stoch_D_prev"] = df["Stoch_D"].shift(1)
        # VWAP: 20-day rolling (Typical Price * Volume) / Volume, Typical = (H+L+C)/3
        typical = (h + l + c) / 3
        df["VWAP"] = (typical * v).rolling(window=20, min_periods=20).sum() / v.rolling(window=20, min_periods=20).sum()

        # Comparative RS vs benchmark (^HSI for HK, ^GSPC for others)
        try:
            benchmark_ticker = "^HSI" if ".HK" in ticker.upper() else "^GSPC"
            start_date, end_date = df.index.min(), df.index.max()
            bench = yf.download(benchmark_ticker, start=start_date, end=end_date, auto_adjust=False, progress=False)
            if not bench.empty:
                if isinstance(bench.columns, pd.MultiIndex):
                    bench.columns = [col[0] if isinstance(col, tuple) else col for col in bench.columns]
                bench_close = bench["Close"] if "Close" in bench.columns else bench.iloc[:, 0]
                bench_close.index = pd.to_datetime(bench_close.index).normalize()
                aligned = bench_close.reindex(df.index, method="ffill")
                df["Benchmark_Close"] = aligned.values
                df["RS_Line"] = df["Close"] / df["Benchmark_Close"].replace(0, float("nan"))
                df["RS_20d_Outperform"] = (df["RS_Line"] / df["RS_Line"].shift(20) - 1) * 100
        except Exception:
            pass

        curr = df.iloc[-1]
        adx = float(curr["ADX"]) if pd.notna(curr["ADX"]) else None
        pdi = float(curr["PDI"]) if pd.notna(curr["PDI"]) else None
        mdi = float(curr["MDI"]) if pd.notna(curr["MDI"]) else None
        if adx is None or pdi is None or mdi is None:
            return None

        # CORE (all enabled criteria must pass)
        close_f = float(curr["Close"])
        sma20_f = float(curr["SMA20"]) if pd.notna(curr.get("SMA20")) else None
        sma50_f = float(curr["SMA_50"]) if pd.notna(curr.get("SMA_50")) else None
        obv_f = float(curr["OBV"]) if pd.notna(curr.get("OBV")) else None
        obv_ema_f = float(curr["OBV_EMA_20"]) if pd.notna(curr.get("OBV_EMA_20")) else None
        vwap_f = float(curr["VWAP"]) if pd.notna(curr.get("VWAP")) else None
        rsi_f = float(curr["RSI"]) if pd.notna(curr.get("RSI")) else None
        mfi_f = float(curr["MFI"]) if pd.notna(curr.get("MFI")) else None
        rvol_f = float(curr["RVOL"]) if pd.notna(curr.get("RVOL")) else None
        rs_20d_f = float(curr["RS_20d_Outperform"]) if pd.notna(curr.get("RS_20d_Outperform")) else None
        obv_5ma_f = float(curr["OBV_5MA"]) if pd.notna(curr.get("OBV_5MA")) else None
        stoch_k_f = float(curr["Stoch_K"]) if pd.notna(curr.get("Stoch_K")) else None
        stoch_d_f = float(curr["Stoch_D"]) if pd.notna(curr.get("Stoch_D")) else None
        stoch_k_prev_f = float(curr["Stoch_K_prev"]) if pd.notna(curr.get("Stoch_K_prev")) else None
        stoch_d_prev_f = float(curr["Stoch_D_prev"]) if pd.notna(curr.get("Stoch_D_prev")) else None
        prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else None
        daily_return = ((close_f - prev_close) / prev_close * 100.0) if prev_close and prev_close != 0 else 0.0

        gap = (pdi - mdi) if (pdi is not None and mdi is not None) else 0.0
        slope_curr = float(adx - curr.get("ADX_prev")) if pd.notna(curr.get("ADX_prev")) else 0.0
        spread_val = curr.get("Spread")

        # Quant strategy override: if one of the 4 elite modes is set, use that condition only (BUY or skip)
        if strategy_mode in (
            "trend_confirmation",
            "capitulation",
            "pullback",
            "rs_breakout",
            "macd_breakout",
            "reversal_breakout",
        ):
            match_strategy = False
            if strategy_mode == "trend_confirmation":
                if gap > 15 and adx > 25 and slope_curr > 0 and close_f > (vwap_f or 0):
                    match_strategy = True
            elif strategy_mode == "capitulation":
                # Align with Veteran preset: RSI > MFI (`rsi>mfi`), not MFI > RSI
                if (rsi_f is not None and rsi_f < 35 and mfi_f is not None and rsi_f > mfi_f
                        and rvol_f is not None and rvol_f > 1.5 and sma20_f is not None and close_f < sma20_f):
                    match_strategy = True
            elif strategy_mode == "pullback":
                if (sma20_f is not None and vwap_f is not None and sma20_f < close_f < vwap_f
                        and rvol_f is not None and rvol_f < 1.0 and gap > 10
                        and (stoch_k_f is None or stoch_k_f < 80)):
                    match_strategy = True
            elif strategy_mode == "rs_breakout":
                if (rs_20d_f is not None and rs_20d_f > 5.0
                        and obv_f is not None and obv_5ma_f is not None and obv_f > obv_5ma_f
                        and slope_curr > 0):
                    match_strategy = True
            elif strategy_mode == "macd_breakout":
                mh = curr.get("MACD_Hist")
                mhp = curr.get("MACD_Hist_Prev")
                if (mh is not None and mhp is not None and pd.notna(mh) and pd.notna(mhp)
                        and float(mh) > 0.0 and float(mhp) <= 0.0
                        and rvol_f is not None and rvol_f >= 1.0):
                    match_strategy = True
            elif strategy_mode == "reversal_breakout":
                mh = curr.get("MACD_Hist")
                mhp = curr.get("MACD_Hist_Prev")
                sk = curr.get("Stoch_K")
                sd = curr.get("Stoch_D")
                if (mh is not None and mhp is not None and pd.notna(mh) and pd.notna(mhp)
                        and float(mh) > float(mhp)
                        and sma20_f is not None and close_f > sma20_f
                        and rvol_f is not None and rvol_f > 1.2):
                    rsi_ok_rb = rsi_f is not None and rsi_f > 40.0
                    stoch_ok_rb = (
                        sk is not None and sd is not None and pd.notna(sk) and pd.notna(sd)
                        and float(sk) > float(sd)
                    )
                    if rsi_ok_rb and stoch_ok_rb:
                        match_strategy = True
            if not match_strategy:
                return None
            signal = "BUY"
            details = {
                "trend_confirmation": "推土機起步",
                "capitulation": "地牢撈底",
                "pullback": "良性回抽",
                "rs_breakout": "RS破位領頭羊",
                "macd_breakout": "MACD 動能爆發",
                "reversal_breakout": "絕地反擊",
            }[strategy_mode]
            details = [details]
        else:
            close_sma20_ok = _check_op(close_f, sma20_f, close_vs_sma20)
            close_sma50_ok = _check_op(close_f, sma50_f, close_vs_sma50)
            obv_ok = _check_op(obv_f, obv_ema_f, obv_vs_obv_ema20)
            obv_5ma_ok = _check_op(obv_f, obv_5ma_f, obv_vs_obv_5ma)
            close_vwap_ok = _check_op(close_f, vwap_f, close_vs_vwap)
            adx_ok = adx_min < adx < adx_max
            pdi_ok = (not core_require_pdi_mdi) or (pdi > mdi + float(pdi_buffer))
            adx_prev = curr.get("ADX_prev")
            adx_prev2 = curr.get("ADX_prev2")
            slope_curr = float(adx - adx_prev) if pd.notna(adx_prev) else 0.0
            slope_prev = float(adx_prev - adx_prev2) if pd.notna(adx_prev) and pd.notna(adx_prev2) else 0.0
            adx_awakening = (slope_prev <= 0 and slope_curr > 0) if core_require_adx_awakening else True
            mfi_rsi_ok = True
            if mfi_vs_rsi == "mfi>rsi" and rsi_f is not None and mfi_f is not None:
                mfi_rsi_ok = mfi_f > rsi_f
            elif mfi_vs_rsi == "rsi>mfi" and rsi_f is not None and mfi_f is not None:
                mfi_rsi_ok = rsi_f > mfi_f
            rsi_ok = _check_op(rsi_f, float(rsi_value), rsi_op)
            rs_20d_ok = _check_op(rs_20d_f, float(rs_20d_value), rs_20d_op)
            mfi_ok = _check_op(mfi_f, float(mfi_value), mfi_op)
            rvol_ok = _check_op(rvol_f, float(rvol_value), rvol_op)
            adx_slope_ok = _check_op(slope_curr, 0.0, adx_slope_op)
            gap_ok = _check_op(gap, float(gap_value), gap_op)
            stoch_k_ok = _check_op(stoch_k_f, float(stoch_k_value), stoch_k_op)
            stoch_x_ok = _stoch_extras_pass(
                stoch_k_f,
                stoch_d_f,
                stoch_k_prev_f,
                stoch_d_prev_f,
                stoch_require_k_gt_d,
                stoch_k_vs_prev_op,
                stoch_d_vs_prev_op,
                stoch_d_op,
                float(stoch_d_value),
            )
            spread_ok = _check_op(float(spread_val) if pd.notna(spread_val) else None, float(spread_value), spread_op)

            core_pass = (close_sma20_ok and close_sma50_ok and obv_ok and obv_5ma_ok and close_vwap_ok and adx_ok and pdi_ok
                         and adx_awakening and mfi_rsi_ok and rsi_ok and rs_20d_ok and mfi_ok and rvol_ok and adx_slope_ok)
            core_pass = core_pass and gap_ok and stoch_k_ok and stoch_x_ok and spread_ok

            details = []
            signal = None
            close_curr = close_f
            open_curr = float(curr["Open"])
            sma20_curr = sma20_f or 0

            if core_pass:
                signal = "BUY"
                details = ["Core"]
            elif sell_use_profit_take and close_curr > sma20_curr and float(curr["RSI"]) > rsi_profit_take and close_curr < open_curr:
                signal = "PROFIT TAKE"
                details = [f"RSI>{rsi_profit_take}", "Bearish"]
            elif sell_use_adx_exhaustion and slope_prev >= 0 and slope_curr < 0:
                signal = "SELL (強弩之末)"
                details = ["ADX Exhaustion"]
            elif sell_use_sma20 and close_curr < sma20_curr:
                signal = "SELL (Trend Break)"
                details = ["Close<SMA20"]
            elif sell_use_pdi_mdi and pdi < mdi:
                signal = "SELL (Momentum Flip)"
                details = ["PDI<MDI"]

        if signal:
            rvol_str = f"{curr['RVOL']:.2f}" if pd.notna(curr.get("RVOL")) else "—"
            mfi_str = f"{curr['MFI']:.1f}" if pd.notna(curr.get("MFI")) else "—"
            sma50_str = f"{curr['SMA_50']:.2f}" if pd.notna(curr.get("SMA_50")) else "—"
            obv_str = f"{curr['OBV']:,.0f}" if pd.notna(curr.get("OBV")) else "—"
            obv_ema_str = f"{curr['OBV_EMA_20']:,.0f}" if pd.notna(curr.get("OBV_EMA_20")) else "—"
            vwap_str = f"{curr['VWAP']:.2f}" if pd.notna(curr.get("VWAP")) else "—"
            rs_val = curr.get("RS_20d_Outperform")
            rs_str = f"{float(rs_val):.2f}%" if pd.notna(rs_val) and rs_val is not None else "—"
            is_distribution = (rvol_f is not None and rvol_f > 2.5 and daily_return <= 0.5)
            _mh = curr.get("MACD_Hist")
            _mhp = curr.get("MACD_Hist_Prev")
            _mln = curr.get("MACD_Line")
            _msn = curr.get("MACD_Signal")
            macd_hist_str = f"{float(_mh):.4f}" if _mh is not None and pd.notna(_mh) else "—"
            macd_hist_prev_str = f"{float(_mhp):.4f}" if _mhp is not None and pd.notna(_mhp) else "—"
            macd_line_str = f"{float(_mln):.4f}" if _mln is not None and pd.notna(_mln) else "—"
            macd_sig_str = f"{float(_msn):.4f}" if _msn is not None and pd.notna(_msn) else "—"
            _skv = curr.get("Stoch_K")
            _sdv = curr.get("Stoch_D")
            stoch_k_str = f"{float(_skv):.1f}" if _skv is not None and pd.notna(_skv) else "—"
            stoch_d_str = f"{float(_sdv):.1f}" if _sdv is not None and pd.notna(_sdv) else "—"
            return {
                "Ticker": ticker,
                "Price": f"{curr['Close']:.2f}",
                "Signal": signal,
                "Why": ",".join(details),
                "ADX": f"{adx:.1f}",
                "ADX_Slope": f"{slope_curr:.2f}",
                "PDI": f"{pdi:.1f}",
                "MDI": f"{mdi:.1f}",
                "RSI": f"{curr['RSI']:.1f}",
                "MFI": mfi_str,
                "RVOL": rvol_str,
                "RS_20d": rs_str,
                "Spread": f"{float(spread_val):.1f}" if pd.notna(spread_val) else "—",
                "SMA_50": sma50_str,
                "OBV": obv_str,
                "OBV_EMA_20": obv_ema_str,
                "VWAP": vwap_str,
                "MACD_Line": macd_line_str,
                "MACD_Signal": macd_sig_str,
                "MACD_Hist": macd_hist_str,
                "MACD_Hist_Prev": macd_hist_prev_str,
                "Stoch_K": stoch_k_str,
                "Stoch_D": stoch_d_str,
                "daily_return": round(daily_return, 2),
                "Distribution_Warning": is_distribution,
                "HS_Index": hk_index_membership(ticker),
            }
    except Exception:
        return None
    return None


# --- 3. SCANNER ENGINE ---
def _run_scan_with_tickers(tickers: list, label: str) -> None:
    """Run scan over a given list of tickers and print results."""
    print(f"\n  Veteran v4.0 — {label} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 85)
    if not tickers:
        print(" No tickers to scan.")
        print("=" * 85)
        return
    print(" Scanning...", end="", flush=True)
    results = []
    for i, t in enumerate(tickers):
        res = analyze_stock(t)
        if res:
            results.append(res)
        print(".", end="", flush=True)
        if i < len(tickers) - 1:
            time.sleep(0.25)
    print(" done.\n" + "=" * 85)
    if results:
        print(f" {'Ticker':<8} {'Price':<8} {'Signal':<18} {'Why':<12} {'ADX':<5} {'Slope':<6} {'PDI':<5} {'MDI':<5} {'RSI':<5} {'MFI':<5} {'RVOL':<5}")
        print("-" * 100)
        for r in results:
            sig = r["Signal"]
            icon = "🟢" if "BUY" in sig else ("🔴" if "SELL" in sig else "🟠")
            adx_slope = r.get("ADX_Slope", "—")
            pdi = r.get("PDI", "—")
            mdi = r.get("MDI", "—")
            mfi = r.get("MFI", "—")
            print(f"{icon} {r['Ticker']:<6} {r['Price']:<8} {r['Signal']:<18} {r['Why']:<12} {r['ADX']:<5} {adx_slope:<6} {pdi:<5} {mdi:<5} {r['RSI']:<5} {mfi:<5} {r['RVOL']:<5}")
    else:
        print(" No actionable signals today. Stay cash.")
    print("=" * 85)


def run_scan(market: str) -> None:
    """Run full scan for a market (HK or US) and print results."""
    print(f" Fetching {market} tickers...", end="", flush=True)
    tickers = get_tickers(market)
    _run_scan_with_tickers(tickers, market)


# --- 4. SCHEDULER ---
def job_hk() -> None:
    print(" Waking for HK scan...")
    run_scan("HK")


def job_us() -> None:
    print(" Waking for US scan...")
    run_scan("US")


def main() -> None:
    # sys.argv[0] = script name; [1:] = user args
    if len(sys.argv) > 1:
        args = [a.strip() for a in sys.argv[1:] if a.strip()]
        # Single arg: use that list
        if len(args) == 1:
            a = args[0].upper()
            if a in ("HK", "TECH", "HSI", "HKCEI", "US"):
                run_scan(a)
                return
        # Otherwise treat all args as custom tickers
        tickers = args
        print(f" Custom scan requested: {tickers}")
        _run_scan_with_tickers(tickers, "Custom")
        return

    # No args: use default list and run once
    print(f" Default scan mode: {len(DEFAULT_TICKERS)} stocks")
    _run_scan_with_tickers(DEFAULT_TICKERS.copy(), "Default")
    return

    # Uncomment below to run scheduler when no args (and comment out the two lines above)
    # schedule.every().day.at("17:00").do(job_hk)
    # schedule.every().day.at("08:30").do(job_us)
    # print(" Veteran Scanner ONLINE. Waiting for schedule (17:00 HK, 08:30 US). Ctrl+C to stop.")
    # while True:
    #     schedule.run_pending()
    #     time.sleep(60)


if __name__ == "__main__":
    main()
