"""Profit-oriented intraday alpha tournament on one-minute NIFTY index bars.

The index is not directly tradable, so returns are a futures-direction proxy.  The primary cost
hurdle is six basis points per round trip and results never claim executable option P&L.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from shaurya.research.intraday_volatility import load_clean_index

PRIMARY_ROUND_TRIP_COST_BPS = 6.0
ROUND_TRIP_COSTS_BPS = (0.0, 2.0, 6.0, 10.0)
SEED = 20260826
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class StrategyMetric:
    days: int
    mean_daily_bps: float
    annualized_sharpe: float
    t_statistic: float
    one_sided_p: float
    positive_day_rate: float
    worst_day_bps: float
    max_drawdown_bps: float
    average_round_trips_per_day: float


def _session_features(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("minute").copy()
    log_close = np.log(group["close"])
    group["ret_1"] = log_close.diff()
    for window in (5, 15, 30, 60):
        group[f"ret_{window}"] = log_close.diff(window)
        group[f"rv_{window}"] = np.sqrt(
            group["ret_1"].pow(2).rolling(window, min_periods=max(2, window // 3)).sum()
        )
        group[f"prior_high_{window}"] = group["high"].shift(1).rolling(window).max()
        group[f"prior_low_{window}"] = group["low"].shift(1).rolling(window).min()
    group["session_return"] = np.log(group["close"] / group["open"].iloc[0])
    group["opening_high"] = group["high"].iloc[:15].max()
    group["opening_low"] = group["low"].iloc[:15].min()
    group["forward_return_bps"] = log_close.shift(-5).sub(log_close).mul(10_000.0)
    return group


def build_tournament_panel(index_zip: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    index, audit = load_clean_index(index_zip)
    daily = index.groupby("date", sort=True).agg(
        day_open=("open", "first"), day_close=("close", "last")
    )
    daily["prior_close"] = daily["day_close"].shift(1)
    daily["overnight_gap"] = np.log(daily["day_open"] / daily["prior_close"])
    panel = (
        index.groupby("date", group_keys=False, sort=True)
        .apply(_session_features, include_groups=False)
        .reset_index(drop=True)
    )
    panel["date"] = panel["datetime"].dt.normalize()
    panel = panel.merge(daily[["overnight_gap"]], left_on="date", right_index=True, how="left")
    panel["elapsed"] = panel["minute"] - (9 * 60 + 15)
    panel["elapsed_fraction"] = panel["elapsed"] / 374.0
    panel["time_sin"] = np.sin(2 * np.pi * panel["elapsed_fraction"])
    panel["time_cos"] = np.cos(2 * np.pi * panel["elapsed_fraction"])
    panel["day_of_week"] = panel["date"].dt.dayofweek
    for day in range(5):
        panel[f"dow_{day}"] = (panel["day_of_week"] == day).astype(float)
    panel["tuesday_regime"] = (panel["date"] >= pd.Timestamp("2025-09-01")).astype(float)
    panel = panel[
        (panel["elapsed"] >= 5)
        & (panel["elapsed"] % 5 == 0)
        & (panel["minute"] <= 15 * 60 + 24)
    ].copy()
    panel = panel.dropna(subset=["forward_return_bps", "overnight_gap"]).reset_index(drop=True)
    audit.update(
        {
            "decision_rows": len(panel),
            "decision_sessions": int(panel["date"].nunique()),
            "first_decision": panel["datetime"].min().isoformat(),
            "last_decision": panel["datetime"].max().isoformat(),
        }
    )
    return panel, audit


def _signed(values: pd.Series) -> pd.Series:
    return np.sign(values).fillna(0.0).astype(float)


def rule_positions(panel: pd.DataFrame) -> dict[str, FloatArray]:
    positions: dict[str, FloatArray] = {}
    for window in (5, 15, 30, 60):
        direction = _signed(panel[f"ret_{window}"])
        positions[f"momentum_{window}m"] = direction.to_numpy()
        positions[f"reversal_{window}m"] = (-direction).to_numpy()
    positions["session_momentum"] = _signed(panel["session_return"]).to_numpy()
    positions["session_reversal"] = -positions["session_momentum"]
    positions["gap_continuation"] = _signed(panel["overnight_gap"]).to_numpy()
    positions["gap_fade"] = -positions["gap_continuation"]
    for window in (15, 30, 60):
        breakout = np.where(
            panel["close"] > panel[f"prior_high_{window}"],
            1.0,
            np.where(panel["close"] < panel[f"prior_low_{window}"], -1.0, 0.0),
        )
        positions[f"breakout_{window}m"] = breakout
        positions[f"breakout_fade_{window}m"] = -breakout
    after_opening_range = panel["elapsed"] >= 15
    opening_break = np.where(
        after_opening_range & (panel["close"] > panel["opening_high"]),
        1.0,
        np.where(
            after_opening_range & (panel["close"] < panel["opening_low"]), -1.0, 0.0
        ),
    )
    positions["opening_range_breakout"] = opening_break
    positions["opening_range_fade"] = -opening_break
    return positions


MODEL_FEATURES = [
    "ret_1",
    "ret_5",
    "ret_15",
    "ret_30",
    "ret_60",
    "rv_5",
    "rv_15",
    "rv_30",
    "rv_60",
    "session_return",
    "overnight_gap",
    "elapsed_fraction",
    "time_sin",
    "time_cos",
    "dow_0",
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
    "tuesday_regime",
]


def _models() -> dict[str, Any]:
    ridge = TransformedTargetRegressor(
        regressor=Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
                ("model", Ridge(alpha=10.0)),
            ]
        ),
        func=np.arcsinh,
        inverse_func=np.sinh,
        check_inverse=False,
    )
    histogram = TransformedTargetRegressor(
        regressor=Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        learning_rate=0.05,
                        max_iter=140,
                        max_leaf_nodes=15,
                        min_samples_leaf=100,
                        l2_regularization=3.0,
                        random_state=SEED,
                    ),
                ),
            ]
        ),
        func=np.arcsinh,
        inverse_func=np.sinh,
        check_inverse=False,
    )
    return {"ridge_return": ridge, "hist_return": histogram}


def _turnover_by_row(frame: pd.DataFrame, positions: FloatArray) -> FloatArray:
    result = np.zeros(len(frame), dtype=float)
    for _, indices in frame.groupby("date", sort=False).indices.items():
        loc = np.asarray(indices, dtype=int)
        day_position = positions[loc]
        result[loc[0]] = abs(day_position[0])
        if len(loc) > 1:
            result[loc[1:]] = np.abs(np.diff(day_position))
        result[loc[-1]] += abs(day_position[-1])
    return result


def daily_pnl(
    frame: pd.DataFrame, positions: FloatArray, round_trip_cost_bps: float
) -> pd.DataFrame:
    turnover = _turnover_by_row(frame, positions)
    row_pnl = positions * frame["forward_return_bps"].to_numpy(float)
    row_pnl -= turnover * round_trip_cost_bps / 2.0
    result = pd.DataFrame({"date": frame["date"], "pnl_bps": row_pnl, "turnover": turnover})
    return result.groupby("date", sort=True).sum().reset_index()


def strategy_metric(daily: pd.DataFrame) -> StrategyMetric:
    pnl = daily["pnl_bps"].to_numpy(float)
    mean = float(pnl.mean())
    standard_deviation = float(pnl.std(ddof=1))
    t_statistic = mean / (standard_deviation / np.sqrt(len(pnl))) if standard_deviation else 0.0
    cumulative = np.cumsum(pnl)
    drawdown = cumulative - np.maximum.accumulate(np.concatenate(([0.0], cumulative)))[1:]
    return StrategyMetric(
        days=len(pnl),
        mean_daily_bps=mean,
        annualized_sharpe=(mean / standard_deviation * np.sqrt(252) if standard_deviation else 0.0),
        t_statistic=t_statistic,
        one_sided_p=float(stats.t.sf(t_statistic, len(pnl) - 1)),
        positive_day_rate=float((pnl > 0).mean()),
        worst_day_bps=float(pnl.min()),
        max_drawdown_bps=float(drawdown.min()),
        average_round_trips_per_day=float(daily["turnover"].mean() / 2.0),
    )


def _holm_passes(p_values: dict[str, float], alpha: float = 0.05) -> set[str]:
    ordered = sorted(p_values, key=p_values.get)  # type: ignore[arg-type]
    passed: set[str] = set()
    total = len(ordered)
    for rank, name in enumerate(ordered):
        if p_values[name] <= alpha / (total - rank):
            passed.add(name)
        else:
            break
    return passed


def run_tournament(panel: pd.DataFrame) -> dict[str, Any]:
    development = panel[panel["date"].dt.year <= 2023]
    selection = panel[panel["date"].dt.year == 2024]
    frozen_train = panel[panel["date"].dt.year <= 2024]
    evaluations = {
        "selection_2024": selection,
        "holdout_2025": panel[panel["date"].dt.year == 2025],
        "current_2026": panel[panel["date"].dt.year == 2026],
        "tuesday_regime": panel[panel["date"] >= pd.Timestamp("2025-09-01")],
    }
    all_positions = rule_positions(panel)

    # Model family and participation rate are chosen on 2024 only, then frozen and refit through
    # 2024. Thresholds are derived from training predictions, never evaluation predictions.
    model_selection: dict[str, Any] = {}
    for model_name, model in _models().items():
        model.fit(development[MODEL_FEATURES], development["forward_return_bps"])
        predicted = np.asarray(model.predict(selection[MODEL_FEATURES]), dtype=float)
        trials: dict[str, float] = {}
        for participation in (0.10, 0.25, 0.50, 1.00):
            threshold = float(np.quantile(np.abs(predicted), 1.0 - participation))
            position = np.where(np.abs(predicted) >= threshold, np.sign(predicted), 0.0)
            trials[str(participation)] = strategy_metric(
                daily_pnl(selection, position, PRIMARY_ROUND_TRIP_COST_BPS)
            ).mean_daily_bps
        chosen = max(trials, key=trials.get)  # type: ignore[arg-type]
        model_selection[model_name] = {"participation": float(chosen), "selection_trials": trials}

        frozen_model = _models()[model_name]
        frozen_model.fit(frozen_train[MODEL_FEATURES], frozen_train["forward_return_bps"])
        training_prediction = np.asarray(
            frozen_model.predict(frozen_train[MODEL_FEATURES]), dtype=float
        )
        threshold = float(
            np.quantile(np.abs(training_prediction), 1.0 - float(chosen))
        )
        full_prediction = np.asarray(frozen_model.predict(panel[MODEL_FEATURES]), dtype=float)
        all_positions[model_name] = np.where(
            np.abs(full_prediction) >= threshold, np.sign(full_prediction), 0.0
        )
        model_selection[model_name]["frozen_threshold_bps"] = threshold

    results: dict[str, Any] = {}
    for strategy, full_position in all_positions.items():
        strategy_result: dict[str, Any] = {}
        for split_name, evaluation in evaluations.items():
            loc = evaluation.index.to_numpy(int)
            split_result: dict[str, Any] = {}
            for cost in ROUND_TRIP_COSTS_BPS:
                metric = strategy_metric(daily_pnl(evaluation, full_position[loc], cost))
                split_result[f"cost_{cost:g}bps"] = asdict(metric)
            strategy_result[split_name] = split_result
        results[strategy] = strategy_result

    p_values = {
        name: value["holdout_2025"]["cost_6bps"]["one_sided_p"]
        for name, value in results.items()
    }
    holm = _holm_passes(p_values)
    survivors = []
    for name, value in results.items():
        holdout = value["holdout_2025"]["cost_6bps"]
        current = value["current_2026"]["cost_6bps"]
        if name in holm and holdout["mean_daily_bps"] > 0 and current["mean_daily_bps"] > 0:
            survivors.append(name)
    survivors.sort(
        key=lambda name: results[name]["current_2026"]["cost_6bps"]["annualized_sharpe"],
        reverse=True,
    )
    return {
        "protocol": {
            "decision_interval": "five minutes using completed one-minute bars",
            "return_proxy": "NIFTY index; futures execution/basis unavailable",
            "development": "2021-2023",
            "model_and_participation_selection": "2024",
            "untouched_evaluations": ["2025", "2026"],
            "primary_round_trip_cost_bps": PRIMARY_ROUND_TRIP_COST_BPS,
            "multiple_testing": "Holm one-sided familywise correction on 2025 daily P&L",
        },
        "model_selection": model_selection,
        "strategies": results,
        "summary": {
            "strategies_tested": len(results),
            "holm_significant_2025": sorted(holm),
            "survivors": survivors,
            "verdict": (
                "one or more directional proxies survived"
                if survivors
                else "no directional proxy survived costs, correction, and both holdouts"
            ),
        },
    }
