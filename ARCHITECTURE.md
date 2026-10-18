# Architecture

This document explains how the Supertrend Scanner is wired together: which files feed which, which functions call which, where data flows, and where to extend things.

---

## 1. System at a glance

```
                     ┌─────────────────────────────────────┐
                     │              USER INPUTS             │
                     │  stocks.csv   ·   trades.csv         │
                     └──────────────┬──────────────────────┘
                                    │
                   ┌────────────────┼────────────────┐
                   ▼                ▼                ▼
          ┌───────────────┐ ┌───────────────┐ ┌─────────────────────┐
          │  scanner.py   │ │daily_scanner  │ │  combined_scanner   │
          │  (weekly)     │ │.py (daily)    │ │  .py (weekly+daily) │
          └───────┬───────┘ └───────┬───────┘ └──────────┬──────────┘
                  │                 │                    │
                  ▼                 ▼                    ▼
          ┌──────────────────────────────────────────────────────┐
          │                      engine.py                        │
          │  run_scan() → run_analysis() → analyze_ticker() →     │
          │  _compute_quality() → supertrend.calculate_supertrend │
          │       │                                               │
          │       ├─ load_stock_list / load_trades / load_history │
          │       ├─ fetch_data (yfinance)                        │
          │       ├─ cross_reference_trades / build_alerts        │
          │       ├─ record_flips (gated by MIN_FLIP_QUALITY)     │
          │       └─ prune_old_reports (30-day cleanup)           │
          └───────┬──────────────────────────────────────────────┘
                  │
         ┌────────┼────────┬──────────────┐
         ▼        ▼        ▼              ▼
   data/        output/   output/     combined_scanner also:
   weekly_      weekly/   daily/      → report.generate_tabbed_html_report
   history.json                       → publish.publish_public_report
   daily_                                   │
   history.json                             ▼
   flip_log.json                       docs/
                                         index.html (TABBED Long + Short)
                                         archive.html
                                         reports/report_<date>.html
                                         .nojekyll
```

Everything flows downhill: user inputs feed scanners; scanners drive the engine; the engine writes histories, flip logs, and per-timeframe reports; the combined scanner additionally hands results to `report.py` and `publish.py` to render the public tabbed page.

---

## 2. File responsibilities

| File | Role | Reads | Writes |
|---|---|---|---|
| **`stocks.csv`** | Watchlist. One ticker per row under a `Ticker` header. | — | user-maintained |
| **`trades.csv`** | Open-position ledger. P/L and held-bearish alerts come from this. | — | user-maintained |
| **`requirements.txt`** | Python deps (`yfinance`, `pandas`, `numpy`). | — | — |
| **`supertrend.py`** | Pure math: Wilder-smoothed ATR + Supertrend band recurrence. No I/O. | — | — |
| **`engine.py`** | Core pipeline: fetch, analyze, score, log flips, prune outputs, orchestrate `run_scan` and `run_analysis`. | `stocks.csv`, `trades.csv`, `data/*_history.json`, `data/flip_log.json` | `data/*_history.json`, `data/flip_log.json`, deletes old reports |
| **`report.py`** | HTML rendering. Three generators: per-timeframe, combined (full), and tabbed (Long+Short in one page). No I/O beyond writing the output file. | — | writes HTML to given path |
| **`publish.py`** | Writes the public `docs/` folder. Calls `report.generate_tabbed_html_report` and `report.generate_combined_html_report`, prunes 30-day docs, and rebuilds `docs/archive.html`. | — | `docs/index.html`, `docs/archive.html`, `docs/reports/*`, `docs/.nojekyll` |
| **`scanner.py`** | Entry point for the weekly scan. Builds a `ScanConfig` and calls `engine.run_scan`. | — | via engine |
| **`daily_scanner.py`** | Entry point for the daily scan. Same shape as `scanner.py` with daily params. | — | via engine |
| **`combined_scanner.py`** | Entry point for the merged run. Calls `engine.run_analysis` twice (weekly + daily), writes histories + flip log + report, and (when `COMBINED_PUBLISH_PAGE=1`) publishes to `docs/`. | — | via engine + publish |
| **`.github/workflows/weekly-scan.yml`** | Cron (06:00 UTC Sat) → `scanner.py` → commit + push with retry-on-race. | — | commits to `main` |
| **`.github/workflows/daily-scan.yml`** | Cron (18:00 UTC Mon-Fri) → `daily_scanner.py`. | — | commits to `main` |
| **`.github/workflows/combined-scan.yml`** | Cron (22:00 UTC weekdays + 07:00 UTC Sat) → `combined_scanner.py`. Sets `COMBINED_PUBLISH_PAGE=1`. | — | commits to `main` |

