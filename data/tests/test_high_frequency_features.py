from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isclose

import pytest

from shaurya.contracts.tape import DepthLevel, QualityFlag, TapeRow
from shaurya.data.high_frequency import (
    ClockBucket,
    OptionQuote,
    RelativeState,
    TargetValue,
    TimedValue,
    TrendState,
    VersionedFeatureRow,
    VersionedValue,
    actual_futures_hedged_markout,
    atm_cp_iv_difference_bp,
    atm_strike,
    ccz_average,
    ccz_event_order_flow,
    exatm_forward_consensus,
    fit_essvi_equal_weight,
    future_mid_move_target,
    future_range_target,
    futures_microprice_tilt_ticks,
    inverse_depth_quantity_imbalance,
    ist_clock_bucket,
    iv_change_target,
    iv_vol_of_vol_60s,
    l1_quantity_lowvol_middepth_gate,
    lagged_median_basis,
    microprice_shift,
    midpoint_volatility,
    order_count_imbalance,
    parity_pressure,
    prior_move_ticks,
    quantity_imbalance,
    relative_tertile_state,
    reversal_pressure_5s,
    sign_agreement,
    spread_ticks,
    surface_residual_difference,
    trend_efficiency,
    trend_state,
)
from shaurya.data.option_pricing import (
    black76_price,
    essvi_total_variance,
    implied_volatility,
)


def _book(
    stamp: datetime,
    *,
    bid_price: float = 100.0,
    ask_price: float = 100.1,
    bid_quantities: tuple[int, ...] = (20, 18, 16, 14, 12),
    ask_quantities: tuple[int, ...] = (10, 12, 14, 16, 18),
    bid_orders: tuple[int, ...] = (5, 4, 3, 2, 1),
    ask_orders: tuple[int, ...] = (1, 2, 3, 4, 5),
    epoch: int = 1,
    sequence: int = 1,
    flags: tuple[QualityFlag, ...] = (),
) -> TapeRow:
    return TapeRow(
        run_id="sha-20260827T091500.000000Z-deadbeef",
        receive_sequence=sequence,
        connection_epoch=epoch,
        source="fixture",
        event_type="depth20",
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-27",
        broker_security_id="1",
        exchange_segment="NSE_FNO",
        receive_ts=stamp,
        raw_message_size_bytes=1,
        bids=tuple(
            DepthLevel(bid_price - 0.05 * index, quantity, bid_orders[index])
            for index, quantity in enumerate(bid_quantities)
        ),
        asks=tuple(
            DepthLevel(ask_price + 0.05 * index, quantity, ask_orders[index])
            for index, quantity in enumerate(ask_quantities)
        ),
        quality_flags=flags,
    )


def _option_quotes(anchor: datetime, expiry: datetime) -> tuple[OptionQuote, ...]:
    rows: list[OptionQuote] = []
    forward = 25_000.0
    for offset in (-4, -3, -2, -1, 0, 1, 2, 3, 4):
        strike = forward + 50.0 * offset
        put_mid = 10.0 + max(strike - forward, 0.0)
        call_mid = put_mid + forward - strike
        for is_call, mid in ((True, call_mid), (False, put_mid)):
            rows.append(
                OptionQuote(
                    expiry,
                    strike,
                    is_call,
                    mid - 0.25,
                    mid + 0.25,
                    anchor - timedelta(milliseconds=100 + abs(offset)),
                    1,
                )
            )
    return tuple(rows)


def test_book_state_constructions_and_microprice_identity() -> None:
    book = _book(datetime(2026, 8, 27, 9, 15, tzinfo=UTC))

    assert isclose(quantity_imbalance(book, levels=1) or 0, 1 / 3)
    assert isclose(order_count_imbalance(book) or 0, 0.0)
    assert -1 <= (inverse_depth_quantity_imbalance(book) or 0) <= 1
    shift = microprice_shift(book)
    assert shift is not None
    identity = 0.5 * (100.1 - 100.0) * (20 - 10) / (20 + 10)
    assert isclose(shift, identity)
    assert isclose(futures_microprice_tilt_ticks(book) or 0, shift / 0.05)
    assert isclose(spread_ticks(book) or 0, 2.0)


def test_invalid_or_stale_book_is_missing_not_zero() -> None:
    book = _book(
        datetime(2026, 8, 27, 9, 15, tzinfo=UTC),
        flags=(QualityFlag.STALE_QUOTE,),
    )
    assert quantity_imbalance(book, levels=1) is None
    assert microprice_shift(book) is None


