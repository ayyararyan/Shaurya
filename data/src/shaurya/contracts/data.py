"""CON-10: broker-neutral dataset requests and DAT-owned dataset handles."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from .base import ContractModel


class DataChannel(StrEnum):
    """Canonical acquisition channels exposed by DAT, never broker packet codes."""

    STANDARD = "standard"
    DEPTH20 = "depth20"
    DEPTH200 = "depth200"
    HISTORICAL = "historical"


class DatasetStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INVALIDATED = "invalidated"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"


class StorageFormat(StrEnum):
    LEGACY_JSONL = "legacy_jsonl"
    SEGMENTED_PARQUET = "segmented_parquet"


def _non_empty(value: str, name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


class DatasetRequest(ContractModel):
    """What a consumer needs from DAT.

    ``consumer`` and ``purpose`` are audit fields, not acquisition identity.  Therefore SUR and
    SIG requests for the same channels/instruments/coverage share one raw dataset under D43.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    consumer: str
    purpose: str
    trading_date: date
    channels: tuple[DataChannel, ...]
    instrument_ids: tuple[str, ...]
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    allow_active: bool = True

    @field_validator("consumer", "purpose")
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _non_empty(value, str(field_name))

    @field_validator("channels")
    @classmethod
    def _channels(cls, value: tuple[DataChannel, ...]) -> tuple[DataChannel, ...]:
        if not value:
            raise ValueError("at least one data channel is required")
        return tuple(sorted(set(value), key=str))

    @field_validator("instrument_ids")
    @classmethod
    def _instruments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(sorted({_non_empty(item, "instrument_id") for item in value}))
        if not cleaned:
            raise ValueError("at least one canonical instrument ID is required")
        return cleaned

    @model_validator(mode="after")
    def _coverage(self) -> Self:
        for name, stamp in (
            ("coverage_start", self.coverage_start),
            ("coverage_end", self.coverage_end),
        ):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_end <= self.coverage_start
        ):
            raise ValueError("coverage_end must be later than coverage_start")
        return self

    @property
    def acquisition_fingerprint(self) -> str:
        """Stable identity for broker work, deliberately excluding consumer/purpose."""

        identity = {
            "schema_version": self.schema_version,
            "trading_date": self.trading_date.isoformat(),
            "channels": [str(item) for item in self.channels],
            "instrument_ids": list(self.instrument_ids),
            "coverage_start": (
                self.coverage_start.isoformat() if self.coverage_start is not None else None
            ),
            "coverage_end": (
                self.coverage_end.isoformat() if self.coverage_end is not None else None
            ),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class DatasetSegment(ContractModel):
    """One closed, immutable, catalogue-published Parquet segment."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    segment_number: int
    path: str
    rows: int
    bytes: int
    sha256: str
    first_receive_sequence: int
    last_receive_sequence: int
    coverage_start: datetime
    coverage_end: datetime
    channels: tuple[DataChannel, ...]
    instrument_ids: tuple[str, ...]
    row_groups: int
    storage_format_version: Literal["2.0.0"] = "2.0.0"
    row_schema_version: str = "2.0.0"

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _non_empty(value, "segment path")

    @field_validator("sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("segment sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("channels")
    @classmethod
    def _segment_channels(cls, value: tuple[DataChannel, ...]) -> tuple[DataChannel, ...]:
        if not value:
            raise ValueError("segment requires channel coverage")
        return tuple(sorted(set(value), key=str))

    @field_validator("instrument_ids")
    @classmethod
    def _segment_instruments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(sorted({_non_empty(item, "instrument_id") for item in value}))
        if not cleaned:
            raise ValueError("segment requires instrument coverage")
        return cleaned

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        if self.segment_number < 1 or self.rows < 1 or self.bytes < 1 or self.row_groups < 1:
            raise ValueError("segment numbers and counts must be positive")
        if self.first_receive_sequence < 1:
            raise ValueError("segment first receive sequence must be positive")
        expected_last = self.first_receive_sequence + self.rows - 1
        if self.last_receive_sequence != expected_last:
            raise ValueError("segment receive sequence bounds are not contiguous with row count")
        if self.coverage_start.tzinfo is None or self.coverage_end.tzinfo is None:
            raise ValueError("segment coverage timestamps must be timezone-aware")
        if self.coverage_end < self.coverage_start:
            raise ValueError("segment coverage end cannot precede start")
        if not self.row_schema_version.startswith("2."):
            raise ValueError("segment row schema major version is unsupported")
        return self


class OperationalArtifact(ContractModel):
    """One immutable Data-owned operational metadata record."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: str
    path: str
    bytes: int
    sha256: str

    @field_validator("kind", "path")
    @classmethod
    def _required(cls, value: str, info: object) -> str:
        return _non_empty(value, str(getattr(info, "field_name", "value")))

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("operational artifact sha256 must be lowercase hexadecimal")
        return value

    @field_validator("bytes")
    @classmethod
    def _bytes(cls, value: int) -> int:
        if value < 1:
            raise ValueError("operational artifact bytes must be positive")
        return value


class DatasetHandle(ContractModel):
    """Immutable snapshot of one DAT dataset's identity, lifecycle and storage provenance."""

    schema_version: Literal["1.0.0", "2.0.0"] = "1.0.0"
    dataset_id: str
    acquisition_fingerprint: str
    producer: Literal["DAT"] = "DAT"
    source: Literal["dhan", "legacy_tape", "legacy_conversion"]
    status: DatasetStatus
    producer_pid: int | None = None
    producer_host: str | None = None
    trading_date: date
    channels: tuple[DataChannel, ...]
    instrument_ids: tuple[str, ...]
    storage_format: StorageFormat | None = None
    storage_format_version: str | None = None
    row_schema_version: str | None = None
    dataset_name: str | None = None
    row_run_id: str | None = None
    dataset_path: str | None = None
    segments: tuple[DatasetSegment, ...] = ()
    operational_artifacts: tuple[OperationalArtifact, ...] = ()
    dataset_digest: str | None = None
    tape_path: str | None = None
    manifest_path: str | None = None
    index_path: str | None = None
    archive_path: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    requested_coverage_start: datetime | None = None
    requested_coverage_end: datetime | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    rows: int = 0
    bytes: int = 0
    tape_sha256: str | None = None
    index_sha256: str | None = None
    archive_sha256: str | None = None
    invalidation_reason: str | None = None
    legacy_source_sha256: str | None = None
    canonical_row_digest: str | None = None

    @field_validator("dataset_id", "acquisition_fingerprint")
    @classmethod
    def _handle_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        cleaned = _non_empty(value, str(field_name))
        if field_name == "dataset_id" and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", cleaned
        ):
            raise ValueError("dataset_id must be a safe filesystem component")
        return cleaned

    @field_validator("channels")
    @classmethod
    def _handle_channels(cls, value: tuple[DataChannel, ...]) -> tuple[DataChannel, ...]:
        if not value:
            raise ValueError("dataset handle requires channels")
        return tuple(sorted(set(value), key=str))

    @field_validator("instrument_ids")
    @classmethod
    def _handle_instruments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(sorted({_non_empty(item, "instrument_id") for item in value}))
        if not cleaned:
            raise ValueError("dataset handle requires instruments")
        return cleaned

    @model_validator(mode="after")
    def _lifecycle(self) -> Self:
        stamps = (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
            ("requested_coverage_start", self.requested_coverage_start),
            ("requested_coverage_end", self.requested_coverage_end),
            ("coverage_start", self.coverage_start),
            ("coverage_end", self.coverage_end),
        )
        for name, stamp in stamps:
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.rows < 0 or self.bytes < 0:
            raise ValueError("dataset rows and bytes must be non-negative")
        if self.producer_pid is not None and self.producer_pid < 1:
            raise ValueError("producer_pid must be positive")
        if self.producer_host is not None and not self.producer_host.strip():
            raise ValueError("producer_host cannot be blank")
        if self.coverage_start and self.coverage_end and self.coverage_end < self.coverage_start:
            raise ValueError("dataset coverage_end cannot precede coverage_start")
        if self.status is DatasetStatus.ACTIVE and self.completed_at is not None:
            raise ValueError("active dataset cannot have completed_at")
        if self.status is DatasetStatus.ACTIVE and self.producer_pid is None:
            raise ValueError("active dataset requires a producer_pid")
        if self.status is not DatasetStatus.ACTIVE and self.completed_at is None:
            raise ValueError("terminal dataset status requires completed_at")
        reasoned = {
            DatasetStatus.INVALIDATED,
            DatasetStatus.FAILED,
            DatasetStatus.CANCELLED,
            DatasetStatus.ORPHANED,
        }
        if self.status in reasoned and not self.invalidation_reason:
            raise ValueError(f"{self.status} dataset requires a reason")
        if self.status not in reasoned and self.invalidation_reason is not None:
            raise ValueError("only non-success terminal datasets carry an invalidation reason")
        if self.schema_version == "1.0.0":
            if not self.tape_path:
                raise ValueError("version-1 dataset handle requires tape_path")
            if self.storage_format not in {None, StorageFormat.LEGACY_JSONL}:
                raise ValueError("version-1 dataset cannot be reinterpreted as non-JSONL")
            return self
        kinds = [artifact.kind for artifact in self.operational_artifacts]
        if len(kinds) != len(set(kinds)):
            raise ValueError("version-2 operational artifact kinds must be unique")
        if self.storage_format is not StorageFormat.SEGMENTED_PARQUET:
            raise ValueError("version-2 dataset requires segmented_parquet storage")
        if self.storage_format_version != "2.0.0" or not (
            self.row_schema_version and self.row_schema_version.startswith("2.")
        ):
            raise ValueError("version-2 dataset has unsupported storage or row schema")
        if not self.dataset_name or not self.dataset_name.strip():
            raise ValueError("version-2 dataset requires a human-readable dataset name")
        if not self.dataset_path or not self.dataset_path.strip():
            raise ValueError("version-2 dataset requires its storage directory")
        if not self.row_run_id or not self.row_run_id.strip():
            raise ValueError("version-2 dataset requires the logical row run ID")
        if (
            self.tape_path is not None
            or self.index_path is not None
            or self.tape_sha256 is not None
        ):
            raise ValueError("version-2 dataset cannot carry legacy single-tape fields")
        numbers = tuple(segment.segment_number for segment in self.segments)
        if numbers != tuple(range(1, len(numbers) + 1)):
            raise ValueError("version-2 segments must be ordered and contiguous from one")
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if current.first_receive_sequence != previous.last_receive_sequence + 1:
                raise ValueError("receive sequence is not contiguous across segments")
        if self.status is DatasetStatus.COMPLETED:
            if not self.segments or not self.dataset_digest:
                raise ValueError("completed version-2 dataset requires segments and digest")
            if self.rows != sum(segment.rows for segment in self.segments):
                raise ValueError("dataset row count differs from ordered segments")
            if self.bytes != sum(segment.bytes for segment in self.segments):
                raise ValueError("dataset byte count differs from ordered segments")
        if self.dataset_digest is not None and (
            len(self.dataset_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.dataset_digest)
        ):
            raise ValueError("dataset digest must be 64 lowercase hexadecimal characters")
        return self

    def satisfies(self, request: DatasetRequest) -> bool:
        """Whether this handle safely covers a consumer request without another acquisition."""

        if self.status not in {DatasetStatus.ACTIVE, DatasetStatus.COMPLETED}:
            return False
        if self.status is DatasetStatus.ACTIVE and not request.allow_active:
            return False
        if self.trading_date != request.trading_date:
            return False
        if not set(request.channels).issubset(self.channels):
            return False
        if not set(request.instrument_ids).issubset(self.instrument_ids):
            return False
        if request.coverage_start is not None:
            # Aggregate dataset bounds do not prove per-slice coverage. Until the
            # catalogue carries per-channel/instrument bounds, only a single exact
            # slice may satisfy a bounded request.
            if (
                len(self.channels) != 1
                or len(self.instrument_ids) != 1
                or self.channels != request.channels
                or self.instrument_ids != request.instrument_ids
            ):
                return False
            available_start = (
                self.coverage_start
                if self.status is DatasetStatus.COMPLETED
                else self.requested_coverage_start
            )
            if available_start is None or available_start > request.coverage_start:
                return False
        if request.coverage_end is not None:
            if (
                len(self.channels) != 1
                or len(self.instrument_ids) != 1
                or self.channels != request.channels
                or self.instrument_ids != request.instrument_ids
            ):
                return False
            available_end = (
                self.coverage_end
                if self.status is DatasetStatus.COMPLETED
                else self.requested_coverage_end
            )
            if available_end is None or available_end < request.coverage_end:
                return False
        return True
