"""
SCSP神器 - Streamlit Application
Streamlit web interface for the mean-reversion trading strategy
"""

import streamlit as st
import sys
import os

# Repo root on path first (for yfinance_bootstrap + backtest_options).
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

try:
    import yfinance_bootstrap

    yfinance_bootstrap.enable()
except Exception:
    pass

import pandas as pd
import ta
import yfinance as yf
import re
import json
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import google.generativeai as genai

from macro_advanced import fetch_advanced_macro_data

# Veteran backtest engine (embed backtest under Stock Analysis page)
try:
    import backtest_options as _bt
    from backtest_options import fetch_data_yfinance, add_indicators, run_veteran_backtest
except Exception:
    _bt = None

from daily_scanner import macd_histogram_status

SYSTEM_PROMPT = (
    "你是一位在華爾街和中環打滾了 20 年的「資深對沖基金經理」。"
    "你的任務是審查股票數據並給出實戰建議。"
    "請嚴格根據 VWAP、OBV、RVOL、RSI、MFI、ADX slope、Stochastic %K/%D、PDI-MDI Gap、RS 等數據，判斷是真突破還是假動作，並給出期權 (Short Put/Call) 的具體防守位。"
    "並給出期權 (Short Put/Call) 的具體防守位。"
    "語氣要幽默、抵死、帶點廣東話口語，踢爆散戶迷思。"
)


def _is_sell_put_trading_persona(score_model: str | None, trading_mode: str | None) -> bool:
    s = str(score_model or "").lower()
    t = str(trading_mode or "")
    return ("sell_put" in s) or ("收租" in t) or ("sell put" in t.lower())


def build_gemini_system_prompt_for_trading_mode(
    *,
    score_model: str | None = None,
    trading_mode: str | None = None,
    score: str,
    close: str,
    vwap: str,
    rvol: str,
    adx: str,
    macd_status: str,
    rs: str,
) -> str:
    """
    Numstation 2.0 — Gemini 人設：保守賣方 (Sell Put) vs 激進買方 (Buy Call / buy_stock) vs 激進做淡 (buy_put)。
    score 為 0–100 字串（Stock Analysis 可用合成評分×10）；rs 建議已含 % 單位。
    """
    sm = str(score_model or "").lower()
    tm = str(trading_mode or "")
    if "buy_put" in sm or "做淡" in tm or "buy put" in tm.lower():
        return f"""
你現在是 Numstation 2.0 的激進做淡 (Short Seller / Put Buyer) 操盤手。你的風格是「捕捉恐慌拋售、極速破底、狙擊弱勢股」。
請根據以下技術數據，寫一段大約 100-150 字的【系統策略草稿】（繁體中文）：

標的數據：評分={score}/100, 收盤價={close}, VWAP={vwap}, RVOL={rvol}, ADX={adx}, MACD={macd_status}, RS={rs}

【寫作要求】：
1. 嚴禁提及「撈底、支撐、買入、多方佔優」等造好字眼。
2. 重點分析「下殺動能、恐慌資金流 (RVOL)、以及弱勢趨勢 (ADX & 負 RS)」。
3. 針對 MACD：必須指出是否處於「空頭柱體擴張 (跌勢加速)」還是「空頭收斂 (跌勢減弱)」。若紅柱縮短，警告追沽風險。
4. 針對 VWAP：指出 VWAP ({vwap}) 已成為上方強大阻力。若收盤價高於 VWAP，警告反彈風險，不宜造淡。
5. 給出具體的 Buy Put / 沽空建議：例如「適合 Buy Put 或 Bear Put Spread」，或在缺乏放量下殺時建議「觀望，等待量能放大」。
""".strip()

    if _is_sell_put_trading_persona(score_model, trading_mode):
        return f"""
你現在是 Numstation 2.0 的頂級期權賣方 (Option Seller) 操盤手。你的風格是極度重視「防守、安全墊、支撐位」。
請根據以下技術數據，寫一段大約 100-150 字的【系統策略草稿】（繁體中文）：

標的數據：評分={score}/100, 收盤價={close}, VWAP={vwap}, RVOL={rvol}, ADX={adx}, MACD={macd_status}, RS={rs}

【寫作要求】：
1. 嚴禁提及「順勢追入、突破、加碼」等買方字眼。
2. 重點分析「下行風險」與「支撐位」(例如比較收盤價與 VWAP 的距離)。如果偏離太遠，必須警告高位回調風險。
3. 針對 MACD：如果紅柱縮短，指出這是「跌勢枯竭，適合佈局」；如果綠柱縮短，警告「衝刺完結，可能均值回歸」。
4. 給出具體的 Sell Put 建議：例如「建議將行使價設於 VWAP ({vwap}) 或更低位置以獲取安全墊」。
""".strip()

    return f"""
你現在是 Numstation 2.0 的激進期權買方 (Option Buyer) 操盤手。你的風格是「捕捉爆發點、順勢而為、刀口舔血」。
請根據以下技術數據，寫一段大約 100-150 字的【系統策略草稿】（繁體中文）：

標的數據：評分={score}/100, 收盤價={close}, VWAP={vwap}, RVOL={rvol}, ADX={adx}, MACD={macd_status}, RS={rs}

【寫作要求】：
1. 重點分析「向上爆發力、資金流入 (RVOL)、以及趨勢強度 (ADX & RS)」。
2. 針對 MACD：必須指出是否處於「水面爆發 (綠柱放大)」還是仍在「水底橫盤」。若在水底，警告假突破風險。
3. 針對 VWAP：如果收盤價跌穿 VWAP，警告日內沽壓強，不宜急進。
4. 給出具體的 Buy Call / 正股突破建議：例如「適合 Buy Call 或 Bull Call Spread」，或在缺乏量能時建議「耐心觀望，等待放量綠柱」。
""".strip()


# Version information
VERSION = "3.0"

# Try to read version from version.txt if it exists
try:
    version_file = os.path.join(os.path.dirname(__file__), 'version.txt')
    if os.path.exists(version_file):
        with open(version_file, 'r') as f:
            VERSION = f.read().strip()
except:
    pass


def score_factors(latest_row, details):
    """
    Professional weighted factor model (0..10).
    Returns per-factor scores (0..10), weighted composite score (0..10), and rating label.
    """
    price = float(details.get("close_price", latest_row.get("close", 0.0)))
    rsi = float(details.get("rsi", latest_row.get("rsi", 50.0)))
    stoch_k = latest_row.get("stoch_k", details.get("stoch_k"))
    try:
        stoch_k = float(stoch_k) if stoch_k is not None else 50.0
    except Exception:
        stoch_k = 50.0

    # --- 1) 趨勢霸權 Trend (DMI & ADX) - Weight: 40% ---
    pdi = float(details.get("dmi_plus", latest_row.get("dmi_plus", 0.0)))
    mdi = float(details.get("dmi_minus", latest_row.get("dmi_minus", 0.0)))
    adx = float(details.get("adx", latest_row.get("adx", 0.0)))
    adx_slope = float(details.get("adx_slope", latest_row.get("adx_slope", 0.0)))
    gap = pdi - mdi
    if gap > 20:
        gap_score = 10
    elif gap > 10:
        gap_score = 8
    elif gap > 0:
        gap_score = 5
    else:
        gap_score = 0

    if adx > 30 and adx_slope > 0:
        adx_score = 10
    elif adx >= 20 and adx_slope > 0:
        adx_score = 7
    else:
        adx_score = 3
    trend_score = (gap_score + adx_score) / 2.0

    # --- 2) 資金真章 Flow (RVOL & OBV) - Weight: 25% ---
    rvol = float(details.get("rvol", latest_row.get("rvol", 1.0)))
    if rvol > 2.0:
        rvol_score = 10
    elif rvol >= 1.0:
        rvol_score = 8
    elif rvol >= 0.5:
        rvol_score = 5
    else:
        rvol_score = 2

    obv = latest_row.get("obv")
    obv_5ma = latest_row.get("obv_5ma")
    try:
        obv = float(obv) if obv is not None else None
        obv_5ma = float(obv_5ma) if obv_5ma is not None else None
    except Exception:
        obv = None
        obv_5ma = None
    obv_score = 10 if (obv is not None and obv_5ma is not None and obv > obv_5ma) else 0
    flow_score = (rvol_score + obv_score) / 2.0

    # --- 3) 位置安全度 Location (BB & SMA) - Weight: 20% ---
    upper_band = float(details.get("bb_upper", latest_row.get("bb_upper", price)))
    middle_band = float(details.get("bb_middle", latest_row.get("bb_middle", price)))
    sma50 = details.get("sma_50", latest_row.get("sma_50"))
    try:
        sma50 = float(sma50) if sma50 is not None else None
    except Exception:
        sma50 = None

    dist_mid = (abs(price - middle_band) / middle_band * 100.0) if middle_band else 999.0
    if dist_mid <= 1.0:
        loc_score = 10
    elif sma50 is not None and price > sma50 and price < middle_band:
        loc_score = 8
    elif price > upper_band:
        loc_score = 2
    elif price > middle_band + (upper_band - middle_band) * 0.8:
        loc_score = 4
    else:
        loc_score = 5

    # --- 4) 動量冷熱 Momentum (RSI & Stochastic) - Weight: 15% ---
    if 40 <= rsi <= 60:
        mom_score = 10
    elif rsi > 70 or stoch_k > 80:
        mom_score = 4
    elif rsi < 30:
        mom_score = 8
    else:
        mom_score = 6

    # --- Exhaustion / Reversal Guardrails ---
    sma200 = details.get("sma_200", latest_row.get("sma_200"))
    try:
        sma200 = float(sma200) if sma200 is not None else None
    except Exception:
        sma200 = None
    dist_sma200_pct = ((price - sma200) / sma200 * 100.0) if (sma200 is not None and sma200 != 0) else None
    low_20 = latest_row.get("low_20", latest_row.get("low"))
    try:
        low_20 = float(low_20) if low_20 is not None else None
    except Exception:
        low_20 = None

    exhaustion = (adx > 45) and (rsi < 25 or rsi > 75)
    low_volume_test = (low_20 is not None) and (price <= low_20) and (rvol < 0.5)
    iron_support = (dist_sma200_pct is not None) and (abs(dist_sma200_pct) <= 3.0)
    macd_line = details.get("macd_line", latest_row.get("macd_line"))
    macd_hist = details.get("macd_hist", latest_row.get("macd_hist"))
    macd_hist_prev = details.get("macd_hist_prev", latest_row.get("macd_hist_prev"))
    macd_hist_prev2 = latest_row.get("macd_hist_prev2")
    try:
        macd_line = float(macd_line) if macd_line is not None else None
        macd_hist = float(macd_hist) if macd_hist is not None else None
        macd_hist_prev = float(macd_hist_prev) if macd_hist_prev is not None else None
        macd_hist_prev2 = float(macd_hist_prev2) if macd_hist_prev2 is not None else None
    except Exception:
        macd_line = macd_hist = macd_hist_prev = macd_hist_prev2 = None
    macd_improving = (
        macd_line is not None and macd_line < 0 and
        macd_hist is not None and macd_hist_prev is not None and macd_hist_prev2 is not None and
        (macd_hist > macd_hist_prev > macd_hist_prev2)
    )

    # --- 5) Total Weighted Score (0..10) ---
    composite = (trend_score * 0.40) + (flow_score * 0.25) + (loc_score * 0.20) + (mom_score * 0.15)

    # --- Hard Penalty for Falling Knives (MDI Dominance) ---
    if gap < -10:
        composite -= 5.0
        composite = max(0.0, composite)

    # Rule 1: exhaustion oversold reversal bonus
    if exhaustion and rsi < 25:
        composite += 1.5

    # Rule 2/3/4: prevent bottom-chasing "strong sell" collapse
    if low_volume_test:
        composite = max(composite, 4.2)
    if iron_support:
        composite = max(composite, 4.0)
    if macd_improving:
        composite = max(composite, 4.3)
    composite = min(10.0, max(0.0, composite))

    # Rating thresholds (0..10)
    if composite >= 8.0:
        rating = "STRONG BUY"
    elif composite >= 6.0:
        rating = "BUY"
    elif composite >= 4.0:
        rating = "HOLD"
    elif composite >= 2.0:
        rating = "SELL"
    else:
        rating = "STRONG SELL"

    # Override bearish extremes around reversal-supportive regimes
    if rating in ("STRONG SELL", "SELL") and (low_volume_test or iron_support or macd_improving):
        rating = "WATCH / NEUTRAL"
    if exhaustion and rating == "STRONG BUY":
        rating = "BUY"

    return {
        "momentum": mom_score,
        "trend": trend_score,
        "flow": flow_score,
        "location": loc_score,
        "composite": composite,
        "rating": rating,
        "exhaustion": bool(exhaustion),
        "low_volume_test": bool(low_volume_test),
        "iron_support": bool(iron_support),
        "macd_improving": bool(macd_improving),
    }


def _compute_risk_exit_score(df, details, latest_row):
    """
    Risk-Exit Score (0-10): how dangerous it is to HOLD.
    Layers: Technical Break (50%), Trend Reversal (30%), Capital Flight (20%).
    Returns dict: risk_score, risk_label, tech_risk, trend_risk, flow_risk (each layer raw 0..10).
    """
    _safe = {
        "risk_score": 0.0,
        "risk_label": "✅ 安全 (SAFE) - 結構穩健，可繼續持有。",
        "tech_risk": 0.0,
        "trend_risk": 0.0,
        "flow_risk": 0.0,
    }
    try:
        price = float(details.get("close_price", latest_row.get("close", 0.0)))
        pdi = float(details.get("dmi_plus", latest_row.get("dmi_plus", 0.0)))
        mdi = float(details.get("dmi_minus", latest_row.get("dmi_minus", 0.0)))
        rvol = float(details.get("rvol", latest_row.get("rvol", 1.0)))
        lower_band = float(details.get("bb_lower", latest_row.get("bb_lower", price)))
        middle_band = float(details.get("bb_middle", latest_row.get("bb_middle", price)))
        sma50_raw = details.get("sma_50", latest_row.get("sma_50"))
        sma50 = float(sma50_raw) if sma50_raw is not None else None

        # Layer 1: Technical Break (Weight 50%, Max 10 points)
        tech_risk = 0
        if sma50 is not None and price < sma50 * 0.99:
            tech_risk += 5
        if price < lower_band:
            tech_risk += 5
        elif price < middle_band:
            tech_risk += 2
        tech_risk = min(10, tech_risk)

        # Layer 2: Trend Reversal (Weight 30%, Max 10 points)
        trend_risk = 0
        death_gap = mdi - pdi
        if death_gap > 15:
            trend_risk = 10
        elif death_gap > 0:
            trend_risk = 6

        # Layer 3: Capital Flight (Weight 20%, Max 10 points)
        flow_risk = 0
        if "obv" in df.columns and "obv_5ma" in df.columns and len(df) >= 3:
            obv_3d_drop = all(
                pd.notna(df["obv"].iloc[-i])
                and pd.notna(df["obv_5ma"].iloc[-i])
                and df["obv"].iloc[-i] < df["obv_5ma"].iloc[-i]
                for i in range(1, 4)
            )
        else:
            obv_3d_drop = False
        if obv_3d_drop:
            flow_risk += 4
        if "close" in df.columns and len(df) >= 2:
            close_curr = float(df["close"].iloc[-1])
            close_prev = float(df["close"].iloc[-2])
            if close_prev and close_prev != 0:
                daily_return = (close_curr - close_prev) / close_prev
                if daily_return < 0 and rvol > 1.5:
                    flow_risk += 6
        flow_risk = min(10, flow_risk)

        risk_score = (tech_risk * 0.50) + (trend_risk * 0.30) + (flow_risk * 0.20)
        risk_score = min(10.0, max(0.0, risk_score))

        if risk_score >= 7.0:
            risk_label = "🚨 滅門位 (CRITICAL DANGER) - 必須執行止蝕！"
        elif risk_score >= 4.0:
            risk_label = "⚠️ 警報 (WARNING) - 趨勢鬆動，準備減磅。"
        else:
            risk_label = "✅ 安全 (SAFE) - 結構穩健，可繼續持有。"
        return {
            "risk_score": risk_score,
            "risk_label": risk_label,
            "tech_risk": float(tech_risk),
            "trend_risk": float(trend_risk),
            "flow_risk": float(flow_risk),
        }
    except Exception as e:
        print(f"⚠️ Risk-exit score computation failed: {e}")
        return dict(_safe)


