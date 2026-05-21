"""
SCSP神器 - Web Application
Flask web interface for the mean-reversion trading strategy
"""

from flask import Flask, render_template, request, jsonify
import json
import pandas as pd
import ta
import yfinance as yf
import sys
import os
from datetime import datetime

_repo_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root_path not in sys.path:
    sys.path.insert(0, _repo_root_path)
from schema_versioning import apply_schema_floor, schema_version_for_export, strategy_display_name  # noqa: E402

# Version information
VERSION = "2.0.1"

# Try to read version from version.txt if it exists
try:
    version_file = os.path.join(os.path.dirname(__file__), 'version.txt')
    if os.path.exists(version_file):
        with open(version_file, 'r') as f:
            VERSION = f.read().strip()
except:
    pass

app = Flask(__name__)

# Scanner `tech_score` / `Why` rule-engine breakdown for sell_put, buy_stock, buy_put:
# implemented in `daily_scanner.technical_universe_row` (repo root), not in this file.


def _stock_row_to_json(row: dict) -> dict:
    """Map one scanner/universe dataframe row to frontend JSON."""
    close_raw = row.get("Close", row.get("Price"))
    rsi_n = _to_number(row.get("RSI"))
    macd_hist_n = _to_number(row.get("MACD_Hist"))
    macd_sign = row.get("MACD_Sign")
    if not macd_sign:
        if macd_hist_n is None:
            macd_sign = "N/A"
        else:
            macd_sign = "Positive" if float(macd_hist_n) >= 0 else "Negative"
    out = {
        "ticker": row.get("Ticker", "N/A"),
        "close": _to_number(close_raw),
        "rsi": rsi_n,
        "mfi": _to_number(row.get("MFI")),
        "macd_hist": macd_hist_n,
        "macd_sign": macd_sign,
        "adx": _to_number(row.get("ADX")),
        "dmi_gap": _to_number(row.get("DMI_Gap", row.get("PDI_MDI_Gap"))),
        "rvol": _to_number(row.get("RVOL")),
        "rs_20d": _to_number(row.get("RS_20d")),
        "vwap": _to_number(row.get("VWAP")),
        "signal": row.get("Signal", "N/A"),
        "reason": row.get("Why", "N/A"),
        "Ticker": row.get("Ticker", "N/A"),
        "Close": close_raw if close_raw is not None else "N/A",
        "RSI": row.get("RSI", "N/A"),
        "MFI": row.get("MFI", "N/A"),
        "ADX": row.get("ADX", "N/A"),
        "PDI": row.get("PDI", "N/A"),
        "MDI": row.get("MDI", "N/A"),
        "DMI_Gap": row.get("DMI_Gap", row.get("PDI_MDI_Gap", "N/A")),
        "MACD_Hist": row.get("MACD_Hist", "N/A"),
        "MACD_Sign": macd_sign,
        "RVOL": row.get("RVOL", "N/A"),
        "RS_20d": row.get("RS_20d", "N/A"),
        "VWAP": row.get("VWAP", "N/A"),
    }
    ts = row.get("tech_score")
    if ts is not None and str(ts) not in ("", "N/A", "nan"):
        tsn = _to_number(ts)
        if tsn is not None:
            out["tech_score"] = int(round(tsn))
    if row.get("score_model") is not None and str(row.get("score_model")).strip().lower() not in ("", "n/a", "nan"):
        out["score_model"] = str(row.get("score_model")).strip().lower()
    if row.get("scan_mode"):
        out["scan_mode"] = row.get("scan_mode")
    if row.get("adx_strength"):
        out["adx_strength"] = row.get("adx_strength")
    if row.get("macd_histogram_status"):
        out["macd_histogram_status"] = row.get("macd_histogram_status")
    ve = row.get("vwap_ext", row.get("VWAP_Ext"))
    if ve is not None and str(ve).strip().upper() in ("Y", "N"):
        out["vwap_ext"] = str(ve).strip().upper()
    if row.get("ai_strategy_comment"):
        out["ai_strategy_comment"] = row.get("ai_strategy_comment")
    tsp = row.get("tech_score_prev")
    if tsp is not None and str(tsp).strip().lower() not in ("", "n/a", "nan", "none"):
        tspn = _to_number(tsp)
        if tspn is not None:
            out["tech_score_prev"] = int(round(tspn))
    tsd = row.get("tech_score_delta")
    if tsd is not None and str(tsd).strip().lower() not in ("", "n/a", "nan", "none"):
        tsdn = _to_number(tsd)
        if tsdn is not None:
            out["tech_score_delta"] = int(round(tsdn))
    for key in ("tech_score_d2", "tech_score_d1"):
        v = row.get(key)
        if v is not None and str(v).strip().lower() not in ("", "n/a", "nan", "none"):
            vn = _to_number(v)
            if vn is not None:
                out[key] = int(round(vn))
    if row.get("score_arc"):
        out["score_arc"] = str(row.get("score_arc"))
    if row.get("score_arc_label"):
        out["score_arc_label"] = str(row.get("score_arc_label"))
    if row.get("score_arc_pattern"):
        out["score_arc_pattern"] = str(row.get("score_arc_pattern"))
    if "data_ok" in row and row.get("data_ok") is not None:
        out["data_ok"] = bool(row.get("data_ok"))
    ixm = row.get("HS_Index", row.get("hs_index"))
    if ixm is not None and str(ixm).strip() not in ("", "nan", "None"):
        s_ix = str(ixm).strip()
        out["hs_index"] = s_ix
        out["HS_Index"] = s_ix
    return out


def export_results_to_json(
    df,
    strategy_name,
    filename="daily_scan.json",
    *,
    score_model_slug: str | None = None,
    schema_version: str | None = None,
):
    """
    Export scanner results with a stable JSON contract for SSG frontend.
    Writes to repository root when filename is relative.

    score_model_slug: optional engine id (sell_put | buy_stock | buy_put) for dashboard binding;
        if omitted, inferred from dataframe column `score_model` when present.
    """
    now_str = _now_iso()
    schema_ver = apply_schema_floor(schema_version or schema_version_for_export(bump=False))

    if not os.path.isabs(filename):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        filename = os.path.join(repo_root, os.path.basename(filename))

    prev_map, prev_asof = _prev_tech_scores_from_scan_json(filename)
    score_hist = None
    inferred_slug = score_model_slug

    empty_slug = (score_model_slug or "sell_put").strip().lower()
    display_strategy = strategy_display_name(empty_slug, strategy_name)

    if df is None or df.empty:
        scan_empty: dict = {
            "strategy": display_strategy,
            "mode": "empty",
            "total": 0,
            "buy_count": 0,
            "sell_count": 0,
            "wait_count": 0,
            "score_model": empty_slug,
        }
        if prev_asof:
            scan_empty["score_prev_asof"] = prev_asof
        export_data = {
            "schema_version": schema_ver,
            "last_updated": now_str,
            "scan": scan_empty,
            "stocks": [],
        }
    else:
        work = df.copy()
        if "Close" not in work.columns and "Price" in work.columns:
            work["Close"] = work["Price"]
        work = work.fillna("N/A")

        raw_rows = work.to_dict(orient="records")

        inferred_slug = score_model_slug
        if inferred_slug is None and raw_rows:
            sm0 = raw_rows[0].get("score_model")
            if sm0 is not None and str(sm0).strip().lower() not in ("", "n/a", "nan", "none"):
                inferred_slug = str(sm0).strip().lower()
        if not inferred_slug:
            inferred_slug = "sell_put"

        today_date = now_str.split("T")[0] if "T" in now_str else now_str[:10]
        score_hist, score_hist_meta = _enrich_rows_with_daily_score_history(
            raw_rows, inferred_slug, today_date
        )

        if prev_map:
            for r in raw_rows:
                sym = str(r.get("Ticker", r.get("ticker", ""))).strip().upper()
                if not sym or sym == "N/A":
                    continue
                if r.get("tech_score_d1") is not None:
                    continue
                if sym not in prev_map:
                    continue
                prev_v = prev_map[sym]
                r["tech_score_prev"] = prev_v
                curr = _to_number(r.get("tech_score"))
                if curr is not None:
                    r["tech_score_delta"] = int(round(float(curr))) - int(prev_v)

        for r in raw_rows:
            d1 = r.get("tech_score_d1")
            if d1 is not None and r.get("tech_score_prev") is None:
                r["tech_score_prev"] = d1
            curr = _to_number(r.get("tech_score"))
            if curr is not None and d1 is not None and r.get("tech_score_delta") is None:
                r["tech_score_delta"] = int(round(float(curr))) - int(_to_number(d1) or 0)

        universe = any(str(r.get("scan_mode", "")).lower() == "universe" for r in raw_rows)

        stocks = [_stock_row_to_json(dict(r)) for r in raw_rows]

        if universe:
            buy_count = sum(1 for s in stocks if "STRONG" in str(s.get("signal", "")).upper())
            wait_count = sum(
                1
                for s in stocks
                if "WATCH" in str(s.get("signal", "")).upper() or "NO DATA" in str(s.get("signal", "")).upper()
            )
            sell_count = sum(1 for s in stocks if "CAUTION" in str(s.get("signal", "")).upper())
            mode = "universe"
        else:
            buy_count = sum(1 for s in stocks if "BUY" in str(s.get("signal", "")).upper())
            sell_count = sum(
                1
                for s in stocks
                if "SELL" in str(s.get("signal", "")).upper()
                or "PROFIT" in str(s.get("signal", "")).upper()
            )
            wait_count = max(len(stocks) - buy_count - sell_count, 0)
            mode = "signals"

        display_strategy = strategy_display_name(inferred_slug, strategy_name)
        scan_block = {
            "strategy": display_strategy,
            "mode": mode,
            "total": len(stocks),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "wait_count": wait_count,
            "score_model": inferred_slug,
        }
        if prev_asof:
            scan_block["score_prev_asof"] = prev_asof
        if score_hist_meta.get("d2_date"):
            scan_block["score_d2_date"] = score_hist_meta["d2_date"]
        if score_hist_meta.get("d1_date"):
            scan_block["score_d1_date"] = score_hist_meta["d1_date"]
        scan_block["score_today_date"] = today_date
        scan_block["score_arc_mode"] = "trading_days"
        export_data = {
            "schema_version": schema_ver,
            "last_updated": now_str,
            "scan": scan_block,
            "stocks": stocks,
        }

    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=4)
        if score_hist is not None:
            _save_score_daily_history(score_hist)
        if df is not None and not df.empty and "export_data" in locals():
            sc = export_data.get("scan") if isinstance(export_data.get("scan"), dict) else {}
            if sc.get("mode") == "universe":
                export_daily_breadth_snapshot(
                    date=today_date,
                    score_model=str(sc.get("score_model") or inferred_slug or "sell_put"),
                    strong=int(sc.get("buy_count") or 0),
                    watch=int(sc.get("wait_count") or 0),
                    caution=int(sc.get("sell_count") or 0),
                    schema_version=schema_ver,
                )
        return True
    except Exception as e:
        print(f"Error exporting to JSON: {e}")
        return False


