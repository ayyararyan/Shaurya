"""Exploratory future-midpoint response scan `X-SIG21-DAT20-01` over the retained DAT-20 tapes.

**This module can never produce a SIG-21 result.** The two retained ``DAT-20`` tapes were
captured at 13:09 and 13:20 IST on 2026-08-19, roughly an hour and fifty minutes *before* the
registering commit ``f2cf6501`` was pushed at 15:00:42 IST. ``H-SIG21`` §1.5 admits only tape
collected after that commit into the first outcome sample, and §1.2 already excludes these
tapes' post-event price paths from SIG-21 inference. They were therefore permanently ineligible
for Confirmed/Falsified status before this module existed, so attaching a response to them now
costs nothing that was not already spent.

What this module is: a declared exploratory scan with the stable ID ``X-SIG21-DAT20-01`` and
``confirmatory_eligible = False``, run at Aryan's explicit direction (voice, 2026-08-19 ~16:42
IST) to find out whether the far-book construction carries any relationship to the later
mid-price at all, and what a candidate model might look like.

What this module is not, and refuses to be presented as: a SIG-21 result, evidence of
predictability, a Confirmed/Falsified verdict, or grounds to modify the immutable 384-cell
registration. :func:`assert_exploratory_claim` turns any such request into a hard failure.

Every threshold computed here is **within sample**. ``H-SIG21`` §5's past-only baseline over
completed prior sessions does not exist for these tapes and is not simulated: every magnitude
cutoff carries the label ``in_sample_exploratory`` and :func:`assert_in_sample_threshold`
refuses any other provenance string.

Working-contract §7.1 object categories are carried on every emitted object.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any, Literal

from shaurya.contracts.timing import NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS
from shaurya.data.depth_thinning_analysis import BookState, percentile
from shaurya.signals.deep_book_anomaly import AtomicEventType, CandidateEvent
from shaurya.signals.deep_book_construction_grid import (
    ConstructionCell,
    construction_cells,
    time_bucket_ist,
)
from shaurya.signals.deep_book_inference import (
    REGISTERED_FAMILY_SIZE,
    REGISTERED_GAPS_SECONDS,
    REGISTERED_HORIZONS_SECONDS,
    REGISTERED_OVERLAP_LAG,
    REGISTERED_THRESHOLDS,
    DistanceBand,
    FamilyCell,
    HacMeanDifference,
    Side,
    canonical_family_manifest,
    hac_newey_west_mean_difference,
    romano_wolf_stepdown,
    stationary_session_block_bootstrap,
)
from shaurya.signals.deep_book_response import (
    EPISODE_WINDOW_NS,
    EPISODE_WINDOW_SECONDS,
    FAMILY_MAXIMUM_EPISODE_WINDOW_NS,
    NANOSECONDS_PER_SECOND,
    ControlMatchFailure,
    EpisodeEvent,
    PreEventCovariates,
    QuietControlCandidate,
    build_depth20_response_labels,
    cluster_event_episodes,
    depth20_midpoint,
    episode_window_ns,
    match_quiet_control,
    select_primary_non_overlapping_episodes,
)

EXPLORATORY_SCAN_ID = "X-SIG21-DAT20-01"
CONFIRMATORY_ELIGIBLE = False
SAMPLE_ROLE = "exploratory_scan_pre_registration_capture"
PROTOCOL_ID = "H-SIG21"
THRESHOLD_PROVENANCE: Literal["in_sample_exploratory"] = "in_sample_exploratory"

# The registering commit and the moment it was pushed, against which §1.5 eligibility is decided.
REGISTERING_COMMIT = "f2cf65011d02882191b5cfda566c1024119964d7"
REGISTERING_COMMIT_TIMESTAMP_IST = "2026-08-19T15:00:42+05:30"

# The only two tapes this scan may ever open, pinned by content hash. Both were captured before
# REGISTERING_COMMIT_TIMESTAMP_IST, which is precisely why they can be looked at and precisely why
# nothing seen in them can ever be confirmatory. Any post-registration calibration tape is refused.
PERMITTED_TAPE_SHA256 = frozenset(
    {
        "751ee15ad5681bd356db06983c86c4aa6fabbcd26ccab356b7e80d77955b71e0",
        "c20590d66631ac3b63748ccbdf172f2e5e2fe81b61b618f3e5df542108c82b82",
    }
)

# NSE NIFTY futures tick. Observed depth20 best quotes on these tapes lie on a Rs 0.10 grid, so
# every midpoint lies on the Rs 0.05 grid and one tick is the smallest representable move.
FUTURES_TICK_SIZE = 0.05
ONE_TICK = 1.0

# A claim naming any of these is a confirmatory or economic claim, which this scan is not
# authorised to make. Whole-word matching, so "unconfirmed" and "falsifiable" are not caught by
# accident and "confirmed"/"falsified" are.
FORBIDDEN_CLAIM_TOKENS = frozenset(
    {
        "admissible",
        "alpha",
        "confirmatory",
        "confirmed",
        "edge",
        "falsified",
        "informative",
        "predictive",
        "profitable",
        "promote",
        "promotion",
        "signal",
        "tradable",
        "tradeable",
        "verdict",
    }
)

SELECTIVITY_GRID: tuple[float, ...] = (
    0.50,
    0.75,
    0.90,
    0.95,
    0.99,
    0.995,
    0.999,
    0.9995,
)

# Extra points bracketing the registered thresholds, so the shape of the episode curve between
# 99.5% and 99.9% is visible rather than interpolated.
SELECTIVITY_GRID_FINE: tuple[float, ...] = (0.996, 0.997, 0.998, 0.9992, 0.9998, 0.9999)

RESPONSE_QUANTILE_PROBABILITIES: tuple[float, ...] = (0.05, 0.25, 0.50, 0.75, 0.95)

BOOTSTRAP_REPLICATES = 399
BOOTSTRAP_SEED = 20260819

# Registered adequacy gates (H-SIG21 §8), reproduced here only to measure the distance to them.
MAX_MEAN_MDE_TICKS = 0.25
MAX_MOVE_PROBABILITY_MDE = 0.05

ObjectCategory = Literal[
    "observed",
    "deterministically_derived",
    "estimated",
    "scenario_based",
    "proxy",
    "unidentified",
]

# H-SIG21 §15.3 sign convention. `side_sign` makes a bid-side event positive and an ask-side event
# negative; `direction_sign` makes displayed liquidity arriving positive and leaving negative.
# Signed magnitude = magnitude x side_sign x direction_sign, so a large bid-side addition is a
# large positive number and a large ask-side addition is a large negative number. The convention
# is descriptive book-pressure bookkeeping and asserts nothing about which way price should move.
_LIQUIDITY_ADDING = frozenset(
    {
        AtomicEventType.ADDITION,
        AtomicEventType.QUANTITY_INCREASE,
        AtomicEventType.ORDER_COUNT_INCREASE,
        AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY,
    }
)


class ConfirmatoryUseRefused(RuntimeError):
    """Raised when this exploratory scan is asked to behave as a confirmatory test."""


class TapeNotPermitted(RuntimeError):
    """Raised when a tape outside the two pre-registration DAT-20 captures is offered."""


class IncompleteFamilyRefused(RuntimeError):
    """Raised when fewer than the complete registered 384 cells are about to be emitted."""


def claim_tokens(name: str) -> frozenset[str]:
    """Split an identifier or phrase into lowercase word tokens for whole-word matching."""

    return frozenset(part for part in re.split(r"[^a-z0-9]+", str(name).strip().lower()) if part)


def assert_exploratory_claim(claims: Iterable[str]) -> None:
    """Refuse any request to dress this scan up as a confirmatory or economic result."""

    offending = sorted({name for name in claims if claim_tokens(name) & FORBIDDEN_CLAIM_TOKENS})
    if offending:
        raise ConfirmatoryUseRefused(
            f"{EXPLORATORY_SCAN_ID} is an exploratory scan with "
            f"confirmatory_eligible={CONFIRMATORY_ELIGIBLE}: its tapes predate the registering "
            f"commit {REGISTERING_COMMIT[:8]} pushed at {REGISTERING_COMMIT_TIMESTAMP_IST}, so "
            f"under {PROTOCOL_ID} §1.5 they were already permanently ineligible for the first "
            "outcome sample and under §1.2 their price paths are excluded from SIG-21 inference. "
            f"Refused claim(s): {', '.join(offending)}."
        )


def assert_permitted_tape(*, run_id: str, tape_sha256: str) -> None:
    """Refuse any tape that is not one of the two pre-registration DAT-20 captures."""

    if tape_sha256 not in PERMITTED_TAPE_SHA256:
        raise TapeNotPermitted(
            f"{EXPLORATORY_SCAN_ID} may only open the two DAT-20 tapes captured before the "
            f"registering commit. Tape {run_id!r} has SHA-256 {tape_sha256}, which is not one of "
            "them. A post-registration calibration tape must never enter this exploratory scan: "
            f"looking at its price path would consume {PROTOCOL_ID}'s first outcome sample."
        )


def assert_in_sample_threshold(provenance: str) -> None:
    """Refuse any threshold that claims a provenance other than within-sample exploratory."""

    if provenance != THRESHOLD_PROVENANCE:
        raise ConfirmatoryUseRefused(
            f"{PROTOCOL_ID} §5 requires an expanding past-only baseline over completed prior "
            "sessions. No completed prior session exists for these tapes, so every cutoff here is "
            f"within sample and must be labelled {THRESHOLD_PROVENANCE!r}; got {provenance!r}."
        )


def assert_complete_family(cell_ids: Sequence[str]) -> None:
    """Refuse to emit a selected, ranked-and-truncated or otherwise partial family."""

    expected = set(canonical_family_manifest().cell_ids)
    observed = set(cell_ids)
    if len(cell_ids) != len(observed):
        raise IncompleteFamilyRefused("the emitted family contains duplicate cell IDs")
    if observed != expected or len(cell_ids) != REGISTERED_FAMILY_SIZE:
        raise IncompleteFamilyRefused(
            f"{PROTOCOL_ID} §7 requires the complete family of {REGISTERED_FAMILY_SIZE} cells to "
            "be reported whether or not a cell is significant. "
            f"missing={len(expected - observed)}, extra={len(observed - expected)}, "
            f"observed={len(cell_ids)}."
        )


# ----------------------------------------------------------------------------------------------
# Within-sample magnitude selectivity
# ----------------------------------------------------------------------------------------------


def construction_cell_of(candidate: CandidateEvent) -> ConstructionCell:
    """The registered construction cell (atomic type x side x distance band) of a candidate."""

    side: Side = "bid" if candidate.side == "bid" else "ask"
    band: DistanceBand = "20_50" if candidate.distance_band == "20_50" else "gt_50"
    return ConstructionCell(candidate.atomic_type, side, band)


@dataclass(frozen=True, slots=True)
class InSampleMagnitudeIndex:
    """Within-sample empirical magnitude percentiles, keyed by construction cell.

    ``H-SIG21`` §5 registers an expanding baseline over *completed prior sessions* keyed on six
    axes.  None of that is available here: there is no completed prior session, and neither the
    past-only liquidity bin nor the ``VOL-04`` regime can be formed from this tape.  This index is
    therefore a deliberately reduced, **within-sample** stand-in on the three construction axes
    only.  It is not the registered baseline, it is never presented as one, and every consumer
    carries the ``in_sample_exploratory`` provenance label.

    The scoring rule is the registered one applied within sample: a candidate's percentile is
    ``bisect_right(sorted magnitudes, magnitude) / n`` and a cutoff ``p`` is crossed when that
    percentile is at least ``p``.  Ties therefore promote or demote whole magnitude values
    together, which is a property of the registered rule and is reported rather than smoothed.
    """

    provenance: Literal["in_sample_exploratory"]
    magnitudes_by_cell: Mapping[str, tuple[float, ...]]

    def percentile_of(self, candidate: CandidateEvent) -> float:
        ordered = self.magnitudes_by_cell.get(construction_cell_of(candidate).cell_id, ())
        if not ordered:
            return 0.0
        return bisect_right(ordered, candidate.magnitude) / len(ordered)

    def crosses(self, candidate: CandidateEvent, cutoff: float) -> bool:
        return self.percentile_of(candidate) >= cutoff

    def cutoff_magnitude(self, cell_id: str, cutoff: float) -> float | None:
        ordered = self.magnitudes_by_cell.get(cell_id, ())
        if not ordered:
            return None
        value = percentile(list(ordered), cutoff)
        return None if value is None else float(value)


def build_in_sample_magnitude_index(
    candidates: Sequence[CandidateEvent],
) -> InSampleMagnitudeIndex:
    """Build the reduced within-sample magnitude distribution for every construction cell."""

    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        grouped[construction_cell_of(candidate).cell_id].append(candidate.magnitude)
    index = InSampleMagnitudeIndex(
        provenance=THRESHOLD_PROVENANCE,
        magnitudes_by_cell={key: tuple(sorted(values)) for key, values in grouped.items()},
    )
    assert_in_sample_threshold(index.provenance)
    return index


def _episode_count(timestamps: Sequence[int], *, window_ns: int) -> int:
    """Non-overlapping registered episodes formed from a set of event timestamps."""

    if not timestamps:
        return 0
    events = [EpisodeEvent(stamp, str(position)) for position, stamp in enumerate(timestamps)]
    episodes = cluster_event_episodes(events, window_ns=window_ns)
    return len(select_primary_non_overlapping_episodes(episodes).selected)


def _gap_summary(gaps: Sequence[float]) -> dict[str, float | int | None]:
    ordered = sorted(gaps)
    return {
        "n": len(ordered),
        "mean": (sum(ordered) / len(ordered)) if ordered else None,
        "median": percentile(ordered, 0.50),
        "p90": percentile(ordered, 0.90),
        "max": ordered[-1] if ordered else None,
    }


@dataclass(frozen=True, slots=True)
class SelectivityPoint:
    """One point of the episode-count-versus-selectivity curve for one grouping."""

    group_id: str
    cutoff: float
    cutoff_magnitude: float | None
    retained_events: int
    retained_bursts: int
    non_overlapping_episodes: int
    capacity_ceiling: int
    capacity_share: float | None
    inter_event_gap_seconds: dict[str, float | int | None]
    inter_burst_gap_seconds: dict[str, float | int | None]
    retained_event_share: float
    retained_burst_share: float


def _selectivity_point(
    *,
    group_id: str,
    cutoff: float,
    cutoff_magnitude: float | None,
    per_tape_retained: Sequence[Sequence[CandidateEvent]],
    total_events: int,
    total_bursts: int,
    capacity_ceiling: int,
    window_ns: int = EPISODE_WINDOW_NS,
) -> SelectivityPoint:
    events = sum(len(group) for group in per_tape_retained)
    bursts = 0
    episodes = 0
    event_gaps: list[float] = []
    burst_gaps: list[float] = []
    for group in per_tape_retained:
        stamps = sorted(candidate.receive_ts_ns for candidate in group)
        distinct = sorted(set(stamps))
        bursts += len(distinct)
        episodes += _episode_count(distinct, window_ns=window_ns)
        event_gaps.extend(
            (later - earlier) / NANOSECONDS_PER_SECOND
            for earlier, later in zip(stamps, stamps[1:], strict=False)
        )
        burst_gaps.extend(
            (later - earlier) / NANOSECONDS_PER_SECOND
            for earlier, later in zip(distinct, distinct[1:], strict=False)
        )
    return SelectivityPoint(
        group_id=group_id,
        cutoff=cutoff,
        cutoff_magnitude=cutoff_magnitude,
        retained_events=events,
        retained_bursts=bursts,
        non_overlapping_episodes=episodes,
        capacity_ceiling=capacity_ceiling,
        capacity_share=(episodes / capacity_ceiling) if capacity_ceiling else None,
        inter_event_gap_seconds=_gap_summary(event_gaps),
        inter_burst_gap_seconds=_gap_summary(burst_gaps),
        retained_event_share=(events / total_events) if total_events else 0.0,
        retained_burst_share=(bursts / total_bursts) if total_bursts else 0.0,
    )


def build_selectivity_curve(
    per_tape_candidates: Sequence[Sequence[CandidateEvent]],
    index: InSampleMagnitudeIndex,
    *,
    observed_seconds_per_tape: Sequence[float],
    cutoffs: Sequence[float] = SELECTIVITY_GRID,
) -> dict[str, Any]:
    """Episode count against within-sample selectivity, pooled and per construction cell.

    This answers, empirically, the question the preceding replay could not: the "2 episodes from
    40,724 candidates" figure was produced with **no threshold applied at all**, whereas the
    registered risk set is built only from anomalies surviving the 99.5%/99.9% tail.  The curve
    shows at what selectivity, if any, the primary risk set stops being degenerate.
    """

    assert_in_sample_threshold(index.provenance)
    capacity = sum(
        int(seconds // EPISODE_WINDOW_SECONDS) for seconds in observed_seconds_per_tape
    )
    total_events = sum(len(group) for group in per_tape_candidates)
    total_bursts = sum(
        len({candidate.receive_ts_ns for candidate in group}) for group in per_tape_candidates
    )
    ordered_cutoffs = sorted(set(cutoffs))
    pooled: list[SelectivityPoint] = []
    for cutoff in ordered_cutoffs:
        retained = [
            [candidate for candidate in group if index.crosses(candidate, cutoff)]
            for group in per_tape_candidates
        ]
        pooled.append(
            _selectivity_point(
                group_id="pooled",
                cutoff=cutoff,
                cutoff_magnitude=None,
                per_tape_retained=retained,
                total_events=total_events,
                total_bursts=total_bursts,
                capacity_ceiling=capacity,
            )
        )
    per_cell: list[SelectivityPoint] = []
    for cell in construction_cells():
        cell_groups = [
            [
                candidate
                for candidate in group
                if construction_cell_of(candidate).cell_id == cell.cell_id
            ]
            for group in per_tape_candidates
        ]
        cell_events = sum(len(group) for group in cell_groups)
        cell_bursts = sum(
            len({candidate.receive_ts_ns for candidate in group}) for group in cell_groups
        )
        for cutoff in ordered_cutoffs:
            retained = [
                [candidate for candidate in group if index.crosses(candidate, cutoff)]
                for group in cell_groups
            ]
            per_cell.append(
                _selectivity_point(
                    group_id=cell.cell_id,
                    cutoff=cutoff,
                    cutoff_magnitude=index.cutoff_magnitude(cell.cell_id, cutoff),
                    per_tape_retained=retained,
                    total_events=cell_events,
                    total_bursts=cell_bursts,
                    capacity_ceiling=capacity,
                )
            )
    # The pooled risk set merges all 32 construction cells' anomalies into one timeline, which is
    # the harshest possible reading. The registered family is estimated cell by cell, so the
    # per-cell totals are the ones the family actually gets. Both are reported; they differ a lot.
    per_cell_totals: list[dict[str, Any]] = []
    for cutoff in ordered_cutoffs:
        members = [point for point in per_cell if point.cutoff == cutoff]
        counts = sorted(float(point.non_overlapping_episodes) for point in members)
        per_cell_totals.append(
            {
                "cutoff": cutoff,
                "summed_over_construction_cells_episodes": int(sum(counts)),
                "cells_with_at_least_one_episode": sum(1 for value in counts if value > 0),
                "median_episodes_per_cell": percentile(counts, 0.50),
                "max_episodes_per_cell": counts[-1] if counts else None,
            }
        )
    degenerate_below = [
        point.cutoff
        for point in pooled
        if point.non_overlapping_episodes <= len(per_tape_candidates)
    ]
    best = max(pooled, key=lambda point: point.non_overlapping_episodes) if pooled else None
    return {
        "object_category": "deterministically_derived",
        "threshold_provenance": index.provenance,
        "episode_window_seconds": EPISODE_WINDOW_SECONDS,
        "capacity_ceiling": capacity,
        "capacity_ceiling_definition": "floor(observed depth200 seconds / 11) summed over tapes",
        "contiguous_tapes": len(per_tape_candidates),
        "cutoffs": list(ordered_cutoffs),
        "pooled": [asdict(point) for point in pooled],
        "per_construction_cell_totals": per_cell_totals,
        "by_construction_cell": [asdict(point) for point in per_cell],
        "degenerate_cutoffs": degenerate_below,
        "max_episode_cutoff": best.cutoff if best is not None else None,
        "max_episode_count": best.non_overlapping_episodes if best is not None else None,
        "note": (
            "A pooled episode count equal to the number of contiguous tapes means the pooled risk "
            "set is degenerate: it is counting tapes, not market structure. The curve is not "
            "monotone in selectivity — episodes rise as surviving bursts separate in time and then "
            "fall again as there are simply too few events left to form separate episodes. Read "
            "the per-cell totals as well: the registered family is estimated cell by cell, and a "
            "single cell's anomalies are far sparser than the union of all 32 cells' anomalies, so "
            "the pooled number understates what any one registered cell actually gets."
        ),
    }


def build_window_decomposition(
    per_tape_candidates: Sequence[Sequence[CandidateEvent]],
    index: InSampleMagnitudeIndex,
    *,
    observed_seconds_per_tape: Sequence[float],
    cutoffs: Sequence[float] = SELECTIVITY_GRID,
) -> dict[str, Any]:
    """Episode counts under each registered ``(Z, h2)`` pair, not only the family maximum.

    ``H-SIG21`` §6 binds the primary risk set to the *largest* registered endpoint, ``Z + h2 =
    11 s``.  A ``Z = 0.5, h2 = 1`` cell only needs 1.5 s of exclusivity, so it is a completely
    different risk set.  Reporting only the 11 s number attributes to the data a collapse that is
    caused by the family-maximum convention.
    """

    assert_in_sample_threshold(index.provenance)
    rows: list[dict[str, Any]] = []
    for cutoff in sorted(set(cutoffs)):
        retained = [
            [candidate for candidate in group if index.crosses(candidate, cutoff)]
            for group in per_tape_candidates
        ]
        for gap in REGISTERED_GAPS_SECONDS:
            for horizon in REGISTERED_HORIZONS_SECONDS:
                window_seconds = gap + horizon
                window_ns = int(round(window_seconds * NANOSECONDS_PER_SECOND))
                episodes = sum(
                    _episode_count(
                        sorted({candidate.receive_ts_ns for candidate in group}),
                        window_ns=window_ns,
                    )
                    for group in retained
                )
                ceiling = sum(
                    int(seconds // window_seconds) for seconds in observed_seconds_per_tape
                )
                rows.append(
                    {
                        "cutoff": cutoff,
                        "gap_seconds": gap,
                        "horizon_seconds": horizon,
                        "window_seconds": window_seconds,
                        "retained_events": sum(len(group) for group in retained),
                        "retained_bursts": sum(
                            len({candidate.receive_ts_ns for candidate in group})
                            for group in retained
                        ),
                        "non_overlapping_episodes": episodes,
                        "capacity_ceiling": ceiling,
                        "capacity_share": (episodes / ceiling) if ceiling else None,
                    }
                )
    return {
        "object_category": "deterministically_derived",
        "threshold_provenance": index.provenance,
        "registered_family_maximum_window_seconds": EPISODE_WINDOW_SECONDS,
        "rows": rows,
        "note": (
            "Each row is the risk set that cell would have if the episode window were bound to "
            "its own Z + h2 rather than the family maximum. H-SIG21 §6 registers the family "
            "maximum, so this is a diagnostic, not an alternative estimate, and nothing in the "
            "registration is changed by reporting it."
        ),
    }


# ----------------------------------------------------------------------------------------------
# Future midpoint responses, attached at burst level
# ----------------------------------------------------------------------------------------------

MAX_HORIZON_SECONDS = max(REGISTERED_HORIZONS_SECONDS)


@dataclass(frozen=True, slots=True)
class ResponseCell:
    """One registered ``(Z, h2)`` endpoint pair evaluated at one burst timestamp."""

    gap_seconds: float
    horizon_seconds: int
    contemporaneous_ticks: float
    future_response_ticks: float
    peak_response_ticks: float
    peak_offset_seconds: float
    response_at_10s_ticks: float | None
    reversion_through_10s_ticks: float | None
    path_observations: int


@dataclass(frozen=True, slots=True)
class BurstResponse:
    """Every registered endpoint pair for one depth200 burst, plus its labelling failures."""

    tape_index: int
    run_id: str
    receive_ts_ns: int
    time_bucket: str
    cells: Mapping[tuple[float, int], ResponseCell]
    failures: tuple[str, ...]


def _midpoint_ticks(state: BookState, *, tick_size: float) -> float | None:
    value = depth20_midpoint(state)
    return None if value is None else float(value) / tick_size


def _path_extremum(
    depth20_states: Sequence[BookState],
    timestamps: Sequence[int],
    *,
    start_ts_ns: int,
    end_ts_ns: int,
    base_ticks: float,
    tick_size: float,
) -> tuple[float, float, int]:
    """Signed extremum of the midpoint path over ``(start, end]``, in ticks from ``base_ticks``.

    Returns ``(peak deviation, seconds from start at which it occurred, observations used)``.
    The path uses only depth20 observations at or before ``end_ts_ns``, so it inherits the
    registered as-of rule and cannot look past the endpoint.
    """

    first = bisect_right(timestamps, start_ts_ns)
    last = bisect_right(timestamps, end_ts_ns)
    peak = 0.0
    offset = 0.0
    used = 0
    for position in range(first, last):
        value = _midpoint_ticks(depth20_states[position], tick_size=tick_size)
        if value is None:
            continue
        used += 1
        deviation = value - base_ticks
        if abs(deviation) > abs(peak):
            peak = deviation
            offset = (timestamps[position] - start_ts_ns) / NANOSECONDS_PER_SECOND
    return peak, offset, used


def attach_burst_responses(
    burst_timestamps: Sequence[int],
    depth20_states: Sequence[BookState],
    *,
    tape_index: int,
    run_id: str,
    tick_size: float = FUTURES_TICK_SIZE,
) -> tuple[tuple[BurstResponse, ...], Counter[str]]:
    """Attach the complete registered response convention to every burst on one tape.

    The contemporaneous path (pre-event midpoint through ``t + Z``) and the predictive response
    (``t + Z`` through ``t + Z + h2``) are carried in separate fields and are never merged, as
    ``H-SIG21`` §2 requires.

    Responses are built **per contiguous tape**.  The two DAT-20 captures are separated by about
    four minutes of no data; resolving an endpoint across that gap would silently label a stale
    pre-gap observation as the endpoint state, so no window is ever allowed to span two tapes.
    """

    timestamps = [state.receive_ts_ns for state in depth20_states]
    coverage_end = timestamps[-1] if timestamps else None
    responses: list[BurstResponse] = []
    failures: Counter[str] = Counter()
    for stamp in burst_timestamps:
        result = build_depth20_response_labels(
            event_id=f"{run_id}:{stamp}",
            event_ts_ns=stamp,
            depth20_states=depth20_states,
            tick_size=tick_size,
            coverage_end_ts_ns=coverage_end,
        )
        for failure in result.failures:
            failures[failure.reason] += 1
        by_key = {(label.gap_seconds, label.horizon_seconds): label for label in result.labels}
        cells: dict[tuple[float, int], ResponseCell] = {}
        for (gap, horizon), label in by_key.items():
            start_ts = label.response_start_source_ts_ns
            base = label.response_start_midpoint / tick_size
            peak, offset, used = _path_extremum(
                depth20_states,
                timestamps,
                start_ts_ns=start_ts,
                end_ts_ns=label.response_end_source_ts_ns,
                base_ticks=base,
                tick_size=tick_size,
            )
            reference = by_key.get((gap, MAX_HORIZON_SECONDS))
            at_ten = reference.future_response_ticks if reference is not None else None
            cells[(gap, horizon)] = ResponseCell(
                gap_seconds=gap,
                horizon_seconds=horizon,
                contemporaneous_ticks=label.contemporaneous_ticks,
                future_response_ticks=label.future_response_ticks,
                peak_response_ticks=peak,
                peak_offset_seconds=offset,
                response_at_10s_ticks=at_ten,
                reversion_through_10s_ticks=(
                    None if at_ten is None else at_ten - peak
                ),
                path_observations=used,
            )
        responses.append(
            BurstResponse(
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=stamp,
                time_bucket=time_bucket_ist(stamp),
                cells=cells,
                failures=tuple(failure.reason for failure in result.failures),
            )
        )
    return tuple(responses), failures


def _summarise_ticks(values: Sequence[float]) -> dict[str, Any]:
    """Complete descriptive summary of a response sample, in futures ticks."""

    ordered = sorted(values)
    n = len(ordered)
    mean = (sum(ordered) / n) if n else None
    variance = (
        (sum((value - mean) ** 2 for value in ordered) / n)
        if n and mean is not None
        else None
    )
    return {
        "n": n,
        "mean_ticks": mean,
        "sd_ticks": sqrt(variance) if variance is not None else None,
        "median_ticks": percentile(ordered, 0.50),
        "quantiles_ticks": {
            f"p{int(round(probability * 100)):02d}": percentile(ordered, probability)
            for probability in RESPONSE_QUANTILE_PROBABILITIES
        },
        "min_ticks": ordered[0] if ordered else None,
        "max_ticks": ordered[-1] if ordered else None,
        "probability_up_at_least_one_tick": (
            sum(1 for value in ordered if value >= ONE_TICK) / n if n else None
        ),
        "probability_down_at_least_one_tick": (
            sum(1 for value in ordered if value <= -ONE_TICK) / n if n else None
        ),
        "probability_no_move": (
            sum(1 for value in ordered if abs(value) < ONE_TICK) / n if n else None
        ),
        "sign_of_mean": (0 if mean is None or mean == 0 else (1 if mean > 0 else -1)),
    }


# ----------------------------------------------------------------------------------------------
# Outcome-blind pre-event covariates and matched quiet controls (H-SIG21 §6)
# ----------------------------------------------------------------------------------------------

RECENT_RETURN_WINDOW_SECONDS = 10
REALISED_VOLATILITY_WINDOW_SECONDS = 60
# No VOL-04 HMM regime is fitted for this instrument-session and fitting one on 22 minutes would
# be within-sample, so the registered regime stratum cannot be formed. It is carried as an
# explicit placeholder rather than silently dropped from the matching key.
REGIME_UNAVAILABLE = "vol04_regime_unavailable"


@dataclass(frozen=True, slots=True)
class CovariateSeries:
    """Past-only depth20 covariates for one contiguous tape, aligned to its observations."""

    run_id: str
    session_id: str
    instrument_id: str
    timestamps: tuple[int, ...]
    midpoint_ticks: tuple[float | None, ...]
    spread_rupees: tuple[float | None, ...]
    top20_depth: tuple[float, ...]
    top20_ofi: tuple[float, ...]

    def as_of_index(self, ts_ns: int) -> int | None:
        position = bisect_right(self.timestamps, ts_ns) - 1
        return position if position >= 0 else None

    def covariates_at(self, ts_ns: int) -> PreEventCovariates | None:
        """The registered matching covariates at an instant, or ``None`` if history is short.

        Every component uses only observations at or before ``ts_ns``.  Nothing here reads a
        future state, so a control chosen with these covariates is chosen without access to any
        response, as §6 requires.
        """

        position = self.as_of_index(ts_ns)
        if position is None:
            return None
        midpoint = self.midpoint_ticks[position]
        spread = self.spread_rupees[position]
        if midpoint is None or spread is None:
            return None
        anchor = self.timestamps[position]
        recent_start = anchor - RECENT_RETURN_WINDOW_SECONDS * NANOSECONDS_PER_SECOND
        volatility_start = anchor - REALISED_VOLATILITY_WINDOW_SECONDS * NANOSECONDS_PER_SECOND
        if volatility_start < self.timestamps[0]:
            return None
        recent_index = bisect_right(self.timestamps, recent_start) - 1
        if recent_index < 0:
            return None
        recent_base = self.midpoint_ticks[recent_index]
        if recent_base is None:
            return None
        window_first = bisect_left(self.timestamps, volatility_start)
        path = [
            value
            for value in self.midpoint_ticks[window_first : position + 1]
            if value is not None
        ]
        if len(path) < 3:
            return None
        steps = [later - earlier for earlier, later in zip(path, path[1:], strict=False)]
        mean_step = sum(steps) / len(steps)
        realised = sqrt(sum((step - mean_step) ** 2 for step in steps) / len(steps))
        return PreEventCovariates(
            instrument_id=self.instrument_id,
            session_id=self.session_id,
            time_bucket=time_bucket_ist(ts_ns),
            regime=REGIME_UNAVAILABLE,
            receive_ts_ns=ts_ns,
            midpoint=midpoint,
            spread=spread,
            top20_depth=self.top20_depth[position],
            top20_ofi=self.top20_ofi[position],
            recent_return=midpoint - recent_base,
            realised_volatility=realised,
        )


def build_covariate_series(
    depth20_states: Sequence[BookState],
    *,
    run_id: str,
    session_id: str,
    instrument_id: str,
    tick_size: float = FUTURES_TICK_SIZE,
) -> CovariateSeries:
    """Build the past-only covariate series for one tape from its depth20 observations.

    ``top20_ofi`` is the change in displayed depth imbalance across the preceding depth20
    transition, ``delta(bid depth) - delta(ask depth)``.  It is a depth-imbalance flow proxy, not
    a message-level order-flow imbalance, because the feed carries no message stream.
    """

    timestamps: list[int] = []
    midpoints: list[float | None] = []
    spreads: list[float | None] = []
    depths: list[float] = []
    ofi: list[float] = []
    previous_bid = 0.0
    previous_ask = 0.0
    for position, state in enumerate(depth20_states):
        timestamps.append(state.receive_ts_ns)
        midpoints.append(_midpoint_ticks(state, tick_size=tick_size))
        spreads.append(
            state.best_ask - state.best_bid
            if state.best_ask is not None and state.best_bid is not None
            else None
        )
        bid_depth = float(sum(quantity for _, quantity, _ in state.bids))
        ask_depth = float(sum(quantity for _, quantity, _ in state.asks))
        depths.append(bid_depth + ask_depth)
        ofi.append(
            0.0 if position == 0 else (bid_depth - previous_bid) - (ask_depth - previous_ask)
        )
        previous_bid = bid_depth
        previous_ask = ask_depth
    return CovariateSeries(
        run_id=run_id,
        session_id=session_id,
        instrument_id=instrument_id,
        timestamps=tuple(timestamps),
        midpoint_ticks=tuple(midpoints),
        spread_rupees=tuple(spreads),
        top20_depth=tuple(depths),
        top20_ofi=tuple(ofi),
    )


@dataclass(frozen=True, slots=True)
class ControlInstant:
    """One candidate quiet control instant with its response and its covariates."""

    control_id: str
    tape_index: int
    run_id: str
    receive_ts_ns: int
    covariates: PreEventCovariates
    response: BurstResponse


def build_control_instants(
    depth20_states: Sequence[BookState],
    series: CovariateSeries,
    *,
    tape_index: int,
    run_id: str,
    tick_size: float = FUTURES_TICK_SIZE,
) -> tuple[ControlInstant, ...]:
    """Every depth20 instant on one tape that could serve as a control, before quietness.

    Quietness is applied later because it depends on which anomaly threshold is in force.  A
    control needs the full registered covariate vector and a complete set of response cells; an
    instant missing either is not a control candidate and is counted as such by the caller.
    """

    stamps = [state.receive_ts_ns for state in depth20_states]
    responses, _ = attach_burst_responses(
        stamps,
        depth20_states,
        tape_index=tape_index,
        run_id=run_id,
        tick_size=tick_size,
    )
    instants: list[ControlInstant] = []
    for response in responses:
        covariates = series.covariates_at(response.receive_ts_ns)
        if covariates is None or not response.cells:
            continue
        instants.append(
            ControlInstant(
                control_id=f"{run_id}:{response.receive_ts_ns}",
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=response.receive_ts_ns,
                covariates=covariates,
                response=response,
            )
        )
    return tuple(instants)


def quiet_control_pool(
    instants: Sequence[ControlInstant],
    anomaly_ts_ns: Sequence[int],
    *,
    window_ns: int = EPISODE_WINDOW_NS,
) -> tuple[QuietControlCandidate, ...]:
    """Restrict control candidates to instants with no retained anomaly within the window."""

    ordered = sorted(anomaly_ts_ns)
    pool: list[QuietControlCandidate] = []
    for instant in instants:
        low = bisect_left(ordered, instant.receive_ts_ns - window_ns)
        high = bisect_right(ordered, instant.receive_ts_ns + window_ns)
        if low != high:
            continue
        pool.append(QuietControlCandidate(instant.control_id, instant.covariates, ()))
    return tuple(pool)


# ----------------------------------------------------------------------------------------------
# Overlap-robust statistics
# ----------------------------------------------------------------------------------------------

# Two-sided normal critical value used for the unadjusted 95% intervals reported alongside the
# Romano-Wolf adjusted p-values. It is the per-cell value and makes no multiplicity allowance.
NORMAL_95_CRITICAL_VALUE = 1.959963984540054


def _bartlett_long_run_variance(values: Sequence[float], *, lag: int) -> float:
    """Bartlett-kernel long-run variance of a mean-zero-centred series."""

    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    residuals = [value - mean for value in values]
    total = sum(value * value for value in residuals) / n
    effective = min(lag, n - 1)
    for offset in range(1, effective + 1):
        covariance = (
            sum(residuals[index] * residuals[index - offset] for index in range(offset, n)) / n
        )
        total += 2.0 * (1.0 - offset / (lag + 1.0)) * covariance
    return max(total, 0.0)


def overlap_lag_observations(
    timestamps: Sequence[int],
    *,
    window_ns: int = EPISODE_WINDOW_NS,
    minimum: int = REGISTERED_OVERLAP_LAG,
) -> int:
    """The largest number of observations whose registered windows overlap one observation.

    ``H-SIG21`` §7 requires a HAC lag "at least the largest overlap".  The overlap is defined in
    seconds; the estimator needs it in observations, so this counts the most observations any
    single registered window can contain and never returns less than the registered floor.
    """

    ordered = sorted(timestamps)
    largest = 0
    for position, stamp in enumerate(ordered):
        end = bisect_right(ordered, stamp + window_ns)
        largest = max(largest, end - position)
    return max(minimum, largest)


@dataclass(frozen=True, slots=True)
class HacMeanEstimate:
    """A sample mean with a Bartlett/Newey-West standard error and an effective sample size."""

    n: int
    distinct_bursts: int
    lag: int
    mean: float | None
    naive_standard_error: float | None
    hac_standard_error: float | None
    t_statistic: float | None
    confidence_low: float | None
    confidence_high: float | None
    n_eff_variance_inflation: float | None
    variance_inflation_factor: float | None


def hac_mean_estimate(
    values: Sequence[float],
    *,
    lag: int,
    distinct_bursts: int,
) -> HacMeanEstimate:
    """Mean of an overlapping response series with dependence-robust precision.

    ``n_eff_variance_inflation`` is the **estimated** effective sample size
    ``n * naive variance / HAC variance``: the number of independent observations that would give
    the same precision.  It is capped at ``n`` and floored at one, and it is an estimate, not a
    count.  The deterministic episode count is reported separately and is the count.
    """

    n = len(values)
    if n == 0:
        return HacMeanEstimate(
            0, distinct_bursts, lag, None, None, None, None, None, None, None, None
        )
    mean = sum(values) / n
    naive_variance = sum((value - mean) ** 2 for value in values) / n
    naive_se = sqrt(naive_variance / n)
    hac_se = sqrt(_bartlett_long_run_variance(values, lag=lag) / n)
    inflation = (hac_se / naive_se) ** 2 if naive_se > 0 else None
    n_eff = None
    if inflation is not None and inflation > 0:
        n_eff = min(float(n), max(1.0, n / inflation))
    t_statistic = mean / hac_se if hac_se > 0 else None
    low = mean - NORMAL_95_CRITICAL_VALUE * hac_se if hac_se > 0 else None
    high = mean + NORMAL_95_CRITICAL_VALUE * hac_se if hac_se > 0 else None
    return HacMeanEstimate(
        n=n,
        distinct_bursts=distinct_bursts,
        lag=lag,
        mean=mean,
        naive_standard_error=naive_se,
        hac_standard_error=hac_se,
        t_statistic=t_statistic,
        confidence_low=low,
        confidence_high=high,
        n_eff_variance_inflation=n_eff,
        variance_inflation_factor=inflation,
    )


@dataclass(frozen=True, slots=True)
class HacRegression:
    """A simple bivariate OLS fit reported with a Bartlett/Newey-West standard error."""

    n: int
    lag: int
    correlation: float | None
    slope: float | None
    intercept: float | None
    naive_standard_error: float | None
    hac_standard_error: float | None
    t_statistic: float | None
    confidence_low: float | None
    confidence_high: float | None
    r_squared: float | None


def hac_simple_regression(
    predictor: Sequence[float],
    response: Sequence[float],
    *,
    lag: int,
) -> HacRegression:
    """Regress ``response`` on ``predictor`` with an overlap-robust standard error.

    The naive standard error is reported alongside deliberately: on overlapping windows the naive
    figure is the one that manufactures significance, and the gap between the two is the point.
    """

    if len(predictor) != len(response):
        raise ValueError("predictor and response must be equally sized")
    n = len(predictor)
    if n < 3:
        return HacRegression(n, lag, None, None, None, None, None, None, None, None, None)
    mean_x = sum(predictor) / n
    mean_y = sum(response) / n
    centred_x = [value - mean_x for value in predictor]
    centred_y = [value - mean_y for value in response]
    sxx = sum(value * value for value in centred_x)
    syy = sum(value * value for value in centred_y)
    if sxx <= 0 or syy <= 0:
        return HacRegression(n, lag, None, None, None, None, None, None, None, None, None)
    sxy = sum(x * y for x, y in zip(centred_x, centred_y, strict=True))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    correlation = sxy / sqrt(sxx * syy)
    residuals = [y - slope * x for x, y in zip(centred_x, centred_y, strict=True)]
    naive_variance = sum(value * value for value in residuals) / max(n - 2, 1)
    naive_se = sqrt(naive_variance / sxx)
    scores = [x * residual for x, residual in zip(centred_x, residuals, strict=True)]
    meat = _bartlett_long_run_variance(scores, lag=lag) * n
    hac_se = sqrt(meat / (sxx * sxx)) if meat > 0 else 0.0
    t_statistic = slope / hac_se if hac_se > 0 else None
    low = slope - NORMAL_95_CRITICAL_VALUE * hac_se if hac_se > 0 else None
    high = slope + NORMAL_95_CRITICAL_VALUE * hac_se if hac_se > 0 else None
    return HacRegression(
        n=n,
        lag=lag,
        correlation=correlation,
        slope=slope,
        intercept=intercept,
        naive_standard_error=naive_se,
        hac_standard_error=hac_se if hac_se > 0 else None,
        t_statistic=t_statistic,
        confidence_low=low,
        confidence_high=high,
        r_squared=correlation * correlation,
    )


# ----------------------------------------------------------------------------------------------
# The complete 384-cell family
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TapeScan:
    """Everything one contiguous tape contributes to the exploratory scan."""

    tape_index: int
    run_id: str
    session_id: str
    instrument_id: str
    tape_sha256: str
    candidates: tuple[CandidateEvent, ...]
    # Rupees from each candidate's price to the outermost occupied price on its own side, aligned
    # positionally with ``candidates``. Used only by the near-boundary-churn negative control.
    edge_distances: tuple[float | None, ...]
    responses_by_ts: Mapping[int, BurstResponse]
    control_instants: tuple[ControlInstant, ...]
    covariates: CovariateSeries
    observed_seconds: float
    label_failures: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CellSeries:
    """The ordered response series of one registered cell, in both registered risk sets."""

    event_values: tuple[float, ...]
    event_timestamps: tuple[int, ...]
    event_sessions: tuple[str, ...]
    episode_values: tuple[float, ...]
    episode_sessions: tuple[str, ...]
    episode_window_seconds: float
    family_maximum_episode_values: tuple[float, ...]
    family_maximum_episode_sessions: tuple[str, ...]
    peak_values: tuple[float, ...]
    reversion_values: tuple[float, ...]
    contemporaneous_values: tuple[float, ...]
    distinct_bursts: int


def _empty_series() -> CellSeries:
    return CellSeries((), (), (), (), (), 0.0, (), (), (), (), (), 0)


def build_cell_series(
    cell: FamilyCell,
    scans: Sequence[TapeScan],
    index: InSampleMagnitudeIndex,
) -> CellSeries:
    """Collect one registered cell's response series in every registered risk set.

    The primary risk set is the ``H-SIG21`` §6 non-overlapping episode set as amended by
    ``H-SIG21-A1`` (``D34``): retained bursts are clustered under **this cell's own** ``Z + h2``
    window, non-overlapping episodes are selected, and each selected episode contributes one
    value, the mean response of its member events.

    The same episodes are built a second time under the original family-maximum 11 s window and
    carried as ``family_maximum_episode_values``.  That arm is the declared robustness comparison
    ``H-SIG21-A1`` requires: it is not deleted, it is not primary, and it reproduces every number
    the pre-amendment primary arm produced.

    The secondary risk set is every retained event, which §6 permits only alongside the primary
    and only with dependence-robust inference.
    """

    key = (cell.gap_seconds, cell.horizon_seconds)
    window_ns = episode_window_ns(
        gap_seconds=cell.gap_seconds, horizon_seconds=cell.horizon_seconds
    )
    event_values: list[float] = []
    event_timestamps: list[int] = []
    event_sessions: list[str] = []
    peaks: list[float] = []
    reversions: list[float] = []
    contemporaneous: list[float] = []
    episode_values: list[float] = []
    episode_sessions: list[str] = []
    family_maximum_values: list[float] = []
    family_maximum_sessions: list[str] = []
    bursts: set[tuple[int, int]] = set()
    for scan in scans:
        by_ts: defaultdict[int, list[float]] = defaultdict(list)
        for candidate in scan.candidates:
            construction = construction_cell_of(candidate)
            if (
                construction.atomic_type is not cell.atomic_type
                or construction.side != cell.side
                or construction.distance_band != cell.distance_band
            ):
                continue
            if not index.crosses(candidate, cell.threshold):
                continue
            response = scan.responses_by_ts.get(candidate.receive_ts_ns)
            if response is None:
                continue
            response_cell = response.cells.get(key)
            if response_cell is None:
                continue
            event_values.append(response_cell.future_response_ticks)
            event_timestamps.append(candidate.receive_ts_ns)
            event_sessions.append(scan.run_id)
            peaks.append(response_cell.peak_response_ticks)
            if response_cell.reversion_through_10s_ticks is not None:
                reversions.append(response_cell.reversion_through_10s_ticks)
            contemporaneous.append(response_cell.contemporaneous_ticks)
            by_ts[candidate.receive_ts_ns].append(response_cell.future_response_ticks)
            bursts.add((scan.tape_index, candidate.receive_ts_ns))
        if not by_ts:
            continue
        stamps = sorted(by_ts)
        events = [EpisodeEvent(stamp, str(stamp)) for stamp in stamps]
        for target_window_ns, values, sessions in (
            (window_ns, episode_values, episode_sessions),
            (FAMILY_MAXIMUM_EPISODE_WINDOW_NS, family_maximum_values, family_maximum_sessions),
        ):
            episodes = cluster_event_episodes(events, window_ns=target_window_ns)
            for episode in select_primary_non_overlapping_episodes(episodes).selected:
                members = [
                    value
                    for burst in episode.bursts
                    for value in by_ts.get(burst.receive_ts_ns, ())
                ]
                if members:
                    values.append(sum(members) / len(members))
                    sessions.append(scan.run_id)
    order = sorted(range(len(event_values)), key=lambda position: event_timestamps[position])
    return CellSeries(
        event_values=tuple(event_values[position] for position in order),
        event_timestamps=tuple(event_timestamps[position] for position in order),
        event_sessions=tuple(event_sessions[position] for position in order),
        episode_values=tuple(episode_values),
        episode_sessions=tuple(episode_sessions),
        episode_window_seconds=window_ns / NANOSECONDS_PER_SECOND,
        family_maximum_episode_values=tuple(family_maximum_values),
        family_maximum_episode_sessions=tuple(family_maximum_sessions),
        peak_values=tuple(peaks[position] for position in order),
        reversion_values=tuple(reversions),
        contemporaneous_values=tuple(contemporaneous[position] for position in order),
        distinct_bursts=len(bursts),
    )


def _bootstrap_t_statistics(
    values: Sequence[float],
    sessions: Sequence[str],
    *,
    lag: int,
    replicates: int,
    seed: int,
) -> tuple[float, ...]:
    """Recentred, studentised block-bootstrap t statistics for one cell.

    The stationary block bootstrap resamples within session only, so no replicate splices two
    contiguous captures together.  Each replicate is recentred on the observed mean, which is what
    makes the resulting distribution a null distribution.
    """

    if len(values) < 3:
        return tuple(0.0 for _ in range(replicates))
    observed_mean = sum(values) / len(values)
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for session, value in zip(sessions, values, strict=True):
        grouped[session].append(value)
    samples = stationary_session_block_bootstrap(
        grouped,
        replicates=replicates,
        mean_block_length=float(max(1, min(lag, len(values)))),
        seed=seed,
    )
    statistics: list[float] = []
    for sample in samples:
        n = len(sample)
        mean = sum(sample) / n
        standard_error = sqrt(_bartlett_long_run_variance(sample, lag=lag) / n)
        statistics.append((mean - observed_mean) / standard_error if standard_error > 0 else 0.0)
    return tuple(statistics)


def _stable_seed(seed: int, cell_id: str) -> int:
    """A deterministic per-cell seed. Scripts may not call ``random`` without one."""

    total = seed
    for character in cell_id:
        total = (total * 131 + ord(character)) % 2_147_483_647
    return total


@dataclass(frozen=True, slots=True)
class ThresholdControlSet:
    """Matched quiet controls for one anomaly threshold, with every failure made explicit."""

    threshold: float
    anomaly_bursts: int
    control_candidates: int
    quiet_candidates: int
    matched: Mapping[tuple[int, int], str]
    control_response_by_id: Mapping[str, BurstResponse]
    failures: tuple[ControlMatchFailure, ...]
    failure_counts: Mapping[str, int]


def build_threshold_controls(
    scans: Sequence[TapeScan],
    index: InSampleMagnitudeIndex,
    *,
    threshold: float,
) -> ThresholdControlSet:
    """Match every retained anomaly instant to a quiet control from the registered strata.

    Quietness is judged against the union of retained anomalies at this same threshold, as §6
    requires: a control instant must have no anomaly in the surrounding 11 seconds.  When the
    retained anomaly set is dense enough that no such instant exists, that is reported as a total
    match failure rather than being weakened into a looser definition of quiet.
    """

    anomaly_ts: list[int] = []
    per_tape_anomalies: dict[int, list[int]] = {}
    for scan in scans:
        stamps = sorted(
            {
                candidate.receive_ts_ns
                for candidate in scan.candidates
                if index.crosses(candidate, threshold)
            }
        )
        per_tape_anomalies[scan.tape_index] = stamps
        anomaly_ts.extend(stamps)
    all_instants = [instant for scan in scans for instant in scan.control_instants]
    pool = quiet_control_pool(all_instants, sorted(anomaly_ts))
    response_by_id = {
        instant.control_id: instant.response
        for instant in all_instants
        if any(instant.control_id == control.control_id for control in pool)
    }
    matched: dict[tuple[int, int], str] = {}
    failures: list[ControlMatchFailure] = []
    counts: Counter[str] = Counter()
    for scan in scans:
        for stamp in per_tape_anomalies[scan.tape_index]:
            covariates = scan.covariates.covariates_at(stamp)
            event_id = f"{scan.run_id}:{stamp}"
            if covariates is None:
                counts["event_covariate_history_insufficient"] += 1
                continue
            result = match_quiet_control(
                event_id=event_id,
                event_covariates=covariates,
                controls=pool,
            )
            if result.match is None:
                assert result.failure is not None
                failures.append(result.failure)
                counts[result.failure.reason] += 1
                continue
            matched[(scan.tape_index, stamp)] = result.match.control_id
    return ThresholdControlSet(
        threshold=threshold,
        anomaly_bursts=len(anomaly_ts),
        control_candidates=len(all_instants),
        quiet_candidates=len(pool),
        matched=matched,
        control_response_by_id=response_by_id,
        failures=tuple(failures),
        failure_counts=dict(counts),
    )


@dataclass(frozen=True, slots=True)
class ControlDifferenceSeries:
    """One cell's paired event and matched-control responses, in event-time order."""

    event_values: tuple[float, ...]
    control_values: tuple[float, ...]
    sessions: tuple[str, ...]
    unmatched_events: int

    @property
    def differences(self) -> tuple[float, ...]:
        return tuple(
            event - control
            for event, control in zip(self.event_values, self.control_values, strict=True)
        )

    def paired_estimate(self, *, lag: int) -> HacMeanDifference | None:
        """The registered paired HAC/Newey-White mean difference, or ``None`` when unmatched.

        This is deliberately the already-registered primitive rather than a local reimplementation:
        the registered estimand is a paired event-minus-control difference and must be estimated by
        the estimator the registration names.
        """

        if not self.event_values:
            return None
        return hac_newey_west_mean_difference(
            self.event_values, self.control_values, lag=max(lag, REGISTERED_OVERLAP_LAG)
        )


