from __future__ import annotations

from math import isclose, log1p

import pytest

from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState
from shaurya.signals.cks_l1_ofi import (
    CELL_MODELS,
    CKS_RETURN_HORIZONS_SECONDS,
    DEPTH_BASELINE_FEATURE,
    L1_COMPONENTS,
    MINIMUM_MEAN_DEPTH_CONTRACTS,
    OFI_WINDOWS_SECONDS,
    CksL1TapeInput,
    assert_no_lookahead,
    build_cks_l1_artifact,
    build_cks_l1_observations,
    build_trade_totals,
    cks_l1_transition,
    comparison_feature,
    component_intensity_table,
    evaluate_grid,
    ofi_feature,
    pressure_feature,
)
from shaurya.signals.deep_book_normal_activity import chronological_embargoed_split
from shaurya.signals.deep_book_ofi import FUTURES_TICK_SIZE

NANOSECONDS_PER_SECOND = 1_000_000_000


def _state(
    stamp: int,
    bids: tuple[tuple[float, int, int], ...],
    asks: tuple[tuple[float, int, int], ...],
    *,
    channel: str = DEPTH200,
    epoch: int = 0,
    flags: tuple[str, ...] = (),
) -> BookState:
    return BookState(
        channel=channel,
        receive_ts_ns=stamp,
        receive_sequence=stamp,
        connection_epoch=epoch,
        bids=bids,
        asks=asks,
        rows_in_burst=1,
        quality_flags=flags,
    )


def _pair(
    bid_before: tuple[float, int],
    ask_before: tuple[float, int],
    bid_after: tuple[float, int],
    ask_after: tuple[float, int],
) -> tuple[BookState, BookState]:
    previous = _state(
        1,
        ((bid_before[0], bid_before[1], 1), (bid_before[0] - 1.0, 50, 1)),
        ((ask_before[0], ask_before[1], 1), (ask_before[0] + 1.0, 50, 1)),
    )
    current = _state(
        2,
        ((bid_after[0], bid_after[1], 1), (bid_after[0] - 1.0, 50, 1)),
        ((ask_after[0], ask_after[1], 1), (ask_after[0] + 1.0, 50, 1)),
    )
    return previous, current


# ------------------------------------------------------------------------------------------
# STATE-CKS-01 — the eight signed cases of the CKS level-one increment
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bid_before", "ask_before", "bid_after", "ask_after", "expected", "component"),
    [
        ((100.0, 200), (101.0, 200), (100.5, 300), (101.0, 200), 300.0, "bid_price_improvement"),
        ((100.0, 300), (101.0, 200), (99.5, 40), (101.0, 200), -300.0, "bid_price_worsening"),
        ((100.0, 200), (101.0, 200), (100.0, 500), (101.0, 200), 300.0, "bid_same_price_addition"),
        ((100.0, 500), (101.0, 200), (100.0, 200), (101.0, 200), -300.0, "bid_same_price_removal"),
        ((100.0, 200), (101.0, 200), (100.0, 200), (100.5, 300), -300.0, "ask_price_improvement"),
        ((100.0, 200), (101.0, 300), (100.0, 200), (101.5, 40), 300.0, "ask_price_worsening"),
        ((100.0, 200), (101.0, 200), (100.0, 200), (101.0, 500), -300.0, "ask_same_price_addition"),
        ((100.0, 200), (101.0, 500), (100.0, 200), (101.0, 200), 300.0, "ask_same_price_removal"),
    ],
)
def test_every_level_one_transition_has_the_frozen_sign(
    bid_before: tuple[float, int],
    ask_before: tuple[float, int],
    bid_after: tuple[float, int],
    ask_after: tuple[float, int],
    expected: float,
    component: str,
) -> None:
    previous, current = _pair(bid_before, ask_before, bid_after, ask_after)

    transition = cks_l1_transition(previous, current)

    assert transition.invalid_reason is None
    assert transition.event == expected
    assert transition.components[component] == expected
    assert sum(transition.components.values()) == transition.event
    assert set(transition.components) == set(L1_COMPONENTS)


