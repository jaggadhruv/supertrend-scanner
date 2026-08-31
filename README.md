# Supertrend Scanner (Weekly + Daily + Combined)

A free, open-source tool that scans a watchlist of stocks using the
**Supertrend indicator** (ATR period 10, multiplier 2.5), flags fresh
BUY/SELL flips, cross-references your own trade log so it can alert you
when a stock you hold turns bearish, and outputs everything as one
interactive HTML dashboard.

There are three entry points, all sharing the same watchlist and trade
log:

- **`scanner.py`** — weekly chart, meant to be run about once a week (positional trades)
- **`daily_scanner.py`** — daily chart, meant to be run as often as you like (intraday/swing-style read)
- **`combined_scanner.py`** — runs both scans in one go and writes a **single merged HTML report** with the weekly and daily views for every ticker sitting side-by-side, plus a "Confluence" section that highlights stocks flipping BUY or SELL on **both** timeframes on the same run. Purely additive — the two individual scanners still work exactly as before.

All three are entirely manual — nothing is scheduled, nothing runs in
the background locally. You run a file, you get a report, that's it.
And all three are **safe to skip**: every run re-downloads fresh data
and recomputes everything from scratch, so missing a day (or several)
never leaves stale or broken state — see "Skip-safety" below.

Nothing costs money — it uses `yfinance` (free Yahoo Finance data),
`pandas`/`numpy` for the maths, and plain HTML/CSS/JS for the report (no
paid services, no external CDN calls).

## Files

| File | Purpose |
|---|---|
| `stocks.csv` | Your watchlist — one ticker per row. Shared by all three scanners. |
| `trades.csv` | Your trade log — shared by all three scanners. |
| `supertrend.py` | The Supertrend indicator math. |
| `engine.py` | Shared scan logic (fetch, analyze, alert, save history). Used by every entry point. |
| `scanner.py` | **Run this for the weekly scan.** |
| `daily_scanner.py` | **Run this for the daily scan.** |
| `combined_scanner.py` | **Run this to produce one merged report with both weekly and daily results.** |
| `report.py` | Builds the interactive HTML reports (per-timeframe + combined). |
| `data/weekly_history.json` | Auto-created — remembers the weekly scanner's last signal per stock. Written by both `scanner.py` and `combined_scanner.py`. |
| `data/daily_history.json` | Auto-created — same, for the daily scanner. Written by both `daily_scanner.py` and `combined_scanner.py`. |
| `output/weekly/report_<date>.html` | Auto-created weekly reports — one per run, never overwritten. |
| `output/daily/report_<date>.html` | Auto-created daily reports — one per run, never overwritten. |
| `output/combined/report_<date>.html` | Auto-created merged (weekly + daily) reports — one per combined run. |

## 1. One-time setup

You need Python 3.9+ installed.

```bash
cd supertrend_scanner
pip install -r requirements.txt
```

(If you use a virtual environment: `python3 -m venv venv && source venv/bin/activate` first.)

## 2. Build your watchlist

Open `stocks.csv` in any editor (or Excel/Google Sheets) and list one ticker
per line under the `Ticker` header:

```
Ticker
RELIANCE.NS
TCS.NS
AAPL
MSFT
```

