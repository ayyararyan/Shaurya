"""D50 nonlinear predictor-geometry gate and causally delayed Kalman-beta horse race."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from math import isfinite
from typing import Any, Final

import numpy as np

from shaurya.contracts.timing import IST
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS
from shaurya.signals.fixed_target_panel import _select_alpha, competitor_features
from shaurya.signals.ofi_horserace import HorseRaceObservation

SPECIFICATION_ID: Final = "D50 / NONLINEAR-OFI-GATE-KALMAN-CALIBRATION"
TRAINING_WINDOWS_SECONDS: Final = (450.0, 600.0, 750.0, 900.0, 1050.0, 1200.0)
SAMPLING_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0)
HORIZONS_SECONDS: Final = (5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 30.0)
CADENCE_SECONDS: Final = 5.0
GATE_FORWARD_SECONDS: Final = 300.0
KALMAN_RHOS: Final = (0.98, 0.995, 1.0)
KALMAN_Q_SCALES: Final = (1e-7, 1e-6, 1e-5, 1e-4, 1e-3)
GATE_PENALTIES: Final = (0.01, 0.1, 1.0, 10.0, 100.0)
SHRINKAGES: Final = (0.0, 0.25, 0.5, 0.75, 1.0)
LEVELS: Final = 10
GEOMETRY_NAMES: Final = (
    "log_ofi_energy",
    "depth_coherence",
    "touch_concentration",
    "multiscale_agreement",
    "ofi_persistence_60s",
    "absolute_ofi_acceleration_10s",
    "spread_ticks",
    "log1p_l1_depth",
)


@dataclass(frozen=True, slots=True)
class Panel:
    timestamps: np.ndarray[Any, np.dtype[np.int64]]
    designs: Mapping[float, np.ndarray[Any, np.dtype[np.float64]]]
    targets: np.ndarray[Any, np.dtype[np.float64]]
    geometry: np.ndarray[Any, np.dtype[np.float64]]


def _ns_at(day: datetime, wall_time: time) -> int:
    return int(datetime.combine(day.date(), wall_time, tzinfo=IST).timestamp() * 1_000_000_000)


def split_masks(timestamps: np.ndarray[Any, np.dtype[np.int64]]) -> dict[str, np.ndarray[Any, Any]]:
    day = datetime.fromtimestamp(int(timestamps[0]) / 1e9, IST)
    bounds = {
        "train": (time(9, 35), time(12, 0)),
        "validation": (time(12, 5), time(13, 30)),
        "test": (time(13, 35), time(15, 29, 30)),
    }
    return {
        name: (timestamps >= _ns_at(day, start)) & (timestamps <= _ns_at(day, end))
        for name, (start, end) in bounds.items()
    }


def cadence_observations(
    observations: Sequence[HorseRaceObservation],
) -> tuple[HorseRaceObservation, ...]:
    """Keep the last usable observation in each five-second bucket."""

    buckets: dict[tuple[int, int], HorseRaceObservation] = {}
    width = int(CADENCE_SECONDS * 1_000_000_000)
    for observation in observations:
        bucket = observation.receive_ts_ns // width
        buckets[(observation.connection_epoch, bucket)] = observation
    return tuple(sorted(buckets.values(), key=lambda value: value.receive_ts_ns))


def _geometry(
    timestamps: np.ndarray[Any, np.dtype[np.int64]],
    designs: Mapping[float, np.ndarray[Any, np.dtype[np.float64]]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    tensor = np.stack([designs[value][:, -LEVELS:] for value in SAMPLING_SECONDS], axis=1)
    absolute = np.abs(tensor)
    totals = absolute.sum(axis=2)
    # NumPy under the production Python 3.14 build may reuse the left operand's temporary buffer
    # for ``tensor**2``.  The original tensor is still required by every subsequent geometry
    # feature, so square an explicit copy in place and preserve the source values.
    squared = tensor.copy()
    np.square(squared, out=squared)
    energy = np.log1p(np.mean(squared, axis=(1, 2))).copy()
    coherence_ratio = np.divide(
        np.abs(tensor.sum(axis=2)),
        totals,
        out=np.zeros_like(totals),
        where=totals > 0,
    )
    coherence = np.mean(coherence_ratio, axis=1).copy()
    touch_ratio = np.divide(
        absolute[:, :, :3].sum(axis=2),
        totals,
        out=np.zeros_like(totals),
        where=totals > 0,
    )
    touch = np.mean(touch_ratio, axis=1).copy()
    aggregate_by_scale = tensor.mean(axis=2)
    agreement = np.abs(np.sign(aggregate_by_scale).sum(axis=1)) / len(SAMPLING_SECONDS)
    aggregate = aggregate_by_scale.mean(axis=1)
    persistence = np.zeros(len(timestamps), dtype=np.float64)
    acceleration = np.zeros(len(timestamps), dtype=np.float64)
    for position, stamp in enumerate(timestamps):
        left = int(np.searchsorted(timestamps, stamp - 60_000_000_000, side="left"))
        history = aggregate[left:position]
        persistence[position] = (
            float(np.mean(np.sign(history) == np.sign(aggregate[position])))
            if history.size
            else 0.5
        )
        lag = int(np.searchsorted(timestamps, stamp - 10_000_000_000, side="right")) - 1
        acceleration[position] = (
            abs(float(aggregate[position] - aggregate[lag])) if lag >= 0 else 0.0
        )
    for name, values in (
        ("depth_coherence", coherence),
        ("touch_concentration", touch),
        ("multiscale_agreement", agreement),
        ("ofi_persistence_60s", persistence),
    ):
        if np.any(values < -1e-12) or np.any(values > 1.0 + 1e-12):
            raise ValueError(f"D50 bounded geometry invariant failed for {name}")
    reference = designs[SAMPLING_SECONDS[0]]
    return np.column_stack(
        (
            energy,
            coherence,
            touch,
            agreement,
            persistence,
            acceleration,
            reference[:, 1],
            reference[:, 0],
        )
    )


def prepare_panel(observations: Sequence[HorseRaceObservation]) -> Panel:
    sampled = cadence_observations(observations)
    names_by_sampling = {
        sampling: competitor_features("C8", sampling, LEVELS) for sampling in SAMPLING_SECONDS
    }
    usable: list[HorseRaceObservation] = []
    for observation in sampled:
        if not all(horizon in observation.future_ticks for horizon in HORIZONS_SECONDS):
            continue
        required = (name for names in names_by_sampling.values() for name in names)
        if not all(
            name in observation.features and isfinite(float(observation.features[name]))
            for name in required
        ):
            continue
        usable.append(observation)
    timestamps = np.asarray([row.receive_ts_ns for row in usable], dtype=np.int64)
    designs = {
        sampling: np.asarray(
            [[float(row.features[name]) for name in names] for row in usable],
            dtype=np.float64,
        )
        for sampling, names in names_by_sampling.items()
    }
    targets = np.asarray(
        [[float(row.future_ticks[horizon]) for horizon in HORIZONS_SECONDS] for row in usable],
        dtype=np.float64,
    )
    geometry = _geometry(timestamps, designs)
    geometry.setflags(write=False)
    return Panel(timestamps, designs, targets, geometry)


def select_ridge_penalties(
    panel: Panel, train: np.ndarray[Any, Any]
) -> dict[tuple[float, float], float]:
    selected: dict[tuple[float, float], float] = {}
    positions = np.flatnonzero(train)
    for sampling in SAMPLING_SECONDS:
        names = competitor_features("C8", sampling, LEVELS)
        for column, horizon in enumerate(HORIZONS_SECONDS):
            alpha, _ = _select_alpha(
                panel.designs[sampling][positions],
                panel.targets[positions, column],
                panel.timestamps[positions],
                names,
            )
            selected[(sampling, horizon)] = alpha
    return selected


def _rolling_prediction(
    design: np.ndarray[Any, np.dtype[np.float64]],
    target: np.ndarray[Any, np.dtype[np.float64]],
    timestamps: np.ndarray[Any, np.dtype[np.int64]],
    *,
    position: int,
    window: float,
    horizon: float,
    alpha: float,
) -> tuple[float, float] | None:
    stamp = int(timestamps[position])
    lower = stamp - int(window * 1e9)
    upper = stamp - int((CAUSAL_GAP_SECONDS + horizon) * 1e9)
    left = int(np.searchsorted(timestamps, lower, side="left"))
    right = int(np.searchsorted(timestamps, upper, side="right"))
    if right - left < 20:
        return None
    x = design[left:right]
    y = target[left:right]
    centre = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale <= 0] = 1.0
    z = (x - centre) / scale
    drift = float(y.mean())
    gram = z.T @ z
    rhs = z.T @ (y - drift)
    try:
        beta = np.linalg.solve(gram + alpha * np.eye(z.shape[1]), rhs)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(gram + alpha * np.eye(z.shape[1]), rhs, rcond=None)[0]
    prediction = drift + float(((design[position] - centre) / scale) @ beta)
    return prediction, drift


def rolling_surface_predictions(
    panel: Panel,
    penalties: Mapping[tuple[float, float], float],
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    n = len(panel.timestamps)
    cells = len(TRAINING_WINDOWS_SECONDS) * len(SAMPLING_SECONDS)
    predictions = np.full((n, len(HORIZONS_SECONDS), cells), np.nan, dtype=np.float64)
    baselines = np.full_like(predictions, np.nan)
    for horizon_column, horizon in enumerate(HORIZONS_SECONDS):
        cell = 0
        target = panel.targets[:, horizon_column]
        for window in TRAINING_WINDOWS_SECONDS:
            for sampling in SAMPLING_SECONDS:
                design = panel.designs[sampling]
                alpha = penalties[(sampling, horizon)]
                for position in range(n):
                    fitted = _rolling_prediction(
                        design,
                        target,
                        panel.timestamps,
                        position=position,
                        window=window,
                        horizon=horizon,
                        alpha=alpha,
                    )
                    if fitted is not None:
                        predictions[position, horizon_column, cell] = fitted[0]
                        baselines[position, horizon_column, cell] = fitted[1]
                cell += 1
    m1 = np.nanmedian(predictions, axis=2)
    m0 = np.nanmedian(baselines, axis=2)
    return predictions, baselines, m0, m1


def future_surface_height(
    panel: Panel,
    predictions: np.ndarray[Any, Any],
    baselines: np.ndarray[Any, Any],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    model_loss = (panel.targets[:, :, None] - predictions) ** 2
    baseline_loss = (panel.targets[:, :, None] - baselines) ** 2
    model_loss = np.where(np.isfinite(model_loss), model_loss, 0.0)
    baseline_loss = np.where(np.isfinite(baseline_loss), baseline_loss, 0.0)
    model_prefix = np.concatenate(
        (np.zeros((1, *model_loss.shape[1:])), np.cumsum(model_loss, axis=0))
    )
    base_prefix = np.concatenate(
        (np.zeros((1, *baseline_loss.shape[1:])), np.cumsum(baseline_loss, axis=0))
    )
    values = np.full(len(panel.timestamps), np.nan, dtype=np.float64)
    for position, stamp in enumerate(panel.timestamps):
        right = int(
            np.searchsorted(panel.timestamps, stamp + int(GATE_FORWARD_SECONDS * 1e9), side="right")
        )
        model_sum = model_prefix[right] - model_prefix[position]
        base_sum = base_prefix[right] - base_prefix[position]
        r2 = np.divide(
            base_sum - model_sum,
            base_sum,
            out=np.full_like(base_sum, np.nan),
            where=base_sum > 0,
        )
        finite = r2[np.isfinite(r2)]
        if finite.size:
            values[position] = float(np.median(finite))
    return values


def _spline_basis_fit(
    geometry: np.ndarray[Any, Any], train: np.ndarray[Any, Any]
) -> tuple[np.ndarray[Any, Any], dict[str, Any]]:
    centre = geometry[train].mean(axis=0)
    scale = geometry[train].std(axis=0)
    scale[scale <= 0] = 1.0
    z = (geometry - centre) / scale
    knots = np.quantile(z[train], (0.2, 0.4, 0.6, 0.8), axis=0)
    columns = [np.ones(len(z))]
    for column in range(z.shape[1]):
        columns.append(z[:, column])
        columns.extend(np.maximum(z[:, column] - knot, 0.0) for knot in knots[:, column])
    columns.append(z[:, 0] * z[:, 1])
    columns.append(z[:, 1] * z[:, 3])
    return np.column_stack(columns), {
        "centre": centre.tolist(),
        "scale": scale.tolist(),
        "knots_standardised": knots.tolist(),
        "basis_columns": len(columns),
    }


def _fit_logistic(
    design: np.ndarray[Any, Any], target: np.ndarray[Any, Any], penalty: float
) -> np.ndarray[Any, Any]:
    beta = np.zeros(design.shape[1], dtype=np.float64)
    if np.all(target == target[0]):
        rate = (float(target.sum()) + 0.5) / (len(target) + 1.0)
        beta[0] = np.log(rate / (1.0 - rate))
        return beta
    penalise = np.eye(design.shape[1], dtype=np.float64)
    penalise[0, 0] = 0.0
    for _ in range(100):
        linear = np.clip(design @ beta, -30.0, 30.0)
        probability = 1.0 / (1.0 + np.exp(-linear))
        weight = np.maximum(probability * (1.0 - probability), 1e-6)
        working = linear + (target - probability) / weight
        gram = design.T @ (design * weight[:, None]) + penalty * penalise
        rhs = design.T @ (weight * working)
        try:
            updated = np.linalg.solve(gram, rhs)
        except np.linalg.LinAlgError:
            updated = np.linalg.lstsq(gram, rhs, rcond=None)[0]
        if float(np.max(np.abs(updated - beta))) < 1e-8:
            beta = updated
            break
        beta = updated
    return beta


def _probability(design: np.ndarray[Any, Any], beta: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    return np.asarray(
        1.0 / (1.0 + np.exp(-np.clip(design @ beta, -30.0, 30.0))),
        dtype=np.float64,
    )


def fit_gate(
    panel: Panel,
    surface_height: np.ndarray[Any, Any],
    masks: Mapping[str, np.ndarray[Any, Any]],
) -> tuple[np.ndarray[Any, Any], dict[str, Any]]:
    end_by_split = {
        name: int(panel.timestamps[np.flatnonzero(mask)[-1]]) for name, mask in masks.items()
    }
    label_eligible = np.isfinite(surface_height)
    for name, mask in masks.items():
        label_eligible &= (~mask) | (
            panel.timestamps + int(GATE_FORWARD_SECONDS * 1e9) <= end_by_split[name]
        )
    train = masks["train"] & label_eligible
    validation = masks["validation"] & label_eligible
    target = (surface_height > 0.0).astype(np.float64)
    basis, transform = _spline_basis_fit(panel.geometry, train)
    scores: list[dict[str, float]] = []
    fits: dict[float, np.ndarray[Any, Any]] = {}
    for penalty in GATE_PENALTIES:
        beta = _fit_logistic(basis[train], target[train], penalty)
        fits[penalty] = beta
        probability = np.clip(_probability(basis[validation], beta), 1e-9, 1 - 1e-9)
        loss = -float(
            np.mean(
                target[validation] * np.log(probability)
                + (1 - target[validation]) * np.log(1 - probability)
            )
        )
        scores.append({"penalty": penalty, "validation_log_loss": loss})
    selected = min(scores, key=lambda row: (row["validation_log_loss"], row["penalty"]))["penalty"]
    probability = _probability(basis, fits[selected])
    return probability, {
        "selected_penalty": selected,
        "validation_grid": scores,
        "transform": transform,
        "train_labels": int(train.sum()),
        "validation_labels": int(validation.sum()),
        "train_positive_rate": float(target[train].mean()),
        "validation_positive_rate": float(target[validation].mean()),
        "coefficients": fits[selected].tolist(),
        "label_eligible": label_eligible.tolist(),
    }


def _kalman_path(
    panel: Panel,
    sampling: float,
    horizon_column: int,
    baseline: np.ndarray[Any, Any],
    train: np.ndarray[Any, Any],
    *,
    rho: float,
    q_scale: float,
    start_position: int,
) -> np.ndarray[Any, Any]:
    horizon = HORIZONS_SECONDS[horizon_column]
    x_raw = panel.designs[sampling]
    centre = x_raw[train].mean(axis=0)
    scale = x_raw[train].std(axis=0)
    scale[scale <= 0] = 1.0
    x = (x_raw - centre) / scale
    residual = panel.targets[:, horizon_column] - baseline[:, horizon_column]
    gram = x[train].T @ x[train] + np.eye(x.shape[1])
    beta = np.linalg.solve(gram, x[train].T @ residual[train])
    covariance = np.eye(x.shape[1], dtype=np.float64)
    train_error = residual[train] - x[train] @ beta
    observation_variance = max(float(np.mean(train_error**2)), 1e-6)
    predictions = np.full(len(x), np.nan, dtype=np.float64)
    matured = start_position
    for position in range(start_position, len(x)):
        beta = rho * beta
        covariance = rho * rho * covariance + q_scale * np.eye(x.shape[1])
        now = int(panel.timestamps[position])
        while matured < position and (
            panel.timestamps[matured] + int((CAUSAL_GAP_SECONDS + horizon) * 1e9) <= now
        ):
            row = x[matured]
            innovation_variance = float(row @ covariance @ row + observation_variance)
            gain = covariance @ row / innovation_variance
            beta = beta + gain * (residual[matured] - float(row @ beta))
            covariance = covariance - np.outer(gain, row) @ covariance
            matured += 1
        predictions[position] = baseline[position, horizon_column] + float(x[position] @ beta)
    return predictions


def kalman_predictions(
    panel: Panel,
    baseline: np.ndarray[Any, Any],
    masks: Mapping[str, np.ndarray[Any, Any]],
) -> tuple[np.ndarray[Any, Any], dict[str, Any]]:
    train = masks["train"]
    validation = masks["validation"]
    start = int(np.flatnonzero(validation)[0])
    per_sampling = np.full(
        (len(panel.timestamps), len(HORIZONS_SECONDS), len(SAMPLING_SECONDS)),
        np.nan,
        dtype=np.float64,
    )
    selections: list[dict[str, Any]] = []
    for horizon_column, horizon in enumerate(HORIZONS_SECONDS):
        for sampling_column, sampling in enumerate(SAMPLING_SECONDS):
            candidates: list[dict[str, float]] = []
            paths: dict[tuple[float, float], np.ndarray[Any, Any]] = {}
            for rho in KALMAN_RHOS:
                for q_scale in KALMAN_Q_SCALES:
                    path = _kalman_path(
                        panel,
                        sampling,
                        horizon_column,
                        baseline,
                        train,
                        rho=rho,
                        q_scale=q_scale,
                        start_position=start,
                    )
                    paths[(rho, q_scale)] = path
                    mse = float(
                        np.mean((panel.targets[validation, horizon_column] - path[validation]) ** 2)
                    )
                    candidates.append({"rho": rho, "q_scale": q_scale, "validation_mse": mse})
            chosen = min(
                candidates, key=lambda row: (row["validation_mse"], row["rho"], row["q_scale"])
            )
            per_sampling[:, horizon_column, sampling_column] = paths[
                (chosen["rho"], chosen["q_scale"])
            ]
            selections.append(
                {
                    "sampling_seconds": sampling,
                    "horizon_seconds": horizon,
                    "selected_rho": chosen["rho"],
                    "selected_q_scale": chosen["q_scale"],
                    "validation_grid": candidates,
                }
            )
    return np.nanmedian(per_sampling, axis=2), {"cells": selections}


def metric_bundle(
    actual: np.ndarray[Any, Any], prediction: np.ndarray[Any, Any], baseline: np.ndarray[Any, Any]
) -> dict[str, Any]:
    finite = np.isfinite(actual) & np.isfinite(prediction) & np.isfinite(baseline)
    y, p, b = actual[finite], prediction[finite], baseline[finite]
    error = y - p
    denominator = float(np.sum((y - b) ** 2))
    return {
        "n": int(len(y)),
        "oos_r2_vs_m0": 1.0 - float(np.sum(error**2)) / denominator if denominator > 0 else None,
        "mae_ticks": float(np.mean(np.abs(error))),
        "rmse_ticks": float(np.sqrt(np.mean(error**2))),
        "direction_accuracy": float(np.mean(np.sign(y[y != 0]) == np.sign(p[y != 0])))
        if np.any(y != 0)
        else None,
    }


def _auc(target: np.ndarray[Any, Any], probability: np.ndarray[Any, Any]) -> float | None:
    positive = target == 1
    negative = target == 0
    if not positive.any() or not negative.any():
        return None
    order = np.argsort(probability)
    ranks = np.empty(len(order), dtype=np.float64)
    ranks[order] = np.arange(1, len(order) + 1)
    return float(
        (ranks[positive].sum() - positive.sum() * (positive.sum() + 1) / 2)
        / (positive.sum() * negative.sum())
    )


def gate_diagnostics(
    probability: np.ndarray[Any, Any],
    surface_height: np.ndarray[Any, Any],
    mask: np.ndarray[Any, Any],
) -> dict[str, Any]:
    finite = mask & np.isfinite(surface_height) & np.isfinite(probability)
    p = probability[finite]
    target = (surface_height[finite] > 0).astype(int)
    edges = np.quantile(p, np.linspace(0, 1, 6))
    bins: list[dict[str, Any]] = []
    for index in range(5):
        selected = (p >= edges[index]) & (
            p <= edges[index + 1] if index == 4 else p < edges[index + 1]
        )
        bins.append(
            {
                "quintile": index + 1,
                "n": int(selected.sum()),
                "mean_probability": float(p[selected].mean()) if selected.any() else None,
                "positive_rate": float(target[selected].mean()) if selected.any() else None,
                "mean_future_surface_r2": float(surface_height[finite][selected].mean())
                if selected.any()
                else None,
            }
        )
    return {
        "n": int(finite.sum()),
        "positive_rate": float(target.mean()),
        "brier_score": float(np.mean((p - target) ** 2)),
        "auc": _auc(target, p),
        "probability_quintiles": bins,
    }


def geometry_diagnostics(
    panel: Panel,
    surface_height: np.ndarray[Any, Any],
    mask: np.ndarray[Any, Any],
) -> list[dict[str, Any]]:
    """Post-estimation univariate shape diagnostic; it never selects or refits the gate."""

    finite = mask & np.isfinite(surface_height)
    rows: list[dict[str, Any]] = []
    for column, name in enumerate(GEOMETRY_NAMES):
        values = panel.geometry[finite, column]
        outcome = surface_height[finite]
        edges = np.quantile(values, np.linspace(0, 1, 6))
        quintiles: list[dict[str, Any]] = []
        for index in range(5):
            selected = (values >= edges[index]) & (
                values <= edges[index + 1] if index == 4 else values < edges[index + 1]
            )
            quintiles.append(
                {
                    "quintile": index + 1,
                    "n": int(selected.sum()),
                    "mean_feature": (float(values[selected].mean()) if selected.any() else None),
                    "mean_future_surface_r2": (
                        float(outcome[selected].mean()) if selected.any() else None
                    ),
                    "positive_rate": (
                        float(np.mean(outcome[selected] > 0.0)) if selected.any() else None
                    ),
                }
            )
        rows.append({"feature": name, "quintiles": quintiles})
    return rows


def surface_timeline(
    panel: Panel,
    surface_height: np.ndarray[Any, Any],
    masks: Mapping[str, np.ndarray[Any, Any]],
) -> list[dict[str, Any]]:
    width = int(300 * 1e9)
    split_by_position = np.full(len(panel.timestamps), "purged", dtype=object)
    for name, mask in masks.items():
        split_by_position[mask] = name
    rows: list[dict[str, Any]] = []
    for bucket in np.unique(panel.timestamps // width):
        selected = (panel.timestamps // width == bucket) & np.isfinite(surface_height)
        if not selected.any():
            continue
        split_values, counts = np.unique(split_by_position[selected], return_counts=True)
        split = str(split_values[int(np.argmax(counts))])
        values = surface_height[selected]
        rows.append(
            {
                "bucket_start_ts_ns": int(bucket * width),
                "split": split,
                "n": int(selected.sum()),
                "median_surface_r2": float(np.median(values)),
                "positive_rate": float(np.mean(values > 0.0)),
            }
        )
    return rows


def build_calibration_artifact(observations: Sequence[HorseRaceObservation]) -> dict[str, Any]:
    panel = prepare_panel(observations)
    masks = split_masks(panel.timestamps)
    if any(int(mask.sum()) < 100 for mask in masks.values()):
        raise ValueError("D50 split support is insufficient")
    penalties = select_ridge_penalties(panel, masks["train"])
    cell_predictions, cell_baselines, m0, m1 = rolling_surface_predictions(panel, penalties)
    surface_height = future_surface_height(panel, cell_predictions, cell_baselines)
    gate_probability, gate_fit = fit_gate(panel, surface_height, masks)
    m2, kalman_fit = kalman_predictions(panel, m0, masks)
    predictions = {
        "M0": m0,
        "M1": m1,
        "M2": m2,
        "M3": m0 + gate_probability[:, None] * (m1 - m0),
        "M4": m0 + gate_probability[:, None] * (m2 - m0),
    }
    metrics = {
        split: {
            model: metric_bundle(panel.targets[mask], value[mask], m0[mask])
            for model, value in predictions.items()
        }
        for split, mask in masks.items()
        if split in {"validation", "test"}
    }
    metrics_by_horizon = {
        split: {
            model: {
                f"h{horizon:g}": metric_bundle(
                    panel.targets[mask, column],
                    value[mask, column],
                    m0[mask, column],
                )
                for column, horizon in enumerate(HORIZONS_SECONDS)
            }
            for model, value in predictions.items()
        }
        for split, mask in masks.items()
        if split in {"validation", "test"}
    }
    shrinkage: dict[str, Any] = {}
    for name, prediction in (("M1", m1), ("M2", m2)):
        validation_rows: list[dict[str, Any]] = []
        for value in SHRINKAGES:
            shrunk = m0 + value * (prediction - m0)
            result = metric_bundle(
                panel.targets[masks["validation"]],
                shrunk[masks["validation"]],
                m0[masks["validation"]],
            )
            validation_rows.append({"shrinkage": value, **result})
        selected = max(
            validation_rows,
            key=lambda row: (
                row["oos_r2_vs_m0"] if row["oos_r2_vs_m0"] is not None else -np.inf,
                -row["shrinkage"],
            ),
        )
        test_prediction = m0 + selected["shrinkage"] * (prediction - m0)
        shrinkage[name] = {
            "selected": selected["shrinkage"],
            "validation_grid": validation_rows,
            "test": metric_bundle(
                panel.targets[masks["test"]], test_prediction[masks["test"]], m0[masks["test"]]
            ),
        }
    eligible = np.asarray(gate_fit.pop("label_eligible"), dtype=bool)
    geometry_support = {
        name: {
            "minimum": float(np.min(panel.geometry[:, column])),
            "maximum": float(np.max(panel.geometry[:, column])),
        }
        for column, name in enumerate(GEOMETRY_NAMES)
    }
    for name in (
        "depth_coherence",
        "touch_concentration",
        "multiscale_agreement",
        "ofi_persistence_60s",
    ):
        if (
            geometry_support[name]["minimum"] < -1e-12
            or geometry_support[name]["maximum"] > 1.0 + 1e-12
        ):
            raise ValueError(f"D50 terminal geometry invariant failed for {name}")
    return {
        "schema_version": "1.0.0",
        "specification_id": SPECIFICATION_ID,
        "confirmatory_eligible": False,
        "sample_role": "same_day_exploratory_chronological_calibration",
        "axes": {
            "training_windows_seconds": list(TRAINING_WINDOWS_SECONDS),
            "sampling_seconds": list(SAMPLING_SECONDS),
            "horizons_seconds": list(HORIZONS_SECONDS),
        },
        "support": {
            "cadence_rows": len(panel.timestamps),
            **{name: int(mask.sum()) for name, mask in masks.items()},
            "first_ts_ns": int(panel.timestamps[0]),
            "last_ts_ns": int(panel.timestamps[-1]),
        },
        "ridge_penalties": {
            f"s{sampling:g}|h{horizon:g}": value for (sampling, horizon), value in penalties.items()
        },
        "gate": {
            **gate_fit,
            "geometry_names": list(GEOMETRY_NAMES),
            "test": gate_diagnostics(gate_probability, surface_height, masks["test"] & eligible),
        },
        "geometry_support": geometry_support,
        "kalman": kalman_fit,
        "metrics": metrics,
        "metrics_by_horizon": metrics_by_horizon,
        "constant_shrinkage_falsifier": shrinkage,
        "test_surface": {
            "median_future_r2": float(np.nanmedian(surface_height[masks["test"] & eligible])),
            "positive_rate": float(np.mean(surface_height[masks["test"] & eligible] > 0)),
            "n": int((masks["test"] & eligible).sum()),
        },
        "post_estimation_diagnostics": {
            "geometry_test_quintiles": geometry_diagnostics(
                panel, surface_height, masks["test"] & eligible
            ),
            "surface_timeline_5m": surface_timeline(panel, surface_height, masks),
            "model_selection_effect": "none; these diagnostics were not used to refit models",
        },
        "causal_checks": {
            "five_second_clock": True,
            "mature_labels_only_in_rolling_fit": True,
            "delayed_kalman_updates": True,
            "gate_future_labels_excluded_at_split_edges": True,
            "test_selected_hyperparameters": False,
        },
        "order_entry_enabled": False,
    }
