"""
report.py
---------
Builds the self-contained interactive HTML report. No external CDN calls -
everything (CSS + JS) is inlined so the file works fully offline once
generated, in any browser.
"""

import html as _html
from datetime import date, datetime, timedelta


def _esc(x):
    return _html.escape(str(x)) if x is not None else ""


def _signal_badge(signal):
    cls = {"BUY": "badge-buy", "SELL": "badge-sell", "NONE": "badge-none"}.get(signal, "badge-none")
    label = {"BUY": "BUY", "SELL": "SELL", "NONE": "—"}.get(signal, "—")
    return f'<span class="badge {cls}">{label}</span>'


def _direction_badge(direction):
    if direction == "Bullish":
        return '<span class="dir dir-bull">▲ Bullish</span>'
    if direction == "Bearish":
        return '<span class="dir dir-bear">▼ Bearish</span>'
    return '<span class="dir dir-none">—</span>'


def _fmt_num(x, dp=2):
    if x is None:
        return "—"
    return f"{x:,.{dp}f}"


def _row_html(r):
    ticker = _esc(r["ticker"])
    status = r.get("status")

    if status != "ok":
        reason = _esc(r.get("error") or "Unknown issue")
        return f"""
        <tr class="row-error" data-ticker="{ticker.lower()}" data-signal="none" data-flip="0" data-held="0">
          <td class="rail rail-none"></td>
          <td class="col-ticker">{ticker}</td>
          <td colspan="8" class="error-cell">⚠ {reason}</td>
        </tr>"""

    direction = r["direction"]
    signal = r["signal"]
    flip = r["flip"]
    changed_since_last_run = r.get("changed_since_last_run", False)
    held = r["held"]
    is_new = r["is_new"]

    rail_cls = "rail-bull" if direction == "Bullish" else "rail-bear"
    last_recorded = r.get("last_recorded_signal")
    last_recorded_dir = r.get("last_recorded_direction")

    if is_new or last_recorded_dir is None:
        last_recorded_html = '<span class="muted">new — no prior run</span>'
    else:
        last_recorded_html = _direction_badge(last_recorded_dir)
        if last_recorded and last_recorded != "NONE":
            last_recorded_html += " " + _signal_badge(last_recorded)

    held_html = '<span class="held-yes">● Held</span>' if held else '<span class="muted">—</span>'
    pnl_html = "—"
    if held and r.get("open_trades"):
        parts = []
        for t in r["open_trades"]:
            pnl = t.get("pnl_pct")
            qty = t.get("Quantity", "")
            entry = t.get("EntryPrice", "")
            if pnl is not None:
                pnl_cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
                parts.append(f'<span class="{pnl_cls}">{pnl:+.2f}%</span> <span class="muted">(qty {qty} @ {entry})</span>')
            else:
                parts.append('<span class="muted">n/a</span>')
        pnl_html = "<br>".join(parts)

    if signal in ("BUY", "SELL"):
        flip_html = '<span class="flip-yes">✓ Flip</span>'
    elif changed_since_last_run:
        flip_html = '<span class="flip-changed" title="Direction differs from your last run, though it did not cross on the very latest bar - you likely missed the exact day.">↺ Changed since last run</span>'
    else:
        flip_html = '<span class="muted">—</span>'

    # "In Trend" column - how long the current direction has been running
    bars = r.get("bars_in_trend")
    unit = r.get("bar_unit", "d")
    trend_start = r.get("trend_start_date") or ""
    if bars is None:
        in_trend_html = '<span class="muted">—</span>'
        in_trend_sort = ""
    else:
        cls = "trend-bull" if direction == "Bullish" else "trend-bear"
        word = ("day" if unit == "d" else "week") + ("s" if bars != 1 else "")
        tip = f"Direction has been {direction} for {bars} {word} — since {trend_start}."
        in_trend_html = f'<span class="in-trend {cls}" title="{_esc(tip)}">{bars}{unit}</span>'
        in_trend_sort = str(bars)

    return f"""
    <tr data-ticker="{ticker.lower()}" data-signal="{signal.lower()}" data-flip="{'1' if flip else '0'}" data-held="{'1' if held else '0'}">
      <td class="rail {rail_cls}"></td>
      <td class="col-ticker">{ticker}</td>
      <td data-sort="{r['close']}">{_fmt_num(r['close'])}</td>
      <td data-sort="{r['supertrend']}">{_fmt_num(r['supertrend'])}</td>
      <td>{_direction_badge(direction)}</td>
      <td>{_signal_badge(signal)}</td>
      <td>{last_recorded_html}</td>
      <td>{flip_html}</td>
      <td data-sort="{in_trend_sort}">{in_trend_html}</td>
      <td>{held_html}</td>
      <td>{pnl_html}</td>
      <td class="muted small">{_esc(r.get('last_bar_date') or '—')}</td>
    </tr>"""


def _alert_html(a):
    ticker = _esc(a["ticker"])
    close = _fmt_num(a["close"])
    date_ = _esc(a.get("last_bar_date"))
    trades_bits = []
    for t in a.get("open_trades", []):
        pnl = t.get("pnl_pct")
        pnl_str = f"{pnl:+.2f}%" if pnl is not None else "n/a"
        trades_bits.append(f"entry {_esc(t.get('EntryPrice'))} · qty {_esc(t.get('Quantity'))} · P/L {pnl_str}")
    trades_str = " · ".join(trades_bits) if trades_bits else ""

    if a.get("signal") == "SELL":
        timing_note = f"Flipped <strong>Bearish</strong> on the most recent bar ({date_}) at close {close}."
    else:
        last_seen = _esc(a.get("last_recorded_date") or "your last run")
        timing_note = (
            f"Already <strong>Bearish</strong> as of {date_} (close {close}) — this differs from what was "
            f"recorded last time you ran the scanner ({last_seen}), so you may have missed the exact flip."
        )

    return f"""
    <div class="alert-item">
      <div class="alert-ticker">{ticker}</div>
      <div class="alert-body">
        {timing_note}
        <div class="alert-trade">{trades_str}</div>
      </div>
    </div>"""


def _buy_html(r):
    ticker = _esc(r["ticker"])
    close = _fmt_num(r["close"])
    st = _fmt_num(r["supertrend"])
    date_ = _esc(r.get("last_bar_date"))
    return f"""
    <div class="buy-item">
      <div class="buy-ticker">{ticker}</div>
      <div class="buy-meta">Close {close} <span class="muted">·</span> Supertrend {st} <span class="muted">·</span> {date_}</div>
    </div>"""


