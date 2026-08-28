"""Run recent-data replications of selected intraday-alpha papers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shaurya.research.paper_alpha_scan import run_paper_alpha_scan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--options-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run_paper_alpha_scan(args.index_zip, args.options_zip)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "paper_alpha_scan.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    quarter = payload["quarter_hour"]["summary"]
    gated = payload["volatility_gated_direction"]["summary"]
    reversal = payload["options"]["half_hour_reversal"]["splits"]
    curvature = payload["options"]["smile_curvature"]["splits"]
    selected = gated["selected_on_validation"]
    best_active = gated["best_active_on_validation"]
    lines = [
        "# Paper-derived recent alpha scan",
        "",
        "The final index week and option week were not used for fitting or selection.",
        "",
        "**Verdict: no costed alpha is ready for promotion.**",
        "",
        "## Results",
        "",
        (
            "- Quarter-hour phase-0 validation correlation: "
            f"{quarter['phase_0_validation_correlation']:+.4f}; final: "
            f"{quarter['phase_0_final_correlation']:+.4f}."
        ),
        (
            "- Quarter-hour gross validation/final: "
            f"{quarter['phase_0_validation_gross_bps_per_day']:+.2f} / "
            f"{quarter['phase_0_final_gross_bps_per_day']:+.2f} bps/day; final net at a "
            "6bp round-trip hurdle: "
            f"{quarter['phase_0_final_net_6bps_per_day']:+.2f} bps/day."
        ),
        (
            f"- Selected on validation: `{selected}`; final net: "
            f"{gated['selected_final']['mean_daily_bps']:+.2f} bps/day."
        ),
        (
            f"- Best active gated candidate: `{best_active}`; final net: "
            f"{gated['best_active_final']['mean_daily_bps']:+.2f} bps/day."
        ),
        (
            "- Best ungated comparator final net: "
            f"{gated['ungated_final']['mean_daily_bps']:+.2f} bps/day."
        ),
        (
            "- Half-hour option reversal correlation (validation/final): "
            f"{reversal['validation']['robust']['correlation']:+.4f} / "
            f"{reversal['final_week']['robust']['correlation']:+.4f}."
        ),
        (
            "- Smile-curvature correlation (validation/final): "
            f"{curvature['validation']['robust']['correlation']:+.4f} / "
            f"{curvature['final_week']['robust']['correlation']:+.4f}; rank correlation: "
            f"{curvature['validation']['robust']['spearman']:+.4f} / "
            f"{curvature['final_week']['robust']['spearman']:+.4f}."
        ),
        "",
        "## Decision",
        "",
        (
            "- The quarter-hour timing structure is the only interesting index result, but "
            "its one-minute turnover makes the observed gross edge uneconomic at the stated "
            "cost hurdle."
        ),
        (
            "- Low-volatility gating reduced losses versus the ungated comparator, but even "
            "the best active candidate lost in validation and the final week; cash won."
        ),
        (
            "- The option reversal changes sign across splits, and curvature changes sign "
            "between linear and rank statistics. Neither is stable enough to promote."
        ),
        "",
        "## Interpretation boundary",
        "",
        (
            "Index P&L is a NIFTY return proxy, not a futures fill simulation. Option "
            "results are predictive diagnostics only: the archive rolls ATM-relative "
            "buckets and lacks fixed strikes, expiries, bid/ask, IV, and open interest. "
            "They must not be read as executable option P&L."
        ),
        "",
        (
            "The option headline uses a fixed 10% jump filter. Raw and rank correlations "
            "remain in the JSON."
        ),
        "",
        "## Paper trail",
        "",
        "- Quarter-hour phase effects: https://arxiv.org/abs/2607.09426",
        "- Regime-aware return prediction: https://arxiv.org/abs/2606.09478",
        (
            "- Intraday option reversals: "
            "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5081696"
        ),
        (
            "- Intraday volatility-smile geometry: "
            "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5893362"
        ),
        "",
        (
            "Full shifted-clock placebos, participation/gating candidates, audit counts, "
            "and split statistics are in `paper_alpha_scan.json`."
        ),
        "",
    ]
    (args.output / "PAPER_ALPHA_SCAN.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"quarter_hour": quarter, "volatility_gated": gated}, indent=2))


if __name__ == "__main__":
    main()
