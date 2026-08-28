"""Immutable Parquet lifecycle catalogue with read-only JSONL compatibility."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetRequest,
    DatasetSegment,
    DatasetStatus,
    OperationalArtifact,
    StorageFormat,
)

CATALOG_SCHEMA_VERSION = "2.0.0"
_UTC_TIMESTAMP = pa.timestamp("ns", tz="UTC")
_SEGMENT_TYPE = pa.struct(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("segment_number", pa.int32(), nullable=False),
        pa.field("path", pa.string(), nullable=False),
        pa.field("rows", pa.int64(), nullable=False),
        pa.field("bytes", pa.int64(), nullable=False),
        pa.field("sha256", pa.string(), nullable=False),
        pa.field("first_receive_sequence", pa.int64(), nullable=False),
        pa.field("last_receive_sequence", pa.int64(), nullable=False),
        pa.field("coverage_start", _UTC_TIMESTAMP, nullable=False),
        pa.field("coverage_end", _UTC_TIMESTAMP, nullable=False),
        pa.field("channels", pa.list_(pa.string()), nullable=False),
        pa.field("instrument_ids", pa.list_(pa.string()), nullable=False),
        pa.field("row_groups", pa.int32(), nullable=False),
        pa.field("storage_format_version", pa.string(), nullable=False),
        pa.field("row_schema_version", pa.string(), nullable=False),
    ]
)
_OPERATIONAL_ARTIFACT_TYPE = pa.struct(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
        pa.field("path", pa.string(), nullable=False),
        pa.field("bytes", pa.int64(), nullable=False),
        pa.field("sha256", pa.string(), nullable=False),
    ]
)

CATALOG_EVENT_SCHEMA = pa.schema(
    [
        pa.field("catalog_schema_version", pa.string(), nullable=False),
        pa.field("event_sequence", pa.int64(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("recorded_at", _UTC_TIMESTAMP, nullable=False),
        pa.field("prior_event_digest", pa.string()),
        pa.field("event_digest", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("handle_schema_version", pa.string(), nullable=False),
        pa.field("acquisition_fingerprint", pa.string(), nullable=False),
        pa.field("producer", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("producer_pid", pa.int64()),
        pa.field("producer_host", pa.string()),
        pa.field("trading_date", pa.date32(), nullable=False),
        pa.field("channels", pa.list_(pa.string()), nullable=False),
        pa.field("instrument_ids", pa.list_(pa.string()), nullable=False),
        pa.field("storage_format", pa.string()),
        pa.field("storage_format_version", pa.string()),
        pa.field("row_schema_version", pa.string()),
        pa.field("dataset_name", pa.string()),
        pa.field("row_run_id", pa.string()),
        pa.field("dataset_path", pa.string()),
        pa.field("segments", pa.list_(_SEGMENT_TYPE), nullable=False),
        pa.field("operational_artifacts", pa.list_(_OPERATIONAL_ARTIFACT_TYPE), nullable=False),
        pa.field("dataset_digest", pa.string()),
        pa.field("tape_path", pa.string()),
        pa.field("manifest_path", pa.string()),
        pa.field("index_path", pa.string()),
        pa.field("archive_path", pa.string()),
        pa.field("started_at", _UTC_TIMESTAMP, nullable=False),
        pa.field("completed_at", _UTC_TIMESTAMP),
        pa.field("requested_coverage_start", _UTC_TIMESTAMP),
        pa.field("requested_coverage_end", _UTC_TIMESTAMP),
        pa.field("coverage_start", _UTC_TIMESTAMP),
        pa.field("coverage_end", _UTC_TIMESTAMP),
        pa.field("rows", pa.int64(), nullable=False),
        pa.field("bytes", pa.int64(), nullable=False),
        pa.field("tape_sha256", pa.string()),
        pa.field("index_sha256", pa.string()),
        pa.field("archive_sha256", pa.string()),
        pa.field("invalidation_reason", pa.string()),
        pa.field("legacy_source_sha256", pa.string()),
        pa.field("canonical_row_digest", pa.string()),
    ],
    metadata={
        b"shaurya.catalog_schema_version": CATALOG_SCHEMA_VERSION.encode(),
        b"shaurya.persistence": b"immutable-parquet-event-fragment",
    },
)


class DatasetUnavailableError(LookupError):
    """DAT has no active/completed dataset satisfying a consumer request."""


class DatasetAlreadyActiveError(RuntimeError):
    """A compatible DAT acquisition already owns the broker work."""

    def __init__(self, handle: DatasetHandle) -> None:
        super().__init__(f"compatible DAT dataset is already active: {handle.dataset_id}")
        self.handle = handle


def _active_process_is_live(handle: DatasetHandle) -> bool:
    if handle.status is not DatasetStatus.ACTIVE or handle.producer_pid is None:
        return True
    if handle.producer_host is not None and handle.producer_host != socket.gethostname():
        return True
    try:
        os.kill(handle.producer_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC)


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _segment_record(segment: DatasetSegment) -> dict[str, Any]:
    return {
        "schema_version": segment.schema_version,
        "segment_number": segment.segment_number,
        "path": segment.path,
        "rows": segment.rows,
        "bytes": segment.bytes,
        "sha256": segment.sha256,
        "first_receive_sequence": segment.first_receive_sequence,
        "last_receive_sequence": segment.last_receive_sequence,
        "coverage_start": _utc(segment.coverage_start),
        "coverage_end": _utc(segment.coverage_end),
        "channels": [str(item) for item in segment.channels],
        "instrument_ids": list(segment.instrument_ids),
        "row_groups": segment.row_groups,
        "storage_format_version": segment.storage_format_version,
        "row_schema_version": segment.row_schema_version,
    }


def _event_payload(
    handle: DatasetHandle,
    *,
    event_sequence: int,
    event_type: str,
    recorded_at: datetime,
    prior_event_digest: str | None,
) -> dict[str, Any]:
    return {
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "event_sequence": event_sequence,
        "event_type": event_type,
        "recorded_at": _utc(recorded_at),
        "prior_event_digest": prior_event_digest,
        "dataset_id": handle.dataset_id,
        "handle_schema_version": handle.schema_version,
        "acquisition_fingerprint": handle.acquisition_fingerprint,
        "producer": handle.producer,
        "source": handle.source,
        "status": str(handle.status),
        "producer_pid": handle.producer_pid,
        "producer_host": handle.producer_host,
        "trading_date": handle.trading_date,
        "channels": [str(item) for item in handle.channels],
        "instrument_ids": list(handle.instrument_ids),
        "storage_format": str(handle.storage_format) if handle.storage_format else None,
        "storage_format_version": handle.storage_format_version,
        "row_schema_version": handle.row_schema_version,
        "dataset_name": handle.dataset_name,
        "row_run_id": handle.row_run_id,
        "dataset_path": handle.dataset_path,
        "segments": [_segment_record(segment) for segment in handle.segments],
        "operational_artifacts": [
            artifact.model_dump(mode="json") for artifact in handle.operational_artifacts
        ],
        "dataset_digest": handle.dataset_digest,
        "tape_path": handle.tape_path,
        "manifest_path": handle.manifest_path,
        "index_path": handle.index_path,
        "archive_path": handle.archive_path,
        "started_at": _utc(handle.started_at),
        "completed_at": _utc(handle.completed_at),
        "requested_coverage_start": _utc(handle.requested_coverage_start),
        "requested_coverage_end": _utc(handle.requested_coverage_end),
        "coverage_start": _utc(handle.coverage_start),
        "coverage_end": _utc(handle.coverage_end),
        "rows": handle.rows,
        "bytes": handle.bytes,
        "tape_sha256": handle.tape_sha256,
        "index_sha256": handle.index_sha256,
        "archive_sha256": handle.archive_sha256,
        "invalidation_reason": handle.invalidation_reason,
        "legacy_source_sha256": handle.legacy_source_sha256,
        "canonical_row_digest": handle.canonical_row_digest,
    }


def _digest_payload(payload: dict[str, Any]) -> str:
    canonical = dict(payload)
    canonical.pop("event_digest", None)

    def default(value: object) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(type(value).__name__)

    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=default).encode()
    return hashlib.sha256(encoded).hexdigest()


def _record_handle(record: dict[str, Any]) -> DatasetHandle:
    raw_segments = record.get("segments") or []
    segments = tuple(
        DatasetSegment.model_validate(
            {
                "schema_version": item["schema_version"],
                "segment_number": item["segment_number"],
                "path": item["path"],
                "rows": item["rows"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "first_receive_sequence": item["first_receive_sequence"],
                "last_receive_sequence": item["last_receive_sequence"],
                "coverage_start": item["coverage_start"],
                "coverage_end": item["coverage_end"],
                "channels": tuple(DataChannel(value) for value in item["channels"]),
                "instrument_ids": tuple(str(value) for value in item["instrument_ids"]),
                "row_groups": item["row_groups"],
                "storage_format_version": item["storage_format_version"],
                "row_schema_version": item["row_schema_version"],
            }
        )
        for item in raw_segments
    )
    storage_value = record.get("storage_format")
    operational_artifacts = tuple(
        OperationalArtifact.model_validate(item)
        for item in (record.get("operational_artifacts") or [])
    )
    return DatasetHandle.model_validate(
        {
            "schema_version": record["handle_schema_version"],
            "dataset_id": record["dataset_id"],
            "acquisition_fingerprint": record["acquisition_fingerprint"],
            "producer": record["producer"],
            "source": record["source"],
            "status": DatasetStatus(str(record["status"])),
            "producer_pid": record.get("producer_pid"),
            "producer_host": record.get("producer_host"),
            "trading_date": record["trading_date"],
            "channels": tuple(DataChannel(value) for value in record["channels"]),
            "instrument_ids": tuple(str(value) for value in record["instrument_ids"]),
            "storage_format": StorageFormat(str(storage_value)) if storage_value else None,
            "storage_format_version": record.get("storage_format_version"),
            "row_schema_version": record.get("row_schema_version"),
            "dataset_name": record.get("dataset_name"),
            "row_run_id": record.get("row_run_id"),
            "dataset_path": record.get("dataset_path"),
            "segments": segments,
            "operational_artifacts": operational_artifacts,
            "dataset_digest": record.get("dataset_digest"),
            "tape_path": record.get("tape_path"),
            "manifest_path": record.get("manifest_path"),
            "index_path": record.get("index_path"),
            "archive_path": record.get("archive_path"),
            "started_at": record["started_at"],
            "completed_at": record.get("completed_at"),
            "requested_coverage_start": record.get("requested_coverage_start"),
            "requested_coverage_end": record.get("requested_coverage_end"),
            "coverage_start": record.get("coverage_start"),
            "coverage_end": record.get("coverage_end"),
            "rows": record["rows"],
            "bytes": record["bytes"],
            "tape_sha256": record.get("tape_sha256"),
            "index_sha256": record.get("index_sha256"),
            "archive_sha256": record.get("archive_sha256"),
            "invalidation_reason": record.get("invalidation_reason"),
            "legacy_source_sha256": record.get("legacy_source_sha256"),
            "canonical_row_digest": record.get("canonical_row_digest"),
        }
    )


def _legacy_iso_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("legacy datetime field must be an ISO-8601 string")


def _legacy_dataset_handle(payload: dict[str, Any]) -> DatasetHandle:
    """Coerce a pre-Parquet legacy JSONL handle into the strict ``DatasetHandle`` types.

    Legacy records were written with plain ``json.dumps`` before the segmented-Parquet
    catalogue existed, so dates/datetimes arrive as ISO strings and channels/instrument_ids
    as lists. The Parquet event path (``_read_event``/``_record_handle``) gets these already
    typed from pyarrow; this mirrors that coercion for the still-active legacy JSONL log so
    ``ContractModel``'s strict validation does not reject an otherwise-valid legacy record.
    """
    coerced = dict(payload)
    coerced["status"] = DatasetStatus(str(coerced["status"]))
    trading_date = coerced.get("trading_date")
    if isinstance(trading_date, str):
        coerced["trading_date"] = date.fromisoformat(trading_date)
    for field in (
        "started_at",
        "completed_at",
        "requested_coverage_start",
        "requested_coverage_end",
        "coverage_start",
        "coverage_end",
    ):
        coerced[field] = _legacy_iso_datetime(coerced.get(field))
    storage_format = coerced.get("storage_format")
    coerced["storage_format"] = StorageFormat(str(storage_format)) if storage_format else None
    coerced["channels"] = tuple(DataChannel(value) for value in coerced.get("channels") or [])
    coerced["instrument_ids"] = tuple(str(value) for value in coerced.get("instrument_ids") or [])
    coerced["segments"] = tuple(
        DatasetSegment.model_validate(item) for item in (coerced.get("segments") or [])
    )
    coerced["operational_artifacts"] = tuple(
        OperationalArtifact.model_validate(item)
        for item in (coerced.get("operational_artifacts") or [])
    )
    return DatasetHandle.model_validate(coerced)


def _read_event(path: Path) -> tuple[int, str, str | None, str, DatasetHandle]:
    try:
        table = pq.read_table(path, schema=CATALOG_EVENT_SCHEMA)
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"invalid data-catalogue event fragment: {path.name}") from exc
    if table.num_rows != 1 or not table.schema.equals(CATALOG_EVENT_SCHEMA, check_metadata=True):
        raise ValueError(f"invalid data-catalogue event shape: {path.name}")
    record = table.to_pylist()[0]
    if record.get("catalog_schema_version") != CATALOG_SCHEMA_VERSION:
        raise ValueError("unsupported data-catalogue schema")
    if record.get("event_digest") != _digest_payload(record):
        raise ValueError(f"data-catalogue event digest differs: {path.name}")
    return (
        int(record["event_sequence"]),
        str(record["event_type"]),
        str(record["prior_event_digest"]) if record.get("prior_event_digest") else None,
        str(record["event_digest"]),
        _record_handle(record),
    )


class DataCatalog:
    """Deterministic current state over immutable event fragments and legacy JSONL history."""

    LEGACY_SCHEMA_VERSION = "1.0.0"

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if self.path.suffix == ".jsonl":
            self.legacy_path = self.path
            self.root = self.path.with_suffix("")
        else:
            self.root = self.path
            self.legacy_path = self.path.with_suffix(".jsonl")

    @property
    def events_root(self) -> Path:
        return self.root / "events"

    @property
    def claim_root(self) -> Path:
        return self.root / "claims"

    @property
    def claim_lock_path(self) -> Path:
        # Compatibility property for callers that display the former lock path.
        return self.claim_root

    @contextmanager
    def acquisition_lock(self) -> Any:
        """Serialize compatibility checks and claims across all request fingerprints."""

        self.claim_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.claim_root / ".acquisition.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _dataset_lock(self, dataset_id: str) -> Any:
        lock_root = self.root / "locks"
        lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = lock_root / f"{dataset_id}.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _event_files(self, dataset_id: str | None = None) -> tuple[Path, ...]:
        root = self.events_root / dataset_id if dataset_id else self.events_root
        return tuple(sorted(root.rglob("*.parquet"))) if root.exists() else ()

    def _next_sequence(self, dataset_id: str) -> int:
        sequences = [_read_event(path)[0] for path in self._event_files(dataset_id)]
        if len(sequences) != len(set(sequences)):
            raise ValueError(f"duplicate data-catalogue event sequence for {dataset_id}")
        return max(sequences, default=0) + 1

    def _append(self, event_type: str, handle: DatasetHandle) -> None:
        with self._dataset_lock(handle.dataset_id):
            history = sorted(
                (_read_event(path) for path in self._event_files(handle.dataset_id)),
                key=lambda item: item[0],
            )
            sequence = len(history) + 1
            if history:
                if event_type == "dataset_registered":
                    raise ValueError(f"dataset already registered: {handle.dataset_id}")
                self._validate_transition(history[-1][4], handle, event_type)
            elif event_type != "dataset_registered":
                raise ValueError("first catalogue event must register the dataset")
            prior_digest = history[-1][3] if history else None
            recorded_at = datetime.now(UTC)
            payload = _event_payload(
                handle,
                event_sequence=sequence,
                event_type=event_type,
                recorded_at=recorded_at,
                prior_event_digest=prior_digest,
            )
            payload["event_digest"] = _digest_payload(payload)
            directory = self.events_root / handle.dataset_id
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            safe_event = event_type.replace("_", "-")
            target = directory / (
                f"{sequence:012d}-{safe_event}-{payload['event_digest'][:12]}.parquet"
            )
            partial = directory / f"{target.name}.partial-{uuid.uuid4().hex}"
            table = pa.Table.from_pylist([payload], CATALOG_EVENT_SCHEMA)
            pq.write_table(table, partial, compression="zstd", version="2.6")
            verified = _read_event(partial)
            if verified[:4] != (sequence, event_type, prior_digest, payload["event_digest"]) or (
                verified[4] != handle
            ):
                raise ValueError("catalogue event changed during Parquet round-trip")
            with partial.open("rb") as source:
                os.fsync(source.fileno())
            os.chmod(partial, 0o600)
            if target.exists():
                raise FileExistsError(target)
            os.rename(partial, target)
            _fsync_directory(directory)

    @staticmethod
    def _validate_transition(
        previous: DatasetHandle, current: DatasetHandle, event_type: str
    ) -> None:
        immutable = (
            "schema_version",
            "dataset_id",
            "acquisition_fingerprint",
            "producer",
            "source",
            "trading_date",
            "channels",
            "instrument_ids",
            "storage_format",
            "storage_format_version",
            "row_schema_version",
            "dataset_name",
            "row_run_id",
            "dataset_path",
            "started_at",
            "requested_coverage_start",
            "requested_coverage_end",
        )
        if any(getattr(previous, name) != getattr(current, name) for name in immutable):
            raise ValueError("catalogue transition changes immutable dataset identity")
        if previous.status is not DatasetStatus.ACTIVE and (
            event_type != "dataset_published" or current.status is not previous.status
        ):
            raise ValueError("terminal dataset status cannot be changed")
        if current.segments[: len(previous.segments)] != previous.segments:
            raise ValueError("catalogue transition rewrites or removes published segments")
        if current.rows < previous.rows or current.bytes < previous.bytes:
            raise ValueError("catalogue transition regresses published row or byte counts")
        if event_type == "segment_published" and current.status is not DatasetStatus.ACTIVE:
            raise ValueError("segment publication must retain ACTIVE status")
        if (
            previous.status is DatasetStatus.ACTIVE
            and event_type == "dataset_published"
            and current.status is DatasetStatus.ACTIVE
        ):
            raise ValueError("terminal publication cannot retain ACTIVE status")

    def register(self, handle: DatasetHandle) -> None:
        if handle.dataset_id in self.handles():
            raise ValueError(f"dataset already registered: {handle.dataset_id}")
        self._append("dataset_registered", handle)

    def publish_segment(self, handle: DatasetHandle) -> None:
        if handle.dataset_id not in self.handles():
            raise KeyError(f"dataset is not registered: {handle.dataset_id}")
        self._append("segment_published", handle)

    def publish(self, handle: DatasetHandle) -> None:
        if handle.dataset_id not in self.handles():
            raise KeyError(f"dataset is not registered: {handle.dataset_id}")
        self._append("dataset_published", handle)

    def _legacy_handles(self) -> dict[str, DatasetHandle]:
        if not self.legacy_path.is_file():
            return {}
        latest: dict[str, DatasetHandle] = {}
        with self.legacy_path.open(encoding="utf-8") as source:
            fcntl.flock(source.fileno(), fcntl.LOCK_SH)
            try:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        raise ValueError(
                            f"blank legacy data-catalogue record at line {line_number}"
                        )
                    try:
                        loaded: Any = json.loads(line)
                        if not isinstance(loaded, dict):
                            raise TypeError("catalogue event is not an object")
                        if loaded.get("schema_version") != self.LEGACY_SCHEMA_VERSION:
                            raise ValueError("unsupported legacy catalogue schema")
                        handle = _legacy_dataset_handle(loaded["handle"])
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        raise ValueError(
                            f"invalid legacy data-catalogue record at line {line_number}: "
                            f"{type(exc).__name__}"
                        ) from exc
                    latest[handle.dataset_id] = handle
            finally:
                fcntl.flock(source.fileno(), fcntl.LOCK_UN)
        return latest

    def handles(self) -> dict[str, DatasetHandle]:
        latest = self._legacy_handles()
        histories: dict[str, list[tuple[int, str, str | None, str, DatasetHandle]]] = {}
        for path in self._event_files():
            event = _read_event(path)
            histories.setdefault(event[4].dataset_id, []).append(event)
        for dataset_id, history in histories.items():
            history.sort(key=lambda item: item[0])
            if [item[0] for item in history] != list(range(1, len(history) + 1)):
                raise ValueError(f"non-contiguous data-catalogue history for {dataset_id}")
            prior_digest: str | None = None
            previous: DatasetHandle | None = None
            for sequence, event_type, claimed_prior, digest, handle in history:
                if claimed_prior != prior_digest:
                    raise ValueError(f"broken data-catalogue digest chain for {dataset_id}")
                if sequence == 1 and event_type != "dataset_registered":
                    raise ValueError(f"invalid first catalogue event for {dataset_id}")
                if previous is not None:
                    self._validate_transition(previous, handle, event_type)
                prior_digest = digest
                previous = handle
            latest[dataset_id] = history[-1][4]
        return latest

    def get(self, dataset_id: str) -> DatasetHandle:
        try:
            return self.handles()[dataset_id]
        except KeyError as exc:
            raise DatasetUnavailableError(f"unknown DAT dataset: {dataset_id}") from exc

    def get_dataset(self, *, trading_date: date) -> DatasetHandle:
        matches = [
            handle
            for handle in self.handles().values()
            if handle.trading_date == trading_date and handle.status is DatasetStatus.COMPLETED
        ]
        if not matches:
            raise DatasetUnavailableError(
                f"DAT has no completed dataset for trading date {trading_date.isoformat()}"
            )
        matches.sort(
            key=lambda handle: (
                handle.completed_at or handle.coverage_end or handle.started_at,
                handle.dataset_id,
            ),
            reverse=True,
        )
        return matches[0]

    def resolve(self, request: DatasetRequest) -> DatasetHandle:
        matches = [
            item
            for item in self.handles().values()
            if item.satisfies(request) and _active_process_is_live(item)
        ]
        if not matches:
            raise DatasetUnavailableError(
                "DAT has no dataset satisfying request "
                f"{request.acquisition_fingerprint[:12]} for {request.consumer}"
            )
        matches.sort(
            key=lambda item: (
                item.status is DatasetStatus.ACTIVE,
                item.coverage_end or item.started_at,
                item.started_at,
            ),
            reverse=True,
        )
        return matches[0]

    def active_satisfying(self, request: DatasetRequest) -> DatasetHandle | None:
        return next(
            (
                handle
                for handle in self.handles().values()
                if handle.status is DatasetStatus.ACTIVE
                and handle.satisfies(request)
                and _active_process_is_live(handle)
            ),
            None,
        )

    def acquire_claim(self, request: DatasetRequest, *, dataset_id: str, producer_pid: int) -> Path:
        self.claim_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        claim = self.claim_root / f"{request.acquisition_fingerprint}.claim"
        descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        payload = "|".join(
            (
                CATALOG_SCHEMA_VERSION,
                dataset_id,
                str(producer_pid),
                socket.gethostname(),
                datetime.now(UTC).isoformat(),
            )
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write((payload + "\n").encode())
            target.flush()
            os.fsync(target.fileno())
        _fsync_directory(self.claim_root)
        return claim

    def release_claim(self, claim: Path, *, terminal: str) -> Path:
        if not claim.is_file():
            return claim
        history = self.claim_root / "history"
        history.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        target = history / f"{claim.stem}-{stamp}-{terminal}.claim"
        os.rename(claim, target)
        _fsync_directory(history)
        return target

    def claim_handle(self, request: DatasetRequest) -> DatasetHandle | None:
        claim = self.claim_root / f"{request.acquisition_fingerprint}.claim"
        if not claim.is_file():
            return None
        try:
            raw = claim.read_text(encoding="utf-8").strip()
            _version, dataset_id, raw_pid, host, _recorded = raw.split("|")
        except ValueError as exc:
            raise ValueError(f"malformed acquisition claim: {claim.name}") from exc
        with suppress(DatasetUnavailableError):
            handle = self.get(dataset_id)
            if host == socket.gethostname():
                try:
                    os.kill(int(raw_pid), 0)
                except ProcessLookupError:
                    if handle.status is DatasetStatus.ACTIVE:
                        orphaned = DatasetHandle.model_validate(
                            handle.model_copy(
                                update={
                                    "status": DatasetStatus.ORPHANED,
                                    "producer_pid": None,
                                    "completed_at": datetime.now(UTC),
                                    "invalidation_reason": "local producer exited without closing",
                                }
                            ).model_dump()
                        )
                        self.publish(orphaned)
                    self.release_claim(claim, terminal="orphaned-local")
                    return None
                except PermissionError:
                    pass
            return handle
        if host == socket.gethostname():
            try:
                os.kill(int(raw_pid), 0)
            except ProcessLookupError:
                self.release_claim(claim, terminal="orphaned-unregistered-local")
        return None
