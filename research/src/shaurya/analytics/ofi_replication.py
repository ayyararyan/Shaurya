"""DAT-21: identity, coverage, and clipping for the full-session OFI replication.

`CCZ-IMPL-07`.  Coverage and identity are estimator-independent and are unchanged.  The receipt
now records which estimator the run's analysis stages used, so a receipt produced after
``D37 / CCZ-OFI-MIGRATION-2026-08-20`` is never mistaken for one produced before it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    DhanInstrumentMaster,
    InstrumentKind,
)
from shaurya.contracts.timing import IST, nse_equity_derivatives_session_bounds

from shaurya.signals.ccz_ofi import ccz_metadata

PROTOCOL_ID = "R-OFI-FULLSESSION-2026-08-20"
REGISTRATION_COMMIT = "af9bec17694b5cf45f1d670113f14b02efb1e418"
SOURCE_SPEC = "research/docs/live-evidence/OFI-FULL-SESSION-REPLICATION-SPEC-2026-08-20.md"
SOURCE_AMENDMENT = "research/docs/live-evidence/OFI-FULL-SESSION-REPLICATION-SPEC-AMENDMENT-1-2026-08-19.md"
MIGRATION_DOCUMENT = "research/docs/legacy/CCZ-OFI-MIGRATION-SPEC-2026-08-20.md"
TRADING_DATE = date(2026, 8, 20)
OPENING_PUBLICATION_TOLERANCE = timedelta(seconds=2)
CLOSING_PUBLICATION_TOLERANCE = timedelta(seconds=2)
REQUIRED_CHANNELS = ("standard", "depth20", "depth200")


def resolve_nifty_front_month_future(
    master: DhanInstrumentMaster, *, trading_date: date
) -> DhanInstrumentMapping:
    """Resolve one exact same-day NIFTY future with the nearest unexpired expiry."""

    candidates = [
        mapping
        for mapping in master.mappings()
        if mapping.as_of_date == trading_date
        and mapping.instrument.kind is InstrumentKind.FUTURE
        and mapping.instrument.underlying.strip().upper() == "NIFTY"
        and mapping.instrument.expiry is not None
        and mapping.instrument.expiry >= trading_date
    ]
    if not candidates:
        raise ValueError("same-day Dhan master contains no unexpired NIFTY future")
    expiries = [
        mapping.instrument.expiry for mapping in candidates if mapping.instrument.expiry is not None
    ]
    expiry = min(expiries)
    front = [mapping for mapping in candidates if mapping.instrument.expiry == expiry]
    if len(front) != 1:
        raise ValueError("same-day Dhan master does not resolve a unique NIFTY front-month future")
    return front[0]


def parse_receive_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(IST)


def _protocol_metadata(metrics: Mapping[str, Any]) -> Mapping[str, Any]:
    configuration = metrics.get("test_configuration")
    if not isinstance(configuration, Mapping):
        raise ValueError("capture metrics lacks test_configuration")
    protocol = configuration.get("ofi_full_session_replication_protocol")
    if not isinstance(protocol, Mapping):
        raise ValueError("capture metrics lacks the OFI full-session protocol metadata")
    expected = {
        "protocol_id": PROTOCOL_ID,
        "source_spec": SOURCE_SPEC,
        "source_amendment": SOURCE_AMENDMENT,
        "registration_commit": REGISTRATION_COMMIT,
        "sample_role": "prospective_full_session_replication",
        "trading_date": TRADING_DATE.isoformat(),
        "outcome_join_allowed": True,
        "sig21_calibration_eligible": False,
        "order_entry_enabled": False,
    }
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise ValueError(f"capture metrics has wrong OFI protocol field {key}")
    configured = {
        "standard": configuration.get("standard_full_5_level") is True,
        "depth20": configuration.get("depth20") is True,
        "depth200": configuration.get("depth200") is True,
    }
    missing = [name for name, enabled in configured.items() if not enabled]
    if missing:
        raise ValueError("OFI replication capture omitted channels: " + ",".join(missing))
    return protocol


def assert_replication_metrics(metrics: Mapping[str, Any]) -> None:
    """Validate immutable protocol and identity metadata without reading the raw tape."""

    _protocol_metadata(metrics)
    parts = str(metrics.get("instrument_id") or "").split(":")
    if len(parts) < 5 or parts[2].upper() != "NIFTY" or parts[3] != "future":
        raise ValueError("OFI replication capture is not a NIFTY future")
    for field in ("run_id", "dhan_security_id", "trading_symbol"):
        if not str(metrics.get(field) or ""):
            raise ValueError(f"OFI replication capture has no {field}")


def iter_session_rows(tape: Path, *, trading_date: date = TRADING_DATE) -> Iterator[dict[str, Any]]:
    """Yield only rows inside the exact dated regular session, in tape order."""

    def tape_rows() -> Iterator[dict[str, Any]]:
        with tape.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                loaded = json.loads(line)
                if isinstance(loaded, dict):
                    yield loaded

    yield from iter_session_records(tape_rows(), trading_date=trading_date)


def iter_session_records(
    rows: Iterable[Mapping[str, Any]], *, trading_date: date = TRADING_DATE
) -> Iterator[dict[str, Any]]:
    """Yield logical rows inside the exact dated regular session, preserving order."""

    opened, closed = nse_equity_derivatives_session_bounds(trading_date)
    for row in rows:
        stamp = parse_receive_ts(row.get("receive_ts"))
        if stamp is not None and opened <= stamp <= closed:
            yield dict(row)


def filtered_session_rows(tape: Path, event_types: Iterable[str]) -> list[dict[str, Any]]:
    wanted = frozenset(event_types)
    return [row for row in iter_session_rows(tape) if row.get("event_type") in wanted]


def inspect_replication_capture(
    tape: Path,
    metrics: Mapping[str, Any],
    *,
    tape_sha256: str,
    manifest_sha256: str | None,
    inspected_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a legacy-tape acceptance receipt through the format-neutral row checker."""

    def rows() -> Iterator[dict[str, Any]]:
        with tape.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                loaded = json.loads(line)
                if isinstance(loaded, dict):
                    yield loaded

    return inspect_replication_rows(
        rows(),
        metrics,
        data_digest=tape_sha256,
        catalog_digest=manifest_sha256,
        inspected_at=inspected_at,
        source={
            "tape": str(tape),
            "tape_sha256": tape_sha256,
            "manifest_sha256": manifest_sha256,
        },
    )


