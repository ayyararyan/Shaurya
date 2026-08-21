"""Prospective C8 response-surface scan, isolated from the dashboard."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np

from shaurya.analytics.live_ofi_studies import atomic_write_json
from shaurya.analytics.rolling_c8 import ScoreAccumulator, fit_forecast_grid
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS
from shaurya.signals.ofi_horserace import HorseRaceObservation
from shaurya.signals.reference_prices import PricePath

SPECIFICATION_ID: Final = "D49 / ANL-06-C8-RESPONSE-SURFACE"
TRAINING_WINDOWS_SECONDS: Final = (450.0, 600.0, 750.0, 900.0, 1050.0, 1200.0)
LOOKBACKS_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0)
HORIZONS_SECONDS: Final = (5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 30.0)
FORECAST_CADENCE_SECONDS: Final = 5.0


def cell_key(window: float, lookback: float, horizon: float) -> str:
    return f"{window / 60:g}m|{lookback:g}|{horizon:g}"


@dataclass(slots=True)
class ResponseSurfaceTracker:
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    accumulators: dict[str, ScoreAccumulator] = field(default_factory=dict)
    pending: list[dict[str, Any]] = field(default_factory=list)
    latest_fit: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_forecast_anchor_ts_ns: int | None = None

    def issue(
        self, observations: Sequence[HorseRaceObservation], *, forecast_position: int
    ) -> list[dict[str, Any]]:
        anchor = observations[forecast_position]
        if (
            self.last_forecast_anchor_ts_ns is not None
            and anchor.receive_ts_ns <= self.last_forecast_anchor_ts_ns
        ):
            return []
        grid = fit_forecast_grid(
            observations,
            forecast_position=forecast_position,
            training_windows_seconds=TRAINING_WINDOWS_SECONDS,
            lookbacks_seconds=LOOKBACKS_SECONDS,
            horizons_seconds=HORIZONS_SECONDS,
        )
        issued: list[dict[str, Any]] = []
        for window in TRAINING_WINDOWS_SECONDS:
            for lookback in LOOKBACKS_SECONDS:
                for horizon in HORIZONS_SECONDS:
                    fitted = grid[(window, lookback, horizon)]
                    key = cell_key(window, lookback, horizon)
                    self.latest_fit[key] = fitted
                    if fitted["status"] != "forecast":
                        continue
                    record = {
                        "cell_key": key,
                        "training_window_seconds": window,
                        "training_window_minutes": window / 60.0,
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
            self.accumulators.setdefault(key, ScoreAccumulator()).score(
                actual=actual,
                prediction=float(record["prediction_ticks"]),
                baseline=float(record["baseline_ticks"]),
            )
            outcomes.append(
                {**record, "actual_ticks": actual, "scored_at": datetime.now(UTC).isoformat()}
            )
        self.pending = retained
        return outcomes

    def payload(self, *, source: Mapping[str, Any], status: str = "running") -> dict[str, Any]:
        cells: list[dict[str, Any]] = []
        for window in TRAINING_WINDOWS_SECONDS:
            for lookback in LOOKBACKS_SECONDS:
                for horizon in HORIZONS_SECONDS:
                    key = cell_key(window, lookback, horizon)
                    cells.append(
                        {
                            "cell_key": key,
                            "training_window_seconds": window,
                            "training_window_minutes": window / 60.0,
                            "lookback_seconds": lookback,
                            "horizon_seconds": horizon,
                            **self.accumulators.get(key, ScoreAccumulator()).payload(),
                            "latest_fit": self.latest_fit.get(
                                key, {"status": "warming", "train_n": 0}
                            ),
                        }
                    )
        return {
            "schema_version": "1.0.0",
            "specification_id": SPECIFICATION_ID,
            "status": status,
            "started_at": self.started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "training_windows_seconds": list(TRAINING_WINDOWS_SECONDS),
            "lookbacks_seconds": list(LOOKBACKS_SECONDS),
            "horizons_seconds": list(HORIZONS_SECONDS),
            "forecast_cadence_seconds": FORECAST_CADENCE_SECONDS,
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "model": "C8",
            "reference_price": "displayed_mid",
            "levels": 10,
            "source": dict(source),
            "last_forecast_anchor_ts_ns": self.last_forecast_anchor_ts_ns,
            "pending_count": len(self.pending),
            "cells": cells,
            "pending": self.pending,
            "latest_fit": self.latest_fit,
            "confirmatory_eligible": False,
            "order_entry_enabled": False,
        }


def persist_tracker(
    tracker: ResponseSurfaceTracker,
    path: Path,
    *,
    source: Mapping[str, Any],
    status: str = "running",
) -> None:
    atomic_write_json(path, tracker.payload(source=source, status=status))


def surface_diagnostics(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Quantify local smoothness separately for each OFI sampling horizon.

    A surface passes when neighboring interpolation errors are small relative to its own
    observed range and it has no isolated interior spike. This tests local regularity, not
    monotonicity and not which parameter wins.
    """

    by_key = {
        (float(row["lookback_seconds"]), float(row["training_window_minutes"]),
         float(row["horizon_seconds"])): row.get("cumulative_oos_r2")
        for row in cells
    }
    results: list[dict[str, Any]] = []
    for lookback in LOOKBACKS_SECONDS:
        matrix = np.asarray(
            [
                [by_key[(lookback, window / 60.0, horizon)] for horizon in HORIZONS_SECONDS]
                for window in TRAINING_WINDOWS_SECONDS
            ],
            dtype=np.float64,
        )
        if not np.isfinite(matrix).all():
            results.append({"lookback_seconds": lookback, "status": "insufficient"})
            continue
        observed_range = float(np.ptp(matrix))
        scale = max(observed_range, 0.01)
        residuals: list[float] = []
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                neighbors: list[float] = []
                if i:
                    neighbors.append(float(matrix[i - 1, j]))
                if i + 1 < matrix.shape[0]:
                    neighbors.append(float(matrix[i + 1, j]))
                if j:
                    neighbors.append(float(matrix[i, j - 1]))
                if j + 1 < matrix.shape[1]:
                    neighbors.append(float(matrix[i, j + 1]))
                residuals.append(float(matrix[i, j]) - float(np.mean(neighbors)))
        rmse = float(np.sqrt(np.mean(np.square(residuals))))
        max_residual = float(np.max(np.abs(residuals)))
        second_l = np.diff(matrix, n=2, axis=0).ravel()
        second_h = np.diff(matrix, n=2, axis=1).ravel()
        median_curvature = float(np.median(np.abs(np.concatenate((second_l, second_h)))))
        passed = (
            rmse <= 0.35 * scale
            and max_residual <= 0.75 * scale
            and median_curvature <= 0.50 * scale
        )
        results.append(
            {
                "lookback_seconds": lookback,
                "status": "smooth" if passed else "not_smooth",
                "r2_min": float(np.min(matrix)),
                "r2_max": float(np.max(matrix)),
                "neighbor_rmse": rmse,
                "max_neighbor_residual": max_residual,
                "median_absolute_second_difference": median_curvature,
                "thresholds_relative_to_range": {"rmse": 0.35, "max": 0.75, "curvature": 0.5},
            }
        )
    decided = [row for row in results if row["status"] != "insufficient"]
    smooth_n = sum(row["status"] == "smooth" for row in decided)
    verdict = (
        "smooth" if len(decided) == len(LOOKBACKS_SECONDS) and smooth_n >= 4
        else "mixed" if smooth_n else "not_smooth"
    )
    return {"verdict": verdict, "smooth_surfaces": smooth_n, "total_surfaces": len(decided),
            "by_lookback": results}
