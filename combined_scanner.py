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

from engine import commit_history, run_analysis
from scanner import CONFIG as WEEKLY_CONFIG
from daily_scanner import CONFIG as DAILY_CONFIG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMBINED_OUTPUT_DIR = os.path.join(BASE_DIR, "output", "combined")


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

    os.makedirs(COMBINED_OUTPUT_DIR, exist_ok=True)
    run_date = daily_scan["run_date"]
    out_path = os.path.join(COMBINED_OUTPUT_DIR, f"report_{run_date}.html")

    from report import generate_combined_html_report

    generate_combined_html_report(
        weekly_scan=weekly_scan,
        daily_scan=daily_scan,
        atr_period=DAILY_CONFIG.atr_period,     # shared params, either works
        atr_multiplier=DAILY_CONFIG.atr_multiplier,
        output_path=out_path,
    )
    print(f"\nCombined report written to: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