**Ticker format follows Yahoo Finance conventions:**
- US stocks: plain ticker, e.g. `AAPL`, `MSFT`
- NSE (India): add `.NS`, e.g. `RELIANCE.NS`
- BSE (India): add `.BO`
- London: add `.L`; Toronto: `.TO`; etc.
- If unsure, search the ticker on [finance.yahoo.com](https://finance.yahoo.com) and copy the symbol shown there.

Add or remove rows any time — the scanner reads this file fresh on every run,
so your list is always up to date. No code changes needed.

## 3. Log your trades (optional but recommended)

Open `trades.csv` and add a row every time you enter a position:

```
Ticker,EntryDate,EntryPrice,Quantity,Status,ExitDate,ExitPrice,Notes
RELIANCE.NS,2026-05-11,2870.50,10,Open,,,Entered on weekly Supertrend buy flip
```

- `Status` must be `Open` or `Closed`. Only `Open` rows are checked for sell alerts.
- When you exit, either change `Status` to `Closed` and fill in `ExitDate`/`ExitPrice`, or delete the row — either is fine, it's your log.
- You can hold multiple open lots of the same ticker (add multiple rows); the report will show each one's P/L.

## 4. Run a scan

**Weekly** — best run after Friday's close (e.g. Saturday morning), so every
weekly candle is fully closed:

```bash
python scanner.py
```

**Daily** — best run after that day's market close, as often as you like:

```bash
python daily_scanner.py
```

**Combined** — runs both scans back-to-back and produces one merged
report with weekly + daily side-by-side per ticker:

```bash
python combined_scanner.py
```

This writes to `output/combined/report_<date>.html` **and** updates
both `weekly_history.json` and `daily_history.json`, so it stays in
sync with the individual scanners no matter which one you use next.

Any of the three will show progress in the terminal, then something like:

```
Report written to: output/weekly/report_2026-08-08.html
```

Open that file in any browser (double-click it, or `open output/weekly/report_2026-08-08.html` on Mac / `start` on Windows). Daily reports land in `output/daily/`; combined reports in `output/combined/`.

## 5. Reading the report

- **Top alert banner** (only appears if triggered): stocks you currently hold (`Status=Open` in trades.csv) that are now flagged bearish — either a fresh flip on this run's latest bar, or a change since your last run that you may have missed.
- **Summary chips**: total scanned, buy signals, sell signals, newly added stocks, errors.
- **Buying Opportunities panel**: every stock with a fresh BUY flip this week, at a glance.
- **Full Watchlist table**: every stock, sortable (click any column header) and filterable (chips for All / Buy / Sell / Flips / My Portfolio, plus a ticker search box). Columns:
  - **Close / Supertrend** — this week's closing price and Supertrend line value
  - **Direction** — Bullish or Bearish (price vs. the Supertrend line right now)
  - **Signal (Latest Bar)** — BUY / SELL only if the trend *flipped on the most recent candle*, otherwise "—"
  - **Last Recorded** — the direction/signal saved from your *previous run of that scanner* (blank/"new" if you just added the stock — nothing to compare yet)
  - **Flip** — "✓ Flip" if it crossed on the latest bar, or amber "↺ Changed since last run" if the direction differs from last time even though the exact crossover bar has already passed (see Skip-safety below)
  - **Held / Position P/L** — pulled from trades.csv

### The combined report (from `combined_scanner.py`)

Layout is the same shape but shows both timeframes in one view:

- **Alert banner** — held stocks flagged bearish in *either* the weekly or daily scan, each row tagged `WEEKLY` or `DAILY` so you can see which timeframe fired.
- **Stats row** — total tickers, then Weekly Buy / Sell, Daily Buy / Sell, and a **Confluence** pair (Buy on both, Sell on both).
- **Buying Opportunities** panel with three sub-sections:
  1. **★ Confluence Buy** — a fresh BUY flip on *both* the weekly and daily charts on this run. Rare and the strongest signal the tool can raise.
  2. **Weekly Buy Flips** — every weekly BUY.
  3. **Daily Buy Flips** — every daily BUY.
- **Full Watchlist table** with one row per ticker and columns for weekly and daily side-by-side, a **Confluence** indicator (▲▲ / ▼▼ / ▲▼), plus Held / P/L. Filters: All / Any Buy / Any Sell / Confluence ▲▲ / Confluence ▼▼ / Weekly Flips / Daily Flips / My Portfolio.

## 6. Repeat as often as you like

Each run overwrites that scanner's own history file (`weekly_history.json`
or `daily_history.json`) with this run's results, and writes a new dated
HTML file — old reports are never deleted, so you naturally build up an
archive in `output/weekly/` and `output/daily/`.

## Skip-safety

Both scanners are designed so that missing a run never causes a problem or
hides information from you:

- Every run pulls a fresh lookback window (3 years of weekly bars / 1 year
  of daily bars) and recomputes the whole Supertrend series from scratch —
  nothing depends on having run "yesterday" or "last week".
- Two separate signals are tracked per stock:
  - **Signal (Latest Bar)** tells you if it crossed *on the most recent
    candle* — precise, but only catches flips from the last session.
  - **Flip / "Changed since last run"** compares the current direction to
    whatever was saved the last time you ran that scanner, no matter how
    long ago that was. So if you skip three days and a flip happened on
    day two, the next run still flags it — you just won't know the exact
    day it crossed.
- The same logic drives the sell alert on held stocks: it fires if the
  stock crossed bearish on the latest bar, **or** if it's bearish now and
  wasn't the last time you checked. Once you've run the scanner and seen
  it, it won't keep re-alerting for the same old flip.

## Customizing

Each scanner has its own `CONFIG` block at the top of its file
(`scanner.py` for weekly, `daily_scanner.py` for daily):

```python
CONFIG = ScanConfig(
    label="Daily",
    interval="1d",
    lookback_period="1y",
    atr_period=10,
    atr_multiplier=2.5,
    ...
)
```

Change and re-run any time — you don't need to reset the history file, but
if you change the parameters mid-stream, "Last Recorded" will reflect the
old parameters for one run until it catches up. The two scanners are fully
independent, so you can run different ATR periods/multipliers on each if
you want a different sensitivity for daily vs. weekly.