---

## 3. Data flow

### 3.1 Per-timeframe scan (weekly or daily)

```
   stocks.csv ───┐
   trades.csv ──►│   engine.run_scan(cfg)                              writes
   data/<tf>_   ►│    │                                                 ↓
   history.json  │    ├─► run_analysis(cfg)        ────────┐
                 │    │    │                                │
                 │    │    ├─► load_stock_list              │
                 │    │    ├─► load_trades                  │     data/<tf>_history.json
                 │    │    ├─► load_history         ◄──────┘        (atomically updated)
                 │    │    │                                        
                 │    │    └─► for each ticker:              writes
                 │    │         ├─► fetch_data (yfinance) ────────► in memory only
                 │    │         ├─► supertrend.calculate_supertrend
                 │    │         └─► _compute_quality
                 │    │
                 │    ├─► cross_reference_trades (joins open trades.csv)
                 │    ├─► build_alerts (held-bearish detection)
                 │    │
                 │    ├─► commit_history(cfg, scan) ─────────────► data/<tf>_history.json
                 │    ├─► record_flips(cfg, results, run_date)  ─► data/flip_log.json
                 │    │     (gated: BUY only logged if quality ≥ MIN_FLIP_QUALITY)
                 │    ├─► prune_old_reports(cfg.output_dir, 30) ─► output/<tf>/ cleanup
                 │    │
                 │    └─► report.generate_html_report(...) ────► output/<tf>/report_<date>.html
```

### 3.2 Combined scan

```
   stocks.csv + trades.csv + both history files
         │
         ▼
   combined_scanner.main()
         │
         ├─► engine.run_analysis(WEEKLY_CONFIG)   → weekly_scan dict
         ├─► engine.run_analysis(DAILY_CONFIG)    → daily_scan dict
         │
         ├─► engine.commit_history (×2)           ─────► data/*_history.json
         │
         ├─► Build weekly_bullish set (tickers whose weekly direction = Bullish)
         │
         ├─► engine.record_flips(WEEKLY_CONFIG, ...)       ─► data/flip_log.json
         ├─► engine.record_flips(DAILY_CONFIG, ...,
         │        weekly_bullish_tickers=weekly_bullish)   ─► data/flip_log.json
         │       (daily BUYs with weekly bull get +15 confluence boost
         │        BEFORE the MIN_FLIP_QUALITY gate check)
         │
         ├─► load_flip_log() → feeds report + publish
         │
         ├─► report.generate_combined_html_report(side="full") ─► output/combined/report_<date>.html
         │
         ├─► prune_old_reports (combined, weekly, daily) ─► output/* 30-day cleanup
         │
         └─► If COMBINED_PUBLISH_PAGE=1:
             publish.publish_public_report()
                ├─► report.generate_tabbed_html_report()  ─► docs/index.html
                ├─► report.generate_combined_html_report(side="full") ─► docs/reports/report_<date>.html
                ├─► prune_old_reports(docs/reports, 30)
                └─► _rebuild_archive_index()               ─► docs/archive.html
```

### 3.3 Persistent artifacts

```
   data/
     weekly_history.json   last state per ticker from the WEEKLY run.
                           Used to detect "changed since last run" when
                           you've missed an exact flip bar.
                           Written by: scanner.py, combined_scanner.py.
                           Read by:   scanner.py, combined_scanner.py.
     daily_history.json    Same shape, for the daily run.
     flip_log.json         Append-only ledger of every BUY/SELL flip
                           that cleared the quality gate. Dedup key is
                           (ticker, timeframe, flip_date). Entries older
                           than 180 days are pruned on each write.
                           Written by: ALL three scanners.
                           Read by:   combined_scanner.py (feeds the
                                      Recent Flips panel).

   output/
     weekly/report_<date>.html    Per-timeframe HTML, 30-day retention.
     daily/report_<date>.html
     combined/report_<date>.html

   docs/                   (only when COMBINED_PUBLISH_PAGE=1)
     index.html            Tabbed Long + Short public view (overwritten).
     archive.html          Landing page with dated archive links.
     reports/              Dated snapshots of the full (both-sides) view.
       report_<date>.html  30-day retention.
     .nojekyll             Tells GitHub Pages to skip Jekyll.
```

---

## 4. Function call graphs

### 4.1 Per-timeframe scan

