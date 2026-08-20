from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts.sig21_exploratory_response_scan import _parser, build_scan, main, run
from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState
from shaurya.signals.deep_book_anomaly import AtomicEventType, CandidateEvent
from shaurya.signals.deep_book_construction_grid import (
    construction_cells,
    edge_distance,
    outer_price,
)
from shaurya.signals.deep_book_exploratory_response import (
    BURST_PREDICTORS,
    CONFIRMATORY_ELIGIBLE,
    EVENT_PREDICTORS,
    EXPLORATORY_SCAN_ID,
    FUTURES_TICK_SIZE,
    MINIMUM_CREDIBLE_CELL_N,
    NEAR_BOUNDARY_RUPEES,
    PERMITTED_TAPE_SHA256,
    REGISTERING_COMMIT,
    SELECTIVITY_GRID,
    THRESHOLD_PROVENANCE,
    ConfirmatoryUseRefused,
    IncompleteFamilyRefused,
    TapeNotPermitted,
    TapeScan,
    _control_difference_series,
    _deterministic_permutation,
    assert_complete_family,
    assert_exploratory_claim,
    assert_in_sample_threshold,
    assert_permitted_tape,
    attach_burst_responses,
    attach_past_return_placebo,
    build_cell_series,
    build_contemporaneous_observations,
    build_control_instants,
    build_covariate_series,
    build_exploratory_artifact,
    build_in_sample_magnitude_index,
    build_negative_controls,
    build_past_return_observations,
    build_predictor_observations,
    build_response_family,
    build_selectivity_curve,
    build_threshold_controls,
    build_window_decomposition,
    burst_predictor_values,
    claim_tokens,
    construction_cell_of,
    event_predictor_values,
    family_rows,
    hac_mean_estimate,
    hac_simple_regression,
    overlap_lag_observations,
    protocol_metadata,
    required_effective_sample,
    required_probability_sample,
    signed_magnitude,
)
from shaurya.signals.deep_book_inference import (
    REGISTERED_FAMILY_SIZE,
    REGISTERED_OVERLAP_LAG,
    FamilyCell,
    canonical_family_manifest,
)
from shaurya.signals.deep_book_response import (
    EpisodeEvent,
    build_depth20_response_labels,
    cluster_event_episodes,
    depth20_midpoint,
    select_primary_non_overlapping_episodes,
)

SECOND = 1_000_000_000
# 2026-08-19T07:39:35Z == 13:09:35 IST, the registered 13:00 bucket, matching the real tapes.
START_NS = 1_787_125_175_000_000_000
INSTRUMENT = "NSE:NSE_FNO:NIFTY:future:2026-08-25"
PERMITTED_SHA = sorted(PERMITTED_TAPE_SHA256)[0]


def depth20_state(
    ts_ns: int,
    *,
    bid: float,
    ask: float,
    bid_quantity: int = 100,
    ask_quantity: int = 100,
    flags: tuple[str, ...] = (),
    epoch: int = 1,
) -> BookState:
    return BookState(
        channel=DEPTH20,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=epoch,
        bids=((bid, bid_quantity, 1), (bid - 1.0, bid_quantity, 1)),
        asks=((ask, ask_quantity, 1), (ask + 1.0, ask_quantity, 1)),
        rows_in_burst=1,
        quality_flags=flags,
    )


