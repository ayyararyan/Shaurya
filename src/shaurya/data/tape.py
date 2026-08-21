"""DAT-05: append-only persistence and deterministic replay of canonical tape rows."""

from __future__ import annotations

import gzip
import json
import os
import shutil
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from shaurya.contracts.artifacts import ArtifactManifest, sha256_file
from shaurya.contracts.data import DataChannel
from shaurya.contracts.tape import TapeRow


class JsonlTapeWriter:
    """Create exactly one immutable tape file for a run.

    The writer deliberately provides no rewrite/truncate/delete operation and refuses to open
    an existing tape. Raw-tape retention is permanent under D12.
    """

    def __init__(
        self,
        manifest: ArtifactManifest,
        *,
        fsync_every: int = 100,
        write_observer: Callable[[TapeRow, int, int], None] | None = None,
    ) -> None:
        if fsync_every < 1:
            raise ValueError("fsync_every must be positive")
        self.manifest = manifest
        self.path = manifest.run_dir / f"tape_{manifest.run_id}.jsonl"
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._handle = os.fdopen(descriptor, "wb")
        self._fsync_every = fsync_every
        self.rows_written = 0
        self._closed = False
        self._write_observer = write_observer
        self.manifest.artifact_opened(self.path, kind="market_data_tape")

    def write(self, row: TapeRow) -> None:
        if self._closed:
            raise ValueError("cannot write to a closed tape")
        if row.run_id != str(self.manifest.run_id):
            raise ValueError("tape row run_id does not match manifest run_id")
        payload = json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":"))
        encoded = (payload + "\n").encode()
        byte_offset = self._handle.tell()
        self._handle.write(encoded)
        self.rows_written += 1
        if self._write_observer is not None:
            self._write_observer(row, byte_offset, len(encoded))
        if self.rows_written % self._fsync_every == 0:
            self._handle.flush()
            os.fsync(self._handle.fileno())

    def close(self, *, failed_error_type: str | None = None) -> None:
        if self._closed:
            return
        try:
            self._handle.flush()
            os.fsync(self._handle.fileno())
        finally:
            self._handle.close()
            self._closed = True
        if failed_error_type:
            self.manifest.artifact_failed(
                self.path,
                kind="market_data_tape",
                error_type=failed_error_type,
            )
        else:
            self.manifest.artifact_closed(
                self.path,
                kind="market_data_tape",
                rows=self.rows_written,
            )

    def __enter__(self) -> JsonlTapeWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(failed_error_type=exc_type.__name__ if exc_type else None)


class TapeIntegrityError(ValueError):
    """A canonical tape cannot be replayed without changing its recorded semantics."""


@contextmanager
def _open_text_tape(path: Path) -> Iterator[TextIO]:
    if path.suffix == ".gz":
        with gzip.open(path, mode="rt", encoding="utf-8") as handle:
            yield handle
        return
    with path.open(encoding="utf-8") as handle:
        yield handle


class JsonlTapeReader:
    """Validate and replay one immutable canonical JSONL tape in recorded receive order."""

    def __init__(
        self,
        path: Path,
        *,
        expected_run_id: str | None = None,
        require_contiguous_sequence: bool = True,
    ) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        self.path = path
        self.expected_run_id = expected_run_id
        self.require_contiguous_sequence = require_contiguous_sequence

    def rows(self) -> Iterator[TapeRow]:
        observed_run_id = self.expected_run_id
        prior_sequence: int | None = None
        with _open_text_tape(self.path) as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise TapeIntegrityError(f"blank tape row at line {line_number}")
                try:
                    payload: Any = json.loads(line)
                    if not isinstance(payload, dict):
                        raise TypeError("row is not an object")
                    row = TapeRow.from_dict(payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise TapeIntegrityError(
                        f"invalid canonical tape row at line {line_number}: {type(exc).__name__}"
                    ) from exc
                if observed_run_id is None:
                    observed_run_id = row.run_id
                if row.run_id != observed_run_id:
                    raise TapeIntegrityError(
                        f"run_id changed at line {line_number}: {row.run_id!r}"
                    )
                if prior_sequence is not None:
                    if row.receive_sequence <= prior_sequence:
                        raise TapeIntegrityError(
                            f"receive sequence is not strictly increasing at line {line_number}"
                        )
                    contiguous = row.receive_sequence == prior_sequence + 1
                    if self.require_contiguous_sequence and not contiguous:
                        raise TapeIntegrityError(
                            f"receive sequence gap before line {line_number}: "
                            f"{prior_sequence} -> {row.receive_sequence}"
                        )
                prior_sequence = row.receive_sequence
                yield row

    def replay(self, consumer: Callable[[TapeRow], None]) -> int:
        """Deliver each validated row exactly once and return the delivered row count."""

        count = 0
        for row in self.rows():
            consumer(row)
            count += 1
        return count


def data_channel_for_row(row: TapeRow) -> DataChannel:
    if row.event_type == "depth20":
        return DataChannel.DEPTH20
    if row.event_type == "depth200":
        return DataChannel.DEPTH200
    return DataChannel.STANDARD


@dataclass(frozen=True, slots=True)
class TapeIndexCheckpoint:
    row_number: int
    byte_offset: int
    receive_sequence: int
    receive_ts: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "row_number": self.row_number,
            "byte_offset": self.byte_offset,
            "receive_sequence": self.receive_sequence,
            "receive_ts": self.receive_ts,
        }