def inspect_replication_rows(
    rows: Iterable[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    *,
    data_digest: str,
    catalog_digest: str | None,
    inspected_at: datetime | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the terminal acceptance receipt from logical receive-ordered rows."""

    reasons: list[str] = []
    try:
        assert_replication_metrics(metrics)
    except ValueError as exc:
        reasons.append(str(exc))
    if catalog_digest is None:
        reasons.append("catalogue does not contain a closed-dataset digest")
    elif catalog_digest != data_digest:
        reasons.append("logical data digest does not match the catalogue")

    opened, closed = nse_equity_derivatives_session_bounds(TRADING_DATE)
    first: dict[str, datetime | None] = {channel: None for channel in REQUIRED_CHANNELS}
    last: dict[str, datetime | None] = {channel: None for channel in REQUIRED_CHANNELS}
    first_after_close: dict[str, datetime | None] = {channel: None for channel in REQUIRED_CHANNELS}
    first_complete: dict[str, datetime | None] = {"depth20": None, "depth200": None}
    last_complete: dict[str, datetime | None] = {"depth20": None, "depth200": None}
    first_complete_after_close: dict[str, datetime | None] = {
        "depth20": None,
        "depth200": None,
    }
    counts = {channel: 0 for channel in REQUIRED_CHANNELS}
    complete_counts = {"depth20": 0, "depth200": 0}
    run_ids: set[str] = set()
    instrument_ids: set[str] = set()
    observed_dates: set[date] = set()

    for loaded in rows:
        stamp = parse_receive_ts(loaded.get("receive_ts"))
        if stamp is None:
            continue
        observed_dates.add(stamp.date())
        run_ids.add(str(loaded.get("run_id") or ""))
        instrument_ids.add(str(loaded.get("instrument_id") or ""))
        event_type = loaded.get("event_type")
        channel = "standard" if event_type == "full" else event_type
        if channel not in counts:
            continue
        counts[channel] += 1
        if first[channel] is None:
            first[channel] = stamp
        last[channel] = stamp
        if stamp >= closed and first_after_close[channel] is None:
            first_after_close[channel] = stamp
        if channel in complete_counts and loaded.get("bids") and loaded.get("asks"):
            complete_counts[channel] += 1
            if first_complete[channel] is None:
                first_complete[channel] = stamp
            last_complete[channel] = stamp
            if stamp >= closed and first_complete_after_close[channel] is None:
                first_complete_after_close[channel] = stamp

    expected_run = str(metrics.get("run_id") or "")
    expected_instrument = str(metrics.get("instrument_id") or "")
    if run_ids != {expected_run}:
        reasons.append("logical dataset contains mixed or unexpected run identities")
    if instrument_ids != {expected_instrument}:
        reasons.append("logical dataset contains mixed or unexpected instrument identities")
    if observed_dates != {TRADING_DATE}:
        reasons.append("logical dataset crosses or misses the registered trading date")
    open_limit = opened + OPENING_PUBLICATION_TOLERANCE
    close_floor = closed - CLOSING_PUBLICATION_TOLERANCE
    inspection_time = (inspected_at or datetime.now(IST)).astimezone(IST)
    if inspection_time < closed:
        reasons.append("coverage was inspected before the registered close")
    for channel in REQUIRED_CHANNELS:
        if counts[channel] == 0:
            reasons.append(f"required channel {channel} has zero retained rows")
            continue
        channel_first = first[channel]
        channel_last = last[channel]
        if channel_first is None or channel_first > open_limit:
            reasons.append(f"required channel {channel} misses the opening coverage bound")
        if channel_last is None or channel_last < close_floor:
            reasons.append(f"required channel {channel} misses the closing coverage bound")
    for channel in ("depth20", "depth200"):
        channel_first_complete = first_complete[channel]
        channel_last_complete = last_complete[channel]
        if complete_counts[channel] == 0:
            reasons.append(f"required channel {channel} has no complete book")
        elif channel_first_complete is None or channel_first_complete > open_limit:
            reasons.append(f"required channel {channel} has no complete opening book")
        elif channel_last_complete is None or channel_last_complete < close_floor:
            reasons.append(f"required channel {channel} has no complete closing book")

    def encoded(values: Mapping[str, datetime | None]) -> dict[str, str | None]:
        return {
            key: value.isoformat() if value is not None else None for key, value in values.items()
        }

    receipt = {
        "schema_version": "1.1.0",
        "protocol_id": PROTOCOL_ID,
        "registration_commit": REGISTRATION_COMMIT,
        "migration_document": MIGRATION_DOCUMENT,
        "ccz": ccz_metadata(),
        "sample_role": "prospective_full_session_replication",
        "confirmatory_eligible": False,
        "sig21_calibration_eligible": False,
        "data_digest": data_digest,
        "catalog_digest": catalog_digest,
        "run_id": expected_run,
        "instrument_id": expected_instrument,
        "session": {"open": opened.isoformat(), "close": closed.isoformat()},
        "inspected_at": inspection_time.isoformat(),
        "controller_observed_through_close": inspection_time >= closed,
        "channel_rows": counts,
        "complete_book_rows": complete_counts,
        "first_receive_ts": encoded(first),
        "last_receive_ts": encoded(last),
        "first_after_close_ts": encoded(first_after_close),
        "first_complete_book_ts": encoded(first_complete),
        "last_complete_book_ts": encoded(last_complete),
        "first_complete_after_close_ts": encoded(first_complete_after_close),
        "accepted": not reasons,
        "reasons": reasons,
    }
    receipt.update(dict(source or {}))
    return receipt


def require_accepted_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("accepted") is not True:
        raise ValueError(
            f"full-session replication capture is ineligible: {receipt.get('reasons')}"
        )