def _control_difference_series(
    cell: FamilyCell,
    scans: Sequence[TapeScan],
    index: InSampleMagnitudeIndex,
    controls: ThresholdControlSet,
) -> ControlDifferenceSeries:
    """Event-minus-matched-control pairs for one cell, plus the unmatched event count."""

    key = (cell.gap_seconds, cell.horizon_seconds)
    paired: list[tuple[int, float, float, str]] = []
    unmatched = 0
    for scan in scans:
        for candidate in scan.candidates:
            construction = construction_cell_of(candidate)
            if (
                construction.atomic_type is not cell.atomic_type
                or construction.side != cell.side
                or construction.distance_band != cell.distance_band
                or not index.crosses(candidate, cell.threshold)
            ):
                continue
            response = scan.responses_by_ts.get(candidate.receive_ts_ns)
            if response is None or key not in response.cells:
                continue
            control_id = controls.matched.get((scan.tape_index, candidate.receive_ts_ns))
            if control_id is None:
                unmatched += 1
                continue
            control_response = controls.control_response_by_id.get(control_id)
            control_cell = None if control_response is None else control_response.cells.get(key)
            if control_cell is None:
                unmatched += 1
                continue
            paired.append(
                (
                    candidate.receive_ts_ns,
                    response.cells[key].future_response_ticks,
                    control_cell.future_response_ticks,
                    scan.run_id,
                )
            )
    paired.sort(key=lambda item: item[0])
    return ControlDifferenceSeries(
        event_values=tuple(item[1] for item in paired),
        control_values=tuple(item[2] for item in paired),
        sessions=tuple(item[3] for item in paired),
        unmatched_events=unmatched,
    )


