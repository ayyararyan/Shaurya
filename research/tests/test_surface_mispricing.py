"""ANL-07: independent surface-relative executable mispricing and episode semantics."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.contracts.timing import IST

from shaurya.analytics.mispricing import (
    InstrumentMetadata,
    MispricingDirection,
    MispricingPolicy,
    SurfaceMispricingDetector,
    _IVResidualSample,
)
from shaurya.surfaces.essvi import ESSVISurface, black76_price, implied_volatility

VALUATION = datetime(2026, 8, 20, 11, 0, tzinfo=IST)
EXPIRY = date(2026, 8, 25)
FORWARD = 24_100.0
THETA, RHO, PSI = 0.0012, -0.30, 0.024
SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0


def _instrument(strike: float, option_type: str) -> str:
    return f"NSE:NSE_FNO:NIFTY:option:{EXPIRY.isoformat()}:{strike:.8f}:{option_type}"


STRIKES = tuple(
    sorted({round(FORWARD * math.exp(k) / 50.0) * 50.0 for k in [i / 100 for i in range(-6, 7)]})
)
TARGET_STRIKE = min((strike for strike in STRIKES if strike > FORWARD), key=lambda x: x - FORWARD)
TARGET_ID = _instrument(TARGET_STRIKE, "CE")


def _maturity(now: datetime) -> float:
    close = datetime(2026, 8, 25, 15, 40, tzinfo=IST)
    return (close - now).total_seconds() / SECONDS_PER_YEAR


def _fair_mid(strike: float, option_type: str, now: datetime) -> float:
    k = math.log(strike / FORWARD)
    variance = ESSVISurface.total_variance(k, theta=THETA, rho=RHO, psi=PSI)
    volatility = math.sqrt(variance / _maturity(now))
    return black76_price(
        forward=FORWARD,
        strike=strike,
        maturity_years=_maturity(now),
        volatility=volatility,
        risk_free_rate=0.0,
        is_call=option_type == "CE",
    )


def _row(
    *,
    instrument_id: str,
    bid: float,
    ask: float,
    quantity: int,
    sequence: int,
    now: datetime,
    age_seconds: float = 0.1,
) -> TapeRow:
    return TapeRow(
        run_id="sha-anl07-test",
        receive_sequence=sequence,
        connection_epoch=1,
        source="synthetic_anl07_fixture",
        event_type="full",
        instrument_id=instrument_id,
        broker_security_id=str(90_000 + sequence),
        exchange_segment="NSE_FNO",
        receive_ts=now - timedelta(seconds=age_seconds),
        raw_message_size_bytes=162,
        update_side="both",
        bids=(DepthLevel(bid, quantity, 2),),
        asks=(DepthLevel(ask, quantity, 3),),
    )


def _chain(
    now: datetime,
    *,
    target_prices: tuple[float, float] | None = None,
    target_quantity: int = 150,
    omit_target: bool = False,
    peer_price_multiplier: float = 1.0,
) -> list[TapeRow]:
    rows: list[TapeRow] = []
    sequence = 1
    for strike in STRIKES:
        for option_type in ("CE", "PE"):
            instrument_id = _instrument(strike, option_type)
            if omit_target and instrument_id == TARGET_ID:
                continue
            mid = _fair_mid(strike, option_type, now)
            half = max(0.05, mid * 0.001)
            bid, ask = max(0.05, mid - half), mid + half
            quantity = 150
            if instrument_id == TARGET_ID:
                quantity = target_quantity
                if target_prices is not None:
                    bid, ask = target_prices
            elif peer_price_multiplier != 1.0:
                bid = max(0.05, bid * peer_price_multiplier)
                ask = max(bid, ask * peer_price_multiplier)
            rows.append(
                _row(
                    instrument_id=instrument_id,
                    bid=bid,
                    ask=ask,
                    quantity=quantity,
                    sequence=sequence,
                    now=now,
                )
            )
            sequence += 1
    rows.append(
        _row(
            instrument_id=f"NSE:NSE_FNO:NIFTY:future:{EXPIRY.isoformat()}",
            bid=FORWARD - 0.5,
            ask=FORWARD + 0.5,
            quantity=500,
            sequence=sequence,
            now=now,
        )
    )
    return rows


def _detector(
    *,
    lot_size: int = 75,
    raw_gap_max_points: float = 5.0,
    smoothing_min_frames: int = 2,
) -> SurfaceMispricingDetector:
    metadata = {
        _instrument(strike, option_type): InstrumentMetadata(
            tick_size=0.05,
            lot_size=lot_size,
            source="test_master",
        )
        for strike in STRIKES
        for option_type in ("CE", "PE")
    }
    return SurfaceMispricingDetector(
        policy=MispricingPolicy(
            cross_fit_folds=3,
            residual_quantile=0.90,
            min_residual_history=2,
            fdr_level=1.0,
            confirmation_frames=2,
            correction_frames=2,
            reference_smoothing_min_frames=smoothing_min_frames,
            reference_max_raw_smoothed_iv_gap_points=raw_gap_max_points,
            buy_turnover_rate=0.0,
            sell_turnover_rate=0.0,
            exit_slippage_ticks=0.0,
            hedge_slippage_ticks=0.0,
        ),
        instrument_metadata=metadata,
        min_quotes_per_slice=5,
    )


def _evaluate(
    detector: SurfaceMispricingDetector,
    now: datetime,
    rows: list[TapeRow],
) -> dict[str, object]:
    return detector.evaluate(
        rows=rows,
        expiries=(EXPIRY,),
        now=now,
        risk_free_rate=0.0,
    ).to_dict()


def test_public_black76_inversion_round_trips_a_supported_price() -> None:
    volatility = 0.18
    price = black76_price(
        forward=FORWARD,
        strike=TARGET_STRIKE,
        maturity_years=_maturity(VALUATION),
        volatility=volatility,
        risk_free_rate=0.0,
        is_call=True,
    )
    recovered = implied_volatility(
        price=price,
        forward=FORWARD,
        strike=TARGET_STRIKE,
        maturity_years=_maturity(VALUATION),
        risk_free_rate=0.0,
        is_call=True,
    )
    assert recovered == pytest.approx(volatility, abs=1e-10)


def test_cheap_option_confirms_then_traces_target_option_led_correction() -> None:
    detector = _detector()

    warm = _evaluate(detector, VALUATION, _chain(VALUATION))
    assert warm["status"] == "warming"
    assert warm["active"] == []

    clean_time = VALUATION + timedelta(seconds=5)
    clean = _evaluate(detector, clean_time, _chain(clean_time))
    assert clean["cross_fit_successful_folds"] == 3

    # A fresh offered price far below a strike-held-out fair value.
    first_time = VALUATION + timedelta(seconds=10)
    first = _evaluate(
        detector,
        first_time,
        _chain(first_time, target_prices=(4.98, 5.00)),
    )
    assert first["outside_band_count"] >= 1
    assert first["exact_confirmed_count"] >= 1
    assert first["pending_count"] >= 1
    assert first["active"] == []

    confirmed_time = VALUATION + timedelta(seconds=15)
    confirmed = _evaluate(
        detector,
        confirmed_time,
        _chain(confirmed_time, target_prices=(4.98, 5.00)),
    )
    episode = next(item for item in confirmed["active"] if item["instrument_id"] == TARGET_ID)
    assert episode["instrument_id"] == TARGET_ID
    assert episode["direction"] == "cheap"
    assert episode["exact_leave_strike_confirmed"] is True
    assert episode["fair_price"] > episode["observed_ask"]
    assert episode["fair_iv_lower"] > episode["observed_ask_iv"]
    assert episode["gross_iv_edge_points"] > 0
    assert episode["target_correction_required_iv_points"] > 0
    assert episode["residual_bucket"].endswith("continuous_knn_iv")
    assert episode["residual_effective_sample_size"] > 0
    assert episode["net_edge_per_lot"] > 0
    assert episode["first_seen_at"] == first_time.isoformat()

    # One clean frame starts hysteresis but does not close the episode.
    correcting_time = VALUATION + timedelta(seconds=20)
    correcting = _evaluate(detector, correcting_time, _chain(correcting_time))
    assert any(item["instrument_id"] == TARGET_ID for item in correcting["active"])

    corrected_time = VALUATION + timedelta(seconds=25)
    corrected = _evaluate(detector, corrected_time, _chain(corrected_time))
    assert not any(item["instrument_id"] == TARGET_ID for item in corrected["active"])
    closed = next(item for item in corrected["recent"] if item["instrument_id"] == TARGET_ID)
    assert closed["status"] == "corrected"
    assert closed["corrected_at"] == corrected_time.isoformat()
    assert closed["duration_seconds"] == pytest.approx(15.0)
    assert closed["correction_driver"] == "target_option_led"
    trace = closed["gap_close_trace"]
    assert trace["attribution"] == "target_option_led"
    assert trace["closure_gate"] == "frozen_entry_target_reached"
    assert trace["target_option_contribution"] > 0
    assert trace["target_iv_contribution_points"] > 0
    assert trace["target_option_share"] > 0.60
    assert trace["gap_closed"] == pytest.approx(
        trace["target_option_contribution"] + trace["reference_market_contribution"],
        abs=1e-10,
    )
    assert trace["identity_error"] == pytest.approx(0.0, abs=1e-10)
    assert trace["iv_identity_error_points"] == pytest.approx(0.0, abs=1e-10)
    assert trace["target_correction_achieved"] is True
    assert trace["delta_hedged_net_per_lot"] is not None


def test_gap_trace_separates_reference_market_movement_from_target_movement() -> None:
    detector = _detector()
    _evaluate(detector, VALUATION, _chain(VALUATION))
    clean_time = VALUATION + timedelta(seconds=5)
    _evaluate(detector, clean_time, _chain(clean_time))
    for seconds in (10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        _evaluate(detector, now, _chain(now, target_prices=(4.98, 5.00)))
    active = detector._active[TARGET_ID]
    initial = active.initial
    reference_move_points = 1.25
    active.latest = replace(
        initial,
        fair_iv_lower=initial.fair_iv_lower - reference_move_points / 100.0,
        gross_iv_edge_points=initial.gross_iv_edge_points - reference_move_points,
    )
    trace = detector._gap_close_trace(active, closure_gate="inside_uncertainty_band")
    assert trace.attribution == "reference_market_led"
    assert trace.target_iv_contribution_points == pytest.approx(0.0)
    assert trace.reference_iv_contribution_points == pytest.approx(reference_move_points)
    assert trace.iv_gap_closed_points == pytest.approx(reference_move_points)
    assert trace.reference_market_share == pytest.approx(1.0)
    assert trace.iv_identity_error_points == pytest.approx(0.0, abs=1e-12)
    assert trace.target_correction_achieved is False

    rich_initial = replace(
        initial,
        direction=MispricingDirection.RICH,
        observed_bid=20.0,
        observed_ask=20.1,
        observed_bid_iv=0.20,
        observed_ask_iv=0.201,
        executable_iv=0.20,
        fair_upper=18.0,
        fair_iv_upper=0.18,
        target_correction_required_iv_points=1.0,
    )
    active.direction = MispricingDirection.RICH
    active.initial = rich_initial
    active.latest = replace(
        rich_initial,
        observed_bid=19.0,
        observed_bid_iv=0.19,
        fair_upper=18.5,
        fair_iv_upper=0.185,
    )
    rich_trace = detector._gap_close_trace(active, closure_gate="inside_uncertainty_band")
    assert rich_trace.entry_iv_gap_points == pytest.approx(2.0)
    assert rich_trace.close_iv_gap_points == pytest.approx(0.5)
    assert rich_trace.target_iv_contribution_points == pytest.approx(1.0)
    assert rich_trace.reference_iv_contribution_points == pytest.approx(0.5)
    assert rich_trace.iv_gap_closed_points == pytest.approx(1.5)
    assert rich_trace.attribution == "target_option_led"
    assert rich_trace.iv_identity_error_points == pytest.approx(0.0, abs=1e-12)
    assert rich_trace.delta_hedged_gross_per_unit == pytest.approx(-0.1)


def test_reference_jump_is_rejected_by_current_raw_smoothed_agreement_gate() -> None:
    detector = _detector(raw_gap_max_points=0.50)
    for seconds in (0, 5, 10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        _evaluate(detector, now, _chain(now))

    jump_time = VALUATION + timedelta(seconds=20)
    jumped = _evaluate(
        detector,
        jump_time,
        _chain(
            jump_time,
            target_prices=(4.98, 5.00),
            peer_price_multiplier=1.20,
        ),
    )
    assert jumped["outside_band_count"] == 0
    assert jumped["reference_rejected_count"] > 0
    assert jumped["active"] == []


def test_default_six_fit_smoother_warmup_precedes_any_opportunity() -> None:
    detector = _detector(
        smoothing_min_frames=6,
        raw_gap_max_points=0.50,
    )
    for seconds in range(0, 30, 5):
        now = VALUATION + timedelta(seconds=seconds)
        frame = _evaluate(detector, now, _chain(now))
        assert frame["active"] == []

    first_time = VALUATION + timedelta(seconds=30)
    first = _evaluate(
        detector,
        first_time,
        _chain(first_time, target_prices=(4.98, 5.00)),
    )
    assert first["outside_band_count"] >= 1
    assert first["pending_count"] >= 1
    assert first["active"] == []

    confirmed_time = VALUATION + timedelta(seconds=35)
    confirmed = _evaluate(
        detector,
        confirmed_time,
        _chain(confirmed_time, target_prices=(4.98, 5.00)),
    )
    episode = next(item for item in confirmed["active"] if item["instrument_id"] == TARGET_ID)
    assert episode["reference_eligible"] is True
    assert episode["reference_smoothing_components"] >= 6


def test_reference_closed_episode_is_invalidated_not_corrected() -> None:
    detector = _detector()
    _evaluate(detector, VALUATION, _chain(VALUATION))
    clean_time = VALUATION + timedelta(seconds=5)
    _evaluate(detector, clean_time, _chain(clean_time))
    for seconds in (10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        _evaluate(detector, now, _chain(now, target_prices=(4.98, 5.00)))
    active = detector._active[TARGET_ID]
    initial = active.initial
    reference_closed = replace(
        initial,
        direction=None,
        fair_lower=initial.observed_ask - 0.05,
        fair_iv_lower=initial.observed_ask_iv - 0.0005,
        gross_edge=-0.05,
        gross_edge_ticks=-1.0,
        gross_iv_edge_points=-0.05,
        net_edge=-0.05,
        net_edge_ticks=-1.0,
        target_correction_required_iv_points=0.0,
        fdr_significant=False,
        exact_leave_strike_confirmed=False,
    )
    for seconds in (15, 20):
        detector._update_episodes(
            now=VALUATION + timedelta(seconds=seconds),
            observations={TARGET_ID: reference_closed},
            qualified={},
            ineligible={},
        )
    closed = detector.latest_frame
    assert closed is not None
    episode = detector._recent[0]
    assert episode.status.value == "invalidated"
    assert episode.corrected_at is None
    assert episode.invalidated_at == VALUATION + timedelta(seconds=20)
    assert episode.gap_close_trace.attribution == "reference_market_led"
    assert episode.gap_close_trace.target_correction_achieved is False
    assert not hasattr(detector, "_reference_iv_history")
    assert episode.latest.reference_smoothing_components >= 2


def test_dislocation_below_one_lot_never_becomes_actionable() -> None:
    detector = _detector(lot_size=75)
    _evaluate(detector, VALUATION, _chain(VALUATION))
    frame: dict[str, object] = {}
    for seconds in (5, 10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        frame = _evaluate(
            detector,
            now,
            _chain(now, target_prices=(4.98, 5.00), target_quantity=10),
        )
    assert not any(item["instrument_id"] == TARGET_ID for item in frame["active"])


def test_missing_target_quote_censors_instead_of_calling_it_corrected() -> None:
    detector = _detector()
    _evaluate(detector, VALUATION, _chain(VALUATION))
    clean_time = VALUATION + timedelta(seconds=5)
    _evaluate(detector, clean_time, _chain(clean_time))
    for seconds in (10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        _evaluate(detector, now, _chain(now, target_prices=(4.98, 5.00)))
    assert detector.latest_frame is not None and detector.latest_frame.active

    missing_time = VALUATION + timedelta(seconds=20)
    frame = _evaluate(detector, missing_time, _chain(missing_time, omit_target=True))
    assert not any(item["instrument_id"] == TARGET_ID for item in frame["active"])
    closed = next(item for item in frame["recent"] if item["instrument_id"] == TARGET_ID)
    assert closed["status"] == "censored"
    assert closed["corrected_at"] is None
    assert closed["censor_reason"] == "observation_unavailable"


def test_continuous_iv_uncertainty_has_no_old_spread_bucket_jump() -> None:
    detector = _detector()
    history = detector._residuals[(EXPIRY, True)]
    for index in range(300):
        relative_spread = 0.0095 + 0.001 * (index % 2)
        history.append(
            _IVResidualSample(
                log_moneyness=0.001 * ((index % 21) - 10),
                log_relative_spread=math.log(relative_spread),
                residual_points=0.20 + 0.002 * (index % 17),
            )
        )

    below = detector._uncertainty_and_p(
        expiry=EXPIRY,
        is_call=True,
        log_moneyness=0.0,
        log_relative_spread=math.log(0.0099),
        residual_points=1.0,
    )
    above = detector._uncertainty_and_p(
        expiry=EXPIRY,
        is_call=True,
        log_moneyness=0.0,
        log_relative_spread=math.log(0.0101),
        residual_points=1.0,
    )
    assert below[0] is not None and above[0] is not None
    assert abs(below[0] - above[0]) < 0.01
    assert below[2] == above[2] == 300
    assert below[3] > 100 and above[3] > 100
    assert below[4].endswith("continuous_knn_iv")

    detector._append_residual(
        (EXPIRY, True),
        _IVResidualSample(
            log_moneyness=0.0,
            log_relative_spread=math.log(0.01),
            residual_points=5.0,
        ),
    )
    refreshed = detector._uncertainty_and_p(
        expiry=EXPIRY,
        is_call=True,
        log_moneyness=0.0,
        log_relative_spread=math.log(0.01),
        residual_points=1.0,
    )
    assert refreshed[2] == 301
    assert refreshed[0] is not None and refreshed[0] >= below[0]


def test_current_outside_iv_residual_does_not_train_its_uncertainty() -> None:
    detector = _detector()
    _evaluate(detector, VALUATION, _chain(VALUATION))
    clean_time = VALUATION + timedelta(seconds=5)
    _evaluate(detector, clean_time, _chain(clean_time))
    dislocation_time = VALUATION + timedelta(seconds=10)
    _evaluate(
        detector,
        dislocation_time,
        _chain(dislocation_time, target_prices=(4.98, 5.00)),
    )
    target = detector._pending[TARGET_ID].observation
    assert target.iv_residual_points is not None
    history = detector._residuals[(EXPIRY, True)]
    assert all(
        sample.residual_points != pytest.approx(target.iv_residual_points) for sample in history
    )


def test_forward_price_move_cannot_fake_iv_target_correction() -> None:
    detector = _detector()
    _evaluate(detector, VALUATION, _chain(VALUATION))
    _evaluate(detector, VALUATION + timedelta(seconds=5), _chain(VALUATION + timedelta(seconds=5)))
    for seconds in (10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        _evaluate(detector, now, _chain(now, target_prices=(4.98, 5.00)))
    active = detector._active[TARGET_ID]
    initial = active.initial
    active.latest = replace(
        initial,
        observed_bid=max(0.05, initial.observed_bid - 1.0),
        observed_ask=max(0.05, initial.observed_ask - 1.0),
        forward=initial.forward - 100.0,
    )
    trace = detector._gap_close_trace(active, closure_gate=None)
    assert trace.target_option_contribution < 0
    assert trace.target_iv_contribution_points == pytest.approx(0.0)
    assert trace.target_correction_achieved is False


def test_iv_convergence_can_correct_while_absolute_option_price_falls() -> None:
    detector = _detector()
    _evaluate(detector, VALUATION, _chain(VALUATION))
    _evaluate(detector, VALUATION + timedelta(seconds=5), _chain(VALUATION + timedelta(seconds=5)))
    for seconds in (10, 15):
        now = VALUATION + timedelta(seconds=seconds)
        _evaluate(detector, now, _chain(now, target_prices=(4.98, 5.00)))
    active = detector._active[TARGET_ID]
    initial = active.initial
    required = initial.target_correction_required_iv_points / 100.0
    new_forward = initial.forward - 1_500.0
    new_ask_iv = initial.observed_ask_iv + required + 0.002
    new_ask = black76_price(
        forward=new_forward,
        strike=initial.strike,
        maturity_years=_maturity(VALUATION + timedelta(seconds=20)),
        volatility=new_ask_iv,
        risk_free_rate=0.0,
        is_call=True,
    )
    assert new_ask < initial.observed_ask
    active.latest = replace(
        initial,
        observed_bid=max(0.05, new_ask - 0.02),
        observed_ask=new_ask,
        observed_bid_iv=max(1e-8, new_ask_iv - 0.0002),
        observed_ask_iv=new_ask_iv,
        forward=new_forward,
    )
    trace = detector._gap_close_trace(active, closure_gate=None)
    assert trace.target_option_contribution < 0
    assert trace.target_iv_contribution_points > initial.target_correction_required_iv_points
    assert trace.target_correction_achieved is True
    assert trace.delta_hedged_gross_per_unit == pytest.approx(
        active.latest.observed_bid
        - initial.observed_ask
        - initial.fair_delta * (new_forward - initial.forward)
    )


def test_monitor_source_has_no_order_or_execution_dependency() -> None:
    source = (
        Path(__file__).parents[1] / "src/shaurya/analytics/mispricing.py"
    ).read_text()
    forbidden = (
        "shaurya.execution",
        "kotak",
        "place_order",
        "modify_order",
        "cancel_order",
    )
    assert all(item not in source for item in forbidden)
