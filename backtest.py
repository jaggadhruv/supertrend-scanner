"""
backtest.py
-----------
Replays historical Supertrend flips on one ticker's OHLC series to
estimate how the flip + fixed SL/target rules performed in the past.
Called once per ticker per scan by engine.analyze_ticker.

Simulation rules (long side; the short side is the mirror image):

  Signal  = Supertrend flips Bullish on bar i. The flip is only known
            once bar i has closed.
  Entry   = OPEN of bar i+1 (the first price you can actually trade
            after seeing the signal).
  Risk    = 1.5 x ATR(bar i), measured from the entry fill.
  Stop    = entry - 1.5 x ATR.   Target = entry + 3 x ATR  (2R).
  Exit    = whichever comes first:
              - stop touched   -> filled at the stop, or at the bar's
                                  open if price gapped through it
                                  (so a gap loses MORE than 1R)
              - target touched -> filled at the target
              - Supertrend flips back -> filled at the next bar's open
            If a bar touches both stop and target, the stop is assumed
            to have been hit first (conservative).
  Costs   = cost_pct of the entry price per round trip (commission +
            slippage), deducted from every trade.

Every trade risks the same 1.5 x ATR, so results are bounded:
roughly -1R (worse on gaps) to +2R. There is no way for one trade
with a tiny stop distance to dominate the profit factor.

Trades still open at the end of the data are not counted.

Returns:
  {"trades": int,              # closed trades counted
   "wins": int, "losses": int,
   "win_rate": float|None,     # % of trades with R > 0 after costs
   "profit_factor": float|None,  # sum(winning R) / |sum(losing R)|
   "avg_r": float|None}        # average R per trade (expectancy)

The profit factor is capped at MAX_PROFIT_FACTOR. A handful of trades
can produce almost any profit factor by luck (4 wins + 1 loss = 8.0),
so callers should require a minimum trade count before trusting it.
See report.SUPERIOR_MIN_TRADES.
"""

import numpy as np

MAX_PROFIT_FACTOR = 10.0
DEFAULT_COST_PCT = 0.10   # round trip, % of entry price


def _empty():
    return {"trades": 0, "wins": 0, "losses": 0,
            "win_rate": None, "profit_factor": None, "avg_r": None}


def simulate_trades(st_df, side="buy", atr_mult_sl=1.5, atr_mult_target=3.0,
                    cost_pct=DEFAULT_COST_PCT):
    """Return the list of closed trades as dicts (for inspection/debugging):
    {signal_idx, entry_idx, exit_idx, entry, exit, r, reason}."""
    required = {"Direction", "Close", "High", "Low", "ATR"}
    if st_df is None or not required.issubset(st_df.columns):
        return []

    direction = st_df["Direction"].to_numpy()
    close = st_df["Close"].to_numpy(dtype=float)
    high = st_df["High"].to_numpy(dtype=float)
    low = st_df["Low"].to_numpy(dtype=float)
    atr = st_df["ATR"].to_numpy(dtype=float)
    n = len(direction)
    if n < 3:
        return []

    # Open of each bar; fall back to the previous close where missing.
    prev_close = np.concatenate(([close[0]], close[:-1]))
    if "Open" in st_df.columns:
        open_ = st_df["Open"].to_numpy(dtype=float)
        open_ = np.where(np.isfinite(open_) & (open_ > 0), open_, prev_close)
    else:
        open_ = prev_close

    long_side = (side == "buy")
    want, opposite = (1, -1) if long_side else (-1, 1)
    sign = 1.0 if long_side else -1.0

    trades = []
    for i in range(1, n - 1):
        if not (direction[i] == want and direction[i - 1] == opposite):
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        e = i + 1
        entry = open_[e]
        if not np.isfinite(entry) or entry <= 0:
            continue
        risk = atr_mult_sl * a
        stop = entry - sign * risk
        target = entry + sign * atr_mult_target * a

        exit_price = None
        exit_idx = None
        reason = None
        for j in range(e, n):
            if long_side:
                stop_hit = low[j] <= stop
                target_hit = high[j] >= target
            else:
                stop_hit = high[j] >= stop
                target_hit = low[j] <= target
            if stop_hit:
                # Gap through the stop fills at the open, which is worse.
                if long_side:
                    exit_price = min(open_[j], stop)
                else:
                    exit_price = max(open_[j], stop)
                exit_idx, reason = j, "stop"
                break
            if target_hit:
                exit_price, exit_idx, reason = target, j, "target"
                break
            if direction[j] == opposite:
                # Opposite flip is confirmed at this bar's close.
                if j + 1 < n:
                    exit_price, exit_idx = open_[j + 1], j + 1
                else:
                    exit_price, exit_idx = close[j], j
                reason = "flip"
                break
        if exit_price is None:
            continue  # still open at the end of the data

        cost = entry * cost_pct / 100.0
        r = (sign * (exit_price - entry) - cost) / risk
        trades.append({"signal_idx": i, "entry_idx": e, "exit_idx": exit_idx,
                       "entry": float(entry), "exit": float(exit_price),
                       "r": float(r), "reason": reason})
    return trades


def backtest_flips(st_df, side="buy", atr_mult_sl=1.5, atr_mult_target=3.0,
                   min_lookback_bars=30, cost_pct=DEFAULT_COST_PCT):
    """
    side: "buy" for long trades after bullish flips,
          "sell" for short trades after bearish flips.
    """
    if st_df is None or len(st_df) < min_lookback_bars:
        return _empty()

    trades = simulate_trades(st_df, side=side, atr_mult_sl=atr_mult_sl,
                             atr_mult_target=atr_mult_target, cost_pct=cost_pct)
    if not trades:
        return _empty()

    r_values = [t["r"] for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]
    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))

    if sum_losses > 0:
        pf = min(sum_wins / sum_losses, MAX_PROFIT_FACTOR)
    elif sum_wins > 0:
        pf = MAX_PROFIT_FACTOR      # no losing trades in the sample
    else:
        pf = 0.0

    return {
        "trades": len(r_values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(r_values) * 100.0, 1),
        "profit_factor": round(pf, 2),
        "avg_r": round(sum(r_values) / len(r_values), 2),
    }
