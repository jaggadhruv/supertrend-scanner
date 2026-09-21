"""
publish.py
----------
Writes the public-view combined report to a docs/ folder that GitHub Pages
can serve. Called from combined_scanner.py when COMBINED_PUBLISH_PAGE=1 is
set in the environment (the combined GitHub Actions workflow sets this;
running combined_scanner locally without the env var leaves docs/ alone).

Layout produced:

    docs/
      index.html                       # always the latest report — overwritten
      reports/
        report_<date>.html             # dated archive, pruned to 30 days
      archive.html                     # auto-generated index of docs/reports/

Public view means: no "Held" or "Position P/L" columns, no "My Portfolio"
filter, no held-bearish alert banner. Watchlist tickers and their weekly/
daily Supertrend signals + the rolling 7-day flip log ARE visible.
"""

import html as _html
import os
from datetime import datetime

from engine import prune_old_reports
from report import generate_combined_html_report


def publish_public_report(weekly_scan, daily_scan, flip_log, atr_period, atr_multiplier,
                          docs_dir: str, run_date: str) -> str:
    """
    Render the combined report in public_view mode into docs/index.html and
    docs/reports/report_<run_date>.html, then rebuild docs/archive.html and
    prune docs/reports/ to 30 days. Returns the archive path.
    """
    reports_dir = os.path.join(docs_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Tell GitHub Pages to skip Jekyll and serve these HTML files as-is.
    # Without this, Pages tries to run Jekyll on docs/, and Jekyll's
    # default theme build (SCSS) fails on our all-HTML layout with
    # "Error: No such file or directory @ dir_chdir0 - .../docs".
    # An empty file is enough — Pages only checks that it exists.
    nojekyll_path = os.path.join(docs_dir, ".nojekyll")
    if not os.path.exists(nojekyll_path):
        open(nojekyll_path, "w").close()

    latest_path = os.path.join(docs_dir, "index.html")
    archive_path = os.path.join(reports_dir, f"report_{run_date}.html")

    # Write the archived (dated) copy first...
    generate_combined_html_report(
        weekly_scan=weekly_scan,
        daily_scan=daily_scan,
        flip_log=flip_log,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier,
        output_path=archive_path,
        public_view=True,
    )
    # ...then the "latest" copy at docs/index.html (identical content today,
    # but is overwritten every run so the URL always shows the newest one).
    generate_combined_html_report(
        weekly_scan=weekly_scan,
        daily_scan=daily_scan,
        flip_log=flip_log,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier,
        output_path=latest_path,
        public_view=True,
    )

    removed = prune_old_reports(reports_dir, days=30, run_date=run_date)
    if removed:
        print(f"Cleanup: removed {removed} public report(s) older than 30 days from {reports_dir}")

    _rebuild_archive_index(docs_dir, run_date)
    return archive_path


def _rebuild_archive_index(docs_dir: str, run_date: str) -> None:
    """Regenerate docs/archive.html — a plain, offline-friendly list of every
    report currently in docs/reports/, newest first."""
    reports_dir = os.path.join(docs_dir, "reports")
    entries = []
    if os.path.isdir(reports_dir):
        for name in sorted(os.listdir(reports_dir), reverse=True):
            if name.startswith("report_") and name.endswith(".html"):
                entries.append(name)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = "\n".join(
        f'      <li><a href="reports/{_html.escape(n)}">{_html.escape(n[len("report_"):-len(".html")])}</a></li>'
        for n in entries
    ) or '      <li class="muted">No archived reports yet.</li>'

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Supertrend Scanner — Archive</title>
<style>
  body {{ background:#0B0E14; color:#E7ECF3; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;
         font-size:14px; line-height:1.6; padding:40px 24px; margin:0; }}
  .wrap {{ max-width:720px; margin:0 auto; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .meta {{ color:#7C8797; font-size:12.5px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
  a {{ color:#96A9E6; text-decoration:none; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
  a:hover {{ text-decoration:underline; }}
  .muted {{ color:#7C8797; }}
  ul {{ padding-left: 20px; margin-top: 20px; }}
  li {{ padding: 3px 0; }}
  .primary {{ display:inline-block; margin-top:16px; padding:8px 16px; background:#2FBF71; color:#0B0E14;
              border-radius:8px; font-weight:700; }}
  footer {{ margin-top:36px; color:#7C8797; font-size:12px; border-top:1px solid #232A38; padding-top:14px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Supertrend Combined Scanner — Archive</h1>
  <div class="meta">Last updated {generated_at} (run {run_date})</div>
  <a class="primary" href="index.html">Open latest report →</a>
  <h2 style="margin-top:32px;font-size:14px;color:#7C8797;text-transform:uppercase;letter-spacing:0.05em;">Archived reports</h2>
  <ul>
{rows}
  </ul>
  <footer>
    Reports older than 30 days are pruned automatically. Public view — portfolio positions are not shown here.
  </footer>
</div>
</body>
</html>
"""
    with open(os.path.join(docs_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
