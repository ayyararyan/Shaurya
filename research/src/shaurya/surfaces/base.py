"""REQ-SUR-01: common interface for every enabled surface parameterisation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from shaurya.contracts.categories import ObjectCategory, ObjectLabel
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST, CausalTimestamps, require_ist

from shaurya.research_contracts.surface import FitDiagnostic, SurfaceFrame, SurfaceParameter

if TYPE_CHECKING:
    from .arbitrage import ArbitrageReport


class EvaluationStatus(StrEnum):
    """Whether a requested cell is supported and how it was constructed."""

    FITTED = "fitted"
    INTERPOLATED = "interpolated"
    EXTRAPOLATED = "extrapolated"
    SMOOTHED = "smoothed"
    DATA_INSUFFICIENT = "data_insufficient"


class SurfaceUse(StrEnum):
    RESEARCH = "research"
    QUOTING = "quoting"


@dataclass(frozen=True, slots=True)
class SurfaceEvaluation:
    """One total-variance evaluation with explicit support semantics."""

    total_variance: float | None
    implied_volatility: float | None
    status: EvaluationStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is EvaluationStatus.DATA_INSUFFICIENT:
            if self.total_variance is not None or self.implied_volatility is not None:
                raise ValueError("data-insufficient evaluations cannot carry fabricated values")
            if not self.reason:
                raise ValueError("data-insufficient evaluations require a reason")
            return
        if self.total_variance is None or self.implied_volatility is None:
            raise ValueError("supported evaluations require variance and volatility")
        if self.total_variance < 0 or self.implied_volatility < 0:
            raise ValueError("variance and volatility must be non-negative")


@dataclass(frozen=True, slots=True)
class SurfaceFitRequest:
    """Fit context whose observed rows are the existing CON-01 tape contract.

    DAT supplies one or more latest option-book rows per instrument. Forward and exact
    expiry timestamps are explicit inputs because neither can be recovered from an option
    book row without silently choosing a market convention.
    """

    tape_rows: tuple[TapeRow, ...]
    valuation_timestamp: datetime
    forward_by_expiry: Mapping[date, float]
    expiry_timestamp_by_expiry: Mapping[date, datetime]
    risk_free_rate: float = 0.0
    min_quotes_per_slice: int = 5
    previous_surface: VolatilitySurface | None = None

    def __post_init__(self) -> None:
        valuation = require_ist(self.valuation_timestamp, "valuation_timestamp")
        object.__setattr__(self, "valuation_timestamp", valuation)
        if not self.tape_rows:
            raise ValueError("surface fitting requires CON-01 tape rows")
        if self.min_quotes_per_slice < 5:
            raise ValueError("eSSVI requires at least five usable quotes per maturity")
        if not self.forward_by_expiry:
            raise ValueError("at least one expiry forward is required")
        if set(self.forward_by_expiry) != set(self.expiry_timestamp_by_expiry):
            raise ValueError("forward and expiry-timestamp maps must cover the same expiries")
        if any(value <= 0 for value in self.forward_by_expiry.values()):
            raise ValueError("forwards must be positive")
        for expiry, timestamp in self.expiry_timestamp_by_expiry.items():
            normalized = require_ist(timestamp, f"expiry_timestamp[{expiry.isoformat()}]")
            if normalized <= valuation:
                raise ValueError("all fitted expiries must be later than valuation time")
        if any(row.receive_ts > valuation for row in self.tape_rows):
            raise ValueError("causality violation: tape rows cannot arrive after valuation time")


class VolatilitySurface(ABC):
    """Common module-facing contract required by REQ-SUR-01."""

    @classmethod
    @abstractmethod
    def fit(cls, request: SurfaceFitRequest) -> Self:
        """Calibrate a surface from observed CON-01 rows."""

    @abstractmethod
    def evaluate(self, *, log_moneyness: float, maturity_years: float) -> SurfaceEvaluation:
        """Evaluate total variance and annualized implied volatility."""

    @property
    @abstractmethod
    def params(self) -> tuple[SurfaceParameter, ...]:
        """Return the fitted parameters using the CON-03 parameter contract."""

    @property
    @abstractmethod
    def diagnostics(self) -> tuple[FitDiagnostic, ...]:
        """Return fit, support, stability, and policy diagnostics."""

    @abstractmethod
    def arb_check(self) -> ArbitrageReport:
        """Independently verify butterfly and calendar no-arbitrage conditions."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Stable parameterisation name written to CON-03 frames."""

    @property
    @abstractmethod
    def surface_timestamp(self) -> datetime:
        """Oldest source timestamp contributing to the fit, in IST."""

    @property
    @abstractmethod
    def instrument_scope(self) -> tuple[str, ...]:
        """Broker-neutral underlying scope represented by the surface."""

    @property
    @abstractmethod
    def is_temporally_smoothed(self) -> bool:
        """Whether this surface is safe to expose to a quoting consumer."""

    def assert_ready_for(self, use: SurfaceUse) -> None:
        if use is SurfaceUse.QUOTING and not self.is_temporally_smoothed:
            raise ValueError("quoting requires a temporally smoothed surface")

    def to_frame(
        self,
        *,
        run_id: str,
        surface_id: str,
        decision_timestamp: datetime,
        staleness_threshold_seconds: float,
        use: SurfaceUse = SurfaceUse.RESEARCH,
    ) -> SurfaceFrame:
        """Build a versioned CON-03 frame using the caller's staleness tolerance."""

        self.assert_ready_for(use)
        decision = require_ist(decision_timestamp, "decision_timestamp")
        if decision < self.surface_timestamp:
            raise ValueError("decision_timestamp cannot predate the surface")
        if staleness_threshold_seconds < 0:
            raise ValueError("staleness threshold must be non-negative")
        age = Decimal(str((decision - self.surface_timestamp).total_seconds()))
        threshold = Decimal(str(staleness_threshold_seconds))
        timing = CausalTimestamps(
            exchange_timestamp=None,
            receive_timestamp=self.surface_timestamp.astimezone(IST),
            decision_timestamp=decision,
            source_timestamps=(self.surface_timestamp.astimezone(IST),),
        )
        return SurfaceFrame(
            run_id=run_id,
            surface_id=surface_id,
            model_name=self.model_name,
            instrument_scope=self.instrument_scope,
            timing=timing,
            surface_timestamp=self.surface_timestamp.astimezone(IST),
            parameters=self.params,
            diagnostics=self.diagnostics,
            surface_age_seconds=age,
            staleness_threshold_seconds=threshold,
            is_stale=age > threshold,
            object_labels=(
                ObjectLabel(
                    object_name="parameters",
                    category=ObjectCategory.ESTIMATED,
                    source=self.model_name,
                ),
                ObjectLabel(
                    object_name="diagnostics",
                    category=ObjectCategory.DERIVED,
                    source=self.model_name,
                ),
            ),
        )
