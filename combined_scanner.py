"""
combined_scanner.py
-------------------
Runs BOTH the weekly and daily Supertrend scans in one go and produces
a single merged HTML report that shows each ticker's weekly and daily
state side-by-side, with a "Confluence" view for stocks that flipped
BUY or SELL on both timeframes on the same run.

    python combined_scanner.py

What this adds on top of running scanner.py + daily_scanner.py separately:

  - A merged report (output/combined/report_<date>.html) with a Recent
    Buy Flips panel sourced from the shared flip log.
  - Weekly-confluence boost: when a daily BUY lands on a ticker whose
    weekly timeframe is also bullish, its logged quality_score gets
    +15 points. This is why confluence BUYs clear the quality gate
    more easily than lone daily BUYs.
  - When env var COMBINED_PUBLISH_PAGE=1 is set, publishes a public-view
    copy to docs/ for GitHub Pages. The combined workflow sets this;
    local runs leave docs/ alone unless you set the var yourself.

Quality gate: BUY flips must score >= MIN_FLIP_QUALITY (default 60) to
be logged. SELL flips are always logged (the held-bearish alert path
depends on them). MIN_FLIP_QUALITY env var overrides the default.
"""

import os

from engine import (
    _flip_log_path,
    _min_quality_from_env,
    commit_history,
    load_flip_log,
    prune_old_reports,
    record_flips,
    run_analysis,
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

    # Advance both history files.
    commit_history(WEEKLY_CONFIG, weekly_scan)
    commit_history(DAILY_CONFIG, daily_scan)

    # The set of tickers that are CURRENTLY bullish on the weekly chart.
    # Daily BUYs for these tickers get the confluence boost in record_flips.
    weekly_bullish = {
        r["ticker"] for r in weekly_scan["results"]
        if r.get("status") == "ok" and r.get("direction") == "Bullish"
    }

    min_q = _min_quality_from_env()

    # Weekly flips: no confluence boost (there's no "higher" timeframe to
    # confluence with here). Still gated on min_quality.
    w_stats = record_flips(
        WEEKLY_CONFIG, weekly_scan["results"], weekly_scan["run_date"],
        min_quality=min_q,
    )
    # Daily flips: pass the confluence set so daily BUYs with weekly
    # agreement get the +15 quality bump BEFORE the gate check.
    d_stats = record_flips(
        DAILY_CONFIG, daily_scan["results"], daily_scan["run_date"],
        min_quality=min_q, weekly_bullish_tickers=weekly_bullish,
    )
    print(
        f"\nFlip log (threshold quality >= {min_q}): "
        f"weekly +{w_stats['added']} (skipped {w_stats['skipped_low_quality']} low-q), "
        f"daily +{d_stats['added']} (skipped {d_stats['skipped_low_quality']} low-q)"
    )

    flip_log = load_flip_log(_flip_log_path(WEEKLY_CONFIG))

    os.makedirs(COMBINED_OUTPUT_DIR, exist_ok=True)
    run_date = daily_scan["run_date"]
    out_path = os.path.join(COMBINED_OUTPUT_DIR, f"report_{run_date}.html")

    from report import generate_combined_html_report
    generate_combined_html_report(
        weekly_scan=weekly_scan,
        daily_scan=daily_scan,
        flip_log=flip_log,
        atr_period=DAILY_CONFIG.atr_period,
        atr_multiplier=DAILY_CONFIG.atr_multiplier,
        output_path=out_path,
    )
    print(f"\nCombined report written to: {out_path}")

    # Prune all three output folders to the last 30 days.
    for label, d in [
        ("combined", COMBINED_OUTPUT_DIR),
        ("weekly",   WEEKLY_CONFIG.output_dir),
        ("daily",    DAILY_CONFIG.output_dir),
    ]:
        removed = prune_old_reports(d, days=30, run_date=run_date)
        if removed:
            print(f"Cleanup: removed {removed} {label} report(s) older than 30 days")

    # Optional publish to docs/ for GitHub Pages.
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
