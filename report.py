"""
report.py
---------
Builds the self-contained interactive HTML reports (per-timeframe,
combined archive, and tabbed public page).
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


# --------------------------------------------------------------------------
# Per-timeframe (weekly OR daily) report
# --------------------------------------------------------------------------
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
    direction = r["direction"]; signal = r["signal"]; flip = r["flip"]
    changed = r.get("changed_since_last_run", False); held = r["held"]; is_new = r["is_new"]
    rail_cls = "rail-bull" if direction == "Bullish" else "rail-bear"
    last_rec = r.get("last_recorded_signal"); last_dir = r.get("last_recorded_direction")
    if is_new or last_dir is None:
        last_rec_html = '<span class="muted">new — no prior run</span>'
    else:
        last_rec_html = _direction_badge(last_dir)
        if last_rec and last_rec != "NONE":
            last_rec_html += " " + _signal_badge(last_rec)
    held_html = '<span class="held-yes">● Held</span>' if held else '<span class="muted">—</span>'
    pnl_html = "—"
    if held and r.get("open_trades"):
        parts = []
        for t in r["open_trades"]:
            pnl = t.get("pnl_pct"); qty = t.get("Quantity", ""); entry = t.get("EntryPrice", "")
            if pnl is not None:
                cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
                parts.append(f'<span class="{cls}">{pnl:+.2f}%</span> <span class="muted">(qty {qty} @ {entry})</span>')
            else:
                parts.append('<span class="muted">n/a</span>')
        pnl_html = "<br>".join(parts)
    if signal in ("BUY", "SELL"):
        flip_html = '<span class="flip-yes">✓ Flip</span>'
    elif changed:
        flip_html = '<span class="flip-changed" title="Direction differs from your last run.">↺ Changed since last run</span>'
    else:
        flip_html = '<span class="muted">—</span>'
    bars = r.get("bars_in_trend"); unit = r.get("bar_unit", "d"); trend_start = r.get("trend_start_date") or ""
    if bars is None:
        in_trend_html = '<span class="muted">—</span>'; in_trend_sort = ""
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
      <td>{last_rec_html}</td>
      <td>{flip_html}</td>
      <td data-sort="{in_trend_sort}">{in_trend_html}</td>
      <td>{held_html}</td>
      <td>{pnl_html}</td>
      <td class="muted small">{_esc(r.get('last_bar_date') or '—')}</td>
    </tr>"""


def _alert_html(a):
    ticker = _esc(a["ticker"]); close = _fmt_num(a["close"]); date_ = _esc(a.get("last_bar_date"))
    trades_bits = []
    for t in a.get("open_trades", []):
        pnl = t.get("pnl_pct")
        pnl_str = f"{pnl:+.2f}%" if pnl is not None else "n/a"
        trades_bits.append(f"entry {_esc(t.get('EntryPrice'))} · qty {_esc(t.get('Quantity'))} · P/L {pnl_str}")
    trades_str = " · ".join(trades_bits) if trades_bits else ""
    if a.get("signal") == "SELL":
        timing = f"Flipped <strong>Bearish</strong> on the most recent bar ({date_}) at close {close}."
    else:
        last_seen = _esc(a.get("last_recorded_date") or "your last run")
        timing = (f"Already <strong>Bearish</strong> as of {date_} (close {close}) — differs from last run ({last_seen}).")
    return f"""
    <div class="alert-item">
      <div class="alert-ticker">{ticker}</div>
      <div class="alert-body">{timing}<div class="alert-trade">{trades_str}</div></div>
    </div>"""


def _buy_html(r):
    ticker = _esc(r["ticker"]); close = _fmt_num(r["close"]); st = _fmt_num(r["supertrend"]); date_ = _esc(r.get("last_bar_date"))
    return f"""
    <div class="buy-item">
      <div class="buy-ticker">{ticker}</div>
      <div class="buy-meta">Close {close} <span class="muted">·</span> Supertrend {st} <span class="muted">·</span> {date_}</div>
    </div>"""


CSS_JS = """
<style>
  :root {
    --bg:#0B0E14; --panel:#12161F; --panel-2:#171C27; --border:#232A38;
    --text:#E7ECF3; --muted:#7C8797;
    --bull:#2FBF71; --bull-bg:rgba(47,191,113,0.12);
    --bear:#F0475D; --bear-bg:rgba(240,71,93,0.12);
    --amber:#F0A93D; --amber-bg:rgba(240,169,61,0.10);
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Consolas, "Cascadia Code", monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font-family:var(--sans);
         font-size:14px; line-height:1.5; padding:32px 24px 80px; }
  .wrap { max-width:1180px; margin:0 auto; }
  .topbar { display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap;
            gap:8px; margin-bottom:24px; border-bottom:1px solid var(--border); padding-bottom:20px; }
  .topbar h1 { font-size:20px; font-weight:700; letter-spacing:-0.01em; margin:0; }
  .topbar .params { color:var(--muted); font-family:var(--mono); font-size:12.5px; }
  .alert-banner { background:var(--bear-bg); border:1px solid rgba(240,71,93,0.35); border-radius:10px; padding:16px 18px; margin-bottom:22px; }
  .alert-banner .alert-head { display:flex; align-items:center; gap:8px; font-weight:700; color:var(--bear); margin-bottom:10px; font-size:13.5px; text-transform:uppercase; letter-spacing:0.03em; }
  .alert-item { display:flex; gap:14px; padding:8px 0; border-top:1px solid rgba(240,71,93,0.18); }
  .alert-item:first-of-type { border-top:none; }
  .alert-ticker { font-family:var(--mono); font-weight:700; min-width:90px; color:var(--text); }
  .alert-body { color:var(--text); font-size:13.5px; }
  .alert-trade { color:var(--muted); font-size:12.5px; margin-top:2px; font-family:var(--mono); }
  .stats-row { display:flex; gap:12px; margin-bottom:22px; flex-wrap:wrap; }
  .stat-chip { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px 18px; min-width:120px; }
  .stat-chip .num { font-family:var(--mono); font-size:22px; font-weight:700; }
  .stat-chip .label { color:var(--muted); font-size:11.5px; text-transform:uppercase; letter-spacing:0.04em; margin-top:2px; }
  .stat-buy .num { color:var(--bull); }
  .stat-sell .num { color:var(--bear); }
  .panel { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:18px 20px; margin-bottom:22px; }
  .panel h2 { font-size:13px; text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); margin:0 0 14px; }
  .buy-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(220px,1fr)); gap:10px; }
  .buy-item { background:var(--bull-bg); border:1px solid rgba(47,191,113,0.3); border-radius:8px; padding:10px 12px; }
  .buy-ticker { font-family:var(--mono); font-weight:700; color:var(--bull); }
  .buy-meta { color:var(--muted); font-size:12px; margin-top:3px; }
  .empty-note { color:var(--muted); font-size:13px; }
  .controls { display:flex; gap:10px; align-items:center; margin-bottom:14px; flex-wrap:wrap; }
  .chip-btn { background:var(--panel-2); border:1px solid var(--border); color:var(--muted); padding:6px 14px; border-radius:999px; font-size:12.5px; cursor:pointer; font-family:var(--sans); }
  .chip-btn.active { background:var(--text); color:var(--bg); border-color:var(--text); font-weight:600; }
  .search-box { margin-left:auto; background:var(--panel-2); border:1px solid var(--border); border-radius:8px; padding:6px 12px; color:var(--text); font-size:13px; font-family:var(--mono); width:200px; }
  .search-box::placeholder { color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-family:var(--mono); font-size:13px; }
  thead th { text-align:left; color:var(--muted); font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:0.03em; padding:10px 10px; border-bottom:1px solid var(--border); cursor:pointer; user-select:none; white-space:nowrap; font-family:var(--sans); }
  thead th:hover { color:var(--text); }
  thead th.sorted-asc::after { content:" ↑"; }
  thead th.sorted-desc::after { content:" ↓"; }
  tbody td { padding:9px 10px; border-bottom:1px solid var(--border); vertical-align:middle; }
  tbody tr:hover { background:var(--panel-2); }
  td.rail { width:4px; padding:0; }
  .rail-bull { background:var(--bull); }
  .rail-bear { background:var(--bear); }
  .rail-none { background:var(--border); }
  .col-ticker { font-weight:700; }
  .error-cell { color:var(--amber); font-family:var(--sans); font-size:12.5px; }
  .badge { display:inline-block; padding:2px 9px; border-radius:999px; font-size:11.5px; font-weight:700; letter-spacing:0.02em; }
  .badge-buy { background:var(--bull-bg); color:var(--bull); }
  .badge-sell { background:var(--bear-bg); color:var(--bear); }
  .badge-none { background:transparent; color:var(--muted); font-weight:400; }
  .dir { font-size:12.5px; }
  .dir-bull { color:var(--bull); }
  .dir-bear { color:var(--bear); }
  .dir-none { color:var(--muted); }
  .muted { color:var(--muted); }
  .small { font-size:11.5px; }
  .held-yes { color:var(--amber); font-weight:700; font-size:12px; }
  .flip-yes { color:var(--text); background:rgba(231,236,243,0.08); padding:2px 8px; border-radius:999px; font-size:11.5px; font-weight:700; }
  .flip-changed { color:var(--amber); background:var(--amber-bg); padding:2px 8px; border-radius:999px; font-size:11.5px; font-weight:700; cursor:help; }
  .in-trend { display:inline-block; padding:2px 8px; border-radius:999px; font-family:var(--mono); font-size:11.5px; font-weight:700; cursor:help; }
  .trend-bull { color:var(--bull); background:var(--bull-bg); }
  .trend-bear { color:var(--bear); background:var(--bear-bg); }
  .pnl-pos { color:var(--bull); font-weight:700; }
  .pnl-neg { color:var(--bear); font-weight:700; }
  footer { margin-top:30px; color:var(--muted); font-size:12px; border-top:1px solid var(--border); padding-top:16px; }
  tr.row-error { opacity:0.7; }
  tr.hidden-row { display:none; }
</style>
"""

