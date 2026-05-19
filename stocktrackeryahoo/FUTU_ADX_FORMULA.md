# Futu ADX Formula Analysis

## Futu's Formula (from user):

```
MTR:=EXPMEMA(MAX(MAX(HIGH-LOW,ABS(HIGH-REF(CLOSE,1))),ABS(REF(CLOSE,1)-LOW)),N);
HD:=HIGH-REF(HIGH,1);
LD:=REF(LOW,1)-LOW;
DMP:=EXPMEMA(IF(HD>0 && HD>LD,HD,0),N);
DMM:=EXPMEMA(IF(LD>0 && LD>HD,LD,0),N);
PDI:DMP*100/MTR;
MDI:DMM*100/MTR;
ADX:EXPMEMA(ABS(MDI-PDI)/(MDI+PDI)*100,M);
ADXR:EXPMEMA(ADX,M);
```

Where N = 14 (移動平均周期) and M = 14

## Step-by-Step Translation:

1. **MTR (Modified True Range)**:
   - Calculate: `MAX(MAX(HIGH-LOW, ABS(HIGH-PREV_CLOSE)), ABS(PREV_CLOSE-LOW))`
   - Smooth with: `EXPMEMA(MTR, 14)`

2. **HD (High Difference)**:
   - `HD = HIGH - PREVIOUS_HIGH`

3. **LD (Low Difference)**:
   - `LD = PREVIOUS_LOW - LOW`

4. **DMP (Directional Movement Plus)**:
   - If `HD > 0 AND HD > LD`: use HD, else 0
   - Smooth with: `EXPMEMA(DMP, 14)`

5. **DMM (Directional Movement Minus)**:
   - If `LD > 0 AND LD > HD`: use LD, else 0
   - Smooth with: `EXPMEMA(DMM, 14)`

6. **PDI (Plus DI)**:
   - `PDI = DMP * 100 / MTR`

7. **MDI (Minus DI)**:
   - `MDI = DMM * 100 / MTR`

8. **ADX**:
   - `DX = ABS(MDI - PDI) / (MDI + PDI) * 100`
   - `ADX = EXPMEMA(DX, 14)`

9. **ADXR** (optional):
   - `ADXR = EXPMEMA(ADX, 14)`

## Key Differences from Standard ADX:

1. **EXPMEMA instead of Wilder's Smoothing** - Futu uses EMA, not RMA
2. **MTR is smoothed first** - True Range is smoothed before calculating DI
3. **ADX uses period M (14)** - Same as the smoothing period

## EXPMEMA Implementation:

EXPMEMA is likely an Exponential Moving Average. The key is how it's initialized:
- First value might be: first period value, or average of first N periods
- Subsequent: `EMA = current × α + previous_EMA × (1-α)` where `α = 2/(N+1)`
