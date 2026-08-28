"""Run the cost-aware NIFTY intraday directional-alpha tournament."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shaurya.research.intraday_alpha_tournament import build_tournament_panel, run_tournament


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    panel, audit = build_tournament_panel(args.index_zip)
    result = run_tournament(panel)
    payload = {"data_audit": audit, **result}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "intraday_alpha_tournament.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    summary = payload["summary"]
    lines = [
        "# Intraday directional-alpha tournament",
        "",
        "**Index-return proxy only; no executable option-P&L claim.**",
        "",
        f"Verdict: **{summary['verdict']}**",
        "",
        f"Strategies tested: {summary['strategies_tested']}",
        f"Survivors: {', '.join(summary['survivors']) if summary['survivors'] else 'none'}",
        "",
        "| strategy | 2025 net bps/day | 2025 Sharpe | 2026 net bps/day | 2026 Sharpe | "
        "10bp 2026 bps/day |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(
        payload["strategies"],
        key=lambda name: payload["strategies"][name]["current_2026"]["cost_6bps"][
            "annualized_sharpe"
        ],
        reverse=True,
    )
    for name in ranked:
        value = payload["strategies"][name]
        y25 = value["holdout_2025"]["cost_6bps"]
        y26 = value["current_2026"]["cost_6bps"]
        y26_hard = value["current_2026"]["cost_10bps"]
        lines.append(
            f"| {name} | {y25['mean_daily_bps']:+.2f} | {y25['annualized_sharpe']:+.2f} | "
            f"{y26['mean_daily_bps']:+.2f} | {y26['annualized_sharpe']:+.2f} | "
            f"{y26_hard['mean_daily_bps']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "A survivor must be positive after the 6bp round-trip hurdle in both 2025 and 2026, "
            "and pass Holm correction on 2025 daily P&L. Full cost ladders, turnover, drawdown, "
            "and Tuesday-regime slices are in the JSON.",
            "",
        ]
    )
    (args.output / "INTRADAY_ALPHA_TOURNAMENT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
