"""Identity and causal-row guard for `X-OFI-LATEPARTIAL-2026-08-20`."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.timing import IST

PROTOCOL_ID = "X-OFI-LATEPARTIAL-2026-08-20"
SOURCE_SPEC = "docs/OFI-LATE-PARTIAL-EXPLORATORY-SPEC-2026-08-20.md"
EXPECTED_RUN_ID = "sha-20260820T035146.093420Z-91f76404"
EXPECTED_INSTRUMENT_ID = "NSE:NSE_FNO:NIFTY:future:2026-08-25"
EXPECTED_SECURITY_ID = "58072"
EXPECTED_FIRST_ROW_LOWER = datetime(2026, 8, 20, 9, 21, 45, tzinfo=IST)
EXPECTED_FIRST_ROW_UPPER = datetime(2026, 8, 20, 9, 21, 50, tzinfo=IST)
FINAL_CLIP = datetime(2026, 8, 20, 15, 40, 0, tzinfo=IST)
REQUIRED_CHANNELS = ("full", "depth20", "depth200")


@dataclass(frozen=True, slots=True)
class PartialSnapshot:
    run_id: str
    instrument_id: str
    tape_sha256: str
    rows: int
    first_receive_ts: str
    last_receive_ts: str
    channel_rows: Mapping[str, int]
    complete_depth20_rows: int
    complete_depth200_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stamp(row: Mapping[str, Any]) -> datetime:
    raw = row.get("receive_ts")
    if not isinstance(raw, str):
        raise ValueError("late-partial row is missing receive_ts")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError("late-partial receive_ts must be timezone aware")
    return parsed.astimezone(IST)


def _validate_identity(row: Mapping[str, Any], path: Path) -> None:
    if row.get("run_id") != EXPECTED_RUN_ID:
        raise ValueError(f"{path} contains a row outside expected run {EXPECTED_RUN_ID}")
    if row.get("instrument_id") != EXPECTED_INSTRUMENT_ID:
        raise ValueError(f"{path} contains a row outside expected instrument")
    if str(row.get("broker_security_id") or "") != EXPECTED_SECURITY_ID:
        raise ValueError(f"{path} contains a row outside expected security ID")


def iter_late_partial_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Yield only the approved partial interval, validating every emitted row."""

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                loaded = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not complete JSON") from exc
            if not isinstance(loaded, dict):
                raise ValueError(f"{path}:{line_number} is not an object")
            _validate_identity(loaded, path)
            stamp = _stamp(loaded)
            if stamp < EXPECTED_FIRST_ROW_LOWER:
                raise ValueError(f"{path} contains a row before the approved partial start")
            if stamp <= FINAL_CLIP:
                yield loaded


def inspect_late_partial_snapshot(path: Path) -> PartialSnapshot:
    counts = dict.fromkeys(REQUIRED_CHANNELS, 0)
    rows = 0
    first: datetime | None = None
    last: datetime | None = None
    complete20 = 0
    complete200 = 0
    for row in iter_late_partial_rows(path):
        stamp = _stamp(row)
        first = stamp if first is None else min(first, stamp)
        last = stamp if last is None else max(last, stamp)
        rows += 1
        event_type = row.get("event_type")
        if event_type in counts:
            counts[event_type] += 1
        if event_type == "depth20" and len(row.get("bids") or ()) == 20 and len(
            row.get("asks") or ()
        ) == 20:
            complete20 += 1
        if event_type == "depth200" and len(row.get("bids") or ()) == 200 and len(
            row.get("asks") or ()
        ) == 200:
            complete200 += 1
    if rows == 0 or first is None or last is None:
        raise ValueError(f"{path} has no rows in the approved partial interval")
    if not EXPECTED_FIRST_ROW_LOWER <= first <= EXPECTED_FIRST_ROW_UPPER:
        raise ValueError(f"{path} first retained row {first.isoformat()} is outside frozen bounds")
    missing = [channel for channel, count in counts.items() if count == 0]
    if missing:
        raise ValueError(f"{path} is missing required channels: {', '.join(missing)}")
    if complete20 == 0 or complete200 == 0:
        raise ValueError(f"{path} has no complete deep-book rows")
    return PartialSnapshot(
        run_id=EXPECTED_RUN_ID,
        instrument_id=EXPECTED_INSTRUMENT_ID,
        tape_sha256=_sha256(path),
        rows=rows,
        first_receive_ts=first.isoformat(),
        last_receive_ts=last.isoformat(),
        channel_rows=counts,
        complete_depth20_rows=complete20,
        complete_depth200_rows=complete200,
    )


def partial_claim(source_scan_id: str, snapshot: PartialSnapshot) -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "source_spec": SOURCE_SPEC,
        "source_scan_id": source_scan_id,
        "sample_role": "growing_partial_session_exploratory",
        "confirmatory_eligible": False,
        "registered_replication_eligible": False,
        "sig21_calibration_eligible": False,
        "order_entry_enabled": False,
        "cross_tape_stability_supported": False,
        "snapshot": snapshot.to_dict(),
    }