class TapeIndexBuilder:
    """Build a small chronological seek index while the append-only tape is written."""

    SCHEMA_VERSION = "1.0.0"

    def __init__(self, *, stride_rows: int = 1_000) -> None:
        if stride_rows < 1:
            raise ValueError("index stride_rows must be positive")
        self.stride_rows = stride_rows
        self.rows = 0
        self.bytes = 0
        self.coverage_start: datetime | None = None
        self.coverage_end: datetime | None = None
        self.receive_time_monotone = True
        self._prior_stamp: datetime | None = None
        self.checkpoints: list[TapeIndexCheckpoint] = []
        self.channel_rows: Counter[str] = Counter()
        self.instrument_rows: Counter[str] = Counter()

    def observe(self, row: TapeRow, byte_offset: int, encoded_bytes: int) -> None:
        if byte_offset < 0 or encoded_bytes < 1:
            raise ValueError("invalid tape index byte accounting")
        self.rows += 1
        self.bytes += encoded_bytes
        stamp = row.receive_ts
        if self.coverage_start is None or stamp < self.coverage_start:
            self.coverage_start = stamp
        if self.coverage_end is None or stamp > self.coverage_end:
            self.coverage_end = stamp
        if self._prior_stamp is not None and stamp < self._prior_stamp:
            self.receive_time_monotone = False
        self._prior_stamp = stamp
        self.channel_rows[str(data_channel_for_row(row))] += 1
        self.instrument_rows[row.instrument_id] += 1
        if self.rows == 1 or (self.rows - 1) % self.stride_rows == 0:
            self.checkpoints.append(
                TapeIndexCheckpoint(
                    row_number=self.rows,
                    byte_offset=byte_offset,
                    receive_sequence=row.receive_sequence,
                    receive_ts=stamp.isoformat(),
                )
            )

    def write(self, path: Path, tape_path: Path) -> None:
        if self.rows < 1 or self.coverage_start is None or self.coverage_end is None:
            raise ValueError("cannot write an index for an empty tape")
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "tape_name": tape_path.name,
            "tape_sha256": sha256_file(tape_path),
            "rows": self.rows,
            "bytes": tape_path.stat().st_size,
            "stride_rows": self.stride_rows,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "receive_time_monotone": self.receive_time_monotone,
            "channel_rows": dict(sorted(self.channel_rows.items())),
            "instrument_rows": dict(sorted(self.instrument_rows.items())),
            "checkpoints": [item.to_dict() for item in self.checkpoints],
        }
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write((json.dumps(payload, sort_keys=True, indent=2) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())


class IndexedJsonlTapeReader:
    """Validated bounded retrieval by time, channel and canonical instrument."""

    def __init__(self, tape_path: Path, index_path: Path) -> None:
        if tape_path.suffix == ".gz":
            raise ValueError("seek indexes require the warm uncompressed JSONL tape")
        if not tape_path.is_file() or not index_path.is_file():
            missing = tape_path if not tape_path.is_file() else index_path
            raise FileNotFoundError(missing)
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or loaded.get("schema_version") != "1.0.0":
            raise TapeIntegrityError("unsupported or malformed tape index")
        if loaded.get("tape_name") != tape_path.name:
            raise TapeIntegrityError("tape index names a different tape")
        if loaded.get("tape_sha256") != sha256_file(tape_path):
            raise TapeIntegrityError("tape hash no longer matches its seek index")
        raw_checkpoints = loaded.get("checkpoints")
        if not isinstance(raw_checkpoints, list) or not raw_checkpoints:
            raise TapeIntegrityError("tape index has no checkpoints")
        self.tape_path = tape_path
        self.index_path = index_path
        self.receive_time_monotone = bool(loaded.get("receive_time_monotone"))
        self.checkpoints = tuple(
            TapeIndexCheckpoint(
                row_number=int(value["row_number"]),
                byte_offset=int(value["byte_offset"]),
                receive_sequence=int(value["receive_sequence"]),
                receive_ts=str(value["receive_ts"]),
            )
            for value in raw_checkpoints
            if isinstance(value, dict)
        )

    def _start_offset(self, start: datetime | None) -> int:
        if start is None or not self.receive_time_monotone:
            return 0
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        stamps = [datetime.fromisoformat(item.receive_ts) for item in self.checkpoints]
        position = max(0, bisect_right(stamps, start) - 1)
        return self.checkpoints[position].byte_offset

    def rows(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        channels: tuple[DataChannel, ...] | None = None,
        instrument_ids: tuple[str, ...] | None = None,
    ) -> Iterator[TapeRow]:
        if end is not None and end.tzinfo is None:
            raise ValueError("end must be timezone-aware")
        if start is not None and end is not None and end < start:
            raise ValueError("end cannot precede start")
        wanted_channels = set(channels or ())
        wanted_instruments = set(instrument_ids or ())
        with self.tape_path.open("rb") as handle:
            handle.seek(self._start_offset(start))
            for line in handle:
                try:
                    loaded: Any = json.loads(line)
                    if not isinstance(loaded, dict):
                        raise TypeError("row is not an object")
                    row = TapeRow.from_dict(loaded)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise TapeIntegrityError(
                        f"invalid indexed tape row: {type(exc).__name__}"
                    ) from exc
                if start is not None and row.receive_ts < start:
                    continue
                if end is not None and row.receive_ts > end:
                    if self.receive_time_monotone:
                        break
                    continue
                if wanted_channels and data_channel_for_row(row) not in wanted_channels:
                    continue
                if wanted_instruments and row.instrument_id not in wanted_instruments:
                    continue
                yield row


@dataclass(frozen=True, slots=True)
class ParsedBatch:
    rows: tuple[dict[str, Any], ...]
    bytes_read: int
    complete_lines: int


class CompleteLineJsonlTail:
    """DAT-owned complete-line reader for a growing warm tape."""

    def __init__(self, path: Path, *, chunk_size: int = 1 << 20) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if not path.is_file():
            raise FileNotFoundError(path)
        self.path = path
        self.chunk_size = chunk_size
        self.offset = 0
        self._buffer = b""
        self._partial_counted = False
        self.rows_parsed = 0
        self.malformed_lines = 0
        self.torn_lines = 0

    @property
    def trailing_partial_bytes(self) -> int:
        return len(self._buffer)

    def poll(self, *, max_bytes: int | None = None) -> ParsedBatch:
        size = self.path.stat().st_size
        if size < self.offset:
            raise RuntimeError("followed tape was truncated; refusing to reinterpret it")
        available = size - self.offset
        if max_bytes is not None:
            available = min(available, max_bytes)
        if available <= 0:
            return ParsedBatch((), 0, 0)
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            payload = handle.read(min(available, self.chunk_size))
        self.offset += len(payload)
        prior_partial_was_counted = self._partial_counted
        combined = self._buffer + payload
        pieces = combined.split(b"\n")
        self._buffer = pieces.pop()
        rows: list[dict[str, Any]] = []
        for raw in pieces:
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise TypeError("JSONL row is not an object")
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                self.malformed_lines += 1
                continue
            rows.append(value)
            self.rows_parsed += 1
        if prior_partial_was_counted and pieces:
            self._partial_counted = False
        reached_current_eof = self.offset == size
        if self._buffer and reached_current_eof and not self._partial_counted:
            self.torn_lines += 1
            self._partial_counted = True
        if not self._buffer:
            self._partial_counted = False
        return ParsedBatch(tuple(rows), len(payload), len(pieces))

    def drain_available(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        while self.offset < self.path.stat().st_size:
            batch = self.poll()
            rows.extend(batch.rows)
            if batch.bytes_read == 0:
                break
        return tuple(rows)


def archive_tape(tape_path: Path, archive_path: Path, *, compresslevel: int = 6) -> str:
    """Create a lossless cold gzip copy without deleting or rewriting the warm tape."""

    if not tape_path.is_file():
        raise FileNotFoundError(tape_path)
    if not 0 <= compresslevel <= 9:
        raise ValueError("gzip compresslevel must be between 0 and 9")
    archive_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tape_path.open("rb") as source, gzip.open(
        archive_path, mode="xb", compresslevel=compresslevel
    ) as target:
        shutil.copyfileobj(source, target, length=1 << 20)
    os.chmod(archive_path, 0o600)
    with gzip.open(archive_path, mode="rb") as restored:
        # Read the full archive once: gzip CRC plus a content hash guards lossless promotion.
        import hashlib

        digest = hashlib.sha256()
        for chunk in iter(lambda: restored.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256_file(tape_path):
        raise TapeIntegrityError("lossless archive verification failed")
    return sha256_file(archive_path)