```
scanner.py / daily_scanner.py
  └── engine.run_scan(cfg)
       ├── engine.run_analysis(cfg)
       │    ├── engine.load_stock_list(cfg.stocks_file)
       │    ├── engine.load_trades(cfg.trades_file)
       │    ├── engine.load_history(cfg.history_file)
       │    ├── engine.analyze_ticker(ticker, history, cfg)       [per ticker]
       │    │    ├── engine.fetch_data   (→ yfinance)
       │    │    ├── supertrend.calculate_supertrend
       │    │    │    └── supertrend.calculate_atr
       │    │    └── engine._compute_quality(st_df, bars_in_trend)
       │    ├── engine.cross_reference_trades
       │    └── engine.build_alerts
       ├── engine.commit_history(cfg, scan)
       │    ├── engine.update_history
       │    └── engine.save_history
       ├── engine.record_flips(cfg, results, run_date,
       │                       min_quality=_min_quality_from_env())
       │    ├── engine.load_flip_log
       │    └── engine.save_flip_log
       ├── engine.prune_old_reports(cfg.output_dir, 30)
       └── report.generate_html_report(results, alerts, …)
            └── report._row_html / _alert_html / _buy_html
```

### 4.2 Combined scan

```
combined_scanner.main()
  ├── engine.run_analysis(WEEKLY_CONFIG)
  ├── engine.run_analysis(DAILY_CONFIG)
  ├── engine.commit_history(WEEKLY_CONFIG, weekly_scan)
  ├── engine.commit_history(DAILY_CONFIG,  daily_scan)
  ├── engine.record_flips(WEEKLY_CONFIG, …, min_quality=min_q)
  ├── engine.record_flips(DAILY_CONFIG,  …, min_quality=min_q,
  │                       weekly_bullish_tickers=weekly_bullish)
  ├── engine.load_flip_log(_flip_log_path(WEEKLY_CONFIG))
  ├── report.generate_combined_html_report(side="full")   → output/combined/
  ├── engine.prune_old_reports × 3 (combined/weekly/daily)
  └── [if COMBINED_PUBLISH_PAGE] publish.publish_public_report()
       ├── report.generate_tabbed_html_report()
       │    ├── report._side_sections("long",  …)
       │    │    ├── report._recent_flips_panel_html(side="long", …)
       │    │    │    └── report._flip_card_html / _build_reason_html
       │    │    ├── report._buy_html         (opportunity grid)
       │    │    └── report._combined_row_html
       │    │         ├── report._tf_status / _combined_tf_cell
       │    │         └── report._confluence_cell
       │    └── report._side_sections("short", …)   [same shape]
       ├── report.generate_combined_html_report(side="full")  → docs/reports/
       ├── engine.prune_old_reports(docs/reports, 30)
       └── publish._rebuild_archive_index()        → docs/archive.html
```

---

## 5. Key data structures

### 5.1 `ScanConfig` (engine.py dataclass)

Each entry point constructs one of these and hands it to the engine.

```python
ScanConfig(
    label=            "Weekly" | "Daily",     # for report title + flip log timeframe
    interval=         "1wk"    | "1d",        # yfinance interval
    lookback_period=  "3y"     | "1y",        # yfinance period
    atr_period=       10,
    atr_multiplier=   2.5,
    stocks_file=      "stocks.csv",           # (or a list of CSV paths)
    trades_file=      "trades.csv",
    history_file=     "data/<tf>_history.json",
    output_dir=       "output/<tf>",
    min_bars_required=15,                     # auto-defaults to atr_period + 5
)
```

### 5.2 Per-ticker result dict (output of `engine.analyze_ticker`)

```python
{
    "ticker": "AAPL",
    "status": "ok" | "error" | "insufficient_data",
    "error":  None | <reason>,

    # Price / indicator state
    "close":            320.17,
    "supertrend":       315.44,
    "last_bar_date":    "2026-10-18",
    "direction":        "Bullish" | "Bearish",
    "signal":           "BUY" | "SELL" | "NONE",   # fresh-cross on latest bar

    # Prior state (from the history file)
    "last_recorded_direction": "Bullish" | "Bearish" | None,
    "last_recorded_signal":    "BUY" | "SELL" | "NONE" | None,
    "last_recorded_date":      "2026-10-11" | None,
    "is_new":                  True | False,
    "flip":                    True | False,
    "changed_since_last_run":  True | False,

    # In-trend
    "bars_in_trend":    12,            # consecutive bars sharing current direction
    "trend_start_date": "2026-10-06",
    "bar_unit":         "d" | "w",

    # Quality (0-100, five components)
    "quality_score":              92,
    "quality_volume_ratio":       1.45,   # 5-bar avg vol / 20-bar avg vol
    "quality_momentum_pct":        4.0,   # 5-bar return %
    "quality_momentum_10_pct":     7.5,   # 10-bar return %
    "quality_prior_run":           12,    # length of prior opposite-direction run
    "quality_rsi":                58.0,
    "quality_high_distance_pct":   0.3,   # (close - 20-bar high) / 20-bar high, %

    # Trade cross-reference (set by engine.cross_reference_trades)
    "held":        True | False,
    "open_trades": [{"EntryPrice": …, "Quantity": …, "pnl_pct": …, …}, …],
}
```