def test_bid_strengthening_and_ask_depletion_are_both_positive() -> None:
    previous, current = _pair((100.0, 200), (101.0, 500), (100.0, 500), (101.0, 200))

    transition = cks_l1_transition(previous, current)

    assert transition.event == 600.0
    assert transition.components["bid_same_price_addition"] == 300.0
    assert transition.components["ask_same_price_removal"] == 300.0


def test_ask_strengthening_and_bid_depletion_are_both_negative() -> None:
    previous, current = _pair((100.0, 500), (101.0, 200), (100.0, 200), (101.0, 500))

    transition = cks_l1_transition(previous, current)

    assert transition.event == -600.0
    assert transition.components["bid_same_price_removal"] == -300.0
    assert transition.components["ask_same_price_addition"] == -300.0


def test_unchanged_best_quote_produces_no_event() -> None:
    previous, current = _pair((100.0, 200), (101.0, 200), (100.0, 200), (101.0, 200))

    transition = cks_l1_transition(previous, current)

    assert transition.event == 0.0
    assert transition.bid_event_kind is None
    assert transition.ask_event_kind is None
    assert transition.total_depth == 400.0


def test_deeper_levels_do_not_enter_the_level_one_object() -> None:
    previous = _state(1, ((100.0, 200, 1), (99.0, 10, 1)), ((101.0, 200, 1), (102.0, 10, 1)))
    current = _state(2, ((100.0, 200, 1), (99.0, 900, 1)), ((101.0, 200, 1), (102.0, 900, 1)))

    assert cks_l1_transition(previous, current).event == 0.0


# ------------------------------------------------------------------------------------------
# Invalid and boundary transitions
# ------------------------------------------------------------------------------------------


def test_connection_epoch_boundary_is_rejected() -> None:
    previous = _state(1, ((100.0, 200, 1),), ((101.0, 200, 1),))
    current = _state(2, ((100.0, 300, 1),), ((101.0, 200, 1),), epoch=1)

    transition = cks_l1_transition(previous, current)

    assert transition.invalid_reason == "connection_epoch_boundary"
    assert transition.event == 0.0


def test_crossed_book_is_rejected() -> None:
    previous = _state(1, ((100.0, 200, 1),), ((101.0, 200, 1),))
    current = _state(2, ((102.0, 200, 1),), ((101.0, 200, 1),))

    assert cks_l1_transition(previous, current).invalid_reason == "crossed_or_missing_book"


def test_invalid_quality_flag_is_rejected() -> None:
    previous = _state(1, ((100.0, 200, 1),), ((101.0, 200, 1),))
    current = _state(2, ((100.0, 300, 1),), ((101.0, 200, 1),), flags=("sequence_gap",))

    reason = cks_l1_transition(previous, current).invalid_reason
    assert reason is not None and reason.startswith("invalid_quality")


def test_non_monotone_receive_time_is_rejected() -> None:
    previous = _state(5, ((100.0, 200, 1),), ((101.0, 200, 1),))
    current = _state(5, ((100.0, 300, 1),), ((101.0, 200, 1),))

    assert cks_l1_transition(previous, current).invalid_reason == "non_monotone_receive_time"


def test_wrong_channel_is_rejected() -> None:
    previous = _state(1, ((100.0, 200, 1),), ((101.0, 200, 1),), channel=DEPTH20)
    current = _state(2, ((100.0, 300, 1),), ((101.0, 200, 1),), channel=DEPTH20)

    assert cks_l1_transition(previous, current).invalid_reason == "not_depth200"


# ------------------------------------------------------------------------------------------
# Observation construction — windows, depth control, no lookahead
# ------------------------------------------------------------------------------------------


