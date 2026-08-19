"""Tests for the ordinary deep-book activity scan `X-DEEPBOOK-DAT20-02`.

Three groups: the protocol refusals that keep this scan non-confirmatory, the deterministic
feature and target construction, and the estimation machinery — including regression tests for
the three defects found while running it, each of which produced a diagnostic that could not have
fired whatever the data said.
"""

from __future__ import annotations

import numpy as np
import pytest

from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState
from shaurya.signals.deep_book_normal_activity import (
    CONFIRMATORY_ELIGIBLE,
    DISTANCE_REGIONS,
    EXPLORATORY_SCAN_ID,
    HORIZONS_SECONDS,
    LEVEL_REGIONS,
    NESTED_LADDER,
    PERMITTED_TAPE_SHA256,
    RIDGE_PENALTIES,
    ConfirmatoryUseRefused,
    IncompleteTableRefused,
    Observation,
    TapeInput,
    TapeNotPermitted,
    assert_complete_table,
    assert_exploratory_claim,
    assert_permitted_tape,
    association_table,
    book_state_features,
    build_depth20_mid_series,
    build_flow_features,
    build_normal_activity_artifact,
    build_observations,
    chronological_embargoed_split,
    feature_region,
    features_for_regions,
    fit_ridge,
    fit_ridge_path,
    nested_region_comparison,
    permute_side_labels,
    required_blocks_for_target,
    response_ticks,
    shuffle_times_within_bucket,
)

SECOND = 1_000_000_000
# 2026-08-19T07:39:35Z == 13:09:35 IST, matching the real tapes' 13:00 bucket.
START_NS = 1_787_125_175_000_000_000
PERMITTED_SHA = sorted(PERMITTED_TAPE_SHA256)[0]


def depth200_state(
    ts_ns: int,
    *,
    best_bid: float = 100.0,
    best_ask: float = 100.1,
    levels: int = 200,
    bid_quantity: int = 10,
    ask_quantity: int = 10,
    bid_orders: int = 2,
    ask_orders: int = 2,
    step: float = 0.5,
) -> BookState:
    bids = tuple(
        (best_bid - index * step, bid_quantity + index, bid_orders) for index in range(levels)
    )
    asks = tuple(
        (best_ask + index * step, ask_quantity + index, ask_orders) for index in range(levels)
    )
    return BookState(
        channel=DEPTH200,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=1,
        bids=bids,
        asks=asks,
        rows_in_burst=1,
        quality_flags=(),
    )


def depth20_state(ts_ns: int, midpoint: float) -> BookState:
    return BookState(
        channel=DEPTH20,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=1,
        bids=((midpoint - 0.025, 100, 2),),
        asks=((midpoint + 0.025, 100, 2),),
        rows_in_burst=1,
        quality_flags=(),
    )