JS = """
<script>
  (function(){var cf='all',st='';function f(){document.querySelectorAll('#scan-table tbody tr').forEach(function(r){var s=r.getAttribute('data-signal'),fl=r.getAttribute('data-flip'),h=r.getAttribute('data-held'),t=r.getAttribute('data-ticker')||'',m=true;if(cf==='buy')m=s==='buy';else if(cf==='sell')m=s==='sell';else if(cf==='flip')m=fl==='1';else if(cf==='held')m=h==='1';r.classList.toggle('hidden-row',!(m&&t.indexOf(st)!==-1));});}document.querySelectorAll('.chip-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.chip-btn').forEach(function(x){x.classList.remove('active');});b.classList.add('active');cf=b.getAttribute('data-filter');f();});});var s=document.getElementById('search-box');if(s)s.addEventListener('input',function(){st=s.value.trim().toLowerCase();f();});var ss={};document.querySelectorAll('#scan-table thead th').forEach(function(th,i){th.addEventListener('click',function(){var tb=document.getElementById('scan-table').querySelector('tbody'),rs=Array.prototype.slice.call(tb.querySelectorAll('tr')),asc=!(ss[i]==='asc');ss={};ss[i]=asc?'asc':'desc';document.querySelectorAll('#scan-table thead th').forEach(function(h){h.classList.remove('sorted-asc','sorted-desc');});th.classList.add(asc?'sorted-asc':'sorted-desc');rs.sort(function(a,b){var cA=a.children[i],cB=b.children[i];if(!cA||!cB)return 0;var va=cA.getAttribute('data-sort'),vb=cB.getAttribute('data-sort');if(va!==null&&vb!==null){va=parseFloat(va);vb=parseFloat(vb);return asc?va-vb:vb-va;}var ta=cA.textContent.trim().toLowerCase(),tb2=cB.textContent.trim().toLowerCase();return ta<tb2?(asc?-1:1):ta>tb2?(asc?1:-1):0;});rs.forEach(function(r){tb.appendChild(r);});});});})();
</script>
"""


def generate_html_report(results, alerts, run_date, atr_period, atr_multiplier, output_path, timeframe_label="Weekly"):
    ok = [r for r in results if r["status"] == "ok"]
    buys = [r for r in ok if r["signal"] == "BUY"]
    sells = [r for r in ok if r["signal"] == "SELL"]
    new = [r for r in ok if r["is_new"]]
    errs = [r for r in results if r["status"] != "ok"]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    if alerts:
        alert_banner = f'<div class="alert-banner"><div class="alert-head">⚠ Sell signal on {len(alerts)} stock(s) you hold ({timeframe_label.lower()} chart)</div>{"".join(_alert_html(a) for a in alerts)}</div>'
    else:
        alert_banner = ""
    stats_html = f"""<div class="stats-row">
      <div class="stat-chip"><div class="num">{len(results)}</div><div class="label">Scanned</div></div>
      <div class="stat-chip stat-buy"><div class="num">{len(buys)}</div><div class="label">Buy Signals</div></div>
      <div class="stat-chip stat-sell"><div class="num">{len(sells)}</div><div class="label">Sell Signals</div></div>
      <div class="stat-chip"><div class="num">{len(new)}</div><div class="label">Newly Added</div></div>
      <div class="stat-chip"><div class="num">{len(errs)}</div><div class="label">Errors</div></div></div>"""
    buy_panel = f'<div class="panel"><h2>Buying Opportunities This Week</h2><div class="buy-grid">{"".join(_buy_html(r) for r in buys)}</div></div>' if buys else '<div class="panel"><h2>Buying Opportunities This Week</h2><div class="empty-note">No fresh BUY flips this week.</div></div>'
    rows_html = "".join(_row_html(r) for r in results)
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Supertrend {timeframe_label} Scanner — {run_date}</title>{CSS_JS}</head><body><div class="wrap">
  <div class="topbar"><h1>Supertrend {timeframe_label} Scanner</h1><div class="params">ATR({atr_period}) &times; {atr_multiplier} &middot; {timeframe_label} chart &middot; Generated {generated_at}</div></div>
  {alert_banner}{stats_html}{buy_panel}
  <div class="panel"><h2>Full Watchlist Detail</h2>
    <div class="controls">
      <button class="chip-btn active" data-filter="all">All</button>
      <button class="chip-btn" data-filter="buy">Buy Signals</button>
      <button class="chip-btn" data-filter="sell">Sell Signals</button>
      <button class="chip-btn" data-filter="flip">Flips Only</button>
      <button class="chip-btn" data-filter="held">My Portfolio</button>
      <input type="text" id="search-box" class="search-box" placeholder="Search ticker...">
    </div>
    <table id="scan-table"><thead><tr><th></th><th>Ticker</th><th>Close</th><th>Supertrend</th><th>Direction</th><th>Signal (Latest Bar)</th><th>Last Recorded</th><th>Flip</th><th>In Trend</th><th>Held</th><th>Position P/L</th><th>Bar Date</th></tr></thead><tbody>{rows_html}</tbody></table>
  </div>
  <footer>Parameters: ATR period {atr_period}, multiplier {atr_multiplier}, {timeframe_label.lower()} interval. Data via Yahoo Finance.</footer>
</div>{JS}</body></html>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(body)
    return output_path


