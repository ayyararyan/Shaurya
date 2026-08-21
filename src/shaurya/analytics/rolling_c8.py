"""Causal 30-minute rolling C8 forecasts for the live OFI table.

At every forecast anchor the estimator sees only labelled anchors from the immediately preceding
30 minutes whose complete response is already observable.  Forecasts are scored once their own
future displayed-mid response matures.  The state is cumulative from worker launch and is never
backfilled from already observed outcomes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Final

import numpy as np

from shaurya.analytics.live_ofi_studies import atomic_write_json
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS
from shaurya.signals.fixed_target_panel import (
    MINIMUM_FIT_OBSERVATIONS,
    _design,
    _fit_predictions,
    competitor_features,
)
from shaurya.signals.ofi_horserace import HorseRaceObservation
from shaurya.signals.reference_prices import PricePath

SPECIFICATION_ID: Final = "D46 / ANL-06-ROLLING-C8-30M"
TRAINING_WINDOW_SECONDS: Final = 30.0 * 60.0
FORECAST_CADENCE_SECONDS: Final = 5.0
WIN_SCORE_WINDOW_SECONDS: Final = 5.0 * 60.0
LOOKBACKS_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0)
HORIZONS_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0)
LEVELS: Final = 10


def cell_key(lookback: float, horizon: float) -> str:
    return f"{lookback:g}|{horizon:g}"


def forecast_win_score(*, prediction: float, actual: float) -> int:
    """Score whether the realised move reached the forecast threshold in either direction."""

    if prediction > 0.0:
        if actual >= prediction:
            return 1
        if actual <= -prediction:
            return -1
    elif prediction < 0.0:
        if actual <= prediction:
            return 1
        if actual >= -prediction:
            return -1
    return 0


def causal_training_positions(
    observations: Sequence[HorseRaceObservation],
    *,
    forecast: HorseRaceObservation,
    lookback: float,
    horizon: float,
    training_window_seconds: float = TRAINING_WINDOW_SECONDS,
) -> tuple[int, ...]:
    """Return rows in [t-30m,t] whose h2 labels have fully matured before t."""

    names = competitor_features("C8", lookback, LEVELS)
    lower = forecast.receive_ts_ns - int(training_window_seconds * 1_000_000_000)
    maturity = int((CAUSAL_GAP_SECONDS + horizon) * 1_000_000_000)
    positions: list[int] = []
    for position, observation in enumerate(observations):
        if observation.tape_index != forecast.tape_index:
            continue
        if observation.connection_epoch != forecast.connection_epoch:
            continue
        if observation.receive_ts_ns < lower:
            continue
        if observation.receive_ts_ns + maturity > forecast.receive_ts_ns:
            continue
        target = observation.future_ticks.get(horizon)
        if target is None or not isfinite(float(target)):
            continue
        if not all(name in observation.features for name in names):
            continue
        if not all(isfinite(float(observation.features[name])) for name in names):
            continue
        positions.append(position)
    return tuple(positions)


def fit_forecast_cell(
    observations: Sequence[HorseRaceObservation],
    *,
    forecast_position: int,
    lookback: float,
    horizon: float,
) -> dict[str, Any]:
    forecast = observations[forecast_position]
    names = competitor_features("C8", lookback, LEVELS)
    train = causal_training_positions(
        observations,
        forecast=forecast,
        lookback=lookback,
        horizon=horizon,
    )
    if len(train) < MINIMUM_FIT_OBSERVATIONS:
        return {"status": "warming", "train_n": len(train)}
    train_design = _design(observations, train, names, {})
    test_design = _design(observations, (forecast_position,), names, {})
    train_target = np.asarray(
        [float(observations[position].future_ticks[horizon]) for position in train],
        dtype=np.float64,
    )
    train_timestamps = np.asarray(
        [observations[position].receive_ts_ns for position in train], dtype=np.int64
    )
    prediction, fit = _fit_predictions(
        "C8",
        names,
        train_design,
        test_design,
        train_target,
        np.zeros(1, dtype=np.float64),
        train_timestamps,
    )
    return {
        "status": "forecast",
        "train_n": len(train),
        "training_start_ts_ns": int(train_timestamps[0]),
        "training_end_ts_ns": int(train_timestamps[-1]),
        "prediction_ticks": float(prediction[0]),
        "baseline_ticks": float(train_target.mean()),
        "selected_ridge_alpha": fit["selected_alpha"],
    }


@dataclass(slots=True)
class ScoreAccumulator:
    forecasts_issued: int = 0
    scored_n: int = 0
    squared_error: float = 0.0
    squared_baseline_error: float = 0.0
    absolute_error: float = 0.0
    direction_correct: int = 0
    direction_n: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ScoreAccumulator:
        return cls(
            forecasts_issued=int(value.get("forecasts_issued", 0)),
            scored_n=int(value.get("scored_n", 0)),
            squared_error=float(value.get("squared_error", 0.0)),
            squared_baseline_error=float(value.get("squared_baseline_error", 0.0)),
            absolute_error=float(value.get("absolute_error", 0.0)),
            direction_correct=int(value.get("direction_correct", 0)),
            direction_n=int(value.get("direction_n", 0)),
        )

    def score(self, *, actual: float, prediction: float, baseline: float) -> None:
        error = actual - prediction
        self.scored_n += 1
        self.squared_error += error * error
        self.squared_baseline_error += (actual - baseline) ** 2
        self.absolute_error += abs(error)
        if actual != 0.0:
            self.direction_n += 1
            self.direction_correct += int(np.sign(actual) == np.sign(prediction))

    def payload(self) -> dict[str, Any]:
        r2 = (
            1.0 - self.squared_error / self.squared_baseline_error
            if self.squared_baseline_error > 0.0
            else None
        )
        return {
            "forecasts_issued": self.forecasts_issued,
            "scored_n": self.scored_n,
            "squared_error": self.squared_error,
            "squared_baseline_error": self.squared_baseline_error,
            "absolute_error": self.absolute_error,
            "direction_correct": self.direction_correct,
            "direction_n": self.direction_n,
            "cumulative_oos_r2": r2,
            "cumulative_mae_ticks": (
                self.absolute_error / self.scored_n if self.scored_n else None
            ),
            "cumulative_rmse_ticks": (
                (self.squared_error / self.scored_n) ** 0.5 if self.scored_n else None
            ),
            "cumulative_direction_accuracy": (
                self.direction_correct / self.direction_n if self.direction_n else None
            ),
        }


@dataclass(slots=True)
class RollingC8Tracker:
    started_at: str
    accumulators: dict[str, ScoreAccumulator] = field(default_factory=dict)
    pending: list[dict[str, Any]] = field(default_factory=list)
    latest_fit: dict[str, dict[str, Any]] = field(default_factory=dict)
    recent_win_scores: list[dict[str, Any]] = field(default_factory=list)
    last_forecast_anchor_ts_ns: int | None = None

    @classmethod
    def fresh(cls) -> RollingC8Tracker:
        return cls(started_at=datetime.now(UTC).isoformat())

    @classmethod
    def load(cls, path: Path) -> RollingC8Tracker:
        if not path.exists():
            return cls.fresh()
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("rolling state is not an object")
        raw_accumulators = loaded.get("accumulators", {})
        raw_latest = loaded.get("latest_fit", {})
        return cls(
            started_at=str(loaded.get("started_at") or datetime.now(UTC).isoformat()),
            accumulators={
                str(key): ScoreAccumulator.from_mapping(value)
                for key, value in raw_accumulators.items()
                if isinstance(value, dict)
            }
            if isinstance(raw_accumulators, dict)
            else {},
            pending=[dict(value) for value in loaded.get("pending", []) if isinstance(value, dict)],
            latest_fit={str(key): dict(value) for key, value in raw_latest.items()}
            if isinstance(raw_latest, dict)
            else {},
            recent_win_scores=[
                dict(value)
                for value in loaded.get("recent_win_scores", [])
                if isinstance(value, dict)
            ],
            last_forecast_anchor_ts_ns=(
                int(loaded["last_forecast_anchor_ts_ns"])
                if loaded.get("last_forecast_anchor_ts_ns") is not None
                else None
            ),
        )

    def issue(
        self,
        observations: Sequence[HorseRaceObservation],
        *,
        forecast_position: int,
    ) -> list[dict[str, Any]]:
        anchor = observations[forecast_position]
        if (
            self.last_forecast_anchor_ts_ns is not None
            and anchor.receive_ts_ns <= self.last_forecast_anchor_ts_ns
        ):
            return []
        issued: list[dict[str, Any]] = []
        for lookback in LOOKBACKS_SECONDS:
            for horizon in HORIZONS_SECONDS:
                fitted = fit_forecast_cell(
                    observations,
                    forecast_position=forecast_position,
                    lookback=lookback,
                    horizon=horizon,
                )
                key = cell_key(lookback, horizon)
                self.latest_fit[key] = fitted
                if fitted["status"] != "forecast":
                    continue
                record = {
                    "cell_key": key,
                    "lookback_seconds": lookback,
                    "horizon_seconds": horizon,
                    "forecast_anchor_ts_ns": anchor.receive_ts_ns,
                    "response_start_ts_ns": anchor.receive_ts_ns
                    + int(CAUSAL_GAP_SECONDS * 1_000_000_000),
                    "response_end_ts_ns": anchor.receive_ts_ns
                    + int((CAUSAL_GAP_SECONDS + horizon) * 1_000_000_000),
                    **fitted,
                }
                self.pending.append(record)
                self.accumulators.setdefault(key, ScoreAccumulator()).forecasts_issued += 1
                issued.append(record)
        self.last_forecast_anchor_ts_ns = anchor.receive_ts_ns
        return issued

    def mature(self, price_path: PricePath) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        retained: list[dict[str, Any]] = []
        for record in self.pending:
            actual = price_path.return_ticks(
                int(record["response_start_ts_ns"]), int(record["response_end_ts_ns"])
            )
            if actual is None:
                retained.append(record)
                continue
            key = str(record["cell_key"])
            prediction = float(record["prediction_ticks"])
            baseline = float(record["baseline_ticks"])
            self.accumulators.setdefault(key, ScoreAccumulator()).score(
                actual=actual, prediction=prediction, baseline=baseline
            )
            point = forecast_win_score(prediction=prediction, actual=actual)
            outcome = {
                **record,
                "actual_ticks": actual,
                "win_score": point,
                "scored_at": datetime.now(UTC).isoformat(),
            }
            outcomes.append(outcome)
            self.recent_win_scores.append(
                {
                    "cell_key": key,
                    "forecast_anchor_ts_ns": int(record["forecast_anchor_ts_ns"]),
                    "response_end_ts_ns": int(record["response_end_ts_ns"]),
                    "win_score": point,
                }
            )
        self.pending = retained
        self.prune_recent_win_scores(price_path.coverage_end_ts_ns)
        return outcomes

    def restore_recent_win_scores(
        self, outcomes: Sequence[Mapping[str, Any]], *, as_of_ts_ns: int | None
    ) -> None:
        """Restore the trailing score window from append-only receipts after an upgrade/restart."""

        existing = {
            (str(row["cell_key"]), int(row["forecast_anchor_ts_ns"]))
            for row in self.recent_win_scores
        }
        for outcome in outcomes:
            required = (
                "cell_key",
                "forecast_anchor_ts_ns",
                "response_end_ts_ns",
                "prediction_ticks",
                "actual_ticks",
            )
            if not all(name in outcome for name in required):
                continue
            identity = (str(outcome["cell_key"]), int(outcome["forecast_anchor_ts_ns"]))
            if identity in existing:
                continue
            point = outcome.get("win_score")
            if point is None:
                point = forecast_win_score(
                    prediction=float(outcome["prediction_ticks"]),
                    actual=float(outcome["actual_ticks"]),
                )
            self.recent_win_scores.append(
                {
                    "cell_key": identity[0],
                    "forecast_anchor_ts_ns": identity[1],
                    "response_end_ts_ns": int(outcome["response_end_ts_ns"]),
                    "win_score": int(point),
                }
            )
            existing.add(identity)
        self.prune_recent_win_scores(as_of_ts_ns)

    def prune_recent_win_scores(self, as_of_ts_ns: int | None) -> None:
        if as_of_ts_ns is None:
            return
        cutoff = as_of_ts_ns - int(WIN_SCORE_WINDOW_SECONDS * 1_000_000_000)
        self.recent_win_scores = [
            row for row in self.recent_win_scores if int(row["response_end_ts_ns"]) > cutoff
        ]

    def rolling_win_score(self, key: str) -> dict[str, Any]:
        values = [
            int(row["win_score"])
            for row in self.recent_win_scores
            if str(row["cell_key"]) == key
        ]
        return {
            "rolling_mean_win_score_5m": sum(values) / len(values) if values else None,
            "rolling_win_score_n_5m": len(values),
            "rolling_wins_5m": values.count(1),
            "rolling_neutral_5m": values.count(0),
            "rolling_losses_5m": values.count(-1),
        }

    def payload(self, *, source: Mapping[str, Any], status: str = "running") -> dict[str, Any]:
        cells: list[dict[str, Any]] = []
        for lookback in LOOKBACKS_SECONDS:
            for horizon in HORIZONS_SECONDS:
                key = cell_key(lookback, horizon)
                score = self.accumulators.get(key, ScoreAccumulator()).payload()
                fit = self.latest_fit.get(key, {"status": "warming", "train_n": 0})
                cells.append(
                    {
                        "cell_key": key,
                        "lookback_seconds": lookback,
                        "horizon_seconds": horizon,
                        **score,
                        **self.rolling_win_score(key),
                        "latest_fit": fit,
                    }
                )
        return {
            "schema_version": "1.0.0",
            "specification_id": SPECIFICATION_ID,
            "status": status,
            "started_at": self.started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "training_window_seconds": TRAINING_WINDOW_SECONDS,
            "forecast_cadence_seconds": FORECAST_CADENCE_SECONDS,
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "model": "C8",
            "reference_price": "displayed_mid",
            "levels": LEVELS,
            "source": dict(source),
            "last_forecast_anchor_ts_ns": self.last_forecast_anchor_ts_ns,
            "pending_count": len(self.pending),
            "cells": cells,
            "accumulators": {
                key: accumulator.payload() for key, accumulator in self.accumulators.items()
            },
            "pending": self.pending,
            "latest_fit": self.latest_fit,
            "recent_win_scores": self.recent_win_scores,
            "confirmatory_eligible": False,
            "order_entry_enabled": False,
            "metric_definition": (
                "1-sum((y-yhat)^2)/sum((y-rolling_training_mean)^2), accumulated only "
                "over forecasts issued after this worker started"
            ),
            "win_score_definition": (
                "+1=same direction and realised magnitude reaches forecast; "
                "-1=opposite direction and realised magnitude reaches forecast; "
                "0=otherwise; displayed mean uses trailing five minutes of outcome end-times"
            ),
        }


def persist_tracker(
    tracker: RollingC8Tracker,
    path: Path,
    *,
    source: Mapping[str, Any],
    status: str = "running",
) -> None:
    atomic_write_json(path, tracker.payload(source=source, status=status))


def append_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
