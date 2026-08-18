"""DAT-05-lite: append-only JSONL persistence for normalized DAT-02 events."""

from __future__ import annotations

import json
import os
from types import TracebackType

from shaurya.contracts.artifacts import ArtifactManifest
from shaurya.contracts.tape import TapeRow


class JsonlTapeWriter:
    """Create exactly one immutable tape file for a run.

    Full deterministic replay remains DAT-05 scope. This writer deliberately provides no
    rewrite/truncate operation and refuses to open an existing tape.
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
