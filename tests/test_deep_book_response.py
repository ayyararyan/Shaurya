from __future__ import annotations

from dataclasses import fields

import pytest

from shaurya.data.depth_thinning_analysis import DEPTH20, BookState
from shaurya.signals.deep_book_response import (
    EPISODE_WINDOW_NS,
    ControlMatchFailure,
    EpisodeEvent,
    EventBurst,
    EventEpisode,
    PreEventCovariates,
    QuietControlCandidate,
    build_depth20_response_labels,
    cluster_event_episodes,
    match_quiet_control,
    select_primary_non_overlapping_episodes,
)

SECOND = 1_000_000_000


def depth20_state(
    ts_ns: int,
    midpoint: float,
    *,
    epoch: int = 1,
    flags: tuple[str, ...] = (),
) -> BookState:
    return BookState(
        channel=DEPTH20,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=epoch,
        bids=((midpoint - 0.025, 100, 2),),
        asks=((midpoint + 0.025, 100, 2),),
        rows_in_burst=2,
        quality_flags=flags,
    )


def test_registered_depth20_grid_uses_asof_endpoints_and_separates_reaction() -> None:
    event_ts = SECOND
    states = [
        depth20_state(0, 100.0),
        depth20_state(event_ts + int(0.5 * SECOND), 100.5),
        depth20_state(event_ts + int(0.6 * SECOND), 999.0),
        depth20_state(event_ts + int(1.5 * SECOND), 100.4),
        depth20_state(event_ts + int(2.0 * SECOND), 100.8),
        depth20_state(event_ts + int(5.5 * SECOND), 100.6),
        depth20_state(event_ts + int(6.0 * SECOND), 100.7),
        depth20_state(event_ts + int(10.5 * SECOND), 100.5),
        depth20_state(event_ts + int(11.0 * SECOND), 100.4),
    ]

    result = build_depth20_response_labels(
        event_id="event-1",
        event_ts_ns=event_ts,
        depth20_states=states,
        tick_size=0.05,
    )

    assert not result.failures
    assert {(label.gap_seconds, label.horizon_seconds) for label in result.labels} == {
        (0.5, 1),
        (0.5, 5),
        (0.5, 10),
        (1.0, 1),
        (1.0, 5),
        (1.0, 10),
    }
    label = next(
        item for item in result.labels if item.gap_seconds == 0.5 and item.horizon_seconds == 1
    )
    assert label.response_start_source_ts_ns == event_ts + int(0.5 * SECOND)
    assert label.response_end_source_ts_ns == event_ts + int(1.5 * SECOND)
    assert label.contemporaneous_ticks == pytest.approx(10.0)
    assert label.future_response_ticks == pytest.approx(-2.0)


def test_response_alignment_never_uses_a_publication_after_the_endpoint() -> None:
    states = [
        depth20_state(0, 100.0),
        depth20_state(SECOND, 100.1),
        depth20_state(SECOND + int(0.6 * SECOND), 101.0),
        depth20_state(SECOND + int(1.6 * SECOND), 102.0),
    ]

    result = build_depth20_response_labels(
        event_id="event-1",
        event_ts_ns=SECOND,
        depth20_states=states,
        tick_size=0.05,
        gaps_seconds=(0.5,),
        horizons_seconds=(1,),
    )

    label = result.labels[0]
    assert label.pre_event_source_ts_ns == 0
    assert label.response_start_source_ts_ns == SECOND
    assert label.response_end_source_ts_ns == SECOND + int(0.6 * SECOND)
    assert label.response_start_midpoint == 100.1
    assert label.response_end_midpoint == 101.0


def test_response_cell_fails_explicitly_across_connection_epoch() -> None:
    result = build_depth20_response_labels(
        event_id="event-1",
        event_ts_ns=SECOND,
        depth20_states=[
            depth20_state(0, 100.0),
            depth20_state(2 * SECOND, 100.5, epoch=2),
        ],
        tick_size=0.05,
        gaps_seconds=(0.5,),
        horizons_seconds=(1,),
    )

    assert not result.labels
    assert result.failures[0].reason == "connection_epoch_boundary"


def test_response_cell_rejects_invalid_intermediate_state_not_selected_as_endpoint() -> None:
    result = build_depth20_response_labels(
        event_id="event-1",
        event_ts_ns=SECOND,
        depth20_states=[
            depth20_state(0, 100.0),
            depth20_state(SECOND + 500_000_000, 100.1),
            depth20_state(SECOND + 750_000_000, 100.2, flags=("sequence_gap",)),
            depth20_state(SECOND + 1_500_000_000, 100.3),
        ],
        gaps_seconds=(0.5,),
        horizons_seconds=(1,),
    )

    assert not result.labels
    assert result.failures[0].reason == "invalid_depth20_path"


