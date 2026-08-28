"""Shared evaluator for independently generated recent intraday-alpha families."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from shaurya.research.intraday_alpha_tournament import (
    MODEL_FEATURES,
    _models,
    daily_pnl,
    rule_positions,
    strategy_metric,
)

VALIDATION_START = pd.Timestamp("2026-07-01")
VALIDATION_END = pd.Timestamp("2026-08-14")
FINAL_START = pd.Timestamp("2026-08-17")
COSTS_BPS = (0.0, 0.25, 0.5, 1.0, 2.0, 6.0)
PRIMARY_COST_BPS = 1.0
FloatArray = npt.NDArray[np.float64]


def baseline_candidates(
    panel: pd.DataFrame,
) -> tuple[dict[str, FloatArray], dict[str, str]]:
    """Create the original rule family plus discovery-fitted return models."""
    candidates = {
        f"baseline__{name}": np.asarray(position, dtype=float)
        for name, position in rule_positions(panel).items()
    }
    families = {name: "baseline_rules" for name in candidates}
    discovery = panel[panel["date"] <= pd.Timestamp("2026-06-30")]
    for model_name, model in _models().items():
        model.fit(discovery[MODEL_FEATURES], discovery["forward_return_bps"])
        discovery_prediction = np.asarray(model.predict(discovery[MODEL_FEATURES]), dtype=float)
        prediction = np.asarray(model.predict(panel[MODEL_FEATURES]), dtype=float)
        for participation in (0.10, 0.25, 0.50, 1.00):
            threshold = float(np.quantile(np.abs(discovery_prediction), 1.0 - participation))
            name = f"baseline_model__{model_name}__p{participation:g}"
            candidates[name] = np.where(np.abs(prediction) >= threshold, np.sign(prediction), 0.0)
            families[name] = "baseline_return_models"
    return candidates, families


def holm_passes(p_values: dict[str, float], alpha: float = 0.05) -> set[str]:
    """Return hypotheses passing Holm's step-down familywise correction."""
    ordered = sorted(p_values, key=p_values.get)  # type: ignore[arg-type]
    passed: set[str] = set()
    for rank, name in enumerate(ordered):
        if p_values[name] <= alpha / (len(ordered) - rank):
            passed.add(name)
        else:
            break
    return passed


def _position_fingerprint(position: FloatArray) -> str:
    normalized = np.asarray(position, dtype="<f8")
    return hashlib.sha256(normalized.tobytes()).hexdigest()[:16]


def validate_positions(panel: pd.DataFrame, candidates: dict[str, FloatArray]) -> None:
    """Reject malformed, leveraged, or duplicate candidate identifiers."""
    if not candidates:
        raise ValueError("candidate registry is empty")
    for name, position in candidates.items():
        values = np.asarray(position, dtype=float)
        if not name or len(values) != len(panel):
            raise ValueError(f"invalid candidate alignment: {name!r}")
        if not np.isfinite(values).all() or np.abs(values).max(initial=0.0) > 1.0:
            raise ValueError(f"invalid candidate positions: {name!r}")


def evaluate_parallel_candidates(
    panel: pd.DataFrame,
    candidates: dict[str, FloatArray],
    family_by_candidate: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a frozen registry on validation and the final five-day confirmation slice."""
    validate_positions(panel, candidates)
    missing_family = set(candidates).difference(family_by_candidate)
    if missing_family:
        raise ValueError(f"missing candidate families: {sorted(missing_family)}")
    validation_mask = panel["date"].between(VALIDATION_START, VALIDATION_END).to_numpy()
    final_mask = (panel["date"] >= FINAL_START).to_numpy()
    results: dict[str, Any] = {}
    for name, full_position in candidates.items():
        position = np.asarray(full_position, dtype=float)
        validation_costs: dict[str, Any] = {}
        for cost in COSTS_BPS:
            validation_costs[f"cost_{cost:g}bps"] = asdict(
                strategy_metric(
                    daily_pnl(panel.loc[validation_mask], position[validation_mask], cost)
                )
            )
        results[name] = {
            "family": family_by_candidate[name],
            "fingerprint": _position_fingerprint(position),
            "active_fraction": float(np.mean(position != 0.0)),
            "results": {"validation": validation_costs},
        }

    primary_key = f"cost_{PRIMARY_COST_BPS:g}bps"
    p_values = {
        name: value["results"]["validation"][primary_key]["one_sided_p"]
        for name, value in results.items()
    }
    corrected = holm_passes(p_values)
    validation_survivors = sorted(
        name
        for name in corrected
        if results[name]["results"]["validation"][primary_key]["mean_daily_bps"] > 0
    )
    # Only corrected, profitable validation survivors may expose final returns.
    for name in validation_survivors:
        final_costs: dict[str, Any] = {}
        position = np.asarray(candidates[name], dtype=float)
        for cost in COSTS_BPS:
            final_costs[f"cost_{cost:g}bps"] = asdict(
                strategy_metric(daily_pnl(panel.loc[final_mask], position[final_mask], cost))
            )
        results[name]["results"]["final_week"] = final_costs
    final_survivors = sorted(
        name
        for name in validation_survivors
        if results[name]["results"]["final_week"][primary_key]["mean_daily_bps"] > 0
    )
    ranked = sorted(
        candidates,
        key=lambda name: results[name]["results"]["validation"][primary_key]["mean_daily_bps"],
        reverse=True,
    )
    return {
        "protocol": {
            "validation": "2026-07-01 through 2026-08-14",
            "final_confirmation": "2026-08-17 through 2026-08-21",
            "primary_round_trip_cost_bps": PRIMARY_COST_BPS,
            "cost_ladder_bps": COSTS_BPS,
            "multiple_testing": "Holm one-sided familywise correction across all candidates",
            "return_proxy": "NIFTY index return; no futures fills or basis in source data",
        },
        "registry": results,
        "summary": {
            "candidate_count": len(results),
            "families": sorted(set(family_by_candidate.values())),
            "holm_validation_passes": sorted(corrected),
            "validation_survivors": validation_survivors,
            "final_survivors": final_survivors,
            "top_validation_candidates": ranked[:10],
            "verdict": (
                "candidate survived validation and final confirmation"
                if final_survivors
                else "no candidate survived the shared protocol"
            ),
        },
    }
