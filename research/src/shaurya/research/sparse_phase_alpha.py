"""Sparse, cost-aware quarter-hour alpha research.

Candidate selection ends on 2026-08-14.  Only the frozen winner is subsequently
evaluated on 2026-08-17 through 2026-08-21.  Index returns are a futures proxy,
not executable index P&L.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from shaurya.research.intraday_volatility import load_clean_index

DISCOVERY_START = pd.Timestamp("2025-09-01")
DISCOVERY_END = pd.Timestamp("2026-06-30")
VALIDATION_START = pd.Timestamp("2026-07-01")
VALIDATION_END = pd.Timestamp("2026-08-14")
FINAL_START = pd.Timestamp("2026-08-17")
FINAL_END = pd.Timestamp("2026-08-21")
HORIZONS = (1, 5, 10, 15)
PARTICIPATION = (0.05, 0.10, 0.25)
COOLDOWNS = (0, 15, 30)
TIME_BUCKETS = ("all", "morning", "midday", "afternoon")
COSTS_BPS = (0.0, 1.0, 2.0, 6.0)
PRIMARY_COST_BPS = 6.0
FloatArray = npt.NDArray[np.float64]


FEATURES = [
    *[f"same_phase_lag_{lag}" for lag in range(1, 13)],
    "prior_ret_1",
    "prior_ret_5",
    "prior_ret_15",
    "prior_rv_15",
    "elapsed_fraction",
    "time_sin",
    "time_cos",
    *[f"dow_{day}" for day in range(5)],
]


@dataclass(frozen=True)
class SparseMetric:
    days: int
    trades: int
    participation: float
    average_trades_per_day: float
    gross_mean_bps_per_day: float
    net_mean_bps_per_day: float
    annualized_sharpe: float
    positive_day_rate: float
    worst_day_bps: float
    max_drawdown_bps: float


@dataclass(frozen=True)
class Candidate:
    horizon: int
    participation: float
    cooldown_minutes: int
    time_bucket: str

    @property
    def name(self) -> str:
        participation = int(round(self.participation * 100))
        return (
            f"phase_h{self.horizon}_p{participation}_cd{self.cooldown_minutes}_{self.time_bucket}"
        )


def _prior_log_return(values: pd.Series, lag: int) -> pd.Series:
    logged = np.log(values)
    return (logged.shift(1) - logged.shift(lag + 1)) * 10_000.0


def build_sparse_phase_panel(index_zip: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return phase-zero decisions whose features are known at each bar's open."""
    index, audit = load_clean_index(index_zip)
    index = index[index["date"] >= DISCOVERY_START].sort_values("datetime").copy()
    by_day = index.groupby("date", sort=False)
    index["open_close_bps"] = np.log(index["close"] / index["open"]) * 10_000.0
    index["prior_ret_1"] = by_day["close"].transform(lambda values: _prior_log_return(values, 1))
    index["prior_ret_5"] = by_day["close"].transform(lambda values: _prior_log_return(values, 5))
    index["prior_ret_15"] = by_day["close"].transform(lambda values: _prior_log_return(values, 15))
    index["prior_rv_15"] = by_day["open_close_bps"].transform(
        lambda values: values.shift(1).pow(2).rolling(15, min_periods=10).sum().pow(0.5)
    )
    index["phase"] = index["minute"] % 15
    for lag in range(1, 13):
        index[f"same_phase_lag_{lag}"] = index.groupby(["date", "phase"], sort=False)[
            "open_close_bps"
        ].shift(lag)
    for horizon in HORIZONS:
        index[f"target_{horizon}m_bps"] = by_day["close"].transform(
            lambda values, steps=horizon: (
                (np.log(values.shift(-(steps - 1))) - np.log(index.loc[values.index, "open"]))
                * 10_000.0
            )
        )
    index["elapsed"] = index["minute"] - (9 * 60 + 15)
    index["elapsed_fraction"] = index["elapsed"] / 374.0
    index["time_sin"] = np.sin(2.0 * np.pi * index["elapsed_fraction"])
    index["time_cos"] = np.cos(2.0 * np.pi * index["elapsed_fraction"])
    for day in range(5):
        index[f"dow_{day}"] = (index["date"].dt.dayofweek == day).astype(float)
    panel = index[index["phase"] == 0].copy().reset_index(drop=True)
    audit = {
        **audit,
        "phase_decisions": len(panel),
        "phase_sessions": int(panel["date"].nunique()),
        "first_phase_decision": panel["datetime"].min().isoformat(),
        "last_phase_decision": panel["datetime"].max().isoformat(),
    }
    return panel, audit


