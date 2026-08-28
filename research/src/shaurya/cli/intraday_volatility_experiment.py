"""Run the causal NIFTY intraday move/volatility forecast experiment."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shaurya.research.intraday_volatility import build_panel, run_experiment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--options-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=1_000)
    return parser


def _markdown(result: dict[str, Any], audit: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Intraday volatility lab — frozen retrospective result",
        "",
        "**Research only. No broker/order path and no executable option-P&L claim.**",
        "",
        f"Overall verdict: **{summary['overall_verdict']}**. ",
        f"{summary['tasks_passing_gate']} of {summary['tasks_tested']} forecast tasks passed.",
        "",
        "## Data audit",
        "",
        f"- Accepted {audit['accepted_sessions']:,} complete weekday sessions; rejected "
        f"{audit['rejected_sessions']:,} incomplete or pathological sessions.",
        f"- Matched {audit['matched_rows']:,} index/rolling-ATM rows and evaluated "
        f"{audit['sample_rows']:,} five-minute decision points.",
        f"- Evaluation panel: {audit['first_sample']} through {audit['last_sample']}.",
        "",
        "## Frozen results",
        "",
        "| target | selected on 2024 | 2025 skill [95% CI] | 2026 skill [95% CI] | "
        "Tuesday-regime skill | gate |",
        "|---|---|---:|---:|---:|---|",
    ]
    for name, task in result["tasks"].items():
        evaluations = task["evaluations"]
        holdout = evaluations.get("holdout_2025", {})
        current = evaluations.get("current_2026", {})
        regime = evaluations.get("tuesday_regime", {})
        h_metric = holdout.get("metric", {})
        interval = holdout.get("mae_skill_daily_bootstrap", {})
        c_metric = current.get("metric", {})
        c_interval = current.get("mae_skill_daily_bootstrap", {})
        r_metric = regime.get("metric", {})
        lines.append(
            f"| {name} | {task['selected_model']} | "
            f"{h_metric.get('mae_skill_vs_seasonal', float('nan')):+.3%} "
            f"[{interval.get('lower_95', float('nan')):+.3%}, "
            f"{interval.get('upper_95', float('nan')):+.3%}] | "
            f"{c_metric.get('mae_skill_vs_seasonal', float('nan')):+.3%} "
            f"[{c_interval.get('lower_95', float('nan')):+.3%}, "
            f"{c_interval.get('upper_95', float('nan')):+.3%}] | "
            f"{r_metric.get('mae_skill_vs_seasonal', float('nan')):+.3%} | "
            f"{'PASS' if task['gate']['passed'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "MAE skill is measured against a training-only time-of-day mean. Positive is better. "
            "The confidence interval resamples whole trading sessions because horizons overlap.",
            "",
            "## Do the rolling-ATM option fields add signal?",
            "",
            "The table below compares otherwise identical histogram models. Positive means adding "
            "the five option price/activity fields reduced MAE.",
            "",
            "| target | 2024 selection | 2025 holdout | 2026 current | Tuesday regime |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, task in result["tasks"].items():
        increment = task["option_feature_increment"]["histogram"]
        lines.append(
            f"| {name} | "
            f"{increment['selection']['option_mae_increment']:+.3%} | "
            f"{increment['holdout_2025']['option_mae_increment']:+.3%} | "
            f"{increment['current_2026']['option_mae_increment']:+.3%} | "
            f"{increment['tuesday_regime']['option_mae_increment']:+.3%} |"
        )
    lines.extend(
        [
            "",
            "**Decision:** the forecast signal is durable, but the rolling-ATM option increment is "
            "not. Freeze an index-only model for prospective validation; do not use aggregate ATM "
            "activity as a directional or volatility alpha until fixed-contract quote data exists.",
            "",
            "## Interpretation rules",
            "",
            "- A task passes only if both its 2025 and 2026 daily-block 95% intervals are above "
            "zero.",
            "- `option_feature_increment` in the JSON contains matched linear and nonlinear tests "
            "of whether rolling-ATM price/activity fields improve otherwise identical models.",
            "- Tuesday-regime results are reported separately; they are short and retrospective, "
            "so they cannot substitute for prospective validation.",
            "- The option archive has no fixed contract, strike, expiry, bid/ask, OI, IV, Greeks, "
            "or trade direction. The result can justify a forecast layer, not a tradable options "
            "strategy.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = _parser().parse_args()
    panel, audit = build_panel(args.index_zip, args.options_zip)
    result = run_experiment(panel, bootstrap_samples=args.bootstrap_samples)
    payload = {"data_audit": asdict(audit), **result}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "intraday_volatility_results.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (args.output / "INTRADAY_VOLATILITY_RESULT.md").write_text(
        _markdown(result, asdict(audit)),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
