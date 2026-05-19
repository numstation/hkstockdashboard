# Conditional Strike Price Display - IMPLEMENTED

## ✅ Smart Strike Price Logic

The strike price display is now conditional based on the trading signal:

### Display Rules:

1. **SHORT PUT Signal** → Only shows **Put Strike**
   - Calculates: `MIN(Close - 2*ATR, Lower Bollinger Band)`
   - Displays: "💡 Suggested Put Strike: <= XX.X"

2. **SHORT CALL Signal** → Only shows **Call Strike**
   - Calculates: `MAX(Close + 2*ATR, Upper Bollinger Band)`
   - Displays: "💡 Suggested Call Strike: >= XX.X"

3. **WAIT Signal** → No strike prices shown
   - Just shows the advice message

4. **WARNING Signal** → No strike prices shown
   - Just shows the warning message

## Implementation Details:

### Command Line (`hk_rangebot.py`):
- Strike prices are calculated **only after** the signal is determined
- Calculation happens inside the conditional blocks
- Only the relevant strike price is printed

### Web App (`app.py`):
- Strike prices are calculated **inside** the signal logic blocks
- `suggested_put_strike` and `suggested_call_strike` are set to `None` by default
- Only populated when there's an actionable signal

### Web UI (`templates/index.html`):
- Checks for `suggested_put_strike` or `suggested_call_strike` separately
- Shows only the relevant strike price box
- No strike prices shown for WAIT or WARNING signals

## Benefits:

✅ Cleaner output - only shows relevant information
✅ Less confusion - user sees strike price only when there's a signal
✅ Better UX - actionable information when needed
✅ Matches trading logic - strike price matches the signal type

## Example Output:

**SHORT PUT Signal:**
```
🎯 TRADING ADVICE: 🟢 SIGNAL: SHORT PUT (Reason: Oversold)
   💡 Suggested Put Strike: <= 385.5
```

**SHORT CALL Signal:**
```
🎯 TRADING ADVICE: 🔴 SIGNAL: SHORT CALL (Reason: Overbought)
   💡 Suggested Call Strike: >= 425.3
```

**WAIT Signal:**
```
🎯 TRADING ADVICE: ☕ WAIT: No clear signal.
(No strike prices shown)
```