# --------------------------------------------------------------------------
# Combined (Weekly + Daily) report
# --------------------------------------------------------------------------
COMBINED_CSS_EXTRA = """
<style>
  .confluence-cell { text-align:center; letter-spacing:1px; font-size:14px; }
  .conf-bull { color:var(--bull); font-weight:700; }
  .conf-bear { color:var(--bear); font-weight:700; }
  .conf-mixed { color:var(--amber); font-weight:700; }
  .conf-none { color:var(--muted); }
  .tf-cell { white-space:nowrap; }
  .tf-cell .dir { margin-right:4px; }
  .tf-tag { display:inline-block; font-family:var(--mono); font-size:10.5px; font-weight:700; padding:1px 6px; border-radius:4px; letter-spacing:0.04em; margin-right:6px; text-transform:uppercase; }
  .tf-tag-w { background:rgba(120,140,220,0.18); color:#96A9E6; }
  .tf-tag-d { background:rgba(220,170,120,0.18); color:#E6BE96; }
  .buy-panels { display:grid; grid-template-columns:1fr; gap:14px; }
  .buy-subpanel h3 { font-size:12px; text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); margin:0 0 10px; display:flex; align-items:center; gap:8px; }
  .buy-subpanel h3 .count { color:var(--text); font-family:var(--mono); }
  .confluence-panel { border:1px solid rgba(47,191,113,0.35); background:rgba(47,191,113,0.05); border-radius:8px; padding:12px 14px; }
  .confluence-panel h3 { color:var(--bull); }
  .confluence-panel .buy-item { background:rgba(47,191,113,0.18); }
  .stats-group-label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:0.05em; padding:0 4px; align-self:center; }
  .side-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; margin-left:10px; vertical-align:middle; }
  .side-badge.long-badge { background:var(--bull-bg); color:var(--bull); }
  .side-badge.short-badge { background:var(--bear-bg); color:var(--bear); }

  /* Tabbed layout */
  .tab-nav { display:flex; gap:2px; align-items:center; margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:0; }
  .tab-nav button { background:none; border:none; padding:10px 18px; font-size:13px; font-weight:600; color:var(--muted); cursor:pointer; border-bottom:2px solid transparent; font-family:inherit; transition:color 100ms; }
  .tab-nav button:hover { color:var(--text); }
  .tab-nav button.active.long-active { color:var(--bull); border-bottom-color:var(--bull); }
  .tab-nav button.active.short-active { color:var(--bear); border-bottom-color:var(--bear); }
  .tab-nav .archive-link { margin-left:auto; padding:10px 14px; color:var(--muted); text-decoration:none; font-size:13px; }
  .tab-nav .archive-link:hover { color:var(--text); }
  .tab-pane { display:none; }
  .tab-pane.active { display:block; }

  /* Recent flips panel */
  .flip-log-panel { border:1px solid var(--border); }
  .flip-log-panel .panel-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:12px; }
  .flip-log-panel .panel-head h2 { margin:0; }
  .flip-log-panel .panel-head .subtle { color:var(--muted); font-family:var(--mono); font-size:11.5px; }
  .flip-day { margin:10px 0 6px; }
  .flip-day-head { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:0.05em; font-weight:700; margin-bottom:6px; }
  .flip-day-head .today-tag { display:inline-block; margin-left:8px; background:rgba(240,169,61,0.16); color:var(--amber); padding:1px 7px; border-radius:999px; font-size:10px; letter-spacing:0.03em; }
  .flip-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:8px; }
  .flip-card { display:flex; flex-direction:column; gap:4px; padding:9px 11px; border-radius:8px; border:1px solid var(--border); background:var(--panel-2); }
  .flip-card.flip-buy { border-color:rgba(47,191,113,0.35); background:rgba(47,191,113,0.06); }
  .flip-card.flip-sell { border-color:rgba(240,71,93,0.35); background:rgba(240,71,93,0.06); }
  .flip-head { display:flex; align-items:center; gap:8px; }
  .flip-head .flip-tkr { font-family:var(--mono); font-weight:700; color:var(--text); min-width:62px; font-size:13px; }
  .flip-head .flip-tag { font-family:var(--mono); font-size:10px; font-weight:700; padding:1px 5px; border-radius:4px; letter-spacing:0.04em; text-transform:uppercase; }
  .flip-main { color:var(--text); font-size:11.5px; font-family:var(--mono); line-height:1.3; }
  .flip-reason { color:var(--muted); font-size:11px; font-family:var(--mono); line-height:1.35; }
  .flip-reason .r-strong { color:var(--text); font-weight:700; }
  .flip-reason .r-pos { color:var(--bull); font-weight:700; }
  .flip-reason .r-neg { color:var(--bear); font-weight:700; }
  .flip-reason .r-conf { color:var(--amber); font-weight:700; }
  .flip-entry { color:var(--muted); font-size:11px; font-family:var(--mono); border-top:1px dashed var(--border); margin-top:5px; padding-top:5px; display:flex; flex-direction:column; gap:2px; }
  .flip-entry .entry-line { display:flex; gap:6px; align-items:baseline; flex-wrap:wrap; }
  .flip-entry .entry-label { color:var(--muted); font-weight:700; min-width:44px; text-transform:uppercase; letter-spacing:0.03em; font-size:10px; }
  .flip-entry .r-pos { color:var(--bull); font-weight:700; }
  .flip-entry .r-neg { color:var(--bear); font-weight:700; }
  .flip-entry .r-strong { color:var(--text); font-weight:700; }
  .flip-entry .r-amber { color:var(--amber); font-weight:700; }
  .flip-head .q-badge { margin-left:auto; font-family:var(--mono); font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:999px; letter-spacing:0.02em; cursor:help; }
  .q-high { background:rgba(47,191,113,0.18); color:var(--bull); }
  .q-med  { background:rgba(240,169,61,0.18); color:var(--amber); }
  .q-low  { background:rgba(231,236,243,0.06); color:var(--muted); }
  .q-star { color:var(--amber); margin-right:4px; font-weight:700; }
  .flip-mode-note { color:var(--muted); font-size:11.5px; font-style:italic; }
  .flip-topbadge { display:inline-block; margin-left:10px; background:rgba(47,191,113,0.16); color:var(--bull); padding:1px 8px; border-radius:999px; font-size:10.5px; letter-spacing:0.03em; font-weight:700; }

  /* ⚡ Superior Selection panel (top of each tab, PF ≥ threshold) */
  .superior-panel {
    border:1px solid rgba(142,116,224,0.42);
    background:linear-gradient(135deg, rgba(142,116,224,0.08), rgba(240,201,107,0.04));
    position:relative;
  }
  .superior-panel::before {
    content:""; position:absolute; top:0; left:0; right:0; height:2px;
    background:linear-gradient(90deg, #8e74e0, #F0C96B);
    border-radius:10px 10px 0 0;
  }
  .superior-panel h2 { color:#B399F0; letter-spacing:0.05em; }
  .superior-panel .subtle { color:#9b8ad1; }
  .superior-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr)); gap:10px; }
  .superior-card {
    background:rgba(142,116,224,0.07);
    border:1px solid rgba(142,116,224,0.28);
    border-radius:8px; padding:10px 12px;
    display:flex; flex-direction:column; gap:3px;
  }
  .superior-card .superior-tkr { font-family:var(--mono); font-weight:700; color:#F0C96B; font-size:14px; display:flex; align-items:center; gap:6px; }
  .superior-card .fresh-tag { background:rgba(240,201,107,0.18); color:#F0C96B; padding:1px 7px; border-radius:999px; font-size:10px; letter-spacing:0.04em; font-weight:700; text-transform:uppercase; }
  .superior-card .superior-pf { color:var(--muted); font-family:var(--mono); font-size:11px; display:flex; align-items:baseline; gap:6px; }
  .superior-card .superior-pf .pf-value { color:#B399F0; font-weight:700; font-size:20px; letter-spacing:-0.02em; }
  .superior-card .superior-meta { color:var(--muted); font-size:11px; font-family:var(--mono); }
  .superior-card .superior-meta .wr-good { color:var(--bull); font-weight:700; }
  .superior-card .superior-meta .wr-neutral { color:#B399F0; font-weight:700; }

  tr.hidden-row { display:none; }
</style>
"""

COMBINED_JS = """
<script>
  (function(){var cf='all',st='';function f(){document.querySelectorAll('#scan-table tbody tr').forEach(function(r){var wS=r.getAttribute('data-w-signal'),dS=r.getAttribute('data-d-signal'),wF=r.getAttribute('data-w-flip')==='1',dF=r.getAttribute('data-d-flip')==='1',h=r.getAttribute('data-held')==='1',cn=r.getAttribute('data-confluence'),t=r.getAttribute('data-ticker')||'',dR=parseInt(r.getAttribute('data-d-recency')||'9999',10),wR=parseInt(r.getAttribute('data-w-recency')||'9999',10),m=true;switch(cf){case 'recent7':m=dR<=7||wR<=1;break;case 'any-buy':m=wS==='buy'||dS==='buy';break;case 'any-sell':m=wS==='sell'||dS==='sell';break;case 'conf-bull':m=cn==='bull';break;case 'conf-bear':m=cn==='bear';break;case 'weekly-flip':m=wF;break;case 'daily-flip':m=dF;break;case 'held':m=h;break;default:m=true;}r.classList.toggle('hidden-row',!(m&&t.indexOf(st)!==-1));});}document.querySelectorAll('.chip-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.chip-btn').forEach(function(x){x.classList.remove('active');});b.classList.add('active');cf=b.getAttribute('data-filter');f();});});var s=document.getElementById('search-box');if(s)s.addEventListener('input',function(){st=s.value.trim().toLowerCase();f();});var ss={};document.querySelectorAll('#scan-table thead th').forEach(function(th,i){th.addEventListener('click',function(){var tb=document.getElementById('scan-table').querySelector('tbody'),rs=Array.prototype.slice.call(tb.querySelectorAll('tr')),asc=!(ss[i]==='asc');ss={};ss[i]=asc?'asc':'desc';document.querySelectorAll('#scan-table thead th').forEach(function(h){h.classList.remove('sorted-asc','sorted-desc');});th.classList.add(asc?'sorted-asc':'sorted-desc');rs.sort(function(a,b){var cA=a.children[i],cB=b.children[i];if(!cA||!cB)return 0;var va=cA.getAttribute('data-sort'),vb=cB.getAttribute('data-sort');if(va!==null&&vb!==null){va=parseFloat(va);vb=parseFloat(vb);return asc?va-vb:vb-va;}var ta=cA.textContent.trim().toLowerCase(),tb2=cB.textContent.trim().toLowerCase();return ta<tb2?(asc?-1:1):ta>tb2?(asc?1:-1):0;});rs.forEach(function(r){tb.appendChild(r);});});});})();
</script>
"""

