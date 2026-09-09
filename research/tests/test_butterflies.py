from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import numpy as np
import pytest
from shaurya.contracts.tape import QualityFlag
from shaurya.contracts.timing import IST
from test_anl03_dashboard import _row

from shaurya.analytics.butterflies import (
    CALLS,
    HOLIDAYS,
    SIGNS,
    candidate,
    fees,
    greeks,
    prices,
    rounded_center,
    scenario_paths,
    schedule,
    simulate,
    strikes_at,
)
from shaurya.analytics.mispricing import InstrumentMetadata
from shaurya.analytics.surface_feed import SurfaceEngine, expiry_timestamp
from shaurya.surfaces.essvi import ESSVISlice, black76_price

NOW = datetime(2026, 9, 9, 14, 0, tzinfo=IST)
EXP = date(2026, 9, 15)
T = (expiry_timestamp(EXP) - NOW).total_seconds() / (365.25 * 86400)
SLICE = ESSVISlice(EXP, T, 24000.0, 0.12**2 * T, -0.2, 0.012, -0.05, 0.05, 50)


def chain():
    rows = []
    metadata = {}
    for strike in range(23100, 24901, 50):
        for kind in ("PE", "CE"):
            iv = math.sqrt(SLICE.total_variance(math.log(strike / 24000)) / T)
            mid = black76_price(
                forward=24000,
                strike=strike,
                maturity_years=T,
                volatility=iv,
                risk_free_rate=0,
                is_call=kind == "CE",
            )
            row = _row(
                instrument_id=f"NSE:NSE_FNO:NIFTY:option:{EXP}:{strike}:{kind}",
                bid=max(0.05, mid - 0.1),
                ask=mid + 0.1,
                sequence=len(rows) + 1,
                receive_ts=NOW - timedelta(milliseconds=100),
            )
            rows.append(row)
            metadata[row.instrument_id] = InstrumentMetadata(0.05, 50, "fixture")
    rows.append(
        _row(
            instrument_id=f"NSE:NSE_FNO:NIFTY:future:{EXP}",
            bid=23999.5,
            ask=24000.5,
            sequence=len(rows) + 1,
            receive_ts=NOW,
        )
    )
    return rows, metadata


def quote_map(rows):
    return {(float(p[5]), p[6]): r for r in rows if len(p := r.instrument_id.split(":")) == 7}


def fly():
    rows, metadata = chain()
    return candidate(24000, 400, SLICE, quote_map(rows), metadata, NOW, 0.0)


@pytest.mark.parametrize("forward", [22000.0, 24000.0, 26000.0])
@pytest.mark.parametrize("rate", [0.0, 0.06])
def test_vector_prices_equal_canonical_black(forward, rate):
    strikes = strikes_at(24000, 400)
    vol = np.array([0.13, 0.12, 0.12, 0.11])
    result = prices(forward, strikes, T, vol, rate)
    for i in range(4):
        expected = black76_price(
            forward=forward,
            strike=strikes[i],
            maturity_years=T,
            volatility=vol[i],
            risk_free_rate=rate,
            is_call=bool(CALLS[i]),
        )
        assert result[i] == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("f", [23000.0, 23600.0, 23900.0, 24000.0, 24200.0, 24400.0, 25000.0])
def test_expiry_payoff_bound_and_sign(f):
    payoff = float(prices(f, strikes_at(24000, 400), 0.0, 0.12) @ SIGNS)
    assert payoff == pytest.approx(-min(abs(f - 24000), 400))


def test_entry_uses_sell_bids_buy_asks_and_counts_fees_once():
    x = fly()
    legs = x["legs"]
    credit = legs[1]["bid"] + legs[2]["bid"] - legs[0]["ask"] - legs[3]["ask"]
    assert x["credit_points"] == pytest.approx(credit)
    assert x["net_entry_credit_points"] < credit
    assert x["mid_credit_points"] - x["entry_cost_points"] == pytest.approx(
        x["net_entry_credit_points"]
    )
    assert x["static_max_loss_before_exercise_tax"] == pytest.approx(
        (400 - x["net_entry_credit_points"]) * 50
    )
    assert [leg["side"] for leg in legs] == ["BUY", "SELL", "SELL", "BUY"]


