"""Atomically published typed operational artifacts for version-2 captures."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from shaurya.contracts.artifacts import sha256_file
from shaurya.contracts.data import OperationalArtifact


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


class ParquetCaptureManifest:
    """Small compatibility facade whose durable history is the Data catalogue.

    Version-2 lifecycle events live in the immutable catalogue. Capture-specific metrics and
    quality records are separate typed Parquet artifacts under the catalogue's operational lane.
    """

    def __init__(self, directory: Path, *, run_id: str) -> None:
        self.run_dir = directory.resolve()
        self.run_id = run_id
        self.path = self.run_dir
        self._artifacts: list[OperationalArtifact] = []
        self.run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    def write_record(self, kind: str, payload: dict[str, Any]) -> Path:
        if re.fullmatch(r"[a-z][a-z0-9_]*", kind) is None:
            raise ValueError("operational artifact kind must be a safe lowercase identifier")
        safe_kind = kind.replace("_", "-")
        target = self.run_dir / f"{safe_kind}.parquet"
        partial = self.run_dir / f"{target.name}.partial-{uuid.uuid4().hex}"
        if target.exists():
            raise FileExistsError(target)
        table = pa.Table.from_pylist([payload]).replace_schema_metadata(
            {
                b"shaurya.artifact_kind": kind.encode(),
                b"shaurya.artifact_schema_version": b"2.0.0",
                b"shaurya.dataset_id": self.run_id.encode(),
            }
        )
        pq.write_table(table, partial, compression="zstd", version="2.6")
        written = pq.read_table(partial)
        if written.num_rows != 1 or not written.schema.equals(table.schema, check_metadata=True):
            raise ValueError(f"operational artifact failed Parquet validation: {kind}")
        with partial.open("rb") as source:
            os.fsync(source.fileno())
        os.chmod(partial, 0o600)
        os.rename(partial, target)
        _fsync_directory(self.run_dir)
        self._artifacts.append(
            OperationalArtifact(
                kind=kind,
                path=str(target),
                bytes=target.stat().st_size,
                sha256=sha256_file(target),
            )
        )
        return target

    @property
    def artifacts(self) -> tuple[OperationalArtifact, ...]:
        return tuple(self._artifacts)

    def register_existing(self, path: Path, *, kind: str, rows: int = 1) -> None:
        del rows
        if path.parent != self.run_dir or not path.is_file():
            raise ValueError(
                "registered artifact must be a file in this capture metadata directory"
            )
        if path.suffix != ".parquet":
            raise ValueError(f"version-2 operational artifact must be Parquet: {kind}")

    def complete(self, **summary: Any) -> None:
        del summary

    def invalidate(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("invalidation reason is required")
