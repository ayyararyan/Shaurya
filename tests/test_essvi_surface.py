from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pytest

from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.contracts.timing import IST
from shaurya.surfaces.base import EvaluationStatus, SurfaceFitRequest
from shaurya.surfaces.essvi import (
    ESSVISurface,
    InsufficientSurfaceData,
    black76_price,
)

VALUATION = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
EXPIRIES = {
    date(2026, 8, 27): datetime(2026, 8, 27, 15, 30, tzinfo=IST),
    date(2026, 9, 24): datetime(2026, 9, 24, 15, 30, tzinfo=IST),
}
FORWARDS = {date(2026, 8, 27): 25_000.0, date(2026, 9, 24): 25_100.0}
PARAMETERS = {
    date(2026, 8, 27): (0.0011, -0.35, 0.025),
    date(2026, 9, 24): (0.0042, -0.30, 0.040),
}


def _synthetic_chain(*, theta_shift: float = 0.0) -> tuple[TapeRow, ...]:
    rows: list[TapeRow] = []
    sequence = 1
    for expiry, expiry_timestamp in EXPIRIES.items():
        forward = FORWARDS[expiry]
        theta, rho, psi = PARAMETERS[expiry]
        theta += theta_shift
        maturity = (expiry_timestamp - VALUATION).total_seconds() / (
            365.25 * 24.0 * 60.0 * 60.0
        )
        for log_moneyness in (-0.08, -0.06, -0.04, -0.02, 0.0, 0.02, 0.04, 0.06, 0.08):
            strike = forward * math.exp(log_moneyness)
            is_call = log_moneyness >= 0
            variance = ESSVISurface.total_variance(
                log_moneyness,
                theta=theta,
                rho=rho,
                psi=psi,
            )
            volatility = math.sqrt(variance / maturity)
            mid = black76_price(
                forward=forward,
                strike=strike,
                maturity_years=maturity,
                volatility=volatility,
                risk_free_rate=0.05,
                is_call=is_call,
            )
            half_spread = max(0.02, mid * 0.002)
            bid = max(0.001, mid - half_spread)
            ask = mid + half_spread
            option_type = "CE" if is_call else "PE"
            rows.append(
                TapeRow(
                    run_id="sha-20260818T043000.000000Z-synthetic",
                    receive_sequence=sequence,
                    connection_epoch=1,
                    source="synthetic_essvi_fixture",
                    event_type="depth20",
                    instrument_id=(
                        f"NSE:NSE_FNO:NIFTY:option:{expiry.isoformat()}:"
                        f"{strike:.8f}:{option_type}"
                    ),
                    broker_security_id=str(10_000 + sequence),
                    exchange_segment="NSE_FNO",
                    receive_ts=VALUATION - timedelta(seconds=20 - sequence / 10),
                    raw_message_size_bytes=332,
                    update_side="both",
                    bids=(DepthLevel(bid, 130, 2),),
                    asks=(DepthLevel(ask, 195, 3),),
                )
            )
            sequence += 1
    return tuple(rows)


def _request(
    *,
    rows: tuple[TapeRow, ...] | None = None,
    theta_shift: float = 0.0,
    previous_surface: ESSVISurface | None = None,
) -> SurfaceFitRequest:
    return SurfaceFitRequest(
        tape_rows=rows or _synthetic_chain(theta_shift=theta_shift),
        valuation_timestamp=VALUATION,
        forward_by_expiry=FORWARDS,
        expiry_timestamp_by_expiry=EXPIRIES,
        risk_free_rate=0.05,
        previous_surface=previous_surface,
    )


def _diagnostics(surface: ESSVISurface) -> dict[str, object]:
    return {item.name: item.value for item in surface.diagnostics}


def test_joint_essvi_fit_recovers_synthetic_surface_and_passes_arb_gates() -> None:
    surface = ESSVISurface.fit(_request())
    diagnostics = _diagnostics(surface)

    assert len(surface.slices) == 2
    assert diagnostics["fit_status"] == "converged"
    assert float(diagnostics["weighted_r_squared"]) > 0.995
    assert surface.arb_check().passed
    assert surface.arb_check().calendar_checked_points > 0

    for fitted_slice in surface.slices:
        expected_theta, _, _ = PARAMETERS[fitted_slice.expiry]
        assert fitted_slice.theta == pytest.approx(expected_theta, abs=2e-4)
        assert fitted_slice.psi * (1 + abs(fitted_slice.rho)) <= 4.0
        assert fitted_slice.psi**2 * (1 + abs(fitted_slice.rho)) <= 4 * fitted_slice.theta
        evaluation = surface.evaluate(
            log_moneyness=0.0,
            maturity_years=fitted_slice.maturity_years,
        )
        assert evaluation.status is EvaluationStatus.FITTED
        assert evaluation.total_variance == pytest.approx(fitted_slice.theta)


def test_surface_frame_round_trip_contains_fit_arb_support_and_policy_diagnostics() -> None:
    surface = ESSVISurface.fit(_request())
    frame = surface.to_frame(
        run_id="sha-20260818T043000.000000Z-synthetic",
        surface_id="nifty-index-options",
        decision_timestamp=VALUATION + timedelta(seconds=2),
        staleness_threshold_seconds=30.0,
    )
    restored = type(frame).model_validate_json(frame.model_dump_json())
    diagnostics = {item.name: item.value for item in restored.diagnostics}
    assert restored == frame
    assert restored.model_name == "eSSVI"
    assert len(restored.parameters) == 6
    assert diagnostics["arbitrage"]["passed"] is True
    assert diagnostics["interpolation_policy"]["strike_extrapolation"] == "none"
    assert diagnostics["support"][0]["quote_count"] == 9


def test_maturity_interpolation_is_total_variance_linear_and_extrapolation_is_explicit() -> None:
    surface = ESSVISurface.fit(_request())
    early, late = surface.slices
    middle = 0.5 * (early.maturity_years + late.maturity_years)
    evaluation = surface.evaluate(log_moneyness=0.0, maturity_years=middle)
    assert evaluation.status is EvaluationStatus.INTERPOLATED
    assert evaluation.total_variance == pytest.approx(0.5 * (early.theta + late.theta))

    strike_outside = surface.evaluate(
        log_moneyness=early.max_log_moneyness + 0.01,
        maturity_years=early.maturity_years,
    )
    maturity_outside = surface.evaluate(
        log_moneyness=0.0,
        maturity_years=late.maturity_years + 0.1,
    )
    assert strike_outside.status is EvaluationStatus.DATA_INSUFFICIENT
    assert "strike extrapolation is disabled" in str(strike_outside.reason)
    assert maturity_outside.status is EvaluationStatus.DATA_INSUFFICIENT
    assert "maturity extrapolation is disabled" in str(maturity_outside.reason)


def test_consecutive_fit_reports_parameter_stability() -> None:
    first = ESSVISurface.fit(_request())
    second = ESSVISurface.fit(
        _request(theta_shift=0.0001, previous_surface=first)
    )
    stability = _diagnostics(second)["parameter_stability"]
    assert stability["status"] == "available"
    assert stability["common_expiry_count"] == 2
    assert stability["max_absolute_parameter_change"] > 0


def test_fit_fails_explicitly_when_any_requested_slice_lacks_support() -> None:
    rows = tuple(row for row in _synthetic_chain() if ":2026-09-24:" not in row.instrument_id)
    with pytest.raises(InsufficientSurfaceData, match="2026-09-24=0"):
        ESSVISurface.fit(_request(rows=rows))
