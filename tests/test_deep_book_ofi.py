from __future__ import annotations

from math import isclose

from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState
from shaurya.signals.deep_book_normal_activity import chronological_embargoed_split
from shaurya.signals.deep_book_ofi import (
    DEPTH_CUTOFFS,
    OFI_WINDOWS_SECONDS,
    RETURN_HORIZONS_SECONDS,
    OFIObservation,
    build_ofi_observations,
    evaluate_grid,
    ofi_feature,
    price_keyed_ofi_transition,
)


def _state(
    stamp: int,
    bids: tuple[tuple[float, int, int], ...],
    asks: tuple[tuple[float, int, int], ...],
    *,
    channel: str = DEPTH200,
    epoch: int = 0,
) -> BookState:
    return BookState(
        channel=channel,
        receive_ts_ns=stamp,
        receive_sequence=stamp,
        connection_epoch=epoch,
        bids=bids,
        asks=asks,
        rows_in_burst=1,
        quality_flags=(),
    )


def test_price_keyed_ofi_has_the_fixed_buy_pressure_sign() -> None:
    previous = _state(
        1,
        ((100.0, 10, 1), (99.0, 20, 1), (98.0, 30, 1)),
        ((101.0, 11, 1), (102.0, 21, 1), (103.0, 31, 1)),
    )
    current = _state(
        2,
        ((100.0, 15, 1), (99.0, 18, 1), (98.0, 30, 1)),
        ((101.0, 8, 1), (102.0, 25, 1), (103.0, 31, 1)),
    )

    transition = price_keyed_ofi_transition(previous, current)

    assert transition.invalid_reason is None
    # Best bid +5 and best ask depletion 3 are both buy pressure.
    assert transition.cumulative_by_depth[1] == 8.0
    # Across the available ladder: bid net +3, ask net +1, hence OFI +2.
    assert transition.cumulative_by_depth[5] == 2.0


def test_outer_window_slide_is_excluded_instead_of_called_flow() -> None:
    bid_prices = tuple(round(100.0 - 0.05 * index, 2) for index in range(201))
    ask_prices = tuple(round(101.0 + 0.05 * index, 2) for index in range(201))
    previous = _state(
        1,
        tuple((price, 10, 1) for price in bid_prices[:200]),
        tuple((price, 10, 1) for price in ask_prices[:200]),
    )
    current = _state(
        2,
        tuple((price, 10, 1) for price in (*bid_prices[:199], bid_prices[200])),
        tuple((price, 10, 1) for price in (*ask_prices[:199], ask_prices[200])),
    )

    transition = price_keyed_ofi_transition(previous, current)

    assert transition.invalid_reason is None
    assert transition.boundary_excluded_quantity == 40.0
    assert all(value == 0.0 for value in transition.cumulative_by_depth.values())


def test_connection_epoch_boundary_refuses_the_transition() -> None:
    previous = _state(1, ((100.0, 10, 1),), ((101.0, 10, 1),), epoch=0)
    current = _state(2, ((100.0, 12, 1),), ((101.0, 10, 1),), epoch=1)

    transition = price_keyed_ofi_transition(previous, current)

    assert transition.invalid_reason == "connection_epoch_boundary"
    assert all(value == 0.0 for value in transition.cumulative_by_depth.values())


def test_observation_builder_aligns_n_states_to_n_minus_one_transitions() -> None:
    depth200 = []
    depth20 = []
    for index in range(51):
        stamp = index * 1_000_000_000
        mid = 100.0 + index * 0.01
        depth200.append(
            _state(
                stamp,
                ((round(mid - 0.05, 2), 10 + index, 1),),
                ((round(mid + 0.05, 2), 12, 1),),
            )
        )
        depth20.append(
            _state(
                stamp,
                ((round(mid - 0.05, 2), 10 + index, 1),),
                ((round(mid + 0.05, 2), 12, 1),),
                channel=DEPTH20,
            )
        )

    observations, failures = build_ofi_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        tape_index=0,
        run_id="alignment",
    )

    assert observations
    assert failures["invalid_transition"] == 0
    assert all(
        set(RETURN_HORIZONS_SECONDS) >= set(observation.future_ticks)
        for observation in observations
    )


def test_complete_grid_is_emitted_without_ranking_away_null_cells() -> None:
    observations: list[OFIObservation] = []
    for tape in (0, 1):
        for index in range(700):
            stamp = (tape * 10_000 + index) * 1_000_000_000
            features = {
                "spread_ticks": 1.0 + (index % 3) * 0.1,
                "microprice_tilt_ticks": ((index % 7) - 3) / 10.0,
            }
            signal = float((index % 11) - 5)
            for window in OFI_WINDOWS_SECONDS:
                for depth in DEPTH_CUTOFFS:
                    features[ofi_feature(window, depth)] = signal * depth / 200.0
                    previous = 0
                    previous_value = 0.0
                    for cutoff in DEPTH_CUTOFFS:
                        if cutoff > depth:
                            break
                        window_label = str(window).replace(".", "p").rstrip("0").rstrip("p")
                        name = f"ofi_w{window_label}__band_{previous + 1}_{cutoff}"
                        cumulative = signal * cutoff / 200.0
                        features[name] = cumulative - previous_value
                        previous = cutoff
                        previous_value = cumulative
            future = {
                horizon: 0.2 * signal + (index % 5) * 0.01 for horizon in RETURN_HORIZONS_SECONDS
            }
            past = {
                horizon: -0.1 * signal + (index % 4) * 0.01 for horizon in RETURN_HORIZONS_SECONDS
            }
            observations.append(
                OFIObservation(
                    tape_index=tape,
                    run_id=f"tape-{tape}",
                    receive_ts_ns=stamp,
                    time_bucket="test",
                    features=features,
                    future_ticks=future,
                    past_ticks=past,
                    contemporaneous_ticks={},
                    same_window_ticks={window: signal for window in OFI_WINDOWS_SECONDS},
                    boundary_excluded_quantity={window: 0.0 for window in OFI_WINDOWS_SECONDS},
                )
            )
    split = chronological_embargoed_split(observations, embargo_seconds=120.0)

    rows = evaluate_grid(observations, split, replicates=5, seed=7)

    assert len(rows) == 175
    assert {row["depth_levels"] for row in rows} == set(DEPTH_CUTOFFS)
    assert {row["ofi_window_seconds"] for row in rows} == set(OFI_WINDOWS_SECONDS)
    assert {row["return_horizon_seconds"] for row in rows} == set(RETURN_HORIZONS_SECONDS)
    assert all(isclose(row["causal_gap_seconds"], 0.5) for row in rows)
