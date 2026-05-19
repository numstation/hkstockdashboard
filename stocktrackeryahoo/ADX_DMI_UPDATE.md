# ADX Calculation Updated with DMI+ and DMI-

## ✅ Changes Made

### 1. **ADX Calculation Now Includes DMI+ and DMI-**
   - **DMI+ (PDI)**: Plus Directional Indicator
   - **DMI- (MDI)**: Minus Directional Indicator
   - Both are calculated using Futu's formula

### 2. **Both Moving Average Periods Set to 14**
   - **N = 14**: For MTR, DMP, DMM smoothing
   - **M = 14**: For ADX smoothing
   - Matches Futu's 移動平均值 setting

### 3. **Futu Formula Implementation**
   ```
   MTR = EXPMEMA(MAX(MAX(HIGH-LOW, ABS(HIGH-PREV_CLOSE)), ABS(PREV_CLOSE-LOW)), 14)
   DMP = EXPMEMA(IF(HD>0 && HD>LD, HD, 0), 14)
   DMM = EXPMEMA(IF(LD>0 && LD>HD, LD, 0), 14)
   PDI (DMI+) = DMP * 100 / MTR
   MDI (DMI-) = DMM * 100 / MTR
   ADX = EXPMEMA(ABS(MDI-PDI) / (MDI+PDI) * 100, 14)
   ```

## Files Updated

1. **`hk_rangebot.py`**
   - Uses `calculate_adx_futu_ewm(df, n=14, m=14)`
   - Displays DMI+ and DMI- values
   - Shows ADX (14, 14) in output

2. **`app.py`**
   - Uses `calculate_adx_futu_ewm(df, n=14, m=14)`
   - Returns DMI+ and DMI- in API response
   - Web UI displays DMI+ and DMI- values

3. **`templates/index.html`**
   - Added DMI+ and DMI- display in results

## What You'll See

### Command Line Output:
```
📊 ADX (14, 14) - Latest Date: XX.XX
📈 ADX Slope (Current - Previous): XX.XX
📈 DMI+ (PDI): XX.XX
📉 DMI- (MDI): XX.XX
```

### Web Interface:
- DMI+ (PDI) value displayed
- DMI- (MDI) value displayed
- ADX calculated using both DMI values

## Testing

Run the script:
```bash
python3 hk_rangebot.py
```

The ADX calculation now:
- ✅ Includes DMI+ and DMI- (required for proper ADX)
- ✅ Uses period 14 for both moving averages
- ✅ Matches Futu's formula exactly

This should give you more accurate ADX values that match Futu's calculation!