### 5.3 Flip log entry (one line in `data/flip_log.json`)

```python
{
    "ticker":    "AAPL",
    "timeframe": "weekly" | "daily",
    "direction": "Bullish" | "Bearish",
    "signal":    "BUY" | "SELL",
    "flip_date":   "2026-10-18",       # the bar the flip landed on
    "recorded_at": "2026-10-18",       # the run that first saw it
    "close":      320.17,
    "supertrend": 315.44,

    # Quality (identical to the result dict's quality_* fields)
    "quality_score":            92,    # post-boost score, if applicable
    "quality_base_score":       77,    # score before weekly-confluence boost
    "quality_volume_ratio":     1.45,
    "quality_momentum_pct":      4.0,
    "quality_momentum_10_pct":   7.5,
    "quality_prior_run":         12,
    "quality_rsi":              58.0,
    "quality_high_distance_pct": 0.3,
    "weekly_confluence":        True | False,
}
```

Dedup key: `(ticker, timeframe, flip_date)`. Entries older than 180 days (`FLIP_LOG_MAX_AGE_DAYS`) are pruned on each write.

---

## 6. The 5-component quality score

Computed per ticker in `engine._compute_quality(st_df, bars_in_trend)`. Returns a 0-100 total plus the raw components (for the inline reason line on cards).

| Component | Weight | What it measures | Favorable zone |
|---|---|---|---|
| **Volume accumulation** | 0-25 | 5-bar avg volume ÷ 20-bar avg volume | ≥1.5× → 25 pts; <0.8× → 2 pts |
| **Momentum consistency** | 0-30 | Both 5-bar AND 10-bar return | Both strong (≥3%/5b, ≥5%/10b) → 30; divergent → 14-22 |
| **Prior-trend maturity** | 0-20 | Length of opposite-direction run just before the current one | ≥15 bars → 20 pts; whipsaw (1-2) → 0-2 pts |
| **RSI condition** | 0-15 | Wilder RSI(14). BULL sweet spot 50-65. BEAR sweet spot 35-50. | Sweet spot → 15; overbought/oversold → 2 pts |
| **Breakout proximity** | 0-10 | Close vs 20-bar high (bull) or low (bear) | Fresh breakout → 10; >5% away → 1 pt |

**Weekly-confluence boost (combined scanner only, daily BUYs only):** when the ticker's current weekly direction is Bullish, the daily BUY's logged score gets `+15`, capped at 100. Applied in `engine.record_flips` BEFORE the `MIN_FLIP_QUALITY` gate — so confluence BUYs clear the gate more easily.

**Quality gate (`MIN_FLIP_QUALITY`):** BUY flips scoring below the threshold (default 60, env-var overridable) are detected but **not persisted** to `flip_log.json`. SELL flips are never gated (the held-bearish alert path depends on them).

---

## 7. Report structure

### 7.1 `generate_html_report` (per-timeframe)

Used by `scanner.py` and `daily_scanner.py` → `output/<tf>/report_<date>.html`. Shows: alert banner (held bearish), stats row, Buy Opportunities panel, full watchlist table (sortable).

### 7.2 `generate_combined_html_report(side)` (full / long / short)

Used by `combined_scanner.py` and `publish.py` for the dated archive at `docs/reports/report_<date>.html`. `side="full"` shows all tickers and both BUY+SELL signals. `side="long"` or `"short"` filters.

### 7.3 `generate_tabbed_html_report` (the published landing page)

Used by `publish.py` for `docs/index.html`. Builds BOTH Long and Short views via `_side_sections` and wraps them in `<div class="tab-pane">` panes with pane-scoped filter/sort JS. Tab state persists to `localStorage` so refresh keeps the active side.

