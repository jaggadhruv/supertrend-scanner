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
            "quality_momentum_10_pct": r.get("quality_momentum_10_pct"),
            "quality_prior_run": r.get("quality_prior_run"),
            "quality_rsi": r.get("quality_rsi"),
            "quality_high_distance_pct": r.get("quality_high_distance_pct"),
            "atr_value": r.get("atr_value"),
            "high_20":   r.get("high_20"),
            "low_20":    r.get("low_20"),
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
    Rate the current trend's quality as a 0-100 score. Used to decide
    which BUY/SELL flips are worth logging (vs. being noise) and to
    rank the flips that are logged.

    Revised five-component formulation:

      1. Volume accumulation (0-25) — 5-bar avg vol / 20-bar avg vol.
         Catches sustained accumulation over a week, not just a single
         climactic bar that could be a liquidation.
      2. Momentum consistency (0-30) — looks at BOTH 5-bar and 10-bar
         % change. Both-positive-and-strong beats a single-day spike.
      3. Prior-trend maturity (0-20) — length of the opposite-direction
         run right before the current one. Still the whipsaw filter.
      4. RSI condition (0-15) — Wilder RSI(14). For a BULL trend, 50-65
         is the sweet spot (confirmed momentum with room to run). >75
         is overbought / late. For a BEAR trend, 35-50 is the sweet
         spot (confirmed weakness with room to fall).
      5. Breakout proximity (0-10) — close vs. 20-bar high (for a bull
         trend) or 20-bar low (bear trend). Rewards flips that are
         confirming a real breakout, not a mid-range crossover.

    All components fail gracefully: if a field is missing (short history,
    no Volume column, flat series) that component falls back to a
    neutral partial-credit score instead of crashing.
    """
    n = len(st_df)
    try:
        current_dir = int(st_df["Direction"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        current_dir = 1
    current_bullish = (current_dir == 1)

    # ------------------------------------------------------------------
    # 1. Volume accumulation (0-25)
    # ------------------------------------------------------------------
    vol_accum = None
    if "Volume" in st_df.columns and n >= 20:
        try:
            avg5 = float(st_df["Volume"].iloc[-5:].mean())
            avg20 = float(st_df["Volume"].iloc[-20:].mean())
            vol_accum = avg5 / avg20 if avg20 > 0 else None
        except (TypeError, ValueError):
            vol_accum = None
    if   vol_accum is None:    vol_score = 10
    elif vol_accum >= 1.5:     vol_score = 25
    elif vol_accum >= 1.2:     vol_score = 20
    elif vol_accum >= 1.0:     vol_score = 12
    elif vol_accum >= 0.8:     vol_score = 7
    else:                      vol_score = 2

    # ------------------------------------------------------------------
    # 2. Momentum consistency (0-30) — 5-bar AND 10-bar return
    # ------------------------------------------------------------------
    mom5 = mom10 = None
    if n >= 11:
        try:
            c_now = float(st_df["Close"].iloc[-1])
            c5    = float(st_df["Close"].iloc[-6])
            c10   = float(st_df["Close"].iloc[-11])
            if c5  > 0: mom5  = (c_now / c5  - 1.0) * 100.0
            if c10 > 0: mom10 = (c_now / c10 - 1.0) * 100.0
        except (TypeError, ValueError, IndexError):
            pass

    def _mom_score_for(sig_bullish, m5, m10):
        if m5 is None or m10 is None:
            return 12
        if sig_bullish:
            if   m5 >=  3 and m10 >=  5:  return 30   # both windows strong
            elif m5 >=  3 and m10 >=  0:  return 24   # strong short-term, flat 10-bar
            elif m5 >=  0 and m10 >=  5:  return 22   # slow build
            elif m5 >=  0 and m10 >=  0:  return 14   # mild positive
            elif m5 >= -2 and m10 >= -2:  return 6
            else:                         return 0
        else:  # bearish: mirror the signs
            if   m5 <= -3 and m10 <= -5:  return 30
            elif m5 <= -3 and m10 <=  0:  return 24
            elif m5 <=  0 and m10 <= -5:  return 22
            elif m5 <=  0 and m10 <=  0:  return 14
            elif m5 <=  2 and m10 <=  2:  return 6
            else:                         return 0
    mom_score = _mom_score_for(current_bullish, mom5, mom10)

    # ------------------------------------------------------------------
    # 3. Prior-trend maturity (0-20)
    # ------------------------------------------------------------------
    prior_run = 0
    try:
        dir_series = st_df["Direction"].to_numpy()
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

    if   prior_run >= 15: mat_score = 20
    elif prior_run >= 10: mat_score = 16
    elif prior_run >= 5:  mat_score = 11
    elif prior_run >= 3:  mat_score = 6
    elif prior_run >= 1:  mat_score = 2
    else:                 mat_score = 0

    # ------------------------------------------------------------------
    # 4. RSI(14) condition (0-15) — favour confirmed-but-not-extended
    # ------------------------------------------------------------------
    rsi = None
    if n >= 15:
        try:
            close = st_df["Close"].astype(float)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
            last_gain = float(avg_gain.iloc[-1])
            last_loss = float(avg_loss.iloc[-1])
            if last_loss > 0:
                rs = last_gain / last_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
            elif last_gain > 0:
                rsi = 100.0  # all-up window
            else:
                rsi = 50.0
        except (TypeError, ValueError, IndexError, KeyError):
            rsi = None

    if rsi is None:
        rsi_score = 7
    elif current_bullish:
        if   50 <= rsi <= 65:                  rsi_score = 15
        elif 45 <= rsi <  50 or 65 < rsi <= 70: rsi_score = 11
        elif 40 <= rsi <  45 or 70 < rsi <= 75: rsi_score = 7
        elif rsi > 75:                          rsi_score = 2   # overbought
        else:                                   rsi_score = 4   # too weak for a bull
    else:  # bearish: mirror
        if   35 <= rsi <= 50:                  rsi_score = 15
        elif 30 <= rsi <  35 or 50 < rsi <= 55: rsi_score = 11
        elif 25 <= rsi <  30 or 55 < rsi <= 60: rsi_score = 7
        elif rsi < 25:                          rsi_score = 2   # oversold
        else:                                   rsi_score = 4

    # ------------------------------------------------------------------
    # 5. Breakout proximity (0-10) — close vs 20-bar high / low
    # ------------------------------------------------------------------
    hl_pct = None
    if n >= 20:
        try:
            close_now = float(st_df["Close"].iloc[-1])
            if current_bullish:
                high_20 = float(st_df["High"].iloc[-20:].max())
                if high_20 > 0:
                    hl_pct = (close_now - high_20) / high_20 * 100.0
                if   hl_pct is None:  hl_score = 5
                elif hl_pct >=  0:    hl_score = 10   # new 20-bar high
                elif hl_pct >= -2:    hl_score = 7    # within 2% of high
                elif hl_pct >= -5:    hl_score = 4
                else:                 hl_score = 1
            else:
                low_20 = float(st_df["Low"].iloc[-20:].min())
                if low_20 > 0:
                    hl_pct = (close_now - low_20) / low_20 * 100.0
                if   hl_pct is None:  hl_score = 5
                elif hl_pct <=  0:    hl_score = 10   # new 20-bar low
                elif hl_pct <=  2:    hl_score = 7
                elif hl_pct <=  5:    hl_score = 4
                else:                 hl_score = 1
        except (TypeError, ValueError, IndexError, KeyError):
            hl_score = 5
            hl_pct = None
    else:
        hl_score = 5

    total = vol_score + mom_score + mat_score + rsi_score + hl_score
    # Levels for the Entry & SL block on cards: latest ATR (for stops) and
    # 20-bar high/low (for targets).
    atr_value = None
    try:
        atr_value = float(st_df["ATR"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        atr_value = None
    high_20 = low_20 = None
    try:
        if n >= 20:
            high_20 = float(st_df["High"].iloc[-20:].max())
            low_20  = float(st_df["Low"].iloc[-20:].min())
    except (KeyError, IndexError, TypeError, ValueError):
        pass

    return {
        "quality_score": int(total),
        "quality_volume_ratio": round(vol_accum, 2) if vol_accum is not None else None,
        "quality_momentum_pct": round(mom5, 2) if mom5 is not None else None,
        "quality_momentum_10_pct": round(mom10, 2) if mom10 is not None else None,
        "quality_prior_run": int(prior_run),
        "quality_rsi": round(rsi, 1) if rsi is not None else None,
        "quality_high_distance_pct": round(hl_pct, 2) if hl_pct is not None else None,
        "atr_value":  round(atr_value, 4) if atr_value is not None else None,
        "high_20":    round(high_20, 2) if high_20 is not None else None,
        "low_20":     round(low_20, 2) if low_20 is not None else None,
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
        "quality_momentum_10_pct": None,
        "quality_prior_run": None,
        "quality_rsi": None,
        "quality_high_distance_pct": None,
        "atr_value": None,
        "high_20": None,
        "low_20": None,
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