def _arm_payload(
    estimate: HacMeanEstimate,
    summary: dict[str, Any],
    *,
    n_eff_deterministic: float | None,
    n_eff_category: ObjectCategory,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(summary)
    payload.update(
        {
            "distinct_bursts": estimate.distinct_bursts,
            "hac_lag_observations": estimate.lag,
            "naive_standard_error_ticks": estimate.naive_standard_error,
            "hac_standard_error_ticks": estimate.hac_standard_error,
            "t_statistic": estimate.t_statistic,
            "confidence_low_ticks": estimate.confidence_low,
            "confidence_high_ticks": estimate.confidence_high,
            "confidence_half_width_ticks": (
                None
                if estimate.hac_standard_error is None
                else NORMAL_95_CRITICAL_VALUE * estimate.hac_standard_error
            ),
            "variance_inflation_factor": estimate.variance_inflation_factor,
            "n_eff_estimated_variance_inflation": estimate.n_eff_variance_inflation,
            "n_eff_deterministic": n_eff_deterministic,
            "n_eff_object_category": n_eff_category,
        }
    )
    return payload


def build_response_family(
    scans: Sequence[TapeScan],
    index: InSampleMagnitudeIndex,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """The complete registered 384-cell family, reported whether or not a cell is interesting.

    Four arms are reported side by side and never silently substituted for one another:

    ``primary_non_overlapping_episodes``
        the ``H-SIG21`` §6 primary risk set as amended by ``H-SIG21-A1`` (``D34``), one value per
        selected non-overlapping episode formed under **each cell's own** ``Z + h2`` window;
    ``robustness_family_maximum_episodes``
        the same risk set formed under the original family-maximum 11 s window.  This is the
        declared robustness comparison the amendment requires and reproduces the pre-amendment
        primary arm exactly.  It is never promoted to primary;
    ``secondary_all_event_overlap_robust``
        the §6-permitted supplement over every retained event, with HAC/Newey-West inference;
    ``event_minus_matched_control``
        the registered primary *estimand*, which exists only where a quiet control could be
        matched at all.  Its quiet window is **unchanged at 11 s**: ``H-SIG21-A1`` deliberately
        leaves the matched-quiet-control definition alone because Aryan deferred that decision.

    Romano-Wolf step-down is applied over the complete family separately for each arm.
    """

    assert_in_sample_threshold(index.provenance)
    manifest = canonical_family_manifest()
    controls = {
        threshold: build_threshold_controls(scans, index, threshold=threshold)
        for threshold in REGISTERED_THRESHOLDS
    }
    series_by_cell: dict[str, CellSeries] = {}
    difference_by_cell: dict[str, ControlDifferenceSeries] = {}
    for cell in manifest.cells:
        series_by_cell[cell.cell_id] = build_cell_series(cell, scans, index)
        difference_by_cell[cell.cell_id] = _control_difference_series(
            cell, scans, index, controls[cell.threshold]
        )

    arms = (
        "primary_non_overlapping_episodes",
        "robustness_family_maximum_episodes",
        "secondary_all_event_overlap_robust",
        "event_minus_matched_control",
    )
    observed_t: dict[str, dict[str, float]] = {arm: {} for arm in arms}
    bootstrap_t: dict[str, list[dict[str, float]]] = {
        arm: [{} for _ in range(replicates)] for arm in arms
    }
    estimates: dict[str, dict[str, HacMeanEstimate]] = {arm: {} for arm in arms}

    paired_estimates: dict[str, HacMeanDifference | None] = {}
    for cell in manifest.cells:
        series = series_by_cell[cell.cell_id]
        control_series = difference_by_cell[cell.cell_id]
        differences = control_series.differences
        difference_sessions = control_series.sessions
        event_lag = overlap_lag_observations(series.event_timestamps)
        paired_estimates[cell.cell_id] = control_series.paired_estimate(lag=event_lag)
        payloads: dict[str, tuple[Sequence[float], Sequence[str], int, int]] = {
            "primary_non_overlapping_episodes": (
                series.episode_values,
                series.episode_sessions,
                REGISTERED_OVERLAP_LAG,
                len(series.episode_values),
            ),
            "robustness_family_maximum_episodes": (
                series.family_maximum_episode_values,
                series.family_maximum_episode_sessions,
                REGISTERED_OVERLAP_LAG,
                len(series.family_maximum_episode_values),
            ),
            "secondary_all_event_overlap_robust": (
                series.event_values,
                series.event_sessions,
                event_lag,
                series.distinct_bursts,
            ),
            "event_minus_matched_control": (
                differences,
                difference_sessions,
                event_lag,
                len(differences),
            ),
        }
        for arm, (values, sessions, lag, bursts) in payloads.items():
            estimate = hac_mean_estimate(values, lag=lag, distinct_bursts=bursts)
            estimates[arm][cell.cell_id] = estimate
            observed_t[arm][cell.cell_id] = (
                estimate.t_statistic if estimate.t_statistic is not None else 0.0
            )
            replicate_t = _bootstrap_t_statistics(
                values,
                sessions,
                lag=lag,
                replicates=replicates,
                seed=_stable_seed(seed, f"{arm}|{cell.cell_id}"),
            )
            for position, value in enumerate(replicate_t):
                bootstrap_t[arm][position][cell.cell_id] = value

    adjusted: dict[str, dict[str, float]] = {}
    ranks: dict[str, dict[str, int]] = {}
    critical_values: dict[str, float] = {}
    for arm in arms:
        stepdown = romano_wolf_stepdown(manifest, observed_t[arm], bootstrap_t[arm])
        adjusted[arm] = {row.cell_id: row.adjusted_p_value for row in stepdown}
        ranks[arm] = {row.cell_id: row.stepdown_rank for row in stepdown}
        # The 95th percentile of the bootstrap max-|t| distribution is the family-wide critical
        # value a single cell must clear once the 384-cell search is paid for.
        maxima = sorted(
            max(abs(value) for value in replicate.values()) for replicate in bootstrap_t[arm]
        )
        critical_values[arm] = percentile(maxima, 0.95) or NORMAL_95_CRITICAL_VALUE

    rows: list[dict[str, Any]] = []
    for cell in manifest.cells:
        series = series_by_cell[cell.cell_id]
        control_series = difference_by_cell[cell.cell_id]
        differences = control_series.differences
        unmatched = control_series.unmatched_events
        control_set = controls[cell.threshold]
        row: dict[str, Any] = {
            "cell_id": cell.cell_id,
            "atomic_type": cell.atomic_type.value,
            "side": cell.side,
            "distance_band": cell.distance_band,
            "threshold": cell.threshold,
            "threshold_provenance": THRESHOLD_PROVENANCE,
            "gap_seconds": cell.gap_seconds,
            "horizon_seconds": cell.horizon_seconds,
            "episode_window_seconds": series.episode_window_seconds,
            "family_maximum_episode_window_seconds": float(EPISODE_WINDOW_SECONDS),
            "family_size": REGISTERED_FAMILY_SIZE,
            "object_category": "estimated",
            "contemporaneous_path_ticks": _summarise_ticks(series.contemporaneous_values),
            "peak_response_ticks": _summarise_ticks(series.peak_values),
            "reversion_through_10s_ticks": _summarise_ticks(series.reversion_values),
            "matched_control_unmatched_events": unmatched,
            "matched_control_quiet_candidates": control_set.quiet_candidates,
        }
        row["arms"] = {
            "robustness_family_maximum_episodes": _arm_payload(
                estimates["robustness_family_maximum_episodes"][cell.cell_id],
                _summarise_ticks(series.family_maximum_episode_values),
                n_eff_deterministic=float(len(series.family_maximum_episode_values)),
                n_eff_category="deterministically_derived",
            ),
            "primary_non_overlapping_episodes": _arm_payload(
                estimates["primary_non_overlapping_episodes"][cell.cell_id],
                _summarise_ticks(series.episode_values),
                n_eff_deterministic=float(len(series.episode_values)),
                n_eff_category="deterministically_derived",
            ),
            "secondary_all_event_overlap_robust": _arm_payload(
                estimates["secondary_all_event_overlap_robust"][cell.cell_id],
                _summarise_ticks(series.event_values),
                n_eff_deterministic=float(len(series.episode_values)),
                n_eff_category="deterministically_derived",
            ),
            "event_minus_matched_control": _arm_payload(
                estimates["event_minus_matched_control"][cell.cell_id],
                _summarise_ticks(differences),
                n_eff_deterministic=None,
                n_eff_category="unidentified",
            ),
        }
        paired = paired_estimates[cell.cell_id]
        # The registered paired estimator is reported alongside the arm payload and cross-checked
        # against it, so the two can never silently disagree.
        row["arms"]["event_minus_matched_control"]["registered_paired_estimator"] = (
            None
            if paired is None
            else {
                "n": paired.n,
                "lag": paired.lag,
                "mean_difference_ticks": paired.mean_difference,
                "standard_error_ticks": paired.standard_error,
                "t_statistic": paired.t_statistic,
                "agrees_with_arm_mean": (
                    estimates["event_minus_matched_control"][cell.cell_id].mean is not None
                    and abs(
                        paired.mean_difference
                        - float(
                            estimates["event_minus_matched_control"][cell.cell_id].mean or 0.0
                        )
                    )
                    <= 1e-9
                ),
            }
        )
        for arm in arms:
            row["arms"][arm]["romano_wolf_adjusted_p_value"] = adjusted[arm][cell.cell_id]
            row["arms"][arm]["romano_wolf_rank"] = ranks[arm][cell.cell_id]
        rows.append(row)

    assert_complete_family([row["cell_id"] for row in rows])
    return {
        "object_category": "estimated",
        "exploratory_scan_id": EXPLORATORY_SCAN_ID,
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "family_size": REGISTERED_FAMILY_SIZE,
        "threshold_provenance": THRESHOLD_PROVENANCE,
        "bootstrap_replicates": replicates,
        "bootstrap_seed": seed,
        "arms": list(arms),
        "family_critical_values": critical_values,
        "family_critical_value_note": (
            "The 95th percentile of the bootstrap max-|t| distribution over all 384 cells. A "
            "per-cell |t| of 1.96 is not enough once the family is paid for; this is the bar."
        ),
        "episode_window_convention": "per_cell_z_plus_h2",
        "episode_window_amendment": "H-SIG21-A1",
        "arm_note": (
            "The registered primary risk set is the non-overlapping episode set formed under "
            "each cell's own Z + h2 window (H-SIG21-A1 / D34). The family-maximum 11 s arm is "
            "retained beside it as the declared robustness comparison and reproduces the "
            "pre-amendment primary arm exactly; it is never promoted to primary. The "
            "all-event arm is the §6-permitted supplement and is reported alongside it, never in "
            "place of it. The event-minus-matched-control arm is the registered estimand and "
            "exists only where a quiet control could be matched."
        ),
        "control_sets": [
            {
                "threshold": control_set.threshold,
                "retained_anomaly_bursts": control_set.anomaly_bursts,
                "control_candidate_instants": control_set.control_candidates,
                "quiet_control_instants": control_set.quiet_candidates,
                "matched_events": len(control_set.matched),
                "match_failure_counts": dict(control_set.failure_counts),
                "regime_stratum": REGIME_UNAVAILABLE,
                "regime_note": (
                    "H-SIG21 §6 matches on instrument, session, 30-minute bucket and VOL-04 "
                    "regime. No VOL-04 regime label exists for this instrument-session, so the "
                    "regime axis is a constant placeholder and the match is on three axes, not "
                    "four. Every control is therefore weaker than the registered design requires."
                ),
            }
            for control_set in controls.values()
        ],
        "cells": rows,
    }


# ----------------------------------------------------------------------------------------------
# Correlation structure (Aryan's explicit request)
# ----------------------------------------------------------------------------------------------

EVENT_PREDICTORS: tuple[str, ...] = (
    "magnitude",
    "signed_magnitude",
    "distance_from_touch_rupees",
    "order_count_change",
)
BURST_PREDICTORS: tuple[str, ...] = (
    "burst_candidate_count",
    "burst_total_magnitude",
    "burst_signed_magnitude",
    "burst_side_imbalance",
)


def signed_magnitude(candidate: CandidateEvent) -> float:
    """Magnitude signed by side and by whether displayed liquidity arrived or left.

    Sign convention (working contract §15.3): ``+`` for the bid side, ``-`` for the ask side,
    multiplied by ``+`` when displayed liquidity arrives and ``-`` when it leaves.  A large
    bid-side addition is therefore a large positive number and a large bid-side removal a large
    negative one.  This is descriptive book-pressure bookkeeping.  It asserts nothing about the
    direction price should move and is not a theory-aligned estimand.
    """

    side_sign = 1.0 if candidate.side == "bid" else -1.0
    direction_sign = 1.0 if candidate.atomic_type in _LIQUIDITY_ADDING else -1.0
    return candidate.magnitude * side_sign * direction_sign


def event_predictor_values(candidate: CandidateEvent) -> dict[str, float]:
    return {
        "magnitude": candidate.magnitude,
        "signed_magnitude": signed_magnitude(candidate),
        "distance_from_touch_rupees": candidate.distance_rupees,
        "order_count_change": float(candidate.orders_after - candidate.orders_before),
    }


def burst_predictor_values(
    candidates: Sequence[CandidateEvent],
) -> dict[str, float]:
    """Burst-level aggregates of one receive-timestamp cluster (``H-SIG21`` §6)."""

    if not candidates:
        return dict.fromkeys(BURST_PREDICTORS, 0.0)
    bid = sum(1 for candidate in candidates if candidate.side == "bid")
    total = len(candidates)
    return {
        "burst_candidate_count": float(total),
        "burst_total_magnitude": float(sum(candidate.magnitude for candidate in candidates)),
        "burst_signed_magnitude": float(
            sum(signed_magnitude(candidate) for candidate in candidates)
        ),
        "burst_side_imbalance": (2.0 * bid - total) / total,
    }


def _block_index(ts_ns: int, origin_ns: int, *, window_ns: int = EPISODE_WINDOW_NS) -> int:
    return (ts_ns - origin_ns) // window_ns


@dataclass(frozen=True, slots=True)
class PredictorObservation:
    tape_index: int
    run_id: str
    receive_ts_ns: int
    block: int
    construction_cell_id: str
    predictors: Mapping[str, float]
    responses: Mapping[tuple[float, int], float]


def build_predictor_observations(scans: Sequence[TapeScan]) -> tuple[PredictorObservation, ...]:
    """One observation per candidate, carrying its predictors and every registered response."""

    observations: list[PredictorObservation] = []
    for scan in scans:
        if not scan.candidates:
            continue
        origin = min(candidate.receive_ts_ns for candidate in scan.candidates)
        by_ts: defaultdict[int, list[CandidateEvent]] = defaultdict(list)
        for candidate in scan.candidates:
            by_ts[candidate.receive_ts_ns].append(candidate)
        burst_values = {stamp: burst_predictor_values(group) for stamp, group in by_ts.items()}
        for candidate in scan.candidates:
            response = scan.responses_by_ts.get(candidate.receive_ts_ns)
            if response is None or not response.cells:
                continue
            predictors = dict(event_predictor_values(candidate))
            predictors.update(burst_values[candidate.receive_ts_ns])
            observations.append(
                PredictorObservation(
                    tape_index=scan.tape_index,
                    run_id=scan.run_id,
                    receive_ts_ns=candidate.receive_ts_ns,
                    block=_block_index(candidate.receive_ts_ns, origin),
                    construction_cell_id=construction_cell_of(candidate).cell_id,
                    predictors=predictors,
                    responses={
                        key: cell.future_response_ticks for key, cell in response.cells.items()
                    },
                )
            )
    return tuple(observations)


def build_past_return_observations(
    scans: Sequence[TapeScan],
    past_returns: Mapping[tuple[int, int], Mapping[tuple[float, int], float]],
) -> tuple[PredictorObservation, ...]:
    """The same predictors against the mirror-image *past* return instead of the future one.

    This is the correlation-side negative control.  A predictor that is genuinely forward-looking
    must not explain the return over the window that closed before the event; one that merely
    tracks the session's drift or reacts to a move already under way will explain it just as well.
    """

    rebuilt: list[PredictorObservation] = []
    for observation in build_predictor_observations(scans):
        past = past_returns.get((observation.tape_index, observation.receive_ts_ns))
        if not past:
            continue
        rebuilt.append(
            PredictorObservation(
                tape_index=observation.tape_index,
                run_id=observation.run_id,
                receive_ts_ns=observation.receive_ts_ns,
                block=observation.block,
                construction_cell_id=observation.construction_cell_id,
                predictors=observation.predictors,
                responses=dict(past),
            )
        )
    return tuple(rebuilt)


def build_contemporaneous_observations(
    scans: Sequence[TapeScan],
) -> tuple[PredictorObservation, ...]:
    """The same predictors against the contemporaneous leg, the pre-event midpoint through t+Z.

    ``H-SIG21`` §2 keeps this leg descriptive and out of any predictive verdict.  It is used here
    only as the third column of the identification argument: a predictor that is simply reacting
    to a move already under way in the last half second will explain this leg, whichever way the
    past and future columns come out.
    """

    return tuple(
        PredictorObservation(
            tape_index=observation.tape_index,
            run_id=observation.run_id,
            receive_ts_ns=observation.receive_ts_ns,
            block=observation.block,
            construction_cell_id=observation.construction_cell_id,
            predictors=observation.predictors,
            responses={
                key: cell.contemporaneous_ticks
                for key, cell in scan.responses_by_ts[observation.receive_ts_ns].cells.items()
            },
        )
        for scan in scans
        for observation in build_predictor_observations([scan])
    )


def _correlation_row(
    observations: Sequence[PredictorObservation],
    *,
    group_id: str,
    predictor: str,
    key: tuple[float, int],
) -> dict[str, Any]:
    """Event-level naive fit and non-overlapping block-level overlap-robust fit, side by side."""

    xs: list[float] = []
    ys: list[float] = []
    blocks: defaultdict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for observation in observations:
        value = observation.responses.get(key)
        if value is None:
            continue
        x = observation.predictors[predictor]
        xs.append(x)
        ys.append(value)
        blocks[(observation.tape_index, observation.block)].append((x, value))
    naive = hac_simple_regression(xs, ys, lag=REGISTERED_OVERLAP_LAG) if len(xs) >= 3 else None
    block_x: list[float] = []
    block_y: list[float] = []
    for _, members in sorted(blocks.items()):
        block_x.append(sum(item[0] for item in members) / len(members))
        block_y.append(sum(item[1] for item in members) / len(members))
    block_fit = (
        hac_simple_regression(block_x, block_y, lag=REGISTERED_OVERLAP_LAG)
        if len(block_x) >= 3
        else None
    )
    return {
        "group_id": group_id,
        "predictor": predictor,
        "gap_seconds": key[0],
        "horizon_seconds": key[1],
        "event_level": {
            "n": len(xs),
            "correlation": None if naive is None else naive.correlation,
            "slope_ticks_per_unit": None if naive is None else naive.slope,
            "naive_standard_error": None if naive is None else naive.naive_standard_error,
            "naive_t_statistic": (
                None
                if naive is None or naive.slope is None or not naive.naive_standard_error
                else naive.slope / naive.naive_standard_error
            ),
            "r_squared": None if naive is None else naive.r_squared,
            "inference_valid": False,
            "inference_note": (
                "Event-level windows overlap almost completely, so this standard error is "
                "invalid and is reported only to show how large the naive figure looks."
            ),
        },
        "non_overlapping_block_level": {
            "n_blocks": len(block_x),
            "block_seconds": EPISODE_WINDOW_SECONDS,
            "correlation": None if block_fit is None else block_fit.correlation,
            "slope_ticks_per_unit": None if block_fit is None else block_fit.slope,
            "hac_standard_error": None if block_fit is None else block_fit.hac_standard_error,
            "t_statistic": None if block_fit is None else block_fit.t_statistic,
            "confidence_low": None if block_fit is None else block_fit.confidence_low,
            "confidence_high": None if block_fit is None else block_fit.confidence_high,
            "r_squared": None if block_fit is None else block_fit.r_squared,
            "inference_valid": True,
        },
    }


def build_correlation_tables(
    observations: Sequence[PredictorObservation],
) -> dict[str, Any]:
    """Correlation and simple regression of the future midpoint return on every predictor.

    Reported pooled and for each of the 32 construction cells, for all six registered ``(Z, h2)``
    pairs and all eight predictors, complete and unfiltered.
    """

    predictors = EVENT_PREDICTORS + BURST_PREDICTORS
    keys = [
        (gap, horizon)
        for gap in REGISTERED_GAPS_SECONDS
        for horizon in REGISTERED_HORIZONS_SECONDS
    ]
    rows: list[dict[str, Any]] = []
    for predictor in predictors:
        for key in keys:
            rows.append(
                _correlation_row(observations, group_id="pooled", predictor=predictor, key=key)
            )
    by_cell: defaultdict[str, list[PredictorObservation]] = defaultdict(list)
    for observation in observations:
        by_cell[observation.construction_cell_id].append(observation)
    for cell in construction_cells():
        members = by_cell.get(cell.cell_id, [])
        for predictor in predictors:
            for key in keys:
                rows.append(
                    _correlation_row(
                        members, group_id=cell.cell_id, predictor=predictor, key=key
                    )
                )
    return {
        "object_category": "estimated",
        "predictors": list(predictors),
        "sign_convention": (
            "signed_magnitude = magnitude x (+1 bid / -1 ask) x (+1 liquidity arriving / -1 "
            "liquidity leaving). Descriptive book-pressure bookkeeping only."
        ),
        "rows": rows,
        "note": (
            "Two fits are reported for every row. The event-level fit uses every candidate and "
            "carries a naive standard error that is not valid under near-total window overlap; it "
            "is shown so the inflation is visible. The block-level fit averages within "
            "non-overlapping 11 s blocks, which removes the overlap by construction, and is the "
            "one to read."
        ),
    }


# ----------------------------------------------------------------------------------------------
# Registered negative controls (H-SIG21 §7)
# ----------------------------------------------------------------------------------------------

NEAR_BOUNDARY_RUPEES = 1.0
NEGATIVE_CONTROL_SEED = 20260819


@dataclass(frozen=True, slots=True)
class PlaceboObservation:
    """One (cell, instant, value) triple feeding a negative control's complete-family summary."""

    cell_id: str
    receive_ts_ns: int
    run_id: str
    value: float


def _summarise_placebo_family(
    observations: Sequence[PlaceboObservation],
    *,
    name: str,
    description: str,
    interpretation: str,
) -> dict[str, Any]:
    """Summarise a negative control over the complete 384-cell family, nothing filtered."""

    grouped: defaultdict[str, list[tuple[int, float, str]]] = defaultdict(list)
    for observation in observations:
        grouped[observation.cell_id].append(
            (observation.receive_ts_ns, observation.value, observation.run_id)
        )
    manifest = canonical_family_manifest()
    rows: list[dict[str, Any]] = []
    significant = 0
    largest = 0.0
    for cell_id in manifest.cell_ids:
        members = sorted(grouped.get(cell_id, []))
        values = [item[1] for item in members]
        stamps = [item[0] for item in members]
        lag = overlap_lag_observations(stamps)
        estimate = hac_mean_estimate(values, lag=lag, distinct_bursts=len(set(stamps)))
        t_statistic = estimate.t_statistic
        if t_statistic is not None:
            largest = max(largest, abs(t_statistic))
            if abs(t_statistic) > NORMAL_95_CRITICAL_VALUE:
                significant += 1
        rows.append(
            {
                "cell_id": cell_id,
                "n": estimate.n,
                "mean_ticks": estimate.mean,
                "hac_standard_error_ticks": estimate.hac_standard_error,
                "t_statistic": t_statistic,
                "confidence_low_ticks": estimate.confidence_low,
                "confidence_high_ticks": estimate.confidence_high,
                "n_eff_estimated_variance_inflation": estimate.n_eff_variance_inflation,
            }
        )
    assert_complete_family([row["cell_id"] for row in rows])
    return {
        "name": name,
        "object_category": "estimated",
        "description": description,
        "interpretation": interpretation,
        "family_size": REGISTERED_FAMILY_SIZE,
        "cells_reported": len(rows),
        "cells_with_absolute_t_over_1p96": significant,
        "share_of_family_nominally_significant": significant / REGISTERED_FAMILY_SIZE,
        "max_absolute_t": largest,
        "cells": rows,
    }


def _retained_events(
    scans: Sequence[TapeScan],
    index: InSampleMagnitudeIndex,
) -> list[tuple[TapeScan, int, CandidateEvent, float | None]]:
    """Every candidate crossing either registered threshold, with its tape and edge distance."""

    retained: list[tuple[TapeScan, int, CandidateEvent, float | None]] = []
    lowest = min(REGISTERED_THRESHOLDS)
    for scan in scans:
        for position, candidate in enumerate(scan.candidates):
            if index.crosses(candidate, lowest):
                edge = (
                    scan.edge_distances[position]
                    if position < len(scan.edge_distances)
                    else None
                )
                retained.append((scan, position, candidate, edge))
    return retained


def _cell_id_for(
    candidate: CandidateEvent,
    *,
    threshold: float,
    gap: float,
    horizon: int,
    side_override: Side | None = None,
) -> str:
    construction = construction_cell_of(candidate)
    return FamilyCell(
        construction.atomic_type,
        side_override if side_override is not None else construction.side,
        construction.distance_band,
        threshold,
        gap,
        horizon,
    ).cell_id


def _deterministic_permutation(size: int, seed: int) -> list[int]:
    """A reproducible permutation without touching the global random state."""

    order = list(range(size))
    state = seed % 2_147_483_647 or 1
    for position in range(size - 1, 0, -1):
        state = (state * 48_271) % 2_147_483_647
        swap = state % (position + 1)
        order[position], order[swap] = order[swap], order[position]
    return order


def build_negative_controls(
    scans: Sequence[TapeScan],
    index: InSampleMagnitudeIndex,
    *,
    past_returns_by_ts: Mapping[tuple[int, int], Mapping[tuple[float, int], float]],
    control_sets: Mapping[float, ThresholdControlSet],
    seed: int = NEGATIVE_CONTROL_SEED,
) -> dict[str, Any]:
    """All five negative controls fixed in ``H-SIG21`` §7, each over the complete family."""

    retained = _retained_events(scans, index)
    keys = [
        (gap, horizon)
        for gap in REGISTERED_GAPS_SECONDS
        for horizon in REGISTERED_HORIZONS_SECONDS
    ]

    lead: list[PlaceboObservation] = []
    churn: list[PlaceboObservation] = []
    for scan, _, candidate, edge in retained:
        past = past_returns_by_ts.get((scan.tape_index, candidate.receive_ts_ns), {})
        response = scan.responses_by_ts.get(candidate.receive_ts_ns)
        for threshold in REGISTERED_THRESHOLDS:
            if not index.crosses(candidate, threshold):
                continue
            for gap, horizon in keys:
                cell_id = _cell_id_for(
                    candidate, threshold=threshold, gap=gap, horizon=horizon
                )
                value = past.get((gap, horizon))
                if value is not None:
                    lead.append(
                        PlaceboObservation(
                            cell_id, candidate.receive_ts_ns, scan.run_id, value
                        )
                    )
                if (
                    edge is not None
                    and edge <= NEAR_BOUNDARY_RUPEES
                    and response is not None
                    and (gap, horizon) in response.cells
                ):
                    churn.append(
                        PlaceboObservation(
                            cell_id,
                            candidate.receive_ts_ns,
                            scan.run_id,
                            response.cells[(gap, horizon)].future_response_ticks,
                        )
                    )

    shuffled: list[PlaceboObservation] = []
    by_bucket: defaultdict[tuple[int, str], list[int]] = defaultdict(list)
    for scan in scans:
        for stamp in sorted(scan.responses_by_ts):
            by_bucket[(scan.tape_index, time_bucket_ist(stamp))].append(stamp)
    shuffle_map: dict[tuple[int, int], int] = {}
    for bucket_key, stamps in sorted(by_bucket.items()):
        permutation = _deterministic_permutation(len(stamps), seed + hash(bucket_key[1]) % 9_973)
        for position, stamp in enumerate(stamps):
            shuffle_map[(bucket_key[0], stamp)] = stamps[permutation[position]]
    scans_by_index = {scan.tape_index: scan for scan in scans}
    for scan, _, candidate, _ in retained:
        target = shuffle_map.get((scan.tape_index, candidate.receive_ts_ns))
        if target is None:
            continue
        shuffled_response = scans_by_index[scan.tape_index].responses_by_ts.get(target)
        if shuffled_response is None:
            continue
        response = shuffled_response
        for threshold in REGISTERED_THRESHOLDS:
            if not index.crosses(candidate, threshold):
                continue
            for gap, horizon in keys:
                response_cell = response.cells.get((gap, horizon))
                if response_cell is None:
                    continue
                shuffled.append(
                    PlaceboObservation(
                        _cell_id_for(candidate, threshold=threshold, gap=gap, horizon=horizon),
                        candidate.receive_ts_ns,
                        scan.run_id,
                        response_cell.future_response_ticks,
                    )
                )

    permuted_side: list[PlaceboObservation] = []
    sides: list[Side] = [
        ("bid" if candidate.side == "bid" else "ask") for _, _, candidate, _ in retained
    ]
    order = _deterministic_permutation(len(sides), seed + 7)
    for position, (scan, _, candidate, _) in enumerate(retained):
        response = scan.responses_by_ts.get(candidate.receive_ts_ns)
        if response is None:
            continue
        override = sides[order[position]]
        for threshold in REGISTERED_THRESHOLDS:
            if not index.crosses(candidate, threshold):
                continue
            for gap, horizon in keys:
                response_cell = response.cells.get((gap, horizon))
                if response_cell is None:
                    continue
                permuted_side.append(
                    PlaceboObservation(
                        _cell_id_for(
                            candidate,
                            threshold=threshold,
                            gap=gap,
                            horizon=horizon,
                            side_override=override,
                        ),
                        candidate.receive_ts_ns,
                        scan.run_id,
                        response_cell.future_response_ticks,
                    )
                )

    placebo: list[PlaceboObservation] = []
    instants_by_id = {
        instant.control_id: instant for scan in scans for instant in scan.control_instants
    }
    for threshold, control_set in sorted(control_sets.items()):
        quiet_ids = sorted(control_set.control_response_by_id)
        if len(quiet_ids) < 2:
            continue
        # Each quiet instant is matched to its nearest *other* quiet instant by exactly the §6
        # covariate rule, so the placebo reproduces the real matching step with a control standing
        # in for the event. A permutation would not do: differencing a set against a bijection of
        # itself sums to zero identically, which manufactures a null instead of testing for one.
        pool_by_id = {
            control_id: QuietControlCandidate(
                control_id, instants_by_id[control_id].covariates, ()
            )
            for control_id in quiet_ids
            if control_id in instants_by_id
        }
        for control_id in quiet_ids:
            first = instants_by_id.get(control_id)
            if first is None:
                continue
            others = [
                candidate for key, candidate in pool_by_id.items() if key != control_id
            ]
            if not others:
                continue
            matched = match_quiet_control(
                event_id=control_id,
                event_covariates=first.covariates,
                controls=others,
            )
            if matched.match is None:
                continue
            second = instants_by_id.get(matched.match.control_id)
            if second is None:
                continue
            for gap, horizon in keys:
                left = first.response.cells.get((gap, horizon))
                right = second.response.cells.get((gap, horizon))
                if left is None or right is None:
                    continue
                for construction in construction_cells():
                    placebo.append(
                        PlaceboObservation(
                            FamilyCell(
                                construction.atomic_type,
                                construction.side,
                                construction.distance_band,
                                threshold,
                                gap,
                                horizon,
                            ).cell_id,
                            first.receive_ts_ns,
                            first.run_id,
                            left.future_response_ticks - right.future_response_ticks,
                        )
                    )

    return {
        "object_category": "estimated",
        "registered_controls": [
            "future_event_leads_predicting_past_returns",
            "within_session_time_bin_timestamp_shuffle",
            "side_label_permutation",
            "near_boundary_churn",
            "matched_quiet_episodes",
        ],
        "nominal_significance_rate_under_the_null": 0.05,
        "results": [
            _summarise_placebo_family(
                lead,
                name="future_event_leads_predicting_past_returns",
                description=(
                    "The registered response is replaced by the midpoint return over the mirror "
                    "window that ends before the event, [t - Z - h2, t - Z]. A real event cannot "
                    "move a price that has already printed."
                ),
                interpretation=(
                    "A non-zero mean here is evidence of a persistent price trend or of a "
                    "conditioning artefact, not of any forward relationship."
                ),
            ),
            _summarise_placebo_family(
                shuffled,
                name="within_session_time_bin_timestamp_shuffle",
                description=(
                    "Each retained event keeps its construction cell but is re-timed to another "
                    "depth200 instant drawn from the same tape and the same 30-minute bucket."
                ),
                interpretation=(
                    "This destroys the event-to-response alignment while preserving the marginal "
                    "distributions of both. Anything surviving is a property of the window."
                ),
            ),
            _summarise_placebo_family(
                permuted_side,
                name="side_label_permutation",
                description=(
                    "Side labels are permuted across retained events, so bid-side responses are "
                    "assigned to ask-side cells and the reverse."
                ),
                interpretation=(
                    "A genuinely side-specific relationship must weaken here. If it does not, the "
                    "cell is measuring something common to both sides, such as the market's drift."
                ),
            ),
            _summarise_placebo_family(
                churn,
                name="near_boundary_churn",
                description=(
                    "Restricted to retained events lying within Rs 1 of the outermost occupied "
                    "price on their own side: the population the preceding replay showed is very "
                    "largely the 200-level window's rim moving rather than interior far-book "
                    "activity."
                ),
                interpretation=(
                    "If the same pattern appears here, the pattern is window geometry, not a far-"
                    "book disturbance carrying information."
                ),
            ),
            _summarise_placebo_family(
                placebo,
                name="matched_quiet_episodes",
                description=(
                    "Quiet control instants differenced against other quiet control instants. No "
                    "anomaly is involved on either side of the difference."
                ),
                interpretation=(
                    "This is the pure placebo. Any nominal significance here is the false-positive "
                    "rate the design actually delivers on this tape."
                ),
            ),
        ],
    }


# ----------------------------------------------------------------------------------------------
# Unconditional response attachment and the honest power statement
# ----------------------------------------------------------------------------------------------

NSE_SESSION_SECONDS = NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS
REGISTERED_EVALUATION_SESSIONS = 20
# Below this many observations a Bartlett long-run variance is not a precision statement: it can
# collapse toward zero and manufacture an interval narrow enough to clear the registered gate.
MINIMUM_CREDIBLE_CELL_N = 30


def build_unconditional_response(scans: Sequence[TapeScan]) -> dict[str, Any]:
    """Responses attached to every candidate and to every burst, with no threshold applied.

    The contemporaneous leg and the predictive leg are reported as separate objects throughout,
    as ``H-SIG21`` §2 requires; nothing here merges them into a single number.
    """

    keys = [
        (gap, horizon)
        for gap in REGISTERED_GAPS_SECONDS
        for horizon in REGISTERED_HORIZONS_SECONDS
    ]
    burst_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    per_cell_rows: list[dict[str, Any]] = []
    for gap, horizon in keys:
        burst_predictive: list[float] = []
        burst_contemporaneous: list[float] = []
        burst_peak: list[float] = []
        candidate_predictive: list[float] = []
        candidate_contemporaneous: list[float] = []
        by_cell_predictive: defaultdict[str, list[float]] = defaultdict(list)
        by_cell_contemporaneous: defaultdict[str, list[float]] = defaultdict(list)
        for scan in scans:
            for response in scan.responses_by_ts.values():
                burst_cell = response.cells.get((gap, horizon))
                if burst_cell is None:
                    continue
                burst_predictive.append(burst_cell.future_response_ticks)
                burst_contemporaneous.append(burst_cell.contemporaneous_ticks)
                burst_peak.append(burst_cell.peak_response_ticks)
            for candidate in scan.candidates:
                candidate_response = scan.responses_by_ts.get(candidate.receive_ts_ns)
                candidate_cell = (
                    None
                    if candidate_response is None
                    else candidate_response.cells.get((gap, horizon))
                )
                if candidate_cell is None:
                    continue
                candidate_predictive.append(candidate_cell.future_response_ticks)
                candidate_contemporaneous.append(candidate_cell.contemporaneous_ticks)
                cell_id = construction_cell_of(candidate).cell_id
                by_cell_predictive[cell_id].append(candidate_cell.future_response_ticks)
                by_cell_contemporaneous[cell_id].append(candidate_cell.contemporaneous_ticks)
        burst_rows.append(
            {
                "gap_seconds": gap,
                "horizon_seconds": horizon,
                "predictive": _summarise_ticks(burst_predictive),
                "contemporaneous": _summarise_ticks(burst_contemporaneous),
                "peak_within_window": _summarise_ticks(burst_peak),
            }
        )
        candidate_rows.append(
            {
                "gap_seconds": gap,
                "horizon_seconds": horizon,
                "predictive": _summarise_ticks(candidate_predictive),
                "contemporaneous": _summarise_ticks(candidate_contemporaneous),
            }
        )
        for construction in construction_cells():
            per_cell_rows.append(
                {
                    "construction_cell_id": construction.cell_id,
                    "gap_seconds": gap,
                    "horizon_seconds": horizon,
                    "predictive": _summarise_ticks(
                        by_cell_predictive.get(construction.cell_id, [])
                    ),
                    "contemporaneous": _summarise_ticks(
                        by_cell_contemporaneous.get(construction.cell_id, [])
                    ),
                }
            )
    return {
        "object_category": "estimated",
        "threshold_applied": None,
        "by_burst": burst_rows,
        "by_candidate": candidate_rows,
        "by_construction_cell_and_candidate": per_cell_rows,
        "note": (
            "Every candidate in one receive-timestamp burst shares that burst's response, so the "
            "per-candidate view weights bursts by how many candidates they contain and adds no "
            "independent information. Both are reported because the registered atomic families "
            "are defined on candidates, not bursts."
        ),
        "label_failures": _merge_counters(scan.label_failures for scan in scans),
    }


def _merge_counters(counters: Iterable[Mapping[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for counter in counters:
        for key, value in counter.items():
            total[key] += value
    return dict(sorted(total.items()))


def required_effective_sample(
    *,
    sigma_ticks: float,
    critical_value: float,
    target_mde_ticks: float,
    two_arm: bool = True,
) -> float | None:
    """Effective sample size needed to reach an MDE at a given critical value."""

    if target_mde_ticks <= 0 or sigma_ticks <= 0 or critical_value <= 0:
        return None
    factor = sqrt(2.0) if two_arm else 1.0
    return (critical_value * factor * sigma_ticks / target_mde_ticks) ** 2


def required_probability_sample(
    *,
    probability: float,
    critical_value: float,
    target_mde: float = MAX_MOVE_PROBABILITY_MDE,
) -> float | None:
    """Effective sample size needed to resolve a move-probability difference to ``target_mde``."""

    if not 0.0 < probability < 1.0 or target_mde <= 0 or critical_value <= 0:
        return None
    return 2.0 * probability * (1.0 - probability) * (critical_value / target_mde) ** 2


def build_power_statement(
    unconditional: Mapping[str, Any],
    family: Mapping[str, Any],
    *,
    observed_seconds: float,
) -> dict[str, Any]:
    """How far the realised precision is from the registered adequacy gates.

    ``H-SIG21`` §8 requires an MDE no larger than 0.25 futures tick for the mean response and no
    larger than 5 percentage points for the probability of a move of at least one tick.  This
    section measures the distance to those gates using the response volatility observed in this
    window.  The volatility is a within-sample estimate from 22 minutes of one mid-morning
    stretch and is stated as such.
    """

    critical_values = family.get("family_critical_values", {})
    ceiling_per_session = NSE_SESSION_SECONDS // EPISODE_WINDOW_SECONDS
    evaluation_ceiling = ceiling_per_session * REGISTERED_EVALUATION_SESSIONS
    rows: list[dict[str, Any]] = []
    for burst_row in unconditional["by_burst"]:
        predictive = burst_row["predictive"]
        sigma = predictive["sd_ticks"]
        probability = predictive["probability_up_at_least_one_tick"]
        sources: list[tuple[str, float]] = [("per_cell_normal_95", NORMAL_95_CRITICAL_VALUE)]
        sources.extend(
            (f"family_bootstrap_max_t_{arm}", value)
            for arm, value in sorted(critical_values.items())
        )
        for label, value in sources:
            required_mean = (
                None
                if sigma is None
                else required_effective_sample(
                    sigma_ticks=sigma,
                    critical_value=value,
                    target_mde_ticks=MAX_MEAN_MDE_TICKS,
                )
            )
            required_probability = (
                None
                if probability is None
                else required_probability_sample(
                    probability=probability, critical_value=value
                )
            )
            rows.append(
                {
                    "gap_seconds": burst_row["gap_seconds"],
                    "horizon_seconds": burst_row["horizon_seconds"],
                    "critical_value_source": label,
                    "critical_value": value,
                    "unconditional_sd_ticks": sigma,
                    "unconditional_move_probability": probability,
                    "required_n_eff_for_mean_gate": required_mean,
                    "required_n_eff_for_probability_gate": required_probability,
                    "registered_evaluation_ceiling_episodes": evaluation_ceiling,
                    "required_n_eff_per_cell_if_ceiling_split_evenly": (
                        None
                        if required_mean is None
                        else required_mean * REGISTERED_FAMILY_SIZE / evaluation_ceiling
                    ),
                    "mean_gate_shortfall_factor": (
                        None
                        if required_mean is None or evaluation_ceiling == 0
                        else required_mean / evaluation_ceiling
                    ),
                    "probability_gate_shortfall_factor": (
                        None
                        if required_probability is None or evaluation_ceiling == 0
                        else required_probability / evaluation_ceiling
                    ),
                }
            )
    realised: dict[str, dict[str, Any]] = {}
    for arm in family["arms"]:
        intervals = [
            (cell["arms"][arm]["confidence_half_width_ticks"], int(cell["arms"][arm]["n"]))
            for cell in family["cells"]
            if cell["arms"][arm]["confidence_half_width_ticks"] is not None
        ]
        ordered = sorted(width for width, _ in intervals)
        meeting = [(width, n) for width, n in intervals if width <= MAX_MEAN_MDE_TICKS]
        thin = [(width, n) for width, n in meeting if n < MINIMUM_CREDIBLE_CELL_N]
        realised[arm] = {
            "cells_with_an_interval": len(ordered),
            "cells_without_an_interval": REGISTERED_FAMILY_SIZE - len(ordered),
            "median_half_width_ticks": percentile(ordered, 0.50),
            "min_half_width_ticks": ordered[0] if ordered else None,
            "max_half_width_ticks": ordered[-1] if ordered else None,
            "cells_meeting_mean_gate": len(meeting),
            "minimum_credible_cell_n": MINIMUM_CREDIBLE_CELL_N,
            "cells_meeting_mean_gate_on_fewer_than_minimum_observations": len(thin),
            "cells_meeting_mean_gate_with_credible_n": len(meeting) - len(thin),
            "median_n_among_gate_meeting_cells": percentile(
                sorted(float(n) for _, n in meeting), 0.50
            ),
            "median_gate_ratio": (
                None
                if not ordered
                else (percentile(ordered, 0.50) or 0.0) / MAX_MEAN_MDE_TICKS
            ),
            "spurious_precision_warning": (
                "A cell can appear to meet the 0.25-tick gate simply because its Bartlett "
                "long-run variance collapsed toward zero on a handful of observations. The "
                "credible-n column strips those out; read that, not the raw count."
            ),
        }
    return {
        "object_category": "estimated",
        "registered_mean_mde_gate_ticks": MAX_MEAN_MDE_TICKS,
        "registered_probability_mde_gate": MAX_MOVE_PROBABILITY_MDE,
        "observed_seconds": observed_seconds,
        "observed_minutes": observed_seconds / 60.0,
        "episode_capacity_ceiling_per_session": ceiling_per_session,
        "registered_evaluation_sessions": REGISTERED_EVALUATION_SESSIONS,
        "registered_evaluation_ceiling_episodes": evaluation_ceiling,
        "requirements": rows,
        "realised_precision_by_arm": realised,
        "note": (
            "The required effective sample sizes assume the event-minus-control contrast the "
            "registration specifies, so they carry a factor of sqrt(2) over a one-sample mean. "
            "The registered evaluation ceiling is the arithmetic maximum number of non-"
            "overlapping 11 s episodes 20 full sessions can contain, before any split by cell or "
            "stratum, so comparing a single cell's requirement against it is generous to the "
            "design rather than harsh."
        ),
    }


# ----------------------------------------------------------------------------------------------
# Past-return mirror windows, protocol metadata and the assembled artifact
# ----------------------------------------------------------------------------------------------


def attach_past_return_placebo(
    burst_timestamps: Sequence[int],
    depth20_states: Sequence[BookState],
    *,
    tick_size: float = FUTURES_TICK_SIZE,
) -> dict[int, dict[tuple[float, int], float]]:
    """The mirror-image *past* return for every registered ``(Z, h2)`` pair at each burst.

    The window ``[t - Z - h2, t - Z]`` is the exact reflection of the registered predictive
    window and ends before the event.  It uses the same as-of rule and refuses any window whose
    left edge falls before the tape's first depth20 observation, so no window is silently
    shortened -- which is the same right-edge defect the forward labels guard against.
    """

    timestamps = [state.receive_ts_ns for state in depth20_states]
    if not timestamps:
        return {}
    coverage_start = timestamps[0]
    results: dict[int, dict[tuple[float, int], float]] = {}
    for stamp in burst_timestamps:
        row: dict[tuple[float, int], float] = {}
        for gap in REGISTERED_GAPS_SECONDS:
            end_target = stamp - int(round(gap * NANOSECONDS_PER_SECOND))
            for horizon in REGISTERED_HORIZONS_SECONDS:
                start_target = end_target - horizon * NANOSECONDS_PER_SECOND
                if start_target < coverage_start:
                    continue
                start_index = bisect_right(timestamps, start_target) - 1
                end_index = bisect_right(timestamps, end_target) - 1
                if start_index < 0 or end_index < 0:
                    continue
                start_value = _midpoint_ticks(depth20_states[start_index], tick_size=tick_size)
                end_value = _midpoint_ticks(depth20_states[end_index], tick_size=tick_size)
                if start_value is None or end_value is None:
                    continue
                row[(gap, horizon)] = end_value - start_value
        results[stamp] = row
    return results


def protocol_metadata(
    scans: Sequence[TapeScan],
    *,
    code_commit: str | None = None,
) -> dict[str, Any]:
    """The metadata every artifact carries so its protocol status can never be misread."""

    return {
        "exploratory_scan_id": EXPLORATORY_SCAN_ID,
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "sample_role": SAMPLE_ROLE,
        "protocol_id": PROTOCOL_ID,
        "registration_document": "docs/sig-claims/H-SIG21.md",
        "registration_document_modified": False,
        "registering_commit": REGISTERING_COMMIT,
        "registering_commit_pushed_at_ist": REGISTERING_COMMIT_TIMESTAMP_IST,
        "code_commit": code_commit,
        "threshold_provenance": THRESHOLD_PROVENANCE,
        "authorisation": (
            "Directed by Aryan by voice on 2026-08-19 at approximately 16:42 IST, after the "
            "construction replay, to measure the future mid-price relationship on the retained "
            "DAT-20 tapes and propose a candidate model."
        ),
        "pre_registration_capture_justification": (
            "Both tapes were captured at 13:09 and 13:20 IST on 2026-08-19, before the "
            f"registering commit {REGISTERING_COMMIT[:8]} was pushed at "
            f"{REGISTERING_COMMIT_TIMESTAMP_IST}. Under {PROTOCOL_ID} §1.5 only tape collected "
            "after that commit may enter the first outcome sample, so these tapes were already "
            "permanently ineligible for Confirmed/Falsified status; under §1.2 their post-event "
            "price paths were already excluded from SIG-21 inference. Attaching a response to "
            "them now therefore costs nothing that was not already spent, and can never be "
            "confirmatory."
        ),
        "what_this_is_not": (
            "Not a SIG-21 result. Not evidence about whether deep-book anomalies forecast price. "
            "Not a Confirmed/Falsified verdict. Not grounds to alter the immutable 384-cell "
            "registration. Every threshold here is within sample."
        ),
        "source_tapes": [
            {
                "run_id": scan.run_id,
                "sha256": scan.tape_sha256,
                "instrument_id": scan.instrument_id,
                "session_id": scan.session_id,
                "observed_seconds": scan.observed_seconds,
                "captured_before_registering_commit": True,
            }
            for scan in scans
        ],
        "object_category_legend": [
            "observed",
            "deterministically_derived",
            "estimated",
            "scenario_based",
            "proxy",
            "unidentified",
        ],
    }


def build_exploratory_artifact(
    scans: Sequence[TapeScan],
    *,
    past_returns: Mapping[tuple[int, int], Mapping[tuple[float, int], float]],
    code_commit: str | None = None,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
    cutoffs: Sequence[float] = SELECTIVITY_GRID,
) -> dict[str, Any]:
    """Assemble the complete scan: selectivity, family, correlations, controls and power."""

    assert_exploratory_claim(["exploratory scan of the pre-registration DAT-20 tapes"])
    for scan in scans:
        assert_permitted_tape(run_id=scan.run_id, tape_sha256=scan.tape_sha256)
    candidates = [candidate for scan in scans for candidate in scan.candidates]
    index = build_in_sample_magnitude_index(candidates)
    per_tape_candidates = [list(scan.candidates) for scan in scans]
    observed_seconds = [scan.observed_seconds for scan in scans]
    family = build_response_family(scans, index, replicates=replicates, seed=seed)
    unconditional = build_unconditional_response(scans)
    observations = build_predictor_observations(scans)
    control_sets = {
        threshold: build_threshold_controls(scans, index, threshold=threshold)
        for threshold in REGISTERED_THRESHOLDS
    }
    return {
        "protocol": protocol_metadata(scans, code_commit=code_commit),
        "totals": {
            "tapes": len(scans),
            "candidates": len(candidates),
            "distinct_bursts": sum(len(scan.responses_by_ts) for scan in scans),
            "observed_depth200_seconds": sum(observed_seconds),
            "control_candidate_instants": sum(len(scan.control_instants) for scan in scans),
        },
        "selectivity_curve": build_selectivity_curve(
            per_tape_candidates,
            index,
            observed_seconds_per_tape=observed_seconds,
            cutoffs=cutoffs,
        ),
        "window_decomposition": build_window_decomposition(
            per_tape_candidates,
            index,
            observed_seconds_per_tape=observed_seconds,
            cutoffs=cutoffs,
        ),
        "unconditional_response": unconditional,
        "family": family,
        "correlations": build_correlation_tables(observations),
        "correlations_past_return_placebo": build_correlation_tables(
            build_past_return_observations(scans, past_returns)
        ),
        "correlations_contemporaneous_leg": build_correlation_tables(
            build_contemporaneous_observations(scans)
        ),
        "negative_controls": build_negative_controls(
            scans,
            index,
            past_returns_by_ts=past_returns,
            control_sets=control_sets,
        ),
        "power": build_power_statement(
            unconditional, family, observed_seconds=sum(observed_seconds)
        ),
    }


def family_rows(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten the family to one JSONL row per cell per arm, all 384 cells always present."""

    protocol = artifact["protocol"]
    rows: list[dict[str, Any]] = []
    for cell in artifact["family"]["cells"]:
        for arm, payload in cell["arms"].items():
            flattened: dict[str, Any] = {
                "exploratory_scan_id": protocol["exploratory_scan_id"],
                "confirmatory_eligible": protocol["confirmatory_eligible"],
                "threshold_provenance": protocol["threshold_provenance"],
                "arm": arm,
            }
            for name, value in cell.items():
                if name == "arms":
                    continue
                if isinstance(value, dict):
                    for inner, inner_value in value.items():
                        if not isinstance(inner_value, dict):
                            flattened[f"{name}_{inner}"] = inner_value
                    continue
                flattened[name] = value
            for name, value in payload.items():
                if isinstance(value, dict):
                    for inner, inner_value in value.items():
                        flattened[f"{name}_{inner}"] = inner_value
                    continue
                flattened[name] = value
            rows.append(flattened)
    assert_complete_family(
        sorted({str(row["cell_id"]) for row in rows})
    )
    return rows
