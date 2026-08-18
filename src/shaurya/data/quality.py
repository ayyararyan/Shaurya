"""DAT-06: stable collector-quality counters derived from emitted canonical rows."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import field_validator, model_validator

from shaurya.contracts.artifacts import ArtifactManifest
from shaurya.contracts.base import ContractModel
from shaurya.contracts.categories import ObjectCategory
from shaurya.contracts.tape import QualityFlag
from shaurya.contracts.timing import require_ist
from shaurya.data.dhan_stream import StreamMetrics


class CollectorQualityAudit(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    recorded_at: datetime
    rows: int
    crossed_book: int
    stale_quote: int
    invalid_depth: int
    gap_count: int
    by_flag: dict[str, int]
    category: Literal[ObjectCategory.DERIVED] = ObjectCategory.DERIVED

    @field_validator("recorded_at")
    @classmethod
    def _ist_timestamp(cls, value: datetime) -> datetime:
        return require_ist(value, "recorded_at")

    @model_validator(mode="after")
    def _valid_counts(self) -> Self:
        if not self.run_id.strip():
            raise ValueError("quality audit run_id is required")
        counts = (
            self.rows,
            self.crossed_book,
            self.stale_quote,
            self.invalid_depth,
            self.gap_count,
            *self.by_flag.values(),
        )
        if min(counts) < 0:
            raise ValueError("quality counters must be non-negative")
        return self

    @classmethod
    def from_metrics(
        cls,
        run_id: str,
        metrics: StreamMetrics,
        *,
        recorded_at: datetime,
    ) -> CollectorQualityAudit:
        by_flag = dict(metrics.quality_counts)
        return cls(
            run_id=run_id,
            recorded_at=recorded_at,
            rows=metrics.rows,
            crossed_book=by_flag.get(QualityFlag.CROSSED_BOOK.value, 0),
            stale_quote=by_flag.get(QualityFlag.STALE_QUOTE.value, 0),
            invalid_depth=by_flag.get(QualityFlag.INVALID_DEPTH.value, 0),
            gap_count=sum(
                by_flag.get(flag.value, 0)
                for flag in (QualityFlag.SEQUENCE_GAP, QualityFlag.CONNECTION_GAP)
            ),
            by_flag=by_flag,
        )


def write_quality_audit(
    manifest: ArtifactManifest, audit: CollectorQualityAudit
) -> Path:
    if audit.run_id != str(manifest.run_id):
        raise ValueError("quality audit run_id does not match manifest")
    path = manifest.run_dir / f"collector_quality_{manifest.run_id}.json"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as handle:
        handle.write((audit.model_dump_json(indent=2) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    manifest.register_existing(path, kind="collector_quality_audit")
    return path
