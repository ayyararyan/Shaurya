"""CON-09: strategy-independent opportunity/finding record."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import field_validator, model_validator
from shaurya.contracts.base import ContractModel
from shaurya.contracts.categories import ObjectLabel
from shaurya.contracts.timing import CausalTimestamps, require_ist


class FindingWindow(ContractModel):
    start_timestamp: datetime
    end_timestamp: datetime

    @field_validator("start_timestamp", "end_timestamp", mode="after")
    @classmethod
    def _ist_only(cls, value: datetime) -> datetime:
        return require_ist(value)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end_timestamp < self.start_timestamp:
            raise ValueError("finding window end cannot precede its start")
        return self


class FindingUncertainty(ContractModel):
    """At least one explicit confidence/significance measure."""

    standard_error: Decimal | None = None
    p_value: Decimal | None = None
    confidence_level: Decimal | None = None
    confidence_interval: tuple[Decimal, Decimal] | None = None

    @model_validator(mode="after")
    def _valid_uncertainty(self) -> Self:
        if all(
            value is None
            for value in (
                self.standard_error,
                self.p_value,
                self.confidence_level,
                self.confidence_interval,
            )
        ):
            raise ValueError("a finding requires an explicit confidence/significance measure")
        if self.standard_error is not None and self.standard_error < 0:
            raise ValueError("standard_error must be non-negative")
        if self.p_value is not None and not Decimal("0") <= self.p_value <= Decimal("1"):
            raise ValueError("p_value must lie in [0, 1]")
        if self.confidence_level is not None and not (
            Decimal("0") < self.confidence_level <= Decimal("1")
        ):
            raise ValueError("confidence_level must lie in (0, 1]")
        if self.confidence_interval is not None:
            lower, upper = self.confidence_interval
            if lower > upper:
                raise ValueError("confidence interval lower bound cannot exceed upper bound")
        return self


class SearchContext(ContractModel):
    tests_evaluated: int
    adjustment_method: str | None
    trial_log_id: str | None

    @field_validator("tests_evaluated")
    @classmethod
    def _positive_search_size(cls, value: int) -> int:
        if value < 1:
            raise ValueError("tests_evaluated must be positive")
        return value


class FindingRecord(ContractModel):
    """What the data shows before any strategy or ledger decision is attached."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    finding_id: str
    run_id: str
    subject: str
    window: FindingWindow
    timing: CausalTimestamps
    statistic_name: str
    statistic_value: Decimal
    magnitude: Decimal
    magnitude_unit: str
    uncertainty: FindingUncertainty
    search_context: SearchContext
    object_label: ObjectLabel

    @field_validator("finding_id", "run_id", "subject", "statistic_name", "magnitude_unit")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("finding identifiers and descriptions must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def _causal_window(self) -> Self:
        if self.window.end_timestamp > self.timing.decision_timestamp:
            raise ValueError("finding window cannot include data after decision_timestamp")
        return self
