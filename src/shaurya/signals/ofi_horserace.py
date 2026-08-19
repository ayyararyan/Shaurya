"""Frozen exploratory predictor horse race `X-OFI-HORSERACE-DAT20-05`.

The module compares depth, static imbalance, identified signed trades, canonical CKS L1 OFI,
price-keyed multi-level OFI, depth-adjusted multi-level OFI, and a regularised combination.  It
uses only information available at each depth200 anchor and is permanently non-confirmatory.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import isfinite, log1p, sqrt
from typing import Any, Literal

import numpy as np

from shaurya.data.depth_thinning_analysis import BookState, parse_receive_ts_ns
from shaurya.data.trade_direction import TRADE_ALIGNMENT_VERSION, TRADE_CLASSIFIER_VERSION
from shaurya.signals.cks_l1_ofi import cks_l1_transition
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EMBARGO_SECONDS,
    Observation,
    SplitIndex,
    _r_squared,
    build_depth20_mid_series,
    chronological_embargoed_split,
    estimate_mean,
    fit_ridge,
)
from shaurya.signals.deep_book_ofi import (
    CAUSAL_GAP_SECONDS,
    OFI_WINDOWS_SECONDS,
    _controls,
    _mid_return,
    price_keyed_ofi_transition,
)
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND

EXPLORATORY_SCAN_ID = "X-OFI-HORSERACE-DAT20-05"
CONFIRMATORY_ELIGIBLE = False
DESIGN_DOCUMENT = "docs/OFI-HORSERACE-SPEC-2026-08-19.md"
RETURN_HORIZONS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
CONDITIONAL_HORIZON_SECONDS = 30.0
BANDS = ((1, 1), (2, 5), (6, 10), (11, 20), (21, 50), (51, 100), (101, 200))
RIDGE_ALPHAS = (0.0, 0.01, 0.1, 1.0, 10.0, 100.0)
MODEL_ORDER = ("M0", "M1", "M2", "M3", "M4", "M5", "M6")
MINIMUM_FIT_OBSERVATIONS = 20
MINIMUM_TRADE_PACKETS = 20


def _label(value: float) -> str:
    return str(value).replace(".", "p").rstrip("0").rstrip("p")


def pk_band_feature(window: float, lower: int, upper: int) -> str:
    return f"pk_ofi_w{_label(window)}__band_{lower}_{upper}"


def adjusted_band_feature(window: float, lower: int, upper: int) -> str:
    return f"depth_adjusted_pk_ofi_w{_label(window)}__band_{lower}_{upper}"


def cks_feature(window: float) -> str:
    return f"cks_ofi_w{_label(window)}"


def cks_pressure_feature(window: float) -> str:
    return f"cks_pressure_w{_label(window)}"


def trade_feature(window: float) -> str:
    return f"signed_trade_imbalance_w{_label(window)}"


def normalised_trade_feature(window: float) -> str:
    return f"normalised_trade_imbalance_w{_label(window)}"


@dataclass(frozen=True, slots=True)
class TradeSeries:
    timestamps: tuple[int, ...]
    signed_prefix: tuple[float, ...]
    absolute_prefix: tuple[float, ...]
    schema_packets: int
    qualified_packets: int
    excluded_missing_classifier_version: int
    excluded_wrong_classifier_version: int
    excluded_missing_alignment_version: int
    excluded_wrong_alignment_version: int
    excluded_coalesced: int
    excluded_degraded_or_unclassified: int

    @property
    def identified(self) -> bool:
        return self.schema_packets > 0 and self.qualified_packets >= MINIMUM_TRADE_PACKETS

    def window(self, start_ns: int, end_ns: int) -> tuple[float, float]:
        left = bisect_right(self.timestamps, start_ns)
        right = bisect_right(self.timestamps, end_ns)
        return (
            self.signed_prefix[right] - self.signed_prefix[left],
            self.absolute_prefix[right] - self.absolute_prefix[left],
        )


def build_trade_series(rows: Sequence[Mapping[str, Any]]) -> TradeSeries:
    """Build capture-time signed executed-volume innovations; never infer an absent sign."""

    values: list[tuple[int, float, float]] = []
    schema_packets = 0
    missing_classifier = 0
    wrong_classifier = 0
    missing_alignment = 0
    wrong_alignment = 0
    coalesced = 0
    degraded = 0
    for row in rows:
        if row.get("event_type") != "full" or row.get("cumulative_volume_increment") is None:
            continue
        if not any(
            key in row
            for key in (
                "trade_side",
                "trade_classifier_version",
                "trade_alignment_version",
                "trade_classification_degraded",
                "trade_coalesced",
            )
        ):
            continue
        schema_packets += 1
        increment = float(row["cumulative_volume_increment"])
        if increment <= 0:
            continue
        classifier_version = row.get("trade_classifier_version")
        if classifier_version is None:
            missing_classifier += 1
            continue
        if classifier_version != TRADE_CLASSIFIER_VERSION:
            wrong_classifier += 1
            continue
        alignment_version = row.get("trade_alignment_version")
        if alignment_version is None:
            missing_alignment += 1
            continue
        if alignment_version != TRADE_ALIGNMENT_VERSION:
            wrong_alignment += 1
            continue
        if row.get("trade_coalesced"):
            coalesced += 1
            continue
        side = row.get("trade_side")
        if row.get("trade_classification_degraded") or side not in {"buy", "sell"}:
            degraded += 1
            continue
        quantity = row.get("last_quantity")
        stamp = row.get("receive_ts")
        if quantity is None or not isinstance(stamp, str):
            degraded += 1
            continue
        absolute_quantity = float(quantity)
        if not isfinite(absolute_quantity) or absolute_quantity <= 0:
            degraded += 1
            continue
        values.append(
            (
                parse_receive_ts_ns(stamp),
                absolute_quantity if side == "buy" else -absolute_quantity,
                absolute_quantity,
            )
        )
    values.sort()
    signed = [0.0]
    absolute_prefix = [0.0]
    for _, signed_value, absolute_value in values:
        signed.append(signed[-1] + signed_value)
        absolute_prefix.append(absolute_prefix[-1] + absolute_value)
    return TradeSeries(
        timestamps=tuple(value[0] for value in values),
        signed_prefix=tuple(signed),
        absolute_prefix=tuple(absolute_prefix),
        schema_packets=schema_packets,
        qualified_packets=len(values),
        excluded_missing_classifier_version=missing_classifier,
        excluded_wrong_classifier_version=wrong_classifier,
        excluded_missing_alignment_version=missing_alignment,
        excluded_wrong_alignment_version=wrong_alignment,
        excluded_coalesced=coalesced,
        excluded_degraded_or_unclassified=degraded,
    )


@dataclass(frozen=True, slots=True)
class HorseRaceObservation:
    tape_index: int
    run_id: str
    receive_ts_ns: int
    features: Mapping[str, float]
    future_ticks: Mapping[float, float]
    past_ticks: Mapping[float, float]
    same_window_ticks: Mapping[float, float]
    window_start_ts_ns: Mapping[float, int]
    connection_epoch: int = 1


def _band_depths(state: BookState) -> dict[tuple[int, int], float | None]:
    result: dict[tuple[int, int], float | None] = {}
    for lower, upper in BANDS:
        levels = (*state.bids[lower - 1 : upper], *state.asks[lower - 1 : upper])
        result[(lower, upper)] = float(sum(level[1] for level in levels)) if levels else None
    return result


def build_horserace_observations(
    *,
    depth200_states: Sequence[BookState],
    depth20_states: Sequence[BookState],
    rows: Sequence[Mapping[str, Any]],
    tape_index: int,
    run_id: str,
) -> tuple[list[HorseRaceObservation], dict[str, Any]]:
    """Construct all predictors and responses at one common causal anchor clock."""

    failures: dict[str, Any] = {
        "invalid_transition": 0,
        "incomplete_history": 0,
        "unusable_state": 0,
        "no_response_anchor": 0,
        "no_future_coverage": 0,
    }
    trades = build_trade_series(rows)
    failures["trade_support"] = {
        "schema_packets": trades.schema_packets,
        "qualified_packets": trades.qualified_packets,
        "excluded_missing_classifier_version": trades.excluded_missing_classifier_version,
        "excluded_wrong_classifier_version": trades.excluded_wrong_classifier_version,
        "excluded_missing_alignment_version": trades.excluded_missing_alignment_version,
        "excluded_wrong_alignment_version": trades.excluded_wrong_alignment_version,
        "excluded_coalesced": trades.excluded_coalesced,
        "excluded_degraded_or_unclassified": trades.excluded_degraded_or_unclassified,
        "identified": trades.identified,
    }
    if len(depth200_states) < 2:
        return [], failures
    cks = [
        cks_l1_transition(previous, current)
        for previous, current in zip(depth200_states[:-1], depth200_states[1:], strict=True)
    ]
    pk = [
        price_keyed_ofi_transition(previous, current)
        for previous, current in zip(depth200_states[:-1], depth200_states[1:], strict=True)
    ]
    stamps = [transition.receive_ts_ns for transition in cks]
    invalid_prefix = [0]
    cks_prefix = [0.0]
    l1_depth_prefix = [0.0]
    pk_prefix = {band: [0.0] for band in BANDS}
    depth_prefix = {band: [0.0] for band in BANDS}
    band_presence_prefix = {band: [0] for band in BANDS}
    count_prefix = [0]
    for transition, pk_transition, state in zip(cks, pk, depth200_states[1:], strict=True):
        valid = transition.invalid_reason is None and pk_transition.invalid_reason is None
        invalid_prefix.append(invalid_prefix[-1] + int(not valid))
        failures["invalid_transition"] += int(not valid)
        cks_prefix.append(cks_prefix[-1] + (transition.event if valid else 0.0))
        l1_depth_prefix.append(
            l1_depth_prefix[-1] + (transition.half_total_depth if valid else 0.0)
        )
        depths = _band_depths(state)
        previous_depth_value = 0.0
        previous_cutoff = 0
        for band in BANDS:
            _, upper = band
            cumulative = pk_transition.cumulative_by_depth[upper] if valid else 0.0
            marginal = cumulative - previous_depth_value
            pk_prefix[band].append(pk_prefix[band][-1] + marginal)
            depth = depths[band]
            depth_prefix[band].append(
                depth_prefix[band][-1] + (depth if valid and depth is not None else 0.0)
            )
            band_presence_prefix[band].append(
                band_presence_prefix[band][-1] + int(valid and depth is not None)
            )
            previous_depth_value = cumulative
            previous_cutoff = upper
        del previous_cutoff
        count_prefix.append(count_prefix[-1] + int(valid))
    mid_series = build_depth20_mid_series(depth20_states)
    observations: list[HorseRaceObservation] = []
    gap_ns = int(CAUSAL_GAP_SECONDS * NANOSECONDS_PER_SECOND)
    longest_ns = int(max(OFI_WINDOWS_SECONDS) * NANOSECONDS_PER_SECOND)
    all_horizons = (*RETURN_HORIZONS_SECONDS, CONDITIONAL_HORIZON_SECONDS)
    for position, (state, transition) in enumerate(zip(depth200_states[1:], cks, strict=True)):
        if transition.invalid_reason is not None:
            continue
        if state.receive_ts_ns - depth200_states[0].receive_ts_ns < longest_ns:
            failures["incomplete_history"] += 1
            continue
        controls = _controls(state)
        if controls is None or not state.bids or not state.asks:
            failures["unusable_state"] += 1
            continue
        bid_quantity = state.bids[0][1]
        ask_quantity = state.asks[0][1]
        total_l1 = bid_quantity + ask_quantity
        if total_l1 <= 0:
            failures["unusable_state"] += 1
            continue
        features: dict[str, float] = {
            "spread_ticks": controls["spread_ticks"],
            "log1p_l1_depth": log1p(total_l1),
            "l1_queue_imbalance": (bid_quantity - ask_quantity) / total_l1,
        }
        window_starts: dict[float, int] = {}
        complete = True
        for window in OFI_WINDOWS_SECONDS:
            start = state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND)
            left = bisect_right(stamps, start)
            right = position + 1
            if left >= right or invalid_prefix[right] - invalid_prefix[left] != 0:
                complete = False
                break
            covered = count_prefix[right] - count_prefix[left]
            if covered <= 0:
                complete = False
                break
            cks_value = cks_prefix[right] - cks_prefix[left]
            mean_l1_half_depth = (l1_depth_prefix[right] - l1_depth_prefix[left]) / covered
            features[cks_feature(window)] = cks_value
            features[cks_pressure_feature(window)] = cks_value / max(mean_l1_half_depth, 1.0)
            signed_trade, absolute_trade = trades.window(start, state.receive_ts_ns)
            features[trade_feature(window)] = signed_trade
            if absolute_trade > 0:
                features[normalised_trade_feature(window)] = signed_trade / absolute_trade
            for band in BANDS:
                lower, upper = band
                flow = pk_prefix[band][right] - pk_prefix[band][left]
                features[pk_band_feature(window, lower, upper)] = flow
                band_support = band_presence_prefix[band][right] - band_presence_prefix[band][left]
                if band_support == covered:
                    mean_depth = (depth_prefix[band][right] - depth_prefix[band][left]) / covered
                    features[adjusted_band_feature(window, lower, upper)] = flow / max(
                        mean_depth, 1.0
                    )
            window_starts[window] = stamps[left]
        if not complete:
            failures["incomplete_history"] += 1
            continue
        response_anchor = state.receive_ts_ns + gap_ns
        if mid_series.as_of(response_anchor) is None:
            failures["no_response_anchor"] += 1
            continue
        future: dict[float, float] = {}
        past: dict[float, float] = {}
        for horizon in all_horizons:
            horizon_ns = int(horizon * NANOSECONDS_PER_SECOND)
            value = _mid_return(mid_series, response_anchor, response_anchor + horizon_ns)
            if value is not None:
                future[horizon] = value
            mirror = _mid_return(mid_series, state.receive_ts_ns - horizon_ns, state.receive_ts_ns)
            if mirror is not None:
                past[horizon] = mirror
        if not any(horizon in future for horizon in RETURN_HORIZONS_SECONDS):
            failures["no_future_coverage"] += 1
            continue
        same: dict[float, float] = {}
        for window in OFI_WINDOWS_SECONDS:
            value = _mid_return(
                mid_series,
                state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND),
                state.receive_ts_ns,
            )
            if value is not None:
                same[window] = value
        observations.append(
            HorseRaceObservation(
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=state.receive_ts_ns,
                features=features,
                future_ticks=future,
                past_ticks=past,
                same_window_ticks=same,
                window_start_ts_ns=window_starts,
                connection_epoch=state.connection_epoch,
            )
        )
    return observations, failures


def as_normal_observation(observation: HorseRaceObservation) -> Observation:
    return Observation(
        tape_index=observation.tape_index,
        run_id=observation.run_id,
        receive_ts_ns=observation.receive_ts_ns,
        time_bucket="mid_afternoon",
        features=observation.features,
        future_ticks=observation.future_ticks,
        past_ticks=observation.past_ticks,
        contemporaneous_ticks={},
    )


def assert_no_lookahead(observations: Sequence[HorseRaceObservation]) -> None:
    for observation in observations:
        for window, start in observation.window_start_ts_ns.items():
            if start <= observation.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND):
                raise AssertionError(
                    "predictor window included an event at/before its open boundary"
                )
            if start > observation.receive_ts_ns:
                raise AssertionError("predictor window starts in the future")


def model_features(model: str, window: float, *, trade_identified: bool) -> tuple[str, ...]:
    baseline = ("log1p_l1_depth", "spread_ticks")
    pk_names = tuple(pk_band_feature(window, *band) for band in BANDS)
    adjusted = tuple(adjusted_band_feature(window, *band) for band in BANDS)
    specifications = {
        "M0": baseline,
        "M1": (*baseline, "l1_queue_imbalance"),
        "M2": (*baseline, trade_feature(window)) if trade_identified else (),
        "M3": (*baseline, cks_feature(window)),
        "M4": (*baseline, *pk_names),
        "M5": (*baseline, *adjusted),
        "M6": (
            *baseline,
            "l1_queue_imbalance",
            *((trade_feature(window),) if trade_identified else ()),
            cks_feature(window),
            *pk_names,
            *adjusted,
        ),
    }
    if model not in specifications:
        raise ValueError(f"unknown model {model}")
    return specifications[model]


def _target(
    observations: Sequence[HorseRaceObservation],
    positions: Sequence[int],
    horizon: float,
    source: Literal["future", "past"],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [
            (
                observations[position].future_ticks
                if source == "future"
                else observations[position].past_ticks
            )[horizon]
            for position in positions
        ],
        dtype=np.float64,
    )


def _design(
    observations: Sequence[HorseRaceObservation], positions: Sequence[int], names: Sequence[str]
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [[observations[position].features[name] for name in names] for position in positions],
        dtype=np.float64,
    ).reshape(len(positions), len(names))


def _has_features(observation: HorseRaceObservation, names: Sequence[str]) -> bool:
    return all(
        name in observation.features and isfinite(float(observation.features[name]))
        for name in names
    )


def _positions(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    horizon: float,
    source: Literal["future", "past"],
    *,
    names: Sequence[str] = (),
) -> tuple[int, ...]:
    return tuple(
        position
        for position in candidates
        if horizon
        in (
            observations[position].future_ticks
            if source == "future"
            else observations[position].past_ticks
        )
        and _has_features(observations[position], names)
    )


def _inner_folds(
    observations: Sequence[HorseRaceObservation], train_positions: Sequence[int]
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    by_tape: dict[int, list[int]] = {}
    for position in train_positions:
        by_tape.setdefault(observations[position].tape_index, []).append(position)
    folds: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    embargo_ns = int((max(RETURN_HORIZONS_SECONDS) + CAUSAL_GAP_SECONDS) * NANOSECONDS_PER_SECOND)
    for fraction in (0.5, 0.65, 0.8):
        inner_train: list[int] = []
        validation: list[int] = []
        for positions in by_tape.values():
            ordered = sorted(positions, key=lambda item: observations[item].receive_ts_ns)
            cut = max(1, int(len(ordered) * fraction))
            boundary = observations[ordered[cut - 1]].receive_ts_ns
            validation_end = min(len(ordered), cut + max(1, len(ordered) // 10))
            inner_train.extend(ordered[:cut])
            validation.extend(
                item
                for item in ordered[cut:validation_end]
                if observations[item].receive_ts_ns > boundary + embargo_ns
            )
        if len(inner_train) >= MINIMUM_FIT_OBSERVATIONS and validation:
            folds.append((tuple(inner_train), tuple(validation)))
    return tuple(folds)


def select_ridge_alpha(
    observations: Sequence[HorseRaceObservation],
    train_positions: Sequence[int],
    *,
    names: Sequence[str],
    horizon: float,
    source: Literal["future", "past"],
) -> tuple[float, tuple[dict[str, float], ...]]:
    """Select penalty entirely inside training by three deterministic expanding folds."""

    scores: dict[float, list[float]] = {alpha: [] for alpha in RIDGE_ALPHAS}
    folds = _inner_folds(observations, train_positions)
    for inner_train, validation in folds:
        raw_train = _target(observations, inner_train, horizon, source)
        raw_validation = _target(observations, validation, horizon, source)
        drift = float(raw_train.mean())
        design_train = _design(observations, inner_train, names)
        design_validation = _design(observations, validation, names)
        for alpha in RIDGE_ALPHAS:
            fit = fit_ridge(design_train, raw_train - drift, feature_names=names, penalty=alpha)
            residual = raw_validation - drift - fit.predict(design_validation)
            scores[alpha].append(float(np.mean(residual**2)))
    mean_scores = {
        alpha: (float(np.mean(values)) if values else float("inf"))
        for alpha, values in scores.items()
    }
    selected = min(RIDGE_ALPHAS, key=lambda alpha: (mean_scores[alpha], alpha))
    if not isfinite(mean_scores[selected]):
        selected = RIDGE_ALPHAS[0]
    diagnostics = tuple(
        {
            "alpha": alpha,
            "mean_validation_mse": mean_scores[alpha],
            "folds": float(len(scores[alpha])),
        }
        for alpha in RIDGE_ALPHAS
    )
    return selected, diagnostics


@dataclass(frozen=True, slots=True)
class FittedScore:
    payload: Mapping[str, Any]
    errors: tuple[float, ...]
    predictions: tuple[float, ...]
    target_drift: float
    fit: Any


def _fit_score(
    observations: Sequence[HorseRaceObservation],
    train: Sequence[int],
    test: Sequence[int],
    *,
    model: str,
    names: Sequence[str],
    horizon: float,
    source: Literal["future", "past"],
) -> FittedScore:
    raw_train = _target(observations, train, horizon, source)
    raw_test = _target(observations, test, horizon, source)
    drift = float(raw_train.mean())
    train_target = raw_train - drift
    test_target = raw_test - drift
    train_design = _design(observations, train, names)
    test_design = _design(observations, test, names)
    regularised = model in {"M4", "M5", "M6"}
    alpha, cv = (
        select_ridge_alpha(observations, train, names=names, horizon=horizon, source=source)
        if regularised
        else (0.0, ())
    )
    fit = fit_ridge(train_design, train_target, feature_names=names, penalty=alpha)
    fitted = fit.predict(train_design)
    predicted = fit.predict(test_design)
    in_sample = _r_squared(train_target, fitted, np.zeros(train_target.shape, dtype=np.float64))
    degrees = len(train) - len(names) - 1
    adjusted = (
        None
        if in_sample is None or degrees <= 0
        else 1.0 - (1.0 - in_sample) * (len(train) - 1) / degrees
    )
    residual = test_target - predicted
    coefficients = {name: float(fit.coefficients[index]) for index, name in enumerate(names)}
    raw_coefficients = {
        name: float(fit.coefficients[index] / fit.scale[index]) for index, name in enumerate(names)
    }
    payload: dict[str, Any] = {
        "status": "estimated",
        "features": list(names),
        "train_n": len(train),
        "test_n": len(test),
        "in_sample_r2": in_sample,
        "in_sample_adjusted_r2": adjusted,
        "oos_r2_training_mean": _r_squared(
            test_target, predicted, np.zeros(test_target.shape, dtype=np.float64)
        ),
        "rmse_ticks": sqrt(float(np.mean(residual**2))),
        "mae_ticks": float(np.mean(np.abs(residual))),
        "target_training_mean_ticks": drift,
        "selected_alpha": alpha,
        "inner_cv": cv,
        "coefficients_ticks_per_training_sd": coefficients,
        "raw_coefficients_ticks_per_unit": raw_coefficients,
        "training_standardisation": {
            "centre": {name: float(fit.centre[index]) for index, name in enumerate(names)},
            "scale": {name: float(fit.scale[index]) for index, name in enumerate(names)},
            "source": "training_only",
        },
    }
    return FittedScore(
        payload=payload,
        errors=tuple(float(value) for value in residual**2),
        predictions=tuple(float(value) for value in predicted),
        target_drift=drift,
        fit=fit,
    )


def _difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _per_tape_scores(
    observations: Sequence[HorseRaceObservation],
    test: Sequence[int],
    *,
    horizon: float,
    source: Literal["future", "past"],
    score: FittedScore,
    baseline: FittedScore,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tape in sorted({observations[position].tape_index for position in test}):
        selection = [
            index
            for index, position in enumerate(test)
            if observations[position].tape_index == tape
        ]
        positions = [test[index] for index in selection]
        target = _target(observations, positions, horizon, source) - score.target_drift
        predicted = np.asarray([score.predictions[index] for index in selection])
        baseline_predicted = np.asarray([baseline.predictions[index] for index in selection])
        benchmark = np.zeros(target.shape, dtype=np.float64)
        current_r2 = _r_squared(target, predicted, benchmark)
        baseline_r2 = _r_squared(target, baseline_predicted, benchmark)
        result[str(tape)] = {
            "test_n": len(positions),
            "oos_r2_training_mean": current_r2,
            "incremental_oos_r2_over_m0": _difference(current_r2, baseline_r2),
            "rmse_ticks": sqrt(float(np.mean((target - predicted) ** 2))),
            "mae_ticks": float(np.mean(np.abs(target - predicted))),
        }
    return result


def _direction_by_tape(
    observations: Sequence[HorseRaceObservation],
    train: Sequence[int],
    *,
    names: Sequence[str],
    model: str,
    horizon: float,
    source: Literal["future", "past"],
    alpha: float,
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    baseline = {"log1p_l1_depth", "spread_ticks"}
    for tape in sorted({observations[position].tape_index for position in train}):
        positions = [position for position in train if observations[position].tape_index == tape]
        if len(positions) < len(names) + 3:
            result[str(tape)] = None
            continue
        target = _target(observations, positions, horizon, source)
        design = _design(observations, positions, names)
        fit = fit_ridge(design, target - target.mean(), feature_names=names, penalty=alpha)
        family_indices = [index for index, name in enumerate(names) if name not in baseline]
        if not family_indices:
            result[str(tape)] = None
            continue
        if len(family_indices) == 1:
            result[str(tape)] = float(fit.coefficients[family_indices[0]])
            continue
        standardised = (design - fit.centre) / fit.scale
        contribution = standardised[:, family_indices] @ fit.coefficients[family_indices]
        covariance = float(np.mean((contribution - contribution.mean()) * (target - target.mean())))
        result[str(tape)] = covariance
    return result


def _band_contribution_diagnostics(
    observations: Sequence[HorseRaceObservation],
    train: Sequence[int],
    test: Sequence[int],
    *,
    names: Sequence[str],
    model: Literal["M4", "M5"],
    horizon: float,
    source: Literal["future", "past"],
    score: FittedScore,
) -> dict[str, Any]:
    """Decompose a fitted Ridge family into auditable per-band held-out contributions."""

    prefix = "pk_ofi_" if model == "M4" else "depth_adjusted_pk_ofi_"
    feature_indices = [index for index, name in enumerate(names) if name.startswith(prefix)]
    test_design = _design(observations, test, names)
    standardised_test = (test_design - score.fit.centre) / score.fit.scale
    tape_fits: dict[int, Any] = {}
    for tape in sorted({observations[position].tape_index for position in train}):
        positions = [position for position in train if observations[position].tape_index == tape]
        if len(positions) < len(names) + 3:
            continue
        target = _target(observations, positions, horizon, source)
        tape_fits[tape] = fit_ridge(
            _design(observations, positions, names),
            target - target.mean(),
            feature_names=names,
            penalty=float(score.payload["selected_alpha"]),
        )

    rows: list[dict[str, Any]] = []
    for feature_index, band in zip(feature_indices, BANDS, strict=True):
        feature = names[feature_index]
        contribution = standardised_test[:, feature_index] * score.fit.coefficients[feature_index]
        per_tape: dict[str, Any] = {}
        tape_coefficients: list[float] = []
        for tape in sorted({observations[position].tape_index for position in test}):
            selection = np.asarray(
                [observations[position].tape_index == tape for position in test], dtype=bool
            )
            tape_fit = tape_fits.get(tape)
            coefficient = None if tape_fit is None else float(tape_fit.coefficients[feature_index])
            if coefficient is not None:
                tape_coefficients.append(coefficient)
            values = contribution[selection]
            per_tape[str(tape)] = {
                "test_n": int(selection.sum()),
                "coefficient_ticks_per_tape_training_sd": coefficient,
                "mean_test_contribution_ticks": float(values.mean()) if len(values) else None,
                "mean_absolute_test_contribution_ticks": (
                    float(np.mean(np.abs(values))) if len(values) else None
                ),
            }
        signs = [int(value > 0) - int(value < 0) for value in tape_coefficients]
        rows.append(
            {
                "band": [band[0], band[1]],
                "feature": feature,
                "train_n": len(train),
                "test_n": len(test),
                "coefficient_ticks_per_pooled_training_sd": float(
                    score.fit.coefficients[feature_index]
                ),
                "raw_coefficient_ticks_per_unit": float(
                    score.fit.coefficients[feature_index] / score.fit.scale[feature_index]
                ),
                "mean_test_contribution_ticks": float(contribution.mean()),
                "mean_absolute_test_contribution_ticks": float(np.mean(np.abs(contribution))),
                "rms_test_contribution_ticks": sqrt(float(np.mean(contribution**2))),
                "coefficient_sign_stable_across_tapes": (
                    len(signs) == len(per_tape)
                    and len(signs) >= 2
                    and len(set(signs)) == 1
                    and signs[0] != 0
                ),
                "per_tape": per_tape,
            }
        )
    return {
        "definition": (
            "held-out contribution = pooled Ridge coefficient (ticks per pooled training SD) "
            "times the feature standardised by pooled training centre/scale; per-tape "
            "coefficient stability refits the same selected alpha on each tape's training rows"
        ),
        "bands": rows,
    }


def _inference(
    baseline: FittedScore,
    score: FittedScore,
    observations: Sequence[HorseRaceObservation],
    test: Sequence[int],
    *,
    horizon: float,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    differential = [left - right for left, right in zip(baseline.errors, score.errors, strict=True)]
    estimate = estimate_mean(
        differential,
        [observations[position].receive_ts_ns for position in test],
        [observations[position].tape_index for position in test],
        overlap_seconds=horizon + CAUSAL_GAP_SECONDS,
        replicates=replicates,
        seed=seed,
    )
    return {**asdict(estimate), "naive_inference_valid": False}


def _support_by_tape(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    horizon: float,
    source: Literal["future", "past"],
    names: Sequence[str] = (),
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for tape in sorted({observation.tape_index for observation in observations}):

        def count(candidates: Sequence[int], tape_index: int = tape) -> int:
            return sum(
                observations[position].tape_index == tape_index
                and horizon
                in (
                    observations[position].future_ticks
                    if source == "future"
                    else observations[position].past_ticks
                )
                and _has_features(observations[position], names)
                for position in candidates
            )

        result[str(tape)] = {
            "total_n": sum(
                observation.tape_index == tape
                and horizon
                in (observation.future_ticks if source == "future" else observation.past_ticks)
                and _has_features(observation, names)
                for observation in observations
            ),
            "train_n": count(split.train),
            "embargoed_n": count(split.embargoed),
            "test_n": count(split.test),
        }
    return result


def _collinearity(
    observations: Sequence[HorseRaceObservation], train: Sequence[int], names: Sequence[str]
) -> dict[str, float | None]:
    if len(names) < 2:
        return {"max_absolute_correlation": None, "condition_number": None, "max_vif": None}
    design = _design(observations, train, names)
    scale = design.std(axis=0)
    active = scale > 0
    if active.sum() < 2:
        return {"max_absolute_correlation": 0.0, "condition_number": None, "max_vif": None}
    standardised = (design[:, active] - design[:, active].mean(axis=0)) / scale[active]
    correlation = np.corrcoef(standardised, rowvar=False)
    off_diagonal = correlation - np.eye(correlation.shape[0])
    inverse = np.linalg.pinv(correlation)
    return {
        "max_absolute_correlation": float(np.max(np.abs(off_diagonal))),
        "condition_number": float(np.linalg.cond(standardised)),
        "max_vif": float(np.max(np.diag(inverse))),
    }


def evaluate_cells(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    horizons: Sequence[float],
    source: Literal["future", "past"],
    trade_identified: bool,
    replicates: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon in horizons:
        for window in OFI_WINDOWS_SECONDS:
            feature_sets = {
                model: model_features(model, window, trade_identified=trade_identified)
                for model in MODEL_ORDER
            }
            common_names = tuple(
                dict.fromkeys(
                    name
                    for model in MODEL_ORDER
                    for name in feature_sets[model]
                    if feature_sets[model]
                )
            )
            train = _positions(observations, split.train, horizon, source, names=common_names)
            test = _positions(observations, split.test, horizon, source, names=common_names)
            embargoed = _positions(
                observations, split.embargoed, horizon, source, names=common_names
            )
            total = _positions(
                observations,
                tuple(range(len(observations))),
                horizon,
                source,
                names=common_names,
            )
            support_by_tape = _support_by_tape(
                observations,
                split,
                horizon=horizon,
                source=source,
                names=common_names,
            )
            if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
                raise ValueError(f"insufficient common support at h1={window}, h2={horizon}")
            scores: dict[str, FittedScore] = {}
            for model in MODEL_ORDER:
                names = feature_sets[model]
                if not names:
                    rows.append(
                        {
                            "source": source,
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "model": model,
                            "status": "blocked_unidentified_signed_trades",
                            "total_n": len(total),
                            "train_n": len(train),
                            "embargoed_n": len(embargoed),
                            "test_n": len(test),
                            "support_by_tape": support_by_tape,
                        }
                    )
                    continue
                model_total = _positions(
                    observations,
                    tuple(range(len(observations))),
                    horizon,
                    source,
                    names=names,
                )
                model_train = _positions(observations, split.train, horizon, source, names=names)
                model_embargoed = _positions(
                    observations, split.embargoed, horizon, source, names=names
                )
                model_test = _positions(observations, split.test, horizon, source, names=names)
                model_specific_support = {
                    "total_n": len(model_total),
                    "train_n": len(model_train),
                    "embargoed_n": len(model_embargoed),
                    "test_n": len(model_test),
                    "support_by_tape": _support_by_tape(
                        observations,
                        split,
                        horizon=horizon,
                        source=source,
                        names=names,
                    ),
                }
                score = _fit_score(
                    observations,
                    train,
                    test,
                    model=model,
                    names=names,
                    horizon=horizon,
                    source=source,
                )
                scores[model] = score
                baseline = scores["M0"]
                payload = dict(score.payload)
                current_r2 = payload["oos_r2_training_mean"]
                baseline_r2 = baseline.payload["oos_r2_training_mean"]
                payload.update(
                    {
                        "source": source,
                        "h1_seconds": window,
                        "h2_seconds": horizon,
                        "causal_gap_seconds": CAUSAL_GAP_SECONDS,
                        "model": model,
                        "total_n": len(total),
                        "embargoed_n": len(embargoed),
                        "support_by_tape": support_by_tape,
                        "common_sample_feature_count": len(common_names),
                        "model_specific_support_before_common_intersection": (
                            model_specific_support
                        ),
                        "support_loss_to_common_sample": {
                            "total_n": len(model_total) - len(total),
                            "train_n": len(model_train) - len(train),
                            "embargoed_n": len(model_embargoed) - len(embargoed),
                            "test_n": len(model_test) - len(test),
                        },
                        "incremental_oos_r2_over_m0": _difference(current_r2, baseline_r2),
                        "incremental_oos_r2_over_prior_model": (
                            _difference(current_r2, scores["M4"].payload["oos_r2_training_mean"])
                            if model == "M5"
                            else _difference(
                                current_r2, scores["M5"].payload["oos_r2_training_mean"]
                            )
                            if model == "M6"
                            else _difference(current_r2, baseline_r2)
                            if model == "M1"
                            else None
                        ),
                        "per_tape": _per_tape_scores(
                            observations,
                            test,
                            horizon=horizon,
                            source=source,
                            score=score,
                            baseline=baseline,
                        ),
                        "direction_by_tape": _direction_by_tape(
                            observations,
                            train,
                            names=names,
                            model=model,
                            horizon=horizon,
                            source=source,
                            alpha=float(payload["selected_alpha"]),
                        ),
                        "collinearity": _collinearity(observations, train, names[2:]),
                    }
                )
                if model in {"M4", "M5"}:
                    payload["band_contribution_diagnostics"] = _band_contribution_diagnostics(
                        observations,
                        train,
                        test,
                        names=names,
                        model="M4" if model == "M4" else "M5",
                        horizon=horizon,
                        source=source,
                        score=score,
                    )
                if model != "M0":
                    payload["error_improvement_inference_over_m0"] = _inference(
                        baseline,
                        score,
                        observations,
                        test,
                        horizon=horizon,
                        seed=seed + int(horizon * 1000) + int(window * 100) + int(model[1]),
                        replicates=replicates,
                    )
                rows.append(payload)
    return rows


def evaluate_same_window(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    trade_identified: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in OFI_WINDOWS_SECONDS:
        feature_sets = {
            model: model_features(model, window, trade_identified=trade_identified)
            for model in MODEL_ORDER
        }
        common_names = tuple(
            dict.fromkeys(
                name for model in MODEL_ORDER for name in feature_sets[model] if feature_sets[model]
            )
        )
        train = tuple(
            position
            for position in split.train
            if window in observations[position].same_window_ticks
            and _has_features(observations[position], common_names)
        )
        test = tuple(
            position
            for position in split.test
            if window in observations[position].same_window_ticks
            and _has_features(observations[position], common_names)
        )
        for model in MODEL_ORDER:
            names = feature_sets[model]
            if not names:
                rows.append({"h1_seconds": window, "model": model, "status": "blocked"})
                continue
            design_train = _design(observations, train, names)
            design_test = _design(observations, test, names)
            raw_train = np.asarray(
                [observations[position].same_window_ticks[window] for position in train]
            )
            raw_test = np.asarray(
                [observations[position].same_window_ticks[window] for position in test]
            )
            drift = float(raw_train.mean())
            alpha = 0.0 if model not in {"M4", "M5", "M6"} else 1.0
            fit = fit_ridge(design_train, raw_train - drift, feature_names=names, penalty=alpha)
            prediction = fit.predict(design_test)
            rows.append(
                {
                    "h1_seconds": window,
                    "model": model,
                    "descriptive_construction_diagnostic_only": True,
                    "oos_r2": _r_squared(
                        raw_test - drift, prediction, np.zeros(raw_test.shape, dtype=np.float64)
                    ),
                }
            )
    return rows


def evaluate_normalised_subarms(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    source: Literal["future", "past"],
    trade_identified: bool,
    replicates: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Evaluate the two frozen normalised robustness sub-arms outside the primary ranking."""

    rows: list[dict[str, Any]] = []
    baseline_names = ("log1p_l1_depth", "spread_ticks")
    for horizon in RETURN_HORIZONS_SECONDS:
        for window in OFI_WINDOWS_SECONDS:
            subarms = (
                ("M2b_normalised_trade", normalised_trade_feature(window), trade_identified),
                ("M3b_depth_normalised_cks", cks_pressure_feature(window), True),
            )
            for label, feature, available in subarms:
                if not available:
                    rows.append(
                        {
                            "source": source,
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "subarm": label,
                            "status": "blocked_unidentified_signed_trades",
                        }
                    )
                    continue
                names = (*baseline_names, feature)
                train = _positions(observations, split.train, horizon, source, names=names)
                test = _positions(observations, split.test, horizon, source, names=names)
                embargoed = _positions(observations, split.embargoed, horizon, source, names=names)
                total = _positions(
                    observations,
                    tuple(range(len(observations))),
                    horizon,
                    source,
                    names=names,
                )
                support_by_tape = _support_by_tape(
                    observations, split, horizon=horizon, source=source, names=names
                )
                if min(len(train), len(test)) < MINIMUM_FIT_OBSERVATIONS:
                    rows.append(
                        {
                            "source": source,
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "subarm": label,
                            "status": "data_insufficient_feature_support",
                            "total_n": len(total),
                            "train_n": len(train),
                            "embargoed_n": len(embargoed),
                            "test_n": len(test),
                            "support_by_tape": support_by_tape,
                        }
                    )
                    continue
                baseline = _fit_score(
                    observations,
                    train,
                    test,
                    model="M0",
                    names=baseline_names,
                    horizon=horizon,
                    source=source,
                )
                score = _fit_score(
                    observations,
                    train,
                    test,
                    model="M3",
                    names=names,
                    horizon=horizon,
                    source=source,
                )
                rows.append(
                    {
                        "source": source,
                        "h1_seconds": window,
                        "h2_seconds": horizon,
                        "subarm": label,
                        "status": "estimated",
                        "total_n": len(total),
                        "train_n": len(train),
                        "embargoed_n": len(embargoed),
                        "test_n": len(test),
                        "support_by_tape": support_by_tape,
                        "in_sample_r2": score.payload["in_sample_r2"],
                        "in_sample_adjusted_r2": score.payload["in_sample_adjusted_r2"],
                        "oos_r2_training_mean": score.payload["oos_r2_training_mean"],
                        "incremental_oos_r2_over_m0": _difference(
                            score.payload["oos_r2_training_mean"],
                            baseline.payload["oos_r2_training_mean"],
                        ),
                        "coefficient_ticks_per_training_sd": score.payload[
                            "coefficients_ticks_per_training_sd"
                        ][feature],
                        "raw_coefficient_ticks_per_unit": score.payload[
                            "raw_coefficients_ticks_per_unit"
                        ][feature],
                        "rmse_ticks": score.payload["rmse_ticks"],
                        "mae_ticks": score.payload["mae_ticks"],
                        "selected_alpha": score.payload["selected_alpha"],
                        "training_standardisation": score.payload["training_standardisation"],
                        "per_tape": _per_tape_scores(
                            observations,
                            test,
                            horizon=horizon,
                            source=source,
                            score=score,
                            baseline=baseline,
                        ),
                        "direction_by_tape": _direction_by_tape(
                            observations,
                            train,
                            names=names,
                            model=label,
                            horizon=horizon,
                            source=source,
                            alpha=0.0,
                        ),
                        "error_improvement_inference_over_m0": _inference(
                            baseline,
                            score,
                            observations,
                            test,
                            horizon=horizon,
                            seed=(
                                seed
                                + int(horizon * 1000)
                                + int(window * 100)
                                + (20_000 if label.startswith("M2b") else 30_000)
                                + (0 if source == "future" else 1_000_000)
                            ),
                            replicates=replicates,
                        ),
                    }
                )
    return rows