CSS_JS = """
<style>
  :root {
    --bg: #0B0E14;
    --panel: #12161F;
    --panel-2: #171C27;
    --border: #232A38;
    --text: #E7ECF3;
    --muted: #7C8797;
    --bull: #2FBF71;
    --bull-bg: rgba(47,191,113,0.12);
    --bear: #F0475D;
    --bear-bg: rgba(240,71,93,0.12);
    --amber: #F0A93D;
    --amber-bg: rgba(240,169,61,0.10);
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Consolas, "Cascadia Code", monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.5;
    padding: 32px 24px 80px;
  }
  .wrap { max-width: 1180px; margin: 0 auto; }
  .topbar { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
  .topbar h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.01em; margin: 0; }
  .topbar .params { color: var(--muted); font-family: var(--mono); font-size: 12.5px; }

  .alert-banner { background: var(--bear-bg); border: 1px solid rgba(240,71,93,0.35); border-radius: 10px; padding: 16px 18px; margin-bottom: 22px; }
  .alert-banner .alert-head { display:flex; align-items:center; gap:8px; font-weight:700; color: var(--bear); margin-bottom: 10px; font-size: 13.5px; text-transform: uppercase; letter-spacing: 0.03em; }
  .alert-item { display:flex; gap:14px; padding: 8px 0; border-top: 1px solid rgba(240,71,93,0.18); }
  .alert-item:first-of-type { border-top: none; }
  .alert-ticker { font-family: var(--mono); font-weight: 700; min-width: 90px; color: var(--text); }
  .alert-body { color: var(--text); font-size: 13.5px; }
  .alert-trade { color: var(--muted); font-size: 12.5px; margin-top: 2px; font-family: var(--mono); }

  .stats-row { display:flex; gap: 12px; margin-bottom: 22px; flex-wrap: wrap; }
  .stat-chip { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 12px 18px; min-width: 120px; }
  .stat-chip .num { font-family: var(--mono); font-size: 22px; font-weight: 700; }
  .stat-chip .label { color: var(--muted); font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 2px; }
  .stat-buy .num { color: var(--bull); }
  .stat-sell .num { color: var(--bear); }

  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; margin-bottom: 22px; }
  .panel h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 14px; }
  .buy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
  .buy-item { background: var(--bull-bg); border: 1px solid rgba(47,191,113,0.3); border-radius: 8px; padding: 10px 12px; }
  .buy-ticker { font-family: var(--mono); font-weight: 700; color: var(--bull); }
  .buy-meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
  .empty-note { color: var(--muted); font-size: 13px; }

  .controls { display:flex; gap: 10px; align-items:center; margin-bottom: 14px; flex-wrap: wrap; }
  .chip-btn { background: var(--panel-2); border: 1px solid var(--border); color: var(--muted); padding: 6px 14px; border-radius: 999px; font-size: 12.5px; cursor: pointer; font-family: var(--sans); }
  .chip-btn.active { background: var(--text); color: var(--bg); border-color: var(--text); font-weight: 600; }
  .search-box { margin-left: auto; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; color: var(--text); font-size: 13px; font-family: var(--mono); width: 200px; }
  .search-box::placeholder { color: var(--muted); }

  table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 13px; }
  thead th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; padding: 10px 10px; border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; white-space: nowrap; font-family: var(--sans); }
  thead th:hover { color: var(--text); }
  thead th.sorted-asc::after { content: " ↑"; }
  thead th.sorted-desc::after { content: " ↓"; }
  tbody td { padding: 9px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tbody tr:hover { background: var(--panel-2); }
  td.rail { width: 4px; padding: 0; }
  .rail-bull { background: var(--bull); }
  .rail-bear { background: var(--bear); }
  .rail-none { background: var(--border); }
  .col-ticker { font-weight: 700; }
  .error-cell { color: var(--amber); font-family: var(--sans); font-size: 12.5px; }

  .badge { display:inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 700; letter-spacing: 0.02em; }
  .badge-buy { background: var(--bull-bg); color: var(--bull); }
  .badge-sell { background: var(--bear-bg); color: var(--bear); }
  .badge-none { background: transparent; color: var(--muted); font-weight: 400; }

  .dir { font-size: 12.5px; }
  .dir-bull { color: var(--bull); }
  .dir-bear { color: var(--bear); }
  .dir-none { color: var(--muted); }

  .muted { color: var(--muted); }
  .small { font-size: 11.5px; }
  .held-yes { color: var(--amber); font-weight: 700; font-size: 12px; }
  .flip-yes { color: var(--text); background: rgba(231,236,243,0.08); padding: 2px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 700; }
  .flip-changed { color: var(--amber); background: var(--amber-bg); padding: 2px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 700; cursor: help; }
  .in-trend { display:inline-block; padding: 2px 8px; border-radius: 999px; font-family: var(--mono); font-size: 11.5px; font-weight: 700; cursor: help; }
  .trend-bull { color: var(--bull); background: var(--bull-bg); }
  .trend-bear { color: var(--bear); background: var(--bear-bg); }
  .pnl-pos { color: var(--bull); font-weight: 700; }
  .pnl-neg { color: var(--bear); font-weight: 700; }

  footer { margin-top: 30px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); padding-top: 16px; }
  tr.row-error { opacity: 0.7; }
  tr.hidden-row { display: none; }
</style>
"""

