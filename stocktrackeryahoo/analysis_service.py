"""Stock analysis JSON API — wraps streamlit_app.analyze_stock for HK Stock Hunter Pro."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pytz


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _fmt_num(v, digits=2, suffix=""):
    if v is None:
        return "N/A"
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return "N/A"
        return f"{f:.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def build_ai_report_text(result: dict, factor_scores: dict) -> str:
    """Markdown report for copy-paste into Gemini / ChatGPT (matches Streamlit Full report)."""
    stock_code = result.get("stock_code") or "N/A"
    stock_name = result.get("stock_name") or stock_code
    signal = result.get("signal") or {}
    details = signal.get("details") or {}
    ext = result.get("extended_fundamental_data") or {}

    hk_tz = pytz.timezone("Asia/Hong_Kong")
    report_dt = datetime.now(hk_tz).strftime("%Y-%m-%d %H:%M:%S")
    header = f"Analyze this stock for me: {stock_code} ({stock_name})"

    price = float(result.get("current_price") or 0)
    chg = result.get("price_change")
    chg_pct = result.get("price_change_percent")
    if chg is not None and chg_pct is not None:
        sign = "+" if float(chg) >= 0 else ""
        change_str = f"{sign}{float(chg):.2f} ({sign}{float(chg_pct):.2f}%)"
    else:
        change_str = "N/A"

    rsi_val = details.get("rsi", (result.get("latest_row") or {}).get("rsi"))
    adx_val = details.get("adx", (result.get("latest_row") or {}).get("adx"))
    adx_slope_val = details.get("adx_slope", (result.get("latest_row") or {}).get("adx_slope"))
    pdi_val = details.get("dmi_plus", (result.get("latest_row") or {}).get("dmi_plus"))
    mdi_val = details.get("dmi_minus", (result.get("latest_row") or {}).get("dmi_minus"))
    gap = (float(pdi_val) - float(mdi_val)) if pdi_val is not None and mdi_val is not None else None

    bb_u = details.get("bb_upper")
    bb_m = details.get("bb_middle")
    bb_l = details.get("bb_lower")
    sma_200 = details.get("sma_200")
    sma_50 = details.get("sma_50")
    atr_val = details.get("atr", (result.get("latest_row") or {}).get("atr"))
    rvol_val = details.get("rvol", (result.get("latest_row") or {}).get("rvol"))
    mfi_val = details.get("mfi", (result.get("latest_row") or {}).get("mfi"))
    rs_out = details.get("rs_20d_outperform")

    market_cap = ext.get("market_cap")
    if market_cap is not None:
        mc = float(market_cap)
        if mc >= 1e12:
            market_cap_str = f"{mc/1e12:.2f}T"
        elif mc >= 1e9:
            market_cap_str = f"{mc/1e9:.2f}B"
        elif mc >= 1e6:
            market_cap_str = f"{mc/1e6:.2f}M"
        else:
            market_cap_str = f"{mc:.2f}"
    else:
        market_cap_str = "N/A"

    fund = result.get("fundamental_status") or {}
    trailing_pe = fund.get("trailing_pe")
    forward_pe = fund.get("forward_pe")
    peg = fund.get("peg_ratio")
    debt_eq = fund.get("debt_to_equity")
    profit_m = fund.get("profit_margins")
    profit_m_str = f"{float(profit_m)*100:.2f}%" if profit_m is not None else "N/A"

    next_earnings = ext.get("next_earnings") or "N/A"
    w52h = ext.get("week_52_high")
    w52l = ext.get("week_52_low")

    signal_advice = signal.get("advice", "無訊號")
    signal_reason = signal.get("commentary", signal.get("reason", ""))

    _mh = details.get("macd_hist")
    _mhp = details.get("macd_hist_prev")
    _ml = details.get("macd_line")
    _ms = details.get("macd_signal")
    macd_zc = "N/A"
    if _mh is not None and _mhp is not None:
        try:
            macd_zc = "Yes" if (float(_mh) > 0 and float(_mhp) <= 0) else "No"
        except (TypeError, ValueError):
            pass

    ref_lines = ""
    ref_put = details.get("suggested_put_strike")
    ref_call = details.get("suggested_call_strike")
    if ref_put is not None or ref_call is not None:
        ref_lines = "\n[Reference option strike — 模型參考行使價]\n"
        if ref_put is not None:
            ref_lines += f"Suggested Short Put strike: ≤ {float(ref_put):.2f}\n"
        if ref_call is not None:
            ref_lines += f"Suggested Short Call strike: ≥ {float(ref_call):.2f}\n"

    part1 = f"""Report Generated: {report_dt} (HKT)
{header}

[Part 1: Real-Time Snapshot]
Price: {price:.2f} ({change_str})

[Multi-Factor Quant Model]
Composite: {factor_scores.get('composite', 0):.1f}/10 → {factor_scores.get('rating', 'N/A')}
Trend (40%): {factor_scores.get('trend', 0):.1f} | Flow (25%): {factor_scores.get('flow', 0):.1f} | Location (20%): {factor_scores.get('location', 0):.1f} | Momentum (15%): {factor_scores.get('momentum', 0):.1f}

[Risk-Exit Radar]
Risk Score: {result.get('risk_score', 0):.1f}/10 → {result.get('risk_label', 'N/A')}
Technical: {(result.get('risk_breakdown') or {}).get('tech_risk', 'N/A')} | Trend: {(result.get('risk_breakdown') or {}).get('trend_risk', 'N/A')} | Flow: {(result.get('risk_breakdown') or {}).get('flow_risk', 'N/A')}

