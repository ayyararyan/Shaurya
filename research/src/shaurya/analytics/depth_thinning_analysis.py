"""DAT-20: activity-thinning versus feed-loss measurements for the depth200 channel.

Tests `H-DAT20` — that depth200's cadence skips are quiet book time rather than lost
packets, so depth200 is a superset of depth20 and of the Full packet's 5-level block.

Every measurement here is backward-looking by default (`DAT-15` discipline). Phase tolerance
is applied only as an explicitly separate, separately reported pass so that a clock-phase
artefact can never be silently counted as agreement.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from math import floor, isfinite, sqrt
from typing import Any

# NSE index-futures tick size in rupees. Used only to test contiguity of populated levels;
# no measurement below assumes levels are contiguous.
NSE_FNO_TICK_RUPEES = 0.05

DEPTH200 = "depth200"
DEPTH20 = "depth20"
FULL = "full"

# Pre-registered thresholds (DAT-20 §1.5, §1.6). Changing these changes the pre-registration.
SKIP_GAP_THRESHOLD_MS = 300.0
STRICT_STALENESS_BOUND_MS = 1_000.0
PHASE_TOLERANCES_MS = (250.0, 500.0)


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _quantiles(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "min": min(values) if values else None,
        "p05": percentile(values, 0.05),
        "p50": percentile(values, 0.50),
        "mean": (sum(values) / len(values)) if values else None,
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
    }


@dataclass(frozen=True, slots=True)
class BookState:
    """One complete book state as of a single receive timestamp on one channel."""

    channel: str
    receive_ts_ns: int
    receive_sequence: int
    connection_epoch: int
    bids: tuple[tuple[float, int, int], ...]
    asks: tuple[tuple[float, int, int], ...]
    rows_in_burst: int
    quality_flags: tuple[str, ...]

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    def ladder(self, side: str, levels: int) -> tuple[tuple[float, int, int], ...] | None:
        source = self.bids if side == "bid" else self.asks
        if len(source) < levels:
            return None
        return source[:levels]


def _parse_ts_ns(value: str) -> int:
    # receive_ts is an ISO-8601 UTC timestamp written by the collector; parse to integer
    # nanoseconds so that exact-equality grouping is not exposed to float rounding.
    date_part, _, time_part = value.partition("T")
    year, month, day = (int(item) for item in date_part.split("-"))
    clock, _, _offset = time_part.partition("+")
    if not _offset:
        clock = clock.rstrip("Z")
    hour, minute, second = clock.split(":")
    whole, _, fraction = second.partition(".")
    fraction = (fraction + "000000000")[:9]
    days = _days_from_civil(year, month, day)
    total = days * 86_400 + int(hour) * 3_600 + int(minute) * 60 + int(whole)
    return total * 1_000_000_000 + int(fraction)


def _days_from_civil(year: int, month: int, day: int) -> int:
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146_097 + day_of_era - 719_468


def parse_receive_ts_ns(value: str) -> int:
    """Public wrapper over the collector receive-timestamp parser, in integer nanoseconds."""

    return _parse_ts_ns(value)


# Prices must be quantised before any cross-tier equality test. The Full packet encodes its
# 5-level block prices as IEEE-754 binary32 (`FIVE_LEVEL_STRUCT` = "<IIHHff") while both depth
# channels encode binary64 (`DEEP_LEVEL` = "<dII"). A price such as 24118.9 therefore arrives as
# 24118.900390625 on Full and as 24118.9 on depth200, so exact float equality between the tiers
# is structurally impossible and would fabricate a 100% disagreement rate that has nothing to do
# with book content. Quantising to 2 decimal places is exact for the NSE 0.05-rupee tick: the
# binary32 representation error near 24,000 is about 0.002 rupees, far inside the 0.005 rounding
# half-width, so no genuine one-tick difference can be masked.
PRICE_DECIMALS = 2


def _levels(raw: Any) -> tuple[tuple[float, int, int], ...]:
    if not isinstance(raw, list):
        return ()
    result: list[tuple[float, int, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        quantity = item.get("quantity")
        orders = item.get("orders")
        if price is None or quantity is None or orders is None:
            continue
        result.append((round(float(price), PRICE_DECIMALS), int(quantity), int(orders)))
    return tuple(result)


def build_states(rows: Iterable[dict[str, Any]], channel: str) -> list[BookState]:
    """Collapse tape rows into one complete book state per distinct receive timestamp.

    Each depth20/depth200 tape row already carries the merged book for both sides (see
    ``DhanLiveStream._emit_deep``); the last row of a burst therefore holds the most complete
    state for that timestamp. Full rows carry both sides in a single row.
    """
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    order: list[tuple[int, int]] = []
    for row in rows:
        if row.get("event_type") != channel:
            continue
        raw_ts = row.get("receive_ts")
        if not isinstance(raw_ts, str):
            continue
        key = (_parse_ts_ns(raw_ts), int(row.get("connection_epoch") or 0))
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    states: list[BookState] = []
    for key in order:
        burst = grouped[key]
        last = burst[-1]
        flags: set[str] = set()
        for row in burst:
            for flag in row.get("quality_flags") or ():
                flags.add(str(flag))
        states.append(
            BookState(
                channel=channel,
                receive_ts_ns=key[0],
                receive_sequence=int(last.get("receive_sequence") or 0),
                connection_epoch=key[1],
                bids=_levels(last.get("bids")),
                asks=_levels(last.get("asks")),
                rows_in_burst=len(burst),
                quality_flags=tuple(sorted(flags)),
            )
        )
    states.sort(key=lambda state: (state.receive_ts_ns, state.receive_sequence))
    return states


def build_states_streaming(rows: Iterable[dict[str, Any]], channel: str) -> list[BookState]:
    """Collapse a chronological tape without retaining every full-book JSON object.

    A full-session three-tier tape is several gigabytes because each depth row repeats the
    complete ladder. The collector writes one channel/timestamp burst contiguously; retaining
    only its last row and union of flags is therefore equivalent to :func:`build_states` while
    keeping memory proportional to the compact state sequence rather than the raw tape.
    """

    states: list[BookState] = []
    current_key: tuple[int, int] | None = None
    current_last: dict[str, Any] | None = None
    current_flags: set[str] = set()
    rows_in_burst = 0

    def finish() -> None:
        if current_key is None or current_last is None:
            return
        states.append(
            BookState(
                channel=channel,
                receive_ts_ns=current_key[0],
                receive_sequence=int(current_last.get("receive_sequence") or 0),
                connection_epoch=current_key[1],
                bids=_levels(current_last.get("bids")),
                asks=_levels(current_last.get("asks")),
                rows_in_burst=rows_in_burst,
                quality_flags=tuple(sorted(current_flags)),
            )
        )

    for row in rows:
        if row.get("event_type") != channel:
            continue
        raw_ts = row.get("receive_ts")
        if not isinstance(raw_ts, str):
            continue
        key = (_parse_ts_ns(raw_ts), int(row.get("connection_epoch") or 0))
        if current_key is not None and key != current_key:
            finish()
            current_flags = set()
            rows_in_burst = 0
        current_key = key
        current_last = row
        rows_in_burst += 1
        for flag in row.get("quality_flags") or ():
            current_flags.add(str(flag))
    finish()
    return states


# --------------------------------------------------------------------------------------
# Measurement 1 — cross-tier agreement
# --------------------------------------------------------------------------------------


def _compare(witness: BookState, comparand: BookState, levels: int) -> dict[str, Any] | None:
    """Compare `levels` levels of two states. Returns None if either lacks the depth."""
    detail: dict[str, Any] = {
        "price_equal_by_level": [],
        "quantity_equal_by_level": [],
        "orders_equal_by_level": [],
    }
    for side in ("bid", "ask"):
        witness_ladder = witness.ladder(side, levels)
        comparand_ladder = comparand.ladder(side, levels)
        if witness_ladder is None or comparand_ladder is None:
            return None
    for side in ("bid", "ask"):
        witness_ladder = witness.ladder(side, levels)
        comparand_ladder = comparand.ladder(side, levels)
        assert witness_ladder is not None and comparand_ladder is not None
        for index in range(levels):
            w_price, w_qty, w_orders = witness_ladder[index]
            c_price, c_qty, c_orders = comparand_ladder[index]
            if side == "bid":
                detail["price_equal_by_level"].append(w_price == c_price)
                detail["quantity_equal_by_level"].append(w_qty == c_qty)
                detail["orders_equal_by_level"].append(w_orders == c_orders)
            else:
                detail["price_equal_by_level"][index] &= w_price == c_price
                detail["quantity_equal_by_level"][index] &= w_qty == c_qty
                detail["orders_equal_by_level"][index] &= w_orders == c_orders
    price = detail["price_equal_by_level"]
    quantity = detail["quantity_equal_by_level"]
    orders = detail["orders_equal_by_level"]
    detail["level1_price_equal"] = price[0]
    detail["level1_all_fields_equal"] = price[0] and quantity[0] and orders[0]
    detail["all_levels_price_equal"] = all(price)
    detail["all_levels_all_fields_equal"] = all(price) and all(quantity) and all(orders)
    return detail


def _last_at_or_before(states: Sequence[BookState], ts_ns: int, cursor: int) -> tuple[int, int]:
    """Advance `cursor` to the last state with receive_ts <= ts_ns. Returns (index, cursor)."""
    while cursor + 1 < len(states) and states[cursor + 1].receive_ts_ns <= ts_ns:
        cursor += 1
    if states[cursor].receive_ts_ns > ts_ns:
        return -1, cursor
    return cursor, cursor


def _any_match_within(
    states: Sequence[BookState],
    stamps: Sequence[int],
    witness: BookState,
    levels: int,
    tolerance_ms: float,
    granularity: str,
) -> bool:
    """Phase-tolerant match. `stamps` is the sorted receive_ts_ns list for `states`.

    The window is bisected rather than scanned so that the cost is proportional to the number
    of comparand states actually inside the tolerance, not to the length of the tape.
    """
    window_ns = int(tolerance_ms * 1_000_000)
    low = witness.receive_ts_ns - window_ns
    high = witness.receive_ts_ns + window_ns
    index = bisect_left(stamps, low)
    while index < len(states) and stamps[index] <= high:
        detail = _compare(witness, states[index], levels)
        if detail is not None and detail[granularity]:
            return True
        index += 1
    return False


GRANULARITIES = (
    "level1_price_equal",
    "level1_all_fields_equal",
    "all_levels_price_equal",
    "all_levels_all_fields_equal",
)


def agreement_pass(
    witnesses: Sequence[BookState],
    comparands: Sequence[BookState],
    levels: int,
    *,
    label: str,
    staleness_bound_ms: float = STRICT_STALENESS_BOUND_MS,
    phase_tolerances_ms: Sequence[float] = PHASE_TOLERANCES_MS,
) -> dict[str, Any]:
    """Pass A (strict backward) plus Pass B (phase-tolerant) for one witness/comparand pair."""
    if not comparands:
        return {"label": label, "levels": levels, "comparisons": 0, "note": "no comparand states"}
    counts = {name: 0 for name in GRANULARITIES}
    per_level = {
        "price": [0] * levels,
        "quantity": [0] * levels,
        "orders": [0] * levels,
    }
    staleness: list[float] = []
    comparisons = 0
    excluded_stale = 0
    excluded_depth = 0
    excluded_no_prior = 0
    disagreements: dict[str, list[BookState]] = {name: [] for name in GRANULARITIES}
    cursor = 0
    for witness in witnesses:
        index, cursor = _last_at_or_before(comparands, witness.receive_ts_ns, cursor)
        if index < 0:
            excluded_no_prior += 1
            continue
        comparand = comparands[index]
        age_ms = (witness.receive_ts_ns - comparand.receive_ts_ns) / 1_000_000
        if age_ms > staleness_bound_ms:
            excluded_stale += 1
            continue
        detail = _compare(witness, comparand, levels)
        if detail is None:
            excluded_depth += 1
            continue
        comparisons += 1
        staleness.append(age_ms)
        for name in GRANULARITIES:
            if detail[name]:
                counts[name] += 1
            else:
                disagreements[name].append(witness)
        for field_name, key in (
            ("price", "price_equal_by_level"),
            ("quantity", "quantity_equal_by_level"),
            ("orders", "orders_equal_by_level"),
        ):
            for level_index, equal in enumerate(detail[key]):
                if equal:
                    per_level[field_name][level_index] += 1
    result: dict[str, Any] = {
        "label": label,
        "levels": levels,
        "witness_states": len(witnesses),
        "comparisons": comparisons,
        "excluded_no_prior_comparand": excluded_no_prior,
        "excluded_stale_comparand": excluded_stale,
        "excluded_insufficient_depth": excluded_depth,
        "comparand_age_ms": _quantiles(staleness),
        "pass_a_strict_backward": {
            name: {
                "agree": counts[name],
                "rate": (counts[name] / comparisons) if comparisons else None,
            }
            for name in GRANULARITIES
        },
        "pass_a_per_level_agreement_rate": {
            field_name: [
                (value / comparisons) if comparisons else None for value in per_level[field_name]
            ]
            for field_name in per_level
        },
    }
    stamps = [state.receive_ts_ns for state in comparands]
    phase: dict[str, Any] = {}
    for tolerance in phase_tolerances_ms:
        entry: dict[str, Any] = {}
        for name in GRANULARITIES:
            failures = disagreements[name]
            resolved = sum(
                1
                for witness in failures
                if _any_match_within(comparands, stamps, witness, levels, tolerance, name)
            )
            entry[name] = {
                "pass_a_disagreements": len(failures),
                "resolved_by_phase": resolved,
                "genuine_content_difference": len(failures) - resolved,
                "pass_b_rate": (((counts[name] + resolved) / comparisons) if comparisons else None),
            }
        phase[f"tolerance_{int(tolerance)}ms"] = entry
    result["pass_b_phase_tolerant"] = phase
    return result


# --------------------------------------------------------------------------------------
# Measurement 2 — change rate by level index
# --------------------------------------------------------------------------------------


def change_rate_by_level(
    rows: Sequence[dict[str, Any]], side: str, *, levels: int = 200
) -> dict[str, Any]:
    """Fraction of depth200 same-side publications carrying a change at each level index."""
    sequence: list[tuple[int, tuple[tuple[float, int, int], ...]]] = []
    for row in rows:
        if row.get("event_type") != DEPTH200 or row.get("update_side") != side:
            continue
        raw_ts = row.get("receive_ts")
        if not isinstance(raw_ts, str):
            continue
        ladder = _levels(row.get("bids") if side == "bid" else row.get("asks"))
        sequence.append((_parse_ts_ns(raw_ts), ladder))
    sequence.sort(key=lambda item: item[0])
    if len(sequence) < 2:
        return {"side": side, "publications": len(sequence), "note": "insufficient publications"}
    span_seconds = (sequence[-1][0] - sequence[0][0]) / 1_000_000_000
    transitions = len(sequence) - 1
    changes = [0] * levels
    last_change_ts: list[int | None] = [None] * levels
    inter_change_ms: list[list[float]] = [[] for _ in range(levels)]
    for (_, previous), (ts_ns, current) in zip(sequence, sequence[1:], strict=False):
        for index in range(levels):
            before = previous[index] if index < len(previous) else None
            after = current[index] if index < len(current) else None
            if before != after:
                changes[index] += 1
                if last_change_ts[index] is not None:
                    inter_change_ms[index].append(
                        (ts_ns - last_change_ts[index]) / 1_000_000  # type: ignore[operator]
                    )
                last_change_ts[index] = ts_ns
    per_level = []
    for index in range(levels):
        gaps = inter_change_ms[index]
        per_level.append(
            {
                "level": index + 1,
                "changed_publications": changes[index],
                "change_fraction_of_publications": changes[index] / transitions,
                "change_rate_per_second": changes[index] / span_seconds,
                "inter_change_ms_mean": (sum(gaps) / len(gaps)) if gaps else None,
                "inter_change_ms_median": percentile(gaps, 0.50),
                "inter_change_observations": len(gaps),
            }
        )
    return {
        "side": side,
        "publications": len(sequence),
        "transitions": transitions,
        "span_seconds": span_seconds,
        "per_level": per_level,
    }


def crossing_level(per_level: Sequence[dict[str, Any]], threshold_per_second: float) -> int | None:
    """First level index whose change rate is below `threshold_per_second` and stays below."""
    for entry in per_level:
        if float(entry["change_rate_per_second"]) < threshold_per_second:
            index = int(entry["level"])
            if all(
                float(later["change_rate_per_second"]) < threshold_per_second
                for later in per_level[index - 1 :]
            ):
                return index
    return None


def spearman(values: Sequence[float]) -> float | None:
    """Spearman rank correlation of `values` against their own index (1..n)."""
    n = len(values)
    if n < 3:
        return None
    order = sorted(range(n), key=lambda index: values[index])
    ranks = [0.0] * n
    position = 0
    while position < n:
        end = position
        while end + 1 < n and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    mean_x = (n + 1) / 2
    mean_y = sum(ranks) / n
    numerator = sum((index + 1 - mean_x) * (ranks[index] - mean_y) for index in range(n))
    denominator = sqrt(
        sum((index + 1 - mean_x) ** 2 for index in range(n))
        * sum((rank - mean_y) ** 2 for rank in ranks)
    )
    if denominator == 0:
        return None
    return numerator / denominator


# --------------------------------------------------------------------------------------
# Measurement 3 — skip windows versus control windows
# --------------------------------------------------------------------------------------


@dataclass
class WindowOutcome:
    windows: int = 0
    windows_with_witness: int = 0
    witnesses: int = 0
    matches_open_only: int = 0
    matches_close_only: int = 0
    matches_both: int = 0
    matches_neither: int = 0
    unmeasurable_depth: int = 0
    gap_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        measured = self.matches_open_only + self.matches_close_only + self.matches_both
        measured += self.matches_neither
        return {
            "windows": self.windows,
            "windows_with_witness": self.windows_with_witness,
            "witness_observations": self.witnesses,
            "measured_witness_observations": measured,
            "unmeasurable_insufficient_depth": self.unmeasurable_depth,
            "matches_open_only": self.matches_open_only,
            "matches_close_only": self.matches_close_only,
            "matches_open_and_close_identical": self.matches_both,
            "matches_neither_unseen_state": self.matches_neither,
            "unseen_state_rate": (self.matches_neither / measured) if measured else None,
            "gap_ms": _quantiles(self.gap_ms),
        }


def skip_window_test(
    depth200: Sequence[BookState],
    witnesses: Sequence[BookState],
    levels: int,
    granularity: str,
    *,
    skip_threshold_ms: float = SKIP_GAP_THRESHOLD_MS,
) -> dict[str, Any]:
    """Did a witness tier see a state inside a depth200 window that depth200 never published?

    A window is bounded by two successive depth200 publications. `skip` windows exceed the
    threshold (at least one ~200 ms base slot produced nothing); `control` windows do not.
    The control arm exists so that a nonzero unseen-state count cannot be read as feed loss
    without the baseline rate of ordinary cross-tier disagreement.
    """
    skip = WindowOutcome()
    control = WindowOutcome()
    witness_cursor = 0
    for opening, closing in zip(depth200, depth200[1:], strict=False):
        gap_ms = (closing.receive_ts_ns - opening.receive_ts_ns) / 1_000_000
        bucket = skip if gap_ms > skip_threshold_ms else control
        bucket.windows += 1
        bucket.gap_ms.append(gap_ms)
        while (
            witness_cursor < len(witnesses)
            and witnesses[witness_cursor].receive_ts_ns <= opening.receive_ts_ns
        ):
            witness_cursor += 1
        local = witness_cursor
        found = 0
        while local < len(witnesses) and witnesses[local].receive_ts_ns < closing.receive_ts_ns:
            witness = witnesses[local]
            local += 1
            open_detail = _compare(witness, opening, levels)
            close_detail = _compare(witness, closing, levels)
            if open_detail is None or close_detail is None:
                bucket.unmeasurable_depth += 1
                bucket.witnesses += 1
                found += 1
                continue
            bucket.witnesses += 1
            found += 1
            open_match = bool(open_detail[granularity])
            close_match = bool(close_detail[granularity])
            if open_match and close_match:
                bucket.matches_both += 1
            elif open_match:
                bucket.matches_open_only += 1
            elif close_match:
                bucket.matches_close_only += 1
            else:
                bucket.matches_neither += 1
        if found:
            bucket.windows_with_witness += 1
    result = {
        "levels": levels,
        "granularity": granularity,
        "skip_threshold_ms": skip_threshold_ms,
        "skip_windows": skip.to_dict(),
        "control_windows": control.to_dict(),
    }
    result["two_proportion_test"] = _two_proportion_test(
        skip.matches_neither,
        skip.matches_open_only + skip.matches_close_only + skip.matches_both + skip.matches_neither,
        control.matches_neither,
        control.matches_open_only
        + control.matches_close_only
        + control.matches_both
        + control.matches_neither,
    )
    return result


def _two_proportion_test(
    successes_a: int, total_a: int, successes_b: int, total_b: int
) -> dict[str, Any]:
    if total_a == 0 or total_b == 0:
        return {"note": "one arm has no measured observations", "z": None, "p_two_sided": None}
    rate_a = successes_a / total_a
    rate_b = successes_b / total_b
    pooled = (successes_a + successes_b) / (total_a + total_b)
    variance = pooled * (1 - pooled) * (1 / total_a + 1 / total_b)
    if variance <= 0:
        return {
            "rate_skip": rate_a,
            "rate_control": rate_b,
            "z": None,
            "p_two_sided": None,
            "note": "zero pooled variance; both arms identical",
        }
    z = (rate_a - rate_b) / sqrt(variance)
    return {
        "rate_skip": rate_a,
        "rate_control": rate_b,
        "difference": rate_a - rate_b,
        "z": z,
        "p_two_sided": _normal_two_sided(z),
    }


def _normal_two_sided(z: float) -> float | None:
    if not isfinite(z):
        return None
    # Abramowitz & Stegun 7.1.26 error-function approximation; adequate for a screening test.
    x = abs(z) / sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * x)
    erf = 1.0 - (
        ((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592
    ) * t * pow(2.718281828459045, -x * x)
    return float(1.0 - erf)


# --------------------------------------------------------------------------------------
# Measurement 4 — occupancy and price span
# --------------------------------------------------------------------------------------


# Rupee distances at which the occupied level index is reported. This converts the price-keyed
# activity profile of measurement 2b into the level-count language DAT-09's width-versus-depth
# decision is stated in.
LEVEL_INDEX_AT_RUPEES = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0)


def occupancy_and_span(
    states: Sequence[BookState], *, tick_rupees: float = NSE_FNO_TICK_RUPEES
) -> dict[str, Any]:
    populated: dict[str, list[float]] = {"bid": [], "ask": []}
    span: dict[str, list[float]] = {"bid": [], "ask": []}
    total_span: list[float] = []
    contiguity_ratio: dict[str, list[float | None]] = {"bid": [], "ask": []}
    missing_ticks: dict[str, list[float]] = {"bid": [], "ask": []}
    level_index_at: dict[str, dict[float, list[int | None]]] = {
        side: {distance: [] for distance in LEVEL_INDEX_AT_RUPEES} for side in ("bid", "ask")
    }
    zero_price_levels = {"bid": 0, "ask": 0}
    zero_quantity_levels = {"bid": 0, "ask": 0}
    measured = 0
    for state in states:
        bid_levels = [level for level in state.bids if level[0] > 0 and level[1] > 0]
        ask_levels = [level for level in state.asks if level[0] > 0 and level[1] > 0]
        zero_price_levels["bid"] += sum(1 for level in state.bids if level[0] <= 0)
        zero_price_levels["ask"] += sum(1 for level in state.asks if level[0] <= 0)
        zero_quantity_levels["bid"] += sum(
            1 for level in state.bids if level[0] > 0 and level[1] <= 0
        )
        zero_quantity_levels["ask"] += sum(
            1 for level in state.asks if level[0] > 0 and level[1] <= 0
        )
        if not bid_levels or not ask_levels:
            continue
        measured += 1
        mid = (bid_levels[0][0] + ask_levels[0][0]) / 2
        populated["bid"].append(len(bid_levels))
        populated["ask"].append(len(ask_levels))
        span["bid"].append(mid - bid_levels[-1][0])
        span["ask"].append(ask_levels[-1][0] - mid)
        total_span.append(ask_levels[-1][0] - bid_levels[-1][0])
        for side, levels in (("bid", bid_levels), ("ask", ask_levels)):
            best = levels[0][0]
            for distance in LEVEL_INDEX_AT_RUPEES:
                count = sum(1 for level in levels if abs(level[0] - best) <= distance)
                # None means the ladder does not reach this distance at all at this instant.
                level_index_at[side][distance].append(
                    count if abs(levels[-1][0] - best) >= distance else None
                )
            price_range = abs(levels[-1][0] - levels[0][0])
            contiguous = round(price_range / tick_rupees) + 1
            contiguity_ratio[side].append(len(levels) / contiguous if contiguous else None)
            missing_ticks[side].append(max(contiguous - len(levels), 0))
    return {
        "states_measured": measured,
        "states_total": len(states),
        "populated_levels": {side: _quantiles(populated[side]) for side in populated},
        "rupees_mid_to_deepest": {side: _quantiles(span[side]) for side in span},
        "rupees_total_span_deepest_bid_to_deepest_ask": _quantiles(total_span),
        "contiguity_ratio_populated_over_tick_span": {
            side: _quantiles([value for value in contiguity_ratio[side] if value is not None])
            for side in contiguity_ratio
        },
        "missing_ticks_within_span": {
            side: _quantiles(missing_ticks[side]) for side in missing_ticks
        },
        "occupied_levels_within_rupees_of_same_side_best": {
            side: {
                f"{distance:g}": (
                    _quantiles([v for v in level_index_at[side][distance] if v is not None])
                    | {
                        "instants_ladder_did_not_reach_this_distance": sum(
                            1 for v in level_index_at[side][distance] if v is None
                        )
                    }
                )
                for distance in LEVEL_INDEX_AT_RUPEES
            }
            for side in ("bid", "ask")
        },
        "padding_levels_zero_price": zero_price_levels,
        "padding_levels_zero_quantity": zero_quantity_levels,
        "tick_rupees_assumed_for_contiguity_only": tick_rupees,
    }


# --------------------------------------------------------------------------------------
# Measurement 1b — set containment (the direct test of the superset claim)
# --------------------------------------------------------------------------------------


def containment_pass(
    witnesses: Sequence[BookState],
    comparands: Sequence[BookState],
    levels: int,
    *,
    label: str,
    max_lag_ms: float = STRICT_STALENESS_BOUND_MS,
) -> dict[str, Any]:
    """Test whether the witness ladder is *contained* in the comparand ladder.

    Positional equality is the wrong test for a superset claim: a single price point present in
    one feed and absent from the other shifts every level below it, so one extra level makes all
    deeper positions mismatch. Containment asks the question `H-DAT20` actually poses — is every
    level the cheaper tier reports also reported by depth200?

    `missing_in_comparand` is the quantity that bears on falsifier `F2`: a level the cheaper tier
    published that depth200 never carried at all.
    """
    if not comparands:
        return {"label": label, "levels": levels, "pairs": 0, "note": "no comparand states"}
    stats: dict[str, dict[str, list[float]]] = {
        side: {
            "price_containment": [],
            "triple_containment": [],
            "positional_prefix_match": [],
            "missing_prices": [],
            "extra_prices_inside_witness_range": [],
        }
        for side in ("bid", "ask")
    }
    perfect_price = {"bid": 0, "ask": 0}
    perfect_triple = {"bid": 0, "ask": 0}
    lags: list[float] = []
    pairs = 0
    cursor = 0
    for witness in witnesses:
        index, cursor = _last_at_or_before(comparands, witness.receive_ts_ns, cursor)
        if index < 0:
            continue
        comparand = comparands[index]
        lag_ms = (witness.receive_ts_ns - comparand.receive_ts_ns) / 1_000_000
        if lag_ms > max_lag_ms:
            continue
        witness_bid = witness.ladder("bid", levels)
        witness_ask = witness.ladder("ask", levels)
        if witness_bid is None or witness_ask is None:
            continue
        pairs += 1
        lags.append(lag_ms)
        for side, witness_ladder, comparand_ladder in (
            ("bid", witness_bid, comparand.bids),
            ("ask", witness_ask, comparand.asks),
        ):
            comparand_prices = {level[0] for level in comparand_ladder}
            comparand_triples = set(comparand_ladder)
            witness_prices = {level[0] for level in witness_ladder}
            found_price = sum(1 for level in witness_ladder if level[0] in comparand_prices)
            found_triple = sum(1 for level in witness_ladder if level in comparand_triples)
            size = len(witness_ladder)
            stats[side]["price_containment"].append(found_price / size)
            stats[side]["triple_containment"].append(found_triple / size)
            stats[side]["missing_prices"].append(size - found_price)
            if found_price == size:
                perfect_price[side] += 1
            if found_triple == size:
                perfect_triple[side] += 1
            best = witness_ladder[0][0]
            worst = witness_ladder[-1][0]
            low, high = (worst, best) if side == "bid" else (best, worst)
            extra = sum(
                1
                for level in comparand_ladder
                if low <= level[0] <= high and level[0] not in witness_prices
            )
            stats[side]["extra_prices_inside_witness_range"].append(extra)
            prefix = 0
            for witness_level, comparand_level in zip(
                witness_ladder, comparand_ladder, strict=False
            ):
                if witness_level == comparand_level:
                    prefix += 1
                else:
                    break
            stats[side]["positional_prefix_match"].append(prefix)
    return {
        "label": label,
        "levels": levels,
        "max_lag_ms": max_lag_ms,
        "pairs": pairs,
        "receive_lag_ms": _quantiles(lags),
        "by_side": {
            side: {key: _quantiles(values) for key, values in stats[side].items()}
            | {
                "pairs_with_full_price_containment": perfect_price[side],
                "pairs_with_full_price_containment_rate": (
                    perfect_price[side] / pairs if pairs else None
                ),
                "pairs_with_full_triple_containment": perfect_triple[side],
                "pairs_with_full_triple_containment_rate": (
                    perfect_triple[side] / pairs if pairs else None
                ),
            }
            for side in ("bid", "ask")
        },
    }


# --------------------------------------------------------------------------------------
# Measurement 2b — price-keyed activity by distance from mid
# --------------------------------------------------------------------------------------

# Rupee distance bands from mid. Chosen to straddle the measured NIFTY-future spread rather
# than to fit a result: the median spread on this tape is about Rs 5, so the first band is
# entirely inside the spread and the later bands cover the visible ladder.
DISTANCE_BANDS_RUPEES: tuple[tuple[float, float], ...] = (
    (0.0, 1.0),
    (1.0, 2.0),
    (2.0, 5.0),
    (5.0, 10.0),
    (10.0, 20.0),
    (20.0, 50.0),
    (50.0, float("inf")),
)


def _band_index(distance: float) -> int:
    for index, (low, high) in enumerate(DISTANCE_BANDS_RUPEES):
        if low <= distance < high:
            return index
    return len(DISTANCE_BANDS_RUPEES) - 1


def activity_by_distance(
    states: Sequence[BookState],
    side: str,
    *,
    reference: str = "mid",
    exclude_boundary_levels: int = 0,
) -> dict[str, Any]:
    """Price-keyed activity as a function of rupee distance from mid.

    Position-keyed change counting (measurement 2) cannot separate two different things: real
    activity at a price point, and the positional shift that a single insertion or deletion
    higher in the book forces onto every level beneath it. A price-keyed measurement is the only
    one that answers the question `H-DAT20` actually asks — does a given *price point* become
    quieter as it moves away from the BBO?

    Events are classified as modification (the price survived and its quantity or order count
    changed), insertion (a new price point appeared) or deletion (a price point vanished).
    `events_per_second_per_price_point` normalises by exposure, so a band containing many price
    points is not credited with more activity merely for being wide.

    `reference` selects the origin for the distance measure. ``"mid"`` measures distance from the
    mid price; ``"same_side_best"`` measures distance from the best quote on the same side. The
    second is the one that tests `H-DAT20` directly: with a median spread of about Rs 5 on this
    instrument, every band closer to mid than the best quote is almost always empty, so mid-keyed
    near bands carry almost no exposure and their rates are not comparable to the rest.

    `exclude_boundary_levels` drops the deepest N levels of each snapshot from the comparison. The
    200-level ladder is a sliding window: when the book shifts, the deepest levels leave and new
    ones enter purely because the window moved, and those are not order-book events. Excluding a
    boundary margin removes that artifact.
    """
    sequence = [
        state
        for state in states
        if state.channel and state.bids and state.asks and state.rows_in_burst
    ]
    if len(sequence) < 2:
        return {"side": side, "transitions": 0, "note": "insufficient states"}
    span_seconds = (sequence[-1].receive_ts_ns - sequence[0].receive_ts_ns) / 1_000_000_000
    bands: list[dict[str, Any]] = [
        {
            "band_rupees": f"[{low:g},{high:g})",
            "price_point_exposure": 0,
            "modifications": 0,
            "insertions": 0,
            "deletions": 0,
        }
        for low, high in DISTANCE_BANDS_RUPEES
    ]
    transitions = 0
    for earlier, later in zip(sequence, sequence[1:], strict=False):
        best_bid = earlier.best_bid
        best_ask = earlier.best_ask
        if best_bid is None or best_ask is None:
            continue
        if reference == "same_side_best":
            origin = best_bid if side == "bid" else best_ask
        else:
            origin = (best_bid + best_ask) / 2
        earlier_levels = [
            level for level in (earlier.bids if side == "bid" else earlier.asks) if level[0] > 0
        ]
        later_levels = [
            level for level in (later.bids if side == "bid" else later.asks) if level[0] > 0
        ]
        if exclude_boundary_levels > 0:
            earlier_levels = earlier_levels[: max(len(earlier_levels) - exclude_boundary_levels, 0)]
            later_levels = later_levels[: max(len(later_levels) - exclude_boundary_levels, 0)]
            if not earlier_levels or not later_levels:
                continue
            # Only the price range both snapshots actually cover can be compared, otherwise a
            # window shift reappears as an insertion or deletion at the truncated edge.
            if side == "bid":
                floor_price = max(earlier_levels[-1][0], later_levels[-1][0])
                earlier_levels = [lv for lv in earlier_levels if lv[0] >= floor_price]
                later_levels = [lv for lv in later_levels if lv[0] >= floor_price]
            else:
                ceiling_price = min(earlier_levels[-1][0], later_levels[-1][0])
                earlier_levels = [lv for lv in earlier_levels if lv[0] <= ceiling_price]
                later_levels = [lv for lv in later_levels if lv[0] <= ceiling_price]
        before = {level[0]: (level[1], level[2]) for level in earlier_levels}
        after = {level[0]: (level[1], level[2]) for level in later_levels}
        if not before or not after:
            continue
        transitions += 1
        for price, value in before.items():
            band = bands[_band_index(abs(price - origin))]
            band["price_point_exposure"] += 1
            if price not in after:
                band["deletions"] += 1
            elif after[price] != value:
                band["modifications"] += 1
        for price in after:
            if price not in before:
                bands[_band_index(abs(price - origin))]["insertions"] += 1
    for band in bands:
        events = int(band["modifications"]) + int(band["insertions"]) + int(band["deletions"])
        exposure = int(band["price_point_exposure"])
        band["total_events"] = events
        band["mean_price_points_present"] = (exposure / transitions) if transitions else None
        band["events_per_second"] = (events / span_seconds) if span_seconds else None
        band["events_per_second_per_price_point"] = (
            (events / span_seconds) / (exposure / transitions)
            if span_seconds and exposure and transitions
            else None
        )
        band["modification_rate_per_price_point_per_second"] = (
            (int(band["modifications"]) / span_seconds) / (exposure / transitions)
            if span_seconds and exposure and transitions
            else None
        )
    normalised = [
        band["events_per_second_per_price_point"]
        for band in bands
        if band["events_per_second_per_price_point"] is not None
    ]
    grand_total = sum(band["total_events"] for band in bands)
    for band in bands:
        band["share_of_all_events"] = (band["total_events"] / grand_total) if grand_total else None
    cumulative = 0.0
    share_within: dict[str, float | None] = {}
    for index, (band, (_low, high)) in enumerate(zip(bands, DISTANCE_BANDS_RUPEES, strict=False)):
        cumulative += band["total_events"]
        if index < len(bands) - 1:
            share_within[f"within_{high:g}_rupees"] = (
                (cumulative / grand_total) if grand_total else None
            )
    return {
        "side": side,
        "reference": reference,
        "exclude_boundary_levels": exclude_boundary_levels,
        "transitions": transitions,
        "span_seconds": span_seconds,
        "bands": bands,
        "total_events": grand_total,
        "cumulative_event_share_within_distance": share_within,
        "spearman_band_index_vs_events_per_price_point": spearman(normalised),
        "note": (
            "A negative Spearman coefficient means a price point does get quieter with "
            "distance from mid, which is the H-DAT20 mechanism. A positive coefficient "
            "refutes it."
        ),
    }


# --------------------------------------------------------------------------------------
# Measurement 3b — duration-matched skip test
# --------------------------------------------------------------------------------------

# Duration band used to match a single skipped ~400 ms window against a ~400 ms span that
# depth200 actually covered with two ~200 ms publications.
MATCHED_DURATION_BAND_MS = (340.0, 460.0)


def duration_matched_skip_test(
    depth200: Sequence[BookState],
    witnesses: Sequence[BookState],
    levels: int,
    granularity: str,
    *,
    duration_band_ms: tuple[float, float] = MATCHED_DURATION_BAND_MS,
    max_steps: int = 3,
) -> dict[str, Any]:
    """Isolate the missing publication from the longer elapsed time.

    Measurement 3's skip-versus-control contrast is confounded: a skipped window is about 400 ms
    long and a control window about 200 ms, so a witness landing inside a skip window has twice as
    long for the book to move away from both endpoints even if nothing was lost.

    This test holds duration fixed instead. Both arms are spans of roughly the same length, taken
    between depth200 publications *k* steps apart:

    - **arm without interior publication** (`k = 1`): a genuine skip. depth200 published nothing
      inside the span.
    - **arm with interior publication** (`k >= 2`): depth200 did publish inside the span, and that
      interior state is deliberately ignored when scoring.

    If the missing publication carried information, the no-interior arm must show a higher
    unseen-state rate. If the rates match, the skipped tick carried nothing — that is `C3`.
    """
    low, high = duration_band_ms
    arms: dict[str, dict[str, Any]] = {
        "no_interior_publication": {"spans": 0, "measured": 0, "unseen": 0, "durations": []},
        "with_interior_publication": {"spans": 0, "measured": 0, "unseen": 0, "durations": []},
    }
    stamps = [state.receive_ts_ns for state in witnesses]
    for start in range(len(depth200)):
        for steps in range(1, max_steps + 1):
            end = start + steps
            if end >= len(depth200):
                break
            opening = depth200[start]
            closing = depth200[end]
            duration_ms = (closing.receive_ts_ns - opening.receive_ts_ns) / 1_000_000
            if duration_ms > high:
                break
            if duration_ms < low:
                continue
            arm = arms["no_interior_publication" if steps == 1 else "with_interior_publication"]
            arm["spans"] += 1
            arm["durations"].append(duration_ms)
            index = bisect_left(stamps, opening.receive_ts_ns + 1)
            while index < len(witnesses) and stamps[index] < closing.receive_ts_ns:
                witness = witnesses[index]
                index += 1
                open_detail = _compare(witness, opening, levels)
                close_detail = _compare(witness, closing, levels)
                if open_detail is None or close_detail is None:
                    continue
                arm["measured"] += 1
                if not open_detail[granularity] and not close_detail[granularity]:
                    arm["unseen"] += 1
    for arm in arms.values():
        arm["unseen_state_rate"] = (arm["unseen"] / arm["measured"]) if arm["measured"] else None
        arm["duration_ms"] = _quantiles(arm["durations"])
        del arm["durations"]
    without = arms["no_interior_publication"]
    with_interior = arms["with_interior_publication"]
    return {
        "levels": levels,
        "granularity": granularity,
        "duration_band_ms": list(duration_band_ms),
        "arms": arms,
        "two_proportion_test": _two_proportion_test(
            without["unseen"],
            without["measured"],
            with_interior["unseen"],
            with_interior["measured"],
        ),
    }
