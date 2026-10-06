"""
daily_scanner.py
----------------
Daily Supertrend scan. Run this file directly:

    python daily_scanner.py

Best run after market close for a fully-formed daily candle. Reads
tickers from stocks.csv — same list as scanner.py uses. Edit stocks.csv
to add or remove names.
"""

import os
from engine import ScanConfig, run_scan

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG = ScanConfig(
    label="Daily",
    interval="1d",
    lookback_period="1y",
    atr_period=10,
    atr_multiplier=2.5,
    stocks_file=os.path.join(BASE_DIR, "stocks.csv"),
    trades_file=os.path.join(BASE_DIR, "trades.csv"),
    history_file=os.path.join(BASE_DIR, "data", "daily_history.json"),
    output_dir=os.path.join(BASE_DIR, "output", "daily"),
)

if __name__ == "__main__":
    run_scan(CONFIG)
