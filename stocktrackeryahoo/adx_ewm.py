"""ADX + DMI using exponential smoothing (EXPMEMA / pandas ewm)."""

import pandas as pd
import numpy as np


def expmema(series, period):
    """Exponential moving average with alpha = 2 / (period + 1)."""
    alpha = 2.0 / (period + 1.0)
    ema = pd.Series(index=series.index, dtype=float)
    first_valid_idx = series.first_valid_index()
    if first_valid_idx is not None:
        ema.loc[first_valid_idx] = series.loc[first_valid_idx]
        for i in range(series.index.get_loc(first_valid_idx) + 1, len(series)):
            prev_idx = series.index[i - 1]
            curr_idx = series.index[i]
            if pd.notna(series.loc[curr_idx]) and pd.notna(ema.loc[prev_idx]):
                ema.loc[curr_idx] = (alpha * series.loc[curr_idx]) + ((1 - alpha) * ema.loc[prev_idx])
            elif pd.notna(series.loc[curr_idx]):
                ema.loc[curr_idx] = series.loc[curr_idx]
    return ema


def calculate_adx_expmema(df, n=14, m=14):
    """ADX with custom EXPMEMA smoothing on TR, DM+, DM-, and DX."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (prev_close - low).abs()
    mtr_raw = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    mtr = expmema(mtr_raw, n)

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    hd = high - prev_high
    ld = prev_low - low

    dmp_raw = np.where((hd > 0) & (hd > ld), hd, 0.0)
    dmp_raw = pd.Series(dmp_raw, index=df.index)
    dmp = expmema(dmp_raw, n)

    dmm_raw = np.where((ld > 0) & (ld > hd), ld, 0.0)
    dmm_raw = pd.Series(dmm_raw, index=df.index)
    dmm = expmema(dmm_raw, n)

    pdi = (dmp * 100) / mtr.replace(0, np.nan)
    mdi = (dmm * 100) / mtr.replace(0, np.nan)

    di_sum = mdi + pdi
    di_diff = (mdi - pdi).abs()
    dx = (di_diff / di_sum.replace(0, np.nan)) * 100
    adx = expmema(dx, m)

    return {"adx": adx, "pdi": pdi, "mdi": mdi, "dx": dx}


def calculate_adx_ewm(df, n=14, m=14):
    """ADX using pandas ewm (default for streamlit / legacy web app)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (prev_close - low).abs()
    mtr_raw = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    mtr = mtr_raw.ewm(span=n, adjust=False).mean()

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    hd = high - prev_high
    ld = prev_low - low

    dmp_raw = np.where((hd > 0) & (hd > ld), hd, 0.0)
    dmp_raw = pd.Series(dmp_raw, index=df.index)
    dmp = dmp_raw.ewm(span=n, adjust=False).mean()

    dmm_raw = np.where((ld > 0) & (ld > hd), ld, 0.0)
    dmm_raw = pd.Series(dmm_raw, index=df.index)
    dmm = dmm_raw.ewm(span=n, adjust=False).mean()

    pdi = (dmp * 100) / mtr.replace(0, np.nan)
    mdi = (dmm * 100) / mtr.replace(0, np.nan)

    di_sum = mdi + pdi
    di_diff = (mdi - pdi).abs()
    dx = (di_diff / di_sum.replace(0, np.nan)) * 100
    adx = dx.ewm(span=m, adjust=False).mean()

    return {"adx": adx, "pdi": pdi, "mdi": mdi, "dx": dx}