def _synthetic_tape(
    count: int = 2400, *, step_ns: int = 500_000_000, invalid_at: int | None = None
) -> tuple[list[BookState], list[BookState]]:
    depth200: list[BookState] = []
    depth20: list[BookState] = []
    quantity = 400
    for index in range(count):
        stamp = 10_000_000_000 + index * step_ns
        quantity = 400 + (index % 7) * 25
        drift = 0.05 * (index // 240)
        epoch = 1 if invalid_at is not None and index >= invalid_at else 0
        depth200.append(
            _state(
                stamp,
                ((100.0 + drift, quantity, 3), (99.95 + drift, 500, 4), (99.9 + drift, 500, 4)),
                ((100.05 + drift, 600, 3), (100.1 + drift, 500, 4), (100.15 + drift, 500, 4)),
                epoch=epoch,
            )
        )
        depth20.append(
            _state(
                stamp,
                ((100.0 + drift, quantity, 3),),
                ((100.05 + drift, 600, 3),),
                channel=DEPTH20,
                epoch=epoch,
            )
        )
    return depth200, depth20


def _one_tick_per_publication_tape(
    count: int = 2400, *, step_ns: int = 500_000_000
) -> tuple[list[BookState], list[BookState]]:
    """A tape whose mid advances exactly one futures tick per 0.5 s publication.

    Today's feed clock is ~0.4-0.5 s, so 0.5 s is one publication step.  Pinning the mid to
    one tick per step makes every horizon's target exactly ``2 * horizon`` ticks, which is
    what lets the sub-second horizon be checked against a value rather than against itself.
    """

    depth200: list[BookState] = []
    depth20: list[BookState] = []
    for index in range(count):
        stamp = 10_000_000_000 + index * step_ns
        drift = FUTURES_TICK_SIZE * index
        bids = ((100.0 + drift, 400, 3), (99.95 + drift, 500, 4), (99.9 + drift, 500, 4))
        asks = ((100.05 + drift, 600, 3), (100.1 + drift, 500, 4), (100.15 + drift, 500, 4))
        depth200.append(_state(stamp, bids, asks))
        depth20.append(_state(stamp, bids[:1], asks[:1], channel=DEPTH20))
    return depth200, depth20


def test_observations_carry_every_window_and_a_causal_depth_control() -> None:
    depth200, depth20 = _synthetic_tape()

    observations, failures, intensities = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    assert observations
    assert failures["invalid_transition"] == 0
    assert intensities["valid_transitions"] == len(depth200) - 1
    for observation in observations:
        for window in OFI_WINDOWS_SECONDS:
            assert ofi_feature(window) in observation.features
            assert pressure_feature(window) in observation.features
            assert comparison_feature(window) in observation.features
        assert observation.features[DEPTH_BASELINE_FEATURE] == log1p(observation.l1_depth_end)
        assert observation.l1_depth_end > 0


def test_no_window_reaches_into_the_future_or_past_its_own_length() -> None:
    depth200, depth20 = _synthetic_tape()

    observations, _, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    assert_no_lookahead(observations)
    for observation in observations:
        for window, start in observation.window_start_ts_ns.items():
            assert start <= observation.receive_ts_ns
            assert observation.receive_ts_ns - start <= int(window * NANOSECONDS_PER_SECOND)


def test_incomplete_history_before_the_longest_window_is_refused() -> None:
    depth200, depth20 = _synthetic_tape(count=15)

    observations, failures, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    assert observations == []
    assert failures["incomplete_ofi_history"] > 0


def test_reconnect_boundary_breaks_window_completeness() -> None:
    depth200, depth20 = _synthetic_tape(invalid_at=1200)

    _, failures, intensities = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    assert failures["invalid_transition"] == 1
    assert intensities["valid_transitions"] == len(depth200) - 2


def test_ofi_window_sum_equals_the_sum_of_its_own_transitions() -> None:
    depth200, depth20 = _synthetic_tape()
    observations, _, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )
    events = {
        current.receive_ts_ns: cks_l1_transition(previous, current).event
        for previous, current in zip(depth200[:-1], depth200[1:], strict=True)
    }

    observation = observations[len(observations) // 2]
    for window in OFI_WINDOWS_SECONDS:
        start = observation.receive_ts_ns - int(window * NANOSECONDS_PER_SECOND)
        expected = sum(
            value for stamp, value in events.items() if start < stamp <= observation.receive_ts_ns
        )
        assert isclose(observation.features[ofi_feature(window)], expected, abs_tol=1e-9)


def test_depth_scaling_divides_by_the_causal_average_depth() -> None:
    depth200, depth20 = _synthetic_tape()
    observations, _, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    observation = observations[len(observations) // 2]
    for window in OFI_WINDOWS_SECONDS:
        denominator = max(observation.mean_depth_by_window[window], MINIMUM_MEAN_DEPTH_CONTRACTS)
        assert isclose(
            observation.features[pressure_feature(window)],
            observation.features[ofi_feature(window)] / denominator,
            rel_tol=1e-12,
        )


# ------------------------------------------------------------------------------------------
# Split, embargo, grid completeness and determinism
# ------------------------------------------------------------------------------------------


def _artifact() -> dict[str, object]:
    tapes = []
    for index in range(2):
        depth200, depth20 = _synthetic_tape()
        depth200 = [
            _state(
                state.receive_ts_ns + index * 2_000_000_000_000,
                state.bids,
                state.asks,
                epoch=state.connection_epoch,
            )
            for state in depth200
        ]
        depth20 = [
            _state(
                state.receive_ts_ns + index * 2_000_000_000_000,
                state.bids,
                state.asks,
                channel=DEPTH20,
                epoch=state.connection_epoch,
            )
            for state in depth20
        ]
        observations, failures, intensities = build_cks_l1_observations(
            depth200_states=depth200,
            depth20_states=depth20,
            tape_index=index,
            run_id=f"run-{index}",
        )
        tapes.append(
            CksL1TapeInput(
                tape_index=index,
                run_id=f"run-{index}",
                instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
                tape_sha256="0" * 64,
                observations=tuple(observations),
                depth200_publications=len(depth200),
                depth20_publications=len(depth20),
                observed_seconds=90.0,
                failures=failures,
                intensities=intensities,
                trades=None,
            )
        )
    return build_cks_l1_artifact(tapes, code_commit="test", replicates=25, seed=7)


def test_the_grid_emits_every_one_of_the_thirty_cells() -> None:
    artifact = _artifact()

    grid = artifact["grid"]
    assert isinstance(grid, list)
    assert len(grid) == len(OFI_WINDOWS_SECONDS) * len(CKS_RETURN_HORIZONS_SECONDS)
    seen = {(row["ofi_window_seconds"], row["return_horizon_seconds"]) for row in grid}
    assert seen == {
        (window, horizon)
        for window in OFI_WINDOWS_SECONDS
        for horizon in CKS_RETURN_HORIZONS_SECONDS
    }
    for row in grid:
        assert set(row["models"]) == {"M1", "M2", "M3", "M4", "M4b", "R1", "C1"}
        assert set(row["past_mirror_models"]) == set(row["models"])


def test_the_half_second_horizon_is_measured_at_exactly_half_a_second() -> None:
    depth200, depth20 = _one_tick_per_publication_tape()

    observations, _, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    assert observations
    observation = observations[len(observations) // 2]
    # The mid advances one tick per 0.5 s publication, so an h-second horizon must move
    # exactly 2h ticks.  A truncating cast (``int(horizon) * NANOSECONDS_PER_SECOND``)
    # would collapse 0.5 s to a zero-length interval and drop the horizon entirely.
    assert 0.5 in observation.future_ticks
    assert 0.5 in observation.past_ticks
    assert isclose(observation.future_ticks[0.5], 1.0, abs_tol=1e-6)
    assert isclose(observation.past_ticks[0.5], 1.0, abs_tol=1e-6)
    for horizon in CKS_RETURN_HORIZONS_SECONDS:
        assert isclose(observation.future_ticks[horizon], 2.0 * horizon, abs_tol=1e-6)
        assert isclose(observation.past_ticks[horizon], 2.0 * horizon, abs_tol=1e-6)
    # 0.5 s must be its own measurement, not an alias of the 1 s target.
    assert not isclose(observation.future_ticks[0.5], observation.future_ticks[1], abs_tol=1e-6)


def test_every_half_second_cell_is_fitted_and_bootstrapped_like_the_others() -> None:
    artifact = _artifact()
    grid = artifact["grid"]
    assert isinstance(grid, list)

    rows = [row for row in grid if row["return_horizon_seconds"] == 0.5]

    assert len(rows) == len(OFI_WINDOWS_SECONDS)
    for row in rows:
        assert row["train_n"] > 0
        assert row["test_n"] > 0
        assert set(row["models"]) == set(CELL_MODELS)
        for payload in (row["ofi_over_depth_inference"], row["pressure_over_depth_inference"]):
            # Reaching here at all proves the bootstrap seed stayed an int: the block
            # bootstrap seeds a NumPy generator, which rejects a float seed outright.
            assert payload["n"] == row["test_n"]
            assert payload["naive_inference_valid"] is False
            assert "block_bootstrap_t" in payload


def test_the_split_embargoes_the_boundary_and_keeps_training_strictly_earlier() -> None:
    depth200, depth20 = _synthetic_tape()
    observations, _, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )
    from shaurya.signals.cks_l1_ofi import as_normal_observation

    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations],
        embargo_seconds=120.0,
    )

    assert split.embargo_seconds == 120.0
    assert not set(split.train) & set(split.test)
    if split.train and split.test:
        latest_train = max(observations[position].receive_ts_ns for position in split.train)
        earliest_test = min(observations[position].receive_ts_ns for position in split.test)
        assert earliest_test - latest_train > 120.0 * NANOSECONDS_PER_SECOND