JS = """
<script>
  (function() {
    var currentFilter = 'all';
    var searchTerm = '';

    function applyFilters() {
      var rows = document.querySelectorAll('#scan-table tbody tr');
      rows.forEach(function(row) {
        var signal = row.getAttribute('data-signal');
        var flip = row.getAttribute('data-flip');
        var held = row.getAttribute('data-held');
        var ticker = row.getAttribute('data-ticker') || '';

        var matchesFilter = true;
        if (currentFilter === 'buy') matchesFilter = signal === 'buy';
        else if (currentFilter === 'sell') matchesFilter = signal === 'sell';
        else if (currentFilter === 'flip') matchesFilter = flip === '1';
        else if (currentFilter === 'held') matchesFilter = held === '1';

        var matchesSearch = ticker.indexOf(searchTerm) !== -1;

        row.classList.toggle('hidden-row', !(matchesFilter && matchesSearch));
      });
    }

    document.querySelectorAll('.chip-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('.chip-btn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        currentFilter = btn.getAttribute('data-filter');
        applyFilters();
      });
    });

    var search = document.getElementById('search-box');
    if (search) {
      search.addEventListener('input', function() {
        searchTerm = search.value.trim().toLowerCase();
        applyFilters();
      });
    }

    var sortState = {};
    document.querySelectorAll('#scan-table thead th').forEach(function(th, colIndex) {
      th.addEventListener('click', function() {
        var table = document.getElementById('scan-table');
        var tbody = table.querySelector('tbody');
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

        var asc = !(sortState[colIndex] === 'asc');
        sortState = {};
        sortState[colIndex] = asc ? 'asc' : 'desc';

        document.querySelectorAll('#scan-table thead th').forEach(function(h) {
          h.classList.remove('sorted-asc', 'sorted-desc');
        });
        th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');

        rows.sort(function(a, b) {
          var cellA = a.children[colIndex];
          var cellB = b.children[colIndex];
          if (!cellA || !cellB) return 0;
          var va = cellA.getAttribute('data-sort');
          var vb = cellB.getAttribute('data-sort');
          if (va !== null && vb !== null) {
            va = parseFloat(va); vb = parseFloat(vb);
            return asc ? va - vb : vb - va;
          }
          var ta = cellA.textContent.trim().toLowerCase();
          var tb = cellB.textContent.trim().toLowerCase();
          if (ta < tb) return asc ? -1 : 1;
          if (ta > tb) return asc ? 1 : -1;
          return 0;
        });

        rows.forEach(function(r) { tbody.appendChild(r); });
      });
    });
  })();
</script>
"""


def generate_html_report(results, alerts, run_date, atr_period, atr_multiplier, output_path, timeframe_label="Weekly"):
    ok_results = [r for r in results if r["status"] == "ok"]
    buy_signals = [r for r in ok_results if r["signal"] == "BUY"]
    sell_signals = [r for r in ok_results if r["signal"] == "SELL"]
    new_stocks = [r for r in ok_results if r["is_new"]]
    error_results = [r for r in results if r["status"] != "ok"]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- alert banner ---
    if alerts:
        alert_items = "".join(_alert_html(a) for a in alerts)
        alert_banner = f"""
        <div class="alert-banner">
          <div class="alert-head">⚠ Sell signal on {len(alerts)} stock(s) you hold ({timeframe_label.lower()} chart)</div>
          {alert_items}
        </div>"""
    else:
        alert_banner = ""

    # --- stats ---
    stats_html = f"""
    <div class="stats-row">
      <div class="stat-chip"><div class="num">{len(results)}</div><div class="label">Scanned</div></div>
      <div class="stat-chip stat-buy"><div class="num">{len(buy_signals)}</div><div class="label">Buy Signals</div></div>
      <div class="stat-chip stat-sell"><div class="num">{len(sell_signals)}</div><div class="label">Sell Signals</div></div>
      <div class="stat-chip"><div class="num">{len(new_stocks)}</div><div class="label">Newly Added</div></div>
      <div class="stat-chip"><div class="num">{len(error_results)}</div><div class="label">Errors</div></div>
    </div>"""

    # --- buy opportunities panel ---
    if buy_signals:
        buy_grid = "".join(_buy_html(r) for r in buy_signals)
        buy_panel = f"""
        <div class="panel">
          <h2>Buying Opportunities This Week</h2>
          <div class="buy-grid">{buy_grid}</div>
        </div>"""
    else:
        buy_panel = """
        <div class="panel">
          <h2>Buying Opportunities This Week</h2>
          <div class="empty-note">No fresh BUY flips this week.</div>
        </div>"""

    # --- table rows ---
    rows_html = "".join(_row_html(r) for r in results)

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Supertrend {timeframe_label} Scanner — {run_date}</title>
{CSS_JS}
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <h1>Supertrend {timeframe_label} Scanner</h1>
    <div class="params">ATR({atr_period}) &times; {atr_multiplier} &middot; {timeframe_label} chart &middot; Generated {generated_at}</div>
  </div>

  {alert_banner}
  {stats_html}
  {buy_panel}

  <div class="panel">
    <h2>Full Watchlist Detail</h2>
    <div class="controls">
      <button class="chip-btn active" data-filter="all">All</button>
      <button class="chip-btn" data-filter="buy">Buy Signals</button>
      <button class="chip-btn" data-filter="sell">Sell Signals</button>
      <button class="chip-btn" data-filter="flip">Flips Only</button>
      <button class="chip-btn" data-filter="held">My Portfolio</button>
      <input type="text" id="search-box" class="search-box" placeholder="Search ticker...">
    </div>
    <table id="scan-table">
      <thead>
        <tr>
          <th></th>
          <th>Ticker</th>
          <th>Close</th>
          <th>Supertrend</th>
          <th>Direction</th>
          <th>Signal (Latest Bar)</th>
          <th>Last Recorded</th>
          <th>Flip</th>
          <th title="How long the current direction has been running (bars in trend). d=trading days, w=weeks.">In Trend</th>
          <th>Held</th>
          <th>Position P/L</th>
          <th>Bar Date</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <footer>
    Parameters: ATR period {atr_period}, multiplier {atr_multiplier}, {timeframe_label.lower()} interval. Data via Yahoo Finance (yfinance).
    "Last Recorded" reflects the signal saved the previous time you ran this scanner (blank if the stock was just added).
    "Flip" covers both a fresh cross on the latest bar and a direction that differs from your last run even if you
    missed the exact day it happened — so it stays accurate even if you skip a run.
    This report is a personal analysis tool, not investment advice — verify signals independently before trading.
  </footer>

</div>
{JS}
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(body)

    return output_path


