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
        result.append((float(price), int(quantity), int(orders)))
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


# --------------------------------------------------------------------------------------
# Measurement 1 — cross-tier agreement
# --------------------------------------------------------------------------------------


def _compare(
    witness: BookState, comparand: BookState, levels: int
) -> dict[str, Any] | None:
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
                "pass_b_rate": (
                    ((counts[name] + resolved) / comparisons) if comparisons else None
                ),
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
        if entry["change_rate_per_second"] < threshold_per_second:
            index = entry["level"]
            if all(
                later["change_rate_per_second"] < threshold_per_second
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
    """Ask whether a witness tier saw a state inside a depth200 window that depth200 never published.

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
        while (
            local < len(witnesses)
            and witnesses[local].receive_ts_ns < closing.receive_ts_ns
        ):
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
        ((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
        + 0.254829592
    ) * t * pow(2.718281828459045, -x * x)
    return 1.0 - erf


# --------------------------------------------------------------------------------------
# Measurement 4 — occupancy and price span
# --------------------------------------------------------------------------------------


def occupancy_and_span(
    states: Sequence[BookState], *, tick_rupees: float = NSE_FNO_TICK_RUPEES
) -> dict[str, Any]:
    populated = {"bid": [], "ask": []}
    span = {"bid": [], "ask": []}
    total_span: list[float] = []
    contiguity_ratio = {"bid": [], "ask": []}
    missing_ticks = {"bid": [], "ask": []}
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
        "missing_ticks_within_span": {side: _quantiles(missing_ticks[side]) for side in missing_ticks},
        "padding_levels_zero_price": zero_price_levels,
        "padding_levels_zero_quantity": zero_quantity_levels,
        "tick_rupees_assumed_for_contiguity_only": tick_rupees,
    }
