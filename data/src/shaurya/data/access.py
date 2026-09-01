"""DAT-22: format-neutral catalogue, capture, validation, replay and migration boundary."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any

import pyarrow.parquet as pq

from shaurya.contracts.artifacts import RunId, sha256_file
from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetRequest,
    DatasetStatus,
    StorageFormat,
)
from shaurya.contracts.tape import TapeRow

from .catalog import (
    DataCatalog as DataCatalog,
)
from .catalog import (
    DatasetAlreadyActiveError as DatasetAlreadyActiveError,
)
from .catalog import (
    DatasetUnavailableError as DatasetUnavailableError,
)
from .metadata import ParquetCaptureManifest, decode_mapping_fields
from .parquet import (
    ROW_SCHEMA_VERSION,
    STORAGE_FORMAT_VERSION,
    SegmentedParquetWriter,
    canonical_row_digest,
    dataset_digest,
    describe_segment,
    human_dataset_name,
    inventory_recovery,
    iter_parquet_rows,
    new_dataset_id,
    scope_key_for_instruments,
    segments_overlap_filter,
    validate_segment,
)
from .tape import (
    CompleteLineJsonlTail,
    IndexedJsonlTapeReader,
    JsonlTapeReader,
    ParsedBatch,
    TapeIndexBuilder,
    TapeIntegrityError,
    archive_tape,
    data_channel_for_row,
)


def _scope_name(request: DatasetRequest) -> str:
    return scope_key_for_instruments(request.instrument_ids)


def _prior_attempt_count(catalog: DataCatalog, request: DatasetRequest, *, scope: str) -> int:
    """Count earlier capture attempts for the same trading date/channels/scope.

    Used only to number retries in the human-readable dataset name (D51-follow-up); a
    crashed-and-relaunched capture otherwise leaves sibling folders with no indication
    they are the same logical capture. Not used for any concurrency or identity decision
    — ``acquisition_fingerprint`` remains the sole correctness-critical identity.
    """

    channel_key = tuple(sorted(str(channel) for channel in request.channels))
    return sum(
        1
        for handle in catalog.handles().values()
        if handle.trading_date == request.trading_date
        and tuple(sorted(str(channel) for channel in handle.channels)) == channel_key
        and scope_key_for_instruments(handle.instrument_ids) == scope
    )


class _ExclusiveFileLease:
    """Process-scoped advisory lease released on success, exception unwind, or process exit."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._handle = path.open("a+b")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        if self._handle.closed:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()

    def __del__(self) -> None:
        self.release()


