"""Exploratory price-keyed OFI scan for `X-OFI-DAT20-03`.

The module isolates one object: signed quantity innovations keyed by absolute price.  It does not
reuse the mixed book-state feature set from ``deep_book_normal_activity``.  The two permitted tapes
have already had their outcomes inspected, so every result produced here is exploratory.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Literal

import numpy as np

from shaurya.data.depth_thinning_analysis import DEPTH200, BookState
from shaurya.signals.deep_book_anomaly import BOUNDARY_OVERLAP_RATIO, INVALID_QUALITY_FLAGS
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EMBARGO_SECONDS,
    MINIMUM_FIT_OBSERVATIONS,
    Depth20MidSeries,
    Observation,
    SplitIndex,
    _r_squared,
    build_depth20_mid_series,
    chronological_embargoed_split,
    estimate_mean,
    fit_ridge,
)
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND

EXPLORATORY_SCAN_ID = "X-OFI-DAT20-03"
CONFIRMATORY_ELIGIBLE = False
DEPTH_CUTOFFS = (1, 5, 10, 20, 50, 100, 200)
OFI_WINDOWS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
RETURN_HORIZONS_SECONDS = (1, 2, 5, 10, 30)
CAUSAL_GAP_SECONDS = 0.5
FUTURES_TICK_SIZE = 0.05


def _label(value: float) -> str:
    return str(value).replace(".", "p").rstrip("0").rstrip("p")


def ofi_feature(window_seconds: float, depth: int) -> str:
    return f"ofi_w{_label(window_seconds)}__depth_{depth}"


def band_feature(window_seconds: float, lower: int, upper: int) -> str:
    return f"ofi_w{_label(window_seconds)}__band_{lower}_{upper}"


def _price_map(state: BookState, side: Literal["bid", "ask"]) -> dict[float, tuple[int, int]]:
    ladder = state.bids if side == "bid" else state.asks
    return {price: (quantity, orders) for price, quantity, orders in ladder}


def _boundary_churn(
    old: Mapping[float, tuple[int, int]],
    new: Mapping[float, tuple[int, int]],
    side: Literal["bid", "ask"],
) -> tuple[set[float], set[float]]:
    """Identify a one-level outer-window slide, which is not an order-flow event."""

    removed = set(old) - set(new)
    added = set(new) - set(old)
    denominator = min(len(old), len(new))
    if not removed or not added or denominator == 0:
        return set(), set()
    overlap = len(set(old) & set(new)) / denominator
    if overlap < BOUNDARY_OVERLAP_RATIO or len(removed) > 2 or len(added) > 2:
        return set(), set()
    old_outer = min(old) if side == "bid" else max(old)
    new_outer = min(new) if side == "bid" else max(new)
    if old_outer not in removed or new_outer not in added:
        return set(), set()
    return removed, added


def _invalid_transition(previous: BookState, current: BookState) -> str | None:
    if previous.channel != DEPTH200 or current.channel != DEPTH200:
        return "not_depth200"
    if current.receive_ts_ns <= previous.receive_ts_ns:
        return "non_monotone_receive_time"
    if current.connection_epoch != previous.connection_epoch:
        return "connection_epoch_boundary"
    flags = (set(previous.quality_flags) | set(current.quality_flags)) & INVALID_QUALITY_FLAGS
    if flags:
        return "invalid_quality:" + ",".join(sorted(flags))
    if not previous.bids or not previous.asks or not current.bids or not current.asks:
        return "incomplete_two_sided_book"
    if (
        previous.best_bid is None
        or previous.best_ask is None
        or current.best_bid is None
        or current.best_ask is None
        or previous.best_bid >= previous.best_ask
        or current.best_bid >= current.best_ask
    ):
        return "crossed_or_missing_book"
    return None


@dataclass(frozen=True, slots=True)
class PriceKeyedOFITransition:
    """One valid endpoint-to-endpoint OFI innovation."""

    receive_ts_ns: int
    cumulative_by_depth: Mapping[int, float]
    boundary_excluded_quantity: float
    included_price_keys: int
    invalid_reason: str | None = None


def price_keyed_ofi_transition(previous: BookState, current: BookState) -> PriceKeyedOFITransition:
    """Compute signed price-keyed quantity innovations for all cumulative depth cutoffs.

    A price is assigned the shallowest rank it occupies in either endpoint.  This prevents a best
    price move from relabelling every surviving price as a new event.  A one-level slide at the
    outer edge is removed explicitly because it is a vendor-window boundary, not observed flow.
    """

    invalid = _invalid_transition(previous, current)
    if invalid is not None:
        return PriceKeyedOFITransition(
            current.receive_ts_ns,
            {depth: 0.0 for depth in DEPTH_CUTOFFS},
            0.0,
            0,
            invalid,
        )
    signed_by_rank: dict[int, float] = {}
    excluded_quantity = 0.0
    included = 0
    for side in ("bid", "ask"):
        typed_side: Literal["bid", "ask"] = side
        old = _price_map(previous, typed_side)
        new = _price_map(current, typed_side)
        old_rank = {price: rank for rank, price in enumerate(old, start=1)}
        new_rank = {price: rank for rank, price in enumerate(new, start=1)}
        removed_boundary, added_boundary = _boundary_churn(old, new, typed_side)
        boundary = removed_boundary | added_boundary
        for price in boundary:
            excluded_quantity += abs(new.get(price, (0, 0))[0] - old.get(price, (0, 0))[0])
        sign = 1.0 if typed_side == "bid" else -1.0
        for price in (set(old) | set(new)) - boundary:
            rank = min(old_rank.get(price, 10**9), new_rank.get(price, 10**9))
            if rank > max(DEPTH_CUTOFFS):
                continue
            delta = float(new.get(price, (0, 0))[0] - old.get(price, (0, 0))[0])
            signed_by_rank[rank] = signed_by_rank.get(rank, 0.0) + sign * delta
            included += 1
    cumulative: dict[int, float] = {}
    running = 0.0
    for rank in range(1, max(DEPTH_CUTOFFS) + 1):
        running += signed_by_rank.get(rank, 0.0)
        if rank in DEPTH_CUTOFFS:
            cumulative[rank] = running
    return PriceKeyedOFITransition(
        current.receive_ts_ns,
        cumulative,
        excluded_quantity,
        included,
        None,
    )


def _controls(state: BookState) -> dict[str, float] | None:
    if not state.bids or not state.asks:
        return None
    bid, bid_quantity, _ = state.bids[0]
    ask, ask_quantity, _ = state.asks[0]
    if bid >= ask or bid_quantity + ask_quantity <= 0:
        return None
    midpoint = (bid + ask) / 2.0
    microprice = (ask_quantity * bid + bid_quantity * ask) / (bid_quantity + ask_quantity)
    return {
        "spread_ticks": (ask - bid) / FUTURES_TICK_SIZE,
        "microprice_tilt_ticks": (microprice - midpoint) / FUTURES_TICK_SIZE,
    }


def _mid_return(series: Depth20MidSeries, start_ts_ns: int, end_ts_ns: int) -> float | None:
    start = series.as_of(start_ts_ns)
    end = series.as_of(end_ts_ns)
    if start is None or end is None or end_ts_ns <= start_ts_ns:
        return None
    return (end - start) / FUTURES_TICK_SIZE


@dataclass(frozen=True, slots=True)
class OFIObservation:
    tape_index: int
    run_id: str
    receive_ts_ns: int
    time_bucket: str
    features: Mapping[str, float]
    future_ticks: Mapping[int, float]
    past_ticks: Mapping[int, float]
    contemporaneous_ticks: Mapping[int, float]
    same_window_ticks: Mapping[float, float]
    boundary_excluded_quantity: Mapping[float, float]


def build_ofi_observations(
    *,
    depth200_states: Sequence[BookState],
    depth20_states: Sequence[BookState],
    tape_index: int,
    run_id: str,
) -> tuple[list[OFIObservation], dict[str, int]]:
    """Build one aligned observation after every complete 10-second OFI history."""

    failures = {
        "invalid_transition": 0,
        "incomplete_ofi_history": 0,
        "unusable_controls": 0,
        "no_depth20_anchor": 0,
        "no_future_horizon_covered": 0,
    }
    if len(depth200_states) < 2:
        return [], failures
    transitions = [
        price_keyed_ofi_transition(previous, current)
        for previous, current in zip(depth200_states[:-1], depth200_states[1:], strict=True)
    ]
    stamps = [transition.receive_ts_ns for transition in transitions]
    invalid_prefix = [0]
    ofi_prefix = {depth: [0.0] for depth in DEPTH_CUTOFFS}
    excluded_prefix = [0.0]
    for transition in transitions:
        invalid_prefix.append(invalid_prefix[-1] + int(transition.invalid_reason is not None))
        if transition.invalid_reason is not None:
            failures["invalid_transition"] += 1
        for depth in DEPTH_CUTOFFS:
            ofi_prefix[depth].append(ofi_prefix[depth][-1] + transition.cumulative_by_depth[depth])
        excluded_prefix.append(excluded_prefix[-1] + transition.boundary_excluded_quantity)
    series = build_depth20_mid_series(depth20_states)
    observations: list[OFIObservation] = []
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
        boundary_by_window: dict[float, float] = {}
        complete = True
        for window in OFI_WINDOWS_SECONDS:
            start = state.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND)
            left = bisect_right(stamps, start)
            right = position + 1
            if left >= right or invalid_prefix[right] - invalid_prefix[left] != 0:
                complete = False
                break
            cumulative: dict[int, float] = {}
            for depth in DEPTH_CUTOFFS:
                value = ofi_prefix[depth][right] - ofi_prefix[depth][left]
                cumulative[depth] = value
                features[ofi_feature(window, depth)] = value
            previous_depth = 0
            previous_value = 0.0
            for depth in DEPTH_CUTOFFS:
                features[band_feature(window, previous_depth + 1, depth)] = (
                    cumulative[depth] - previous_value
                )
                previous_depth = depth
                previous_value = cumulative[depth]
            boundary_by_window[window] = excluded_prefix[right] - excluded_prefix[left]
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
            OFIObservation(
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=state.receive_ts_ns,
                time_bucket="mid_afternoon",
                features=features,
                future_ticks=future,
                past_ticks=past,
                contemporaneous_ticks={},
                same_window_ticks=same_window,
                boundary_excluded_quantity=boundary_by_window,
            )
        )
    return observations, failures


def _positions(
    observations: Sequence[OFIObservation],
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
    observations: Sequence[OFIObservation],
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
    observations: Sequence[OFIObservation],
    positions: Sequence[int],
    names: Sequence[str],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(
        [[observations[position].features[name] for name in names] for position in positions],
        dtype=np.float64,
    ).reshape(len(positions), len(names))


@dataclass(frozen=True, slots=True)
class ModelScore:
    r2_training_mean: float | None
    r2_zero_raw: float | None
    errors: tuple[float, ...]
    standardised_ofi_coefficient: float | None
    raw_ofi_coefficient_per_100_contracts: float | None


def _score_model(
    observations: Sequence[OFIObservation],
    train_positions: Sequence[int],
    test_positions: Sequence[int],
    *,
    names: Sequence[str],
    horizon: int,
    source: Literal["future", "past"],
    ofi_name: str | None,
) -> ModelScore:
    raw_train = _target(observations, train_positions, horizon, source)
    raw_test = _target(observations, test_positions, horizon, source)
    drift = float(raw_train.mean())
    train_target = raw_train - drift
    test_target = raw_test - drift
    train_design = _design(observations, train_positions, names)
    test_design = _design(observations, test_positions, names)
    fit = fit_ridge(train_design, train_target, feature_names=names, penalty=0.0)
    predicted = fit.predict(test_design)
    benchmark = np.zeros(test_target.shape, dtype=np.float64)
    raw_benchmark = np.zeros(raw_test.shape, dtype=np.float64)
    standardised: float | None = None
    raw_per_100: float | None = None
    if ofi_name is not None:
        index = tuple(names).index(ofi_name)
        standardised = float(fit.coefficients[index])
        raw_per_100 = float(fit.coefficients[index] / fit.scale[index] * 100.0)
    return ModelScore(
        r2_training_mean=_r_squared(test_target, predicted, benchmark),
        r2_zero_raw=_r_squared(raw_test, predicted + drift, raw_benchmark),
        errors=tuple(float(value) for value in (test_target - predicted) ** 2),
        standardised_ofi_coefficient=standardised,
        raw_ofi_coefficient_per_100_contracts=raw_per_100,
    )


def _inference_payload(
    before: Sequence[float],
    after: Sequence[float],
    observations: Sequence[OFIObservation],
    test_positions: Sequence[int],
    *,
    horizon: int,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    differential = [left - right for left, right in zip(before, after, strict=True)]
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
    distinguishable = all(value is not None and value > 1.96 for value in statistics)
    return {
        **asdict(estimate),
        "distinguishable_positive_improvement": distinguishable,
        "naive_inference_valid": False,
    }


def evaluate_grid(
    observations: Sequence[OFIObservation],
    split: SplitIndex,
    *,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """Evaluate all 175 depth × OFI-window × return-horizon cells without filtering."""

    rows: list[dict[str, Any]] = []
    controls = ("spread_ticks", "microprice_tilt_ticks")
    for horizon in RETURN_HORIZONS_SECONDS:
        future_train = _positions(observations, split.train, horizon, "future")
        future_test = _positions(observations, split.test, horizon, "future")
        past_train = _positions(observations, split.train, horizon, "past")
        past_test = _positions(observations, split.test, horizon, "past")
        smallest_sample = min(len(future_train), len(future_test), len(past_train), len(past_test))
        if smallest_sample < MINIMUM_FIT_OBSERVATIONS:
            raise ValueError(f"insufficient observations at {horizon}s")
        future_control = _score_model(
            observations,
            future_train,
            future_test,
            names=controls,
            horizon=horizon,
            source="future",
            ofi_name=None,
        )
        past_control = _score_model(
            observations,
            past_train,
            past_test,
            names=controls,
            horizon=horizon,
            source="past",
            ofi_name=None,
        )
        for window in OFI_WINDOWS_SECONDS:
            for depth in DEPTH_CUTOFFS:
                name = ofi_feature(window, depth)
                future_ofi = _score_model(
                    observations,
                    future_train,
                    future_test,
                    names=(name,),
                    horizon=horizon,
                    source="future",
                    ofi_name=name,
                )
                future_full = _score_model(
                    observations,
                    future_train,
                    future_test,
                    names=(*controls, name),
                    horizon=horizon,
                    source="future",
                    ofi_name=name,
                )
                past_full = _score_model(
                    observations,
                    past_train,
                    past_test,
                    names=(*controls, name),
                    horizon=horizon,
                    source="past",
                    ofi_name=name,
                )
                inference = _inference_payload(
                    future_control.errors,
                    future_full.errors,
                    observations,
                    future_test,
                    horizon=horizon,
                    replicates=replicates,
                    seed=seed + horizon * 10_000 + int(window * 100) + depth,
                )
                rows.append(
                    {
                        "ofi_window_seconds": window,
                        "depth_levels": depth,
                        "return_horizon_seconds": horizon,
                        "causal_gap_seconds": CAUSAL_GAP_SECONDS,
                        "train_n": len(future_train),
                        "test_n": len(future_test),
                        "ofi_only_oos_r2": future_ofi.r2_training_mean,
                        "state_baseline_oos_r2": future_control.r2_training_mean,
                        "state_plus_ofi_oos_r2": future_full.r2_training_mean,
                        "incremental_oos_r2_over_state": (
                            None
                            if future_full.r2_training_mean is None
                            or future_control.r2_training_mean is None
                            else future_full.r2_training_mean - future_control.r2_training_mean
                        ),
                        "state_plus_ofi_raw_r2_vs_zero": future_full.r2_zero_raw,
                        "standardised_ofi_coefficient_ticks": (
                            future_full.standardised_ofi_coefficient
                        ),
                        "raw_ofi_coefficient_ticks_per_100_contracts": (
                            future_full.raw_ofi_coefficient_per_100_contracts
                        ),
                        "past_state_baseline_oos_r2": past_control.r2_training_mean,
                        "past_state_plus_ofi_oos_r2": past_full.r2_training_mean,
                        "past_incremental_oos_r2_over_state": (
                            None
                            if past_full.r2_training_mean is None
                            or past_control.r2_training_mean is None
                            else past_full.r2_training_mean - past_control.r2_training_mean
                        ),
                        "future_error_improvement_inference": inference,
                    }
                )
    expected = len(OFI_WINDOWS_SECONDS) * len(DEPTH_CUTOFFS) * len(RETURN_HORIZONS_SECONDS)
    if len(rows) != expected:
        raise RuntimeError(f"complete grid required: expected {expected}, got {len(rows)}")
    return rows


def evaluate_nested_depth(
    observations: Sequence[OFIObservation],
    split: SplitIndex,
    *,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> list[dict[str, Any]]:
    """Secondary nested ladder using disjoint OFI bands at every window and horizon."""

    rows: list[dict[str, Any]] = []
    controls = ("spread_ticks", "microprice_tilt_ticks")
    bands = tuple(
        (previous + 1, depth)
        for previous, depth in zip((0, *DEPTH_CUTOFFS[:-1]), DEPTH_CUTOFFS, strict=True)
    )
    for horizon in RETURN_HORIZONS_SECONDS:
        train = _positions(observations, split.train, horizon, "future")
        test = _positions(observations, split.test, horizon, "future")
        for window in OFI_WINDOWS_SECONDS:
            previous = _score_model(
                observations,
                train,
                test,
                names=controls,
                horizon=horizon,
                source="future",
                ofi_name=None,
            )
            selected: list[str] = []
            for lower, upper in bands:
                selected.append(band_feature(window, lower, upper))
                current = _score_model(
                    observations,
                    train,
                    test,
                    names=(*controls, *selected),
                    horizon=horizon,
                    source="future",
                    ofi_name=selected[-1],
                )
                inference = _inference_payload(
                    previous.errors,
                    current.errors,
                    observations,
                    test,
                    horizon=horizon,
                    replicates=replicates,
                    seed=seed + 1_000_000 + horizon * 10_000 + int(window * 100) + upper,
                )
                rows.append(
                    {
                        "ofi_window_seconds": window,
                        "return_horizon_seconds": horizon,
                        "adds_band": f"{lower}-{upper}",
                        "through_depth": upper,
                        "oos_r2": current.r2_training_mean,
                        "incremental_oos_r2": (
                            None
                            if current.r2_training_mean is None or previous.r2_training_mean is None
                            else current.r2_training_mean - previous.r2_training_mean
                        ),
                        "error_improvement_inference": inference,
                    }
                )
                previous = current
    return rows


def evaluate_same_window(
    observations: Sequence[OFIObservation], split: SplitIndex
) -> list[dict[str, Any]]:
    """Construction diagnostic only: OFI and price change over the same window."""

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
        train_target = np.asarray(
            [observations[position].same_window_ticks[window] for position in train],
            dtype=np.float64,
        )
        test_target = np.asarray(
            [observations[position].same_window_ticks[window] for position in test],
            dtype=np.float64,
        )
        drift = float(train_target.mean())
        train_target -= drift
        test_target -= drift
        for depth in DEPTH_CUTOFFS:
            name = ofi_feature(window, depth)
            design_train = _design(observations, train, (name,))
            design_test = _design(observations, test, (name,))
            fit = fit_ridge(design_train, train_target, feature_names=(name,), penalty=0.0)
            predicted = fit.predict(design_test)
            rows.append(
                {
                    "ofi_window_seconds": window,
                    "depth_levels": depth,
                    "same_window_oos_r2": _r_squared(
                        test_target, predicted, np.zeros(test_target.shape, dtype=np.float64)
                    ),
                    "descriptive_only": True,
                }
            )
    return rows


@dataclass(frozen=True, slots=True)
class OFITapeInput:
    tape_index: int
    run_id: str
    instrument_id: str
    tape_sha256: str
    observations: tuple[OFIObservation, ...]
    depth200_publications: int
    depth20_publications: int
    observed_seconds: float
    failures: Mapping[str, int]


def build_ofi_artifact(
    tapes: Sequence[OFITapeInput],
    *,
    code_commit: str | None,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    observations = [observation for tape in tapes for observation in tape.observations]
    if not observations:
        raise ValueError("at least one OFI observation is required")
    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations],
        embargo_seconds=EMBARGO_SECONDS,
    )
    grid = evaluate_grid(observations, split, replicates=replicates, seed=seed)
    nested = evaluate_nested_depth(observations, split, replicates=replicates, seed=seed)
    same_window = evaluate_same_window(observations, split)
    ranked = sorted(
        grid,
        key=lambda row: (
            float("-inf") if row["state_plus_ofi_oos_r2"] is None else row["state_plus_ofi_oos_r2"]
        ),
        reverse=True,
    )
    distinguishable = [
        row
        for row in grid
        if row["future_error_improvement_inference"]["distinguishable_positive_improvement"]
    ]
    past_better = sum(
        1
        for row in grid
        if (
            row["past_incremental_oos_r2_over_state"] is not None
            and row["incremental_oos_r2_over_state"] is not None
            and row["past_incremental_oos_r2_over_state"] > row["incremental_oos_r2_over_state"]
        )
    )
    boundary = {
        str(window): sum(
            observation.boundary_excluded_quantity[window] for observation in observations
        )
        for window in OFI_WINDOWS_SECONDS
    }
    if not all(isfinite(value) for value in boundary.values()):
        raise ValueError("non-finite boundary exclusion total")
    return {
        "protocol": {
            "exploratory_scan_id": EXPLORATORY_SCAN_ID,
            "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
            "part_of_h_sig21": False,
            "code_commit": code_commit,
            "design_document": "docs/OFI-PREDICTIVE-SCAN-SPEC-2026-08-19.md",
            "grid_size": len(grid),
            "depth_cutoffs": list(DEPTH_CUTOFFS),
            "ofi_windows_seconds": list(OFI_WINDOWS_SECONDS),
            "return_horizons_seconds": list(RETURN_HORIZONS_SECONDS),
            "causal_gap_seconds": CAUSAL_GAP_SECONDS,
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
            }
            for tape in tapes
        ],
        "totals": {
            "observations": len(observations),
            "train_n": len(split.train),
            "test_n": len(split.test),
            "embargoed_n": len(split.embargoed),
            "boundary_excluded_quantity_by_window": boundary,
        },
        "plain_summary_inputs": {
            "best_cells_by_state_plus_ofi_r2": ranked[:10],
            "positive_error_improvements_surviving_all_three_checks": len(distinguishable),
            "past_increment_beats_future_increment_cells": past_better,
            "grid_cells": len(grid),
        },
        "grid": grid,
        "nested_depth": nested,
        "same_window_diagnostic": same_window,
    }


def as_normal_observation(observation: OFIObservation) -> Observation:
    """Compatibility helper used only by tests and generic split tooling."""

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
