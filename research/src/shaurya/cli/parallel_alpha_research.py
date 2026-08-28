"""Run the parallel recent-alpha families under one shared evaluation protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from shaurya.research.formula_alpha_mining import mine_formula_alphas
from shaurya.research.intraday_alpha_tournament import build_tournament_panel
from shaurya.research.parallel_alpha_tournament import (
    baseline_candidates,
    evaluate_parallel_candidates,
)
from shaurya.research.regime_jump_alpha import regime_jump_positions
from shaurya.research.sparse_phase_alpha import run_sparse_phase_scan


def _run(index_zip: Path) -> dict[str, Any]:
    panel, audit = build_tournament_panel(index_zip)
    candidates, families = baseline_candidates(panel)

    regime, calibration = regime_jump_positions(
        panel, calibration_end=panel.loc[panel["date"] <= "2026-06-30", "date"].max()
    )
    for name, position in regime.items():
        registered = f"regime_jump__{name}"
        candidates[registered] = np.asarray(position, dtype=float)
        families[registered] = "regime_jump"

    formula = mine_formula_alphas(panel)
    for name in formula.validation_candidates:
        registered = f"formula__{name}"
        candidates[registered] = np.asarray(formula.candidates[name].position, dtype=float)
        families[registered] = "formula_mining"

    tournament = evaluate_parallel_candidates(panel, candidates, families)
    return {
        "data_audit": audit,
        "shared_tournament": tournament,
        "sparse_phase": run_sparse_phase_scan(index_zip),
        "formula_discovery": formula.metadata,
        "regime_calibration": {
            "calibration_end": calibration.calibration_end,
            "jump_z_threshold": calibration.jump_z_threshold,
            "trend_strength_tercile": calibration.trend_strength_tercile,
            "absolute_gap_terciles": calibration.absolute_gap_terciles,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = _run(args.index_zip)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "parallel_alpha_research.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    shared = payload["shared_tournament"]
    summary = shared["summary"]
    registry = shared["registry"]
    primary = "cost_1bps"
    lines = [
        "# Parallel alpha research tournament",
        "",
        f"**Verdict: {summary['verdict']}.**",
        "",
        f"Candidates in shared correction: {summary['candidate_count']}",
        f"Families: {', '.join(summary['families'])}",
        f"Holm validation passes: {', '.join(summary['holm_validation_passes']) or 'none'}",
        f"Final survivors: {', '.join(summary['final_survivors']) or 'none'}",
        "",
        "## Shared validation leaders",
        "",
        "| candidate | family | net 1bp/day | Sharpe | p-value | round trips/day |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name in summary["top_validation_candidates"]:
        value = registry[name]
        metric = value["results"]["validation"][primary]
        lines.append(
            f"| {name} | {value['family']} | {metric['mean_daily_bps']:+.3f} | "
            f"{metric['annualized_sharpe']:+.2f} | {metric['one_sided_p']:.4f} | "
            f"{metric['average_round_trips_per_day']:.2f} |"
        )
    sparse = payload["sparse_phase"]["selection"]
    formula = payload["formula_discovery"]
    lines.extend(
        [
            "",
            "## Separate-horizon tracks",
            "",
            (
                f"- Sparse quarter-hour grid: 144 candidates; selected `{sparse['selected']}`. "
                f"Best active was `{sparse['best_active']}` at "
                f"{sparse['best_active_validation']['net_mean_bps_per_day']:+.3f} net bps/day "
                "using the 6bp hurdle."
            ),
            (
                f"- Formula grammar: {formula['protocol']['formulas_generated']} formulas; "
                f"selected `{formula['selected_candidate'] or 'cash'}` after Holm correction "
                "at the 6bp hurdle."
            ),
            "",
            "The final week is accessed only for strategies that pass corrected validation. "
            "Index returns remain a proxy because futures fills and basis are unavailable.",
            "",
        ]
    )
    (args.output / "PARALLEL_ALPHA_RESEARCH.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
