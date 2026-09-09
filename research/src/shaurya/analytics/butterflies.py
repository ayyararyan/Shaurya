"""Read-only BFLY-01..10 pricing and conditional carry; see BUTTERFLY_CARRY_DESIGN.md."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr
from shaurya.contracts.tape import QualityFlag, TapeRow
from shaurya.contracts.timing import IST

from shaurya.analytics.mispricing import InstrumentMetadata
from shaurya.analytics.variance_carry import realized_volatility_forecast
from shaurya.surfaces.essvi import ESSVISlice, ESSVISurface, black76_price

VERSION = "iron-carry-v1"
PATHS = 1024
HOLIDAYS = {
    date.fromisoformat(x)
    for x in (
        "2026-01-26",
        "2026-03-03",
        "2026-03-26",
        "2026-03-31",
        "2026-04-03",
        "2026-04-14",
        "2026-05-01",
        "2026-05-28",
        "2026-06-26",
        "2026-09-14",
        "2026-10-02",
        "2026-10-20",
        "2026-11-10",
        "2026-11-24",
        "2026-12-25",
    )
}
SIGNS = np.array([1.0, -1.0, -1.0, 1.0])
CALLS = np.array([False, False, True, True])
SCENARIOS = (
    ("base", 1.0, 1.0, 1.0, 0.0),
    ("high_rv_cost", 1.25, 1.2, 2.0, 0.0),
    ("low_rv", 0.8, 0.8, 1.0, 0.0),
    ("gap_down_2pct", 1.0, 1.0, 1.0, -0.02),
    ("gap_up_2pct", 1.0, 1.0, 1.0, 0.02),
)


def trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS


def schedule(now: datetime, expiry: datetime) -> tuple[list[datetime], datetime]:
    if now.year != 2026 or expiry.year != 2026:
        raise ValueError("trading_calendar_verified_for_2026_only")
    if expiry <= now:
        raise ValueError("expiry_has_passed")
    checks: list[datetime] = []
    opens: list[datetime] = []
    day = now.astimezone(IST).date()
    while day <= expiry.date():
        if trading_day(day):
            check = datetime.combine(day, time(15, 15), IST)
            opening = datetime.combine(day, time(9, 15), IST)
            if now < check < expiry and day != expiry.date():
                checks.append(check)
            if now < opening <= expiry:
                opens.append(opening)
        day += timedelta(days=1)
    next_open = opens[0] if opens else expiry
    return sorted(set([*checks, next_open, expiry])), next_open


def prices(f: Any, strikes: Any, t: float, iv: Any, rate: float = 0.0) -> NDArray[np.float64]:
    """Vectorized Black-76, with exact expiry payoff (validated against DAT scalar)."""
    f = np.asarray(f, dtype=float)[..., None]
    k = np.asarray(strikes, dtype=float)
    intrinsic = np.maximum(np.where(CALLS, f - k, k - f), 0.0)
    if t <= 0:
        return np.asarray(intrinsic, dtype=float)
    v = np.maximum(np.asarray(iv, dtype=float) * math.sqrt(t), 1e-12)
    d1 = np.log(f / k) / v + 0.5 * v
    d2 = d1 - v
    cp = np.where(CALLS, 1.0, -1.0)
    return np.asarray(
        math.exp(-rate * t) * cp * (f * ndtr(cp * d1) - k * ndtr(cp * d2)), dtype=float
    )


def fees(buys: Any, sells: Any) -> Any:
    """Points/unit; API brokerage zero. Add quantity only when converting to rupees."""
    turnover = buys + sells
    return turnover * (0.00035530 + 0.000001) * 1.18 + buys * 0.00003 + sells * 0.0015


def strikes_at(center: Any, width: float) -> NDArray[np.float64]:
    return np.asarray(
        np.asarray(center)[..., None] + np.array([-width, 0.0, 0.0, width]), dtype=float
    )


def rounded_center(f: Any) -> Any:
    return 50.0 * np.floor(np.asarray(f) / 50.0 + 0.5)


def scenario_paths(
    f: float,
    rv: float,
    t: float,
    fractions: NDArray[np.float64],
    gap_index: int,
    shock: float,
    *,
    paths: int = PATHS,
) -> NDArray[np.float64]:
    rng = np.random.default_rng(20260909)
    z = rng.standard_normal((paths // 2, len(fractions)))
    z = np.concatenate((z, -z), axis=0)
    variance = rv * rv * t * np.diff(np.r_[0.0, fractions])
    increments = -0.5 * variance + np.sqrt(variance) * z
    increments[:, gap_index] += math.log1p(shock)
    return np.asarray(f * np.exp(np.cumsum(increments, axis=1)), dtype=float)


def summary(pnl: NDArray[np.float64], lot: int) -> dict[str, float]:
    x = pnl * lot
    p05 = float(np.quantile(x, 0.05))
    paired = (x[: len(x) // 2] + x[len(x) // 2 :]) / 2 if len(x) >= 4 else x
    return {
        "mean": float(x.mean()),
        "mc_se": float(paired.std(ddof=1) / math.sqrt(len(paired))),
        "p05": p05,
        "tail_mean": float(x[x <= p05].mean()),
        "loss_probability": float((x < 0).mean()),
    }


def simulate(
    *,
    row: dict[str, Any],
    path: NDArray[np.float64],
    fractions: NDArray[np.float64],
    check_indices: set[int],
    open_index: int,
    t: float,
    iv: float,
    rate: float,
    friction: float = 1.0,
) -> dict[str, Any]:
    """Full close/open cash ledger; state updates only at that day's decision time."""
    n = len(path)
    lot = row["lot_size"]
    width = row["width"]
    centers = np.full(n, row["center"])
    cash = np.full(n, row["net_entry_credit_points"])
    cost = np.full(n, row["entry_cost_points"])
    count = np.zeros(n)
    half = np.array([x["half_spread"] + x["tick_size"] for x in row["legs"]]) * friction
    # Stress charges extra initial crossing/slippage, never improves entry vs observed BBO.
    extra = (friction - 1) * row["entry_spread_slippage_points"]
    cash -= extra
    cost += extra
    initial_cash = cash.copy()
    overnight: NDArray[np.float64] | None = None
    previous_fraction = 0.0
    for i, fraction in enumerate(fractions):
        cash *= math.exp(rate * t * (fraction - previous_fraction))
        previous_fraction = float(fraction)
        forward = path[:, i]
        remaining = max(0.0, t * (1 - fraction))
        if i == open_index:
            p = prices(forward, strikes_at(row["center"], width), remaining, iv, rate)
            close = np.maximum(0.0, p - SIGNS * half)
            close_fee = fees(close[:, SIGNS < 0].sum(axis=1), close[:, SIGNS > 0].sum(axis=1))
            if remaining == 0:
                close = p
                close_fee = 0.0015 * p[:, SIGNS > 0].sum(axis=1)
            overnight = (
                initial_cash * math.exp(rate * t * fraction)
                + (close * SIGNS).sum(axis=1)
                - close_fee
            )
        if i in check_indices:
            move = np.abs(forward - centers) >= width / 2
            if np.any(move):
                old = prices(forward[move], strikes_at(centers[move], width), remaining, iv, rate)
                new_centers = rounded_center(forward[move])
                new = prices(forward[move], strikes_at(new_centers, width), remaining, iv, rate)
                close = np.maximum(0.0, old - SIGNS * half)
                opening = np.maximum(0.0, new + SIGNS * half)
                charge = fees(close[:, SIGNS < 0].sum(axis=1), close[:, SIGNS > 0].sum(axis=1))
                charge += fees(opening[:, SIGNS > 0].sum(axis=1), opening[:, SIGNS < 0].sum(axis=1))
                cash[move] += (close * SIGNS).sum(axis=1) - (opening * SIGNS).sum(axis=1) - charge
                cost[move] += (
                    np.abs(close - old).sum(axis=1) + np.abs(opening - new).sum(axis=1) + charge
                )
                centers[move] = new_centers
                count[move] += 1
    payoff = prices(path[:, -1], strikes_at(centers, width), 0.0, iv)
    exercise_tax = 0.0015 * payoff[:, SIGNS > 0].sum(axis=1)
    pnl = cash + (payoff * SIGNS).sum(axis=1) - exercise_tax
    hold_payoff = prices(path[:, -1], strikes_at(row["center"], width), 0.0, iv)
    hold_tax = 0.0015 * hold_payoff[:, SIGNS > 0].sum(axis=1)
    hold = initial_cash * math.exp(rate * t) + (hold_payoff * SIGNS).sum(axis=1) - hold_tax
    assert overnight is not None
    return {
        "recenter": summary(pnl, lot),
        "hold": summary(hold, lot),
        "overnight": summary(overnight, lot),
        "mean_recenters": float(count.mean()),
        "mean_total_cost": float((cost + exercise_tax).mean() * lot),
        "manual_brokerage_extra": float((4 + 8 * count.mean()) * 10 * 1.18),
    }


