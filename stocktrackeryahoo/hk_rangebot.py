"""
HK-RangeBot: Mean-Reversion Trading Strategy for Hong Kong Stocks
Uses Futu Open API to fetch data and ta library for technical indicators
"""

import pandas as pd
import ta
from futu import *
import sys


def detect_bullish_pin_bar(row):
    """
    Detect if a candle is a Bullish Pin Bar.
    Criteria: Long lower shadow >= 2x body size
    
    Args:
        row: DataFrame row with 'open', 'high', 'low', 'close' columns
    
    Returns:
        bool: True if bullish pin bar detected
    """
    body_size = abs(row['close'] - row['open'])
    lower_shadow = min(row['open'], row['close']) - row['low']
    
    # Avoid division by zero
    if body_size == 0:
        return lower_shadow > 0
    
    return lower_shadow >= 2 * body_size


def calculate_indicators(df):
    """
    Calculate all required technical indicators.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        DataFrame with added indicator columns
    """
    # Ensure we have the required columns
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
    
    # Calculate ADX slope (current ADX - previous ADX)
    df['adx_slope'] = df['adx'].diff()
    
    # Detect Bullish Pin Bar
    df['is_pin_bar'] = df.apply(detect_bullish_pin_bar, axis=1)
    
    return df


def generate_trading_signal(df):
    """
    Generate trading signal based on HK-RangeBot rules.
    
    Priority:
    1. Logic A: Safety Check (Strong Trend)
    2. Logic B: Short Put Signal (Oversold)
    3. Logic C: Short Call Signal (Overbought)
    4. Logic D: No Action
    
    Args:
        df: DataFrame with indicators calculated
    
    Returns:
        str: Trading advice message
    """
    if len(df) < 2:
        return "❌ ERROR: Insufficient data for analysis"
    
    # Get latest values
    latest = df.iloc[-1]
    
    current_adx = latest['adx']
    adx_slope = latest['adx_slope']
    close_price = latest['close']
    rsi = latest['rsi']
    bb_lower = latest['bb_lower']
    bb_upper = latest['bb_upper']
    is_pin_bar = latest['is_pin_bar']
    
    # Check for NaN values
    if pd.isna(current_adx) or pd.isna(adx_slope) or pd.isna(close_price):
        return "❌ ERROR: Missing indicator data"
    
    # Logic A: SAFETY CHECK (The Filter)
    if current_adx > 30 and adx_slope > 0:
        return "⚠️ WARNING: Strong Trend Detected. DO NOT TRADE."
    
    # Logic B: SHORT PUT SIGNAL (Buy the Dip)
    # Conditions: ADX < 30 (or ADX slope is negative) AND Close <= BB Lower AND (RSI < 30 OR Pin Bar)
    if (current_adx < 30 or adx_slope < 0):
        if close_price <= bb_lower and (rsi < 30 or is_pin_bar):
            reason_parts = []
            if close_price <= bb_lower:
                reason_parts.append("Oversold")
            if rsi < 30:
                reason_parts.append("RSI < 30")
            if is_pin_bar:
                reason_parts.append("Bullish Pin Bar")
            reason = " + ".join(reason_parts)
            return f"🟢 SIGNAL: SHORT PUT (Reason: {reason})"
    
    # Logic C: SHORT CALL SIGNAL (Harvest Premium)
    # Conditions: ADX < 30 AND (Close >= BB Upper OR RSI > 70)
    if current_adx < 30:
        if close_price >= bb_upper or rsi > 70:
            reason_parts = []
            if close_price >= bb_upper:
                reason_parts.append("Overbought")
            if rsi > 70:
                reason_parts.append("RSI > 70")
            reason = " + ".join(reason_parts)
            return f"🔴 SIGNAL: SHORT CALL (Reason: {reason})"
    
    # Logic D: NO ACTION
    return "☕ WAIT: No clear signal."


