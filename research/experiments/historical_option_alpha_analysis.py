"""Run the full-history option-surface alpha study and write an auditable report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from shaurya.research.historical_option_alpha import (
    build_historical_option_panel,
    run_historical_option_alpha,
)


def _candidate_table(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    corrected = set(payload["summary"]["holm_passes"])
    stable = set(payload["summary"]["stable_candidates"])
    for name, result in payload["candidates"].items():
        metric = result["costs"]["cost_6bps"]
        rows.append(
            {
                "candidate": name,
                "mean_daily_bps_6bps": metric["mean_daily_bps"],
                "annualized_sharpe_6bps": metric["annualized_sharpe"],
                "one_sided_p_6bps": metric["one_sided_p"],
                "positive_month_rate_6bps": result["positive_month_rate_at_6bps"],
                "average_round_trips_per_day": metric["average_round_trips_per_day"],
                "holm_pass": name in corrected,
                "stable": name in stable,
            }
        )
    return pd.DataFrame(rows).sort_values("mean_daily_bps_6bps", ascending=False)


def _readme(payload: dict[str, Any], candidates: pd.DataFrame) -> str:
    top = candidates.head(10).to_csv(index=False)
    return f"""# Full-history option-surface alpha study

This analysis uses every completed historical session available in the one-minute NIFTY index
and rolling ATM-relative option archives. It does not use the invalid 2026-08-28 capture and does
not alter or consume the frozen prospective JEPA bundle.

## Result

**{payload["summary"]["verdict"]}**

- Matched sessions: {payload["audit"]["matched_sessions"]}
- Decisions: {payload["audit"]["matched_decisions"]}
- Decision range: {payload["audit"]["first_decision"]} to {payload["audit"]["last_decision"]}
- Evaluation: monthly pseudo-live, beginning 2022-01
- Calibration: trailing 252 completed sessions before each month
- Primary assumed round-trip cost: 6 bps
- Holm-corrected passes: {payload["summary"]["holm_passes"]}
- Stable candidates: {payload["summary"]["stable_candidates"]}

The option files are rolling moneyness buckets, not fixed tradable contracts. Accordingly, their
surface variables are used only as predictors. P&L uses the matched NIFTY index return as a
directional futures proxy, so any apparent survivor still requires fixed-contract futures data and
slippage validation before it can be called tradable.

## Candidate ranking at 6 bps

```csv
{top.strip()}
```

Machine-readable details are in `results.json`; monthly and yearly diagnostics are in the CSV
files alongside this report.
"""


def run(index_zip: Path, options_zip: Path, output: Path) -> None:
    panel, audit = build_historical_option_panel(index_zip, options_zip)
    payload, monthly = run_historical_option_alpha(panel)
    payload["audit"] = audit
    output.mkdir(parents=True, exist_ok=True)
    candidates = _candidate_table(payload)
    diagnostics = pd.DataFrame(payload["yearly_diagnostics"])
    (output / "results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    monthly.to_csv(output / "monthly.csv", index=False)
    diagnostics.to_csv(output / "yearly_diagnostics.csv", index=False)
    candidates.to_csv(output / "candidates.csv", index=False)
    (output / "README.md").write_text(_readme(payload, candidates), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--options-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.index_zip, args.options_zip, args.output)


if __name__ == "__main__":
    main()
