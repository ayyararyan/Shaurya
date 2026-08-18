"""DAT-05: append-only persistence and deterministic replay of canonical tape rows."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

from shaurya.contracts.artifacts import ArtifactManifest
from shaurya.contracts.tape import TapeRow


class JsonlTapeWriter:
    """Create exactly one immutable tape file for a run.

    The writer deliberately provides no rewrite/truncate/delete operation and refuses to open
    an existing tape. Raw-tape retention is permanent under D12.
    """

    def __init__(self, manifest: ArtifactManifest, *, fsync_every: int = 100) -> None:
        if fsync_every < 1:
            raise ValueError("fsync_every must be positive")
        self.manifest = manifest
        self.path = manifest.run_dir / f"tape_{manifest.run_id}.jsonl"
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._handle = os.fdopen(descriptor, "wb")
        self._fsync_every = fsync_every
        self.rows_written = 0
        self._closed = False
        self.manifest.artifact_opened(self.path, kind="market_data_tape")

    def write(self, row: TapeRow) -> None:
        if self._closed:
            raise ValueError("cannot write to a closed tape")
        if row.run_id != str(self.manifest.run_id):
            raise ValueError("tape row run_id does not match manifest run_id")
        payload = json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":"))
        self._handle.write((payload + "\n").encode())
        self.rows_written += 1
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
        with self.path.open(encoding="utf-8") as handle:
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