def ramp_states(count: int, *, step_ns: int = SECOND // 2, drift: float = 0.0) -> list[BookState]:
    """A depth20 series whose midpoint drifts by ``drift`` rupees per observation."""

    return [
        depth20_state(
            START_NS + position * step_ns,
            bid=24_000.0 + position * drift,
            ask=24_000.2 + position * drift,
        )
        for position in range(count)
    ]


def candidate(
    ts_ns: int,
    *,
    atomic_type: AtomicEventType = AtomicEventType.ADDITION,
    side: str = "bid",
    band: str = "gt_50",
    magnitude: float = 100.0,
    price: float = 23_900.0,
    distance: float = 60.0,
    orders_before: int = 0,
    orders_after: int = 1,
) -> CandidateEvent:
    return CandidateEvent(
        instrument_id=INSTRUMENT,
        receive_ts_ns=ts_ns,
        connection_epoch=1,
        atomic_type=atomic_type,
        side=side,  # type: ignore[arg-type]
        price=price,
        source_price=None,
        distance_rupees=distance,
        distance_band=band,
        magnitude=magnitude,
        quantity_before=0,
        quantity_after=int(magnitude),
        orders_before=orders_before,
        orders_after=orders_after,
        object_category="deterministically_derived",
    )


def build_fixture_scan(
    candidates: list[CandidateEvent],
    states: list[BookState],
    *,
    tape_index: int = 0,
    run_id: str = "fixture-run",
) -> TapeScan:
    stamps = sorted({item.receive_ts_ns for item in candidates})
    responses, failures = attach_burst_responses(
        stamps, states, tape_index=tape_index, run_id=run_id
    )
    series = build_covariate_series(
        states, run_id=run_id, session_id="2026-08-19", instrument_id=INSTRUMENT
    )
    return TapeScan(
        tape_index=tape_index,
        run_id=run_id,
        session_id="2026-08-19",
        instrument_id=INSTRUMENT,
        tape_sha256=PERMITTED_SHA,
        candidates=tuple(candidates),
        edge_distances=tuple(0.0 for _ in candidates),
        responses_by_ts={response.receive_ts_ns: response for response in responses},
        control_instants=build_control_instants(
            states, series, tape_index=tape_index, run_id=run_id
        ),
        covariates=series,
        observed_seconds=(
            (states[-1].receive_ts_ns - states[0].receive_ts_ns) / SECOND if states else 0.0
        ),
        label_failures=dict(failures),
    )


# ----------------------------------------------------------------------------------------------
# Protocol refusals
# ----------------------------------------------------------------------------------------------


def test_scan_is_declared_non_confirmatory() -> None:
    assert EXPLORATORY_SCAN_ID == "X-SIG21-DAT20-01"
    assert CONFIRMATORY_ELIGIBLE is False
    assert THRESHOLD_PROVENANCE == "in_sample_exploratory"


@pytest.mark.parametrize(
    "claim",
    [
        "confirmed directional response",
        "the deep book is predictive",
        "falsified at the registered scale",
        "promote to the quoting configuration",
        "this is a tradeable signal",
        "confirmatory read-out",
        "economic edge",
        "verdict",
    ],
)
def test_confirmatory_claims_are_refused(claim: str) -> None:
    with pytest.raises(ConfirmatoryUseRefused) as error:
        assert_exploratory_claim([claim])
    assert "§1.5" in str(error.value)
    assert REGISTERING_COMMIT[:8] in str(error.value)


@pytest.mark.parametrize(
    "claim",
    [
        "exploratory scan of the pre-registration DAT-20 tapes",
        "episode count versus selectivity",
        "unconfirmed by design",
        "falsifiable model proposal",
        "correlation structure",
    ],
)
def test_ordinary_exploratory_requests_are_allowed(claim: str) -> None:
    assert_exploratory_claim([claim])


def test_claim_tokens_match_whole_words_only() -> None:
    assert "confirmed" in claim_tokens("Confirmed, at last")
    assert "confirmed" not in claim_tokens("unconfirmed")
    assert claim_tokens("burst_signed_magnitude") == {"burst", "signed", "magnitude"}


def test_post_registration_tape_is_refused() -> None:
    with pytest.raises(TapeNotPermitted) as error:
        assert_permitted_tape(run_id="calibration-session-1", tape_sha256="0" * 64)
    assert "first outcome sample" in str(error.value)


def test_the_two_pre_registration_tapes_are_permitted() -> None:
    for sha in PERMITTED_TAPE_SHA256:
        assert_permitted_tape(run_id="dat20", tape_sha256=sha)
    assert len(PERMITTED_TAPE_SHA256) == 2


@pytest.mark.parametrize("provenance", ["past_only", "registered", "", "in-sample"])
def test_non_within_sample_threshold_provenance_is_refused(provenance: str) -> None:
    with pytest.raises(ConfirmatoryUseRefused) as error:
        assert_in_sample_threshold(provenance)
    assert "§5" in str(error.value)


def test_partial_family_is_refused() -> None:
    complete = list(canonical_family_manifest().cell_ids)
    assert_complete_family(complete)
    with pytest.raises(IncompleteFamilyRefused):
        assert_complete_family(complete[:100])
    with pytest.raises(IncompleteFamilyRefused):
        assert_complete_family(complete + [complete[0]])


def test_script_refuses_a_confirmatory_claim_before_opening_any_tape() -> None:
    args = argparse.Namespace(
        tape=[Path("/nonexistent/tape.jsonl")],
        output=Path("/nonexistent/out.json"),
        family_rows_output=None,
        replicates=9,
        seed=1,
        fine_selectivity=False,
        claim=["confirmed predictive relationship"],
    )
    with pytest.raises(ConfirmatoryUseRefused):
        run(args)


def test_script_main_reports_refusal_without_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--tape",
            "/nonexistent/tape.jsonl",
            "--output",
            "/nonexistent/out.json",
            "--claim",
            "falsified",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"


def test_script_refuses_a_tape_outside_the_permitted_pair(tmp_path: Path) -> None:
    run_id = "post-registration-calibration-1"
    tape = tmp_path / f"tape_{run_id}.jsonl"
    tape.write_text('{"event_type": "depth200", "receive_ts": "2026-08-20T04:00:00+00:00"}\n')
    (tmp_path / f"capture_metrics_{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "instrument_id": INSTRUMENT,
                "dhan_security_id": "58072",
                "trading_symbol": "NIFTY-Aug2026-FUT",
            }
        )
    )
    with pytest.raises(TapeNotPermitted):
        build_scan(tape, tape_index=0)


def test_parser_exposes_the_documented_switches() -> None:
    parser = _parser()
    args = parser.parse_args(["--tape", "a.jsonl", "--output", "b.json", "--fine-selectivity"])
    assert args.fine_selectivity is True
    assert args.claim is None


# ----------------------------------------------------------------------------------------------
# Regression: the right-edge coverage defect found on first contact with real tape
# ----------------------------------------------------------------------------------------------


