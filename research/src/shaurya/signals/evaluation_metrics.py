"""Evaluation metrics — `D38 / TOUCH-METRICS-2026-08-20`, section B.

Out-of-sample R2 alone has been carrying the whole horse race, and it is the wrong single
statistic for a trading signal: it rewards fitting the large moves and says nothing about whether
the sign is right, whether the edge survives the spread, or whether the association is monotone
rather than linear.  This module supplies the companions the frozen specification requires and the
discipline that keeps them honest.

* `METRIC-01` :func:`information_coefficient` — Pearson and Spearman correlation between the
  prediction and the realised return, with stationary block-bootstrap confidence intervals
  resampled **within tape** so no replicate splices two captures.
* `METRIC-02` :func:`sign_accuracy` — hit rate against both the 50% null and the majority-class
  null, additionally on strictly non-zero realised moves.
* `METRIC-03` :func:`net_of_cost_pnl` — the CCZ section 4.2.2 forecast strategy: take a position
  when the forecast exceeds the prevailing spread, self-financed.  Gross PnL, PnL net of half
  spread plus fees, turnover, and PnL per unit risk, at a declared grid of cost assumptions.
* `METRIC-04` :func:`metric_bundle` — the bundle every reported cell carries alongside R2, and
  :func:`assert_companion_metrics` — a cell that emits R2 by itself is a defect, asserted.
* `METRIC-05` :func:`benjamini_yekutieli` and :func:`past_mirror_verdict` — the dependence-aware
  FDR correction and the past-mirror rule.  A metric that improves the headline while failing the
  past mirror is reported as failing, not as an improvement.

Every statistic here is computed on the identical held-out rows that produced the R2 it
accompanies (`VAL-METRIC-01`); the caller passes one aligned triple of predictions, realised
returns and per-row context, and receives one bundle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

SPECIFICATION_ID: Final = "D38 / TOUCH-METRICS-2026-08-20"
DESIGN_DOCUMENT: Final = "research/docs/TOUCH-METRICS-SPEC-2026-08-20.md"

#: `METRIC-01`.  Percentile confidence level for the bootstrap interval.
CONFIDENCE_LEVEL: Final = 0.95
#: `METRIC-01`.  Replicates and seed default to the repository-wide values so a metric interval is
#: reproducible from the artifact alone.
DEFAULT_REPLICATES: Final = 399
DEFAULT_SEED: Final = 20260820

#: `METRIC-03`.  NSE index-futures round-trip statutory cost, expressed as a fraction of turnover
#: and converted to ticks against the declared reference price.  Recorded as an explicit grid
#: rather than one hidden number, because the answer to "does this survive costs?" depends
#: entirely on which costs a reader believes apply to them.
REFERENCE_PRICE_RUPEES: Final = 24_250.0
TICK_SIZE_RUPEES: Final = 0.05
#: Exchange transaction charge, both sides, grossed up for GST at 18%.
EXCHANGE_ROUND_TRIP_FRACTION: Final = 2.0 * 0.000019 * 1.18
#: SEBI turnover fee, both sides, grossed up for GST.
SEBI_ROUND_TRIP_FRACTION: Final = 2.0 * 0.000001 * 1.18
#: Stamp duty, buy side only.
STAMP_BUY_SIDE_FRACTION: Final = 0.00002
#: Securities transaction tax on futures, sell side only, at the post-2024 rate.
STT_SELL_SIDE_FRACTION: Final = 0.0002


def _fraction_to_ticks(fraction: float) -> float:
    return fraction * REFERENCE_PRICE_RUPEES / TICK_SIZE_RUPEES


#: `METRIC-03`.  Declared cost arms.  ``charge_half_spread`` crosses half the prevailing displayed
#: spread on entry and again on exit; ``fee_ticks`` is a flat round-trip charge in ticks.
COST_ARMS: Final = (
    ("gross", 0.0, False),
    ("half_spread_only", 0.0, True),
    (
        "half_spread_plus_exchange_and_stamp",
        _fraction_to_ticks(
            EXCHANGE_ROUND_TRIP_FRACTION + SEBI_ROUND_TRIP_FRACTION + STAMP_BUY_SIDE_FRACTION
        ),
        True,
    ),
    (
        "half_spread_plus_full_statutory",
        _fraction_to_ticks(
            EXCHANGE_ROUND_TRIP_FRACTION
            + SEBI_ROUND_TRIP_FRACTION
            + STAMP_BUY_SIDE_FRACTION
            + STT_SELL_SIDE_FRACTION
        ),
        True,
    ),
)
#: The arm reported as the headline net figure.
PRIMARY_COST_ARM: Final = "half_spread_plus_full_statutory"

#: `METRIC-04`.  A reported cell must carry all of these beside its R2.
REQUIRED_COMPANION_METRICS: Final = ("information_coefficient", "sign_accuracy", "net_of_cost_pnl")


class CompanionMetricsMissing(ValueError):
    """`VAL-METRIC-02`: a cell emitted an R2 without its companion metrics."""


# ------------------------------------------------------------------------------------ METRIC-01


def _finite_pairs(
    predictions: Sequence[float], realised: Sequence[float], tapes: Sequence[int]
) -> tuple[FloatArray, FloatArray, IntArray]:
    if not (len(predictions) == len(realised) == len(tapes)):
        raise ValueError("predictions, realised returns and tape labels must be aligned")
    x = np.asarray(predictions, dtype=np.float64)
    y = np.asarray(realised, dtype=np.float64)
    groups = np.asarray(tapes, dtype=np.int64)
    keep = np.isfinite(x) & np.isfinite(y)
    return x[keep], y[keep], groups[keep]


def _correlation(x: FloatArray, y: FloatArray, *, spearman: bool) -> float | None:
    if len(x) < 3:
        return None
    if spearman:
        x = np.asarray(rankdata(x), dtype=np.float64)
        y = np.asarray(rankdata(y), dtype=np.float64)
    x_scale = float(np.std(x))
    y_scale = float(np.std(y))
    if x_scale <= 0.0 or y_scale <= 0.0:
        return None
    value = float(np.mean((x - float(np.mean(x))) / x_scale * (y - float(np.mean(y))) / y_scale))
    return value if isfinite(value) else None


def _stationary_block_indices(
    size: int, *, mean_block_length: float, generator: np.random.Generator
) -> IntArray:
    """One stationary-bootstrap index path of length ``size`` over ``0..size-1``."""

    restart = 1.0 / max(mean_block_length, 1.0)
    indices = np.empty(size, dtype=np.int64)
    index = int(generator.integers(size))
    for position in range(size):
        if position and generator.random() < restart:
            index = int(generator.integers(size))
        elif position:
            index = (index + 1) % size
        indices[position] = index
    return indices


def _bootstrap_replicates(
    x: FloatArray,
    y: FloatArray,
    groups: IntArray,
    *,
    spearman: bool,
    replicates: int,
    mean_block_length: float,
    seed: int,
) -> list[float]:
    """Resample contiguous blocks **within tape**, so no replicate splices two captures."""

    generator = np.random.default_rng(seed)
    partitions = [np.flatnonzero(groups == tape) for tape in sorted(set(groups.tolist()))]
    draws: list[float] = []
    for _ in range(replicates):
        parts_x: list[FloatArray] = []
        parts_y: list[FloatArray] = []
        for positions in partitions:
            if positions.size == 0:
                continue
            picked = positions[
                _stationary_block_indices(
                    positions.size, mean_block_length=mean_block_length, generator=generator
                )
            ]
            parts_x.append(x[picked])
            parts_y.append(y[picked])
        if not parts_x:
            continue
        value = _correlation(np.concatenate(parts_x), np.concatenate(parts_y), spearman=spearman)
        if value is not None:
            draws.append(value)
    return draws


def _interval(draws: Sequence[float]) -> dict[str, float | None]:
    if len(draws) < 2:
        return {"lower": None, "upper": None, "standard_error": None, "replicates": len(draws)}
    ordered = np.sort(np.asarray(draws, dtype=np.float64))
    tail = (1.0 - CONFIDENCE_LEVEL) / 2.0
    return {
        "lower": float(np.quantile(ordered, tail)),
        "upper": float(np.quantile(ordered, 1.0 - tail)),
        "standard_error": float(np.std(ordered, ddof=1)),
        "replicates": len(ordered),
    }


def information_coefficient(
    predictions: Sequence[float],
    realised: Sequence[float],
    *,
    tapes: Sequence[int],
    mean_block_length: float = 8.0,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """`METRIC-01`: Pearson and Spearman IC with stationary block-bootstrap intervals."""

    x, y, groups = _finite_pairs(predictions, realised, tapes)
    result: dict[str, Any] = {
        "requirement": "METRIC-01",
        "n": int(x.size),
        "confidence_level": CONFIDENCE_LEVEL,
        "mean_block_length": mean_block_length,
        "resampled_within_tape": True,
    }
    for label, spearman in (("pearson", False), ("spearman", True)):
        point = _correlation(x, y, spearman=spearman)
        draws = (
            _bootstrap_replicates(
                x,
                y,
                groups,
                spearman=spearman,
                replicates=replicates,
                mean_block_length=mean_block_length,
                seed=seed + (1 if spearman else 0),
            )
            if point is not None and x.size >= 8
            else []
        )
        interval = _interval(draws)
        standard_error = interval["standard_error"]
        result[label] = {
            "estimate": point,
            **interval,
            "t": (
                point / standard_error
                if point is not None and standard_error is not None and standard_error > 0.0
                else None
            ),
            "excludes_zero": (
                None
                if interval["lower"] is None or interval["upper"] is None
                else bool(interval["lower"] > 0.0 or interval["upper"] < 0.0)
            ),
        }
    return result


# ------------------------------------------------------------------------------------ METRIC-02


def sign_accuracy(predictions: Sequence[float], realised: Sequence[float]) -> dict[str, Any]:
    """`METRIC-02`: hit rate against the 50% null and the majority-class null.

    A hit rate of 62% is meaningless if 62% of realised moves are up; the majority-class null is
    the only one that can distinguish skill from drift.  The strictly non-zero panel removes the
    flat moves, where a sign is not defined and a zero prediction would otherwise score.
    """

    x, y, _ = _finite_pairs(predictions, realised, [0] * len(predictions))
    predicted_sign = np.sign(x)
    realised_sign = np.sign(y)

    def panel(mask: NDArray[np.bool_]) -> dict[str, Any]:
        total = int(mask.sum())
        if total == 0:
            return {
                "n": 0,
                "hits": 0,
                "hit_rate": None,
                "majority_class_share": None,
                "excess_over_coin_flip": None,
                "excess_over_majority_class": None,
            }
        hits = int((predicted_sign[mask] == realised_sign[mask]).sum())
        up = float((realised_sign[mask] > 0).mean())
        down = float((realised_sign[mask] < 0).mean())
        flat = float((realised_sign[mask] == 0).mean())
        majority = max(up, down, flat)
        rate = hits / total
        return {
            "n": total,
            "hits": hits,
            "hit_rate": rate,
            "up_share": up,
            "down_share": down,
            "flat_share": flat,
            "majority_class_share": majority,
            "excess_over_coin_flip": rate - 0.5,
            "excess_over_majority_class": rate - majority,
            "binomial_standard_error": sqrt(rate * (1.0 - rate) / total) if total else None,
        }

    everything = np.ones(x.shape, dtype=bool)
    non_zero = realised_sign != 0
    return {
        "requirement": "METRIC-02",
        "all_rows": panel(everything),
        "strictly_non_zero_moves": panel(non_zero),
    }


# ------------------------------------------------------------------------------------ METRIC-03


@dataclass(frozen=True, slots=True)
class CostArm:
    name: str
    fee_ticks: float
    charge_half_spread: bool


def declared_cost_arms() -> tuple[CostArm, ...]:
    return tuple(CostArm(name, fee, half) for name, fee, half in COST_ARMS)


def net_of_cost_pnl(
    predictions: Sequence[float],
    realised: Sequence[float],
    spread_ticks: Sequence[float],
) -> dict[str, Any]:
    """`METRIC-03`: the CCZ section 4.2.2 forecast strategy, at every declared cost arm.

    The entry rule is the paper's: hold one self-financed unit in the direction of the forecast
    whenever ``|forecast|`` exceeds the prevailing displayed spread, and nothing otherwise.  Costs
    are applied afterwards so the entry rule and the cost assumption stay separable — a reader who
    disagrees with one does not have to discard the other.
    """

    if not (len(predictions) == len(realised) == len(spread_ticks)):
        raise ValueError("predictions, realised returns and spreads must be aligned")
    x = np.asarray(predictions, dtype=np.float64)
    y = np.asarray(realised, dtype=np.float64)
    spread = np.asarray(spread_ticks, dtype=np.float64)
    keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(spread) & (spread >= 0.0)
    x, y, spread = x[keep], y[keep], spread[keep]
    position = np.where(np.abs(x) > spread, np.sign(x), 0.0)
    gross = position * y
    traded = position != 0.0
    trades = int(traded.sum())
    turnover = float(np.abs(np.diff(position, prepend=0.0)).sum())
    arms: dict[str, Any] = {}
    for arm in declared_cost_arms():
        charge = np.where(traded, arm.fee_ticks, 0.0)
        if arm.charge_half_spread:
            charge = charge + np.where(traded, spread, 0.0)
        net = gross - charge
        deviation = float(np.std(net, ddof=1)) if net.size > 1 else 0.0
        arms[arm.name] = {
            "fee_ticks_round_trip": arm.fee_ticks,
            "charges_half_spread_each_side": arm.charge_half_spread,
            "total_pnl_ticks": float(net.sum()),
            "mean_pnl_ticks_per_observation": float(net.mean()) if net.size else None,
            "mean_pnl_ticks_per_trade": (float(net[traded].mean()) if trades else None),
            "pnl_per_unit_risk": (
                float(net.mean() / deviation) if net.size and deviation > 0.0 else None
            ),
            "profitable": (bool(net.sum() > 0.0) if net.size else None),
        }
    return {
        "requirement": "METRIC-03",
        "rule": (
            "self-financed unit position when |forecast| exceeds the prevailing displayed spread"
        ),
        "reference": "Cont, Cucuringu and Zhang (2023) section 4.2.2",
        "n": int(x.size),
        "trades": trades,
        "participation_rate": (trades / x.size) if x.size else None,
        "turnover_units": turnover,
        "turnover_per_observation": (turnover / x.size) if x.size else None,
        "mean_spread_ticks": float(spread.mean()) if spread.size else None,
        "gross_total_pnl_ticks": float(gross.sum()),
        "cost_arms": arms,
        "primary_cost_arm": PRIMARY_COST_ARM,
        "cost_basis": {
            "reference_price_rupees": REFERENCE_PRICE_RUPEES,
            "tick_size_rupees": TICK_SIZE_RUPEES,
            "exchange_round_trip_fraction_of_turnover": EXCHANGE_ROUND_TRIP_FRACTION,
            "sebi_round_trip_fraction_of_turnover": SEBI_ROUND_TRIP_FRACTION,
            "stamp_buy_side_fraction_of_turnover": STAMP_BUY_SIDE_FRACTION,
            "stt_sell_side_fraction_of_turnover": STT_SELL_SIDE_FRACTION,
            "note": (
                "costs are declared as a grid, not one hidden number; fee arms are converted to "
                "ticks at the reference price and are therefore a scenario, not an observed cost"
            ),
            "object_category": "scenario_based",
        },
    }


# ------------------------------------------------------------------------------------ METRIC-04


def metric_bundle(
    predictions: Sequence[float],
    realised: Sequence[float],
    *,
    spread_ticks: Sequence[float],
    tapes: Sequence[int],
    mean_block_length: float = 8.0,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """`METRIC-04`: the companion set every R2 cell carries, on the identical held-out rows."""

    return {
        "specification_id": SPECIFICATION_ID,
        "held_out_rows": len(predictions),
        "information_coefficient": information_coefficient(
            predictions,
            realised,
            tapes=tapes,
            mean_block_length=mean_block_length,
            replicates=replicates,
            seed=seed,
        ),
        "sign_accuracy": sign_accuracy(predictions, realised),
        "net_of_cost_pnl": net_of_cost_pnl(predictions, realised, spread_ticks),
    }


def assert_companion_metrics(cell: Mapping[str, Any], *, label: str = "cell") -> None:
    """`VAL-METRIC-02`: refuse a cell that reports an R2 without its companions."""

    r2_keys = [key for key in cell if key.startswith("oos_r2") or key == "in_sample_r2"]
    if not r2_keys:
        return
    metrics = cell.get("metrics")
    if not isinstance(metrics, Mapping):
        raise CompanionMetricsMissing(
            f"{label} reports {sorted(r2_keys)} without a metrics block (METRIC-04)"
        )
    missing = [name for name in REQUIRED_COMPANION_METRICS if name not in metrics]
    if missing:
        raise CompanionMetricsMissing(f"{label} is missing companion metrics {missing}")
    held_out = metrics.get("held_out_rows")
    if held_out is not None and cell.get("test_n") is not None and held_out != cell["test_n"]:
        raise CompanionMetricsMissing(
            f"{label} computed its companion metrics on {held_out} rows but reports "
            f"{cell['test_n']} held-out rows (VAL-METRIC-01)"
        )


# ------------------------------------------------------------------------------------ METRIC-05


def benjamini_yekutieli(p_values: Sequence[float | None]) -> list[float | None]:
    """`METRIC-05`: dependence-aware FDR control.

    Benjamini-Yekutieli rather than Benjamini-Hochberg: the cells of this grid share observations,
    share features and share a tape, so positive-regression dependence cannot be assumed and the
    harmonic-number penalty is the price of not assuming it.
    """

    eligible = [
        (index, float(value))
        for index, value in enumerate(p_values)
        if value is not None and isfinite(float(value))
    ]
    adjusted: list[float | None] = [None] * len(p_values)
    total = len(eligible)
    if total == 0:
        return adjusted
    penalty = sum(1.0 / rank for rank in range(1, total + 1))
    eligible.sort(key=lambda item: item[1])
    running = 1.0
    for rank, (index, value) in reversed(list(enumerate(eligible, start=1))):
        running = min(running, value * total * penalty / rank)
        adjusted[index] = min(running, 1.0)
    return adjusted


def past_mirror_verdict(
    *, future_value: float | None, past_value: float | None, label: str, two_sided: bool = False
) -> dict[str, Any]:
    """`METRIC-05`: a metric that improves the headline while the past mirror also fires fails.

    The mirror runs the identical machinery against *past* returns, where no predictor can have
    information.  A future improvement the past mirror reproduces is a property of the
    construction, not of the signal.

    The comparison is **signed** by default, matching the rule already in this repository
    (``past_mirror_exceeds_or_equals_future`` in the dashboard and the 30 s gate): a mirror
    increment that is large and *negative* means the model does worse than the baseline on past
    returns, which is evidence against leakage, not for it.  Comparing magnitudes would fail such
    a cell, which is exactly backwards.

    ``two_sided=True`` compares magnitudes instead, and is correct only for a statistic whose sign
    is a direction rather than a quality — an information coefficient of -0.3 on past returns is
    as much of a warning as +0.3.
    """

    if future_value is None or past_value is None:
        return {
            "metric": label,
            "future": future_value,
            "past_mirror": past_value,
            "comparison": "two_sided" if two_sided else "signed",
            "verdict": "unevaluable",
            "passes_past_mirror": None,
        }
    passes = abs(future_value) > abs(past_value) if two_sided else future_value > past_value
    return {
        "metric": label,
        "future": future_value,
        "past_mirror": past_value,
        "comparison": "two_sided" if two_sided else "signed",
        "margin": (abs(future_value) - abs(past_value) if two_sided else future_value - past_value),
        "verdict": "passes" if passes else "fails_past_mirror",
        "passes_past_mirror": passes,
    }


def per_tape_sign_check(values: Mapping[str, float | None], *, label: str) -> dict[str, Any]:
    """`METRIC-05`: one tape carrying the whole result is a warning, not a confirmation."""

    observed = {tape: value for tape, value in values.items() if value is not None}
    signs = {tape: (1 if value > 0 else -1 if value < 0 else 0) for tape, value in observed.items()}
    positive = sum(1 for value in signs.values() if value > 0)
    negative = sum(1 for value in signs.values() if value < 0)
    return {
        "metric": label,
        "tapes": len(observed),
        "by_tape": observed,
        "positive_tapes": positive,
        "negative_tapes": negative,
        "consistent": (len(observed) > 0 and (positive == 0 or negative == 0)),
    }


def metric_metadata() -> dict[str, Any]:
    """The block every artifact built on these metrics carries."""

    return {
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "required_companion_metrics": list(REQUIRED_COMPANION_METRICS),
        "confidence_level": CONFIDENCE_LEVEL,
        "cost_arms": [arm.name for arm in declared_cost_arms()],
        "primary_cost_arm": PRIMARY_COST_ARM,
        "multiple_testing_correction": "benjamini_yekutieli",
        "r2_alone_is_a_defect": True,
        "naive_iid_inference_valid": False,
    }