def mid_path(count: int, *, drift: float = 0.0, start: float = 100.0) -> list[BookState]:
    """A depth20 path published every 100 ms."""

    return [
        depth20_state(START_NS + index * SECOND // 10, start + index * drift)
        for index in range(count)
    ]


# ----------------------------------------------------------------------------------------------
# Protocol refusals
# ----------------------------------------------------------------------------------------------


def test_the_scan_declares_itself_permanently_non_confirmatory() -> None:
    assert EXPLORATORY_SCAN_ID == "X-DEEPBOOK-DAT20-02"
    assert CONFIRMATORY_ELIGIBLE is False


@pytest.mark.parametrize(
    "claim",
    [
        "deep book is predictive",
        "confirmed deep-book effect",
        "tradable signal",
        "promote to strategy",
        "falsified",
        "economic edge",
        "SIG-21 verdict",
    ],
)
def test_a_confirmatory_or_economic_framing_is_refused(claim: str) -> None:
    with pytest.raises(ConfirmatoryUseRefused):
        assert_exploratory_claim([claim])


@pytest.mark.parametrize(
    "claim",
    ["ordinary book activity description", "unconfirmed pattern", "falsifiable proposal"],
)
def test_an_honest_exploratory_framing_is_allowed(claim: str) -> None:
    assert_exploratory_claim([claim])


def test_a_tape_outside_the_two_pinned_captures_is_refused() -> None:
    with pytest.raises(TapeNotPermitted) as error:
        assert_permitted_tape(run_id="post-registration-calibration", tape_sha256="00" * 32)
    assert "H-SIG21 §1.5" in str(error.value)


def test_the_two_pre_registration_captures_are_permitted() -> None:
    for sha in PERMITTED_TAPE_SHA256:
        assert_permitted_tape(run_id="dat20", tape_sha256=sha)


def test_a_filtered_table_is_refused() -> None:
    with pytest.raises(IncompleteTableRefused):
        assert_complete_table(emitted=3, expected=10, name="association table")


def test_the_scan_states_it_is_not_part_of_h_sig21() -> None:
    artifact = build_normal_activity_artifact([], code_commit=None)
    assert artifact["protocol"]["is_part_of_h_sig21"] is False
    assert artifact["protocol"]["confirmatory_eligible"] is False
    assert "384-cell registration is untouched" in artifact["protocol"]["relationship_to_h_sig21"]


# ----------------------------------------------------------------------------------------------
# Ordinary book state
# ----------------------------------------------------------------------------------------------


def test_region_totals_count_quantity_and_orders_over_the_right_levels() -> None:
    features = book_state_features(depth200_state(START_NS))
    assert features is not None
    # Level quantities are 10, 11, 12, ... so the first five sum to 60 and the first level to 10.
    assert features["best__bid_quantity"] == 10.0
    assert features["l1_5__bid_quantity"] == 10 + 11 + 12 + 13 + 14
    assert features["l1_20__bid_order_count"] == 20 * 2
    assert features["l21_50__bid_occupied_levels"] == 30.0
    assert features["l51_200__bid_occupied_levels"] == 150.0


def test_average_order_size_is_quantity_over_order_count() -> None:
    features = book_state_features(depth200_state(START_NS, bid_quantity=100, bid_orders=4))
    assert features is not None
    assert features["best__bid_average_order_size_proxy"] == pytest.approx(100 / 4)


def test_a_perfectly_symmetric_book_has_zero_imbalance_everywhere() -> None:
    features = book_state_features(depth200_state(START_NS))
    assert features is not None
    for region, *_ in LEVEL_REGIONS:
        assert features[f"{region}__quantity_imbalance"] == pytest.approx(0.0)
        assert features[f"{region}__order_count_imbalance"] == pytest.approx(0.0)


def test_a_bid_heavy_book_has_positive_quantity_imbalance() -> None:
    features = book_state_features(depth200_state(START_NS, bid_quantity=100, ask_quantity=10))
    assert features is not None
    assert features["best__quantity_imbalance"] > 0.0
    assert features["l51_200__quantity_imbalance"] > 0.0


def test_distance_regions_are_not_the_same_partition_as_level_regions() -> None:
    """Rs 0.50 between levels puts the first ten levels inside Rs 5, not the first twenty."""

    features = book_state_features(depth200_state(START_NS, step=0.5))
    assert features is not None
    assert features["d_le5__bid_occupied_levels"] == 10.0
    assert features["l1_20__bid_occupied_levels"] == 20.0
    assert {region for region, *_ in DISTANCE_REGIONS} == {"d_le5", "d_5_20", "d_20_50", "d_gt50"}


def test_size_build_slope_is_positive_when_the_book_deepens_with_distance() -> None:
    features = book_state_features(depth200_state(START_NS))
    assert features is not None
    # Quantity rises by 1 per level and each level is Rs 0.50 further out, so the slope is 2.
    assert features["l51_200__bid_size_build_slope"] == pytest.approx(2.0)


def test_an_unusable_book_state_produces_no_features_rather_than_imputed_ones() -> None:
    empty = BookState(DEPTH200, START_NS, 1, 1, (), (), 1, ())
    crossed = BookState(
        DEPTH200, START_NS, 1, 1, ((100.5, 10, 1),), ((100.0, 10, 1),), 1, ()
    )
    assert book_state_features(empty) is None
    assert book_state_features(crossed) is None


def test_book_shape_is_computed_per_region_so_the_nested_ladder_cannot_leak() -> None:
    """A whole-book shape number would consume levels 51-200 inside the best-quote-only rung."""

    features = book_state_features(depth200_state(START_NS))
    assert features is not None
    names = sorted(features)
    best_only = features_for_regions(names, ["best"])
    assert any("size_build_slope" in name for name in best_only)
    assert not any(name.startswith("l51_200__") for name in best_only)
    assert not any(name.startswith("l21_50__") for name in best_only)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("best__spread_rupees", "best"),
        ("l21_50__bid_quantity", "l21_50"),
        ("flow_1s__l51_200__quantity_imbalance", "l51_200"),
        ("flow_5s__d_gt50__bid_order_count", "d_gt50"),
        ("flow_tick__available", None),
        ("midpoint", None),
    ],
)
def test_every_feature_is_attributed_to_exactly_one_region(name: str, expected: str | None) -> None:
    assert feature_region(name) == expected


