"""CON-04: one strict JSON configuration contract for Python and future C++."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from .base import ContractModel


class RiskScope(StrEnum):
    ACCOUNT = "account"
    PORTFOLIO = "portfolio"
    INSTRUMENT = "instrument"


class LimitComparison(StrEnum):
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="


class CredentialHandle(ContractModel):
    """Reference to externally stored credentials; never a secret value."""

    provider: str
    handle: str
    required_fields: tuple[str, ...]

    @field_validator("provider", "handle")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("credential provider and handle must be non-empty")
        return value.strip()


class RiskLimitDefinition(ContractModel):
    """Shared, unit-explicit limit definition; the threshold is always caller supplied."""

    name: str
    scope: RiskScope
    metric: str
    comparison: LimitComparison
    threshold: Decimal
    unit: str
    instrument_id: str | None = None

    @field_validator("name", "metric", "unit")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("risk limit names, metrics, and units must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def _scope_consistency(self) -> Self:
        if self.scope is RiskScope.INSTRUMENT and not self.instrument_id:
            raise ValueError("instrument-scoped limits require instrument_id")
        if self.scope is not RiskScope.INSTRUMENT and self.instrument_id is not None:
            raise ValueError("instrument_id is valid only for instrument-scoped limits")
        return self


class ShauryaConfig(ContractModel):
    """Versioned shared config root.

    C++ consumption remains an INF-03/NAT implementation requirement. This contract fixes
    the JSON shape and rejects unknown fields now so both languages can consume the same
    fixture later. It intentionally supplies no risk threshold or trading default.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    config_id: str
    credential_handles: tuple[CredentialHandle, ...]
    risk_limits: tuple[RiskLimitDefinition, ...]

    @field_validator("config_id")
    @classmethod
    def _config_id_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("config_id is required")
        return value.strip()

    @model_validator(mode="after")
    def _unique_entries(self) -> Self:
        handles = [(item.provider, item.handle) for item in self.credential_handles]
        if len(set(handles)) != len(handles):
            raise ValueError("credential handles must be unique by provider and handle")
        names = [item.name for item in self.risk_limits]
        if len(set(names)) != len(names):
            raise ValueError("risk limit names must be unique")
        return self
