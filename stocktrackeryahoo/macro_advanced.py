"""
Rich macro snapshot (same logic as Stock Analysis ``get_advanced_macro``), without Streamlit.
Used by streamlit_app (cached) and by ``export_macro_snapshot_to_json`` for the static site.
"""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


def _norm_hk_ticker_yahoo(code: int) -> str:
    """Map numeric HKEX code to Yahoo .HK (same 4-digit convention as daily_scanner)."""
    sym = f"{code:04d}.HK" if code < 100_000 else f"{code}.HK"
    s = sym.strip().upper()
    if not s.endswith(".HK"):
        return s
    prefix = s[:-3]
    if len(prefix) == 5 and prefix.startswith("0"):
        return prefix[1:] + ".HK"
    return s


def load_hk_breadth_universe_csv(path: str | Path) -> list[str]:
    """CSV: first column numeric HK code (e.g. 700), optional header 代碼."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[str] = []
    try:
        with p.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or not str(row[0]).strip():
                    continue
                a = str(row[0]).strip()
                if a.lower() in ("代碼", "code", "ticker", "symbol"):
                    continue
                try:
                    code = int(a, 10)
                except ValueError:
                    continue
                if code <= 0:
                    continue
                out.append(_norm_hk_ticker_yahoo(code))
    except OSError:
        return []
    return list(dict.fromkeys(out))


def load_us_breadth_universe_csv(path: str | Path) -> list[str]:
    """CSV: first column US ticker (e.g. NVDA); skip common header tokens."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[str] = []
    try:
        with p.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or not str(row[0]).strip():
                    continue
                t = str(row[0]).strip().upper()
                if t in ("TICKER", "SYMBOL", "CODE", "代碼"):
                    continue
                if not t.replace(".", "").replace("-", "").isalnum():
                    continue
                out.append(t)
    except OSError:
        return []
    return list(dict.fromkeys(out))


