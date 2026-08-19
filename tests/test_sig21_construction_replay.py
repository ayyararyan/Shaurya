from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.sig21_construction_replay import (
    _parser,
    main,
    manifest_sha256_for,
    replay_tape,
    run,
    sha256_file,
    verify_instrument,
)
from shaurya.data.depth_thinning_analysis import DEPTH200, BookState
from shaurya.signals import deep_book_response
from shaurya.signals.deep_book_anomaly import AtomicEventType, detect_candidates
from shaurya.signals.deep_book_construction_grid import (
    CONSTRUCTION_CELL_COUNT,
    FAMILY_CELLS_PER_CONSTRUCTION_CELL,
    FORBIDDEN_REQUEST_TOKENS,
    MIN_BASELINE_EVENTS,
    OutcomeJoinRefused,
    TapeReplay,
    assert_outcome_blind_request,
    bucket_exposure_seconds,
    build_replay_artifact,
    build_tape_replay,
    construction_cells,
    distance_histogram_bin,
    grid_rows,
    name_tokens,
    replay_states,
    time_bucket_ist,
)
from shaurya.signals.deep_book_inference import REGISTERED_FAMILY_SIZE

INSTRUMENT = "NSE:NSE_FNO:NIFTY:future:2026-08-25"
SECURITY_ID = "58072"
SYMBOL = "NIFTY-Aug2026-FUT"

# 2026-08-19T07:39:35Z == 13:09:35 IST, inside the 13:00 registered bucket.
FIXTURE_START_NS = 1_787_125_175_000_000_000


def state(
    ts_ns: int,
    *,
    bids: list[tuple[float, int, int]] | None = None,
    asks: list[tuple[float, int, int]] | None = None,
    epoch: int = 1,
    flags: tuple[str, ...] = (),
) -> BookState:
    return BookState(
        channel=DEPTH200,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=epoch,
        bids=tuple(bids or [(100.0, 10, 1), (70.0, 10, 1), (40.0, 10, 1)]),
        asks=tuple(asks or [(101.0, 10, 1), (131.0, 10, 1), (161.0, 10, 1)]),
        rows_in_burst=1,
        quality_flags=flags,
    )


def fixture_states() -> list[BookState]:
    """A deterministic three-transition fixture touching several construction cells."""

    return [
        state(FIXTURE_START_NS),
        # bid gt_50 addition (price 45 is 55 rupees below the best bid of 100).
        state(
            FIXTURE_START_NS + 1_000_000_000,
            bids=[(100.0, 10, 1), (70.0, 10, 1), (45.0, 7, 2), (40.0, 10, 1)],
        ),
        # ask 20_50 quantity and order-count change at 131 (30 rupees above the best ask).
        state(
            FIXTURE_START_NS + 2_000_000_000,
            bids=[(100.0, 10, 1), (70.0, 10, 1), (45.0, 7, 2), (40.0, 10, 1)],
            asks=[(101.0, 10, 1), (131.0, 25, 4), (161.0, 10, 1)],
        ),
        # bid 20_50 removal at 70 (30 rupees below the best bid).
        state(
            FIXTURE_START_NS + 3_000_000_000,
            bids=[(100.0, 10, 1), (45.0, 7, 2), (40.0, 10, 1)],
            asks=[(101.0, 10, 1), (131.0, 25, 4), (161.0, 10, 1)],
        ),
    ]


def fixture_replay() -> TapeReplay:
    states = fixture_states()
    candidates, exclusions, attempted, valid, edges = replay_states(
        states, instrument_id=INSTRUMENT
    )
    return TapeReplay(
        run_id="fixture-run",
        tape_sha256="0" * 64,
        instrument_id=INSTRUMENT,
        dhan_security_id=SECURITY_ID,
        trading_symbol=SYMBOL,
        candidates=tuple(candidates),
        depth200_publications=len(states),
        transitions_attempted=attempted,
        transitions_valid=valid,
        exclusions=tuple(exclusions),
        edge_distances=tuple(edges),
        first_receive_ts_ns=states[0].receive_ts_ns,
        last_receive_ts_ns=states[-1].receive_ts_ns,
        publication_gaps_ms=(1_000.0, 1_000.0, 1_000.0),
        depth200_rows=len(states),
        depth20_rows=0,
        depth20_first_receive_ts_ns=None,
        depth20_last_receive_ts_ns=None,
    )


