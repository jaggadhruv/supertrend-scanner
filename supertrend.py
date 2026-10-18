"""supertrend.py — standalone Supertrend indicator (Wilder-smoothed ATR)."""
import pandas as pd
import numpy as np


def calculate_atr(df, period):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calculate_supertrend(df, period=10, multiplier=2.5):
    df = df.copy()
    high, low, close = df["High"], df["Low"], df["Close"]
    atr = calculate_atr(df, period)
    hl2 = (high + low) / 2
    bu = (hl2 + multiplier * atr).to_numpy(copy=True)
    bl = (hl2 - multiplier * atr).to_numpy(copy=True)
    c = close.to_numpy(copy=True)
    n = len(df)
    fu = bu.copy(); fl = bl.copy()
    st = np.full(n, np.nan); d = np.zeros(n, dtype=int)
    first_valid = atr.first_valid_index()
    if first_valid is None:
        df["ATR"] = atr; df["Supertrend"] = st; df["Direction"] = d
        return df
    s = df.index.get_loc(first_valid)
    fu[s] = bu[s]; fl[s] = bl[s]; st[s] = fu[s]; d[s] = -1
    for i in range(s + 1, n):
        fu[i] = bu[i] if (bu[i] < fu[i-1] or c[i-1] > fu[i-1]) else fu[i-1]
        fl[i] = bl[i] if (bl[i] > fl[i-1] or c[i-1] < fl[i-1]) else fl[i-1]
        if st[i-1] == fu[i-1]:
            if c[i] <= fu[i]: st[i] = fu[i]; d[i] = -1
            else:             st[i] = fl[i]; d[i] = 1
        else:
            if c[i] >= fl[i]: st[i] = fl[i]; d[i] = 1
            else:             st[i] = fu[i]; d[i] = -1
    df["ATR"] = atr; df["Supertrend"] = st; df["Direction"] = d
    return df