def test_unguarded_labels_silently_truncate_the_horizon_at_the_tape_edge() -> None:
    """Documents the defect this scan found, so a future change cannot reintroduce it silently.

    With no coverage bound, an endpoint past the final observation resolves back to that final
    observation.  The label is emitted with no failure recorded, its realised horizon measured
    from the intended window start is *negative*, and both endpoints collapse onto the same state
    so the "10-second future return" is an exact fabricated zero.
    """

    states = ramp_states(30, drift=0.1)
    last = states[-1].receive_ts_ns
    event_ts = last + SECOND
    unguarded = build_depth20_response_labels(
        event_id="edge", event_ts_ns=event_ts, depth20_states=states
    )
    ten_second = [label for label in unguarded.labels if label.horizon_seconds == 10]
    assert ten_second, "the unguarded builder still emits a label past the tape edge"
    assert unguarded.failures == ()
    label = ten_second[0]
    intended_start = label.event_ts_ns + int(label.gap_seconds * SECOND)
    realised_horizon_ns = label.response_end_source_ts_ns - intended_start
    assert realised_horizon_ns < 0  # the window closed before it was supposed to open
    assert label.response_end_source_ts_ns == label.response_start_source_ts_ns
    assert label.future_response_ticks == 0.0  # a fabricated zero, reported as a measurement


def test_coverage_guard_refuses_endpoints_past_the_last_observation() -> None:
    states = ramp_states(30, drift=0.1)
    last = states[-1].receive_ts_ns
    guarded = build_depth20_response_labels(
        event_id="edge",
        event_ts_ns=last - 2 * SECOND,
        depth20_states=states,
        coverage_end_ts_ns=last,
    )
    reasons = {failure.reason for failure in guarded.failures}
    assert reasons == {"endpoint_beyond_coverage"}
    assert all(
        label.response_end_source_ts_ns >= label.response_start_source_ts_ns
        for label in guarded.labels
    )
    assert all(label.horizon_seconds == 1 for label in guarded.labels)


def test_coverage_guard_defaults_to_the_previous_behaviour() -> None:
    states = ramp_states(60, drift=0.05)
    event_ts = states[0].receive_ts_ns + SECOND
    default = build_depth20_response_labels(
        event_id="mid", event_ts_ns=event_ts, depth20_states=states
    )
    explicit = build_depth20_response_labels(
        event_id="mid",
        event_ts_ns=event_ts,
        depth20_states=states,
        coverage_end_ts_ns=states[-1].receive_ts_ns,
    )
    assert default.labels == explicit.labels
    assert default.failures == explicit.failures == ()


def test_attach_burst_responses_applies_the_coverage_guard() -> None:
    states = ramp_states(30, drift=0.1)
    stamps = [states[-1].receive_ts_ns - 2 * SECOND]
    responses, failures = attach_burst_responses(stamps, states, tape_index=0, run_id="fixture-run")
    assert failures["endpoint_beyond_coverage"] > 0
    assert all(key[1] == 1 for key in responses[0].cells)


def test_depth20_midpoint_matches_the_label_builder() -> None:
    states = ramp_states(20, drift=0.1)
    labels = build_depth20_response_labels(
        event_id="mid",
        event_ts_ns=states[4].receive_ts_ns,
        depth20_states=states,
        coverage_end_ts_ns=states[-1].receive_ts_ns,
    ).labels
    assert labels
    midpoint = depth20_midpoint(states[4])
    assert midpoint is not None
    assert float(midpoint) == pytest.approx(24_000.1 + 4 * 0.1)


def test_depth20_midpoint_rejects_unusable_states() -> None:
    crossed = depth20_state(START_NS, bid=24_010.0, ask=24_000.0)
    flagged = depth20_state(START_NS, bid=24_000.0, ask=24_000.2, flags=("partial_book",))
    assert depth20_midpoint(crossed) is None
    assert depth20_midpoint(flagged) is None


def test_past_return_placebo_refuses_windows_before_coverage_starts() -> None:
    states = ramp_states(60, drift=0.1)
    early = states[0].receive_ts_ns + SECOND
    late = states[-1].receive_ts_ns
    placebo = attach_past_return_placebo([early, late], states)
    assert placebo[early] == {}
    assert placebo[late]
    assert all(value > 0 for value in placebo[late].values())  # the fixture midpoint rises


# ----------------------------------------------------------------------------------------------
# Selectivity, episodes and the window decomposition
# ----------------------------------------------------------------------------------------------


def test_in_sample_index_uses_the_registered_scoring_rule_and_keeps_ties_together() -> None:
    candidates = [candidate(START_NS + index * SECOND, magnitude=100.0) for index in range(9)]
    candidates.append(candidate(START_NS + 9 * SECOND, magnitude=900.0))
    index = build_in_sample_magnitude_index(candidates)
    assert index.provenance == THRESHOLD_PROVENANCE
    assert index.percentile_of(candidates[-1]) == pytest.approx(1.0)
    assert index.percentile_of(candidates[0]) == pytest.approx(0.9)
    assert index.crosses(candidates[0], 0.90)
    assert not index.crosses(candidates[0], 0.95)
    assert index.cutoff_magnitude(construction_cell_of(candidates[0]).cell_id, 0.5) == 100.0