def _resolve_repo_json_path(filename: str) -> str:
    """Resolve JSON file path to repository root when using relative path."""
    if os.path.isabs(filename):
        return filename
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(repo_root, os.path.basename(filename))


def _read_json_file(path: str, default):
    """Best-effort JSON read with fallback default."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _prev_tech_scores_from_scan_json(abs_path: str) -> tuple[dict[str, int], str | None]:
    """
    Read an existing daily_scan*.json on disk (same path we are about to overwrite).
    Returns (ticker_upper -> tech_score, last_updated of that file) for score trend vs last export.
    """
    if not abs_path or not os.path.isfile(abs_path):
        return {}, None
    data = _read_json_file(abs_path, None)
    if not isinstance(data, dict):
        return {}, None
    prev_asof = data.get("last_updated")
    prev_asof_s = str(prev_asof).strip() if prev_asof not in (None, "") else None
    stocks = data.get("stocks")
    if not isinstance(stocks, list):
        return {}, prev_asof_s
    out: dict[str, int] = {}
    for s in stocks:
        if not isinstance(s, dict):
            continue
        sym = str(s.get("ticker") or s.get("Ticker") or "").strip().upper()
        if not sym or sym == "N/A":
            continue
        ts = s.get("tech_score")
        if ts is None or str(ts).strip().lower() in ("", "n/a", "nan", "none"):
            continue
        tsn = _to_number(ts)
        if tsn is None:
            continue
        try:
            out[sym] = int(round(float(tsn)))
        except (TypeError, ValueError):
            continue
    return out, prev_asof_s


SCORE_DAILY_HISTORY_FILE = "score_daily_history.json"
SCORE_HISTORY_RETENTION_DAYS = 120


def _score_daily_history_path() -> str:
    return _resolve_repo_json_path(SCORE_DAILY_HISTORY_FILE)


def _load_score_daily_history() -> dict:
    default = {"schema_version": "1.0", "last_updated": None, "models": {}}
    data = _read_json_file(_score_daily_history_path(), default)
    if not isinstance(data, dict):
        return default
    if "models" not in data or not isinstance(data["models"], dict):
        data["models"] = {}
    return data


def _save_score_daily_history(payload: dict) -> None:
    payload["last_updated"] = _now_iso()
    try:
        with open(_score_daily_history_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving score daily history: {e}")


def _prune_score_date_map(date_map: dict, *, today: str, retention_days: int) -> dict:
    """Keep only dates within retention window (by calendar day string YYYY-MM-DD)."""
    if not date_map:
        return {}
    try:
        today_dt = datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return dict(date_map)
    out = {}
    for d, sc in date_map.items():
        try:
            dd = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if (today_dt - dd).days <= retention_days:
            try:
                out[str(d)[:10]] = int(round(float(sc)))
            except (TypeError, ValueError):
                continue
    return out


def _prior_daily_scores(
    history: dict, model: str, ticker: str, today: str
) -> tuple[int | None, int | None, str | None, str | None]:
    """Last two calendar days strictly before `today` with stored scores."""
    models = history.get("models") or {}
    model_map = models.get(model) or {}
    ticker_map = model_map.get(ticker.upper()) or {}
    if not isinstance(ticker_map, dict):
        return None, None, None, None
    pairs: list[tuple[str, int]] = []
    for d, sc in ticker_map.items():
        ds = str(d)[:10]
        if ds >= today:
            continue
        sn = _to_number(sc)
        if sn is None:
            continue
        pairs.append((ds, int(round(float(sn)))))
    pairs.sort(key=lambda x: x[0])
    if len(pairs) >= 2:
        return pairs[-2][1], pairs[-1][1], pairs[-2][0], pairs[-1][0]
    if len(pairs) == 1:
        return None, pairs[-1][1], None, pairs[-1][0]
    return None, None, None, None


def _format_score_arc(s0: int | None, s1: int | None, s2: int | None) -> str:
    parts: list[str] = []
    for v in (s0, s1, s2):
        if v is None:
            parts.append("—")
        else:
            parts.append(str(int(v)))
    return " → ".join(parts)


def _classify_score_arc(s0: int | None, s1: int | None, s2: int | None) -> tuple[str, str]:
    """
    Classify 3-day score path (T-2, T-1, today).
    perfect_accel: strictly rising e.g. 70→85→100
    erratic: large V/W swing e.g. 90→50→100
    """
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


def _enrich_rows_with_daily_score_history(
    raw_rows: list[dict], model: str, today: str
) -> tuple[dict, dict]:
    """
    Attach tech_score_d2/d1, score_arc*, update in-memory history with today's scores.
    Returns (history_payload, meta with d2_date/d1_date).
    """
    history = _load_score_daily_history()
    models = history.setdefault("models", {})
    model_map = models.setdefault(model, {})
    meta: dict = {"d2_date": None, "d1_date": None}
    global_d2: str | None = None
    global_d1: str | None = None

    for r in raw_rows:
        sym = str(r.get("Ticker", r.get("ticker", ""))).strip().upper()
        if not sym or sym == "N/A":
            continue
        curr = _to_number(r.get("tech_score"))
        if curr is None:
            continue
        curr_i = int(round(float(curr)))

        row_d2 = r.get("tech_score_d2")
        row_d1 = r.get("tech_score_d1")
        if row_d2 is not None and str(row_d2).strip().lower() not in ("", "n/a", "nan", "none"):
            d2n = _to_number(row_d2)
            d2 = int(round(d2n)) if d2n is not None else None
            d1n = _to_number(row_d1) if row_d1 is not None else None
            d1 = int(round(d1n)) if d1n is not None else None
            d2_date = r.get("score_d2_trade_date")
            d1_date = r.get("score_d1_trade_date")
            if not r.get("score_arc"):
                label, pattern = _classify_score_arc(d2, d1, curr_i)
                r["score_arc"] = _format_score_arc(d2, d1, curr_i)
                r["score_arc_label"] = label
                r["score_arc_pattern"] = pattern
        else:
            d2, d1, d2_date, d1_date = _prior_daily_scores(history, model, sym, today)
            label, pattern = _classify_score_arc(d2, d1, curr_i)
            r["tech_score_d2"] = d2
            r["tech_score_d1"] = d1
            r["score_arc"] = _format_score_arc(d2, d1, curr_i)
            r["score_arc_label"] = label
            r["score_arc_pattern"] = pattern

        if d2_date and global_d2 is None:
            global_d2 = str(d2_date)[:10]
        if d1_date and global_d1 is None:
            global_d1 = str(d1_date)[:10]

        ticker_map = model_map.setdefault(sym, {})
        if not isinstance(ticker_map, dict):
            ticker_map = {}
            model_map[sym] = ticker_map
        ticker_map[today] = curr_i
        model_map[sym] = _prune_score_date_map(ticker_map, today=today, retention_days=SCORE_HISTORY_RETENTION_DAYS)

    meta["d2_date"] = global_d2
    meta["d1_date"] = global_d1
    history["schema_version"] = "1.0"
    return history, meta


def _now_iso() -> str:
    """Return local timestamp in ISO-8601 seconds precision."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _to_number(value):
    """Convert strings like '123.4', '1.2x', '1,234.5' to float; else None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("x"):
        text = text[:-1]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _signal_is_bearish_underlying(sig: dict) -> bool:
    """Buy Put / bearish: profit when underlying price falls."""
    if not isinstance(sig, dict):
        return False
    action = str(sig.get("action", "")).strip().upper()
    model = str(sig.get("score_model", "")).strip().lower()
    return action == "BUY_PUT" or model == "buy_put"


def _pnl_pct_underlying(entry_px: float, latest_px: float, *, bearish: bool) -> float:
    """Return % P&L vs entry. Long: (latest-entry)/entry; bearish: (entry-latest)/entry."""
    if entry_px == 0:
        return 0.0
    if bearish:
        return round((float(entry_px) - float(latest_px)) / float(entry_px) * 100.0, 2)
    return round((float(latest_px) - float(entry_px)) / float(entry_px) * 100.0, 2)


def _is_within_days(iso_or_date_text, retention_days: int) -> bool:
    """Keep records within retention window; if parse fails keep record."""
    if not retention_days or retention_days <= 0:
        return True
    if not iso_or_date_text:
        return True
    try:
        text = str(iso_or_date_text)
        dt = datetime.fromisoformat(text)
    except Exception:
        try:
            dt = datetime.strptime(str(iso_or_date_text), "%Y-%m-%d")
        except Exception:
            return True

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    age_days = (datetime.now().astimezone() - dt).days
    return age_days <= retention_days


def _dedupe_keep_latest(items, key_fn):
    """Deduplicate list of dicts using key_fn, keeping the latest occurrence."""
    latest = {}
    for item in items:
        latest[key_fn(item)] = item
    return list(latest.values())


def _fetch_macro_pair(ticker: str):
    """
    Return (latest_close, daily_change_pct) from Yahoo Finance.
    Returns (None, None) if data unavailable.
    Tries longer windows so thin symbols (e.g. DX-Y.NYB) still get two closes.
    """
    for period in ("5d", "1mo", "3mo"):
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            if isinstance(hist.columns, pd.MultiIndex):
                hist = hist.copy()
                hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
            closes = hist["Close"].dropna()
            if getattr(closes, "ndim", 1) == 2:
                closes = closes.iloc[:, 0]
            if len(closes) < 2:
                continue
            latest = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            change_pct = ((latest - prev) / prev) * 100.0 if prev else None
            return latest, change_pct
        except Exception:
            continue
    return None, None


def _fetch_dxy_pair():
    """ICE US Dollar index (Yahoo); fallbacks for session quirks."""
    for sym in ("DX-Y.NYB", "DX=F"):
        v, c = _fetch_macro_pair(sym)
        if v is not None:
            return v, c, sym
    return None, None, None


def _fetch_southbound_net_yi() -> float | None:
    """港股通（北水）淨額：滬港通 + 深港通，單位億人民幣（East Money kamt API）。"""
    try:
        import requests
    except ImportError:
        return None
    url = (
        "https://push2.eastmoney.com/api/qt/kamt/get"
        "?fields1=f1,f2,f3,f4&fields2=f51,f52,f54,f55,f56,f58,f59,f60,f62,f63"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            resp = requests.get(url.replace("https://", "http://"), headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        body = resp.json()
        d = (body or {}).get("data") or {}
        sh = d.get("sh2hk") or {}
        sz = d.get("sz2hk") or {}
        wan = float(sh.get("netBuyAmt") or 0) + float(sz.get("netBuyAmt") or 0)
        return round(wan / 10000.0, 2)
    except Exception as e:
        print(f"Southbound flow API: {e}")
        return None


def _build_ticker_bar(
    *,
    hsi_val,
    hsi_chg,
    sse_val,
    sse_chg,
    y10_val,
    y10_chg,
    dxy_val,
    dxy_chg,
    vix_val,
    vix_chg,
    southbound_yi,
) -> list[dict]:
    """Compact items for the top scrolling macro ticker (static site)."""

    def _fmt_chg(v) -> str | None:
        if not isinstance(v, (int, float)):
            return None
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    def _item(iid: str, label: str, value, change, unit: str = "", extra: str = ""):
        usable = value is not None and str(value).strip() not in ("", "N/A", "—", "nan")
        return {
            "id": iid,
            "label": label,
            "value": str(value) if usable else "—",
            "change": change if change else "",
            "unit": unit,
            "extra": extra,
        }

    def _fmt_num(v, d=2):
        return f"{v:.{d}f}" if isinstance(v, (int, float)) else None

    sb_val = "—"
    if isinstance(southbound_yi, (int, float)):
        sign = "+" if southbound_yi >= 0 else ""
        sb_val = f"{sign}{southbound_yi:.2f}億"

    y10_display = "—"
    if isinstance(y10_val, (int, float)):
        y10_display = f"{y10_val:.2f}%"

    return [
        _item("hsi", "恒生 HSI", _fmt_num(hsi_val), _fmt_chg(hsi_chg)),
        _item("sse", "上證 SSE", _fmt_num(sse_val), _fmt_chg(sse_chg)),
        _item("us10y", "10Y 國債", y10_display, _fmt_chg(y10_chg), unit="%"),
        _item("dxy", "美元 DXY", _fmt_num(dxy_val, 2), _fmt_chg(dxy_chg)),
        _item("vix", "VIX", _fmt_num(vix_val, 2), _fmt_chg(vix_chg)),
        _item(
            "northbound",
            "北水淨額",
            sb_val,
            "",
            unit="",
            extra="滬港通＋深港通",
        ),
    ]


def _build_macro_live_comment(
    *,
    vix_val: float | None,
    y10_val: float | None,
    southbound_yi: float | None,
    breadth_markets: dict | None,
    final_score: float | None,
) -> str:
    """One-line 大佬即時規則摘要 for static dashboard."""
    parts: list[str] = []
    if isinstance(vix_val, (int, float)):
        parts.append(
            f"VIX {vix_val:.2f} {'< 18 放心進攻' if vix_val < 18 else '≥ 18 防守克制'}"
        )
    if isinstance(y10_val, (int, float)):
        parts.append(
            f"美債10Y {y10_val:.2f}% {'偏緊' if y10_val > 4.5 else '尚可'}"
        )
    bm = breadth_markets if isinstance(breadth_markets, dict) else {}
    pcts: list[float] = []
    for key in ("hk", "us"):
        blk = bm.get(key)
        if isinstance(blk, dict):
            try:
                pcts.append(float(blk["above_ma200_pct"]))
            except (TypeError, ValueError, KeyError):
                pass
    if pcts:
        avg = sum(pcts) / len(pcts)
        parts.append(
            f"市寬 >200MA 均值 {avg:.0f}% → {'結構偏強' if avg >= 50 else '震盪／偏弱'}"
        )
    if isinstance(southbound_yi, (int, float)):
        parts.append(
            f"北水 {'+' if southbound_yi >= 0 else ''}{southbound_yi:.2f}億 → "
            f"{'流入支撐' if southbound_yi >= 0 else '抽水撤離'}"
        )
    if isinstance(final_score, (int, float)):
        regime = "Risk-On" if final_score > 75 else "Risk-Off" if final_score < 45 else "Neutral"
        parts.append(f"Global Risk {final_score:.0f}（{regime}）")
    if not parts:
        return "宏觀資料不足，待下次匯出更新。"
    return "；".join(parts) + "。"


def _compute_global_risk_score(
    *,
    vix_val: float | None,
    dxy_chg_pct: float | None,
    y10_chg_pct: float | None,
    breadth_markets: dict | None,
    southbound_yi: float | None,
) -> dict:
    """
    Global Risk Score 0–100 for option-trading macro context.
    VIX (30) + Capital cost DXY/US10Y (30) + breadth (20) + northbound (20).
    Breadth uses global sample >SMA50% (breadth_markets), not scanner signal rows.
    """
    components: dict = {}

    vix_pts = None
    if isinstance(vix_val, (int, float)):
        if vix_val < 15:
            vix_pts = 30
        elif vix_val <= 22:
            vix_pts = 15
        else:
            vix_pts = 0
        components["vix_pts"] = vix_pts

    cap_pts = 0
    cap_max = 0
    if isinstance(dxy_chg_pct, (int, float)):
        cap_max += 15
        if dxy_chg_pct < 0:
            cap_pts += 15
        components["dxy_down_pts"] = 15 if dxy_chg_pct < 0 else 0
    if isinstance(y10_chg_pct, (int, float)):
        cap_max += 15
        if y10_chg_pct < 0:
            cap_pts += 15
        components["y10_down_pts"] = 15 if y10_chg_pct < 0 else 0
    components["capital_pts"] = cap_pts if cap_max else None

    breadth_pts = None
    bm = breadth_markets if isinstance(breadth_markets, dict) else {}
    pcts: list[float] = []
    for key in ("hk", "us"):
        blk = bm.get(key)
        if isinstance(blk, dict):
            try:
                pcts.append(float(blk["above_ma50_pct"]))
            except (TypeError, ValueError, KeyError):
                pass
    if pcts:
        avg_pct = max(0.0, min(100.0, sum(pcts) / len(pcts)))
        breadth_pts = int(round((avg_pct / 100.0) * 20))
        components["breadth_sma50_pct"] = round(avg_pct, 2)
        components["breadth_source"] = "breadth_markets_ma50"
        components["breadth_pts"] = breadth_pts

    sb_pts = None
    if isinstance(southbound_yi, (int, float)):
        sb_pts = 20 if southbound_yi >= 0 else 0
        components["southbound_pts"] = sb_pts

    parts = [x for x in (vix_pts, cap_pts if cap_max else None, breadth_pts, sb_pts) if x is not None]
    score = float(sum(parts)) if parts else None
    regime = None
    if score is not None:
        if score > 75:
            regime = "Risk-On"
        elif score >= 45:
            regime = "Neutral"
        else:
            regime = "Risk-Off"
    return {
        "score": score,
        "regime": regime,
        "formula": "VIX(30)+Capital(30)+Breadth(20)+Northbound(20)",
        "components": components,
    }


def _yf_close_series_daily(ticker: str, period: str = "6mo", max_points: int = 120):
    """Last N trading days closing prices for frontend line charts [{d, c}, ...]."""
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        if isinstance(hist.columns, pd.MultiIndex):
            hist = hist.copy()
            hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
        if "Close" not in hist.columns:
            return []
        s = hist["Close"].dropna()
        if getattr(s, "ndim", 1) == 2:
            s = s.iloc[:, 0]
        pts = []
        for idx, val in s.items():
            try:
                pts.append({"d": pd.Timestamp(idx).strftime("%Y-%m-%d"), "c": round(float(val), 4)})
            except (TypeError, ValueError):
                continue
        return pts[-max_points:] if pts else []
    except Exception:
        return []


def _parse_row_rvol(row: dict) -> float | None:
    raw = row.get("RVOL", row.get("rvol"))
    if raw is None:
        return None
    try:
        s = str(raw).strip().replace("—", "").replace("x", "").replace(",", "")
        if s.endswith("%"):
            s = s[:-1]
        if s in ("", "nan", "N/A", "None"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _entry_date_from_iso(iso_text: str) -> str:
    if not iso_text:
        return datetime.now().astimezone().strftime("%Y-%m-%d")
    return str(iso_text).split("T")[0][:10]


def _holding_days(entry_date: str, as_of_date: str) -> int | None:
    try:
        d0 = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(str(as_of_date)[:10], "%Y-%m-%d").date()
        return max((d1 - d0).days, 0)
    except Exception:
        return None


def _band_counts_from_stocks(stocks: list) -> tuple[int, int, int]:
    """Map scan rows to 強勢 / 觀望 / 危險 counts (universe band labels)."""
    strong = watch = caution = 0
    for s in stocks or []:
        sig = str(s.get("signal", s.get("Signal", ""))).upper()
        if "STRONG" in sig:
            strong += 1
        elif "CAUTION" in sig:
            caution += 1
        else:
            watch += 1
    return strong, watch, caution


def export_daily_breadth_snapshot(
    *,
    date: str,
    score_model: str,
    strong: int,
    watch: int,
    caution: int,
    filename: str = "breadth_daily_history.json",
    schema_version: str | None = None,
) -> bool:
    """Append/replace one calendar day's band counts for a score model (feeds 每日訊號市寬 chart)."""
    out_path = _resolve_repo_json_path(filename)
    now_str = _now_iso()
    day = str(date or "")[:10]
    model = str(score_model or "sell_put").strip().lower()
    if len(day) != 10:
        day = _entry_date_from_iso(now_str)
    schema_ver = apply_schema_floor(schema_version or schema_version_for_export(bump=False))
    payload = _read_json_file(
        out_path, {"schema_version": schema_ver, "last_updated": now_str, "days": []}
    )
    if not isinstance(payload, dict):
        payload = {"schema_version": schema_ver, "last_updated": now_str, "days": []}
    days = payload.get("days")
    if not isinstance(days, list):
        days = []
    entry = {
        "date": day,
        "model": model,
        "strong": int(strong),
        "watch": int(watch),
        "caution": int(caution),
        "total": int(strong) + int(watch) + int(caution),
    }
    days = [d for d in days if not (isinstance(d, dict) and d.get("date") == day and d.get("model") == model)]
    days.append(entry)
    days.sort(key=lambda x: (str(x.get("date", "")), str(x.get("model", ""))))
    if len(days) > 400:
        days = days[-400:]
    payload["days"] = days
    payload["last_updated"] = now_str
    payload["schema_version"] = schema_ver
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error exporting daily breadth snapshot: {e}")
        return False