def test_the_artifact_is_deterministic_for_the_same_inputs() -> None:
    import json

    first = json.dumps(_artifact(), sort_keys=True)
    second = json.dumps(_artifact(), sort_keys=True)

    assert first == second


def test_the_artifact_refuses_a_confirmatory_reading() -> None:
    artifact = _artifact()

    protocol = artifact["protocol"]
    assert isinstance(protocol, dict)
    assert protocol["confirmatory_eligible"] is False
    assert protocol["part_of_h_sig21"] is False
    assert protocol["compared_against_scan_id"] == "X-OFI-DAT20-03"


def test_grid_refuses_a_sample_too_small_to_fit() -> None:
    depth200, depth20 = _synthetic_tape(count=800)
    observations, _, _ = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )
    from shaurya.signals.cks_l1_ofi import as_normal_observation

    split = chronological_embargoed_split(
        [as_normal_observation(observation) for observation in observations[:40]],
        embargo_seconds=120.0,
    )
    with pytest.raises(ValueError, match="insufficient observations"):
        evaluate_grid(observations[:40], split, replicates=5, seed=1)


# ------------------------------------------------------------------------------------------
# Identification discipline
# ------------------------------------------------------------------------------------------


def test_component_table_labels_removals_as_displayed_not_cancellations() -> None:
    depth200, depth20 = _synthetic_tape()
    _, _, intensities = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )

    table = component_intensity_table(intensities, trades=None)

    assert table["components"]["bid_same_price_removal"]["identification"] == (
        "displayed_removal_not_cancellation"
    )
    assert table["components"]["ask_same_price_addition"]["identification"] == (
        "displayed_addition_not_gross_arrival"
    )
    assert "gross_cancellation_intensity" in table["unidentified_quantities"]
    assert "gross_limit_order_arrival_intensity" in table["unidentified_quantities"]


