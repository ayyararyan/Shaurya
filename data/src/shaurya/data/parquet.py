"""Version-2 typed, segmented Parquet persistence for canonical market events."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq

from shaurya.contracts.artifacts import sha256_file
from shaurya.contracts.data import DataChannel, DatasetSegment
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST

from .tape import TapeIntegrityError, data_channel_for_row

ROW_SCHEMA_VERSION = "2.0.0"
STORAGE_FORMAT_VERSION = "2.0.0"
PRICE_TYPE = pa.decimal128(38, 12)
UTC_TIMESTAMP = pa.timestamp("ns", tz="UTC")
DEPTH_LEVEL_TYPE = pa.struct(
    [
        pa.field("price", PRICE_TYPE, nullable=False),
        pa.field("quantity", pa.int64(), nullable=False),
        pa.field("orders", pa.int32(), nullable=False),
    ]
)

MARKET_EVENT_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("receive_sequence", pa.int64(), nullable=False),
        pa.field("source_sequence", pa.int64()),
        pa.field("connection_epoch", pa.int32(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("broker_security_id", pa.string(), nullable=False),
        pa.field("exchange_segment", pa.string(), nullable=False),
        pa.field("exchange_ts", UTC_TIMESTAMP),
        pa.field("receive_ts", UTC_TIMESTAMP, nullable=False),
        pa.field("raw_message_size_bytes", pa.int64(), nullable=False),
        pa.field("connection_id", pa.string(), nullable=False),
        pa.field("update_side", pa.string()),
        pa.field("last_price", PRICE_TYPE),
        pa.field("last_quantity", pa.int64()),
        pa.field("cumulative_volume", pa.int64()),
        pa.field("cumulative_volume_increment", pa.int64()),
        pa.field("open_interest", pa.int64()),
        pa.field("trade_quote_bid", PRICE_TYPE),
        pa.field("trade_quote_ask", PRICE_TYPE),
        pa.field("trade_quote_channel", pa.string()),
        pa.field("trade_quote_bid_receive_ts", UTC_TIMESTAMP),
        pa.field("trade_quote_ask_receive_ts", UTC_TIMESTAMP),
        pa.field("trade_quote_receive_ts", UTC_TIMESTAMP),
        pa.field("trade_quote_age_ms", pa.float64()),
        pa.field("trade_quote_freshness_bound_ms", pa.float64()),
        pa.field("trade_side", pa.string()),
        pa.field("trade_classifier_version", pa.string()),
        pa.field("trade_alignment_version", pa.string()),
        pa.field("trade_classification_degraded", pa.bool_()),
        pa.field("trade_classification_reason", pa.string()),
        pa.field("trade_coalesced", pa.bool_()),
        pa.field("bids", pa.list_(DEPTH_LEVEL_TYPE), nullable=False),
        pa.field("asks", pa.list_(DEPTH_LEVEL_TYPE), nullable=False),
        pa.field("quality_flags", pa.list_(pa.string()), nullable=False),
    ],
    metadata={
        b"shaurya.row_schema": b"market-event",
        b"shaurya.row_schema_version": ROW_SCHEMA_VERSION.encode(),
        b"shaurya.storage_format_version": STORAGE_FORMAT_VERSION.encode(),
        b"shaurya.ordering": b"strictly-increasing-receive-sequence",
        b"shaurya.timestamp_semantics": b"timezone-aware-instants-normalized-to-UTC",
        b"shaurya.price_units": b"native-quote-currency-decimal-12",
    },
)


_PRICE_QUANTUM = Decimal(1).scaleb(-PRICE_TYPE.scale)


def _decimal(value: float | None) -> Decimal | None:
    """Convert a feed price to the schema's fixed ``decimal128(38, 12)`` scale.

    Dhan's wire format carries prices as IEEE-754 single precision (float32).
    Widened to Python's float64, the exact binary value can need more than 12
    fractional digits to state precisely (e.g. ``71.55`` arrives as
    ``71.55000305175781``) even though the schema's own metadata declares
    ``shaurya.price_units: native-quote-currency-decimal-12``. Quantizing here
    conforms every price to that declared contract instead of failing PyArrow's
    Parquet rescale at segment-finalize time, potentially discarding an entire
    in-memory segment of already-captured rows.
    """

    return Decimal(str(value)).quantize(_PRICE_QUANTUM) if value is not None else None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Parquet timestamps must be timezone-aware")
    return value.astimezone(UTC)


def row_to_arrow(row: TapeRow) -> dict[str, Any]:
    """Map every logical TapeRow field to the exact version-2 Arrow schema."""

    return {
        "run_id": row.run_id,
        "receive_sequence": row.receive_sequence,
        "source_sequence": row.source_sequence,
        "connection_epoch": row.connection_epoch,
        "source": row.source,
        "event_type": row.event_type,
        "instrument_id": row.instrument_id,
        "broker_security_id": row.broker_security_id,
        "exchange_segment": row.exchange_segment,
        "exchange_ts": _utc(row.exchange_ts),
        "receive_ts": _utc(row.receive_ts),
        "raw_message_size_bytes": row.raw_message_size_bytes,
        "connection_id": row.connection_id,
        "update_side": row.update_side,
        "last_price": _decimal(row.last_price),
        "last_quantity": row.last_quantity,
        "cumulative_volume": row.cumulative_volume,
        "cumulative_volume_increment": row.cumulative_volume_increment,
        "open_interest": row.open_interest,
        "trade_quote_bid": _decimal(row.trade_quote_bid),
        "trade_quote_ask": _decimal(row.trade_quote_ask),
        "trade_quote_channel": row.trade_quote_channel,
        "trade_quote_bid_receive_ts": _utc(row.trade_quote_bid_receive_ts),
        "trade_quote_ask_receive_ts": _utc(row.trade_quote_ask_receive_ts),
        "trade_quote_receive_ts": _utc(row.trade_quote_receive_ts),
        "trade_quote_age_ms": row.trade_quote_age_ms,
        "trade_quote_freshness_bound_ms": row.trade_quote_freshness_bound_ms,
        "trade_side": str(row.trade_side) if row.trade_side is not None else None,
        "trade_classifier_version": row.trade_classifier_version,
        "trade_alignment_version": row.trade_alignment_version,
        "trade_classification_degraded": row.trade_classification_degraded,
        "trade_classification_reason": row.trade_classification_reason,
        "trade_coalesced": row.trade_coalesced,
        "bids": [
            {"price": _decimal(level.price), "quantity": level.quantity, "orders": level.orders}
            for level in row.bids
        ],
        "asks": [
            {"price": _decimal(level.price), "quantity": level.quantity, "orders": level.orders}
            for level in row.asks
        ],
        "quality_flags": [str(flag) for flag in row.quality_flags],
    }


def arrow_to_row(value: dict[str, Any]) -> TapeRow:
    """Restore a logical TapeRow without exposing Arrow types to consumers."""

    payload = dict(value)
    payload["schema_version"] = TapeRow.SCHEMA_VERSION
    for name in (
        "exchange_ts",
        "receive_ts",
        "trade_quote_bid_receive_ts",
        "trade_quote_ask_receive_ts",
        "trade_quote_receive_ts",
    ):
        stamp = payload.get(name)
        payload[name] = stamp.isoformat() if isinstance(stamp, datetime) else None
    for name in ("last_price", "trade_quote_bid", "trade_quote_ask"):
        decimal_value = payload.get(name)
        payload[name] = str(decimal_value) if isinstance(decimal_value, Decimal) else decimal_value
    for side in ("bids", "asks"):
        payload[side] = [
            {
                "price": str(level["price"]),
                "quantity": level["quantity"],
                "orders": level["orders"],
            }
            for level in payload.get(side, [])
        ]
    return TapeRow.from_dict(payload)


def _schema_from_file(path: Path) -> pa.Schema:
    try:
        return pq.ParquetFile(path).schema_arrow
    except (OSError, pa.ArrowException) as exc:
        raise TapeIntegrityError(f"unreadable Parquet footer: {path.name}") from exc


def validate_parquet_schema(path: Path) -> pq.FileMetaData:
    schema = _schema_from_file(path)
    metadata = schema.metadata or {}
    raw_version = metadata.get(b"shaurya.row_schema_version", b"").decode()
    if not raw_version.startswith("2."):
        raise TapeIntegrityError("unsupported Parquet market-event schema version")
    for field in MARKET_EVENT_SCHEMA:
        try:
            observed = schema.field(field.name)
        except KeyError as exc:
            raise TapeIntegrityError(
                f"Parquet market-event schema lacks field {field.name}"
            ) from exc
        if not observed.equals(field, check_metadata=False):
            raise TapeIntegrityError(f"Parquet market-event field is incompatible: {field.name}")
    canonical_names = set(MARKET_EVENT_SCHEMA.names)
    if any(not field.nullable for field in schema if field.name not in canonical_names):
        raise TapeIntegrityError("additive Parquet market-event fields must be nullable")
    return pq.ParquetFile(path).metadata


def _filter_expression(
    *,
    start: datetime | None,
    end: datetime | None,
    channels: tuple[DataChannel, ...] | None,
    instrument_ids: tuple[str, ...] | None,
) -> pads.Expression | None:
    expression: pads.Expression | None = None

    def combine(term: pads.Expression) -> None:
        nonlocal expression
        expression = term if expression is None else expression & term

    if start is not None:
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        combine(pads.field("receive_ts") >= pa.scalar(start.astimezone(UTC), type=UTC_TIMESTAMP))
    if end is not None:
        if end.tzinfo is None:
            raise ValueError("end must be timezone-aware")
        combine(pads.field("receive_ts") <= pa.scalar(end.astimezone(UTC), type=UTC_TIMESTAMP))
    if channels:
        event_types: set[str] = set()
        if DataChannel.STANDARD in channels:
            event_types.update(("quote", "full"))
        if DataChannel.DEPTH20 in channels:
            event_types.add("depth20")
        if DataChannel.DEPTH200 in channels:
            event_types.add("depth200")
        if DataChannel.HISTORICAL in channels:
            event_types.add("historical")
        combine(pads.field("event_type").isin(sorted(event_types)))
    if instrument_ids:
        combine(pads.field("instrument_id").isin(instrument_ids))
    return expression


def iter_parquet_rows(
    path: Path,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    channels: tuple[DataChannel, ...] | None = None,
    instrument_ids: tuple[str, ...] | None = None,
    batch_size: int = 8_192,
) -> Iterator[TapeRow]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    validate_parquet_schema(path)
    dataset = pads.dataset(path, format="parquet", schema=MARKET_EVENT_SCHEMA)
    scanner = dataset.scanner(
        filter=_filter_expression(
            start=start,
            end=end,
            channels=channels,
            instrument_ids=instrument_ids,
        ),
        batch_size=batch_size,
        use_threads=True,
    )
    for batch in scanner.to_batches():
        for value in batch.to_pylist():
            yield arrow_to_row(value)


def _safe_component(value: str, *, max_length: int = 64) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (cleaned or "dataset")[:max_length].rstrip("-")


def resolve_shared_underlying(instrument_ids: tuple[str, ...]) -> str | None:
    """Return the underlying symbol (e.g. ``NIFTY``) shared by every ID, or ``None``.

    Canonical instrument IDs are ``exchange:segment:underlying:...``; a multi-instrument
    capture (an option chain, say) has one underlying per instrument at index 2. When
    every instrument agrees, callers use this to name the capture after that underlying
    instead of the generic exchange segment — without it, a NIFTY chain and a BANKNIFTY
    chain are indistinguishable in both the scope directory and the dataset name.
    """

    underlyings = {item.split(":")[2] for item in instrument_ids if item.count(":") >= 2}
    return next(iter(underlyings)) if len(underlyings) == 1 else None


def scope_key_for_instruments(instrument_ids: tuple[str, ...]) -> str:
    """Human scope label for a set of canonical instrument IDs, underlying-aware."""

    if len(instrument_ids) == 1:
        parts = instrument_ids[0].split(":")
        raw = "-".join(parts[1:4]) if len(parts) >= 4 else instrument_ids[0]
    else:
        segments = {item.split(":")[1] for item in instrument_ids if ":" in item}
        segment = next(iter(segments)) if len(segments) == 1 else "multi-market"
        underlying = resolve_shared_underlying(instrument_ids)
        raw = f"{segment}-{underlying}" if underlying else f"{segment}-universe"
    return _safe_component(raw)


def human_dataset_name(
    *,
    trading_date: datetime,
    channels: tuple[DataChannel, ...],
    instrument_ids: tuple[str, ...],
    suffix: str | None = None,
    attempt: int = 1,
) -> str:
    """Build the leaf directory name for one capture run:
    ``{scope}-{channel}-[retry{N}-]{HH-MM-SS}-{suffix}``.

    Deliberately omits two components that were previously included but are
    always redundant with this name's own placement on disk: a ``dhan-``
    producer prefix (the literal parent directory is already ``dhan/``) and the
    full ``YYYYMMDD`` date (production captures already land under a
    date-partitioned ``YYYY-MM-DD/`` root; a controlled test run's own
    ``--output-root`` is the caller's responsibility to date if that matters).
    ``HH-MM-SS`` is the capture's IST start time (kept for same-day intra-scope
    ordering; NSE trading hours are conventionally read in IST, not UTC) and
    the ``suffix`` (the dataset id's own trailing hex) is for uniqueness.
    ``attempt`` numbers repeated starts of the same logical capture (same
    trading date, channels and scope) so a crash-and-retry sequence reads as
    ``retry2``, ``retry3``, ... instead of unrelated-looking sibling folders;
    the first attempt omits the marker.
    """

    if len(instrument_ids) == 1:
        parts = instrument_ids[0].split(":")
        scope = "-".join(parts[2:4]) if len(parts) >= 4 else instrument_ids[0]
    else:
        segments = {item.split(":")[1] for item in instrument_ids if ":" in item}
        segment = next(iter(segments)) if len(segments) == 1 else "multi-market"
        underlying = resolve_shared_underlying(instrument_ids)
        scope_prefix = f"{segment}-{underlying}" if underlying else segment
        scope = f"{scope_prefix}-{len(instrument_ids)}-instruments"
    channel_part = "-".join(str(channel) for channel in channels)
    base = f"{_safe_component(scope)}-{_safe_component(channel_part)}"
    if attempt > 1:
        base += f"-retry{attempt}"
    base += f"-{trading_date.astimezone(IST).strftime('%H-%M-%S')}"
    return f"{base}-{_safe_component(suffix, max_length=20)}" if suffix else base


def new_dataset_id() -> str:
    return f"ds-{uuid.uuid4().hex}"


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        # Some SMB implementations do not expose directory fsync. File fsync plus same-directory
        # atomic rename remains required; the limitation is visible in the ADR.
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def dataset_digest(segments: Iterable[DatasetSegment]) -> str:
    payload = [segment.model_dump(mode="json") for segment in segments]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_row_digest(rows: Iterable[TapeRow]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        encoded = json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return digest.hexdigest(), count


@dataclass(frozen=True, slots=True)
class RecoveryInventory:
    partial_files: tuple[Path, ...]
    orphan_files: tuple[Path, ...]
    quarantined_files: tuple[Path, ...]


def inventory_recovery(
    dataset_dir: Path,
    published_segments: Iterable[DatasetSegment],
    *,
    quarantine_partials: bool = False,
) -> RecoveryInventory:
    published = {Path(segment.path).resolve() for segment in published_segments}
    partials = tuple(sorted(dataset_dir.glob("*.partial*"))) if dataset_dir.exists() else ()
    finals = tuple(sorted(dataset_dir.glob("*.parquet"))) if dataset_dir.exists() else ()
    orphans = tuple(path for path in finals if path.resolve() not in published)
    quarantined: list[Path] = []
    if quarantine_partials and partials:
        quarantine = dataset_dir / "quarantine"
        quarantine.mkdir(mode=0o700, exist_ok=True)
        for path in partials:
            target = quarantine / f"{path.name}.quarantined"
            os.rename(path, target)
            quarantined.append(target)
        _fsync_directory(quarantine)
        _fsync_directory(dataset_dir)
    return RecoveryInventory(partials, orphans, tuple(quarantined))


class SegmentedParquetWriter:
    """Bounded writer that publishes only closed, validated immutable segments."""

    def __init__(
        self,
        dataset_dir: Path,
        *,
        dataset_id: str,
        expected_run_id: str | None = None,
        max_rows: int = 50_000,
        max_duration: timedelta = timedelta(seconds=30),
        max_estimated_bytes: int = 64 * 1024 * 1024,
        row_group_size: int = 10_000,
        existing_segments: Iterable[DatasetSegment] = (),
        resume_directory: bool = False,
    ) -> None:
        if max_rows < 1 or max_duration <= timedelta(0) or max_estimated_bytes < 1:
            raise ValueError("segment rotation bounds must be positive")
        if row_group_size < 1:
            raise ValueError("row_group_size must be positive")
        self.dataset_dir = dataset_dir.resolve()
        self.dataset_id = dataset_id
        self.expected_run_id = expected_run_id or dataset_id
        self.max_rows = max_rows
        self.max_duration = max_duration
        self.max_estimated_bytes = max_estimated_bytes
        self.row_group_size = row_group_size
        resumed = tuple(existing_segments)
        self.rows_written = sum(segment.rows for segment in resumed)
        self.bytes_written = sum(segment.bytes for segment in resumed)
        self._rows: list[TapeRow] = []
        self._estimated_bytes = 0
        self._segments: list[DatasetSegment] = list(resumed)
        self._pending_publications: list[DatasetSegment] = []
        self._prior_sequence: int | None = resumed[-1].last_receive_sequence if resumed else None
        self._closed = False
        self.dataset_dir.mkdir(
            mode=0o700,
            parents=True,
            exist_ok=bool(resumed) or resume_directory,
        )
        for expected_number, segment in enumerate(resumed, start=1):
            if segment.segment_number != expected_number:
                raise TapeIntegrityError("resumed segment numbers are not contiguous")
            if Path(segment.path).resolve().parent != self.dataset_dir:
                raise TapeIntegrityError("resumed segment belongs to a different dataset directory")
            if expected_number > 1:
                prior = resumed[expected_number - 2]
                if segment.first_receive_sequence != prior.last_receive_sequence + 1:
                    raise TapeIntegrityError("resumed segment receive sequences are not contiguous")
            validate_segment(segment)
            if any(
                row.run_id != self.expected_run_id for row in iter_parquet_rows(Path(segment.path))
            ):
                raise TapeIntegrityError("resumed segment logical run ID is inconsistent")
        expected_files = {Path(segment.path).resolve() for segment in resumed}
        observed_files = {path.resolve() for path in self.dataset_dir.glob("*.parquet")}
        if observed_files != expected_files:
            raise TapeIntegrityError("dataset directory contains unacknowledged final segments")
        _fsync_directory(self.dataset_dir.parent)

    @property
    def segments(self) -> tuple[DatasetSegment, ...]:
        return tuple(self._segments)

    def drain_published(self) -> tuple[DatasetSegment, ...]:
        published = tuple(self._pending_publications)
        self._pending_publications.clear()
        return published

    def write(self, row: TapeRow) -> None:
        if self._closed:
            raise ValueError("cannot write to a closed segmented dataset")
        if row.run_id != self.expected_run_id:
            raise ValueError("row run_id does not match the dataset's logical run ID")
        if self._prior_sequence is not None and row.receive_sequence != self._prior_sequence + 1:
            raise TapeIntegrityError("receive sequence must remain contiguous across segments")
        self._prior_sequence = row.receive_sequence
        if self._rows and row.receive_ts - self._rows[0].receive_ts >= self.max_duration:
            self._finalize_segment()
        self._rows.append(row)
        self.rows_written += 1
        self._estimated_bytes += len(
            json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        )
        if self._rotation_due():
            self._finalize_segment()

    def _rotation_due(self) -> bool:
        return len(self._rows) >= self.max_rows or self._estimated_bytes >= self.max_estimated_bytes

    @staticmethod
    def _time_name(stamp: datetime) -> str:
        return stamp.astimezone(UTC).strftime("%H%M%S%fZ")

    def _finalize_segment(self) -> DatasetSegment | None:
        if not self._rows:
            return None
        number = len(self._segments) + 1
        start = min(row.receive_ts for row in self._rows)
        end = max(row.receive_ts for row in self._rows)
        filename = (
            f"market-events-{number:06d}-{self._time_name(start)}-{self._time_name(end)}.parquet"
        )
        final_path = self.dataset_dir / filename
        partial_path = self.dataset_dir / f"{filename}.partial-{uuid.uuid4().hex}"
        table = pa.Table.from_pylist([row_to_arrow(row) for row in self._rows], MARKET_EVENT_SCHEMA)
        try:
            pq.write_table(
                table,
                partial_path,
                compression="zstd",
                use_dictionary=True,
                write_statistics=True,
                row_group_size=min(self.row_group_size, len(self._rows)),
                version="2.6",
            )
            metadata = validate_parquet_schema(partial_path)
            if metadata.num_rows != len(self._rows):
                raise TapeIntegrityError("Parquet footer row count differs before publication")
            with partial_path.open("rb") as source:
                os.fsync(source.fileno())
            os.chmod(partial_path, 0o600)
            os.rename(partial_path, final_path)
            _fsync_directory(self.dataset_dir)
        except BaseException:
            # Preserve the partial file as crash/failure evidence when it exists.
            raise
        channels = tuple(sorted({data_channel_for_row(row) for row in self._rows}, key=str))
        instruments = tuple(sorted({row.instrument_id for row in self._rows}))
        segment = DatasetSegment(
            segment_number=number,
            path=str(final_path),
            rows=len(self._rows),
            bytes=final_path.stat().st_size,
            sha256=sha256_file(final_path),
            first_receive_sequence=self._rows[0].receive_sequence,
            last_receive_sequence=self._rows[-1].receive_sequence,
            coverage_start=start,
            coverage_end=end,
            channels=channels,
            instrument_ids=instruments,
            row_groups=metadata.num_row_groups,
        )
        self._segments.append(segment)
        self._pending_publications.append(segment)
        self.bytes_written += segment.bytes
        self._rows = []
        self._estimated_bytes = 0
        return segment

    def close(self) -> tuple[DatasetSegment, ...]:
        if not self._closed:
            self._finalize_segment()
            self._closed = True
        return self.segments


def validate_segment(segment: DatasetSegment) -> None:
    path = Path(segment.path)
    if not path.is_file() or ".partial" in path.name:
        raise TapeIntegrityError(f"published segment is missing or partial: {path.name}")
    if path.stat().st_size != segment.bytes or sha256_file(path) != segment.sha256:
        raise TapeIntegrityError(f"published segment hash or byte count differs: {path.name}")
    metadata = validate_parquet_schema(path)
    if metadata.num_rows != segment.rows or metadata.num_row_groups != segment.row_groups:
        raise TapeIntegrityError(f"published segment footer counts differ: {path.name}")
    rows = tuple(iter_parquet_rows(path))
    if not rows:
        raise TapeIntegrityError(f"published segment is empty: {path.name}")
    for prior, current in zip(rows, rows[1:], strict=False):
        if current.receive_sequence != prior.receive_sequence + 1:
            raise TapeIntegrityError(f"published segment sequence is not contiguous: {path.name}")
    declared = (
        segment.first_receive_sequence,
        segment.last_receive_sequence,
        segment.coverage_start,
        segment.coverage_end,
        segment.channels,
        segment.instrument_ids,
    )
    observed = (
        rows[0].receive_sequence,
        rows[-1].receive_sequence,
        min(row.receive_ts for row in rows),
        max(row.receive_ts for row in rows),
        tuple(sorted({data_channel_for_row(row) for row in rows}, key=str)),
        tuple(sorted({row.instrument_id for row in rows})),
    )
    if observed != declared:
        raise TapeIntegrityError(f"published segment summary differs: {path.name}")


def describe_segment(path: Path, *, segment_number: int) -> DatasetSegment:
    """Reconstruct verified metadata for a final-but-unpublished recovery segment."""

    if segment_number < 1 or not path.is_file() or ".partial" in path.name:
        raise TapeIntegrityError("recovery segment must be a numbered final Parquet file")
    metadata = validate_parquet_schema(path)
    rows = tuple(iter_parquet_rows(path))
    if not rows or metadata.num_rows != len(rows):
        raise TapeIntegrityError("recovery segment row count differs from its footer")
    for prior, current in zip(rows, rows[1:], strict=False):
        if current.receive_sequence != prior.receive_sequence + 1:
            raise TapeIntegrityError("recovery segment receive sequence is not contiguous")
    return DatasetSegment(
        segment_number=segment_number,
        path=str(path.resolve()),
        rows=len(rows),
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        first_receive_sequence=rows[0].receive_sequence,
        last_receive_sequence=rows[-1].receive_sequence,
        coverage_start=min(row.receive_ts for row in rows),
        coverage_end=max(row.receive_ts for row in rows),
        channels=tuple(sorted({data_channel_for_row(row) for row in rows}, key=str)),
        instrument_ids=tuple(sorted({row.instrument_id for row in rows})),
        row_groups=metadata.num_row_groups,
    )


def segments_overlap_filter(
    segment: DatasetSegment,
    *,
    start: datetime | None,
    end: datetime | None,
    channels: tuple[DataChannel, ...] | None,
    instrument_ids: tuple[str, ...] | None,
) -> bool:
    if start is not None and segment.coverage_end < start:
        return False
    if end is not None and segment.coverage_start > end:
        return False
    if channels and not set(segment.channels).intersection(channels):
        return False
    return not (instrument_ids and not set(segment.instrument_ids).intersection(instrument_ids))
