"""
combined_scanner.py
-------------------
Runs BOTH the weekly and daily Supertrend scans in one go and produces a
single merged HTML report that shows each ticker's weekly and daily state
side-by-side, with an added "Confluence" view for stocks that flipped
BUY or SELL on both timeframes on the same run.

    python combined_scanner.py

This is entirely additive - scanner.py and daily_scanner.py still work
exactly as before. The individual reports and history files are
untouched by design if you just run this script (this script writes the
same history files each individual scanner writes to, so the state
stays consistent whichever entry point you use).

Output:
    output/combined/report_<date>.html  - the merged report
    data/weekly_history.json            - updated (same file the weekly scanner uses)
    data/daily_history.json             - updated (same file the daily scanner uses)

Best run after the market close so both the daily candle and (on
weekends) the weekly candle are fully formed. Safe to run as often as
you like - like the other scanners, every run re-downloads a full
lookback window and recomputes Supertrend from scratch.
"""

import os

from engine import (
    commit_history,
    load_flip_log,
    prune_old_reports,
    record_flips,
    run_analysis,
    _flip_log_path,
)
from scanner import CONFIG as WEEKLY_CONFIG
from daily_scanner import CONFIG as DAILY_CONFIG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMBINED_OUTPUT_DIR = os.path.join(BASE_DIR, "output", "combined")
DOCS_DIR = os.path.join(BASE_DIR, "docs")


def main():
    print("=" * 68)
    print("Supertrend Combined Scanner (Weekly + Daily)")
    print("=" * 68)

    print("\n[1/2] Running WEEKLY analysis...")
    weekly_scan = run_analysis(WEEKLY_CONFIG)
    if weekly_scan is None:
        print("Weekly analysis returned nothing — aborting.")
        return None

    print("\n[2/2] Running DAILY analysis...")
    daily_scan = run_analysis(DAILY_CONFIG)
    if daily_scan is None:
        print("Daily analysis returned nothing — aborting.")
        return None

    # Advance both history files - equivalent to having run each individual
    # scanner. Keeps things consistent whether you run this script or the
    # per-timeframe ones next time.
    commit_history(WEEKLY_CONFIG, weekly_scan)
    commit_history(DAILY_CONFIG, daily_scan)

    # Append any fresh BUY/SELL flips to the shared, timeframe-spanning flip
    # log. Dedupes on (ticker, timeframe, flip_date), so if you already ran
    # scanner.py earlier today, this call adds nothing for that timeframe.
    w_added = record_flips(WEEKLY_CONFIG, weekly_scan["results"], weekly_scan["run_date"])
    d_added = record_flips(DAILY_CONFIG,  daily_scan["results"],  daily_scan["run_date"])
    print(f"\nFlip log: +{w_added} weekly, +{d_added} daily new flip(s) recorded")

    # Reload the log so the report gets the full picture (including flips
    # from earlier runs still inside the retention window).
    flip_log = load_flip_log(_flip_log_path(WEEKLY_CONFIG))

    os.makedirs(COMBINED_OUTPUT_DIR, exist_ok=True)
    run_date = daily_scan["run_date"]
    out_path = os.path.join(COMBINED_OUTPUT_DIR, f"report_{run_date}.html")

    from report import generate_combined_html_report

    generate_combined_html_report(
        weekly_scan=weekly_scan,
        daily_scan=daily_scan,
        flip_log=flip_log,
        atr_period=DAILY_CONFIG.atr_period,     # shared params, either works
        atr_multiplier=DAILY_CONFIG.atr_multiplier,
        output_path=out_path,
    )
    print(f"\nCombined report written to: {out_path}")

    # Cleanup: keep each output/<flavor>/ folder to the last 30 days of
    # reports. run_scan() already prunes its own timeframe when scanner.py
    # / daily_scanner.py run individually, but a combined run touches all
    # three folders' fresh data too, so we prune all three here.
    for label, d in [
        ("combined", COMBINED_OUTPUT_DIR),
        ("weekly",   WEEKLY_CONFIG.output_dir),
        ("daily",    DAILY_CONFIG.output_dir),
    ]:
        removed = prune_old_reports(d, days=30, run_date=run_date)
        if removed:
            print(f"Cleanup: removed {removed} {label} report(s) older than 30 days")

    # Optional: publish the public-view copy to docs/ so GitHub Pages can
    # serve it. Enabled by setting COMBINED_PUBLISH_PAGE=1 in the environment
    # (the combined GitHub Actions workflow does this). Never touched
    # otherwise, so local runs don't accidentally write to docs/.
    if os.environ.get("COMBINED_PUBLISH_PAGE"):
        from publish import publish_public_report
        pub_path = publish_public_report(
            weekly_scan=weekly_scan,
            daily_scan=daily_scan,
            flip_log=flip_log,
            atr_period=DAILY_CONFIG.atr_period,
            atr_multiplier=DAILY_CONFIG.atr_multiplier,
            docs_dir=DOCS_DIR,
            run_date=run_date,
        )
        print(f"Public page published to: {os.path.join(DOCS_DIR, 'index.html')}")
        print(f"                archived: {pub_path}")

    return out_path


if __name__ == "__main__":
    main()