class DataCaptureSession:
    """Bounded version-2 capture with atomic segment and lifecycle publication."""

    def __init__(
        self,
        *,
        catalog: DataCatalog,
        request: DatasetRequest,
        manifest: ParquetCaptureManifest,
        writer: SegmentedParquetWriter,
        handle: DatasetHandle,
        claim_path: Path,
    ) -> None:
        self.catalog = catalog
        self.request = request
        self.manifest = manifest
        self.writer = writer
        self.handle = handle
        self.claim_path = claim_path
        self._closed = False

    @classmethod
    def create(
        cls,
        *,
        catalog: DataCatalog,
        request: DatasetRequest,
        output_root: Path,
        run_id: RunId | None = None,
        fsync_every: int = 100,
        index_stride_rows: int = 1_000,
        segment_max_rows: int = 50_000,
        segment_max_seconds: float = 30.0,
        segment_max_estimated_bytes: int = 64 * 1024 * 1024,
        row_group_size: int = 10_000,
        dataset_name_suffix: str | None = None,
    ) -> DataCaptureSession:
        del fsync_every, index_stride_rows
        dataset_id = str(run_id) if run_id is not None else new_dataset_id()
        started = datetime.now(UTC)
        naming_stamp = started.replace(
            year=request.trading_date.year,
            month=request.trading_date.month,
            day=request.trading_date.day,
        )
        scope = _scope_name(request)
        with catalog.acquisition_lock():
            existing = catalog.active_satisfying(request)
            if existing is not None:
                raise DatasetAlreadyActiveError(existing)
            claimed = catalog.claim_handle(request)
            if claimed is not None:
                raise DatasetAlreadyActiveError(claimed)
            attempt = 1 + _prior_attempt_count(catalog, request, scope=scope)
            dataset_name = human_dataset_name(
                trading_date=naming_stamp,
                channels=request.channels,
                instrument_ids=request.instrument_ids,
                suffix=dataset_name_suffix or dataset_id[-8:],
                attempt=attempt,
            )
            dataset_dir = output_root / "dhan" / scope / dataset_name
            try:
                claim = catalog.acquire_claim(
                    request, dataset_id=dataset_id, producer_pid=os.getpid()
                )
            except FileExistsError as exc:
                claimed = catalog.claim_handle(request)
                if claimed is not None:
                    raise DatasetAlreadyActiveError(claimed) from exc
                raise RuntimeError(
                    "compatible acquisition claim exists without a valid dataset"
                ) from exc
            try:
                writer = SegmentedParquetWriter(
                    dataset_dir,
                    dataset_id=dataset_id,
                    max_rows=segment_max_rows,
                    max_duration=timedelta(seconds=segment_max_seconds),
                    max_estimated_bytes=segment_max_estimated_bytes,
                    row_group_size=row_group_size,
                )
                manifest = ParquetCaptureManifest(
                    catalog.root / "operational" / dataset_id,
                    run_id=dataset_id,
                )
                active = DatasetHandle(
                    schema_version="2.0.0",
                    dataset_id=dataset_id,
                    acquisition_fingerprint=request.acquisition_fingerprint,
                    source="dhan",
                    status=DatasetStatus.ACTIVE,
                    producer_pid=os.getpid(),
                    producer_host=socket.gethostname(),
                    trading_date=request.trading_date,
                    channels=request.channels,
                    instrument_ids=request.instrument_ids,
                    storage_format=StorageFormat.SEGMENTED_PARQUET,
                    storage_format_version=STORAGE_FORMAT_VERSION,
                    row_schema_version=ROW_SCHEMA_VERSION,
                    dataset_name=dataset_name,
                    row_run_id=dataset_id,
                    dataset_path=str(dataset_dir.resolve()),
                    manifest_path=str(manifest.path),
                    started_at=started,
                    requested_coverage_start=request.coverage_start,
                    requested_coverage_end=request.coverage_end,
                )
                catalog.register(active)
            except BaseException:
                catalog.release_claim(claim, terminal="create-failed")
                raise
        return cls(
            catalog=catalog,
            request=request,
            manifest=manifest,
            writer=writer,
            handle=active,
            claim_path=claim,
        )

    @property
    def dataset_id(self) -> str:
        return self.handle.dataset_id

    def _publish_closed_segments(self) -> None:
        if not self.writer.drain_published():
            return
        segments = self.writer.segments
        updated = self.handle.model_copy(
            update={
                "segments": segments,
                "dataset_digest": dataset_digest(segments),
                "rows": sum(segment.rows for segment in segments),
                "bytes": sum(segment.bytes for segment in segments),
                "coverage_start": min(segment.coverage_start for segment in segments),
                "coverage_end": max(segment.coverage_end for segment in segments),
            }
        )
        self.handle = DatasetHandle.model_validate(updated.model_dump())
        self.catalog.publish_segment(self.handle)

    def write(self, row: TapeRow) -> None:
        if self._closed:
            raise ValueError("cannot write to a closed DAT capture")
        if row.instrument_id not in self.request.instrument_ids:
            raise ValueError("capture row instrument is outside the claimed DAT request")
        if data_channel_for_row(row) not in self.request.channels:
            raise ValueError("capture row channel is outside the claimed DAT request")
        self.writer.write(row)
        self._publish_closed_segments()

    def close(
        self,
        *,
        invalidation_reason: str | None = None,
        archive: bool = False,
    ) -> DatasetHandle:
        del archive
        if self._closed:
            return self.handle
        try:
            self.writer.close()
            self._publish_closed_segments()
            now = datetime.now(UTC)
            segments = self.writer.segments
            if invalidation_reason is None and not segments:
                invalidation_reason = "capture produced zero canonical rows"
            status = (
                DatasetStatus.INVALIDATED
                if invalidation_reason is not None
                else DatasetStatus.COMPLETED
            )
            terminal = self.handle.model_copy(
                update={
                    "status": status,
                    "producer_pid": None,
                    "completed_at": now,
                    "segments": segments,
                    "operational_artifacts": self.manifest.artifacts,
                    "dataset_digest": dataset_digest(segments) if segments else None,
                    "coverage_start": (
                        min(segment.coverage_start for segment in segments) if segments else None
                    ),
                    "coverage_end": (
                        max(segment.coverage_end for segment in segments) if segments else None
                    ),
                    "rows": sum(segment.rows for segment in segments),
                    "bytes": sum(segment.bytes for segment in segments),
                    "invalidation_reason": invalidation_reason,
                }
            )
            self.handle = DatasetHandle.model_validate(terminal.model_dump())
            self.catalog.publish(self.handle)
        except BaseException as exc:
            segments = self.writer.segments
            failed = self.handle.model_copy(
                update={
                    "status": DatasetStatus.FAILED,
                    "producer_pid": None,
                    "completed_at": datetime.now(UTC),
                    "segments": segments,
                    "operational_artifacts": self.manifest.artifacts,
                    "dataset_digest": dataset_digest(segments) if segments else None,
                    "coverage_start": (
                        min(segment.coverage_start for segment in segments) if segments else None
                    ),
                    "coverage_end": (
                        max(segment.coverage_end for segment in segments) if segments else None
                    ),
                    "rows": sum(segment.rows for segment in segments),
                    "bytes": sum(segment.bytes for segment in segments),
                    "invalidation_reason": f"capture finalization failed: {type(exc).__name__}",
                }
            )
            try:
                self.handle = DatasetHandle.model_validate(failed.model_dump())
                self.catalog.publish(self.handle)
            except BaseException as publication_exc:
                # Retain the active claim if even failure publication is unavailable. A later
                # recovery must resolve the active handle and any final-but-unpublished files.
                raise exc from publication_exc
            self._closed = True
            self.catalog.release_claim(self.claim_path, terminal="failed")
            raise
        self._closed = True
        self.catalog.release_claim(
            self.claim_path,
            terminal="invalidated" if invalidation_reason else "completed",
        )
        return self.handle

    def __enter__(self) -> DataCaptureSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        self.close(invalidation_reason=exc_type.__name__ if exc_type is not None else None)


