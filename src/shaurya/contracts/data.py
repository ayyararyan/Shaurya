"""CON-10: broker-neutral dataset requests and DAT-owned dataset handles."""

from __future__ import annotations

import hashlib
import json
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


class DatasetHandle(ContractModel):
    """Immutable snapshot of one DAT dataset's identity, lifecycle and storage provenance."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset_id: str
    acquisition_fingerprint: str
    producer: Literal["DAT"] = "DAT"
    source: Literal["dhan", "legacy_tape"]
    status: DatasetStatus
    producer_pid: int | None = None
    trading_date: date
    channels: tuple[DataChannel, ...]
    instrument_ids: tuple[str, ...]
    tape_path: str
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

    @field_validator("dataset_id", "acquisition_fingerprint", "tape_path")
    @classmethod
    def _handle_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _non_empty(value, str(field_name))

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
        if self.coverage_start and self.coverage_end and self.coverage_end < self.coverage_start:
            raise ValueError("dataset coverage_end cannot precede coverage_start")
        if self.status is DatasetStatus.ACTIVE and self.completed_at is not None:
            raise ValueError("active dataset cannot have completed_at")
        if self.status is DatasetStatus.ACTIVE and self.producer_pid is None:
            raise ValueError("active dataset requires a producer_pid")
        if self.status is not DatasetStatus.ACTIVE and self.completed_at is None:
            raise ValueError("terminal dataset status requires completed_at")
        if self.status is DatasetStatus.INVALIDATED and not self.invalidation_reason:
            raise ValueError("invalidated dataset requires a reason")
        if self.status is not DatasetStatus.INVALIDATED and self.invalidation_reason is not None:
            raise ValueError("only invalidated datasets carry an invalidation reason")
        return self

    def satisfies(self, request: DatasetRequest) -> bool:
        """Whether this handle safely covers a consumer request without another acquisition."""

        if self.status is DatasetStatus.INVALIDATED:
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
            available_start = (
                self.coverage_start
                if self.status is DatasetStatus.COMPLETED
                else self.requested_coverage_start
            )
            if available_start is None or available_start > request.coverage_start:
                return False
        if request.coverage_end is not None:
            available_end = (
                self.coverage_end
                if self.status is DatasetStatus.COMPLETED
                else self.requested_coverage_end
            )
            if available_end is None or available_end < request.coverage_end:
                return False
        return True