# Page config and CSS only when run as main (skip when embedded in HK Stock Hunter)
if __name__ == "__main__":
    st.set_page_config(
        page_title="股票分析器",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

# Custom CSS for Light Cyber / Modern FinTech (only when run as main; embedded uses config.toml)
if __name__ == "__main__":
    st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    /* Inter font — top-tier FinTech typography */
    .stApp, .main, .block-container, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    /* Light tech background */
    .main {
        background-color: #F4F7F9;
        padding-top: 1rem;
    }
    .stApp {
        background-color: #F4F7F9;
    }
    
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        max-width: 1400px;
    }
    
    /* Typography — sharp dark grey, Inter */
    h1, h2, h3 {
        color: #111827;
        font-weight: 600;
        font-family: 'Inter', sans-serif;
    }
    h1 { font-size: 1.75rem; margin-bottom: 0.25rem; }
    h2 { font-size: 1.5rem; margin-top: 1.5rem; margin-bottom: 0.75rem; }
    h3 { font-size: 1.25rem; margin-top: 1rem; margin-bottom: 0.5rem; }
    
    .stContainer {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    
    .stTextInput > div > div > input {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 4px;
        color: #111827;
        font-size: 1rem;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #0055FF;
        box-shadow: 0 0 0 3px rgba(0,85,255,0.15);
    }
    
    /* Electric Blue primary buttons */
    .stButton > button {
        background-color: #0055FF;
        color: #ffffff;
        border: none;
        border-radius: 4px;
        font-weight: 600;
        padding: 0.5rem 1.5rem;
        font-size: 0.95rem;
        transition: all 0.2s;
    }
    
    .stButton > button:hover {
        background-color: #0044CC;
        box-shadow: 0 4px 12px rgba(0,85,255,0.25);
    }
    
    [data-testid="stExpander"] summary {
        background-color: #0055FF !important;
        color: white !important;
        border: 1px solid #0044CC !important;
        font-weight: 600 !important;
        padding: 0.5rem 1rem !important;
        border-radius: 4px;
    }
    [data-testid="stExpander"] summary:hover {
        background-color: #0044CC !important;
        border-color: #003399 !important;
    }
    
    .main .stMarkdown h3 { margin-top: 0.75rem; margin-bottom: 0.35rem; }
    .main .stMarkdown p { margin-bottom: 0.25rem; }
    
    [data-testid="stMetricValue"] {
        color: #0055FF;
        font-weight: 800;
    }
    
    [data-testid="stMetricLabel"] {
        color: #6B7280;
        font-weight: 500;
        font-size: 0.875rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    [data-testid="stMetricDelta"] {
        font-weight: 600;
        font-size: 1rem;
    }
    
    /* Info boxes */
    .stInfo {
        background-color: #e0f2fe;
        border-left: 4px solid #0055FF;
        border-radius: 4px;
    }
    
    .stSuccess {
        background-color: #d1fae5;
        border-left: 4px solid #10b981;
    }
    
    .stWarning {
        background-color: #fef3c7;
        border-left: 4px solid #f59e0b;
    }
    
    .stError {
        background-color: #fee2e2;
        border-left: 4px solid #ef4444;
    }
    
    /* Markdown text */
    .stMarkdown {
        color: #374151;
        line-height: 1.6;
    }
    
    .stMarkdown strong {
        color: #111827;
        font-weight: 600;
    }
    
    /* Divider */
    hr {
        border: none;
        border-top: 1px solid #e5e7eb;
        margin: 1.5rem 0;
    }
    
    /* Code blocks */
    code {
        background-color: #f3f4f6;
        color: #0055FF;
        padding: 0.2rem 0.4rem;
        border-radius: 3px;
        font-size: 0.875rem;
    }
    
    /* Remove Streamlit default styling */
    .stApp > header {
        background-color: #FFFFFF;
        border-bottom: 2px solid #0055FF;
    }
    
    /* Professional spacing */
    .element-container {
        margin-bottom: 1rem;
    }
</style>
    """, unsafe_allow_html=True)


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
    
    # Calculate ADX (period 14) with DMI+ and DMI- (N=14, M=14)
    from adx_ewm import calculate_adx_ewm
    adx_result = calculate_adx_ewm(df, n=14, m=14)
    df['adx'] = adx_result['adx']
    df['dmi_plus'] = adx_result['pdi']  # DMI+ (PDI)
    df['dmi_minus'] = adx_result['mdi']  # DMI- (MDI)
    
    # Calculate ADX slope
    df['adx_slope'] = df['adx'].diff()
    
    # Detect Bullish Pin Bar
    df['is_pin_bar'] = df.apply(detect_bullish_pin_bar, axis=1)
    
    # Calculate MFI (Money Flow Index) - Period 14
    try:
        mfi_indicator = ta.volume.MFIIndicator(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            volume=df['volume'],
            window=14
        )
        # Use the correct method name: money_flow_index()
        df['mfi'] = mfi_indicator.money_flow_index()
    except Exception as e:
        # If MFI calculation fails, set to NaN and continue
        import warnings
        warnings.warn(f"MFI calculation failed: {e}. Setting MFI to NaN.")
        df['mfi'] = pd.NA
    
    # Calculate RVOL (Relative Volume) - Ratio of current volume to 20-day SMA of volume
    # Avoid division by zero
    volume_sma_20 = df['volume'].rolling(window=20).mean()
    df['rvol'] = df['volume'] / volume_sma_20.replace(0, pd.NA)
    # Replace infinite values with NaN
    df['rvol'] = df['rvol'].replace([float('inf'), float('-inf')], pd.NA)
    
    # Calculate SMA 50 and SMA 200 (for trend analysis)
    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['sma_200'] = df['close'].rolling(window=200).mean()
    
    # OBV (On-Balance Volume): +Volume if Close > Prev_Close, -Volume if Close < Prev_Close, else 0; cumulative
    close_diff = df['close'].diff()
    obv_direction = (close_diff > 0).astype(float) - (close_diff < 0).astype(float)
    obv_direction = obv_direction.fillna(0)
    df['obv'] = (obv_direction * df['volume']).cumsum()
    df['obv_5ma'] = df['obv'].rolling(window=5).mean()
    
    # Daily VWAP proxy (Typical Price for daily bars): (High + Low + Close) / 3
    df['vwap'] = (df['high'] + df['low'] + df['close']) / 3
    
    # OBV 5-day slope (change in OBV over last 5 days)
    df['obv_slope_5d'] = df['obv'] - df['obv'].shift(5)
    
    # Stochastic Oscillator: %K and %D (window=14, smooth_window=3)
    try:
        stoch = ta.momentum.StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()
    except Exception:
        df['stoch_k'] = pd.NA
        df['stoch_d'] = pd.NA

    # MACD (12, 26, 9) — same convention as backtest_options.add_indicators
    _c = df['close']
    df['ema_12'] = _c.ewm(span=12, adjust=False).mean()
    df['ema_26'] = _c.ewm(span=26, adjust=False).mean()
    df['macd_line'] = df['ema_12'] - df['ema_26']
    df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd_line'] - df['macd_signal']
    df['macd_hist_prev'] = df['macd_hist'].shift(1)

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
    
    analysis_parts = []
    
    # 1. Trend Analysis (ADX & DI)
    trend_desc = ""
    adx_value_str = "N/A"
    if pd.notna(current_adx):
        adx_value = float(current_adx)
        adx_value_str = f"{adx_value:.2f}"
        if adx_value > ADX_THRESHOLD:
            trend_desc = "強勢趨勢"
        elif adx_value < 25:
            trend_desc = "弱勢趨勢 / 橫盤整理"
        else:
            trend_desc = "中等趨勢 / 轉換期"
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
    
    return "\n\n".join(analysis_parts)


def get_detailed_wait_analysis(df, signal_type='wait'):
    """
    Generate detailed analysis for WAIT signals explaining WHY there's no trade signal.
    Returns specific explanations for different WAIT scenarios.
    """
    if len(df) < 1:
        return ""
    
    latest = df.iloc[-1]
    
    current_adx = latest.get('adx', pd.NA)
    pdi = latest.get('dmi_plus', pd.NA)
    mdi = latest.get('dmi_minus', pd.NA)
    rsi = latest.get('rsi', pd.NA)
    close_price = latest.get('close', pd.NA)
    bb_upper = latest.get('bb_upper', pd.NA)
    bb_lower = latest.get('bb_lower', pd.NA)
    is_pin_bar = latest.get('is_pin_bar', False)
    
    wait_analysis_parts = []
    
    # Check if we have valid data
    if pd.isna(close_price) or pd.isna(bb_upper) or pd.isna(bb_lower):
        return ""
    
    close_val = float(close_price)
    upper_val = float(bb_upper)
    lower_val = float(bb_lower)
    rsi_val = float(rsi) if pd.notna(rsi) else None
    
    # NEW: Scenario - Choppy Trend (ADX > ADX_THRESHOLD but PDI/MDI gap < PDI_MDI_GAP)
    if pd.notna(current_adx) and pd.notna(pdi) and pd.notna(mdi):
        adx_val = float(current_adx)
        pdi_val = float(pdi)
        mdi_val = float(mdi)
        
        if adx_val > ADX_THRESHOLD:
            pdi_mdi_gap = abs(pdi_val - mdi_val)
            if pdi_mdi_gap < PDI_MDI_GAP:
                wait_analysis_parts.append("🌪️ **趨勢混亂：多空力量接近**")
                wait_analysis_parts.append(f"雖然 ADX 顯示強勢趨勢（{adx_val:.2f} > {ADX_THRESHOLD}），但多空雙方力量接近（PDI: {pdi_val:.2f}, MDI: {mdi_val:.2f}，差距僅 {pdi_mdi_gap:.2f} < {PDI_MDI_GAP}）。")
                wait_analysis_parts.append("多空雙方正在激烈爭奪，趨勢方向不明確。這是市場噪音，而非明確趨勢。此時交易風險較高，建議等待更明確的方向。")
                return "\n\n".join(wait_analysis_parts)
    
    # NEW: Scenario - Band Squeeze (Bandwidth < BB_BANDWIDTH_MIN%)
    bb_middle = latest.get('bb_middle', pd.NA)
    if pd.notna(bb_upper) and pd.notna(bb_lower) and pd.notna(bb_middle):
        bandwidth_pct = ((float(bb_upper) - float(bb_lower)) / float(bb_middle)) * 100
        if bandwidth_pct < BB_BANDWIDTH_MIN:
            wait_analysis_parts.append("🤏 **波動率收窄：布林通道過緊**")
            wait_analysis_parts.append(f"布林通道寬度僅 {bandwidth_pct:.2f}% < {BB_BANDWIDTH_MIN}%，波動率過低，通道過於緊窄。")
            wait_analysis_parts.append("這通常預示著即將出現大幅波動（突破或崩跌）。在通道收窄時進行均值回歸交易風險極高，建議等待方向明確後再進場，避免在波動爆發前被套。")
            return "\n\n".join(wait_analysis_parts)
    
    # Scenario 4: Trend Confusion (check first as it can apply regardless of price position)
    # But only if we have the necessary data
    trend_confusion_detected = False
    if pd.notna(current_adx) and pd.notna(rsi) and rsi_val is not None:
        adx_val = float(current_adx)
        adx_slope = latest.get('adx_slope', pd.NA)
        
        # Check if ADX is rising (trend strengthening)
        adx_rising = pd.notna(adx_slope) and float(adx_slope) > 0
        
        # Check for conflicting signals
        if adx_val > 25 and adx_rising and pd.notna(pdi) and pd.notna(mdi):
            pdi_val = float(pdi)
            mdi_val = float(mdi)
            # Uptrend but RSI not confirming
            if pdi_val > mdi_val and rsi_val < 50:
                wait_analysis_parts.append("🌪️ **訊號衝突：趨勢指標與動量指標不一致**")
                wait_analysis_parts.append("ADX 顯示上升趨勢正在加強，但 RSI 顯示動量不足。")
                wait_analysis_parts.append("趨勢指標和動量指標出現分歧，最好暫時觀望，等待更明確的信號。")
                trend_confusion_detected = True
            # Downtrend but RSI not confirming
            elif mdi_val > pdi_val and rsi_val > 50:
                wait_analysis_parts.append("🌪️ **訊號衝突：趨勢指標與動量指標不一致**")
                wait_analysis_parts.append("ADX 顯示下降趨勢正在加強，但 RSI 顯示動量仍然強勁。")
                wait_analysis_parts.append("趨勢指標和動量指標出現分歧，最好暫時觀望，等待更明確的信號。")
                trend_confusion_detected = True
    
    # If trend confusion detected, return it (it's more important than price position)
    if trend_confusion_detected:
        return "\n\n".join(wait_analysis_parts)
    
    # Scenario 1: Price broke/touched LOWER Band, but NO Signal
    if close_val <= lower_val:
        # Check why there's no signal
        rsi_not_oversold = rsi_val is None or rsi_val >= 30
        no_pin_bar = not is_pin_bar
        
        if rsi_not_oversold and no_pin_bar:
            wait_analysis_parts.append("⚠️ **危險：價格已跌破下軌，但無交易訊號**")
            wait_analysis_parts.append("價格已經跌破布林下軌，但 RSI 未達到超賣水平（<30），且沒有出現看漲針形（拒絕信號）。")
            wait_analysis_parts.append("這看起來像是「接飛刀」的情況，等待價格穩定後再考慮進場。")
            return "\n\n".join(wait_analysis_parts)
    
    # Scenario 2: Price broke/touched UPPER Band, but NO Signal
    if close_val >= upper_val:
        # Check why there's no signal
        rsi_not_overbought = rsi_val is None or rsi_val <= 70
        
        if rsi_not_overbought:
            wait_analysis_parts.append("⚠️ **謹慎：價格測試上軌，但無交易訊號**")
            wait_analysis_parts.append("價格正在測試布林上軌，但 RSI 未達到超買水平（>70），不足以支持賣出認購期權。")
            wait_analysis_parts.append("動量可能推動價格繼續上漲，等待動能耗盡的信號。")
            return "\n\n".join(wait_analysis_parts)
    
    # Scenario 3: Price is in the Middle
    if lower_val < close_val < upper_val:
        wait_analysis_parts.append("⚖️ **中性：價格位於布林通道中間**")
        wait_analysis_parts.append("價格目前浮動在布林通道的中間區域，風險回報比不佳。")
        wait_analysis_parts.append("需要耐心等待價格接近上軌或下軌時再考慮交易機會。")
        return "\n\n".join(wait_analysis_parts)
    
    return ""


def get_analysis_text(df, signal_type=None, strategy_name=None, strike_price=None):
    """
    Professional analyst report: trend/momentum/flow/location with context clues,
    big-player scenario (Capitulation/Distribution/Exhaustion), and trader-style summary.
    Uses ADX slope, gap tiers (Mild/Strong/Choppy), and richer strategy wording.
    """
    if len(df) < 1:
        return "❌ 數據不足，無法進行分析"

    latest = df.iloc[-1]
    current_adx = latest.get('adx', pd.NA)
    adx_slope = latest.get('adx_slope', pd.NA)
    pdi = latest.get('dmi_plus', pd.NA)
    mdi = latest.get('dmi_minus', pd.NA)
    rsi = latest.get('rsi', pd.NA)
    close_price = latest.get('close', pd.NA)
    bb_upper = latest.get('bb_upper', pd.NA)
    bb_lower = latest.get('bb_lower', pd.NA)
    bb_middle = latest.get('bb_middle', pd.NA)
    mfi = latest.get('mfi', pd.NA)
    rvol = latest.get('rvol', pd.NA)
    vwap = latest.get('vwap', pd.NA)
    obv = latest.get('obv', pd.NA)
    obv_slope_5d = latest.get('obv_slope_5d', pd.NA)
    stoch_k = latest.get('stoch_k', pd.NA)
    stoch_d = latest.get('stoch_d', pd.NA)

    # Resolve numeric values for context detection
    rsi_val = float(rsi) if pd.notna(rsi) else None
    mfi_val = float(mfi) if pd.notna(mfi) else None
    rvol_val = float(rvol) if pd.notna(rvol) else None
    adx_val = float(current_adx) if pd.notna(current_adx) else None
    slope_val = float(adx_slope) if pd.notna(adx_slope) else None
    price_val = float(close_price) if pd.notna(close_price) else None
    vwap_val = float(vwap) if pd.notna(vwap) else None

    # Context flags for 大戶情境 & strategy bias
    possible_capitulation = (
        rvol_val is not None and rvol_val > 1.5
        and rsi_val is not None and rsi_val < 30
        and mfi_val is not None and mfi_val < 25
    )
    possible_distribution = (
        rvol_val is not None and rvol_val > 1.5
        and rsi_val is not None and rsi_val > 70
        and mfi_val is not None and mfi_val > 75
    )
    trend_exhaustion = (
        adx_val is not None and adx_val > 35
        and slope_val is not None and slope_val < -0.3
    )

    lines = []

    # --- 📉 趨勢狀態 (Trend State) ---
    # Changes: ADX slope = strengthening/weakening/choppy; Gap tier = Mild/Strong; Choppy when low ADX + small |gap|
    trend_lines = ["**📉 趨勢狀態 (Trend State)**"]
    if pd.notna(pdi) and pd.notna(mdi):
        pdi_val = float(pdi)
        mdi_val = float(mdi)
        gap = round(pdi_val - mdi_val, 2)
        gap_abs = abs(gap)
        if gap > GAP_STRONG:
            dmi_state = "Strong Bullish (強勢多頭)"
        elif gap > PDI_MDI_GAP:
            dmi_state = "Mild Bullish (溫和多頭)"
        elif gap < -GAP_STRONG:
            dmi_state = "Strong Bearish (強勢空頭)"
        elif gap < -PDI_MDI_GAP:
            dmi_state = "Mild Bearish (溫和空頭)"
        else:
            dmi_state = "Neutral / Choppy (中性／震盪)"
        trend_lines.append(f"* **DMI:** MDI {mdi_val:.2f} vs PDI {pdi_val:.2f} (Gap: {gap}). [State: {dmi_state}].")
    else:
        trend_lines.append("* **DMI:** N/A")

    if pd.notna(current_adx):
        adx_f = float(current_adx)
        slope_str = f"{float(adx_slope):+.2f}" if pd.notna(adx_slope) else "N/A"
        if pd.notna(adx_slope):
            sl = float(adx_slope)
            if sl > 0.2:
                adx_interp = "Trend strengthening 趨勢加強"
            elif sl < -0.2:
                adx_interp = "Trend weakening / exhaustion 趨勢減弱／衰竭"
            else:
                adx_interp = "Stable 穩定"
        else:
            adx_interp = "N/A"
        if adx_f >= ADX_THRESHOLD:
            adx_state = f"Trending ({adx_interp})"
        else:
            adx_state = f"Range / Choppy 區間／震盪 (ADX < {ADX_THRESHOLD})"
        trend_lines.append(f"* **ADX:** {adx_f:.2f} (Slope: {slope_str}). [State: {adx_state}].")
    else:
        trend_lines.append("* **ADX:** N/A")

    if pd.notna(close_price) and pd.notna(vwap):
        price_val_f = float(close_price)
        vwap_val_f = float(vwap)
        vwap_side = "Above" if price_val_f > vwap_val_f else "Below"
        trend_lines.append(f"* **VWAP:** Price {price_val_f:.2f} is {vwap_side} VWAP {vwap_val_f:.2f}.")
    else:
        trend_lines.append("* **VWAP:** N/A")

    lines.append("\n".join(trend_lines))

    # --- 💪 動量狀態 (Momentum State) ---
    # Changes: 50-65 = 黃金區; >75 = 熱過頭/可能衰竭; <25 = 深度超賣/可能Capitulation; practical wording
    mom_lines = ["**💪 動量狀態 (Momentum State)**"]
    if pd.notna(rsi):
        rsi_f = float(rsi)
        if rsi_f >= 50 and rsi_f <= 65:
            rsi_zone = "Sweet zone 黃金區 (50-65)"
        elif rsi_f > 75:
            rsi_zone = "Overheated / possible exhaustion 熱過頭／可能衰竭 (watch reversal)"
        elif rsi_f < 25:
            rsi_zone = "Deep oversold / possible Capitulation 深度超賣／可能見底 (avoid chase shorts)"
        elif rsi_f > 70:
            rsi_zone = "Overbought 超買 (caution IV crush on puts)"
        elif rsi_f < 30:
            rsi_zone = "Oversold 超賣 (capitulation risk)"
        else:
            rsi_zone = "Neutral 中性"
        mom_lines.append(f"* **RSI:** {rsi_f:.2f}. [Zone: {rsi_zone}].")
    else:
        mom_lines.append("* **RSI:** N/A")

    if pd.notna(stoch_k) and pd.notna(stoch_d):
        mom_lines.append(f"* **Stochastic:** K={float(stoch_k):.2f}, D={float(stoch_d):.2f}.")
    else:
        mom_lines.append("* **Stochastic:** K=N/A, D=N/A.")
    lines.append("\n".join(mom_lines))

    # --- 💸 資金流向 (Institutional Flow) ---
    # Keep OBV/RVOL/MFI display; add 2-3 context hints (Capitulation, Distribution, ADX exhaustion)
    flow_lines = ["**💸 資金流向 (Institutional Flow)**"]
    if pd.notna(obv):
        obv_val = float(obv)
        obv_rising = pd.notna(obv_slope_5d) and float(obv_slope_5d) > 0
        obv_trend = "Rising" if obv_rising else "Falling"
        if abs(obv_val) >= 1e9:
            obv_str = f"{obv_val/1e9:.2f}B"
        elif abs(obv_val) >= 1e6:
            obv_str = f"{obv_val/1e6:.2f}M"
        elif abs(obv_val) >= 1e3:
            obv_str = f"{obv_val/1e3:.2f}K"
        else:
            obv_str = f"{int(obv_val)}"
        flow_lines.append(f"* **OBV:** {obv_str} (5d slope: {obv_trend}).")
    else:
        flow_lines.append("* **OBV:** N/A")

    if pd.notna(rvol):
        flow_lines.append(f"* **RVOL:** {float(rvol):.2f}x.")
    else:
        flow_lines.append("* **RVOL:** N/A")

    if pd.notna(mfi):
        flow_lines.append(f"* **MFI:** {float(mfi):.2f}.")
    else:
        flow_lines.append("* **MFI:** N/A")

    if possible_capitulation:
        flow_lines.append("* **情境提示:** Possible Capitulation zone 可能地牢見底 (RVOL>1.5 + RSI<30 + MFI<25).")
    if possible_distribution:
        flow_lines.append("* **情境提示:** Possible Distribution / exhaustion 可能閣樓派貨 (RVOL>1.5 + RSI>70 + MFI>75).")
    if trend_exhaustion:
        flow_lines.append("* **情境提示:** Trend exhaustion 趨勢衰竭警號 (ADX>35 but slope<-0.3).")

    lines.append("\n".join(flow_lines))

    # --- 📍 位置 (Location) ---
    loc_lines = ["**📍 位置 (Location)**"]
    if pd.notna(close_price) and pd.notna(bb_upper) and pd.notna(bb_lower) and pd.notna(bb_middle):
        close_val = float(close_price)
        upper_val = float(bb_upper)
        lower_val = float(bb_lower)
        middle_val = float(bb_middle)
        if lower_val < upper_val:
            if close_val > upper_val:
                loc_lines.append(f"* Price is above Upper Band ({upper_val:.2f}).")
            elif close_val < lower_val:
                loc_lines.append(f"* Price is below Lower Band ({lower_val:.2f}).")
            elif middle_val < close_val < upper_val:
                loc_lines.append(f"* Price is between {middle_val:.2f} (MiddleBand) and {upper_val:.2f} (UpperBand).")
            elif lower_val < close_val < middle_val:
                loc_lines.append(f"* Price is between {lower_val:.2f} (LowerBand) and {middle_val:.2f} (MiddleBand).")
            else:
                loc_lines.append(f"* Price is near Middle Band ({middle_val:.2f}).")
        else:
            loc_lines.append("* Band data invalid.")
        if pd.notna(bb_middle) and float(bb_middle) != 0:
            dist_pct = ((close_val - float(bb_middle)) / float(bb_middle)) * 100
            loc_lines.append(f"* Distance from SMA20: {dist_pct:+.2f}%.")
    else:
        loc_lines.append("* N/A (missing data)")
    lines.append("\n".join(loc_lines))

    # --- 🩸 大戶情境判斷 (Context Clues) ---
    context_lines = ["**🩸 大戶情境判斷 (Context Clues)**"]
    context_phrases = []
    if possible_capitulation and price_val is not None and vwap_val is not None and price_val < vwap_val:
        context_phrases.append("* Possible Capitulation zone 可能地牢見底 (low RSI/MFI + high RVOL + below VWAP).")
    elif possible_capitulation:
        context_phrases.append("* Possible Capitulation zone 可能地牢見底 (low RSI/MFI + high RVOL).")
    if possible_distribution:
        context_phrases.append("* Possible Distribution / exhaustion 可能閣樓派貨 (high RSI/MFI + high RVOL).")
    if trend_exhaustion:
        context_phrases.append("* Trend weakening 趨勢衰竭 (high ADX but negative slope).")
    if not context_phrases:
        context_phrases.append("* No strong institutional context signal 暫無明顯大戶情境.")
    context_lines.extend(context_phrases)
    lines.append("\n".join(context_lines))

    # --- ✅ 數學策略建議 (Calculated Strategy) ---
    # Richer AND/OR math reason; Capitulation → Short Put bias; Distribution → Short Call bias
    strategy_lines = ["**✅ 數學策略建議 (Calculated Strategy)**"]
    strategy_lines.append(f"* **建議:** {strategy_name if strategy_name else '(見下方機器人訊號)'}")

    reason_parts = []
    if pd.notna(pdi) and pd.notna(mdi):
        gap = float(pdi) - float(mdi)
        if gap > GAP_STRONG:
            reason_parts.append("Bullish trend (Gap > 7)")
        elif gap > PDI_MDI_GAP:
            reason_parts.append("Mild bullish trend (Gap > 5)")
        elif gap < -GAP_STRONG:
            reason_parts.append("Bearish trend (Gap < -7)")
        elif gap < -PDI_MDI_GAP:
            reason_parts.append("Mild bearish trend (Gap < -5)")
        else:
            reason_parts.append("Neutral / Choppy (|Gap| <= 5)")
    if pd.notna(close_price) and pd.notna(vwap):
        if float(close_price) > float(vwap):
            reason_parts.append("Price > VWAP")
        else:
            reason_parts.append("Price < VWAP")
    if pd.notna(adx_slope) and float(adx_slope) > 0:
        reason_parts.append("ADX slope positive")
    elif pd.notna(adx_slope) and float(adx_slope) < -0.3:
        reason_parts.append("ADX slope negative (caution)")

    if possible_capitulation:
        strategy_lines.append("* **情境偏向:** Short Put bias in potential bottom 潛在見底偏賣 Put.")
    elif possible_distribution:
        strategy_lines.append("* **情境偏向:** Short Call or protective bias 偏 Short Call／防守.")
    math_reason = " AND ".join(reason_parts) if reason_parts else "N/A"
    strategy_lines.append(f"* **數學理由:** {math_reason}.")
    strategy_lines.append(f"* **目標行使價:** {strike_price if strike_price is not None else '(見下方機器人訊號)'} (Based on ATR).")
    lines.append("\n".join(strategy_lines))

    # --- 💡 數據總結 ---
    # Trader-style one-liner
    summary_parts = []
    if pd.notna(pdi) and pd.notna(mdi):
        gap = float(pdi) - float(mdi)
        if gap > GAP_STRONG:
            summary_parts.append("Bullish structure with strong trend")
        elif gap > PDI_MDI_GAP:
            summary_parts.append("Bullish structure with healthy momentum")
        elif gap < -GAP_STRONG:
            summary_parts.append("Bearish structure – defensive stance")
        elif gap < -PDI_MDI_GAP:
            summary_parts.append("Mild bearish – reduce exposure")
        else:
            summary_parts.append("Neutral / choppy – range trading preferred")
    if possible_capitulation:
        summary_parts.append("Possible capitulation bottom forming – watch for reversal")
    elif possible_distribution:
        summary_parts.append("Possible distribution / exhaustion – caution on new longs")
    elif pd.notna(rsi):
        rv = float(rsi)
        if rv >= 50 and rv <= 65 and not summary_parts:
            summary_parts.append("Sweet zone momentum – structure intact")
        elif rv > 75:
            summary_parts.append("Overheated – reversal risk")
        elif rv < 25:
            summary_parts.append("Deep oversold – avoid chase shorts")
    summary = ". ".join(summary_parts) if summary_parts else "Insufficient data."
    lines.append(f"**💡 數據總結:**\n{summary}.")

    return "\n\n".join(lines)


# ============================================================================
# STABILITY FILTER CONSTANTS
# ============================================================================
# These constants prevent whipsaw signals and false positives by requiring
# clear market conditions before generating trade signals.
# Stricter thresholds to reduce false signals and increase signal quality.
# ============================================================================
ADX_THRESHOLD = 30.0  # ADX value above which trend-following strategy is used
PDI_MDI_GAP = 5.0  # Minimum spread required between PDI and MDI for trend signals (prevents whipsaws)
# Report-tier gap: Strong trend when |Gap| >= GAP_STRONG (used in analyst report wording only)
GAP_STRONG = 7.0
BB_BANDWIDTH_MIN = 3.0  # Minimum Bollinger Bandwidth % to avoid squeeze detection (prevents false range signals)
# ============================================================================


def _first_value(series):
    """Get first non-null numeric value from a Series, or None."""
    if series is None or (hasattr(series, 'empty') and series.empty):
        return None
    try:
        for v in series:
            if v is not None and (isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '').replace('-', '').isdigit())):
                return float(v) if isinstance(v, str) else (float(v) if v == v else None)  # NaN check
    except (TypeError, ValueError):
        pass
    return None


def _find_row_value(df, *candidates):
    """From a DataFrame (index = row names), get first non-null column value for first matching row name."""
    if df is None or (hasattr(df, 'empty') and df.empty) or not hasattr(df, 'index'):
        return None
    index_str = [str(i).strip().lower() for i in df.index]
    for name in candidates:
        name_lower = name.strip().lower()
        for i, idx in enumerate(index_str):
            if name_lower in idx or idx in name_lower:
                row = df.iloc[i]
                if hasattr(row, 'dropna'):
                    row = row.dropna()
                val = None
                if hasattr(row, 'iloc') and len(row) > 0:
                    val = row.iloc[0]
                elif hasattr(row, '__iter__') and not isinstance(row, (str, dict)):
                    for v in row:
                        if v is not None and (isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '').replace('-', '').replace('e', '').isdigit())):
                            val = v
                            break
                if val is None:
                    continue
                try:
                    f = float(val)
                    return f if f == f else None  # NaN check
                except (TypeError, ValueError):
                    pass
    return None


def _get_fundamentals_fallback(ticker_obj):
    """
    Fallback when ticker.info lacks fundamental fields (Yahoo 2025 API change).
    Tries to get metrics from financial statements and fast_info.
    Returns dict with only keys that could be resolved (values may be None).
    """
    out = {}
    try:
        # Current price from fast_info or history
        try:
            if hasattr(ticker_obj, 'fast_info') and ticker_obj.fast_info is not None:
                p = getattr(ticker_obj.fast_info, 'last_price', None) or getattr(ticker_obj.fast_info, 'regular_market_price', None)
                if p is not None:
                    out['current_price'] = float(p)
        except Exception:
            pass
        if out.get('current_price') is None:
            try:
                hist = ticker_obj.history(period='5d')
                if hist is not None and not hist.empty and 'Close' in hist.columns:
                    out['current_price'] = float(hist['Close'].iloc[-1])
            except Exception:
                pass
    except Exception:
        pass

    try:
        # Income statement (trailing) for profit margin, EPS
        inc = ticker_obj.get_income_stmt(freq='trailing', as_dict=False)
        if inc is not None and not inc.empty:
            rev = _find_row_value(inc, 'Total Revenue', 'Revenue', 'Net Revenue')
            ni = _find_row_value(inc, 'Net Income', 'Net Income Common Stockholders', 'Net Income Continuous Operations')
            eps = _find_row_value(inc, 'Diluted EPS', 'Basic EPS', 'Earnings Per Share')
            if rev is not None and rev != 0 and ni is not None:
                out['profit_margins'] = ni / rev
            if eps is not None:
                out['eps'] = eps
            # Trailing P/E = price / eps
            if out.get('current_price') and eps is not None and eps != 0:
                out['trailing_pe'] = out['current_price'] / eps
    except Exception:
        pass

    try:
        # Balance sheet: debt, equity, current assets/liabilities, inventory
        bs = ticker_obj.get_balance_sheet(as_dict=False)
        if bs is not None and not bs.empty:
            total_debt = _find_row_value(bs, 'Total Debt', 'Total Liabilities Net Minority Interest')
            if total_debt is None:
                ld = _find_row_value(bs, 'Long Term Debt', 'Long Term Debt And Capital Lease Obligation')
                sd = _find_row_value(bs, 'Short Term Debt', 'Current Debt', 'Short Long Term Debt')
                if ld is not None or sd is not None:
                    total_debt = (ld or 0) + (sd or 0)
            equity = _find_row_value(bs, 'Total Stockholder Equity', 'Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity')
            if total_debt is not None and equity is not None and equity != 0:
                out['debt_to_equity'] = (total_debt / equity) * 100.0  # store as percentage to match Yahoo convention
            ca = _find_row_value(bs, 'Total Current Assets', 'Current Assets')
            cl = _find_row_value(bs, 'Total Current Liabilities', 'Current Liabilities')
            inv = _find_row_value(bs, 'Inventory', 'Total Inventory')
            if ca is not None and cl is not None and cl != 0:
                out['current_ratio'] = ca / cl
            if ca is not None and cl is not None and cl != 0 and inv is not None:
                out['quick_ratio'] = (ca - inv) / cl
            elif ca is not None and cl is not None and cl != 0:
                out['quick_ratio'] = ca / cl  # no inventory row
    except Exception:
        pass

    return out


def _get_stock_name_fallback(stock_code):
    """
    Fallback when ticker.info doesn't return longName/shortName (Yahoo API change).
    Uses Yahoo Finance search API to get company short name.
    """
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(stock_code)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        quotes = data.get("quotes") or []
        if quotes:
            name = quotes[0].get("shortname") or quotes[0].get("longname") or quotes[0].get("symbol")
            if name:
                return name
    except Exception as e:
        print(f"⚠️ Company name fallback (search API) failed: {e}")
    return stock_code


def get_fundamental_status(ticker):
    """
    Fetch and analyze fundamental data from yfinance to filter out distressed companies.
    PRIORITY: Solvency & Distress Detection (Zombie Stock Filter)
    
    This function focuses on identifying financially distressed companies that may be
    "zombie stocks" or facing solvency issues, rather than just valuation metrics.
    
    Args:
        ticker: yfinance Ticker object or ticker symbol string
    
    Returns:
        dict: {
            'status': 'healthy' | 'overvalued' | 'unprofitable' | 'toxic' | 'unknown',
            'trailing_pe': float or None,
            'forward_pe': float or None,
            'peg_ratio': float or None,
            'eps': float or None,
            'debt_to_equity': float or None,
            'profit_margins': float or None,
            'current_price': float or None,
            'quick_ratio': float or None,
            'current_ratio': float or None,
            'warnings': list of warning messages,
            'risk_level': 'low' | 'medium' | 'high' | 'toxic',
            'red_flags': list of specific red flag reasons
        }
    """
    try:
        # If ticker is a string, create Ticker object
        if isinstance(ticker, str):
            ticker_obj = yf.Ticker(ticker)
        else:
            ticker_obj = ticker
        
        # Fetch info - this may take a moment
        # Note: yfinance.info is a property that fetches data on access
        # Sometimes yfinance returns an empty dict or None (e.g. Yahoo 2025 API change)
        info = None
        try:
            info = ticker_obj.info
        except Exception as info_error:
            print(f"⚠️ yfinance error fetching info: {str(info_error)}")
            info = {}
        
        # When info is empty or missing fundamental keys, use fallback from financial statements (Yahoo 2025 fix)
        fallback = {}
        if not info or not any(k in (info or {}) for k in ['trailingPE', 'forwardPE', 'debtToEquity', 'profitMargins', 'trailingEps']):
            print("📊 DEBUG: info missing fundamental data; trying fallback from financial statements & fast_info")
            fallback = _get_fundamentals_fallback(ticker_obj)
            if fallback:
                print(f"📊 DEBUG: Fallback resolved keys: {list(fallback.keys())}")
        
        # Use info if we have it, else treat as empty dict so we rely on fallback
        info = info or {}
        
        # Extract SOLVENCY & DISTRESS metrics (Priority 1) — prefer info, fill from fallback
        debt_to_equity = info.get('debtToEquity') if info.get('debtToEquity') is not None else fallback.get('debt_to_equity')
        profit_margins = info.get('profitMargins') if info.get('profitMargins') is not None else fallback.get('profit_margins')
        current_price = info.get('currentPrice') or info.get('regularMarketPrice') or fallback.get('current_price')
        quick_ratio = info.get('quickRatio') if info.get('quickRatio') is not None else fallback.get('quick_ratio')
        current_ratio = info.get('currentRatio') if info.get('currentRatio') is not None else fallback.get('current_ratio')
        
        # Extract VALUATION metrics (Priority 2)
        trailing_pe = info.get('trailingPE') if info.get('trailingPE') is not None else fallback.get('trailing_pe')
        forward_pe = info.get('forwardPE') if info.get('forwardPE') is not None else fallback.get('forward_pe')
        peg_ratio = info.get('pegRatio') if info.get('pegRatio') is not None else fallback.get('peg_ratio')
        eps = info.get('trailingEps') or info.get('epsTrailingTwelveMonths') or fallback.get('eps')
        
        # DEBUG: Log what values we extracted
        print(f"📊 DEBUG: Extracted values:")
        print(f"   trailing_pe: {trailing_pe}")
        print(f"   forward_pe: {forward_pe}")
        print(f"   debt_to_equity: {debt_to_equity}")
        print(f"   profit_margins: {profit_margins}")
        print(f"   eps: {eps}")
        print(f"   quick_ratio: {quick_ratio}")
        print(f"   current_ratio: {current_ratio}")
        
        warnings = []
        red_flags = []
        risk_level = 'low'
        status = 'healthy'
        
        # ========================================================================
        # RED FLAG LOGIC: STRICT DISTRESS DETECTION (Priority 1)
        # Only flag truly distressed "zombie stocks" - not healthy companies
        # ========================================================================
        
        # Rule A: The Debt Trap - Extreme Debt Levels
        # NOTE: Yahoo Finance returns debtToEquity as a PERCENTAGE (e.g., 27.2 = 27.2%)
        # Healthy range: < 100% (e.g., 27.2% is very healthy)
        # Extreme: > 200% (e.g., 350% is extremely distressed)
        if debt_to_equity is not None:
            debt_ratio = float(debt_to_equity)
            # Threshold: 200 (meaning 200% debt-to-equity)
            # This catches only truly distressed companies (like 2777.HK with 300+)
            # Healthy companies like 9988.HK (27.2%) will pass this check
            if debt_ratio > 200:
                status = 'toxic'
                risk_level = 'toxic'
                red_flags.append('extreme_debt')
                warnings.append(f"☠️ **極度負債：** 負債權益比 {debt_ratio:.1f}% > 200%，公司面臨嚴重財務壓力")
        
        # Rule B: The Bleeding Cash - Significant Losses
        # Only flag if losing 15%+ (stricter threshold to avoid false positives)
        if profit_margins is not None:
            profit_margin_pct = float(profit_margins)
            if profit_margin_pct < -0.15:  # Negative 15% (stricter than -10%)
                status = 'toxic'
                risk_level = 'toxic'
                red_flags.append('significant_losses')
                warnings.append(f"☠️ **嚴重虧損：** 利潤率 {profit_margin_pct*100:.1f}%，公司正在大量失血")
        
        # Rule C: Penny Stock Risk - Loss-making Penny Stock
        # Stricter: Only flag if price < $2.00 AND losing money (not just < $1.00)
        if current_price is not None and profit_margins is not None:
            price = float(current_price)
            profit_margin_pct = float(profit_margins)
            if price < 2.0 and profit_margin_pct < 0:
                status = 'toxic'
                risk_level = 'toxic'
                red_flags.append('penny_stock_loss')
                warnings.append(f"☠️ **虧損低價股：** 股價 ${price:.2f} < $2.00 且公司虧損，極高風險")
        
        # Rule D: Missing Earnings Data - Only flag if truly suspicious (penny stock)
        # Do NOT flag blue chips (like 9988.HK) that might have temporary N/A due to reporting periods
        if trailing_pe is None and current_price is not None:
            price = float(current_price)
            # Only flag if price < $5 (penny stock territory)
            # Blue chips with complex reporting might have temporary N/A - don't penalize them
            if price < 5.0:
                status = 'toxic'
                risk_level = 'toxic'
                red_flags.append('no_earnings_data')
                warnings.append(f"☠️ **無盈利數據：** 股價 ${price:.2f} < $5.00 且無 PE 數據，很可能虧損")
        
        # ========================================================================
        # VALUATION CHECKS (Priority 2 - Only if not already TOXIC)
        # Safe handling: Skip checks if data is None (don't penalize for missing data)
        # ========================================================================
        
        if status != 'toxic':
            # Check for unprofitable company (negative PE)
            # Only check if PE is available (not None)
            if trailing_pe is not None and trailing_pe < 0:
                status = 'unprofitable'
                risk_level = 'high'
                warnings.append("⚠️ 公司虧損：Trailing PE < 0，公司目前不盈利")
            
            # Check for overvaluation (only if PE is available)
            elif trailing_pe is not None and trailing_pe > 50:
                # Check PEG if available (if None, skip PEG check)
                if peg_ratio is not None and peg_ratio > 2:
                    status = 'overvalued'
                    risk_level = 'high'
                    warnings.append(f"⚠️ 估值過高：Trailing PE ({trailing_pe:.2f}) > 50 且 PEG ({peg_ratio:.2f}) > 2")
                else:
                    status = 'overvalued'
                    risk_level = 'medium'
                    warnings.append(f"⚠️ 估值偏高：Trailing PE ({trailing_pe:.2f}) > 50")
            
            # Check for high PEG (only if PEG is available and PE is reasonable or None)
            # If PE is None, we can still check PEG independently
            elif peg_ratio is not None and peg_ratio > 2:
                status = 'overvalued'
                risk_level = 'medium'
                warnings.append(f"⚠️ 成長估值偏高：PEG ({peg_ratio:.2f}) > 2")
            
            # If PE is None but price is reasonable (> $5), don't flag as unprofitable
            # Blue chips like 9988.HK might have temporary N/A due to reporting periods
            # This is handled by Rule D above (only flags if price < $5)
        
        return {
            'status': status,
            'trailing_pe': trailing_pe,
            'forward_pe': forward_pe,
            'peg_ratio': peg_ratio,
            'eps': eps,
            'debt_to_equity': debt_to_equity,
            'profit_margins': profit_margins,
            'current_price': current_price,
            'quick_ratio': quick_ratio,
            'current_ratio': current_ratio,
            'warnings': warnings,
            'risk_level': risk_level,
            'red_flags': red_flags
        }
    
    except Exception as e:
        # If fundamental data is unavailable, return unknown status
        # Log the error for debugging (but don't expose to user in production)
        error_msg = str(e)
        import traceback
        error_details = traceback.format_exc()
        
        # Check if this is the known 2025 yfinance issue (empty dict or missing fields)
        is_known_issue = ("Empty or None info" in error_msg or 
                          "Info dictionary is empty" in error_msg or
                          "Failed to fetch info" in error_msg)
        
        if is_known_issue:
            warning_msg = "無法獲取基本面數據：這是 yfinance 庫的已知問題（2025年）。Yahoo Finance 更改了 API 結構，導致基本面數據無法通過 yfinance 獲取。"
        else:
            warning_msg = f"無法獲取基本面數據：{error_msg}"
        
        print(f"⚠️ get_fundamental_status error: {error_msg}")
        if is_known_issue:
            print("   This appears to be the known 2025 yfinance issue with fundamental data")
        
        return {
            'status': 'unknown',
            'trailing_pe': None,
            'forward_pe': None,
            'peg_ratio': None,
            'eps': None,
            'debt_to_equity': None,
            'profit_margins': None,
            'current_price': None,
            'quick_ratio': None,
            'current_ratio': None,
            'warnings': [warning_msg],
            'risk_level': 'medium',  # Default to medium risk if data unavailable
            'red_flags': [],
            '_error_details': error_details,  # For debugging only
            '_is_known_issue': is_known_issue  # Flag for UI to show appropriate message
        }


def apply_fundamental_filters(signal, fundamental_status, is_bullish=True):
    """
    Apply fundamental filters to downgrade or override trading signals.
    CRITICAL: "TOXIC" status forces WAIT or SHORT ONLY (never buy).
    
    Args:
        signal: dict with signal information (advice, signal_type, commentary, etc.)
        fundamental_status: dict from get_fundamental_status() or None
        is_bullish: bool, True for buy signals (Short Put), False for sell signals (Short Call)
    
    Returns:
        dict: Modified signal with downgraded status if filters trigger
    """
    warnings = []
    should_downgrade = False
    is_toxic = False
    
    # Check fundamental status (Priority 1: TOXIC status)
    if fundamental_status:
        fund_status = fundamental_status.get('status', 'unknown')
        fund_risk = fundamental_status.get('risk_level', 'low')
        fund_warnings = fundamental_status.get('warnings', [])
        fund_red_flags = fundamental_status.get('red_flags', [])
        
        # CRITICAL: TOXIC status - Force WAIT for buy signals, allow SHORT for sell signals
        if fund_status == 'toxic' or fund_risk == 'toxic':
            is_toxic = True
            should_downgrade = True
            warnings.extend(fund_warnings)
            
            # Build toxic warning message
            toxic_reasons = []
            if 'extreme_debt' in fund_red_flags:
                debt_eq = fundamental_status.get('debt_to_equity', 'N/A')
                toxic_reasons.append(f"極度負債 (負債權益比: {debt_eq})")
            if 'significant_losses' in fund_red_flags:
                profit_margin = fundamental_status.get('profit_margins', 'N/A')
                if isinstance(profit_margin, (int, float)):
                    toxic_reasons.append(f"嚴重虧損 (利潤率: {profit_margin*100:.1f}%)")
            if 'penny_stock_loss' in fund_red_flags:
                toxic_reasons.append("虧損仙股")
            if 'no_earnings_data' in fund_red_flags:
                toxic_reasons.append("無盈利數據")
            
            if toxic_reasons:
                warnings.append(f"☠️ **TOXIC / 高風險資產：** {' & '.join(toxic_reasons)}。強烈建議避免買入。")
            else:
                warnings.append("☠️ **TOXIC / 高風險資產：** 公司財務狀況極度危險。強烈建議避免買入。")
        
        # Check for other high-risk fundamental issues (only if not already TOXIC)
        elif fund_status in ['unprofitable', 'overvalued'] and fund_risk == 'high':
            should_downgrade = True
            warnings.extend(fund_warnings)
            warnings.append("🔴 **基本面風險：** 技術面雖好，但基本面存在高風險。建議等待。")
    
    # Apply filters based on signal type
    signal_type = signal.get('signal_type', 'wait')
    
    # For BUY signals (Short Put): Downgrade to WAIT if any filter triggers
    if signal_type == 'buy' and is_bullish and should_downgrade:
        original_advice = signal.get('advice', '')
        original_commentary = signal.get('commentary', '')
        
        # Create new WAIT signal with appropriate warning level
        if is_toxic:
            filter_header = "**☠️ TOXIC 資產過濾器觸發**"
            advice_prefix = "☠️ TOXIC："
        else:
            filter_header = "**⚠️ 基本面過濾器觸發**"
            advice_prefix = "☕ 等待："
        
        new_commentary = original_commentary + f"\n\n---\n{filter_header}\n"
        new_commentary += "\n".join(warnings)
        
        if is_toxic:
            new_commentary += "\n\n**結論：** 技術面雖顯示買入訊號，但這是高風險/TOXIC 資產（可能面臨財務危機、極度負債或嚴重虧損）。**強烈建議避免買入，等待更好的標的。**"
        else:
            new_commentary += "\n\n**結論：** 技術面雖顯示買入訊號，但基本面存在風險。建議暫時觀望，等待更好的進場時機。"
        
        return {
            'advice': f'{advice_prefix}技術面良好，但基本面存在風險（已過濾原訊號：{original_advice}）',
            'signal_type': 'wait',
            'details': signal.get('details', {}),
            'strategy_type': signal.get('strategy_type', 'none'),
            'commentary': new_commentary,
            'original_signal': original_advice,  # Keep track of what was filtered
            'filter_reasons': warnings,
            'is_toxic': is_toxic
        }
    
    # For SELL signals (Short Call): Allow if TOXIC (can short distressed companies)
    # But still warn about the risks
    if signal_type == 'sell' and not is_bullish and is_toxic:
        original_commentary = signal.get('commentary', '')
        new_commentary = original_commentary + "\n\n---\n**⚠️ TOXIC 資產警告**\n"
        new_commentary += "\n".join(warnings)
        new_commentary += "\n\n**注意：** 雖然技術面支持賣出認購期權，但這是 TOXIC 資產。做空高風險資產需格外謹慎，建議降低倉位。"
        
        return {
            'advice': signal.get('advice', ''),
            'signal_type': 'sell',
            'details': signal.get('details', {}),
            'strategy_type': signal.get('strategy_type', 'none'),
            'commentary': new_commentary,
            'is_toxic': True
        }
    
    # No downgrade needed, return original signal
    return signal


def generate_trading_signal(df, fundamental_status=None):
    """
    Generate trading signal with Trend-Following and Mean-Reversion strategies.
    Includes strict stability filters to reduce whipsaws and false signals.
    Now includes fundamental filters to avoid bad companies.
    
    Scenarios:
    A: RANGE MARKET (ADX <= 35) -> Mean Reversion (with Bandwidth filter)
    B: STRONG UPTREND (ADX > 35 & PDI > MDI + 5) -> Trend Following (Short Put)
    C: STRONG DOWNTREND (ADX > 35 & MDI > PDI + 5) -> Trend Following (Short Call)
    D: TRANSITION (ADX 25-35) -> Wait/Caution
    E: CHOPPY TREND (ADX > 35 but PDI/MDI gap < 5) -> Wait
    F: BAND SQUEEZE (Bandwidth < 3%) -> Wait
    
    Args:
        df: DataFrame with calculated indicators
        fundamental_status: dict from get_fundamental_status() or None
    
    Note: ADX threshold raised to 35 to filter out weak trends and reduce false signals.
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
    mfi = latest.get('mfi', pd.NA)
    rvol = latest.get('rvol', pd.NA)
    
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
    has_valid_data = pd.notna(atr) and pd.notna(close_price) and pd.notna(bb_lower) and pd.notna(bb_upper)
    
    # Get SMA values from latest data
    sma_50 = latest.get('sma_50', pd.NA)
    sma_200 = latest.get('sma_200', pd.NA)
    bb_middle = latest.get('bb_middle', pd.NA)
    
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
        'bb_middle': float(bb_middle) if pd.notna(bb_middle) else 0,
        'is_pin_bar': bool(is_pin_bar),
        'mfi': float(mfi) if pd.notna(mfi) else 0,
        'rvol': float(rvol) if pd.notna(rvol) else 0,
        'sma_50': float(sma_50) if pd.notna(sma_50) else None,
        'sma_200': float(sma_200) if pd.notna(sma_200) else None,
        # Comparative RS (20d outperformance vs benchmark) — institutional metric
        'rs_20d_outperform': float(latest.get('RS_20d_Outperform')) if pd.notna(latest.get('RS_20d_Outperform')) else None,
        'macd_line': float(latest.get('macd_line')) if pd.notna(latest.get('macd_line')) else None,
        'macd_signal': float(latest.get('macd_signal')) if pd.notna(latest.get('macd_signal')) else None,
        'macd_hist': float(latest.get('macd_hist')) if pd.notna(latest.get('macd_hist')) else None,
        'macd_hist_prev': float(latest.get('macd_hist_prev')) if pd.notna(latest.get('macd_hist_prev')) else None,
        'suggested_put_strike': None,
        'suggested_call_strike': None
    }
    
    # Get base commentary (will be enhanced with signal-specific details)
    base_commentary = get_analysis_text(df)
    commentary = base_commentary

    # ---- Reversal/Exhaustion overlays ----
    dist_sma200_pct = None
    if pd.notna(sma_200) and float(sma_200) != 0:
        dist_sma200_pct = ((float(close_price) - float(sma_200)) / float(sma_200)) * 100.0
    low_20 = df['close'].tail(20).min() if len(df) >= 20 else pd.NA
    low_volume_test = pd.notna(low_20) and pd.notna(rvol) and float(close_price) <= float(low_20) and float(rvol) < 0.5
    iron_support = (dist_sma200_pct is not None) and (abs(dist_sma200_pct) <= 3.0)
    exhaustion = pd.notna(current_adx) and pd.notna(rsi) and float(current_adx) > 45 and (float(rsi) < 25 or float(rsi) > 75)
    macd_improving = False
    if len(df) >= 3 and pd.notna(latest.get('macd_line')) and pd.notna(latest.get('macd_hist')) and pd.notna(df['macd_hist'].iloc[-2]) and pd.notna(df['macd_hist'].iloc[-3]):
        macd_improving = float(latest.get('macd_line')) < 0 and float(df['macd_hist'].iloc[-1]) > float(df['macd_hist'].iloc[-2]) > float(df['macd_hist'].iloc[-3])

    if exhaustion:
        commentary += "\n\n⚠️ **Exhaustion (趨勢衰竭)：** ADX 過高且 RSI 極端，趨勢延續風險上升。"
        if float(rsi) < 25:
            commentary += "\n🔄 超賣反轉偏向：+1.5 分 reversal bias（物極必反）。"
    if low_volume_test:
        commentary += "\n\n🧪 **Low Volume Test（低量測底 / 縮量空頭陷阱）：** 無量下跌，大戶未動，謹防報復性抽升。"
    if iron_support:
        commentary += "\n\n🛡️ **200天線守護：** 接近 200 天線長線生命線，具強大買盤支撐，不宜殺跌。"
    if macd_improving:
        commentary += "\n\n📈 **Momentum Improving（跌勢放緩）：** MACD 仍在零軸下，但柱體已連續 2 天以上改善。"
        commentary += "\n策略建議：由單純止蝕改為觀察反彈 / Consider Cash Secured Put。"
    
    # ========================================================================
    # OVERRIDE LOGIC: SUPER BREAKOUT (Priority 0 - Checks BEFORE normal logic)
    # ========================================================================
    # If PDI/MDI gap is extremely large (>20) AND volume spike (RVOL > 2.0) 
    # AND price breaks above Upper Band, this is an EXPLOSIVE BREAKOUT.
    # Override normal ADX threshold - this is a high-conviction signal.
    # ========================================================================
    if pd.notna(pdi) and pd.notna(mdi) and pd.notna(rvol) and pd.notna(bb_upper):
        pdi_val = float(pdi)
        mdi_val = float(mdi)
        pdi_mdi_gap = pdi_val - mdi_val
        rvol_val = float(rvol)
        
        # Check for SUPER BREAKOUT conditions
        if pdi_mdi_gap > 20 and rvol_val > 2.0 and close_price > bb_upper:
            # EXPLOSIVE BREAKOUT detected - Override normal ADX threshold
            if has_valid_data:
                suggested_put_strike = close_price - (1.5 * atr)
                details['suggested_put_strike'] = float(suggested_put_strike)
            
            commentary += "\n\n🚀 **策略：爆炸性突破（超級突破）**"
            commentary += f"\n成交量爆升 (RVOL {rvol_val:.1f} > 2.0) 確認了突破上軌的訊號。多頭極度主導 (PDI/MDI 差距 {pdi_mdi_gap:.1f} > 20)。"
            commentary += "\n**理由：** 這是罕見的爆炸性突破模式 - 即使 ADX 較低 ({:.1f})，但極大的多空差距和成交量爆升顯示這是高確信度的突破訊號。".format(float(current_adx))
            commentary += "\n**目標行使價：** 收盤價減 1.5 倍 ATR（積極策略，獲取更好溢價）。"
            
            # Add "The Verdict" summary
            strike_price = details.get('suggested_put_strike', close_price - (1.5 * atr) if has_valid_data else None)
            if strike_price:
                verdict_reason = f"爆炸性突破：成交量爆升 (RVOL {rvol_val:.1f}) 且多頭極度主導 (差距 {pdi_mdi_gap:.1f})。這是高確信度的突破訊號，即使 ADX 較低也值得跟進。"
                commentary += f"\n\n💡 **結論：** 賣出認沽期權 @ ${strike_price:.1f}。**為什麼？** {verdict_reason}"
            
            # Create EXPLOSIVE BREAKOUT signal
            original_signal = {
                'advice': '🚀 訊號：爆炸性突破 - 賣出認沽期權（超級突破策略）',
                'signal_type': 'buy',
                'details': details,
                'strategy_type': 'explosive_breakout',
                'commentary': commentary
            }
            
            # Apply fundamental filters (but this is a high-conviction signal)
            filtered_signal = apply_fundamental_filters(
                original_signal, 
                fundamental_status,
                is_bullish=True
            )
            
            return filtered_signal
    
    # SCENARIO B: STRONG TREND (ADX >= ADX_THRESHOLD) -> Trend Following
    # CORRECTED LOGIC: Simple, clear flow to prevent math errors
    if pd.notna(pdi) and pd.notna(mdi) and current_adx >= ADX_THRESHOLD and not exhaustion:
        pdi_val = float(pdi)
        mdi_val = float(mdi)
        pdi_mdi_gap = pdi_val - mdi_val
        gap_abs = abs(pdi_mdi_gap)
        
        # Case 1: Clear Uptrend (PDI leads by >= PDI_MDI_GAP) -> SIGNAL: SHORT PUT
        if pdi_val > (mdi_val + PDI_MDI_GAP):
            # Suggest SHORT PUT (Bullish) - Trading with the trend
            # AGGRESSIVE: Use 1.5x ATR (ignore Lower Band as it's too far away)
            if has_valid_data:
                suggested_put_strike = close_price - (1.5 * atr)
                details['suggested_put_strike'] = float(suggested_put_strike)
            
            commentary += "\n\n✅ **策略：順勢交易（趨勢跟隨）**"
            if gap_abs > 15:
                commentary += "\n趨勢非常強勁且向上，多頭主導市場。適合賣出認沽期權。"
                commentary += "\n**理由：** 這是主導性多頭行情（差距 > 15），趨勢明確且高確信度，支撐位持續上升，賣出認沽期權相對安全。"
            else:
                commentary += f"\n強勢上升趨勢（ADX {current_adx:.2f}）。多頭領先 {gap_abs:.2f} 點。適合賣出認沽期權。"
                commentary += "\n**理由：** 趨勢明確向上，支撐位持續上升，賣出認沽期權相對安全。"
            commentary += "\n**目標行使價：** 收盤價減 1.5 倍 ATR（積極策略，獲取更好溢價）。"
            
            # Add "The Verdict" summary
            strike_price = details.get('suggested_put_strike', close_price - (1.5 * atr) if has_valid_data else None)
            if strike_price:
                rsi_val = float(rsi) if pd.notna(rsi) else None
                if rsi_val and 50 <= rsi_val <= 65:
                    verdict_reason = f"趨勢主導（差距 {gap_abs:.1f}）且 RSI 仍有充足上漲空間（{rsi_val:.1f}）。不要害怕緩慢上漲。"
                elif gap_abs > 15:
                    verdict_reason = f"這是主導性多頭行情（差距 {gap_abs:.1f}），趨勢非常明確且高確信度。"
                else:
                    verdict_reason = f"強勢上升趨勢（ADX {current_adx:.1f}）。多頭領先 {gap_abs:.1f} 點。"
                commentary += f"\n\n💡 **結論：** 賣出認沽期權 @ ${strike_price:.1f}。**為什麼？** {verdict_reason}"
            
            # FUNDAMENTAL & NEWS FILTER: Check if we should downgrade this buy signal
            original_signal = {
                'advice': '🟢 訊號：賣出認沽期權（趨勢跟隨策略）',
                'signal_type': 'buy',
                'details': details,
                'strategy_type': 'trend_following',
                'commentary': commentary
            }
            
            # Apply fundamental filters
            filtered_signal = apply_fundamental_filters(
                original_signal,
                fundamental_status,
                is_bullish=True
            )
            
            return filtered_signal
        # Case 2: Clear Downtrend (MDI leads by >= PDI_MDI_GAP) -> SIGNAL: SHORT CALL
        elif mdi_val > (pdi_val + PDI_MDI_GAP):
            if low_volume_test or iron_support or macd_improving:
                return {
                    'advice': '⚖️ 觀察：Potential Reversal / Watch-Neutral',
                    'signal_type': 'wait',
                    'details': details,
                    'strategy_type': 'watch_neutral',
                    'commentary': commentary
                }
            # SCENARIO C: STRONG DOWNTREND (ADX > ADX_THRESHOLD & MDI > PDI + PDI_MDI_GAP) -> Trend Following
            # Suggest SHORT CALL (Bearish) - Trading with the trend
            # AGGRESSIVE: Use 1.5x ATR (ignore Upper Band as it's too far away)
            if has_valid_data:
                suggested_call_strike = close_price + (1.5 * atr)
                details['suggested_call_strike'] = float(suggested_call_strike)
            
            commentary += "\n\n✅ **策略：順勢交易（趨勢跟隨）**"
            if gap_abs > 15:
                commentary += "\n趨勢非常強勁且向下，空頭主導市場。適合賣出認購期權。"
                commentary += "\n**理由：** 這是主導性空頭行情（差距 > 15），趨勢明確且高確信度，阻力位持續下降，賣出認購期權相對安全。"
            else:
                commentary += f"\n強勢下降趨勢（ADX {current_adx:.2f}）。空頭領先 {gap_abs:.2f} 點。適合賣出認購期權。"
                commentary += "\n**理由：** 趨勢明確向下，阻力位持續下降，賣出認購期權相對安全。"
            commentary += "\n**目標行使價：** 收盤價加 1.5 倍 ATR（積極策略，獲取更好溢價）。"
            
            # Add "The Verdict" summary
            strike_price = details.get('suggested_call_strike', close_price + (1.5 * atr) if has_valid_data else None)
            if strike_price:
                if gap_abs > 15:
                    verdict_reason = f"這是主導性空頭行情（差距 {gap_abs:.1f}），趨勢非常明確且高確信度。"
                else:
                    verdict_reason = f"強勢下降趨勢（ADX {current_adx:.1f}）。空頭領先 {gap_abs:.1f} 點。"
                commentary += f"\n\n💡 **結論：** 賣出認購期權 @ ${strike_price:.1f}。**為什麼？** {verdict_reason}"
            
            return {
                'advice': '🔴 訊號：賣出認購期權（趨勢跟隨策略）',
                'signal_type': 'sell',
                'details': details,
                'strategy_type': 'trend_following',
                'commentary': commentary
            }
        # Case 3: Gap is too small (< PDI_MDI_GAP) -> WAIT
        else:
            # SCENARIO E: CHOPPY TREND - Gap is less than PDI_MDI_GAP
            # Market is undecided despite high ADX
            # Get detailed WAIT analysis
            detailed_wait = get_detailed_wait_analysis(df, 'wait')
            
            commentary += "\n\n🌪️ **策略：等待（趨勢混亂）**"
            commentary += f"\n雖然 ADX 顯示強勢趨勢（{current_adx:.2f}），但多空雙方力量接近（PDI: {pdi_val:.2f}, MDI: {mdi_val:.2f}，差距僅 {gap_abs:.2f} < {PDI_MDI_GAP}）。"
            commentary += "\n**理由：** 市場方向不明確，多空雙方正在激烈爭奪，此時交易風險較高。這是市場噪音，而非明確趨勢。"
            
            # Add detailed WAIT analysis if available
            if detailed_wait:
                commentary += "\n\n---"
                commentary += "\n**詳細等待分析：**"
                commentary += "\n" + detailed_wait
            
            return {
                'advice': f'☕ 等待：趨勢混亂（ADX={current_adx:.1f}，但PDI/MDI差距僅{gap_abs:.1f} < {PDI_MDI_GAP}）',
                'signal_type': 'wait',
                'details': details,
                'strategy_type': 'transition',
                'commentary': commentary
            }
    
    # SCENARIO A: RANGE MARKET (ADX < 20) -> Mean Reversion
    # STABILITY FIX: Check Bandwidth before generating signals to avoid squeeze
    elif current_adx < 20:
        # ADX < 20: Clear Range Market - proceed with Mean Reversion logic
        # Calculate Bollinger Bandwidth to detect squeeze
        bb_middle = latest.get('bb_middle', pd.NA)
        if pd.notna(bb_upper) and pd.notna(bb_lower) and pd.notna(bb_middle) and pd.notna(close_price):
            bandwidth_pct = ((float(bb_upper) - float(bb_lower)) / float(bb_middle)) * 100
            
            # SCENARIO F: BAND SQUEEZE - If bandwidth is too narrow, return WAIT
            if bandwidth_pct < BB_BANDWIDTH_MIN:
                # Get detailed WAIT analysis
                detailed_wait = get_detailed_wait_analysis(df, 'wait')
                
                commentary += "\n\n🤏 **策略：等待（波動率收窄）**"
                commentary += f"\n布林通道過於緊窄（寬度 {bandwidth_pct:.2f}% < {BB_BANDWIDTH_MIN}%），波動率過低。"
                commentary += "\n**理由：** 這通常預示著即將出現大幅波動（突破或崩跌）。在通道收窄時進行均值回歸交易風險極高，建議等待方向明確後再進場。"
                
                # Add detailed WAIT analysis if available
                if detailed_wait:
                    commentary += "\n\n---"
                    commentary += "\n**詳細等待分析：**"
                    commentary += "\n" + detailed_wait
                
                return {
                    'advice': f'☕ 等待：波動率收窄（通道寬度{bandwidth_pct:.1f}% < {BB_BANDWIDTH_MIN}%），預期大幅波動',
                    'signal_type': 'wait',
                    'details': details,
                    'strategy_type': 'none',
                    'commentary': commentary
                }
        
        # Bandwidth is OK (>= BB_BANDWIDTH_MIN%), proceed with Mean Reversion logic
        # Extract volume indicators for mean reversion signals
        mfi_val = float(mfi) if pd.notna(mfi) else None
        rvol_val = float(rvol) if pd.notna(rvol) else None
        
        # Logic B: SHORT PUT SIGNAL (Mean Reversion) - WITH VOLUME FILTER
        # Check for volume confirmation
        
        # Check for MFI divergence (Current MFI > Previous MFI while Price is lower)
        mfi_divergence = False
        if len(df) >= 2 and pd.notna(mfi):
            prev_mfi = df.iloc[-2].get('mfi', pd.NA)
            prev_close = df.iloc[-2].get('close', pd.NA)
            if pd.notna(prev_mfi) and pd.notna(prev_close):
                if float(mfi) > float(prev_mfi) and float(close_price) < float(prev_close):
                    mfi_divergence = True
        
        # Volume filter conditions for SHORT PUT
        volume_confirmed = False
        volume_reason = []
        
        if mfi_val is not None and mfi_val < 20:
            volume_confirmed = True
            volume_reason.append(f"MFI 超賣 ({mfi_val:.2f} < 20)")
        
        if mfi_divergence:
            volume_confirmed = True
            volume_reason.append("MFI 背離（資金流入但價格下跌）")
        
        if rvol_val is not None and rvol_val > 2.0 and rsi < 30:
            volume_confirmed = True
            volume_reason.append(f"恐慌性拋售 (RVOL {rvol_val:.2f} > 2.0)")
        
        # Original condition: Price <= Lower BB AND (RSI < 30 OR Pin Bar)
        base_condition = close_price <= bb_lower and (rsi < 30 or is_pin_bar)
        
        # NEW: Require volume confirmation OR keep original condition if volume data unavailable
        if base_condition and (volume_confirmed or (mfi_val is None and rvol_val is None)):
            reason_parts = []
            if close_price <= bb_lower:
                reason_parts.append("超賣")
            if rsi < 30:
                reason_parts.append("RSI < 30")
            if is_pin_bar:
                reason_parts.append("看漲針形")
            if volume_reason:
                reason_parts.extend(volume_reason)
            reason = " + ".join(reason_parts)
            
            if has_valid_data:
                put_strike_1 = close_price - (2 * atr)
                put_strike_2 = bb_lower
                suggested_put_strike = min(put_strike_1, put_strike_2)
                details['suggested_put_strike'] = float(suggested_put_strike)
            
            commentary += "\n\n✅ **策略：均值回歸（成交量確認）**"
            commentary += "\n市場處於橫盤整理，價格接近下軌，適合賣出認沽期權。"
            if volume_reason:
                commentary += f"\n**成交量確認：** {', '.join(volume_reason)}，顯示資金流向支持反彈。"
            commentary += f"\n**理由：** {reason}，預期價格回歸均值。"
            commentary += "\n**目標行使價：** 使用布林下軌或收盤價減 2 倍 ATR。"
            
            # Add "The Verdict" summary
            strike_price = details.get('suggested_put_strike', None)
            if strike_price:
                rsi_val = float(rsi) if pd.notna(rsi) else None
                if is_pin_bar:
                    verdict_reason = "價格在區間底部且出現看漲反轉信號（Pin Bar），預期反彈。"
                elif rsi_val and rsi_val < 30:
                    verdict_reason = f"價格在區間底部且 RSI 超賣（{rsi_val:.1f}），預期反彈回歸均值。"
                else:
                    verdict_reason = "價格在區間底部，預期反彈回歸均值。"
                commentary += f"\n\n💡 **結論：** 賣出認沽期權 @ ${strike_price:.1f}。**為什麼？** {verdict_reason}"
            
            # FUNDAMENTAL & NEWS FILTER: Check if we should downgrade this buy signal
            original_signal = {
                'advice': f'🟢 訊號：賣出認沽期權（均值回歸策略，原因：{reason}）',
                'signal_type': 'buy',
                'details': details,
                'strategy_type': 'mean_reversion',
                'commentary': commentary
            }
            
            # Apply fundamental filters
            filtered_signal = apply_fundamental_filters(
                original_signal,
                fundamental_status,
                is_bullish=True
            )
            
            return filtered_signal
        
        # Logic C: SHORT CALL SIGNAL (Mean Reversion) - WITH VOLUME FILTER
        # Volume filter conditions for SHORT CALL (mfi_val and rvol_val already extracted above)
        volume_confirmed = False
        volume_reason = []
        fake_breakout = False
        
        if mfi_val is not None and mfi_val > 80:
            volume_confirmed = True
            volume_reason.append(f"MFI 超買 ({mfi_val:.2f} > 80)")
        
        if rvol_val is not None and rvol_val < 1.0 and close_price >= bb_upper:
            volume_confirmed = True
            fake_breakout = True
            volume_reason.append(f"假突破 (RVOL {rvol_val:.2f} < 1.0，價格上漲但成交量萎縮)")
        
        # Original condition: Price >= Upper BB OR RSI > 70
        base_condition = close_price >= bb_upper or rsi > 70
        
        # NEW: Require volume confirmation OR keep original condition if volume data unavailable
        if base_condition and (volume_confirmed or fake_breakout or (mfi_val is None and rvol_val is None)):
            reason_parts = []
            if close_price >= bb_upper:
                reason_parts.append("超買")
            if rsi > 70:
                reason_parts.append("RSI > 70")
            if volume_reason:
                reason_parts.extend(volume_reason)
            reason = " + ".join(reason_parts)
            
            if has_valid_data:
                call_strike_1 = close_price + (2 * atr)
                call_strike_2 = bb_upper
                suggested_call_strike = max(call_strike_1, call_strike_2)
                details['suggested_call_strike'] = float(suggested_call_strike)
            
            commentary += "\n\n✅ **策略：均值回歸（成交量確認）**"
            commentary += "\n市場處於橫盤整理，價格接近上軌，適合賣出認購期權。"
            if volume_reason:
                if fake_breakout:
                    commentary += f"\n**成交量確認：** {', '.join(volume_reason)}，這是假突破信號，預期回調。"
                else:
                    commentary += f"\n**成交量確認：** {', '.join(volume_reason)}，顯示資金流向支持回調。"
            commentary += f"\n**理由：** {reason}，預期價格回歸均值。"
            commentary += "\n**目標行使價：** 使用布林上軌或收盤價加 2 倍 ATR。"
            
            # Add "The Verdict" summary
            strike_price = details.get('suggested_call_strike', None)
            if strike_price:
                rsi_val = float(rsi) if pd.notna(rsi) else None
                if rsi_val and rsi_val > 70:
                    verdict_reason = f"價格在區間頂部且 RSI 超買（{rsi_val:.1f}），預期回調回歸均值。"
                else:
                    verdict_reason = "價格在區間頂部，預期回調回歸均值。"
                commentary += f"\n\n💡 **結論：** 賣出認購期權 @ ${strike_price:.1f}。**為什麼？** {verdict_reason}"
            
            return {
                'advice': f'🔴 訊號：賣出認購期權（均值回歸策略，原因：{reason}）',
                'signal_type': 'sell',
                'details': details,
                'strategy_type': 'mean_reversion',
                'commentary': commentary
            }
    
    # SCENARIO D: TRANSITION (ADX between 20-30) -> Wait/Caution
    # This handles the case where ADX is not high enough for trend following, but not low enough for range trading
    elif 20 <= current_adx < ADX_THRESHOLD:
        detailed_wait = get_detailed_wait_analysis(df, 'wait')
        
        commentary += "\n\n⚠️ **策略：等待 / 謹慎觀察**"
        commentary += f"\n市場處於趨勢轉換期，ADX 在 20-{ADX_THRESHOLD} 之間（當前 {current_adx:.2f}），建議等待更明確的信號。"
        commentary += f"\n**理由：** 趨勢強度不足（ADX < {ADX_THRESHOLD}），不足以支持趨勢跟隨策略，但也不夠弱到明確的橫盤整理。此時交易風險較高。"
        
        # Add detailed WAIT analysis if available
        if detailed_wait:
            commentary += "\n\n---"
            commentary += "\n**詳細等待分析：**"
            commentary += "\n" + detailed_wait
        
        return {
            'advice': f'☕ 等待：趨勢轉換期（ADX {current_adx:.1f} 在 20-{ADX_THRESHOLD} 之間），建議謹慎觀察',
            'signal_type': 'wait',
            'details': details,
            'strategy_type': 'transition',
            'commentary': commentary
        }
    
    # Default: NO ACTION - This is where detailed WAIT analysis is most important
    # Get detailed WAIT analysis for the "no signal" case
    detailed_wait = get_detailed_wait_analysis(df, 'wait')
    
    commentary += "\n\n☕ **策略：等待**"
    commentary += "\n目前無明確的交易訊號，建議繼續觀察市場變化。"
    
    # Add detailed WAIT analysis explaining WHY there's no signal
    if detailed_wait:
        commentary += "\n\n---"
        commentary += "\n**詳細等待分析：**"
        commentary += "\n" + detailed_wait
    
    # Final report summary requested by user
    if pd.notna(current_adx) and pd.notna(rsi) and dist_sma200_pct is not None:
        if float(current_adx) > 45 and float(rsi) < 30 and abs(dist_sma200_pct) < 5:
            commentary += "\n\n📋 **Report Status:** Oversold - Potential Reversal"
            commentary += "\n✅ **Recommended Action:** Wait for Rebound / Recommend Cash Secured Put"

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


@st.cache_data(ttl=300)
def get_data(ticker_symbol):
    """
    Fetch daily OHLCV data from Yahoo Finance.
    Uses explicit end date = today + 1 day so the latest trading day is included
    (yfinance treats 'end' as exclusive, so end=tomorrow includes today's data).
    """
    try:
        end_date = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.now().date() - timedelta(days=730)).strftime("%Y-%m-%d")  # 2 years
        df = yf.download(ticker_symbol, start=start_date, end=end_date, interval="1d", auto_adjust=True, progress=False)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def analyze_stock(stock_code, original_input=None, backtest_date=None, debug_mode=False):
    """
    Analyze a stock and return trading signal using Yahoo Finance.
    
    Args:
        stock_code: Stock ticker symbol
        original_input: Original user input (for display)
        backtest_date: datetime.date object for backtesting. If None, uses latest data.
        debug_mode: If True, include debug_last5 and debug_index_dtype in result.
    
    Returns:
        dict with analysis results
    """
    if original_input is None:
        original_input = stock_code
    
    debug_last5 = None
    debug_index_dtype = None
    history_log_10d = ""
    try:
        # Fetch data via get_data (period="2y", no start/end, no row dropping)
        data = get_data(stock_code)
        if data is None:
            return {
                'success': False,
                'error': f'No data returned for {stock_code}'
            }
        data.index = pd.to_datetime(data.index)
        debug_index_dtype = str(data.index.dtype) if debug_mode else None
        
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
        if 'Date' in df.columns:
            df['time'] = df['Date']
        elif len(df.columns) > 0 and df.columns[0] == 'Date':
            # Sometimes the reset_index creates a column with the index name
            date_col = df.columns[0] if len(df.columns) > 0 else None
            if date_col:
                df['time'] = df[date_col]
        else:
            # Create a time column from the index if it was datetime
            df['time'] = df.index if hasattr(df.index, '__iter__') else range(len(df))
        
        # Sort by time to ensure chronological order
        df = df.sort_values('time').reset_index(drop=True)
        debug_last5 = df.tail(5).copy() if debug_mode else None
        
        # ========================================================================
        # TIME MACHINE / BACKTEST LOGIC
        # ========================================================================
        backtest_index = None
        actual_future_performance = None
        selected_date_str = None
        
        if backtest_date is not None:
            # Convert backtest_date to datetime for comparison
            backtest_datetime = pd.Timestamp(backtest_date)
            
            # Find the row index for the selected date (or nearest previous trading day)
            # Filter to dates <= backtest_date
            valid_dates = df[df['time'] <= backtest_datetime]
            
            if len(valid_dates) == 0:
                return {
                    'success': False,
                    'error': f'No data available before {backtest_date}. Please select a later date.'
                }
            
            # Get the last valid date (nearest previous trading day)
            backtest_index = valid_dates.index[-1]
            selected_date = valid_dates.iloc[-1]['time']
            selected_date_str = selected_date.strftime('%Y-%m-%d') if hasattr(selected_date, 'strftime') else str(selected_date)
            
            # Save original dataframe for future performance calculation (before slicing)
            original_df_for_future = df.copy()
            
            # Slice dataframe to only include data up to and including the backtest date
            df = df.iloc[:backtest_index + 1].copy()
            
            # Calculate "Future Outcome" - 5 trading days ahead using original dataframe
            future_index = backtest_index + 5
            if future_index < len(original_df_for_future):
                # We have enough data to calculate future performance
                backtest_close = float(original_df_for_future.iloc[backtest_index]['close'])
                future_close = float(original_df_for_future.iloc[future_index]['close'])
                actual_future_performance = ((future_close - backtest_close) / backtest_close) * 100
            else:
                # Not enough future data available
                actual_future_performance = None
            
            print(f"📅 BACKTEST MODE: Analyzing as of {selected_date_str}")
            print(f"   Data points available: {len(df)}")
            print(f"   Backtest index: {backtest_index}")
            if actual_future_performance is not None:
                print(f"   5-Day Future Performance: {actual_future_performance:.2f}%")
        
        # ========================================================================
        
        # Get stock basic info (name) from yfinance; fallback to Yahoo search API when info is empty (2025 API change)
        # NOTE: In backtest mode, we don't fetch current price from yfinance (it's always today's price)
        stock_name = stock_code  # Default to stock code if name not available
        if backtest_date is None:  # Only fetch from yfinance in live mode
            try:
                ticker = yf.Ticker(stock_code)
                info = ticker.info or {}
                if info.get('longName'):
                    stock_name = info['longName']
                elif info.get('shortName'):
                    stock_name = info['shortName']
                elif info.get('symbol'):
                    stock_name = info['symbol']
                else:
                    # info empty or missing name fields (Yahoo 2025 API) — use search API fallback
                    stock_name = _get_stock_name_fallback(stock_code)
            except Exception as e:
                print(f"Warning: Could not fetch stock info: {e}")
                stock_name = _get_stock_name_fallback(stock_code)
        
        # Calculate indicators (this must happen after slicing in backtest mode)
        df = calculate_indicators(df)
        
        # Comparative Relative Strength vs benchmark (^HSI for HK, ^GSPC for others)
        benchmark_ticker = "^HSI" if ".HK" in stock_code.upper() else "^GSPC"
        try:
            start_date = df['time'].min()
            end_date = df['time'].max()
            bench = yf.download(benchmark_ticker, start=start_date, end=end_date, auto_adjust=True, progress=False)
            if not bench.empty:
                if isinstance(bench.columns, pd.MultiIndex):
                    bench.columns = [col[0] if isinstance(col, tuple) else col for col in bench.columns]
                bench_close = bench['Close'] if 'Close' in bench.columns else bench.iloc[:, 0]
                bench_close.index = pd.to_datetime(bench_close.index).normalize()
                df_dates = pd.DatetimeIndex(pd.to_datetime(df['time'])).normalize()
                aligned_bench = bench_close.reindex(df_dates, method='ffill')
                df['Benchmark_Close'] = aligned_bench.values
                df['RS_Line'] = df['close'] / df['Benchmark_Close'].replace(0, pd.NA)
                df['RS_20d_Outperform'] = (df['RS_Line'] / df['RS_Line'].shift(20) - 1) * 100
        except Exception as rs_err:
            print(f"Warning: Could not compute RS vs benchmark: {rs_err}")
        
        # Get price from the dataframe (this will be the backtest date price if in backtest mode)
        # In backtest mode, df has been sliced to end at the backtest date
        # In live mode, df.iloc[-1] is the latest available data
        current_price = float(df.iloc[-1]['close'])
        
        # If in backtest mode, also update the selected date string for display
        if backtest_date is not None and selected_date_str:
            print(f"📅 BACKTEST: Using price from {selected_date_str}: ${current_price:.2f}")
        
        # Calculate price change from yesterday's close
        price_change = None
        price_change_percent = None
        if len(df) >= 2:
            yesterday_close = float(df.iloc[-2]['close'])
            price_change = current_price - yesterday_close
            if yesterday_close > 0:
                price_change_percent = (price_change / yesterday_close) * 100
        
        # Prepare price history for Candlestick chart with Bollinger Bands (last 50 days)
        price_history = df.tail(50).copy()
        
        # Format dates for chart (extract date part if datetime)
        dates = []
        if 'time' in price_history.columns:
            for dt in price_history['time']:
                if pd.notna(dt):
                    # Keep as datetime for Plotly
                    dates.append(dt)
                else:
                    dates.append(None)
        else:
            dates = price_history.index.tolist()
        
        chart_data = {
            'dates': dates,
            'open': [float(x) for x in price_history['open'].tolist() if pd.notna(x)],
            'high': [float(x) for x in price_history['high'].tolist() if pd.notna(x)],
            'low': [float(x) for x in price_history['low'].tolist() if pd.notna(x)],
            'close': [float(x) for x in price_history['close'].tolist() if pd.notna(x)],
            'volume': [float(x) for x in price_history['volume'].tolist() if pd.notna(x)],
            'bb_upper': [float(x) for x in price_history['bb_upper'].tolist() if pd.notna(x)],
            'bb_middle': [float(x) for x in price_history['bb_middle'].tolist() if pd.notna(x)],
            'bb_lower': [float(x) for x in price_history['bb_lower'].tolist() if pd.notna(x)]
        }
        
        # RSI series for mini chart (last 30 days)
        rsi_history = df[['time', 'rsi']].tail(30).copy()

        # Fetch fundamental data for filtering and additional data for copy report
        # Always try to get fundamental data, even if it fails
        fundamental_status = None
        extended_fundamental_data = {}  # Store additional data for copy report
        try:
            print(f"📊 DEBUG: Fetching fundamental data for ticker: {stock_code}")
            ticker_obj = yf.Ticker(stock_code)
            print(f"📊 DEBUG: Ticker object created, fetching info...")
            fundamental_status = get_fundamental_status(ticker_obj)
            print(f"📊 DEBUG: Fundamental status retrieved: {fundamental_status.get('status', 'unknown')}")
            
            # Fetch additional data for copy report
            try:
                info = ticker_obj.info
                
                # Market Cap
                market_cap = info.get('marketCap', info.get('enterpriseValue', None))
                extended_fundamental_data['market_cap'] = market_cap
                
                # 52-week high/low
                week_52_high = info.get('fiftyTwoWeekHigh', info.get('52WeekHigh', None))
                week_52_low = info.get('fiftyTwoWeekLow', info.get('52WeekLow', None))
                extended_fundamental_data['week_52_high'] = week_52_high
                extended_fundamental_data['week_52_low'] = week_52_low
                
                # Earnings date
                try:
                    # Try calendar first
                    calendar = ticker_obj.calendar
                    if calendar is not None and not calendar.empty:
                        # calendar is a DataFrame, get the first row's earnings date
                        if 'Earnings Date' in calendar.columns:
                            earnings_date = calendar['Earnings Date'].iloc[0]
                            if pd.notna(earnings_date):
                                if isinstance(earnings_date, pd.Timestamp):
                                    extended_fundamental_data['next_earnings'] = earnings_date.strftime('%Y-%m-%d')
                                else:
                                    extended_fundamental_data['next_earnings'] = str(earnings_date)
                            else:
                                extended_fundamental_data['next_earnings'] = None
                        else:
                            # Try to get from index if it's a datetime index
                            if isinstance(calendar.index, pd.DatetimeIndex) and len(calendar) > 0:
                                next_earnings_date = calendar.index[0]
                                extended_fundamental_data['next_earnings'] = next_earnings_date.strftime('%Y-%m-%d')
                            else:
                                extended_fundamental_data['next_earnings'] = None
                    else:
                        # Try alternative method - earnings_dates
                        try:
                            earnings_dates = ticker_obj.earnings_dates
                            if earnings_dates is not None and not earnings_dates.empty:
                                # Get the first future earnings date
                                now = pd.Timestamp.now()
                                future_dates = earnings_dates[earnings_dates.index > now]
                                if not future_dates.empty:
                                    next_earnings_date = future_dates.index[0]
                                    extended_fundamental_data['next_earnings'] = next_earnings_date.strftime('%Y-%m-%d')
                                else:
                                    extended_fundamental_data['next_earnings'] = None
                            else:
                                extended_fundamental_data['next_earnings'] = None
                        except:
                            extended_fundamental_data['next_earnings'] = None
                except Exception as earnings_error:
                    print(f"⚠️ Could not fetch earnings date: {earnings_error}")
                    extended_fundamental_data['next_earnings'] = None
                    
            except Exception as ext_error:
                print(f"⚠️ Could not fetch extended fundamental data: {ext_error}")
                
        except Exception as fund_error:
            # If fundamental data fetch fails, create a fallback status
            import traceback
            error_details = traceback.format_exc()
            fundamental_status = {
                'status': 'unknown',
                'trailing_pe': None,
                'forward_pe': None,
                'peg_ratio': None,
                'eps': None,
                'debt_to_equity': None,
                'profit_margins': None,
                'current_price': None,
                'quick_ratio': None,
                'current_ratio': None,
                'warnings': [f"無法獲取基本面數據：{str(fund_error)}"],
                'risk_level': 'medium',
                'red_flags': [],
                '_error_details': error_details
            }
            # Log the error but don't fail the entire analysis
            print(f"Warning: Failed to fetch fundamental data: {fund_error}")
        
        # Generate signal (with fundamental filters applied)
        signal = generate_trading_signal(df, fundamental_status)
        
        # Generate detailed market analysis
        market_analysis = generate_analysis(df)
        
        # Use commentary from signal if available, otherwise use market_analysis
        analyst_commentary = signal.get('commentary', market_analysis) if signal else market_analysis
        
        # Build 10-Day History Log for AI trend analysis (PDI, MDI, ADX, Slope, RSI, MFI, RVOL)
        # df already has dmi_plus (PDI), dmi_minus (MDI), adx, adx_slope (daily change) for all rows
        history_log_10d = ""
        if len(df) >= 1:
            last_10 = df.tail(10)
            hk_tz = pytz.timezone('Asia/Hong_Kong')
            current_time_hkt = datetime.now(hk_tz).strftime('%Y-%m-%d %H:%M:%S')
            lines = [
                f"=== 10-DAY TREND LOG: {stock_code} ===",
                f"Report Time: {current_time_hkt} (HKT)",
                "",
                "| Date       | Close  | VWAP   | OBV     | SMA20  | PDI   | MDI   | ADX (Slope) | RSI  | MFI | RVOL  | MHist  | MHprev | Signal / Warning       |",
                "|------------|--------|--------|---------|--------|-------|-------|-------------|------|-----|-------|--------|--------|------------------------|",
            ]
            for _, row in last_10.iterrows():
                t = row.get('time')
                date_str = t.strftime('%Y-%m-%d') if hasattr(t, 'strftime') else str(t)[:10]
                close = row.get('close')
                close_str = f"{float(close):.2f}" if pd.notna(close) else "N/A"
                vwap = row.get('vwap')
                vwap_str = f"{float(vwap):.2f}" if pd.notna(vwap) else "N/A"
                obv = row.get('obv')
                if pd.notna(obv):
                    o = float(obv)
                    if abs(o) >= 1e9:
                        obv_str = f"{o/1e9:.2f}B"
                    elif abs(o) >= 1e6:
                        obv_str = f"{o/1e6:.2f}M"
                    elif abs(o) >= 1e3:
                        obv_str = f"{o/1e3:.2f}K"
                    else:
                        obv_str = f"{int(o)}"
                else:
                    obv_str = "N/A"
                sma20 = row.get('bb_middle')
                sma20_str = f"{float(sma20):.2f}" if pd.notna(sma20) else "N/A"
                pdi = row.get('dmi_plus')
                pdi_str = f"{float(pdi):.1f}" if pd.notna(pdi) else "N/A"
                mdi = row.get('dmi_minus')
                mdi_str = f"{float(mdi):.1f}" if pd.notna(mdi) else "N/A"
                adx = row.get('adx')
                slope = row.get('adx_slope')
                if pd.notna(adx):
                    if pd.notna(slope):
                        adx_slope_str = f"{float(adx):.1f} ({float(slope):+.1f})"
                    else:
                        adx_slope_str = f"{float(adx):.1f} (-)"
                else:
                    adx_slope_str = "N/A"
                rsi = row.get('rsi')
                rsi_str = f"{int(round(float(rsi)))}" if pd.notna(rsi) else "N/A"
                mfi = row.get('mfi')
                mfi_str = f"{int(round(float(mfi)))}" if pd.notna(mfi) else "N/A"
                rvol = row.get('rvol')
                rvol_str = f"{float(rvol):.1f}x" if pd.notna(rvol) else "N/A"
                _mh = row.get('macd_hist')
                _mhp = row.get('macd_hist_prev')
                mh_str = f"{float(_mh):.4f}" if pd.notna(_mh) else "N/A"
                mhp_str = f"{float(_mhp):.4f}" if pd.notna(_mhp) else "N/A"
                # Signal warning: Price vs SMA20, and Vol Spike when RVOL > 2
                warn = "-"
                if pd.notna(close) and pd.notna(sma20):
                    vol_spike = pd.notna(rvol) and float(rvol) > 2.0
                    if close < sma20:
                        warn = "☠️ <SMA20 (Vol Spike)" if vol_spike else "☠️ Price < SMA20"
                    elif close > sma20:
                        warn = ">SMA20 (Vol Spike)" if vol_spike else "Price > SMA20"
                lines.append(
                    f"| {date_str} | {close_str:>6} | {vwap_str:>6} | {obv_str:>7} | {sma20_str:>6} | {pdi_str:>5} | {mdi_str:>5} | {adx_slope_str:>11} | {rsi_str:>4} | {mfi_str:>3} | {rvol_str:>5} | {mh_str:>6} | {mhp_str:>6} | {warn:<22} |"
                )
            # Institutional context for AI: Price vs VWAP, OBV Trend (vs 5-day avg)
            last_row = last_10.iloc[-1]
            last_close = last_row.get('close')
            last_vwap = last_row.get('vwap')
            price_vs_vwap = "N/A"
            if pd.notna(last_close) and pd.notna(last_vwap):
                price_vs_vwap = "Above" if last_close > last_vwap else "Below"
            obv_trend = "N/A"
            if 'obv' in last_10.columns and last_10['obv'].notna().any():
                obv_5d = last_10['obv'].tail(5).dropna()
                if len(obv_5d) >= 2:
                    current_obv = last_10['obv'].iloc[-1]
                    avg_obv_5 = last_10['obv'].tail(5).mean()
                    obv_trend = "Rising (OBV > 5d avg)" if current_obv > avg_obv_5 else "Falling (OBV < 5d avg)"
            # Key Insights: Max RVOL (and date), Lowest MFI, plus institutional
            lines.extend([
                "",
                "[Institutional Context]",
                f"Price vs VWAP: {price_vs_vwap}",
                f"OBV Trend: {obv_trend}",
            ])
            # Key Insights: Max RVOL (and date), Lowest MFI
            rvol_vals = last_10['rvol'].dropna()
            if len(rvol_vals) > 0:
                idx_max_rvol = rvol_vals.idxmax()
                max_rvol_row = last_10.loc[idx_max_rvol]
                max_rvol = f"{float(max_rvol_row.get('rvol', 0)):.1f}x"
                date_max = max_rvol_row.get('time')
                date_of_max_rvol = date_max.strftime('%Y-%m-%d') if hasattr(date_max, 'strftime') else str(date_max)[:10]
            else:
                max_rvol = "N/A"
                date_of_max_rvol = "N/A"
            mfi_vals = last_10['mfi'].dropna()
            min_mfi = f"{int(round(float(mfi_vals.min())))}" if len(mfi_vals) else "N/A"
            lines.extend([
                "",
                "[Key Insights]",
                f"Max RVOL: {max_rvol} on {date_of_max_rvol}",
                f"Lowest MFI: {min_mfi}",
            ])
            _lr = last_10.iloc[-1]
            _ml = _lr.get("macd_line")
            _ms = _lr.get("macd_signal")
            _mh = _lr.get("macd_hist")
            _mhp = _lr.get("macd_hist_prev")
            _zc = "N/A"
            if pd.notna(_mh) and pd.notna(_mhp):
                _zc = "Yes" if (float(_mh) > 0 and float(_mhp) <= 0) else "No"
            _mld = f"{float(_ml):.4f}" if pd.notna(_ml) else "N/A"
            _msd = f"{float(_ms):.4f}" if pd.notna(_ms) else "N/A"
            _mhd = f"{float(_mh):.4f}" if pd.notna(_mh) else "N/A"
            _mhpd = f"{float(_mhp):.4f}" if pd.notna(_mhp) else "N/A"
            lines.extend([
                "",
                "[MACD (12,26,9) — latest bar]",
                f"Line: {_mld} | Signal: {_msd} | Hist: {_mhd} | Hist (prev): {_mhpd} | Zero-cross (Hist>0 & Hist_prev<=0): {_zc}",
            ])
            history_log_10d = "\n".join(lines)
        
        # Smart Bilingual News: Chinese (RSS) for HK stocks, English (yfinance) for US/others
        news_text = "No recent news available."
        if stock_code.upper().endswith(".HK"):
            # Route 1: Hong Kong — Traditional Chinese via Yahoo HK RSS
            rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(stock_code)}&region=HK&lang=zh-Hant-HK"
            try:
                req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
                with urllib.request.urlopen(req, timeout=8) as response:
                    xml_data = response.read()
                root = ET.fromstring(xml_data)
                news_list = []
                items = root.findall("./channel/item")
                if not items:
                    items = root.findall(".//item")  # fallback if feed uses default namespace
                for item in items[:3]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    title = title_el.text if title_el is not None and title_el.text else None
                    link = link_el.text if link_el is not None and link_el.text else "#"
                    if title:
                        news_list.append(f"- [{title}]({link}) (Yahoo HK)")
                if news_list:
                    news_text = "\n".join(news_list)
                else:
                    news_text = "暫無最新中文新聞。"
            except Exception as e:
                print(f"⚠️ HK RSS news fetch failed: {e}")
                news_text = "無法載入中文新聞 (RSS Error)。"
        else:
            # Route 2: US / others — English via yfinance (nested + flat structure)
            try:
                ticker_obj = yf.Ticker(stock_code)
                raw_news = ticker_obj.news[:5] if hasattr(ticker_obj, "news") and ticker_obj.news else []
                news_list = []
                for item in raw_news:
                    if "content" in item:
                        content = item["content"]
                        title = content.get("title", "No Title")
                        prov = content.get("provider") or {}
                        publisher = prov.get("displayName", "Unknown") if isinstance(prov, dict) else "Unknown"
                        link = None
                        if isinstance(content.get("clickThroughUrl"), dict):
                            link = content["clickThroughUrl"].get("url")
                        if not link and isinstance(content.get("canonicalUrl"), dict):
                            link = content["canonicalUrl"].get("url")
                        link = link or "#"
                    else:
                        title = item.get("title", "No Title")
                        publisher = item.get("publisher", "Unknown")
                        link = item.get("link", "#")
                    if title and title != "No Title":
                        news_list.append(f"- [{title}]({link}) ({publisher})")
                if news_list:
                    news_text = "\n".join(news_list[:3])
            except Exception as e:
                print(f"⚠️ yfinance news fetch failed: {e}")
                news_text = "Error fetching English news."

        # Risk-Exit Score (0-10) for hold danger
        details_for_risk = signal.get("details", {}) if signal else {}
        risk_info = _compute_risk_exit_score(df, details_for_risk, df.iloc[-1].to_dict())
        risk_score = risk_info["risk_score"]
        risk_label = risk_info["risk_label"]
        risk_breakdown = {
            "tech_risk": risk_info["tech_risk"],
            "trend_risk": risk_info["trend_risk"],
            "flow_risk": risk_info["flow_risk"],
        }

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
            'fundamental_status': fundamental_status,
            'extended_fundamental_data': extended_fundamental_data,  # Additional data for copy report
            'backtest_date': selected_date_str,  # The actual date used for backtesting
            'actual_future_performance': actual_future_performance,  # 5-day future performance for validation
            'is_backtest': backtest_date is not None,
            'timestamp': datetime.now(pytz.timezone('Asia/Hong_Kong')).strftime('%Y-%m-%d %H:%M:%S'),
            'latest_data_date': df.iloc[-1]['time'].strftime('%Y-%m-%d') if hasattr(df.iloc[-1]['time'], 'strftime') else str(df.iloc[-1]['time']),
            'debug_last5': debug_last5,
            'debug_index_dtype': debug_index_dtype,
            'history_log_10d': history_log_10d,
            'latest_row': df.iloc[-1].to_dict(),
            'rsi_history': rsi_history.to_dict(orient='list'),
            'news_text': news_text,
            'risk_score': risk_score,
            'risk_label': risk_label,
            'risk_breakdown': risk_breakdown,
        }
        
    except Exception as e:
        # Even on error, try to include fundamental_status if possible
        fundamental_status = None
        try:
            ticker_obj = yf.Ticker(stock_code)
            fundamental_status = get_fundamental_status(ticker_obj)
        except:
            # If we can't get fundamental data, create a fallback
            fundamental_status = {
                'status': 'unknown',
                'trailing_pe': None,
                'forward_pe': None,
                'peg_ratio': None,
                'eps': None,
                'debt_to_equity': None,
                'profit_margins': None,
                'current_price': None,
                'quick_ratio': None,
                'current_ratio': None,
                'warnings': [f"無法獲取基本面數據：分析過程中發生錯誤"],
                'risk_level': 'medium',
                'red_flags': []
            }
        
        return {
            'success': False,
            'error': str(e),
            'fundamental_status': fundamental_status  # Include even on error
        }


