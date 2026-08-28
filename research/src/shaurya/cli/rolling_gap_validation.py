"""Run rolling pseudo-live validation of the three frozen gap candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shaurya.research.intraday_alpha_tournament import build_tournament_panel
from shaurya.research.rolling_gap_validation import run_rolling_gap_validation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    panel, audit = build_tournament_panel(args.index_zip)
    payload, monthly = run_rolling_gap_validation(panel)
    payload["data_audit"] = audit
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "rolling_gap_validation.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    monthly.to_csv(args.output / "rolling_gap_monthly.csv", index=False)

    lines = [
        "# Rolling pseudo-live gap validation",
        "",
        f"**Verdict: {payload['summary']['verdict']}.**",
        "",
        "This is a retrospective monthly walk-forward stability test, not a new holdout.",
        "",
        "| candidate | net 1bp/day | net 2bp/day | net 6bp/day | positive months | p-value |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, value in payload["candidates"].items():
        one = value["costs"]["cost_1bps"]
        two = value["costs"]["cost_2bps"]
        six = value["costs"]["cost_6bps"]
        lines.append(
            f"| {name} | {one['mean_daily_bps']:+.3f} | {two['mean_daily_bps']:+.3f} | "
            f"{six['mean_daily_bps']:+.3f} | {value['positive_month_rate_at_1bps']:.1%} | "
            f"{one['one_sided_p']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"Holm passes: {', '.join(payload['summary']['holm_passes']) or 'none'}.",
            f"Stability passes: {', '.join(payload['summary']['stable_candidates']) or 'none'}.",
            "",
            "Year-level metrics and every monthly calibration are in the JSON; monthly P&L and "
            "turnover are in the CSV.",
            "",
        ]
    )
    (args.output / "ROLLING_GAP_VALIDATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
