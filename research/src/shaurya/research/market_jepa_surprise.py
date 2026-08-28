"""Leakage-safe JEPA latent prediction-error diagnostics.

The primitives here deliberately accept already-computed latent vectors.  Model
execution lives in the experiment runner, while this module owns the alignment,
normalisation, quintile, and block-bootstrap contracts that are easy to test.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def aligned_latent_surprise(
    predictions: FloatArray,
    realizations: FloatArray,
    prediction_ends: IntArray,
    realization_ends: IntArray,
    horizon_steps: int,
) -> dict[str, FloatArray]:
    """Return raw/unit-L2 and cosine surprise after enforcing exact alignment.

    A prediction made at row ``e`` may only be compared with the target-encoder
    realization at ``e + horizon_steps``.  Passing independently aligned arrays
    makes the no-look-ahead contract explicit and testable.
    """
    if horizon_steps <= 0:
        raise ValueError("horizon_steps must be positive")
    if predictions.ndim != 2 or realizations.ndim != 2:
        raise ValueError("predictions and realizations must be two-dimensional")
    if predictions.shape != realizations.shape:
        raise ValueError("prediction and realization shapes differ")
    if len(predictions) != len(prediction_ends) or len(predictions) != len(realization_ends):
        raise ValueError("latent arrays and endpoint arrays differ in length")
    if not np.array_equal(prediction_ends + horizon_steps, realization_ends):
        raise ValueError("prediction/realization endpoint alignment is not causal")
    if not np.all(np.isfinite(predictions)) or not np.all(np.isfinite(realizations)):
        raise ValueError("latent vectors must be finite")

    raw = np.linalg.norm(realizations - predictions, axis=1)
    prediction_norm = np.linalg.norm(predictions, axis=1, keepdims=True)
    realization_norm = np.linalg.norm(realizations, axis=1, keepdims=True)
    unit_prediction = predictions / np.maximum(prediction_norm, 1e-12)
    unit_realization = realizations / np.maximum(realization_norm, 1e-12)
    unit_l2 = np.linalg.norm(unit_realization - unit_prediction, axis=1)
    cosine = 1.0 - np.sum(unit_realization * unit_prediction, axis=1)
    return {
        "l2": raw.astype(np.float64),
        "unit_l2": unit_l2.astype(np.float64),
        "cosine": np.clip(cosine, 0.0, 2.0).astype(np.float64),
        "prediction_norm": prediction_norm[:, 0].astype(np.float64),
        "realization_norm": realization_norm[:, 0].astype(np.float64),
    }


def spearman_statistic(left: FloatArray, right: FloatArray) -> float:
    """Spearman correlation without IID assumptions or scipy warning noise."""
    finite = np.isfinite(left) & np.isfinite(right)
    if finite.sum() < 3:
        return float("nan")
    left_rank = rankdata(left[finite])
    right_rank = rankdata(right[finite])
    if np.std(left_rank) <= 0.0 or np.std(right_rank) <= 0.0:
        return float("nan")
    return float(np.corrcoef(left_rank, right_rank)[0, 1])


def block_bootstrap_spearman(
    signal: FloatArray,
    target: FloatArray,
    *,
    block_rows: int,
    draws: int = 1000,
    seed: int = 20260828,
) -> dict[str, Any]:
    """Moving-block bootstrap interval for an overlapping-sample rank correlation."""
    if block_rows <= 0 or draws <= 0:
        raise ValueError("block_rows and draws must be positive")
    if len(signal) != len(target):
        raise ValueError("signal and target lengths differ")
    finite = np.isfinite(signal) & np.isfinite(target)
    clean_signal = signal[finite]
    clean_target = target[finite]
    if len(clean_signal) < max(12, 2 * block_rows):
        raise ValueError("insufficient finite rows for block bootstrap")
    ranked_signal = rankdata(clean_signal).astype(np.float64)
    ranked_target = rankdata(clean_target).astype(np.float64)
    starts = np.arange(0, len(clean_signal) - block_rows + 1)
    signal_blocks = np.stack(
        [ranked_signal[start : start + block_rows] for start in starts], axis=0
    )
    target_blocks = np.stack(
        [ranked_target[start : start + block_rows] for start in starts], axis=0
    )
    block_moments = np.column_stack(
        (
            signal_blocks.sum(axis=1),
            target_blocks.sum(axis=1),
            np.square(signal_blocks).sum(axis=1),
            np.square(target_blocks).sum(axis=1),
            (signal_blocks * target_blocks).sum(axis=1),
        )
    )
    blocks_needed = int(np.ceil(len(clean_signal) / block_rows))
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(starts), size=(draws, blocks_needed))
    moments = block_moments[selected].sum(axis=1)
    sample_size = float(blocks_needed * block_rows)
    covariance = moments[:, 4] - moments[:, 0] * moments[:, 1] / sample_size
    signal_variance = moments[:, 2] - np.square(moments[:, 0]) / sample_size
    target_variance = moments[:, 3] - np.square(moments[:, 1]) / sample_size
    estimates = np.divide(
        covariance,
        np.sqrt(np.maximum(signal_variance * target_variance, 0.0)),
        out=np.full(draws, np.nan, dtype=np.float64),
        where=(signal_variance > 0.0) & (target_variance > 0.0),
    )
    estimates = estimates[np.isfinite(estimates)]
    if not len(estimates):
        raise ValueError("bootstrap produced no finite estimates")
    return {
        "spearman": spearman_statistic(clean_signal, clean_target),
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "block_rows": int(block_rows),
        "draws": int(draws),
        "samples": int(len(clean_signal)),
    }


def development_quantile_edges(values: FloatArray, bins: int = 5) -> FloatArray:
    """Fit deterministic bin edges on development values only."""
    finite = values[np.isfinite(values)]
    if bins < 2 or len(finite) < bins * 5:
        raise ValueError("insufficient development values for quantile edges")
    edges = np.quantile(finite, np.linspace(0.0, 1.0, bins + 1)[1:-1])
    if len(np.unique(edges)) != len(edges):
        raise ValueError("development quantile edges are not unique")
    return np.asarray(edges, dtype=np.float64)


def conditional_means_by_development_quintile(
    development_signal: FloatArray,
    test_signal: FloatArray,
    test_target: FloatArray,
) -> dict[str, Any]:
    """Apply discovery/validation-fitted quintiles to a diagnostic session."""
    if len(test_signal) != len(test_target):
        raise ValueError("test signal and target lengths differ")
    edges = development_quantile_edges(development_signal, bins=5)
    labels = np.digitize(test_signal, edges, right=False)
    rows: list[dict[str, Any]] = []
    means: list[float] = []
    for quintile in range(5):
        finite = (labels == quintile) & np.isfinite(test_signal) & np.isfinite(test_target)
        mean = float(np.mean(test_target[finite])) if finite.any() else float("nan")
        means.append(mean)
        rows.append(
            {
                "quintile": quintile + 1,
                "samples": int(finite.sum()),
                "signal_mean": float(np.mean(test_signal[finite])) if finite.any() else None,
                "target_mean": mean if np.isfinite(mean) else None,
            }
        )
    finite_means = np.asarray([value for value in means if np.isfinite(value)])
    monotonic = bool(
        len(finite_means) == 5
        and (np.all(np.diff(finite_means) >= 0.0) or np.all(np.diff(finite_means) <= 0.0))
    )
    return {"edges": edges.tolist(), "rows": rows, "monotonic": monotonic}
