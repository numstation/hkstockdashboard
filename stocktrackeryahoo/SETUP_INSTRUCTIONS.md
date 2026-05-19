# HK-RangeBot Setup Instructions

## Step-by-Step Guide to Run the Trading Strategy

### Step 1: Install Python Dependencies

Open your terminal and navigate to the project directory, then install the required packages:

```bash
cd /Users/chrislau/Documents/IT/stocktracker
pip3 install -r requirements.txt
```

**Alternative if you prefer using a virtual environment (recommended):**
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

### Step 2: Set Up FutuOpenD

**You need to have FutuOpenD running before executing the script.**

1. **Download FutuOpenD** (if you haven't already):
   - Visit: https://www.futunn.com/download/openAPI
   - Download the FutuOpenD application for macOS

2. **Install and Launch FutuOpenD**:
   - Install the application
   - Launch FutuOpenD
   - It should start a server on `localhost:11111` by default

3. **Verify FutuOpenD is Running**:
   - You should see the FutuOpenD application window
   - Check that it's listening on port 11111
   - The status should show it's ready to accept connections

**Note:** You may need to log in with your Futu account credentials in FutuOpenD.

---

### Step 3: Configure the Stock Code (Optional)

If you want to analyze a different stock, edit `hk_rangebot.py`:

1. Open `hk_rangebot.py` in a text editor
2. Find this line (around line 120):
   ```python
   STOCK_CODE = 'HK.00700'  # Example: Tencent Holdings
   ```
3. Change it to your desired stock code, for example:
   - `'HK.00700'` - Tencent Holdings
   - `'HK.09988'` - Alibaba
   - `'HK.03690'` - Meituan
   - Any other HK stock code

---

### Step 4: Run the Script

Once FutuOpenD is running, execute the script:

```bash
python3 hk_rangebot.py
```

**Or if you're using a virtual environment:**
```bash
source venv/bin/activate
python3 hk_rangebot.py
```

---

### Step 5: Understand the Output

The script will display:

1. **Connection Status**: Confirms connection to FutuOpenD
2. **Data Fetching**: Shows how many days of data were retrieved
3. **Latest Indicator Values**: 
   - Close Price
   - RSI (Relative Strength Index)
   - ADX (Average Directional Index)
   - ADX Slope (trend acceleration)
   - Bollinger Bands (Upper and Lower)
   - Bullish Pin Bar detection
4. **Trading Advice**: One of four possible outputs:
   - ⚠️ **WARNING**: Strong trend detected - DO NOT TRADE
   - 🟢 **SIGNAL: SHORT PUT**: Oversold conditions detected
   - 🔴 **SIGNAL: SHORT CALL**: Overbought conditions detected
   - ☕ **WAIT**: No clear signal

---

### Troubleshooting

**Error: "Failed to connect to FutuOpenD"**
- Make sure FutuOpenD is running
- Check that it's listening on port 11111
- Verify your firewall isn't blocking the connection

**Error: "No data returned"**
- Check that the stock code is correct
- Ensure you have market data access in FutuOpenD
- Try a different stock code

**Error: "Missing indicator data"**
- This usually means there isn't enough historical data
- The script needs at least 20-30 days of data for accurate indicators
- Try a more liquid stock

**ModuleNotFoundError**
- Make sure you installed all dependencies: `pip3 install -r requirements.txt`
- If using a virtual environment, make sure it's activated

---

### Next Steps

Once the script runs successfully, you can:

1. **Automate it**: Set up a cron job or scheduler to run it periodically
2. **Extend it**: Add more stocks, email notifications, or logging
3. **Backtest**: Modify the script to test the strategy on historical data
4. **Integrate**: Connect it to your trading platform for automated execution

---

### Important Notes

⚠️ **This is a trading strategy script for educational purposes. Always:**
- Test thoroughly before using with real money
- Understand the risks involved
- Consider transaction costs and slippage
- Consult with a financial advisor if needed
- Never risk more than you can afford to lose