def backfill_daily_breadth_from_scan_json(
    scan_filename: str,
    score_model: str,
    breadth_filename: str = "breadth_daily_history.json",
) -> bool:
    """One-off helper: read an existing daily_scan_*.json and record its band counts."""
    path = _resolve_repo_json_path(scan_filename)
    data = _read_json_file(path, None)
    if not isinstance(data, dict):
        return False
    scan = data.get("scan") if isinstance(data.get("scan"), dict) else {}
    stocks = data.get("stocks") if isinstance(data.get("stocks"), list) else []
    lu = str(data.get("last_updated") or "")
    day = lu.split("T")[0][:10] if "T" in lu else lu[:10]
    if len(day) != 10:
        day = str(scan.get("score_today_date") or "")[:10]
    if len(day) != 10:
        return False
    model = str(score_model or scan.get("score_model") or "sell_put").strip().lower()
    if scan.get("mode") == "universe" and all(k in scan for k in ("buy_count", "wait_count", "sell_count")):
        strong = int(scan.get("buy_count") or 0)
        watch = int(scan.get("wait_count") or 0)
        caution = int(scan.get("sell_count") or 0)
    else:
        strong, watch, caution = _band_counts_from_stocks(stocks)
    return export_daily_breadth_snapshot(
        date=day,
        score_model=model,
        strong=strong,
        watch=watch,
        caution=caution,
        filename=breadth_filename,
    )


