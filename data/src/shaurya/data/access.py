"""DAT-22: the sole catalogue, acquisition claim, storage and retrieval boundary."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from shaurya.contracts.artifacts import ArtifactManifest, RunId, sha256_file
from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetRequest,
    DatasetStatus,
)
from shaurya.contracts.tape import TapeRow

from .tape import (
    CompleteLineJsonlTail,
    IndexedJsonlTapeReader,
    JsonlTapeReader,
    JsonlTapeWriter,
    TapeIndexBuilder,
    TapeIntegrityError,
    archive_tape,
    data_channel_for_row,
)


class DatasetUnavailableError(LookupError):
    """DAT has no active/completed dataset satisfying a consumer request."""


class DatasetAlreadyActiveError(RuntimeError):
    """A compatible DAT acquisition already owns the broker work."""

    def __init__(self, handle: DatasetHandle) -> None:
        super().__init__(f"compatible DAT dataset is already active: {handle.dataset_id}")
        self.handle = handle


class DataCatalog:
    """One append-only, flock-serialised catalogue shared by every Shaurya component."""

    SCHEMA_VERSION = "1.0.0"

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @property
    def claim_lock_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.claim.lock")

    def _append(self, event_type: str, handle: DatasetHandle) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "event_type": event_type,
            "recorded_at": datetime.now(UTC).isoformat(),
            "dataset_id": handle.dataset_id,
            "handle": handle.model_dump(mode="json"),
        }
        encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=True) as target:
                fcntl.flock(target.fileno(), fcntl.LOCK_EX)
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
                fcntl.flock(target.fileno(), fcntl.LOCK_UN)
        except BaseException:
            with suppress(OSError):
                os.close(descriptor)
            raise

    def register(self, handle: DatasetHandle) -> None:
        if handle.dataset_id in self.handles():
            raise ValueError(f"dataset already registered: {handle.dataset_id}")
        self._append("dataset_registered", handle)

    def publish(self, handle: DatasetHandle) -> None:
        if handle.dataset_id not in self.handles():
            raise KeyError(f"dataset is not registered: {handle.dataset_id}")
        self._append("dataset_published", handle)

    def handles(self) -> dict[str, DatasetHandle]:
        if not self.path.exists():
            return {}
        latest: dict[str, DatasetHandle] = {}
        with self.path.open(encoding="utf-8") as source:
            fcntl.flock(source.fileno(), fcntl.LOCK_SH)
            try:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        raise ValueError(f"blank data-catalogue record at line {line_number}")
                    try:
                        loaded: Any = json.loads(line)
                        if not isinstance(loaded, dict):
                            raise TypeError("catalogue event is not an object")
                        if loaded.get("schema_version") != self.SCHEMA_VERSION:
                            raise ValueError("unsupported catalogue schema")
                        raw_handle = loaded["handle"]
                        # Validate through Pydantic's JSON boundary: the contracts are strict,
                        # while persistence serialises enums, tuples and datetimes to JSON.
                        handle = DatasetHandle.model_validate_json(json.dumps(raw_handle))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        raise ValueError(
                            f"invalid data-catalogue record at line {line_number}: "
                            f"{type(exc).__name__}"
                        ) from exc
                    latest[handle.dataset_id] = handle
            finally:
                fcntl.flock(source.fileno(), fcntl.LOCK_UN)
        return latest

    def get(self, dataset_id: str) -> DatasetHandle:
        try:
            return self.handles()[dataset_id]
        except KeyError as exc:
            raise DatasetUnavailableError(f"unknown DAT dataset: {dataset_id}") from exc

    def get_dataset(self, *, trading_date: date) -> DatasetHandle:
        """Return the latest completed dataset published for a trading date."""

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
            if item.satisfies(request)
            and not (
                item.status is DatasetStatus.ACTIVE
                and item.producer_pid is not None
                and not _process_exists(item.producer_pid)
            )
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
        for handle in self.handles().values():
            if (
                handle.status is DatasetStatus.ACTIVE
                and handle.satisfies(request)
                and (handle.producer_pid is None or _process_exists(handle.producer_pid))
            ):
                return handle
        return None


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class DataCaptureSession:
    """DAT-owned append-only capture lifecycle with one cross-process acquisition claim."""

    def __init__(
        self,
        *,
        catalog: DataCatalog,
        request: DatasetRequest,
        manifest: ArtifactManifest,
        writer: JsonlTapeWriter,
        index: TapeIndexBuilder,
        handle: DatasetHandle,
    ) -> None:
        self.catalog = catalog
        self.request = request
        self.manifest = manifest
        self.writer = writer
        self.index = index
        self.handle = handle
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
    ) -> DataCaptureSession:
        catalog.claim_lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_descriptor = os.open(
            catalog.claim_lock_path,
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            with os.fdopen(lock_descriptor, "a+b", closefd=True) as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                existing = catalog.active_satisfying(request)
                if existing is not None:
                    raise DatasetAlreadyActiveError(existing)
                manifest = ArtifactManifest.create(output_root, run_id)
                index = TapeIndexBuilder(stride_rows=index_stride_rows)
                writer = JsonlTapeWriter(
                    manifest,
                    fsync_every=fsync_every,
                    write_observer=index.observe,
                )
                active = DatasetHandle(
                    dataset_id=str(manifest.run_id),
                    acquisition_fingerprint=request.acquisition_fingerprint,
                    source="dhan",
                    status=DatasetStatus.ACTIVE,
                    producer_pid=os.getpid(),
                    trading_date=request.trading_date,
                    channels=request.channels,
                    instrument_ids=request.instrument_ids,
                    tape_path=str(writer.path.resolve()),
                    manifest_path=str(manifest.path.resolve()),
                    started_at=datetime.now(UTC),
                    requested_coverage_start=request.coverage_start,
                    requested_coverage_end=request.coverage_end,
                )
                catalog.register(active)
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except BaseException:
            with suppress(OSError):
                os.close(lock_descriptor)
            raise
        return cls(
            catalog=catalog,
            request=request,
            manifest=manifest,
            writer=writer,
            index=index,
            handle=active,
        )

    @property
    def dataset_id(self) -> str:
        return self.handle.dataset_id

    def write(self, row: TapeRow) -> None:
        if self._closed:
            raise ValueError("cannot write to a closed DAT capture")
        if row.instrument_id not in self.request.instrument_ids:
            raise ValueError("capture row instrument is outside the claimed DAT request")
        if data_channel_for_row(row) not in self.request.channels:
            raise ValueError("capture row channel is outside the claimed DAT request")
        self.writer.write(row)

    def close(
        self,
        *,
        invalidation_reason: str | None = None,
        archive: bool = False,
    ) -> DatasetHandle:
        if self._closed:
            return self.handle
        self._closed = True
        self.writer.close(
            failed_error_type="CaptureInvalidated" if invalidation_reason is not None else None
        )
        now = datetime.now(UTC)
        index_path: Path | None = None
        index_hash: str | None = None
        archive_path: Path | None = None
        archive_hash: str | None = None
        if self.writer.rows_written:
            index_path = self.writer.path.with_suffix(".index.json")
            self.index.write(index_path, self.writer.path)
            self.manifest.register_existing(index_path, kind="market_data_seek_index")
            index_hash = sha256_file(index_path)
            if archive:
                archive_path = self.writer.path.with_suffix(".jsonl.gz")
                archive_hash = archive_tape(self.writer.path, archive_path)
                self.manifest.register_existing(archive_path, kind="market_data_cold_archive")
        status = (
            DatasetStatus.INVALIDATED
            if invalidation_reason is not None
            else DatasetStatus.COMPLETED
        )
        if invalidation_reason is not None:
            self.manifest.invalidate(invalidation_reason)
        else:
            self.manifest.complete(rows=self.writer.rows_written)
        terminal = self.handle.model_copy(
            update={
                "status": status,
                "completed_at": now,
                "coverage_start": self.index.coverage_start,
                "coverage_end": self.index.coverage_end,
                "rows": self.writer.rows_written,
                "bytes": self.writer.path.stat().st_size,
                "tape_sha256": sha256_file(self.writer.path),
                "index_path": str(index_path.resolve()) if index_path is not None else None,
                "index_sha256": index_hash,
                "archive_path": (str(archive_path.resolve()) if archive_path is not None else None),
                "archive_sha256": archive_hash,
                "invalidation_reason": invalidation_reason,
            }
        )
        # Re-validate because ``model_copy`` intentionally skips validation in Pydantic.
        self.handle = DatasetHandle.model_validate(terminal.model_dump())
        self.catalog.publish(self.handle)
        return self.handle

    def __enter__(self) -> DataCaptureSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(invalidation_reason=exc_type.__name__ if exc_type is not None else None)


class DataAccess:
    """The public DAT request/handle/replay-follow facade used by every consumer."""

    def __init__(self, catalog: DataCatalog) -> None:
        self.catalog = catalog

    def request(self, request: DatasetRequest) -> DatasetHandle:
        return self.catalog.resolve(request)

    def handle(self, dataset_id: str) -> DatasetHandle:
        return self.catalog.get(dataset_id)

    def rows(
        self,
        handle: DatasetHandle,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: tuple[DataChannel, ...] | None = None,
        instrument_ids: tuple[str, ...] | None = None,
    ) -> Iterator[TapeRow]:
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
            if (
                handle.archive_sha256 is not None
                and sha256_file(source_path) != handle.archive_sha256
            ):
                raise TapeIntegrityError("DAT archive hash differs from its published handle")
        if start is not None or end is not None or channels or instrument_ids:
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
            return
        yield from JsonlTapeReader(source_path).rows()

    def follow(self, handle: DatasetHandle) -> CompleteLineJsonlTail:
        if handle.status is DatasetStatus.INVALIDATED:
            raise ValueError("cannot follow an invalidated DAT dataset")
        return CompleteLineJsonlTail(Path(handle.tape_path))

    def adopt_legacy_tape(
        self,
        tape_path: Path,
        *,
        consumer: str,
        purpose: str,
    ) -> DatasetHandle:
        resolved = tape_path.resolve()
        tape_hash = sha256_file(resolved)
        dataset_id = f"legacy-{tape_hash[:16]}"
        with suppress(DatasetUnavailableError):
            return self.catalog.get(dataset_id)
        index = TapeIndexBuilder()
        channels_seen: set[DataChannel] = set()
        instruments_seen: set[str] = set()
        row_count = 0
        offset = 0
        rows = JsonlTapeReader(resolved).rows()
        with resolved.open("rb") as source:
            for row, encoded in zip(rows, source, strict=True):
                index.observe(row, offset, len(encoded))
                offset += len(encoded)
                row_count += 1
                channels_seen.add(data_channel_for_row(row))
                instruments_seen.add(row.instrument_id)
        if row_count == 0 or index.coverage_start is None or index.coverage_end is None:
            raise ValueError("cannot adopt an empty legacy tape")
        channels = tuple(sorted(channels_seen, key=str))
        instruments = tuple(sorted(instruments_seen))
        trading_date = index.coverage_start.date()
        request = DatasetRequest(
            consumer=consumer,
            purpose=purpose,
            trading_date=trading_date,
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
            # Existing legacy sidecars are trusted only after their tape hash and schema bind.
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
            tape_path=str(resolved),
            index_path=str(index_path.resolve()),
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
        """Register an already-running pre-DAT writer without pretending its tape is immutable.

        D43 moved every consumer behind DAT after the 2026-08-21 OFI collector had already
        opened its append-only tape.  Hashing that growing file and registering it as completed
        would freeze a false identity.  This migration bridge instead validates every complete
        row currently present, ignores only the torn trailing row owned by the writer, and emits
        an ACTIVE handle with no terminal tape hash or seek index.
        """

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
        with suppress(DatasetUnavailableError):
            existing = self.catalog.get(dataset_id)
            if Path(existing.tape_path) != resolved:
                raise ValueError("active legacy dataset ID resolved to a different tape")
            return existing

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
            trading_date=request.trading_date,
            channels=request.channels,
            instrument_ids=request.instrument_ids,
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

    def promote_archive(
        self, handle: DatasetHandle, archive_path: Path | None = None
    ) -> DatasetHandle:
        if handle.status is DatasetStatus.ACTIVE:
            raise ValueError("active DAT datasets cannot be cold-archived")
        if handle.archive_path is not None:
            return handle
        target = archive_path or Path(handle.tape_path).with_suffix(".jsonl.gz")
        if (
            handle.tape_sha256 is not None
            and sha256_file(Path(handle.tape_path)) != handle.tape_sha256
        ):
            raise TapeIntegrityError("refusing to archive a tape that differs from its handle")
        archive_hash = archive_tape(Path(handle.tape_path), target)
        updated = DatasetHandle.model_validate(
            handle.model_copy(
                update={
                    "archive_path": str(target.resolve()),
                    "archive_sha256": archive_hash,
                }
            ).model_dump()
        )
        self.catalog.publish(updated)
        return updated