def receive_ts(ts_ns: int) -> str:
    seconds, fraction = divmod(ts_ns, 1_000_000_000)
    stamp = datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{fraction:09d}+00:00"


def tape_row(state_object: BookState, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_type": DEPTH200,
        "receive_ts": receive_ts(state_object.receive_ts_ns),
        "receive_sequence": state_object.receive_sequence,
        "connection_epoch": state_object.connection_epoch,
        "quality_flags": list(state_object.quality_flags),
        "bids": [
            {"price": price, "quantity": quantity, "orders": orders}
            for price, quantity, orders in state_object.bids
        ],
        "asks": [
            {"price": price, "quantity": quantity, "orders": orders}
            for price, quantity, orders in state_object.asks
        ],
    }
    row.update(overrides)
    return row


def write_capture(directory: Path, run_id: str, rows: list[dict[str, Any]]) -> Path:
    tape = directory / f"tape_{run_id}.jsonl"
    tape.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    metrics = {
        "run_id": run_id,
        "instrument_id": INSTRUMENT,
        "dhan_security_id": SECURITY_ID,
        "trading_symbol": SYMBOL,
    }
    (directory / f"capture_metrics_{run_id}.json").write_text(
        json.dumps(metrics), encoding="utf-8"
    )
    (directory / f"manifest_{run_id}.jsonl").write_text(
        json.dumps(
            {
                "event_type": "artifact_closed",
                "artifact": tape.name,
                "kind": "market_data_tape",
                "sha256": hashlib.sha256(tape.read_bytes()).hexdigest(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return tape


# --------------------------------------------------------------------------------------
# Grid construction
# --------------------------------------------------------------------------------------


def test_the_registered_family_decomposes_into_exactly_thirty_two_construction_cells() -> None:
    cells = construction_cells()

    assert len(cells) == CONSTRUCTION_CELL_COUNT == 32
    assert len(set(cells)) == 32
    assert CONSTRUCTION_CELL_COUNT * FAMILY_CELLS_PER_CONSTRUCTION_CELL == REGISTERED_FAMILY_SIZE


def test_grid_emits_every_construction_cell_including_the_empty_ones() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    grid = artifact["construction_grid"]

    assert len(grid) == 32
    assert [row["cell_id"] for row in grid] == [cell.cell_id for cell in construction_cells()]
    populated = {row["cell_id"] for row in grid if row["candidate_count"] > 0}
    empty = [row for row in grid if row["candidate_count"] == 0]
    assert populated and empty, "the fixture must exercise both populated and empty cells"
    assert all(row["share_of_candidates"] == 0.0 for row in empty)
    assert all(row["magnitude"]["count"] == 0 for row in empty)
    assert all(row["magnitude"]["median"] is None for row in empty)
    assert all(row["distinct_bursts"] == 0 for row in empty)
    assert artifact["family_decomposition"]["construction_cells_populated"] == len(populated)
    assert artifact["family_decomposition"]["construction_cells_empty"] == len(empty)


def test_deterministic_fixture_produces_the_expected_construction_cells() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    populated = {
        row["cell_id"]: row["candidate_count"]
        for row in artifact["construction_grid"]
        if row["candidate_count"] > 0
    }

    assert populated == {
        "addition|bid|gt_50": 1,
        "quantity_increase|ask|20_50": 1,
        "order_count_increase|ask|20_50": 1,
        "removal|bid|20_50": 1,
    }
    assert artifact["totals"]["candidates"] == 4
    assert artifact["totals"]["distinct_bursts"] == 3


def test_shares_and_family_expansion_are_internally_consistent() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    grid = artifact["construction_grid"]
    decomposition = artifact["family_decomposition"]

    assert sum(row["candidate_count"] for row in grid) == artifact["totals"]["candidates"]
    assert pytest.approx(sum(row["share_of_candidates"] for row in grid)) == 1.0
    assert (
        decomposition["family_cells_with_any_construction_support"]
        + decomposition["family_cells_with_zero_construction_support"]
        == REGISTERED_FAMILY_SIZE
    )


def test_relocation_cells_stay_labelled_as_proxies() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    by_type = {row["cell_id"]: row["object_category"] for row in artifact["construction_grid"]}

    for cell in construction_cells():
        expected = (
            "proxy"
            if cell.atomic_type
            in {
                AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY,
                AtomicEventType.RELOCATION_AWAY_FROM_TOUCH_PROXY,
            }
            else "deterministically_derived"
        )
        assert by_type[cell.cell_id] == expected


# --------------------------------------------------------------------------------------
# Transitions, exclusions and episode structure
# --------------------------------------------------------------------------------------


def test_boundary_churn_is_recorded_without_rejecting_the_transition() -> None:
    old_bids = [(100.0 - index, 10, 1) for index in range(40)]
    new_bids = [*old_bids[:-1], (59.0, 10, 1)]
    states = [state(1, bids=old_bids), state(2, bids=new_bids)]

    detected = detect_candidates(states[0], states[1], instrument_id=INSTRUMENT)
    _, exclusions, attempted, valid, _edges = replay_states(states, instrument_id=INSTRUMENT)

    assert any(item.reason == "whole_ladder_boundary_churn" for item in detected.exclusions)
    assert exclusions.count("whole_ladder_boundary_churn") == 1
    assert (attempted, valid) == (1, 1)


def test_a_contaminated_transition_is_counted_as_rejected_with_its_reason() -> None:
    states = [state(1), state(2, flags=("crossed_book",))]

    _, exclusions, attempted, valid, _edges = replay_states(states, instrument_id=INSTRUMENT)

    assert exclusions == ["invalid_quality:crossed_book"]
    assert (attempted, valid) == (1, 0)


def test_exclusion_breakdown_reconciles_with_publications() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    exclusions = artifact["exclusions"]

    assert exclusions["depth200_publications"] == 4
    assert exclusions["transitions_attempted"] == 3
    assert exclusions["transitions_valid"] == 3
    assert exclusions["transitions_rejected"] == 0
    assert exclusions["valid_transition_share"] == 1.0


def test_episode_structure_uses_the_registered_eleven_second_window() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    episodes = artifact["burst_and_episode_structure"]

    assert episodes["episode_window_seconds"] == 11
    # Three bursts one second apart share overlapping 11 s windows: one episode, not three.
    assert episodes["episodes"] == 1
    assert episodes["non_overlapping_episodes"] == 1
    assert episodes["inter_burst_gaps_at_or_over_episode_window"] == 0
    assert episodes["risk_set_is_degenerate"] is True


def test_separated_bursts_produce_separate_non_overlapping_episodes() -> None:
    far_apart = [
        state(FIXTURE_START_NS),
        state(FIXTURE_START_NS + 1_000_000_000, bids=[(100.0, 10, 1), (70.0, 10, 1)]),
        state(FIXTURE_START_NS + 40_000_000_000, bids=[(100.0, 10, 1), (70.0, 10, 1)]),
        state(
            FIXTURE_START_NS + 41_000_000_000,
            bids=[(100.0, 10, 1), (70.0, 10, 1), (40.0, 10, 1)],
        ),
    ]
    candidates, _, _, _, edges = replay_states(far_apart, instrument_id=INSTRUMENT)
    replay = TapeReplay(
        run_id="fixture-run",
        tape_sha256="0" * 64,
        instrument_id=INSTRUMENT,
        dhan_security_id=SECURITY_ID,
        trading_symbol=SYMBOL,
        candidates=tuple(candidates),
        depth200_publications=len(far_apart),
        transitions_attempted=3,
        transitions_valid=3,
        exclusions=(),
        edge_distances=tuple(edges),
        first_receive_ts_ns=far_apart[0].receive_ts_ns,
        last_receive_ts_ns=far_apart[-1].receive_ts_ns,
        publication_gaps_ms=(),
        depth200_rows=len(far_apart),
        depth20_rows=0,
        depth20_first_receive_ts_ns=None,
        depth20_last_receive_ts_ns=None,
    )

    episodes = build_replay_artifact([replay])["burst_and_episode_structure"]

    assert episodes["non_overlapping_episodes"] == 2
    assert episodes["inter_burst_gaps_at_or_over_episode_window"] == 1


# --------------------------------------------------------------------------------------
# Strata, coverage and the baseline layer
# --------------------------------------------------------------------------------------


def test_time_buckets_are_thirty_minute_ist_buckets() -> None:
    assert time_bucket_ist(FIXTURE_START_NS) == "13:00"
    assert time_bucket_ist(FIXTURE_START_NS + 1_500 * 1_000_000_000) == "13:30"


def test_bucket_exposure_splits_an_observation_window_across_buckets() -> None:
    # 13:09:35 IST plus 1,500 seconds ends at 13:34:35, so the window straddles 13:30.
    exposure = bucket_exposure_seconds(
        [(FIXTURE_START_NS, FIXTURE_START_NS + 1_500 * 1_000_000_000)]
    )

    assert pytest.approx(exposure["13:00"]) == 1_225.0
    assert pytest.approx(exposure["13:30"]) == 275.0
    assert pytest.approx(sum(exposure.values())) == 1_500.0


def test_time_of_day_reports_exposure_so_counts_are_comparable() -> None:
    time_of_day = build_replay_artifact([fixture_replay()])["time_of_day"]
    bucket = next(row for row in time_of_day["by_bucket"] if row["time_bucket"] == "13:00")

    assert pytest.approx(bucket["observed_seconds"]) == 3.0
    assert pytest.approx(bucket["candidates_per_second"]) == 4 / 3


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (20.5, "(20,25]"),
        (50.0, "(40,50]"),
        (50.1, "(50,75]"),
        (87.7, "(75,100]"),
        (900.0, "(500,inf)"),
    ],
)
def test_finer_distance_bins_nest_inside_the_registered_split(
    distance: float, expected: str
) -> None:
    assert distance_histogram_bin(distance) == expected


def test_distance_breakdown_splits_at_the_registered_boundary() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    distance = artifact["distance"]

    assert distance["far_boundary_rupees"] == 20.0
    assert distance["registered_split_rupees"] == 50.0
    assert [band["distance_band"] for band in distance["registered_bands"]] == ["20_50", "gt_50"]
    assert sum(band["candidate_count"] for band in distance["registered_bands"]) == 4
    assert sum(item["candidate_count"] for item in distance["finer_histogram"]) == 4


def test_baseline_layer_reports_every_registered_key_as_insufficient() -> None:
    baseline = build_replay_artifact([fixture_replay()])["baseline_layer"]

    assert baseline["minimum_history_per_key"] == MIN_BASELINE_EVENTS
    assert baseline["all_keys_status"] == "baseline_insufficient"
    assert baseline["keys_meeting_minimum_full_six_axis"] == 0
    assert baseline["scored_candidates"] == 0
    assert baseline["thresholds_estimable"] is False
    assert {entry["axis"] for entry in baseline["axes_not_determinable_here"]} == {
        "past_only_liquidity_bin",
        "vol04_regime",
    }
    assert all(row["status"] == "baseline_insufficient" for row in baseline["partial_keys"])
    assert all(
        row["shortfall_to_minimum_lower_bound"]
        == max(MIN_BASELINE_EVENTS - row["observed_candidates_upper_bound"], 0)
        for row in baseline["partial_keys"]
    )


def test_scenario_extrapolation_is_labelled_and_never_a_measurement() -> None:
    scenario = build_replay_artifact([fixture_replay()])["scenario_extrapolation"]

    assert scenario["object_category"] == "scenario_based"
    assert scenario["is_measurement"] is False
    assert "assumption" in scenario and "bias_warning" in scenario
    assert scenario["episode_capacity_ceiling_per_session"] == 22_500 // 11
    assert [item["scenario"] for item in scenario["scenarios"]] == [
        "one_full_session",
        "registered_calibration_sample",
        "registered_evaluation_sample",
    ]
    assert [item["sessions"] for item in scenario["scenarios"]] == [1, 5, 20]
    for row in scenario["retention_bounds"]:
        assert row["non_overlapping_episodes_upper_bound_per_session"] <= min(
            row["retained_bursts_per_session"], 22_500 // 11
        )


def test_coverage_counts_depth20_without_reading_any_depth20_price() -> None:
    rows = [tape_row(item) for item in fixture_states()]
    rows.append(
        {
            "event_type": "depth20",
            "receive_ts": receive_ts(FIXTURE_START_NS + 1_000_000_000),
            "connection_epoch": 1,
            "receive_sequence": 99,
            # A deliberately absurd depth20 book: if any of it leaked into the grid the counts
            # below would change. They do not, because only event_type and receive_ts are read.
            "bids": [{"price": 1.0, "quantity": 999_999, "orders": 999}],
            "asks": [{"price": 2.0, "quantity": 999_999, "orders": 999}],
        }
    )
    replay = build_tape_replay(
        rows,
        run_id="fixture-run",
        tape_sha256="0" * 64,
        instrument_id=INSTRUMENT,
        dhan_security_id=SECURITY_ID,
        trading_symbol=SYMBOL,
    )
    coverage = build_replay_artifact([replay])["coverage"]

    assert replay.depth20_rows == 1
    assert replay.candidates == fixture_replay().candidates
    assert coverage["per_tape"][0]["depth20_rows_counted_for_coverage_only"] == 1
    assert coverage["per_tape"][0]["depth200_publications"] == 4


# --------------------------------------------------------------------------------------
# Protocol refusal
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "requested",
    ["response", "responses", "future_returns", "markout", "midpoint", "outcome_join", "Y"],
)
def test_outcome_bearing_requests_are_refused(requested: str) -> None:
    with pytest.raises(OutcomeJoinRefused) as error:
        assert_outcome_blind_request([requested])

    assert "H-SIG21" in str(error.value)
    assert "construction_replay_only" in str(error.value)


@pytest.mark.parametrize(
    "requested",
    ["construction_grid", "distance", "coverage", "exclusions", "baseline_layer"],
)
def test_construction_sections_are_permitted(requested: str) -> None:
    assert_outcome_blind_request([requested])


def test_every_forbidden_token_is_actually_refused() -> None:
    for token in FORBIDDEN_REQUEST_TOKENS:
        with pytest.raises(OutcomeJoinRefused):
            assert_outcome_blind_request([token])


def test_a_refused_request_never_opens_the_tape(tmp_path: Path) -> None:
    missing = tmp_path / "tape_does_not_exist.jsonl"
    args = _parser().parse_args(
        ["--tape", str(missing), "--output", str(tmp_path / "out.json"), "--section", "response"]
    )

    with pytest.raises(OutcomeJoinRefused):
        run(args)

    assert not missing.exists()


def test_the_cli_exits_two_and_writes_nothing_when_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out.json"
    code = main(
        [
            "--tape",
            str(tmp_path / "tape_missing.jsonl"),
            "--output",
            str(output),
            "--section",
            "future_price_response",
        ]
    )

    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    assert not output.exists()


def test_the_replay_never_calls_the_response_label_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("H-SIG21 §1.2 violation: a response label was requested")

    monkeypatch.setattr(deep_book_response, "build_depth20_response_labels", explode)

    artifact = build_replay_artifact([fixture_replay()])

    assert artifact["protocol"]["outcome_join_allowed"] is False


def test_no_outcome_bearing_field_name_appears_anywhere_in_the_artifact() -> None:
    artifact = build_replay_artifact([fixture_replay()])
    allowed = {"outcome_join_allowed"}
    offending: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in allowed and name_tokens(key) & FORBIDDEN_REQUEST_TOKENS:
                    offending.append(str(key))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(artifact)

    assert offending == []


def test_the_candidate_schema_reaching_the_grid_carries_no_outcome_field() -> None:
    replay = fixture_replay()

    for candidate in replay.candidates:
        offending = [
            field
            for field in candidate.to_dict()
            if name_tokens(field) & FORBIDDEN_REQUEST_TOKENS
        ]
        assert offending == []


# --------------------------------------------------------------------------------------
# Source pinning: SHA-256, manifest agreement and instrument identity
# --------------------------------------------------------------------------------------


def test_source_tape_sha256_is_computed_and_recorded(tmp_path: Path) -> None:
    tape = write_capture(tmp_path, "fixture-run", [tape_row(item) for item in fixture_states()])
    expected = hashlib.sha256(tape.read_bytes()).hexdigest()

    replay = replay_tape(tape)
    artifact = build_replay_artifact([replay])
    source = artifact["protocol"]["source_tapes"][0]

    assert sha256_file(tape) == expected
    assert manifest_sha256_for(tape) == expected
    assert source["sha256"] == expected
    assert source["run_id"] == "fixture-run"
    assert source["instrument_id"] == INSTRUMENT
    assert source["dhan_security_id"] == SECURITY_ID
    assert source["trading_symbol"] == SYMBOL


def test_a_tape_that_no_longer_matches_its_manifest_is_refused(tmp_path: Path) -> None:
    tape = write_capture(tmp_path, "fixture-run", [tape_row(item) for item in fixture_states()])
    with tape.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_type": "standard"}) + "\n")

    with pytest.raises(ValueError, match="does not match the manifest value"):
        replay_tape(tape)


def test_only_a_nifty_future_may_be_replayed() -> None:
    with pytest.raises(ValueError, match="not a future"):
        verify_instrument(
            {
                "run_id": "r",
                "instrument_id": "NSE:NSE_FNO:NIFTY:option:2026-08-25:24000:CE",
                "dhan_security_id": SECURITY_ID,
                "trading_symbol": "NIFTY24000CE",
            },
            Path("tape.jsonl"),
        )
    with pytest.raises(ValueError, match="not a NIFTY contract"):
        verify_instrument(
            {
                "run_id": "r",
                "instrument_id": "NSE:NSE_FNO:RELIANCE:future:2026-08-25",
                "dhan_security_id": SECURITY_ID,
                "trading_symbol": "RELIANCE-Aug2026-FUT",
            },
            Path("tape.jsonl"),
        )


def test_protocol_metadata_is_present_and_outcome_join_is_denied() -> None:
    protocol = build_replay_artifact([fixture_replay()])["protocol"]

    assert protocol["protocol_id"] == "H-SIG21"
    assert protocol["sample_role"] == "construction_replay_only"
    assert protocol["outcome_join_allowed"] is False
    assert protocol["registration_document"] == "docs/sig-claims/H-SIG21.md"
    assert "§1.2" in protocol["excluded_by_registration"]


# --------------------------------------------------------------------------------------
# End-to-end artifact production
# --------------------------------------------------------------------------------------


def test_end_to_end_run_writes_a_complete_grid_artifact(tmp_path: Path) -> None:
    tape = write_capture(tmp_path, "fixture-run", [tape_row(item) for item in fixture_states()])
    output = tmp_path / "artifact.json"
    rows_output = tmp_path / "rows.jsonl"

    code = main(
        [
            "--tape",
            str(tape),
            "--output",
            str(output),
            "--grid-rows-output",
            str(rows_output),
        ]
    )

    assert code == 0
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert len(artifact["construction_grid"]) == 32
    assert artifact["totals"]["candidates"] == 4
    rows = [json.loads(line) for line in rows_output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 32
    assert all(row["protocol_id"] == "H-SIG21" for row in rows)
    assert all(row["outcome_join_allowed"] is False for row in rows)
    assert all("magnitude_count" in row and "magnitude" not in row for row in rows)


def test_grid_rows_flattening_preserves_every_cell(tmp_path: Path) -> None:
    del tmp_path
    artifact = build_replay_artifact([fixture_replay()])

    rows = grid_rows(artifact)

    assert [row["cell_id"] for row in rows] == [cell.cell_id for cell in construction_cells()]
    assert sum(row["candidate_count"] for row in rows) == artifact["totals"]["candidates"]


# --------------------------------------------------------------------------------------
# Window-edge proximity diagnostic
# --------------------------------------------------------------------------------------


def test_edge_proximity_covers_every_atomic_type_and_side() -> None:
    edge = build_replay_artifact([fixture_replay()])["window_edge_proximity"]

    assert len(edge["by_atomic_type_side"]) == 16
    assert edge["thresholds_rupees"] == [1.0, 5.0]
    assert edge["measured_candidates"] == 4
    empty = [row for row in edge["by_atomic_type_side"] if row["candidate_count"] == 0]
    assert empty and all(row["share_within_1_rupees"] == 0.0 for row in empty)


def test_edge_proximity_measures_distance_from_the_outermost_occupied_price() -> None:
    # The bid ladder's outer price is 40. An addition at 45 sits 5 rupees inside that rim; an
    # addition at 39 would extend the rim itself and sit exactly on it.
    inside = [
        state(1, bids=[(100.0, 10, 1), (40.0, 10, 1)]),
        state(2, bids=[(100.0, 10, 1), (45.0, 7, 2), (40.0, 10, 1)]),
    ]
    on_rim = [
        state(1, bids=[(100.0, 10, 1), (40.0, 10, 1)]),
        state(2, bids=[(100.0, 10, 1), (40.0, 10, 1), (39.0, 7, 2)]),
    ]

    _, _, _, _, inside_edges = replay_states(inside, instrument_id=INSTRUMENT)
    _, _, _, _, rim_edges = replay_states(on_rim, instrument_id=INSTRUMENT)

    assert inside_edges == [("addition", "bid", 5.0)]
    assert rim_edges == [("addition", "bid", 0.0)]


def test_a_removal_is_measured_against_the_ladder_it_left() -> None:
    states = [
        state(1, bids=[(100.0, 10, 1), (45.0, 10, 1), (40.0, 10, 1)]),
        state(2, bids=[(100.0, 10, 1), (40.0, 10, 1)]),
    ]

    _, _, _, _, edges = replay_states(states, instrument_id=INSTRUMENT)

    assert edges == [("removal", "bid", 5.0)]
