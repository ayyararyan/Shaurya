"""Atomically published typed operational artifacts for version-2 captures."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from shaurya.contracts.artifacts import sha256_file
from shaurya.contracts.data import OperationalArtifact

JSON_FIELDS_METADATA_KEY = b"shaurya.json_fields"


def _encode_mapping_fields(payload: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Give open-ended mappings/sequences a stable Arrow representation.

    Both are JSON-encoded to a scalar string rather than left as native Arrow
    list/struct columns: PyArrow's Parquet writer renames a list's child field
    from ``item`` to ``element`` on every round trip, which fails this module's
    strict post-write schema-equality check for *any* top-level list field, not
    just nested structs. JSON-encoding sidesteps that entirely, the same way it
    already does for mappings.
    """

    encoded = dict(payload)
    json_fields: list[str] = []
    for field_name, value in payload.items():
        if isinstance(value, dict | list):
            encoded[field_name] = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            json_fields.append(field_name)
    return encoded, tuple(json_fields)


def decode_mapping_fields(
    record: dict[str, Any], metadata: dict[bytes, bytes]
) -> dict[str, Any]:
    """Restore mappings encoded by :class:`ParquetCaptureManifest`."""

    raw_fields = metadata.get(JSON_FIELDS_METADATA_KEY)
    if raw_fields is None:
        return record
    field_names = json.loads(raw_fields)
    if not isinstance(field_names, list) or not all(isinstance(name, str) for name in field_names):
        raise ValueError("operational artifact has invalid JSON-field metadata")
    decoded = dict(record)
    for field_name in field_names:
        value = decoded.get(field_name)
        if not isinstance(value, str):
            raise ValueError(f"operational artifact JSON field is not a string: {field_name}")
        decoded[field_name] = json.loads(value)
    return decoded


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
        encoded_payload, json_fields = _encode_mapping_fields(payload)
        metadata = {
            b"shaurya.artifact_kind": kind.encode(),
            b"shaurya.artifact_schema_version": b"2.0.0",
            b"shaurya.dataset_id": self.run_id.encode(),
        }
        if json_fields:
            metadata[JSON_FIELDS_METADATA_KEY] = json.dumps(json_fields).encode()
        table = pa.Table.from_pylist([encoded_payload]).replace_schema_metadata(metadata)
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