def test_fee_rates_buy_sell_asymmetry_and_no_brokerage():
    common = (0.0003553 + 0.000001) * 1.18
    assert fees(100, 0) == pytest.approx(100 * (common + 0.00003))
    assert fees(0, 100) == pytest.approx(100 * (common + 0.0015))
    assert fees(0, 0) == 0


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("stale", "stale_or_future_quote"),
        ("future", "stale_or_future_quote"),
        ("missing", "missing_leg_quote"),
        ("lot", "missing_lot_metadata"),
        ("thin", "less_than_one_lot_at_bbo"),
        ("crossed", "invalid_book"),
    ],
)
def test_unexecutable_candidates_are_rejected(fault, reason):
    rows, meta = chain()
    q = quote_map(rows)
    key = (23600.0, "PE")
    r = q[key]
    if fault == "stale":
        q[key] = replace(r, receive_ts=NOW - timedelta(seconds=4))
    if fault == "future":
        q[key] = replace(r, receive_ts=NOW + timedelta(seconds=1))
    if fault == "missing":
        del q[key]
    if fault == "lot":
        del meta[r.instrument_id]
    if fault == "thin":
        q[key] = replace(r, asks=(replace(r.asks[0], quantity=1),))
    if fault == "crossed":
        q[key] = replace(r, bids=(replace(r.bids[0], price=r.best_ask + 1),))
    with pytest.raises(ValueError, match=reason):
        candidate(24000, 400, SLICE, q, meta, NOW, 0.0)


def test_unsupported_wings_never_extrapolated():
    rows, meta = chain()
    with pytest.raises(ValueError, match="outside_surface_support"):
        candidate(
            24000, 400, replace(SLICE, min_log_moneyness=-0.01), quote_map(rows), meta, NOW, 0.0
        )


def test_schedule_honours_weekend_holiday_expiry_and_daily_cap():
    assert date(2026, 9, 14) in HOLIDAYS
    friday = datetime(2026, 9, 11, 15, 20, tzinfo=IST)
    times, opening = schedule(friday, expiry_timestamp(EXP))
    assert opening == datetime(2026, 9, 15, 10, 0, tzinfo=IST)
    assert all(x.date() == EXP for x in times)
    times, _ = schedule(NOW, expiry_timestamp(EXP))
    checks = [x for x in times if x.time() == time(10, 0)]
    assert [x.date() for x in checks] == [date(2026, 9, 10), date(2026, 9, 11)]
    assert len({x.date() for x in checks}) == len(checks)


def run_sim(path, checks=None, friction=1.0):
    return simulate(
        row=fly(),
        path=np.asarray(path),
        fractions=np.array([0.5, 1.0]),
        check_indices=checks or set(),
        open_index=0,
        t=T,
        iv=0.12,
        rate=0.0,
        friction=friction,
    )


def test_no_recenter_identical_to_hold_and_terminal_cash_ledger():
    x = fly()
    result = run_sim([[24000.0, 24000.0], [24000.0, 24500.0]])
    assert result["hold"] == result["recenter"]
    # One path pays width plus tax on the long upper call's 100-point intrinsic.
    assert result["hold"]["mean"] == pytest.approx(
        (x["net_entry_credit_points"] - 200 - 0.075) * 50
    )


def test_recenter_threshold_and_no_future_lookahead():
    assert float(rounded_center(24225)) == 24250
    a = run_sim([[24199.0, 25000.0], [24200.0, 23000.0]], {0})
    b = run_sim([[24199.0, 23000.0], [24200.0, 25000.0]], {0})
    assert a["mean_recenters"] == b["mean_recenters"] == 0.5
    assert a["mean_total_cost"] > fly()["entry_cost_rupees"]