def test_response_cell_rejects_intermediate_connection_epoch_even_when_endpoints_match() -> None:
    result = build_depth20_response_labels(
        event_id="event-1",
        event_ts_ns=SECOND,
        depth20_states=[
            depth20_state(0, 100.0),
            depth20_state(SECOND + 500_000_000, 100.1),
            depth20_state(SECOND + 750_000_000, 100.2, epoch=2),
            depth20_state(SECOND + 1_500_000_000, 100.3),
        ],
        gaps_seconds=(0.5,),
        horizons_seconds=(1,),
    )

    assert not result.labels
    assert result.failures[0].reason == "connection_epoch_boundary"


def test_receive_time_labels_allow_missing_exchange_timestamps() -> None:
    result = build_depth20_response_labels(
        event_id="event-1",
        event_ts_ns=SECOND,
        depth20_states=[
            depth20_state(0, 100.0, flags=("exchange_timestamp_missing",)),
            depth20_state(2 * SECOND, 100.5, flags=("exchange_timestamp_missing",)),
            depth20_state(3 * SECOND, 100.4, flags=("exchange_timestamp_missing",)),
            depth20_state(7 * SECOND, 100.3, flags=("exchange_timestamp_missing",)),
            depth20_state(12 * SECOND, 100.2, flags=("exchange_timestamp_missing",)),
        ],
    )

    assert len(result.labels) == 6
    assert not result.failures


def test_same_timestamp_changes_form_bursts_and_overlapping_windows_chain() -> None:
    events = [
        EpisodeEvent(0, "b"),
        EpisodeEvent(0, "a"),
        EpisodeEvent(10 * SECOND, "c"),
        EpisodeEvent(20 * SECOND, "d"),
        EpisodeEvent(32 * SECOND, "e"),
    ]

    episodes = cluster_event_episodes(events)

    assert len(episodes) == 2
    assert episodes[0].event_ids == ("a", "b", "c", "d")
    assert episodes[0].start_ts_ns == 0
    assert episodes[0].end_ts_ns == 31 * SECOND
    assert episodes[1].event_ids == ("e",)


def test_primary_episode_selection_reports_overlap_exclusions() -> None:
    def episode(start: int, end: int, event_id: str) -> EventEpisode:
        return EventEpisode(start, end, (EventBurst(start, (event_id,)),))

    first = episode(0, 11, "first")
    touching = episode(11, 22, "touching")
    later = episode(23, 34, "later")

    result = select_primary_non_overlapping_episodes([later, touching, first])

    assert result.selected == (first, later)
    assert result.overlap_excluded == (touching,)


def covariates(
    ts_ns: int,
    *,
    session_id: str = "2026-08-20",
    spread: float = 0.05,
) -> PreEventCovariates:
    return PreEventCovariates(
        instrument_id="NIFTY-FUT-AUG",
        session_id=session_id,
        time_bucket="09:30",
        regime="R1",
        receive_ts_ns=ts_ns,
        midpoint=24_000.0,
        spread=spread,
        top20_depth=10_000.0,
        top20_ofi=0.1,
        recent_return=0.0,
        realised_volatility=0.002,
    )


def test_control_match_uses_exact_strata_and_rejects_nonquiet_candidates() -> None:
    event = covariates(100 * SECOND)
    anomalous_near = QuietControlCandidate(
        "anomalous-near",
        covariates(200 * SECOND, spread=0.051),
        surrounding_anomaly_ts_ns=(200 * SECOND + EPISODE_WINDOW_NS,),
    )
    wrong_session = QuietControlCandidate(
        "wrong-session",
        covariates(300 * SECOND, session_id="2026-08-21"),
    )
    quiet_far = QuietControlCandidate("quiet-far", covariates(400 * SECOND, spread=0.06))
    quiet_near = QuietControlCandidate("quiet-near", covariates(500 * SECOND, spread=0.052))

    result = match_quiet_control(
        event_id="event-1",
        event_covariates=event,
        controls=[anomalous_near, wrong_session, quiet_far, quiet_near],
    )

    assert result.failure is None
    assert result.match is not None
    assert result.match.control_id == "quiet-near"


def test_control_match_returns_explicit_failure_when_no_control_is_quiet() -> None:
    event = covariates(100 * SECOND)
    candidate = QuietControlCandidate(
        "contaminated",
        covariates(200 * SECOND),
        surrounding_anomaly_ts_ns=(200 * SECOND,),
    )

    result = match_quiet_control(
        event_id="event-1",
        event_covariates=event,
        controls=[candidate],
    )

    assert result.match is None
    assert result.failure == ControlMatchFailure(
        event_id="event-1",
        reason="no_quiet_same_stratum_candidates",
        same_stratum_candidates=1,
        quiet_candidates=0,
    )


def test_matching_input_schema_contains_only_registered_pre_event_covariates() -> None:
    names = {item.name for item in fields(PreEventCovariates)}

    assert names == {
        "instrument_id",
        "session_id",
        "time_bucket",
        "regime",
        "receive_ts_ns",
        "midpoint",
        "spread",
        "top20_depth",
        "top20_ofi",
        "recent_return",
        "realised_volatility",
    }
    assert not ({"future", "outcome", "response", "label"} & names)
