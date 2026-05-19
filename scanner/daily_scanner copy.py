import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="🦁 Veteran Sniper", page_icon="🦁", layout="wide")

# Default Tickers
DEFAULT_TICKERS = [
    "9988.HK", "0700.HK", "1211.HK", "0005.HK", "9992.HK", "9626.HK",
    "9999.HK", "0027.HK", "1772.HK", "9888.HK", "1810.HK", "3750.HK",
    "2318.HK", "0388.HK", "0941.HK", "0001.HK", "0016.HK", "0823.HK",
    "3416.HK", "1299.HK", "1024.HK", "0003.HK", "1928.HK", "2020.HK",
    "0939.HK", "1398.HK", "6618.HK", "0001.HK", "0016.HK", "3690.HK",
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AMD",
]

# --- LOGIC (Same as Veteran v4.0) ---
def get_veteran_signal(ticker):
    try:
        # Check if it's HK stock to append .HK if missing (Optional helper)
        # For this script, we assume user types correct format
        
        df = yf.download(ticker, period="6mo", progress=False)
        if len(df) < 50: return None
        
        # Calculations
        df['SMA20'] = ta.sma(df['Close'], length=20)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
        df = df.join(adx_df)
        df['Vol_SMA20'] = ta.sma(df['Volume'], length=20)
        df['RVOL'] = df['Volume'] / df['Vol_SMA20']
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Logic
        core_pass = (curr['Close'] > curr['SMA20']) and (20 < curr['ADX_14'] < 50) and (curr['DMP_14'] > curr['DMN_14'])
        
        score = 0
        details = []
        if curr['RSI'] > 50: score += 1; details.append("RSI")
        if curr['MFI'] > 55: score += 1; details.append("MFI")
        if curr['RVOL'] >= 1.0: score += 1; details.append("VOL")
        
        signal = "WAIT"
        
        if core_pass and score >= 2:
            signal = f"🚀 BUY ({score}/3)"
        elif (curr['Close'] > curr['SMA20']) and (curr['RSI'] > 75):
            signal = "💰 PROFIT TAKE"
            details = ["Overheated"]
        elif curr['Close'] < curr['SMA20']:
            signal = "💀 SELL / AVOID"
            details = ["Trend Broken"]
            
        return {
            "Ticker": ticker,
            "Price": float(curr['Close']),
            "Signal": signal,
            "Why": ",".join(details),
            "ADX": round(curr['ADX_14'], 1),
            "RSI": round(curr['RSI'], 1),
            "MFI": round(curr['MFI'], 1),
            "RVOL": round(curr['RVOL'], 2)
        }
    except Exception as e:
        return None

# --- UI LAYOUT ---
st.title("🦁 Veteran Stock Scanner (v4.0)")
st.markdown("### The Elite Quant Dashboard")

# Sidebar for Inputs
with st.sidebar:
    st.header("⚙️ Settings")
    ticker_input = st.text_area("Enter Tickers (comma separated)", value=",".join(DEFAULT_TICKERS), height=150)
    run_btn = st.button("🔍 Run Scanner", type="primary")
    st.info("Tip: Add '.HK' for Hong Kong stocks.")

# Main Execution
if run_btn:
    tickers_list = [x.strip() for x in ticker_input.split(',')]
    
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    results = []
    
    for i, t in enumerate(tickers_list):
        status_text.text(f"Scanning {t}...")
        res = get_veteran_signal(t)
        if res:
            results.append(res)
        progress_bar.progress((i + 1) / len(tickers_list))
    
    status_text.text("Scan Complete!")
    progress_bar.empty()
    
    if results:
        df_res = pd.DataFrame(results)
        
        # Color Styling Function
        def highlight_signal(val):
            color = ''
            if 'BUY' in val: color = 'background-color: #d4edda; color: #155724' # Green
            elif 'PROFIT' in val: color = 'background-color: #fff3cd; color: #856404' # Orange
            elif 'SELL' in val: color = 'background-color: #f8d7da; color: #721c24' # Red
            return color

        # Display the Dataframe
        st.dataframe(
            df_res.style.map(highlight_signal, subset=['Signal'])
            .format({"Price": "{:.2f}", "RVOL": "{:.2f}"}),
            use_container_width=True,
            hide_index=True
        )
        
        # Quick Stats
        buy_count = len(df_res[df_res['Signal'].str.contains("BUY")])
        st.success(f"Found {buy_count} BUY signals out of {len(results)} stocks.")
        
    else:
        st.warning("No data found or all tickers invalid.")

else:
    st.write("👈 Click 'Run Scanner' in the sidebar to start.")