# --------------------------------------------------------------------------
# Combined (Weekly + Daily) report
# --------------------------------------------------------------------------
COMBINED_CSS_EXTRA = """
<style>
  .confluence-cell { text-align: center; letter-spacing: 1px; font-size: 14px; }
  .conf-bull { color: var(--bull); font-weight: 700; }
  .conf-bear { color: var(--bear); font-weight: 700; }
  .conf-mixed { color: var(--amber); font-weight: 700; }
  .conf-none { color: var(--muted); }

  .tf-cell { white-space: nowrap; }
  .tf-cell .dir { margin-right: 4px; }

  .tf-tag { display:inline-block; font-family: var(--mono); font-size: 10.5px; font-weight: 700; padding: 1px 6px; border-radius: 4px; letter-spacing: 0.04em; margin-right: 6px; text-transform: uppercase; }
  .tf-tag-w { background: rgba(120,140,220,0.18); color: #96A9E6; }
  .tf-tag-d { background: rgba(220,170,120,0.18); color: #E6BE96; }

  .buy-panels { display: grid; grid-template-columns: 1fr; gap: 14px; }
  .buy-subpanel h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 10px; display:flex; align-items:center; gap:8px; }
  .buy-subpanel h3 .count { color: var(--text); font-family: var(--mono); }
  .confluence-panel { border: 1px solid rgba(47,191,113,0.35); background: rgba(47,191,113,0.05); border-radius: 8px; padding: 12px 14px; }
  .confluence-panel h3 { color: var(--bull); }
  .confluence-panel .buy-item { background: rgba(47,191,113,0.18); }

  .stats-group-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; padding: 0 4px; align-self: center; }

  /* --- Recent flips (rolling 7-day) panel --- */
  .flip-log-panel { border: 1px solid var(--border); }
  .flip-log-panel .panel-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom: 12px; }
  .flip-log-panel .panel-head h2 { margin: 0; }
  .flip-log-panel .panel-head .subtle { color: var(--muted); font-family: var(--mono); font-size: 11.5px; }
  .flip-day { margin: 10px 0 6px; }
  .flip-day-head { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; margin-bottom: 6px; }
  .flip-day-head .today-tag { display:inline-block; margin-left: 8px; background: rgba(240,169,61,0.16); color: var(--amber); padding: 1px 7px; border-radius: 999px; font-size: 10px; letter-spacing: 0.03em; }
  .flip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; }
  .flip-card { display:flex; align-items:center; gap: 10px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--panel-2); }
  .flip-card.flip-buy  { border-color: rgba(47,191,113,0.35); background: rgba(47,191,113,0.06); }
  .flip-card.flip-sell { border-color: rgba(240,71,93,0.35);  background: rgba(240,71,93,0.06);  }
  .flip-card .flip-tkr { font-family: var(--mono); font-weight: 700; color: var(--text); min-width: 62px; }
  .flip-card .flip-meta { color: var(--muted); font-size: 11.5px; font-family: var(--mono); }
  .flip-card .flip-tag { font-family: var(--mono); font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 4px; letter-spacing: 0.04em; text-transform: uppercase; }

  /* Quality badges on flip cards */
  .flip-card .q-badge {
    margin-left: auto;
    font-family: var(--mono); font-size: 10.5px; font-weight: 700;
    padding: 2px 8px; border-radius: 999px; letter-spacing: 0.02em;
    cursor: help;
  }
  .q-high   { background: rgba(47,191,113,0.18); color: var(--bull); }
  .q-med    { background: rgba(240,169,61,0.18); color: var(--amber); }
  .q-low    { background: rgba(231,236,243,0.06); color: var(--muted); }
  .q-star   { color: var(--amber); margin-right: 4px; font-weight: 700; }

  .flip-mode-note { color: var(--muted); font-size: 11.5px; font-style: italic; }
  .flip-topbadge {
    display:inline-block; margin-left: 10px; background: rgba(47,191,113,0.16);
    color: var(--bull); padding: 1px 8px; border-radius: 999px;
    font-size: 10.5px; letter-spacing: 0.03em; font-weight: 700;
  }

  tr.hidden-row { display: none; }
</style>
"""

COMBINED_JS = """
<script>
  (function() {
    var currentFilter = 'all';
    var searchTerm = '';

    function applyFilters() {
      var rows = document.querySelectorAll('#scan-table tbody tr');
      rows.forEach(function(row) {
        var wSig = row.getAttribute('data-w-signal');
        var dSig = row.getAttribute('data-d-signal');
        var wFlip = row.getAttribute('data-w-flip') === '1';
        var dFlip = row.getAttribute('data-d-flip') === '1';
        var held = row.getAttribute('data-held') === '1';
        var confluence = row.getAttribute('data-confluence');
        var ticker = row.getAttribute('data-ticker') || '';

        var dRec = parseInt(row.getAttribute('data-d-recency') || '9999', 10);
        var wRec = parseInt(row.getAttribute('data-w-recency') || '9999', 10);

        var m = true;
        switch (currentFilter) {
          case 'recent7':      m = dRec <= 7 || wRec <= 1; break;  // 7 daily bars OR 1 weekly bar ~= last week
          case 'any-buy':      m = wSig === 'buy' || dSig === 'buy'; break;
          case 'any-sell':     m = wSig === 'sell' || dSig === 'sell'; break;
          case 'conf-bull':    m = confluence === 'bull'; break;
          case 'conf-bear':    m = confluence === 'bear'; break;
          case 'weekly-flip':  m = wFlip; break;
          case 'daily-flip':   m = dFlip; break;
          case 'held':         m = held; break;
          default:             m = true;
        }
        var matchesSearch = ticker.indexOf(searchTerm) !== -1;
        row.classList.toggle('hidden-row', !(m && matchesSearch));
      });
    }

    document.querySelectorAll('.chip-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('.chip-btn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        currentFilter = btn.getAttribute('data-filter');
        applyFilters();
      });
    });

    var search = document.getElementById('search-box');
    if (search) {
      search.addEventListener('input', function() {
        searchTerm = search.value.trim().toLowerCase();
        applyFilters();
      });
    }

    var sortState = {};
    document.querySelectorAll('#scan-table thead th').forEach(function(th, colIndex) {
      th.addEventListener('click', function() {
        var table = document.getElementById('scan-table');
        var tbody = table.querySelector('tbody');
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

        var asc = !(sortState[colIndex] === 'asc');
        sortState = {};
        sortState[colIndex] = asc ? 'asc' : 'desc';

        document.querySelectorAll('#scan-table thead th').forEach(function(h) {
          h.classList.remove('sorted-asc', 'sorted-desc');
        });
        th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');

        rows.sort(function(a, b) {
          var cellA = a.children[colIndex];
          var cellB = b.children[colIndex];
          if (!cellA || !cellB) return 0;
          var va = cellA.getAttribute('data-sort');
          var vb = cellB.getAttribute('data-sort');
          if (va !== null && vb !== null) {
            va = parseFloat(va); vb = parseFloat(vb);
            return asc ? va - vb : vb - va;
          }
          var ta = cellA.textContent.trim().toLowerCase();
          var tb = cellB.textContent.trim().toLowerCase();
          if (ta < tb) return asc ? -1 : 1;
          if (ta > tb) return asc ? 1 : -1;
          return 0;
        });

        rows.forEach(function(r) { tbody.appendChild(r); });
      });
    });
  })();
</script>
"""