def main():
    """
    Main function to execute the HK-RangeBot strategy.
    """
    # Configuration
    STOCK_CODE = 'HK.00700'  # Example: Tencent Holdings
    HOST = '127.0.0.1'
    PORT = 11111
    
    # Initialize Futu API connection
    quote_ctx = None
    try:
        quote_ctx = OpenQuoteContext(host=HOST, port=PORT)
        print(f"✅ Connected to FutuOpenD at {HOST}:{PORT}")
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to FutuOpenD: {e}")
        print("Please ensure FutuOpenD is running on localhost:11111")
        sys.exit(1)
    
    try:
        # Subscribe to K-line data first (required by Futu API)
        print(f"📡 Subscribing to K-line data for {STOCK_CODE}...")
        ret, err = quote_ctx.subscribe([STOCK_CODE], [SubType.K_DAY])
        if ret != RET_OK:
            print(f"❌ ERROR: Failed to subscribe: {err}")
            return
        
        # Fetch last 1000 days of daily K-line data (for ADX stability)
        print(f"📊 Fetching daily K-line data for {STOCK_CODE} (1000 days for ADX stability)...")
        ret, data = quote_ctx.get_cur_kline(
            code=STOCK_CODE,
            num=1000,
            ktype=KLType.K_DAY,
            autype=AuType.QFQ  # Forward adjusted
        )
        
        if ret != RET_OK:
            print(f"❌ ERROR: Failed to fetch data: {data}")
            return
        
        if data.empty:
            print(f"❌ ERROR: No data returned for {STOCK_CODE}")
            return
        
        print(f"✅ Fetched {len(data)} days of data")
        
        # Prepare DataFrame (ensure column names are lowercase)
        df = data.copy()
        df.columns = [col.lower() for col in df.columns]
        
        # Ensure we have the required columns
        # Futu API typically returns: time_key, open, high, low, close, volume, turnover
        required_mapping = {
            'time_key': 'time',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        }
        
        # Rename columns if needed
        for old_col, new_col in required_mapping.items():
            if old_col in df.columns and new_col not in df.columns:
                df[new_col] = df[old_col]
        
        # Sort by time (oldest first)
        if 'time' in df.columns:
            df = df.sort_values('time').reset_index(drop=True)
        
        # Calculate indicators
        print("🔧 Calculating technical indicators...")
        df = calculate_indicators(df)
        
        # Get latest values
        latest = df.iloc[-1]
        latest_adx = latest['adx']
        latest_adx_slope = latest['adx_slope']
        
        # Display latest values for debugging
        print("\n📈 Latest Indicator Values:")
        print(f"  Close Price: {latest['close']:.2f}")
        print(f"  RSI: {latest['rsi']:.2f}")
        print(f"  BB Upper: {latest['bb_upper']:.2f}")
        print(f"  BB Lower: {latest['bb_lower']:.2f}")
        print(f"  Bullish Pin Bar: {latest['is_pin_bar']}")
        
        # Print ADX and ADX Slope (as requested)
        print("\n" + "="*60)
        print(f"📊 ADX (14, 14) - Latest Date: {latest_adx:.2f}")
        print(f"📈 ADX Slope (Current - Previous): {latest_adx_slope:.2f}")
        print(f"📈 DMI+ (PDI): {latest['dmi_plus']:.2f}")
        print(f"📉 DMI- (MDI): {latest['dmi_minus']:.2f}")
        print("="*60)
        
        # Display all latest values
        print("\n📈 Complete Latest Indicator Values:")
        print(f"  Close Price: {latest['close']:.2f}")
        print(f"  RSI: {latest['rsi']:.2f}")
        print(f"  ADX: {latest_adx:.2f}")
        print(f"  ADX Slope: {latest_adx_slope:.2f}")
        print(f"  DMI+ (PDI): {latest['dmi_plus']:.2f}")
        print(f"  DMI- (MDI): {latest['dmi_minus']:.2f}")
        print(f"  ATR: {latest['atr']:.2f}")
        print(f"  BB Upper: {latest['bb_upper']:.2f}")
        print(f"  BB Lower: {latest['bb_lower']:.2f}")
        print(f"  Bullish Pin Bar: {latest['is_pin_bar']}")
        
        # Generate trading signal
        print("\n" + "="*60)
        advice = generate_trading_signal(df)
        print(f"🎯 TRADING ADVICE: {advice}")
        
        # Calculate and display strike prices ONLY for actionable signals
        close_price = latest['close']
        atr = latest['atr']
        bb_lower = latest['bb_lower']
        bb_upper = latest['bb_upper']
        
        if "SHORT PUT" in advice:
            # Only show Put Strike for SHORT PUT signal
            put_strike_1 = close_price - (2 * atr)
            put_strike_2 = bb_lower
            suggested_put_strike = min(put_strike_1, put_strike_2)
            print(f"   💡 Suggested Put Strike: <= {suggested_put_strike:.1f}")
        elif "SHORT CALL" in advice:
            # Only show Call Strike for SHORT CALL signal
            call_strike_1 = close_price + (2 * atr)
            call_strike_2 = bb_upper
            suggested_call_strike = max(call_strike_1, call_strike_2)
            print(f"   💡 Suggested Call Strike: >= {suggested_call_strike:.1f}")
        # For WAIT or WARNING, don't show any strike prices
        
        print("="*60)
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Close connection
        if quote_ctx:
            quote_ctx.close()
            print("\n✅ Connection closed")


if __name__ == "__main__":
    main()
