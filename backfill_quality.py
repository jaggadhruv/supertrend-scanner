"""
backfill_quality.py
-------------------
One-off: walk data/flip_log.json and compute quality_score for entries
that were logged BEFORE the quality-score feature existed. After this
runs, every BUY flip in the last 7 days (that has enough Yahoo history)
will have a badge on it in the Recent Buy Flips panel.

    python backfill_quality.py

Idempotent — entries that already have a quality_score are skipped.
Slow: ~0.3s per entry. ATR params are read from scanner.py and
daily_scanner.py so a drift between here and the live scanner cannot
happen.
"""

import os
import time

import pandas as pd
import yfinance as yf

from engine import _compute_quality, load_flip_log, save_flip_log
from supertrend import calculate_supertrend
from scanner import CONFIG as WEEKLY_CONFIG
from daily_scanner import CONFIG as DAILY_CONFIG


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FLIP_LOG_PATH = os.path.join(BASE_DIR, "data", "flip_log.json")


def _cfg_for(timeframe: str):
    return WEEKLY_CONFIG if timeframe == "weekly" else DAILY_CONFIG


def _trim_to_flip_date(df: pd.DataFrame, flip_date: str) -> pd.DataFrame:
    target = pd.to_datetime(flip_date).tz_localize(None)
    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_localize(None)
    return df[idx <= target]


def score_entry(entry):
    ticker = entry["ticker"]
    tf = entry["timeframe"]
    flip_date = entry["flip_date"]
    cfg = _cfg_for(tf)
    data = yf.Ticker(ticker).history(
        period=cfg.lookback_period,
        interval=cfg.interval,
        auto_adjust=False,
    )
    if data is None or data.empty:
        return None
    data = data.dropna(subset=["High", "Low", "Close"])
    data = _trim_to_flip_date(data, flip_date)
    if len(data) < cfg.min_bars_required:
        return None
    st = calculate_supertrend(data, period=cfg.atr_period, multiplier=cfg.atr_multiplier)
    st = st.dropna(subset=["Supertrend"])
    if len(st) < 2:
        return None
    dir_series = st["Direction"].to_numpy()
    last_dir = dir_series[-1]
    bars_in_trend = 1
    for i in range(len(dir_series) - 2, -1, -1):
        if dir_series[i] == last_dir:
            bars_in_trend += 1
        else:
            break
    return _compute_quality(st, bars_in_trend)


def main():
    if not os.path.exists(FLIP_LOG_PATH):
        print(f"No flip log at {FLIP_LOG_PATH}. Nothing to backfill.")
        return
    log = load_flip_log(FLIP_LOG_PATH)
    if not log:
        print("Flip log is empty. Nothing to backfill.")
        return
    unscored = [e for e in log if e.get("quality_score") is None]
    if not unscored:
        print(f"All {len(log)} entry/entries already have quality_score.")
        return

    print(f"Backfilling quality_score for {len(unscored)} of {len(log)} entry/entries...")
    scored = skipped = errored = 0
    for i, e in enumerate(unscored, 1):
        label = f"[{i}/{len(unscored)}] {e['ticker']:<8} {e['timeframe']:<7} {e['flip_date']}"
        try:
            q = score_entry(e)
        except Exception as ex:
            print(f"{label}  ✗ error: {type(ex).__name__}: {ex}")
            errored += 1
            time.sleep(0.3)
            continue
        if q is None:
            print(f"{label}  · insufficient data, skipping")
            skipped += 1
        else:
            e.update(q)
            print(f"{label}  → score {q['quality_score']}")
            scored += 1
        time.sleep(0.3)

    save_flip_log(FLIP_LOG_PATH, log)
    print()
    print(f"Done. Scored: {scored}. Skipped: {skipped}. Errored: {errored}.")


if __name__ == "__main__":
    main()