def _tf_status(r):
    """Compact per-timeframe state, tolerant of missing/erroring results."""
    if r is None:
        return {"present": False, "ok": False, "direction": None, "signal": "NONE",
                "flip": False, "changed": False, "close": None, "supertrend": None,
                "bar_date": None, "bars_in_trend": None, "trend_start_date": None,
                "bar_unit": "d", "error": "not in this scan"}
    if r.get("status") != "ok":
        return {"present": True, "ok": False, "direction": None, "signal": "NONE",
                "flip": False, "changed": False, "close": None, "supertrend": None,
                "bar_date": None, "bars_in_trend": None, "trend_start_date": None,
                "bar_unit": r.get("bar_unit", "d"),
                "error": r.get("error") or r.get("status")}
    return {
        "present": True, "ok": True,
        "direction": r["direction"], "signal": r["signal"],
        "flip": r.get("flip", False),
        "changed": r.get("changed_since_last_run", False),
        "close": r.get("close"), "supertrend": r.get("supertrend"),
        "bar_date": r.get("last_bar_date"),
        "bars_in_trend": r.get("bars_in_trend"),
        "trend_start_date": r.get("trend_start_date"),
        "bar_unit": r.get("bar_unit", "d"),
        "error": None,
    }


def _combined_tf_cell(state):
    """Render one 'Direction + Signal + ST + In-Trend' cell for a single timeframe."""
    if not state["ok"]:
        note = _esc(state.get("error") or "n/a")
        return f'<span class="muted small" title="{note}">—</span>'
    dir_html = _direction_badge(state["direction"])
    sig_html = _signal_badge(state["signal"])
    if state["signal"] == "NONE" and state["changed"]:
        # Direction differs from last run but not on the very latest bar.
        sig_html = '<span class="flip-changed" title="Direction differs from your last run, though it did not cross on the very latest bar - you likely missed the exact day.">↺ Changed</span>'
    st = _fmt_num(state["supertrend"])

    bars = state.get("bars_in_trend")
    unit = state.get("bar_unit", "d")
    if bars is None:
        trend_html = ""
    else:
        cls = "trend-bull" if state["direction"] == "Bullish" else "trend-bear"
        word = ("day" if unit == "d" else "week") + ("s" if bars != 1 else "")
        tip = f"{state['direction']} for {bars} {word} — since {state.get('trend_start_date') or ''}"
        trend_html = f' <span class="in-trend {cls}" title="{_esc(tip)}">{bars}{unit}</span>'

    return f'<span class="tf-cell">{dir_html} {sig_html}{trend_html} <span class="muted small">ST {st}</span></span>'


def _confluence_cell(w, d):
    """Bull/Bear/Mixed indicator based on both timeframes' current direction."""
    if not (w["ok"] and d["ok"]):
        return '<span class="confluence-cell conf-none">—</span>', "none"
    if w["direction"] == "Bullish" and d["direction"] == "Bullish":
        return '<span class="confluence-cell conf-bull" title="Both weekly and daily are bullish">▲▲</span>', "bull"
    if w["direction"] == "Bearish" and d["direction"] == "Bearish":
        return '<span class="confluence-cell conf-bear" title="Both weekly and daily are bearish">▼▼</span>', "bear"
    return '<span class="confluence-cell conf-mixed" title="Weekly and daily disagree">▲▼</span>', "mixed"


def _combined_row_html(ticker, weekly_r, daily_r, public_view=False):
    w = _tf_status(weekly_r)
    d = _tf_status(daily_r)

    # Numeric ranks used for sorting. Lower = "more interesting", so
    # ascending sort naturally puts freshest daily flips / bullish
    # confluence at the top.
    conf_rank = {"bull": 0, "bear": 1, "mixed": 2, "none": 3}
    # bars_in_trend of 1 means "flipped on the latest bar" — the smaller
    # the number, the more recent the flip. Missing → 9999 so it sinks.
    d_recency = d.get("bars_in_trend") if d.get("ok") else None
    w_recency = w.get("bars_in_trend") if w.get("ok") else None
    d_recency_sort = d_recency if d_recency is not None else 9999
    w_recency_sort = w_recency if w_recency is not None else 9999

    # If BOTH are non-ok, render an error row spanning the metric columns.
    if not w["ok"] and not d["ok"]:
        errs = []
        if w["error"]: errs.append(f"weekly: {w['error']}")
        if d["error"]: errs.append(f"daily: {d['error']}")
        # Public view has 2 fewer columns (no Held / P/L) → shorter colspan.
        colspan = 6 if public_view else 8
        return f"""
        <tr class="row-error" data-ticker="{_esc(ticker).lower()}"
            data-w-signal="none" data-d-signal="none"
            data-w-flip="0" data-d-flip="0"
            data-w-dir="none" data-d-dir="none"
            data-held="0" data-confluence="none"
            data-d-recency="9999" data-w-recency="9999">
          <td data-sort="3" class="confluence-cell conf-none">—</td>
          <td class="col-ticker">{_esc(ticker)}</td>
          <td colspan="{colspan}" class="error-cell">⚠ {_esc(' · '.join(errs))}</td>
        </tr>"""

    conf_html, conf_key = _confluence_cell(w, d)

    # Held / P/L come from whichever timeframe carries the trade info.
    # analyze_ticker + cross_reference_trades populate both identically for a
    # ticker present in trades.csv, so prefer daily for the freshest close,
    # falling back to weekly.
    trade_source = daily_r if (daily_r and daily_r.get("held")) else weekly_r if (weekly_r and weekly_r.get("held")) else None
    held = bool(trade_source and trade_source.get("held"))
    held_html = '<span class="held-yes">● Held</span>' if held else '<span class="muted">—</span>'
    pnl_html = "—"
    if held and trade_source.get("open_trades"):
        parts = []
        for t in trade_source["open_trades"]:
            pnl = t.get("pnl_pct")
            qty = t.get("Quantity", "")
            entry = t.get("EntryPrice", "")
            if pnl is not None:
                cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
                parts.append(f'<span class="{cls}">{pnl:+.2f}%</span> <span class="muted">(qty {qty} @ {entry})</span>')
            else:
                parts.append('<span class="muted">n/a</span>')
        pnl_html = "<br>".join(parts)

    # Latest price: daily close if present, else weekly close.
    close_source = d["close"] if d["ok"] else w["close"]

    w_dir_key = (w["direction"] or "none").lower() if w["ok"] else "none"
    d_dir_key = (d["direction"] or "none").lower() if d["ok"] else "none"

    # Public view strips the two portfolio columns (Held + Position P/L).
    portfolio_cells = "" if public_view else f"""
      <td>{held_html}</td>
      <td>{pnl_html}</td>"""

    return f"""
    <tr data-ticker="{_esc(ticker).lower()}"
        data-w-signal="{w['signal'].lower()}"
        data-d-signal="{d['signal'].lower()}"
        data-w-flip="{'1' if w['flip'] else '0'}"
        data-d-flip="{'1' if d['flip'] else '0'}"
        data-w-dir="{w_dir_key}"
        data-d-dir="{d_dir_key}"
        data-held="{'1' if held else '0'}"
        data-confluence="{conf_key}"
        data-d-recency="{d_recency_sort}"
        data-w-recency="{w_recency_sort}">
      <td data-sort="{conf_rank[conf_key]}">{conf_html}</td>
      <td class="col-ticker">{_esc(ticker)}</td>
      <td data-sort="{close_source if close_source is not None else ''}">{_fmt_num(close_source)}</td>
      <td data-sort="{w_recency_sort}">{_combined_tf_cell(w)}</td>
      <td data-sort="{d_recency_sort}">{_combined_tf_cell(d)}</td>{portfolio_cells}
      <td class="muted small">{_esc(w['bar_date'] or '—')}</td>
      <td class="muted small">{_esc(d['bar_date'] or '—')}</td>
    </tr>"""