def _model() -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=20.0)),
        ]
    )


def walk_forward_predictions(
    panel: pd.DataFrame,
    horizon: int,
    prediction_start: pd.Timestamp,
    prediction_end: pd.Timestamp,
) -> pd.DataFrame:
    """Predict monthly blocks using only observations strictly before each block."""
    if horizon not in HORIZONS:
        raise ValueError(f"unsupported horizon: {horizon}")
    target = f"target_{horizon}m_bps"
    requested = panel[panel["date"].between(prediction_start, prediction_end)].copy()
    outputs: list[pd.DataFrame] = []
    for period in requested["date"].dt.to_period("M").drop_duplicates().sort_values():
        block = requested[requested["date"].dt.to_period("M") == period].copy()
        block_start = period.start_time
        train = panel[
            (panel["date"] >= DISCOVERY_START)
            & (panel["date"] < block_start)
            & panel[target].notna()
        ].copy()
        if train.empty:
            raise ValueError(f"no training observations before {block_start.date()}")
        fitted = _model().fit(train[FEATURES], train[target])
        block["prediction_bps"] = np.asarray(fitted.predict(block[FEATURES]), dtype=float)
        fitted_train = np.abs(np.asarray(fitted.predict(train[FEATURES]), dtype=float))
        for participation in PARTICIPATION:
            block[f"threshold_p{int(participation * 100)}"] = float(
                np.quantile(fitted_train, 1.0 - participation)
            )
        block["trained_through"] = train["date"].max()
        outputs.append(block)
    if not outputs:
        return requested.assign(prediction_bps=np.nan)
    return pd.concat(outputs).sort_values("datetime").reset_index(drop=True)


def _time_mask(frame: pd.DataFrame, bucket: str) -> npt.NDArray[np.bool_]:
    minute = frame["minute"].to_numpy(int)
    if bucket == "all":
        return np.ones(len(frame), dtype=bool)
    if bucket == "morning":
        return np.asarray(minute <= 11 * 60, dtype=bool)
    if bucket == "midday":
        return np.asarray((minute > 11 * 60) & (minute <= 13 * 60 + 30), dtype=bool)
    if bucket == "afternoon":
        return np.asarray(minute > 13 * 60 + 30, dtype=bool)
    raise ValueError(f"unknown time bucket: {bucket}")


def candidate_positions(frame: pd.DataFrame, candidate: Candidate) -> FloatArray:
    """Apply a discovery-derived threshold and causal per-session cooldown."""
    threshold = frame[f"threshold_p{int(candidate.participation * 100)}"].to_numpy(float)
    prediction = frame["prediction_bps"].to_numpy(float)
    eligible = (np.abs(prediction) >= threshold) & _time_mask(frame, candidate.time_bucket)
    positions = np.zeros(len(frame), dtype=float)
    for indices in frame.groupby("date", sort=False).indices.values():
        last_trade_minute = -10_000
        for location in np.asarray(indices, dtype=int):
            minute = int(frame.iloc[location]["minute"])
            if eligible[location] and minute - last_trade_minute >= candidate.cooldown_minutes:
                positions[location] = float(np.sign(prediction[location]))
                last_trade_minute = minute
    return positions


