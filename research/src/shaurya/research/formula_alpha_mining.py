"""Constrained, auditable formula-alpha mining on the NIFTY tournament panel.

The grammar is intentionally tiny.  It contains only frozen empirical ranks, binary sums or
products, and an explicit sign.  All transformations and participation thresholds are fit on
the discovery window; validation chooses at most one formula, and only that frozen formula is
scored on the final window.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from shaurya.research.intraday_alpha_tournament import daily_pnl, strategy_metric

FloatArray = npt.NDArray[np.float64]

DISCOVERY_START = pd.Timestamp("2025-09-01")
DISCOVERY_END = pd.Timestamp("2026-06-30")
VALIDATION_START = pd.Timestamp("2026-07-01")
VALIDATION_END = pd.Timestamp("2026-08-14")
FINAL_START = pd.Timestamp("2026-08-17")
FINAL_END = pd.Timestamp("2026-08-21")
ROUND_TRIP_COST_BPS = 6.0
PARTICIPATION = 0.10
MAX_FORMULAS = 96
MAX_COMPLEXITY = 6
MAX_VALIDATION_CANDIDATES = 12

# These are all computed from completed bars by build_tournament_panel.  Volatility is retained
# as one state variable; products let the grammar express simple volatility-conditioned signals.
ATOMIC_FEATURES = (
    "ret_5",
    "ret_15",
    "ret_60",
    "session_return",
    "overnight_gap",
    "rv_30",
)


@dataclass(frozen=True)
class FormulaSpec:
    """One preregistered expression in the bounded grammar."""

    name: str
    operation: Literal["rank", "sum", "product"]
    left: str
    right: str | None
    polarity: Literal[-1, 1]
    complexity: int


@dataclass(frozen=True)
class CandidateSeries:
    """A candidate's causal score and frozen sparse position over the supplied panel."""

    spec: FormulaSpec
    score: FloatArray
    position: FloatArray
    discovery_threshold: float


@dataclass(frozen=True)
class FormulaMiningResult:
    """Formula series plus JSON-safe experiment metadata for a shared tournament."""

    candidates: dict[str, CandidateSeries]
    validation_candidates: tuple[str, ...]
    selected_candidate: str | None
    metadata: dict[str, Any]


def formula_specs() -> tuple[FormulaSpec, ...]:
    """Return the complete preregistered family; no data-dependent formulas are added."""

    unsigned: list[tuple[str, Literal["rank", "sum", "product"], str, str | None, int]] = []
    for feature in ATOMIC_FEATURES:
        unsigned.append((f"rank_{feature}", "rank", feature, None, 2))
    for left_index, left in enumerate(ATOMIC_FEATURES):
        for right_feature in ATOMIC_FEATURES[left_index + 1 :]:
            unsigned.append(
                (f"sum_rank_{left}__{right_feature}", "sum", left, right_feature, 5)
            )
            unsigned.append(
                (
                    f"product_rank_{left}__{right_feature}",
                    "product",
                    left,
                    right_feature,
                    5,
                )
            )

    result: list[FormulaSpec] = []
    polarities: tuple[tuple[Literal[-1, 1], str], ...] = ((1, "positive"), (-1, "negative"))
    for stem, operation, left, right_operand, base_complexity in unsigned:
        for polarity, prefix in polarities:
            complexity = base_complexity + int(polarity == -1)
            result.append(
                FormulaSpec(
                    name=f"{prefix}__{stem}",
                    operation=operation,
                    left=left,
                    right=right_operand,
                    polarity=polarity,
                    complexity=complexity,
                )
            )
    if len(result) > MAX_FORMULAS or any(item.complexity > MAX_COMPLEXITY for item in result):
        raise AssertionError("formula grammar exceeds its preregistered bounds")
    return tuple(result)


def _fit_rank_reference(values: pd.Series) -> FloatArray:
    finite = values.to_numpy(float)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        raise ValueError(f"cannot fit empirical rank for empty feature {values.name!r}")
    return np.sort(finite)


def _frozen_centered_rank(values: pd.Series, reference: FloatArray) -> FloatArray:
    """Map values to [-1, 1] using only a frozen discovery empirical distribution."""

    raw = values.to_numpy(float)
    result = np.zeros(len(raw), dtype=float)
    finite = np.isfinite(raw)
    # Mid-rank search avoids a deterministic positive bias at values equal to training samples.
    left = np.searchsorted(reference, raw[finite], side="left")
    right = np.searchsorted(reference, raw[finite], side="right")
    percentile = (left + right) / (2.0 * len(reference))
    result[finite] = 2.0 * percentile - 1.0
    return np.clip(result, -1.0, 1.0)


def _formula_score(spec: FormulaSpec, ranks: dict[str, FloatArray]) -> FloatArray:
    left = ranks[spec.left]
    if spec.operation == "rank":
        unsigned = left
    else:
        if spec.right is None:
            raise AssertionError("binary formula missing right operand")
        right = ranks[spec.right]
        unsigned = left + right if spec.operation == "sum" else left * right
    return np.asarray(spec.polarity * unsigned, dtype=float)


def _holm_passes(p_values: dict[str, float], alpha: float = 0.05) -> set[str]:
    ordered = sorted(p_values, key=p_values.get)  # type: ignore[arg-type]
    passed: set[str] = set()
    for rank, name in enumerate(ordered):
        if p_values[name] <= alpha / (len(ordered) - rank):
            passed.add(name)
        else:
            break
    return passed