def test_trade_totals_split_identified_executed_volume_by_side() -> None:
    rows = [
        {"event_type": "full", "cumulative_volume_increment": 100, "trade_side": "buy"},
        {"event_type": "full", "cumulative_volume_increment": 50, "trade_side": "sell"},
        {
            "event_type": "full",
            "cumulative_volume_increment": 25,
            "trade_side": "unclassified",
            "trade_classification_degraded": True,
        },
        {"event_type": "full", "cumulative_volume_increment": None, "trade_side": None},
        {"event_type": "depth200", "cumulative_volume_increment": 999, "trade_side": "buy"},
    ]

    totals = build_trade_totals(rows)

    assert totals.packets == 3
    assert totals.executed_contracts == 175.0
    assert totals.buy_contracts == 100.0
    assert totals.sell_contracts == 50.0
    assert totals.unclassified_contracts == 25.0
    assert totals.degraded_packets == 1


def test_execution_share_is_reported_as_an_upper_bound() -> None:
    depth200, depth20 = _synthetic_tape()
    _, _, intensities = build_cks_l1_observations(
        depth200_states=depth200, depth20_states=depth20, tape_index=0, run_id="run"
    )
    totals = build_trade_totals(
        [{"event_type": "full", "cumulative_volume_increment": 10, "trade_side": "buy"}]
    )

    attribution = component_intensity_table(intensities, trades=totals)["execution_attribution"]

    assert attribution is not None
    assert attribution["executed_share_of_displayed_removal_upper_bound"] <= 1.0
    assert "upper bound" in attribution["limits"]
    assert attribution["residual_unattributed_displayed_removal_contracts"] >= 0.0