TABBED_JS = """
<script>
  (function() {
    var tabButtons = document.querySelectorAll('.tab-nav button[data-tab]');
    var panes = document.querySelectorAll('.tab-pane');
    function showTab(tabId) {
      tabButtons.forEach(function(b){ b.classList.toggle('active', b.getAttribute('data-tab') === tabId); });
      panes.forEach(function(p){ p.classList.toggle('active', p.id === 'pane-' + tabId); });
      try { localStorage.setItem('supertrend-side', tabId); } catch(e) {}
    }
    tabButtons.forEach(function(b) { b.addEventListener('click', function(){ showTab(b.getAttribute('data-tab')); }); });
    try { var s = localStorage.getItem('supertrend-side'); if (s === 'short' || s === 'long') showTab(s); } catch(e) {}

    function initPane(pane) {
      var table = pane.querySelector('.scan-table');
      if (!table) return;
      var tbody = table.querySelector('tbody');
      var chips = pane.querySelectorAll('.chip-btn');
      var search = pane.querySelector('.search-box');
      var currentFilter = 'all', searchTerm = '';
      function apply() {
        tbody.querySelectorAll('tr').forEach(function(row){
          var wS=row.getAttribute('data-w-signal'),dS=row.getAttribute('data-d-signal'),wF=row.getAttribute('data-w-flip')==='1',dF=row.getAttribute('data-d-flip')==='1',h=row.getAttribute('data-held')==='1',cn=row.getAttribute('data-confluence'),t=row.getAttribute('data-ticker')||'',dR=parseInt(row.getAttribute('data-d-recency')||'9999',10),wR=parseInt(row.getAttribute('data-w-recency')||'9999',10),m=true;
          switch(currentFilter){case 'recent7':m=dR<=7||wR<=1;break;case 'any-buy':m=wS==='buy'||dS==='buy';break;case 'any-sell':m=wS==='sell'||dS==='sell';break;case 'conf-bull':m=cn==='bull';break;case 'conf-bear':m=cn==='bear';break;case 'weekly-flip':m=wF;break;case 'daily-flip':m=dF;break;case 'held':m=h;break;default:m=true;}
          row.classList.toggle('hidden-row', !(m && t.indexOf(searchTerm) !== -1));
        });
      }
      chips.forEach(function(btn){ btn.addEventListener('click', function(){ chips.forEach(function(b){b.classList.remove('active');}); btn.classList.add('active'); currentFilter = btn.getAttribute('data-filter'); apply(); }); });
      if (search) search.addEventListener('input', function(){ searchTerm = search.value.trim().toLowerCase(); apply(); });
      var sortState = {};
      table.querySelectorAll('thead th').forEach(function(th, i){
        th.addEventListener('click', function(){
          var rs = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
          var asc = !(sortState[i] === 'asc'); sortState = {}; sortState[i] = asc ? 'asc' : 'desc';
          table.querySelectorAll('thead th').forEach(function(h){ h.classList.remove('sorted-asc','sorted-desc'); });
          th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
          rs.sort(function(a,b){
            var cA=a.children[i],cB=b.children[i]; if(!cA||!cB) return 0;
            var va=cA.getAttribute('data-sort'),vb=cB.getAttribute('data-sort');
            if(va!==null&&vb!==null){ va=parseFloat(va); vb=parseFloat(vb); return asc?va-vb:vb-va; }
            var ta=cA.textContent.trim().toLowerCase(),tb2=cB.textContent.trim().toLowerCase();
            return ta<tb2?(asc?-1:1):ta>tb2?(asc?1:-1):0;
          });
          rs.forEach(function(r){ tbody.appendChild(r); });
        });
      });
    }
    panes.forEach(initPane);
  })();
</script>
"""


def _tf_status(r):
    if r is None:
        return {"present": False, "ok": False, "direction": None, "signal": "NONE", "flip": False, "changed": False,
                "close": None, "supertrend": None, "bar_date": None, "bars_in_trend": None, "trend_start_date": None,
                "bar_unit": "d", "error": "not in this scan"}
    if r.get("status") != "ok":
        return {"present": True, "ok": False, "direction": None, "signal": "NONE", "flip": False, "changed": False,
                "close": None, "supertrend": None, "bar_date": None, "bars_in_trend": None, "trend_start_date": None,
                "bar_unit": r.get("bar_unit", "d"), "error": r.get("error") or r.get("status")}
    return {"present": True, "ok": True, "direction": r["direction"], "signal": r["signal"],
            "flip": r.get("flip", False), "changed": r.get("changed_since_last_run", False),
            "close": r.get("close"), "supertrend": r.get("supertrend"), "bar_date": r.get("last_bar_date"),
            "bars_in_trend": r.get("bars_in_trend"), "trend_start_date": r.get("trend_start_date"),
            "bar_unit": r.get("bar_unit", "d"), "error": None}


def _combined_tf_cell(state):
    if not state["ok"]:
        note = _esc(state.get("error") or "n/a")
        return f'<span class="muted small" title="{note}">—</span>'
    dir_html = _direction_badge(state["direction"])
    sig_html = _signal_badge(state["signal"])
    if state["signal"] == "NONE" and state["changed"]:
        sig_html = '<span class="flip-changed" title="Direction differs from your last run.">↺ Changed</span>'
    st_val = _fmt_num(state["supertrend"])
    bars = state.get("bars_in_trend"); unit = state.get("bar_unit", "d")
    if bars is None:
        trend_html = ""
    else:
        cls = "trend-bull" if state["direction"] == "Bullish" else "trend-bear"
        word = ("day" if unit == "d" else "week") + ("s" if bars != 1 else "")
        tip = f"{state['direction']} for {bars} {word} — since {state.get('trend_start_date') or ''}"
        trend_html = f' <span class="in-trend {cls}" title="{_esc(tip)}">{bars}{unit}</span>'
    return f'<span class="tf-cell">{dir_html} {sig_html}{trend_html} <span class="muted small">ST {st_val}</span></span>'


def _confluence_cell(w, d):
    if not (w["ok"] and d["ok"]):
        return '<span class="confluence-cell conf-none">—</span>', "none"
    if w["direction"] == "Bullish" and d["direction"] == "Bullish":
        return '<span class="confluence-cell conf-bull" title="Both weekly and daily are bullish">▲▲</span>', "bull"
    if w["direction"] == "Bearish" and d["direction"] == "Bearish":
        return '<span class="confluence-cell conf-bear" title="Both weekly and daily are bearish">▼▼</span>', "bear"
    return '<span class="confluence-cell conf-mixed" title="Weekly and daily disagree">▲▼</span>', "mixed"


def _combined_row_html(ticker, weekly_r, daily_r, public_view=False):
    w = _tf_status(weekly_r); d = _tf_status(daily_r)
    conf_rank = {"bull": 0, "bear": 1, "mixed": 2, "none": 3}
    d_rec = d.get("bars_in_trend") if d.get("ok") else None
    w_rec = w.get("bars_in_trend") if w.get("ok") else None
    d_rec_sort = d_rec if d_rec is not None else 9999
    w_rec_sort = w_rec if w_rec is not None else 9999

    if not w["ok"] and not d["ok"]:
        errs = []
        if w["error"]: errs.append(f"weekly: {w['error']}")
        if d["error"]: errs.append(f"daily: {d['error']}")
        colspan = 6 if public_view else 8
        return f"""
        <tr class="row-error" data-ticker="{_esc(ticker).lower()}" data-w-signal="none" data-d-signal="none"
            data-w-flip="0" data-d-flip="0" data-w-dir="none" data-d-dir="none" data-held="0"
            data-confluence="none" data-d-recency="9999" data-w-recency="9999">
          <td data-sort="3" class="confluence-cell conf-none">—</td>
          <td class="col-ticker">{_esc(ticker)}</td>
          <td colspan="{colspan}" class="error-cell">⚠ {_esc(' · '.join(errs))}</td>
        </tr>"""

    conf_html, conf_key = _confluence_cell(w, d)
    trade_source = daily_r if (daily_r and daily_r.get("held")) else weekly_r if (weekly_r and weekly_r.get("held")) else None
    held = bool(trade_source and trade_source.get("held"))
    held_html = '<span class="held-yes">● Held</span>' if held else '<span class="muted">—</span>'
    pnl_html = "—"
    if held and trade_source.get("open_trades"):
        parts = []
        for t in trade_source["open_trades"]:
            pnl = t.get("pnl_pct"); qty = t.get("Quantity", ""); entry = t.get("EntryPrice", "")
            if pnl is not None:
                cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
                parts.append(f'<span class="{cls}">{pnl:+.2f}%</span> <span class="muted">(qty {qty} @ {entry})</span>')
            else:
                parts.append('<span class="muted">n/a</span>')
        pnl_html = "<br>".join(parts)
    close_source = d["close"] if d["ok"] else w["close"]
    w_dir_key = (w["direction"] or "none").lower() if w["ok"] else "none"
    d_dir_key = (d["direction"] or "none").lower() if d["ok"] else "none"
    portfolio_cells = "" if public_view else f'<td>{held_html}</td><td>{pnl_html}</td>'
    return f"""
    <tr data-ticker="{_esc(ticker).lower()}" data-w-signal="{w['signal'].lower()}" data-d-signal="{d['signal'].lower()}"
        data-w-flip="{'1' if w['flip'] else '0'}" data-d-flip="{'1' if d['flip'] else '0'}"
        data-w-dir="{w_dir_key}" data-d-dir="{d_dir_key}" data-held="{'1' if held else '0'}"
        data-confluence="{conf_key}" data-d-recency="{d_rec_sort}" data-w-recency="{w_rec_sort}">
      <td data-sort="{conf_rank[conf_key]}">{conf_html}</td>
      <td class="col-ticker">{_esc(ticker)}</td>
      <td data-sort="{close_source if close_source is not None else ''}">{_fmt_num(close_source)}</td>
      <td data-sort="{w_rec_sort}">{_combined_tf_cell(w)}</td>
      <td data-sort="{d_rec_sort}">{_combined_tf_cell(d)}</td>{portfolio_cells}
      <td class="muted small">{_esc(w['bar_date'] or '—')}</td>
      <td class="muted small">{_esc(d['bar_date'] or '—')}</td>
    </tr>"""


