# ADX Calculation Explained

## Current Implementation

Your code currently uses the `ta` library's ADX calculation:

```python
adx_indicator = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
df['adx'] = adx_indicator.adx()
```

## How ADX is Calculated (Standard Method)

ADX (Average Directional Index) measures trend strength. Here's the step-by-step calculation:

### Step 1: Calculate True Range (TR)
For each period:
```
TR = max(
    High - Low,
    abs(High - Previous Close),
    abs(Low - Previous Close)
)
```

### Step 2: Calculate Directional Movement (+DM and -DM)
```
+DM = High - Previous High  (if > 0 and > (Previous Low - Low))
-DM = Previous Low - Low    (if > 0 and > (High - Previous High))
```

### Step 3: Smooth TR, +DM, and -DM
The `ta` library uses **Exponential Moving Average (EMA)** by default:
```
Smoothed TR = EMA(TR, period=14)
Smoothed +DM = EMA(+DM, period=14)
Smoothed -DM = EMA(-DM, period=14)
```

### Step 4: Calculate Directional Indicators (+DI and -DI)
```
+DI = 100 × (Smoothed +DM / Smoothed TR)
-DI = 100 × (Smoothed -DM / Smoothed TR)
```

### Step 5: Calculate Directional Index (DX)
```
DX = 100 × abs(+DI - -DI) / (+DI + -DI)
```

### Step 6: Calculate ADX
```
ADX = EMA(DX, period=14)
```

## Why Your ADX Might Differ from Futu

**Futu likely uses Wilder's Smoothing (RMA)** instead of EMA:

### Wilder's Smoothing Formula:
```
First value: Sum of first 14 periods
Subsequent: new_value = (old_value × 13 + current_value) / 14
```

### EMA Formula (what `ta` library uses):
```
EMA = (current_value × multiplier) + (previous_EMA × (1 - multiplier))
where multiplier = 2 / (period + 1)
```

**This difference causes the discrepancy!**

## How to Modify to Match Futu

I'll create a custom ADX function using Wilder's smoothing that you can adjust:
