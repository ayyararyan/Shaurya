"""Continuous JEPA trajectory and cross-seed uncertainty primitives."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def contiguous_analysis_ends(
    timestamps: IntArray,
    *,
    history_steps: int,
    future_steps: int,
    step_ns: int,
    minimum_samples: int = 50,
) -> IntArray:
    """Return endpoints with complete history/future windows or reject the session."""
    if timestamps.ndim != 1 or np.any(np.diff(timestamps) <= 0):
        raise ValueError("timestamps must be a strictly increasing one-dimensional array")
    if min(history_steps, future_steps, step_ns, minimum_samples) <= 0:
        raise ValueError("window, cadence, and minimum sample arguments must be positive")
    valid: list[int] = []
    for end in range(history_steps, len(timestamps) - future_steps):
        window = timestamps[end - history_steps : end + future_steps + 1]
        if np.all(np.diff(window) == step_ns):
            valid.append(end)
    ends = np.asarray(valid, dtype=np.int64)
    if len(ends) < minimum_samples:
        raise ValueError("incomplete session: insufficient contiguous analysis endpoints")
    return ends


def _endpoint_lookup(ends: IntArray) -> dict[int, int]:
    if ends.ndim != 1 or len(np.unique(ends)) != len(ends):
        raise ValueError("ends must be a one-dimensional unique array")
    return {int(end): position for position, end in enumerate(ends)}


def latent_dynamics(
    embedding: FloatArray,
    ends: IntArray,
    evaluation_ends: IntArray,
    lag_steps: int,
) -> dict[str, FloatArray]:
    """Compute velocity, acceleration, and curvature at exact endpoint lags."""
    if embedding.ndim != 2 or len(embedding) != len(ends):
        raise ValueError("embedding and ends are misaligned")
    if lag_steps <= 0:
        raise ValueError("lag_steps must be positive")
    lookup = _endpoint_lookup(ends)
    current_positions: list[int] = []
    prior_positions: list[int] = []
    twice_prior_positions: list[int] = []
    for end in evaluation_ends:
        current = lookup.get(int(end))
        prior = lookup.get(int(end) - lag_steps)
        twice_prior = lookup.get(int(end) - 2 * lag_steps)
        if current is None or prior is None or twice_prior is None:
            raise ValueError("evaluation endpoint lacks an exact latent-history lag")
        current_positions.append(current)
        prior_positions.append(prior)
        twice_prior_positions.append(twice_prior)
    current_values = embedding[np.asarray(current_positions)]
    prior_values = embedding[np.asarray(prior_positions)]
    twice_prior_values = embedding[np.asarray(twice_prior_positions)]
    latest_move = current_values - prior_values
    earlier_move = prior_values - twice_prior_values
    velocity = np.linalg.norm(latest_move, axis=1)
    acceleration = np.linalg.norm(latest_move - earlier_move, axis=1)
    denominator = np.linalg.norm(latest_move, axis=1) * np.linalg.norm(earlier_move, axis=1)
    cosine = np.divide(
        np.sum(latest_move * earlier_move, axis=1),
        denominator,
        out=np.ones_like(denominator),
        where=denominator > 1e-12,
    )
    curvature = np.clip(1.0 - cosine, 0.0, 2.0)
    return {
        "velocity": velocity.astype(np.float64),
        "acceleration": acceleration.astype(np.float64),
        "curvature": curvature.astype(np.float64),
    }


@dataclass(frozen=True)
class OrthogonalAlignment:
    """Affine orthogonal map from one seed's latent coordinates to a reference."""

    source_mean: FloatArray
    reference_mean: FloatArray
    rotation: FloatArray

    def transform(self, values: FloatArray) -> FloatArray:
        if values.ndim != 2 or values.shape[1] != len(self.source_mean):
            raise ValueError("latent alignment feature dimension mismatch")
        return ((values - self.source_mean) @ self.rotation + self.reference_mean).astype(
            np.float64
        )