[Technical Structure]
RSI: {_fmt_num(rsi_val)} | ADX: {_fmt_num(adx_val)} (Slope: {_fmt_num(adx_slope_val)}) | PDI: {_fmt_num(pdi_val)} | MDI: {_fmt_num(mdi_val)} | Gap: {_fmt_num(gap)}
ATR: {_fmt_num(atr_val)} | Bollinger: {_fmt_num(bb_u)} / {_fmt_num(bb_m)} / {_fmt_num(bb_l)} | SMA 200: {_fmt_num(sma_200)} | SMA 50: {_fmt_num(sma_50)}
52W Range: {_fmt_num(w52l)} - {_fmt_num(w52h)}

[MACD (12,26,9)]
Line: {_fmt_num(_ml, 4)} | Signal: {_fmt_num(_ms, 4)} | Hist: {_fmt_num(_mh, 4)} | Hist (prev): {_fmt_num(_mhp, 4)} | Zero-cross: {macd_zc}

[Fundamental Health]
Market Cap: {market_cap_str} | PE (Trail/Fwd): {_fmt_num(trailing_pe)} / {_fmt_num(forward_pe)} | PEG: {_fmt_num(peg)}
Profit Margin: {profit_m_str} | Debt/Eq: {_fmt_num(debt_eq)}

[Risk Check]
Next Earnings: {next_earnings} | RVOL: {_fmt_num(rvol_val)} | MFI: {_fmt_num(mfi_val)}

[Comparative RS]
Comparative RS (20d Outperformance vs Market): {_fmt_num(rs_out)}%
{ref_lines}
[Robot Signal]
{signal_advice}
{signal_reason or 'No additional signal details'}"""

    history = result.get("history_log_10d") or ""
    part2_lines = history.split("\n")[3:] if history else []
    part2 = "\n".join(part2_lines) if part2_lines else "(No 10-day data)"
    return part1 + "\n\n========================================\n=== 📜 10-DAY TREND LOG ===\n\n" + part2


def run_stock_analysis_api(stock_code_input: str) -> dict:
    """Run full Hunter analysis; return JSON-safe dict for REST API."""
    from streamlit_app import analyze_stock, normalize_stock_code, score_factors

    raw_input = str(stock_code_input or "").strip()
    if not raw_input:
        return {"ok": False, "error": "Please enter a stock code"}

    try:
        normalized = normalize_stock_code(raw_input)
    except Exception as e:
        return {"ok": False, "error": f"Invalid code: {e}"}

    result = analyze_stock(normalized, original_input=raw_input)
    if not result.get("success"):
        return {
            "ok": False,
            "error": result.get("error") or "Analysis failed",
            "stock_code": normalized,
        }

    signal = result.get("signal") or {}
    details = signal.get("details") or {}
    latest_row = result.get("latest_row") or {}
    factors = score_factors(latest_row, details)
    ai_report = build_ai_report_text(result, factors)

    rb = result.get("risk_breakdown") or {}
    tech_r = float(rb.get("tech_risk") or 0)
    trend_r = float(rb.get("trend_risk") or 0)
    flow_r = float(rb.get("flow_risk") or 0)

    return _json_safe(
        {
            "ok": True,
            "stock_code": result.get("stock_code"),
            "stock_name": result.get("stock_name"),
            "original_input": raw_input,
            "current_price": result.get("current_price"),
            "price_change": result.get("price_change"),
            "price_change_percent": result.get("price_change_percent"),
            "timestamp": result.get("timestamp"),
            "latest_data_date": result.get("latest_data_date"),
            "signal": {
                "advice": signal.get("advice"),
                "commentary": signal.get("commentary") or signal.get("reason"),
                "type": signal.get("type"),
            },
            "factors": {
                "composite": factors.get("composite"),
                "rating": factors.get("rating"),
                "momentum": factors.get("momentum"),
                "trend": factors.get("trend"),
                "flow": factors.get("flow"),
                "location": factors.get("location"),
            },
            "risk": {
                "score": result.get("risk_score"),
                "label": result.get("risk_label"),
                "tech": tech_r,
                "trend": trend_r,
                "flow": flow_r,
                "tech_weighted": round(tech_r * 0.5, 2),
                "trend_weighted": round(trend_r * 0.3, 2),
                "flow_weighted": round(flow_r * 0.2, 2),
            },
            "indicators": {
                "rsi": details.get("rsi", latest_row.get("rsi")),
                "adx": details.get("adx", latest_row.get("adx")),
                "adx_slope": details.get("adx_slope", latest_row.get("adx_slope")),
                "pdi": details.get("dmi_plus", latest_row.get("dmi_plus")),
                "mdi": details.get("dmi_minus", latest_row.get("dmi_minus")),
                "rvol": details.get("rvol", latest_row.get("rvol")),
                "mfi": details.get("mfi", latest_row.get("mfi")),
                "vwap": details.get("vwap", latest_row.get("vwap")),
                "macd_hist": details.get("macd_hist", latest_row.get("macd_hist")),
                "rs_20d": details.get("rs_20d_outperform", latest_row.get("RS_20d_Outperform")),
            },
            "fundamental_status": result.get("fundamental_status"),
            "news_text": result.get("news_text"),
            "ai_report": ai_report,
        }
    )
