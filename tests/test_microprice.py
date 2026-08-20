"""Tests for `D38 / TOUCH-METRICS-2026-08-20` section D.

`VAL-MICRO-01` — the Stoikov state model is fitted on training rows only — is the frozen
acceptance test; the rest pin the state discretisation and the chain algebra.
"""

from __future__ import annotations

import pytest

from shaurya.signals.deep_book_ofi import FUTURES_TICK_SIZE
from shaurya.signals.microprice import (
    ID_MICRO_01,
    IMBALANCE_BUCKETS,
    MINIMUM_TRANSITIONS_PER_STATE,
    SPREAD_BUCKET_EDGES_TICKS,
    MicropriceState,
    StoikovLeakage,
    StoikovTransition,
    build_stoikov_transitions,
    classify_state,
    fit_stoikov_microprice,
    imbalance_bucket,
    microprice_metadata,
    microprice_tilt_ticks,
    queue_imbalance,
    simple_microprice,
    spread_bucket,
)

SECOND = 1_000_000_000


# ------------------------------------------------------------------------------------ MICRO-01


def test_simple_microprice_leans_towards_the_side_with_the_smaller_queue() -> None:
    # A heavy bid queue and a light ask queue means the ask clears first, so the fair value sits
    # nearer the ask.
    value = simple_microprice(bid=100.0, bid_quantity=900.0, ask=100.05, ask_quantity=100.0)
    assert value is not None
    assert 100.025 < value < 100.05
    tilt = microprice_tilt_ticks(bid=100.0, bid_quantity=900.0, ask=100.05, ask_quantity=100.0)
    assert tilt is not None and tilt > 0.0


def test_simple_microprice_is_the_mid_when_the_queues_balance() -> None:
    assert simple_microprice(
        bid=100.0, bid_quantity=50.0, ask=100.05, ask_quantity=50.0
    ) == pytest.approx(100.025)
    assert microprice_tilt_ticks(
        bid=100.0, bid_quantity=50.0, ask=100.05, ask_quantity=50.0
    ) == pytest.approx(0.0)


def test_simple_microprice_never_leaves_the_displayed_quote() -> None:
    for bid_quantity in (1.0, 10.0, 1_000.0, 10_000.0):
        value = simple_microprice(
            bid=100.0, bid_quantity=bid_quantity, ask=100.05, ask_quantity=7.0
        )
        assert value is not None and 100.0 <= value <= 100.05


def test_simple_microprice_is_missing_on_a_crossed_or_empty_quote() -> None:
    assert simple_microprice(bid=100.05, bid_quantity=1.0, ask=100.0, ask_quantity=1.0) is None
    assert simple_microprice(bid=100.0, bid_quantity=0.0, ask=100.05, ask_quantity=0.0) is None
    assert microprice_tilt_ticks(bid=100.0, bid_quantity=0.0, ask=100.05, ask_quantity=0.0) is None
    assert queue_imbalance(0.0, 0.0) is None


# ------------------------------------------------------------------------------------ MICRO-02


def test_imbalance_buckets_span_the_signed_range_and_clamp_at_both_ends() -> None:
    assert imbalance_bucket(-1.0) == 0
    assert imbalance_bucket(1.0) == IMBALANCE_BUCKETS - 1
    assert imbalance_bucket(-5.0) == 0
    assert imbalance_bucket(5.0) == IMBALANCE_BUCKETS - 1
    assert imbalance_bucket(0.0) == IMBALANCE_BUCKETS // 2
    with pytest.raises(ValueError):
        imbalance_bucket(0.0, buckets=0)


def test_spread_buckets_are_half_open_with_an_open_final_bucket() -> None:
    assert spread_bucket(0.0) == 0
    assert spread_bucket(SPREAD_BUCKET_EDGES_TICKS[0]) == 1
    assert spread_bucket(10_000.0) == len(SPREAD_BUCKET_EDGES_TICKS)


def test_classify_state_is_missing_on_an_unusable_book() -> None:
    assert classify_state(bid_quantity=0.0, ask_quantity=0.0, spread_ticks=1.0) is None
    assert classify_state(bid_quantity=1.0, ask_quantity=1.0, spread_ticks=-1.0) is None
    state = classify_state(bid_quantity=3.0, ask_quantity=1.0, spread_ticks=1.0)
    assert state is not None and state.key.startswith("i")


def test_transitions_step_on_mid_changes_not_on_publications() -> None:
    state = MicropriceState(imbalance_bucket=5, spread_bucket=0)
    samples = [
        (0 * SECOND, 100.0, state),
        (1 * SECOND, 100.0, state),
        (2 * SECOND, 100.0, state),
        (3 * SECOND, 100.05, state),
        (4 * SECOND, 100.10, state),
    ]
    transitions = build_stoikov_transitions(samples)
    # three observations shared the first mid and all resolve to the same change
    assert [item.receive_ts_ns for item in transitions] == [0, 1 * SECOND, 2 * SECOND, 3 * SECOND]
    assert all(item.mid_change_ticks == pytest.approx(1.0) for item in transitions[:3])
    assert all(item.resolved_ts_ns == 3 * SECOND for item in transitions[:3])


def _transition(
    offset: int, state: MicropriceState, change: float, nxt: MicropriceState
) -> StoikovTransition:
    return StoikovTransition(
        receive_ts_ns=offset * SECOND,
        resolved_ts_ns=(offset + 1) * SECOND,
        state=state,
        mid_change_ticks=change,
        next_state=nxt,
    )


