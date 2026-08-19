"""Cont-Kukanov-Stoikov level-one order-flow imbalance for `X-CKS-L1-OFI-DAT20-04`.

The object here is deliberately narrow: the *best quote only*.  ``deep_book_ofi`` builds a
price-keyed innovation across the whole 200-level ladder; this module builds the canonical CKS
level-one event increment, decomposes it into auditable transition components, scales it by
causally measured depth, and asks how much of the following futures mid change it explains.

Dhan publishes snapshots rather than order-by-order messages, so gross limit arrivals and gross
cancellations are **not identified**.  Same-price increases are therefore called displayed
additions and same-price decreases displayed removals throughout, never arrival or cancellation
intensities.  See ``docs/CKS-L1-OFI-SPEC-2026-08-19.md`` for the frozen design.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import log1p
from typing import Any, Literal

import numpy as np

from shaurya.data.depth_thinning_analysis import BookState
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EMBARGO_SECONDS,
    MINIMUM_FIT_OBSERVATIONS,
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
    RETURN_HORIZONS_SECONDS,
    _controls,
    _invalid_transition,
    _label,
    _mid_return,
    price_keyed_ofi_transition,
)
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND

EXPLORATORY_SCAN_ID = "X-CKS-L1-OFI-DAT20-04"
CONFIRMATORY_ELIGIBLE = False
DESIGN_DOCUMENT = "docs/CKS-L1-OFI-SPEC-2026-08-19.md"

#: Floor on the average-depth denominator, in contracts, so scaling cannot divide by ~zero.
MINIMUM_MEAN_DEPTH_CONTRACTS = 1.0

DEPTH_BASELINE_FEATURE = "log1p_l1_depth_end"
STATE_ROBUSTNESS_FEATURES = ("spread_ticks", "microprice_tilt_ticks")

#: The eight mutually exclusive, jointly exhaustive level-one transition components.
L1_COMPONENTS = (
    "bid_price_improvement",
    "bid_same_price_addition",
    "bid_same_price_removal",
    "bid_price_worsening",
    "ask_price_improvement",
    "ask_same_price_addition",
    "ask_same_price_removal",
    "ask_price_worsening",
)


def ofi_feature(window_seconds: float) -> str:
    return f"cks_ofi_w{_label(window_seconds)}"


def pressure_feature(window_seconds: float) -> str:
    return f"cks_pressure_w{_label(window_seconds)}"


#: Depth cutoff of the `X-OFI-DAT20-03` construction carried alongside purely for comparison.
COMPARISON_DEPTH_LEVELS = 10


def comparison_feature(window_seconds: float) -> str:
    """The `X-OFI-DAT20-03` price-keyed top-10 OFI, carried only to compare the two objects."""

    return f"pk_ofi_w{_label(window_seconds)}__depth_{COMPARISON_DEPTH_LEVELS}"


@dataclass(frozen=True, slots=True)
class CksL1Transition:
    """One best-quote-to-best-quote CKS increment with its component decomposition."""

    receive_ts_ns: int
    event: float
    components: Mapping[str, float]
    absolute_contribution: float
    half_total_depth: float
    total_depth: float
    bid_event_kind: str | None
    ask_event_kind: str | None
    invalid_reason: str | None = None


def _empty_components() -> dict[str, float]:
    return dict.fromkeys(L1_COMPONENTS, 0.0)


def cks_l1_transition(previous: BookState, current: BookState) -> CksL1Transition:
    """Compute the level-one CKS event increment between two consecutive book snapshots.

    ``e_n = 1{P^B_n >= P^B_{n-1}} q^B_n - 1{P^B_n <= P^B_{n-1}} q^B_{n-1}
            - 1{P^A_n <= P^A_{n-1}} q^A_n + 1{P^A_n >= P^A_{n-1}} q^A_{n-1}``

    Bid strengthening and ask depletion are positive; ask strengthening and bid depletion are
    negative.  The eight components returned sum exactly to ``event``.
    """

    invalid = _invalid_transition(previous, current)
    if invalid is not None:
        return CksL1Transition(
            current.receive_ts_ns, 0.0, _empty_components(), 0.0, 0.0, 0.0, None, None, invalid
        )
    old_bid_price, old_bid_quantity, _ = previous.bids[0]
    new_bid_price, new_bid_quantity, _ = current.bids[0]
    old_ask_price, old_ask_quantity, _ = previous.asks[0]
    new_ask_price, new_ask_quantity, _ = current.asks[0]
    components = _empty_components()
    bid_kind: str | None
    ask_kind: str | None
    if new_bid_price > old_bid_price:
        components["bid_price_improvement"] = float(new_bid_quantity)
        bid_kind = "bid_price_improvement"
    elif new_bid_price < old_bid_price:
        components["bid_price_worsening"] = -float(old_bid_quantity)
        bid_kind = "bid_price_worsening"
    else:
        delta = float(new_bid_quantity - old_bid_quantity)
        if delta > 0:
            components["bid_same_price_addition"] = delta
            bid_kind = "bid_same_price_addition"
        elif delta < 0:
            components["bid_same_price_removal"] = delta
            bid_kind = "bid_same_price_removal"
        else:
            bid_kind = None
    if new_ask_price < old_ask_price:
        components["ask_price_improvement"] = -float(new_ask_quantity)
        ask_kind = "ask_price_improvement"
    elif new_ask_price > old_ask_price:
        components["ask_price_worsening"] = float(old_ask_quantity)
        ask_kind = "ask_price_worsening"
    else:
        delta = float(new_ask_quantity - old_ask_quantity)
        if delta > 0:
            components["ask_same_price_addition"] = -delta
            ask_kind = "ask_same_price_addition"
        elif delta < 0:
            components["ask_same_price_removal"] = -delta
            ask_kind = "ask_same_price_removal"
        else:
            ask_kind = None
    event = sum(components.values())
    # The closed-form definition and the decomposition must agree exactly, always.
    closed_form = (
        (float(new_bid_quantity) if new_bid_price >= old_bid_price else 0.0)
        - (float(old_bid_quantity) if new_bid_price <= old_bid_price else 0.0)
        - (float(new_ask_quantity) if new_ask_price <= old_ask_price else 0.0)
        + (float(old_ask_quantity) if new_ask_price >= old_ask_price else 0.0)
    )
    if event != closed_form:
        raise RuntimeError(
            f"component decomposition {event} disagrees with CKS closed form {closed_form}"
        )
    total_depth = float(new_bid_quantity + new_ask_quantity)
    return CksL1Transition(
        receive_ts_ns=current.receive_ts_ns,
        event=event,
        components=components,
        absolute_contribution=sum(abs(value) for value in components.values()),
        half_total_depth=total_depth / 2.0,
        total_depth=total_depth,
        bid_event_kind=bid_kind,
        ask_event_kind=ask_kind,
        invalid_reason=None,
    )


@dataclass(frozen=True, slots=True)
class CksL1Observation:
    tape_index: int
    run_id: str
    receive_ts_ns: int
    time_bucket: str
    features: Mapping[str, float]
    future_ticks: Mapping[int, float]
    past_ticks: Mapping[int, float]
    contemporaneous_ticks: Mapping[int, float]
    same_window_ticks: Mapping[float, float]
    l1_depth_end: float
    mean_depth_by_window: Mapping[float, float]
    depth_floor_hits: tuple[float, ...]
    window_start_ts_ns: Mapping[float, int]


def build_cks_l1_observations(
    *,
    depth200_states: Sequence[BookState],
    depth20_states: Sequence[BookState],
    tape_index: int,
    run_id: str,
) -> tuple[list[CksL1Observation], dict[str, int], dict[str, Any]]:
    """Build one aligned observation after every complete longest-window CKS history."""

    failures = {
        "invalid_transition": 0,
        "incomplete_ofi_history": 0,
        "unusable_controls": 0,
        "no_depth20_anchor": 0,
        "no_future_horizon_covered": 0,
    }
    intensities: dict[str, Any] = {
        "valid_transitions": 0,
        "component_events": dict.fromkeys(L1_COMPONENTS, 0),
        "component_signed_contracts": dict.fromkeys(L1_COMPONENTS, 0.0),
        "component_absolute_contracts": dict.fromkeys(L1_COMPONENTS, 0.0),
        "bid_no_change_events": 0,
        "ask_no_change_events": 0,
        "valid_span_seconds": 0.0,
    }
    if len(depth200_states) < 2:
        return [], failures, intensities
    transitions = [
        cks_l1_transition(previous, current)
        for previous, current in zip(depth200_states[:-1], depth200_states[1:], strict=True)
    ]
    comparison = [
        price_keyed_ofi_transition(previous, current)
        for previous, current in zip(depth200_states[:-1], depth200_states[1:], strict=True)
    ]
    stamps = [transition.receive_ts_ns for transition in transitions]
    invalid_prefix = [0]
    event_prefix = [0.0]
    depth_prefix = [0.0]
    count_prefix = [0]
    comparison_prefix = [0.0]
    for transition, pk in zip(transitions, comparison, strict=True):
        invalid_prefix.append(invalid_prefix[-1] + int(transition.invalid_reason is not None))
        valid = transition.invalid_reason is None
        if not valid:
            failures["invalid_transition"] += 1
        else:
            intensities["valid_transitions"] += 1
            for name, value in transition.components.items():
                if value != 0.0:
                    intensities["component_events"][name] += 1
                intensities["component_signed_contracts"][name] += value
                intensities["component_absolute_contracts"][name] += abs(value)
            if transition.bid_event_kind is None:
                intensities["bid_no_change_events"] += 1
            if transition.ask_event_kind is None:
                intensities["ask_no_change_events"] += 1
        event_prefix.append(event_prefix[-1] + (transition.event if valid else 0.0))
        depth_prefix.append(depth_prefix[-1] + (transition.half_total_depth if valid else 0.0))
        count_prefix.append(count_prefix[-1] + int(valid))
        comparison_prefix.append(
            comparison_prefix[-1]
            + (pk.cumulative_by_depth[COMPARISON_DEPTH_LEVELS] if valid else 0.0)
        )
    intensities["valid_span_seconds"] = (
        depth200_states[-1].receive_ts_ns - depth200_states[0].receive_ts_ns
    ) / NANOSECONDS_PER_SECOND
    series = build_depth20_mid_series(depth20_states)
    observations: list[CksL1Observation] = []
    max_window_ns = int(max(OFI_WINDOWS_SECONDS) * NANOSECONDS_PER_SECOND)
    gap_ns = int(CAUSAL_GAP_SECONDS * NANOSECONDS_PER_SECOND)
    for position, (state, transition) in enumerate(
        zip(depth200_states[1:], transitions, strict=True)
    ):
        if transition.invalid_reason is not None:
            continue
        if state.receive_ts_ns - depth200_states[0].receive_ts_ns < max_window_ns:
            failures["incomplete_ofi_history"] += 1
            continue
        controls = _controls(state)
        if controls is None:
            failures["unusable_controls"] += 1
            continue
        features = dict(controls)
        features[DEPTH_BASELINE_FEATURE] = log1p(transition.total_depth)
        mean_depth_by_window: dict[float, float] = {}
        window_start: dict[float, int] = {}
        floor_hits: list[float] = []
        complete = True
        for window in OFI_WINDOWS_SECONDS:
            start = state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND)
            left = bisect_right(stamps, start)
            right = position + 1
            if left >= right or invalid_prefix[right] - invalid_prefix[left] != 0:
                complete = False
                break
            value = event_prefix[right] - event_prefix[left]
            covered = count_prefix[right] - count_prefix[left]
            mean_depth = (depth_prefix[right] - depth_prefix[left]) / covered
            denominator = max(mean_depth, MINIMUM_MEAN_DEPTH_CONTRACTS)
            if mean_depth < MINIMUM_MEAN_DEPTH_CONTRACTS:
                floor_hits.append(window)
            features[ofi_feature(window)] = value
            features[pressure_feature(window)] = value / denominator
            features[comparison_feature(window)] = (
                comparison_prefix[right] - comparison_prefix[left]
            )
            mean_depth_by_window[window] = mean_depth
            window_start[window] = stamps[left]
        if not complete:
            failures["incomplete_ofi_history"] += 1
            continue
        response_anchor = state.receive_ts_ns + gap_ns
        if series.as_of(response_anchor) is None:
            failures["no_depth20_anchor"] += 1
            continue
        future: dict[int, float] = {}
        past: dict[int, float] = {}
        for horizon in RETURN_HORIZONS_SECONDS:
            horizon_ns = horizon * NANOSECONDS_PER_SECOND
            response_value = _mid_return(series, response_anchor, response_anchor + horizon_ns)
            if response_value is not None:
                future[horizon] = response_value
            mirror = _mid_return(series, state.receive_ts_ns - horizon_ns, state.receive_ts_ns)
            if mirror is not None:
                past[horizon] = mirror
        if not future:
            failures["no_future_horizon_covered"] += 1
            continue
        same_window: dict[float, float] = {}
        for window in OFI_WINDOWS_SECONDS:
            same_value = _mid_return(
                series,
                state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND),
                state.receive_ts_ns,
            )
            if same_value is not None:
                same_window[window] = same_value
        observations.append(
            CksL1Observation(
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=state.receive_ts_ns,
                time_bucket="mid_afternoon",
                features=features,
                future_ticks=future,
                past_ticks=past,
                contemporaneous_ticks={},
                same_window_ticks=same_window,
                l1_depth_end=transition.total_depth,
                mean_depth_by_window=mean_depth_by_window,
                depth_floor_hits=tuple(floor_hits),
                window_start_ts_ns=window_start,
            )
        )
    return observations, failures, intensities


def as_normal_observation(observation: CksL1Observation) -> Observation:
    """Compatibility helper so the shared chronological split tooling can be reused unchanged."""

    return Observation(
        tape_index=observation.tape_index,
        run_id=observation.run_id,
        receive_ts_ns=observation.receive_ts_ns,
        time_bucket=observation.time_bucket,
        features=observation.features,
        future_ticks=observation.future_ticks,
        past_ticks=observation.past_ticks,
        contemporaneous_ticks=observation.contemporaneous_ticks,
    )


def assert_no_lookahead(observations: Sequence[CksL1Observation]) -> None:
    """Every right-hand-side quantity must be dated at or before its own observation stamp."""

    for observation in observations:
        for window, start in observation.window_start_ts_ns.items():
            if start > observation.receive_ts_ns:
                raise ValueError(f"window {window}s starts after its own observation")
            if observation.receive_ts_ns - start > int(window * NANOSECONDS_PER_SECOND):
                raise ValueError(f"window {window}s reaches further back than its own length")


def _positions(
    observations: Sequence[CksL1Observation],
    candidates: Sequence[int],
    horizon: int,
    source: Literal["future", "past"],
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
    )


def _target(
    observations: Sequence[CksL1Observation],
    positions: Sequence[int],
    horizon: int,
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
    observations: Sequence[CksL1Observation],
    positions: Sequence[int],
    names: Sequence[str],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [[observations[position].features[name] for name in names] for position in positions],
        dtype=np.float64,
    ).reshape(len(positions), len(names))


@dataclass(frozen=True, slots=True)
class ModelResult:
    """One fitted model on one cell, scored in and out of sample."""

    name: str
    features: tuple[str, ...]
    train_n: int
    test_n: int
    in_sample_r2: float | None
    in_sample_adjusted_r2: float | None
    oos_r2_training_mean: float | None
    errors: tuple[float, ...]
    coefficient_ticks_per_training_sd: Mapping[str, float]
    ofi_coefficient_ticks_per_100_contracts: float | None
    pressure_coefficient_ticks_per_unit: float | None


def _evaluate_model(
    observations: Sequence[CksL1Observation],
    train_positions: Sequence[int],
    test_positions: Sequence[int],
    *,
    name: str,
    names: Sequence[str],
    horizon: int,
    source: Literal["future", "past"],
    ofi_name: str | None,
    pressure_name: str | None,
) -> ModelResult:
    raw_train = _target(observations, train_positions, horizon, source)
    raw_test = _target(observations, test_positions, horizon, source)
    drift = float(raw_train.mean())
    train_target = raw_train - drift
    test_target = raw_test - drift
    train_design = _design(observations, train_positions, names)
    test_design = _design(observations, test_positions, names)
    fit = fit_ridge(train_design, train_target, feature_names=names, penalty=0.0)
    fitted_train = fit.predict(train_design)
    predicted = fit.predict(test_design)
    zero_train = np.zeros(train_target.shape, dtype=np.float64)
    in_sample = _r_squared(train_target, fitted_train, zero_train)
    degrees = len(train_positions) - len(names) - 1
    adjusted = (
        None
        if in_sample is None or degrees <= 0
        else 1.0 - (1.0 - in_sample) * (len(train_positions) - 1) / degrees
    )
    coefficients = {
        feature: float(fit.coefficients[index]) for index, feature in enumerate(names)
    }
    per_100: float | None = None
    if ofi_name is not None and ofi_name in coefficients:
        index = tuple(names).index(ofi_name)
        per_100 = float(fit.coefficients[index] / fit.scale[index] * 100.0)
    per_unit: float | None = None
    if pressure_name is not None and pressure_name in coefficients:
        index = tuple(names).index(pressure_name)
        per_unit = float(fit.coefficients[index] / fit.scale[index])
    return ModelResult(
        name=name,
        features=tuple(names),
        train_n=len(train_positions),
        test_n=len(test_positions),
        in_sample_r2=in_sample,
        in_sample_adjusted_r2=adjusted,
        oos_r2_training_mean=_r_squared(
            test_target, predicted, np.zeros(test_target.shape, dtype=np.float64)
        ),
        errors=tuple(float(value) for value in (test_target - predicted) ** 2),
        coefficient_ticks_per_training_sd=coefficients,
        ofi_coefficient_ticks_per_100_contracts=per_100,
        pressure_coefficient_ticks_per_unit=per_unit,
    )


def _model_payload(result: ModelResult) -> dict[str, Any]:
    payload = asdict(result)
    payload.pop("errors")
    return payload


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _inference_payload(
    baseline_errors: Sequence[float],
    candidate_errors: Sequence[float],
    observations: Sequence[CksL1Observation],
    test_positions: Sequence[int],
    *,
    horizon: int,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    """Paired squared-error improvement of the candidate over the baseline, assessed three ways."""

    differential = [
        baseline - candidate
        for baseline, candidate in zip(baseline_errors, candidate_errors, strict=True)
    ]
    estimate = estimate_mean(
        differential,
        [observations[position].receive_ts_ns for position in test_positions],
        [observations[position].tape_index for position in test_positions],
        overlap_seconds=float(horizon) + CAUSAL_GAP_SECONDS,
        replicates=replicates,
        seed=seed,
    )
    statistics = (
        estimate.newey_west_t,
        estimate.block_bootstrap_t,
        estimate.non_overlapping_t,
    )
    return {
        **asdict(estimate),
        "distinguishable_positive_improvement": all(
            value is not None and value > 1.96 for value in statistics
        ),
        "naive_inference_valid": False,
    }


CELL_MODELS = ("M1", "M2", "M3", "M4", "M4b", "R1", "C1")


def _cell_model_specification(
    window: float,
) -> dict[str, tuple[tuple[str, ...], str | None, str | None]]:
    ofi = ofi_feature(window)
    pressure = pressure_feature(window)
    comparison = comparison_feature(window)
    return {
        "M1": ((ofi,), ofi, None),
        "M2": ((DEPTH_BASELINE_FEATURE,), None, None),
        "M3": ((DEPTH_BASELINE_FEATURE, ofi), ofi, None),
        "M4": ((pressure,), None, pressure),
        "M4b": ((DEPTH_BASELINE_FEATURE, pressure), None, pressure),
        "R1": ((*STATE_ROBUSTNESS_FEATURES, DEPTH_BASELINE_FEATURE, ofi), ofi, None),
        "C1": ((DEPTH_BASELINE_FEATURE, comparison), comparison, None),
    }


def evaluate_grid(
    observations: Sequence[CksL1Observation],
    split: SplitIndex,
    *,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """Evaluate all 25 window x horizon cells, six models each, without any filtering."""

    rows: list[dict[str, Any]] = []
    for horizon in RETURN_HORIZONS_SECONDS:
        future_train = _positions(observations, split.train, horizon, "future")
        future_test = _positions(observations, split.test, horizon, "future")
        past_train = _positions(observations, split.train, horizon, "past")
        past_test = _positions(observations, split.test, horizon, "past")
        smallest = min(len(future_train), len(future_test), len(past_train), len(past_test))
        if smallest < MINIMUM_FIT_OBSERVATIONS:
            raise ValueError(f"insufficient observations at {horizon}s")
        for window in OFI_WINDOWS_SECONDS:
            specification = _cell_model_specification(window)
            future_models: dict[str, ModelResult] = {}
            past_models: dict[str, ModelResult] = {}
            for name, (names, ofi_name, pressure_name) in specification.items():
                future_models[name] = _evaluate_model(
                    observations,
                    future_train,
                    future_test,
                    name=name,
                    names=names,
                    horizon=horizon,
                    source="future",
                    ofi_name=ofi_name,
                    pressure_name=pressure_name,
                )
                past_models[name] = _evaluate_model(
                    observations,
                    past_train,
                    past_test,
                    name=name,
                    names=names,
                    horizon=horizon,
                    source="past",
                    ofi_name=ofi_name,
                    pressure_name=pressure_name,
                )
            base = seed + horizon * 10_000 + int(window * 100)
            rows.append(
                {
                    "ofi_window_seconds": window,
                    "return_horizon_seconds": horizon,
                    "causal_gap_seconds": CAUSAL_GAP_SECONDS,
                    "train_n": len(future_train),
                    "test_n": len(future_test),
                    "models": {
                        name: _model_payload(result) for name, result in future_models.items()
                    },
                    "past_mirror_models": {
                        name: _model_payload(result) for name, result in past_models.items()
                    },
                    "incremental_oos_r2_ofi_over_depth": _difference(
                        future_models["M3"].oos_r2_training_mean,
                        future_models["M2"].oos_r2_training_mean,
                    ),
                    "incremental_oos_r2_pressure_over_depth": _difference(
                        future_models["M4b"].oos_r2_training_mean,
                        future_models["M2"].oos_r2_training_mean,
                    ),
                    "incremental_oos_r2_price_keyed_top10_over_depth": _difference(
                        future_models["C1"].oos_r2_training_mean,
                        future_models["M2"].oos_r2_training_mean,
                    ),
                    "past_incremental_oos_r2_ofi_over_depth": _difference(
                        past_models["M3"].oos_r2_training_mean,
                        past_models["M2"].oos_r2_training_mean,
                    ),
                    "depth_scaling_helps_oos": (
                        None
                        if future_models["M4b"].oos_r2_training_mean is None
                        or future_models["M3"].oos_r2_training_mean is None
                        else future_models["M4b"].oos_r2_training_mean
                        > future_models["M3"].oos_r2_training_mean
                    ),
                    "ofi_over_depth_inference": _inference_payload(
                        future_models["M2"].errors,
                        future_models["M3"].errors,
                        observations,
                        future_test,
                        horizon=horizon,
                        replicates=replicates,
                        seed=base,
                    ),
                    "pressure_over_depth_inference": _inference_payload(
                        future_models["M2"].errors,
                        future_models["M4b"].errors,
                        observations,
                        future_test,
                        horizon=horizon,
                        replicates=replicates,
                        seed=base + 1,
                    ),
                }
            )
    expected = len(OFI_WINDOWS_SECONDS) * len(RETURN_HORIZONS_SECONDS)
    if len(rows) != expected:
        raise RuntimeError(f"complete grid required: expected {expected}, got {len(rows)}")
    return rows


def evaluate_same_window(
    observations: Sequence[CksL1Observation], split: SplitIndex
) -> list[dict[str, Any]]:
    """Construction diagnostic only: CKS OFI against the mid change over the same window."""

    rows: list[dict[str, Any]] = []
    for window in OFI_WINDOWS_SECONDS:
        train = tuple(
            position
            for position in split.train
            if window in observations[position].same_window_ticks
        )
        test = tuple(
            position
            for position in split.test
            if window in observations[position].same_window_ticks
        )
        if not train or not test:
            rows.append(
                {
                    "ofi_window_seconds": window,
                    "same_window_oos_r2_ofi": None,
                    "same_window_oos_r2_pressure": None,
                    "descriptive_only": True,
                }
            )
            continue
        train_target = np.asarray(
            [observations[position].same_window_ticks[window] for position in train],
            dtype=np.float64,
        )
        test_target = np.asarray(
            [observations[position].same_window_ticks[window] for position in test],
            dtype=np.float64,
        )
        drift = float(train_target.mean())
        train_target = train_target - drift
        test_target = test_target - drift
        scores: dict[str, float | None] = {}
        for key, name in (
            ("same_window_oos_r2_ofi", ofi_feature(window)),
            ("same_window_oos_r2_pressure", pressure_feature(window)),
        ):
            fit = fit_ridge(
                _design(observations, train, (name,)),
                train_target,
                feature_names=(name,),
                penalty=0.0,
            )
            predicted = fit.predict(_design(observations, test, (name,)))
            scores[key] = _r_squared(
                test_target, predicted, np.zeros(test_target.shape, dtype=np.float64)
            )
        rows.append({"ofi_window_seconds": window, **scores, "descriptive_only": True})
    return rows


@dataclass(frozen=True, slots=True)
class TradeTotals:
    """Vendor-reported executed volume inside the tape, used only as a conservative diagnostic.

    Dhan's trade fields arrive on coalesced ``full`` packets at a far slower cadence than the
    depth stream and carry no level attribution, so these totals can bound but never identify the
    execution share of an observed displayed removal.
    """

    packets: int
    classified_packets: int
    executed_contracts: float
    buy_contracts: float
    sell_contracts: float
    unclassified_contracts: float
    degraded_packets: int


def build_trade_totals(rows: Sequence[Mapping[str, Any]]) -> TradeTotals:
    """Accumulate identified executed volume and its classified side from `full` packets."""

    packets = 0
    classified = 0
    executed = 0.0
    buy = 0.0
    sell = 0.0
    unclassified = 0.0
    degraded = 0
    for row in rows:
        if row.get("event_type") != "full":
            continue
        increment = row.get("cumulative_volume_increment")
        if increment is None:
            continue
        packets += 1
        volume = float(increment)
        executed += volume
        if row.get("trade_classification_degraded"):
            degraded += 1
        side = row.get("trade_side")
        if side == "buy":
            classified += 1
            buy += volume
        elif side == "sell":
            classified += 1
            sell += volume
        else:
            unclassified += volume
    return TradeTotals(
        packets=packets,
        classified_packets=classified,
        executed_contracts=executed,
        buy_contracts=buy,
        sell_contracts=sell,
        unclassified_contracts=unclassified,
        degraded_packets=degraded,
    )


def component_intensity_table(
    intensities: Mapping[str, Any], *, trades: TradeTotals | None
) -> dict[str, Any]:
    """Counts per second, contracts per second, and shares, with the identification labels kept."""

    span = float(intensities["valid_span_seconds"]) or None
    absolute = intensities["component_absolute_contracts"]
    total_absolute = sum(absolute.values())
    components = {
        name: {
            "events": intensities["component_events"][name],
            "events_per_second": (
                None if span is None else intensities["component_events"][name] / span
            ),
            "signed_contracts": intensities["component_signed_contracts"][name],
            "absolute_contracts": absolute[name],
            "absolute_contracts_per_second": (None if span is None else absolute[name] / span),
            "share_of_absolute_contribution": (
                None if total_absolute <= 0 else absolute[name] / total_absolute
            ),
            "identification": (
                "displayed_addition_not_gross_arrival"
                if name.endswith("addition")
                else (
                    "displayed_removal_not_cancellation"
                    if name.endswith("removal")
                    else "best_quote_price_move"
                )
            ),
        }
        for name in L1_COMPONENTS
    }
    displayed_removal = (
        absolute["bid_same_price_removal"] + absolute["ask_same_price_removal"]
    )
    price_move_depletion = (
        absolute["bid_price_worsening"] + absolute["ask_price_worsening"]
    )
    payload: dict[str, Any] = {
        "valid_transitions": intensities["valid_transitions"],
        "valid_span_seconds": intensities["valid_span_seconds"],
        "valid_transitions_per_second": (
            None if span is None else intensities["valid_transitions"] / span
        ),
        "bid_no_change_events": intensities["bid_no_change_events"],
        "ask_no_change_events": intensities["ask_no_change_events"],
        "total_absolute_contracts": total_absolute,
        "components": components,
        "unidentified_quantities": [
            "gross_limit_order_arrival_intensity",
            "gross_cancellation_intensity",
            "queue_position",
        ],
    }
    if trades is None:
        payload["execution_attribution"] = None
        return payload
    payload["execution_attribution"] = {
        "identified_executed_contracts": trades.executed_contracts,
        "identified_buy_contracts": trades.buy_contracts,
        "identified_sell_contracts": trades.sell_contracts,
        "unclassified_executed_contracts": trades.unclassified_contracts,
        "trade_packets": trades.packets,
        "side_classified_packets": trades.classified_packets,
        "degraded_classification_packets": trades.degraded_packets,
        "l1_displayed_removal_contracts": displayed_removal,
        "l1_price_move_depletion_contracts": price_move_depletion,
        "executed_share_of_displayed_removal_upper_bound": (
            None
            if displayed_removal <= 0
            else min(1.0, trades.executed_contracts / displayed_removal)
        ),
        "residual_unattributed_displayed_removal_contracts": max(
            0.0, displayed_removal - trades.executed_contracts
        ),
        "limits": (
            "Vendor trade packets are coalesced, far slower than the depth stream, and carry no "
            "level attribution. Executed volume may consume levels behind the touch, so the share "
            "above is an upper bound and the residual is not a cancellation intensity."
        ),
    }
    return payload


@dataclass(frozen=True, slots=True)
class CksL1TapeInput:
    tape_index: int
    run_id: str
    instrument_id: str
    tape_sha256: str
    observations: tuple[CksL1Observation, ...]
    depth200_publications: int
    depth20_publications: int
    observed_seconds: float
    failures: Mapping[str, int]
    intensities: Mapping[str, Any]
    trades: TradeTotals | None


def _merge_intensities(tapes: Sequence[CksL1TapeInput]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "valid_transitions": 0,
        "component_events": dict.fromkeys(L1_COMPONENTS, 0),
        "component_signed_contracts": dict.fromkeys(L1_COMPONENTS, 0.0),
        "component_absolute_contracts": dict.fromkeys(L1_COMPONENTS, 0.0),
        "bid_no_change_events": 0,
        "ask_no_change_events": 0,
        "valid_span_seconds": 0.0,
    }
    for tape in tapes:
        merged["valid_transitions"] += tape.intensities["valid_transitions"]
        merged["bid_no_change_events"] += tape.intensities["bid_no_change_events"]
        merged["ask_no_change_events"] += tape.intensities["ask_no_change_events"]
        merged["valid_span_seconds"] += tape.intensities["valid_span_seconds"]
        for name in L1_COMPONENTS:
            merged["component_events"][name] += tape.intensities["component_events"][name]
            merged["component_signed_contracts"][name] += tape.intensities[
                "component_signed_contracts"
            ][name]
            merged["component_absolute_contracts"][name] += tape.intensities[
                "component_absolute_contracts"
            ][name]
    return merged


def _merge_trades(tapes: Sequence[CksL1TapeInput]) -> TradeTotals | None:
    available = [tape.trades for tape in tapes if tape.trades is not None]
    if not available:
        return None
    return TradeTotals(
        packets=sum(item.packets for item in available),
        classified_packets=sum(item.classified_packets for item in available),
        executed_contracts=sum(item.executed_contracts for item in available),
        buy_contracts=sum(item.buy_contracts for item in available),
        sell_contracts=sum(item.sell_contracts for item in available),
        unclassified_contracts=sum(item.unclassified_contracts for item in available),
        degraded_packets=sum(item.degraded_packets for item in available),
    )


def _cell_key(row: Mapping[str, Any]) -> tuple[float, int]:
    return (float(row["ofi_window_seconds"]), int(row["return_horizon_seconds"]))


def build_cks_l1_artifact(
    tapes: Sequence[CksL1TapeInput],
    *,
    code_commit: str | None,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Assemble the complete deterministic scan artifact for `X-CKS-L1-OFI-DAT20-04`."""

    observations = [observation for tape in tapes for observation in tape.observations]
    if not observations:
        raise ValueError("at least one CKS level-one observation is required")
    assert_no_lookahead(observations)
    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations],
        embargo_seconds=EMBARGO_SECONDS,
    )
    grid = evaluate_grid(observations, split, replicates=replicates, seed=seed)
    same_window = evaluate_same_window(observations, split)
    per_tape: list[dict[str, Any]] = []
    stratified: dict[tuple[str, float, int], dict[str, Any]] = {}
    for tape in tapes:
        tape_observations = list(tape.observations)
        tape_split = chronological_embargoed_split(
            [as_normal_observation(observation) for observation in tape_observations],
            embargo_seconds=EMBARGO_SECONDS,
        )
        tape_rows = evaluate_grid(
            tape_observations,
            tape_split,
            replicates=min(replicates, 100),
            seed=seed + 3_000_000 + tape.tape_index,
        )
        for row in tape_rows:
            window, horizon = _cell_key(row)
            stratified[(tape.run_id, window, horizon)] = row
        per_tape.append(
            {
                "run_id": tape.run_id,
                "train_n": len(tape_split.train),
                "test_n": len(tape_split.test),
                "embargoed_n": len(tape_split.embargoed),
                "grid": tape_rows,
            }
        )
    for row in grid:
        window, horizon = _cell_key(row)
        strata: list[dict[str, Any]] = []
        for tape in tapes:
            stratum = stratified[(tape.run_id, window, horizon)]
            strata.append(
                {
                    "run_id": tape.run_id,
                    "m2_depth_only_oos_r2": stratum["models"]["M2"]["oos_r2_training_mean"],
                    "m3_depth_plus_ofi_oos_r2": stratum["models"]["M3"]["oos_r2_training_mean"],
                    "incremental_oos_r2_ofi_over_depth": stratum[
                        "incremental_oos_r2_ofi_over_depth"
                    ],
                    "m3_ofi_coefficient_ticks_per_training_sd": stratum["models"]["M3"][
                        "coefficient_ticks_per_training_sd"
                    ].get(ofi_feature(window)),
                    "m3_ofi_coefficient_ticks_per_100_contracts": stratum["models"]["M3"][
                        "ofi_coefficient_ticks_per_100_contracts"
                    ],
                }
            )
        coefficients = [
            float(stratum["m3_ofi_coefficient_ticks_per_training_sd"])
            for stratum in strata
            if stratum["m3_ofi_coefficient_ticks_per_training_sd"] is not None
        ]
        row["per_tape"] = strata
        row["coefficient_sign_consistent_across_tapes"] = bool(coefficients) and (
            all(value > 0 for value in coefficients) or all(value < 0 for value in coefficients)
        )
        row["positive_increment_in_both_tapes"] = all(
            stratum["incremental_oos_r2_ofi_over_depth"] is not None
            and float(stratum["incremental_oos_r2_ofi_over_depth"]) > 0
            for stratum in strata
        )
    ranked = sorted(
        grid,
        key=lambda row: (
            float("-inf")
            if row["incremental_oos_r2_ofi_over_depth"] is None
            else row["incremental_oos_r2_ofi_over_depth"]
        ),
        reverse=True,
    )
    distinguishable = [
        row
        for row in grid
        if row["ofi_over_depth_inference"]["distinguishable_positive_improvement"]
    ]
    past_beats_future = sum(
        1
        for row in grid
        if row["past_incremental_oos_r2_ofi_over_depth"] is not None
        and row["incremental_oos_r2_ofi_over_depth"] is not None
        and row["past_incremental_oos_r2_ofi_over_depth"] > row["incremental_oos_r2_ofi_over_depth"]
    )
    depth_scaling_helps = sum(1 for row in grid if row["depth_scaling_helps_oos"] is True)
    price_keyed_better = sum(
        1
        for row in grid
        if row["incremental_oos_r2_price_keyed_top10_over_depth"] is not None
        and row["incremental_oos_r2_ofi_over_depth"] is not None
        and row["incremental_oos_r2_price_keyed_top10_over_depth"]
        > row["incremental_oos_r2_ofi_over_depth"]
    )
    positive_increment = sum(
        1
        for row in grid
        if row["incremental_oos_r2_ofi_over_depth"] is not None
        and row["incremental_oos_r2_ofi_over_depth"] > 0
    )
    floor_hits = sum(len(observation.depth_floor_hits) for observation in observations)
    return {
        "protocol": {
            "exploratory_scan_id": EXPLORATORY_SCAN_ID,
            "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
            "part_of_h_sig21": False,
            "code_commit": code_commit,
            "design_document": DESIGN_DOCUMENT,
            "compared_against_scan_id": "X-OFI-DAT20-03",
            "grid_size": len(grid),
            "models": list(CELL_MODELS),
            "ofi_windows_seconds": list(OFI_WINDOWS_SECONDS),
            "return_horizons_seconds": list(RETURN_HORIZONS_SECONDS),
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
            "minimum_mean_depth_contracts": MINIMUM_MEAN_DEPTH_CONTRACTS,
            "depth_baseline_feature": DEPTH_BASELINE_FEATURE,
        },
        "tapes": [
            {
                "run_id": tape.run_id,
                "instrument_id": tape.instrument_id,
                "tape_sha256": tape.tape_sha256,
                "depth200_publications": tape.depth200_publications,
                "depth20_publications": tape.depth20_publications,
                "observed_seconds": tape.observed_seconds,
                "observations": len(tape.observations),
                "failures": dict(tape.failures),
                "component_intensities": component_intensity_table(
                    tape.intensities, trades=tape.trades
                ),
            }
            for tape in tapes
        ],
        "totals": {
            "observations": len(observations),
            "train_n": len(split.train),
            "test_n": len(split.test),
            "embargoed_n": len(split.embargoed),
            "depth_floor_observations_windows": floor_hits,
            "mean_l1_depth_end_contracts": sum(
                observation.l1_depth_end for observation in observations
            )
            / len(observations),
        },
        "component_intensities_pooled": component_intensity_table(
            _merge_intensities(tapes), trades=_merge_trades(tapes)
        ),
        "plain_summary_inputs": {
            "best_cells_by_incremental_oos_r2": ranked[:5],
            "cells_with_positive_incremental_oos_r2": positive_increment,
            "cells_surviving_all_three_dependence_checks": len(distinguishable),
            "past_increment_beats_future_increment_cells": past_beats_future,
            "cells_where_depth_scaling_helps": depth_scaling_helps,
            "cells_where_price_keyed_top10_beats_level_one": price_keyed_better,
            "grid_cells": len(grid),
        },
        "grid": grid,
        "per_tape_grid": per_tape,
        "same_window_diagnostic": same_window,
    }
