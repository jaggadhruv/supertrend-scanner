"""
engine.py
---------
Shared scan engine. scanner.py (weekly), daily_scanner.py (daily), and
combined_scanner.py all call run_analysis()/run_scan() with their own
ScanConfig. The fetching, indicator math, alerting, flip logging, and
cleanup logic doesn't care which timeframe it's on.

Skip-safety: nothing here assumes you run on a fixed schedule. Every
run re-downloads a full lookback window and recomputes Supertrend from
scratch, so there's nothing that can go "stale" or break if you miss a
day (or a week). See analyze_ticker() for exactly how that's handled.

Watchlist layering: cfg.stocks_file can be a single CSV path OR a list
of CSV paths. All of them are read, deduped (case-insensitive on the
ticker), and merged in list order. Missing files are silently skipped
so you can refer to data/universe.csv even on a brand-new repo.

Flip log: data/flip_log.json records every BUY/SELL flip across runs.
BUY logging is gated on quality_score >= min_quality (default 60) so
noise doesn't accumulate. SELL logging has no quality gate because the
held-bearish alert path depends on it.
"""

import json
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Union, List, Optional, Set

import pandas as pd
import yfinance as yf

from supertrend import calculate_supertrend


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
@dataclass
class ScanConfig:
    label: str                # "Weekly" or "Daily" - shown in the report title
    interval: str              # yfinance interval: "1wk" or "1d"
    lookback_period: str       # yfinance period: e.g. "3y" or "1y"
    atr_period: int
    atr_multiplier: float
    stocks_file: Union[str, List[str]]   # single path or list of paths; see load_stock_list
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
def load_stock_list(path_or_paths):
    """
    Load tickers from one CSV or a list of CSVs. Dedupes case-insensitively
    while preserving first-seen order. Missing files are silently skipped —
    useful because data/universe.csv won't exist until refresh_universe.py
    has run at least once.

    Each CSV must have a header row and tickers in the first column.
    Raises FileNotFoundError only if NO source could be read.
    """
    paths = [path_or_paths] if isinstance(path_or_paths, str) else list(path_or_paths)
    seen = set()
    out = []
    read_any = False
    for path in paths:
        if not os.path.exists(path):
            continue
        read_any = True
        df = pd.read_csv(path)
        if df.empty or len(df.columns) == 0:
            continue
        col = df.columns[0]
        for t in df[col].dropna().astype(str):
            t = t.strip()
            if not t:
                continue
            key = t.upper()
            if key not in seen:
                seen.add(key)
                out.append(t)
    if not read_any:
        raise FileNotFoundError(f"No watchlist file found. Looked in: {paths}")
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
# Flip log
# --------------------------------------------------------------------------
FLIP_LOG_MAX_AGE_DAYS = 180
DEFAULT_MIN_FLIP_QUALITY = 60      # BUY flips below this score are not logged
WEEKLY_CONFLUENCE_BONUS = 15       # extra quality for daily BUYs whose weekly agrees