def _combined_alert_html(a, timeframe_label):
    tag_cls = "tf-tag-w" if timeframe_label.lower().startswith("w") else "tf-tag-d"
    tag = f'<span class="tf-tag {tag_cls}">{_esc(timeframe_label)}</span>'
    ticker = _esc(a["ticker"])
    close = _fmt_num(a["close"])
    date_ = _esc(a.get("last_bar_date"))
    trades_bits = []
    for t in a.get("open_trades", []):
        pnl = t.get("pnl_pct")
        pnl_str = f"{pnl:+.2f}%" if pnl is not None else "n/a"
        trades_bits.append(f"entry {_esc(t.get('EntryPrice'))} · qty {_esc(t.get('Quantity'))} · P/L {pnl_str}")
    trades_str = " · ".join(trades_bits) if trades_bits else ""

    if a.get("signal") == "SELL":
        timing = f"Flipped <strong>Bearish</strong> on the most recent {timeframe_label.lower()} bar ({date_}) at close {close}."
    else:
        last_seen = _esc(a.get("last_recorded_date") or "your last run")
        timing = (
            f"Already <strong>Bearish</strong> as of {date_} (close {close}) on the {timeframe_label.lower()} chart — "
            f"this differs from what was recorded last time you ran the {timeframe_label.lower()} scanner ({last_seen})."
        )

    return f"""
    <div class="alert-item">
      <div class="alert-ticker">{tag}{ticker}</div>
      <div class="alert-body">
        {timing}
        <div class="alert-trade">{trades_str}</div>
      </div>
    </div>"""


def _quality_bucket(score):
    """Categorize a 0-100 quality score into High/Medium/Low."""
    if score is None:
        return None, None
    if score >= 70:
        return "high", "q-high"
    if score >= 40:
        return "med", "q-med"
    return "low", "q-low"


def _flip_card_html(entry, is_top_quality: bool = False):
    """
    One card for the rolling 'Recent Flips' panel. Only BUY entries reach
    here — the panel filters SELLs out at the source, since the user's
    strategy is long-only. Quality badge is shown when the entry has a
    quality_score; is_top_quality adds a ★ marker (used to auto-highlight
    the top 3 when a day has more than 5 BUYs).
    """
    ticker = _esc(entry.get("ticker", ""))
    timeframe = _esc(entry.get("timeframe", "")).lower()
    direction = _esc(entry.get("direction", ""))
    close = entry.get("close")
    close_str = _fmt_num(close)
    st = _fmt_num(entry.get("supertrend"))
    tf_cls = "tf-tag-w" if timeframe == "weekly" else "tf-tag-d"

    q = entry.get("quality_score")
    _, q_cls = _quality_bucket(q)
    if q is not None:
        vol = entry.get("quality_volume_ratio")
        mom = entry.get("quality_momentum_pct")
        prior = entry.get("quality_prior_run")
        vol_txt = f"{vol}x avg" if vol is not None else "n/a"
        mom_txt = f"{mom:+.1f}% 5-bar" if isinstance(mom, (int, float)) else "n/a"
        prior_txt = f"{prior}-bar prior trend" if prior is not None else "n/a"
        tip = f"Quality {q}/100 — volume {vol_txt}, momentum {mom_txt}, {prior_txt}"
        badge = f'<span class="q-badge {q_cls}" title="{_esc(tip)}">{q}</span>'
    else:
        badge = ""

    star = '<span class="q-star" title="Top-ranked BUY on this day">★</span>' if is_top_quality else ""

    return f"""
    <div class="flip-card flip-buy">
      <span class="flip-tag {tf_cls}">{timeframe.upper()[:1]}</span>
      <span class="flip-tkr">{star}{ticker}</span>
      <span class="flip-meta">BUY · {direction} · Close {close_str} · ST {st}</span>
      {badge}
    </div>"""


