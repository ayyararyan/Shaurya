"""Synthetic, post-registration primitives for the H-SIG21 response design.

The functions in this module are deliberately small and deterministic.  They encode the
registered endpoint timing, event-overlap, quiet-control and ex-ante power gates without
performing inference or reading tapes.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import Literal

from shaurya.data.depth_thinning_analysis import DEPTH20, BookState

NANOSECONDS_PER_SECOND = 1_000_000_000
RESPONSE_GAPS_SECONDS = (0.5, 1.0)
RESPONSE_HORIZONS_SECONDS = (1, 5, 10)
EPISODE_WINDOW_SECONDS = 11
EPISODE_WINDOW_NS = EPISODE_WINDOW_SECONDS * NANOSECONDS_PER_SECOND

# `D34` / `H-SIG21-A1`: the family-maximum window is no longer the primary convention.  It is
# retained under an explicit name because the amendment keeps it as a declared robustness arm and
# because the matched-quiet-control definition still uses 11 s unchanged (that decision is open and
# deferred).  Reading `EPISODE_WINDOW_NS` as "the primary risk-set window" is now wrong; read
# `episode_window_ns(...)` instead.
FAMILY_MAXIMUM_EPISODE_WINDOW_SECONDS = EPISODE_WINDOW_SECONDS
FAMILY_MAXIMUM_EPISODE_WINDOW_NS = EPISODE_WINDOW_NS
INVALID_RESPONSE_QUALITY_FLAGS = frozenset(
    {
        "sequence_gap",
        "sequence_regression",
        "connection_gap",
        "reconnected",
        "heartbeat_timeout",
        "partial_book",
        "crossed_book",
        "invalid_depth",
    }
)


@dataclass(frozen=True, slots=True)
class Depth20ResponseLabel:
    """One registered future-midpoint label plus its separately reported reaction leg."""

    event_id: str
    event_ts_ns: int
    gap_seconds: float
    horizon_seconds: int
    pre_event_source_ts_ns: int
    response_start_source_ts_ns: int
    response_end_source_ts_ns: int
    pre_event_midpoint: float
    response_start_midpoint: float
    response_end_midpoint: float
    contemporaneous_ticks: float
    future_response_ticks: float


@dataclass(frozen=True, slots=True)
class ResponseLabelFailure:
    """An endpoint cell that could not be labelled without violating as-of timing."""

    event_id: str
    gap_seconds: float
    horizon_seconds: int
    reason: str


@dataclass(frozen=True, slots=True)
class ResponseLabelResult:
    labels: tuple[Depth20ResponseLabel, ...]
    failures: tuple[ResponseLabelFailure, ...]


def _seconds_to_ns(seconds: float | int) -> int:
    value = Decimal(str(seconds)) * NANOSECONDS_PER_SECOND
    if value != value.to_integral_value():
        raise ValueError("endpoint seconds must resolve to whole nanoseconds")
    return int(value)


def _midpoint(state: BookState) -> Decimal | None:
    if state.channel != DEPTH20:
        return None
    if (
        set(state.quality_flags) & INVALID_RESPONSE_QUALITY_FLAGS
        or state.best_bid is None
        or state.best_ask is None
    ):
        return None
    bid = Decimal(str(state.best_bid))
    ask = Decimal(str(state.best_ask))
    if bid >= ask:
        return None
    return (bid + ask) / Decimal(2)


def depth20_midpoint(state: BookState) -> Decimal | None:
    """The registered depth20 BBO midpoint, or ``None`` if the state cannot supply one.

    Public accessor over the same rule the label builder uses, so a caller that needs the
    midpoint *path* between two registered endpoints cannot drift from the endpoint convention
    by reimplementing it.
    """

    return _midpoint(state)


def _has_invalid_quality(state: BookState) -> bool:
    return bool(set(state.quality_flags) & INVALID_RESPONSE_QUALITY_FLAGS)


def build_depth20_response_labels(
    *,
    event_id: str,
    event_ts_ns: int,
    depth20_states: Sequence[BookState],
    tick_size: float = 0.05,
    gaps_seconds: tuple[float, ...] = RESPONSE_GAPS_SECONDS,
    horizons_seconds: tuple[int, ...] = RESPONSE_HORIZONS_SECONDS,
    coverage_end_ts_ns: int | None = None,
) -> ResponseLabelResult:
    """Build the registered labels using only the last depth20 state at each endpoint.

    No state after an endpoint can be selected.  The move from the pre-event midpoint to
    ``t + Z`` is retained as ``contemporaneous_ticks`` and is not folded into the predictive
    move from ``t + Z`` to ``t + Z + h``.

    ``coverage_end_ts_ns`` is the last instant the depth20 feed is known to cover.  When it is
    supplied, any cell whose registered endpoint ``t + Z + h`` falls after it is refused with
    ``endpoint_beyond_coverage`` instead of being resolved to a stale earlier observation.  It
    defaults to ``None``, which preserves the previous behaviour exactly for existing callers.

    The guard exists because the as-of rule alone is not safe at the right edge of a finite
    tape: with no coverage bound, an endpoint past the final observation silently resolves back
    to that final observation, which can sit *before* the response start and fabricate a
    zero-return label over a negative realised horizon.  See
    ``docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md``.
    """

    if event_ts_ns < 0:
        raise ValueError("event_ts_ns must be non-negative")
    tick = Decimal(str(tick_size))
    if not tick.is_finite() or tick <= 0:
        raise ValueError("tick_size must be finite and positive")
    if not gaps_seconds or any(gap < 0 for gap in gaps_seconds):
        raise ValueError("gaps_seconds must be non-empty and non-negative")
    if not horizons_seconds or any(horizon <= 0 for horizon in horizons_seconds):
        raise ValueError("horizons_seconds must be non-empty and positive")

    timestamps = [state.receive_ts_ns for state in depth20_states]
    if any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise ValueError("depth20_states must have strictly increasing receive timestamps")

    def as_of(target_ts_ns: int) -> tuple[int, BookState] | None:
        position = bisect_right(timestamps, target_ts_ns) - 1
        return (position, depth20_states[position]) if position >= 0 else None

    pre_event_position = bisect_left(timestamps, event_ts_ns) - 1
    pre_event = (
        (pre_event_position, depth20_states[pre_event_position])
        if pre_event_position >= 0
        else None
    )
    labels: list[Depth20ResponseLabel] = []
    failures: list[ResponseLabelFailure] = []
    for gap in gaps_seconds:
        start_target = event_ts_ns + _seconds_to_ns(gap)
        start = as_of(start_target)
        for horizon in horizons_seconds:
            end_target = start_target + _seconds_to_ns(horizon)
            if coverage_end_ts_ns is not None and end_target > coverage_end_ts_ns:
                failures.append(
                    ResponseLabelFailure(event_id, gap, horizon, "endpoint_beyond_coverage")
                )
                continue
            end = as_of(end_target)
            selected = (pre_event, start, end)
            if any(state is None for state in selected):
                failures.append(
                    ResponseLabelFailure(event_id, gap, horizon, "missing_asof_publication")
                )
                continue
            pre_selected, start_selected, end_selected = selected
            assert (
                pre_selected is not None and start_selected is not None and end_selected is not None
            )
            _, pre = pre_selected
            _, response_start = start_selected
            end_position, response_end = end_selected
            midpoints = (_midpoint(pre), _midpoint(response_start), _midpoint(response_end))
            if any(midpoint is None for midpoint in midpoints):
                failures.append(
                    ResponseLabelFailure(event_id, gap, horizon, "invalid_depth20_asof_state")
                )
                continue
            cell_path = depth20_states[pre_event_position : end_position + 1]
            if any(_has_invalid_quality(state) for state in cell_path):
                failures.append(
                    ResponseLabelFailure(event_id, gap, horizon, "invalid_depth20_path")
                )
                continue
            if len({state.connection_epoch for state in cell_path}) > 1:
                failures.append(
                    ResponseLabelFailure(event_id, gap, horizon, "connection_epoch_boundary")
                )
                continue
            pre_mid, start_mid, end_mid = midpoints
            assert pre_mid is not None and start_mid is not None and end_mid is not None
            labels.append(
                Depth20ResponseLabel(
                    event_id=event_id,
                    event_ts_ns=event_ts_ns,
                    gap_seconds=gap,
                    horizon_seconds=horizon,
                    pre_event_source_ts_ns=pre.receive_ts_ns,
                    response_start_source_ts_ns=response_start.receive_ts_ns,
                    response_end_source_ts_ns=response_end.receive_ts_ns,
                    pre_event_midpoint=float(pre_mid),
                    response_start_midpoint=float(start_mid),
                    response_end_midpoint=float(end_mid),
                    contemporaneous_ticks=float((start_mid - pre_mid) / tick),
                    future_response_ticks=float((end_mid - start_mid) / tick),
                )
            )
    return ResponseLabelResult(tuple(labels), tuple(failures))


@dataclass(frozen=True, slots=True, order=True)
class EpisodeEvent:
    receive_ts_ns: int
    event_id: str


@dataclass(frozen=True, slots=True)
class EventBurst:
    receive_ts_ns: int
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventEpisode:
    """A connected component of overlapping registered predictive windows."""

    start_ts_ns: int
    end_ts_ns: int
    bursts: tuple[EventBurst, ...]

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(event_id for burst in self.bursts for event_id in burst.event_ids)


def episode_window_ns(*, gap_seconds: float, horizon_seconds: int) -> int:
    """The exclusivity window one registered cell needs: its own ``Z + h2``, in nanoseconds.

    ``H-SIG21`` §6 as originally registered bound *every* cell of the 384-cell family to the
    family-maximum endpoint ``Z_max + h2_max = 11 s``.  Amendment ``H-SIG21-A1`` (``D34``,
    approved by Aryan 2026-08-19, committed before any confirmatory tape existed) replaces that
    with each cell's own endpoint.  A cell that predicts one second ahead from a half-second gap
    only needs 1.5 s of exclusivity; charging it 11 s discards risk-set support it never needed.

    On the retained ``DAT-20`` tapes the measured difference at the registered 99.5% threshold is
    260 non-overlapping episodes under a cell's own 1.5 s window against 2 under the 11 s family
    maximum — a factor of 130 between two cells of the same registered family.

    The non-overlapping *principle* is unchanged: episodes remain genuinely non-overlapping for
    the predictive window they are actually used to estimate.  Only the window changes.
    """

    if gap_seconds < 0:
        raise ValueError("gap_seconds must be non-negative")
    if horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive")
    window = _seconds_to_ns(gap_seconds) + _seconds_to_ns(horizon_seconds)
    if window <= 0:
        raise ValueError("the derived episode window must be positive")
    return window


def cluster_event_episodes(
    events: Sequence[EpisodeEvent],
    *,
    window_ns: int = EPISODE_WINDOW_NS,
) -> tuple[EventEpisode, ...]:
    """Collapse exact-timestamp bursts, then connect bursts with overlapping windows.

    ``window_ns`` defaults to the family maximum for backward compatibility, but the registered
    primary convention since ``H-SIG21-A1`` (``D34``) is each cell's own ``Z + h2``: callers
    forming a primary risk set must pass ``episode_window_ns(gap_seconds=..., horizon_seconds=...)``
    and the family-maximum default is a declared robustness comparison, not the primary.
    """

    if window_ns <= 0:
        raise ValueError("window_ns must be positive")
    grouped: defaultdict[int, list[str]] = defaultdict(list)
    for event in events:
        if event.receive_ts_ns < 0:
            raise ValueError("event timestamps must be non-negative")
        grouped[event.receive_ts_ns].append(event.event_id)
    bursts = [
        EventBurst(timestamp, tuple(sorted(event_ids)))
        for timestamp, event_ids in sorted(grouped.items())
    ]
    episodes: list[EventEpisode] = []
    current: list[EventBurst] = []
    current_end = -1
    for burst in bursts:
        if current and burst.receive_ts_ns > current_end:
            episodes.append(EventEpisode(current[0].receive_ts_ns, current_end, tuple(current)))
            current = []
        current.append(burst)
        current_end = max(current_end, burst.receive_ts_ns + window_ns)
    if current:
        episodes.append(EventEpisode(current[0].receive_ts_ns, current_end, tuple(current)))
    return tuple(episodes)


@dataclass(frozen=True, slots=True)
class PrimaryEpisodeSelection:
    selected: tuple[EventEpisode, ...]
    overlap_excluded: tuple[EventEpisode, ...]


def select_primary_non_overlapping_episodes(
    episodes: Sequence[EventEpisode],
) -> PrimaryEpisodeSelection:
    """Greedily retain chronologically first episodes with no shared predictive endpoint.

    **This is the identity on :func:`cluster_event_episodes` output, at every window size.**  The
    clustering step starts a new episode only when a burst begins strictly after the running
    episode's end, so consecutive clustered episodes never share an endpoint and nothing here can
    be excluded.  ``overlap_excluded`` therefore reads zero *by construction*, not by measurement,
    and must never be cited as evidence that overlap exclusion was checked and found unnecessary.

    ``H-SIG21-A1`` (``D34``) re-examined this under the new per-cell window and found the property
    unchanged: shrinking the window shrinks each episode's end but preserves the strict inequality,
    so the composition is still the identity.  The function is deliberately kept rather than
    removed, because it is the guard for episode sets that did *not* come from a single
    ``cluster_event_episodes`` call — a union of per-cell episode sets, a set rebuilt from a stored
    artifact, or a set assembled by any future caller — where episodes genuinely can overlap and
    the exclusion does real work.  ``test_selection_is_the_identity_on_clustered_output`` and
    ``test_selection_excludes_overlap_from_an_externally_assembled_episode_set`` pin both halves.
    """

    selected: list[EventEpisode] = []
    excluded: list[EventEpisode] = []
    last_end: int | None = None
    for episode in sorted(episodes, key=lambda item: (item.start_ts_ns, item.end_ts_ns)):
        if episode.end_ts_ns < episode.start_ts_ns:
            raise ValueError("episode end must not precede episode start")
        if last_end is not None and episode.start_ts_ns <= last_end:
            excluded.append(episode)
            continue
        selected.append(episode)
        last_end = episode.end_ts_ns
    return PrimaryEpisodeSelection(tuple(selected), tuple(excluded))


@dataclass(frozen=True, slots=True)
class PreEventCovariates:
    """The complete registered, outcome-blind covariate vector at one risk-set instant."""

    instrument_id: str
    session_id: str
    time_bucket: str
    regime: str
    receive_ts_ns: int
    midpoint: float
    spread: float
    top20_depth: float
    top20_ofi: float
    recent_return: float
    realised_volatility: float

    def numeric_vector(self) -> tuple[float, ...]:
        values = (
            self.midpoint,
            self.spread,
            self.top20_depth,
            self.top20_ofi,
            self.recent_return,
            self.realised_volatility,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("pre-event covariates must be finite")
        return values


@dataclass(frozen=True, slots=True)
class QuietControlCandidate:
    control_id: str
    covariates: PreEventCovariates
    surrounding_anomaly_ts_ns: tuple[int, ...] = ()

    def is_quiet(self, *, window_ns: int = EPISODE_WINDOW_NS) -> bool:
        return all(
            abs(timestamp - self.covariates.receive_ts_ns) > window_ns
            for timestamp in self.surrounding_anomaly_ts_ns
        )


@dataclass(frozen=True, slots=True)
class ControlMatch:
    event_id: str
    control_id: str
    covariate_distance: float


MatchFailureReason = Literal[
    "no_same_stratum_candidates",
    "no_quiet_same_stratum_candidates",
]


@dataclass(frozen=True, slots=True)
class ControlMatchFailure:
    event_id: str
    reason: MatchFailureReason
    same_stratum_candidates: int
    quiet_candidates: int


@dataclass(frozen=True, slots=True)
class ControlMatchResult:
    match: ControlMatch | None
    failure: ControlMatchFailure | None


def _same_control_stratum(left: PreEventCovariates, right: PreEventCovariates) -> bool:
    return (
        left.instrument_id,
        left.session_id,
        left.time_bucket,
        left.regime,
    ) == (
        right.instrument_id,
        right.session_id,
        right.time_bucket,
        right.regime,
    )


def match_quiet_control(
    *,
    event_id: str,
    event_covariates: PreEventCovariates,
    controls: Sequence[QuietControlCandidate],
    quiet_window_ns: int = EPISODE_WINDOW_NS,
) -> ControlMatchResult:
    """Choose an outcome-blind nearest quiet control from the registered exact strata."""

    if quiet_window_ns <= 0:
        raise ValueError("quiet_window_ns must be positive")
    event_vector = event_covariates.numeric_vector()
    same_stratum = [
        control
        for control in controls
        if _same_control_stratum(event_covariates, control.covariates)
    ]
    if not same_stratum:
        return ControlMatchResult(
            None,
            ControlMatchFailure(event_id, "no_same_stratum_candidates", 0, 0),
        )
    quiet = [control for control in same_stratum if control.is_quiet(window_ns=quiet_window_ns)]
    if not quiet:
        return ControlMatchResult(
            None,
            ControlMatchFailure(
                event_id,
                "no_quiet_same_stratum_candidates",
                len(same_stratum),
                0,
            ),
        )

    control_vectors = [control.covariates.numeric_vector() for control in quiet]
    columns = tuple(zip(event_vector, *control_vectors, strict=True))
    scales = tuple(max(column) - min(column) or 1.0 for column in columns)

    def distance(control: QuietControlCandidate) -> float:
        vector = control.covariates.numeric_vector()
        return sum(
            ((left - right) / scale) ** 2
            for left, right, scale in zip(event_vector, vector, scales, strict=True)
        )

    chosen = min(quiet, key=lambda control: (distance(control), control.control_id))
    return ControlMatchResult(
        ControlMatch(event_id, chosen.control_id, distance(chosen)),
        None,
    )