def export_trade_signals_history_to_json(
    df,
    strategy_name,
    *,
    score_model_slug: str,
    filename: str = "signals_history.json",
    max_entries: int = 5000,
    retention_days: int = 180,
    schema_version: str | None = None,
) -> int:
    """
    Log only rows that pass model-specific entry triggers; update mark-to-market on each run.
    Returns count of newly logged triggers this run.
    """
    try:
        from daily_scanner import (
            evaluate_trade_trigger,
            macd_status_from_row,
            sell_put_trigger_scenario,
        )
    except ImportError as e:
        print(f"[warn] trade trigger engine unavailable (daily_scanner import): {e}")
        evaluate_trade_trigger = None  # type: ignore[assignment]
        macd_status_from_row = None  # type: ignore[assignment]
        sell_put_trigger_scenario = None  # type: ignore[assignment]

    out_path = _resolve_repo_json_path(filename)
    now_str = _now_iso()
    today = _entry_date_from_iso(now_str)
    schema_ver = apply_schema_floor(schema_version or schema_version_for_export(bump=False))
    strat_label = strategy_display_name(score_model_slug, strategy_name)
    payload = _read_json_file(
        out_path, {"schema_version": schema_ver, "last_updated": now_str, "signals": []}
    )
    if not isinstance(payload, dict):
        payload = {"schema_version": schema_ver, "last_updated": now_str, "signals": []}
    if "signals" not in payload or not isinstance(payload["signals"], list):
        payload["signals"] = []

    price_map: dict[str, float] = {}
    if df is not None and not df.empty:
        work = df.copy().fillna("N/A")
        if "Close" not in work.columns and "Price" in work.columns:
            work["Close"] = work["Price"]
        for row in work.to_dict(orient="records"):
            sym = str(row.get("Ticker", row.get("ticker", ""))).strip().upper()
            px = _to_number(row.get("Close", row.get("Price")))
            if sym and sym != "N/A" and px is not None:
                price_map[sym] = float(px)

    for sig in payload["signals"]:
        if not isinstance(sig, dict):
            continue
        sym = str(sig.get("ticker", "")).strip().upper()
        entry_px = _to_number(sig.get("entry_price", sig.get("close")))
        latest = price_map.get(sym) if sym else None
        if latest is None:
            latest = _to_number(sig.get("latest_price"))
        if latest is not None:
            sig["latest_price"] = round(float(latest), 4)
            if entry_px is not None and float(entry_px) != 0:
                sig["pnl_pct"] = _pnl_pct_underlying(
                    float(entry_px), float(latest), bearish=_signal_is_bearish_underlying(sig)
                )
        sig["last_marked"] = today
        ed = sig.get("entry_date") or _entry_date_from_iso(sig.get("date", ""))
        hd = _holding_days(ed, today)
        if hd is not None:
            sig["holding_days"] = hd

    new_count = 0
    model_slug = str(score_model_slug or "sell_put").strip().lower()
    if df is not None and not df.empty and evaluate_trade_trigger is not None:
        work = df.copy().fillna("N/A")
        if "Close" not in work.columns and "Price" in work.columns:
            work["Close"] = work["Price"]
        for row in work.to_dict(orient="records"):
            action = evaluate_trade_trigger(dict(row), model_slug)
            if not action:
                continue
            sym = str(row.get("Ticker", row.get("ticker", "N/A"))).strip().upper()
            entry_px = _to_number(row.get("Close", row.get("Price")))
            if not sym or sym == "N/A" or entry_px is None:
                continue
            macd_st = macd_status_from_row(dict(row)) if macd_status_from_row else ""
            ts = row.get("tech_score")
            try:
                score_i = int(round(float(ts))) if ts is not None else None
            except (TypeError, ValueError):
                score_i = None
            trigger_track = None
            if (
                action == "SELL_PUT"
                and sell_put_trigger_scenario is not None
                and model_slug == "sell_put"
            ):
                trigger_track = sell_put_trigger_scenario(dict(row))
            entry = {
                "date": now_str,
                "entry_date": today,
                "ticker": sym,
                "action": action,
                "score_model": model_slug,
                "strategy": strat_label,
                "signal": row.get("Signal", "N/A"),
                "score": score_i,
                "entry_price": round(float(entry_px), 4),
                "latest_price": round(float(entry_px), 4),
                "pnl_pct": 0.0,
                "holding_days": 0,
                "macd_status": macd_st,
                "rvol": _parse_row_rvol(dict(row)),
                "status": "open",
                "last_marked": today,
            }
            if trigger_track:
                entry["trigger_track"] = trigger_track
            ve = dict(row).get("vwap_ext")
            if ve is not None and str(ve).strip().upper() in ("Y", "N"):
                entry["vwap_ext"] = str(ve).strip().upper()
            payload["signals"].append(entry)
            new_count += 1

    payload["signals"] = [x for x in payload["signals"] if _is_within_days(x.get("date"), retention_days)]
    payload["signals"] = _dedupe_keep_latest(
        payload["signals"],
        lambda x: (
            f"{x.get('entry_date','')}|{x.get('ticker','')}|{x.get('action','')}|{x.get('score_model','')}"
        ),
    )
    if max_entries and len(payload["signals"]) > max_entries:
        payload["signals"] = payload["signals"][-max_entries:]
    payload["last_updated"] = now_str
    payload["schema_version"] = schema_ver
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error exporting trade signals history: {e}")
        return 0
    return new_count


def export_signals_history_to_json(
    df,
    strategy_name,
    filename="signals_history.json",
    max_entries=5000,
    retention_days=180,
    schema_version: str | None = None,
    score_model_slug: str | None = None,
):
    """Append this run's signals into a historical signal store with dedupe + retention."""
    out_path = _resolve_repo_json_path(filename)
    now_str = _now_iso()
    schema_ver = apply_schema_floor(schema_version or schema_version_for_export(bump=False))
    strat_label = strategy_display_name(score_model_slug or "sell_put", strategy_name)
    payload = _read_json_file(out_path, {"schema_version": schema_ver, "last_updated": now_str, "signals": []})
    if not isinstance(payload, dict):
        payload = {"schema_version": schema_ver, "last_updated": now_str, "signals": []}
    if "signals" not in payload or not isinstance(payload["signals"], list):
        payload["signals"] = []

    if df is not None and not df.empty:
        work = df.copy().fillna("N/A")
        if "Close" not in work.columns and "Price" in work.columns:
            work["Close"] = work["Price"]
        rows = work.to_dict(orient="records")
        for row in rows:
            payload["signals"].append(
                {
                    "date": now_str,
                    "ticker": row.get("Ticker", "N/A"),
                    "strategy": strat_label,
                    "signal": row.get("Signal", "N/A"),
                    "close": _to_number(row.get("Close", row.get("Price"))),
                }
            )

    payload["signals"] = [x for x in payload["signals"] if _is_within_days(x.get("date"), retention_days)]
    payload["signals"] = _dedupe_keep_latest(
        payload["signals"],
        lambda x: f"{x.get('date','')}|{x.get('ticker','')}|{x.get('strategy','')}|{x.get('signal','')}",
    )
    if max_entries and len(payload["signals"]) > max_entries:
        payload["signals"] = payload["signals"][-max_entries:]
    payload["last_updated"] = now_str
    payload["schema_version"] = schema_ver
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error exporting signals history: {e}")
        return False


def append_future_log_to_json(
    df,
    strategy_name,
    filename="future_log.json",
    max_entries=5000,
    retention_days=180,
    schema_version: str | None = None,
    score_model_slug: str | None = None,
):
    """Append latest run snapshot rows into a future log with dedupe + retention."""
    out_path = _resolve_repo_json_path(filename)
    now_str = _now_iso()
    schema_ver = apply_schema_floor(schema_version or schema_version_for_export(bump=False))
    strat_label = strategy_display_name(score_model_slug or "sell_put", strategy_name)
    payload = _read_json_file(out_path, {"schema_version": schema_ver, "logs": []})
    if not isinstance(payload, dict):
        payload = {"schema_version": schema_ver, "logs": []}
    if "logs" not in payload or not isinstance(payload["logs"], list):
        payload["logs"] = []

    if df is not None and not df.empty:
        work = df.copy().fillna("N/A")
        if "Close" not in work.columns and "Price" in work.columns:
            work["Close"] = work["Price"]
        for row in work.to_dict(orient="records"):
            payload["logs"].append(
                {
                    "logged_at": now_str,
                    "trigger_date": now_str.split("T")[0],
                    "ticker": row.get("Ticker", "N/A"),
                    "strategy": strat_label,
                    "entry_price": _to_number(row.get("Close", row.get("Price"))),
                    "risk_notes": row.get("Why", "N/A"),
                }
            )

    payload["logs"] = [x for x in payload["logs"] if _is_within_days(x.get("logged_at"), retention_days)]
    payload["logs"] = _dedupe_keep_latest(
        payload["logs"],
        lambda x: f"{x.get('trigger_date','')}|{x.get('ticker','')}|{x.get('strategy','')}",
    )
    if max_entries and len(payload["logs"]) > max_entries:
        payload["logs"] = payload["logs"][-max_entries:]
    payload["last_updated"] = now_str
    payload["schema_version"] = schema_ver

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error appending future log: {e}")
        return False