def test_ccz_price_change_uses_prior_quantity_and_window_common_depth() -> None:
    stamp = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    previous = _book(
        stamp,
        bid_quantities=(40, 18, 16, 14, 12),
        ask_quantities=(30, 12, 14, 16, 18),
    )
    current = _book(
        stamp + timedelta(milliseconds=250),
        bid_price=99.95,
        ask_price=100.15,
        bid_quantities=(5, 18, 16, 14, 12),
        ask_quantities=(7, 12, 14, 16, 18),
        sequence=2,
    )

    flow = ccz_event_order_flow(previous, current)
    assert flow == (-33.0,)  # -old bid quantity minus (-new ask quantity)
    expected_depth = (5 + 7) / 2
    assert isclose(
        ccz_average((previous, current), anchor=current.receive_ts) or 0,
        -33 / expected_depth,
    )


def test_ccz_refuses_reconnect_boundary() -> None:
    stamp = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    previous = _book(stamp)
    current = _book(stamp + timedelta(milliseconds=100), epoch=2, sequence=2)
    assert ccz_event_order_flow(previous, current) is None
    assert ccz_average((previous, current), anchor=current.receive_ts) is None


def test_exatm_consensus_excludes_atm_and_enforces_freshness() -> None:
    anchor = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    expiry = datetime(2026, 8, 27, 10, tzinfo=UTC)
    quotes = _option_quotes(anchor, expiry)

    result = exatm_forward_consensus(
        futures_mid=25_001,
        option_quotes=quotes,
        anchor=anchor,
        expiry=expiry,
        connection_epoch=1,
    )

    assert result.forward == 25_000
    assert result.pairs == 8
    assert 25_000 not in result.strikes
    stale = tuple(
        OptionQuote(
            item.expiry,
            item.strike,
            item.is_call,
            item.bid,
            item.ask,
            anchor - timedelta(seconds=2),
            item.connection_epoch,
        )
        for item in quotes
    )
    assert (
        exatm_forward_consensus(
            futures_mid=25_001,
            option_quotes=stale,
            anchor=anchor,
            expiry=expiry,
            connection_epoch=1,
        ).unavailable_reason
        == "fewer_than_five_fresh_exatm_pairs"
    )


def test_slow_basis_excludes_current_and_future_values() -> None:
    anchor = datetime(2026, 8, 27, 9, 15, 30, tzinfo=UTC)
    history = [
        TimedValue(anchor - timedelta(seconds=seconds), 1, float(seconds))
        for seconds in range(1, 31)
    ]
    baseline = lagged_median_basis(history, anchor=anchor, connection_epoch=1)
    mutated = [
        *history,
        TimedValue(anchor, 1, 10_000.0),
        TimedValue(anchor + timedelta(seconds=1), 1, -10_000.0),
    ]
    assert lagged_median_basis(mutated, anchor=anchor, connection_epoch=1) == baseline
    assert parity_pressure(5.0, 3.0) == -2.0


def test_exact_grid_reversal_volatility_and_trend_refuse_gaps() -> None:
    anchor = datetime(2026, 8, 27, 9, 15, 10, tzinfo=UTC)
    points = [
        TimedValue(anchor - timedelta(seconds=10 - index), 1, 100.0 + index) for index in range(11)
    ]
    assert prior_move_ticks(points, anchor=anchor, connection_epoch=1) == 100.0
    assert reversal_pressure_5s(100.0) == -100.0
    assert midpoint_volatility(points, anchor=anchor, connection_epoch=1, seconds=10) == 0
    assert trend_efficiency(points, anchor=anchor, connection_epoch=1) == 1
    assert trend_state(0.30) is TrendState.CHOPPY
    assert trend_state(0.65) is TrendState.TRENDING
    assert prior_move_ticks(points[:-1], anchor=anchor, connection_epoch=1) is None


def test_relative_state_is_past_only_same_epoch_and_requires_support() -> None:
    anchor = datetime(2026, 8, 27, 9, 30, tzinfo=UTC)
    history = [
        TimedValue(anchor - timedelta(seconds=120 - index), 1, float(index)) for index in range(120)
    ]
    current = TimedValue(anchor, 1, 200.0)
    baseline = relative_tertile_state(current, history)
    assert baseline[0] is RelativeState.HIGH
    changed_current = relative_tertile_state(TimedValue(anchor, 1, -200.0), history)
    assert changed_current[1:] == baseline[1:]
    future_mutation = [*history, TimedValue(anchor + timedelta(seconds=1), 1, 999.0)]
    assert relative_tertile_state(current, future_mutation) == baseline
    assert relative_tertile_state(current, history[:-1]) == (None, None, None)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (3, 45, ClockBucket.OPEN),
        (4, 30, ClockBucket.MORNING),
        (6, 30, ClockBucket.MIDDAY),
        (8, 30, ClockBucket.LATE),
        (9, 30, ClockBucket.CLOSE),
    ],
)
def test_ist_clock_boundaries(hour: int, minute: int, expected: ClockBucket) -> None:
    assert ist_clock_bucket(datetime(2026, 8, 27, hour, minute, tzinfo=UTC)) is expected