def _recent_flips_panel_html(flip_log, run_date, days=7, buy_only=True, auto_rank_threshold=5):
    """
    Rolling 'flips in the last N days' panel. Reads the shared flip log,
    keeps entries whose flip_date is within `days` calendar days of
    run_date, groups them by day (newest first), and renders each as a
    card.

    buy_only=True (default): filter out SELL entries entirely. The user's
    strategy is long-only, so SELL flips are noise here — they still get
    surfaced via the held-bearish alert banner when they matter, and
    they're still in flip_log.json for the record.

    auto_rank_threshold: when a single DAY has more than this many BUY
    flips, sort them by quality_score descending and mark the top 3 with
    a ★ so the eye goes to the high-quality candidates first. Below the
    threshold, cards are shown by quality still (highest first) but
    without the star.
    """
    if flip_log is None:
        flip_log = []
    try:
        run_d = date.fromisoformat(run_date)
    except (ValueError, TypeError):
        run_d = date.today()
    cutoff = (run_d - timedelta(days=days)).isoformat()

    kept = [e for e in flip_log if (e.get("flip_date") or "") >= cutoff]
    if buy_only:
        kept = [e for e in kept if (e.get("signal") or "").upper() == "BUY"]

    # Group by flip_date, newest date first
    by_day = {}
    for e in kept:
        by_day.setdefault(e["flip_date"], []).append(e)
    day_order = sorted(by_day.keys(), reverse=True)

    mode_note = (
        'Long-only view — SELL flips are hidden here (they still trigger the held-bearish alert). '
        'Sorted by quality within each day; ★ marks the top 3 when a day has more than '
        f'{auto_rank_threshold} candidates.'
    )
    subtle_tail = f"Anything older than {days} days rolls off this list automatically. Full history in <code>data/flip_log.json</code>."

    if not kept:
        return f"""
        <div class="panel flip-log-panel">
          <div class="panel-head">
            <h2>Recent Buy Flips (Last {days} Days)</h2>
            <span class="subtle">{subtle_tail}</span>
          </div>
          <div class="flip-mode-note">{mode_note}</div>
          <div class="empty-note" style="margin-top:10px;">No BUY flips recorded in the last {days} days — the log picks them up automatically on the next run.</div>
        </div>"""

    day_blocks = []
    for d in day_order:
        entries = by_day[d]
        # Sort by quality DESCENDING within each day; ties break by
        # timeframe (weekly first) and ticker for stability. Entries
        # missing a quality_score sort to the bottom.
        def _key(e):
            q = e.get("quality_score")
            return (-(q if q is not None else -1),
                    e.get("timeframe", ""),
                    e.get("ticker", ""))
        entries.sort(key=_key)

        # Auto-highlight the top 3 by quality when the day is crowded.
        top_set = set()
        if len(entries) > auto_rank_threshold:
            for e in entries[:3]:
                if e.get("quality_score") is not None:
                    top_set.add((e.get("ticker"), e.get("timeframe"), e.get("flip_date")))

        today_tag = ' <span class="today-tag">today</span>' if d == run_date else ""
        crowded_tag = (
            f' <span class="flip-topbadge">★ top 3 of {len(entries)}</span>'
            if len(entries) > auto_rank_threshold else ""
        )
        cards = "".join(
            _flip_card_html(e, is_top_quality=(e.get("ticker"), e.get("timeframe"), e.get("flip_date")) in top_set)
            for e in entries
        )
        day_blocks.append(
            f"""<div class="flip-day">
              <div class="flip-day-head">{_esc(d)}{today_tag}{crowded_tag}</div>
              <div class="flip-grid">{cards}</div>
            </div>"""
        )

    return f"""
    <div class="panel flip-log-panel">
      <div class="panel-head">
        <h2>Recent Buy Flips (Last {days} Days)</h2>
        <span class="subtle">{len(kept)} BUY flip(s) across {len(day_order)} day(s). {subtle_tail}</span>
      </div>
      <div class="flip-mode-note">{mode_note}</div>
      {''.join(day_blocks)}
    </div>"""


