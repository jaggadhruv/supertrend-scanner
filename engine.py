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
import re
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta

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
# Flip log — a persistent, timeframe-spanning record of every BUY/SELL flip
#
# Every entry point (scanner.py, daily_scanner.py, combined_scanner.py) feeds
# the SAME file: data/flip_log.json (path derived from cfg.history_file's
# directory). Entries are deduplicated on (ticker, timeframe, flip_date) so
# it's safe to re-run any scanner as often as you like.
# --------------------------------------------------------------------------
FLIP_LOG_MAX_AGE_DAYS = 180


def _flip_log_path(cfg: "ScanConfig") -> str:
    """Both weekly and daily scanners share one flip log next to their histories."""
    return os.path.join(os.path.dirname(cfg.history_file), "flip_log.json")


def load_flip_log(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_flip_log(path: str, log: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(log, f, indent=2, default=str)


def record_flips(cfg: "ScanConfig", results: list, run_date: str,
                 max_age_days: int = FLIP_LOG_MAX_AGE_DAYS) -> int:
    """
    Append fresh BUY/SELL flips (r["signal"] in {"BUY","SELL"}) to
    data/flip_log.json. Dedupes on (ticker, timeframe, flip_date), prunes
    entries older than max_age_days, and re-sorts newest first. Returns
    the number of NEW entries added on this call.
    """
    path = _flip_log_path(cfg)
    log = load_flip_log(path)
    timeframe = cfg.label.lower()  # "weekly" | "daily"

    existing = {(e.get("ticker"), e.get("timeframe"), e.get("flip_date")) for e in log}
    added = 0
    for r in results:
        if r.get("status") != "ok":
            continue
        if r.get("signal") not in ("BUY", "SELL"):
            continue
        key = (r["ticker"], timeframe, r["last_bar_date"])
        if key in existing:
            continue
        log.append({
            "ticker": r["ticker"],
            "timeframe": timeframe,
            "direction": r["direction"],
            "signal": r["signal"],
            "flip_date": r["last_bar_date"],   # the actual bar the flip landed on
            "recorded_at": run_date,           # the run that first saw it
            "close": r.get("close"),
            "supertrend": r.get("supertrend"),
        })
        existing.add(key)
        added += 1

    # Prune anything older than the cutoff so the file stays bounded.
    try:
        cutoff = (date.fromisoformat(run_date) - timedelta(days=max_age_days)).isoformat()
    except ValueError:
        cutoff = "0000-00-00"
    log = [e for e in log if (e.get("flip_date") or "0000-00-00") >= cutoff]

    # Newest first — the report reads this file top-down.
    log.sort(key=lambda e: (e.get("flip_date") or "", e.get("recorded_at") or ""), reverse=True)

    save_flip_log(path, log)
    return added


# --------------------------------------------------------------------------
# Output-folder cleanup
#
# Report files pile up: one HTML per run per timeframe. This helper deletes
# report_YYYY-MM-DD.html files whose date is older than `days` from run_date,
# so `output/weekly/`, `output/daily/`, `output/combined/`, and the published
# `docs/reports/` folder stay bounded.
# --------------------------------------------------------------------------
_REPORT_FILENAME_RE = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.html$")


def prune_old_reports(output_dir: str, days: int = 30, run_date: str = None) -> int:
    """
    Delete report_YYYY-MM-DD.html files whose date is more than `days`
    days before run_date. Returns the number of files removed. Silent if
    the directory doesn't exist. Anything not matching the report_<date>.html
    pattern (README.txt, index.html, subfolders, ad-hoc files) is left alone.
    """
    if not os.path.isdir(output_dir):
        return 0
    if run_date is None:
        run_date = date.today().isoformat()
    try:
        cutoff = (date.fromisoformat(run_date) - timedelta(days=days)).isoformat()
    except ValueError:
        return 0

    removed = 0
    for name in os.listdir(output_dir):
        m = _REPORT_FILENAME_RE.match(name)
        if not m:
            continue
        if m.group(1) < cutoff:
            try:
                os.remove(os.path.join(output_dir, name))
                removed += 1
            except OSError:
                pass
    return removed


def recent_flips(log: list, days: int = 7, run_date: str | None = None):
    """
    Filter to flips whose flip_date is within `days` calendar days of
    run_date (defaults to today). Preserves the log's existing sort order
    (newest first).
    """
    if run_date is None:
        run_date = date.today().isoformat()
    try:
        cutoff = (date.fromisoformat(run_date) - timedelta(days=days)).isoformat()
    except ValueError:
        return []
    return [e for e in log if (e.get("flip_date") or "") >= cutoff]


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
        "bars_in_trend": None,     # how many consecutive most-recent bars share the current direction
        "trend_start_date": None,  # date of the first bar in that run (i.e. the bar the trend started on)
        "bar_unit": "d" if cfg.interval.endswith("d") else "w",
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

    # How long the current trend has been running: walk back from the last
    # bar and count consecutive bars that share the current direction. The
    # count includes the last bar itself, so a fresh flip today reads as 1.
    dir_series = st["Direction"].to_numpy()
    last_dir = dir_series[-1]
    bars_in_trend = 1
    for i in range(len(dir_series) - 2, -1, -1):
        if dir_series[i] == last_dir:
            bars_in_trend += 1
        else:
            break
    trend_start_idx = len(dir_series) - bars_in_trend
    trend_start_date = st.index[trend_start_idx].strftime("%Y-%m-%d")

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
            "bars_in_trend": bars_in_trend,
            "trend_start_date": trend_start_date,
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
def run_analysis(cfg: ScanConfig, verbose: bool = True):
    """
    Runs the fetch + Supertrend + trade-cross-reference pipeline for one
    timeframe and returns everything needed downstream. Pure with respect
    to disk beyond the reads it does - it does NOT write history or any
    report. Callers decide when to save state and how (or whether) to
    render output.

    Returns a dict:
      {
        "cfg": ScanConfig,
        "run_date": "YYYY-MM-DD",
        "results": [...],       # per-ticker result dicts, trades already cross-referenced
        "alerts": [...],        # held bearish alerts derived from results
        "history_store": {...}, # the PRIOR history read from disk (not yet updated)
      }

    Returns None if the watchlist is empty (mirrors run_scan's behaviour).
    """
    if verbose:
        print(f"Supertrend {cfg.label} Scanner — ATR({cfg.atr_period}) x {cfg.atr_multiplier}, {cfg.interval} bars")
    run_date = date.today().isoformat()

    tickers = load_stock_list(cfg.stocks_file)
    if not tickers:
        if verbose:
            print("No tickers found in stocks.csv — add some tickers first.")
        return None
    if verbose:
        print(f"Watchlist: {len(tickers)} stocks")

    trades_df = load_trades(cfg.trades_file)
    history_store = load_history(cfg.history_file)

    results = []
    for i, ticker in enumerate(tickers, 1):
        if verbose:
            print(f"  [{i}/{len(tickers)}] {ticker} ...", end=" ")
        try:
            r = analyze_ticker(ticker, history_store, cfg)
        except Exception as e:
            r = {"ticker": ticker, "status": "error", "error": str(e)}
            traceback.print_exc()
        if verbose:
            print(r.get("status"))
        results.append(r)
        time.sleep(0.3)  # be polite to the free data endpoint

    results = cross_reference_trades(results, trades_df)
    alerts = build_alerts(results)

    return {
        "cfg": cfg,
        "run_date": run_date,
        "results": results,
        "alerts": alerts,
        "history_store": history_store,
    }


def commit_history(cfg: ScanConfig, scan: dict) -> None:
    """Advance the on-disk history store using this run's results."""
    updated = update_history(scan["history_store"], scan["results"], scan["run_date"])
    save_history(cfg.history_file, updated)


def run_scan(cfg: ScanConfig):
    """
    One-timeframe scan: analyze, save history, append any fresh flips to
    the shared flip log, and render the individual HTML report to
    cfg.output_dir. Used by scanner.py and daily_scanner.py.
    combined_scanner.py bypasses this and drives run_analysis directly so
    it can produce a single merged report instead (and records flips itself).
    """
    scan = run_analysis(cfg)
    if scan is None:
        return None

    commit_history(cfg, scan)
    added = record_flips(cfg, scan["results"], scan["run_date"])
    if added:
        print(f"Flip log: +{added} new {cfg.label.lower()} flip(s) recorded")

    # Keep this timeframe's output folder bounded — deletes report_*.html
    # dated more than 30 days before this run. Only touches files matching
    # our own naming convention, never anything else.
    removed = prune_old_reports(cfg.output_dir, days=30, run_date=scan["run_date"])
    if removed:
        print(f"Cleanup: removed {removed} report(s) older than 30 days from {cfg.output_dir}")

    os.makedirs(cfg.output_dir, exist_ok=True)
    out_path = os.path.join(cfg.output_dir, f"report_{scan['run_date']}.html")

    from report import generate_html_report

    generate_html_report(
        results=scan["results"],
        alerts=scan["alerts"],
        run_date=scan["run_date"],
        atr_period=cfg.atr_period,
        atr_multiplier=cfg.atr_multiplier,
        output_path=out_path,
        timeframe_label=cfg.label,
    )
    print(f"\nReport written to: {out_path}")
    return out_path