def test_black76_inversion_and_equal_weight_essvi() -> None:
    forward = 25_000.0
    maturity = 10 / 365.25
    price = black76_price(
        forward=forward,
        strike=25_000,
        maturity_years=maturity,
        volatility=0.12,
        risk_free_rate=0.055,
        is_call=True,
    )
    recovered = implied_volatility(
        price=price,
        forward=forward,
        strike=25_000,
        maturity_years=maturity,
        risk_free_rate=0.055,
        is_call=True,
    )
    assert recovered is not None and isclose(recovered, 0.12, abs_tol=1e-8)
    strikes = (24_800.0, 24_850.0, 24_900.0, 25_100.0, 25_150.0, 25_200.0)
    logs = [__import__("math").log(strike / forward) for strike in strikes]
    variances = [essvi_total_variance(value, theta=0.04, rho=-0.2, psi=0.1) for value in logs]
    fit = fit_essvi_equal_weight(logs, variances, strikes=strikes)
    assert fit.converged and fit.static_arbitrage_passed
    assert fit.total_variance(0.0) is not None


def test_targets_are_future_only_same_epoch_and_complete_horizon() -> None:
    anchor = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    points = [
        TimedValue(anchor + timedelta(seconds=index), 1, 100.0 + index) for index in range(11)
    ]
    move = future_mid_move_target(points, anchor=anchor, connection_epoch=1, horizon_seconds=5)
    assert isinstance(move, TargetValue)
    assert move.value == 100.0
    assert (
        future_range_target(points, anchor=anchor, connection_epoch=1, horizon_seconds=10).value
        == 200.0
    )
    assert (
        iv_change_target(points, anchor=anchor, connection_epoch=1, horizon_seconds=5).value
        == 50_000
    )
    broken = future_range_target(points[:-1], anchor=anchor, connection_epoch=1, horizon_seconds=10)
    assert broken.value is None and broken.unavailable_reason


def test_option_targets_and_interactions_preserve_sign_and_missingness() -> None:
    assert (
        actual_futures_hedged_markout(
            current_option_mid=10,
            future_option_mid=12,
            beta=0.5,
            current_futures_mid=100,
            future_futures_mid=102,
        )
        == 1
    )
    assert surface_residual_difference(2, 0.5) == 1.5
    assert atm_cp_iv_difference_bp(0.10, 0.09) == pytest.approx(100)
    assert sign_agreement(1, 2, require_nonzero=True) == 1
    assert sign_agreement(0, 0, require_nonzero=True) == 0
    assert sign_agreement(None, 1) is None


def test_iv_vov_ddof_one_and_minimum_support() -> None:
    anchor = datetime(2026, 8, 27, 9, 16, tzinfo=UTC)
    shocks = [
        TimedValue(anchor - timedelta(seconds=39 - index), 1, float(index % 2))
        for index in range(40)
    ]
    assert iv_vol_of_vol_60s(shocks, anchor=anchor, connection_epoch=1) is not None
    assert iv_vol_of_vol_60s(shocks[:-1], anchor=anchor, connection_epoch=1) is None


def test_versioned_rows_persist_identity_and_reject_future_lineage() -> None:
    anchor = datetime(2026, 8, 27, 9, 15, tzinfo=UTC)
    value = VersionedValue("parity.pressure.v1", 1.0, anchor, (anchor,))
    row = VersionedFeatureRow(anchor, 1, (value,))
    assert row.to_dict()["features"][0]["feature_version"] == "parity.pressure.v1"
    with pytest.raises(ValueError, match="future information"):
        VersionedFeatureRow(
            anchor,
            1,
            (VersionedValue("x.v1", 1.0, anchor + timedelta(seconds=1), (anchor,)),),
        )


def test_gate_missingness_and_state_definition() -> None:
    assert l1_quantity_lowvol_middepth_gate(RelativeState.LOW, RelativeState.MID) is True
    assert l1_quantity_lowvol_middepth_gate(None, RelativeState.MID) is None


def test_atm_rounding_is_half_up_and_not_bankers_rounding() -> None:
    assert atm_strike(25_025) == 25_050