# Light Cyber / Modern FinTech SaaS — data card CSS (applies when Tracker runs)
CUSTOM_CSS_FINTECH = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
/* App-wide Inter font for top-tier FinTech look */
.stApp, .main, .block-container, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
/* Style the metric containers to look like sleek tech cards */
div[data-testid="metric-container"] {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    padding: 15px;
    border-radius: 10px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    transition: transform 0.2s ease-in-out;
}
div[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 12px rgba(0,85,255,0.15);
    border-color: #0055FF;
}
/* Make the metric values look crisp and techy */
div[data-testid="metric-container"] label {
    color: #6B7280 !important;
    font-weight: 600;
    font-family: 'Inter', sans-serif !important;
}
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #0055FF !important;
    font-weight: 800;
    font-family: 'Inter', sans-serif !important;
}
/* Hide default header/footer for standalone app feel */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
/* Keep Streamlit header visible so mobile users can reopen sidebar/hamburger */
header {visibility: visible;}
/* Compact “Key data” strip — lighter than full-width st.metric grid */
.key-data-strip {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 0.55rem 0.85rem;
    margin-bottom: 0.65rem;
    font-size: 0.8125rem;
    line-height: 1.45;
    color: #374151;
}
.key-data-strip .kv {
    display: inline-block;
    margin-right: 1.1rem;
    margin-bottom: 0.2rem;
    vertical-align: top;
}
.key-data-strip .k {
    color: #9CA3AF;
    font-weight: 600;
    font-size: 0.68rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.key-data-strip .v {
    color: #111827;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.key-data-signal {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.75rem;
    border-radius: 999px;
    font-size: 0.8125rem;
    font-weight: 600;
    margin-top: 0.35rem;
    border: 1px solid #E5E7EB;
    background: #F9FAFB;
    color: #111827;
}
.key-data-signal.buy { border-color: #10B981; background: #ECFDF5; color: #065F46; }
.key-data-signal.sell { border-color: #EF4444; background: #FEF2F2; color: #991B1B; }
.key-data-signal.wait { border-color: #F59E0B; background: #FFFBEB; color: #92400E; }
.key-data-signal.err { border-color: #DC2626; background: #FEF2F2; color: #7F1D1D; }
/* Quant dark dashboard cards — mobile-safe text + wrapping grids */
.quant-dark-card, .quant-radar-card {
    word-wrap: break-word;
    overflow-wrap: break-word;
    white-space: normal;
    max-width: 100%;
    box-sizing: border-box;
    font-size: clamp(0.75rem, 2vw, 1rem);
}
.quant-radar-card .plotly-graph-div {
    max-width: 100% !important;
}
@media (max-width: 640px) {
    .quant-dark-card {
        flex-wrap: wrap !important;
    }
    /* Inline grid tiles: stack / narrow columns on small screens */
    .quant-dark-card [style*="grid-template-columns: repeat(3"] {
        grid-template-columns: repeat(1, minmax(0, 1fr)) !important;
    }
    .quant-dark-card [style*="grid-template-columns: repeat(4"] {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
    .quant-dark-card [style*="grid-template-columns: repeat(2"] {
        grid-template-columns: 1fr !important;
    }
}
/* Dark Plotly charts — match quant card frame */
div[data-testid="stPlotlyChart"] {
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 10px 25px rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(51, 65, 85, 0.55);
    margin-bottom: 0.5rem;
}
</style>
"""


@st.cache_data(ttl=1800)
def get_advanced_macro():
    """Global macro snapshot (shared with macro_snapshot.json on the static site)."""
    return fetch_advanced_macro_data()


def calculate_macro_sentiment(macro_dict):
    try:
        # 1. VIX Contribution (25% Weight) - Fear Gauge
        vix_val = macro_dict.get("⚡ VIX 恐慌指數", {}).get("current", 20)
        if vix_val < 12:
            vix_score = 100
        elif vix_val > 35:
            vix_score = 0
        else:
            vix_score = 100 - ((vix_val - 12) / (35 - 12) * 100)

        # 2. S&P 500 RSI (25% Weight) - Market Momentum
        spx_rsi = macro_dict.get("🇺🇸 S&P 500", {}).get("rsi", 50)
        rsi_score = spx_rsi

        # 3. Yield Curve Spread: 10Y - 3M (30% Weight) - Systemic Recession Risk
        tnx_val = macro_dict.get("🇺🇸 10Y 國債息", {}).get("current", 4.0)
        irx_val = macro_dict.get("🇺🇸 3M 國債息", {}).get("current", 4.0)
        yield_spread = tnx_val - irx_val

        # If Spread is Negative (Inverted), it's a massive warning (Score drops to 0-30)
        # If Spread is Normal (> 1.0%), healthy environment (Score 80-100)
        if yield_spread < -0.5:
            spread_score = 0
        elif yield_spread > 1.5:
            spread_score = 100
        else:
            spread_score = (yield_spread + 0.5) / 2.0 * 100

        # 4. Bitcoin Momentum (20% Weight) - Speculative Greed / Liquidity Proxy
        btc_change = macro_dict.get("₿ Bitcoin", {}).get("change_pct", 0)
        # BTC is highly volatile. A +5% day is extremely greedy, a -5% day is panic.
        if btc_change > 5.0:
            btc_score = 100
        elif btc_change < -5.0:
            btc_score = 0
        else:
            btc_score = (btc_change + 5.0) / 10.0 * 100

        # Calculate final weighted score
        final_score = (vix_score * 0.25) + (rsi_score * 0.25) + (spread_score * 0.30) + (btc_score * 0.20)
        return max(0, min(100, final_score))

    except Exception:
        # Fallback to neutral if data is missing
        return 50.0


def calculate_macro_sentiment_breakdown(macro_dict: dict):
    """Return component values + scores for AI review."""
    try:
        # 1. VIX Contribution (25% Weight) - Fear Gauge
        vix_val = macro_dict.get("⚡ VIX 恐慌指數", {}).get("current", 20)
        if vix_val < 12:
            vix_score = 100
        elif vix_val > 35:
            vix_score = 0
        else:
            vix_score = 100 - ((vix_val - 12) / (35 - 12) * 100)

        # 2. S&P 500 RSI (25% Weight) - Market Momentum
        spx_rsi = macro_dict.get("🇺🇸 S&P 500", {}).get("rsi", 50)
        rsi_score = spx_rsi

        # 3. Yield Curve Spread: 10Y - 3M (30% Weight) - Systemic Recession Risk
        tnx_val = macro_dict.get("🇺🇸 10Y 國債息", {}).get("current", 4.0)
        irx_val = macro_dict.get("🇺🇸 3M 國債息", {}).get("current", 4.0)
        yield_spread = tnx_val - irx_val
        if yield_spread < -0.5:
            spread_score = 0
        elif yield_spread > 1.5:
            spread_score = 100
        else:
            spread_score = (yield_spread + 0.5) / 2.0 * 100

        # 4. Bitcoin Momentum (20% Weight) - Speculative Greed / Liquidity Proxy
        btc_change = macro_dict.get("₿ Bitcoin", {}).get("change_pct", 0)
        if btc_change > 5.0:
            btc_score = 100
        elif btc_change < -5.0:
            btc_score = 0
        else:
            btc_score = (btc_change + 5.0) / 10.0 * 100

        final_score = (vix_score * 0.25) + (rsi_score * 0.25) + (spread_score * 0.30) + (btc_score * 0.20)
        final_score = max(0, min(100, final_score))

        return {
            "vix_val": float(vix_val),
            "vix_score": float(vix_score),
            "spx_rsi": float(spx_rsi),
            "rsi_score": float(rsi_score),
            "tnx_val": float(tnx_val),
            "irx_val": float(irx_val),
            "yield_spread": float(yield_spread),
            "spread_score": float(spread_score),
            "btc_change": float(btc_change),
            "btc_score": float(btc_score),
            "final_score": float(final_score),
        }
    except Exception:
        return None


def _macro_sentiment_card_html(macro_dict: dict, light_mode: bool) -> str:
    """Institutional Macro Sentiment (Risk-On) compact card."""
    try:
        vix_val = macro_dict.get("⚡ VIX 恐慌指數", {}).get("current", 20)
        spx_rsi = macro_dict.get("🇺🇸 S&P 500", {}).get("rsi", 50)
        tnx_val = macro_dict.get("🇺🇸 10Y 國債息", {}).get("current", 4.0)
        irx_val = macro_dict.get("🇺🇸 3M 國債息", {}).get("current", 4.0)
        yield_spread = tnx_val - irx_val
        btc_change = macro_dict.get("₿ Bitcoin", {}).get("change_pct", 0)
        score = calculate_macro_sentiment(macro_dict)

        bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
        title_color = "#64748b" if light_mode else "#9ca3af"
        value_color = "#0f172a" if light_mode else "#f1f5f9"
        sub_color = "#475569" if light_mode else "#64748b"
        border_color = "#2563eb" if light_mode else "#3182ce"

        if score >= 75:
            mood = "Risk-On 偏強"
            mood_color = "#00cc66"
        elif score >= 50:
            mood = "Risk-On 中性"
            mood_color = "#f6ad55"
        else:
            mood = "Risk-Off 警戒"
            mood_color = "#ff4b4b"

        return f"""
        <div class="quant-dark-card" style="background: {bg}; padding: 14px 16px; border-radius: 12px;
            border: 1px solid {border_color}; box-shadow: 0 10px 25px rgba(15,23,42,{0.25 if light_mode else 0.45});">
            <p style="color: {title_color}; margin:0; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase;">
                Macro Sentiment（Risk-On）
            </p>
            <h3 style="color: {value_color}; margin: 8px 0 0 0; font-size: 1.5rem; font-weight: 900;">
                {score:.1f} <span style="font-size: 0.95rem; color: {mood_color}; font-weight: 800;">/ 100</span>
            </h3>
            <p style="color: {sub_color}; margin: 6px 0 0 0; font-size: 0.78rem; line-height: 1.45;">
                ⚡ VIX {vix_val:.1f} · S&P RSI {spx_rsi:.0f} · 10Y-3M {yield_spread:+.2f} · BTC {btc_change:+.2f}%
            </p>
            <p style="color: {mood_color}; margin: 4px 0 0 0; font-size: 0.82rem; font-weight: 700;">{mood}</p>
        </div>
        """
    except Exception:
        return ""


@st.cache_data(ttl=120)
def get_money_flow():
    """港股通（南下）淨額：滬港通 + 深港通，單位億人民幣。

    EastMoney `kamt/get` 裡 `dayNetAmtIn` 與額度欄位重疊，並非真實淨買賣；
    南下淨額應用 `sh2hk`/`sz2hk` 的 `netBuyAmt`（API 為萬元），除以 1e4 得億元。
    """
    url = "https://push2.eastmoney.com/api/qt/kamt/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f54,f55,f56,f58,f59,f60,f62,f63"

    flow_data = {"southbound_net": None}

    def _num(v):
        try:
            return float(v)
        except Exception:
            return 0.0

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "http://quote.eastmoney.com/",
        }
        response = requests.get(url, headers=headers, timeout=6)
        if response.status_code != 200:
            response = requests.get(url.replace("https://", "http://"), headers=headers, timeout=6)

        if response.status_code == 200:
            data = response.json()
            if data and data.get("data"):
                d = data["data"]
                sh = d.get("sh2hk") or {}
                sz = d.get("sz2hk") or {}
                # 萬元 → 億人民幣
                wan = _num(sh.get("netBuyAmt")) + _num(sz.get("netBuyAmt"))
                flow_data["southbound_net"] = wan / 10000.0

    except Exception as e:
        print(f"Money Flow API Error: {e}")

    return flow_data


@st.cache_data(ttl=1800)
def fetch_live_polymarket_data():
    """
    Live Polymarket via Gamma events API.
    Filters macro keywords, keeps valid Yes probabilities, then ranks by
    market volume/liquidity and returns top 3 highest-volume markets.
    Returns (dict, error_message). No mock fallback.
    """
    url = "https://gamma-api.polymarket.com/events"
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://polymarket.com/",
        "Origin": "https://polymarket.com",
    }

    target_keywords = ["recession", "rate cut", "fed", "inflation", "cpi"]
    candidates = []
    seen_condition = set()

    def _parse_list(value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return []

    def _num(value):
        try:
            return float(value)
        except Exception:
            return 0.0

    try:
        response = requests.get(
            url,
            params={"closed": "false", "limit": 500},
            headers=headers,
            timeout=25,
        )
        response.raise_for_status()
        raw = response.json()
        if isinstance(raw, list):
            events = raw
        elif isinstance(raw, dict):
            events = raw.get("data") or raw.get("events") or raw.get("results")
            if not isinstance(events, list):
                return {}, "Polymarket Gamma API Error: unexpected JSON shape (expected list or list under data/events)"
        else:
            return {}, "Polymarket Gamma API Error: response JSON is not a list or object"

        for event in events:
            event_title = (event.get("title") or "").strip()
            markets = event.get("markets") or []
            if not markets:
                continue

            for market in markets:
                question = (market.get("question") or "").strip()
                haystack = f"{event_title} {question}".lower()
                if not any(kw in haystack for kw in target_keywords):
                    continue

                outcomes = _parse_list(market.get("outcomes"))
                prices = _parse_list(market.get("outcomePrices"))
                if not outcomes or not prices:
                    continue

                yes_idx = next(
                    (i for i, out in enumerate(outcomes) if str(out).strip().lower() == "yes"),
                    None,
                )
                if yes_idx is None or yes_idx >= len(prices):
                    continue
                try:
                    prob = float(prices[yes_idx]) * 100.0
                except (TypeError, ValueError):
                    continue
                if not (1.0 < prob < 99.0):
                    continue

                condition_id = market.get("conditionId") or f"{event_title}:{question}"
                if condition_id in seen_condition:
                    continue
                seen_condition.add(condition_id)

                title = question or event_title or "Unknown market"
                volume = _num(market.get("volumeNum") or market.get("volume"))
                liquidity = _num(market.get("liquidity"))
                candidates.append(
                    {
                        "title": title,
                        "prob": prob,
                        "volume": volume,
                        "liquidity": liquidity,
                    }
                )

        # CRITICAL: rank macro markets by highest volume/liquidity (descending).
        ranked = sorted(candidates, key=lambda x: (x["volume"], x["liquidity"]), reverse=True)
        top3 = ranked[:3]
        return {row["title"]: row["prob"] for row in top3}, None

    except requests.exceptions.HTTPError as http_err:
        return {}, f"HTTP Error (API Blocked?): {http_err}"
    except Exception as e:
        return {}, f"Connection Error: {e}"


def _macro_index_card_html(title: str, data_dict: dict) -> str:
    """Rich index tile with RSI / SMA200 distance / 52w drawdown (gradient dark card)."""
    if not data_dict:
        return ""
    chg = float(data_dict.get("change_pct", 0.0))
    color = "#34d399" if chg > 0 else "#f87171"
    sign = "▲" if chg > 0 else "▼"
    cur = float(data_dict["current"])
    rsi = float(data_dict.get("rsi", 50.0))
    if rsi > 70:
        rsi_color = "#f87171"
    elif rsi < 30:
        rsi_color = "#34d399"
    else:
        # In light mode the neutral color cannot be near-white, otherwise RSI text blends in.
        rsi_color = "#64748b" if bool(st.session_state.get("light_box_mode", False)) else "#f1f5f9"
    dist = float(data_dict.get("dist_sma200", 0.0))
    dd = float(data_dict.get("drawdown", 0.0))
    dist_color = "#34d399" if dist > 0 else "#f87171" if dist < 0 else "#94a3b8"
    border = "#805ad5" if "S&P" in title else "#dd6b20"
    light_mode = bool(st.session_state.get("light_box_mode", False))
    bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
    title_color = "#64748b" if light_mode else "#9ca3af"
    value_color = "#0f172a" if light_mode else "#f1f5f9"
    sub_color = "#475569" if light_mode else "#64748b"
    box = (
        f"background: {bg}; padding: 14px 16px; border-radius: 12px; "
        "margin-bottom: 10px; box-shadow: 0 10px 25px rgba(15,23,42,0.25); border-left: 4px solid %s; "
        "word-wrap: break-word; overflow-wrap: break-word;"
    ) % border
    return f"""
    <div style="{box}">
        <p style="color: {title_color}; margin:0; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase;">{html.escape(title)}</p>
        <h3 style="color: {value_color}; margin: 8px 0; font-size: 1.35rem; font-weight: 800;">
            {cur:,.2f} <span style="font-size: 0.95rem; color: {color}; font-weight: 700;">{sign} {abs(chg):.2f}%</span>
        </h3>
        <p style="color: {sub_color}; margin:0; font-size: 0.78rem; line-height: 1.5;">
            RSI: <span style="color: {rsi_color}; font-weight: 600;">{rsi:.1f}</span> ·
            距200天線: <span style="color: {dist_color}; font-weight: 600;">{dist:+.1f}%</span> ·
            52週回撤: <span style="color: #f87171; font-weight: 600;">{dd:.1f}%</span>
        </p>
    </div>
    """


def _macro_simple_index_html(title: str, data_dict: dict) -> str:
    """Index row when only current + daily change (insufficient history)."""
    if not data_dict:
        return ""
    chg = float(data_dict.get("change_pct", 0.0))
    color = "#34d399" if chg > 0 else "#f87171"
    sign = "▲" if chg > 0 else "▼"
    cur = float(data_dict["current"])
    light_mode = bool(st.session_state.get("light_box_mode", False))
    bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
    title_color = "#64748b" if light_mode else "#9ca3af"
    value_color = "#0f172a" if light_mode else "#f1f5f9"
    sub_color = "#475569" if light_mode else "#64748b"
    box = (
        f"background: {bg}; padding: 14px 16px; border-radius: 12px; "
        "margin-bottom: 10px; box-shadow: 0 10px 25px rgba(15,23,42,0.25); border-left: 4px solid #64748b; "
        "word-wrap: break-word; overflow-wrap: break-word;"
    )
    return f"""
    <div style="{box}">
        <p style="color: {title_color}; margin:0; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase;">{html.escape(title)}</p>
        <h3 style="color: {value_color}; margin: 8px 0; font-size: 1.35rem; font-weight: 800;">
            {cur:,.2f} <span style="font-size: 0.95rem; color: {color}; font-weight: 700;">{sign} {abs(chg):.2f}%</span>
        </h3>
        <p style="color: {sub_color}; margin:0; font-size: 0.72rem;">技術指標需更長歷史數據</p>
    </div>
    """


def _macro_mini_card_html(title: str, data_dict: dict) -> str:
    """Commodity / FX compact tile."""
    if not data_dict:
        return ""
    chg = float(data_dict.get("change_pct", 0.0))
    color = "#34d399" if chg > 0 else "#f87171"
    sign = "▲" if chg > 0 else "▼"
    cur = float(data_dict["current"])
    if "USD/" in title or "HKD/" in title or "人幣" in title or "日圓" in title:
        cur_fmt = f"{cur:.4f}"
    else:
        cur_fmt = f"{cur:,.2f}"
    light_mode = bool(st.session_state.get("light_box_mode", False))
    bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
    title_color = "#64748b" if light_mode else "#9ca3af"
    value_color = "#0f172a" if light_mode else "#f1f5f9"
    box = (
        f"background: {bg}; padding: 12px 14px; border-radius: 12px; "
        "box-shadow: 0 8px 20px rgba(15,23,42,0.25); border: 1px solid rgba(51,65,85,0.4); "
        "word-wrap: break-word; overflow-wrap: break-word;"
    )
    return f"""
    <div style="{box}">
        <p style="color: {title_color}; margin:0; font-size: 0.72rem; letter-spacing: 0.05em;">{html.escape(title)}</p>
        <h4 style="color: {value_color}; margin: 4px 0; font-size: 1.1rem; font-weight: 800;">{cur_fmt}</h4>
        <p style="color: {color}; margin:0; font-size: 0.8rem; font-weight: 600;">{sign} {abs(chg):.2f}%</p>
    </div>
    """


def _macro_rate_card_html(title: str, data_dict: dict) -> str:
    """Interest-rate specific card (adds % sign)."""
    if not data_dict:
        return ""
    chg = float(data_dict.get("change_pct", 0.0))
    color = "#34d399" if chg > 0 else "#f87171"
    sign = "▲" if chg > 0 else "▼"
    cur = float(data_dict["current"])
    light_mode = bool(st.session_state.get("light_box_mode", False))
    bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
    title_color = "#64748b" if light_mode else "#9ca3af"
    value_color = "#0f172a" if light_mode else "#f1f5f9"
    box = (
        f"background: {bg}; padding: 12px 14px; border-radius: 12px; "
        "box-shadow: 0 8px 20px rgba(15,23,42,0.25); border: 1px solid rgba(51,65,85,0.4); "
        "word-wrap: break-word; overflow-wrap: break-word;"
    )
    return f"""
    <div style="{box}">
        <p style="color: {title_color}; margin:0; font-size: 0.72rem; letter-spacing: 0.05em;">{html.escape(title)}</p>
        <h4 style="color: {value_color}; margin: 6px 0 4px 0; font-size: 1.2rem; font-weight: 900;">{cur:.2f}%</h4>
        <p style="color: {color}; margin:0; font-size: 0.85rem; font-weight: 700;">{sign} {abs(chg):.2f}%</p>
        <p style="color: #64748b; margin:0; font-size: 0.7rem;">1-day % change on yield</p>
    </div>
    """


def _macro_vix_card_html(data_dict: dict) -> str:
    if not data_dict:
        return ""
    v = float(data_dict["current"])
    chg = float(data_dict.get("change_pct", 0.0))
    if v > 25:
        v_color = "#f87171"
        mood = "高波動 / 恐慌區"
    elif v > 20:
        v_color = "#fb923c"
        mood = "警戒"
    else:
        v_color = "#34d399"
        mood = "相對安定"
    chg_color = "#34d399" if chg > 0 else "#f87171"
    sign = "▲" if chg > 0 else "▼"
    light_mode = bool(st.session_state.get("light_box_mode", False))
    bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
    title_color = "#64748b" if light_mode else "#9ca3af"
    value_color = "#0f172a" if light_mode else "#f1f5f9"
    box = (
        f"background: {bg}; padding: 14px 16px; border-radius: 12px; "
        "margin-bottom: 10px; box-shadow: 0 10px 25px rgba(15,23,42,0.25); border-left: 4px solid %s; "
        "word-wrap: break-word; overflow-wrap: break-word;"
    ) % v_color
    return f"""
    <div style="{box}">
        <p style="color: {title_color}; margin:0; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase;">⚡ VIX 恐慌指數</p>
        <h3 style="color: {value_color}; margin: 8px 0; font-size: 1.35rem; font-weight: 800;">{v:.2f}</h3>
        <p style="color: {chg_color}; margin:0; font-size: 0.8rem; font-weight: 600;">{sign} {abs(chg):.2f}% 日變化</p>
        <p style="color: {v_color}; margin: 8px 0 0 0; font-size: 0.82rem; font-weight: 600;">{mood} · 大市波動率預期</p>
    </div>
    """


def _box_theme_css(light_mode: bool) -> str:
    """Theme override for black information cards only."""
    if light_mode:
        return """
        <style>
        .quant-dark-card, .quant-radar-card, .key-data-strip {
            background: #f8fafc !important;
            border: 1px solid #e2e8f0 !important;
            box-shadow: 0 2px 8px rgba(2, 6, 23, 0.08) !important;
            color: #0f172a !important;
        }
        .quant-dark-card h1, .quant-dark-card h2, .quant-dark-card h3, .quant-dark-card h4,
        .quant-dark-card p, .quant-dark-card div, .quant-radar-card h1, .quant-radar-card h2,
        .quant-radar-card h3, .quant-radar-card h4, .quant-radar-card p, .quant-radar-card div {
            color: #0f172a !important;
        }
        </style>
        """
    return """
    <style>
    .quant-dark-card, .quant-radar-card, .key-data-strip {
        background: linear-gradient(120deg, #020617, #0f172a) !important;
        border: 1px solid rgba(51, 65, 85, 0.55) !important;
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.45) !important;
        color: #e2e8f0 !important;
    }
    </style>
    """


# Main Streamlit App
def main():
    # Sticky API key and per-stock chat history (survives mode/ticker switches)
    if "api_key" not in st.session_state:
        st.session_state.api_key = ""
    if "stock_chats" not in st.session_state:
        st.session_state.stock_chats = {}

    st.markdown(CUSTOM_CSS_FINTECH, unsafe_allow_html=True)

    # Sidebar for Time Machine / Backtest Mode + Gemini
    with st.sidebar:
        if "light_box_mode" not in st.session_state:
            st.session_state.light_box_mode = False
        st.session_state.light_box_mode = st.toggle(
            "🌗 黑色卡片改 Light Mode",
            value=st.session_state.light_box_mode,
            help="只切換深色資訊卡（black boxes）明暗，不改整體頁面主題。",
        )
        st.markdown("---")
        st.sidebar.markdown("### 🔧 系統修復 (System Tools)")
        if st.sidebar.button(
            "🔄 重新整理 (Refresh)",
            type="primary",
            help="清除所有資料快取並重新載入頁面（全球宏觀儀表板、股票分析快取等）",
        ):
            st.cache_data.clear()
            st.rerun()
        debug_mode = st.sidebar.checkbox("🐞 開啟除錯模式 (Debug Mode)")

        st.markdown("### 🤖 Gemini AI 設定")
        st.session_state.api_key = st.sidebar.text_input(
            "🔑 Gemini API Key",
            value=st.session_state.api_key,
            type="password",
        )
        if st.session_state.api_key:
            try:
                genai.configure(api_key=st.session_state.api_key)
            except Exception as e:
                st.error(f"Gemini 配置失敗: {e}")

        st.markdown("### ⚙️ 分析模式")
        mode = st.radio(
            "選擇模式",
            ["🔴 即時模式", "⏳ 回測模式"],
            index=0,
            help="即時模式：分析當前市場數據\n回測模式：選擇歷史日期進行回測驗證"
        )
        
        backtest_date = None
        is_backtest_mode = (mode == "⏳ 回測模式")
        
        if is_backtest_mode:
            st.markdown("---")
            st.markdown("### 📅 選擇歷史日期")
            # Default to 30 days ago
            default_date = datetime.now().date() - pd.Timedelta(days=30)
            backtest_date = st.date_input(
                "選擇回測日期",
                value=default_date,
                max_value=datetime.now().date(),
                help="選擇一個過去的日期，系統將以該日期為基準進行分析"
            )
            st.info("💡 **提示：** 系統會自動選擇該日期之前最近的交易日（如果選擇的是週末或假日）")
    
    # Apply box-only theme override from sidebar toggle.
    st.markdown(_box_theme_css(st.session_state.light_box_mode), unsafe_allow_html=True)
    light_mode = bool(st.session_state.light_box_mode)

    # --- Global Macro Dashboard (top of main area, before stock scanner) ---
    _macro_hdr_l, _macro_hdr_r = st.columns([4, 1])
    with _macro_hdr_l:
        st.markdown("### 🌍 全球宏觀天氣預報 (Global Macro Dashboard)")
        st.caption("指數含 RSI / 距200天線 / 52週回撤；商品與外匯為近5日行情。快取 30 分鐘，右側可強制更新。")
    with _macro_hdr_r:
        st.markdown("<div style='height: 2.25rem;'></div>", unsafe_allow_html=True)
        if st.button(
            "🔄 更新宏觀",
            key="macro_refresh_btn",
            use_container_width=True,
            help="只刷新全球宏觀儀表板資料，不影響個股分析快取",
        ):
            get_advanced_macro.clear()
            get_money_flow.clear()
            fetch_live_polymarket_data.clear()
            st.rerun()

    macro = get_advanced_macro()
    polymarket_predictions, pm_error = fetch_live_polymarket_data()

    # --- Macro Dashboard layout (mobile-friendly grouping) ---
    st.subheader("📊 主要指數 (Major Indices)")

    equity_keys = [
        "🇺🇸 S&P 500",
        "🇺🇸 納斯達克 (Nasdaq)",
        "🇭🇰 恒生指數 (HSI)",
        "🇨🇳 上證指數 (SSE)",
    ]
    for i in range(0, len(equity_keys), 2):
        cols = st.columns(2)
        with cols[0]:
            k0 = equity_keys[i]
            data0 = macro.get(k0)
            if data0:
                st.markdown(_macro_index_card_html(k0, data0), unsafe_allow_html=True)
            else:
                st.caption(f"{k0} 暫不可用")
        with cols[1]:
            if i + 1 < len(equity_keys):
                k1 = equity_keys[i + 1]
                data1 = macro.get(k1)
                if data1:
                    st.markdown(_macro_index_card_html(k1, data1), unsafe_allow_html=True)
                else:
                    st.caption(f"{k1} 暫不可用")

    st.subheader("🏦 風險與資金成本 (Risk & Yields)")
    # VIX + Yield curve proxies: 10Y / 5Y / 3M
    r_col1, r_col2, r_col3, r_col4 = st.columns(4)
    with r_col1:
        vix = macro.get("⚡ VIX 恐慌指數")
        if vix:
            st.markdown(_macro_vix_card_html(vix), unsafe_allow_html=True)
        else:
            st.caption("VIX 暫不可用")
    with r_col2:
        tnx10 = macro.get("🇺🇸 10Y 國債息")
        if tnx10:
            st.markdown(_macro_rate_card_html("🇺🇸 10Y 國債息", tnx10), unsafe_allow_html=True)
        else:
            st.caption("10Y 暫不可用")
    with r_col3:
        fvx5 = macro.get("🇺🇸 5Y 國債息")
        if fvx5:
            st.markdown(_macro_rate_card_html("🇺🇸 5Y 國債息", fvx5), unsafe_allow_html=True)
        else:
            st.caption("5Y 暫不可用")
    with r_col4:
        irx3m = macro.get("🇺🇸 3M 國債息")
        if irx3m:
            st.markdown(_macro_rate_card_html("🇺🇸 3M 國債息", irx3m), unsafe_allow_html=True)
        else:
            st.caption("3M 暫不可用")

    st.subheader("商品、加密貨幣與外匯 · Commodities, Crypto & FX")
    c_row1_col1, c_row1_col2 = st.columns(2)
    with c_row1_col1:
        o = macro.get("期油 (WTI)")
        if o:
            st.markdown(_macro_mini_card_html("🛢️ 期油 (WTI)", o), unsafe_allow_html=True)
        else:
            st.caption("WTI 暫不可用")
    with c_row1_col2:
        dxy = macro.get("📈 美元指數 (DXY)")
        if dxy:
            st.markdown(_macro_mini_card_html("📈 美元指數 (DXY)", dxy), unsafe_allow_html=True)
        else:
            st.caption("DXY 暫不可用")
    c_row2_col1, c_row2_col2 = st.columns(2)
    with c_row2_col1:
        b = macro.get("₿ Bitcoin")
        if b:
            st.markdown(_macro_mini_card_html("₿ Bitcoin (BTC-USD)", b), unsafe_allow_html=True)
    with c_row2_col2:
        fx = macro.get("USD/HKD (美元/港幣)")
        if fx:
            st.markdown(_macro_mini_card_html("🇭🇰 USD/HKD (美元/港幣)", fx), unsafe_allow_html=True)

    # --- Macro Sentiment + 港股通（北水）淨額 ---
    money_flow = get_money_flow()
    sb_net_raw = money_flow.get("southbound_net")
    if sb_net_raw is not None:
        st.session_state["last_southbound_net"] = float(sb_net_raw)
        sb_net = float(sb_net_raw)
    else:
        sb_net = float(st.session_state.get("last_southbound_net", 0.0))

    sb_color_display = "#00cc66" if sb_net > 0 else "#ff4b4b"
    sb_sign = "+" if sb_net > 0 else ""

    st.subheader("🦈 資金與風險偏好")
    mf_col1, mf_col2 = st.columns(2)
    with mf_col1:
        st.markdown(_macro_sentiment_card_html(macro, light_mode=light_mode), unsafe_allow_html=True)
    with mf_col2:
        mf_bg = "#f8fafc" if light_mode else "linear-gradient(120deg, #020617, #0f172a)"
        mf_label = "#64748b" if light_mode else "#a0aec0"
        mf_value = "#0f172a" if light_mode else "#f8fafc"
        stale_note = ""
        if sb_net_raw is None:
            stale_note = '<p style="color:#f6ad55; margin:4px 0 0 0; font-size:0.75rem;">（暫用上次有效數據，請稍後再刷新）</p>'
        st.markdown(
            f"""
            <div class="quant-dark-card" style="background: {mf_bg}; padding: 15px; border-radius: 12px; border-left: 5px solid {sb_color_display}; box-shadow: 0 10px 25px rgba(15,23,42,0.25);">
                <p style="color: {mf_label}; margin:0; font-size: 0.9rem;">🇭🇰 港股通（北水）淨額（滬港通＋深港通）</p>
                <h3 style="color: {mf_value}; margin: 6px 0;">{sb_sign}{sb_net:.2f} <span style="font-size: 1rem;">億人民幣</span></h3>
                <p style="color: {sb_color_display}; margin:0; font-size: 0.8rem;">正數＝淨流入港股 · 負數＝淨流出港股</p>
                {stale_note}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")  # Spacing

    if pm_error:
        st.error(f"🔴 Polymarket 數據連線失敗: {pm_error}")
    elif polymarket_predictions:
        st.subheader("🔮 Polymarket 實時預測 (Live Probabilities)")
        pm_bg = "#f8fafc" if light_mode else "#1e293b"
        pm_title_color = "#64748b" if light_mode else "#a0aec0"
        pm_value_color = "#7c3aed" if light_mode else "#c4b5fd"
        pm_border = "#8b5cf6"
        cols = st.columns(len(polymarket_predictions))
        for i, (event_title, prob) in enumerate(polymarket_predictions.items()):
            safe_title = html.escape(event_title)
            safe_attr = html.escape(event_title, quote=True)
            with cols[i]:
                st.markdown(
                    f"""
            <div style="background-color: {pm_bg}; padding: 15px; border-radius: 8px; border-left: 4px solid {pm_border};">
                <p style="color: {pm_title_color}; margin:0; font-size: 0.8rem; line-height: 1.2; height: 35px; overflow: hidden;" title="{safe_attr}">{safe_title}</p>
                <h3 style="color: {pm_value_color}; margin: 5px 0;">{prob:.1f}%</h3>
                <p style="color: {pm_border}; margin:0; font-size: 0.75rem;"></p>
            </div>
            """,
                    unsafe_allow_html=True,
                )
    else:
        st.caption(
            "Polymarket (gamma-api.polymarket.com /events): OK, but no macro markets matched "
            "keywords (recession / rate cut / fed / inflation / cpi), or Yes% not in (1%, 99%)."
        )

    # --- Generate AI Summary String ---
    ai_summary_text = "【全球宏觀大市數據總結】\n"
    hk_now = datetime.now(pytz.timezone("Asia/Hong_Kong"))
    ai_summary_text += f"更新時間: {hk_now.strftime('%Y-%m-%d %H:%M')} (HKT)\n\n"

    for asset_name, data in macro.items():
        if not isinstance(data, dict):
            continue
        current = data.get("current", 0)
        change = data.get("change_pct", 0)
        try:
            current_f = float(current)
            change_f = float(change)
        except Exception:
            continue
        ai_summary_text += f"🔹 {asset_name}: {current_f:.2f} (日變化: {change_f:.2f}%)\n"

        # Add technicals if they exist for this asset
        if "rsi" in data:
            rsi = float(data.get("rsi", 0) or 0)
            dist_sma = float(data.get("dist_sma200", 0) or 0)
            drawdown = float(data.get("drawdown", 0) or 0)
            ai_summary_text += f"   - 走勢數據: RSI {rsi:.1f} | 距200天線 {dist_sma:.1f}% | 52週回撤 {drawdown:.1f}%\n"

    macro_sentiment_score = calculate_macro_sentiment(macro)
    macro_sentiment_breakdown = calculate_macro_sentiment_breakdown(macro)
    ai_summary_text += "\n【宏觀風險情緒 Macro Sentiment（Risk-On）】\n"
    ai_summary_text += f"🔹 風險偏好指數（0-100）: {macro_sentiment_score:.1f}\n"
    if macro_sentiment_breakdown:
        ai_summary_text += "\n【計算方法（供 AI 參考）】\n"
        ai_summary_text += (
            "1) VIX（Fear Gauge, 25%）："
            f"VIX={macro_sentiment_breakdown['vix_val']:.1f} -> score={macro_sentiment_breakdown['vix_score']:.1f}\n"
        )
        ai_summary_text += (
            "2) S&P RSI（Momentum, 25%）："
            f"RSI={macro_sentiment_breakdown['spx_rsi']:.1f} -> score={macro_sentiment_breakdown['rsi_score']:.1f}\n"
        )
        ai_summary_text += (
            "3) Yield Curve Spread（10Y-3M, 30%）："
            f"spread={macro_sentiment_breakdown['yield_spread']:+.2f} -> score={macro_sentiment_breakdown['spread_score']:.1f}\n"
        )
        ai_summary_text += (
            "4) BTC Change（Spec Greed, 20%）："
            f"BTCd={macro_sentiment_breakdown['btc_change']:+.2f}% -> score={macro_sentiment_breakdown['btc_score']:.1f}\n"
        )
        ai_summary_text += (
            "Final = VIX*25% + RSI*25% + Spread*30% + BTC*20% (clamped 0..100)\n"
        )
    else:
        ai_summary_text += "\n（提示：宏觀情緒計算缺少部分輸入數據，已回落到中性值。）\n"

    ai_summary_text += "\n【港股通（北水）淨額】\n"
    ai_summary_text += f"🔹 淨額（正＝淨流入港股，負＝淨流出）: {sb_sign}{sb_net:.2f} 億人民幣\n"
    if polymarket_predictions and not pm_error:
        ai_summary_text += "\n【🔮 Polymarket 真金白銀預測機率】\n"
        for event_title, prob in polymarket_predictions.items():
            ai_summary_text += f"🔹 {event_title}: {prob:.1f}%\n"
    elif pm_error:
        ai_summary_text += f"\n【Polymarket】無法取得資料: {pm_error}\n"
    ai_summary_text += "\n請根據以上數據，以專業對沖基金經理的視角，為我分析今日的宏觀市場情緒、資金流向趨勢，並給出港美股的操作建議。"

    st.write("")  # Spacing
    with st.expander("🤖 複製數據交給 AI 助手分析 (1-Click Copy for AI)"):
        st.markdown("點擊下方代碼塊右上角的 **「複製」** 按鈕，直接貼上給 Gemini / ChatGPT 分析大市：")
        st.code(ai_summary_text, language="markdown")
    st.divider()

    # Compact header
    col_header1, col_header2 = st.columns([4, 1])
    with col_header1:
        st.markdown("## 股票分析器")
        if is_backtest_mode:
            st.markdown(f"<div style='background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 0.5rem 1rem; border-radius: 4px; margin-top: 0.5rem;'><strong>⏳ 回測模式：</strong> 分析日期：{backtest_date.strftime('%Y-%m-%d')}</div>", unsafe_allow_html=True)
    with col_header2:
        st.markdown(f"<div style='text-align: right; color: #6b7280; font-size: 0.75rem; padding-top: 0.5rem;'>v{VERSION}</div>", unsafe_allow_html=True)
    
    # Input section - compact: ticker + button on one row
    search_col1, search_col2 = st.columns([3, 1])
    with search_col1:
        stock_input = st.text_input(
            "",
            value="700",
            placeholder="輸入股票代碼（例如：700, AAPL, 1）",
            help="支援格式：700, 00700, HK.00700, AAPL, US.AAPL",
            label_visibility="collapsed"
        )
    with search_col2:
        analyze_button = st.button("分析", type="primary", use_container_width=True)
    
    # Analyze button clicked or Enter key pressed
    if analyze_button or stock_input:
        if not stock_input.strip():
            st.warning("請輸入股票代碼")
        else:
            with st.spinner("正在分析股票數據..."):
                # Normalize stock code
                stock_code = normalize_stock_code(stock_input)
                
                # Analyze stock
                result = analyze_stock(stock_code, original_input=stock_input, backtest_date=backtest_date if is_backtest_mode else None, debug_mode=debug_mode)
                
                if result['success']:
                    # Debug: show last 5 rows and index dtype at top of main page
                    if debug_mode and result.get('debug_last5') is not None:
                        st.markdown("### 🐞 Debug: Raw Data (Last 5 Rows)")
                        st.dataframe(result['debug_last5'], use_container_width=True)
                        st.caption(f"**Index dtype (before reset):** `{result.get('debug_index_dtype', 'N/A')}` — check for timezone issues.")
                        st.markdown("---")
                    
                    # Display backtest validation if in backtest mode
                    if result.get('is_backtest', False):
                        actual_performance = result.get('actual_future_performance')
                        backtest_date_str = result.get('backtest_date', 'Unknown')
                        
                        if actual_performance is not None:
                            performance_color = "#16a34a" if actual_performance > 0 else "#dc2626"
                            performance_icon = "🚀" if actual_performance > 0 else "📉"
                            st.markdown(
                                f"<div style='background-color: #f0f9ff; border-left: 4px solid #0066CC; padding: 1rem; border-radius: 4px; margin-bottom: 1rem;'>"
                                f"<h4 style='margin-top: 0; color: #0066CC;'>⏳ 回測驗證結果</h4>"
                                f"<p style='margin-bottom: 0.5rem;'><strong>分析日期：</strong>{backtest_date_str}</p>"
                                f"<p style='margin-bottom: 0;'><strong>實際 5 日表現：</strong> "
                                f"<span style='color: {performance_color}; font-weight: 700; font-size: 1.2rem;'>{performance_icon} {actual_performance:+.2f}%</span></p>"
                                f"<p style='margin-top: 0.5rem; margin-bottom: 0; font-size: 0.875rem; color: #6b7280;'>"
                                f"💡 此數據僅供驗證 AI 預測準確度，不會包含在複製報告中</p>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                        else:
                            st.info(f"⚠️ 回測模式：分析日期 {backtest_date_str}，但無法計算 5 日後表現（數據不足）")
                    
                    # Yahoo Finance-style Ticker Tape Header
                    price_change = result.get('price_change')
                    price_change_percent = result.get('price_change_percent')
                    current_price = result['current_price']
                    
                    # Determine color based on price change
                    if price_change is not None:
                        if price_change > 0:
                            price_color = "#16a34a"  # Green for up
                            change_color = "#16a34a"
                            change_prefix = "+"
                        elif price_change < 0:
                            price_color = "#dc2626"  # Red for down
                            change_color = "#dc2626"
                            change_prefix = ""
                        else:
                            price_color = "#1a1a1a"  # Black for no change
                            change_color = "#6b7280"
                            change_prefix = ""
                    else:
                        price_color = "#1a1a1a"
                        change_color = "#6b7280"
                        change_prefix = ""
                    
                    # Unified header layout
                    header_col1, header_col2, header_col3 = st.columns([3, 2, 1])
                    with header_col1:
                        st.markdown(f"<div style='margin-bottom: 0.5rem;'><span style='font-size: 1.75rem; font-weight: 700; color: #1a1a1a;'>{result['stock_name']}</span> <span style='font-size: 1.25rem; font-weight: 600; color: #6b7280; margin-left: 0.5rem;'>{result['stock_code']}</span></div>", unsafe_allow_html=True)
                    
                    with header_col2:
                        if price_change is not None and price_change_percent is not None:
                            delta_display = f"{change_prefix}{price_change:.2f} ({change_prefix}{price_change_percent:.2f}%)"
                        else:
                            delta_display = "N/A"
                        
                        st.markdown(f"""
                        <div style='text-align: right;'>
                            <div style='font-size: 2.25rem; font-weight: 700; color: {price_color}; line-height: 1.2;'>{current_price:.2f}</div>
                            <div style='font-size: 1rem; font-weight: 600; color: {change_color}; margin-top: 0.25rem;'>{delta_display}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with header_col3:
                        st.markdown(
                            f"<div style='text-align: right; color: #9ca3af; font-size: 0.75rem; padding-top: 1.5rem;'>"
                            f"Updated: {result['timestamp']} (HKT)"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                    
                    # Display Candlestick Chart with Bollinger Bands
                    if result.get('chart_data'):
                        chart_data = result['chart_data']
                        
                        # Prepare data
                        dates = chart_data['dates']
                        opens = chart_data['open']
                        highs = chart_data['high']
                        lows = chart_data['low']
                        closes = chart_data['close']
                        bb_upper = chart_data['bb_upper']
                        bb_middle = chart_data['bb_middle']
                        bb_lower = chart_data['bb_lower']
                        
                        fig = go.Figure()
                        
                        # Add Bollinger Bands as filled area (semi-transparent)
                        fig.add_trace(go.Scatter(
                            x=dates,
                            y=bb_upper,
                            name='布林上軌',
                            line=dict(color='rgba(248, 113, 113, 0.35)', width=1),
                            showlegend=False,
                            hoverinfo='skip'
                        ))
                        fig.add_trace(go.Scatter(
                            x=dates,
                            y=bb_lower,
                            name='布林下軌',
                            line=dict(color='rgba(248, 113, 113, 0.35)', width=1),
                            fill='tonexty',
                            fillcolor='rgba(248, 113, 113, 0.08)',
                            showlegend=False,
                            hoverinfo='skip'
                        ))
                        
                        # Add Bollinger Middle line
                        fig.add_trace(go.Scatter(
                            x=dates,
                            y=bb_middle,
                            name='布林中線',
                            line=dict(color='#64748b', width=1, dash='dot'),
                            hovertemplate='<b>布林中線</b><br>日期: %{x}<br>價格: %{y:.2f}<extra></extra>'
                        ))
                        
                        # Add Bollinger Upper line (visible)
                        fig.add_trace(go.Scatter(
                            x=dates,
                            y=bb_upper,
                            name='布林上軌',
                            line=dict(color='#f87171', width=1.5, dash='dash'),
                            hovertemplate='<b>布林上軌</b><br>日期: %{x}<br>價格: %{y:.2f}<extra></extra>'
                        ))
                        
                        # Add Bollinger Lower line (visible)
                        fig.add_trace(go.Scatter(
                            x=dates,
                            y=bb_lower,
                            name='布林下軌',
                            line=dict(color='#4ade80', width=1.5, dash='dash'),
                            hovertemplate='<b>布林下軌</b><br>日期: %{x}<br>價格: %{y:.2f}<extra></extra>'
                        ))
                        
                        # Add Candlestick chart (dark-theme friendly greens/reds)
                        fig.add_trace(go.Candlestick(
                            x=dates,
                            open=opens,
                            high=highs,
                            low=lows,
                            close=closes,
                            name='價格',
                            increasing_line_color='#4ade80',
                            decreasing_line_color='#f87171',
                            increasing_fillcolor='#22c55e',
                            decreasing_fillcolor='#ef4444',
                            hovertemplate='<b>%{fullData.name}</b><br>日期: %{x}<br>開盤: %{open:.2f}<br>最高: %{high:.2f}<br>最低: %{low:.2f}<br>收盤: %{close:.2f}<extra></extra>'
                        ))
                        
                        # Chart layout follows light/dark card mode
                        chart_plot_bg = '#f8fafc' if light_mode else '#111827'
                        chart_paper_bg = '#ffffff' if light_mode else '#0f172a'
                        chart_title_color = '#0f172a' if light_mode else '#e5e7eb'
                        chart_axis_color = '#475569' if light_mode else '#94a3b8'
                        chart_grid_color = '#cbd5e1' if light_mode else '#334155'
                        chart_line_color = '#94a3b8' if light_mode else '#475569'
                        chart_font_color = '#334155' if light_mode else '#cbd5e1'
                        fig.update_layout(
                            title_text=f"{result['stock_code']} · 價格圖表",
                            title_x=0.5,
                            title_font_size=15,
                            title_font_color=chart_title_color,
                            xaxis_title="",
                            yaxis_title="價格",
                            yaxis_title_font=dict(color=chart_axis_color, size=12),
                            hovermode='x unified',
                            plot_bgcolor=chart_plot_bg,
                            paper_bgcolor=chart_paper_bg,
                            font=dict(family='Inter, sans-serif', color=chart_font_color, size=11),
                            height=380,
                            margin=dict(l=8, r=8, t=48, b=8),
                            xaxis_rangeslider_visible=False,
                            legend=dict(
                                orientation="h",
                                yanchor="bottom",
                                y=1.02,
                                xanchor="right",
                                x=1,
                                font_size=10,
                                font_color=chart_axis_color,
                                bgcolor='rgba(255,255,255,0.70)' if light_mode else 'rgba(15,23,42,0.6)',
                            )
                        )
                        
                        fig.update_xaxes(
                            title_font_size=11,
                            tickfont_size=10,
                            tickfont_color=chart_axis_color,
                            gridcolor=chart_grid_color,
                            showgrid=True,
                            linecolor=chart_line_color,
                            linewidth=1,
                            zerolinecolor=chart_line_color,
                        )
                        
                        fig.update_yaxes(
                            title_font_size=11,
                            title_font_color=chart_axis_color,
                            tickfont_size=10,
                            tickfont_color=chart_axis_color,
                            gridcolor=chart_grid_color,
                            showgrid=True,
                            linecolor=chart_line_color,
                            linewidth=1,
                            zerolinecolor=chart_line_color,
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)

                    # --- Veteran Backtest (embedded under this stock page) ---
                    ticker_bt = result.get('stock_code', 'N/A')
                    with st.expander("⏱️ 在此股票下跑 Veteran 回測（不離開頁面）", expanded=False):
                        if _bt is None:
                            st.warning("回測引擎暫不可用（缺少 `backtest_options.py` 依賴或載入失敗）。")
                        else:
                            bt_period = st.selectbox(
                                "Period",
                                ["3mo", "6mo", "1y", "2y", "5y", "10y", "max"],
                                index=2,
                                key=f"vet_period_{ticker_bt}",
                            )
                            use_smart_exit = st.checkbox(
                                "Smart exit (trail + profit take)",
                                value=True,
                                key=f"vet_smart_{ticker_bt}",
                            )
                            bt_strategy = st.radio(
                                "選擇回測策略 (Preset)",
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
                                key=f"vet_strategy_{ticker_bt}",
                            )
                            vet_show_manual = bt_strategy == "🛠️ 手動自訂參數 (Manual Setup)"
                            vet_opts = ["Off", ">", "<", ">=", "<="]

                            with st.expander("⚙️ Manual entry criteria", expanded=vet_show_manual):
                                st.caption("Only used when Manual Setup is selected.")
                                with st.container(border=True):
                                    st.caption("Trend & Price")
                                    vc1, vc2, vc3, vc4 = st.columns(4)
                                    with vc1:
                                        vet_close_vs_sma20 = st.selectbox("Close vs SMA20", vet_opts, index=0, key=f"vet_close_sma20_{ticker_bt}")
                                    with vc2:
                                        vet_close_vs_sma50 = st.selectbox("Close vs SMA(50)", vet_opts, index=0, key=f"vet_close_sma50_{ticker_bt}")
                                    with vc3:
                                        vet_close_vs_vwap = st.selectbox("Close vs VWAP (20d)", vet_opts, index=0, key=f"vet_close_vwap_{ticker_bt}")
                                    with vc4:
                                        vet_rs_20d_op = st.selectbox("RS(20d) operator", vet_opts, index=0, key=f"vet_rs20_op_{ticker_bt}")
                                    vcp1, _, _, _ = st.columns(4)
                                    with vcp1:
                                        vet_rs_20d_value = st.number_input("RS(20d) %", min_value=-50.0, max_value=50.0, value=0.0, step=0.5, format="%.1f", key=f"vet_rs20_val_{ticker_bt}")

                                    st.caption("Momentum")
                                    vr1, vr2, vm1, vm2 = st.columns(4)
                                    with vr1:
                                        vet_rsi_op = st.selectbox("RSI operator", vet_opts, index=0, key=f"vet_rsi_op_{ticker_bt}")
                                    with vr2:
                                        vet_rsi_value = st.number_input("RSI value", min_value=0, max_value=100, value=50, step=1, key=f"vet_rsi_val_{ticker_bt}")
                                    with vm1:
                                        vet_mfi_op = st.selectbox("MFI operator", vet_opts, index=0, key=f"vet_mfi_op_{ticker_bt}")
                                    with vm2:
                                        vet_mfi_value = st.number_input("MFI value", min_value=0, max_value=100, value=55, step=1, key=f"vet_mfi_val_{ticker_bt}")
                                    vmc1, vmc2, _, _ = st.columns(4)
                                    with vmc1:
                                        vet_macd_sign = st.selectbox("MACD now", ["Off", "Positive", "Negative"], index=0, key=f"vet_macd_sign_{ticker_bt}")
                                    with vmc2:
                                        vet_macd_trend = st.selectbox(
                                            "MACD vs yesterday",
                                            ["Off", "Higher", "Lower", "Turn Green (Cross Up)"],
                                            index=0,
                                            key=f"vet_macd_trend_{ticker_bt}",
                                        )

                                    st.caption("Volume & DMI")
                                    vv1, vv2, vo1, vo2 = st.columns(4)
                                    with vv1:
                                        vet_rvol_op = st.selectbox("RVOL operator", vet_opts, index=0, key=f"vet_rvol_op_{ticker_bt}")
                                    with vv2:
                                        vet_rvol_value = st.number_input("RVOL value", min_value=0.0, max_value=10.0, value=1.0, step=0.1, format="%.1f", key=f"vet_rvol_val_{ticker_bt}")
                                    with vo1:
                                        vet_obv_ema_op = st.selectbox("OBV (20) operator", vet_opts, index=0, key=f"vet_obv20_op_{ticker_bt}")
                                    with vo2:
                                        vet_obv_5ma_op = st.selectbox("OBV (5) operator", vet_opts, index=0, key=f"vet_obv5_op_{ticker_bt}")
                                    va1, va2, vadx1, vadx2 = st.columns(4)
                                    with va1:
                                        vet_adx_slope_op = st.selectbox("ADX slope operator", vet_opts, index=0, key=f"vet_adx_slope_op_{ticker_bt}")
                                    with va2:
                                        vet_adx_up = st.checkbox("ADX goes up", value=True, key=f"vet_adx_up_{ticker_bt}")
                                    with vadx1:
                                        vet_adx_op = st.selectbox("ADX operator", vet_opts, index=0, key=f"vet_adx_op_{ticker_bt}")
                                    with vadx2:
                                        vet_adx_value = st.number_input("ADX value", min_value=0, max_value=100, value=25, step=1, key=f"vet_adx_val_{ticker_bt}")
                                    vg1, vg2, vk1, vk2 = st.columns(4)
                                    with vg1:
                                        vet_gap_op = st.selectbox("DMI gap operator (PDI-MDI)", vet_opts, index=0, key=f"vet_gap_op_{ticker_bt}")
                                    with vg2:
                                        vet_gap_value = st.number_input("Gap value", min_value=-50.0, max_value=50.0, value=10.0, step=0.5, format="%.1f", key=f"vet_gap_val_{ticker_bt}")
                                    with vk1:
                                        vet_stoch_k_op = st.selectbox("Stoch %K operator", vet_opts, index=0, key=f"vet_stoch_op_{ticker_bt}")
                                    with vk2:
                                        vet_stoch_k_value = st.number_input("Stoch %K value", min_value=0.0, max_value=100.0, value=80.0, step=1.0, format="%.0f", key=f"vet_stoch_val_{ticker_bt}")

                            with st.expander("📉 平倉規則 (SELL Rules)", expanded=True):
                                st.caption("與 Scanner 回測一致：預設策略只決定進場，離場由下列選項控制。")
                                vse1, vse2, vse3, vse4 = st.columns(4)
                                with vse1:
                                    vet_sell_adx_exh = st.checkbox(
                                        "ADX goes down", value=False, key=f"vet_sell_adx_{ticker_bt}"
                                    )
                                    vet_sell_stop = st.checkbox(
                                        "Use stop loss %", value=True, key=f"vet_sell_stop_{ticker_bt}"
                                    )
                                with vse2:
                                    vet_sell_sma20 = st.checkbox(
                                        "Close < SMA20", value=False, key=f"vet_sell_sma20_{ticker_bt}"
                                    )
                                    vet_sell_trail = st.checkbox(
                                        "Use ATR trailing stop", value=True, key=f"vet_sell_trail_{ticker_bt}"
                                    )
                                with vse3:
                                    vet_sell_pdi_mdi = st.checkbox(
                                        "PDI < MDI", value=False, key=f"vet_sell_pdi_{ticker_bt}"
                                    )
                                    vet_sell_pt = st.checkbox(
                                        "RSI climax partial sell", value=True, key=f"vet_sell_pt_{ticker_bt}"
                                    )
                                with vse4:
                                    vet_sell_me = st.checkbox(
                                        "Force close month-end", value=False, key=f"vet_sell_me_{ticker_bt}"
                                    )
                                st.caption("Thresholds")
                                vse3, vse4, vse5 = st.columns(3)
                                with vse3:
                                    vet_sl_pct = (
                                        st.number_input(
                                            "Stop loss %",
                                            min_value=1,
                                            max_value=20,
                                            value=8,
                                            step=1,
                                            key=f"vet_sl_pct_{ticker_bt}",
                                        )
                                        / 100.0
                                    )
                                with vse4:
                                    vet_atr_mult = st.number_input(
                                        "Trailing stop (× ATR)",
                                        min_value=1.0,
                                        max_value=6.0,
                                        value=3.0,
                                        step=0.5,
                                        format="%.1f",
                                        key=f"vet_atr_{ticker_bt}",
                                    )
                                with vse5:
                                    vet_rsi_pt = st.number_input(
                                        "Profit take when RSI >",
                                        min_value=65,
                                        max_value=85,
                                        value=75,
                                        step=1,
                                        key=f"vet_rsi_pt_{ticker_bt}",
                                    )

                            def _op(x):
                                return "off" if x == "Off" else x

                            def _mfi_vs_rsi(x):
                                return "off" if x == "Off" else ("mfi>rsi" if x == "MFI > RSI" else "rsi>mfi")

                            def _adx_ui_to_range(op_label, value):
                                _op_val = str(op_label).strip() if op_label is not None else "Off"
                                _v = int(value)
                                if _op_val in (">", ">="):
                                    return _v, 100
                                if _op_val in ("<", "<="):
                                    return 0, _v
                                return 0, 100

                            def _apply_preset(preset_name: str):
                                # Entry presets only — SELL rules from UI (same as scanner_streamlit Backtest)
                                _bt.ENTRY_USE_MACD_CROSSOVER = False
                                _bt.MACD_HIST_MIN = 0.0
                                _bt.MACD_HIST_PREV_MAX = 0.0
                                _bt.ENTRY_USE_REVERSAL_BREAKOUT = False

                                if preset_name == "🔥 1. 推土機起步 (Trend Confirmation)":
                                    _bt.CLOSE_VS_SMA20 = ">"
                                    _bt.CLOSE_VS_SMA50 = "off"
                                    _bt.OBV_VS_OBV_EMA20 = "off"
                                    _bt.OBV_VS_OBV_5MA = "off"
                                    _bt.CLOSE_VS_VWAP = ">="
                                    _bt.MFI_VS_RSI = "mfi>rsi"
                                    _bt.RSI_OP = ">="
                                    _bt.RSI_VALUE = 50.0
                                    _bt.RS_20D_OP = "off"
                                    _bt.RS_20D_VALUE = 0.0
                                    _bt.MFI_OP = ">="
                                    _bt.MFI_VALUE = 50.0
                                    _bt.RVOL_OP = ">="
                                    _bt.RVOL_VALUE = 1.2
                                    _bt.ADX_SLOPE_OP = ">"
                                    _bt.GAP_OP = ">="
                                    _bt.GAP_VALUE = 5.0
                                    _bt.STOCH_K_OP = "<="
                                    _bt.STOCH_K_VALUE = 80.0
                                    _bt.SPREAD_OP = ">="
                                    _bt.SPREAD_VALUE = 0.0
                                    _bt.CORE_REQUIRE_PDI_MDI = True
                                    _bt.PDI_BUFFER = 0.0
                                    _bt.ADX_MIN = 25
                                    _bt.ADX_MAX = 60
                                    _bt.CORE_REQUIRE_ADX_AWAKENING = True

                                elif preset_name == "🩸 2. 地牢撈底 (Capitulation Bottom)":
                                    _bt.CLOSE_VS_SMA20 = "<="
                                    _bt.CLOSE_VS_SMA50 = "off"
                                    _bt.OBV_VS_OBV_EMA20 = "off"
                                    _bt.OBV_VS_OBV_5MA = "off"
                                    _bt.CLOSE_VS_VWAP = "<="
                                    _bt.MFI_VS_RSI = "rsi>mfi"
                                    _bt.RSI_OP = "<="
                                    _bt.RSI_VALUE = 35.0
                                    _bt.RS_20D_OP = "off"
                                    _bt.RS_20D_VALUE = 0.0
                                    _bt.MFI_OP = "<="
                                    _bt.MFI_VALUE = 25.0
                                    _bt.RVOL_OP = ">="
                                    _bt.RVOL_VALUE = 1.5
                                    _bt.ADX_SLOPE_OP = "off"
                                    _bt.GAP_OP = "off"
                                    _bt.GAP_VALUE = 0.0
                                    _bt.STOCH_K_OP = "<="
                                    _bt.STOCH_K_VALUE = 30.0
                                    _bt.SPREAD_OP = "<="
                                    _bt.SPREAD_VALUE = -5.0
                                    _bt.CORE_REQUIRE_PDI_MDI = False
                                    _bt.PDI_BUFFER = -10.0
                                    _bt.ADX_MIN = 10
                                    _bt.ADX_MAX = 35
                                    _bt.CORE_REQUIRE_ADX_AWAKENING = False

                                elif preset_name == "♻️ 3. 良性回抽 (Healthy Pullback)":
                                    _bt.CLOSE_VS_SMA20 = ">="
                                    _bt.CLOSE_VS_SMA50 = "off"
                                    _bt.OBV_VS_OBV_EMA20 = "off"
                                    _bt.OBV_VS_OBV_5MA = "off"
                                    _bt.CLOSE_VS_VWAP = ">="
                                    _bt.MFI_VS_RSI = "off"
                                    _bt.RSI_OP = ">="
                                    _bt.RSI_VALUE = 45.0
                                    _bt.RS_20D_OP = ">="
                                    _bt.RS_20D_VALUE = 0.0
                                    _bt.MFI_OP = ">="
                                    _bt.MFI_VALUE = 45.0
                                    _bt.RVOL_OP = "<="
                                    _bt.RVOL_VALUE = 1.2
                                    _bt.ADX_SLOPE_OP = ">"
                                    _bt.GAP_OP = ">="
                                    _bt.GAP_VALUE = 3.0
                                    _bt.STOCH_K_OP = "<="
                                    _bt.STOCH_K_VALUE = 80.0
                                    _bt.SPREAD_OP = ">="
                                    _bt.SPREAD_VALUE = 0.0
                                    _bt.CORE_REQUIRE_PDI_MDI = True
                                    _bt.PDI_BUFFER = 0.0
                                    _bt.ADX_MIN = 20
                                    _bt.ADX_MAX = 50
                                    _bt.CORE_REQUIRE_ADX_AWAKENING = True

                                elif preset_name == "🚀 4. RS破位領頭羊 (RS Breakout)":
                                    _bt.CLOSE_VS_SMA20 = ">"
                                    _bt.CLOSE_VS_SMA50 = "off"
                                    _bt.OBV_VS_OBV_EMA20 = "off"
                                    _bt.OBV_VS_OBV_5MA = "off"
                                    _bt.CLOSE_VS_VWAP = ">="
                                    _bt.MFI_VS_RSI = "mfi>rsi"
                                    _bt.RSI_OP = ">="
                                    _bt.RSI_VALUE = 55.0
                                    _bt.RS_20D_OP = ">="
                                    _bt.RS_20D_VALUE = 5.0
                                    _bt.MFI_OP = ">="
                                    _bt.MFI_VALUE = 55.0
                                    _bt.RVOL_OP = ">="
                                    _bt.RVOL_VALUE = 1.3
                                    _bt.ADX_SLOPE_OP = ">"
                                    _bt.GAP_OP = ">="
                                    _bt.GAP_VALUE = 5.0
                                    _bt.STOCH_K_OP = ">="
                                    _bt.STOCH_K_VALUE = 70.0
                                    _bt.SPREAD_OP = ">="
                                    _bt.SPREAD_VALUE = 0.0
                                    _bt.CORE_REQUIRE_PDI_MDI = True
                                    _bt.PDI_BUFFER = 0.0
                                    _bt.ADX_MIN = 25
                                    _bt.ADX_MAX = 70
                                    _bt.CORE_REQUIRE_ADX_AWAKENING = True

                                elif preset_name == "📈 5. MACD 動能爆發 (MACD Expansion)":
                                    _bt.ENTRY_USE_MACD_CROSSOVER = True
                                    _bt.MACD_HIST_MIN = 0.0
                                    _bt.MACD_HIST_PREV_MAX = 0.0
                                    _bt.RVOL_OP = ">="
                                    _bt.RVOL_VALUE = 1.0

                                elif preset_name == "🌊 6. 絕地反擊 (Reversal Breakout)":
                                    _bt.ENTRY_USE_REVERSAL_BREAKOUT = True
                                    _bt.REVERSAL_RSI_MIN = 40.0
                                    _bt.REVERSAL_RVOL_MIN = 1.2

                            if st.button("Run Veteran Backtest", key=f"vet_run_{ticker_bt}", type="primary", use_container_width=True):
                                if bt_strategy == "🛠️ 手動自訂參數 (Manual Setup)":
                                    _bt.CLOSE_VS_SMA20 = _op(vet_close_vs_sma20)
                                    _bt.CLOSE_VS_SMA50 = _op(vet_close_vs_sma50)
                                    _bt.OBV_VS_OBV_EMA20 = _op(vet_obv_ema_op)
                                    _bt.OBV_VS_OBV_5MA = _op(vet_obv_5ma_op)
                                    _bt.CLOSE_VS_VWAP = _op(vet_close_vs_vwap)
                                    _bt.MFI_VS_RSI = "off"
                                    _bt.RSI_OP = _op(vet_rsi_op)
                                    _bt.RSI_VALUE = float(vet_rsi_value)
                                    _bt.RS_20D_OP = _op(vet_rs_20d_op)
                                    _bt.RS_20D_VALUE = float(vet_rs_20d_value)
                                    _bt.MFI_OP = _op(vet_mfi_op)
                                    _bt.MFI_VALUE = float(vet_mfi_value)
                                    _bt.RVOL_OP = _op(vet_rvol_op)
                                    _bt.RVOL_VALUE = float(vet_rvol_value)
                                    _bt.ADX_SLOPE_OP = _op(vet_adx_slope_op)
                                    _bt.GAP_OP = _op(vet_gap_op)
                                    _bt.GAP_VALUE = float(vet_gap_value)
                                    _bt.STOCH_K_OP = _op(vet_stoch_k_op)
                                    _bt.STOCH_K_VALUE = float(vet_stoch_k_value)
                                    _bt.CORE_REQUIRE_PDI_MDI = False
                                    _bt.PDI_BUFFER = 0.0
                                    _adx_min, _adx_max = _adx_ui_to_range(vet_adx_op, vet_adx_value)
                                    _bt.ADX_MIN = int(_adx_min)
                                    _bt.ADX_MAX = int(_adx_max)
                                    _bt.CORE_REQUIRE_ADX_AWAKENING = bool(vet_adx_up)
                                    macd_enabled = (vet_macd_sign != "Off") or (vet_macd_trend != "Off")
                                    _bt.ENTRY_USE_MACD_CROSSOVER = macd_enabled
                                    if vet_macd_sign == "Positive":
                                        _bt.MACD_HIST_MIN = 0.0
                                        _bt.MACD_HIST_PREV_MAX = 1e9
                                    elif vet_macd_sign == "Negative":
                                        _bt.MACD_HIST_MIN = -1e9
                                        _bt.MACD_HIST_PREV_MAX = -0.000001
                                    else:
                                        _bt.MACD_HIST_MIN = -1e9
                                        _bt.MACD_HIST_PREV_MAX = 1e9
                                    if vet_macd_trend == "Higher":
                                        _bt.MACD_HIST_PREV_MAX = min(_bt.MACD_HIST_PREV_MAX, 0.0)
                                    elif vet_macd_trend == "Lower":
                                        _bt.MACD_HIST_MIN = max(_bt.MACD_HIST_MIN, 0.0)
                                    elif vet_macd_trend == "Turn Green (Cross Up)":
                                        # Strict "turn green": previous histogram negative, current positive.
                                        _bt.MACD_HIST_MIN = 0.000001
                                        _bt.MACD_HIST_PREV_MAX = -0.000001
                                        _bt.ENTRY_USE_MACD_CROSSOVER = True
                                    _bt.ENTRY_USE_REVERSAL_BREAKOUT = False
                                else:
                                    _apply_preset(bt_strategy)
                                _bt.SELL_USE_ADX_EXHAUSTION = vet_sell_adx_exh
                                _bt.SELL_USE_SMA20 = vet_sell_sma20
                                _bt.SELL_USE_PDI_MDI = vet_sell_pdi_mdi
                                _bt.SELL_USE_STOP_LOSS = vet_sell_stop
                                _bt.SELL_USE_TRAILING = vet_sell_trail
                                _bt.SELL_USE_PROFIT_TAKE = vet_sell_pt
                                _bt.SELL_USE_MONTH_END = vet_sell_me
                                _bt.STOP_LOSS_PCT = vet_sl_pct
                                _bt.ATR_TRAIL_MULT = vet_atr_mult
                                _bt.RSI_PROFIT_TAKING = vet_rsi_pt
                                with st.spinner(f"Running Veteran backtest for {ticker_bt}..."):
                                    try:
                                        df_bt = fetch_data_yfinance(ticker_bt, period=bt_period)
                                        df_bt = add_indicators(df_bt, symbol=ticker_bt)
                                        required = ["SMA20", "RSI14", "ADX", "ADX_prev", "ADX_prev2", "PDI", "MDI", "MFI14", "RVOL", "Spread", "ATR14"]
                                        if _bt.ENTRY_USE_MACD_CROSSOVER or _bt.ENTRY_USE_REVERSAL_BREAKOUT:
                                            required = required + ["MACD_Hist", "MACD_Hist_Prev"]
                                        valid_bt = df_bt.dropna(subset=required)
                                        if len(valid_bt) < 10:
                                            st.warning(f"Not enough valid bars after warm-up ({len(valid_bt)}).")
                                        else:
                                            trades = run_veteran_backtest(valid_bt, verbose=False, use_smart_exit=use_smart_exit)
                                            if not trades:
                                                st.warning("Verdict: No trades triggered for this ticker in this period.")
                                            else:
                                                tdf = pd.DataFrame(trades)
                                                wins = tdf[tdf["Result"] == "WIN"] if "Result" in tdf.columns else pd.DataFrame()
                                                losses = tdf[tdf["Result"] == "LOSS"] if "Result" in tdf.columns else pd.DataFrame()
                                                n = len(tdf)
                                                total_pnl = tdf["PnL"].sum() if "PnL" in tdf.columns else 0.0
                                                total_cost = tdf["Cost"].sum() if "Cost" in tdf.columns else 0.0
                                                total_proceeds = tdf["Proceeds"].sum() if "Proceeds" in tdf.columns else 0.0
                                                overall_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost else 0.0
                                                win_rate = (len(wins) / n * 100.0) if n else 0.0
                                                avg_win = wins["PnL%"].mean() if len(wins) > 0 and "PnL%" in wins.columns else 0.0
                                                avg_loss = losses["PnL%"].mean() if len(losses) > 0 and "PnL%" in losses.columns else 0.0

                                                st.success(
                                                    f"✅ {ticker_bt}: {n} trades | Win rate {win_rate:.1f}% | Total P&L HK$ {total_pnl:+.2f} | Return {overall_pnl_pct:+.1f}%"
                                                )

                                                c1, c2, c3, c4, c5 = st.columns(5)
                                                c1.metric("💰 Total P&L (HK$)", f"{total_pnl:+.2f}")
                                                c2.metric("📈 Overall Return %", f"{overall_pnl_pct:+.1f}%")
                                                c3.metric("💵 Total Cost", f"HK$ {total_cost:,.0f}")
                                                c4.metric("💵 Total Proceeds", f"HK$ {total_proceeds:,.0f}")
                                                c5.metric("🏆 Wins / Losses", f"{len(wins)} / {len(losses)}")
                                                _vet_log = [
                                                    "Entry_Date", "Entry_Price", "Entry_Reason",
                                                    "E_ADX", "E_ADX_Slope", "E_PDI", "E_MDI", "E_RSI", "E_MFI", "E_RVOL",
                                                    "E_MACD_Line", "E_MACD_Signal", "E_MACD_Hist", "E_MACD_Hist_Prev",
                                                    "E_RS_20d", "E_Spread", "E_SMA_50", "E_OBV", "E_OBV_EMA_20", "E_VWAP",
                                                    "Exit_Date", "Exit_Price", "Exit_Reason", "Hold_Days", "PnL", "PnL%", "Result",
                                                ]
                                                _vet_log = [c for c in _vet_log if c in tdf.columns]
                                                st.dataframe(tdf[_vet_log], use_container_width=True, hide_index=True)
                                    except Exception as e:
                                        st.error(f"Backtest failed: {e}")

                    # Copy Report to AI — right under the graph (HK time in report)
                    signal = result.get('signal', {})
                    details = signal.get('details', {}) if signal else {}
                    ticker = result.get('stock_code', 'N/A')
                    if ticker not in st.session_state.stock_chats:
                        st.session_state.stock_chats[ticker] = []
                    stock_name = result.get('stock_name', 'N/A')
                    current_price_val = result.get('current_price', 0)
                    price_change_val = result.get('price_change')
                    price_change_pct = result.get('price_change_percent')
                    if price_change_val is not None and price_change_pct is not None:
                        change_str = f"+{price_change_val:.2f} (+{price_change_pct:.2f}%)" if price_change_val > 0 else f"{price_change_val:.2f} ({price_change_pct:.2f}%)"
                    else:
                        change_str = "N/A"
                    fundamental_status = result.get('fundamental_status') or {}
                    extended_data = result.get('extended_fundamental_data') or {}
                    rsi_val = details.get('rsi', 0)
                    adx_val = details.get('adx', 0)
                    adx_slope_val = details.get('adx_slope', 0)
                    pdi_val = details.get('dmi_plus', 0)
                    mdi_val = details.get('dmi_minus', 0)
                    pdi_mdi_gap = abs(pdi_val - mdi_val)
                    atr_val = details.get('atr', 0)
                    bb_upper_val = details.get('bb_upper', 0)
                    bb_lower_val = details.get('bb_lower', 0)
                    bb_middle_val = details.get('bb_middle', 0)
                    mfi_val = details.get('mfi', 0)
                    rvol_val = details.get('rvol', 0)
                    
                    # =========================================================
                    # Quant Trade Plan (Risk-Reward 1:3) — ATR-based
                    # =========================================================
                    # Treat BB middle (bb_middle) as SMA20 structural reference.
                    # Note: This is a technical planning aid, not a guarantee.
                    current_price = float(current_price_val) if current_price_val not in (None, "", 0) else None
                    atr_value = float(atr_val) if atr_val not in (None, "", 0) else None
                    sma20_val = float(bb_middle_val) if bb_middle_val not in (None, "", 0) else None
                    stop_loss = None
                    target_price_3r = None
                    risk_amount = None
                    upside_pct = None
                    if current_price is not None and atr_value is not None and atr_value > 0 and sma20_val is not None:
                        # Smart Stop Loss: 1.5x ATR below current price,
                        # but if price is above SMA20, clamp to SMA20 with a 1% buffer.
                        if current_price > sma20_val:
                            stop_loss = max(current_price - (1.5 * atr_value), sma20_val * 0.99)
                        else:
                            stop_loss = current_price - (1.5 * atr_value)

                        risk_amount = current_price - stop_loss
                        if risk_amount > 0:
                            target_price_3r = current_price + (risk_amount * 3.0)
                            upside_pct = (target_price_3r - current_price) / current_price * 100.0

                    sma_50_val = details.get('sma_50', None)
                    sma_200_val = details.get('sma_200', None)
                    trailing_pe = fundamental_status.get('trailing_pe')
                    forward_pe = fundamental_status.get('forward_pe')
                    peg_ratio = fundamental_status.get('peg_ratio')
                    debt_to_equity = fundamental_status.get('debt_to_equity')
                    profit_margins = fundamental_status.get('profit_margins')
                    market_cap = extended_data.get('market_cap', None)
                    week_52_high = extended_data.get('week_52_high', None)
                    week_52_low = extended_data.get('week_52_low', None)
                    next_earnings = extended_data.get('next_earnings', None)
                    if market_cap is not None:
                        market_cap_str = f"{market_cap/1e12:.2f}T" if market_cap >= 1e12 else f"{market_cap/1e9:.2f}B" if market_cap >= 1e9 else f"{market_cap/1e6:.2f}M" if market_cap >= 1e6 else f"{market_cap:.2f}"
                    else:
                        market_cap_str = "N/A"
                    profit_margins_str = f"{profit_margins*100:.2f}%" if profit_margins is not None else "N/A"
                    sma_200_str = f"{sma_200_val:.2f}" if sma_200_val is not None else "N/A"
                    sma_50_str = f"{sma_50_val:.2f}" if sma_50_val is not None else "N/A"
                    week_52_low_str = f"{week_52_low:.2f}" if week_52_low is not None else "N/A"
                    week_52_high_str = f"{week_52_high:.2f}" if week_52_high is not None else "N/A"
                    trailing_pe_str = f"{trailing_pe:.2f}" if trailing_pe is not None else "N/A"
                    forward_pe_str = f"{forward_pe:.2f}" if forward_pe is not None else "N/A"
                    peg_ratio_str = f"{peg_ratio:.2f}" if peg_ratio is not None else "N/A"
                    debt_to_equity_str = f"{debt_to_equity:.2f}" if debt_to_equity is not None else "N/A"
                    next_earnings_str = next_earnings if next_earnings else "N/A"
                    latest_rs_outperform = details.get('rs_20d_outperform')
                    rs_report_str = f"{latest_rs_outperform:.2f}%" if latest_rs_outperform is not None else "N/A"

                    # =========================
                    # Multi-Factor Quant Dashboard (Hero + Radar)
                    # =========================
                    latest_row = result.get('latest_row') or {}
                    factor_scores = score_factors(latest_row, details)
                    mom_score = factor_scores["momentum"]
                    trend_score = factor_scores["trend"]
                    flow_score = factor_scores["flow"]
                    location_score = factor_scores["location"]

                    # Hero Score Card + factor breakdown (single card; ticker only here)
                    hero_rating = factor_scores["rating"]
                    hero_score = factor_scores["composite"]
                    rating_color = "#10b981" if hero_rating in ("STRONG BUY", "BUY") else \
                                   "#f59e0b" if hero_rating == "HOLD" else "#ef4444"
                    st.markdown(
                        f"""
                        <div class="quant-dark-card" style="margin-top: 0.75rem; margin-bottom: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
                                    background: linear-gradient(120deg, #020617, #0f172a); color: #e5e7eb;
                                    box-shadow: 0 10px 25px rgba(15,23,42,0.55);">
                            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
                                <div>
                                    <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280;">
                                        MULTI-FACTOR QUANT MODEL
                                    </div>
                                    <div style="font-size: 1.6rem; font-weight: 700; margin-top: 0.25rem;">{html.escape(str(ticker))}</div>
                                    <div style="margin-top: 0.4rem; font-size: 0.95rem;">
                                        <span style="padding: 0.15rem 0.6rem; border-radius: 999px; background-color: rgba(15,118,110,0.15); border: 1px solid {rating_color}; color: {rating_color}; font-weight: 600;">
                                            {html.escape(str(hero_rating))}
                                        </span>
                                    </div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.12em; color: #9ca3af;">
                                        Composite Score
                                    </div>
                                    <div style="font-size: 2.4rem; font-weight: 800; color: {rating_color}; line-height: 1.1;">
                                        {hero_score:.1f}
                                    </div>
                                    <div style="font-size: 0.75rem; color: #6b7280;">Range: 0 (Weak) → 10.0 (Strong)</div>
                                </div>
                            </div>
                            <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid rgba(148,163,184,0.2);">
                                <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280; margin-bottom: 0.65rem;">
                                    FACTOR BREAKDOWN · 因子評分
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.65rem;">
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(167,139,250,0.12); border: 1px solid rgba(167,139,250,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #c4b5fd; text-transform: uppercase;">Momentum · 15%</div>
                                        <div style="font-size: 1.45rem; font-weight: 800; color: #a78bfa; margin-top: 0.2rem;">{mom_score:.1f}</div>
                                        <div style="font-size: 0.68rem; color: #94a3b8;">/ 10.0</div>
                                        <div style="font-size: 0.62rem; color: #64748b; margin-top: 0.15rem;">RSI, Stoch</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #7dd3fc; text-transform: uppercase;">Trend · 40%</div>
                                        <div style="font-size: 1.45rem; font-weight: 800; color: #38bdf8; margin-top: 0.2rem;">{trend_score:.1f}</div>
                                        <div style="font-size: 0.68rem; color: #94a3b8;">/ 10.0</div>
                                        <div style="font-size: 0.62rem; color: #64748b; margin-top: 0.15rem;">ADX, DMI Gap</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fcd34d; text-transform: uppercase;">Flow · 25%</div>
                                        <div style="font-size: 1.45rem; font-weight: 800; color: #fbbf24; margin-top: 0.2rem;">{flow_score:.1f}</div>
                                        <div style="font-size: 0.68rem; color: #94a3b8;">/ 10.0</div>
                                        <div style="font-size: 0.62rem; color: #64748b; margin-top: 0.15rem;">RVOL, OBV 5MA</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(52,211,153,0.12); border: 1px solid rgba(52,211,153,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #6ee7b7; text-transform: uppercase;">Location · 20%</div>
                                        <div style="font-size: 1.45rem; font-weight: 800; color: #34d399; margin-top: 0.2rem;">{location_score:.1f}</div>
                                        <div style="font-size: 0.68rem; color: #94a3b8;">/ 10.0</div>
                                        <div style="font-size: 0.62rem; color: #64748b; margin-top: 0.15rem;">BB, SMA50</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Multi-factor scores — compact horizontal bars (same accent colors as factor tiles)
                    _mf_cats = ["Momentum", "Trend", "Flow", "Location"]
                    _mf_vals = [mom_score, trend_score, flow_score, location_score]
                    _mf_colors = ["#a78bfa", "#38bdf8", "#fbbf24", "#34d399"]
                    factor_bar_fig = go.Figure()
                    factor_bar_fig.add_trace(
                        go.Bar(
                            x=_mf_vals,
                            y=_mf_cats,
                            orientation="h",
                            marker=dict(color=_mf_colors, line=dict(width=0)),
                            text=[f"{v:.1f}" for v in _mf_vals],
                            textposition="outside",
                            textfont=dict(color="#334155" if light_mode else "#e2e8f0", size=12),
                            hovertemplate="<b>%{y}</b><br>%{x:.1f} / 10<extra></extra>",
                        )
                    )
                    factor_bar_fig.update_layout(
                        title=dict(
                            text="MULTI-FACTOR SCORES · 因子分佈（條形）",
                            font=dict(size=13, color="#475569" if light_mode else "#94a3b8"),
                            x=0.02,
                            xanchor="left",
                        ),
                        paper_bgcolor="#ffffff" if light_mode else "#0f172a",
                        plot_bgcolor="#f8fafc" if light_mode else "#111827",
                        font=dict(color="#334155" if light_mode else "#A0AEC0", size=11),
                        height=245,
                        margin=dict(l=8, r=52, t=42, b=28),
                        xaxis=dict(
                            range=[0, 10.8],
                            gridcolor="#cbd5e1" if light_mode else "#334155",
                            zeroline=False,
                            showline=True,
                            linecolor="#94a3b8" if light_mode else "#475569",
                            tickfont=dict(color="#475569" if light_mode else "#94a3b8"),
                            title=dict(text="Score / 10", font=dict(size=10, color="#64748b")),
                        ),
                        yaxis=dict(
                            showgrid=False,
                            autorange="reversed",
                            tickfont=dict(color="#334155" if light_mode else "#e2e8f0", size=11),
                        ),
                        bargap=0.42,
                        showlegend=False,
                    )
                    st.plotly_chart(factor_bar_fig, use_container_width=True)

                    # Risk-Exit Radar (倉位危險雷達) — same black card style as Composite Score hero
                    risk_score_val = result.get("risk_score")
                    risk_label_val = result.get("risk_label")
                    risk_breakdown = result.get("risk_breakdown") or {}
                    tech_rr = float(risk_breakdown.get("tech_risk", 0) or 0)
                    trend_rr = float(risk_breakdown.get("trend_risk", 0) or 0)
                    flow_rr = float(risk_breakdown.get("flow_risk", 0) or 0)
                    tech_contrib = tech_rr * 0.50
                    trend_contrib = trend_rr * 0.30
                    flow_contrib = flow_rr * 0.20
                    if risk_score_val is not None and risk_label_val:
                        if risk_score_val >= 7.0:
                            risk_hex = "#f87171"
                            risk_bar = "rgba(248,113,113,0.35)"
                        elif risk_score_val >= 4.0:
                            risk_hex = "#fb923c"
                            risk_bar = "rgba(251,146,60,0.35)"
                        else:
                            risk_hex = "#4ade80"
                            risk_bar = "rgba(74,222,128,0.35)"
                        risk_pct = min(100.0, max(0.0, (risk_score_val / 10.0) * 100.0))
                        st.markdown(
                            f"""
                            <div class="quant-dark-card" style="margin-top: 0.5rem; margin-bottom: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
                                        background: linear-gradient(120deg, #020617, #0f172a); color: #e5e7eb;
                                        box-shadow: 0 10px 25px rgba(15,23,42,0.55);">
                                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
                                    <div>
                                        <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280;">
                                            RISK-EXIT RADAR · 倉位危險雷達
                                        </div>
                                        <div style="margin-top: 0.4rem; font-size: 0.95rem;">
                                            <span style="padding: 0.15rem 0.6rem; border-radius: 999px; background-color: {risk_bar}; border: 1px solid {risk_hex}; color: {risk_hex}; font-weight: 600;">
                                                {html.escape(str(risk_label_val))}
                                            </span>
                                        </div>
                                    </div>
                                    <div style="text-align: right; min-width: 140px;">
                                        <div style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.12em; color: #9ca3af;">
                                            危險指數 Risk Score
                                        </div>
                                        <div style="font-size: 2.4rem; font-weight: 800; color: {risk_hex}; line-height: 1.1;">
                                            {risk_score_val:.1f}
                                        </div>
                                        <div style="font-size: 0.75rem; color: #6b7280;">/ 10.0</div>
                                        <div style="margin-top: 0.5rem; margin-left: auto; width: 120px; max-width: 100%; height: 6px; background: rgba(51,65,85,0.9); border-radius: 999px; overflow: hidden;">
                                            <div style="width: {risk_pct:.1f}%; height: 100%; background: {risk_hex}; border-radius: 999px;"></div>
                                        </div>
                                    </div>
                                </div>
                                <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid rgba(148,163,184,0.2);">
                                    <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280; margin-bottom: 0.65rem;">
                                        RISK BREAKDOWN · 計算基礎
                                    </div>
                                    <div style="font-size: 0.68rem; color: #64748b; margin-bottom: 0.65rem; line-height: 1.45;">
                                        綜合 = 技術破位×50% + 趨勢反轉×30% + 資金撤離×20%（各層原始分 0–10，再加權）
                                    </div>
                                    <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.65rem;">
                                        <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(251,113,133,0.12); border: 1px solid rgba(251,113,133,0.45);">
                                            <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fda4af; text-transform: uppercase;">Technical · 50%</div>
                                            <div style="font-size: 0.58rem; color: #94a3b8; margin-top: 0.15rem;">技術破位</div>
                                            <div style="font-size: 1.35rem; font-weight: 800; color: #fb7185; margin-top: 0.2rem;">{tech_rr:.1f}</div>
                                            <div style="font-size: 0.65rem; color: #64748b;">/ 10.0 → 權重 {tech_contrib:.2f}</div>
                                            <div style="font-size: 0.58rem; color: #64748b; margin-top: 0.2rem; line-height: 1.35;">SMA50、布林上下軌</div>
                                        </div>
                                        <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.45);">
                                            <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fcd34d; text-transform: uppercase;">Trend · 30%</div>
                                            <div style="font-size: 0.58rem; color: #94a3b8; margin-top: 0.15rem;">趨勢反轉</div>
                                            <div style="font-size: 1.35rem; font-weight: 800; color: #fbbf24; margin-top: 0.2rem;">{trend_rr:.1f}</div>
                                            <div style="font-size: 0.65rem; color: #64748b;">/ 10.0 → 權重 {trend_contrib:.2f}</div>
                                            <div style="font-size: 0.58rem; color: #64748b; margin-top: 0.2rem; line-height: 1.35;">MDI − PDI gap</div>
                                        </div>
                                        <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(34,211,238,0.12); border: 1px solid rgba(34,211,238,0.45);">
                                            <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #67e8f9; text-transform: uppercase;">Flow · 20%</div>
                                            <div style="font-size: 0.58rem; color: #94a3b8; margin-top: 0.15rem;">資金撤離</div>
                                            <div style="font-size: 1.35rem; font-weight: 800; color: #22d3ee; margin-top: 0.2rem;">{flow_rr:.1f}</div>
                                            <div style="font-size: 0.65rem; color: #64748b;">/ 10.0 → 權重 {flow_contrib:.2f}</div>
                                            <div style="font-size: 0.58rem; color: #64748b; margin-top: 0.2rem; line-height: 1.35;">OBV vs 5MA、RVOL+陰線</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # Q&A: explain score math and interpretation for users
                    with st.expander("❓ Q&A：分數點解讀（Quant Model / Risk Radar）", expanded=False):
                        st.markdown(
                            f"""
### 1) MULTI-FACTOR QUANT MODEL 係點計？

- **Composite Score (0-10)**  
  `Trend × 40% + Flow × 25% + Location × 20% + Momentum × 15%`
- **Trend (40%)**：由 `DMI gap (PDI-MDI)` 同 `ADX + ADX slope` 平均得出。
  - gap > 20 → 10；>10 → 8；>0 → 5；<=0 → 0  
  - ADX > 30 且 slope > 0 → 10；ADX >= 20 且 slope > 0 → 7；否則 3
- **Flow (25%)**：`RVOL score` 同 `OBV > OBV_5MA` 平均。
- **Location (20%)**：睇價位對 `布林中線/上軌` 同 `SMA50` 的位置（越接近中線、結構越穩分數越高）。
- **Momentum (15%)**：主要睇 `RSI + Stoch`（過熱會扣分）。
- **額外保護/修正**：
  - 跌勢刀（gap < -10）會硬扣分；
  - 若出現 `low-volume test / 200天線鐵底 / MACD 改善`，會有防誤殺保底機制。

**你而家呢隻股票（即時）**
- Momentum: **{mom_score:.1f}/10**
- Trend: **{trend_score:.1f}/10**
- Flow: **{flow_score:.1f}/10**
- Location: **{location_score:.1f}/10**
- Composite: **{hero_score:.1f}/10** → **{hero_rating}**

**評級區間**
- `>= 8.0`: STRONG BUY
- `>= 6.0`: BUY
- `>= 4.0`: HOLD
- `>= 2.0`: SELL
- `< 2.0`: STRONG SELL

---

### 2) RISK-EXIT RADAR（倉位危險雷達）係點計？

- **Risk Score (0-10)**  
  `Technical Break × 50% + Trend Reversal × 30% + Capital Flight × 20%`

- **Technical Break (50%)**
  - 價格低過 `SMA50 * 0.99`：+5
  - 價格跌穿布林下軌：+5  
    （若只係低過中軌：+2）

- **Trend Reversal (30%)**
  - `MDI - PDI > 15`：10
  - `MDI - PDI > 0`：6
  - 否則：0

- **Capital Flight (20%)**
  - `OBV < OBV_5MA` 連續 3 日：+4
  - 當日陰線且 `RVOL > 1.5`：+6

**你而家呢隻股票（即時）**
- Technical: **{tech_rr:.1f}/10**（加權 {tech_contrib:.2f}）
- Trend: **{trend_rr:.1f}/10**（加權 {trend_contrib:.2f}）
- Flow: **{flow_rr:.1f}/10**（加權 {flow_contrib:.2f}）
- Risk Score: **{(risk_score_val if risk_score_val is not None else 0.0):.1f}/10** → **{(risk_label_val or 'N/A')}**

**Risk 狀態區間**
- `>= 7.0`：🚨 CRITICAL（要嚴格止蝕）
- `>= 4.0`：⚠️ WARNING（趨勢鬆動，減倉/對沖）
- `< 4.0`：✅ SAFE（結構相對穩健）
"""
                        )

                    # Trade Plan UI: Risk-Reward 1:3 — per-metric tinted tiles (distinct colors)
                    if stop_loss is not None and target_price_3r is not None and risk_amount is not None and upside_pct is not None:
                        upside_tile_bg = "rgba(245,158,11,0.14)" if upside_pct > 25.0 else "rgba(99,102,241,0.14)"
                        upside_tile_border = "rgba(245,158,11,0.5)" if upside_pct > 25.0 else "rgba(129,140,248,0.5)"
                        upside_lbl = "#fcd34d" if upside_pct > 25.0 else "#a5b4fc"
                        upside_val = "#fbbf24" if upside_pct > 25.0 else "#818cf8"
                        st.markdown(
                            f"""
                            <div class="quant-dark-card" style="margin-top: 0.5rem; margin-bottom: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
                                        background: linear-gradient(120deg, #020617, #0f172a); color: #e5e7eb;
                                        box-shadow: 0 10px 25px rgba(15,23,42,0.55);">
                                <div style="margin-bottom: 0.75rem;">
                                    <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280;">
                                        RISK-REWARD 1:3 · 大佬級值博率計算
                                    </div>
                                    <div style="font-size: 0.72rem; color: #94a3b8; margin-top: 0.35rem; line-height: 1.45;">
                                        專業交易不求必勝，只求「輸一博三」。以下為系統按波動率 (ATR) 計算之量化參考。
                                    </div>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.65rem;">
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(248,113,113,0.14); border: 1px solid rgba(248,113,113,0.5);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fca5a5; text-transform: uppercase;">止蝕 Stop</div>
                                        <div style="font-size: 1.35rem; font-weight: 800; color: #f87171; margin-top: 0.2rem;">${stop_loss:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(251,146,60,0.14); border: 1px solid rgba(251,146,60,0.5);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fdba74; text-transform: uppercase;">1R 風險</div>
                                        <div style="font-size: 1.35rem; font-weight: 800; color: #fb923c; margin-top: 0.2rem;">-${risk_amount:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(74,222,128,0.14); border: 1px solid rgba(74,222,128,0.5);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #86efac; text-transform: uppercase;">1:3 目標 Target</div>
                                        <div style="font-size: 1.35rem; font-weight: 800; color: #4ade80; margin-top: 0.2rem;">${target_price_3r:.2f}</div>
                                    </div>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.65rem; margin-top: 0.65rem;">
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: rgba(45,212,191,0.14); border: 1px solid rgba(45,212,191,0.5);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #5eead4; text-transform: uppercase;">3R 潛在利潤</div>
                                        <div style="font-size: 1.35rem; font-weight: 800; color: #2dd4bf; margin-top: 0.2rem;">+${(risk_amount * 3):.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.55rem 0.35rem; border-radius: 10px; background: {upside_tile_bg}; border: 1px solid {upside_tile_border};">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: {upside_lbl}; text-transform: uppercase;">需要升幅</div>
                                        <div style="font-size: 1.35rem; font-weight: 800; color: {upside_val}; margin-top: 0.2rem;">{upside_pct:.1f}%</div>
                                    </div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if upside_pct > 25.0:
                            st.warning("⚠️ 注意：1賠3 目標需要極大升幅，代表目前止蝕位太遠（值博率低）。建議等待回調，縮細止蝕距離。")

                    # Key data — black card + 3×3 metric tiles + in-card signal pill
                    if details:
                        rsi_val = details.get('rsi', 0)
                        adx_val = details.get('adx', 0)
                        adx_slope_val = details.get('adx_slope', 0)
                        pdi_val = details.get('dmi_plus', 0)
                        mdi_val = details.get('dmi_minus', 0)
                        atr_val = details.get('atr', 0)
                        mfi_val = details.get('mfi', 0)
                        rvol_val = details.get('rvol', 0)
                        latest_rs_outperform = details.get('rs_20d_outperform')
                        rs_line = f"{latest_rs_outperform:.2f}%" if latest_rs_outperform is not None else "N/A"
                        macd_l = details.get("macd_line")
                        macd_s = details.get("macd_signal")
                        macd_h = details.get("macd_hist")
                        macd_hp = details.get("macd_hist_prev")
                        macd_l_s = f"{float(macd_l):.4f}" if macd_l is not None else "N/A"
                        macd_s_s = f"{float(macd_s):.4f}" if macd_s is not None else "N/A"
                        macd_h_s = f"{float(macd_h):.4f}" if macd_h is not None else "N/A"
                        macd_hp_s = f"{float(macd_hp):.4f}" if macd_hp is not None else "N/A"
                        sig_html = ""
                        if signal:
                            advice_text = signal.get('advice', '無訊號')
                            signal_type = signal.get('signal_type', 'wait')
                            if signal_type == 'buy':
                                sb, sc, stxt = "rgba(16,185,129,0.2)", "#34d399", "#a7f3d0"
                            elif signal_type == 'sell':
                                sb, sc, stxt = "rgba(239,68,68,0.2)", "#f87171", "#fecaca"
                            elif signal_type == 'error':
                                sb, sc, stxt = "rgba(220,38,38,0.25)", "#ef4444", "#fecaca"
                            else:
                                sb, sc, stxt = "rgba(245,158,11,0.2)", "#fbbf24", "#fde68a"
                            # Single-line HTML: leading spaces in markdown become "code blocks" and render as raw text
                            sig_html = (
                                f'<div style="margin-top: 0.85rem; padding-top: 0.75rem; border-top: 1px solid rgba(148,163,184,0.2);">'
                                f'<div style="display: inline-flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; '
                                f'padding: 0.4rem 0.85rem; border-radius: 999px; background: {sb}; border: 1px solid {sc}; '
                                f'color: {stxt}; font-size: 0.8125rem; font-weight: 600;">'
                                f'<span style="color: #e5e7eb;">交易訊號</span><span>·</span>'
                                f'<span>{html.escape(str(advice_text))}</span></div></div>'
                            )
                        st.markdown(
                            f"""
                            <div class="quant-dark-card" style="margin-top: 0.25rem; margin-bottom: 1rem; padding: 1rem 1.25rem; border-radius: 12px;
                                        background: linear-gradient(120deg, #020617, #0f172a); color: #e5e7eb;
                                        box-shadow: 0 10px 25px rgba(15,23,42,0.55);">
                                <div style="margin-bottom: 0.85rem;">
                                    <div style="font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280;">
                                        KEY DATA · 關鍵數據
                                    </div>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.65rem;">
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(244,114,182,0.12); border: 1px solid rgba(244,114,182,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #f9a8d4; text-transform: uppercase;">RSI</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #f472b6; margin-top: 0.15rem;">{rsi_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(167,139,250,0.12); border: 1px solid rgba(167,139,250,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #c4b5fd; text-transform: uppercase;">MFI</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #a78bfa; margin-top: 0.15rem;">{mfi_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(56,189,248,0.12); border: 1px solid rgba(56,189,248,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #7dd3fc; text-transform: uppercase;">ADX</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #38bdf8; margin-top: 0.15rem;">{adx_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(34,211,238,0.12); border: 1px solid rgba(34,211,238,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #67e8f9; text-transform: uppercase;">ADX slope</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #22d3ee; margin-top: 0.15rem;">{adx_slope_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(74,222,128,0.12); border: 1px solid rgba(74,222,128,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #86efac; text-transform: uppercase;">PDI</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #4ade80; margin-top: 0.15rem;">{pdi_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(251,113,133,0.12); border: 1px solid rgba(251,113,133,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fda4af; text-transform: uppercase;">MDI</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #fb7185; margin-top: 0.15rem;">{mdi_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fcd34d; text-transform: uppercase;">ATR</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #fbbf24; margin-top: 0.15rem;">{atr_val:.2f}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(249,115,22,0.12); border: 1px solid rgba(249,115,22,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #fdba74; text-transform: uppercase;">RVOL</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #fb923c; margin-top: 0.15rem;">{rvol_val:.2f}x</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(45,212,191,0.12); border: 1px solid rgba(45,212,191,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #5eead4; text-transform: uppercase;">RS 20d</div>
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #2dd4bf; margin-top: 0.15rem;">{html.escape(str(rs_line))}</div>
                                    </div>
                                </div>
                                <div style="margin-top: 0.75rem; font-size: 0.72rem; letter-spacing: 0.06em; color: #94a3b8; text-transform: uppercase;">MACD (12,26,9)</div>
                                <div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.65rem; margin-top: 0.35rem;">
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(129,140,248,0.12); border: 1px solid rgba(129,140,248,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #a5b4fc; text-transform: uppercase;">MACD Line</div>
                                        <div style="font-size: 1.1rem; font-weight: 800; color: #818cf8; margin-top: 0.15rem;">{html.escape(str(macd_l_s))}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(147,197,253,0.12); border: 1px solid rgba(147,197,253,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #93c5fd; text-transform: uppercase;">Signal</div>
                                        <div style="font-size: 1.1rem; font-weight: 800; color: #60a5fa; margin-top: 0.15rem;">{html.escape(str(macd_s_s))}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(196,181,253,0.12); border: 1px solid rgba(196,181,253,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #c4b5fd; text-transform: uppercase;">Hist</div>
                                        <div style="font-size: 1.1rem; font-weight: 800; color: #a78bfa; margin-top: 0.15rem;">{html.escape(str(macd_h_s))}</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem 0.3rem; border-radius: 10px; background: rgba(165,180,252,0.12); border: 1px solid rgba(165,180,252,0.45);">
                                        <div style="font-size: 0.62rem; letter-spacing: 0.06em; color: #a5b4fc; text-transform: uppercase;">Hist (prev)</div>
                                        <div style="font-size: 1.1rem; font-weight: 800; color: #6366f1; margin-top: 0.15rem;">{html.escape(str(macd_hp_s))}</div>
                                    </div>
                                </div>
                                {sig_html}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # Updated News (always visible)
                    news_text = result.get('news_text', 'No recent news available.')
                    with st.expander("📰 Updated News（更新消息）", expanded=True):
                        if news_text != "No recent news available.":
                            st.markdown(news_text)
                        else:
                            st.write("暫無更新消息。")

                    signal_advice = signal.get('advice', '無訊號') if signal else '無訊號'
                    signal_reason = signal.get('commentary', signal.get('reason', '')) if signal else ''
                    hk_tz = pytz.timezone('Asia/Hong_Kong')
                    report_datetime_hk = datetime.now(hk_tz).strftime("%Y-%m-%d %H:%M:%S")
                    is_backtest = result.get('is_backtest', False)
                    backtest_date_str = result.get('backtest_date', None)
                    header = f"Analyze this stock for me (AS OF {backtest_date_str}): {ticker} ({stock_name})" if (is_backtest and backtest_date_str) else f"Analyze this stock for me: {ticker} ({stock_name})"
                    _ref_put = details.get("suggested_put_strike") if details else None
                    _ref_call = details.get("suggested_call_strike") if details else None
                    _ref_strike_lines = ""
                    if _ref_put is not None or _ref_call is not None:
                        _ref_strike_lines = "\n[Reference option strike — 模型參考行使價]\n"
                        if _ref_put is not None:
                            _ref_strike_lines += f"Suggested Short Put strike: ≤ {_ref_put:.2f}\n"
                        if _ref_call is not None:
                            _ref_strike_lines += f"Suggested Short Call strike: ≥ {_ref_call:.2f}\n"
                    _ml_r = details.get("macd_line")
                    _ms_r = details.get("macd_signal")
                    _mh_r = details.get("macd_hist")
                    _mhp_r = details.get("macd_hist_prev")
                    _macd_zc = "N/A"
                    if _mh_r is not None and _mhp_r is not None:
                        try:
                            _macd_zc = "Yes" if (float(_mh_r) > 0 and float(_mhp_r) <= 0) else "No"
                        except Exception:
                            _macd_zc = "N/A"
                    _macd_line_s = f"{float(_ml_r):.4f}" if _ml_r is not None else "N/A"
                    _macd_sig_s = f"{float(_ms_r):.4f}" if _ms_r is not None else "N/A"
                    _macd_h_s = f"{float(_mh_r):.4f}" if _mh_r is not None else "N/A"
                    _macd_hp_s = f"{float(_mhp_r):.4f}" if _mhp_r is not None else "N/A"
                    part1_snapshot = f"""Report Generated: {report_datetime_hk} (HKT)
{header}

[Part 1: Real-Time Snapshot]
Price: {current_price_val:.2f} ({change_str})

[Technical Structure]
RSI: {rsi_val:.2f} | ADX: {adx_val:.2f} (Slope: {adx_slope_val:.2f}) | PDI: {pdi_val:.2f} | MDI: {mdi_val:.2f} | Gap: {pdi_mdi_gap:.2f}
ATR: {atr_val:.2f} | Bollinger: {bb_upper_val:.2f} / {bb_middle_val:.2f} / {bb_lower_val:.2f} | SMA 200: {sma_200_str} | SMA 50: {sma_50_str}
52W Range: {week_52_low_str} - {week_52_high_str}

[MACD (12,26,9)]
Line: {_macd_line_s} | Signal: {_macd_sig_s} | Hist: {_macd_h_s} | Hist (prev): {_macd_hp_s} | Zero-cross (Hist>0 & Hist_prev<=0): {_macd_zc}

[Fundamental Health]
Market Cap: {market_cap_str} | PE (Trail/Fwd): {trailing_pe_str} / {forward_pe_str} | PEG: {peg_ratio_str}
Profit Margin: {profit_margins_str} | Debt/Eq: {debt_to_equity_str}

[Risk Check]
Next Earnings: {next_earnings_str} | RVOL: {rvol_val:.2f} | MFI: {mfi_val:.2f}

[Comparative RS]
Comparative RS (20d Outperformance vs Market): {rs_report_str}
{_ref_strike_lines}
[Robot Signal]
{signal_advice}
{signal_reason if signal_reason else 'No additional signal details'}"""
                    history_log_10d = result.get("history_log_10d", "")
                    part2_lines = history_log_10d.split("\n")[3:] if history_log_10d else []  # skip "=== ...", "Report Time", ""
                    part2_content = "\n".join(part2_lines) if part2_lines else "(No 10-day data)"
                    full_report_text = part1_snapshot + "\n\n========================================\n=== 📜 10-DAY TREND LOG ===\n\n" + part2_content
                    with st.expander("📄 Full report", expanded=False):
                        st.code(full_report_text, language="markdown")

                    # Portfolio context (optional) — inject into AI prompt
                    user_context = st.text_area(
                        "💼 我的持倉/實時備註 (Optional Context)",
                        placeholder="例如：我喺 $300 買咗 1000 股 0700.HK，諗緊好唔好做 Short Call...",
                        key="stocktracker_user_context",
                        height=80,
                    )

                    gemini_persona = st.radio(
                        "🎭 Gemini 人設（與完整報告一併送入模型）",
                        ("穩健收租 (Sell Put)", "極限爆發 (Buy Call)", "恐慌破底 (Buy Put / 做淡)"),
                        index=0,
                        horizontal=True,
                        key="stocktracker_gemini_persona_v1",
                        help="賣方：防守、安全墊、Sell Put；買方：爆發、順勢、Buy Call；做淡：破底放量、Buy Put / Bear Put Spread。",
                    )

                    # 召喚大佬實戰分析 (AI) — analyse the full report (per-stock chat + past context)
                    if st.button("🤖 召喚大佬實戰分析 (AI Analysis)", key="stocktracker_ai"):
                        if not st.session_state.api_key:
                            st.error("請先在左側輸入 Gemini API Key!")
                        else:
                            # Past context for this ticker only (last 3 interactions to save tokens)
                            past_entries = st.session_state.stock_chats[ticker][-3:]
                            past_context = "\n\n".join(
                                f"User: {e.get('user', '(無)')}\nAI: {e.get('response', '')}"
                                for e in past_entries
                            )
                            _vwap_raw = latest_row.get("vwap") if isinstance(latest_row, dict) else None
                            if _vwap_raw is not None and not (isinstance(_vwap_raw, float) and pd.isna(_vwap_raw)):
                                vwap_for_prompt = f"{float(_vwap_raw):.2f}"
                            else:
                                vwap_for_prompt = "N/A"
                            score_for_prompt = str(int(round(min(10.0, max(0.0, float(hero_score)))) * 10))
                            macd_row_ai = {
                                "MACD_Hist": details.get("macd_hist"),
                                "MACD_Hist_Prev": details.get("macd_hist_prev"),
                            }
                            macd_status_ai = macd_histogram_status(macd_row_ai)
                            if "Sell Put" in gemini_persona:
                                _sm = "sell_put"
                            elif "Buy Put" in gemini_persona or "做淡" in gemini_persona:
                                _sm = "buy_put"
                            else:
                                _sm = "buy_stock"
                            system_prompt = build_gemini_system_prompt_for_trading_mode(
                                score_model=_sm,
                                trading_mode=gemini_persona,
                                score=score_for_prompt,
                                close=f"{float(current_price_val):.2f}",
                                vwap=vwap_for_prompt,
                                rvol=f"{float(rvol_val):.2f}",
                                adx=f"{float(adx_val):.2f}",
                                macd_status=macd_status_ai,
                                rs=rs_report_str,
                            )
                            combined_prompt = (
                                system_prompt
                                + "\n\n以下係「完整策略報告」(Live + 10-Day History)。請先完成上文【系統策略草稿】的寫作要求，"
                                "再結合報告全文（含 Part 1 與 10-Day Trend）作補充；人設、禁語與工具建議必須與上文一致。\n\n"
                                "----------------------------------------\n"
                                + full_report_text
                            )
                            news_for_ai = result.get('news_text', 'No recent news available.')
                            combined_prompt += (
                                f"\n\nUpdated News (更新消息):\n{news_for_ai}\n\n"
                                "Please factor these news headlines into your strategy recommendation to explain any sudden volume or trend changes."
                            )
                            risk_score_ai = result.get("risk_score")
                            risk_label_ai = result.get("risk_label", "")
                            if risk_score_ai is not None:
                                combined_prompt += (
                                    f"\n\n【倉位危險指數 Risk-Exit Score】\n"
                                    f"Risk Score: {risk_score_ai:.1f} / 10.0\n"
                                    f"Status: {risk_label_ai}\n\n"
                                    "If risk score is high (≥7), advise on exit/stop-loss strategies; if ≥4, suggest reducing position or adding hedges."
                                )
                            if stop_loss is not None and target_price_3r is not None:
                                combined_prompt += (
                                    f"\n\nQuant Trade Plan -> Stop Loss: ${stop_loss:.2f}, 1:3 Target: ${target_price_3r:.2f}."
                                )
                            if past_context.strip():
                                combined_prompt += "\n\n【老闆之前的對話與持倉記憶】：\n" + past_context
                            if (user_context or "").strip():
                                combined_prompt += "\n\n【老闆持倉現況與問題】\n" + (user_context or "").strip()
                            try:
                                model = genai.GenerativeModel("gemini-2.5-flash")
                                stream = model.generate_content(combined_prompt, stream=True)

                                with st.expander("🤖 大佬實戰分析（Gemini）", expanded=True):
                                    status_placeholder = st.empty()
                                    response_placeholder = st.empty()
                                    with status_placeholder.container():
                                        st.spinner("大佬睇緊盤…")
                                    full_text = ""
                                    first_chunk = True
                                    for chunk in stream:
                                        if getattr(chunk, "text", None):
                                            if first_chunk:
                                                status_placeholder.empty()
                                                first_chunk = False
                                            full_text += chunk.text
                                            response_placeholder.markdown(full_text)
                                    if first_chunk:
                                        status_placeholder.empty()
                                        response_placeholder.markdown("（AI 沒有返回文字回應）")
                                    elif full_text:
                                        response_placeholder.markdown(full_text)
                                    # Append to this stock's chat history (user + AI response)
                                    if full_text:
                                        st.session_state.stock_chats[ticker].append({
                                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "user": (user_context or "").strip(),
                                            "response": full_text,
                                        })
                            except Exception as e:
                                st.error(f"Gemini 調用失敗: {e}")

                    # Session history — only this stock's chat (per-stock like Gemini UI)
                    with st.expander("📜 歷史分析紀錄 (Session History)", expanded=False):
                        chat_list = st.session_state.stock_chats.get(ticker, [])
                        if not chat_list:
                            st.caption("本股票尚未有分析紀錄，分析完會顯示喺呢度。")
                        else:
                            for i, entry in enumerate(reversed(chat_list)):
                                st.markdown(f"**{ticker}** · {entry['timestamp']}")
                                if entry.get("user"):
                                    st.caption("老闆: " + entry["user"])
                                st.markdown(entry.get("response", ""))
                                if i < len(chat_list) - 1:
                                    st.divider()
                    
                else:
                    st.error(f"❌ 錯誤: {result.get('error', '未知錯誤')}")


if __name__ == "__main__":
    main()