def _metric(frame: pd.DataFrame, position: FloatArray) -> dict[str, Any]:
    return asdict(strategy_metric(daily_pnl(frame, position, ROUND_TRIP_COST_BPS)))


def _window_masks(panel: pd.DataFrame) -> dict[str, npt.NDArray[np.bool_]]:
    dates = pd.to_datetime(panel["date"]).dt.normalize()
    return {
        "discovery": ((dates >= DISCOVERY_START) & (dates <= DISCOVERY_END)).to_numpy(bool),
        "validation": ((dates >= VALIDATION_START) & (dates <= VALIDATION_END)).to_numpy(bool),
        "final": ((dates >= FINAL_START) & (dates <= FINAL_END)).to_numpy(bool),
    }


def mine_formula_alphas(panel: pd.DataFrame) -> FormulaMiningResult:
    """Mine, validate, and finally evaluate a bounded formula family.

    The returned arrays align one-for-one with ``panel``.  Final outcomes influence only the
    selected formula's final metric, never rankings, thresholds, eligibility, or selection.
    """

    required = {"datetime", "date", "forward_return_bps", *ATOMIC_FEATURES}
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ValueError(f"panel is missing required columns: {missing}")
    if not panel["datetime"].is_monotonic_increasing:
        raise ValueError("panel must be sorted by datetime")

    masks = _window_masks(panel)
    for name, mask in masks.items():
        if not mask.any():
            raise ValueError(f"panel has no rows in {name} window")
    discovery = panel.loc[masks["discovery"]].reset_index(drop=True)
    validation = panel.loc[masks["validation"]].reset_index(drop=True)
    final = panel.loc[masks["final"]].reset_index(drop=True)

    references = {
        feature: _fit_rank_reference(panel.loc[masks["discovery"], feature])
        for feature in ATOMIC_FEATURES
    }
    ranks = {
        feature: _frozen_centered_rank(panel[feature], reference)
        for feature, reference in references.items()
    }

    candidates: dict[str, CandidateSeries] = {}
    discovery_metrics: dict[str, dict[str, Any]] = {}
    for spec in formula_specs():
        score = _formula_score(spec, ranks)
        threshold = float(np.quantile(np.abs(score[masks["discovery"]]), 1.0 - PARTICIPATION))
        position = np.where(np.abs(score) >= threshold, np.sign(score), 0.0).astype(float)
        candidates[spec.name] = CandidateSeries(spec, score, position, threshold)
        discovery_metrics[spec.name] = _metric(discovery, position[masks["discovery"]])

    # Only the preregistered number of discovery leaders is allowed to touch validation.
    leaders = sorted(
        candidates,
        key=lambda name: (
            discovery_metrics[name]["mean_daily_bps"],
            discovery_metrics[name]["annualized_sharpe"],
            name,
        ),
        reverse=True,
    )[:MAX_VALIDATION_CANDIDATES]
    validation_metrics = {
        name: _metric(validation, candidates[name].position[masks["validation"]])
        for name in leaders
    }
    validation_passes = _holm_passes(
        {name: metric["one_sided_p"] for name, metric in validation_metrics.items()}
    )
    eligible = [
        name
        for name in leaders
        if name in validation_passes and validation_metrics[name]["mean_daily_bps"] > 0.0
    ]
    selected = (
        max(
            eligible,
            key=lambda name: (
                validation_metrics[name]["mean_daily_bps"],
                validation_metrics[name]["annualized_sharpe"],
                name,
            ),
        )
        if eligible
        else None
    )

    # This is the only access to final returns.  If validation selects cash, the holdout remains
    # unreported rather than being mined for a consolation winner.
    final_metric = (
        _metric(final, candidates[selected].position[masks["final"]])
        if selected is not None
        else None
    )
    metadata: dict[str, Any] = {
        "protocol": {
            "grammar": "sign of frozen rank; pairwise ranked sums/products; explicit polarity",
            "atomic_features": list(ATOMIC_FEATURES),
            "complexity_cap": MAX_COMPLEXITY,
            "formula_family_cap": MAX_FORMULAS,
            "formulas_generated": len(candidates),
            "participation": PARTICIPATION,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "discovery": (
                f"{DISCOVERY_START.date().isoformat()} through "
                f"{DISCOVERY_END.date().isoformat()}"
            ),
            "validation": (
                f"{VALIDATION_START.date().isoformat()} through "
                f"{VALIDATION_END.date().isoformat()}"
            ),
            "final": f"{FINAL_START.date().isoformat()} through {FINAL_END.date().isoformat()}",
            "validation_family_cap": MAX_VALIDATION_CANDIDATES,
            "multiple_testing": "Holm one-sided correction on validation daily net P&L",
        },
        "row_counts": {name: int(mask.sum()) for name, mask in masks.items()},
        "candidate_specs": {
            name: asdict(candidate.spec) for name, candidate in candidates.items()
        },
        "discovery_metrics": discovery_metrics,
        "validation_candidates": leaders,
        "validation_metrics": validation_metrics,
        "holm_validation_passes": sorted(validation_passes),
        "eligible_candidates": sorted(eligible),
        "selected_candidate": selected,
        "final_metric": final_metric,
        "verdict": (
            "one frozen formula selected for final evaluation"
            if selected is not None
            else "cash selected; no formula survived validation costs and correction"
        ),
    }
    return FormulaMiningResult(candidates, tuple(leaders), selected, metadata)
