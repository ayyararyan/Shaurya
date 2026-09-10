"""Select/audit an RV-V2 q threshold from prepared 10:00 butterfly candidates.

Input rows must already be causal 10:00 observations and contain the frozen RV-V2 q score.
This script deliberately does not refit the RV model or reconstruct changing option contracts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_Q_GRID = tuple(np.round(np.arange(0.40, 1.201, 0.025), 3))
DEFAULT_COST_POINTS = 2.0
FROZEN_Q = 0.825
LEGACY_RR400 = 0.0270810062


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidates", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--cost-points", type=float, default=DEFAULT_COST_POINTS)
    return p


def selected_trades(
    rows: pd.DataFrame,
    *,
    q_threshold: float,
    cost_points: float,
    rr400_threshold: float | None = None,
) -> pd.DataFrame:
    eligible = rows[rows["q_new"] < q_threshold].copy()
    if rr400_threshold is not None:
        eligible = eligible[
            eligible["essvi_rr400"].notna()
            & (eligible["essvi_rr400"] <= rr400_threshold)
        ]
    eligible = (
        eligible.sort_values(["expiry", "date"])
        .groupby("expiry", as_index=False)
        .first()
    )
    eligible["net_pnl"] = eligible["gross_pnl"] - cost_points
    eligible["net_R"] = eligible["net_pnl"] / (eligible["maxloss"] + cost_points)
    return eligible


def metrics(rows: pd.DataFrame) -> dict[str, float | int | None]:
    if rows.empty:
        return {
            "n": 0,
            "total_pnl": 0.0,
            "mean_pnl": None,
            "win_rate": None,
            "mean_R": None,
        }
    return {
        "n": int(len(rows)),
        "total_pnl": float(rows["net_pnl"].sum()),
        "mean_pnl": float(rows["net_pnl"].mean()),
        "win_rate": float((rows["net_pnl"] > 0).mean()),
        "mean_R": float(rows["net_R"].mean()),
    }


def main() -> int:
    args = parser().parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    rows = pd.read_csv(args.candidates, parse_dates=["date", "expiry"])
    required = {"date", "expiry", "q_new", "gross_pnl", "maxloss", "essvi_rr400"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise SystemExit(f"missing columns: {', '.join(missing)}")

    # Reproduce the original development-only selection first. It is diagnostic: the
    # resulting 0.75 failed later periods and is not the frozen operational threshold.
    grid_rows: list[dict[str, object]] = []
    dev = rows[rows["date"].dt.year.isin([2023, 2024])]
    for q in DEFAULT_Q_GRID:
        trade_rows = selected_trades(
            dev, q_threshold=q, cost_points=args.cost_points
        )
        grid_rows.append({"q": q, **metrics(trade_rows)})
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(out / "development_q_grid.csv", index=False)
    eligible = grid[grid["n"] >= 25].sort_values(["mean_R", "q"], ascending=[False, True])
    dev_only_q = float(eligible.iloc[0]["q"])

    # Frozen robustness audit. 0.825 was chosen adaptively after the dev-only optimum
    # failed validation; this table does not manufacture a new untouched holdout.
    stable_rows: list[dict[str, object]] = []
    for q in (0.80, 0.825, 0.85):
        yearly: list[float] = []
        for year in (2023, 2024, 2025):
            m = metrics(
                selected_trades(
                    rows[rows["date"].dt.year == year],
                    q_threshold=q,
                    cost_points=args.cost_points,
                )
            )
            stable_rows.append({"q": q, "sample": str(year), **m})
            if m["mean_R"] is not None:
                yearly.append(float(m["mean_R"]))
        stable_rows.append(
            {
                "q": q,
                "sample": "min_2023_25",
                "n": None,
                "total_pnl": None,
                "mean_pnl": None,
                "win_rate": None,
                "mean_R": min(yearly),
            }
        )
    pd.DataFrame(stable_rows).to_csv(out / "stable_band.csv", index=False)

    result = {
        "development_only_q": dev_only_q,
        "development_only_q_status": "rejected_after_validation_instability",
        "frozen_operational_q": FROZEN_Q,
        "sensitivity_band": [0.80, 0.85],
        "q_definition": "forecast integrated realized variance / eSSVI theta",
        "rule": "q < 0.825",
        "rr400_master_veto": False,
        "legacy_rr400_reference": LEGACY_RR400,
        "selection_status": "adaptive robustness calibration; prospectively frozen",
    }
    (out / "selection.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