class DatasetFollower:
    """Format-neutral bounded follower of complete JSONL rows or published Parquet segments."""

    def __init__(self, catalog: DataCatalog, handle: DatasetHandle) -> None:
        if handle.status not in {DatasetStatus.ACTIVE, DatasetStatus.COMPLETED}:
            raise ValueError(f"cannot follow dataset in state {handle.status}")
        self.catalog = catalog
        self.dataset_id = handle.dataset_id
        self.storage_format = handle.storage_format or StorageFormat.LEGACY_JSONL
        self._legacy = (
            CompleteLineJsonlTail(Path(handle.tape_path or ""))
            if self.storage_format is StorageFormat.LEGACY_JSONL
            else None
        )
        self._next_segment = 1
        self.offset = 0
        self.rows_parsed = 0
        self.malformed_lines = 0
        self.torn_lines = 0

    @property
    def trailing_partial_bytes(self) -> int:
        return self._legacy.trailing_partial_bytes if self._legacy is not None else 0

    @property
    def finished(self) -> bool:
        handle = self.catalog.get(self.dataset_id)
        if self._legacy is not None:
            path = Path(handle.tape_path or "")
            return (
                handle.status is not DatasetStatus.ACTIVE
                and path.is_file()
                and self._legacy.offset >= path.stat().st_size
                and self._legacy.trailing_partial_bytes == 0
            )
        return handle.status is not DatasetStatus.ACTIVE and self._next_segment > len(
            handle.segments
        )

    def poll(self, *, max_bytes: int | None = None) -> ParsedBatch:
        if self._legacy is not None:
            batch = self._legacy.poll(max_bytes=max_bytes)
            self.offset = self._legacy.offset
            self.rows_parsed = self._legacy.rows_parsed
            self.malformed_lines = self._legacy.malformed_lines
            self.torn_lines = self._legacy.torn_lines
            return batch
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        handle = self.catalog.get(self.dataset_id)
        rows: list[dict[str, Any]] = []
        bytes_read = 0
        while self._next_segment <= len(handle.segments):
            segment = handle.segments[self._next_segment - 1]
            if max_bytes is not None and bytes_read + segment.bytes > max_bytes:
                if not rows:
                    raise ValueError("max_bytes is smaller than the next immutable Parquet segment")
                break
            validate_segment(segment)
            rows.extend(row.to_dict() for row in iter_parquet_rows(Path(segment.path)))
            bytes_read += segment.bytes
            self.offset += segment.bytes
            self._next_segment += 1
        self.rows_parsed += len(rows)
        return ParsedBatch(tuple(rows), bytes_read, len(rows))

    def drain_available(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        while True:
            batch = self.poll()
            rows.extend(batch.rows)
            if batch.bytes_read == 0:
                return tuple(rows)


class LegacySourceState(StrEnum):
    COMPLETED = "completed"
    ACTIVE = "active"
    TORN_TAIL = "torn_tail"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


def _legacy_lifecycle_evidence(
    tape_path: Path,
    *,
    run_id: str,
    tape_sha256: str,
    manifest_path: Path | None = None,
) -> tuple[LegacySourceState, Path]:
    """Classify a legacy run from its append-only manifest and bind the exact tape hash."""

    candidate = (
        manifest_path.resolve()
        if manifest_path is not None
        else tape_path.parent / f"manifest_{run_id}.jsonl"
    )
    if not candidate.is_file():
        raise ValueError("completed legacy evidence requires its lifecycle manifest")
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(candidate.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TapeIntegrityError(
                f"invalid legacy lifecycle manifest at line {line_number}"
            ) from exc
        if not isinstance(event, dict) or event.get("run_id") != run_id:
            raise TapeIntegrityError("legacy lifecycle manifest has a different run identity")
        if event.get("manifest_sequence") != line_number:
            raise TapeIntegrityError("legacy lifecycle manifest sequence is not contiguous")
        events.append(event)
    if not events:
        raise TapeIntegrityError("legacy lifecycle manifest is empty")
    matching_close = [
        event
        for event in events
        if event.get("event_type") == "artifact_closed"
        and event.get("artifact") == tape_path.name
        and event.get("sha256") == tape_sha256
        and event.get("bytes") == tape_path.stat().st_size
    ]
    terminal = str(events[-1].get("event_type", ""))
    state = {
        "run_completed": LegacySourceState.COMPLETED,
        "run_invalidated": LegacySourceState.INVALIDATED,
        "run_cancelled": LegacySourceState.CANCELLED,
        "run_failed": LegacySourceState.FAILED,
    }.get(terminal)
    if state is None:
        state = (
            LegacySourceState.FAILED
            if any(event.get("event_type") == "artifact_failed" for event in events)
            else LegacySourceState.ACTIVE
        )
    if state is LegacySourceState.COMPLETED and len(matching_close) != 1:
        raise TapeIntegrityError(
            "completed legacy manifest does not bind the exact closed tape hash"
        )
    return state, candidate.resolve()


class DataAccess:
    """Public logical row and lifecycle interface for legacy and version-2 datasets."""

    def __init__(self, catalog: DataCatalog) -> None:
        self.catalog = catalog

    def request(self, request: DatasetRequest) -> DatasetHandle:
        return self.catalog.resolve(request)

    def handle(self, dataset_id: str) -> DatasetHandle:
        return self.catalog.get(dataset_id)

    def _verify_v2_metadata(self, handle: DatasetHandle) -> None:
        if handle.schema_version != "2.0.0":
            raise TapeIntegrityError("unsupported segmented dataset handle version")
        if handle.storage_format is not StorageFormat.SEGMENTED_PARQUET:
            raise TapeIntegrityError("version-2 handle storage format is inconsistent")
        if (
            handle.status is DatasetStatus.ACTIVE
            and not handle.segments
            and handle.dataset_digest is None
        ):
            return
        if handle.dataset_digest != dataset_digest(handle.segments):
            raise TapeIntegrityError("DAT dataset digest differs from ordered segment metadata")
        for segment in handle.segments:
            validate_segment(segment)

    def rows(
        self,
        handle: DatasetHandle,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: tuple[DataChannel, ...] | None = None,
        instrument_ids: tuple[str, ...] | None = None,
    ) -> Iterator[TapeRow]:
        storage_format = handle.storage_format or StorageFormat.LEGACY_JSONL
        if storage_format is StorageFormat.SEGMENTED_PARQUET:
            self._verify_v2_metadata(handle)
            selected = (
                segment
                for segment in handle.segments
                if segments_overlap_filter(
                    segment,
                    start=start,
                    end=end,
                    channels=channels,
                    instrument_ids=instrument_ids,
                )
            )
            prior_sequence: int | None = None
            unfiltered = start is None and end is None and not channels and not instrument_ids
            for segment in selected:
                for row in iter_parquet_rows(
                    Path(segment.path),
                    start=start,
                    end=end,
                    channels=channels,
                    instrument_ids=instrument_ids,
                ):
                    if (
                        unfiltered
                        and prior_sequence is not None
                        and row.receive_sequence != prior_sequence + 1
                    ):
                        raise TapeIntegrityError(
                            "receive sequence is not contiguous during segmented replay"
                        )
                    prior_sequence = row.receive_sequence
                    yield row
            return
        if handle.tape_path is None:
            raise TapeIntegrityError("legacy dataset handle has no tape path")
        tape_path = Path(handle.tape_path)
        if (
            tape_path.is_file()
            and handle.tape_sha256 is not None
            and sha256_file(tape_path) != handle.tape_sha256
        ):
            raise TapeIntegrityError("DAT tape hash differs from its published handle")
        if handle.index_path is not None and tape_path.is_file():
            index_path = Path(handle.index_path)
            if handle.index_sha256 is not None and sha256_file(index_path) != handle.index_sha256:
                raise TapeIntegrityError("DAT index hash differs from its published handle")
            yield from IndexedJsonlTapeReader(tape_path, index_path).rows(
                start=start,
                end=end,
                channels=channels,
                instrument_ids=instrument_ids,
            )
            return
        source_path = tape_path
        if not source_path.is_file() and handle.archive_path is not None:
            source_path = Path(handle.archive_path)
            if handle.archive_sha256 and sha256_file(source_path) != handle.archive_sha256:
                raise TapeIntegrityError("DAT archive hash differs from its published handle")
        wanted_channels = set(channels or ())
        wanted_instruments = set(instrument_ids or ())
        for row in JsonlTapeReader(source_path).rows():
            if start is not None and row.receive_ts < start:
                continue
            if end is not None and row.receive_ts > end:
                continue
            if wanted_channels and data_channel_for_row(row) not in wanted_channels:
                continue
            if wanted_instruments and row.instrument_id not in wanted_instruments:
                continue
            yield row

    def validate(self, handle: DatasetHandle) -> dict[str, Any]:
        if handle.status is not DatasetStatus.COMPLETED:
            raise TapeIntegrityError("full validation requires a completed dataset")
        canonical = self.catalog.get(handle.dataset_id)
        if canonical != handle:
            raise TapeIntegrityError("dataset handle is not current catalogue authority")
        if handle.storage_format is StorageFormat.SEGMENTED_PARQUET:
            self._verify_v2_metadata(handle)
        digest = hashlib.sha256()
        rows = 0
        prior: int | None = None
        first: datetime | None = None
        last: datetime | None = None
        for row in self.rows(handle):
            if row.run_id != (handle.row_run_id or handle.dataset_id):
                raise TapeIntegrityError("row logical run ID differs from dataset handle")
            if row.instrument_id not in handle.instrument_ids:
                raise TapeIntegrityError("row instrument is outside dataset coverage")
            if data_channel_for_row(row) not in handle.channels:
                raise TapeIntegrityError("row channel is outside dataset coverage")
            if prior is not None and row.receive_sequence != prior + 1:
                raise TapeIntegrityError("receive sequence is not globally contiguous")
            prior = row.receive_sequence
            first = row.receive_ts if first is None else min(first, row.receive_ts)
            last = row.receive_ts if last is None else max(last, row.receive_ts)
            encoded = json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            rows += 1
        if rows == 0 or rows != handle.rows or first is None or last is None:
            raise TapeIntegrityError("full replay row count differs from completed handle")
        if first != handle.coverage_start or last != handle.coverage_end:
            raise TapeIntegrityError("full replay coverage differs from completed handle")
        observed_row_digest = digest.hexdigest()
        if handle.canonical_row_digest and observed_row_digest != handle.canonical_row_digest:
            raise TapeIntegrityError("canonical row digest differs from completed handle")
        return {
            "dataset_id": handle.dataset_id,
            "storage_format": str(handle.storage_format or StorageFormat.LEGACY_JSONL),
            "rows": rows,
            "bytes": handle.bytes,
            "segments": len(handle.segments),
            "coverage_start": first.isoformat(),
            "coverage_end": last.isoformat(),
            "dataset_digest": handle.dataset_digest,
            "canonical_row_digest": observed_row_digest,
            "valid": True,
        }

    def follow(self, handle: DatasetHandle) -> DatasetFollower:
        return DatasetFollower(self.catalog, handle)

    def operational_record(self, handle: DatasetHandle, kind: str) -> dict[str, Any]:
        """Read one Data-owned operational artifact without exposing its physical format."""

        if handle.manifest_path is None:
            raise FileNotFoundError("dataset has no operational metadata location")
        if handle.storage_format is StorageFormat.SEGMENTED_PARQUET:
            matches = [
                artifact for artifact in handle.operational_artifacts if artifact.kind == kind
            ]
            if len(matches) != 1:
                raise FileNotFoundError(f"dataset has no unique operational artifact: {kind}")
            artifact = matches[0]
            path = Path(artifact.path)
            if (
                not path.is_file()
                or path.stat().st_size != artifact.bytes
                or sha256_file(path) != artifact.sha256
            ):
                raise TapeIntegrityError(f"operational artifact changed or is missing: {kind}")
            table = pq.read_table(path)
            metadata = table.schema.metadata or {}
            if (
                table.num_rows != 1
                or metadata.get(b"shaurya.artifact_kind") != kind.encode()
                or metadata.get(b"shaurya.dataset_id") != handle.dataset_id.encode()
            ):
                raise TapeIntegrityError(f"malformed operational artifact: {kind}")
            loaded = table.to_pylist()[0]
            if not isinstance(loaded, dict):
                raise TapeIntegrityError(f"operational artifact is not a record: {kind}")
            try:
                return decode_mapping_fields(dict(loaded), metadata)
            except (TypeError, ValueError) as exc:
                raise TapeIntegrityError(
                    f"malformed operational artifact JSON fields: {kind}"
                ) from exc
        manifest_path = Path(handle.manifest_path)
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        legacy_artifact: Path | None = None
        expected_hash: str | None = None
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event_type") == "artifact_closed" and event.get("kind") == kind:
                legacy_artifact = manifest_path.parent / str(event["artifact"])
                expected_hash = str(event["sha256"])
        if (
            legacy_artifact is None
            or not legacy_artifact.is_file()
            or sha256_file(legacy_artifact) != expected_hash
        ):
            raise TapeIntegrityError(f"legacy operational artifact is missing or changed: {kind}")
        loaded = json.loads(legacy_artifact.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TapeIntegrityError(f"legacy operational artifact is not a record: {kind}")
        return dict(loaded)

    def adopt_legacy_tape(
        self,
        tape_path: Path,
        *,
        source_state: LegacySourceState,
        manifest_path: Path | None = None,
        consumer: str,
        purpose: str,
    ) -> DatasetHandle:
        resolved = tape_path.resolve()
        if source_state is not LegacySourceState.COMPLETED:
            raise ValueError("only explicitly completed legacy evidence may be adopted as complete")
        if not resolved.is_file() or resolved.stat().st_size == 0:
            raise ValueError("cannot adopt a missing or empty legacy tape")
        with resolved.open("rb") as source:
            source.seek(-1, os.SEEK_END)
            if source.read(1) != b"\n":
                raise TapeIntegrityError("completed legacy evidence has a torn trailing row")
        tape_hash = sha256_file(resolved)
        dataset_id = f"legacy-{tape_hash[:16]}"
        with suppress(DatasetUnavailableError):
            return self.catalog.get(dataset_id)
        index = TapeIndexBuilder()
        channels_seen: set[DataChannel] = set()
        instruments_seen: set[str] = set()
        row_count = 0
        offset = 0
        row_digest = hashlib.sha256()
        observed_run_id: str | None = None
        rows = JsonlTapeReader(resolved).rows()
        with resolved.open("rb") as source:
            for row, encoded in zip(rows, source, strict=True):
                observed_run_id = observed_run_id or row.run_id
                if row.run_id != observed_run_id:
                    raise TapeIntegrityError("legacy tape mixes logical run IDs")
                index.observe(row, offset, len(encoded))
                offset += len(encoded)
                row_count += 1
                channels_seen.add(data_channel_for_row(row))
                instruments_seen.add(row.instrument_id)
                canonical = json.dumps(
                    row.to_dict(), sort_keys=True, separators=(",", ":")
                ).encode()
                row_digest.update(len(canonical).to_bytes(8, "big"))
                row_digest.update(canonical)
        if (
            row_count == 0
            or index.coverage_start is None
            or index.coverage_end is None
            or observed_run_id is None
        ):
            raise ValueError("cannot adopt an empty legacy tape")
        if sha256_file(resolved) != tape_hash:
            raise TapeIntegrityError("legacy tape changed during adoption")
        evidenced_state, evidenced_manifest = _legacy_lifecycle_evidence(
            resolved,
            run_id=observed_run_id,
            tape_sha256=tape_hash,
            manifest_path=manifest_path,
        )
        if evidenced_state is not source_state:
            raise ValueError(f"legacy lifecycle evidence is {evidenced_state}, not {source_state}")
        channels = tuple(sorted(channels_seen, key=str))
        instruments = tuple(sorted(instruments_seen))
        request = DatasetRequest(
            consumer=consumer,
            purpose=purpose,
            trading_date=index.coverage_start.date(),
            channels=channels,
            instrument_ids=instruments,
            coverage_start=index.coverage_start,
            coverage_end=index.coverage_end,
            allow_active=False,
        )
        index_path = resolved.with_suffix(".index.json")
        if not index_path.exists():
            index.write(index_path, resolved)
        else:
            IndexedJsonlTapeReader(resolved, index_path)
        now = datetime.now(UTC)
        handle = DatasetHandle(
            dataset_id=dataset_id,
            acquisition_fingerprint=request.acquisition_fingerprint,
            source="legacy_tape",
            status=DatasetStatus.COMPLETED,
            trading_date=request.trading_date,
            channels=channels,
            instrument_ids=instruments,
            storage_format=StorageFormat.LEGACY_JSONL,
            row_run_id=observed_run_id,
            tape_path=str(resolved),
            index_path=str(index_path.resolve()),
            manifest_path=str(evidenced_manifest),
            started_at=index.coverage_start,
            completed_at=now,
            requested_coverage_start=request.coverage_start,
            requested_coverage_end=request.coverage_end,
            coverage_start=request.coverage_start,
            coverage_end=request.coverage_end,
            rows=row_count,
            bytes=resolved.stat().st_size,
            tape_sha256=tape_hash,
            index_sha256=sha256_file(index_path),
            canonical_row_digest=row_digest.hexdigest(),
        )
        self.catalog.register(handle)
        return handle

    def adopt_active_legacy_tape(
        self,
        tape_path: Path,
        *,
        consumer: str,
        purpose: str,
        producer_pid: int,
        requested_coverage_end: datetime | None = None,
    ) -> DatasetHandle:
        if producer_pid < 1:
            raise ValueError("active legacy adoption requires a positive producer_pid")
        try:
            os.kill(producer_pid, 0)
        except OSError as exc:
            raise ValueError(f"legacy producer PID {producer_pid} is not alive") from exc
        resolved = tape_path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        identity = hashlib.sha256(str(resolved).encode()).hexdigest()[:16]
        dataset_id = f"legacy-active-{identity}"
        existing: DatasetHandle | None = None
        with suppress(DatasetUnavailableError):
            existing = self.catalog.get(dataset_id)
            if Path(existing.tape_path or "") != resolved:
                raise ValueError("active legacy dataset ID resolved to a different tape")
        channels_seen: set[DataChannel] = set()
        instruments_seen: set[str] = set()
        first: datetime | None = None
        last: datetime | None = None
        prior_sequence: int | None = None
        observed_run_id: str | None = None
        rows = 0
        complete_bytes = 0
        with resolved.open("rb") as source:
            for line_number, encoded in enumerate(source, start=1):
                if not encoded.endswith(b"\n"):
                    break
                try:
                    loaded: Any = json.loads(encoded)
                    if not isinstance(loaded, dict):
                        raise TypeError("row is not an object")
                    row = TapeRow.from_dict(loaded)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise TapeIntegrityError(
                        f"invalid active legacy tape row at line {line_number}: "
                        f"{type(exc).__name__}"
                    ) from exc
                if observed_run_id is None:
                    observed_run_id = row.run_id
                if row.run_id != observed_run_id:
                    raise TapeIntegrityError("active legacy tape mixes run IDs")
                if prior_sequence is not None and row.receive_sequence <= prior_sequence:
                    raise TapeIntegrityError("active legacy receive sequence is not increasing")
                prior_sequence = row.receive_sequence
                rows += 1
                complete_bytes += len(encoded)
                channels_seen.add(data_channel_for_row(row))
                instruments_seen.add(row.instrument_id)
                first = row.receive_ts if first is None else min(first, row.receive_ts)
                last = row.receive_ts if last is None else max(last, row.receive_ts)
        if rows == 0 or first is None or last is None or observed_run_id is None:
            raise ValueError("cannot adopt an empty active legacy tape")
        if existing is not None:
            if existing.producer_pid != producer_pid or existing.row_run_id != observed_run_id:
                raise ValueError("active legacy tape path was reused by a different producer run")
            return existing
        request = DatasetRequest(
            consumer=consumer,
            purpose=purpose,
            trading_date=first.date(),
            channels=tuple(sorted(channels_seen, key=str)),
            instrument_ids=tuple(sorted(instruments_seen)),
            coverage_start=first,
            coverage_end=requested_coverage_end,
            allow_active=True,
        )
        handle = DatasetHandle(
            dataset_id=dataset_id,
            acquisition_fingerprint=request.acquisition_fingerprint,
            source="legacy_tape",
            status=DatasetStatus.ACTIVE,
            producer_pid=producer_pid,
            producer_host=socket.gethostname(),
            trading_date=request.trading_date,
            channels=request.channels,
            instrument_ids=request.instrument_ids,
            storage_format=StorageFormat.LEGACY_JSONL,
            row_run_id=observed_run_id,
            tape_path=str(resolved),
            started_at=first,
            requested_coverage_start=first,
            requested_coverage_end=requested_coverage_end,
            coverage_start=first,
            coverage_end=last,
            rows=rows,
            bytes=complete_bytes,
        )
        self.catalog.register(handle)
        return handle

    def migrate_legacy_tape(
        self,
        tape_path: Path,
        *,
        source_state: LegacySourceState,
        source_manifest: Path | None = None,
        output_root: Path | None = None,
        convert: bool = False,
        dry_run: bool = True,
        segment_max_rows: int = 50_000,
    ) -> dict[str, Any]:
        resolved = tape_path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        original_hash = sha256_file(resolved)
        ends_with_newline = resolved.stat().st_size == 0
        if resolved.stat().st_size:
            with resolved.open("rb") as source:
                source.seek(-1, os.SEEK_END)
                ends_with_newline = source.read(1) == b"\n"
        if source_state is LegacySourceState.COMPLETED and not ends_with_newline:
            raise TapeIntegrityError("completed legacy declaration has a torn trailing row")
        if source_state is not LegacySourceState.COMPLETED:
            return {
                "source": str(resolved),
                "source_sha256": original_hash,
                "source_state": str(source_state),
                "eligible_for_completion": False,
                "converted": False,
                "dry_run": dry_run,
                "original_preserved": sha256_file(resolved) == original_hash,
            }
        first_row: TapeRow | None = None
        last_row: TapeRow | None = None
        channels: set[DataChannel] = set()
        instruments: set[str] = set()
        digest = hashlib.sha256()
        count = 0
        observed_run_id: str | None = None
        prior_sequence: int | None = None
        for row in JsonlTapeReader(resolved).rows():
            observed_run_id = observed_run_id or row.run_id
            if row.run_id != observed_run_id:
                raise TapeIntegrityError("legacy migration source mixes logical run IDs")
            if prior_sequence is not None and row.receive_sequence != prior_sequence + 1:
                raise TapeIntegrityError("legacy migration source sequence is not contiguous")
            prior_sequence = row.receive_sequence
            first_row = row if first_row is None else first_row
            last_row = row
            channels.add(data_channel_for_row(row))
            instruments.add(row.instrument_id)
            encoded = json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        if first_row is None or last_row is None or observed_run_id is None:
            raise ValueError("cannot migrate an empty legacy tape")
        evidenced_state, evidenced_manifest = _legacy_lifecycle_evidence(
            resolved,
            run_id=observed_run_id,
            tape_sha256=original_hash,
            manifest_path=source_manifest,
        )
        if evidenced_state is not source_state:
            raise ValueError(f"legacy lifecycle evidence is {evidenced_state}, not {source_state}")
        report: dict[str, Any] = {
            "source": str(resolved),
            "source_sha256": original_hash,
            "source_state": str(source_state),
            "source_manifest": str(evidenced_manifest),
            "eligible_for_completion": True,
            "rows": count,
            "coverage_start": first_row.receive_ts.isoformat(),
            "coverage_end": last_row.receive_ts.isoformat(),
            "canonical_row_digest": digest.hexdigest(),
            "converted": False,
            "dry_run": dry_run,
            "original_preserved": True,
        }
        if dry_run or not convert:
            return report
        if output_root is None:
            raise ValueError("legacy conversion requires output_root")
        dataset_id = f"legacy-converted-{original_hash[:16]}"
        with suppress(DatasetUnavailableError):
            existing = self.handle(dataset_id)
            validation = self.validate(existing)
            if (
                existing.legacy_source_sha256 != original_hash
                or validation["canonical_row_digest"] != digest.hexdigest()
            ):
                raise TapeIntegrityError("existing legacy conversion has different lineage")
            report.update(
                {
                    "converted": True,
                    "dry_run": False,
                    "dataset_id": existing.dataset_id,
                    "dataset_name": existing.dataset_name,
                    "dataset_digest": existing.dataset_digest,
                    "segments": len(existing.segments),
                    "output_directory": str(Path(existing.segments[0].path).parent),
                    "original_preserved": sha256_file(resolved) == original_hash,
                    "resumed": True,
                }
            )
            return report
        channel_tuple = tuple(sorted(channels, key=str))
        instrument_tuple = tuple(sorted(instruments))
        name = human_dataset_name(
            trading_date=first_row.receive_ts,
            channels=channel_tuple,
            instrument_ids=instrument_tuple,
            suffix=f"legacy-{original_hash[:8]}",
        )
        request = DatasetRequest(
            consumer="DAT-legacy-conversion",
            purpose="explicit verified legacy conversion",
            trading_date=first_row.receive_ts.date(),
            channels=channel_tuple,
            instrument_ids=instrument_tuple,
            coverage_start=first_row.receive_ts,
            coverage_end=last_row.receive_ts,
            allow_active=False,
        )
        directory = output_root / "legacy" / _scope_name(request) / name
        conversion_lease = _ExclusiveFileLease(directory.parent / f".{dataset_id}.conversion.lock")
        # A concurrent converter may have completed while this process waited for the lease.
        with suppress(DatasetUnavailableError):
            existing = self.handle(dataset_id)
            validation = self.validate(existing)
            if (
                existing.legacy_source_sha256 != original_hash
                or validation["canonical_row_digest"] != digest.hexdigest()
            ):
                raise TapeIntegrityError("concurrent legacy conversion has different lineage")
            report.update(
                {
                    "converted": True,
                    "dry_run": False,
                    "dataset_id": existing.dataset_id,
                    "dataset_name": existing.dataset_name,
                    "dataset_digest": existing.dataset_digest,
                    "segments": len(existing.segments),
                    "output_directory": str(Path(existing.segments[0].path).parent),
                    "original_preserved": sha256_file(resolved) == original_hash,
                    "resumed": True,
                }
            )
            conversion_lease.release()
            return report
        recovery = inventory_recovery(directory, (), quarantine_partials=True)
        resumed_segments = tuple(
            describe_segment(path, segment_number=number)
            for number, path in enumerate(recovery.orphan_files, start=1)
        )
        resumed_rows = sum(segment.rows for segment in resumed_segments)
        if resumed_rows > count:
            raise TapeIntegrityError("legacy conversion recovery has more rows than its source")
        source_prefix = JsonlTapeReader(resolved).rows()
        recovered_prefix = (
            row for segment in resumed_segments for row in iter_parquet_rows(Path(segment.path))
        )
        for recovered in recovered_prefix:
            try:
                original = next(source_prefix)
            except StopIteration as exc:
                raise TapeIntegrityError("legacy conversion recovery exceeds its source") from exc
            if recovered != original:
                raise TapeIntegrityError("legacy conversion recovery differs from source prefix")
        writer = SegmentedParquetWriter(
            directory,
            dataset_id=dataset_id,
            expected_run_id=first_row.run_id,
            max_rows=segment_max_rows,
            existing_segments=resumed_segments,
            resume_directory=directory.exists(),
        )
        for row_index, row in enumerate(JsonlTapeReader(resolved).rows(), start=1):
            if row_index <= resumed_rows:
                continue
            writer.write(row)
        segments = writer.close()
        converted_digest, converted_rows = canonical_row_digest(
            row for segment in segments for row in iter_parquet_rows(Path(segment.path))
        )
        if converted_rows != count or converted_digest != digest.hexdigest():
            raise TapeIntegrityError("legacy conversion semantic equality verification failed")
        if sha256_file(resolved) != original_hash:
            raise TapeIntegrityError("legacy source changed during conversion")
        handle = DatasetHandle(
            schema_version="2.0.0",
            dataset_id=dataset_id,
            acquisition_fingerprint=request.acquisition_fingerprint,
            source="legacy_conversion",
            status=DatasetStatus.COMPLETED,
            trading_date=request.trading_date,
            channels=channel_tuple,
            instrument_ids=instrument_tuple,
            storage_format=StorageFormat.SEGMENTED_PARQUET,
            storage_format_version=STORAGE_FORMAT_VERSION,
            row_schema_version=ROW_SCHEMA_VERSION,
            dataset_name=name,
            row_run_id=first_row.run_id,
            dataset_path=str(directory.resolve()),
            segments=segments,
            dataset_digest=dataset_digest(segments),
            started_at=first_row.receive_ts,
            completed_at=datetime.now(UTC),
            requested_coverage_start=first_row.receive_ts,
            requested_coverage_end=last_row.receive_ts,
            coverage_start=first_row.receive_ts,
            coverage_end=last_row.receive_ts,
            rows=count,
            bytes=sum(segment.bytes for segment in segments),
            legacy_source_sha256=original_hash,
            canonical_row_digest=converted_digest,
        )
        self.catalog.register(handle)
        report.update(
            {
                "converted": True,
                "dry_run": False,
                "dataset_id": dataset_id,
                "dataset_name": name,
                "dataset_digest": handle.dataset_digest,
                "segments": len(segments),
                "output_directory": str(directory),
                "original_preserved": sha256_file(resolved) == original_hash,
                "resumed": bool(resumed_segments or recovery.quarantined_files),
                "quarantined_partials": [str(path) for path in recovery.quarantined_files],
            }
        )
        conversion_lease.release()
        return report

    def recovery_inventory(
        self,
        handle: DatasetHandle,
        *,
        quarantine_partials: bool = False,
    ) -> dict[str, tuple[str, ...]]:
        if handle.storage_format is not StorageFormat.SEGMENTED_PARQUET:
            raise ValueError("recovery inventory applies only to segmented Parquet datasets")
        directory = (
            Path(handle.dataset_path)
            if handle.dataset_path
            else Path(handle.segments[0].path).parent
        )
        inventory = inventory_recovery(
            directory,
            handle.segments,
            quarantine_partials=quarantine_partials,
        )
        return {
            "partial_files": tuple(str(path) for path in inventory.partial_files),
            "orphan_files": tuple(str(path) for path in inventory.orphan_files),
            "quarantined_files": tuple(str(path) for path in inventory.quarantined_files),
        }

    def promote_archive(
        self, handle: DatasetHandle, archive_path: Path | None = None
    ) -> DatasetHandle:
        if handle.storage_format is StorageFormat.SEGMENTED_PARQUET:
            return handle
        if handle.status is DatasetStatus.ACTIVE:
            raise ValueError("active DAT datasets cannot be cold-archived")
        if handle.archive_path is not None:
            return handle
        if handle.tape_path is None:
            raise ValueError("legacy handle has no tape path")
        target = archive_path or Path(handle.tape_path).with_suffix(".jsonl.gz")
        if handle.tape_sha256 and sha256_file(Path(handle.tape_path)) != handle.tape_sha256:
            raise TapeIntegrityError("refusing to archive a tape that differs from its handle")
        archive_hash = archive_tape(Path(handle.tape_path), target)
        updated = DatasetHandle.model_validate(
            handle.model_copy(
                update={"archive_path": str(target.resolve()), "archive_sha256": archive_hash}
            ).model_dump()
        )
        self.catalog.publish(updated)
        return updated