def test_selectivity_curve_reports_the_degenerate_and_the_separated_regimes() -> None:
    """The real shape: continuous small activity collapses, a sparse tail separates."""

    dense = [candidate(START_NS + index * SECOND // 2, magnitude=10.0) for index in range(600)]
    rare = [
        candidate(START_NS + (20 + index * 40) * SECOND, magnitude=10_000.0) for index in range(6)
    ]
    candidates = dense + rare
    index = build_in_sample_magnitude_index(candidates)
    curve = build_selectivity_curve(
        [candidates], index, observed_seconds_per_tape=[300.0], cutoffs=(0.5, 0.995)
    )
    pooled = {row["cutoff"]: row for row in curve["pooled"]}
    assert pooled[0.5]["retained_events"] == len(candidates)
    assert pooled[0.5]["non_overlapping_episodes"] == 1  # one contiguous chain
    assert pooled[0.995]["retained_events"] == len(rare)
    assert pooled[0.995]["non_overlapping_episodes"] == len(rare)
    assert curve["degenerate_cutoffs"] == [0.5]
    assert curve["max_episode_cutoff"] == 0.995
    assert curve["capacity_ceiling"] == 300 // 11
    assert len(curve["by_construction_cell"]) == len(construction_cells()) * 2


def test_selectivity_curve_emits_every_construction_cell_including_empty_ones() -> None:
    candidates = [candidate(START_NS + index * SECOND) for index in range(5)]
    index = build_in_sample_magnitude_index(candidates)
    curve = build_selectivity_curve(
        [candidates], index, observed_seconds_per_tape=[60.0], cutoffs=SELECTIVITY_GRID
    )
    reported = {row["group_id"] for row in curve["by_construction_cell"]}
    assert reported == {cell.cell_id for cell in construction_cells()}


def test_window_decomposition_gives_a_smaller_window_a_larger_risk_set() -> None:
    candidates = [candidate(START_NS + index * 3 * SECOND) for index in range(20)]
    index = build_in_sample_magnitude_index(candidates)
    decomposition = build_window_decomposition(
        [candidates], index, observed_seconds_per_tape=[600.0], cutoffs=(0.0,)
    )
    rows = {
        (row["gap_seconds"], row["horizon_seconds"]): row["non_overlapping_episodes"]
        for row in decomposition["rows"]
    }
    assert rows[(0.5, 1)] > rows[(0.5, 5)] >= rows[(0.5, 10)]
    assert len(decomposition["rows"]) == 6


# ----------------------------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------------------------


def test_overlap_lag_never_falls_below_the_registered_floor() -> None:
    assert overlap_lag_observations([]) == REGISTERED_OVERLAP_LAG
    sparse = [START_NS + index * 100 * SECOND for index in range(5)]
    assert overlap_lag_observations(sparse) == REGISTERED_OVERLAP_LAG
    dense = [START_NS + index * SECOND // 4 for index in range(200)]
    assert overlap_lag_observations(dense) > REGISTERED_OVERLAP_LAG


def test_hac_mean_estimate_reports_n_eff_within_bounds() -> None:
    alternating = [1.0, -1.0] * 40
    estimate = hac_mean_estimate(alternating, lag=REGISTERED_OVERLAP_LAG, distinct_bursts=80)
    assert estimate.n == 80
    assert estimate.mean == pytest.approx(0.0)
    assert estimate.n_eff_variance_inflation is not None
    assert 1.0 <= estimate.n_eff_variance_inflation <= 80.0


def test_hac_mean_estimate_discounts_perfectly_duplicated_observations() -> None:
    varied = [float(index % 7) for index in range(120)]
    duplicated = [value for value in varied for _ in range(3)]
    plain = hac_mean_estimate(varied, lag=REGISTERED_OVERLAP_LAG, distinct_bursts=120)
    inflated = hac_mean_estimate(duplicated, lag=REGISTERED_OVERLAP_LAG, distinct_bursts=120)
    assert inflated.n == 3 * plain.n
    assert inflated.variance_inflation_factor is not None
    assert plain.variance_inflation_factor is not None
    assert inflated.variance_inflation_factor > plain.variance_inflation_factor


def test_hac_mean_estimate_handles_an_empty_sample() -> None:
    estimate = hac_mean_estimate([], lag=REGISTERED_OVERLAP_LAG, distinct_bursts=0)
    assert estimate.n == 0
    assert estimate.mean is None
    assert estimate.t_statistic is None


def test_hac_regression_recovers_a_noiseless_slope() -> None:
    predictor = [float(index) for index in range(50)]
    response = [3.0 + 2.5 * value for value in predictor]
    fit = hac_simple_regression(predictor, response, lag=REGISTERED_OVERLAP_LAG)
    assert fit.slope == pytest.approx(2.5)
    assert fit.intercept == pytest.approx(3.0)
    assert fit.correlation == pytest.approx(1.0)
    assert fit.r_squared == pytest.approx(1.0)


def test_hac_regression_refuses_degenerate_inputs() -> None:
    assert hac_simple_regression([1.0, 2.0], [1.0, 2.0], lag=11).slope is None
    flat = hac_simple_regression([1.0] * 20, [float(i) for i in range(20)], lag=11)
    assert flat.slope is None


def test_hac_regression_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        hac_simple_regression([1.0, 2.0, 3.0], [1.0, 2.0], lag=11)


def test_required_sample_sizes_scale_as_specified() -> None:
    base = required_effective_sample(sigma_ticks=10.0, critical_value=1.96, target_mde_ticks=0.25)
    doubled = required_effective_sample(
        sigma_ticks=20.0, critical_value=1.96, target_mde_ticks=0.25
    )
    assert base is not None and doubled is not None
    assert doubled == pytest.approx(4.0 * base)
    assert (
        required_effective_sample(sigma_ticks=0.0, critical_value=1.96, target_mde_ticks=0.25)
        is None
    )
    probability = required_probability_sample(probability=0.5, critical_value=1.96)
    assert probability is not None and probability > 0
    assert required_probability_sample(probability=0.0, critical_value=1.96) is None


def test_deterministic_permutation_is_a_permutation_and_reproducible() -> None:
    first = _deterministic_permutation(50, 7)
    second = _deterministic_permutation(50, 7)
    assert first == second
    assert sorted(first) == list(range(50))
    assert _deterministic_permutation(50, 8) != first


# ----------------------------------------------------------------------------------------------
# Sign convention and predictors
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("atomic_type", "side", "expected_sign"),
    [
        (AtomicEventType.ADDITION, "bid", 1.0),
        (AtomicEventType.ADDITION, "ask", -1.0),
        (AtomicEventType.REMOVAL, "bid", -1.0),
        (AtomicEventType.REMOVAL, "ask", 1.0),
        (AtomicEventType.QUANTITY_INCREASE, "bid", 1.0),
        (AtomicEventType.QUANTITY_DECREASE, "bid", -1.0),
        (AtomicEventType.ORDER_COUNT_INCREASE, "ask", -1.0),
        (AtomicEventType.ORDER_COUNT_DECREASE, "ask", 1.0),
        (AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY, "bid", 1.0),
        (AtomicEventType.RELOCATION_AWAY_FROM_TOUCH_PROXY, "bid", -1.0),
    ],
)
def test_signed_magnitude_follows_the_declared_convention(
    atomic_type: AtomicEventType, side: str, expected_sign: float
) -> None:
    event = candidate(START_NS, atomic_type=atomic_type, side=side, magnitude=250.0)
    assert signed_magnitude(event) == pytest.approx(expected_sign * 250.0)


def test_event_and_burst_predictors_cover_the_declared_names() -> None:
    event = candidate(START_NS, orders_before=2, orders_after=5)
    values = event_predictor_values(event)
    assert set(values) == set(EVENT_PREDICTORS)
    assert values["order_count_change"] == 3.0
    burst = burst_predictor_values(
        [
            candidate(START_NS, side="bid", magnitude=100.0),
            candidate(START_NS, side="ask", magnitude=300.0),
        ]
    )
    assert set(burst) == set(BURST_PREDICTORS)
    assert burst["burst_candidate_count"] == 2.0
    assert burst["burst_total_magnitude"] == 400.0
    assert burst["burst_side_imbalance"] == pytest.approx(0.0)
    assert burst_predictor_values([])["burst_candidate_count"] == 0.0


# ----------------------------------------------------------------------------------------------
# Aggregation into the complete family
# ----------------------------------------------------------------------------------------------


def test_cell_series_collapses_overlapping_bursts_into_one_episode() -> None:
    states = ramp_states(200, drift=0.05)
    candidates = [candidate(START_NS + 20 * SECOND + index * SECOND) for index in range(5)]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    cell = FamilyCell(AtomicEventType.ADDITION, "bid", "gt_50", 0.995, 0.5, 1)
    series = build_cell_series(cell, [scan], index)
    assert series.distinct_bursts == 5
    assert len(series.event_values) == 5
    assert len(series.episode_values) == 1  # 1 s apart, inside this cell's 1.5 s window


def test_cell_series_separates_bursts_spaced_beyond_the_window() -> None:
    states = ramp_states(400, drift=0.02)
    candidates = [candidate(START_NS + (20 + index * 20) * SECOND) for index in range(4)]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    cell = FamilyCell(AtomicEventType.ADDITION, "bid", "gt_50", 0.995, 0.5, 1)
    series = build_cell_series(cell, [scan], index)
    assert len(series.episode_values) == 4


def test_cell_series_uses_this_cells_own_window_not_the_family_maximum() -> None:
    """`D34` / `H-SIG21-A1` on the shape the DAT-20 tapes actually showed.

    Bursts every three seconds.  The `Z = 0.5 s, h2 = 1 s` cell needs 1.5 s of exclusivity, so
    every burst is its own episode.  Under the old family-maximum 11 s convention the whole train
    collapsed to one, which is the distortion the amendment removes.  Both numbers are emitted.
    """

    states = ramp_states(400, drift=0.02)
    candidates = [candidate(START_NS + (20 + index * 3) * SECOND) for index in range(10)]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)

    short = build_cell_series(
        FamilyCell(AtomicEventType.ADDITION, "bid", "gt_50", 0.995, 0.5, 1), [scan], index
    )
    assert short.episode_window_seconds == pytest.approx(1.5)
    assert len(short.episode_values) == 10
    assert len(short.family_maximum_episode_values) == 1

    longest = build_cell_series(
        FamilyCell(AtomicEventType.ADDITION, "bid", "gt_50", 0.995, 1.0, 10), [scan], index
    )
    assert longest.episode_window_seconds == pytest.approx(11.0)
    # The cell the family maximum was derived from is untouched by the amendment.
    assert longest.episode_values == longest.family_maximum_episode_values


def test_the_family_maximum_arm_reproduces_the_pre_amendment_primary_arm() -> None:
    """The robustness arm is not decoration: it equals the old primary arm cell for cell."""

    states = ramp_states(400, drift=0.02)
    candidates = [candidate(START_NS + (20 + index * 3) * SECOND) for index in range(10)]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    cell = FamilyCell(AtomicEventType.ADDITION, "bid", "gt_50", 0.995, 0.5, 1)

    series = build_cell_series(cell, [scan], index)
    stamps = sorted({event.receive_ts_ns for event in scan.candidates})
    # `cluster_event_episodes` with no `window_ns` is exactly the pre-amendment call site.
    pre_amendment = select_primary_non_overlapping_episodes(
        cluster_event_episodes([EpisodeEvent(stamp, str(stamp)) for stamp in stamps])
    ).selected

    assert len(pre_amendment) == 1
    assert len(series.family_maximum_episode_values) == len(pre_amendment)
    assert len(series.episode_values) == 10


def test_family_emits_all_384_cells_with_all_four_arms() -> None:
    states = ramp_states(300, drift=0.05)
    candidates = [
        candidate(
            START_NS + (20 + index * 4) * SECOND,
            atomic_type=atomic_type,
            side=side,
            magnitude=100.0 + index,
        )
        for index, (atomic_type, side) in enumerate(
            [(atomic_type, side) for atomic_type in AtomicEventType for side in ("bid", "ask")]
        )
    ]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    family = build_response_family([scan], index, replicates=9, seed=3)
    assert family["family_size"] == REGISTERED_FAMILY_SIZE
    assert len(family["cells"]) == REGISTERED_FAMILY_SIZE
    assert family["confirmatory_eligible"] is False
    assert set(family["arms"]) == {
        "primary_non_overlapping_episodes",
        "robustness_family_maximum_episodes",
        "secondary_all_event_overlap_robust",
        "event_minus_matched_control",
    }
    assert family["episode_window_convention"] == "per_cell_z_plus_h2"
    assert family["episode_window_amendment"] == "H-SIG21-A1"
    for cell in family["cells"]:
        assert set(cell["arms"]) == set(family["arms"])
        for arm in family["arms"]:
            payload = cell["arms"][arm]
            assert 0.0 <= payload["romano_wolf_adjusted_p_value"] <= 1.0
            assert payload["n"] >= 0
    assert_complete_family([cell["cell_id"] for cell in family["cells"]])


def test_family_records_control_match_failures_explicitly() -> None:
    states = ramp_states(300, drift=0.05)
    # Anomalies once a second across the whole tape, exactly the density the real far book has:
    # no instant anywhere is more than 11 s from one, so the registered quiet control set is empty.
    candidates = [candidate(START_NS + index * SECOND) for index in range(150)]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    controls = build_threshold_controls([scan], index, threshold=0.5)
    assert controls.anomaly_bursts > 0
    assert controls.control_candidates > 0
    assert controls.quiet_candidates == 0
    assert controls.failure_counts
    assert not controls.matched


def test_negative_controls_report_the_complete_family_each() -> None:
    states = ramp_states(300, drift=0.05)
    candidates = [
        candidate(START_NS + (20 + index * 3) * SECOND, magnitude=100.0 + index)
        for index in range(30)
    ]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    stamps = sorted({item.receive_ts_ns for item in candidates})
    past = attach_past_return_placebo(stamps, states)
    control_sets = {
        threshold: build_threshold_controls([scan], index, threshold=threshold)
        for threshold in (0.995, 0.999)
    }
    controls = build_negative_controls(
        [scan],
        index,
        past_returns_by_ts={(0, stamp): row for stamp, row in past.items()},
        control_sets=control_sets,
    )
    names = {result["name"] for result in controls["results"]}
    assert names == set(controls["registered_controls"])
    for result in controls["results"]:
        assert result["cells_reported"] == REGISTERED_FAMILY_SIZE
        assert_complete_family([cell["cell_id"] for cell in result["cells"]])
        assert 0.0 <= result["share_of_family_nominally_significant"] <= 1.0


def test_quiet_episode_placebo_is_not_forced_to_zero_by_construction() -> None:
    """Regression for a defect in an earlier draft of this scan.

    Differencing a set of controls against a *permutation* of itself sums to zero identically, so
    the placebo could never fire whatever the data did.  The implemented placebo matches each
    quiet instant to its nearest other quiet instant by the §6 covariate rule, which is not a
    bijection, so a real imbalance can show up.
    """

    states = ramp_states(400, drift=0.05)
    candidates = [candidate(START_NS + 30 * SECOND, magnitude=100.0)]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    control_sets = {
        threshold: build_threshold_controls([scan], index, threshold=threshold)
        for threshold in (0.995, 0.999)
    }
    controls = build_negative_controls(
        [scan], index, past_returns_by_ts={}, control_sets=control_sets
    )
    placebo = next(
        result for result in controls["results"] if result["name"] == "matched_quiet_episodes"
    )
    observed = [cell for cell in placebo["cells"] if cell["n"] > 0]
    assert observed, "the placebo must actually be populated"
    assert any(
        cell["mean_ticks"] is not None and abs(cell["mean_ticks"]) > 0.0 for cell in observed
    )


def test_predictor_observations_carry_every_registered_response() -> None:
    states = ramp_states(300, drift=0.05)
    candidates = [candidate(START_NS + (20 + index * 3) * SECOND) for index in range(10)]
    scan = build_fixture_scan(candidates, states)
    observations = build_predictor_observations([scan])
    assert len(observations) == len(candidates)
    assert all(len(observation.responses) == 6 for observation in observations)
    assert all(
        set(observation.predictors) == set(EVENT_PREDICTORS) | set(BURST_PREDICTORS)
        for observation in observations
    )


def test_protocol_metadata_states_the_pre_registration_justification() -> None:
    states = ramp_states(60, drift=0.0)
    scan = build_fixture_scan([candidate(START_NS + 20 * SECOND)], states)
    metadata = protocol_metadata([scan], code_commit="abc123")
    assert metadata["confirmatory_eligible"] is False
    assert metadata["registration_document_modified"] is False
    assert metadata["registering_commit"] == REGISTERING_COMMIT
    assert "§1.5" in metadata["pre_registration_capture_justification"]
    assert metadata["source_tapes"][0]["captured_before_registering_commit"] is True


def test_exploratory_artifact_assembles_every_required_section() -> None:
    states = ramp_states(400, drift=0.05)
    candidates = [
        candidate(START_NS + (20 + index * 5) * SECOND, magnitude=100.0 + index)
        for index in range(20)
    ]
    scan = build_fixture_scan(candidates, states)
    stamps = sorted({item.receive_ts_ns for item in candidates})
    past = attach_past_return_placebo(stamps, states)
    artifact = build_exploratory_artifact(
        [scan],
        past_returns={(0, stamp): row for stamp, row in past.items()},
        code_commit="deadbeef",
        replicates=9,
        seed=5,
        cutoffs=(0.5, 0.995),
    )
    assert set(artifact) == {
        "protocol",
        "totals",
        "selectivity_curve",
        "window_decomposition",
        "unconditional_response",
        "family",
        "correlations",
        "correlations_past_return_placebo",
        "correlations_contemporaneous_leg",
        "negative_controls",
        "power",
    }
    assert artifact["protocol"]["exploratory_scan_id"] == EXPLORATORY_SCAN_ID
    rows = family_rows(artifact)
    assert len(rows) == REGISTERED_FAMILY_SIZE * 4
    assert all(row["confirmatory_eligible"] is False for row in rows)
    assert all(row["threshold_provenance"] == THRESHOLD_PROVENANCE for row in rows)


def test_artifact_refuses_a_tape_outside_the_permitted_pair() -> None:
    states = ramp_states(60, drift=0.0)
    scan = build_fixture_scan([candidate(START_NS + 20 * SECOND)], states)
    forged = TapeScan(
        tape_index=scan.tape_index,
        run_id="calibration-1",
        session_id=scan.session_id,
        instrument_id=scan.instrument_id,
        tape_sha256="f" * 64,
        candidates=scan.candidates,
        edge_distances=scan.edge_distances,
        responses_by_ts=scan.responses_by_ts,
        control_instants=scan.control_instants,
        covariates=scan.covariates,
        observed_seconds=scan.observed_seconds,
        label_failures=scan.label_failures,
    )
    with pytest.raises(TapeNotPermitted):
        build_exploratory_artifact([forged], past_returns={}, replicates=3)


def test_correlations_cover_every_predictor_cell_and_horizon() -> None:
    states = ramp_states(300, drift=0.05)
    candidates = [
        candidate(START_NS + (20 + index * 3) * SECOND, magnitude=100.0 + index)
        for index in range(15)
    ]
    scan = build_fixture_scan(candidates, states)
    stamps = sorted({item.receive_ts_ns for item in candidates})
    past = attach_past_return_placebo(stamps, states)
    artifact = build_exploratory_artifact(
        [scan],
        past_returns={(0, stamp): row for stamp, row in past.items()},
        replicates=5,
        cutoffs=(0.5,),
    )
    rows = artifact["correlations"]["rows"]
    predictors = set(EVENT_PREDICTORS) | set(BURST_PREDICTORS)
    groups = {"pooled"} | {cell.cell_id for cell in construction_cells()}
    assert len(rows) == len(predictors) * len(groups) * 6
    assert {row["predictor"] for row in rows} == predictors
    assert {row["group_id"] for row in rows} == groups
    assert all(row["event_level"]["inference_valid"] is False for row in rows)
    assert all(row["non_overlapping_block_level"]["inference_valid"] is True for row in rows)


def test_power_section_separates_apparent_from_credible_precision() -> None:
    states = ramp_states(400, drift=0.05)
    candidates = [
        candidate(START_NS + (20 + index * 5) * SECOND, magnitude=100.0 + index)
        for index in range(20)
    ]
    scan = build_fixture_scan(candidates, states)
    artifact = build_exploratory_artifact([scan], past_returns={}, replicates=5, cutoffs=(0.5,))
    power = artifact["power"]
    assert power["registered_mean_mde_gate_ticks"] == 0.25
    assert power["registered_evaluation_ceiling_episodes"] == (23_100 // 11) * 20
    for arm, realised in power["realised_precision_by_arm"].items():
        assert realised["minimum_credible_cell_n"] == MINIMUM_CREDIBLE_CELL_N
        assert (
            realised["cells_meeting_mean_gate_with_credible_n"]
            + realised["cells_meeting_mean_gate_on_fewer_than_minimum_observations"]
            == realised["cells_meeting_mean_gate"]
        ), arm
    sources = {row["critical_value_source"] for row in power["requirements"]}
    assert "per_cell_normal_95" in sources
    assert any(source.startswith("family_bootstrap_max_t_") for source in sources)


# ----------------------------------------------------------------------------------------------
# Reused construction helpers
# ----------------------------------------------------------------------------------------------


def depth200_state(ts_ns: int, prices: list[float]) -> BookState:
    return BookState(
        channel=DEPTH200,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=1,
        bids=tuple((price, 100, 1) for price in prices),
        asks=((24_100.0, 100, 1),),
        rows_in_burst=1,
        quality_flags=(),
    )


def test_outer_price_and_edge_distance_are_publicly_reusable() -> None:
    state = depth200_state(START_NS, [24_000.0, 23_950.0, 23_900.0])
    assert outer_price(state, "bid") == 23_900.0
    assert outer_price(state, "ask") == 24_100.0
    added = candidate(START_NS, atomic_type=AtomicEventType.ADDITION, price=23_899.5)
    distance = edge_distance(added, 23_900.0, 23_899.5)
    assert distance == pytest.approx(0.0)
    assert distance is not None and distance <= NEAR_BOUNDARY_RUPEES


def test_futures_tick_is_the_registered_nse_tick() -> None:
    assert FUTURES_TICK_SIZE == 0.05


def test_past_return_observations_swap_in_the_mirror_window() -> None:
    states = ramp_states(400, drift=0.05)
    candidates = [candidate(START_NS + (100 + index * 3) * SECOND) for index in range(10)]
    scan = build_fixture_scan(candidates, states)
    stamps = sorted({item.receive_ts_ns for item in candidates})
    past = attach_past_return_placebo(stamps, states)
    forward = build_predictor_observations([scan])
    backward = build_past_return_observations(
        [scan], {(0, stamp): row for stamp, row in past.items()}
    )
    assert backward
    assert len(backward) <= len(forward)
    forward_by_ts = {item.receive_ts_ns: item for item in forward}
    for observation in backward:
        reference = forward_by_ts[observation.receive_ts_ns]
        assert observation.predictors == reference.predictors
        assert observation.responses != reference.responses


def test_contemporaneous_observations_use_the_reaction_leg_not_the_predictive_one() -> None:
    states = ramp_states(400, drift=0.05)
    candidates = [candidate(START_NS + (100 + index * 3) * SECOND) for index in range(10)]
    scan = build_fixture_scan(candidates, states)
    forward = {item.receive_ts_ns: item for item in build_predictor_observations([scan])}
    contemporaneous = build_contemporaneous_observations([scan])
    assert len(contemporaneous) == len(forward)
    for observation in contemporaneous:
        reference = forward[observation.receive_ts_ns]
        assert observation.predictors == reference.predictors
        assert set(observation.responses) == set(reference.responses)
        # The reaction leg is Z seconds long; the predictive leg is h2 seconds long.
        assert observation.responses != reference.responses


def test_control_arm_uses_the_registered_paired_estimator_and_agrees_with_it() -> None:
    """The registered estimand is a paired difference, so the registered primitive estimates it."""

    states = ramp_states(1_200, drift=0.02)
    candidates = [
        candidate(START_NS + (100 + index * 60) * SECOND, magnitude=100.0 + index)
        for index in range(8)
    ]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    controls = build_threshold_controls([scan], index, threshold=0.5)
    assert controls.quiet_candidates > 0
    assert controls.matched
    cell = FamilyCell(AtomicEventType.ADDITION, "bid", "gt_50", 0.995, 0.5, 1)
    series = _control_difference_series(cell, [scan], index, controls)
    assert series.event_values
    assert len(series.event_values) == len(series.control_values)
    paired = series.paired_estimate(lag=REGISTERED_OVERLAP_LAG)
    assert paired is not None
    assert paired.lag >= REGISTERED_OVERLAP_LAG
    direct = hac_mean_estimate(
        series.differences, lag=paired.lag, distinct_bursts=len(series.differences)
    )
    assert direct.mean is not None
    assert paired.mean_difference == pytest.approx(direct.mean)
    assert paired.standard_error == pytest.approx(direct.hac_standard_error)


def test_family_reports_the_registered_paired_estimator_alongside_the_arm() -> None:
    states = ramp_states(1_200, drift=0.02)
    candidates = [
        candidate(START_NS + (100 + index * 60) * SECOND, magnitude=100.0 + index)
        for index in range(8)
    ]
    scan = build_fixture_scan(candidates, states)
    index = build_in_sample_magnitude_index(candidates)
    family = build_response_family([scan], index, replicates=5, seed=11)
    reported = [
        cell["arms"]["event_minus_matched_control"]["registered_paired_estimator"]
        for cell in family["cells"]
    ]
    populated = [entry for entry in reported if entry is not None]
    assert populated
    assert all(entry["agrees_with_arm_mean"] for entry in populated)


def test_selectivity_curve_separates_pooled_from_per_cell_risk_sets() -> None:
    """Pooling all 32 cells into one timeline is harsher than the family's own cell-by-cell view."""

    bid = [candidate(START_NS + index * SECOND, side="bid", magnitude=100.0) for index in range(60)]
    ask = [
        candidate(START_NS + (index * SECOND) + SECOND // 2, side="ask", magnitude=100.0)
        for index in range(60)
    ]
    candidates = bid + ask
    index = build_in_sample_magnitude_index(candidates)
    curve = build_selectivity_curve(
        [candidates], index, observed_seconds_per_tape=[600.0], cutoffs=(0.0,)
    )
    pooled = curve["pooled"][0]
    totals = curve["per_construction_cell_totals"][0]
    assert pooled["non_overlapping_episodes"] == 1
    assert totals["summed_over_construction_cells_episodes"] >= 2
    assert totals["cells_with_at_least_one_episode"] == 2
    assert totals["cutoff"] == 0.0
