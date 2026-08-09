"""
daily_scanner.py
----------------
Daily Supertrend scan - same indicator, same watchlist and trade log, just
running on daily candles instead of weekly. Run this file directly:

    python daily_scanner.py

Best run after market close for a fully-formed daily candle. Completely
manual, like scanner.py - nothing runs unless you run it, and nothing
breaks if you skip a day (or several). Every run re-downloads a fresh
lookback window and recomputes everything from scratch, and any flip you
missed while away still gets caught (see "changed_since_last_run" in
engine.py / the "Flip" column in the report).

Writes its report to output/daily/report_<date>.html and remembers state
in data/daily_history.json - completely separate from the weekly scan, so
running one never affects the other.
"""

import os
from engine import ScanConfig, run_scan

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG = ScanConfig(
    label="Daily",
    interval="1d",
    lookback_period="1y",       # ~1 year of daily bars, plenty for ATR(10) to settle
    atr_period=10,
    atr_multiplier=2.5,
    stocks_file=os.path.join(BASE_DIR, "stocks.csv"),
    trades_file=os.path.join(BASE_DIR, "trades.csv"),
    history_file=os.path.join(BASE_DIR, "data", "daily_history.json"),
    output_dir=os.path.join(BASE_DIR, "output", "daily"),
)

if __name__ == "__main__":
    run_scan(CONFIG)