```
docs/index.html structure:

┌─────────────────────────────────────────────────────┐
│ Supertrend Combined Scanner                          │
│ ATR(10) × 2.5 · Weekly + Daily · Generated …         │
├─────────────────────────────────────────────────────┤
│ [▲ Long · Uptrend Confluence (N) ]  [▼ Short …]  Archive →
├─────────────────────────────────────────────────────┤
│ (pane-long OR pane-short visible)                    │
│                                                      │
│   Recent Buy|Sell Flips (7-day rolling)              │
│   Stats (count of fresh weekly, daily, confluence)   │
│   Buying|Selling Opportunities (3 subpanels)         │
│   Full Watchlist table (filtered to this side)       │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## 8. Scheduling + workflow interactions

```
Mon  18:00 UTC  daily-scan.yml      → scanner.py (daily)
Tue  18:00 UTC  daily-scan.yml
Wed  18:00 UTC  daily-scan.yml
Thu  18:00 UTC  daily-scan.yml
Fri  18:00 UTC  daily-scan.yml

Mon-Fri 22:00 UTC  combined-scan.yml  → combined_scanner.py (+ publish docs/)
Sat 06:00 UTC      weekly-scan.yml    → scanner.py (weekly)
Sat 07:00 UTC      combined-scan.yml  → combined_scanner.py
```

**All three workflows have a retry-on-race loop around `git push`** (up to 5 attempts, `--rebase --autostash -X theirs`). If two workflows commit at the same time the second one just rebases and retries, so no run fails because of a push conflict.

**Workflow permissions:** each workflow has `permissions: contents: write` so it can push results back. GitHub Pages (if enabled) reads from `docs/` on `main` on every push.

---

## 9. Extension points

**Add a new scoring component:**
Edit `engine._compute_quality`. Add computation, decide a weight that keeps the total ≤100, append a key to the returned dict, mirror it in `engine.analyze_ticker`'s result template, and in `engine.record_flips`'s log entry. Then teach `report._build_reason_html` to show it on the card.

**Change the quality threshold without editing code:**
Set the `MIN_FLIP_QUALITY` env var in `.github/workflows/combined-scan.yml` (or export it before `python combined_scanner.py` locally). Clamped to [0, 100]; default 60; invalid values fall back to default. See `engine._min_quality_from_env`.

**Add a new timeframe (e.g., 4-hour):**
Create a new entry point (`four_hour_scanner.py`) with a `ScanConfig(label="4H", interval="60m", lookback_period="60d", history_file="data/four_hour_history.json", output_dir="output/four_hour", …)`. Everything downstream in the engine works transparently.

**Change the Recent Flips window from 7 days:**
Pass `days=N` to `report._recent_flips_panel_html` from the two callers (`generate_combined_html_report` and `_side_sections`).

**Add a new filter chip to the tables:**
Add a `<button class="chip-btn" data-filter="new-filter-id">Label</button>` next to the others in `_combined_row_html` and `_side_sections`, then add the case to the `switch (currentFilter)` block in both `COMBINED_JS` and `TABBED_JS`.

**Disable Pages publishing:**
Remove the `COMBINED_PUBLISH_PAGE: "1"` env line from `combined-scan.yml` (or set to empty). `combined_scanner.py` falls back to writing only `output/combined/` and never touches `docs/`.

**Change the ATR period or multiplier:**
Edit the `CONFIG` block in each scanner entry point. Weekly and daily can have different values if you want different sensitivity on each timeframe.

---

## 10. Dependency ownership

```
Direct deps (requirements.txt):   yfinance, pandas, numpy
Transitive via yfinance:          requests, beautifulsoup4, lxml, …
Standard library:                 json, os, re, time, dataclasses, datetime, html

Zero external services beyond Yahoo Finance for OHLCV.
Zero paid APIs.
Zero required accounts beyond GitHub (for Actions + Pages).
```

---

## 11. Failure modes + where they land

| Failure | Where it manifests | How the code handles it |
|---|---|---|
| Yahoo returns no data for a ticker | `fetch_data` returns None | Result dict has `status="error"`, error row in report. |
| Yahoo rate-limits during scan | `yfinance` raises inside `fetch_data` | Caught, same `status="error"` path. 0.3s sleep between tickers mitigates. |
| Not enough history for ATR | `analyze_ticker` returns `status="insufficient_data"` | Error row in report with "Only N bars available". |
| Workflow push races another | `git push` rejected | Retry loop pulls --rebase and retries up to 5 times. |
| Pages tries to run Jekyll | `pages-build-deployment` fails | `docs/.nojekyll` tells Pages to skip Jekyll entirely. |
| Flip log corrupted | `load_flip_log` catches `JSONDecodeError` | Returns empty list; next `record_flips` writes fresh. |
| History file missing (first run) | `load_history` returns `{}` | Every ticker shows as "new — no prior run". |

---

## 12. The one-liner view

> **Scanners → engine → persist state → render report. The combined scanner additionally runs both timeframes, boosts BUYs that have weekly agreement, and publishes a tabbed public page to GitHub Pages.**