def evaluate_combined_ablations(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    trade_identified: bool,
) -> list[dict[str, Any]]:
    """Leave each predictor family out of M6 and score the held-out loss of fit."""

    rows: list[dict[str, Any]] = []
    for horizon in RETURN_HORIZONS_SECONDS:
        for window in OFI_WINDOWS_SECONDS:
            full_names = model_features("M6", window, trade_identified=trade_identified)
            train = _positions(observations, split.train, horizon, "future", names=full_names)
            test = _positions(observations, split.test, horizon, "future", names=full_names)
            full = _fit_score(
                observations,
                train,
                test,
                model="M6",
                names=full_names,
                horizon=horizon,
                source="future",
            )
            families: dict[str, set[str]] = {
                "M1_static_queue": {"l1_queue_imbalance"},
                "M2_signed_trades": {trade_feature(window)} if trade_identified else set(),
                "M3_cks_l1": {cks_feature(window)},
                "M4_multilevel_ofi": {pk_band_feature(window, *band) for band in BANDS},
                "M5_depth_adjusted_multilevel": {
                    adjusted_band_feature(window, *band) for band in BANDS
                },
            }
            for family, excluded in families.items():
                if not excluded:
                    rows.append(
                        {
                            "h1_seconds": window,
                            "h2_seconds": horizon,
                            "excluded_family": family,
                            "status": "blocked_unidentified_signed_trades",
                        }
                    )
                    continue
                reduced_names = tuple(name for name in full_names if name not in excluded)
                reduced = _fit_score(
                    observations,
                    train,
                    test,
                    model="M6",
                    names=reduced_names,
                    horizon=horizon,
                    source="future",
                )
                rows.append(
                    {
                        "h1_seconds": window,
                        "h2_seconds": horizon,
                        "excluded_family": family,
                        "status": "estimated",
                        "full_m6_oos_r2": full.payload["oos_r2_training_mean"],
                        "without_family_oos_r2": reduced.payload["oos_r2_training_mean"],
                        "family_incremental_oos_r2": _difference(
                            full.payload["oos_r2_training_mean"],
                            reduced.payload["oos_r2_training_mean"],
                        ),
                        "full_alpha": full.payload["selected_alpha"],
                        "reduced_alpha": reduced.payload["selected_alpha"],
                    }
                )
    return rows


