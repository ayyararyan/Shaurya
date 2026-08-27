"""Time-varying alpha stability, decay and structural-break diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class StabilitySummary:
    observations: int
    sign_stability: float | None
    coefficient_stability: float | None
    rank_stability: float | None
    cross_day_persistence: float | None
    rolling_degradation: float | None
    estimated_half_life_sessions: float | None
    structural_break_score: float | None
    structural_break_detected: bool


def _correlation(
    left: Sequence[float] | NDArray[np.float64],
    right: Sequence[float] | NDArray[np.float64],
) -> float | None:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def stability_summary(
    scores: Sequence[float], *, coefficients: Sequence[float] | None = None
) -> StabilitySummary:
    if not scores:
        return StabilitySummary(0, None, None, None, None, None, None, None, False)
    values = np.asarray(scores, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("stability scores must be finite")
    nonzero = values[values != 0]
    sign = float(max(np.mean(nonzero > 0), np.mean(nonzero < 0))) if len(nonzero) else None
    persistence = _correlation(values[:-1], values[1:]) if len(values) > 3 else None
    midpoint = len(values) // 2
    degradation = (
        float(np.mean(values[midpoint:]) - np.mean(values[:midpoint])) if midpoint else None
    )
    absolute = np.abs(values)
    half_life: float | None = None
    positive = np.flatnonzero(absolute > 0)
    if len(positive) >= 3:
        x = positive.astype(np.float64)
        slope = float(np.polyfit(x, np.log(absolute[positive]), 1)[0])
        if slope < 0:
            half_life = log(2.0) / -slope
    centered = values - float(np.mean(values))
    denominator = float(np.std(values)) * max(1.0, np.sqrt(len(values)))
    cusum = float(np.max(np.abs(np.cumsum(centered))) / denominator) if denominator else 0.0
    coefficients_array = np.asarray(coefficients if coefficients is not None else scores)
    coefficient_stability = (
        1.0 / (1.0 + float(np.std(coefficients_array))) if len(coefficients_array) else None
    )
    ranks = np.argsort(np.argsort(values)).astype(np.float64)
    rank_stability = _correlation(ranks[:-1], ranks[1:]) if len(ranks) > 3 else None
    return StabilitySummary(
        len(values),
        sign,
        coefficient_stability,
        rank_stability,
        persistence,
        degradation,
        half_life,
        cusum,
        cusum > 1.25,
    )


def regime_comparison(
    global_scores: Sequence[float], regime_scores: Mapping[str, Sequence[float]], *, minimum_n: int
) -> Mapping[str, object]:
    """Require causal regime labels from the caller and make complexity earn OOS value."""

    if not global_scores:
        raise ValueError("global OOS scores are required")
    global_mean = float(np.mean(global_scores))
    rows: dict[str, object] = {}
    weighted = 0.0
    support = 0
    for regime, values in sorted(regime_scores.items()):
        if len(values) < minimum_n:
            rows[regime] = {"status": "insufficient_support", "n": len(values)}
            continue
        mean = float(np.mean(values))
        rows[regime] = {"status": "eligible", "n": len(values), "mean_oos_score": mean}
        weighted += len(values) * mean
        support += len(values)
    conditioned = weighted / support if support else None
    return {
        "global_mean_oos_score": global_mean,
        "conditioned_mean_oos_score": conditioned,
        "conditioned_earns_complexity": conditioned is not None and conditioned > global_mean,
        "regimes": rows,
    }
