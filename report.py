"""
report.py
---------
Builds the self-contained interactive HTML report. No external CDN calls -
everything (CSS + JS) is inlined so the file works fully offline once
generated, in any browser.
"""

import html as _html
from datetime import datetime


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
          <td colspan="7" class="error-cell">⚠ {reason}</td>
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