def _combined_alert_html(a, timeframe_label):
    tag_cls = "tf-tag-w" if timeframe_label.lower().startswith("w") else "tf-tag-d"
    tag = f'<span class="tf-tag {tag_cls}">{_esc(timeframe_label)}</span>'
    ticker = _esc(a["ticker"]); close = _fmt_num(a["close"]); date_ = _esc(a.get("last_bar_date"))
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
        timing = f"Already <strong>Bearish</strong> as of {date_} on the {timeframe_label.lower()} chart — differs from last run ({last_seen})."
    return f'<div class="alert-item"><div class="alert-ticker">{tag}{ticker}</div><div class="alert-body">{timing}<div class="alert-trade">{trades_str}</div></div></div>'


def _quality_bucket(score):
    if score is None: return None, None
    if score >= 70: return "high", "q-high"
    if score >= 40: return "med", "q-med"
    return "low", "q-low"


def _build_reason_html(entry):
    bits = []
    signal = (entry.get("signal") or "").upper()
    is_buy = signal == "BUY"
    vol = entry.get("quality_volume_ratio")
    if isinstance(vol, (int, float)):
        delta = (vol - 1.0) * 100.0
        cls = "r-pos" if delta > 0 else "r-neg" if delta < 0 else ""
        sign = "+" if delta > 0 else ""
        bits.append(f'vol <span class="{cls}">{sign}{delta:.0f}%</span> (5/20 avg)')
    m5 = entry.get("quality_momentum_pct"); m10 = entry.get("quality_momentum_10_pct")
    if isinstance(m5, (int, float)) or isinstance(m10, (int, float)):
        parts = []
        if isinstance(m5, (int, float)):
            cls = ("r-pos" if m5 > 0 else "r-neg") if is_buy else ("r-pos" if m5 < 0 else "r-neg")
            parts.append(f'<span class="{cls}">{m5:+.1f}%</span>/5b')
        if isinstance(m10, (int, float)):
            cls = ("r-pos" if m10 > 0 else "r-neg") if is_buy else ("r-pos" if m10 < 0 else "r-neg")
            parts.append(f'<span class="{cls}">{m10:+.1f}%</span>/10b')
        bits.append("mom " + ", ".join(parts))
    prior = entry.get("quality_prior_run")
    if isinstance(prior, int) and prior > 0:
        prior_dir = "bear" if is_buy else "bull"
        strong = ' class="r-strong"' if prior >= 10 else ""
        bits.append(f'<span{strong}>{prior}-bar prior {prior_dir}</span>')
    rsi = entry.get("quality_rsi")
    if isinstance(rsi, (int, float)):
        if is_buy: sweet, danger = 50 <= rsi <= 65, rsi > 75
        else:      sweet, danger = 35 <= rsi <= 50, rsi < 25
        cls = "r-pos" if sweet else "r-neg" if danger else "r-strong"
        bits.append(f'RSI <span class="{cls}">{rsi:.0f}</span>')
    hd = entry.get("quality_high_distance_pct")
    if isinstance(hd, (int, float)):
        if is_buy:
            if   hd >=  0: bits.append('<span class="r-pos">new 20-bar high</span>')
            elif hd >= -2: bits.append(f'within <span class="r-strong">{abs(hd):.1f}%</span> of 20-bar high')
            elif hd >= -5: bits.append(f'<span class="r-neg">{abs(hd):.1f}%</span> below 20-bar high')
        else:
            if   hd <=  0: bits.append('<span class="r-pos">new 20-bar low</span>')
            elif hd <=  2: bits.append(f'within <span class="r-strong">{hd:.1f}%</span> of 20-bar low')
            elif hd <=  5: bits.append(f'<span class="r-neg">{hd:.1f}%</span> above 20-bar low')
    if entry.get("weekly_confluence"):
        bits.append('<span class="r-conf">W↑ confluence +15</span>')
    return f'<div class="flip-reason">{" · ".join(bits)}</div>' if bits else ""


def _build_entry_sl_html(entry):
    close = entry.get("close"); st = entry.get("supertrend"); atr = entry.get("atr_value")
    signal = (entry.get("signal") or "").upper()
    if close is None or st is None or atr is None or signal not in ("BUY", "SELL"):
        return ""
    try:
        close = float(close); st = float(st); atr = float(atr)
    except (TypeError, ValueError):
        return ""
    if close <= 0 or atr <= 0:
        return ""

    def pct(from_, to):
        return (to - from_) / from_ * 100.0 if from_ else 0.0

    if signal == "BUY":
        pullback = (close + st) / 2.0
        sl_tight = max(close - 1.5 * atr, st)
        sl_natural = st
        target = close + 3.0 * atr
        target_label = "3×ATR"
        h20 = entry.get("high_20")
        res_note = ""
        if isinstance(h20, (int, float)) and close < h20 < target:
            res_pct = (h20 - close) / close * 100.0
            res_note = (f'<span class="muted">·</span> '
                        f'<span>near resistance <span class="r-amber">{h20:.2f}</span> '
                        f'(<span class="r-amber">{res_pct:+.1f}%</span>, scale-out?)</span>')
        rr_denom = (close - sl_tight)
        rr = (target - close) / rr_denom if rr_denom > 0 else 0.0
        pullback_pct = pct(close, pullback); sl_tight_pct = pct(close, sl_tight)
        sl_nat_pct = pct(close, sl_natural); target_pct = pct(close, target)
        return f"""
    <div class="flip-entry">
      <div class="entry-line">
        <span class="entry-label">Entry</span>
        <span>Buy @ <span class="r-strong">{close:.2f}</span></span>
        <span class="muted">·</span>
        <span>Limit @ <span class="r-strong">{pullback:.2f}</span> (<span class="r-amber">{pullback_pct:+.1f}%</span>, pullback to midpoint)</span>
      </div>
      <div class="entry-line">
        <span class="entry-label">SL</span>
        <span>tight <span class="r-neg">{sl_tight:.2f}</span> (<span class="r-neg">{sl_tight_pct:+.1f}%</span>, 1.5×ATR)</span>
        <span class="muted">·</span>
        <span>natural <span class="r-neg">{sl_natural:.2f}</span> (<span class="r-neg">{sl_nat_pct:+.1f}%</span>, ST line)</span>
      </div>
      <div class="entry-line">
        <span class="entry-label">Target</span>
        <span><span class="r-strong">{target:.2f}</span> (<span class="r-pos">{target_pct:+.1f}%</span>, {target_label})</span>
        <span class="muted">·</span>
        <span>R:R <span class="r-pos">1 : {rr:.1f}</span></span>
        {res_note}
      </div>
    </div>"""

    # SELL
    pullback = (close + st) / 2.0
    sl_tight = min(close + 1.5 * atr, st)
    sl_natural = st
    target = close - 3.0 * atr
    target_label = "3×ATR"
    l20 = entry.get("low_20")
    sup_note = ""
    if isinstance(l20, (int, float)) and target < l20 < close:
        sup_pct = (l20 - close) / close * 100.0
        sup_note = (f'<span class="muted">·</span> '
                    f'<span>near support <span class="r-amber">{l20:.2f}</span> '
                    f'(<span class="r-amber">{sup_pct:+.1f}%</span>, scale-out?)</span>')
    rr_denom = (sl_tight - close)
    rr = (close - target) / rr_denom if rr_denom > 0 else 0.0
    pullback_pct = pct(close, pullback); sl_tight_pct = pct(close, sl_tight)
    sl_nat_pct = pct(close, sl_natural); target_pct = pct(close, target)
    return f"""
    <div class="flip-entry">
      <div class="entry-line">
        <span class="entry-label">Entry</span>
        <span>Short @ <span class="r-strong">{close:.2f}</span></span>
        <span class="muted">·</span>
        <span>Limit @ <span class="r-strong">{pullback:.2f}</span> (<span class="r-amber">{pullback_pct:+.1f}%</span>, bounce to midpoint)</span>
      </div>
      <div class="entry-line">
        <span class="entry-label">SL</span>
        <span>tight <span class="r-neg">{sl_tight:.2f}</span> (<span class="r-neg">{sl_tight_pct:+.1f}%</span>, 1.5×ATR)</span>
        <span class="muted">·</span>
        <span>natural <span class="r-neg">{sl_natural:.2f}</span> (<span class="r-neg">{sl_nat_pct:+.1f}%</span>, ST line)</span>
      </div>
      <div class="entry-line">
        <span class="entry-label">Target</span>
        <span><span class="r-strong">{target:.2f}</span> (<span class="r-pos">{target_pct:+.1f}%</span>, {target_label})</span>
        <span class="muted">·</span>
        <span>R:R <span class="r-pos">1 : {rr:.1f}</span></span>
        {sup_note}
      </div>
    </div>"""