## Troubleshooting

- **"No data returned"** for a ticker — usually a wrong/missing exchange suffix. Check the symbol on finance.yahoo.com.
- **"Only N bars available"** — the stock is too newly listed to have enough history yet; it'll resolve itself over time.
- **Rate limiting from Yahoo Finance** — the engine already pauses briefly between tickers; if you have a very long watchlist and hit errors, increase the `time.sleep(0.3)` value near the bottom of `engine.py` (`run_scan`).

## Not investment advice

This is a personal analysis tool. Supertrend is a trend-following indicator,
not a guarantee — always verify signals independently before acting on them.

---

## Running it automatically on GitHub (free)

Instead of running `scanner.py` / `daily_scanner.py` on your own machine,
you can have **GitHub Actions** run them on a schedule for you, for free,
and commit each report straight back into the repo — so you get a
permanent, browsable archive without keeping your PC on.

⚠️ **Privacy note first:** `trades.csv` contains your real entry prices and
position sizes. Use a **private** GitHub repo (free, unlimited on any
account) unless you're fine with that data being public. The setup below
assumes a private repo.

### One-time setup

1. **Create a private repo** on GitHub (e.g. `supertrend-scanner`) — don't initialize it with a README, you already have one.
2. **Push this project to it.** From inside the `supertrend_scanner` folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/supertrend-scanner.git
   git push -u origin main
   ```
   (In PyCharm you can do this via **VCS → Share Project on GitHub** instead, which handles the same steps through the UI — just make sure to select "Private" when it asks.)
3. **Allow the workflow to push results.** On GitHub: your repo → **Settings → Actions → General → Workflow permissions** → select **"Read and write permissions"** → Save. Without this, the "commit results" step in the workflow will fail with a permissions error.
4. That's it — `.github/workflows/weekly-scan.yml`, `.github/workflows/daily-scan.yml`, and `.github/workflows/combined-scan.yml` are already in the project and will now run on their schedules automatically. You can also trigger any of them manually any time: repo → **Actions** tab → pick the workflow → **Run workflow**.

> **Weekly + Daily + Combined together?** If you're happy with the merged view, you can just leave `combined-scan.yml` enabled and disable the weekly/daily ones from the **Actions** tab. All three are safe to leave running side-by-side too — they never conflict on the report files (each writes into its own `output/<flavor>/` subfolder), and the history files are always overwritten from a fresh recompute, so whichever workflow ran last just leaves the up-to-date state.

### Adjusting the schedule

All workflow files use cron syntax in **UTC**:

```yaml
- cron: '0 6 * * 6'      # weekly: 06:00 UTC every Saturday
- cron: '0 18 * * 1-5'   # daily: 18:00 UTC, Monday-Friday
- cron: '0 22 * * 1-5'   # combined: 22:00 UTC weekdays (after US close)
- cron: '0 7 * * 6'      # combined: 07:00 UTC Saturday (weekly candle just closed)
```

Edit the hour to land after your target market's close, converted to UTC.
GitHub's scheduler isn't second-precise under load, so treat it as
"around this time," not exact.

### Day-to-day workflow once this is set up

- **Adding/removing stocks or logging a trade**: edit `stocks.csv` /
  `trades.csv` and push the change (or, easiest, edit the file directly on
  github.com — click the file, the pencil icon, edit, commit to `main`,
  even from your phone). The next scheduled or manually-triggered run
  will pick it up automatically.
- **Viewing a report**: pull the repo (`git pull`) and open the relevant
  file in `output/weekly/` or `output/daily/` in your browser, or browse
  to it on github.com and use the "Download raw file" button. GitHub's
  file viewer shows HTML as source code, not rendered, so downloading (or
  pulling locally) is the way to actually see the dashboard.
- **Checking a run succeeded**: repo → **Actions** tab shows every run
  and its logs.

### A known caveat

Yahoo Finance (via `yfinance`) occasionally rate-limits or blocks requests
coming from cloud/datacenter IP ranges, including GitHub's runners — this
can vary over time and isn't something I can guarantee from here. After
setting this up, trigger a manual run (**Actions → Run workflow**) and
check the logs before relying on the schedule. If it turns out to be
unreliable, running locally (as before) remains the fallback.

### If you'd rather have a shareable webpage instead

GitHub Pages can turn a repo into a live URL you can open from any device,
but on GitHub's free plan, Pages sites are **public even if the source
repo is private** — so this only makes sense if you're fine with your
signals (and, since it reads the same repo, your trades) being visible to
anyone with the link. If that's acceptable, say so and I'll set up a
`docs/` folder + Pages workflow that publishes a "latest report" page.

