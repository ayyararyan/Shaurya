"""Shared strict-model conventions for versioned Shaurya contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Immutable, strict-at-the-boundary base used by new JSON contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