def _flip_card_html(entry, is_top_quality=False):
    ticker = _esc(entry.get("ticker", ""))
    timeframe = _esc(entry.get("timeframe", "")).lower()
    direction = _esc(entry.get("direction", ""))
    signal = (entry.get("signal") or "").upper()
    close_str = _fmt_num(entry.get("close"))
    st = _fmt_num(entry.get("supertrend"))
    tf_cls = "tf-tag-w" if timeframe == "weekly" else "tf-tag-d"
    card_cls = "flip-buy" if signal == "BUY" else "flip-sell"
    q = entry.get("quality_score")
    _, q_cls = _quality_bucket(q)
    badge = f'<span class="q-badge {q_cls}" title="Quality {q}/100">{q}</span>' if q is not None else ""
    star = '<span class="q-star" title="Top-ranked flip on this day">★</span>' if is_top_quality else ""
    reason_html = _build_reason_html(entry)
    entry_sl_html = _build_entry_sl_html(entry)
    main_html = f'<div class="flip-main">{signal} · {direction} · Close {close_str} · <span class="muted">ST {st}</span></div>'
    return f"""
    <div class="flip-card {card_cls}">
      <div class="flip-head">
        <span class="flip-tag {tf_cls}">{timeframe.upper()[:1]}</span>
        <span class="flip-tkr">{star}{ticker}</span>
        {badge}
      </div>
      {main_html}
      {reason_html}
      {entry_sl_html}
    </div>"""


def _recent_flips_panel_html(flip_log, run_date, days=7, side="long", allowed_tickers=None, auto_rank_threshold=5):
    if flip_log is None: flip_log = []
    try: run_d = date.fromisoformat(run_date)
    except (ValueError, TypeError): run_d = date.today()
    cutoff = (run_d - timedelta(days=days)).isoformat()
    kept = [e for e in flip_log if (e.get("flip_date") or "") >= cutoff]
    if side == "long":
        kept = [e for e in kept if (e.get("signal") or "").upper() == "BUY"]
        panel_title = f"Recent Buy Flips (Last {days} Days)"; signal_word = "BUY"
    elif side == "short":
        kept = [e for e in kept if (e.get("signal") or "").upper() == "SELL"]
        panel_title = f"Recent Sell Flips (Last {days} Days)"; signal_word = "SELL"
    else:
        panel_title = f"Recent Flips (Last {days} Days)"; signal_word = "BUY/SELL"
    if allowed_tickers is not None:
        kept = [e for e in kept if e.get("ticker") in allowed_tickers]
    by_day = {}
    for e in kept: by_day.setdefault(e["flip_date"], []).append(e)
    day_order = sorted(by_day.keys(), reverse=True)
    if side == "long":
        mode_note = f'Showing only BUY flips on tickers whose current weekly direction is Bullish. Sorted by quality within each day; ★ marks the top 3 when a day has more than {auto_rank_threshold} candidates.'
    elif side == "short":
        mode_note = f'Showing only SELL flips on tickers whose current weekly direction is Bearish. Sorted by quality within each day; ★ marks the top 3 when a day has more than {auto_rank_threshold} candidates.'
    else:
        mode_note = f'Sorted by quality within each day; ★ marks the top 3 when a day has more than {auto_rank_threshold} candidates.'
    subtle_tail = f"Anything older than {days} days rolls off this list automatically. Full history in <code>data/flip_log.json</code>."
    if not kept:
        return f'<div class="panel flip-log-panel"><div class="panel-head"><h2>{panel_title}</h2><span class="subtle">{subtle_tail}</span></div><div class="flip-mode-note">{mode_note}</div><div class="empty-note" style="margin-top:10px;">No {signal_word} flips in the last {days} days that match this section\'s filter.</div></div>'
    day_blocks = []
    for d in day_order:
        entries = by_day[d]
        def _key(e):
            q = e.get("quality_score")
            return (-(q if q is not None else -1), e.get("timeframe", ""), e.get("ticker", ""))
        entries.sort(key=_key)
        top_set = set()
        if len(entries) > auto_rank_threshold:
            for e in entries[:3]:
                if e.get("quality_score") is not None:
                    top_set.add((e.get("ticker"), e.get("timeframe"), e.get("flip_date")))
        today_tag = ' <span class="today-tag">today</span>' if d == run_date else ""
        crowded = f' <span class="flip-topbadge">★ top 3 of {len(entries)}</span>' if len(entries) > auto_rank_threshold else ""
        cards = "".join(_flip_card_html(e, is_top_quality=(e.get("ticker"), e.get("timeframe"), e.get("flip_date")) in top_set) for e in entries)
        day_blocks.append(f'<div class="flip-day"><div class="flip-day-head">{_esc(d)}{today_tag}{crowded}</div><div class="flip-grid">{cards}</div></div>')
    return f'<div class="panel flip-log-panel"><div class="panel-head"><h2>{panel_title}</h2><span class="subtle">{len(kept)} {signal_word} flip(s) across {len(day_order)} day(s). {subtle_tail}</span></div><div class="flip-mode-note">{mode_note}</div>{"".join(day_blocks)}</div>'


def _superior_panel_html(daily_results, side_tickers, side, pf_threshold=1.5, min_trades=5):
    """Top-of-pane: tickers with historical backtest PF >= pf_threshold."""
    if side == "long":
        pf_k, wr_k, tr_k, ar_k = "backtest_buy_pf", "backtest_buy_win_rate", "backtest_buy_trades", "backtest_buy_avg_r"
        fresh_sig = "BUY"; title = "⚡ Superior Long Selection"
    else:
        pf_k, wr_k, tr_k, ar_k = "backtest_sell_pf", "backtest_sell_win_rate", "backtest_sell_trades", "backtest_sell_avg_r"
        fresh_sig = "SELL"; title = "⚡ Superior Short Selection"
    candidates = []
    for r in daily_results:
        if r.get("status") != "ok": continue
        if r["ticker"] not in side_tickers: continue
        pf = r.get(pf_k); trades = r.get(tr_k) or 0
        if pf is None or pf < pf_threshold or trades < min_trades: continue
        candidates.append(r)
    candidates.sort(key=lambda r: (r.get(pf_k) or 0), reverse=True)
    subtle = (f"Profit factor &ge; {pf_threshold} with {min_trades}+ sample trades on the daily chart. "
              f"Backtest replays every historical flip with current SL (1.5&times;ATR) and target (3&times;ATR) rules.")
    if not candidates:
        return f'<div class="panel superior-panel"><div class="panel-head"><h2>{title}</h2><span class="subtle">{subtle}</span></div><div class="empty-note">No tickers currently match this filter.</div></div>'
    cards = []
    for r in candidates:
        pf = r[pf_k]; wr = r.get(wr_k) or 0; trades = r.get(tr_k) or 0; avg_r = r.get(ar_k) or 0
        ticker = _esc(r["ticker"])
        fresh = (r.get("signal") == fresh_sig)
        fresh_html = ' <span class="fresh-tag">fresh flip</span>' if fresh else ""
        wr_cls = "wr-good" if wr >= 55 else "wr-neutral"
        tip = f"Profit factor {pf:.2f} — sum of winning R divided by sum of losing R (capped at 99)."
        cards.append(f'<div class="superior-card"><div class="superior-tkr">{ticker}{fresh_html}</div><div class="superior-pf" title="{_esc(tip)}">PF <span class="pf-value">{pf:.2f}</span></div><div class="superior-meta"><span class="{wr_cls}">{wr:.0f}% WR</span> &middot; {trades} trades &middot; avg {avg_r:+.2f}R</div></div>')
    return f'<div class="panel superior-panel"><div class="panel-head"><h2>{title} <span class="subtle" style="font-weight:400">({len(candidates)})</span></h2><span class="subtle">{subtle}</span></div><div class="superior-grid">{"".join(cards)}</div></div>'


