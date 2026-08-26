"""D39 fixed-target competitor panel and bid-ask-bounce diagnostics.

The module exists because three earlier reports compared a predictor with three different kinds
of object: a controls baseline, a past-target falsifier, and a sign-classification null.  D39
keeps one future-return target and enters each alternative explanation as an ordinary competitor
on identical held-out rows.  The past mirror remains a boolean contamination guard only.

The two print-based robustness references are fitted strictly on the training partition.  No
function in this module imports an order or credential path.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite, sqrt
from typing import Any, Final, Literal

import numpy as np

from shaurya.signals.ccz_ofi import level_feature, normalised_level_feature
from shaurya.signals.deep_book_normal_activity import (
    EMBARGO_SECONDS,
    SplitIndex,
    chronological_embargoed_split,
    fit_ridge,
    fit_ridge_path,
)
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS, FUTURES_TICK_SIZE
from shaurya.signals.effective_touch import TradePrint
from shaurya.signals.evaluation_metrics import assert_companion_metrics, metric_bundle
from shaurya.signals.ofi_horserace import (
    BASELINE_FEATURES,
    RIDGE_ALPHAS,
    HorseRaceObservation,
    HorseRaceTapeInput,
    as_normal_observation,
    cks_feature,
    normalised_trade_feature,
    touch_relative_feature,
)
from shaurya.signals.reference_prices import REFERENCE_PRICE_LADDER, PricePath

SPECIFICATION_ID: Final = "D39 / FIXED-TARGET-COMPETITOR-PANEL"
DESIGN_DOCUMENT: Final = "research/docs/D39-FIXED-TARGET-PANEL-SPEC-2026-08-21.md"
RETROSPECTIVE_SCAN_ID: Final = "X-D39-LATEPARTIAL-2026-08-20"

COMPETITOR_ORDER: Final = tuple(f"C{index}" for index in range(13))
CCZ_LEVEL_COUNTS: Final = (1, 5, 10, 20)
WINDOWS_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0)
HORIZONS_SECONDS: Final = (0.5, 1.0, 2.0, 5.0, 10.0)
TRADE_SIGN_CORRECTED: Final = "trade_sign_corrected"
SAME_SIDE_PRINT: Final = "same_side_print"
D39_REFERENCE_PRICE_LADDER: Final = (
    *REFERENCE_PRICE_LADDER,
    TRADE_SIGN_CORRECTED,
    SAME_SIDE_PRINT,
)
MINIMUM_FIT_OBSERVATIONS: Final = 20
REGULARISED_COMPETITORS: Final = frozenset({"C7", "C8", "C10", "C11", "C12"})


@dataclass(frozen=True, slots=True)
class RollEstimate:
    """Roll (1984) spread diagnostic, expressed on the futures tick grid."""

    n_prices: int
    n_returns: int
    mean_return_ticks: float | None
    first_order_autocovariance_ticks2: float | None
    first_order_autocorrelation: float | None
    effective_half_spread_ticks: float | None
    effective_spread_ticks: float | None

    @property
    def identified(self) -> bool:
        return self.effective_half_spread_ticks is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_prices": self.n_prices,
            "n_returns": self.n_returns,
            "mean_return_ticks": self.mean_return_ticks,
            "first_order_autocovariance_ticks2": self.first_order_autocovariance_ticks2,
            "first_order_autocorrelation": self.first_order_autocorrelation,
            "effective_half_spread_ticks": self.effective_half_spread_ticks,
            "effective_spread_ticks": self.effective_spread_ticks,
            "identified": self.identified,
            "rule": "half_spread=sqrt(-gamma_1); spread=2*half_spread; missing if gamma_1>=0",
        }


def _usable_signed_prints(prints: Sequence[TradePrint]) -> list[TradePrint]:
    return sorted(
        (
            item
            for item in prints
            if item.signed and not item.degraded and not item.coalesced and isfinite(item.price)
        ),
        key=lambda item: item.receive_ts_ns,
    )


def roll_effective_spread(prints: Sequence[TradePrint]) -> RollEstimate:
    """Estimate Roll's spread from consecutive classified print-price changes.

    The estimate is deliberately missing when the first-order autocovariance is non-negative.
    Forcing ``sqrt(max(-gamma, 0))`` would turn non-identification into a fabricated zero spread.
    """

    selected = _usable_signed_prints(prints)
    prices = np.asarray([item.price / FUTURES_TICK_SIZE for item in selected], dtype=np.float64)
    changes = np.diff(prices)
    if changes.size < 3:
        return RollEstimate(len(prices), int(changes.size), None, None, None, None, None)
    left = changes[:-1]
    right = changes[1:]
    left_c = left - float(left.mean())
    right_c = right - float(right.mean())
    covariance = float(np.mean(left_c * right_c))
    left_sd = float(np.std(left))
    right_sd = float(np.std(right))
    correlation = covariance / (left_sd * right_sd) if left_sd > 0 and right_sd > 0 else None
    half = sqrt(-covariance) if covariance < 0.0 else None
    return RollEstimate(
        n_prices=len(prices),
        n_returns=int(changes.size),
        mean_return_ticks=float(changes.mean()),
        first_order_autocovariance_ticks2=covariance,
        first_order_autocorrelation=correlation,
        effective_half_spread_ticks=half,
        effective_spread_ticks=(2.0 * half if half is not None else None),
    )


def roll_diagnostics(
    prints: Sequence[TradePrint], *, training_upper_bound_ts_ns: int
) -> dict[str, Any]:
    """`BOUNCE-01`: training-only fit plus whole-tape and 15-minute descriptive panels."""

    selected = _usable_signed_prints(prints)
    training = [item for item in selected if item.receive_ts_ns <= training_upper_bound_ts_ns]
    buckets: dict[int, list[TradePrint]] = {}
    bucket_ns = 15 * 60 * 1_000_000_000
    for item in selected:
        buckets.setdefault(item.receive_ts_ns // bucket_ns, []).append(item)
    return {
        "requirement": "BOUNCE-01",
        "training_upper_bound_ts_ns": training_upper_bound_ts_ns,
        "training_fit": roll_effective_spread(training).to_dict(),
        "whole_tape_descriptive": roll_effective_spread(selected).to_dict(),
        "fifteen_minute_descriptive": [
            {
                "bucket_start_ts_ns": bucket * bucket_ns,
                "bucket_end_ts_ns": (bucket + 1) * bucket_ns,
                **roll_effective_spread(values).to_dict(),
            }
            for bucket, values in sorted(buckets.items())
        ],
    }


def build_trade_sign_corrected_path(
    prints: Sequence[TradePrint], *, effective_half_spread_ticks: float | None
) -> PricePath:
    """`BOUNCE-02`: remove the training-estimated signed half-spread from every print."""

    timestamps: list[int] = []
    prices: list[float] = []
    if effective_half_spread_ticks is None:
        return PricePath(TRADE_SIGN_CORRECTED, (), ())
    correction = effective_half_spread_ticks * FUTURES_TICK_SIZE
    for item in _usable_signed_prints(prints):
        sign = 1.0 if item.side == "buy" else -1.0
        value = item.price - sign * correction
        if timestamps and item.receive_ts_ns <= timestamps[-1]:
            continue
        timestamps.append(item.receive_ts_ns)
        prices.append(value)
    return PricePath(TRADE_SIGN_CORRECTED, tuple(timestamps), tuple(prices))


@dataclass(frozen=True, slots=True)
class SameSidePrintPath:
    """`BOUNCE-03`: resolve both endpoints through prints carrying the same classified side."""

    all_timestamps: tuple[int, ...]
    all_sides: tuple[str, ...]
    by_side_timestamps: Mapping[str, tuple[int, ...]]
    by_side_prices: Mapping[str, tuple[float, ...]]

    def return_ticks(self, start_ts_ns: int, end_ts_ns: int) -> float | None:
        if end_ts_ns <= start_ts_ns or not self.all_timestamps:
            return None
        at_start = bisect_right(self.all_timestamps, start_ts_ns) - 1
        if at_start < 0:
            return None
        side = self.all_sides[at_start]
        stamps = self.by_side_timestamps[side]
        prices = self.by_side_prices[side]
        left = bisect_right(stamps, start_ts_ns) - 1
        right = bisect_right(stamps, end_ts_ns) - 1
        if left < 0 or right <= left:
            return None
        return (prices[right] - prices[left]) / FUTURES_TICK_SIZE


def build_same_side_print_path(prints: Sequence[TradePrint]) -> SameSidePrintPath:
    selected = _usable_signed_prints(prints)
    timestamps: dict[str, list[int]] = {"buy": [], "sell": []}
    prices: dict[str, list[float]] = {"buy": [], "sell": []}
    all_timestamps: list[int] = []
    all_sides: list[str] = []
    for item in selected:
        assert item.side in {"buy", "sell"}
        if all_timestamps and item.receive_ts_ns <= all_timestamps[-1]:
            continue
        all_timestamps.append(item.receive_ts_ns)
        all_sides.append(item.side)
        timestamps[item.side].append(item.receive_ts_ns)
        prices[item.side].append(item.price)
    return SameSidePrintPath(
        tuple(all_timestamps),
        tuple(all_sides),
        {side: tuple(values) for side, values in timestamps.items()},
        {side: tuple(values) for side, values in prices.items()},
    )


def competitor_features(competitor: str, window: float, levels: int) -> tuple[str, ...]:
    """The declared C0..C12 panel. Lagged return is injected separately as ``__lagged__``."""

    baseline = BASELINE_FEATURES
    raw = tuple(level_feature(window, level) for level in range(1, levels + 1))
    scaled = tuple(
        normalised_level_feature(window, level, levels) for level in range(1, levels + 1)
    )
    touch_scaled = tuple(touch_relative_feature(name) for name in scaled)
    specifications = {
        "C0": (),
        "C1": (),
        "C2": ("__lagged__",),
        "C3": baseline,
        "C4": (*baseline, "l1_queue_imbalance"),
        "C5": (*baseline, normalised_trade_feature(window)),
        "C6": (*baseline, cks_feature(window)),
        "C7": (*baseline, *raw),
        "C8": (*baseline, *scaled),
        "C9": (*baseline, "microprice_tilt_ticks"),
        "C10": (
            *baseline,
            touch_relative_feature("l1_queue_imbalance"),
            touch_relative_feature("microprice_tilt_ticks"),
            *touch_scaled,
        ),
        "C11": (
            *baseline,
            "l1_queue_imbalance",
            normalised_trade_feature(window),
            cks_feature(window),
            *raw,
            *scaled,
            "microprice_tilt_ticks",
        ),
        "C12": ("__lagged__", *baseline, *scaled),
    }
    if competitor not in specifications:
        raise ValueError(f"unknown D39 competitor {competitor}")
    return tuple(dict.fromkeys(specifications[competitor]))


def _standard_return(
    observation: HorseRaceObservation,
    reference: str,
    source: Literal["future", "past"],
    horizon: float,
) -> float | None:
    if reference == "displayed_mid":
        values = observation.future_ticks if source == "future" else observation.past_ticks
    else:
        ladder = (
            observation.reference_future_ticks
            if source == "future"
            else observation.reference_past_ticks
        )
        values = ladder.get(reference, {})
    value = values.get(horizon)
    return float(value) if value is not None and isfinite(float(value)) else None


ReturnResolver = Callable[[HorseRaceObservation, Literal["future", "past"], float], float | None]


def make_return_resolver(
    reference: str,
    *,
    corrected: PricePath,
    same_side: SameSidePrintPath,
) -> ReturnResolver:
    if reference in REFERENCE_PRICE_LADDER:
        return lambda observation, source, horizon: _standard_return(
            observation, reference, source, horizon
        )
    if reference == TRADE_SIGN_CORRECTED:
        path: PricePath | SameSidePrintPath = corrected
    elif reference == SAME_SIDE_PRINT:
        path = same_side
    else:
        raise ValueError(f"unknown D39 reference {reference}")

    gap_ns = int(CAUSAL_GAP_SECONDS * 1_000_000_000)

    def resolve(
        observation: HorseRaceObservation, source: Literal["future", "past"], horizon: float
    ) -> float | None:
        horizon_ns = int(horizon * 1_000_000_000)
        if source == "future":
            start = observation.receive_ts_ns + gap_ns
            end = start + horizon_ns
        else:
            start = observation.receive_ts_ns - horizon_ns
            end = observation.receive_ts_ns
        value = path.return_ticks(start, end)
        return float(value) if value is not None and isfinite(float(value)) else None

    return resolve


def _epoch_bounds(
    observations: Sequence[HorseRaceObservation],
) -> dict[tuple[int, int], tuple[int, int]]:
    values: dict[tuple[int, int], list[int]] = {}
    for observation in observations:
        values.setdefault((observation.tape_index, observation.connection_epoch), []).append(
            observation.receive_ts_ns
        )
    return {key: (min(stamps), max(stamps)) for key, stamps in values.items()}


def _row_hash(observations: Sequence[HorseRaceObservation], positions: Sequence[int]) -> str:
    digest = sha256()
    for position in positions:
        digest.update(str(observations[position].receive_ts_ns).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _has_named_features(observation: HorseRaceObservation, names: Sequence[str]) -> bool:
    return all(
        name == "__lagged__"
        or (name in observation.features and isfinite(float(observation.features[name])))
        for name in names
    )


def _design(
    observations: Sequence[HorseRaceObservation],
    positions: Sequence[int],
    names: Sequence[str],
    lagged: Mapping[int, float],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [
            [
                lagged[position]
                if name == "__lagged__"
                else float(observations[position].features[name])
                for name in names
            ]
            for position in positions
        ],
        dtype=np.float64,
    ).reshape(len(positions), len(names))


def _oos_r2(
    test: np.ndarray[Any, Any], prediction: np.ndarray[Any, Any], train_mean: float
) -> float | None:
    denominator = float(np.sum((test - train_mean) ** 2))
    if denominator <= 0.0:
        return None
    return 1.0 - float(np.sum((test - prediction) ** 2)) / denominator


def _select_alpha(
    train_design: np.ndarray[Any, Any],
    train_target: np.ndarray[Any, Any],
    train_timestamps: np.ndarray[Any, Any],
    names: Sequence[str],
) -> tuple[float, list[dict[str, Any]]]:
    scores: dict[float, list[float]] = {alpha: [] for alpha in RIDGE_ALPHAS}
    embargo_ns = int(EMBARGO_SECONDS * 1_000_000_000)
    size = len(train_target)
    for fraction in (0.5, 0.65, 0.8):
        cut = max(1, int(size * fraction))
        boundary = int(train_timestamps[cut - 1])
        validation = np.flatnonzero(train_timestamps > boundary + embargo_ns)
        validation = validation[validation < min(size, cut + max(1, size // 10))]
        if cut < MINIMUM_FIT_OBSERVATIONS or validation.size == 0:
            continue
        inner_target = train_target[:cut]
        drift = float(inner_target.mean())
        fits = fit_ridge_path(
            train_design[:cut],
            inner_target - drift,
            feature_names=names,
            penalties=RIDGE_ALPHAS,
        )
        for alpha, fit in fits.items():
            prediction = drift + fit.predict(train_design[validation])
            scores[alpha].append(float(np.mean((train_target[validation] - prediction) ** 2)))
    means = {
        alpha: (float(np.mean(values)) if values else float("inf"))
        for alpha, values in scores.items()
    }
    selected = min(RIDGE_ALPHAS, key=lambda alpha: (means[alpha], alpha))
    if not isfinite(means[selected]):
        selected = RIDGE_ALPHAS[0]
    return selected, [
        {"alpha": alpha, "mean_validation_mse": means[alpha], "folds": len(scores[alpha])}
        for alpha in RIDGE_ALPHAS
    ]


def _fit_predictions(
    competitor: str,
    names: Sequence[str],
    train_design: np.ndarray[Any, Any],
    test_design: np.ndarray[Any, Any],
    train_target: np.ndarray[Any, Any],
    test_target: np.ndarray[Any, Any],
    train_timestamps: np.ndarray[Any, Any],
) -> tuple[np.ndarray[Any, Any], dict[str, Any]]:
    drift = float(train_target.mean())
    if competitor == "C0":
        prediction = np.full(test_target.shape, drift, dtype=np.float64)
        return prediction, {"selected_alpha": None, "coefficients": {}, "inner_cv": []}
    if competitor == "C1":
        signs = np.sign(train_target).astype(int).tolist()
        counts = Counter(signs)
        majority = max((-1, 0, 1), key=lambda value: (counts[value], -abs(value), value))
        magnitude = float(np.mean(np.abs(train_target)))
        prediction = np.full(test_target.shape, majority * magnitude, dtype=np.float64)
        return prediction, {
            "selected_alpha": None,
            "coefficients": {},
            "inner_cv": [],
            "training_majority_direction": majority,
            "training_mean_absolute_return_ticks": magnitude,
        }
    alpha, cv = (
        _select_alpha(train_design, train_target, train_timestamps, names)
        if competitor in REGULARISED_COMPETITORS
        else (0.0, [])
    )
    fit = fit_ridge(
        train_design,
        train_target - drift,
        feature_names=names,
        penalty=alpha,
    )
    prediction = drift + fit.predict(test_design)
    return prediction, {
        "selected_alpha": alpha,
        "coefficients_ticks_per_training_sd": {
            name: float(fit.coefficients[index]) for index, name in enumerate(names)
        },
        "raw_coefficients_ticks_per_unit": {
            name: float(fit.coefficients[index] / fit.scale[index])
            for index, name in enumerate(names)
        },
        "inner_cv": cv,
    }


def _candidate_positions(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    *,
    names: Sequence[str],
    lagged: Mapping[int, float],
    future: Mapping[int, float],
    past: Mapping[int, float],
    window: float,
    horizon: float,
    epoch_bounds: Mapping[tuple[int, int], tuple[int, int]],
) -> tuple[int, ...]:
    history_ns = int(window * 1_000_000_000)
    forward_ns = int((CAUSAL_GAP_SECONDS + horizon) * 1_000_000_000)
    result: list[int] = []
    for position in candidates:
        observation = observations[position]
        bounds = epoch_bounds[(observation.tape_index, observation.connection_epoch)]
        if observation.receive_ts_ns - history_ns < bounds[0]:
            continue
        if observation.receive_ts_ns + forward_ns > bounds[1]:
            continue
        if position not in lagged or position not in future or position not in past:
            continue
        if not _has_named_features(observation, names):
            continue
        result.append(position)
    return tuple(result)


def evaluate_panel_cell(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    reference: str,
    resolver: ReturnResolver,
    window: float,
    horizon: float,
    levels: int,
    replicates: int,
    seed: int,
    epoch_bounds: Mapping[tuple[int, int], tuple[int, int]],
) -> dict[str, Any]:
    """Evaluate one reference x M x h1 x h2 panel on an exact common sample."""

    lagged = {
        position: value
        for position, observation in enumerate(observations)
        if (value := resolver(observation, "past", window)) is not None
    }
    future = {
        position: value
        for position, observation in enumerate(observations)
        if (value := resolver(observation, "future", horizon)) is not None
    }
    past = {
        position: value
        for position, observation in enumerate(observations)
        if (value := resolver(observation, "past", horizon)) is not None
    }
    feature_sets = {
        competitor: competitor_features(competitor, window, levels)
        for competitor in COMPETITOR_ORDER
    }
    non_touch = tuple(
        dict.fromkeys(
            name
            for competitor in COMPETITOR_ORDER
            if competitor != "C10"
            for name in feature_sets[competitor]
            if name != "__lagged__"
        )
    )
    touch_names = tuple(name for name in feature_sets["C10"] if name != "__lagged__")
    touch_train = _candidate_positions(
        observations,
        split.train,
        names=(*non_touch, *touch_names),
        lagged=lagged,
        future=future,
        past=past,
        window=window,
        horizon=horizon,
        epoch_bounds=epoch_bounds,
    )
    touch_test = _candidate_positions(
        observations,
        split.test,
        names=(*non_touch, *touch_names),
        lagged=lagged,
        future=future,
        past=past,
        window=window,
        horizon=horizon,
        epoch_bounds=epoch_bounds,
    )
    touch_covered = min(len(touch_train), len(touch_test)) >= MINIMUM_FIT_OBSERVATIONS
    common_names = tuple(dict.fromkeys((*non_touch, *(touch_names if touch_covered else ()))))
    train = _candidate_positions(
        observations,
        split.train,
        names=common_names,
        lagged=lagged,
        future=future,
        past=past,
        window=window,
        horizon=horizon,
        epoch_bounds=epoch_bounds,
    )
    test = _candidate_positions(
        observations,
        split.test,
        names=common_names,
        lagged=lagged,
        future=future,
        past=past,
        window=window,
        horizon=horizon,
        epoch_bounds=epoch_bounds,
    )
    if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
        return {
            "reference_price": reference,
            "h1_seconds": window,
            "h2_seconds": horizon,
            "levels": levels,
            "status": "insufficient_common_support",
            "train_n": len(train),
            "test_n": len(test),
            "competitors": [],
        }
    y_train = np.asarray([future[position] for position in train], dtype=np.float64)
    y_test = np.asarray([future[position] for position in test], dtype=np.float64)
    y_past_train = np.asarray([past[position] for position in train], dtype=np.float64)
    y_past_test = np.asarray([past[position] for position in test], dtype=np.float64)
    train_timestamps = np.asarray(
        [observations[position].receive_ts_ns for position in train], dtype=np.int64
    )
    spread_test = [float(observations[position].features["spread_ticks"]) for position in test]
    results: list[dict[str, Any]] = []
    for competitor in COMPETITOR_ORDER:
        if competitor == "C10" and not touch_covered:
            results.append(
                {
                    "competitor": competitor,
                    "status": "uncovered_effective_touch",
                    "pre_common_train_n": len(touch_train),
                    "pre_common_test_n": len(touch_test),
                }
            )
            continue
        names = feature_sets[competitor]
        train_design = _design(observations, train, names, lagged)
        test_design = _design(observations, test, names, lagged)
        prediction, fit = _fit_predictions(
            competitor,
            names,
            train_design,
            test_design,
            y_train,
            y_test,
            train_timestamps,
        )
        past_prediction, _ = _fit_predictions(
            competitor,
            names,
            train_design,
            test_design,
            y_past_train,
            y_past_test,
            train_timestamps,
        )
        future_r2 = _oos_r2(y_test, prediction, float(y_train.mean()))
        past_r2 = _oos_r2(y_past_test, past_prediction, float(y_past_train.mean()))
        metrics = metric_bundle(
            [float(value) for value in prediction],
            [float(value) for value in y_test],
            spread_ticks=spread_test,
            tapes=[observations[position].tape_index for position in test],
            mean_block_length=8.0,
            replicates=replicates,
            seed=seed + int(competitor[1:]) * 10_000,
        )
        results.append(
            {
                "competitor": competitor,
                "status": "estimated",
                "features": list(names),
                "absolute_oos_r2": future_r2,
                "past_mirror_absolute_oos_r2": past_r2,
                "past_mirror_guard_passed": (
                    None if future_r2 is None or past_r2 is None else future_r2 > past_r2
                ),
                "mae_ticks": float(np.mean(np.abs(y_test - prediction))),
                "train_n": len(train),
                "test_n": len(test),
                "row_hash": _row_hash(observations, test),
                "metrics": metrics,
                **fit,
            }
        )
    estimated = {row["competitor"]: row for row in results if row.get("status") == "estimated"}
    expected_estimated = set(COMPETITOR_ORDER) - ({"C10"} if not touch_covered else set())
    if set(estimated) != expected_estimated:
        raise RuntimeError(
            "D39 competitor panel is incomplete: "
            f"expected {sorted(expected_estimated)}, observed {sorted(estimated)}"
        )
    row_hashes = {str(row["row_hash"]) for row in estimated.values()}
    if row_hashes != {_row_hash(observations, test)}:
        raise RuntimeError(f"D39 competitors do not share identical test rows: {row_hashes}")
    for competitor, row in estimated.items():
        assert_companion_metrics(
            row, label=f"D39 {reference}/{levels}/{window}/{horizon}/{competitor}"
        )
    for row in estimated.values():
        value = row["absolute_oos_r2"]
        row["incremental_oos_r2_over_c0"] = (
            None if value is None else value - float(estimated["C0"]["absolute_oos_r2"])
        )
        row["incremental_oos_r2_over_c2"] = (
            None if value is None else value - float(estimated["C2"]["absolute_oos_r2"])
        )
        row["incremental_oos_r2_over_c3"] = (
            None if value is None else value - float(estimated["C3"]["absolute_oos_r2"])
        )
        hit = row["metrics"]["sign_accuracy"]["all_rows"]["hit_rate"]
        c1_hit = estimated["C1"]["metrics"]["sign_accuracy"]["all_rows"]["hit_rate"]
        c2_hit = estimated["C2"]["metrics"]["sign_accuracy"]["all_rows"]["hit_rate"]
        row["sign_accuracy_excess_over_c1"] = (
            None if hit is None or c1_hit is None else hit - c1_hit
        )
        row["sign_accuracy_excess_over_c2"] = (
            None if hit is None or c2_hit is None else hit - c2_hit
        )
    c8 = estimated["C8"]
    c2 = estimated["C2"]
    c12 = estimated["C12"]
    c1_hit = estimated["C1"]["metrics"]["sign_accuracy"]["all_rows"]["hit_rate"]
    c8_hit = c8["metrics"]["sign_accuracy"]["all_rows"]["hit_rate"]
    conditions = {
        "positive_absolute_oos_r2": bool(
            c8["absolute_oos_r2"] is not None and c8["absolute_oos_r2"] > 0.0
        ),
        "c8_beats_lagged_return_c2": bool(
            c8["absolute_oos_r2"] is not None
            and c2["absolute_oos_r2"] is not None
            and c8["absolute_oos_r2"] > c2["absolute_oos_r2"]
        ),
        "c12_adds_beyond_lagged_return_c2": bool(
            c12["incremental_oos_r2_over_c2"] is not None
            and c12["incremental_oos_r2_over_c2"] > 0.0
        ),
        "past_mirror_guard_not_tripped": c8["past_mirror_guard_passed"] is True,
        "sign_accuracy_at_least_c1": bool(
            c8_hit is not None and c1_hit is not None and c8_hit >= c1_hit
        ),
    }
    failed = {name for name, passed in conditions.items() if not passed}
    if not failed:
        verdict = "predictive"
    elif failed == {"sign_accuracy_at_least_c1"}:
        verdict = "magnitude_only"
    elif failed & {"c8_beats_lagged_return_c2", "c12_adds_beyond_lagged_return_c2"}:
        verdict = "subsumed_by_past"
    else:
        verdict = "not_predictive"
    ranking = sorted(
        (
            {
                "rank": 0,
                "competitor": row["competitor"],
                "absolute_oos_r2": row["absolute_oos_r2"],
            }
            for row in estimated.values()
            if row["absolute_oos_r2"] is not None
        ),
        key=lambda row: (-float(row["absolute_oos_r2"]), str(row["competitor"])),
    )
    for index, row in enumerate(ranking, start=1):
        row["rank"] = index
    return {
        "reference_price": reference,
        "h1_seconds": window,
        "h2_seconds": horizon,
        "levels": levels,
        "causal_gap_seconds": CAUSAL_GAP_SECONDS,
        "status": "estimated",
        "train_n": len(train),
        "test_n": len(test),
        "common_test_row_hash": _row_hash(observations, test),
        "effective_touch_competitor_covered": touch_covered,
        "competitors": results,
        "ranking_by_absolute_oos_r2": ranking,
        "ofi_question": {
            "c2_lagged_return_absolute_oos_r2": c2["absolute_oos_r2"],
            "c8_ofi_absolute_oos_r2": c8["absolute_oos_r2"],
            "c12_lagged_plus_ofi_absolute_oos_r2": c12["absolute_oos_r2"],
            "c12_incremental_oos_r2_over_c2": c12["incremental_oos_r2_over_c2"],
            "conditions": conditions,
            "verdict": verdict,
        },
    }


def build_fixed_target_panel(
    tape: HorseRaceTapeInput,
    *,
    prints: Sequence[TradePrint],
    references: Sequence[str] = D39_REFERENCE_PRICE_LADDER,
    levels: Sequence[int] = CCZ_LEVEL_COUNTS,
    windows: Sequence[float] = WINDOWS_SECONDS,
    horizons: Sequence[float] = HORIZONS_SECONDS,
    replicates: int = 399,
    seed: int = 20260820,
    embargo_seconds: float = EMBARGO_SECONDS,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cell_callback: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    observations = list(tape.observations)
    if not observations:
        raise ValueError("D39 needs at least one observation")
    minimum_embargo = CAUSAL_GAP_SECONDS + max(float(value) for value in horizons)
    if embargo_seconds < minimum_embargo:
        raise ValueError(
            "embargo_seconds must cover the causal gap plus the longest response horizon "
            f"({minimum_embargo:g} seconds)"
        )
    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations],
        embargo_seconds=embargo_seconds,
    )
    training_upper = max(observations[position].receive_ts_ns for position in split.train)
    bounce = roll_diagnostics(prints, training_upper_bound_ts_ns=training_upper)
    half = bounce["training_fit"]["effective_half_spread_ticks"]
    corrected = build_trade_sign_corrected_path(prints, effective_half_spread_ticks=half)
    same_side = build_same_side_print_path(prints)
    epoch_bounds = _epoch_bounds(observations)
    cells: list[dict[str, Any]] = []
    total = len(references) * len(levels) * len(windows) * len(horizons)
    completed = 0
    for reference in references:
        resolver = make_return_resolver(reference, corrected=corrected, same_side=same_side)
        for level_count in levels:
            for window in windows:
                for horizon in horizons:
                    cell = evaluate_panel_cell(
                        observations,
                        split,
                        reference=reference,
                        resolver=resolver,
                        window=float(window),
                        horizon=float(horizon),
                        levels=int(level_count),
                        replicates=replicates,
                        seed=(
                            seed
                            + completed * 100_000
                            + int(float(window) * 1000)
                            + int(float(horizon) * 100)
                        ),
                        epoch_bounds=epoch_bounds,
                    )
                    cells.append(cell)
                    completed += 1
                    if cell_callback is not None:
                        cell_callback(cell, completed, total)
                    if progress is not None:
                        progress(
                            {
                                "completed_cells": completed,
                                "total_cells": total,
                                "reference_price": reference,
                                "levels": level_count,
                                "h1_seconds": window,
                                "h2_seconds": horizon,
                                "status": cell["status"],
                            }
                        )
    bounce_cells = [
        cell
        for cell in cells
        if cell.get("status") == "estimated"
        and cell["reference_price"] in {"last_trade", TRADE_SIGN_CORRECTED}
    ]
    bounce_index = {
        (cell["reference_price"], cell["levels"], cell["h1_seconds"], cell["h2_seconds"]): cell
        for cell in bounce_cells
    }
    comparisons: list[dict[str, Any]] = []
    for key in sorted(
        {(cell["levels"], cell["h1_seconds"], cell["h2_seconds"]) for cell in bounce_cells}
    ):
        last = bounce_index.get(("last_trade", *key))
        corrected_cell = bounce_index.get((TRADE_SIGN_CORRECTED, *key))
        if last is None or corrected_cell is None:
            continue
        comparisons.append(
            {
                "levels": key[0],
                "h1_seconds": key[1],
                "h2_seconds": key[2],
                "last_trade": last["ofi_question"],
                "trade_sign_corrected": corrected_cell["ofi_question"],
                "id_bounce_01_discharged": (
                    corrected_cell["ofi_question"]["conditions"]["positive_absolute_oos_r2"]
                    and corrected_cell["ofi_question"]["conditions"]["c8_beats_lagged_return_c2"]
                    and corrected_cell["ofi_question"]["conditions"][
                        "c12_adds_beyond_lagged_return_c2"
                    ]
                ),
            }
        )
    return {
        "schema_version": 1,
        "scan_id": RETROSPECTIVE_SCAN_ID,
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "sample_role": "retrospective_partial_session_exploration",
        "confirmatory_eligible": False,
        "registered_replication_eligible": False,
        "sig21_calibration_eligible": False,
        "order_entry_enabled": False,
        "opening_coverage_missed": True,
        "tape": {
            "run_id": tape.run_id,
            "instrument_id": tape.instrument_id,
            "sha256": tape.tape_sha256,
            "observations": len(observations),
            "depth20_publications": tape.depth20_publications,
            "depth200_publications": tape.depth200_publications,
            "observed_seconds": tape.observed_seconds,
            "failures": tape.failures,
        },
        "split": {
            "train_n": len(split.train),
            "embargoed_n": len(split.embargoed),
            "test_n": len(split.test),
            "embargo_seconds": split.embargo_seconds,
            "boundaries": split.boundaries,
        },
        "axes": {
            "references": list(references),
            "levels": list(levels),
            "windows_seconds": list(windows),
            "horizons_seconds": list(horizons),
            "competitors": list(COMPETITOR_ORDER),
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "m200_status": "explicitly_deferred_by_frozen_spec",
        },
        "bounce": {
            **bounce,
            "trade_sign_corrected_points": len(corrected),
            "same_side_print_points": len(same_side.all_timestamps),
            "comparisons": comparisons,
        },
        "cells": cells,
        "evidence_level": (
            "retrospective exploratory replay on one validated partial-session tape; "
            "the design was written after outcomes had been inspected"
        ),
    }
