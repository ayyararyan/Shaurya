"""Mechanism-level evidence aggregation without pretending related cells are independent."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

import numpy as np


@dataclass(frozen=True, slots=True)
class MechanismSummary:
    mechanism: str
    current_evidence: float | None
    historical_evidence: float | None
    sign: int | None
    effect_range: tuple[float, float] | None
    parameter_region: tuple[str, ...]
    stability: float | None
    decay: float | None
    current_confidence: float | None
    supporting_feature_count: int
    contradictory_feature_count: int


def summarize_mechanism(
    mechanism: str,
    current_effects: Mapping[str, float],
    historical_effects: Mapping[str, Sequence[float]],
    *,
    adjusted_p_values: Mapping[str, float] | None = None,
) -> MechanismSummary:
    if not current_effects:
        return MechanismSummary(mechanism, None, None, None, None, (), None, None, None, 0, 0)
    if not all(isfinite(value) for value in current_effects.values()):
        raise ValueError("mechanism effects must be finite")
    values = np.asarray([current_effects[key] for key in sorted(current_effects)], dtype=np.float64)
    current = float(np.mean(values))
    sign = 1 if current > 0 else -1 if current < 0 else 0
    supporting = int(sum(bool((value > 0) == (sign > 0)) for value in values if value != 0))
    contradictory = int(
        sum(bool((value > 0) != (sign > 0)) for value in values if value != 0)
    )
    histories = [
        value for key in sorted(historical_effects) for value in historical_effects[key]
    ]
    historical = float(np.mean(histories)) if histories else None
    decay = current - historical if historical is not None else None
    per_feature_stability = [
        1.0 / (1.0 + float(np.std(historical_effects[key])))
        for key in sorted(historical_effects)
        if historical_effects[key]
    ]
    confidence = (
        1.0
        - float(np.median([adjusted_p_values[key] for key in sorted(adjusted_p_values)]))
        if adjusted_p_values
        else None
    )
    maximum = max(abs(value) for value in current_effects.values())
    region = tuple(
        sorted(name for name, value in current_effects.items() if abs(value) >= 0.85 * maximum)
    )
    return MechanismSummary(
        mechanism,
        current,
        historical,
        sign,
        (float(np.min(values)), float(np.max(values))),
        region,
        float(np.mean(per_feature_stability)) if per_feature_stability else None,
        decay,
        confidence,
        supporting,
        contradictory,
    )