def _flip_log_path(cfg: "ScanConfig") -> str:
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
                 min_quality: Optional[int] = None,
                 weekly_bullish_tickers: Optional[Set[str]] = None,
                 max_age_days: int = FLIP_LOG_MAX_AGE_DAYS) -> dict:
    """
    Append fresh BUY/SELL flips to data/flip_log.json. Dedupes on
    (ticker, timeframe, flip_date), prunes entries older than
    max_age_days, and re-sorts newest first.

    Quality gate (BUY only):
      - If min_quality is set, a BUY is logged only when its final
        quality_score (after weekly-confluence boost) is >= min_quality.
      - SELLs are always logged — the held-bearish alert depends on
        them regardless of score.

    Weekly confluence boost (daily BUYs only):
      - If weekly_bullish_tickers is provided, any daily BUY whose
        ticker is in that set gets a +WEEKLY_CONFLUENCE_BONUS boost on
        its logged quality_score, capped at 100. The boosted value is
        what the quality gate above checks.

    Returns a dict: {"added": int, "skipped_low_quality": int}.
    """
    path = _flip_log_path(cfg)
    log = load_flip_log(path)
    timeframe = cfg.label.lower()  # "weekly" | "daily"

    existing = {(e.get("ticker"), e.get("timeframe"), e.get("flip_date")) for e in log}
    added = 0
    skipped_low_q = 0
    for r in results:
        if r.get("status") != "ok":
            continue
        if r.get("signal") not in ("BUY", "SELL"):
            continue
        key = (r["ticker"], timeframe, r["last_bar_date"])
        if key in existing:
            continue

        # Base quality + optional weekly-confluence boost (daily BUYs only)
        base_q = r.get("quality_score")
        boosted_q = base_q
        has_confluence = False
        if (base_q is not None
                and timeframe == "daily"
                and r.get("signal") == "BUY"
                and weekly_bullish_tickers is not None
                and r["ticker"] in weekly_bullish_tickers):
            boosted_q = min(100, int(base_q) + WEEKLY_CONFLUENCE_BONUS)
            has_confluence = True

        # Quality gate (BUY only) — low-quality BUYs are detected but not
        # persisted. The user still sees them this run if the report
        # happens to look at results directly, but they don't accumulate.
        if (min_quality is not None
                and r.get("signal") == "BUY"
                and boosted_q is not None
                and boosted_q < min_quality):
            skipped_low_q += 1
            continue

        log.append({
            "ticker": r["ticker"],
            "timeframe": timeframe,
            "direction": r["direction"],
            "signal": r["signal"],
            "flip_date": r["last_bar_date"],
            "recorded_at": run_date,
            "close": r.get("close"),
            "supertrend": r.get("supertrend"),
            "quality_score": boosted_q,
            "quality_base_score": base_q,
            "quality_volume_ratio": r.get("quality_volume_ratio"),
            "quality_momentum_pct": r.get("quality_momentum_pct"),
            "quality_prior_run": r.get("quality_prior_run"),
            "weekly_confluence": has_confluence,
        })
        existing.add(key)
        added += 1

    # Prune anything older than the cutoff so the file stays bounded.
    try:
        cutoff = (date.fromisoformat(run_date) - timedelta(days=max_age_days)).isoformat()
    except ValueError:
        cutoff = "0000-00-00"
    log = [e for e in log if (e.get("flip_date") or "0000-00-00") >= cutoff]

    log.sort(key=lambda e: (e.get("flip_date") or "", e.get("recorded_at") or ""), reverse=True)
    save_flip_log(path, log)
    return {"added": added, "skipped_low_quality": skipped_low_q}


def recent_flips(log: list, days: int = 7, run_date: Optional[str] = None):
    """Filter to flips within `days` calendar days of run_date."""
    if run_date is None:
        run_date = date.today().isoformat()
    try:
        cutoff = (date.fromisoformat(run_date) - timedelta(days=days)).isoformat()
    except ValueError:
        return []
    return [e for e in log if (e.get("flip_date") or "") >= cutoff]


# --------------------------------------------------------------------------
# Output-folder cleanup
# --------------------------------------------------------------------------
_REPORT_FILENAME_RE = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.html$")


def prune_old_reports(output_dir: str, days: int = 30, run_date: Optional[str] = None) -> int:
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


def _compute_quality(st_df, bars_in_trend: int):
    """
    Rate the current trend's quality as a 0-100 score. Three components:
      - Volume surge (0-35): latest bar vol / 20-bar avg
      - 5-bar momentum (0-30): % change over last 5 bars
      - Prior-trend maturity (0-35): length of opposite-direction run
    See _compute_quality's inline comments for the exact bands.
    """
    n = len(st_df)

    # Volume
    vol_ratio = None
    if "Volume" in st_df.columns and n >= 20:
        try:
            recent_vol = float(st_df["Volume"].iloc[-1])
            avg_vol = float(st_df["Volume"].iloc[-20:].mean())
            vol_ratio = recent_vol / avg_vol if avg_vol > 0 else None
        except (TypeError, ValueError):
            vol_ratio = None
    if vol_ratio is None:   vol_score = 15
    elif vol_ratio >= 2.0:  vol_score = 35
    elif vol_ratio >= 1.5:  vol_score = 28
    elif vol_ratio >= 1.2:  vol_score = 22
    elif vol_ratio >= 1.0:  vol_score = 15
    else:                   vol_score = 7

    # Momentum
    mom_pct = None
    if n >= 6:
        try:
            c5 = float(st_df["Close"].iloc[-6])
            c_now = float(st_df["Close"].iloc[-1])
            if c5 > 0:
                mom_pct = (c_now / c5 - 1.0) * 100.0
        except (TypeError, ValueError):
            mom_pct = None
    if mom_pct is None:   mom_score = 12
    elif mom_pct >= 5:    mom_score = 30
    elif mom_pct >= 2:    mom_score = 22
    elif mom_pct >= 0:    mom_score = 12
    elif mom_pct >= -2:   mom_score = 5
    else:                 mom_score = 0

    # Prior-trend maturity
    prior_run = 0
    try:
        dir_series = st_df["Direction"].to_numpy()
        current_dir = dir_series[-1]
        end_of_prior = n - bars_in_trend - 1
        if end_of_prior >= 0:
            prior_dir = dir_series[end_of_prior]
            if prior_dir != current_dir:
                for i in range(end_of_prior, -1, -1):
                    if dir_series[i] == prior_dir:
                        prior_run += 1
                    else:
                        break
    except (KeyError, IndexError, TypeError, ValueError):
        prior_run = 0

    if   prior_run >= 15: mat_score = 35
    elif prior_run >= 10: mat_score = 28
    elif prior_run >= 5:  mat_score = 20
    elif prior_run >= 3:  mat_score = 12
    elif prior_run >= 1:  mat_score = 5
    else:                 mat_score = 0

    return {
        "quality_score": int(vol_score + mom_score + mat_score),
        "quality_volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "quality_momentum_pct": round(mom_pct, 2) if mom_pct is not None else None,
        "quality_prior_run": int(prior_run),
    }