def _side_sections(weekly_scan, daily_scan, side, flip_log, public_view,
                   w_by, d_by, side_tickers, atr_period, atr_multiplier):
    """Build the three sections for one tab: Superior → Recent Flips → Opportunities → Full Watchlist."""
    run_date = daily_scan.get("run_date") or weekly_scan.get("run_date")
    weekly_results = weekly_scan["results"]; daily_results = daily_scan["results"]

    def _sort_key(ticker):
        wr = w_by.get(ticker) or {}; dr = d_by.get(ticker) or {}
        d_rec = dr.get("bars_in_trend") if dr.get("status") == "ok" else None
        w_rec = wr.get("bars_in_trend") if wr.get("status") == "ok" else None
        return (d_rec if d_rec is not None else 9999, w_rec if w_rec is not None else 9999, ticker)

    table_tickers = side_tickers
    allowed = side_tickers
    order = sorted(table_tickers, key=_sort_key)

    def _ok(rs): return [r for r in rs if r.get("status") == "ok"]
    w_ok = _ok(weekly_results); d_ok = _ok(daily_results)
    in_side = lambda r: r["ticker"] in table_tickers
    w_buys  = [r for r in w_ok if r["signal"] == "BUY"  and in_side(r)]
    w_sells = [r for r in w_ok if r["signal"] == "SELL" and in_side(r)]
    d_buys  = [r for r in d_ok if r["signal"] == "BUY"  and in_side(r)]
    d_sells = [r for r in d_ok if r["signal"] == "SELL" and in_side(r)]

    def _buy_grid(rs):
        if not rs: return '<div class="empty-note">Nothing fresh matching this section.</div>'
        return '<div class="buy-grid">' + "".join(_buy_html(r) for r in rs) + '</div>'

    if side == "long":
        confluence_fresh = {r["ticker"] for r in w_buys} & {r["ticker"] for r in d_buys}
        confluence_results = [r for r in d_buys if r["ticker"] in confluence_fresh] or [r for r in w_buys if r["ticker"] in confluence_fresh]
        opp_panels = f'<div class="panel"><h2>Buying Opportunities</h2><div class="buy-panels"><div class="buy-subpanel confluence-panel"><h3>★ Confluence Buy (fresh BUY on both weekly &amp; daily) <span class="count">{len(confluence_fresh)}</span></h3>{_buy_grid(confluence_results)}</div><div class="buy-subpanel"><h3><span class="tf-tag tf-tag-w">Weekly</span> Buy Flips <span class="count">{len(w_buys)}</span></h3>{_buy_grid(w_buys)}</div><div class="buy-subpanel"><h3><span class="tf-tag tf-tag-d">Daily</span> Buy Flips <span class="count">{len(d_buys)}</span></h3>{_buy_grid(d_buys)}</div></div></div>'
        recent_side = "long"
        table_h2 = "Full Weekly-Uptrend Watchlist — Weekly &amp; Daily Side-by-Side"
    else:
        confluence_fresh = {r["ticker"] for r in w_sells} & {r["ticker"] for r in d_sells}
        confluence_results = [r for r in d_sells if r["ticker"] in confluence_fresh] or [r for r in w_sells if r["ticker"] in confluence_fresh]
        opp_panels = f'<div class="panel"><h2>Selling Opportunities</h2><div class="buy-panels"><div class="buy-subpanel confluence-panel" style="border-color:rgba(240,71,93,0.35);background:rgba(240,71,93,0.05);"><h3 style="color:var(--bear);">★ Confluence Sell (fresh SELL on both weekly &amp; daily) <span class="count">{len(confluence_fresh)}</span></h3>{_buy_grid(confluence_results)}</div><div class="buy-subpanel"><h3><span class="tf-tag tf-tag-w">Weekly</span> Sell Flips <span class="count">{len(w_sells)}</span></h3>{_buy_grid(w_sells)}</div><div class="buy-subpanel"><h3><span class="tf-tag tf-tag-d">Daily</span> Sell Flips <span class="count">{len(d_sells)}</span></h3>{_buy_grid(d_sells)}</div></div></div>'
        recent_side = "short"
        table_h2 = "Full Weekly-Downtrend Watchlist — Weekly &amp; Daily Side-by-Side"

    superior_panel = _superior_panel_html(daily_results, table_tickers, side)
    recent_flips_panel = _recent_flips_panel_html(flip_log, run_date, days=7, side=recent_side, allowed_tickers=allowed)
    rows_html = "".join(_combined_row_html(t, w_by.get(t), d_by.get(t), public_view=public_view) for t in order)
    portfolio_headers = "" if public_view else '<th>Held</th><th>Position P/L</th>'
    portfolio_chip = "" if public_view else '<button class="chip-btn" data-filter="held">My Portfolio</button>'
    table_block = f'<div class="panel"><h2>{table_h2}</h2><div class="controls"><button class="chip-btn active" data-filter="all">All</button><button class="chip-btn" data-filter="recent7">Recent (7d)</button><button class="chip-btn" data-filter="any-buy">Any Buy</button><button class="chip-btn" data-filter="any-sell">Any Sell</button><button class="chip-btn" data-filter="conf-bull">Confluence ▲▲</button><button class="chip-btn" data-filter="conf-bear">Confluence ▼▼</button><button class="chip-btn" data-filter="weekly-flip">Weekly Flips</button><button class="chip-btn" data-filter="daily-flip">Daily Flips</button>{portfolio_chip}<input type="text" class="search-box" placeholder="Search ticker..."></div><table class="scan-table"><thead><tr><th>Conf. ↕</th><th>Ticker</th><th>Close</th><th><span class="tf-tag tf-tag-w">W</span>Weekly ↕</th><th><span class="tf-tag tf-tag-d">D</span>Daily ↕</th>{portfolio_headers}<th>Weekly Bar</th><th>Daily Bar</th></tr></thead><tbody>{rows_html}</tbody></table></div>'

    return {
        "superior_panel": superior_panel,
        "opp_panels": opp_panels,
        "recent_flips_panel": recent_flips_panel,
        "table_block": table_block,
        "ticker_count": len(table_tickers),
    }


