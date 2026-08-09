"""
engine.py
---------
Shared scan engine. scanner.py (weekly) and daily_scanner.py (daily) both
call run_scan() with their own ScanConfig - the fetching / indicator /
alerting / reporting logic itself doesn't care which timeframe it's on.

Skip-safety: nothing here assumes you run on a fixed schedule. Every run
re-downloads a full lookback window and recomputes Supertrend from
scratch, so there's nothing that can go "stale" or break if you miss a
day (or a week). See analyze_ticker() for exactly how that's handled.
"""

import json
import os
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import yfinance as yf

from supertrend import calculate_supertrend


@dataclass
class ScanConfig:
    label: str              # "Weekly" or "Daily" - shown in the report title
    interval: str            # yfinance interval: "1wk" or "1d"
    lookback_period: str     # yfinance period: e.g. "3y" or "1y"
    atr_period: int
    atr_multiplier: float
    stocks_file: str
    trades_file: str
    history_file: str
    output_dir: str
    min_bars_required: int = None

    def __post_init__(self):
        if self.min_bars_required is None:
            self.min_bars_required = self.atr_period + 5


# --------------------------------------------------------------------------
# IO helpers (timeframe-agnostic)
# --------------------------------------------------------------------------
def load_stock_list(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Watchlist not found: {path}")
    df = pd.read_csv(path)
    col = df.columns[0]
    tickers = (
        df[col]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .tolist()
    )
    seen = set()
    out = []
    for t in tickers:
        if t.upper() not in seen:
            seen.add(t.upper())
            out.append(t)
    return out


def load_trades(path):
    if not os.path.exists(path):
        return pd.DataFrame(
            columns=["Ticker", "EntryDate", "EntryPrice", "Quantity", "Status", "ExitDate", "ExitPrice", "Notes"]
        )
    df = pd.read_csv(path)
    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    df["Status"] = df["Status"].astype(str).str.strip().str.title()
    return df


def load_history(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_history(path, history):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(history, f, indent=2, default=str)


# --------------------------------------------------------------------------
# Data fetch + analysis
# --------------------------------------------------------------------------
def fetch_data(ticker, interval, period):
    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        if data is None or data.empty:
            return None
        return data.dropna(subset=["High", "Low", "Close"])
    except Exception:
        return None


def analyze_ticker(ticker, history_store, cfg: ScanConfig):
    """
    Returns a result dict describing this ticker's current Supertrend state.

    Two distinct signals are computed, on purpose:
      - "signal": a fresh BUY/SELL cross detected on the very latest bar
        (comparing the last two bars in the freshly-downloaded series).
        This is precise ("it flipped on this exact close") but says
        nothing about older flips.
      - "changed_since_last_run": True if the Bullish/Bearish state now
        differs from what was saved in history.json the last time you
        ran the scanner - regardless of which bar it actually flipped
        on. This is what keeps the tool safe to run irregularly: even
        if you skip several sessions and miss the exact flip bar, the
        next run will still tell you "this changed while you were away".
    "flip" (used for the table's Flip column / filter) is the union of
    both, so nothing slips through either way.
    """
    result = {
        "ticker": ticker,
        "status": "ok",
        "error": None,
        "close": None,
        "supertrend": None,
        "last_bar_date": None,
        "direction": None,
        "signal": "NONE",
        "last_recorded_direction": None,
        "last_recorded_signal": None,
        "last_recorded_date": None,
        "is_new": ticker not in history_store,
        "flip": False,
        "changed_since_last_run": False,
    }

    data = fetch_data(ticker, cfg.interval, cfg.lookback_period)
    if data is None or data.empty:
        result["status"] = "error"
        result["error"] = "No data returned (check ticker symbol / exchange suffix)"
        return result

    if len(data) < cfg.min_bars_required:
        result["status"] = "insufficient_data"
        result["error"] = f"Only {len(data)} bars available, need at least {cfg.min_bars_required}"
        return result

    st = calculate_supertrend(data, period=cfg.atr_period, multiplier=cfg.atr_multiplier)
    st = st.dropna(subset=["Supertrend"])
    if len(st) < 2:
        result["status"] = "insufficient_data"
        result["error"] = "Not enough valid Supertrend bars yet"
        return result

    last = st.iloc[-1]
    prev = st.iloc[-2]

    direction_now = "Bullish" if last["Direction"] == 1 else "Bearish"
    direction_prev = "Bullish" if prev["Direction"] == 1 else "Bearish"

    if direction_prev == "Bearish" and direction_now == "Bullish":
        signal_now = "BUY"
    elif direction_prev == "Bullish" and direction_now == "Bearish":
        signal_now = "SELL"
    else:
        signal_now = "NONE"

    prior = history_store.get(ticker)
    last_recorded_direction = prior.get("direction") if prior else None
    changed_since_last_run = (last_recorded_direction is not None) and (last_recorded_direction != direction_now)

    result.update(
        {
            "close": round(float(last["Close"]), 2),
            "supertrend": round(float(last["Supertrend"]), 2),
            "last_bar_date": last.name.strftime("%Y-%m-%d"),
            "direction": direction_now,
            "signal": signal_now,
            "last_recorded_direction": last_recorded_direction,
            "last_recorded_signal": prior.get("signal") if prior else None,
            "last_recorded_date": prior.get("last_run_date") if prior else None,
            "is_new": prior is None,
            "flip": (signal_now in ("BUY", "SELL")) or changed_since_last_run,
            "changed_since_last_run": changed_since_last_run,
        }
    )
    return result


def cross_reference_trades(results, trades_df):
    open_trades = trades_df[trades_df["Status"] == "Open"] if not trades_df.empty else trades_df
    for r in results:
        matches = open_trades[open_trades["Ticker"].str.upper() == r["ticker"].upper()] if not open_trades.empty else open_trades
        if matches is not None and len(matches) > 0:
            r["held"] = True
            r["open_trades"] = matches.to_dict("records")
            if r["close"] is not None:
                for t in r["open_trades"]:
                    try:
                        entry = float(t["EntryPrice"])
                        t["pnl_pct"] = round(((r["close"] - entry) / entry) * 100, 2)
                    except (ValueError, TypeError, KeyError):
                        t["pnl_pct"] = None
        else:
            r["held"] = False
            r["open_trades"] = []
    return results


def build_alerts(results):
    """
    Held stock, currently Bearish, and that's new information: either it
    crossed on the very latest bar (signal == SELL) or it was already
    Bearish by the time you checked but differs from what you last saw
    (changed_since_last_run). Either way you get told about it once -
    after this run updates history.json, it won't re-alert unless it
    flips again.
    """
    alerts = []
    for r in results:
        if r["status"] != "ok" or not r["held"] or r["direction"] != "Bearish":
            continue
        if r["signal"] == "SELL" or r["changed_since_last_run"]:
            alerts.append(r)
    return alerts


def update_history(history_store, results, run_date):
    for r in results:
        if r["status"] != "ok":
            continue
        history_store[r["ticker"]] = {
            "last_run_date": run_date,
            "direction": r["direction"],
            "signal": r["signal"],
            "close": r["close"],
            "supertrend": r["supertrend"],
        }
    return history_store


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_scan(cfg: ScanConfig):
    print(f"Supertrend {cfg.label} Scanner — ATR({cfg.atr_period}) x {cfg.atr_multiplier}, {cfg.interval} bars")
    run_date = date.today().isoformat()

    tickers = load_stock_list(cfg.stocks_file)
    if not tickers:
        print("No tickers found in stocks.csv — add some tickers first.")
        return None
    print(f"Watchlist: {len(tickers)} stocks")

    trades_df = load_trades(cfg.trades_file)
    history_store = load_history(cfg.history_file)

    results = []
    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i}/{len(tickers)}] {ticker} ...", end=" ")
        try:
            r = analyze_ticker(ticker, history_store, cfg)
        except Exception as e:
            r = {"ticker": ticker, "status": "error", "error": str(e)}
            traceback.print_exc()
        print(r.get("status"))
        results.append(r)
        time.sleep(0.3)  # be polite to the free data endpoint

    results = cross_reference_trades(results, trades_df)
    alerts = build_alerts(results)

    history_store = update_history(history_store, results, run_date)
    save_history(cfg.history_file, history_store)

    os.makedirs(cfg.output_dir, exist_ok=True)
    out_path = os.path.join(cfg.output_dir, f"report_{run_date}.html")

    from report import generate_html_report

    generate_html_report(
        results=results,
        alerts=alerts,
        run_date=run_date,
        atr_period=cfg.atr_period,
        atr_multiplier=cfg.atr_multiplier,
        output_path=out_path,
        timeframe_label=cfg.label,
    )
    print(f"\nReport written to: {out_path}")
    return out_path
