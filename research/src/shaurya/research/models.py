"""Dependency-light shrinkage and past-only adaptive models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

import numpy as np

from shaurya.research.contracts import canonical_sha256


@dataclass(frozen=True, slots=True)
class RidgeModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[float, ...]
    penalty: float
    training_fingerprint: str


def fit_ridge(
    rows: Sequence[Mapping[str, float | None]],
    targets: Sequence[float],
    *,
    feature_names: Sequence[str],
    penalty: float = 1.0,
) -> RidgeModel:
    """Fit all normalization and coefficients exclusively from supplied training rows."""

    names = tuple(feature_names)
    if not rows or len(rows) != len(targets) or not names:
        raise ValueError("aligned non-empty training rows, targets and features are required")
    if penalty < 0 or not isfinite(penalty):
        raise ValueError("ridge penalty must be finite and non-negative")
    matrix_values: list[list[float]] = []
    for row in rows:
        output_row: list[float] = []
        for name in names:
            value = row.get(name)
            output_row.append(np.nan if value is None else float(value))
        matrix_values.append(output_row)
    matrix = np.asarray(matrix_values, dtype=np.float64)
    y = np.asarray(targets, dtype=np.float64)
    if not np.isfinite(y).all():
        raise ValueError("training targets must be finite")
    means_array = np.nanmedian(matrix, axis=0)
    means_array = np.where(np.isfinite(means_array), means_array, 0.0)
    filled = np.where(np.isfinite(matrix), matrix, means_array)
    scales_array = np.std(filled, axis=0)
    scales_array = np.where(scales_array > 0, scales_array, 1.0)
    design = (filled - means_array) / scales_array
    centered_y = y - float(np.mean(y))
    gram = design.T @ design + penalty * np.eye(len(names))
    coefficients = np.linalg.solve(gram, design.T @ centered_y)
    payload = {
        "rows": [[row.get(name) for name in names] for row in rows],
        "targets": list(targets),
        "features": names,
        "penalty": penalty,
    }
    return RidgeModel(
        names,
        tuple(float(value) for value in means_array),
        tuple(float(value) for value in scales_array),
        float(np.mean(y)),
        tuple(float(value) for value in coefficients),
        penalty,
        canonical_sha256(payload),
    )


def predict_ridge(
    model: RidgeModel, rows: Sequence[Mapping[str, float | None]]
) -> tuple[float, ...]:
    matrix_values: list[list[float]] = []
    for row in rows:
        output_row: list[float] = []
        for name in model.feature_names:
            value = row.get(name)
            output_row.append(np.nan if value is None else float(value))
        matrix_values.append(output_row)
    matrix = np.asarray(matrix_values, dtype=np.float64)
    means = np.asarray(model.means)
    filled = np.where(np.isfinite(matrix), matrix, means)
    predictions = model.intercept + (filled - means) / np.asarray(model.scales) @ np.asarray(
        model.coefficients
    )
    return tuple(float(value) for value in predictions)


def family_shrinkage(
    effects: Mapping[str, float], standard_errors: Mapping[str, float], *, prior_variance: float
) -> dict[str, float]:
    """Independent empirical-Bayes normal shrinkage toward the family zero prior."""

    if prior_variance < 0 or not isfinite(prior_variance):
        raise ValueError("prior_variance must be finite and non-negative")
    if set(effects) != set(standard_errors):
        raise ValueError("effects and standard errors must cover the same hypotheses")
    result: dict[str, float] = {}
    for identity in sorted(effects):
        error = standard_errors[identity]
        if error < 0 or not isfinite(error):
            raise ValueError("standard errors must be finite and non-negative")
        weight = 0.0 if prior_variance == 0 else prior_variance / (prior_variance + error**2)
        result[identity] = weight * effects[identity]
    return result


def past_only_ensemble_weights(
    historical_scores: Mapping[str, Sequence[float]], *, temperature: float = 1.0
) -> dict[str, float]:
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    names = sorted(historical_scores)
    if not names or any(not values for values in historical_scores.values()):
        raise ValueError("every model requires past scores")
    means = np.asarray([np.mean(historical_scores[name]) for name in names], dtype=np.float64)
    logits = (means - float(np.max(means))) / temperature
    weights = np.exp(logits)
    weights /= np.sum(weights)
    return {name: float(weight) for name, weight in zip(names, weights, strict=True)}


@dataclass(frozen=True, slots=True)
class ExponentiallyWeightedEstimate:
    value: float
    weight: float
    observations: int


def update_ew_estimate(
    previous: ExponentiallyWeightedEstimate | None, value: float, *, decay: float
) -> ExponentiallyWeightedEstimate:
    if not 0 < decay <= 1 or not isfinite(value):
        raise ValueError("value must be finite and decay must lie in (0, 1]")
    if previous is None:
        return ExponentiallyWeightedEstimate(value, 1.0, 1)
    return ExponentiallyWeightedEstimate(
        decay * value + (1 - decay) * previous.value,
        decay + (1 - decay) * previous.weight,
        previous.observations + 1,
    )