def test_more_friction_cannot_improve_simulated_pnl():
    path = [[24300.0, 24100.0], [23700.0, 23900.0]]
    a = run_sim(path, {0}, 1.0)
    b = run_sim(path, {0}, 2.0)
    assert b["recenter"]["mean"] < a["recenter"]["mean"]
    assert b["hold"]["mean"] < a["hold"]["mean"]
    assert b["mean_total_cost"] > a["mean_total_cost"]


def test_seeded_paths_and_explicit_gap_only_at_open():
    fractions = np.array([0.1, 0.2, 1.0])
    a = scenario_paths(24000, 0.1, T, fractions, 1, 0.0)
    b = scenario_paths(24000, 0.1, T, fractions, 1, 0.02)
    assert np.array_equal(a[:, 0], b[:, 0])
    assert b[:, 1:] == pytest.approx(a[:, 1:] * 1.02)
    assert np.array_equal(a, scenario_paths(24000, 0.1, T, fractions, 1, 0.0))


def test_signed_greeks_at_symmetric_center():
    result = greeks(24000, strikes_at(24000, 400), T, np.full(4, 0.12), 0.0)
    assert result["gamma"] < 0 and result["theta_day"] > 0 and result["vega_point"] < 0
    # For flat vol, theta and gamma cancel at matching RV in the local diffusion approximation.
    assert result["theta_day"] + 0.5 * result[
        "gamma"
    ] * 24000**2 * 0.12**2 / 365.25 == pytest.approx(0, abs=0.03)


def test_engine_produces_one_atm_500_point_position_and_historical_snapshot():
    rows, meta = chain()
    engine = SurfaceEngine(
        "test",
        "test",
        (EXP,),
        (-0.03, 0.0, 0.03),
        wall_clock=False,
        smoothing_enabled=False,
        instrument_metadata=meta,
        underlying="NIFTY",
    )
    for row in rows:
        engine.ingest(row)
    snap = engine.fit(NOW)
    assert snap.fit_ok
    b = snap.butterflies
    assert b["status"] == "ok"
    assert {c["width"] for c in b["candidates"]} == {500}
    assert len(b["candidates"]) == 1
    assert b["candidates"][0]["center"] == 24000
    assert b["strategy_signal"]["threshold"] == 0.70
    assert b["strategy_signal"]["condition_met"] is False
    for c in b["candidates"]:
        assert len(c["scenarios"]) == 5
        assert c["scenarios"]["base"]["mean_recenters"] <= len(b["recenter_checks"])
        assert c["carry_risk_ratio"] == pytest.approx(
            c["scenarios"]["base"]["recenter"]["mean"] / c["static_max_loss_before_exercise_tax"]
        )
    assert snap.to_dict()["butterflies"] == b
    later = engine.fit(NOW + timedelta(seconds=10))
    assert later.butterflies["status"] == "unavailable"
    assert engine.history[0].butterflies == b


def test_informational_feed_flags_retained_but_invalid_bbo_flags_rejected():
    rows, meta = chain()
    quotes = quote_map(rows)
    key = (23600.0, "PE")
    row = quotes[key]
    quotes[key] = replace(row, quality_flags=(QualityFlag.SOURCE_SEQUENCE_UNAVAILABLE,))
    result = candidate(24000, 400, SLICE, quotes, meta, NOW, 0.0)
    assert result["legs"][0]["quality_flags"] == ["source_sequence_unavailable"]
    quotes[key] = replace(row, quality_flags=(QualityFlag.STALE_QUOTE,))
    with pytest.raises(ValueError, match="invalid_quote_quality"):
        candidate(24000, 400, SLICE, quotes, meta, NOW, 0.0)


def test_monte_carlo_standard_error_uses_independent_antithetic_pairs():
    from shaurya.analytics.butterflies import summary

    # Pair means 2 and 4: sample SD sqrt(2), SE=1, in point units.
    result = summary(np.array([1.0, 3.0, 3.0, 5.0]), 50)
    assert result["mean"] == 150
    assert result["mc_se"] == pytest.approx(50)
