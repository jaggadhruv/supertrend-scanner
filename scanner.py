"""
scanner.py
----------
Weekly Supertrend positional-trade scan. Run this file directly:

    python scanner.py

Best run on a weekend, after Friday's close, so every weekly candle is
fully closed. Uses the shared logic in engine.py. Writes its report to
output/weekly/report_<date>.html and remembers state in
data/weekly_history.json.
"""

import os
from engine import ScanConfig, run_scan

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG = ScanConfig(
    label="Weekly",
    interval="1wk",
    lookback_period="3y",       # ~3 years of weekly bars
    atr_period=10,
    atr_multiplier=2.5,
    stocks_file=os.path.join(BASE_DIR, "stocks.csv"),
    trades_file=os.path.join(BASE_DIR, "trades.csv"),
    history_file=os.path.join(BASE_DIR, "data", "weekly_history.json"),
    output_dir=os.path.join(BASE_DIR, "output", "weekly"),
)

if __name__ == "__main__":
    run_scan(CONFIG)
