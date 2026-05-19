# How to Modify ADX Calculation to Match Futu

## Current Situation

- **Your code uses**: `ta.trend.ADXIndicator` which uses **EMA smoothing**
- **Futu app uses**: **Wilder's Smoothing (RMA)**
- **Result**: Different ADX values

## Solution: Replace with Custom Wilder's ADX

### Step 1: Add the Custom Function

I've created `adx_custom.py` with a Wilder's smoothing implementation. You can:

1. **Option A**: Import and use it directly
2. **Option B**: Copy the function into your main file

### Step 2: Modify Your Code

Replace this in `hk_rangebot.py` and `app.py`:

**OLD (using ta library):**
```python
adx_indicator = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
df['adx'] = adx_indicator.adx()
```

**NEW (using Wilder's smoothing):**
```python
from adx_custom import calculate_adx_wilders

df['adx'] = calculate_adx_wilders(df, length=14)
```

### Step 3: Test and Compare

1. Run your script and note the ADX value
2. Compare with Futu app's ADX value
3. If still different, you can adjust the calculation

## Key Differences to Adjust

### 1. Smoothing Method
- **Wilder's (RMA)**: `new = (old × 13 + current) / 14`
- **EMA**: `new = current × α + old × (1-α)` where α = 2/(14+1) = 0.133

### 2. Initial Value
- **Wilder's**: First value = sum of first 14 periods
- **EMA**: First value = first period value (or average)

### 3. ADX Initialization
- **Wilder's**: First ADX = average of DX from period 14 to 27
- **EMA**: First ADX = first DX value (or smoothed)

## Fine-Tuning Parameters

If values still don't match exactly, you can adjust:

1. **Period length**: Try 13 or 15 instead of 14
2. **Initial ADX calculation**: Change how first ADX is calculated
3. **Rounding**: Futu might round differently

## Testing Script

Create a test file to compare:

```python
import pandas as pd
from adx_custom import calculate_adx_wilders, calculate_adx_ema
# ... load your data ...

# Compare both methods
adx_wilders = calculate_adx_wilders(df, length=14)
adx_ema = calculate_adx_ema(df, length=14)

print("Wilder's ADX (latest):", adx_wilders.iloc[-1])
print("EMA ADX (latest):", adx_ema.iloc[-1])
print("Futu ADX:", YOUR_FUTU_VALUE)
```

## Next Steps

1. Use `calculate_adx_wilders()` function
2. Compare results with Futu
3. If still different, check:
   - Data alignment (same dates?)
   - Period length (14 vs other?)
   - Rounding differences
   - Initial value calculation