def generate_combined_html_report(weekly_scan, daily_scan, atr_period, atr_multiplier, output_path,
                                  flip_log=None, public_view=False):
    """
    One HTML report that stacks the weekly and daily views for every ticker.
    weekly_scan and daily_scan are the dicts returned by engine.run_analysis.
    flip_log is an optional list of dicts from engine.load_flip_log(); when
    provided, a rolling "Recent Flips (Last 7 Days)" panel is included.

    When public_view=True, portfolio-sensitive parts are omitted so the
    resulting HTML is safe to publish to a public URL (e.g. GitHub Pages):
      - Held / Position P/L columns are not rendered
      - "My Portfolio" filter chip is removed
      - The held-bearish alert banner is not emitted (it names held stocks)
    The watchlist, per-ticker signals, and flip log ARE still visible in
    public view - it's the "signals only" cut, not a fully private one.
    """
    weekly_results = weekly_scan["results"]
    daily_results = daily_scan["results"]
    run_date = daily_scan.get("run_date") or weekly_scan.get("run_date")

    # index by ticker
    w_by = {r["ticker"]: r for r in weekly_results}
    d_by = {r["ticker"]: r for r in daily_results}

    # Default row order: freshest DAILY flip first, then freshest weekly
    # flip, then alphabetical. bars_in_trend=1 means "flipped on the last
    # bar", so ascending puts today's flips at the top and calm trends at
    # the bottom. Users can still click any column to re-sort in the browser.
    def _sort_key(ticker):
        wr = w_by.get(ticker) or {}
        dr = d_by.get(ticker) or {}
        d_rec = dr.get("bars_in_trend") if dr.get("status") == "ok" else None
        w_rec = wr.get("bars_in_trend") if wr.get("status") == "ok" else None
        return (
            d_rec if d_rec is not None else 9999,
            w_rec if w_rec is not None else 9999,
            ticker,
        )

    all_tickers = set()
    for r in weekly_results:
        all_tickers.add(r["ticker"])
    for r in daily_results:
        all_tickers.add(r["ticker"])
    order = sorted(all_tickers, key=_sort_key)

    # --- headline counts ---
    def _ok(rs): return [r for r in rs if r.get("status") == "ok"]
    w_ok = _ok(weekly_results)
    d_ok = _ok(daily_results)
    w_buys = [r for r in w_ok if r["signal"] == "BUY"]
    w_sells = [r for r in w_ok if r["signal"] == "SELL"]
    d_buys = [r for r in d_ok if r["signal"] == "BUY"]
    d_sells = [r for r in d_ok if r["signal"] == "SELL"]
    error_count = sum(1 for r in weekly_results if r.get("status") != "ok") + \
                  sum(1 for r in daily_results if r.get("status") != "ok")

    # Confluence buys/sells: BUY/SELL flip on the latest bar in BOTH timeframes.
    w_buy_set = {r["ticker"] for r in w_buys}
    d_buy_set = {r["ticker"] for r in d_buys}
    w_sell_set = {r["ticker"] for r in w_sells}
    d_sell_set = {r["ticker"] for r in d_sells}
    confluence_buy_tickers = w_buy_set & d_buy_set
    confluence_sell_tickers = w_sell_set & d_sell_set

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- alerts, tagged by timeframe ---
    # Public view omits the alert banner entirely — it names held tickers
    # and their entry prices via the trade context, which is private.
    weekly_alerts = weekly_scan.get("alerts", [])
    daily_alerts = daily_scan.get("alerts", [])
    all_alerts = [(a, "Weekly") for a in weekly_alerts] + [(a, "Daily") for a in daily_alerts]

    if all_alerts and not public_view:
        alert_items = "".join(_combined_alert_html(a, tf) for (a, tf) in all_alerts)
        alert_banner = f"""
        <div class="alert-banner">
          <div class="alert-head">⚠ Sell signal on held stock(s) — {len(weekly_alerts)} weekly, {len(daily_alerts)} daily</div>
          {alert_items}
        </div>"""
    else:
        alert_banner = ""

    # --- stats ---
    stats_html = f"""
    <div class="stats-row">
      <div class="stat-chip"><div class="num">{len(order)}</div><div class="label">Tickers</div></div>
      <div class="stats-group-label">Weekly</div>
      <div class="stat-chip stat-buy"><div class="num">{len(w_buys)}</div><div class="label">Buy</div></div>
      <div class="stat-chip stat-sell"><div class="num">{len(w_sells)}</div><div class="label">Sell</div></div>
      <div class="stats-group-label">Daily</div>
      <div class="stat-chip stat-buy"><div class="num">{len(d_buys)}</div><div class="label">Buy</div></div>
      <div class="stat-chip stat-sell"><div class="num">{len(d_sells)}</div><div class="label">Sell</div></div>
      <div class="stats-group-label">Confluence</div>
      <div class="stat-chip stat-buy"><div class="num">{len(confluence_buy_tickers)}</div><div class="label">Buy (both)</div></div>
      <div class="stat-chip stat-sell"><div class="num">{len(confluence_sell_tickers)}</div><div class="label">Sell (both)</div></div>
      <div class="stat-chip"><div class="num">{error_count}</div><div class="label">Errors</div></div>
    </div>"""

    # --- buy opportunity panels ---
    def _buy_grid(rs):
        if not rs:
            return '<div class="empty-note">Nothing fresh.</div>'
        return '<div class="buy-grid">' + "".join(_buy_html(r) for r in rs) + '</div>'

    confluence_buy_results = [r for r in d_buys if r["ticker"] in confluence_buy_tickers] \
                             or [r for r in w_buys if r["ticker"] in confluence_buy_tickers]

    buy_panels = f"""
    <div class="panel">
      <h2>Buying Opportunities</h2>
      <div class="buy-panels">
        <div class="buy-subpanel confluence-panel">
          <h3>★ Confluence Buy (fresh BUY on both weekly &amp; daily) <span class="count">{len(confluence_buy_tickers)}</span></h3>
          {_buy_grid(confluence_buy_results)}
        </div>
        <div class="buy-subpanel">
          <h3><span class="tf-tag tf-tag-w">Weekly</span> Buy Flips <span class="count">{len(w_buys)}</span></h3>
          {_buy_grid(w_buys)}
        </div>
        <div class="buy-subpanel">
          <h3><span class="tf-tag tf-tag-d">Daily</span> Buy Flips <span class="count">{len(d_buys)}</span></h3>
          {_buy_grid(d_buys)}
        </div>
      </div>
    </div>"""

    # --- rolling recent-flips panel (last 7 days) ---
    recent_flips_panel = _recent_flips_panel_html(flip_log, run_date, days=7)

    # --- full merged table ---
    rows_html = "".join(_combined_row_html(t, w_by.get(t), d_by.get(t), public_view=public_view) for t in order)

    # Header + filter chips flex based on public_view.
    portfolio_headers = "" if public_view else """
          <th>Held</th>
          <th>Position P/L</th>"""
    portfolio_chip = "" if public_view else """
      <button class="chip-btn" data-filter="held">My Portfolio</button>"""
    title_suffix = " · Public view" if public_view else ""
    private_notice = "" if public_view else ""
    public_notice = ("" if not public_view else
        '<div class="params" style="margin-top:6px;">Public view — portfolio positions are hidden. Signals, watchlist, and flip log are shown as-is.</div>')

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Supertrend Combined Scanner — {run_date}</title>
{CSS_JS}
{COMBINED_CSS_EXTRA}
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <h1>Supertrend Combined Scanner{title_suffix}</h1>
    <div class="params">ATR({atr_period}) &times; {atr_multiplier} &middot; Weekly + Daily &middot; Generated {generated_at}</div>
    {public_notice}
  </div>

  {alert_banner}
  {recent_flips_panel}
  {stats_html}
  {buy_panels}

  <div class="panel">
    <h2>Full Watchlist — Weekly &amp; Daily Side-by-Side</h2>
    <div class="controls">
      <button class="chip-btn active" data-filter="all">All</button>
      <button class="chip-btn" data-filter="recent7">Recent (7d)</button>
      <button class="chip-btn" data-filter="any-buy">Any Buy</button>
      <button class="chip-btn" data-filter="any-sell">Any Sell</button>
      <button class="chip-btn" data-filter="conf-bull">Confluence ▲▲</button>
      <button class="chip-btn" data-filter="conf-bear">Confluence ▼▼</button>
      <button class="chip-btn" data-filter="weekly-flip">Weekly Flips</button>
      <button class="chip-btn" data-filter="daily-flip">Daily Flips</button>{portfolio_chip}
      <input type="text" id="search-box" class="search-box" placeholder="Search ticker...">
    </div>
    <table id="scan-table">
      <thead>
        <tr>
          <th title="Both weekly and daily agree bullish (▲▲) / bearish (▼▼) / mixed (▲▼) — click to sort: bull → bear → mixed → none">Conf. ↕</th>
          <th>Ticker</th>
          <th>Close</th>
          <th title="Click to sort by weekly bars-in-trend (freshest weekly flip first)"><span class="tf-tag tf-tag-w">W</span>Weekly (dir · signal · in-trend · ST) ↕</th>
          <th title="Click to sort by daily bars-in-trend (freshest daily flip first) — this is the default order"><span class="tf-tag tf-tag-d">D</span>Daily (dir · signal · in-trend · ST) ↕</th>{portfolio_headers}
          <th>Weekly Bar</th>
          <th>Daily Bar</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <footer>
    Parameters: ATR period {atr_period}, multiplier {atr_multiplier}. Data via Yahoo Finance (yfinance).
    "Signal" is a fresh cross on the latest bar of that timeframe. "↺ Changed" means the current direction
    differs from what was saved last time you ran that scanner even if the exact flip bar has already passed
    — so nothing is missed if you skip a run. "In-trend" counts the consecutive bars the current direction has
    been running (d = trading days, w = weeks; hover for the start date). "Confluence" agrees when both
    weekly and daily point the same way. The table is sorted by daily flip recency by default (freshest first);
    click any column header to re-sort — Confluence sorts bull → bear → mixed → none. The "Recent Flips" panel
    reads from <code>data/flip_log.json</code>, which every run of any scanner appends to.
    This report is a personal analysis tool, not investment advice — verify signals independently before trading.
  </footer>

</div>
{COMBINED_JS}
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(body)

    return output_path
