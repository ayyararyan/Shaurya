"""SIG-21 outcome-blind construction replay and the basic 32-cell support grid.

This module answers one question and refuses the other. It answers: *how much registered
construction support does an already-recorded depth200 tape actually contain?* It refuses:
*what happened to the price afterwards?*

``H-SIG21`` §1.2 permits the two retained ``DAT-20`` tapes to be used only for
parser/event-construction verification and event counts; their post-event price paths are
permanently excluded from SIG-21 inference. Nothing here computes, reads, joins or reports a
future price, return, midpoint response, markout or label, and :func:`assert_outcome_blind_request`
turns any request for one into a hard failure rather than a silent computation.

The registered discovery family is ``8 x 2 x 2 x 2 x 2 x 3 = 384`` cells. Only the first three
axes are determined by construction; the remaining three multiply the same construction support
and cannot be measured here at all (thresholds need a past-only baseline over completed prior
sessions, ``Z``/``h2`` need outcomes). The "basic grid" is therefore the 32 construction cells,
each of which expands to 12 registered family cells. See ``docs/sig-claims/H-SIG21.md``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from shaurya.contracts.timing import NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS
from shaurya.data.depth_thinning_analysis import (
    DEPTH200,
    BookState,
    build_states,
    parse_receive_ts_ns,
    percentile,
)
from shaurya.signals.deep_book_anomaly import (
    DISTANCE_SPLIT_RUPEES,
    FAR_BOUNDARY_RUPEES,
    MIN_BASELINE_EVENTS,
    AtomicEventType,
    CandidateEvent,
    detect_candidates,
)
from shaurya.signals.deep_book_inference import (
    REGISTERED_DISTANCE_BANDS,
    REGISTERED_FAMILY_SIZE,
    REGISTERED_GAPS_SECONDS,
    REGISTERED_HORIZONS_SECONDS,
    REGISTERED_SIDES,
    REGISTERED_THRESHOLDS,
    DistanceBand,
    Side,
)

# Only the two purely geometric helpers are imported from the response module. Both operate on
# ``(receive_ts_ns, event_id)`` pairs alone: they collapse exact-timestamp bursts and connect
# bursts whose registered 11 s windows overlap. Neither reads a price, a midpoint or a horizon
# endpoint, so neither can produce or imply a response. No response-producing symbol from that
# module -- ``build_depth20_response_labels`` above all -- is imported or called anywhere here.
from shaurya.signals.deep_book_response import (  # isort: skip
    EPISODE_WINDOW_SECONDS,
    EpisodeEvent,
    cluster_event_episodes,
    select_primary_non_overlapping_episodes,
)
PROTOCOL_ID = "H-SIG21"
SAMPLE_ROLE = "construction_replay_only"
OUTCOME_JOIN_ALLOWED = False

NANOSECONDS_PER_SECOND = 1_000_000_000
IST_OFFSET_SECONDS = 19_800
TIME_BUCKET_SECONDS = 1_800
SECONDS_PER_MINUTE = 60.0

# H-SIG21 §8: a full NSE session, the five calibration sessions and the twenty evaluation
# sessions. Used only to label scenario-based extrapolations, never as a measurement.
NSE_SESSION_SECONDS = NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS
CALIBRATION_SESSIONS = 5
EVALUATION_SESSIONS = 20

# The registered publication-gap threshold carried over from DAT-20 §1.5, reused here so the
# coverage section reports gaps against an already-registered bound rather than a new one.
PUBLICATION_GAP_THRESHOLD_MS = 300.0

BOUNDARY_CHURN_REASON = "whole_ladder_boundary_churn"

CONSTRUCTION_CELL_COUNT = 32
FAMILY_CELLS_PER_CONSTRUCTION_CELL = REGISTERED_FAMILY_SIZE // CONSTRUCTION_CELL_COUNT

# Upper edges of the finer far-distance histogram, in rupees from the same-side best quote. The
# registered split at Rs 50 is one of these edges so the finer view nests inside the registered
# bands instead of competing with them.
DISTANCE_HISTOGRAM_EDGES: tuple[float, ...] = (
    25.0,
    30.0,
    40.0,
    50.0,
    75.0,
    100.0,
    150.0,
    200.0,
    300.0,
    500.0,
)

# Any of these appearing as a word in a caller's requested output list means the caller is asking
# this replay for an outcome. H-SIG21 §1.2 forbids that for these tapes, so it is refused loudly.
# Matching is on whole words, not substrings: "quantity" and "dhan_security_id" are ordinary
# construction names and must not be caught by the single-letter response token "y".
FORBIDDEN_REQUEST_TOKENS = frozenset(
    {
        "forecast",
        "future",
        "label",
        "labels",
        "markout",
        "markouts",
        "mid",
        "midpoint",
        "midpoints",
        "outcome",
        "outcomes",
        "pnl",
        "predictive",
        "prediction",
        "response",
        "responses",
        "return",
        "returns",
        "y",
    }
)


class OutcomeJoinRefused(RuntimeError):
    """Raised when a caller asks this outcome-blind replay for outcome-bearing output."""


def name_tokens(name: str) -> frozenset[str]:
    """Split an identifier into lowercase word tokens for whole-word matching."""

    return frozenset(part for part in re.split(r"[^a-z0-9]+", str(name).strip().lower()) if part)


def assert_outcome_blind_request(requested: Iterable[str]) -> None:
    """Refuse any request naming a response, return, label or other outcome quantity."""

    offending = sorted(
        {name for name in requested if name_tokens(name) & FORBIDDEN_REQUEST_TOKENS}
    )
    if offending:
        raise OutcomeJoinRefused(
            f"{PROTOCOL_ID} §1.2 permanently excludes the post-event price paths of the retained "
            "DAT-20 tapes from SIG-21 inference; this replay is "
            f"sample_role={SAMPLE_ROLE!r} with outcome_join_allowed={OUTCOME_JOIN_ALLOWED}. "
            f"Refused request(s): {', '.join(offending)}."
        )


@dataclass(frozen=True, slots=True, order=True)
class ConstructionCell:
    """One construction-determined cell: atomic type x side x registered distance band."""

    atomic_type: AtomicEventType
    side: Side
    distance_band: DistanceBand

    @property
    def cell_id(self) -> str:
        return f"{self.atomic_type.value}|{self.side}|{self.distance_band}"


def construction_cells() -> tuple[ConstructionCell, ...]:
    """The complete 32 construction cells, always emitted whether populated or not."""

    return tuple(
        ConstructionCell(atomic_type, side, band)
        for atomic_type in AtomicEventType
        for side in REGISTERED_SIDES
        for band in REGISTERED_DISTANCE_BANDS
    )


def _summary(values: Sequence[float]) -> dict[str, float | int | None]:
    """Count/mean/median/p90/p99/max of a displayed-quantity magnitude sample."""

    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": (sum(ordered) / len(ordered)) if ordered else None,
        "median": percentile(ordered, 0.50),
        "p90": percentile(ordered, 0.90),
        "p99": percentile(ordered, 0.99),
        "max": ordered[-1] if ordered else None,
    }


def time_bucket_ist(receive_ts_ns: int) -> str:
    """The registered 30-minute time-of-day bucket in IST, labelled by its opening edge."""

    ist_seconds = receive_ts_ns // NANOSECONDS_PER_SECOND + IST_OFFSET_SECONDS
    seconds_into_day = ist_seconds % 86_400
    bucket_start = (seconds_into_day // TIME_BUCKET_SECONDS) * TIME_BUCKET_SECONDS
    return f"{bucket_start // 3_600:02d}:{(bucket_start % 3_600) // 60:02d}"


def distance_histogram_bin(distance_rupees: float) -> str:
    """Finer nested label for a far distance, so the registered split can be judged."""

    lower = FAR_BOUNDARY_RUPEES
    for edge in DISTANCE_HISTOGRAM_EDGES:
        if distance_rupees <= edge:
            return f"({lower:g},{edge:g}]"
        lower = edge
    return f"({lower:g},inf)"


@dataclass(frozen=True, slots=True)
class TapeReplay:
    """Everything one tape contributes, with no outcome field of any kind."""

    run_id: str
    tape_sha256: str
    instrument_id: str
    dhan_security_id: str
    trading_symbol: str
    candidates: tuple[CandidateEvent, ...]
    depth200_publications: int
    transitions_attempted: int
    transitions_valid: int
    exclusions: tuple[str, ...]
    edge_distances: tuple[tuple[str, str, float], ...]
    first_receive_ts_ns: int | None
    last_receive_ts_ns: int | None
    publication_gaps_ms: tuple[float, ...]
    depth200_rows: int
    depth20_rows: int
    depth20_first_receive_ts_ns: int | None
    depth20_last_receive_ts_ns: int | None

    @property
    def observed_seconds(self) -> float:
        if self.first_receive_ts_ns is None or self.last_receive_ts_ns is None:
            return 0.0
        return (self.last_receive_ts_ns - self.first_receive_ts_ns) / NANOSECONDS_PER_SECOND


# Distance thresholds, in rupees, used to report how much construction mass sits at the very edge
# of the 200-level window rather than inside a stable far ladder.
EDGE_PROXIMITY_THRESHOLDS: tuple[float, ...] = (1.0, 5.0)

_EDGE_FROM_POST = frozenset(
    {
        AtomicEventType.ADDITION,
        AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY,
        AtomicEventType.RELOCATION_AWAY_FROM_TOUCH_PROXY,
    }
)


def _outer_price(state: BookState, side: Side) -> float | None:
    ladder = state.bids if side == "bid" else state.asks
    if not ladder:
        return None
    prices = [price for price, _, _ in ladder]
    return min(prices) if side == "bid" else max(prices)


def _edge_distance(
    candidate: CandidateEvent,
    outer_previous: float | None,
    outer_current: float | None,
) -> float | None:
    """Rupees between a candidate's price and the outermost occupied price on its own side.

    A removal is measured against the ladder it left; an addition or relocation destination
    against the ladder it joined; a change at a retained price against whichever edge is nearer.
    """

    if candidate.atomic_type is AtomicEventType.REMOVAL:
        return None if outer_previous is None else abs(candidate.price - outer_previous)
    if candidate.atomic_type in _EDGE_FROM_POST:
        return None if outer_current is None else abs(candidate.price - outer_current)
    available = [edge for edge in (outer_previous, outer_current) if edge is not None]
    if not available:
        return None
    return min(abs(candidate.price - edge) for edge in available)


def outer_price(state: BookState, side: Side) -> float | None:
    """The outermost occupied price on one side of a 200-level window, or ``None`` if empty."""

    return _outer_price(state, side)


def edge_distance(
    candidate: CandidateEvent,
    outer_previous: float | None,
    outer_current: float | None,
) -> float | None:
    """Public accessor for a candidate's rupee distance from its own side's outer rim."""

    return _edge_distance(candidate, outer_previous, outer_current)


def replay_states(
    states: Sequence[BookState],
    *,
    instrument_id: str,
) -> tuple[list[CandidateEvent], list[str], int, int, list[tuple[str, str, float]]]:
    """Run the registered detector across every consecutive depth200 transition.

    Returns candidates, exclusion reasons, transitions attempted, transitions that produced a
    valid construction pass, and one ``(atomic type, side, edge distance)`` triple per candidate
    whose edge distance is defined. The detector's semantics are used exactly as registered; the
    edge distance is a diagnostic computed alongside it and changes no classification.
    """

    candidates: list[CandidateEvent] = []
    exclusions: list[str] = []
    edge_distances: list[tuple[str, str, float]] = []
    valid = 0
    for previous, current in zip(states, states[1:], strict=False):
        result = detect_candidates(previous, current, instrument_id=instrument_id)
        reasons = [exclusion.reason for exclusion in result.exclusions]
        # A whole-transition rejection returns exactly that one reason and no candidates.
        # Boundary churn is a within-transition exclusion that leaves the transition valid.
        rejected = any(reason != BOUNDARY_CHURN_REASON for reason in reasons)
        if not rejected:
            valid += 1
        candidates.extend(result.candidates)
        exclusions.extend(reasons)
        if result.candidates:
            edges = {
                side: (_outer_price(previous, side), _outer_price(current, side))
                for side in REGISTERED_SIDES
            }
            for candidate in result.candidates:
                side_key: Side = "bid" if candidate.side == "bid" else "ask"
                outer_previous, outer_current = edges[side_key]
                distance = _edge_distance(candidate, outer_previous, outer_current)
                if distance is not None:
                    edge_distances.append(
                        (str(candidate.atomic_type), candidate.side, distance)
                    )
    return candidates, exclusions, max(len(states) - 1, 0), valid, edge_distances


def build_edge_proximity(replays: Sequence[TapeReplay]) -> dict[str, Any]:
    """How much construction mass sits at the outer rim of the 200-level window.

    The registered §3 boundary-churn rule only suppresses a *near-complete* window slide: at least
    95% price overlap and at most two prices entering or leaving. A busier shift of the outer rim
    passes through as ordinary additions and removals. This section measures how large that
    population is so the grid is not read as if it were all interior far-book activity. It changes
    no classification and is outcome-blind: only same-side displayed prices are used.
    """

    triples = [triple for replay in replays for triple in replay.edge_distances]
    by_key: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    for atomic_type, side, distance in triples:
        by_key[(atomic_type, side)].append(distance)
    rows: list[dict[str, Any]] = []
    for atomic_type in AtomicEventType:
        for side in REGISTERED_SIDES:
            values = by_key.get((atomic_type.value, side), [])
            row: dict[str, Any] = {
                "atomic_type": atomic_type.value,
                "side": side,
                "candidate_count": len(values),
                "edge_distance_rupees": _summary(values),
            }
            for threshold in EDGE_PROXIMITY_THRESHOLDS:
                within = sum(1 for value in values if value <= threshold)
                row[f"within_{threshold:g}_rupees"] = within
                row[f"share_within_{threshold:g}_rupees"] = (
                    (within / len(values)) if values else 0.0
                )
            rows.append(row)
    total = len(triples)
    overall = {
        f"share_within_{threshold:g}_rupees": (
            (sum(1 for _, _, distance in triples if distance <= threshold) / total)
            if total
            else 0.0
        )
        for threshold in EDGE_PROXIMITY_THRESHOLDS
    }
    return {
        "measured_candidates": total,
        "thresholds_rupees": list(EDGE_PROXIMITY_THRESHOLDS),
        "overall": overall,
        "by_atomic_type_side": rows,
        "note": (
            "Distance from the outermost occupied price on the candidate's own side. A high share "
            "near zero means the 200-level window's own rim is moving, which the registered §3 "
            "boundary-churn rule only suppresses for near-complete slides. Reported so the grid "
            "is read correctly; no candidate was reclassified and the registration is unchanged."
        ),
    }


def build_tape_replay(
    rows: Iterable[dict[str, Any]],
    *,
    run_id: str,
    tape_sha256: str,
    instrument_id: str,
    dhan_security_id: str,
    trading_symbol: str,
) -> TapeReplay:
    """Replay one tape. Depth20 rows are counted for coverage only; no depth20 price is read."""

    depth200_rows: list[dict[str, Any]] = []
    depth20_rows = 0
    depth20_first: int | None = None
    depth20_last: int | None = None
    for row in rows:
        event_type = row.get("event_type")
        if event_type == DEPTH200:
            depth200_rows.append(row)
        elif event_type == "depth20":
            # Coverage accounting only: the row's timestamp and nothing else is inspected. No
            # depth20 price, quantity, midpoint or ladder is read anywhere in this module.
            depth20_rows += 1
            raw_ts = row.get("receive_ts")
            if isinstance(raw_ts, str):
                stamp = parse_receive_ts_ns(raw_ts)
                depth20_first = stamp if depth20_first is None else min(depth20_first, stamp)
                depth20_last = stamp if depth20_last is None else max(depth20_last, stamp)
    states = build_states(depth200_rows, DEPTH200)
    candidates, exclusions, attempted, valid, edges = replay_states(
        states, instrument_id=instrument_id
    )
    gaps = tuple(
        (later.receive_ts_ns - earlier.receive_ts_ns) / 1_000_000.0
        for earlier, later in zip(states, states[1:], strict=False)
    )
    return TapeReplay(
        run_id=run_id,
        tape_sha256=tape_sha256,
        instrument_id=instrument_id,
        dhan_security_id=dhan_security_id,
        trading_symbol=trading_symbol,
        candidates=tuple(candidates),
        depth200_publications=len(states),
        transitions_attempted=attempted,
        transitions_valid=valid,
        exclusions=tuple(exclusions),
        edge_distances=tuple(edges),
        first_receive_ts_ns=states[0].receive_ts_ns if states else None,
        last_receive_ts_ns=states[-1].receive_ts_ns if states else None,
        publication_gaps_ms=gaps,
        depth200_rows=len(depth200_rows),
        depth20_rows=depth20_rows,
        depth20_first_receive_ts_ns=depth20_first,
        depth20_last_receive_ts_ns=depth20_last,
    )


def build_construction_grid(
    candidates: Sequence[CandidateEvent],
    *,
    observed_seconds: float,
) -> list[dict[str, Any]]:
    """The complete 32-cell grid, including every empty cell."""

    by_cell: defaultdict[ConstructionCell, list[CandidateEvent]] = defaultdict(list)
    for candidate in candidates:
        side: Side = "bid" if candidate.side == "bid" else "ask"
        band: DistanceBand = "20_50" if candidate.distance_band == "20_50" else "gt_50"
        by_cell[ConstructionCell(candidate.atomic_type, side, band)].append(candidate)
    total = len(candidates)
    minutes = observed_seconds / SECONDS_PER_MINUTE if observed_seconds > 0 else 0.0
    grid: list[dict[str, Any]] = []
    for cell in construction_cells():
        members = by_cell.get(cell, [])
        grid.append(
            {
                "cell_id": cell.cell_id,
                "atomic_type": cell.atomic_type.value,
                "side": cell.side,
                "distance_band": cell.distance_band,
                "candidate_count": len(members),
                "share_of_candidates": (len(members) / total) if total else 0.0,
                "distinct_bursts": len({member.receive_ts_ns for member in members}),
                "candidates_per_minute": (len(members) / minutes) if minutes > 0 else None,
                "magnitude": _summary([member.magnitude for member in members]),
                "object_category": (
                    "proxy"
                    if cell.atomic_type
                    in {
                        AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY,
                        AtomicEventType.RELOCATION_AWAY_FROM_TOUCH_PROXY,
                    }
                    else "deterministically_derived"
                ),
                "expands_to_registered_family_cells": FAMILY_CELLS_PER_CONSTRUCTION_CELL,
            }
        )
    return grid


def bucket_exposure_seconds(windows: Sequence[tuple[int, int]]) -> dict[str, float]:
    """Observed depth200 seconds falling in each 30-minute IST bucket.

    Raw per-bucket candidate counts are unreadable without this: a bucket the tape only clips
    for two minutes is not quieter than one it covers for twenty.
    """

    exposure: defaultdict[str, float] = defaultdict(float)
    for start_ns, end_ns in windows:
        if end_ns <= start_ns:
            continue
        cursor = start_ns
        while cursor < end_ns:
            ist_seconds = cursor // NANOSECONDS_PER_SECOND + IST_OFFSET_SECONDS
            offset = ist_seconds % TIME_BUCKET_SECONDS
            boundary_ns = cursor + (TIME_BUCKET_SECONDS - offset) * NANOSECONDS_PER_SECOND
            segment_end = min(boundary_ns, end_ns)
            exposure[time_bucket_ist(cursor)] += (
                segment_end - cursor
            ) / NANOSECONDS_PER_SECOND
            cursor = segment_end
    return dict(exposure)


def build_time_of_day_breakdowns(
    candidates: Sequence[CandidateEvent],
    *,
    windows: Sequence[tuple[int, int]] = (),
) -> dict[str, Any]:
    """Candidates by 30-minute IST bucket x side, and by atomic type x bucket."""

    by_bucket_side: Counter[tuple[str, str]] = Counter()
    by_bucket_type: Counter[tuple[str, str]] = Counter()
    by_bucket: Counter[str] = Counter()
    for candidate in candidates:
        bucket = time_bucket_ist(candidate.receive_ts_ns)
        by_bucket[bucket] += 1
        by_bucket_side[(bucket, candidate.side)] += 1
        by_bucket_type[(bucket, str(candidate.atomic_type))] += 1
    exposure = bucket_exposure_seconds(windows)
    buckets = sorted(set(by_bucket) | set(exposure))
    return {
        "buckets_observed": buckets,
        "bucket_seconds_note": (
            "Buckets are clipped by the tape, not by the session. Compare candidates per second, "
            "not raw counts."
        ),
        "by_bucket": [
            {
                "time_bucket": key,
                "candidate_count": by_bucket[key],
                "observed_seconds": exposure.get(key, 0.0),
                "candidates_per_second": (
                    (by_bucket[key] / exposure[key]) if exposure.get(key) else None
                ),
            }
            for key in buckets
        ],
        "by_bucket_side": [
            {"time_bucket": bucket, "side": side, "candidate_count": by_bucket_side[(bucket, side)]}
            for bucket in buckets
            for side in REGISTERED_SIDES
        ],
        "by_bucket_atomic_type": [
            {
                "time_bucket": bucket,
                "atomic_type": atomic_type.value,
                "candidate_count": by_bucket_type[(bucket, atomic_type.value)],
            }
            for bucket in buckets
            for atomic_type in AtomicEventType
        ],
    }


def build_distance_breakdown(candidates: Sequence[CandidateEvent]) -> dict[str, Any]:
    """Registered band split plus a finer nested histogram of far distances."""

    band_counts: Counter[str] = Counter()
    histogram: Counter[str] = Counter()
    distances = [candidate.distance_rupees for candidate in candidates]
    for candidate in candidates:
        band_counts[candidate.distance_band] += 1
        histogram[distance_histogram_bin(candidate.distance_rupees)] += 1
    labels: list[str] = []
    lower = FAR_BOUNDARY_RUPEES
    for edge in DISTANCE_HISTOGRAM_EDGES:
        labels.append(f"({lower:g},{edge:g}]")
        lower = edge
    labels.append(f"({lower:g},inf)")
    total = len(candidates)
    return {
        "far_boundary_rupees": FAR_BOUNDARY_RUPEES,
        "registered_split_rupees": DISTANCE_SPLIT_RUPEES,
        "registered_bands": [
            {
                "distance_band": band,
                "candidate_count": band_counts[band],
                "share_of_candidates": (band_counts[band] / total) if total else 0.0,
            }
            for band in REGISTERED_DISTANCE_BANDS
        ],
        "finer_histogram": [
            {
                "bin": label,
                "candidate_count": histogram[label],
                "share_of_candidates": (histogram[label] / total) if total else 0.0,
            }
            for label in labels
        ],
        "distance_quantiles_rupees": _summary(distances),
    }


def build_burst_and_episode_structure(
    per_tape_candidates: Sequence[Sequence[CandidateEvent]],
    *,
    observed_seconds: float,
) -> dict[str, Any]:
    """Burst counts and the registered 11 s non-overlapping episode risk set."""

    all_candidates = [candidate for group in per_tape_candidates for candidate in group]
    burst_sizes: Counter[int] = Counter()
    for candidate in all_candidates:
        burst_sizes[candidate.receive_ts_ns] += 1
    episodes_total = 0
    non_overlapping_total = 0
    overlap_excluded_total = 0
    per_tape: list[dict[str, Any]] = []
    for index, group in enumerate(per_tape_candidates):
        events = [
            EpisodeEvent(candidate.receive_ts_ns, f"{index}:{position}")
            for position, candidate in enumerate(group)
        ]
        episodes = cluster_event_episodes(events)
        selection = select_primary_non_overlapping_episodes(episodes)
        episodes_total += len(episodes)
        non_overlapping_total += len(selection.selected)
        overlap_excluded_total += len(selection.overlap_excluded)
        stamps = sorted({candidate.receive_ts_ns for candidate in group})
        span_seconds = (
            (stamps[-1] - stamps[0]) / NANOSECONDS_PER_SECOND if len(stamps) > 1 else 0.0
        )
        per_tape.append(
            {
                "tape_index": index,
                "candidates": len(group),
                "bursts": len(stamps),
                "candidate_span_seconds": span_seconds,
                "episodes": len(episodes),
                "non_overlapping_episodes": len(selection.selected),
                "overlap_excluded_episodes": len(selection.overlap_excluded),
                "observed_seconds_capacity": int(span_seconds // EPISODE_WINDOW_SECONDS),
            }
        )
    minutes = observed_seconds / SECONDS_PER_MINUTE if observed_seconds > 0 else 0.0
    sizes = [float(size) for size in burst_sizes.values()]
    gaps: list[float] = []
    for group in per_tape_candidates:
        stamps = sorted({candidate.receive_ts_ns for candidate in group})
        gaps.extend(
            (later - earlier) / NANOSECONDS_PER_SECOND
            for earlier, later in zip(stamps, stamps[1:], strict=False)
        )
    capacity = sum(int(entry["observed_seconds_capacity"]) for entry in per_tape)
    return {
        "episode_window_seconds": EPISODE_WINDOW_SECONDS,
        "total_bursts": len(burst_sizes),
        "bursts_per_minute": (len(burst_sizes) / minutes) if minutes > 0 else None,
        "candidates_per_burst": _summary(sizes),
        "inter_burst_gap_seconds": _summary(gaps),
        "inter_burst_gaps_at_or_over_episode_window": sum(
            1 for gap in gaps if gap >= EPISODE_WINDOW_SECONDS
        ),
        "episodes": episodes_total,
        "non_overlapping_episodes": non_overlapping_total,
        "overlap_excluded_episodes": overlap_excluded_total,
        "non_overlapping_episodes_per_minute": (
            (non_overlapping_total / minutes) if minutes > 0 else None
        ),
        "episode_capacity_ceiling": capacity,
        "risk_set_is_degenerate": non_overlapping_total <= len(per_tape_candidates),
        "per_tape": per_tape,
        "note": (
            "The non-overlapping episode count is the H-SIG21 §6 primary risk set and is what "
            "drives N_eff. It is a construction count only; no response is attached to any "
            "episode here. Because the risk set is built by connecting bursts whose 11 s windows "
            "overlap, a stretch of tape with no inter-burst gap of at least 11 s collapses to "
            "exactly one episode however many candidates it contains. The capacity ceiling is "
            "floor(observed seconds / 11) and bounds the risk set from above whatever the "
            "eventual anomaly-retention rate turns out to be."
        ),
    }


def build_exclusion_breakdown(replays: Sequence[TapeReplay]) -> dict[str, Any]:
    """Exclusions by reason, plus valid transitions against total depth200 publications."""

    by_reason: Counter[str] = Counter()
    by_family: Counter[str] = Counter()
    for replay in replays:
        for reason in replay.exclusions:
            by_reason[reason] += 1
            by_family[reason.split(":", 1)[0]] += 1
    publications = sum(replay.depth200_publications for replay in replays)
    attempted = sum(replay.transitions_attempted for replay in replays)
    valid = sum(replay.transitions_valid for replay in replays)
    return {
        "depth200_publications": publications,
        "transitions_attempted": attempted,
        "transitions_valid": valid,
        "transitions_rejected": attempted - valid,
        "valid_transition_share": (valid / attempted) if attempted else None,
        "by_reason": [
            {"reason": reason, "count": count} for reason, count in sorted(by_reason.items())
        ],
        "by_reason_family": [
            {"reason_family": family, "count": count} for family, count in sorted(by_family.items())
        ],
    }


def build_coverage(replays: Sequence[TapeReplay]) -> dict[str, Any]:
    """Observed depth200 seconds, cadence and publication gaps, per tape and combined."""

    per_tape: list[dict[str, Any]] = []
    for replay in replays:
        gaps = list(replay.publication_gaps_ms)
        seconds = replay.observed_seconds
        per_tape.append(
            {
                "run_id": replay.run_id,
                "tape_sha256": replay.tape_sha256,
                "instrument_id": replay.instrument_id,
                "dhan_security_id": replay.dhan_security_id,
                "trading_symbol": replay.trading_symbol,
                "depth200_rows": replay.depth200_rows,
                "depth200_publications": replay.depth200_publications,
                "observed_seconds": seconds,
                "publications_per_second": (
                    (replay.depth200_publications / seconds) if seconds > 0 else None
                ),
                "publication_gap_ms": _summary(gaps),
                "gaps_over_registered_threshold": sum(
                    1 for gap in gaps if gap > PUBLICATION_GAP_THRESHOLD_MS
                ),
                "registered_gap_threshold_ms": PUBLICATION_GAP_THRESHOLD_MS,
                "depth20_rows_counted_for_coverage_only": replay.depth20_rows,
                "depth20_observed_seconds": (
                    (replay.depth20_last_receive_ts_ns - replay.depth20_first_receive_ts_ns)
                    / NANOSECONDS_PER_SECOND
                    if replay.depth20_first_receive_ts_ns is not None
                    and replay.depth20_last_receive_ts_ns is not None
                    else None
                ),
            }
        )
    total_seconds = sum(replay.observed_seconds for replay in replays)
    return {
        "per_tape": per_tape,
        "total_observed_depth200_seconds": total_seconds,
        "total_observed_depth200_minutes": total_seconds / SECONDS_PER_MINUTE,
        "depth20_note": (
            "Depth20 is counted here for coverage only. No depth20 price, quantity, ladder or "
            "midpoint is read anywhere in this replay, so no response can be formed from it."
        ),
    }


def build_baseline_layer(candidates: Sequence[CandidateEvent]) -> dict[str, Any]:
    """How far the registered past-only baseline keys are from being estimable at all.

    ``H-SIG21`` §5 keys on atomic type x side x distance band x 30-minute bucket x past-only
    liquidity bin x ``VOL-04`` regime, and needs at least 200 historical candidates per key from
    *completed prior sessions*. These tapes contain no completed prior session, so every key is
    ``baseline_insufficient`` by construction. The two conditioning axes that cannot be formed
    here are reported as such, and because adding an axis can only partition a key further, the
    counts below are strict upper bounds on any full six-axis key count.
    """

    partial: Counter[tuple[str, str, str, str]] = Counter()
    for candidate in candidates:
        partial[
            (
                str(candidate.atomic_type),
                candidate.side,
                candidate.distance_band,
                time_bucket_ist(candidate.receive_ts_ns),
            )
        ] += 1
    rows = [
        {
            "atomic_type": key[0],
            "side": key[1],
            "distance_band": key[2],
            "time_bucket": key[3],
            "observed_candidates_upper_bound": count,
            "shortfall_to_minimum_lower_bound": max(MIN_BASELINE_EVENTS - count, 0),
            "status": "baseline_insufficient",
        }
        for key, count in sorted(partial.items())
    ]
    counts = [row["observed_candidates_upper_bound"] for row in rows]
    meeting = sum(1 for value in counts if isinstance(value, int) and value >= MIN_BASELINE_EVENTS)
    return {
        "registered_key_axes": [
            "atomic_type",
            "side",
            "distance_band",
            "time_bucket_30m",
            "past_only_liquidity_bin",
            "vol04_regime",
        ],
        "axes_determinable_in_this_replay": [
            "atomic_type",
            "side",
            "distance_band",
            "time_bucket_30m",
        ],
        "axes_not_determinable_here": [
            {
                "axis": "past_only_liquidity_bin",
                "reason": (
                    "The bin edges are defined on completed prior sessions; none exist before "
                    "these tapes, and deriving edges from this sample would be a within-sample "
                    "threshold, which H-SIG21 §5 forbids."
                ),
            },
            {
                "axis": "vol04_regime",
                "reason": (
                    "No VOL-04 HMM regime label is fitted for this instrument-session, and "
                    "fitting one on an 11-minute window would again be within-sample."
                ),
            },
        ],
        "minimum_history_per_key": MIN_BASELINE_EVENTS,
        "keys_populated_partial": len(rows),
        "keys_meeting_minimum": meeting,
        "keys_meeting_minimum_full_six_axis": 0,
        "all_keys_status": "baseline_insufficient",
        "upper_bound_note": (
            "Counts are four-axis partial keys and are strict upper bounds on the full six-axis "
            "registered key counts, because the two missing axes can only partition further."
        ),
        "scored_candidates": 0,
        "thresholds_estimable": False,
        "registered_thresholds": list(REGISTERED_THRESHOLDS),
        "partial_keys": rows,
    }


def build_family_decomposition(grid: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """State plainly which of the 384 registered axes construction can and cannot measure."""

    populated = sum(1 for row in grid if int(row["candidate_count"]) > 0)
    return {
        "registered_family_size": REGISTERED_FAMILY_SIZE,
        "construction_determined_axes": [
            {"axis": "atomic_type", "levels": len(AtomicEventType)},
            {"axis": "side", "levels": len(REGISTERED_SIDES)},
            {"axis": "distance_band", "levels": len(REGISTERED_DISTANCE_BANDS)},
        ],
        "construction_cells": CONSTRUCTION_CELL_COUNT,
        "construction_cells_populated": populated,
        "construction_cells_empty": CONSTRUCTION_CELL_COUNT - populated,
        "multiplier_axes_not_measurable_here": [
            {
                "axis": "threshold",
                "levels": len(REGISTERED_THRESHOLDS),
                "values": list(REGISTERED_THRESHOLDS),
                "blocked_by": (
                    "needs the H-SIG21 §5 past-only empirical baseline over completed prior "
                    "sessions; none exist for these tapes"
                ),
            },
            {
                "axis": "gap_z_seconds",
                "levels": len(REGISTERED_GAPS_SECONDS),
                "values": list(REGISTERED_GAPS_SECONDS),
                "blocked_by": "defines the start of an outcome window; outcomes are excluded",
            },
            {
                "axis": "horizon_h2_seconds",
                "levels": len(REGISTERED_HORIZONS_SECONDS),
                "values": list(REGISTERED_HORIZONS_SECONDS),
                "blocked_by": "defines the outcome horizon itself; outcomes are excluded",
            },
        ],
        "family_cells_per_construction_cell": FAMILY_CELLS_PER_CONSTRUCTION_CELL,
        "family_cells_with_any_construction_support": (
            populated * FAMILY_CELLS_PER_CONSTRUCTION_CELL
        ),
        "family_cells_with_zero_construction_support": (
            (CONSTRUCTION_CELL_COUNT - populated) * FAMILY_CELLS_PER_CONSTRUCTION_CELL
        ),
        "note": (
            "The threshold, Z and h2 axes multiply the same construction support rather than "
            "adding independent support. A construction cell with zero candidates leaves all "
            f"{FAMILY_CELLS_PER_CONSTRUCTION_CELL} of its registered family cells empty."
        ),
    }


# Retention rates used only to bound the primary risk set. The last two coincide with the
# registered upper-tail thresholds, but nothing here ranks a magnitude or estimates a threshold:
# each row is the arithmetic bound min(retained bursts, floor(T / 11)).
RETENTION_SCENARIOS: tuple[float, ...] = (1.0, 0.1, 0.05, 0.01, 0.005, 0.001)


def build_scenario_extrapolation(
    *,
    total_candidates: int,
    total_bursts: int,
    total_non_overlapping_episodes: int,
    observed_seconds: float,
) -> dict[str, Any]:
    """Scenario-based, explicitly not a measurement (working contract §7.1 category)."""

    if observed_seconds <= 0:
        rate_candidates = 0.0
        rate_episodes = 0.0
        rate_bursts = 0.0
    else:
        rate_candidates = total_candidates / observed_seconds
        rate_episodes = total_non_overlapping_episodes / observed_seconds
        rate_bursts = total_bursts / observed_seconds
    session_candidates = rate_candidates * NSE_SESSION_SECONDS
    session_episodes = rate_episodes * NSE_SESSION_SECONDS
    session_bursts = rate_bursts * NSE_SESSION_SECONDS
    session_capacity = NSE_SESSION_SECONDS // EPISODE_WINDOW_SECONDS
    retention_bounds = [
        {
            "retained_fraction_of_bursts": fraction,
            "retained_bursts_per_session": session_bursts * fraction,
            "non_overlapping_episodes_upper_bound_per_session": min(
                session_bursts * fraction, float(session_capacity)
            ),
            "non_overlapping_episodes_upper_bound_calibration_sample": min(
                session_bursts * fraction, float(session_capacity)
            )
            * CALIBRATION_SESSIONS,
            "non_overlapping_episodes_upper_bound_evaluation_sample": min(
                session_bursts * fraction, float(session_capacity)
            )
            * EVALUATION_SESSIONS,
        }
        for fraction in RETENTION_SCENARIOS
    ]
    return {
        "object_category": "scenario_based",
        "is_measurement": False,
        "assumption": (
            "Candidate and episode arrival rates are assumed constant at the observed "
            "mid-morning rate for the whole session. This is an assumption, not an estimate."
        ),
        "bias_warning": (
            "The observed window is roughly eleven minutes of a single mid-morning stretch. It "
            "excludes the open and close, contains one 30-minute time bucket, one volatility "
            "regime and one contract, and cannot represent intraday seasonality in far-book "
            "activity. Treat every number below as an order-of-magnitude planning figure only."
        ),
        "observed_seconds": observed_seconds,
        "observed_candidates": total_candidates,
        "observed_bursts": total_bursts,
        "observed_non_overlapping_episodes": total_non_overlapping_episodes,
        "candidates_per_second": rate_candidates,
        "bursts_per_second": rate_bursts,
        "non_overlapping_episodes_per_second": rate_episodes,
        "full_session_seconds": NSE_SESSION_SECONDS,
        "episode_capacity_ceiling_per_session": session_capacity,
        "episode_linear_extrapolation_is_degenerate": (
            total_non_overlapping_episodes <= 2
        ),
        "episode_extrapolation_caveat": (
            "Linearly scaling the observed non-overlapping episode count is degenerate here: "
            "candidate activity is continuous, so each contiguous stretch of tape collapses to "
            "one episode and the observed count measures how many tapes there are rather than "
            "how much risk-set support exists. Read the capacity ceiling and the retention "
            "bounds instead."
        ),
        "scenarios": [
            {
                "scenario": "one_full_session",
                "sessions": 1,
                "candidates": session_candidates,
                "bursts": session_bursts,
                "non_overlapping_episodes_linear_degenerate": session_episodes,
                "non_overlapping_episodes_capacity_ceiling": session_capacity,
            },
            {
                "scenario": "registered_calibration_sample",
                "sessions": CALIBRATION_SESSIONS,
                "candidates": session_candidates * CALIBRATION_SESSIONS,
                "bursts": session_bursts * CALIBRATION_SESSIONS,
                "non_overlapping_episodes_linear_degenerate": (
                    session_episodes * CALIBRATION_SESSIONS
                ),
                "non_overlapping_episodes_capacity_ceiling": (
                    session_capacity * CALIBRATION_SESSIONS
                ),
            },
            {
                "scenario": "registered_evaluation_sample",
                "sessions": EVALUATION_SESSIONS,
                "candidates": session_candidates * EVALUATION_SESSIONS,
                "bursts": session_bursts * EVALUATION_SESSIONS,
                "non_overlapping_episodes_linear_degenerate": (
                    session_episodes * EVALUATION_SESSIONS
                ),
                "non_overlapping_episodes_capacity_ceiling": (
                    session_capacity * EVALUATION_SESSIONS
                ),
            },
        ],
        "retention_bounds": retention_bounds,
        "retention_bounds_note": (
            "Each row assumes some fraction of observed bursts survives the registered past-only "
            "threshold layer and reports the arithmetic upper bound on non-overlapping episodes, "
            "min(retained bursts, floor(session seconds / 11)). No magnitude was ranked and no "
            "threshold was estimated: H-SIG21 §5 forbids a within-sample threshold and none was "
            "computed."
        ),
    }


def protocol_metadata(replays: Sequence[TapeReplay]) -> dict[str, Any]:
    """The metadata every artifact must carry so its protocol status is unambiguous."""

    return {
        "protocol_id": PROTOCOL_ID,
        "sample_role": SAMPLE_ROLE,
        "outcome_join_allowed": OUTCOME_JOIN_ALLOWED,
        "registration_document": "docs/sig-claims/H-SIG21.md",
        "source_tapes": [
            {
                "run_id": replay.run_id,
                "sha256": replay.tape_sha256,
                "instrument_id": replay.instrument_id,
                "dhan_security_id": replay.dhan_security_id,
                "trading_symbol": replay.trading_symbol,
            }
            for replay in replays
        ],
        "excluded_by_registration": (
            "H-SIG21 §1.2 — the post-event price paths of these retained DAT-20 tapes are "
            "permanently excluded from SIG-21 inference. This artifact contains no response, "
            "return, label, midpoint, markout or outcome field."
        ),
    }


def build_replay_artifact(
    replays: Sequence[TapeReplay],
    *,
    requested_sections: Iterable[str] = (),
) -> dict[str, Any]:
    """Assemble the complete outcome-blind construction artifact."""

    assert_outcome_blind_request(requested_sections)
    candidates = [candidate for replay in replays for candidate in replay.candidates]
    observed_seconds = sum(replay.observed_seconds for replay in replays)
    grid = build_construction_grid(candidates, observed_seconds=observed_seconds)
    episodes = build_burst_and_episode_structure(
        [replay.candidates for replay in replays],
        observed_seconds=observed_seconds,
    )
    return {
        "protocol": protocol_metadata(replays),
        "totals": {
            "tapes": len(replays),
            "candidates": len(candidates),
            "distinct_bursts": episodes["total_bursts"],
            "non_overlapping_episodes": episodes["non_overlapping_episodes"],
            "observed_depth200_seconds": observed_seconds,
            "candidates_per_minute": (
                (len(candidates) / (observed_seconds / SECONDS_PER_MINUTE))
                if observed_seconds > 0
                else None
            ),
        },
        "family_decomposition": build_family_decomposition(grid),
        "construction_grid": grid,
        "time_of_day": build_time_of_day_breakdowns(
            candidates,
            windows=[
                (replay.first_receive_ts_ns, replay.last_receive_ts_ns)
                for replay in replays
                if replay.first_receive_ts_ns is not None and replay.last_receive_ts_ns is not None
            ],
        ),
        "distance": build_distance_breakdown(candidates),
        "burst_and_episode_structure": episodes,
        "exclusions": build_exclusion_breakdown(replays),
        "window_edge_proximity": build_edge_proximity(replays),
        "coverage": build_coverage(replays),
        "baseline_layer": build_baseline_layer(candidates),
        "scenario_extrapolation": build_scenario_extrapolation(
            total_candidates=len(candidates),
            total_bursts=int(episodes["total_bursts"]),
            total_non_overlapping_episodes=int(episodes["non_overlapping_episodes"]),
            observed_seconds=observed_seconds,
        ),
    }


def grid_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the grid to one JSONL row per construction cell, empty cells included."""

    protocol = artifact["protocol"]
    rows: list[dict[str, Any]] = []
    for row in artifact["construction_grid"]:
        flattened: dict[str, Any] = {
            "protocol_id": protocol["protocol_id"],
            "sample_role": protocol["sample_role"],
            "outcome_join_allowed": protocol["outcome_join_allowed"],
        }
        flattened.update(row)
        magnitude = flattened.pop("magnitude")
        for name, value in magnitude.items():
            flattened[f"magnitude_{name}"] = value
        rows.append(flattened)
    return rows
