"""CON-03: versioned model-agnostic volatility-surface frame contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic.types import JsonValue

from .base import ContractModel
from .categories import ObjectCategory, ObjectLabel
from .timing import CausalTimestamps, require_ist


class SurfaceParameter(ContractModel):
    name: str
    value: Decimal

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("surface parameter name is required")
        return value.strip()


class FitDiagnostic(ContractModel):
    """One named scalar or structured diagnostic, without model-specific assumptions."""

    name: str
    value: JsonValue
    unit: str | None = None

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fit diagnostic name is required")
        return value.strip()


class SurfaceFrame(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    surface_id: str
    model_name: str
    instrument_scope: tuple[str, ...]
    timing: CausalTimestamps
    surface_timestamp: datetime
    parameters: tuple[SurfaceParameter, ...]
    diagnostics: tuple[FitDiagnostic, ...]
    surface_age_seconds: Decimal
    staleness_threshold_seconds: Decimal
    is_stale: bool
    object_labels: tuple[ObjectLabel, ...]

    @field_validator("run_id", "surface_id", "model_name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("surface identifiers and model_name must be non-empty")
        return value.strip()

    @field_validator("surface_timestamp", mode="after")
    @classmethod
    def _surface_timestamp_ist(cls, value: datetime) -> datetime:
        return require_ist(value, "surface_timestamp")

    @model_validator(mode="after")
    def _consistent_frame(self) -> Self:
        if not self.instrument_scope or not self.parameters or not self.diagnostics:
            raise ValueError("surface scope, parameters, and diagnostics must be non-empty")
        if self.surface_age_seconds < 0 or self.staleness_threshold_seconds < 0:
            raise ValueError("surface age and staleness threshold must be non-negative")
        if self.surface_timestamp > self.timing.decision_timestamp:
            raise ValueError("surface_timestamp cannot be later than decision_timestamp")
        elapsed = self.timing.decision_timestamp - self.surface_timestamp
        expected_age = Decimal(str(elapsed.total_seconds()))
        if self.surface_age_seconds != expected_age:
            raise ValueError(
                "surface_age_seconds must equal decision_timestamp - surface_timestamp"
            )
        if self.is_stale != (self.surface_age_seconds > self.staleness_threshold_seconds):
            raise ValueError("is_stale must reflect the supplied staleness threshold")
        parameter_names = [item.name for item in self.parameters]
        diagnostic_names = [item.name for item in self.diagnostics]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("surface parameter names must be unique")
        if len(set(diagnostic_names)) != len(diagnostic_names):
            raise ValueError("fit diagnostic names must be unique")
        labels = {label.object_name: label.category for label in self.object_labels}
        if labels.get("parameters") is not ObjectCategory.ESTIMATED:
            raise ValueError("surface parameters must be labelled estimated")
        if labels.get("diagnostics") is not ObjectCategory.DERIVED:
            raise ValueError("surface diagnostics must be labelled derived")
        return self