def fit_orthogonal_alignment(source: FloatArray, reference: FloatArray) -> OrthogonalAlignment:
    """Fit a Procrustes rotation using development realizations only."""
    if source.shape != reference.shape or source.ndim != 2:
        raise ValueError("source and reference development arrays must have equal 2D shape")
    if len(source) < source.shape[1]:
        raise ValueError("insufficient development rows for latent alignment")
    source_mean = source.mean(axis=0)
    reference_mean = reference.mean(axis=0)
    cross = (source - source_mean).T @ (reference - reference_mean)
    left, _, right = np.linalg.svd(cross, full_matrices=False)
    rotation = left @ right
    return OrthogonalAlignment(source_mean, reference_mean, rotation.astype(np.float64))


def cross_seed_disagreement(aligned_predictions: list[FloatArray]) -> FloatArray:
    """Mean squared distance from the aligned cross-seed prediction centroid."""
    if len(aligned_predictions) < 2:
        raise ValueError("at least two seeds are required")
    shape = aligned_predictions[0].shape
    if any(values.shape != shape for values in aligned_predictions) or len(shape) != 2:
        raise ValueError("aligned seed prediction arrays differ in shape")
    stacked = np.stack(aligned_predictions, axis=0)
    centroid = stacked.mean(axis=0, keepdims=True)
    return np.mean(np.sum(np.square(stacked - centroid), axis=2), axis=0).astype(np.float64)


def fit_stress_thresholds(development: dict[str, FloatArray]) -> dict[str, dict[str, float]]:
    """Fit low/median/high stress thresholds on development rows only."""
    required = {"velocity", "surprise", "uncertainty", "disequilibrium"}
    if set(development) != required:
        raise ValueError(f"stress inputs must be exactly {sorted(required)}")
    thresholds: dict[str, dict[str, float]] = {}
    for name, values in development.items():
        finite = values[np.isfinite(values)]
        if len(finite) < 30:
            raise ValueError(f"insufficient development rows for {name}")
        low, median, high = np.quantile(finite, (0.33, 0.50, 0.67))
        thresholds[name] = {"low": float(low), "median": float(median), "high": float(high)}
    return thresholds


def classify_stress_states(
    values: dict[str, FloatArray], thresholds: dict[str, dict[str, float]]
) -> NDArray[np.str_]:
    """Apply interpretable, priority-ordered stress states without forced clustering."""
    required = {"velocity", "surprise", "uncertainty", "disequilibrium"}
    if set(values) != required or set(thresholds) != required:
        raise ValueError("stress value/threshold keys differ from the frozen contract")
    lengths = {len(item) for item in values.values()}
    if len(lengths) != 1:
        raise ValueError("stress inputs differ in length")
    v, s, u, d = (
        values[name] for name in ("velocity", "surprise", "uncertainty", "disequilibrium")
    )
    labels = np.full(len(v), "unclassified", dtype="U32")
    finite = np.isfinite(v) & np.isfinite(s) & np.isfinite(u) & np.isfinite(d)
    low = {name: thresholds[name]["low"] for name in required}
    median = {name: thresholds[name]["median"] for name in required}
    high = {name: thresholds[name]["high"] for name in required}
    stable = (
        finite
        & (v <= low["velocity"])
        & (s <= low["surprise"])
        & (u <= low["uncertainty"])
        & (d <= low["disequilibrium"])
    )
    labels[stable] = "stable"
    information = (
        finite & (v >= high["velocity"]) & (s >= high["surprise"]) & (u >= high["uncertainty"])
    )
    labels[information] = "information_shock"
    cross_market = finite & (d >= high["disequilibrium"]) & (s >= median["surprise"])
    labels[(labels == "unclassified") & cross_market] = "cross_market_dislocation"
    hidden = finite & (v <= low["velocity"]) & (s >= high["surprise"])
    labels[(labels == "unclassified") & hidden] = "hidden_disturbance"
    ambiguous = finite & (u >= high["uncertainty"]) & (v <= low["velocity"])
    labels[(labels == "unclassified") & ambiguous] = "ambiguous_state"
    orderly = finite & (v >= high["velocity"]) & (s <= low["surprise"])
    labels[(labels == "unclassified") & orderly] = "orderly_transition"
    return labels


def write_frozen_config(path: Path, payload: dict[str, Any]) -> None:
    """Serialize a JSON-safe frozen plan deterministically and without overwrite."""
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen config: {path}")

    def convert(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        if hasattr(value, "__dataclass_fields__"):
            return convert(asdict(value))
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        return value

    path.write_text(json.dumps(convert(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
