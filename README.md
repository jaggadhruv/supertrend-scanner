# Website
https://jaggadhruv.github.io/supertrend-scanner/

# Supertrend Scanner

Free, open-source tool that scans your US-equity watchlist with the Supertrend
indicator on weekly and daily charts. Produces interactive HTML reports with
quality-ranked BUY/SELL flips, confluence detection, and a rolling 7-day flip
log. Runs locally or as scheduled GitHub Actions, with an optional public
GitHub Pages site.

**Read `ARCHITECTURE.md`** for a full walkthrough of files, functions, data
flow, and extension points.

## Quick start

```bash
pip install -r requirements.txt
python scanner.py           # weekly scan → output/weekly/report_<date>.html
python daily_scanner.py     # daily scan  → output/daily/report_<date>.html
python combined_scanner.py  # merged      → output/combined/report_<date>.html
```

Edit `stocks.csv` to change your watchlist. Add rows to `trades.csv` when you
open positions (so held-bearish alerts fire).

## Three entry points, same engine

| Script | Timeframe | Output |
|---|---|---|
| `scanner.py` | Weekly | `output/weekly/report_<date>.html` |
| `daily_scanner.py` | Daily | `output/daily/report_<date>.html` |
| `combined_scanner.py` | Both, side-by-side | `output/combined/report_<date>.html` + `docs/` (when `COMBINED_PUBLISH_PAGE=1`) |

Each run:
- Downloads a fresh lookback window from Yahoo (3y weekly / 1y daily).
- Recomputes Supertrend from scratch — **no dependency on previous runs, safe to skip days**.
- Updates `data/*_history.json` so "Changed since last run" detection works.
- Appends BUY/SELL flips to `data/flip_log.json` **if they clear the quality gate** (default 60, env var `MIN_FLIP_QUALITY` to tune).
- Prunes report files older than 30 days from each `output/<flavor>/` folder.

## The quality score (0-100, 5 components)

Gates which flips enter the log and ranks the ones that do:

| Component | Max | What it measures |
|---|---|---|
| Volume accumulation | 25 | 5-bar avg vol / 20-bar avg vol |
| Momentum consistency | 30 | Both 5-bar AND 10-bar % return |
| Prior-trend maturity | 20 | Length of opposite trend before the flip (whipsaw filter) |
| RSI condition | 15 | Wilder RSI(14); favors confirmed-but-not-extended |
| Breakout proximity | 10 | Close vs 20-bar high (bull) / low (bear) |

Daily BUYs where the weekly chart is also bullish get a **+15 confluence boost** at log time (combined scanner only).

## GitHub Actions (optional, free)

Three workflows ship under `.github/workflows/`:

- **`weekly-scan.yml`** — 06:00 UTC Saturday
- **`daily-scan.yml`** — 18:00 UTC Mon-Fri
- **`combined-scan.yml`** — 22:00 UTC weekdays + 07:00 UTC Saturday, publishes to `docs/`

All three commit results back to `main` with a push-rebase retry loop so they never fail on races.

One-time GitHub setup: **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**.

## GitHub Pages (optional)

The combined workflow publishes a public tabbed page to `docs/index.html`:

- **▲ Long** tab: tickers in weekly+daily bullish confluence, their Recent Buy Flips (7d rolling), Buy Opportunities, and the full long-side table.
- **▼ Short** tab: mirror for bearish confluence.
- Tab state persists per visitor via `localStorage`.

**Privacy caveat (free Pages plan):** your Pages URL is public even if the repo is private. The published pages run in `public_view` mode so Held / Position P/L columns and the held-bearish alert banner are stripped — but the **watchlist tickers and signals themselves are visible at the URL**. If the watchlist is sensitive, leave Pages disabled.

To enable Pages: **Settings → Pages → Source: Deploy from a branch → Branch: main, folder: /docs → Save**. Then trigger the combined workflow manually and browse `https://<you>.github.io/<repo>/`.

## Files to edit by hand

- `stocks.csv` — watchlist. One ticker per row under `Ticker` header. Yahoo-format tickers (BRK-B, RELIANCE.NS).
- `trades.csv` — your open-position ledger. Columns: `Ticker,EntryDate,EntryPrice,Quantity,Status,ExitDate,ExitPrice,Notes`. `Status` must be `Open` or `Closed`.
- `.github/workflows/combined-scan.yml` — change `MIN_FLIP_QUALITY` or `COMBINED_PUBLISH_PAGE` here.
- Entry-point scripts' `CONFIG` blocks — change ATR period/multiplier if you want.

## Everything else

See `ARCHITECTURE.md` — covers the full file list, data flow diagrams, function call graphs, data structures, extension points, and failure modes.

## Not investment advice

Supertrend is a trend-following indicator, not a guarantee. Verify every signal independently before trading.
