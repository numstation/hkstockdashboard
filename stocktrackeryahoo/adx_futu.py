"""
ADX Calculation Matching Futu's Formula
Based on Futu's actual formula using EXPMEMA
"""

import pandas as pd
import numpy as np


def expmema(series, period):
    """
    Exponential Moving Average (EXPMEMA) as used by Futu.
    
    Args:
        series: pandas Series to smooth
        period: smoothing period
    
    Returns:
        Series with EXPMEMA values
    """
    # Alpha (smoothing factor)
    alpha = 2.0 / (period + 1.0)
    
    # Initialize EMA
    ema = pd.Series(index=series.index, dtype=float)
    
    # First value: use first non-NaN value
    first_valid_idx = series.first_valid_index()
    if first_valid_idx is not None:
        ema.loc[first_valid_idx] = series.loc[first_valid_idx]
        
        # Calculate EMA for subsequent values
        for i in range(series.index.get_loc(first_valid_idx) + 1, len(series)):
            prev_idx = series.index[i-1]
            curr_idx = series.index[i]
            
            if pd.notna(series.loc[curr_idx]) and pd.notna(ema.loc[prev_idx]):
                ema.loc[curr_idx] = (alpha * series.loc[curr_idx]) + ((1 - alpha) * ema.loc[prev_idx])
            elif pd.notna(series.loc[curr_idx]):
                ema.loc[curr_idx] = series.loc[curr_idx]
    
    return ema


def calculate_adx_futu(df, n=14, m=14):
    """
    Calculate ADX exactly matching Futu's formula.
    
    Futu Formula:
    MTR:=EXPMEMA(MAX(MAX(HIGH-LOW,ABS(HIGH-REF(CLOSE,1))),ABS(REF(CLOSE,1)-LOW)),N);
    HD:=HIGH-REF(HIGH,1);
    LD:=REF(LOW,1)-LOW;
    DMP:=EXPMEMA(IF(HD>0 && HD>LD,HD,0),N);
    DMM:=EXPMEMA(IF(LD>0 && LD>HD,LD,0),N);
    PDI:DMP*100/MTR;
    MDI:DMM*100/MTR;
    ADX:EXPMEMA(ABS(MDI-PDI)/(MDI+PDI)*100,M);
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        n: Period for MTR, DMP, DMM smoothing (default 14)
        m: Period for ADX smoothing (default 14)
    
    Returns:
        Dictionary with ADX, PDI, MDI values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Step 1: Calculate MTR (Modified True Range)
    # MTR = MAX(MAX(HIGH-LOW, ABS(HIGH-REF(CLOSE,1))), ABS(REF(CLOSE,1)-LOW))
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (prev_close - low).abs()
    mtr_raw = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Smooth MTR with EXPMEMA
    mtr = expmema(mtr_raw, n)
    
    # Step 2: Calculate HD and LD
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    hd = high - prev_high
    ld = prev_low - low
    
    # Step 3: Calculate DMP (Directional Movement Plus)
    # DMP = EXPMEMA(IF(HD>0 && HD>LD, HD, 0), N)
    dmp_raw = pd.Series(0.0, index=df.index)
    dmp_raw = np.where((hd > 0) & (hd > ld), hd, 0.0)
    dmp_raw = pd.Series(dmp_raw, index=df.index)
    dmp = expmema(dmp_raw, n)
    
    # Step 4: Calculate DMM (Directional Movement Minus)
    # DMM = EXPMEMA(IF(LD>0 && LD>HD, LD, 0), N)
    dmm_raw = pd.Series(0.0, index=df.index)
    dmm_raw = np.where((ld > 0) & (ld > hd), ld, 0.0)
    dmm_raw = pd.Series(dmm_raw, index=df.index)
    dmm = expmema(dmm_raw, n)
    
    # Step 5: Calculate PDI and MDI
    # PDI = DMP * 100 / MTR
    # MDI = DMM * 100 / MTR
    pdi = (dmp * 100) / mtr.replace(0, np.nan)
    mdi = (dmm * 100) / mtr.replace(0, np.nan)
    
    # Step 6: Calculate DX
    # DX = ABS(MDI - PDI) / (MDI + PDI) * 100
    di_sum = mdi + pdi
    di_diff = (mdi - pdi).abs()
    dx = (di_diff / di_sum.replace(0, np.nan)) * 100
    
    # Step 7: Calculate ADX
    # ADX = EXPMEMA(DX, M)
    adx = expmema(dx, m)
    
    return {
        'adx': adx,
        'pdi': pdi,
        'mdi': mdi,
        'dx': dx
    }


# Alternative implementation using pandas ewm (might be closer to Futu)
def calculate_adx_futu_ewm(df, n=14, m=14):
    """
    Calculate ADX using pandas ewm (exponential weighted moving average).
    This might match Futu's EXPMEMA more closely.
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Step 1: MTR
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (prev_close - low).abs()
    mtr_raw = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    mtr = mtr_raw.ewm(span=n, adjust=False).mean()
    
    # Step 2: HD and LD
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    hd = high - prev_high
    ld = prev_low - low
    
    # Step 3: DMP
    dmp_raw = np.where((hd > 0) & (hd > ld), hd, 0.0)
    dmp_raw = pd.Series(dmp_raw, index=df.index)
    dmp = dmp_raw.ewm(span=n, adjust=False).mean()
    
    # Step 4: DMM
    dmm_raw = np.where((ld > 0) & (ld > hd), ld, 0.0)
    dmm_raw = pd.Series(dmm_raw, index=df.index)
    dmm = dmm_raw.ewm(span=n, adjust=False).mean()
    
    # Step 5: PDI and MDI
    pdi = (dmp * 100) / mtr.replace(0, np.nan)
    mdi = (dmm * 100) / mtr.replace(0, np.nan)
    
    # Step 6: DX
    di_sum = mdi + pdi
    di_diff = (mdi - pdi).abs()
    dx = (di_diff / di_sum.replace(0, np.nan)) * 100
    
    # Step 7: ADX
    adx = dx.ewm(span=m, adjust=False).mean()
    
    return {
        'adx': adx,
        'pdi': pdi,
        'mdi': mdi,
        'dx': dx
    }


if __name__ == "__main__":
    print("Futu ADX Calculation Functions")
    print("Use calculate_adx_futu() or calculate_adx_futu_ewm()")
    print("Both should match Futu's EXPMEMA formula")
