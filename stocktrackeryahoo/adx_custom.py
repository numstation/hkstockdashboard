"""
Custom ADX Calculation with Wilder's Smoothing
This matches the calculation method used by Futu trading app
"""

import pandas as pd
import numpy as np


def calculate_adx_wilders(df, length=14):
    """
    Calculate ADX using Wilder's Smoothing (RMA) method.
    This should match Futu's ADX calculation.
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        length: Period for ADX calculation (default 14)
    
    Returns:
        Series with ADX values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Step 1: Calculate True Range (TR)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Step 2: Calculate Directional Movement
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    
    plus_dm = high - prev_high
    minus_dm = prev_low - low
    
    # Filter: +DM only if it's positive and greater than -DM
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    # Filter: -DM only if it's positive and greater than +DM
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # Step 3: Apply Wilder's Smoothing (RMA) to TR, +DM, -DM
    # First value: sum of first 'length' periods
    tr_smooth = tr.rolling(window=length, min_periods=length).sum()
    plus_dm_smooth = plus_dm.rolling(window=length, min_periods=length).sum()
    minus_dm_smooth = minus_dm.rolling(window=length, min_periods=length).sum()
    
    # Apply Wilder's smoothing for subsequent values
    # Formula: new_value = (old_value × (n-1) + current_value) / n
    for i in range(length, len(df)):
        if not pd.isna(tr_smooth.iloc[i-1]):
            tr_smooth.iloc[i] = (tr_smooth.iloc[i-1] * (length - 1) + tr.iloc[i]) / length
            plus_dm_smooth.iloc[i] = (plus_dm_smooth.iloc[i-1] * (length - 1) + plus_dm.iloc[i]) / length
            minus_dm_smooth.iloc[i] = (minus_dm_smooth.iloc[i-1] * (length - 1) + minus_dm.iloc[i]) / length
    
    # Step 4: Calculate +DI and -DI
    plus_di = 100 * (plus_dm_smooth / tr_smooth)
    minus_di = 100 * (minus_dm_smooth / tr_smooth)
    
    # Step 5: Calculate DX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    # Avoid division by zero
    dx = 100 * (di_diff / di_sum.replace(0, np.nan))
    
    # Step 6: Calculate ADX by smoothing DX with Wilder's method
    adx = pd.Series(np.nan, index=df.index)
    
    # First ADX value: average of first 'length' DX values after initial period
    # ADX needs 2×length periods to stabilize
    first_adx_idx = length * 2 - 1
    if first_adx_idx < len(dx):
        # Initial ADX is the average of DX values from period 'length' to '2×length-1'
        adx.iloc[first_adx_idx] = dx.iloc[length:first_adx_idx+1].mean()
        
        # Apply Wilder's smoothing for subsequent ADX values
        for i in range(first_adx_idx + 1, len(df)):
            if not pd.isna(adx.iloc[i-1]) and not pd.isna(dx.iloc[i]):
                adx.iloc[i] = (adx.iloc[i-1] * (length - 1) + dx.iloc[i]) / length
    
    return adx


def calculate_adx_ema(df, length=14):
    """
    Calculate ADX using EMA (Exponential Moving Average) method.
    This is what the 'ta' library uses by default.
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        length: Period for ADX calculation (default 14)
    
    Returns:
        Series with ADX values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Calculate True Range (TR)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Calculate Directional Movement
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    
    plus_dm = high - prev_high
    minus_dm = prev_low - low
    
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # Use EMA for smoothing (this is what 'ta' library does)
    tr_smooth = tr.ewm(span=length, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(span=length, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(span=length, adjust=False).mean()
    
    # Calculate +DI and -DI
    plus_di = 100 * (plus_dm_smooth / tr_smooth)
    minus_di = 100 * (minus_dm_smooth / tr_smooth)
    
    # Calculate DX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100 * (di_diff / di_sum.replace(0, np.nan))
    
    # Calculate ADX using EMA
    adx = dx.ewm(span=length, adjust=False).mean()
    
    return adx


# Example usage and comparison
if __name__ == "__main__":
    print("ADX Calculation Methods:")
    print("1. Wilder's Smoothing (RMA) - matches Futu")
    print("2. EMA Smoothing - matches 'ta' library")
    print("\nUse calculate_adx_wilders() to match Futu's calculation")
