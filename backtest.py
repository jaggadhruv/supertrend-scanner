"""
backtest.py
-----------
Replays historical Supertrend flips on one ticker's OHLC series to
estimate expectancy. Called once per ticker per scan by
engine.analyze_ticker, cheap enough to do in-line.

Simulation rules mirror the Entry & SL block the report shows:
  Entry  = close on the flip bar
  SL     = close - 1.5*ATR (BUY) / close + 1.5*ATR (SELL)
           Clamped so it doesn't exceed the ST line at flip time.
  Target = close +/- 3*ATR
  Exit on first touch of target, SL, or opposite Supertrend flip.

R per trade = (exit - entry) / sl_distance for BUY, mirrored for SELL.
A target-hit nets +2R (because target distance = 2 x SL distance by
construction), an SL stop nets -1R, an opposite-flip exit nets whatever
R the move was at the opposing bar's close.

Returns:
  {"trades": int,        # number of CLOSED trades counted
   "win_rate": float|None,
   "profit_factor": float|None,   # sum(win_R) / |sum(loss_R)|; capped at 99
   "avg_r": float|None}
"""

import numpy as np


def backtest_flips(st_df, side="buy", atr_mult_sl=1.5, atr_mult_target=3.0,
                   min_lookback_bars=30):
    """
    side: "buy" for long trades after bullish flips,
          "sell" for short trades after bearish flips.
    """
    empty = {"trades": 0, "win_rate": None, "profit_factor": None, "avg_r": None}
    if st_df is None or len(st_df) < min_lookback_bars:
        return empty
    required = {"Direction", "Close", "High", "Low", "ATR", "Supertrend"}
    if not required.issubset(st_df.columns):
        return empty

    direction = st_df["Direction"].to_numpy()
    close = st_df["Close"].to_numpy()
    high = st_df["High"].to_numpy()
    low = st_df["Low"].to_numpy()
    atr = st_df["ATR"].to_numpy()
    st  = st_df["Supertrend"].to_numpy()
    n = len(direction)

    # Find flip indices for the chosen side.
    flips = []
    for i in range(1, n):
        if side == "buy"  and direction[i] ==  1 and direction[i - 1] == -1:
            flips.append(i)
        elif side == "sell" and direction[i] == -1 and direction[i - 1] ==  1:
            flips.append(i)

    # The most recent flip may still be open — exclude it from stats so
    # we don't flatter the numbers with unresolved trades.
    if flips and flips[-1] >= n - 3:
        flips = flips[:-1]

    r_values = []
    for flip_idx in flips:
        entry = float(close[flip_idx])
        a = float(atr[flip_idx])
        if not np.isfinite(a) or a <= 0:
            continue

        if side == "buy":
            # Tight SL = close - 1.5*ATR, clamped above the ST line.
            sl = max(entry - atr_mult_sl * a, float(st[flip_idx]))
            target = entry + atr_mult_target * a
            sl_dist = entry - sl
            if sl_dist <= 0:
                continue
            outcome_r = None
            for j in range(flip_idx + 1, n):
                # Intrabar order: if BOTH SL and target are inside the
                # bar, we assume the loss triggered first (conservative).
                if low[j] <= sl:
                    outcome_r = -1.0
                    break
                if high[j] >= target:
                    outcome_r = (target - entry) / sl_dist
                    break
                if direction[j] == -1:
                    outcome_r = (float(close[j]) - entry) / sl_dist
                    break
            if outcome_r is not None:
                r_values.append(outcome_r)

        else:  # sell
            sl = min(entry + atr_mult_sl * a, float(st[flip_idx]))
            target = entry - atr_mult_target * a
            sl_dist = sl - entry
            if sl_dist <= 0:
                continue
            outcome_r = None
            for j in range(flip_idx + 1, n):
                if high[j] >= sl:
                    outcome_r = -1.0
                    break
                if low[j] <= target:
                    outcome_r = (entry - target) / sl_dist
                    break
                if direction[j] == 1:
                    outcome_r = (entry - float(close[j])) / sl_dist
                    break
            if outcome_r is not None:
                r_values.append(outcome_r)

    if not r_values:
        return empty

    wins   = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    sum_wins   = sum(wins)
    sum_losses = abs(sum(losses))

    win_rate = len(wins) / len(r_values) * 100.0
    if sum_losses > 0:
        pf = sum_wins / sum_losses
    else:
        pf = 99.0 if sum_wins > 0 else 0.0
    avg_r = sum(r_values) / len(r_values)

    return {
        "trades": len(r_values),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(min(pf, 99.0), 2),
        "avg_r": round(avg_r, 2),
    }