def test_val_micro_01_a_transition_resolving_after_the_boundary_is_refused() -> None:
    state = MicropriceState(imbalance_bucket=9, spread_bucket=0)
    transitions = [_transition(index, state, 1.0, state) for index in range(20)]
    boundary = 21 * SECOND
    fitted = fit_stoikov_microprice(transitions, training_upper_bound_ts_ns=boundary)
    assert fitted.transitions == 20

    # the same transition set, but the boundary now falls inside it: the fit must refuse
    with pytest.raises(StoikovLeakage):
        fit_stoikov_microprice(transitions, training_upper_bound_ts_ns=10 * SECOND)


def test_val_micro_01_a_transition_whose_origin_is_in_training_but_resolves_later_is_refused() -> (
    None
):
    state = MicropriceState(imbalance_bucket=9, spread_bucket=0)
    straddling = StoikovTransition(
        receive_ts_ns=5 * SECOND,
        resolved_ts_ns=50 * SECOND,
        state=state,
        mid_change_ticks=1.0,
        next_state=state,
    )
    with pytest.raises(StoikovLeakage):
        fit_stoikov_microprice([straddling], training_upper_bound_ts_ns=10 * SECOND)


def test_stoikov_adjustment_accumulates_the_whole_future_move_not_only_the_next_one() -> None:
    # A pure drift chain: from the bullish state the mid always rises one tick and stays bullish
    # until it is absorbed into a state that is never estimated.  The iterated estimator must
    # therefore exceed the one-step expectation of one tick.
    bullish = MicropriceState(imbalance_bucket=9, spread_bucket=0)
    neutral = MicropriceState(imbalance_bucket=5, spread_bucket=0)
    transitions = [_transition(index, bullish, 1.0, bullish) for index in range(90)]
    transitions.extend(_transition(200 + index, bullish, 1.0, neutral) for index in range(10))
    fitted = fit_stoikov_microprice(transitions, training_upper_bound_ts_ns=10_000 * SECOND)
    adjustment = fitted.adjustment(bullish)
    assert adjustment is not None
    # 90% of steps stay bullish, so the geometric sum is 1 / (1 - 0.9) = 10 ticks.
    assert adjustment == pytest.approx(10.0, rel=1e-6)
    assert fitted.converged
    assert fitted.spectral_radius == pytest.approx(0.9)
    # the neutral state never originated a transition, so it is missing rather than zero
    assert fitted.adjustment(neutral) is None
    assert fitted.fair_value_ticks(bullish, 100.0) == pytest.approx(
        100.0 + 10.0 * FUTURES_TICK_SIZE
    )
    assert fitted.fair_value_ticks(neutral, 100.0) is None


def test_stoikov_signs_are_symmetric_across_the_imbalance_axis() -> None:
    bullish = MicropriceState(imbalance_bucket=9, spread_bucket=0)
    bearish = MicropriceState(imbalance_bucket=0, spread_bucket=0)
    transitions = [_transition(index, bullish, 2.0, bullish) for index in range(20)]
    transitions.extend(_transition(100 + index, bearish, -2.0, bearish) for index in range(20))
    # each state must eventually leak out or the chain is stochastic and (I - B) is singular
    other = MicropriceState(imbalance_bucket=4, spread_bucket=0)
    transitions.extend(_transition(300 + index, bullish, 2.0, other) for index in range(20))
    transitions.extend(_transition(400 + index, bearish, -2.0, other) for index in range(20))
    fitted = fit_stoikov_microprice(transitions, training_upper_bound_ts_ns=10_000 * SECOND)
    up = fitted.adjustment(bullish)
    down = fitted.adjustment(bearish)
    assert up is not None and down is not None
    assert up == pytest.approx(-down)
    assert up > 0.0


def test_states_below_the_support_floor_are_dropped_not_estimated_noisily() -> None:
    busy = MicropriceState(imbalance_bucket=9, spread_bucket=0)
    thin = MicropriceState(imbalance_bucket=1, spread_bucket=2)
    transitions = [
        _transition(index, busy, 1.0, MicropriceState(imbalance_bucket=4, spread_bucket=0))
        for index in range(MINIMUM_TRANSITIONS_PER_STATE)
    ]
    transitions.append(_transition(500, thin, 99.0, thin))
    fitted = fit_stoikov_microprice(transitions, training_upper_bound_ts_ns=10_000 * SECOND)
    assert busy.key in fitted.estimated_states
    assert thin.key in fitted.dropped_states
    assert fitted.adjustment(thin) is None
    assert fitted.state_counts[thin.key] == 1


def test_a_chain_with_no_estimable_state_is_empty_and_says_so() -> None:
    thin = MicropriceState(imbalance_bucket=1, spread_bucket=2)
    fitted = fit_stoikov_microprice(
        [_transition(0, thin, 1.0, thin)], training_upper_bound_ts_ns=10_000 * SECOND
    )
    assert fitted.estimated_states == ()
    assert not fitted.converged
    assert fitted.adjustment(thin) is None
    assert fitted.to_dict()["estimated_states"] == []


def test_model_payload_labels_the_object_and_carries_the_limitation() -> None:
    state = MicropriceState(imbalance_bucket=9, spread_bucket=0)
    other = MicropriceState(imbalance_bucket=4, spread_bucket=0)
    transitions = [_transition(index, state, 1.0, other) for index in range(20)]
    payload = fit_stoikov_microprice(
        transitions, training_upper_bound_ts_ns=10_000 * SECOND
    ).to_dict()
    assert payload["object_category"] == "estimated"
    assert payload["fitted_on"] == "training_rows_only"
    assert payload["limitation_id"] == ID_MICRO_01
    metadata = microprice_metadata()
    assert metadata["simple_microprice"]["arm"] == "M7"
    assert metadata["stoikov_microprice"]["arm"] == "M8"
    assert metadata["simple_microprice"]["object_category"] == "deterministically_derived"
    assert metadata["stoikov_microprice"]["object_category"] == "estimated"