def greeks(
    f: float, strikes: NDArray[np.float64], t: float, iv: NDArray[np.float64], rate: float
) -> dict[str, float]:
    h = 1.0
    dt = min(1 / 365.25, t / 100)
    v = 0.0001

    def val(ff: float, tt: float, vv: Any) -> float:
        return float(np.dot(prices(ff, strikes, tt, vv, rate), SIGNS))

    base = val(f, t, iv)
    return {
        "delta": (val(f + h, t, iv) - val(f - h, t, iv)) / (2 * h),
        "gamma": (val(f + h, t, iv) - 2 * base + val(f - h, t, iv)) / (h * h),
        "theta_day": (val(f, t - dt, iv) - val(f, t + dt, iv)) / (2 * dt) / 365.25,
        "vega_point": (val(f, t, iv + v) - val(f, t, iv - v)) / (2 * v) * 0.01,
    }


def candidate(
    center: float,
    width: float,
    slice_: ESSVISlice,
    quotes: Mapping[tuple[float, str], TapeRow],
    metadata: Mapping[str, InstrumentMetadata],
    now: datetime,
    rate: float,
) -> dict[str, Any]:
    legs: list[dict[str, Any]] = []
    lot_sizes = set()
    for strike, kind, sign in zip(
        strikes_at(center, width), ("PE", "PE", "CE", "CE"), SIGNS, strict=True
    ):
        row = quotes.get((float(strike), kind))
        if row is None:
            raise ValueError("missing_leg_quote")
        meta = metadata.get(row.instrument_id)
        if meta is None or meta.lot_size is None:
            raise ValueError("missing_lot_metadata")
        invalid = {
            QualityFlag.CROSSED_BOOK,
            QualityFlag.INVALID_DEPTH,
            QualityFlag.STALE_QUOTE,
            QualityFlag.PARTIAL_BOOK,
        }
        if invalid.intersection(row.quality_flags):
            raise ValueError("invalid_quote_quality")
        age = (now - row.receive_ts).total_seconds()
        if not 0 <= age <= 3:
            raise ValueError("stale_or_future_quote")
        bid = row.best_bid
        ask = row.best_ask
        if bid is None or ask is None or not 0 < bid <= ask:
            raise ValueError("invalid_book")
        size = row.asks[0].quantity if sign > 0 else row.bids[0].quantity
        if size < meta.lot_size:
            raise ValueError("less_than_one_lot_at_bbo")
        k = math.log(float(strike) / slice_.forward)
        if not slice_.min_log_moneyness <= k <= slice_.max_log_moneyness:
            raise ValueError("wing_outside_surface_support")
        iv = math.sqrt(slice_.total_variance(k) / slice_.maturity_years)
        theoretical = black76_price(
            forward=slice_.forward,
            strike=float(strike),
            maturity_years=slice_.maturity_years,
            volatility=iv,
            risk_free_rate=rate,
            is_call=kind == "CE",
        )
        lot_sizes.add(meta.lot_size)
        legs.append(
            {
                "instrument_id": row.instrument_id,
                "strike": float(strike),
                "type": kind,
                "side": "BUY" if sign > 0 else "SELL",
                "bid": bid,
                "ask": ask,
                "iv": iv,
                "model_price": theoretical,
                "entry_price": ask if sign > 0 else bid,
                "tick_size": meta.tick_size,
                "half_spread": (ask - bid) / 2,
                "quantity_available": size,
                "quote_age_seconds": age,
                "quality_flags": [str(flag) for flag in row.quality_flags],
            }
        )
    if len(lot_sizes) != 1:
        raise ValueError("inconsistent_lot_sizes")
    lot = lot_sizes.pop()
    entry = np.array([x["entry_price"] for x in legs])
    ticks = np.array([x["tick_size"] for x in legs])
    assumed = np.maximum(0.0, entry + SIGNS * ticks)
    credit = -float(entry @ SIGNS)
    charge = float(fees(assumed[SIGNS > 0].sum(), assumed[SIGNS < 0].sum()))
    net = -float(assumed @ SIGNS) - charge
    if not 0 < credit < width or net <= 0:
        raise ValueError("nonviable_credit")
    spread = float(sum(x["half_spread"] for x in legs))
    slip = float(np.abs(assumed - entry).sum())
    g = greeks(
        slice_.forward,
        strikes_at(center, width),
        slice_.maturity_years,
        np.array([x["iv"] for x in legs]),
        rate,
    )
    return {
        "id": f"{int(center)}-{int(width)}",
        "center": center,
        "width": width,
        "lot_size": lot,
        "legs": legs,
        "expiry": slice_.expiry.isoformat(),
        "forward": slice_.forward,
        "credit_points": credit,
        "credit_rupees": credit * lot,
        "net_entry_credit_points": net,
        "model_credit_points": -sum(s * x["model_price"] for s, x in zip(SIGNS, legs, strict=True)),
        "mid_credit_points": -sum(
            s * (x["bid"] + x["ask"]) / 2 for s, x in zip(SIGNS, legs, strict=True)
        ),
        "entry_cost_points": spread + slip + charge,
        "entry_spread_slippage_points": spread + slip,
        "entry_fees_rupees": charge * lot,
        "entry_cost_rupees": (spread + slip + charge) * lot,
        "static_max_loss_before_exercise_tax": (
            width - net * math.exp(rate * slice_.maturity_years)
        )
        * lot,
        "max_profit_before_exercise_tax": net * math.exp(rate * slice_.maturity_years) * lot,
        "breakeven_low_before_exercise_tax": center - net * math.exp(rate * slice_.maturity_years),
        "breakeven_high_before_exercise_tax": center + net * math.exp(rate * slice_.maturity_years),
        "greeks_per_lot": {key: value * lot for key, value in g.items()},
        "available_lots": min(x["quantity_available"] // lot for x in legs),
    }


def build_butterflies(
    surface: ESSVISurface,
    rows: Sequence[TapeRow],
    metadata: Mapping[str, InstrumentMetadata],
    now: datetime,
    expiry_time: datetime,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    front = min(surface.slices, key=lambda s: s.maturity_years)
    if now.date() < date(2026, 4, 1):
        return {"status": "unavailable", "reason": "fee_schedule_effective_2026_04_01"}
    forecast = realized_volatility_forecast(
        atm_iv=math.sqrt(front.theta / front.maturity_years), maturity_years=front.maturity_years
    )
    times, next_open = schedule(now, expiry_time)
    fractions = np.array(
        [(x - now).total_seconds() / (expiry_time - now).total_seconds() for x in times]
    )
    open_index = times.index(next_open)
    checks = {
        i
        for i, x in enumerate(times)
        if x.time() == time(15, 15) and x.date() != expiry_time.date()
    }
    quote_map: dict[tuple[float, str], TapeRow] = {}
    for row in rows:
        parts = row.instrument_id.split(":")
        if (
            len(parts) == 7
            and parts[2] == "NIFTY"
            and parts[3] == "option"
            and parts[4] == front.expiry.isoformat()
        ):
            key = (float(parts[5]), parts[6])
            prev = quote_map.get(key)
            if prev is None or prev.receive_ts < row.receive_ts:
                quote_map[key] = row
    if not quote_map:
        return {"status": "unavailable", "reason": "nearest_weekly_nifty_only"}
    candidates = []
    rejected: Counter[str] = Counter()
    for width in (400.0, 500.0):
        for center in sorted({k[0] for k in quote_map}):
            if abs(center - front.forward) > width / 2:
                continue
            try:
                candidates.append(
                    candidate(center, width, front, quote_map, metadata, now, risk_free_rate)
                )
            except ValueError as error:
                rejected[str(error)] += 1
    common = []
    for name, rv_mult, iv_mult, friction, gap in SCENARIOS:
        path = scenario_paths(
            front.forward,
            forecast.forecast_annualized_realized_volatility * rv_mult,
            front.maturity_years,
            fractions,
            open_index,
            gap,
        )
        common.append((name, path, iv_mult, friction))
    for fly in candidates:
        outcomes = {
            name: simulate(
                row=fly,
                path=path,
                fractions=fractions,
                check_indices=checks,
                open_index=open_index,
                t=front.maturity_years,
                iv=forecast.atm_iv * iv_mult,
                rate=risk_free_rate,
                friction=friction,
            )
            for name, path, iv_mult, friction in common
        }
        fly["scenarios"] = outcomes
        base = outcomes["base"]
        g = fly["greeks_per_lot"]
        fly["gamma_theta_day"] = (
            g["theta_day"]
            + 0.5
            * g["gamma"]
            * front.forward**2
            * forecast.forecast_annualized_realized_volatility**2
            / 365.25
        )
        fly["carry_risk_ratio"] = (
            base["recenter"]["mean"] / fly["static_max_loss_before_exercise_tax"]
        )
        fly["worst_stress_mean"] = min(x["recenter"]["mean"] for x in outcomes.values())
        fly["signal_label"] = (
            "no_positive_scenario_edge"
            if base["recenter"]["mean"] <= 0
            else "within_monte_carlo_noise"
            if base["recenter"]["mean"] <= 2 * base["recenter"]["mc_se"]
            else "stress_sensitive"
            if fly["worst_stress_mean"] < 0
            else "positive_in_tested_scenarios"
        )
    candidates.sort(key=lambda x: (-x["carry_risk_ratio"], x["entry_cost_rupees"]))
    return {
        "status": "ok" if candidates else "unavailable",
        "reason": None if candidates else "no_eligible_four_leg_butterflies",
        "version": VERSION,
        "as_of": now.isoformat(),
        "expiry": front.expiry.isoformat(),
        "forward": front.forward,
        "forecast_rv": forecast.forecast_annualized_realized_volatility,
        "atm_iv": forecast.atm_iv,
        "next_open": next_open.isoformat(),
        "recenter_checks": [times[i].isoformat() for i in sorted(checks)],
        "path_count": PATHS,
        "candidates": candidates,
        "rejected": dict(rejected),
        "scope": "conditional_scenarios_not_validated_expected_returns",
        "margin": None,
        "margin_reason": "actual_broker_margin_not_requested",
        "rates": {
            "sell_stt": 0.0015,
            "exercise_stt": 0.0015,
            "exchange_ipft": 0.0003553,
            "sebi": 0.000001,
            "gst": 0.18,
            "buy_stamp": 0.00003,
            "brokerage_per_order": 0.0,
        },
    }
