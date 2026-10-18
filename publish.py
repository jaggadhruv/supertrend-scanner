"""
publish.py
----------
Writes the public-view combined report into a docs/ folder that
GitHub Pages serves. Called from combined_scanner.py when the env var
COMBINED_PUBLISH_PAGE=1 is set.

Layout:

    docs/
      .nojekyll                               # tells Pages to skip Jekyll
      index.html                              # TABBED Long + Short page
      archive.html                            # landing + dated archive index
      reports/
        report_<date>.html                    # dated archive (full view)

The old docs/short.html is no longer produced. If an old file exists
from a previous publish, it's deleted on the first run of this version.
"""

import html as _html
import os
from datetime import datetime

from engine import prune_old_reports
from report import generate_combined_html_report, generate_tabbed_html_report


def publish_public_report(weekly_scan, daily_scan, flip_log, atr_period, atr_multiplier,
                          docs_dir: str, run_date: str) -> str:
    """
    Writes three files per run and returns the full-archive path:

      - docs/index.html  = tabbed single page (Long + Short) in public mode
      - docs/reports/report_<run_date>.html = full archive (both sides visible)
      - docs/archive.html = regenerated listing of reports/

    Also writes/preserves docs/.nojekyll and removes the legacy
    docs/short.html if it survived from a previous publish.
    """
    reports_dir = os.path.join(docs_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    nojekyll_path = os.path.join(docs_dir, ".nojekyll")
    if not os.path.exists(nojekyll_path):
        open(nojekyll_path, "w").close()

    # One-time cleanup of the pre-tabbed layout.
    legacy_short = os.path.join(docs_dir, "short.html")
    if os.path.exists(legacy_short):
        try:
            os.remove(legacy_short)
            print(f"Cleanup: removed legacy {legacy_short} (consolidated into index.html)")
        except OSError:
            pass

    latest_path = os.path.join(docs_dir, "index.html")
    archive_path = os.path.join(reports_dir, f"report_{run_date}.html")

    # The main public page: tabbed Long + Short in one HTML, public-view.
    generate_tabbed_html_report(
        weekly_scan=weekly_scan, daily_scan=daily_scan,
        flip_log=flip_log,
        atr_period=atr_period, atr_multiplier=atr_multiplier,
        output_path=latest_path, public_view=True,
    )
    # The dated archive: full combined view (both sides visible, no tabs,
    # single long scrollable page — the authoritative historical record).
    generate_combined_html_report(
        weekly_scan=weekly_scan, daily_scan=daily_scan,
        flip_log=flip_log,
        atr_period=atr_period, atr_multiplier=atr_multiplier,
        output_path=archive_path, public_view=True, side="full",
    )

    removed = prune_old_reports(reports_dir, days=30, run_date=run_date)
    if removed:
        print(f"Cleanup: removed {removed} public report(s) older than 30 days from {reports_dir}")

    _rebuild_archive_index(docs_dir, run_date)
    return archive_path


def _rebuild_archive_index(docs_dir: str, run_date: str) -> None:
    """Regenerate docs/archive.html — a plain, offline-friendly list of every
    dated full-view report currently in docs/reports/, newest first."""
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
  h2 {{ font-size:14px; color:#7C8797; text-transform:uppercase; letter-spacing:0.05em; margin-top:28px; }}
  .meta {{ color:#7C8797; font-size:12.5px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
  a {{ color:#96A9E6; text-decoration:none; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
  a:hover {{ text-decoration:underline; }}
  .muted {{ color:#7C8797; }}
  ul {{ padding-left: 20px; margin-top: 12px; }}
  li {{ padding: 3px 0; }}
  .btn {{ display:inline-block; margin-top:16px; padding:10px 20px; border-radius:8px;
          background:#2FBF71; color:#0B0E14; font-weight:700; font-size: 14px; }}
  footer {{ margin-top:36px; color:#7C8797; font-size:12px; border-top:1px solid #232A38; padding-top:14px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Supertrend Combined Scanner — Archive</h1>
  <div class="meta">Last updated {generated_at} (run {run_date})</div>
  <a class="btn" href="index.html">Open latest report (Long + Short tabs) →</a>
  <h2>Dated archives (full view, both sides)</h2>
  <ul>
{rows}
  </ul>
  <footer>
    Reports older than 30 days are pruned automatically. Public view — portfolio positions are not shown.
  </footer>
</div>
</body>
</html>
"""
    with open(os.path.join(docs_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