def generate_combined_html_report(weekly_scan, daily_scan, atr_period, atr_multiplier, output_path,
                                  flip_log=None, public_view=False, side="full"):
    """Full combined report (used for the dated archive at docs/reports/)."""
    weekly_results = weekly_scan["results"]; daily_results = daily_scan["results"]
    run_date = daily_scan.get("run_date") or weekly_scan.get("run_date")
    w_by = {r["ticker"]: r for r in weekly_results}; d_by = {r["ticker"]: r for r in daily_results}

    def _dir_of(by, t):
        r = by.get(t); return r.get("direction") if r and r.get("status") == "ok" else None
    all_tickers = set()
    for r in weekly_results: all_tickers.add(r["ticker"])
    for r in daily_results: all_tickers.add(r["ticker"])

    def _sort_key(ticker):
        wr = w_by.get(ticker) or {}; dr = d_by.get(ticker) or {}
        d_rec = dr.get("bars_in_trend") if dr.get("status") == "ok" else None
        w_rec = wr.get("bars_in_trend") if wr.get("status") == "ok" else None
        return (d_rec if d_rec is not None else 9999, w_rec if w_rec is not None else 9999, ticker)

    order = sorted(all_tickers, key=_sort_key)
    def _ok(rs): return [r for r in rs if r.get("status") == "ok"]
    w_ok = _ok(weekly_results); d_ok = _ok(daily_results)
    w_buys = [r for r in w_ok if r["signal"] == "BUY"]; w_sells = [r for r in w_ok if r["signal"] == "SELL"]
    d_buys = [r for r in d_ok if r["signal"] == "BUY"]; d_sells = [r for r in d_ok if r["signal"] == "SELL"]
    error_count = sum(1 for r in weekly_results if r.get("status") != "ok") + sum(1 for r in daily_results if r.get("status") != "ok")
    confluence_buy_fresh = {r["ticker"] for r in w_buys} & {r["ticker"] for r in d_buys}
    confluence_sell_fresh = {r["ticker"] for r in w_sells} & {r["ticker"] for r in d_sells}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    weekly_alerts = weekly_scan.get("alerts", []); daily_alerts = daily_scan.get("alerts", [])
    all_alerts = [(a, "Weekly") for a in weekly_alerts] + [(a, "Daily") for a in daily_alerts]
    if all_alerts and not public_view:
        alert_banner = f'<div class="alert-banner"><div class="alert-head">⚠ Sell signal on held stock(s) — {len(weekly_alerts)} weekly, {len(daily_alerts)} daily</div>{"".join(_combined_alert_html(a, tf) for (a, tf) in all_alerts)}</div>'
    else:
        alert_banner = ""
    stats_html = f'<div class="stats-row"><div class="stat-chip"><div class="num">{len(order)}</div><div class="label">Tickers</div></div><div class="stats-group-label">Weekly</div><div class="stat-chip stat-buy"><div class="num">{len(w_buys)}</div><div class="label">Buy</div></div><div class="stat-chip stat-sell"><div class="num">{len(w_sells)}</div><div class="label">Sell</div></div><div class="stats-group-label">Daily</div><div class="stat-chip stat-buy"><div class="num">{len(d_buys)}</div><div class="label">Buy</div></div><div class="stat-chip stat-sell"><div class="num">{len(d_sells)}</div><div class="label">Sell</div></div><div class="stats-group-label">Confluence</div><div class="stat-chip stat-buy"><div class="num">{len(confluence_buy_fresh)}</div><div class="label">Buy (both)</div></div><div class="stat-chip stat-sell"><div class="num">{len(confluence_sell_fresh)}</div><div class="label">Sell (both)</div></div><div class="stat-chip"><div class="num">{error_count}</div><div class="label">Errors</div></div></div>'
    def _buy_grid(rs):
        return '<div class="buy-grid">' + "".join(_buy_html(r) for r in rs) + '</div>' if rs else '<div class="empty-note">Nothing fresh.</div>'
    confluence_results = [r for r in d_buys if r["ticker"] in confluence_buy_fresh] or [r for r in w_buys if r["ticker"] in confluence_buy_fresh]
    opp_panels = f'<div class="panel"><h2>Buying Opportunities</h2><div class="buy-panels"><div class="buy-subpanel confluence-panel"><h3>★ Confluence Buy <span class="count">{len(confluence_buy_fresh)}</span></h3>{_buy_grid(confluence_results)}</div><div class="buy-subpanel"><h3><span class="tf-tag tf-tag-w">Weekly</span> Buy Flips <span class="count">{len(w_buys)}</span></h3>{_buy_grid(w_buys)}</div><div class="buy-subpanel"><h3><span class="tf-tag tf-tag-d">Daily</span> Buy Flips <span class="count">{len(d_buys)}</span></h3>{_buy_grid(d_buys)}</div></div></div>'
    recent_flips_panel = _recent_flips_panel_html(flip_log, run_date, days=7, side="all")
    rows_html = "".join(_combined_row_html(t, w_by.get(t), d_by.get(t), public_view=public_view) for t in order)
    portfolio_headers = "" if public_view else '<th>Held</th><th>Position P/L</th>'
    portfolio_chip = "" if public_view else '<button class="chip-btn" data-filter="held">My Portfolio</button>'
    title_suffix = " · Full Archive" + (" · Public view" if public_view else "")
    public_notice = '<div class="params" style="margin-top:6px;">Public view — portfolio positions are hidden.</div>' if public_view else ""
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Supertrend Scanner — {run_date}{title_suffix}</title>{CSS_JS}{COMBINED_CSS_EXTRA}</head><body><div class="wrap">
  <div class="topbar"><h1>Supertrend Combined Scanner{title_suffix}</h1><div class="params">ATR({atr_period}) &times; {atr_multiplier} &middot; Weekly + Daily &middot; Generated {generated_at}</div>{public_notice}</div>
  {alert_banner}{recent_flips_panel}{stats_html}{opp_panels}
  <div class="panel"><h2>Full Watchlist — Weekly &amp; Daily Side-by-Side</h2>
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
    <table id="scan-table"><thead><tr><th>Conf. ↕</th><th>Ticker</th><th>Close</th><th><span class="tf-tag tf-tag-w">W</span>Weekly ↕</th><th><span class="tf-tag tf-tag-d">D</span>Daily ↕</th>{portfolio_headers}<th>Weekly Bar</th><th>Daily Bar</th></tr></thead><tbody>{rows_html}</tbody></table>
  </div>
  <footer>Parameters: ATR period {atr_period}, multiplier {atr_multiplier}.</footer>
</div>{COMBINED_JS}</body></html>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(body)
    return output_path


def generate_tabbed_html_report(weekly_scan, daily_scan, atr_period, atr_multiplier, output_path,
                                flip_log=None, public_view=True):
    """Single-page tabbed Long + Short public view."""
    weekly_results = weekly_scan["results"]; daily_results = daily_scan["results"]
    run_date = daily_scan.get("run_date") or weekly_scan.get("run_date")
    w_by = {r["ticker"]: r for r in weekly_results}; d_by = {r["ticker"]: r for r in daily_results}

    all_tickers = set()
    for r in weekly_results: all_tickers.add(r["ticker"])
    for r in daily_results: all_tickers.add(r["ticker"])

    def _dir_of(by, t):
        r = by.get(t); return r.get("direction") if r and r.get("status") == "ok" else None
    weekly_bullish_tickers = {t for t in all_tickers if _dir_of(w_by, t) == "Bullish"}
    weekly_bearish_tickers = {t for t in all_tickers if _dir_of(w_by, t) == "Bearish"}

    long_sections  = _side_sections(weekly_scan, daily_scan, "long",  flip_log, public_view, w_by, d_by, weekly_bullish_tickers, atr_period, atr_multiplier)
    short_sections = _side_sections(weekly_scan, daily_scan, "short", flip_log, public_view, w_by, d_by, weekly_bearish_tickers, atr_period, atr_multiplier)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    weekly_alerts = weekly_scan.get("alerts", []); daily_alerts = daily_scan.get("alerts", [])
    all_alerts = [(a, "Weekly") for a in weekly_alerts] + [(a, "Daily") for a in daily_alerts]
    if all_alerts and not public_view:
        alert_banner = f'<div class="alert-banner"><div class="alert-head">⚠ Sell signal on held stock(s) — {len(weekly_alerts)} weekly, {len(daily_alerts)} daily</div>{"".join(_combined_alert_html(a, tf) for (a, tf) in all_alerts)}</div>'
    else:
        alert_banner = ""
    public_notice = '<div class="params" style="margin-top:6px;">Public view — portfolio positions are hidden.</div>' if public_view else ""

    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Supertrend Scanner — {run_date}</title>{CSS_JS}{COMBINED_CSS_EXTRA}</head><body><div class="wrap">
  <div class="topbar"><h1>Supertrend Combined Scanner</h1><div class="params">ATR({atr_period}) &times; {atr_multiplier} &middot; Weekly + Daily &middot; Generated {generated_at}</div>{public_notice}</div>
  <div class="tab-nav">
    <button data-tab="long" class="active long-active">▲ Long · Weekly Uptrend <span class="muted">({long_sections['ticker_count']})</span></button>
    <button data-tab="short" class="short-active">▼ Short · Weekly Downtrend <span class="muted">({short_sections['ticker_count']})</span></button>
    <a class="archive-link" href="archive.html">Archive →</a>
  </div>
  {alert_banner}
  <div id="pane-long" class="tab-pane active">
    {long_sections['superior_panel']}
    {long_sections['recent_flips_panel']}
    {long_sections['opp_panels']}
    {long_sections['table_block']}
  </div>
  <div id="pane-short" class="tab-pane">
    {short_sections['superior_panel']}
    {short_sections['recent_flips_panel']}
    {short_sections['opp_panels']}
    {short_sections['table_block']}
  </div>
  <footer>Parameters: ATR period {atr_period}, multiplier {atr_multiplier}. Long tab shows every ticker whose current weekly direction is Bullish; Short mirrors. Superior Selection ranks tickers by historical backtest profit factor.</footer>
</div>{TABBED_JS}</body></html>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(body)
    return output_path