def feature_intensity_table(
    observations: Sequence[HorseRaceObservation], *, trade_identified: bool
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in OFI_WINDOWS_SECONDS:
        names = [
            "l1_queue_imbalance",
            cks_feature(window),
            cks_pressure_feature(window),
        ]
        if trade_identified:
            names.extend((trade_feature(window), normalised_trade_feature(window)))
        names.extend(pk_band_feature(window, *band) for band in BANDS)
        names.extend(adjusted_band_feature(window, *band) for band in BANDS)
        for name in names:
            values = np.asarray(
                [
                    observation.features[name]
                    for observation in observations
                    if name in observation.features
                ]
            )
            rows.append(
                {
                    "h1_seconds": window,
                    "feature": name,
                    "n": len(values),
                    "missing_n": len(observations) - len(values),
                    "mean": float(values.mean()) if len(values) else None,
                    "standard_deviation": float(values.std()) if len(values) else None,
                    "mean_absolute": float(np.mean(np.abs(values))) if len(values) else None,
                    "zero_share": float(np.mean(values == 0.0)) if len(values) else None,
                }
            )
    return rows


def compact_support_table(
    primary_rows: Sequence[Mapping[str, Any]],
    normalised_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten common and model-specific support for compact artifact export."""

    result: list[dict[str, Any]] = []
    for category, rows, label_key in (
        ("primary", primary_rows, "model"),
        ("normalised_subarm", normalised_rows, "subarm"),
    ):
        for row in rows:
            support_by_tape = row.get("support_by_tape", {})
            model_support = row.get("model_specific_support_before_common_intersection", {})
            support_loss = row.get("support_loss_to_common_sample", {})
            result.append(
                {
                    "source": row.get("source"),
                    "category": category,
                    "label": row.get(label_key),
                    "h1_seconds": row.get("h1_seconds"),
                    "h2_seconds": row.get("h2_seconds"),
                    "status": row.get("status"),
                    "common_total_n": row.get("total_n"),
                    "common_train_n": row.get("train_n"),
                    "common_embargoed_n": row.get("embargoed_n"),
                    "common_test_n": row.get("test_n"),
                    "tape_0_test_n": support_by_tape.get("0", {}).get("test_n"),
                    "tape_1_test_n": support_by_tape.get("1", {}).get("test_n"),
                    "model_specific_total_n": model_support.get("total_n"),
                    "model_specific_train_n": model_support.get("train_n"),
                    "model_specific_embargoed_n": model_support.get("embargoed_n"),
                    "model_specific_test_n": model_support.get("test_n"),
                    "loss_to_common_total_n": support_loss.get("total_n"),
                    "loss_to_common_train_n": support_loss.get("train_n"),
                    "loss_to_common_embargoed_n": support_loss.get("embargoed_n"),
                    "loss_to_common_test_n": support_loss.get("test_n"),
                }
            )
    return result


def resolve_30_second_gate(
    future: Sequence[Mapping[str, Any]], past: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply the frozen four-condition gate mechanically to h2=10 non-combined models."""

    past_index = {
        (row.get("h1_seconds"), row.get("h2_seconds"), row.get("model")): row for row in past
    }
    candidates: list[dict[str, Any]] = []
    for model in ("M1", "M2", "M3", "M4", "M5"):
        model_rows = [
            row
            for row in future
            if row.get("model") == model
            and row.get("h2_seconds") == 10.0
            and row.get("status") == "estimated"
        ]
        if not model_rows:
            candidates.append({"model": model, "status": "unavailable", "all_conditions": False})
            continue
        row = max(
            model_rows,
            key=lambda item: (
                float(item.get("incremental_oos_r2_over_m0") or -float("inf")),
                -float(item["h1_seconds"]),
            ),
        )
        past_row = past_index[(row["h1_seconds"], row["h2_seconds"], model)]
        per_tape = row["per_tape"]
        directions = [value for value in row["direction_by_tape"].values() if value is not None]
        conditions = {
            "pooled_increment_strictly_positive": float(row["incremental_oos_r2_over_m0"]) > 0,
            "per_tape_increment_non_negative": all(
                value["incremental_oos_r2_over_m0"] is not None
                and value["incremental_oos_r2_over_m0"] >= 0
                for value in per_tape.values()
            ),
            "direction_stable_across_tapes": len(directions) == len(per_tape)
            and len(directions) >= 2
            and all(value > 0 for value in directions)
            or len(directions) >= 2
            and all(value < 0 for value in directions),
            "future_increment_stronger_than_past_mirror": (
                float(row["incremental_oos_r2_over_m0"])
                > float(past_row["incremental_oos_r2_over_m0"])
            ),
        }
        candidates.append(
            {
                "model": model,
                "h1_seconds": row["h1_seconds"],
                "future_incremental_oos_r2_over_m0": row["incremental_oos_r2_over_m0"],
                "past_incremental_oos_r2_over_m0": past_row["incremental_oos_r2_over_m0"],
                "conditions": conditions,
                "all_conditions": all(conditions.values()),
            }
        )
    passing = [candidate for candidate in candidates if candidate.get("all_conditions")]
    return {
        "gate_passed": bool(passing),
        "passing_candidates": passing,
        "evaluated_candidates": candidates,
        "same_window_cannot_open_gate": True,
        "combined_model_cannot_open_gate": True,
    }


def compact_rankings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for horizon in RETURN_HORIZONS_SECONDS:
        eligible = [
            row
            for row in rows
            if row.get("h2_seconds") == horizon
            and row.get("status") == "estimated"
            and row.get("model") != "M0"
        ]
        ordered = sorted(
            eligible,
            key=lambda row: (
                -(float(row.get("incremental_oos_r2_over_m0") or -float("inf"))),
                MODEL_ORDER.index(str(row["model"])),
                float(row["h1_seconds"]),
            ),
        )
        for rank, row in enumerate(ordered, start=1):
            result.append(
                {
                    "h2_seconds": horizon,
                    "rank": rank,
                    "model": row["model"],
                    "h1_seconds": row["h1_seconds"],
                    "oos_r2": row["oos_r2_training_mean"],
                    "incremental_oos_r2_over_m0": row["incremental_oos_r2_over_m0"],
                    "per_tape_increment": {
                        tape: payload["incremental_oos_r2_over_m0"]
                        for tape, payload in row["per_tape"].items()
                    },
                }
            )
    return result


@dataclass(frozen=True, slots=True)
class HorseRaceTapeInput:
    tape_index: int
    run_id: str
    instrument_id: str
    tape_sha256: str
    observations: tuple[HorseRaceObservation, ...]
    depth200_publications: int
    depth20_publications: int
    observed_seconds: float
    failures: Mapping[str, Any]


def build_horserace_artifact(
    tapes: Sequence[HorseRaceTapeInput],
    *,
    code_commit: str | None,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    observations = [observation for tape in tapes for observation in tape.observations]
    if not observations:
        raise ValueError("at least one horse-race observation is required")
    assert_no_lookahead(observations)
    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations],
        embargo_seconds=EMBARGO_SECONDS,
    )
    trade_identified = all(
        bool(
            tape.failures.get("trade_support", {}).get("qualified_packets", 0)
            >= MINIMUM_TRADE_PACKETS
        )
        for tape in tapes
    )
    future = evaluate_cells(
        observations,
        split,
        horizons=RETURN_HORIZONS_SECONDS,
        source="future",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed,
    )
    past = evaluate_cells(
        observations,
        split,
        horizons=RETURN_HORIZONS_SECONDS,
        source="past",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed + 10_000_000,
    )
    normalised_future = evaluate_normalised_subarms(
        observations,
        split,
        source="future",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed + 30_000_000,
    )
    normalised_past = evaluate_normalised_subarms(
        observations,
        split,
        source="past",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed + 40_000_000,
    )
    ablations = evaluate_combined_ablations(observations, split, trade_identified=trade_identified)
    gate = resolve_30_second_gate(future, past)
    conditional: list[dict[str, Any]] = []
    if gate["gate_passed"]:
        conditional = evaluate_cells(
            observations,
            split,
            horizons=(CONDITIONAL_HORIZON_SECONDS,),
            source="future",
            trade_identified=trade_identified,
            replicates=replicates,
            seed=seed + 20_000_000,
        )
    intensity = feature_intensity_table(observations, trade_identified=trade_identified)
    support = compact_support_table([*future, *past], [*normalised_future, *normalised_past])
    return {
        "schema_version": 2,
        "scan_id": EXPLORATORY_SCAN_ID,
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "design_document": DESIGN_DOCUMENT,
        "code_commit": code_commit,
        "tapes": [
            {
                "tape_index": tape.tape_index,
                "run_id": tape.run_id,
                "instrument_id": tape.instrument_id,
                "tape_sha256": tape.tape_sha256,
                "observations": len(tape.observations),
                "depth200_publications": tape.depth200_publications,
                "depth20_publications": tape.depth20_publications,
                "observed_seconds": tape.observed_seconds,
                "failures": tape.failures,
            }
            for tape in tapes
        ],
        "sample": {
            "observations": len(observations),
            "train_n": len(split.train),
            "embargoed_n": len(split.embargoed),
            "test_n": len(split.test),
            "split_boundaries": split.boundaries,
            "trade_model_identified": trade_identified,
            "common_sample_models": list(MODEL_ORDER),
        },
        "axes": {
            "h1_seconds": OFI_WINDOWS_SECONDS,
            "h2_seconds": RETURN_HORIZONS_SECONDS,
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "models": MODEL_ORDER,
            "bands": BANDS,
            "ridge_alphas": RIDGE_ALPHAS,
        },
        "future_cells": future,
        "past_mirror_cells": past,
        "same_window_diagnostic": evaluate_same_window(
            observations, split, trade_identified=trade_identified
        ),
        "rankings": compact_rankings(future),
        "normalised_subarms_future": normalised_future,
        "normalised_subarms_past": normalised_past,
        "combined_ablations": ablations,
        "feature_intensity": intensity,
        "support_table": support,
        "gate_30_seconds": gate,
        "conditional_30_second_cells": conditional,
        "multiplicity": {
            "future_ranked_cells": len(future),
            "past_mirror_cells": len(past),
            "same_window_diagnostic_cells": 5 * len(MODEL_ORDER),
            "normalised_subarm_cells_per_direction": len(normalised_future),
            "combined_ablation_cells": len(ablations),
            "naive_iid_inference_valid": False,
        },
        "evidence_level": "Level 3 machinery; exploratory empirical content only",
    }