def test_the_deepest_rung_is_a_strict_superset_of_the_shallowest() -> None:
    features = book_state_features(depth200_state(START_NS))
    assert features is not None
    names = sorted(features)
    rungs = [set(features_for_regions(names, regions)) for _, regions in NESTED_LADDER]
    for shallower, deeper in zip(rungs, rungs[1:], strict=False):
        assert shallower < deeper


# ----------------------------------------------------------------------------------------------
# Flow
# ----------------------------------------------------------------------------------------------


def test_flow_measures_the_change_since_the_previous_publication() -> None:
    states = [
        depth200_state(START_NS, bid_quantity=10),
        depth200_state(START_NS + SECOND, bid_quantity=30),
    ]
    levels = [book_state_features(state) for state in states]
    assert levels[0] is not None and levels[1] is not None
    flows = build_flow_features(states, [levels[0], levels[1]])
    assert flows[0]["flow_tick__available"] == 0.0
    assert flows[0]["flow_tick__best__bid_quantity"] == 0.0
    assert flows[1]["flow_tick__available"] == 1.0
    assert flows[1]["flow_tick__best__bid_quantity"] == pytest.approx(20.0)


def test_an_unavailable_lookback_is_flagged_and_not_reported_as_a_measured_zero() -> None:
    states = [depth200_state(START_NS), depth200_state(START_NS + SECOND // 2)]
    levels = [book_state_features(state) for state in states]
    assert levels[0] is not None and levels[1] is not None
    flows = build_flow_features(states, [levels[0], levels[1]])
    # The second publication is only 0.5 s in, so the 5 s look-back has no earlier reference.
    assert flows[1]["flow_5s__available"] == 0.0
    assert flows[1]["flow_5s__best__bid_quantity"] == 0.0


def test_the_lookback_resolves_as_of_and_never_interpolates_forward() -> None:
    states = [
        depth200_state(START_NS + index * SECOND, bid_quantity=10 * index)
        for index in range(8)
    ]
    levels = []
    for state in states:
        computed = book_state_features(state)
        assert computed is not None
        levels.append(computed)
    flows = build_flow_features(states, levels)
    # At t = 6 s the 5 s look-back resolves to t = 1 s: quantities 60 and 10 respectively.
    assert flows[6]["flow_5s__best__bid_quantity"] == pytest.approx(50.0)


# ----------------------------------------------------------------------------------------------
# Target
# ----------------------------------------------------------------------------------------------


def test_the_future_response_is_measured_in_ticks_from_the_as_of_midpoint() -> None:
    series = build_depth20_mid_series(mid_path(200, drift=0.05))
    future, _, _ = response_ticks(series, anchor_ts_ns=START_NS + 2 * SECOND)
    # 0.05 rupees per 100 ms is 0.5 rupees per second, which is 10 ticks per second.
    assert future[1] == pytest.approx(10.0)
    assert future[5] == pytest.approx(50.0)


def test_an_endpoint_past_the_end_of_coverage_is_refused_rather_than_resolved_backwards() -> None:
    """The right-edge defect found on these exact tapes: no guard fabricates a zero response."""

    series = build_depth20_mid_series(mid_path(30, drift=0.05))
    covered_end = series.coverage_end_ts_ns
    assert covered_end is not None
    future, _, _ = response_ticks(series, anchor_ts_ns=covered_end - SECOND // 2)
    assert 1 not in future
    assert 60 not in future
    assert series.as_of(covered_end + SECOND) is None


def test_the_past_mirror_covers_the_same_span_backwards() -> None:
    series = build_depth20_mid_series(mid_path(300, drift=0.05))
    anchor = START_NS + 15 * SECOND
    future, past, _ = response_ticks(series, anchor_ts_ns=anchor)
    assert past[5] == pytest.approx(future[5])


def test_the_contemporaneous_leg_is_not_forced_to_zero_by_construction() -> None:
    """Regression test for a diagnostic that could not have fired whatever the data said.

    The first version resolved both ends of the contemporaneous leg to the same publication and
    reported exactly 0.0 for every observation. It now spans the depth20 interval that straddles
    the depth200 publication, which is a real quantity.
    """

    series = build_depth20_mid_series(mid_path(200, drift=0.05))
    # A depth200 publication landing between two depth20 ticks.
    anchor = START_NS + 2 * SECOND + SECOND // 20
    _, _, contemporaneous = response_ticks(series, anchor_ts_ns=anchor)
    assert contemporaneous[1] != 0.0
    assert contemporaneous[1] == pytest.approx(1.0)


def test_every_horizon_shares_one_contemporaneous_value() -> None:
    series = build_depth20_mid_series(mid_path(200, drift=0.05))
    anchor = START_NS + 3 * SECOND + SECOND // 20
    _, _, contemporaneous = response_ticks(series, anchor_ts_ns=anchor)
    assert len(set(contemporaneous.values())) == 1


# ----------------------------------------------------------------------------------------------
# Observations end to end
# ----------------------------------------------------------------------------------------------


def build_fixture_observations(count: int = 200, *, drift: float = 0.02) -> list[Observation]:
    """A varying, side-asymmetric synthetic book.

    Both properties matter. A constant book gives every feature zero variance, so nothing can be
    fitted; a side-symmetric book is unchanged by the side-label mirror, so that control cannot
    be exercised. Quantities are driven by a deterministic sequence rather than a random one so
    the fixture is reproducible.
    """

    depth200 = [
        depth200_state(
            START_NS + 10 * SECOND + index * SECOND,
            bid_quantity=10 + (index * 7) % 23,
            ask_quantity=10 + (index * 11) % 17,
            bid_orders=2 + index % 3,
            ask_orders=2 + (index * 5) % 4,
        )
        for index in range(count)
    ]
    depth20 = mid_path(count * 10 + 1200, drift=drift)
    observations, _ = build_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        tape_index=0,
        run_id="fixture",
    )
    return observations


def test_observations_carry_features_and_every_covered_horizon() -> None:
    observations = build_fixture_observations()
    assert observations
    first = observations[0]
    assert first.time_bucket.startswith("13:")
    assert set(first.future_ticks) <= set(HORIZONS_SECONDS)
    assert "l51_200__quantity_imbalance" in first.features
    assert "flow_5s__l51_200__quantity_imbalance" in first.features


def test_every_drop_reason_is_counted_rather_than_silently_dropped() -> None:
    depth200 = [
        BookState(DEPTH200, START_NS + 10 * SECOND, 1, 1, (), (), 1, ()),
        depth200_state(START_NS + 11 * SECOND),
    ]
    _, failures = build_observations(
        depth200_states=depth200,
        depth20_states=mid_path(2000, drift=0.01),
        tape_index=0,
        run_id="fixture",
    )
    assert failures["unusable_depth200_state"] == 1
    assert set(failures) == {
        "unusable_depth200_state",
        "no_depth20_anchor",
        "no_future_horizon_covered",
    }


# ----------------------------------------------------------------------------------------------
# Split, fits, and the central comparison
# ----------------------------------------------------------------------------------------------


def test_the_split_is_chronological_and_the_embargo_band_is_discarded_from_both_sides() -> None:
    observations = build_fixture_observations(900)
    split = chronological_embargoed_split(observations)
    assert split.train and split.test and split.embargoed
    latest_train = max(observations[position].receive_ts_ns for position in split.train)
    earliest_test = min(observations[position].receive_ts_ns for position in split.test)
    assert earliest_test - latest_train > split.embargo_seconds * SECOND
    assert not set(split.train) & set(split.test)
    assert not set(split.train) & set(split.embargoed)


def test_the_embargo_must_exceed_the_longest_target_horizon() -> None:
    observations = build_fixture_observations(200)
    with pytest.raises(ValueError, match="longest target horizon"):
        chronological_embargoed_split(observations, embargo_seconds=10.0)


def test_the_split_keeps_both_tapes_on_both_sides() -> None:
    first = build_fixture_observations(900)
    second = [
        Observation(
            tape_index=1,
            run_id="second",
            receive_ts_ns=observation.receive_ts_ns + 10_000 * SECOND,
            time_bucket=observation.time_bucket,
            features=observation.features,
            future_ticks=observation.future_ticks,
            past_ticks=observation.past_ticks,
            contemporaneous_ticks=observation.contemporaneous_ticks,
        )
        for observation in first
    ]
    pooled = [*first, *second]
    split = chronological_embargoed_split(pooled)
    assert {pooled[position].tape_index for position in split.train} == {0, 1}
    assert {pooled[position].tape_index for position in split.test} == {0, 1}


def test_ridge_shrinks_toward_the_training_mean_as_the_penalty_grows() -> None:
    generator = np.random.default_rng(11)
    design = generator.normal(size=(400, 5))
    target = design[:, 0] * 2.0 + generator.normal(size=400) * 0.1
    names = [f"f{index}" for index in range(5)]
    light = fit_ridge(design, target, feature_names=names, penalty=0.0)
    heavy = fit_ridge(design, target, feature_names=names, penalty=1e6)
    assert abs(light.coefficients[0]) > abs(heavy.coefficients[0])
    assert float(np.abs(heavy.coefficients).max()) < 1e-2
    assert heavy.intercept == pytest.approx(float(target.mean()))


def test_the_ridge_path_agrees_with_fitting_each_penalty_separately() -> None:
    generator = np.random.default_rng(3)
    design = generator.normal(size=(200, 8))
    target = generator.normal(size=200)
    names = [f"f{index}" for index in range(8)]
    path = fit_ridge_path(design, target, feature_names=names, penalties=RIDGE_PENALTIES)
    for penalty in RIDGE_PENALTIES:
        separate = fit_ridge(design, target, feature_names=names, penalty=penalty)
        assert np.allclose(path[penalty].coefficients, separate.coefficients, atol=1e-9)


def test_a_constant_training_column_is_neutralised_rather_than_dividing_by_zero() -> None:
    design = np.column_stack(
        [np.ones(100), np.linspace(0.0, 1.0, 100)]
    )
    target = np.linspace(0.0, 2.0, 100)
    fit = fit_ridge(design, target, feature_names=["constant", "ramp"], penalty=1.0)
    assert np.isfinite(fit.coefficients).all()
    assert fit.scale[0] == 1.0


def test_the_nested_ladder_reports_every_rung_and_every_step() -> None:
    observations = build_fixture_observations(500)
    split = chronological_embargoed_split(observations)
    result = nested_region_comparison(observations, split, horizon=1, replicates=19)
    assert [row["rung"] for row in result["rungs"]] == [rung for rung, _ in NESTED_LADDER]
    assert len(result["steps"]) == len(NESTED_LADDER) - 1
    assert result["steps"][-1]["adds_region"] == "l51_200"
    for step in result["steps"]:
        assert step["naive_inference_valid"] is False
        assert "newey_west_t" in step
        assert "block_bootstrap_t" in step
        assert "non_overlapping_t" in step


def test_an_underpowered_split_reports_insufficient_rather_than_a_number() -> None:
    observations = build_fixture_observations(60)
    split = chronological_embargoed_split(observations)
    result = nested_region_comparison(observations, split, horizon=60, replicates=9)
    assert result["data_sufficient"] is False
    assert all(row["out_of_sample_r2_vs_training_mean"] is None for row in result["rungs"])


def test_a_step_needs_all_three_dependence_aware_estimators_to_agree() -> None:
    observations = build_fixture_observations(500)
    split = chronological_embargoed_split(observations)
    result = nested_region_comparison(observations, split, horizon=1, replicates=19)
    for step in result["steps"]:
        if step["distinguishable_from_zero"]:
            statistics = [
                step["newey_west_t"],
                step["block_bootstrap_t"],
                step["non_overlapping_t"],
            ]
            assert all(value is not None and abs(value) > 1.96 for value in statistics)
            assert len({value > 0 for value in statistics}) == 1


# ----------------------------------------------------------------------------------------------
# Negative controls
# ----------------------------------------------------------------------------------------------


def test_the_time_shuffle_keeps_the_book_and_the_response_pool_but_breaks_the_pairing() -> None:
    observations = build_fixture_observations(300)
    shuffled = shuffle_times_within_bucket(observations, seed=7)
    assert len(shuffled) == len(observations)
    assert [row.features for row in shuffled] == [row.features for row in observations]
    original = sorted(row.future_ticks.get(1, 0.0) for row in observations)
    permuted = sorted(row.future_ticks.get(1, 0.0) for row in shuffled)
    assert original == permuted
    assert any(
        row.future_ticks.get(1) != other.future_ticks.get(1)
        for row, other in zip(shuffled, observations, strict=True)
    )


def test_the_side_label_control_mirrors_a_subset_not_the_whole_sample() -> None:
    observations = build_fixture_observations(300)
    mirrored = permute_side_labels(observations, seed=5)
    changed = sum(
        1
        for before, after in zip(observations, mirrored, strict=True)
        if before.features != after.features
    )
    assert 0 < changed < len(observations)


def test_side_label_control_is_not_a_symmetry_the_model_can_relearn() -> None:
    """Regression test for a null manufactured by arithmetic.

    Mirroring *every* observation is an exact symmetry of a refit linear model: negating a column
    flips its coefficient and swapping two columns swaps two coefficients, so the predictions come
    out identical and the control reproduces the real result whatever the data says. Mirroring a
    subset is not a symmetry, and the fit must actually lose the side information.
    """

    observations = build_fixture_observations(500)
    split = chronological_embargoed_split(observations)
    real = nested_region_comparison(observations, split, horizon=1, replicates=19)
    mirrored = permute_side_labels(observations, seed=5)
    control = nested_region_comparison(
        mirrored, chronological_embargoed_split(mirrored), horizon=1, replicates=19
    )
    real_r2 = [row["out_of_sample_r2_vs_training_mean"] for row in real["rungs"]]
    control_r2 = [row["out_of_sample_r2_vs_training_mean"] for row in control["rungs"]]
    assert real_r2 != control_r2


def test_an_imbalance_flips_sign_under_the_mirror_and_a_total_moves_sides() -> None:
    observations = build_fixture_observations(300)
    mirrored = permute_side_labels(observations, seed=5)
    for before, after in zip(observations, mirrored, strict=True):
        if before.features == after.features:
            continue
        assert after.features["best__quantity_imbalance"] == pytest.approx(
            -before.features["best__quantity_imbalance"]
        )
        assert after.features["l51_200__ask_quantity"] == pytest.approx(
            before.features["l51_200__bid_quantity"]
        )
        break
    else:  # pragma: no cover - the previous test proves the subset is non-empty
        pytest.fail("the mirror changed nothing")


# ----------------------------------------------------------------------------------------------
# Tables, power, and the assembled artifact
# ----------------------------------------------------------------------------------------------


def test_the_association_table_is_emitted_complete_for_every_feature_and_horizon() -> None:
    observations = build_fixture_observations(200)
    rows = association_table(observations, horizons_seconds=(1, 5))
    features = {row.feature for row in rows}
    assert "midpoint" not in features
    assert len(rows) == len(features) * 2
    assert {row.horizon_seconds for row in rows} == {1, 5}


def test_the_required_sample_answers_how_much_tape_would_settle_a_step() -> None:
    differential = [0.01 * ((index % 7) - 3) for index in range(400)]
    timestamps = [START_NS + index * SECOND for index in range(400)]
    result = required_blocks_for_target(
        differential,
        timestamps,
        [0] * 400,
        overlap_seconds=10.0,
        baseline_mean_squared_error=100.0,
        test_share_of_tape=0.12,
    )
    assert result["required_blocks"] is not None
    assert result["required_tape_sessions"] > result["required_test_sessions"]


def test_the_required_sample_refuses_to_invent_a_number_without_a_baseline() -> None:
    result = required_blocks_for_target(
        [1.0, 2.0], [START_NS, START_NS + SECOND], [0, 0],
        overlap_seconds=1.0,
        baseline_mean_squared_error=None,
    )
    assert result["required_blocks"] is None


def test_the_assembled_artifact_carries_every_required_section() -> None:
    observations = build_fixture_observations(500)
    tape = TapeInput(
        tape_index=0,
        run_id="fixture",
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
        tape_sha256=PERMITTED_SHA,
        observations=tuple(observations),
        depth200_publications=500,
        depth20_publications=6200,
        observed_seconds=500.0,
        failures={},
    )
    artifact = build_normal_activity_artifact(
        [tape],
        code_commit="deadbeef",
        horizons_seconds=(1, 5),
        replicates=9,
        include_yardstick=False,
    )
    assert set(artifact) == {
        "protocol",
        "tapes",
        "totals",
        "split",
        "unconditional_response",
        "nested_region_comparison",
        "negative_controls",
        "associations",
        "yardstick",
        "feature_names",
    }
    assert artifact["tapes"][0]["tape_sha256"] == PERMITTED_SHA
    assert set(artifact["nested_region_comparison"]) == {"level_index", "price_distance"}
    assert set(artifact["negative_controls"]) == {
        "time_shuffle_within_30_minute_bucket",
        "side_label_permutation",
        "past_return_mirror",
        "contemporaneous_leg",
    }
    assert set(artifact["associations"]) == {"future", "past", "contemporaneous"}


def test_the_raw_and_drift_adjusted_columns_are_not_the_same_number() -> None:
    """Regression test: scored on the adjusted scale, both benchmarks collapse onto each other.

    After removing the training drift the training mean *is* zero, so "R-squared against zero" and
    "R-squared against the training mean" become the same statistic and the raw column silently
    stops showing the drift it exists to show. The raw column is now scored on the unadjusted
    scale, where a falling market makes it much larger.
    """

    observations = build_fixture_observations(500, drift=0.05)
    split = chronological_embargoed_split(observations)
    result = nested_region_comparison(observations, split, horizon=10, replicates=9)
    assert result["removed_training_drift_ticks"] != 0.0
    for row in result["rungs"]:
        if row["out_of_sample_r2_vs_zero"] is None:
            continue
        assert row["out_of_sample_r2_vs_zero"] != row["out_of_sample_r2_vs_training_mean"]
