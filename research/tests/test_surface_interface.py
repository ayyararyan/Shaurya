from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.contracts.timing import IST

from shaurya.research_contracts.surface import FitDiagnostic, SurfaceParameter
from shaurya.surfaces.base import (
    EvaluationStatus,
    SurfaceEvaluation,
    SurfaceFitRequest,
    SurfaceUse,
    VolatilitySurface,
)


def _time(second: int = 0) -> datetime:
    return datetime(2026, 8, 18, 10, 0, second, tzinfo=IST)


def _option_row(receive_ts: datetime | None = None) -> TapeRow:
    return TapeRow(
        run_id="sha-20260818T043000.000000Z-surfixture",
        receive_sequence=1,
        connection_epoch=1,
        source="synthetic",
        event_type="depth20",
        instrument_id="NSE:NSE_FNO:NIFTY:option:2026-08-27:25000:CE",
        broker_security_id="10001",
        exchange_segment="NSE_FNO",
        receive_ts=receive_ts or _time(),
        raw_message_size_bytes=332,
        update_side="both",
        bids=(DepthLevel(99.0, 100, 2),),
        asks=(DepthLevel(101.0, 120, 3),),
    )


def _request(*, receive_ts: datetime | None = None) -> SurfaceFitRequest:
    expiry = date(2026, 8, 27)
    return SurfaceFitRequest(
        tape_rows=(_option_row(receive_ts),),
        valuation_timestamp=_time(1),
        forward_by_expiry={expiry: 25_000.0},
        expiry_timestamp_by_expiry={expiry: datetime(2026, 8, 27, 15, 40, tzinfo=IST)},
    )


class _DummySurface(VolatilitySurface):
    @classmethod
    def fit(cls, request: SurfaceFitRequest) -> _DummySurface:
        return cls()

    def evaluate(self, *, log_moneyness: float, maturity_years: float) -> SurfaceEvaluation:
        return SurfaceEvaluation(0.04, 0.2, EvaluationStatus.FITTED)

    @property
    def params(self) -> tuple[SurfaceParameter, ...]:
        return (SurfaceParameter(name="theta", value=Decimal("0.04")),)

    @property
    def diagnostics(self) -> tuple[FitDiagnostic, ...]:
        return (FitDiagnostic(name="fit_status", value="converged"),)

    def arb_check(self) -> object:  # type: ignore[override]
        return object()

    @property
    def model_name(self) -> str:
        return "dummy"

    @property
    def surface_timestamp(self) -> datetime:
        return _time()

    @property
    def instrument_scope(self) -> tuple[str, ...]:
        return ("NSE:NSE_FNO:NIFTY",)

    @property
    def is_temporally_smoothed(self) -> bool:
        return False


def test_fit_request_uses_tape_contract_and_rejects_future_information() -> None:
    assert _request().tape_rows[0].best_bid == 99.0
    with pytest.raises(ValueError, match="causality violation"):
        _request(receive_ts=_time(2))


def test_data_insufficient_evaluation_cannot_hide_a_value() -> None:
    with pytest.raises(ValueError, match="fabricated"):
        SurfaceEvaluation(0.04, None, EvaluationStatus.DATA_INSUFFICIENT, "outside support")


def test_surface_frame_uses_caller_threshold_and_rejects_raw_quoting() -> None:
    surface = _DummySurface.fit(_request())
    fresh = surface.to_frame(
        run_id="sha-20260818T043000.000000Z-surfixture",
        surface_id="nifty",
        decision_timestamp=_time(4),
        staleness_threshold_seconds=5.0,
    )
    stale = surface.to_frame(
        run_id="sha-20260818T043000.000000Z-surfixture",
        surface_id="nifty",
        decision_timestamp=_time(4),
        staleness_threshold_seconds=timedelta(seconds=3).total_seconds(),
    )
    assert fresh.surface_age_seconds == Decimal("4.0")
    assert fresh.is_stale is False
    assert stale.is_stale is True
    with pytest.raises(ValueError, match="temporally smoothed"):
        surface.to_frame(
            run_id="sha-20260818T043000.000000Z-surfixture",
            surface_id="nifty",
            decision_timestamp=_time(4),
            staleness_threshold_seconds=5.0,
            use=SurfaceUse.QUOTING,
        )
