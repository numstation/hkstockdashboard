#!/bin/bash
# Run the Veteran scanner using the project venv (so yfinance, pandas_ta, etc. are found).
# First time: create venv and install deps (run these in Terminal):
#   cd /Users/chrislau/Documents/IT/backtest
#   python3 -m venv .venv
#   source .venv/bin/activate
#   pip install yfinance pandas ta schedule
# Then either:
#   ./run_scanner.sh HK
#   ./run_scanner.sh US
#   ./run_scanner.sh
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "No .venv found. Run:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install yfinance pandas pandas_ta schedule"
  exit 1
fi
.venv/bin/python daily_scanner.py "$@"