def evaluate_candidate(
    frame: pd.DataFrame,
    candidate: Candidate,
    round_trip_cost_bps: float = PRIMARY_COST_BPS,
) -> SparseMetric:
    positions = candidate_positions(frame, candidate)
    target = frame[f"target_{candidate.horizon}m_bps"].to_numpy(float)
    valid = np.isfinite(target)
    gross = np.where(valid, positions * target, 0.0)
    trade = (positions != 0.0) & valid
    net = gross - trade.astype(float) * round_trip_cost_bps
    daily = (
        pd.DataFrame(
            {"date": frame["date"], "gross": gross, "net": net, "trades": trade.astype(int)}
        )
        .groupby("date", sort=True)
        .sum()
    )
    pnl = daily["net"].to_numpy(float)
    mean = float(pnl.mean()) if len(pnl) else 0.0
    standard_deviation = float(pnl.std(ddof=1)) if len(pnl) > 1 else 0.0
    cumulative = np.cumsum(pnl)
    high_water = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))[1:]
    return SparseMetric(
        days=len(daily),
        trades=int(daily["trades"].sum()),
        participation=float(trade.mean()) if len(trade) else 0.0,
        average_trades_per_day=float(daily["trades"].mean()) if len(daily) else 0.0,
        gross_mean_bps_per_day=float(daily["gross"].mean()) if len(daily) else 0.0,
        net_mean_bps_per_day=mean,
        annualized_sharpe=(mean / standard_deviation * np.sqrt(252) if standard_deviation else 0.0),
        positive_day_rate=float((pnl > 0).mean()) if len(pnl) else 0.0,
        worst_day_bps=float(pnl.min()) if len(pnl) else 0.0,
        max_drawdown_bps=float((cumulative - high_water).min()) if len(pnl) else 0.0,
    )


def candidate_grid() -> list[Candidate]:
    return [
        Candidate(horizon, participation, cooldown, bucket)
        for horizon in HORIZONS
        for participation in PARTICIPATION
        for cooldown in COOLDOWNS
        for bucket in TIME_BUCKETS
    ]


def run_sparse_phase_scan(index_zip: Path) -> dict[str, Any]:
    """Select on pre-final data, then evaluate only the frozen selections on final."""
    panel, audit = build_sparse_phase_panel(index_zip)
    validation_by_horizon = {
        horizon: walk_forward_predictions(panel, horizon, VALIDATION_START, VALIDATION_END)
        for horizon in HORIZONS
    }
    candidates = candidate_grid()
    validation_metrics: dict[str, SparseMetric] = {}
    for candidate in candidates:
        validation_metrics[candidate.name] = evaluate_candidate(
            validation_by_horizon[candidate.horizon], candidate, PRIMARY_COST_BPS
        )
    trading_candidates = [
        candidate for candidate in candidates if validation_metrics[candidate.name].trades > 0
    ]
    if not trading_candidates:
        raise ValueError("no candidate generated a validation trade")
    best_active = max(
        trading_candidates,
        key=lambda candidate: validation_metrics[candidate.name].net_mean_bps_per_day,
    )
    best_metric = validation_metrics[best_active.name]
    selected: Candidate | None = best_active if best_metric.net_mean_bps_per_day > 0 else None

    # The final targets are touched only after every selection field has been frozen above.
    final_candidates = [] if selected is None else [selected]
    final_results: dict[str, Any] = {}
    for candidate in final_candidates:
        final_predictions = walk_forward_predictions(
            panel, candidate.horizon, FINAL_START, FINAL_END
        )
        final_results[candidate.name] = {
            f"cost_{cost:g}bps": asdict(evaluate_candidate(final_predictions, candidate, cost))
            for cost in COSTS_BPS
        }
    leaderboard = sorted(
        ((name, metric) for name, metric in validation_metrics.items() if metric.trades > 0),
        key=lambda item: item[1].net_mean_bps_per_day,
        reverse=True,
    )
    return {
        "protocol": {
            "signal": "phase-zero (:00/:15/:30/:45) ridge return forecast",
            "discovery": "2025-09-01 through the month before each walk-forward block",
            "validation": "2026-07-01 through 2026-08-14",
            "sealed_final": "2026-08-17 through 2026-08-21",
            "selection_cost_bps_round_trip": PRIMARY_COST_BPS,
            "candidate_count": len(candidates),
            "warning": "NIFTY index return proxy; futures execution and basis are unavailable",
        },
        "data_audit": audit,
        "selection": {
            "selected": selected.name if selected is not None else "cash",
            "best_active": best_active.name,
            "best_active_validation": asdict(best_metric),
            "top_validation": [
                {"candidate": name, **asdict(metric)} for name, metric in leaderboard[:10]
            ],
        },
        "final": (
            {"cash": {"net_mean_bps_per_day": 0.0}, **final_results}
            if selected is None
            else final_results
        ),
    }
