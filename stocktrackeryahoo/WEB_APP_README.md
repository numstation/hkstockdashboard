# HK-RangeBot Web Application

A beautiful web interface for analyzing Hong Kong stocks using the mean-reversion trading strategy.

## Features

- 🎨 Modern, responsive web interface
- 📊 Real-time stock analysis
- 📈 Detailed technical indicators display
- 🚦 Clear trading signals (Buy/Sell/Wait/Warning)
- ⚡ Fast and easy to use

## How to Run

### Step 1: Make sure FutuOpenD is running
- Launch FutuOpenD application
- Ensure it's logged in and listening on port 11111

### Step 2: Start the web application

```bash
cd /Users/chrislau/Documents/IT/stocktracker
python3 app.py
```

### Step 3: Open in browser

Open your web browser and go to:
```
http://127.0.0.1:5000
```

## Usage

1. Enter a stock code in the input field (e.g., `HK.00700`)
2. Click "🔍 Analyze Stock" button
3. View the trading signal and detailed indicators

## Supported Stock Codes

- **Hong Kong Stocks**: `HK.00700` (Tencent), `HK.09988` (Alibaba), etc.
- **US Stocks**: `US.AAPL`, `US.TSLA`, etc.

## Trading Signals

- 🟢 **SHORT PUT**: Oversold conditions detected - potential buying opportunity
- 🔴 **SHORT CALL**: Overbought conditions detected - potential selling opportunity
- ⚠️ **WARNING**: Strong trend detected - do not trade
- ☕ **WAIT**: No clear signal - wait for better conditions

## Technical Indicators Displayed

- **Close Price**: Current stock price
- **RSI**: Relative Strength Index (14 period)
- **ADX**: Average Directional Index (14 period)
- **ADX Slope**: Trend acceleration indicator
- **BB Upper/Lower**: Bollinger Bands (20 period, 2 std dev)
- **Pin Bar**: Bullish pin bar pattern detection

## Troubleshooting

**Connection Error**: Make sure FutuOpenD is running and logged in

**No Data**: Check that the stock code is correct and the market is open

**Port Already in Use**: If port 5000 is busy, edit `app.py` and change the port number
