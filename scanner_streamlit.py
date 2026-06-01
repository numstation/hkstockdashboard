#!/usr/bin/env python3
"""
==========================================================================
  Veteran v4.0 — Streamlit Scanner + Backtest
==========================================================================
  Scanner: same logic as daily_scanner.py (Core + Score 2/3)
  Backtest: same logic as backtest_options.py (Veteran backtest engine)
  Run:   streamlit run scanner_streamlit.py
  Deps:  pip install streamlit yfinance pandas ta
==========================================================================
"""

import sys
from pathlib import Path

# Ensure the app directory is on Python path (so backtest_options + daily_scanner are found)
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import inspect
import importlib.util
import time
import pandas as pd
import streamlit as st
import yfinance as yf

# Page config must be the first Streamlit command (required for layout/theme)
st.set_page_config(
    page_title="HK Stock Hunter Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Yahoo Finance–inspired light UI (Scanner + Backtest): clean, data-dense, no forced dark mode
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    .stApp, [data-testid="stAppViewContainer"] { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
    .main .block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1280px; }
    /* Soft page chrome (respects Streamlit theme; stays light) */
    section[data-testid="stSidebar"] { background: #fafbfc; border-right: 1px solid #e8e8e8; }
    /* Primary actions — Yahoo-adjacent purple accent */
    .stButton > button[kind="primary"] {
        background-color: #6001d2 !important;
        border: none !important;
        color: #fff !important;
        font-weight: 600 !important;
        border-radius: 6px !important;
        padding: 0.45rem 1.1rem !important;
    }
    .stButton > button[kind="primary"]:hover { background-color: #4c00ad !important; }
    /* Tabs — underline style */
    [data-baseweb="tab-list"] { gap: 0.25rem; border-bottom: 1px solid #e5e7eb !important; background: transparent !important; }
    [data-baseweb="tab"] { font-weight: 600 !important; color: #6b7280 !important; padding: 0.5rem 0.75rem !important; }
    [data-baseweb="tab"][aria-selected="true"] { color: #6001d2 !important; border-bottom: 2px solid #6001d2 !important; }
    /* Inputs — subtle borders */
    .stSelectbox > div > div, .stNumberInput > div > div > input {
        border-radius: 6px !important;
        border-color: #d1d5db !important;
    }
    /* Expanders — card-like */
    [data-testid="stExpander"] details {
        border: 1px solid #e5e7eb !important;
        border-radius: 8px !important;
        background: #fff !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
    }
    [data-testid="stExpander"] summary { font-weight: 600 !important; color: #111827 !important; }
    /* Metrics */
    [data-testid="stVerticalBlock"] > div:has([data-testid="stMetric"]) { padding: 0.35rem 0; }
    div[data-testid="metric-container"] {
        background: #fff !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 8px !important;
        padding: 0.75rem 1rem !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05) !important;
    }
    div[data-testid="stSuccess"], div[data-testid="stWarning"] {
        border-radius: 8px; padding: 1rem 1.25rem; margin: 0.75rem 0;
        border-left: 4px solid;
    }
    div[data-testid="stSuccess"] { border-left-color: #059669; }
    div[data-testid="stWarning"] { border-left-color: #d97706; }
    /* Section headers (HTML snippets) */
    .yf-section-title {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #6b7280;
        margin: 0 0 0.15rem 0;
    }
    .yf-section-sub {
        font-size: 0.8rem;
        color: #9ca3af;
        margin: 0 0 0.75rem 0;
        line-height: 1.35;
    }
    .yf-page-kicker {
        font-size: 0.8rem;
        color: #6b7280;
        margin: -0.35rem 0 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Reuse scanner logic from the existing CLI script
try:
    from daily_scanner import (
        analyze_stock,
        technical_universe_row,
        _fetch_ohlcv,
        TECH_TICKERS,
        HSI_TICKERS,
        HKCEI_TICKERS,
        HK_TICKERS,
        HK_UNIVERSE_TAG,
        US_TICKERS,
    )
except ImportError as e:
    st.error(f"Failed to load daily_scanner: {e}")
    st.info("Ensure daily_scanner.py is in the same folder and has no syntax errors. Dependencies: yfinance, pandas, ta.")
    st.stop()

# Yahoo Finance: use a browser-like session (reduces empty history / HTTP issues).
try:
    import yfinance_bootstrap  # noqa: E402

    yfinance_bootstrap.enable()
except Exception:
    pass

# JSON export lives in stocktrackeryahoo/app.py (single source of truth for SSG output).
_scsp_dir = _here / "stocktrackeryahoo"
_scsp_dir_str = str(_scsp_dir)
if _scsp_dir_str not in sys.path:
    sys.path.insert(0, _scsp_dir_str)
# app.py imports Flask at module level; only stub when Flask is not installed.
try:
    import flask  # noqa: F401  # type: ignore[import-untyped]
except ImportError:
    import headless_flask_stub  # noqa: E402  # pyright: ignore[reportMissingImports]

    headless_flask_stub.install()
_spec_app = importlib.util.spec_from_file_location("scsp_web_app", _scsp_dir / "app.py")
_scsp_web = importlib.util.module_from_spec(_spec_app)
_spec_app.loader.exec_module(_scsp_web)
export_results_to_json = _scsp_web.export_results_to_json
export_signals_history_to_json = _scsp_web.export_signals_history_to_json
export_trade_signals_history_to_json = _scsp_web.export_trade_signals_history_to_json
append_future_log_to_json = _scsp_web.append_future_log_to_json
export_macro_snapshot_to_json = _scsp_web.export_macro_snapshot_to_json


def _enrich_with_tech_score(df: pd.DataFrame, score_model: str = "sell_put") -> pd.DataFrame:
    """
    Add universe score fields to scanner result rows so website table keeps Score populated
    even when running from Streamlit signal mode.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Ticker" not in out.columns:
        return out
    tickers = [str(t).strip() for t in out["Ticker"].tolist() if str(t).strip()]
    if not tickers:
        return out
    score_map: dict[str, dict] = {}
    for t in tickers:
        if t in score_map:
            continue
        try:
            score_map[t] = technical_universe_row(t, score_model=score_model)
        except Exception:
            score_map[t] = {}
    ticker_series = out["Ticker"].astype(str)

    def _overlay_field(field: str, default):
        if field in out.columns:
            base = out[field].tolist()
        else:
            base = [default] * len(out)
        merged = []
        for t, b in zip(ticker_series, base):
            v = (score_map.get(t, {}) or {}).get(field)
            merged.append(b if v is None else v)
        out[field] = merged

    _overlay_field("tech_score", None)
    _overlay_field("adx_strength", "—")
    _overlay_field("macd_histogram_status", "—")
    _overlay_field("ai_strategy_comment", "")

    # Force Streamlit-exported rows to follow the same score-band grading as universe mode.
    # Without this, manual scanner results can keep legacy BUY/SELL labels from signal mode.
    _overlay_field("Signal", "N/A")
    _overlay_field("Reason", "")
    _overlay_field("MACD_Sign", "N/A")
    _overlay_field("RS_20d", "—")
    _overlay_field("VWAP", "—")
    _overlay_field("score_model", score_model)
    _overlay_field("HS_Index", "N/A")
    return out


def _is_manual_strategy_label(label: str):
    """Manual mode: do not rely on exact leading emoji (VS16 / font substitution can break startswith/==)."""
    if not label:
        return False
    low = label.strip().lower()
    return "手動" in label and "manual" in low


def _strategy_preset_slug(label: str):
    """Map strategy radio label to engine slug using Chinese or English tags (stable across emoji variants)."""
    if not label or _is_manual_strategy_label(label):
        return None
    low = label.strip().lower()
    if "推土機起步" in label or "(trend confirmation)" in low:
        return "trend_confirmation"
    if "地牢撈底" in label or "(capitulation bottom)" in low:
        return "capitulation"
    if "良性回抽" in label or "(healthy pullback)" in low:
        return "pullback"
    if "rs破位" in low or "領頭羊" in label or "(rs breakout)" in low:
        return "rs_breakout"
    if "macd 動能爆發" in low or "(macd expansion)" in low:
        return "macd_breakout"
    if "絕地反擊" in label or "(reversal breakout)" in low:
        return "reversal_breakout"
    return None


def _engine_op_to_label(op: str) -> str:
    """Map backtest-style 'off' / '>' to Streamlit selectbox labels."""
    if op is None or str(op).strip().lower() in ("", "off"):
        return "Off"
    return str(op).strip()


def _stoch_vs_yesterday_ui_to_op(label) -> str:
    """Map scanner/backtest UI label to engine op: today vs yesterday bar."""
    if label is None:
        return "off"
    s = str(label).strip()
    if s == "Off":
        return "off"
    if s in ("K > K yesterday", "D > D yesterday"):
        return ">"
    if s in ("K < K yesterday", "D < D yesterday"):
        return "<"
    return "off"


def _adx_range_to_ui(adx_min, adx_max) -> tuple[str, int]:
    """Convert engine ADX min/max range to one UI operator+value."""
    mn = int(adx_min) if adx_min is not None else 0
    mx = int(adx_max) if adx_max is not None else 100
    if mn > 0 and mx >= 100:
        return ">=", mn
    if mn <= 0 and mx < 100:
        return "<=", mx
    return "Off", max(mn, 10)


def _adx_ui_to_range(op_label, value) -> tuple[int, int]:
    """Convert UI ADX operator+value back to engine min/max range."""
    op = str(op_label).strip() if op_label is not None else "Off"
    v = int(value)
    if op in (">", ">="):
        return v, 100
    if op in ("<", "<="):
        return 0, v
    return 0, 100


# One source of truth for preset 1–6 entry fields (matches backtest_options _apply_preset + MACD / reversal flags).
_PRESET_ENTRY = {
    "trend_confirmation": {
        "close_vs_sma20": ">", "close_vs_sma50": "off", "obv_vs_obv_ema20": "off", "obv_vs_obv_5ma": "off",
        "close_vs_vwap": ">=", "mfi_vs_rsi": "mfi>rsi", "rsi_op": ">=", "rsi_value": 50.0,
        "rs_20d_op": "off", "rs_20d_value": 0.0, "mfi_op": ">=", "mfi_value": 50.0,
        "rvol_op": ">=", "rvol_value": 1.2, "adx_slope_op": ">", "gap_op": ">=", "gap_value": 5.0,
        "stoch_k_op": "<=", "stoch_k_value": 80.0, "spread_op": ">=", "spread_value": 0.0,
        "core_require_pdi_mdi": True, "pdi_buffer": 0.0, "adx_min": 25, "adx_max": 60, "core_require_adx_awakening": True,
        "macd_sign": "Off", "macd_trend": "Off", "entry_reversal": False,
    },
    "capitulation": {
        "close_vs_sma20": "<=", "close_vs_sma50": "off", "obv_vs_obv_ema20": "off", "obv_vs_obv_5ma": "off",
        "close_vs_vwap": "<=", "mfi_vs_rsi": "rsi>mfi", "rsi_op": "<=", "rsi_value": 35.0,
        "rs_20d_op": "off", "rs_20d_value": 0.0, "mfi_op": "<=", "mfi_value": 25.0,
        "rvol_op": ">=", "rvol_value": 1.5, "adx_slope_op": "off", "gap_op": "off", "gap_value": 0.0,
        "stoch_k_op": "<=", "stoch_k_value": 30.0, "spread_op": "<=", "spread_value": -5.0,
        "core_require_pdi_mdi": False, "pdi_buffer": -10.0, "adx_min": 10, "adx_max": 35, "core_require_adx_awakening": False,
        "macd_sign": "Off", "macd_trend": "Off", "entry_reversal": False,
    },
    "pullback": {
        "close_vs_sma20": ">=", "close_vs_sma50": "off", "obv_vs_obv_ema20": "off", "obv_vs_obv_5ma": "off",
        "close_vs_vwap": ">=", "mfi_vs_rsi": "off", "rsi_op": ">=", "rsi_value": 45.0,
        "rs_20d_op": ">", "rs_20d_value": 0.0, "mfi_op": ">=", "mfi_value": 45.0,
        "rvol_op": "<=", "rvol_value": 1.2, "adx_slope_op": ">", "gap_op": ">=", "gap_value": 3.0,
        "stoch_k_op": "<=", "stoch_k_value": 80.0, "spread_op": ">=", "spread_value": 0.0,
        "core_require_pdi_mdi": True, "pdi_buffer": 0.0, "adx_min": 20, "adx_max": 50, "core_require_adx_awakening": True,
        "macd_sign": "Off", "macd_trend": "Off", "entry_reversal": False,
    },
    "rs_breakout": {
        "close_vs_sma20": ">", "close_vs_sma50": "off", "obv_vs_obv_ema20": "off", "obv_vs_obv_5ma": "off",
        "close_vs_vwap": ">=", "mfi_vs_rsi": "mfi>rsi", "rsi_op": ">=", "rsi_value": 55.0,
        "rs_20d_op": ">=", "rs_20d_value": 5.0, "mfi_op": ">=", "mfi_value": 55.0,
        "rvol_op": ">=", "rvol_value": 1.3, "adx_slope_op": ">", "gap_op": ">=", "gap_value": 5.0,
        "stoch_k_op": ">=", "stoch_k_value": 70.0, "spread_op": ">=", "spread_value": 0.0,
        "core_require_pdi_mdi": True, "pdi_buffer": 0.0, "adx_min": 25, "adx_max": 70, "core_require_adx_awakening": True,
        "macd_sign": "Off", "macd_trend": "Off", "entry_reversal": False,
    },
    "macd_breakout": {
        "close_vs_sma20": "off", "close_vs_sma50": "off", "obv_vs_obv_ema20": "off", "obv_vs_obv_5ma": "off",
        "close_vs_vwap": "off", "mfi_vs_rsi": "off", "rsi_op": "off", "rsi_value": 50.0,
        "rs_20d_op": "off", "rs_20d_value": 0.0, "mfi_op": "off", "mfi_value": 55.0,
        "rvol_op": ">=", "rvol_value": 1.0, "adx_slope_op": "off", "gap_op": "off", "gap_value": 0.0,
        "stoch_k_op": "off", "stoch_k_value": 80.0, "spread_op": "off", "spread_value": 0.0,
        "core_require_pdi_mdi": False, "pdi_buffer": 0.0, "adx_min": 10, "adx_max": 50, "core_require_adx_awakening": False,
        "macd_sign": "Off", "macd_trend": "Turn Green (Cross Up)", "entry_reversal": False,
    },
    "reversal_breakout": {
        "close_vs_sma20": ">", "close_vs_sma50": "off", "obv_vs_obv_ema20": "off", "obv_vs_obv_5ma": "off",
        "close_vs_vwap": "off", "mfi_vs_rsi": "off", "rsi_op": ">", "rsi_value": 40.0,
        "rs_20d_op": "off", "rs_20d_value": 0.0, "mfi_op": "off", "mfi_value": 55.0,
        "rvol_op": ">", "rvol_value": 1.2, "adx_slope_op": "off", "gap_op": "off", "gap_value": 0.0,
        "stoch_k_op": "off", "stoch_k_value": 80.0, "spread_op": "off", "spread_value": 0.0,
        "core_require_pdi_mdi": False, "pdi_buffer": 0.0, "adx_min": 10, "adx_max": 50, "core_require_adx_awakening": False,
        "macd_sign": "Off", "macd_trend": "Higher", "entry_reversal": True,
        "stoch_require_k_gt_d": True,
        "stoch_k_vs_prev_ui": "Off",
        "stoch_d_vs_prev_ui": "Off",
        "stoch_d_op": "off",
        "stoch_d_value": 50.0,
    },
}


def _preset_row(slug: str):
    return _PRESET_ENTRY.get(slug) or {}


def _scan_session_from_preset(slug: str) -> dict:
    r = _preset_row(slug)
    if not r:
        return {}
    _scan_adx_op, _scan_adx_val = _adx_range_to_ui(r.get("adx_min", 0), r.get("adx_max", 100))
    return {
        "scan_close_sma20": _engine_op_to_label(r["close_vs_sma20"]),
        "scan_close_sma50": _engine_op_to_label(r["close_vs_sma50"]),
        "scan_close_vwap": _engine_op_to_label(r["close_vs_vwap"]),
        "scan_rsi_op": _engine_op_to_label(r["rsi_op"]),
        "scan_rsi_val": int(r["rsi_value"]),
        "scan_mfi_op": _engine_op_to_label(r["mfi_op"]),
        "scan_mfi_val": int(r["mfi_value"]),
        "scan_rs_20d_op": _engine_op_to_label(r["rs_20d_op"]),
        "scan_rs_20d_val": float(r["rs_20d_value"]),
        "scan_macd_sign": r["macd_sign"],
        "scan_macd_trend": r["macd_trend"],
        "scan_rvol_op": _engine_op_to_label(r["rvol_op"]),
        "scan_rvol_val": float(r["rvol_value"]),
        "scan_obv_ema": _engine_op_to_label(r["obv_vs_obv_ema20"]),
        "scan_obv_5ma": _engine_op_to_label(r["obv_vs_obv_5ma"]),
        "scan_adx_slope_op": _engine_op_to_label(r["adx_slope_op"]),
        "scan_adx_awakening": bool(r["core_require_adx_awakening"]),
        "scan_adx_op": _scan_adx_op,
        "scan_adx_val": int(_scan_adx_val),
        "scan_gap_op": _engine_op_to_label(r["gap_op"]),
        "scan_gap_val": float(r["gap_value"]),
        "scan_stoch_k_op": _engine_op_to_label(r["stoch_k_op"]),
        "scan_stoch_k_val": float(r["stoch_k_value"]),
        "scan_mfi_vs_rsi_display": {"off": "Off", "mfi>rsi": "MFI > RSI", "rsi>mfi": "RSI > MFI"}.get(
            str(r.get("mfi_vs_rsi", "off")).lower(), "Off"
        ),
        "scan_pdi_buffer": float(r["pdi_buffer"]),
        "scan_stoch_k_gt_d": bool(r.get("stoch_require_k_gt_d", False)),
        "scan_stoch_k_vs_prev": r.get("stoch_k_vs_prev_ui", "Off"),
        "scan_stoch_d_vs_prev": r.get("stoch_d_vs_prev_ui", "Off"),
        "scan_stoch_d_op": _engine_op_to_label(r.get("stoch_d_op", "off")),
        "scan_stoch_d_val": float(r.get("stoch_d_value", 50.0)),
    }


def _bt_session_from_preset(slug: str) -> dict:
    r = _preset_row(slug)
    if not r:
        return {}
    _bt_adx_op, _bt_adx_val = _adx_range_to_ui(r.get("adx_min", 0), r.get("adx_max", 100))
    return {
        "bt_close_sma20": _engine_op_to_label(r["close_vs_sma20"]),
        "bt_close_sma50": _engine_op_to_label(r["close_vs_sma50"]),
        "bt_close_vwap": _engine_op_to_label(r["close_vs_vwap"]),
        "bt_rsi_op": _engine_op_to_label(r["rsi_op"]),
        "bt_rsi_val": int(r["rsi_value"]),
        "bt_mfi_op": _engine_op_to_label(r["mfi_op"]),
        "bt_mfi_val": int(r["mfi_value"]),
        "bt_rs_20d_op": _engine_op_to_label(r["rs_20d_op"]),
        "bt_rs_20d_val": float(r["rs_20d_value"]),
        "bt_macd_sign": r["macd_sign"],
        "bt_macd_trend": r["macd_trend"],
        "bt_rvol_op": _engine_op_to_label(r["rvol_op"]),
        "bt_rvol_val": float(r["rvol_value"]),
        "bt_obv_ema": _engine_op_to_label(r["obv_vs_obv_ema20"]),
        "bt_obv_5ma": _engine_op_to_label(r["obv_vs_obv_5ma"]),
        "bt_adx_slope_op": _engine_op_to_label(r["adx_slope_op"]),
        "core_adx_awakening": bool(r["core_require_adx_awakening"]),
        "bt_adx_op": _bt_adx_op,
        "bt_adx_val": int(_bt_adx_val),
        "bt_gap_op": _engine_op_to_label(r["gap_op"]),
        "bt_gap_val": float(r["gap_value"]),
        "bt_stoch_k_op": _engine_op_to_label(r["stoch_k_op"]),
        "bt_stoch_k_val": float(r["stoch_k_value"]),
        "bt_mfi_vs_rsi_display": {"off": "Off", "mfi>rsi": "MFI > RSI", "rsi>mfi": "RSI > MFI"}.get(
            str(r.get("mfi_vs_rsi", "off")).lower(), "Off"
        ),
        "bt_pdi_buffer": float(r["pdi_buffer"]),
        "bt_entry_use_reversal": bool(r.get("entry_reversal", False)),
        "bt_stoch_k_gt_d": bool(r.get("stoch_require_k_gt_d", False)),
        "bt_stoch_k_vs_prev": r.get("stoch_k_vs_prev_ui", "Off"),
        "bt_stoch_d_vs_prev": r.get("stoch_d_vs_prev_ui", "Off"),
        "bt_stoch_d_op": _engine_op_to_label(r.get("stoch_d_op", "off")),
        "bt_stoch_d_val": float(r.get("stoch_d_value", 50.0)),
    }


def _sync_scanner_widgets_from_preset(slug):
    """When user picks a preset, push template into widget session keys once per preset change."""
    _mark = "_scanner_preset_seed_slug"
    if slug is None:
        st.session_state[_mark] = None
        return
    if st.session_state.get(_mark) == slug:
        return
    for k, v in _scan_session_from_preset(slug).items():
        st.session_state[k] = v
    st.session_state[_mark] = slug


def _sync_backtest_widgets_from_preset(slug):
    _mark = "_backtest_preset_seed_slug"
    if slug is None:
        st.session_state[_mark] = None
        st.session_state["bt_entry_use_reversal"] = False
        return
    if st.session_state.get(_mark) == slug:
        return
    for k, v in _bt_session_from_preset(slug).items():
        st.session_state[k] = v
    st.session_state[_mark] = slug


st.title("📊 HK Stock Hunter Pro")

mode = st.sidebar.radio(
    "Mode",
    ["Scanner", "Backtest", "Stock Analysis"],
    index=0,
    horizontal=True,
)
st.sidebar.divider()

# ========== Stock Analysis — 交易數據分析器 ==========
if mode == "Stock Analysis":
    _stocktracker_dir = _here / "stocktrackeryahoo"
    _streamlit_app_py = _stocktracker_dir / "streamlit_app.py"
    if _streamlit_app_py.is_file():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("stocktracker_streamlit_app", _streamlit_app_py)
            streamlit_app_module = importlib.util.module_from_spec(spec)
            # Ensure the folder is on path so streamlit_app can import its own helpers / use __file__
            if str(_stocktracker_dir) not in sys.path:
                sys.path.insert(0, str(_stocktracker_dir))
            spec.loader.exec_module(streamlit_app_module)
            streamlit_app_module.main()
        except Exception as e:
            st.error(f"Stock Analysis failed to load: {e}")
            import traceback
            st.code(traceback.format_exc())
    elif _stocktracker_dir.is_dir():
        st.warning("**Stock Analysis** folder found but `streamlit_app.py` is missing inside it.")
    else:
        st.warning("**Stock Analysis** folder not found. Add the `stocktrackeryahoo` folder next to scanner_streamlit.py and push to Railway.")

# ========== Scanner ==========
elif mode == "Scanner":
    st.markdown(
        '<p class="yf-page-kicker">Screening · Pick a universe, choose a strategy, tune BUY/SELL rules, then run.</p>',
        unsafe_allow_html=True,
    )
    st.sidebar.header("Ticker source")
    source_options = ["Tech", "HSI", "HKCEI", "HK stock list", "US Top 300", "Custom (type below)"]
    source = st.sidebar.radio("Choose list", source_options, index=0)

    tickers = []
    if source == "Tech":
        tickers = TECH_TICKERS.copy()
        st.sidebar.info(f"Using {len(tickers)} Tech tickers.")
    elif source == "HSI":
        tickers = HSI_TICKERS.copy()
        st.sidebar.info(f"Using {len(tickers)} HSI tickers.")
    elif source == "HKCEI":
        tickers = HKCEI_TICKERS.copy()
        st.sidebar.info(f"Using {len(tickers)} HKCEI tickers.")
    elif source == "HK stock list":
        tickers = HK_TICKERS.copy()
        st.sidebar.info(f"Using {len(tickers)} HK tickers ({HK_UNIVERSE_TAG}).")
    elif source == "US Top 300":
        tickers = US_TICKERS.copy()
        st.sidebar.info(f"Using {len(tickers)} US tickers (Top 300 universe).")
    else:
        custom = st.sidebar.text_area(
            "Enter tickers (one per line or comma-separated)",
            placeholder="0700.HK\n9988.HK\nNVDA",
            height=100,
        )
        if custom:
            raw = custom.replace(",", " ").split()
            tickers = [t.strip().upper() for t in raw if t.strip()]
        if not tickers and source == "Custom (type below)":
            st.sidebar.warning("Enter at least one ticker.")

    scan_period = st.sidebar.selectbox("Data lookback", ["3mo", "6mo", "1y", "2y"], index=1, key="scan_period", help="History per ticker.")
    scan_relaxed_mode = st.sidebar.checkbox(
        "Content mode: broaden candidates",
        value=False,
        key="scan_relaxed_mode",
        help="Temporarily relaxes technical filters so you can get more tickers for review/comments.",
    )
    run_diag = st.sidebar.button("Run data diagnostics", key="scan_run_diag", use_container_width=True)
    st.sidebar.divider()
    st.sidebar.metric("Tickers to scan", len(tickers) if tickers else 0)

    if run_diag:
        st.subheader("Scanner diagnostics")
        st.caption(
            f"python={sys.executable} | yfinance={getattr(yf, '__version__', 'unknown')} | tickers={len(tickers)} | period={scan_period}"
        )
        if not tickers:
            st.warning("No tickers selected for diagnostics.")
        else:
            sample = tickers[: min(8, len(tickers))]
            diag_rows = []
            for t in sample:
                raw_rows = -1
                ohlcv_rows = -1
                default_sig = "None"
                err = ""
                try:
                    raw = yf.Ticker(t).history(period=scan_period, auto_adjust=False)
                    raw_rows = 0 if raw is None else len(raw)
                except Exception as e:
                    err = f"raw:{e}"
                try:
                    ohl = _fetch_ohlcv(t, period=scan_period)
                    ohlcv_rows = 0 if ohl is None else len(ohl)
                except Exception as e:
                    err = (err + " | " if err else "") + f"_fetch_ohlcv:{e}"
                try:
                    dres = analyze_stock(t)
                    if dres:
                        default_sig = str(dres.get("Signal", "YES"))
                except Exception as e:
                    err = (err + " | " if err else "") + f"analyze_stock:{e}"
                diag_rows.append(
                    {
                        "ticker": t,
                        "yahoo_rows": raw_rows,
                        "_fetch_ohlcv_rows": ohlcv_rows,
                        "analyze_stock_default": default_sig,
                        "error": err or "",
                    }
                )
            st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)
            ok_raw = sum(1 for r in diag_rows if int(r["yahoo_rows"]) > 0)
            ok_ohl = sum(1 for r in diag_rows if int(r["_fetch_ohlcv_rows"]) >= 50)
            ok_sig = sum(1 for r in diag_rows if r["analyze_stock_default"] != "None")
            st.caption(f"diag summary: yahoo_ok={ok_raw}/{len(diag_rows)} | ohlcv_ok={ok_ohl}/{len(diag_rows)} | signal_ok={ok_sig}/{len(diag_rows)}")

    # ---------- Quant Strategy Mode ----------
    strategy_mode = st.radio(
        "Strategy",
        [
            "🛠️ 手動自訂 (Manual)",
            "🔥 1. 推土機起步 (Trend Confirmation)",
            "🩸 2. 地牢撈底 (Capitulation Bottom)",
            "♻️ 3. 良性回抽 (Healthy Pullback)",
            "🚀 4. RS破位領頭羊 (RS Breakout)",
            "📈 5. MACD 動能爆發 (MACD Expansion)",
            "🌊 6. 絕地反擊 (Reversal Breakout)",
        ],
        horizontal=False,
        key="scan_strategy_mode",
    )
    manual_mode = _is_manual_strategy_label(strategy_mode)
    score_mode_label = st.selectbox(
        "Scoring model",
        ["Sell Put 穩健收租模式", "Buy Stock 極限爆發模式", "Buy Put 恐慌破底模式"],
        index=0,
        key="scan_score_model",
        help="Choose scoring engine used for website tech_score and band labels.",
    )
    if score_mode_label.startswith("Buy Stock"):
        score_model = "buy_stock"
    elif score_mode_label.startswith("Buy Put"):
        score_model = "buy_put"
    else:
        score_model = "sell_put"
    _scan_preset_slug = _strategy_preset_slug(strategy_mode)
    _sync_scanner_widgets_from_preset(None if manual_mode else _scan_preset_slug)

    # ---------- Criteria (Yahoo Finance style) ----------
    OPTS = ["Off", ">", "<", ">=", "<="]

    if not manual_mode and _scan_preset_slug:
        st.caption(
            "已載入此預設的入場條件到下方手動欄位，可直接微調後按 **Run scan**（掃描與預設共用同一套條件邏輯）。"
        )

    st.markdown(
        '<p class="yf-section-title">Entry criteria (single-page manual panel)</p><p class="yf-section-sub">All settings in one compact page. Use Off to disable any condition.</p>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.caption("Trend & Price")
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            scan_close_vs_sma20 = st.selectbox("Close vs SMA20", OPTS, index=0, key="scan_close_sma20", help="Price position relative to 20-day simple moving average.")
        with p2:
            scan_close_vs_sma50 = st.selectbox("Close vs SMA(50)", OPTS, index=0, key="scan_close_sma50", help="Price position relative to 50-day simple moving average.")
        with p3:
            scan_close_vs_vwap = st.selectbox("Close vs VWAP (20d)", OPTS, index=0, key="scan_close_vwap", help="Price vs 20-day volume-weighted average price.")
        with p4:
            scan_rs_20d_op = st.selectbox("RS(20d) operator", OPTS, index=0, key="scan_rs_20d_op", help="Relative strength operator vs benchmark over 20 days.")
        p5, p6, _, _ = st.columns(4)
        with p5:
            scan_rs_20d_value = st.number_input("RS(20d) %", min_value=-50.0, max_value=50.0, value=0.0, step=0.5, format="%.1f", key="scan_rs_20d_val", help="Positive means outperforming benchmark.")

        st.caption("Momentum")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            scan_rsi_op = st.selectbox("RSI operator", OPTS, index=0, key="scan_rsi_op", help="Compare RSI with threshold.")
        with m2:
            scan_rsi_value = st.number_input("RSI value", min_value=0, max_value=100, value=50, step=1, key="scan_rsi_val", help="Common ranges: <35 oversold, >70 overbought.")
        with m3:
            scan_mfi_op = st.selectbox("MFI operator", OPTS, index=0, key="scan_mfi_op", help="Compare money flow index (volume-adjusted RSI style).")
        with m4:
            scan_mfi_value = st.number_input("MFI value", min_value=0, max_value=100, value=55, step=1, key="scan_mfi_val", help="MFI threshold for entry filter.")
        m5, m6, m7, _ = st.columns(4)
        with m5:
            scan_mfi_vs_rsi_display = st.selectbox("MFI vs RSI", ["Off", "MFI > RSI", "RSI > MFI"], key="scan_mfi_vs_rsi_display", help="Cross-check money flow strength vs RSI.")
        with m6:
            scan_macd_sign = st.selectbox("MACD now", ["Off", "Positive", "Negative"], index=0, key="scan_macd_sign", help="Current MACD histogram sign.")
        with m7:
            scan_macd_trend = st.selectbox("MACD vs yesterday", ["Off", "Higher", "Lower", "Turn Green (Cross Up)"], index=0, key="scan_macd_trend", help="Histogram direction change vs previous bar.")

        st.caption("Volume, DMI & ADX")
        v1, v2, v3, v4 = st.columns(4)
        with v1:
            scan_rvol_op = st.selectbox("RVOL operator", OPTS, index=0, key="scan_rvol_op", help="RVOL = current volume / 20-day average volume.")
        with v2:
            scan_rvol_value = st.number_input("RVOL value", min_value=0.0, max_value=10.0, value=1.0, step=0.1, format="%.1f", key="scan_rvol_val", help="1.0 means average volume.")
        with v3:
            scan_obv_vs_obv_ema20 = st.selectbox("OBV (20) operator", OPTS, index=0, key="scan_obv_ema", help="Compare OBV vs OBV EMA20.")
        with v4:
            scan_obv_vs_obv_5ma = st.selectbox("OBV (5) operator", OPTS, index=0, key="scan_obv_5ma", help="Compare OBV vs OBV 5-day MA.")
        v5, v6, v7, v8 = st.columns(4)
        with v5:
            scan_adx_slope_op = st.selectbox("ADX slope operator", OPTS, index=0, key="scan_adx_slope_op", help="Operator for ADX slope (trend acceleration).")
        with v6:
            scan_adx_awakening = st.checkbox("ADX goes up", value=True, key="scan_adx_awakening", help="Requires ADX to turn from down to up.")
        with v7:
            scan_adx_op = st.selectbox("ADX operator", OPTS, index=0, key="scan_adx_op", help="Compare ADX with one threshold value.")
        with v8:
            scan_adx_value = st.number_input("ADX value", min_value=0, max_value=100, value=25, step=1, key="scan_adx_val", help="Single ADX threshold used by ADX operator.")
        v9, v10, v11, _ = st.columns(4)
        with v9:
            scan_gap_op = st.selectbox("DMI gap op (PDI-MDI)", OPTS, index=0, key="scan_gap_op", help="Operator on directional gap = +DI - -DI.")
        with v10:
            scan_gap_value = st.number_input("Gap value", min_value=-50.0, max_value=50.0, value=10.0, step=0.5, format="%.1f", key="scan_gap_val", help="Threshold for (+DI - -DI).")
        with v11:
            scan_pdi_buffer = st.number_input("PDI-MDI buffer", min_value=-50.0, max_value=50.0, value=0.0, step=0.5, format="%.1f", key="scan_pdi_buffer", help="Extra margin added to PDI > MDI check.")

        st.caption("Stochastic")
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            scan_stoch_k_op = st.selectbox("Stoch %K operator", OPTS, index=0, key="scan_stoch_k_op", help="Operator for %K level filter.")
        with s2:
            scan_stoch_k_value = st.number_input("Stoch %K value", min_value=0.0, max_value=100.0, value=80.0, step=1.0, format="%.0f", key="scan_stoch_k_val", help="%K threshold.")
        with s3:
            scan_stoch_d_op = st.selectbox("Stoch %D vs level", OPTS, index=0, key="scan_stoch_d_op", help="Operator for %D level filter.")
        with s4:
            scan_stoch_d_value = st.number_input("Stoch %D threshold", min_value=0.0, max_value=100.0, value=50.0, step=1.0, format="%.0f", key="scan_stoch_d_val", help="%D threshold.")
        s5, s6, s7, _ = st.columns(4)
        with s5:
            scan_stoch_k_gt_d = st.checkbox("Require %K > %D", value=False, key="scan_stoch_k_gt_d", help="Only pass when %K is above %D (bullish momentum bias).")
        with s6:
            scan_stoch_k_vs_prev = st.selectbox("%K vs yesterday", ["Off", "K > K yesterday", "K < K yesterday"], key="scan_stoch_k_vs_prev", help="Compare today's %K with yesterday's %K.")
        with s7:
            scan_stoch_d_vs_prev = st.selectbox("%D vs yesterday", ["Off", "D > D yesterday", "D < D yesterday"], key="scan_stoch_d_vs_prev", help="Compare today's %D with yesterday's %D.")

    with st.expander("Exit rules (signal labelling)", expanded=False):
        st.markdown(
            '<p class="yf-section-title">Exit logic</p><p class="yf-section-sub">Used for signal labelling in scan results — align with your backtest exit rules.</p>',
            unsafe_allow_html=True,
        )
        ex_c1, ex_c2, ex_c3, ex_c4 = st.columns(4)
        with ex_c1:
            scan_sell_adx_exhaustion = st.checkbox("ADX goes down", value=False, key="scan_sell_adx_exh", help="Exit signal if ADX turns from rising to falling.")
        with ex_c2:
            scan_sell_sma20 = st.checkbox("Close < SMA20", value=False, key="scan_sell_sma20", help="Exit signal when price loses 20-day trend support.")
        with ex_c3:
            scan_sell_pdi_mdi = st.checkbox("PDI < MDI", value=False, key="scan_sell_pdi_mdi", help="Exit signal when -DI overtakes +DI.")
        with ex_c4:
            scan_sell_profit_take = st.checkbox("RSI climax partial sell", value=True, key="scan_sell_pt", help="Label profit-taking when RSI is too hot.")
        scan_rsi_profit_take = st.number_input("Profit take when RSI >", min_value=65, max_value=85, value=75, step=1, key="scan_rsi_pt", help="RSI threshold used by partial take-profit label.")

    # ---------- Main: run button + results ----------
    if tickers:
        if st.button("Run scan", type="primary", key="scan_btn", use_container_width=True):
            # Show active strategy mode
            if manual_mode:
                st.info("🎯 **大佬級自動篩選:** 🛠️ 手動自訂 (Manual) — 使用你自訂的所有掃描條件。")
            elif "推土機起步" in strategy_mode:
                st.info("🎯 **大佬級自動篩選:** 🔥 推土機起步 — Gap>15, ADX>25, ADX slope>0, Price>VWAP。")
            elif "地牢撈底" in strategy_mode:
                st.info("🎯 **大佬級自動篩選:** 🩸 地牢撈底 — RSI<35, **RSI>MFI**, RVOL>1.5, Price<SMA20（與引擎 `rsi>mfi` 一致）。")
            elif "良性回抽" in strategy_mode:
                st.info("🎯 **大佬級自動篩選:** ♻️ 良性回抽 — SMA20<Price<VWAP, RVOL<1.0, Gap>10, Stoch_K<80。")
            elif "RS破位領頭羊" in strategy_mode:
                st.info("🎯 **大佬級自動篩選:** 🚀 RS破位領頭羊 — RS_20d>5%, OBV>OBV_5MA, ADX slope>0。")
            elif "MACD 動能爆發" in strategy_mode:
                st.info("🎯 **大佬級自動篩選:** 📈 MACD 動能爆發 — MACD Hist 由負轉正（零軸上穿）且 RVOL≥1.0。")
            elif "絕地反擊" in strategy_mode:
                st.info(
                    "🎯 **大佬級自動篩選:** 🌊 絕地反擊 — Hist 較昨日改善、"
                    "**RSI>40 且 Stoch K>D**、RVOL>1.2、收市>SMA20（K 線由你肉眼確認）。"
                )
            else:
                st.info("🎯 **大佬級自動篩選:** 當前策略模式。")

            progress = st.progress(0, text="Scanning...")
            results = []
            n = len(tickers)
            _op = lambda x: "off" if x == "Off" else x
            mfi_vs = {"Off": "off", "MFI > RSI": "mfi>rsi", "RSI > MFI": "rsi>mfi"}.get(scan_mfi_vs_rsi_display, "off")

            # Preset + manual share one path: widgets (seeded when you pick a preset) drive analyze_stock.
            scan_adx_min, scan_adx_max = _adx_ui_to_range(scan_adx_op, scan_adx_value)
            scan_kwargs = {
                "period": scan_period,
                "strategy_mode": "",
                "close_vs_sma20": _op(scan_close_vs_sma20),
                "close_vs_sma50": _op(scan_close_vs_sma50),
                "obv_vs_obv_ema20": _op(scan_obv_vs_obv_ema20),
                "obv_vs_obv_5ma": _op(scan_obv_vs_obv_5ma),
                "close_vs_vwap": _op(scan_close_vs_vwap),
                "mfi_vs_rsi": mfi_vs,
                "rsi_op": _op(scan_rsi_op),
                "rsi_value": float(scan_rsi_value),
                "rs_20d_op": _op(scan_rs_20d_op),
                "rs_20d_value": float(scan_rs_20d_value),
                "mfi_op": _op(scan_mfi_op),
                "mfi_value": float(scan_mfi_value),
                "rvol_op": _op(scan_rvol_op),
                "rvol_value": float(scan_rvol_value),
                "adx_slope_op": _op(scan_adx_slope_op),
                "gap_op": _op(scan_gap_op),
                "gap_value": float(scan_gap_value),
                "stoch_k_op": _op(scan_stoch_k_op),
                "stoch_k_value": float(scan_stoch_k_value),
                "stoch_require_k_gt_d": bool(scan_stoch_k_gt_d),
                "stoch_k_vs_prev_op": _stoch_vs_yesterday_ui_to_op(scan_stoch_k_vs_prev),
                "stoch_d_vs_prev_op": _stoch_vs_yesterday_ui_to_op(scan_stoch_d_vs_prev),
                "stoch_d_op": _op(scan_stoch_d_op),
                "stoch_d_value": float(scan_stoch_d_value),
                "core_require_pdi_mdi": False,
                "pdi_buffer": float(scan_pdi_buffer),
                "adx_min": int(scan_adx_min),
                "adx_max": int(scan_adx_max),
                "core_require_adx_awakening": scan_adx_awakening,
                "rsi_profit_take": int(scan_rsi_profit_take),
                "sell_use_sma20": scan_sell_sma20,
                "sell_use_pdi_mdi": scan_sell_pdi_mdi,
                "sell_use_adx_exhaustion": scan_sell_adx_exhaustion,
                "sell_use_profit_take": scan_sell_profit_take,
            }
            if scan_relaxed_mode:
                # Broad content mode: keep signal engine running but remove most entry constraints.
                scan_kwargs.update(
                    {
                        "close_vs_sma20": "off",
                        "close_vs_sma50": "off",
                        "obv_vs_obv_ema20": "off",
                        "obv_vs_obv_5ma": "off",
                        "close_vs_vwap": "off",
                        "mfi_vs_rsi": "off",
                        "rsi_op": "off",
                        "rs_20d_op": "off",
                        "mfi_op": "off",
                        "rvol_op": "off",
                        "adx_slope_op": "off",
                        "gap_op": "off",
                        "stoch_k_op": "off",
                        "stoch_require_k_gt_d": False,
                        "stoch_k_vs_prev_op": "off",
                        "stoch_d_vs_prev_op": "off",
                        "stoch_d_op": "off",
                        "core_require_pdi_mdi": False,
                        "pdi_buffer": 0.0,
                        "adx_min": 0,
                        "adx_max": 100,
                        "core_require_adx_awakening": False,
                    }
                )
            sig = inspect.signature(analyze_stock)
            valid_params = {p for p in sig.parameters if p != "ticker"}
            filtered = {k: v for k, v in scan_kwargs.items() if k in valid_params}
            raw_hits = 0
            eff_macd_sign = "Off" if scan_relaxed_mode else scan_macd_sign
            eff_macd_trend = "Off" if scan_relaxed_mode else scan_macd_trend
            for i, t in enumerate(tickers):
                res = None
                try:
                    res = analyze_stock(t, **filtered)
                except TypeError as e:
                    st.error(f"Scan error for {t}: {e}")
                    res = None
                if res:
                    raw_hits += 1
                    macd_ok = True
                    try:
                        mh = float(str(res.get("MACD_Hist", "nan")).replace("—", "nan"))
                        mh_prev = float(str(res.get("MACD_Hist_Prev", "nan")).replace("—", "nan"))
                        if eff_macd_sign == "Positive":
                            macd_ok = macd_ok and (mh > 0.0)
                        elif eff_macd_sign == "Negative":
                            macd_ok = macd_ok and (mh < 0.0)
                        if eff_macd_trend == "Higher":
                            macd_ok = macd_ok and (mh > mh_prev)
                        elif eff_macd_trend == "Lower":
                            macd_ok = macd_ok and (mh < mh_prev)
                        elif eff_macd_trend == "Turn Green (Cross Up)":
                            macd_ok = macd_ok and (mh_prev < 0.0) and (mh > 0.0)
                    except Exception:
                        if eff_macd_sign != "Off" or eff_macd_trend != "Off":
                            macd_ok = False
                    if macd_ok:
                        results.append(res)

                progress.progress((i + 1) / n, text=f"Scanning {t}...")
                time.sleep(0.12)
            progress.progress(1.0, text="Done.")
            time.sleep(0.3)
            progress.empty()
            rescue_hits = 0
            if scan_relaxed_mode and n > 0 and raw_hits == 0:
                st.warning("Primary pass returned 0 rows; trying fallback pass with engine defaults.")
                progress2 = st.progress(0, text="Fallback scan...")
                fallback_results = []
                for i, t in enumerate(tickers):
                    res2 = None
                    try:
                        # Hard fallback: call analyze_stock with defaults only.
                        res2 = analyze_stock(t)
                    except TypeError as e:
                        st.error(f"Fallback scan error for {t}: {e}")
                        res2 = None
                    if res2:
                        rescue_hits += 1
                        fallback_results.append(res2)
                    progress2.progress((i + 1) / n, text=f"Fallback scanning {t}...")
                    time.sleep(0.06)
                progress2.progress(1.0, text="Fallback done.")
                time.sleep(0.2)
                progress2.empty()
                if fallback_results:
                    results = fallback_results
            if scan_relaxed_mode:
                st.info("Content mode enabled: filters were relaxed to increase candidate count.")
                st.caption("MACD post-filter is also forced Off in content mode.")
            st.caption(f"Debug: raw hits before MACD post-filter = {raw_hits}; final shown = {len(results)}.")
            if scan_relaxed_mode and raw_hits == 0:
                st.caption(f"Debug fallback hits (analyze_stock defaults) = {rescue_hits}.")

            if results:
                df = pd.DataFrame(results)
                df[" "] = df["Signal"].apply(lambda s: "🟢" if "BUY" in s else ("🔴" if "SELL" in s else "🟠"))
                n_buy = sum(1 for _, r in df.iterrows() if "BUY" in str(r.get("Signal", "")))
                n_sell = sum(1 for _, r in df.iterrows() if "SELL" in str(r.get("Signal", "")) or "PROFIT" in str(r.get("Signal", "")))
                # Dashboard: top row of metrics (Boss vibe)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("📡 Signals", len(results), None)
                m2.metric("🟢 BUY", n_buy, None)
                m3.metric("🔴 SELL / Profit take", n_sell, None)
                m4.metric("📋 Tickers scanned", n, None)
                # Verdict box — styled for clarity
                if n_buy > 0 and n_sell == 0:
                    st.success(f"**✅ Verdict:** {n_buy} BUY signal(s). Consider entries.")
                elif n_buy > 0 and n_sell > 0:
                    st.warning(f"**⚠️ Verdict:** {n_buy} BUY, {n_sell} SELL/Profit take. Mixed signals.")
                elif n_sell > 0:
                    st.warning(f"**⚠️ Verdict:** {n_sell} SELL/Profit take signal(s). Review exits.")
                else:
                    st.success(f"**✅ Verdict:** {len(results)} actionable signal(s).")
                # Key metrics: Price, VWAP, OBV trend, RVOL
                first = df.iloc[0]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("💰 Sample price", first.get("Price", "—"), None)
                c2.metric("📊 VWAP (20d)", first.get("VWAP", "—"), None)
                c3.metric("🌊 OBV trend (EMA20)", first.get("OBV_EMA_20", "—"), None)
                c4.metric("⛽ RVOL", first.get("RVOL", "—"), None)
                cols = [
                    " ", "Ticker", "Price", "Signal", "Why", "ADX", "ADX_Slope", "PDI", "MDI", "RSI", "MFI", "RVOL",
                    "RS_20d", "Spread", "SMA_50", "OBV", "OBV_EMA_20", "VWAP",
                    "Stoch_K", "Stoch_D",
                    "MACD_Line", "MACD_Signal", "MACD_Hist", "MACD_Hist_Prev",
                ]
                cols = [c for c in cols if c in df.columns]
                st.dataframe(df[cols], use_container_width=True, hide_index=True)

                result_df = _enrich_with_tech_score(df, score_model=score_model)
                result_df_sell_put = _enrich_with_tech_score(df, score_model="sell_put")
                result_df_buy_stock = _enrich_with_tech_score(df, score_model="buy_stock")
                result_df_buy_put = _enrich_with_tech_score(df, score_model="buy_put")
                _g = globals()
                actual_strategy = _g["backtest_strategy"] if "backtest_strategy" in _g else strategy_mode
                actual_strategy = f"{actual_strategy} | ScoreModel={score_mode_label}"
                export_success = export_results_to_json(
                    result_df, actual_strategy, score_model_slug=score_model
                )
                export_results_to_json(
                    result_df_sell_put,
                    f"{actual_strategy} | AutoDual=sell_put",
                    filename="daily_scan_sell_put.json",
                    score_model_slug="sell_put",
                )
                export_results_to_json(
                    result_df_buy_stock,
                    f"{actual_strategy} | AutoDual=buy_stock",
                    filename="daily_scan_buy_stock.json",
                    score_model_slug="buy_stock",
                )
                export_results_to_json(
                    result_df_buy_put,
                    f"{actual_strategy} | AutoDual=buy_put",
                    filename="daily_scan_buy_put.json",
                    score_model_slug="buy_put",
                )
                if export_success:
                    st.success("✅ 真實數據已成功導出至 daily_scan.json")
                for _m, _df_m, _slug in (
                    ("sell_put", result_df_sell_put, "sell_put"),
                    ("buy_stock", result_df_buy_stock, "buy_stock"),
                    ("buy_put", result_df_buy_put, "buy_put"),
                ):
                    export_trade_signals_history_to_json(
                        _df_m,
                        f"{actual_strategy} | ScoreModel={_m}",
                        score_model_slug=_slug,
                    )
                append_future_log_to_json(result_df, actual_strategy)
                export_macro_snapshot_to_json()
            else:
                st.info("**📌 Verdict:** No actionable signals. Stay cash.")
                result_df = pd.DataFrame()
                _g = globals()
                actual_strategy = _g["backtest_strategy"] if "backtest_strategy" in _g else strategy_mode
                actual_strategy = f"{actual_strategy} | ScoreModel={score_mode_label}"
                export_success = export_results_to_json(
                    result_df, actual_strategy, score_model_slug=score_model
                )
                export_results_to_json(
                    result_df,
                    f"{actual_strategy} | AutoDual=sell_put",
                    filename="daily_scan_sell_put.json",
                    score_model_slug="sell_put",
                )
                export_results_to_json(
                    result_df,
                    f"{actual_strategy} | AutoDual=buy_stock",
                    filename="daily_scan_buy_stock.json",
                    score_model_slug="buy_stock",
                )
                export_results_to_json(
                    result_df,
                    f"{actual_strategy} | AutoDual=buy_put",
                    filename="daily_scan_buy_put.json",
                    score_model_slug="buy_put",
                )
                if export_success:
                    st.success("✅ 真實數據已成功導出至 daily_scan.json")
                for _m, _df_m, _slug in (
                    ("sell_put", result_df if not result_df.empty else result_df_sell_put, "sell_put"),
                    ("buy_stock", result_df_buy_stock, "buy_stock"),
                    ("buy_put", result_df_buy_put, "buy_put"),
                ):
                    export_trade_signals_history_to_json(
                        _df_m,
                        f"{actual_strategy} | ScoreModel={_m}",
                        score_model_slug=_slug,
                    )
                append_future_log_to_json(result_df, actual_strategy)
                export_macro_snapshot_to_json()
    else:
        st.info("Select a ticker source in the sidebar and (for Custom) enter at least one ticker.")

# ========== Backtest ==========
elif mode == "Backtest":
    st.markdown(
        '<p class="yf-page-kicker">Backtest · Historical entries/exits on your ticker using the same Veteran engine as the CLI.</p>',
        unsafe_allow_html=True,
    )
    # Load backtest engine
    import importlib.util
    _bt_path = _here / "backtest_options.py"
    if not _bt_path.exists():
        st.error("Backtest requires **backtest_options.py** in the same folder. File not found.")
        st.stop()
    try:
        spec = importlib.util.spec_from_file_location("backtest_options", _bt_path)
        _bt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_bt)
        fetch_data_yfinance = _bt.fetch_data_yfinance
        add_indicators = _bt.add_indicators
        run_veteran_backtest = _bt.run_veteran_backtest
    except Exception as e:
        st.error(f"Could not load backtest_options.py: {e}")
        st.stop()

    # ---------- Sidebar: symbol & period only ----------
    st.sidebar.header("Backtest")
    symbol = st.sidebar.text_input("Ticker", value="9988.HK", key="bt_symbol", placeholder="0700.HK or NVDA")
    period = st.sidebar.selectbox("Period", ["3mo", "6mo", "1y", "2y", "5y", "10y", "max"], index=2, key="bt_period")
    use_smart_exit = st.sidebar.checkbox("Smart exit (trail + profit take)", value=True, key="bt_smart")

    st.subheader("Backtest engine")

    # Strategy Presets (Framework First): hide granular params unless Manual Setup
    backtest_strategy = st.radio(
        "Strategy",
        [
            "🔥 1. 推土機起步 (Trend Confirmation)",
            "🩸 2. 地牢撈底 (Capitulation Bottom)",
            "♻️ 3. 良性回抽 (Healthy Pullback)",
            "🚀 4. RS破位領頭羊 (RS Breakout)",
            "📈 5. MACD 動能爆發 (MACD Expansion)",
            "🌊 6. 絕地反擊 (Reversal Breakout)",
            "🛠️ 手動自訂參數 (Manual Setup)",
        ],
        horizontal=False,
    )
    show_manual = _is_manual_strategy_label(backtest_strategy)
    _bt_preset_slug = _strategy_preset_slug(backtest_strategy) if not show_manual else None
    _sync_backtest_widgets_from_preset(None if show_manual else _bt_preset_slug)
    BT_OPTS = ["Off", ">", "<", ">=", "<="]

    if not show_manual and _bt_preset_slug:
        st.caption("已載入此預設的入場條件到下方欄位，可自行微調後按 **Run backtest**（與回測引擎一致）。")

    with st.expander("Entry criteria (presets load here; same controls as Scanner)", expanded=True):
        st.caption("選 **預設 1–6** 會自動填入對應條件；選 **手動** 則由你自行設定。兩者都用這裡的數值跑回測。")
        st.markdown(
            '<p class="yf-section-title">One-page compact entry controls</p><p class="yf-section-sub">Reordered for fast top-down tuning: trend → momentum → volume/DMI → stochastic.</p>',
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            st.caption("Trend & Price")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                close_vs_sma20 = st.selectbox("Close vs SMA20", BT_OPTS, index=0, key="bt_close_sma20", help="Price relative to 20-day SMA.")
            with c2:
                close_vs_sma50 = st.selectbox("Close vs SMA(50)", BT_OPTS, index=0, key="bt_close_sma50", help="Price relative to 50-day SMA.")
            with c3:
                close_vs_vwap = st.selectbox("Close vs VWAP (20d)", BT_OPTS, index=0, key="bt_close_vwap", help="Price vs 20-day VWAP.")
            with c4:
                rs_20d_op = st.selectbox("RS(20d) operator", BT_OPTS, index=0, key="bt_rs_20d_op", help="Relative strength operator.")
            c5, _, _, _ = st.columns(4)
            with c5:
                rs_20d_value = st.number_input("RS(20d) %", min_value=-50.0, max_value=50.0, value=0.0, step=0.5, format="%.1f", key="bt_rs_20d_val", help="Positive means outperforming benchmark.")

            st.caption("Momentum")
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                rsi_op = st.selectbox("RSI operator", BT_OPTS, index=0, key="bt_rsi_op", help="RSI threshold operator.")
            with m2:
                rsi_value = st.number_input("RSI value", min_value=0, max_value=100, value=50, step=1, key="bt_rsi_val", help="RSI threshold value.")
            with m3:
                mfi_op = st.selectbox("MFI operator", BT_OPTS, index=0, key="bt_mfi_op", help="MFI threshold operator.")
            with m4:
                mfi_value = st.number_input("MFI value", min_value=0, max_value=100, value=55, step=1, key="bt_mfi_val", help="MFI threshold value.")
            m5, m6, m7, _ = st.columns(4)
            with m5:
                bt_mfi_vs_rsi_display = st.selectbox("MFI vs RSI", ["Off", "MFI > RSI", "RSI > MFI"], key="bt_mfi_vs_rsi_display", help="Relative comparison of MFI and RSI.")
            with m6:
                bt_macd_sign = st.selectbox("MACD now", ["Off", "Positive", "Negative"], index=0, key="bt_macd_sign", help="Current MACD histogram sign.")
            with m7:
                bt_macd_trend = st.selectbox("MACD vs yesterday", ["Off", "Higher", "Lower", "Turn Green (Cross Up)"], index=0, key="bt_macd_trend", help="Histogram trend change vs previous bar.")

            st.caption("Volume, DMI & ADX")
            v1, v2, v3, v4 = st.columns(4)
            with v1:
                rvol_op = st.selectbox("RVOL operator", BT_OPTS, index=0, key="bt_rvol_op", help="Relative volume operator.")
            with v2:
                rvol_value = st.number_input("RVOL value", min_value=0.0, max_value=10.0, value=1.0, step=0.1, format="%.1f", key="bt_rvol_val", help="1.0 equals 20-day average volume.")
            with v3:
                obv_vs_obv_ema20 = st.selectbox("OBV (20) operator", BT_OPTS, index=0, key="bt_obv_ema", help="Compare OBV with EMA20.")
            with v4:
                obv_vs_obv_5ma = st.selectbox("OBV (5) operator", BT_OPTS, index=0, key="bt_obv_5ma", help="Compare OBV with 5-day MA.")
            v5, v6, v7, v8 = st.columns(4)
            with v5:
                adx_slope_op = st.selectbox("ADX slope operator", BT_OPTS, index=0, key="bt_adx_slope_op", help="ADX slope operator.")
            with v6:
                core_require_adx_awakening = st.checkbox("ADX goes up", value=True, key="core_adx_awakening", help="Require ADX to turn up.")
            with v7:
                bt_adx_op = st.selectbox("ADX operator", BT_OPTS, index=0, key="bt_adx_op", help="Compare ADX with one threshold value.")
            with v8:
                bt_adx_value = st.number_input("ADX value", min_value=0, max_value=100, value=25, step=1, key="bt_adx_val", help="Single ADX threshold for filter.")
            v9, v10, v11, _ = st.columns(4)
            with v9:
                gap_op = st.selectbox("DMI gap op (PDI-MDI)", BT_OPTS, index=0, key="bt_gap_op", help="Operator for +DI - -DI.")
            with v10:
                gap_value = st.number_input("Gap value", min_value=-50.0, max_value=50.0, value=10.0, step=0.5, format="%.1f", key="bt_gap_val", help="Threshold for directional gap.")
            with v11:
                bt_pdi_buffer = st.number_input("PDI-MDI buffer", min_value=-50.0, max_value=50.0, value=0.0, step=0.5, format="%.1f", key="bt_pdi_buffer", help="Extra buffer for +DI > -DI check.")

            st.caption("Stochastic")
            s1, s2, s3, s4 = st.columns(4)
            with s1:
                stoch_k_op = st.selectbox("Stoch %K operator", BT_OPTS, index=0, key="bt_stoch_k_op", help="Operator for %K level.")
            with s2:
                stoch_k_value = st.number_input("Stoch %K value", min_value=0.0, max_value=100.0, value=80.0, step=1.0, format="%.0f", key="bt_stoch_k_val", help="%K threshold.")
            with s3:
                bt_stoch_d_op = st.selectbox("Stoch %D vs level", BT_OPTS, index=0, key="bt_stoch_d_op", help="Operator for %D level.")
            with s4:
                bt_stoch_d_value = st.number_input("Stoch %D threshold", min_value=0.0, max_value=100.0, value=50.0, step=1.0, format="%.0f", key="bt_stoch_d_val", help="%D threshold.")
            s5, s6, s7, _ = st.columns(4)
            with s5:
                bt_stoch_k_gt_d = st.checkbox("Require %K > %D", value=False, key="bt_stoch_k_gt_d", help="Bullish momentum filter.")
            with s6:
                bt_stoch_k_vs_prev = st.selectbox("%K vs yesterday", ["Off", "K > K yesterday", "K < K yesterday"], key="bt_stoch_k_vs_prev", help="Direction of %K vs prior bar.")
            with s7:
                bt_stoch_d_vs_prev = st.selectbox("%D vs yesterday", ["Off", "D > D yesterday", "D < D yesterday"], key="bt_stoch_d_vs_prev", help="Direction of %D vs prior bar.")

    # SELL rules: visible after entry (same order as Scanner)
    with st.expander("Exit rules (applies to all strategies)", expanded=True):
        st.caption("Same knobs as Scanner · Presets only set **entry**; you control exits here.")
        se1, se2, se3, se4 = st.columns(4)
        with se1:
            sell_use_adx_exhaustion = st.checkbox("ADX goes down", value=False, key="sell_adx_exh", help="Exit when trend strength starts fading.")
            sell_use_stop_loss = st.checkbox("Use stop loss %", value=True, key="sell_stop", help="Hard stop based on entry price.")
        with se2:
            sell_use_sma20 = st.checkbox("Close < SMA20", value=False, key="sell_sma20", help="Exit when price closes below 20-day trend line.")
            sell_use_trailing = st.checkbox("Use ATR trailing stop", value=True, key="sell_trail", help="Dynamic stop based on ATR volatility.")
        with se3:
            sell_use_pdi_mdi = st.checkbox("PDI < MDI", value=False, key="sell_pdi_mdi", help="Exit when bearish directional index leads.")
            sell_use_profit_take = st.checkbox("RSI climax partial sell", value=True, key="sell_pt", help="Take partial profit at high RSI.")
        with se4:
            sell_use_month_end = st.checkbox("Force close month-end", value=False, key="sell_me", help="Close open position at month-end for bookkeeping.")
        st.markdown(
            '<p class="yf-section-title">Thresholds</p><p class="yf-section-sub">Stop %, ATR trail, RSI profit-taking.</p>',
            unsafe_allow_html=True,
        )
        se3, se4, se5 = st.columns(3)
        with se3:
            stop_loss_pct = st.number_input("Stop loss %", min_value=1, max_value=20, value=8, step=1, key="sl_pct", help="Example: 8 means stop at -8% from entry.") / 100.0
        with se4:
            atr_trail_mult = st.number_input("Trailing stop (x ATR)", min_value=1.0, max_value=6.0, value=3.0, step=0.5, format="%.1f", key="atr_mult", help="Higher multiplier = looser trailing stop.")
        with se5:
            rsi_profit_taking = st.number_input("Profit take when RSI >", min_value=65, max_value=85, value=75, step=1, key="rsi_pt", help="RSI level for partial take-profit trigger.")

    # ---------- Main: run button + results ----------
    if st.button("Run backtest", type="primary", key="backtest_btn"):
        symbol = (symbol or "").strip().upper()
        if not symbol:
            st.warning("Enter a ticker.")
        else:
            with st.spinner(f"Fetching {symbol} and running backtest..."):
                try:
                    # --- Framework for Strategy Parameters ---
                    def _op(x):
                        return "off" if x == "Off" else x

                    # Entry always comes from the Entry criteria widgets (presets seed them once per preset).
                    _bt.CLOSE_VS_SMA20 = _op(close_vs_sma20)
                    _bt.CLOSE_VS_SMA50 = _op(close_vs_sma50)
                    _bt.OBV_VS_OBV_EMA20 = _op(obv_vs_obv_ema20)
                    _bt.OBV_VS_OBV_5MA = _op(obv_vs_obv_5ma)
                    _bt.CLOSE_VS_VWAP = _op(close_vs_vwap)
                    _disp = (
                        bt_mfi_vs_rsi_display
                        if isinstance(bt_mfi_vs_rsi_display, str)
                        else st.session_state.get("bt_mfi_vs_rsi_display", "Off")
                    )
                    _bt.MFI_VS_RSI = {"Off": "off", "MFI > RSI": "mfi>rsi", "RSI > MFI": "rsi>mfi"}.get(_disp, "off")
                    _bt.RSI_OP = _op(rsi_op)
                    _bt.RSI_VALUE = float(rsi_value)
                    _bt.RS_20D_OP = _op(rs_20d_op)
                    _bt.RS_20D_VALUE = float(rs_20d_value)
                    _bt.MFI_OP = _op(mfi_op)
                    _bt.MFI_VALUE = float(mfi_value)
                    _bt.RVOL_OP = _op(rvol_op)
                    _bt.RVOL_VALUE = float(rvol_value)
                    _bt.ADX_SLOPE_OP = _op(adx_slope_op)
                    adx_min, adx_max = _adx_ui_to_range(bt_adx_op, bt_adx_value)
                    _bt.GAP_OP = _op(gap_op)
                    _bt.GAP_VALUE = float(gap_value)
                    _bt.STOCH_K_OP = _op(stoch_k_op)
                    _bt.STOCH_K_VALUE = float(stoch_k_value)
                    _bt.STOCH_REQUIRE_K_GT_D = bool(bt_stoch_k_gt_d)
                    _bt.STOCH_K_VS_PREV_OP = _stoch_vs_yesterday_ui_to_op(bt_stoch_k_vs_prev)
                    _bt.STOCH_D_VS_PREV_OP = _stoch_vs_yesterday_ui_to_op(bt_stoch_d_vs_prev)
                    _bt.STOCH_D_OP = _op(bt_stoch_d_op)
                    _bt.STOCH_D_VALUE = float(bt_stoch_d_value)
                    _bt.CORE_REQUIRE_PDI_MDI = False
                    _bt.PDI_BUFFER = float(bt_pdi_buffer)
                    _bt.ADX_MIN = int(adx_min)
                    _bt.ADX_MAX = int(adx_max)
                    _bt.CORE_REQUIRE_ADX_AWAKENING = core_require_adx_awakening

                    use_rev = bool(st.session_state.get("bt_entry_use_reversal", False))
                    if use_rev:
                        _bt.ENTRY_USE_REVERSAL_BREAKOUT = True
                        _bt.REVERSAL_RSI_MIN = float(rsi_value)
                        _bt.REVERSAL_RVOL_MIN = float(rvol_value)
                        _bt.ENTRY_USE_MACD_CROSSOVER = False
                    else:
                        _bt.ENTRY_USE_REVERSAL_BREAKOUT = False
                        macd_enabled = (bt_macd_sign != "Off") or (bt_macd_trend != "Off")
                        _bt.ENTRY_USE_MACD_CROSSOVER = macd_enabled
                        if bt_macd_sign == "Positive":
                            _bt.MACD_HIST_MIN = 0.0
                            _bt.MACD_HIST_PREV_MAX = 1e9
                        elif bt_macd_sign == "Negative":
                            _bt.MACD_HIST_MIN = -1e9
                            _bt.MACD_HIST_PREV_MAX = -0.000001
                        else:
                            _bt.MACD_HIST_MIN = -1e9
                            _bt.MACD_HIST_PREV_MAX = 1e9
                        if bt_macd_trend == "Higher":
                            _bt.MACD_HIST_PREV_MAX = min(_bt.MACD_HIST_PREV_MAX, 0.0)
                        elif bt_macd_trend == "Lower":
                            _bt.MACD_HIST_MIN = max(_bt.MACD_HIST_MIN, 0.0)
                        elif bt_macd_trend == "Turn Green (Cross Up)":
                            _bt.MACD_HIST_MIN = 0.000001
                            _bt.MACD_HIST_PREV_MAX = -0.000001
                            _bt.ENTRY_USE_MACD_CROSSOVER = True

                    # Apply SELL / exit from UI for every strategy (presets no longer force exits)
                    _bt.SELL_USE_ADX_EXHAUSTION = sell_use_adx_exhaustion
                    _bt.SELL_USE_SMA20 = sell_use_sma20
                    _bt.SELL_USE_PDI_MDI = sell_use_pdi_mdi
                    _bt.SELL_USE_STOP_LOSS = sell_use_stop_loss
                    _bt.SELL_USE_TRAILING = sell_use_trailing
                    _bt.SELL_USE_PROFIT_TAKE = sell_use_profit_take
                    _bt.SELL_USE_MONTH_END = sell_use_month_end
                    _bt.STOP_LOSS_PCT = stop_loss_pct
                    _bt.ATR_TRAIL_MULT = atr_trail_mult
                    _bt.RSI_PROFIT_TAKING = rsi_profit_taking

                    df = fetch_data_yfinance(symbol, period=period)
                    df = add_indicators(df, symbol=symbol)
                    required = [
                        "SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread", "ATR14",
                        "Stoch_K", "Stoch_D", "Stoch_K_prev", "Stoch_D_prev",
                    ]
                    if _bt.ENTRY_USE_MACD_CROSSOVER or _bt.ENTRY_USE_REVERSAL_BREAKOUT:
                        required = required + ["MACD_Hist", "MACD_Hist_Prev"]
                    valid = df.dropna(subset=required)
                    if len(valid) < 10:
                        st.warning(f"Not enough valid bars after warm-up ({len(valid)}). Try a longer period.")
                    else:
                        trades = run_veteran_backtest(valid, verbose=False, use_smart_exit=use_smart_exit)

                        if not trades:
                            st.warning(f"**Verdict:** No trades triggered for **{symbol}** in this period. Data: {valid.index[0].date()} → {valid.index[-1].date()} ({len(valid)} bars).")
                        else:
                            tdf = pd.DataFrame(trades)
                            wins = tdf[tdf["Result"] == "WIN"]
                            losses = tdf[tdf["Result"] == "LOSS"]
                            n = len(tdf)
                            total_pnl = tdf["PnL"].sum()
                            total_cost = tdf["Cost"].sum() if "Cost" in tdf.columns else 0
                            total_proceeds = tdf["Proceeds"].sum() if "Proceeds" in tdf.columns else 0
                            overall_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
                            win_rate = len(wins) / n * 100
                            avg_win = wins["PnL%"].mean() if len(wins) > 0 else 0
                            avg_loss = losses["PnL%"].mean() if len(losses) > 0 else 0

                            if overall_pnl_pct > 0:
                                st.success(f"**✅ Verdict:** **{symbol}** — {n} trades | Win rate {win_rate:.1f}% | Total P&L **HK$ {total_pnl:+.2f}** | Return **{overall_pnl_pct:+.1f}%**")
                            else:
                                st.error(f"**❌ Verdict:** **{symbol}** — {n} trades | Win rate {win_rate:.1f}% | Total P&L **HK$ {total_pnl:+.2f}** | Return **{overall_pnl_pct:+.1f}%**")
                            c1, c2, c3, c4, c5 = st.columns(5)
                            c1.metric("💰 Total P&L (HK$)", f"{total_pnl:+.2f}", None)
                            c2.metric("📈 Overall Return %", f"{overall_pnl_pct:+.1f}%", None)
                            c3.metric("💵 Total Cost", f"HK$ {total_cost:,.0f}", None)
                            c4.metric("💵 Total Proceeds", f"HK$ {total_proceeds:,.0f}", None)
                            c5.metric("🏆 Wins / Losses", f"{len(wins)} / {len(losses)}", None)
                            st.caption("Overall Return % = (Total Proceeds − Total Cost) / Total Cost × 100")
                            d1, d2, d3, d4 = st.columns(4)
                            d1.metric("📊 Trades", n, None)
                            d2.metric("⛽ Avg Win %", f"{avg_win:+.2f}%", None)
                            d3.metric("📉 Avg Loss %", f"{avg_loss:+.2f}%", None)
                            latest_rs = valid["RS_20d_Outperform"].iloc[-1] if "RS_20d_Outperform" in valid.columns and pd.notna(valid["RS_20d_Outperform"].iloc[-1]) else None
                            d4.metric("📈 RS vs Market (20d)", f"{latest_rs:.2f}%" if latest_rs is not None else "N/A", f"{latest_rs:+.2f}%" if latest_rs is not None else None)

                            log_cols = [
                                "Entry_Date", "Entry_Price", "Entry_Reason",
                                "E_ADX", "E_ADX_Slope", "E_PDI", "E_MDI", "E_RSI", "E_MFI", "E_RVOL",
                                "E_MACD_Line", "E_MACD_Signal", "E_MACD_Hist", "E_MACD_Hist_Prev",
                                "E_RS_20d", "E_Spread", "E_SMA_50", "E_OBV", "E_OBV_EMA_20", "E_VWAP",
                                "Exit_Date", "Exit_Price", "Exit_Reason", "Hold_Days", "PnL", "PnL%", "Result",
                            ]
                            log_cols = [c for c in log_cols if c in tdf.columns]
                            st.dataframe(tdf[log_cols], use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"Backtest failed: {e}")

st.divider()
st.subheader("💡 系統指南與六大神級策略 (FAQ & Strategies)")
st.caption("了解 Numstation 2.0 的量化運作邏輯及嚴格篩選條件")

with st.expander("Q: 系統內置的「六大神級策略」具體參數是什麼？"):
    st.markdown("""
系統內置六大機構級篩選邏輯，確保您的每次進場都有大數據支撐：

**🔥 1. 推土機起步 (Trend Confirmation)**
*捕捉單邊爆發力極強的股票，適合順勢追入或 Short Put。*
* `Gap (PDI - MDI) > 15`: 多頭買盤絕對主導。
* `ADX > 25 且 Slope > 0`: 趨勢已經成型且正在加速。
* `Price > VWAP`: 股價企穩於大戶日內平均成本之上。

**🩸 2. 地牢底背馳 (Capitulation Bottom)**
*捕捉散戶恐慌拋售、大戶暗中接貨的黃金坑。*
* `Price < SMA20`: 股價處於20天線下方（技術破底）。
* `RSI < 35`: 極度超賣狀態。
* `RSI > MFI`: 與引擎一致；RSI 仍弱但相對 MFI 較強，解讀為超賣區資金面相對不更差（非「MFI>RSI」）。
* `RVOL > 1.5x`: 爆發1.5倍以上成交量（震倉放量）。

**♻️ 3. 良性回抽 (Healthy Pullback)**
*捕捉強勢股升浪中的健康調整位，極佳的加注點。*
* `SMA20 < Price < VWAP`: 跌穿日內均價，但大方向守住20天線支撐。
* `RVOL < 1.0x`: 縮量回調（代表跌勢中沒有恐慌拋售）。
* `Gap (PDI - MDI) > 10`: 多頭底子仍在。
* `Stochastic %K < 80`: 高位超買狀態已消化完畢。

**🚀 4. RS破位領頭羊 (RS Breakout)**
*找出無視大市跌勢、極度硬淨的「乾升股」。*
* `RS (20d) > 5%`: 過去20日相對強度跑贏大市 (S&P500/HSI) 5% 以上。
* `OBV > OBV 5MA`: 資金持續流入，無派貨跡象。
* `ADX Slope > 0`: 趨勢動能維持向上。

**📈 5. MACD 動能爆發 (MACD Expansion)**
*捕捉 MACD 柱狀圖由零軸下方翻上、動能重新轉強的時刻。*
* `MACD Hist > 0` 且前一日 `MACD Hist ≤ 0`（零軸上穿）。
* `RVOL ≥ 1.0x`: 成交量至少達 20 日均量（有參與度）。

**🌊 6. 絕地反擊 (Reversal Breakout) — 人機協作**
*只作篩選提示：MACD 柱狀圖較昨日改善，動量與成交配合；是否陽線由你圖上確認。*
* `MACD Hist(t) > MACD Hist(t-1)`（柱狀圖改善）。
* `RSI > 40` **且** `Stoch %K > Stoch %D`（動量修復，兩者同時成立）。
* `RVOL > 1.2`（放量；K 線顏色請肉眼核對）。
* `Close > SMA20`（短線趨勢收回）。
""")

with st.expander("Q: MULTI-FACTOR QUANT MODEL 同 RISK-EXIT RADAR 分數點睇？"):
    st.markdown("""
以下兩個分數，一個主攻「值唔值得買」，一個主攻「持倉危唔危險」。

---

### ① MULTI-FACTOR QUANT MODEL（0–10，越高越好）

**核心公式：**
`Composite = Trend × 40% + Flow × 25% + Location × 20% + Momentum × 15%`

**四大因子基礎：**
- **Trend（40%）**：DMI Gap（PDI-MDI）+ ADX / ADX slope
- **Flow（25%）**：RVOL + OBV 相對 5MA/20MA（資金是否入場）
- **Location（20%）**：價格相對 BB 中軌/上軌、SMA50 的位置安全度
- **Momentum（15%）**：RSI + Stoch（避免過熱追頂）

**分數解讀（偏向進場決策）：**
- **8.0 – 10.0：STRONG BUY**（結構最完整，可積極）
- **6.0 – 7.9：BUY**（條件成立，可分注）
- **4.0 – 5.9：HOLD**（中性，等確認）
- **2.0 – 3.9：SELL**（弱勢，慎入/減倉）
- **0.0 – 1.9：STRONG SELL**（高風險，避免抄底）

---

### ② RISK-EXIT RADAR · 倉位危險雷達（0–10，越高越危險）

**核心公式：**
`Risk Score = Technical Break × 50% + Trend Reversal × 30% + Capital Flight × 20%`

**三層風險基礎：**
- **Technical Break（50%）**：是否跌穿 SMA50、布林中下軌
- **Trend Reversal（30%）**：`MDI - PDI` 是否轉空、空方差距是否擴大
- **Capital Flight（20%）**：OBV 是否連續弱於均線、陰線放量（RVOL）是否出現

**分數解讀（偏向持倉/止蝕決策）：**
- **0.0 – 3.9：SAFE**（結構穩健，可持有）
- **4.0 – 6.9：WARNING**（趨勢鬆動，考慮減磅/對沖）
- **7.0 – 10.0：CRITICAL**（高危，應嚴格執行止蝕）

---

### 實戰用法（簡化版）
- **想搵買點**：先看 `Multi-Factor >= 6`
- **想守倉位**：再看 `Risk-Exit < 4`
- **最好配搭**：`Multi-Factor 高` + `Risk-Exit 低`（先攻後守）
""")

with st.expander("Q: 為什麼 Scanner 有時候掃不出任何股票？"):
    st.markdown("""
**這正是量化系統的價值所在！** 以上六大策略是「極度嚴謹的大戶過濾網」。當大市橫行無方向（例如 ADX 低迷），或未有極端情緒時，系統會自動過濾掉低勝率的雜訊。在華爾街，我們貫徹**「寧願錯過，絕不買錯 (Better missed than lost)」**的原則，幫您保住本金。
""")

with st.expander("Q: ⚖️ 1賠3 值博率計算的意義是什麼？"):
    st.markdown("""
專業對沖基金的長期勝率通常只有 45% - 55%。他們穩定獲利的秘訣在於**「贏谷輸縮」 (正期望值)**。系統根據個股近期的真實波動率 (ATR) 計算出科學止蝕位，並按 1:3 的風險回報比推算出目標價。助您根治「贏粒糖、輸間廠」的散戶通病。
""")
