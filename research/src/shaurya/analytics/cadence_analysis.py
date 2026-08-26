"""Receive-timestamp cadence measurements for retained Dhan tapes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from math import floor
from typing import Any


@dataclass(frozen=True, slots=True)
class CadenceResult:
    event_type: str
    rows: int
    bursts: int
    gaps: int
    window_seconds: float
    burst_rate_per_second: float | None
    rows_per_burst_mean: float | None
    gap_min_ms: float | None
    gap_p05_ms: float | None
    gap_p50_ms: float | None
    gap_p95_ms: float | None
    gap_max_ms: float | None
    modal_gap_bin_ms: str | None
    modal_gap_bin_count: int
    top_price_change_bursts: int
    top_price_change_fraction: float | None
    top_field_change_bursts: int
    top_field_change_fraction: float | None
    complete_five_level_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _top_price_signature(row: dict[str, Any]) -> tuple[Any, Any]:
    return row.get("best_bid"), row.get("best_ask")


def _level_signature(levels: Any) -> tuple[Any, Any, Any] | None:
    if not isinstance(levels, list) or not levels or not isinstance(levels[0], dict):
        return None
    level = levels[0]
    return level.get("price"), level.get("quantity"), level.get("orders")


def _top_field_signature(row: dict[str, Any]) -> tuple[Any, Any]:
    return _level_signature(row.get("bids")), _level_signature(row.get("asks"))


def analyze_cadence(rows: Iterable[dict[str, Any]], event_type: str) -> CadenceResult:
    """Measure cadence after exact grouping by distinct receive timestamp."""
    selected = [row for row in rows if row.get("event_type") == event_type]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in selected:
        timestamp = row.get("receive_ts")
        if not isinstance(timestamp, str):
            raise ValueError("every selected row must have a string receive_ts")
        grouped.setdefault(timestamp, []).append(row)

    ordered = sorted(grouped.items(), key=lambda item: datetime.fromisoformat(item[0]))
    timestamps = [datetime.fromisoformat(timestamp) for timestamp, _ in ordered]
    gaps_ms = [
        (current - previous).total_seconds() * 1000.0
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    gap_bins = Counter(int(floor(gap / 50.0)) * 50 for gap in gaps_ms)
    modal_start, modal_count = (gap_bins.most_common(1)[0] if gap_bins else (None, 0))

    price_changes = 0
    field_changes = 0
    previous_price: tuple[Any, Any] | None = None
    previous_fields: tuple[Any, Any] | None = None
    for _, burst_rows in ordered:
        final = burst_rows[-1]
        price = _top_price_signature(final)
        fields = _top_field_signature(final)
        if previous_price is not None and price != previous_price:
            price_changes += 1
        if previous_fields is not None and fields != previous_fields:
            field_changes += 1
        previous_price = price
        previous_fields = fields

    comparable_bursts = max(len(ordered) - 1, 0)
    window_seconds = (
        (timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) >= 2 else 0.0
    )
    complete_five_level_rows = sum(
        isinstance(row.get("bids"), list)
        and len(row["bids"]) == 5
        and isinstance(row.get("asks"), list)
        and len(row["asks"]) == 5
        for row in selected
    )
    return CadenceResult(
        event_type=event_type,
        rows=len(selected),
        bursts=len(ordered),
        gaps=len(gaps_ms),
        window_seconds=window_seconds,
        burst_rate_per_second=(comparable_bursts / window_seconds if window_seconds else None),
        rows_per_burst_mean=(len(selected) / len(ordered) if ordered else None),
        gap_min_ms=min(gaps_ms) if gaps_ms else None,
        gap_p05_ms=_percentile(gaps_ms, 0.05),
        gap_p50_ms=_percentile(gaps_ms, 0.50),
        gap_p95_ms=_percentile(gaps_ms, 0.95),
        gap_max_ms=max(gaps_ms) if gaps_ms else None,
        modal_gap_bin_ms=(
            f"[{modal_start},{modal_start + 50})" if modal_start is not None else None
        ),
        modal_gap_bin_count=modal_count,
        top_price_change_bursts=price_changes,
        top_price_change_fraction=(
            price_changes / comparable_bursts if comparable_bursts else None
        ),
        top_field_change_bursts=field_changes,
        top_field_change_fraction=(
            field_changes / comparable_bursts if comparable_bursts else None
        ),
        complete_five_level_rows=complete_five_level_rows,
    )
