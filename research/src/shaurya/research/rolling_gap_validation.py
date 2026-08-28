"""Historical monthly pseudo-live validation for three frozen gap-related candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from shaurya.research.intraday_alpha_tournament import (
    daily_pnl,
    strategy_metric,
)
from shaurya.research.parallel_alpha_tournament import holm_passes

START_MONTH = pd.Period("2022-01", freq="M")
TRAINING_SESSIONS = 252
COSTS_BPS = (0.0, 1.0, 2.0, 6.0)
PRIMARY_COST_BPS = 1.0
PARTICIPATION = 0.10
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class MonthlyCalibration:
    month: str
    training_start: str
    training_end: str
    training_sessions: int
    large_gap_cutoff: float
    formula_threshold: float


def _rank_reference(values: pd.Series) -> FloatArray:
    finite = values.to_numpy(float)
    finite = np.sort(finite[np.isfinite(finite)])
    if len(finite) == 0:
        raise ValueError("rank reference is empty")
    return finite


def _centered_rank(values: pd.Series, reference: FloatArray) -> FloatArray:
    raw = values.to_numpy(float)
    result = np.zeros(len(raw), dtype=float)
    finite = np.isfinite(raw)
    result[finite] = (
        2.0 * np.searchsorted(reference, raw[finite], side="right") / len(reference) - 1.0
    )
    return np.clip(result, -1.0, 1.0)


def rolling_gap_positions(
    panel: pd.DataFrame,
    *,
    start_month: pd.Period = START_MONTH,
    training_sessions: int = TRAINING_SESSIONS,
) -> tuple[dict[str, FloatArray], list[MonthlyCalibration]]:
    """Generate month-ahead positions using only preceding sessions for calibration."""
    required = {"date", "elapsed", "overnight_gap", "rv_30"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"panel is missing columns: {sorted(missing)}")
    month = panel["date"].dt.to_period("M")
    candidates: dict[str, FloatArray] = {
        "gap_continuation": np.zeros(len(panel), dtype=float),
        "large_gap_continuation_first_hour": np.zeros(len(panel), dtype=float),
        "gap_x_volatility_formula": np.zeros(len(panel), dtype=float),
    }
    calibrations: list[MonthlyCalibration] = []
    for test_month in sorted(month[month >= start_month].unique()):
        test_mask = (month == test_month).to_numpy()
        month_start = test_month.start_time
        prior_dates = panel.loc[panel["date"] < month_start, "date"].drop_duplicates()
        selected_dates = prior_dates.tail(training_sessions)
        if len(selected_dates) < min(120, training_sessions):
            continue
        train = panel[panel["date"].isin(selected_dates)]
        test = panel.loc[test_mask]

        daily_gap = train.groupby("date", sort=True)["overnight_gap"].first().abs()
        gap_cutoff = float(daily_gap.quantile(2 / 3))
        gap_reference = _rank_reference(train["overnight_gap"])
        vol_reference = _rank_reference(train["rv_30"])
        train_score = _centered_rank(train["overnight_gap"], gap_reference) * _centered_rank(
            train["rv_30"], vol_reference
        )
        formula_threshold = float(np.quantile(np.abs(train_score), 1.0 - PARTICIPATION))

        gap_direction = np.sign(test["overnight_gap"].fillna(0.0).to_numpy(float))
        candidates["gap_continuation"][test_mask] = gap_direction
        large_gap = test["overnight_gap"].abs().to_numpy(float) > gap_cutoff
        first_hour = test["elapsed"].to_numpy(float) <= 60.0
        candidates["large_gap_continuation_first_hour"][test_mask] = np.where(
            large_gap & first_hour, gap_direction, 0.0
        )
        test_score = _centered_rank(test["overnight_gap"], gap_reference) * _centered_rank(
            test["rv_30"], vol_reference
        )
        candidates["gap_x_volatility_formula"][test_mask] = np.where(
            np.abs(test_score) >= formula_threshold, np.sign(test_score), 0.0
        )
        calibrations.append(
            MonthlyCalibration(
                month=str(test_month),
                training_start=selected_dates.min().date().isoformat(),
                training_end=selected_dates.max().date().isoformat(),
                training_sessions=len(selected_dates),
                large_gap_cutoff=gap_cutoff,
                formula_threshold=formula_threshold,
            )
        )
    return candidates, calibrations


def run_rolling_gap_validation(panel: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    positions, calibrations = rolling_gap_positions(panel)
    evaluated_months = {calibration.month for calibration in calibrations}
    month = panel["date"].dt.to_period("M").astype(str)
    evaluation_mask = month.isin(evaluated_months).to_numpy()
    evaluation = panel.loc[evaluation_mask]
    results: dict[str, Any] = {}
    monthly_rows: list[dict[str, Any]] = []
    primary_p_values: dict[str, float] = {}
    for name, full_position in positions.items():
        position = full_position[evaluation_mask]
        costs: dict[str, Any] = {}
        daily_by_cost: dict[float, pd.DataFrame] = {}
        for cost in COSTS_BPS:
            daily = daily_pnl(evaluation, position, cost)
            daily_by_cost[cost] = daily
            costs[f"cost_{cost:g}bps"] = asdict(strategy_metric(daily))
            daily = daily.assign(month=daily["date"].dt.to_period("M").astype(str))
            for test_month, group in daily.groupby("month", sort=True):
                monthly_rows.append(
                    {
                        "candidate": name,
                        "month": test_month,
                        "cost_bps": cost,
                        "mean_daily_bps": float(group["pnl_bps"].mean()),
                        "total_bps": float(group["pnl_bps"].sum()),
                        "round_trips": float(group["turnover"].sum() / 2.0),
                    }
                )
        primary_daily = daily_by_cost[PRIMARY_COST_BPS]
        yearly = primary_daily.assign(year=primary_daily["date"].dt.year).groupby("year")
        year_metrics = {
            str(year): asdict(strategy_metric(group.drop(columns="year"))) for year, group in yearly
        }
        monthly_primary = [
            row
            for row in monthly_rows
            if row["candidate"] == name and row["cost_bps"] == PRIMARY_COST_BPS
        ]
        positive_month_rate = float(np.mean([row["mean_daily_bps"] > 0 for row in monthly_primary]))
        results[name] = {
            "costs": costs,
            "yearly_at_1bps": year_metrics,
            "positive_month_rate_at_1bps": positive_month_rate,
            "months": len(monthly_primary),
        }
        primary_p_values[name] = costs["cost_1bps"]["one_sided_p"]

    corrected = holm_passes(primary_p_values)
    stable = sorted(
        name
        for name in corrected
        if results[name]["costs"]["cost_1bps"]["mean_daily_bps"] > 0
        and results[name]["positive_month_rate_at_1bps"] >= 0.55
        and sum(metric["mean_daily_bps"] > 0 for metric in results[name]["yearly_at_1bps"].values())
        >= 4
    )
    payload = {
        "protocol": {
            "test_months": f"{min(evaluated_months)} through {max(evaluated_months)}",
            "calibration": "trailing 252 sessions before each test month",
            "candidates": list(positions),
            "primary_round_trip_cost_bps": PRIMARY_COST_BPS,
            "cost_ladder_bps": COSTS_BPS,
            "multiple_testing": "Holm one-sided correction across three frozen candidates",
            "status": "retrospective pseudo-live stability test; not a new holdout",
        },
        "calibrations": [asdict(calibration) for calibration in calibrations],
        "candidates": results,
        "summary": {
            "holm_passes": sorted(corrected),
            "stable_candidates": stable,
            "verdict": (
                "one or more candidates passed retrospective stability gates"
                if stable
                else "no candidate passed all retrospective stability gates"
            ),
        },
    }
    return payload, pd.DataFrame(monthly_rows)