def _macro_value_usable(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().upper()
    return s not in ("", "N/A", "NAN", "NONE", "—")


def _merge_macro_payload(prev: dict, new: dict) -> dict:
    """Keep last good macro/breadth/chart data when a fetch pass returns N/A or empty."""
    if not isinstance(prev, dict) or not prev:
        return new
    merged = dict(new)
    prev_metrics = {
        m.get("name"): m
        for m in (prev.get("metrics") or [])
        if isinstance(m, dict) and m.get("name")
    }
    out_metrics = []
    for m in new.get("metrics") or []:
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        if name and not _macro_value_usable(m.get("value")) and name in prev_metrics:
            pm = prev_metrics[name]
            if _macro_value_usable(pm.get("value")):
                out_metrics.append(
                    {
                        **m,
                        "value": pm.get("value"),
                        "change": pm.get("change") if _macro_value_usable(pm.get("change")) else m.get("change"),
                    }
                )
                continue
        out_metrics.append(m)
    merged["metrics"] = out_metrics

    prev_cs = prev.get("chart_series") if isinstance(prev.get("chart_series"), dict) else {}
    new_cs = merged.get("chart_series") if isinstance(merged.get("chart_series"), dict) else {}
    cs_out = dict(prev_cs)
    for k, v in new_cs.items():
        if v:
            cs_out[k] = v
    merged["chart_series"] = cs_out

    prev_sb = prev.get("southbound_connect") if isinstance(prev.get("southbound_connect"), dict) else {}
    new_sb = merged.get("southbound_connect") if isinstance(merged.get("southbound_connect"), dict) else {}
    if new_sb.get("net_yi") is None and prev_sb.get("net_yi") is not None:
        merged["southbound_connect"] = {**new_sb, "net_yi": prev_sb.get("net_yi")}

    prev_tb = prev.get("ticker_bar") if isinstance(prev.get("ticker_bar"), list) else []
    new_tb = merged.get("ticker_bar") if isinstance(merged.get("ticker_bar"), list) else []
    if new_tb and prev_tb:
        prev_by_id = {x.get("id"): x for x in prev_tb if isinstance(x, dict) and x.get("id")}
        out_tb = []
        for item in new_tb:
            if not isinstance(item, dict):
                continue
            iid = item.get("id")
            if iid and str(item.get("value", "")).strip() in ("—", "", "N/A") and iid in prev_by_id:
                out_tb.append({**item, **{k: v for k, v in prev_by_id[iid].items() if k in ("value", "change")}})
            else:
                out_tb.append(item)
        merged["ticker_bar"] = out_tb

    prev_adv = prev.get("advanced") if isinstance(prev.get("advanced"), dict) else {}
    new_adv = merged.get("advanced") if isinstance(merged.get("advanced"), dict) else {}
    if not new_adv and prev_adv:
        merged["advanced"] = prev_adv
    elif prev_adv and new_adv:
        adv_out = dict(prev_adv)
        adv_out.update(new_adv)
        merged["advanced"] = adv_out

    bm = merged.get("breadth_markets") if isinstance(merged.get("breadth_markets"), dict) else {}
    pbm = prev.get("breadth_markets") if isinstance(prev.get("breadth_markets"), dict) else {}
    hk_sampled = int((bm.get("hk") or {}).get("sampled") or 0) if isinstance(bm.get("hk"), dict) else 0
    if hk_sampled <= 0 and pbm:
        merged["breadth_markets"] = pbm
        merged["breadth_stale"] = True

    prev_mr = prev.get("macro_risk") if isinstance(prev.get("macro_risk"), dict) else {}
    new_mr = merged.get("macro_risk") if isinstance(merged.get("macro_risk"), dict) else {}
    if new_mr.get("final_score") is None and prev_mr.get("final_score") is not None:
        merged["macro_risk"] = prev_mr
    hist = merged.get("macro_risk_history")
    if not hist and isinstance(prev.get("macro_risk_history"), list):
        merged["macro_risk_history"] = prev["macro_risk_history"]
    return merged


def export_trade_signals_from_scan_files(
    filenames: dict[str, str] | None = None,
    strategy_name: str = "Scan file sync",
) -> int:
    """
    Re-apply trigger logging from saved daily_scan_*.json (safety net if in-memory export was skipped).
    Returns total newly logged triggers.
    """
    if filenames is None:
        filenames = {
            "sell_put": "daily_scan_sell_put.json",
            "buy_stock": "daily_scan_buy_stock.json",
            "buy_put": "daily_scan_buy_put.json",
        }
    total = 0
    for model_slug, fname in filenames.items():
        path = _resolve_repo_json_path(fname)
        data = _read_json_file(path, None)
        if not isinstance(data, dict):
            continue
        stocks = data.get("stocks")
        if not isinstance(stocks, list) or not stocks:
            continue
        df = pd.DataFrame(stocks)
        if "Ticker" not in df.columns and "ticker" in df.columns:
            df["Ticker"] = df["ticker"]
        if "Close" not in df.columns and "close" in df.columns:
            df["Close"] = df["close"]
        if "macd_histogram_status" not in df.columns:
            for col in ("macd_histogram_status", "vwap_ext", "tech_score", "reason", "data_ok"):
                if col in df.columns:
                    continue
        total += export_trade_signals_history_to_json(
            df, f"{strategy_name} | ScoreModel={model_slug}", score_model_slug=model_slug
        )
    return total


def export_macro_snapshot_to_json(filename="macro_snapshot.json", schema_version: str | None = None):
    """Export lightweight macro snapshot with live values when available."""
    out_path = _resolve_repo_json_path(filename)
    now_str = _now_iso()
    schema_ver = apply_schema_floor(schema_version or schema_version_for_export(bump=True))
    try:
        import yfinance_bootstrap  # noqa: E402

        yfinance_bootstrap.enable()
    except Exception:
        pass
    vix_val, vix_chg = _fetch_macro_pair("^VIX")
    hsi_val, hsi_chg = _fetch_macro_pair("^HSI")
    sse_val, sse_chg = _fetch_macro_pair("000001.SS")
    btc_val, btc_chg = _fetch_macro_pair("BTC-USD")
    dxy_val, dxy_chg, _dxy_sym = _fetch_dxy_pair()
    southbound_yi = _fetch_southbound_net_yi()

    def _fmt(v, d=2):
        return f"{v:.{d}f}" if isinstance(v, (int, float)) else "N/A"

    def _fmt_chg(v):
        if not isinstance(v, (int, float)):
            return "N/A"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    advanced: dict = {}
    try:
        from macro_advanced import fetch_advanced_macro_data

        advanced = fetch_advanced_macro_data()
    except Exception as e:
        print(f"Advanced macro export (optional): {e}")

    chart_series = {}
    for label, sym in (
        ("恒生", "^HSI"),
        ("S&P500", "^GSPC"),
        ("NASDAQ", "^IXIC"),
        ("VIX", "^VIX"),
        ("BTC", "BTC-USD"),
        ("黃金", "GC=F"),
    ):
        ser = _yf_close_series_daily(sym)
        if ser:
            chart_series[label] = ser
    dxy_chart = _yf_close_series_daily("DX-Y.NYB", period="6mo")
    if not dxy_chart:
        dxy_chart = _yf_close_series_daily("DX=F", period="6mo")
    if dxy_chart:
        chart_series["DXY"] = dxy_chart

    def _num(x):
        try:
            if x is None:
                return None
            return float(x)
        except Exception:
            return None

    def _find_adv_value(keys_contains: list[str], field: str):
        if not isinstance(advanced, dict):
            return None
        for k, v in advanced.items():
            ku = str(k).upper()
            if any(s in ku for s in keys_contains):
                if isinstance(v, dict):
                    return _num(v.get(field))
        return None

    def _clamp(v: float | None):
        if v is None:
            return None
        return max(0.0, min(100.0, float(v)))

    def _score_vix(vix: float | None):
        # Calibrated to user's reference: VIX 17.5 -> ~75.9
        return _clamp(None if vix is None else 100.0 - (vix - 15.0) * 9.64)

    def _score_rsi(rsi: float | None):
        return _clamp(rsi)

    def _score_spread(spread: float | None):
        # Calibrated to user's reference: spread +0.76 -> ~62.8
        return _clamp(None if spread is None else 50.0 + spread * 16.84)

    def _score_btc_change(btc_pct: float | None):
        # Calibrated to user's reference: BTC -0.10% -> ~49.0
        return _clamp(None if btc_pct is None else 50.0 + btc_pct * 10.0)

    spx_rsi = _find_adv_value(["S&P", "SPX"], "rsi")
    y10 = _find_adv_value(["10Y"], "current")
    y3m = _find_adv_value(["3M"], "current")
    spread = (y10 - y3m) if (y10 is not None and y3m is not None) else None
    y10_chg = None
    if isinstance(advanced, dict):
        for k, v in advanced.items():
            if "10Y" in str(k) and isinstance(v, dict) and v.get("change_pct") is not None:
                y10_chg = _num(v.get("change_pct"))
                break
    if y10 is None:
        y10_pair = _fetch_macro_pair("^TNX")
        if y10_pair[0] is not None:
            y10 = y10_pair[0]
            if y10_chg is None:
                y10_chg = y10_pair[1]

    vix_score = _score_vix(_num(vix_val))
    rsi_score = _score_rsi(spx_rsi)
    spread_score = _score_spread(spread)
    btc_score = _score_btc_change(_num(btc_chg))
    legacy_score = None
    if all(x is not None for x in (vix_score, rsi_score, spread_score, btc_score)):
        legacy_score = _clamp(vix_score * 0.25 + rsi_score * 0.25 + spread_score * 0.30 + btc_score * 0.20)

    final_score = legacy_score

    prev_payload = _read_json_file(out_path, {})
    breadth_markets: dict = {}
    try:
        import sys
        from pathlib import Path as _Path

        _root = _Path(__file__).resolve().parent.parent
        _rs = str(_root)
        if _rs not in sys.path:
            sys.path.insert(0, _rs)
        from daily_scanner import get_tickers  # noqa: E402
        from macro_advanced import (  # noqa: E402
            compute_sampled_ma_breadth,
            load_hk_breadth_universe_csv,
            load_us_breadth_universe_csv,
        )

        _prev_bm = prev_payload.get("breadth_markets") if isinstance(prev_payload, dict) else None
        hk_csv = _root / "hk_breadth_universe.csv"
        us_csv = _root / "us_breadth_universe.csv"
        hk_from_csv = load_hk_breadth_universe_csv(hk_csv) if hk_csv.is_file() else []
        us_from_csv = load_us_breadth_universe_csv(us_csv) if us_csv.is_file() else []
        if hk_from_csv and us_from_csv:
            _n = max(len(hk_from_csv), len(us_from_csv))
            _workers = min(24, max(12, _n // 6))
            breadth_markets = compute_sampled_ma_breadth(
                hk_from_csv,
                us_from_csv,
                max_per_market=None,
                max_workers=_workers,
                prev_breadth=_prev_bm if isinstance(_prev_bm, dict) else None,
            )
            breadth_markets["universe_source"] = (
                f"{hk_csv.name} ({len(hk_from_csv)} names) + {us_csv.name} ({len(us_from_csv)} names)"
            )
            breadth_markets["method_short_zh"] = (
                f"市寬樣本：{hk_csv.name}（港股順序）+ {us_csv.name}（美股順序）；"
                "Yahoo 不足 50 根日線者剔除；tickers_ok 為實際入計代號。"
            )
        else:
            breadth_markets = compute_sampled_ma_breadth(
                get_tickers("HK"),
                get_tickers("US"),
                max_per_market=85,
                prev_breadth=_prev_bm if isinstance(_prev_bm, dict) else None,
            )
            breadth_markets["universe_source"] = "get_tickers(HK/US) cap 85 — add hk_breadth_universe.csv + us_breadth_universe.csv in repo root for custom lists"
    except Exception as e:
        print(f"Breadth markets (optional): {e}")

    global_risk = _compute_global_risk_score(
        vix_val=_num(vix_val),
        dxy_chg_pct=_num(dxy_chg),
        y10_chg_pct=y10_chg,
        breadth_markets=breadth_markets,
        southbound_yi=southbound_yi,
    )
    if global_risk.get("score") is not None:
        final_score = global_risk["score"]

    score_history = []
    if isinstance(prev_payload, dict) and isinstance(prev_payload.get("macro_risk_history"), list):
        for item in prev_payload["macro_risk_history"]:
            if isinstance(item, dict) and item.get("d") and item.get("score") is not None:
                try:
                    score_history.append({"d": str(item["d"]), "score": float(item["score"])})
                except Exception:
                    continue
    day = now_str.split("T")[0]
    if final_score is not None:
        replaced = False
        for h in score_history:
            if h["d"] == day:
                h["score"] = float(final_score)
                replaced = True
                break
        if not replaced:
            score_history.append({"d": day, "score": float(final_score)})
        score_history = sorted(score_history, key=lambda x: x["d"])[-365:]

    payload = {
        "schema_version": schema_ver,
        "last_updated": now_str,
        "metrics": [
            {"name": "VIX", "value": _fmt(vix_val), "change": _fmt_chg(vix_chg)},
            {"name": "HSI", "value": _fmt(hsi_val), "change": _fmt_chg(hsi_chg)},
            {"name": "DXY", "value": _fmt(dxy_val), "change": _fmt_chg(dxy_chg)},
            {"name": "BTC", "value": _fmt(btc_val), "change": _fmt_chg(btc_chg)},
        ],
        "advanced": advanced,
        "chart_series": chart_series,
        "breadth_markets": breadth_markets,
        "macro_risk": {
            "formula": global_risk.get("formula") or "VIX*25% + RSI*25% + Spread*30% + BTC*20%",
            "global_risk": global_risk,
            "inputs": {
                "vix": _num(vix_val),
                "dxy_change_pct": _num(dxy_chg),
                "y10_change_pct": y10_chg,
                "spx_rsi": spx_rsi,
                "yield_spread_10y_3m": spread,
                "btc_change_pct": _num(btc_chg),
                "breadth_sma50_pct": global_risk.get("components", {}).get("breadth_sma50_pct"),
            },
            "components": {
                "vix_score": vix_score,
                "rsi_score": rsi_score,
                "spread_score": spread_score,
                "btc_score": btc_score,
            },
            "final_score": final_score,
        },
        "macro_risk_history": score_history,
        "southbound_connect": {
            "label": "港股通（北水）淨額",
            "subtitle": "滬港通＋深港通",
            "net_yi": southbound_yi,
            "unit": "億人民幣",
        },
        "macro_comment": _build_macro_live_comment(
            vix_val=_num(vix_val),
            y10_val=_num(y10),
            southbound_yi=southbound_yi,
            breadth_markets=breadth_markets,
            final_score=final_score,
        ),
        "ticker_bar": _build_ticker_bar(
            hsi_val=_num(hsi_val),
            hsi_chg=_num(hsi_chg),
            sse_val=_num(sse_val),
            sse_chg=_num(sse_chg),
            y10_val=_num(y10),
            y10_chg=y10_chg,
            dxy_val=_num(dxy_val),
            dxy_chg=_num(dxy_chg),
            vix_val=_num(vix_val),
            vix_chg=_num(vix_chg),
            southbound_yi=southbound_yi,
        ),
    }
    if isinstance(southbound_yi, (int, float)):
        sign = "+" if southbound_yi >= 0 else ""
        payload["metrics"].append(
            {
                "name": "北水淨額",
                "value": f"{sign}{southbound_yi:.2f}億",
                "change": "滬港+深港",
            }
        )
    if isinstance(prev_payload, dict) and prev_payload.get("last_updated"):
        payload = _merge_macro_payload(prev_payload, payload)
        if payload.get("breadth_stale"):
            print("Macro export: Yahoo breadth fetch empty — kept previous breadth_markets.")
        stale_cs = not chart_series and isinstance(prev_payload.get("chart_series"), dict)
        if stale_cs:
            print("Macro export: chart_series fetch empty — merged previous series.")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error exporting macro snapshot: {e}")
        return False


def detect_bullish_pin_bar(row):
    """Detect if a candle is a Bullish Pin Bar."""
    body_size = abs(row['close'] - row['open'])
    lower_shadow = min(row['open'], row['close']) - row['low']
    
    if body_size == 0:
        return lower_shadow > 0
    
    return lower_shadow >= 2 * body_size


def calculate_indicators(df):
    """Calculate all required technical indicators."""
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame must contain columns: {required_cols}")
    
    # Calculate RSI (period 14)
    rsi_indicator = ta.momentum.RSIIndicator(df['close'], window=14)
    df['rsi'] = rsi_indicator.rsi()
    
    # Calculate Bollinger Bands (period 20, std dev 2)
    bb_indicator = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_upper'] = bb_indicator.bollinger_hband()
    df['bb_middle'] = bb_indicator.bollinger_mavg()
    df['bb_lower'] = bb_indicator.bollinger_lband()
    
    # Calculate ATR (Average True Range) with window=14
    atr_indicator = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14)
    df['atr'] = atr_indicator.average_true_range()
    
    # Calculate ADX (period 14) using Futu's formula with DMI+ and DMI-
    # Both moving average periods are 14 (N=14, M=14)
    from adx_futu import calculate_adx_futu_ewm
    adx_result = calculate_adx_futu_ewm(df, n=14, m=14)
    df['adx'] = adx_result['adx']
    df['dmi_plus'] = adx_result['pdi']  # DMI+ (PDI)
    df['dmi_minus'] = adx_result['mdi']  # DMI- (MDI)
    
    # Calculate ADX slope
    df['adx_slope'] = df['adx'].diff()

    # Long-term support + volume participation
    sma200_indicator = ta.trend.SMAIndicator(df['close'], window=200)
    df['sma200'] = sma200_indicator.sma_indicator()
    df['vol_sma20'] = df['volume'].rolling(window=20, min_periods=1).mean()
    df['rvol'] = df['volume'] / df['vol_sma20'].replace(0, pd.NA)

    # MACD dynamics for momentum turn detection
    macd_indicator = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd_line'] = macd_indicator.macd()
    df['macd_signal'] = macd_indicator.macd_signal()
    df['macd_hist'] = macd_indicator.macd_diff()
    
    # Detect Bullish Pin Bar
    df['is_pin_bar'] = df.apply(detect_bullish_pin_bar, axis=1)
    
    return df


def generate_analysis(df):
    """
    Generate detailed market analysis in Traditional Chinese.
    
    Returns a formatted analysis string covering:
    1. Trend Analysis (ADX & DI)
    2. Momentum Analysis (RSI)
    3. Position Analysis (Bollinger Bands)
    """
    if len(df) < 1:
        return "❌ 數據不足，無法進行分析"
    
    latest = df.iloc[-1]
    
    # Get values with safe defaults
    current_adx = latest.get('adx', pd.NA)
    pdi = latest.get('dmi_plus', pd.NA)
    mdi = latest.get('dmi_minus', pd.NA)
    rsi = latest.get('rsi', pd.NA)
    close_price = latest.get('close', pd.NA)
    bb_upper = latest.get('bb_upper', pd.NA)
    bb_lower = latest.get('bb_lower', pd.NA)
    sma200 = latest.get('sma200', pd.NA)
    
    analysis_parts = []
    
    # 1. Trend Analysis (ADX & DI)
    trend_desc = ""
    adx_value_str = "N/A"
    if pd.notna(current_adx):
        adx_value = float(current_adx)
        adx_value_str = f"{adx_value:.2f}"
        if adx_value > 30:
            trend_desc = "強勢趨勢"
        elif adx_value < 25:
            trend_desc = "弱勢趨勢 / 橫盤整理"
        else:
            trend_desc = "中等趨勢"
    else:
        trend_desc = "無法判斷"
    
    direction_desc = ""
    if pd.notna(pdi) and pd.notna(mdi):
        pdi_val = float(pdi)
        mdi_val = float(mdi)
        if pdi_val > mdi_val:
            direction_desc = "多頭主導（上升趨勢）"
        else:
            direction_desc = "空頭主導（下降趨勢）"
    else:
        direction_desc = "無法判斷方向"
    
    analysis_parts.append(f"📊 **趨勢分析：** {trend_desc}（ADX: {adx_value_str}，{direction_desc}）")
    
    # 2. Momentum Analysis (RSI)
    momentum_desc = ""
    rsi_value_str = "N/A"
    if pd.notna(rsi):
        rsi_value = float(rsi)
        rsi_value_str = f"{rsi_value:.2f}"
        if rsi_value > 70:
            momentum_desc = "🔥 超買（過熱）"
        elif rsi_value < 30:
            momentum_desc = "❄️ 超賣（過冷）"
        elif 45 <= rsi_value <= 55:
            momentum_desc = "⚖️ 中性（無明確方向）"
        else:
            momentum_desc = "適中"
    else:
        momentum_desc = "無法判斷"
    
    analysis_parts.append(f"💪 **動量分析：** {momentum_desc}（RSI: {rsi_value_str}）")
    
    # 3. Position Analysis (Bollinger Bands)
    position_desc = ""
    if pd.notna(close_price) and pd.notna(bb_upper) and pd.notna(bb_lower):
        close_val = float(close_price)
        upper_val = float(bb_upper)
        lower_val = float(bb_lower)
        
        if upper_val > lower_val:
            # Calculate distance to bands
            distance_to_upper = abs(close_val - upper_val) / upper_val * 100
            distance_to_lower = abs(close_val - lower_val) / lower_val * 100
            
            if distance_to_upper < 1:
                position_desc = "測試阻力位（接近上軌）"
            elif distance_to_lower < 1:
                position_desc = "測試支撐位（接近下軌）"
            else:
                position_desc = "位於中間通道（無明顯優勢）"
        else:
            position_desc = "無法判斷（布林通道數據異常）"
    else:
        position_desc = "無法判斷"
    
    analysis_parts.append(f"📍 **位置分析：** {position_desc}")

    # 200D long-term support context
    if pd.notna(close_price) and pd.notna(sma200) and float(sma200) != 0:
        dist_200 = (float(close_price) - float(sma200)) / float(sma200) * 100.0
        if abs(dist_200) <= 3.0:
            analysis_parts.append("🛡️ **長線支撐：** 接近 200 天線長線生命線，具強大買盤支撐，不宜殺跌。")
    
    return "\n\n".join(analysis_parts)


def get_analysis_text(df):
    """
    Smart Analyst Commentary - Explains the "Why" behind the market status and signals.
    Returns detailed commentary in Traditional Chinese.
    """
    if len(df) < 1:
        return "❌ 數據不足，無法進行分析"
    
    latest = df.iloc[-1]
    
    current_adx = latest.get('adx', pd.NA)
    pdi = latest.get('dmi_plus', pd.NA)
    mdi = latest.get('dmi_minus', pd.NA)
    rsi = latest.get('rsi', pd.NA)
    close_price = latest.get('close', pd.NA)
    bb_upper = latest.get('bb_upper', pd.NA)
    bb_lower = latest.get('bb_lower', pd.NA)
    
    commentary_parts = []
    
    # 1. Trend Analysis with Emoji
    if pd.notna(current_adx) and pd.notna(pdi) and pd.notna(mdi):
        adx_val = float(current_adx)
        pdi_val = float(pdi)
        mdi_val = float(mdi)
        
        if adx_val > 30:
            if pdi_val > mdi_val:
                commentary_parts.append("🚀 **趨勢：強勢上升趨勢**")
                commentary_parts.append("市場呈現強勁的多頭動能，上升趨勢明確且持續。")
            else:
                commentary_parts.append("📉 **趨勢：強勢下降趨勢**")
                commentary_parts.append("市場呈現強勁的空頭動能，下降趨勢明確且持續。")
        elif adx_val < 25:
            commentary_parts.append("📊 **趨勢：橫盤整理 / 弱勢趨勢**")
            commentary_parts.append("市場缺乏明確方向，價格在區間內震盪，適合均值回歸策略。")
        else:
            commentary_parts.append("⚡ **趨勢：過渡期 / 中等趨勢**")
            commentary_parts.append("市場處於趨勢轉換階段，建議謹慎觀察，等待更明確的信號。")
    
    # 2. Momentum Analysis
    if pd.notna(rsi):
        rsi_val = float(rsi)
        if rsi_val > 70:
            commentary_parts.append("🔥 **動量：超買狀態**")
            commentary_parts.append("RSI 顯示市場過熱，價格可能面臨回調壓力。")
        elif rsi_val < 30:
            commentary_parts.append("❄️ **動量：超賣狀態**")
            commentary_parts.append("RSI 顯示市場過冷，價格可能出現反彈機會。")
        elif 45 <= rsi_val <= 55:
            commentary_parts.append("⚖️ **動量：中性狀態**")
            commentary_parts.append("RSI 處於中性區域，動量指標無明顯偏向。")
        else:
            commentary_parts.append("💪 **動量：適中**")
            commentary_parts.append("RSI 顯示動量適中，市場情緒平衡。")
    
    # 3. Action Explanation (will be enhanced by signal generation)
    commentary_parts.append("")
    commentary_parts.append("💡 **策略建議：**")
    
    return "\n\n".join(commentary_parts)


def generate_trading_signal(df):
    """
    Generate trading signal with Trend-Following and Mean-Reversion strategies.
    
    Scenarios:
    A: RANGE MARKET (ADX < 25) -> Mean Reversion
    B: STRONG UPTREND (ADX > 30 & PDI > MDI) -> Trend Following (Short Put)
    C: STRONG DOWNTREND (ADX > 30 & MDI > PDI) -> Trend Following (Short Call)
    D: TRANSITION (ADX 25-30) -> Wait/Caution
    """
    if len(df) < 2:
        return {
            'advice': '❌ 錯誤：數據不足，無法進行分析',
            'signal_type': 'error',
            'details': {},
            'strategy_type': None,
            'commentary': None
        }
    
    latest = df.iloc[-1]
    
    current_adx = latest['adx']
    adx_slope = latest['adx_slope']
    close_price = latest['close']
    rsi = latest['rsi']
    bb_lower = latest['bb_lower']
    bb_upper = latest['bb_upper']
    is_pin_bar = latest['is_pin_bar']
    pdi = latest.get('dmi_plus', 0)
    mdi = latest.get('dmi_minus', 0)
    
    if pd.isna(current_adx) or pd.isna(adx_slope) or pd.isna(close_price):
        return {
            'advice': '❌ 錯誤：缺少技術指標數據',
            'signal_type': 'error',
            'details': {},
            'strategy_type': None,
            'commentary': None
        }
    
    # Initialize strike prices
    suggested_put_strike = None
    suggested_call_strike = None
    atr = latest.get('atr', 0)
    sma200 = latest.get('sma200', pd.NA)
    rvol = latest.get('rvol', pd.NA)
    macd_line = latest.get('macd_line', pd.NA)
    macd_hist = latest.get('macd_hist', pd.NA)
    low_20 = df['low'].tail(20).min() if 'low' in df.columns and len(df) >= 20 else pd.NA
    has_valid_data = pd.notna(atr) and pd.notna(close_price) and pd.notna(bb_lower) and pd.notna(bb_upper)
    
    details = {
        'close_price': float(close_price),
        'rsi': float(rsi),
        'adx': float(current_adx),
        'adx_slope': float(adx_slope),
        'dmi_plus': float(pdi) if pd.notna(pdi) else 0,
        'dmi_minus': float(mdi) if pd.notna(mdi) else 0,
        'atr': float(atr) if pd.notna(atr) else 0,
        'bb_upper': float(bb_upper),
        'bb_lower': float(bb_lower),
        'is_pin_bar': bool(is_pin_bar),
        'sma200': float(sma200) if pd.notna(sma200) else None,
        'rvol': float(rvol) if pd.notna(rvol) else None,
        'macd_line': float(macd_line) if pd.notna(macd_line) else None,
        'macd_hist': float(macd_hist) if pd.notna(macd_hist) else None,
        'suggested_put_strike': None,
        'suggested_call_strike': None
    }
    
    # Get base commentary
    base_commentary = get_analysis_text(df)
    commentary = base_commentary

    # ---- Rule 1: Exhaustion filter (物極必反) ----
    exhaustion = False
    if pd.notna(current_adx) and pd.notna(rsi):
        if current_adx > 45 and (rsi < 25 or rsi > 75):
            exhaustion = True
            commentary += "\n\n⚠️ **趨勢衰竭 (Exhaustion)：** ADX 過高且 RSI 極端，趨勢可能接近尾聲。"
            if rsi < 25:
                commentary += "\n🔄 **反轉加分：** 超賣狀態，回彈潛力上升（+1.5 reversal bias）。"

    # ---- Rule 2: Volume-price divergence (low volume test) ----
    low_volume_test = False
    if pd.notna(low_20) and pd.notna(rvol):
        if close_price <= float(low_20) and float(rvol) < 0.5:
            low_volume_test = True
            commentary += "\n\n🧪 **低量測底/縮量空頭陷阱：** 無量下跌，大戶未動，謹防報復性抽升。"

    # ---- Rule 3: 200DMA iron support ----
    near_sma200_support = False
    dist_sma200 = None
    if pd.notna(sma200) and float(sma200) != 0:
        dist_sma200 = (float(close_price) - float(sma200)) / float(sma200) * 100.0
        if abs(dist_sma200) <= 3.0:
            near_sma200_support = True
            commentary += "\n\n🛡️ **200 天線守護：** 接近 200 天線長線生命線，具強大買盤支撐，不宜殺跌。"

    # ---- Rule 4: MACD histogram improving while below zero-line ----
    macd_improving = False
    if len(df) >= 3 and pd.notna(macd_line):
        h0 = df['macd_hist'].iloc[-1] if 'macd_hist' in df.columns else pd.NA
        h1 = df['macd_hist'].iloc[-2] if 'macd_hist' in df.columns else pd.NA
        h2 = df['macd_hist'].iloc[-3] if 'macd_hist' in df.columns else pd.NA
        if pd.notna(h0) and pd.notna(h1) and pd.notna(h2):
            if float(macd_line) < 0 and float(h0) > float(h1) > float(h2):
                macd_improving = True
                commentary += "\n\n📈 **Momentum Improving (跌勢放緩)：** MACD 柱狀圖連續改善，動能轉折中。"
                commentary += "\n策略建議由止蝕轉為：考慮現金擔保沽期權 / 反彈部署。"

    # Final summary rule for report generator
    if pd.notna(current_adx) and pd.notna(rsi):
        if current_adx > 45 and rsi < 30 and dist_sma200 is not None and abs(dist_sma200) < 5:
            commentary += "\n\n📋 **Report Status:** Oversold - Potential Reversal"
            commentary += "\n✅ **Recommended Action:** Wait for Rebound / Recommend Cash Secured Put"
    
    # SCENARIO B: STRONG UPTREND (ADX > 30 & PDI > MDI) -> Trend Following
    if current_adx > 30 and pd.notna(pdi) and pd.notna(mdi) and pdi > mdi and not exhaustion:
        # Suggest SHORT PUT (Bullish) - Trading with the trend
        # AGGRESSIVE: Use 1.5x ATR (ignore Lower Band as it's too far away)
        if has_valid_data:
            suggested_put_strike = close_price - (1.5 * atr)
            details['suggested_put_strike'] = float(suggested_put_strike)
        
        commentary += "\n\n✅ **策略：順勢交易（趨勢跟隨）**"
        commentary += "\n趨勢強勁且向上，適合賣出認沽期權。"
        commentary += "\n**理由：** 趨勢明確向上，支撐位持續上升，賣出認沽期權相對安全。"
        commentary += "\n**目標行使價：** 收盤價減 1.5 倍 ATR（積極策略，獲取更好溢價）。"
        
        return {
            'advice': '🟢 訊號：賣出認沽期權（趨勢跟隨策略）',
            'signal_type': 'buy',
            'details': details,
            'strategy_type': 'trend_following',
            'commentary': commentary
        }
    
    # SCENARIO C: STRONG DOWNTREND (ADX > 30 & MDI > PDI) -> Trend Following
    if current_adx > 30 and pd.notna(pdi) and pd.notna(mdi) and mdi > pdi and not exhaustion:
        # Suggest SHORT CALL (Bearish) - Trading with the trend
        # AGGRESSIVE: Use 1.5x ATR (ignore Upper Band as it's too far away)
        if has_valid_data:
            suggested_call_strike = close_price + (1.5 * atr)
            details['suggested_call_strike'] = float(suggested_call_strike)
        
        commentary += "\n\n✅ **策略：順勢交易（趨勢跟隨）**"
        commentary += "\n趨勢強勁且向下，適合賣出認購期權。"
        commentary += "\n**理由：** 趨勢明確向下，阻力位持續下降，賣出認購期權相對安全。"
        commentary += "\n**目標行使價：** 收盤價加 1.5 倍 ATR（積極策略，獲取更好溢價）。"
        
        return {
            'advice': '🔴 訊號：賣出認購期權（趨勢跟隨策略）',
            'signal_type': 'sell',
            'details': details,
            'strategy_type': 'trend_following',
            'commentary': commentary
        }
    
    # SCENARIO D: TRANSITION (ADX between 25-30) -> Wait/Caution
    if 25 <= current_adx <= 30:
        commentary += "\n\n⚠️ **策略：等待 / 謹慎觀察**"
        commentary += "\n市場處於趨勢轉換期，ADX 在 25-30 之間，建議等待更明確的信號。"
        commentary += "\n**理由：** 趨勢強度中等，方向可能轉換，此時交易風險較高。"
        
        return {
            'advice': '☕ 等待：趨勢轉換期，建議謹慎觀察',
            'signal_type': 'wait',
            'details': details,
            'strategy_type': 'transition',
            'commentary': commentary
        }
    
    # SCENARIO A: RANGE MARKET (ADX < 25) -> Mean Reversion (Original Logic)
    if current_adx < 25:
        # Logic B: SHORT PUT SIGNAL (Mean Reversion)
        if close_price <= bb_lower and (rsi < 30 or is_pin_bar):
            reason_parts = []
            if close_price <= bb_lower:
                reason_parts.append("超賣")
            if rsi < 30:
                reason_parts.append("RSI < 30")
            if is_pin_bar:
                reason_parts.append("看漲針形")
            reason = " + ".join(reason_parts)
            
            if has_valid_data:
                put_strike_1 = close_price - (2 * atr)
                put_strike_2 = bb_lower
                suggested_put_strike = min(put_strike_1, put_strike_2)
                details['suggested_put_strike'] = float(suggested_put_strike)
            
            commentary += "\n\n✅ **策略：均值回歸**"
            commentary += "\n市場處於橫盤整理，價格接近下軌，適合賣出認沽期權。"
            commentary += f"\n**理由：** {reason}，預期價格回歸均值。"
            commentary += "\n**目標行使價：** 使用布林下軌或收盤價減 2 倍 ATR。"
            
            return {
                'advice': f'🟢 訊號：賣出認沽期權（均值回歸策略，原因：{reason}）',
                'signal_type': 'buy',
                'details': details,
                'strategy_type': 'mean_reversion',
                'commentary': commentary
            }
        
        # Logic C: SHORT CALL SIGNAL (Mean Reversion)
        if close_price >= bb_upper or rsi > 70:
            reason_parts = []
            if close_price >= bb_upper:
                reason_parts.append("超買")
            if rsi > 70:
                reason_parts.append("RSI > 70")
            reason = " + ".join(reason_parts)
            
            if has_valid_data:
                call_strike_1 = close_price + (2 * atr)
                call_strike_2 = bb_upper
                suggested_call_strike = max(call_strike_1, call_strike_2)
                details['suggested_call_strike'] = float(suggested_call_strike)
            
            commentary += "\n\n✅ **策略：均值回歸**"
            commentary += "\n市場處於橫盤整理，價格接近上軌，適合賣出認購期權。"
            commentary += f"\n**理由：** {reason}，預期價格回歸均值。"
            commentary += "\n**目標行使價：** 使用布林上軌或收盤價加 2 倍 ATR。"
            
            if low_volume_test or near_sma200_support or macd_improving:
                return {
                    'advice': '⚖️ 中性觀察：跌勢/升勢動能轉弱，先觀察反彈確認',
                    'signal_type': 'wait',
                    'details': details,
                    'strategy_type': 'watch_neutral',
                    'commentary': commentary
                }
            return {
                'advice': f'🔴 訊號：賣出認購期權（均值回歸策略，原因：{reason}）',
                'signal_type': 'sell',
                'details': details,
                'strategy_type': 'mean_reversion',
                'commentary': commentary
            }
    
    # Default: NO ACTION
    if low_volume_test or near_sma200_support or macd_improving or exhaustion:
        commentary += "\n\n⚖️ **策略：中性觀察 / 等待確認**"
        commentary += "\n避免在疑似末段趨勢位置追殺，等待反彈或二次確認。"
    else:
        commentary += "\n\n☕ **策略：等待**"
    commentary += "\n目前無明確的交易訊號，建議繼續觀察市場變化。"
    
    return {
        'advice': '☕ 等待：無明確訊號',
        'signal_type': 'wait',
        'details': details,
        'strategy_type': 'none',
        'commentary': commentary
    }


def normalize_stock_code(input_code):
    """
    Normalize stock code input to Yahoo Finance format.
    
    Examples:
        "700" -> "0700.HK"
        "00700" -> "0700.HK"
        "HK.00700" -> "0700.HK"
        "AAPL" -> "AAPL"
        "US.AAPL" -> "AAPL"
    
    Args:
        input_code: User input (e.g., "700", "00700", "HK.00700", "AAPL", "US.AAPL")
    
    Returns:
        Normalized stock code in Yahoo Finance format
    """
    input_code = input_code.strip().upper()
    
    # Handle HK stocks (Futu format: HK.00700 or just 00700)
    if input_code.startswith('HK.'):
        # Extract the number part (e.g., "00700" from "HK.00700")
        # Yahoo Finance requires 4-digit format with leading zeros (e.g., "0700.HK")
        number_part = input_code[3:].zfill(4)  # Pad to 4 digits with leading zeros
        return f"{number_part}.HK"
    
    # Handle US stocks (Futu format: US.AAPL)
    if input_code.startswith('US.'):
        # Extract the ticker (e.g., "AAPL" from "US.AAPL")
        return input_code[3:]
    
    # Check if it's a number (HK stock like "700" or "00700")
    if input_code.isdigit():
        # Yahoo Finance requires 4-digit format with leading zeros (e.g., "0700.HK")
        number_part = input_code.zfill(4)  # Pad to 4 digits with leading zeros
        return f"{number_part}.HK"
    
    # Check if it's all letters (likely US stock)
    if input_code.isalpha():
        return input_code
    
    # If mixed or unclear, try to extract numbers for HK stock
    digits = ''.join(filter(str.isdigit, input_code))
    if digits:
        # Yahoo Finance requires 4-digit format with leading zeros
        number_part = digits.zfill(4)  # Pad to 4 digits with leading zeros
        return f"{number_part}.HK"
    
    # Default: assume it's a US stock code (return as is)
    return input_code


def analyze_stock(stock_code, original_input=None):
    """Analyze a stock and return trading signal using Yahoo Finance."""
    if original_input is None:
        original_input = stock_code
    
    try:
        # Fetch 5 years of daily data using Yahoo Finance
        data = yf.download(stock_code, period="5y", interval="1d", progress=False)
        
        if data.empty:
            return {
                'success': False,
                'error': f'No data returned for {stock_code}'
            }
        
        # Handle MultiIndex columns from Yahoo Finance
        # Yahoo Finance returns MultiIndex columns like ('Open', 'Close', etc.) when downloading multiple tickers
        # For single ticker, it's usually a simple Index, but we handle both cases
        if isinstance(data.columns, pd.MultiIndex):
            # Flatten MultiIndex: take the first level (usually the column name)
            data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]
        
        # Rename columns to lowercase to match expected format
        column_mapping = {
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
            'Adj Close': 'adj_close'  # Keep for reference but we'll use 'close'
        }
        
        # Rename columns
        df = data.copy()
        df.columns = [column_mapping.get(col, col.lower()) for col in df.columns]
        
        # Ensure we have the required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return {
                'success': False,
                'error': f'Missing required columns: {missing_cols}'
            }
        
        # Reset index to make Date a column (Yahoo Finance uses Date as index)
        # This ensures we have a 'time' column for consistency with the rest of the code
        df = df.reset_index()
        
        # Rename the date column to 'time' if it exists
        # Yahoo Finance typically names the index 'Date' after reset_index
        if 'Date' in df.columns:
            df['time'] = df['Date']
        elif len(df.columns) > 0 and isinstance(df.columns[0], str) and 'date' in df.columns[0].lower():
            # Handle case where column might be named differently
            df['time'] = df[df.columns[0]]
        else:
            # Fallback: use index as time
            df['time'] = df.index
        
        # Sort by time to ensure chronological order
        df = df.sort_values('time').reset_index(drop=True)
        
        # Get stock basic info (name, current price) from yfinance
        stock_name = stock_code  # Default to stock code if name not available
        current_price = None
        try:
            ticker = yf.Ticker(stock_code)
            info = ticker.info
            if 'longName' in info:
                stock_name = info['longName']
            elif 'shortName' in info:
                stock_name = info['shortName']
            elif 'symbol' in info:
                stock_name = info['symbol']
            
            # Get current price from info or latest close
            if 'currentPrice' in info:
                current_price = float(info['currentPrice'])
            elif 'regularMarketPrice' in info:
                current_price = float(info['regularMarketPrice'])
        except Exception as e:
            print(f"Warning: Could not fetch stock info: {e}")
        
        # Calculate indicators
        df = calculate_indicators(df)
        
        # Get latest price if not available from snapshot
        if current_price is None:
            current_price = float(df.iloc[-1]['close'])
        
        # Calculate price change from yesterday's close
        price_change = None
        price_change_percent = None
        if len(df) >= 2:
            yesterday_close = float(df.iloc[-2]['close'])
            price_change = current_price - yesterday_close
            if yesterday_close > 0:
                price_change_percent = (price_change / yesterday_close) * 100
        
        # Prepare price history for Bollinger Bands chart (last 50 days)
        price_history = df.tail(50).copy()
        
        # Format dates for chart (extract date part if datetime)
        dates = []
        if 'time' in price_history.columns:
            for dt in price_history['time']:
                if pd.notna(dt):
                    # Convert to string, extract date part if it's a datetime
                    dt_str = str(dt)
                    if ' ' in dt_str:
                        dt_str = dt_str.split(' ')[0]  # Get date part only
                    dates.append(dt_str)
                else:
                    dates.append('')
        else:
            dates = [f'Day {i+1}' for i in range(len(price_history))]
        
        chart_data = {
            'dates': dates,
            'close_prices': [float(x) for x in price_history['close'].tolist() if pd.notna(x)],
            'bb_upper': [float(x) for x in price_history['bb_upper'].tolist() if pd.notna(x)],
            'bb_middle': [float(x) for x in price_history['bb_middle'].tolist() if pd.notna(x)],
            'bb_lower': [float(x) for x in price_history['bb_lower'].tolist() if pd.notna(x)]
        }
        
        # Generate signal
        signal = generate_trading_signal(df)
        
        # Generate detailed market analysis
        market_analysis = generate_analysis(df)
        
        # Use commentary from signal if available, otherwise use market_analysis
        analyst_commentary = signal.get('commentary', market_analysis) if signal else market_analysis
        
        return {
            'success': True,
            'stock_code': stock_code,
            'stock_name': stock_name,
            'current_price': current_price,
            'price_change': price_change,
            'price_change_percent': price_change_percent,
            'original_input': original_input,
            'data_points': len(df),
            'chart_data': chart_data,
            'signal': signal,
            'market_analysis': market_analysis,
            'analyst_commentary': analyst_commentary,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@app.route('/')
def index():
    """Main page."""
    try:
        return render_template('index.html')
    except Exception as e:
        return f"Error loading template: {str(e)}", 500


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'version': VERSION,
        'message': 'SCSP神器 is running'
    })