def analyze_ticker(ticker, history_store, cfg: ScanConfig):
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
        "bars_in_trend": None,
        "trend_start_date": None,
        "bar_unit": "d" if cfg.interval.endswith("d") else "w",
        "quality_score": None,
        "quality_volume_ratio": None,
        "quality_momentum_pct": None,
        "quality_prior_run": None,
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

    quality = _compute_quality(st, bars_in_trend)

    result.update({
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
        **quality,
    })
    return result


def cross_reference_trades(results, trades_df):
    open_trades = trades_df[trades_df["Status"] == "Open"] if not trades_df.empty else trades_df
    for r in results:
        matches = open_trades[open_trades["Ticker"].str.upper() == r["ticker"].upper()] if not open_trades.empty else open_trades
        if matches is not None and len(matches) > 0:
            r["held"] = True
            r["open_trades"] = matches.to_dict("records")
            if r.get("close") is not None:
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
    alerts = []
    for r in results:
        if r.get("status") != "ok" or not r.get("held") or r.get("direction") != "Bearish":
            continue
        if r.get("signal") == "SELL" or r.get("changed_since_last_run"):
            alerts.append(r)
    return alerts


def update_history(history_store, results, run_date):
    for r in results:
        if r.get("status") != "ok":
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
    if verbose:
        print(f"Supertrend {cfg.label} Scanner — ATR({cfg.atr_period}) x {cfg.atr_multiplier}, {cfg.interval} bars")
    run_date = date.today().isoformat()

    tickers = load_stock_list(cfg.stocks_file)
    if not tickers:
        if verbose:
            print("No tickers found — add some to stocks.csv first.")
        return None
    if verbose:
        src_count = 1 if isinstance(cfg.stocks_file, str) else len([p for p in cfg.stocks_file if os.path.exists(p)])
        print(f"Watchlist: {len(tickers)} unique stocks from {src_count} source(s)")

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
        time.sleep(0.3)

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
    updated = update_history(scan["history_store"], scan["results"], scan["run_date"])
    save_history(cfg.history_file, updated)


def _min_quality_from_env():
    """MIN_FLIP_QUALITY env var overrides the default. Clamped to [0, 100]."""
    try:
        raw = os.environ.get("MIN_FLIP_QUALITY")
        if raw is None:
            return DEFAULT_MIN_FLIP_QUALITY
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_MIN_FLIP_QUALITY


def run_scan(cfg: ScanConfig):
    """
    One-timeframe scan path (scanner.py / daily_scanner.py). Running a
    single timeframe can't do the weekly-confluence boost - that needs
    both scans at once (combined_scanner.py). So BUY flips here are
    gated purely on their base quality score.
    """
    scan = run_analysis(cfg)
    if scan is None:
        return None

    commit_history(cfg, scan)

    min_q = _min_quality_from_env()
    stats = record_flips(cfg, scan["results"], scan["run_date"], min_quality=min_q)
    msg_bits = []
    if stats["added"]:
        msg_bits.append(f"+{stats['added']} new {cfg.label.lower()} flip(s)")
    if stats["skipped_low_quality"]:
        msg_bits.append(f"skipped {stats['skipped_low_quality']} BUY(s) below quality {min_q}")
    if msg_bits:
        print("Flip log: " + ", ".join(msg_bits))

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
