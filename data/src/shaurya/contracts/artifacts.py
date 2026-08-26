"""CON-08: run IDs and append-only artifact manifests."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunId:
    value: str

    PATTERN = re.compile(r"^sha-(\d{8}T\d{6}\.\d{6}Z)-([0-9a-f]{8})$")

    def __post_init__(self) -> None:
        if not self.PATTERN.fullmatch(self.value):
            raise ValueError(f"invalid Shaurya run ID: {self.value!r}")

    @classmethod
    def new(cls, now: datetime | None = None) -> RunId:
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("run-ID timestamp must be timezone-aware")
        stamp = instant.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        return cls(f"sha-{stamp}-{secrets.token_hex(4)}")

    def __str__(self) -> str:
        return self.value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactManifest:
    """One append-only JSONL manifest inside a unique run directory."""

    SCHEMA_VERSION = "1.0.0"

    def __init__(self, run_dir: Path, run_id: RunId, *, create: bool) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.path = run_dir / f"manifest_{run_id}.jsonl"
        self._sequence = 0
        if create:
            run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            self._append(
                "run_started",
                status="active",
                started_at=datetime.now(UTC).isoformat(),
            )
        else:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            with self.path.open(encoding="utf-8") as handle:
                self._sequence = sum(1 for line in handle if line.strip())

    @classmethod
    def create(cls, root: Path, run_id: RunId | None = None) -> ArtifactManifest:
        resolved = run_id or RunId.new()
        return cls(root / str(resolved), resolved, create=True)

    @classmethod
    def open_existing(cls, run_dir: Path, run_id: RunId) -> ArtifactManifest:
        return cls(run_dir, run_id, create=False)

    def _append(self, event_type: str, **payload: Any) -> None:
        self._sequence += 1
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": str(self.run_id),
            "manifest_sequence": self._sequence,
            "recorded_at": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            **payload,
        }
        encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=True) as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except BaseException:
            # fdopen owns the descriptor after it succeeds; close only if ownership was not taken.
            with suppress(OSError):
                os.close(descriptor)
            raise

    def artifact_opened(self, path: Path, *, kind: str) -> None:
        self._append("artifact_opened", artifact=path.name, kind=kind)

    def artifact_closed(self, path: Path, *, kind: str, rows: int) -> None:
        self._append(
            "artifact_closed",
            artifact=path.name,
            kind=kind,
            rows=rows,
            bytes=path.stat().st_size,
            sha256=sha256_file(path),
        )

    def artifact_failed(self, path: Path, *, kind: str, error_type: str) -> None:
        self._append(
            "artifact_failed",
            artifact=path.name,
            kind=kind,
            error_type=error_type,
        )

    def register_existing(self, path: Path, *, kind: str, rows: int = 1) -> None:
        if path.parent != self.run_dir or not path.is_file():
            raise ValueError("registered artifact must be a file in this run directory")
        self.artifact_closed(path, kind=kind, rows=rows)

    def complete(self, **summary: Any) -> None:
        self._append("run_completed", status="completed", **summary)

    def invalidate(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("invalidation reason is required")
        self._append("run_invalidated", status="invalidated", reason=reason.strip())