@app.route('/analyze', methods=['POST'])
def analyze():
    """Analyze stock endpoint."""
    data = request.get_json()
    input_code = data.get('stock_code', '').strip()
    
    if not input_code:
        return jsonify({
            'success': False,
            'error': 'Please enter a stock code'
        })
    
    # Normalize the stock code (e.g., "700" -> "HK.00700", "AAPL" -> "US.AAPL")
    stock_code = normalize_stock_code(input_code)
    
    result = analyze_stock(stock_code, original_input=input_code)
    return jsonify(result)


if __name__ == '__main__':
    import socket
    
    # Check if port 5000 is available
    port = 5000
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    
    if result == 0:
        # Port is in use, try to find and kill the process
        import subprocess
        try:
            # Find process using port 5000
            result = subprocess.run(['lsof', '-ti:5000'], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                print(f"⚠️  發現端口 5000 被佔用，正在清理進程: {', '.join(pids)}")
                for pid in pids:
                    try:
                        subprocess.run(['kill', '-9', pid], check=False)
                    except:
                        pass
                import time
                time.sleep(2)
        except:
            pass
    
    print("═══════════════════════════════════════════════════════════")
    print("           SCSP神器 - 交易策略分析器")
    print(f"           版本: {VERSION}")
    print("═══════════════════════════════════════════════════════════")
    print("🚀 正在啟動 Web 應用程式...")
    print("📱 請在瀏覽器中打開: http://127.0.0.1:5000")
    print("📊 數據來源: Yahoo Finance")
    print("═══════════════════════════════════════════════════════════")
    print("")
    
    # Try to run on port 5000, if it fails, try 5001
    try:
        print("🌐 啟動 Flask 伺服器...")
        app.run(debug=True, host='127.0.0.1', port=5000, use_reloader=False, threaded=True)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"⚠️  端口 5000 被佔用，嘗試使用端口 5001...")
            print("📱 請在瀏覽器中打開: http://127.0.0.1:5001")
            app.run(debug=True, host='127.0.0.1', port=5001, use_reloader=False, threaded=True)
        else:
            print(f"❌ 錯誤: {e}")
            raise