def _yf_price_series(df: pd.DataFrame, col: str) -> pd.Series:
    d = df
    if isinstance(d.columns, pd.MultiIndex):
        d = d.copy()
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    if col not in d.columns:
        raise KeyError(col)
    s = d[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return pd.to_numeric(s, errors="coerce").astype(float)


def _wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    c = close.astype(float)
    d = c.diff()
    gain = d.where(d > 0, 0.0)
    loss = (-d).where(d < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100.0 - (100.0 / (1.0 + rs))


def fetch_advanced_macro_data() -> dict:
    """
    Global macro snapshot: indices with ~1y history (SMA200, 52w high drawdown, RSI14)
    and commodities/FX with 5d history (latest vs prior close).
    Returns display keys -> dicts with float values (JSON-serializable).
    """
    macro_data: dict = {}

    indices = {
        "🇺🇸 S&P 500": "^GSPC",
        "🇺🇸 納斯達克 (Nasdaq)": "^IXIC",
        "🇭🇰 恒生指數 (HSI)": "^HSI",
        "🇨🇳 上證指數 (SSE)": "000001.SS",
        "⚡ VIX 恐慌指數": "^VIX",
    }
    for name, ticker in indices.items():
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if hist is None or len(hist) < 2:
                continue
            close = _yf_price_series(hist, "Close")
            current = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            change_pct = ((current - prev) / prev * 100.0) if prev else 0.0

            if ticker == "^VIX":
                macro_data[name] = {"current": current, "change_pct": change_pct}
                continue

            if len(hist) <= 200:
                macro_data[name] = {"current": current, "change_pct": change_pct}
                continue

            sma50 = float(close.rolling(window=50).mean().iloc[-1]) if len(close) >= 50 else float("nan")
            dist_sma50 = ((current - sma50) / sma50 * 100.0) if sma50 and sma50 == sma50 and sma50 != 0 else 0.0
            sma200 = float(close.rolling(window=200).mean().iloc[-1])
            dist_sma200 = ((current - sma200) / sma200 * 100.0) if sma200 else 0.0
            high_52w = float(_yf_price_series(hist, "High").max())
            drawdown_52w = ((current - high_52w) / high_52w * 100.0) if high_52w else 0.0

            rsi_series = _wilder_rsi(close, 14)
            rsi_val = rsi_series.iloc[-1]
            if pd.isna(rsi_val):
                rsi_val = 50.0
            else:
                rsi_val = max(0.0, min(100.0, float(rsi_val)))

            row = {
                "current": current,
                "change_pct": change_pct,
                "rsi": rsi_val,
                "dist_sma200": dist_sma200,
                "drawdown": drawdown_52w,
            }
            if len(close) >= 50 and sma50 == sma50:
                row["dist_sma50"] = dist_sma50
            macro_data[name] = row
        except Exception:
            pass

    def _fetch_ohlc_pair(ticker: str, invert: bool = False):
        for period in ("5d", "1mo", "3mo"):
            try:
                hist = yf.Ticker(ticker).history(period=period)
                if hist is None or len(hist) < 2:
                    continue
                cl = _yf_price_series(hist, "Close")
                cur = float(cl.iloc[-1])
                prev = float(cl.iloc[-2])
                if cur != cur or prev != prev:
                    continue
                if invert:
                    if cur == 0 or prev == 0:
                        continue
                    cur = 1.0 / cur
                    prev = 1.0 / prev
                chg = ((cur - prev) / prev * 100.0) if prev else 0.0
                return cur, chg
            except Exception:
                continue
        return None

    simple_assets = {"期油 (WTI)": "CL=F", "黃金 (Gold)": "GC=F"}
    for name, ticker in simple_assets.items():
        pair = _fetch_ohlc_pair(ticker)
        if pair:
            macro_data[name] = {"current": pair[0], "change_pct": pair[1]}

    for sym in ("DX-Y.NYB", "DX=F"):
        pair = _fetch_ohlc_pair(sym)
        if pair:
            macro_data["📈 美元指數 (DXY)"] = {"current": pair[0], "change_pct": pair[1], "source": sym}
            break

    pair = _fetch_ohlc_pair("BTC-USD")
    if pair:
        macro_data["₿ Bitcoin"] = {"current": pair[0], "change_pct": pair[1]}

    pair = _fetch_ohlc_pair("^TNX")
    if pair:
        macro_data["🇺🇸 10Y 國債息"] = {"current": pair[0], "change_pct": pair[1]}

    pair = _fetch_ohlc_pair("^FVX")
    if pair:
        macro_data["🇺🇸 5Y 國債息"] = {"current": pair[0], "change_pct": pair[1]}

    pair = _fetch_ohlc_pair("^IRX")
    if pair:
        macro_data["🇺🇸 3M 國債息"] = {"current": pair[0], "change_pct": pair[1]}

    pair = _fetch_ohlc_pair("USDHKD=X")
    if pair:
        macro_data["USD/HKD (美元/港幣)"] = {"current": pair[0], "change_pct": pair[1]}
    else:
        pair = _fetch_ohlc_pair("HKDUSD=X", invert=True)
        if pair:
            macro_data["USD/HKD (美元/港幣)"] = {"current": pair[0], "change_pct": pair[1]}

    return _sanitize_macro_dict(macro_data)


def _sanitize_macro_dict(data: dict) -> dict:
    """Drop NaN/Inf floats so macro_snapshot.json is valid in browsers."""
    import math

    out: dict = {}
    for name, row in (data or {}).items():
        if not isinstance(row, dict):
            out[name] = row
            continue
        clean: dict = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                continue
            clean[k] = v
        if clean:
            out[name] = clean
    return out


def _single_stock_ma_flags(ticker: str) -> dict[str, Any] | None:
    """Latest close vs SMA50 / SMA200 from ~1y daily history (Yahoo)."""
    try:
        hist = yf.Ticker(ticker).history(period="1y", auto_adjust=False)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        if isinstance(hist.columns, pd.MultiIndex):
            hist = hist.copy()
            hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
        cl = pd.to_numeric(hist["Close"], errors="coerce").astype(float).dropna()
        if len(cl) < 50:
            return None
        last = float(cl.iloc[-1])
        sma50 = float(cl.rolling(50).mean().iloc[-1])
        if not (sma50 == sma50) or sma50 == 0:
            return None
        above50 = last > sma50
        above200: bool | None = None
        if len(cl) >= 200:
            sma200 = float(cl.rolling(200).mean().iloc[-1])
            if sma200 == sma200 and sma200 != 0:
                above200 = last > sma200
        return {"above50": above50, "above200": above200}
    except Exception:
        return None


def _run_batch_ordered(tickers: list[str], *, max_workers: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Run fetches in parallel; return (rows in ticker order, tickers that returned data)."""
    if not tickers:
        return [], []
    results: dict[str, dict[str, Any] | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_single_stock_ma_flags, t): t for t in tickers}
        for fut in as_completed(futs):
            t = futs[fut]
            results[t] = fut.result()
    rows: list[dict[str, Any]] = []
    ok_syms: list[str] = []
    for t in tickers:
        r = results.get(t)
        if r:
            rows.append(r)
            ok_syms.append(t)
    return rows, ok_syms


def _summarize_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n50 = sum(1 for r in rows if r.get("above50") is not None)
    a50 = sum(1 for r in rows if r.get("above50") is True)
    n200 = sum(1 for r in rows if r.get("above200") is not None)
    a200 = sum(1 for r in rows if r.get("above200") is True)
    return {
        "sampled": len(rows),
        "denom_ma50": n50,
        "above_ma50_pct": (a50 / n50 * 100.0) if n50 else None,
        "denom_ma200": n200,
        "above_ma200_pct": (a200 / n200 * 100.0) if n200 else None,
        "label_ma50": "50日線（中期趨勢）",
        "label_ma200": "200日線（長線牛熊）",
    }


def _breadth_drop_warnings(tag_zh: str, prev_block: dict[str, Any] | None, cur_block: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if not prev_block or not cur_block:
        return out
    for key, label in (("above_ma50_pct", "50日線上方比例"), ("above_ma200_pct", "200日線上方比例")):
        p = prev_block.get(key)
        c = cur_block.get(key)
        if not isinstance(p, (int, float)) or not isinstance(c, (int, float)):
            continue
        if p != p or c != c:
            continue
        p, c = float(p), float(c)
        if p >= 90 and c <= 70:
            out.append(
                f"{tag_zh}：{label}由 {p:.0f}% 大幅跌至 {c:.0f}% — 即使指數未必跟跌，亦要警戒「大戶靜悄悄走貨」、市寬惡化。"
            )
        elif p >= 85 and (p - c) >= 15:
            out.append(
                f"{tag_zh}：{label}由 {p:.0f}% 跌至 {c:.0f}%（跌 {p - c:.0f} 個百分點）— 建議收緊注碼並留意是否失守整固區。"
            )
    return out


def compute_sampled_ma_breadth(
    hk_tickers: list[str],
    us_tickers: list[str],
    *,
    max_per_market: int | None = 85,
    max_workers: int = 10,
    prev_breadth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Sampled market breadth: % of names with last close above SMA50 / SMA200 (Yahoo ~1y daily).
    max_per_market=None uses the full ticker lists (e.g. custom CSV universes).
    """
    hk_clean = [str(t).strip().upper() for t in hk_tickers if str(t).strip()]
    us_clean = [str(t).strip().upper() for t in us_tickers if str(t).strip()]
    if max_per_market is not None:
        hk_list = hk_clean[: int(max_per_market)]
        us_list = us_clean[: int(max_per_market)]
    else:
        hk_list = hk_clean
        us_list = us_clean

    hk_rows, hk_ok = _run_batch_ordered(hk_list, max_workers=max_workers)
    us_rows, us_ok = _run_batch_ordered(us_list, max_workers=max_workers)
    hk_sum = _summarize_breadth(hk_rows)
    us_sum = _summarize_breadth(us_rows)
    hk_sum["market"] = "HK"
    hk_sum["title_zh"] = "港股（抽樣）"
    hk_sum["attempted"] = len(hk_list)
    hk_sum["tickers_universe"] = hk_list
    hk_sum["tickers_ok"] = hk_ok
    us_sum["market"] = "US"
    us_sum["title_zh"] = "美股（抽樣）"
    us_sum["attempted"] = len(us_list)
    us_sum["tickers_universe"] = us_list
    us_sum["tickers_ok"] = us_ok

    warnings: list[str] = []
    prev_hk = (prev_breadth or {}).get("hk") if isinstance(prev_breadth, dict) else None
    prev_us = (prev_breadth or {}).get("us") if isinstance(prev_breadth, dict) else None
    if isinstance(prev_hk, dict):
        warnings.extend(_breadth_drop_warnings("港股", prev_hk, hk_sum))
    if isinstance(prev_us, dict):
        warnings.extend(_breadth_drop_warnings("美股", prev_us, us_sum))

    return {
        "hk": hk_sum,
        "us": us_sum,
        "warnings_zh": warnings,
        "method_zh": "各市場最多抽樣若干股票，以 Yahoo 日線計算收市價高於 SMA50／SMA200 比例；與全市場實際廣度或有偏差。",
        "method_short_zh": (
            "樣本＝傳入之 ticker 清單順序；Yahoo 不足 50 根日線者剔除。tickers_ok 為實際入計代號。"
            if max_per_market is None
            else "樣本＝清單開首最多 85 只；Yahoo 不足 50 根日線者剔除。tickers_ok 為實際入計代號。"
        ),
    }
