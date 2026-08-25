#!/usr/bin/env python3
"""Which option structure, if any, monetises the Gate-B directional spot signal?

New module.  It does not modify, and is not imported by, any pre-existing script.

The research question
---------------------
Every Gate-B test so far has bought one at-the-money CALL and varied the exit.  All 39
exit rules in ``gate_b_exit_grid_real.py`` and all 45 in ``gate_b_early_exit_scan.py``
lose.  An at-the-money option carries the maximum theta and the maximum vega per rupee of
delta, so it is the worst available vehicle for a modest directional view.  This module
asks the question nobody has asked: **given the measured spot edge, is there an instrument
that monetises it?**

Structure of the study
----------------------
A.  The spot edge measured on its own, in INDEX POINTS, options entirely aside.
B.  The break-even hurdle in points for every candidate structure at every horizon,
    read against the empirical distribution from A.
C.  Backtest of ten structure families on real strike-tracked traded premiums.
D.  Greek decomposition under a TRADING-TIME maturity convention.
E.  Capital feasibility at Aryan's Rs 10,000 weekly budget, NIFTY lot size 75.
F.  Multiplicity: Bonferroni, Benjamini-Hochberg, and a shuffled-label best-of-grid
    placebo scored against the distribution of best-of-grid p-values.
G.  Power.

Conventions that are NOT negotiable here
----------------------------------------
* **Trading-time maturity.**  ``CORRECTION_GATE_B_VOL_CRUSH.md`` retracted the "volatility
  crush" finding: implied volatility in this project had been inverted with a CALENDAR-time
  maturity, which mechanically depresses IV across a session on short-dated options.  Every
  implied volatility and every Greek below uses trading minutes to expiry over a 375-minute
  session and a 252-session year.  Quoted IVs here are therefore NOT comparable to the
  calendar-convention numbers in ``GATE_B_REAL_PREMIUM_VALIDATION.md``.
* **Real strike-tracked traded premiums.**  Every leg is priced from the one-minute bar
  close of the ACTUAL contract, looked up by absolute strike, never from a labelled-ATM
  series that rolls strike mid-session.
* **Rupees per lot is the primary metric.**  Percentage-of-entry-premium cannot compare a
  long call against a credit structure against futures, because the denominators are
  different objects.  Percentages are reported alongside for the long-premium structures so
  the numbers tie back to the published Gate-B evidence.

Offline analysis only.  No broker, credential, exchange network, or order path is used
anywhere in this module.  No live order is authorised.
"""
from __future__ import annotations

import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq
from scipy.stats import norm

import gate_b_common as gbc
import gate_b_full_paths as gfp
from bs_gap_fill_pnl import RISK_FREE_RATE, STRIKE_STEP, bs_call

# --------------------------------------------------------------------------- constants
LOT_SIZE = 75

SESSION_OPEN_MIN = 9 * 60 + 15       # 09:15
SESSION_CLOSE_MIN = 15 * 60 + 30     # 15:30, the contract expiry stamp
TRADING_MINUTES_PER_DAY = SESSION_CLOSE_MIN - SESSION_OPEN_MIN     # 375
TRADING_DAYS_PER_YEAR = 252

HORIZONS = (15, 30, 45, 60, 90, 120, None)   # None == hold to 15:29
HORIZON_LABEL = {15: "15m", 30: "30m", 45: "45m", 60: "60m", 90: "90m",
                 120: "120m", None: "close"}

# Favourable / adverse spot thresholds in index points (section A).
THRESHOLDS = (25, 50, 75, 100, 150, 200)

# --- transaction costs -----------------------------------------------------------------
# Options, per leg, per side.  A pure proportional half-spread badly understates the cost
# of a cheap out-of-the-money weekly, which is exactly the direction that would manufacture
# a false positive for the OTM structures this study exists to test.  A floor is therefore
# imposed in absolute index points as well.
OPT_HALF_SPREAD_PCT   = 0.0035     # 0.35% of premium, the base case used project-wide
OPT_HALF_SPREAD_FLOOR = 0.25       # index points, ~5 ticks of the Rs 0.05 tick
OPT_HALF_SPREAD_PCT_PESS   = 0.0100
OPT_HALF_SPREAD_FLOOR_PESS = 0.75

FUT_HALF_SPREAD_PTS      = 0.25    # NIFTY front-month future, index points per side
FUT_HALF_SPREAD_PTS_PESS = 1.00

BROKERAGE_PER_ORDER = 20.0         # flat, discount broker
GST_RATE = 0.18

OPT_STT_SELL   = 0.001000          # 0.10% of premium value, sell side (post 2024-10-01)
OPT_TXN_RATE   = 0.0003503         # NSE F&O options, premium value, each side
OPT_STAMP_BUY  = 0.00003           # 0.003% of premium value, buy side
FUT_STT_SELL   = 0.000200          # 0.02% of notional turnover, sell side
FUT_TXN_RATE   = 0.0000173         # NSE index futures, notional turnover, each side
FUT_STAMP_BUY  = 0.00002           # 0.002% of notional turnover, buy side
SEBI_RATE      = 0.000001          # Rs 10 per crore of turnover, each side

# --- capital ---------------------------------------------------------------------------
BUDGET_RUPEES = 10_000.0
# SPAN + exposure on one NIFTY lot, stated as a fraction of notional.  Naked short index
# options and index futures both sit in this band at Indian brokers; 12% is the central
# assumption and it is carried as an assumption, not a measurement.
MARGIN_FRAC_OF_NOTIONAL = 0.12

# Cost of carry used to turn the spot path into a futures path.  No futures tape exists in
# the local archive, so the futures leg is DERIVED, not observed, and this is the assumption
# it rests on: r - q net of NIFTY's dividend yield.
FUT_CARRY_NET = 0.02

N_PLACEBO = 5000
SEED = 20260823

QUOTE_CACHE = Path("gate_b_structure_quotes.pkl")


def clock_to_minutes(clock: str) -> int:
    hh, mm = clock.split(":")
    return int(hh) * 60 + int(mm)


# ============================================================ trading-time maturity
def session_dates() -> np.ndarray:
    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    return np.asarray(sorted(dm["date"].dt.normalize().unique()), dtype="datetime64[D]")


def trading_minutes_to_expiry(date_str: str, clock_min: int, expiry_str: str,
                              sessions: np.ndarray) -> float:
    """Trading minutes from ``clock_min`` on ``date_str`` to 15:30 on the expiry date."""
    d = np.datetime64(pd.Timestamp(date_str).normalize(), "D")
    e = np.datetime64(pd.Timestamp(expiry_str).normalize(), "D")
    today = max(0.0, float(SESSION_CLOSE_MIN - clock_min))
    if e <= d:
        return today
    between = sessions[(sessions > d) & (sessions <= e)]
    return today + TRADING_MINUTES_PER_DAY * float(len(between))


def trading_T(date_str: str, clock_min: int, expiry_str: str, sessions: np.ndarray) -> float:
    m = trading_minutes_to_expiry(date_str, clock_min, expiry_str, sessions)
    return max(m / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR), 1e-9)


# ============================================================ Black-Scholes plumbing
def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    return bs_call(S, K, T, r, sigma) if kind == "CALL" else bs_put(S, K, T, r, sigma)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> dict:
    """Delta, gamma, vega, theta.  Theta is returned per TRADING MINUTE."""
    if T <= 0 or sigma <= 0:
        d = 1.0 if (kind == "CALL" and S > K) else (-1.0 if (kind == "PUT" and S < K) else 0.0)
        return {"delta": d, "gamma": 0.0, "vega": 0.0, "theta_min": 0.0}
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    pdf = norm.pdf(d1)
    gamma = pdf / (S * sq)
    vega = S * pdf * math.sqrt(T)                      # per 1.00 of vol (i.e. 100 vol pts)
    if kind == "CALL":
        delta = norm.cdf(d1)
        theta_yr = -S * pdf * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        delta = norm.cdf(d1) - 1.0
        theta_yr = -S * pdf * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm.cdf(-d2)
    return {
        "delta": delta, "gamma": gamma, "vega": vega,
        "theta_min": theta_yr / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR),
    }


def implied_vol(price: float, S: float, K: float, T: float, r: float, kind: str) -> float:
    """Invert Black-Scholes for sigma under the TRADING-TIME maturity already supplied."""
    if not np.isfinite(price) or price <= 0 or T <= 0:
        return float("nan")
    if kind == "CALL":
        lo, hi = max(S - K * math.exp(-r * T), 0.0), S
    else:
        lo, hi = max(K * math.exp(-r * T) - S, 0.0), K * math.exp(-r * T)
    if not (lo + 1e-8 < price < hi - 1e-8):
        return float("nan")
    try:
        return float(brentq(lambda s: bs_price(S, K, T, r, s, kind) - price,
                            1e-4, 5.0, xtol=1e-10))
    except ValueError:
        return float("nan")


# ============================================================ traded quotes, both types
def load_quotes(rebuild: bool = False) -> dict:
    """CALL and PUT one-minute bar closes for every relevant date.

    Returned as ``{date: {(kind, strike): {clock: (close, high, low)}}}``.  Trimmed to the
    264 dates in the Gate-B parent pool, which is what makes a combined CALL+PUT cache
    small enough to hold in memory.
    """
    if QUOTE_CACHE.exists() and not rebuild:
        with QUOTE_CACHE.open("rb") as handle:
            return pickle.load(handle)

    paths = gfp.load_full_paths()
    want_dates = {p["date"] for p in paths}

    book: dict[str, dict] = {}
    kept = 0
    for row in gbc.manifest_rows():
        kind = row.get("drv_option_type")
        if kind not in ("CALL", "PUT"):
            continue
        f = gbc.cached_path(row)
        if not f.exists():
            continue
        df = pd.read_csv(f, usecols=["close", "high", "low", "strike", "datetime", "volume"])
        df["date"] = df["datetime"].str.slice(0, 10)
        df = df[df["date"].isin(want_dates)]
        if df.empty:
            continue
        df = df[df["close"] > 0]
        if df.empty:
            continue
        df["clock"] = df["datetime"].str.slice(11, 16)
        df = df.sort_values(["date", "clock", "strike", "volume"], ascending=[1, 1, 1, 0])
        df = df.drop_duplicates(subset=["date", "clock", "strike"], keep="first")
        for (d, k), g in df.groupby(["date", "strike"]):
            slot = book.setdefault(d, {}).setdefault((kind, float(k)), {})
            slot.update(dict(zip(g["clock"],
                                 zip(g["close"].astype(float),
                                     g["high"].astype(float),
                                     g["low"].astype(float)))))
            kept += len(g)

    with QUOTE_CACHE.open("wb") as handle:
        pickle.dump(book, handle, protocol=4)
    print(f"  quote cache built: {kept:,} bars over {len(book):,} dates")
    return book


# ============================================================ A. the spot edge, in points
def spot_index_at(path: dict, offset: int | None) -> int:
    """Index of the last observed minute at or before ``offset`` minutes after entry."""
    if offset is None:
        return len(path["clocks"]) - 1
    eligible = np.flatnonzero(path["elapsed"] <= offset)
    return int(eligible[-1]) if len(eligible) else 0


def spot_move(path: dict, offset: int | None) -> float:
    """Favourable (upward) spot move from entry, in INDEX POINTS."""
    i = spot_index_at(path, offset)
    return float(path["spots"][i] - path["spots"][0])


def describe_points(vals: np.ndarray) -> dict:
    v = vals[np.isfinite(vals)]
    if len(v) == 0:
        return {}
    t = stats.ttest_1samp(v, 0.0) if len(v) > 1 else None
    return {
        "n": int(len(v)), "mean": float(v.mean()), "median": float(np.median(v)),
        "q1": float(np.percentile(v, 25)), "q3": float(np.percentile(v, 75)),
        "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90)),
        "sd": float(v.std(ddof=1)) if len(v) > 1 else float("nan"),
        "up_pct": float((v > 0).mean() * 100.0),
        "p": float(t.pvalue) if t is not None else float("nan"),
    }


def section_a(paths: list[dict], label: str) -> dict:
    out: dict = {"population": label, "n": len(paths)}

    # --- distribution of the favourable move at each horizon ---------------------------
    rows = []
    for h in HORIZONS:
        mv = np.asarray([spot_move(p, h) for p in paths], dtype=float)
        held = np.asarray([float(p["elapsed"][spot_index_at(p, h)]) for p in paths])
        d = describe_points(mv)
        d["horizon"] = HORIZON_LABEL[h]
        d["mean_minutes_held"] = float(held.mean())
        d["pts_per_min"] = d["mean"] / held.mean() if held.mean() > 0 else float("nan")
        rows.append(d)
    out["horizon_distribution"] = rows

    # --- maximum favourable / adverse excursion and their timing -----------------------
    mfe, mae, t_mfe, t_mae = [], [], [], []
    for p in paths:
        s = p["spots"].astype(float)
        e = p["elapsed"].astype(float)
        rel = s - s[0]
        i_hi, i_lo = int(np.argmax(rel)), int(np.argmin(rel))
        mfe.append(rel[i_hi]); t_mfe.append(e[i_hi])
        mae.append(rel[i_lo]); t_mae.append(e[i_lo])
    out["mfe"] = describe_points(np.asarray(mfe))
    out["mae"] = describe_points(np.asarray(mae))
    out["mfe_minutes"] = describe_points(np.asarray(t_mfe))
    out["mae_minutes"] = describe_points(np.asarray(t_mae))

    # --- how many days ever reach +X points, and when ----------------------------------
    reach = []
    for thr in THRESHOLDS:
        hit, when = [], []
        for p in paths:
            rel = p["spots"].astype(float) - float(p["spots"][0])
            idx = np.flatnonzero(rel >= thr)
            hit.append(len(idx) > 0)
            if len(idx):
                when.append(float(p["elapsed"][idx[0]]))
        hit = np.asarray(hit)
        reach.append({
            "threshold_pts": thr,
            "ever_reached_pct": float(hit.mean() * 100.0),
            "n_reached": int(hit.sum()),
            "median_minutes_to_first_touch": float(np.median(when)) if when else float("nan"),
            "q1_minutes": float(np.percentile(when, 25)) if when else float("nan"),
            "q3_minutes": float(np.percentile(when, 75)) if when else float("nan"),
        })
    out["favourable_thresholds"] = reach

    adverse = []
    for thr in THRESHOLDS:
        hit = []
        for p in paths:
            rel = p["spots"].astype(float) - float(p["spots"][0])
            hit.append(bool((rel <= -thr).any()))
        adverse.append({"threshold_pts": -thr,
                        "ever_reached_pct": float(np.mean(hit) * 100.0)})
    out["adverse_thresholds"] = adverse

    # --- the rate through the session, wall clock --------------------------------------
    buckets = [("09:15", "09:30"), ("09:30", "10:00"), ("10:00", "10:30"),
               ("10:30", "11:00"), ("11:00", "11:30"), ("11:30", "12:00"),
               ("12:00", "12:30"), ("12:30", "13:00"), ("13:00", "13:30"),
               ("13:30", "14:00"), ("14:00", "14:30"), ("14:30", "15:00"),
               ("15:00", "15:29")]
    brows = []
    for lo, hi in buckets:
        lo_m, hi_m = clock_to_minutes(lo), clock_to_minutes(hi)
        inc = []
        for p in paths:
            minutes = p["entry_minute"] + p["elapsed"]
            sel = np.flatnonzero((minutes >= lo_m) & (minutes <= hi_m))
            if len(sel) < 2:
                continue
            inc.append(float(p["spots"][sel[-1]] - p["spots"][sel[0]]))
        inc = np.asarray(inc, dtype=float)
        if len(inc) < 2:
            brows.append({"bucket": f"{lo}-{hi}", "n": len(inc)})
            continue
        d = describe_points(inc)
        d["bucket"] = f"{lo}-{hi}"
        d["minutes"] = hi_m - lo_m
        d["pts_per_min"] = d["mean"] / (hi_m - lo_m)
        brows.append(d)
    out["session_rate"] = brows

    # --- spot level, so points can be read as percentages if wanted --------------------
    out["entry_spot"] = describe_points(np.asarray([float(p["spots"][0]) for p in paths]))
    out["entry_minute_clock"] = {
        "median": float(np.median([p["entry_minute"] for p in paths])),
        "min": int(min(p["entry_minute"] for p in paths)),
        "max": int(max(p["entry_minute"] for p in paths)),
    }
    return out


# ============================================================ B/C. candidate structures
class Leg:
    """One option or futures leg of a structure."""

    __slots__ = ("kind", "strike", "qty", "entry_px", "iv", "T0", "greeks")

    def __init__(self, kind: str, strike: float, qty: int, entry_px: float,
                 iv: float, T0: float, greeks: dict):
        self.kind = kind          # "CALL", "PUT" or "FUT"
        self.strike = strike
        self.qty = qty            # +1 long, -1 short
        self.entry_px = entry_px
        self.iv = iv
        self.T0 = T0
        self.greeks = greeks


_ENTRY_BOOK_CACHE: dict = {}


def entry_book(path: dict, quotes: dict, sessions: np.ndarray,
               kind: str) -> list[dict]:
    """Every strike of ``kind`` quoted at the entry minute, with trading-time IV and delta.

    Strike selection uses entry-minute information only.  The implied volatility is
    inverted from that strike's OWN traded price, so the selection respects the observed
    smile rather than assuming a flat surface.
    """
    ck = (path["date"], path["entry_clock"], kind)
    if ck in _ENTRY_BOOK_CACHE:
        return _ENTRY_BOOK_CACHE[ck]
    day = quotes.get(path["date"], {})
    S0, clock = float(path["spots"][0]), path["entry_clock"]
    T0 = trading_T(path["date"], path["entry_minute"], path["expiry"], sessions)
    rows = []
    for (k, strike), series in day.items():
        if k != kind or clock not in series:
            continue
        px = float(series[clock][0])
        if not np.isfinite(px) or px <= 0:
            continue
        iv = implied_vol(px, S0, strike, T0, RISK_FREE_RATE, kind)
        if not np.isfinite(iv):
            continue
        g = bs_greeks(S0, strike, T0, RISK_FREE_RATE, iv, kind)
        rows.append({"strike": float(strike), "px": px, "iv": iv, "T0": T0, **g})
    rows = sorted(rows, key=lambda r: r["strike"])
    _ENTRY_BOOK_CACHE[ck] = rows
    return rows


def pick_by_delta(book: list[dict], target: float) -> dict | None:
    if not book:
        return None
    return min(book, key=lambda r: abs(abs(r["delta"]) - abs(target)))


def pick_by_strike(book: list[dict], strike: float) -> dict | None:
    for r in book:
        if np.isclose(r["strike"], strike):
            return r
    return None


def make_leg(row: dict, kind: str, qty: int) -> Leg:
    return Leg(kind, row["strike"], qty, row["px"], row["iv"], row["T0"],
               {"delta": row["delta"], "gamma": row["gamma"],
                "vega": row["vega"], "theta_min": row["theta_min"]})


def carry_mult(date_str: str, clock_min: int, monthly_expiry: str) -> float:
    """F/S at one instant.  Calendar tau, because carry accrues in calendar time."""
    d = pd.Timestamp(date_str) + pd.Timedelta(minutes=clock_min - SESSION_OPEN_MIN)
    e = pd.Timestamp(monthly_expiry) + pd.Timedelta(hours=15, minutes=30)
    tau = max((e - d).total_seconds() / (365.0 * 24 * 3600), 0.0)
    return math.exp(FUT_CARRY_NET * tau)


def futures_price(S: float, date_str: str, clock_min: int, sessions: np.ndarray,
                  monthly_expiry: str) -> float:
    """DERIVED, not observed: no futures tape exists in the local archive.

    F = S * exp((r - q) * tau) with tau in CALENDAR years to the monthly expiry, because
    carry accrues in calendar time even though variance does not.
    """
    return S * carry_mult(date_str, clock_min, monthly_expiry)


STRUCTURES = (
    ("long ATM call",              "atm_call"),
    ("long ITM call ~0.70d",       "itm70_call"),
    ("long deep ITM call ~0.85d",  "itm85_call"),
    ("long OTM call ~0.30d",       "otm30_call"),
    ("bull call spread 1 strike",  "bcs1"),
    ("bull call spread 2 strikes", "bcs2"),
    ("bull call spread 3 strikes", "bcs3"),
    ("short OTM put ~0.25d",       "short_otm_put"),
    ("short ATM put",              "short_atm_put"),
    ("risk reversal +0.30c/-0.25p", "risk_reversal"),
    ("long NIFTY futures",         "futures"),
)


def build_structure(path: dict, quotes: dict, sessions: np.ndarray, key: str,
                    monthly_expiry: str) -> list[Leg] | None:
    """Legs of one structure at the entry minute, or None when it cannot be constructed."""
    if key == "futures":
        S0 = float(path["spots"][0])
        F0 = futures_price(S0, path["date"], path["entry_minute"], sessions, monthly_expiry)
        return [Leg("FUT", float("nan"), +1, F0, float("nan"), float("nan"),
                    {"delta": 1.0, "gamma": 0.0, "vega": 0.0, "theta_min": 0.0})]

    calls = entry_book(path, quotes, sessions, "CALL")
    puts = entry_book(path, quotes, sessions, "PUT")
    atm_k = float(round(float(path["spots"][0]) / STRIKE_STEP) * STRIKE_STEP)

    if key == "atm_call":
        r = pick_by_strike(calls, atm_k)
        return [make_leg(r, "CALL", +1)] if r else None
    if key == "itm70_call":
        r = pick_by_delta(calls, 0.70)
        return [make_leg(r, "CALL", +1)] if r else None
    if key == "itm85_call":
        r = pick_by_delta(calls, 0.85)
        return [make_leg(r, "CALL", +1)] if r else None
    if key == "otm30_call":
        r = pick_by_delta(calls, 0.30)
        return [make_leg(r, "CALL", +1)] if r else None
    if key in ("bcs1", "bcs2", "bcs3"):
        w = int(key[-1])
        lo = pick_by_strike(calls, atm_k)
        hi = pick_by_strike(calls, atm_k + w * STRIKE_STEP)
        if lo is None or hi is None:
            return None
        return [make_leg(lo, "CALL", +1), make_leg(hi, "CALL", -1)]
    if key == "short_otm_put":
        r = pick_by_delta(puts, 0.25)
        return [make_leg(r, "PUT", -1)] if r else None
    if key == "short_atm_put":
        r = pick_by_strike(puts, atm_k)
        return [make_leg(r, "PUT", -1)] if r else None
    if key == "risk_reversal":
        c = pick_by_delta(calls, 0.30)
        p = pick_by_delta(puts, 0.25)
        if c is None or p is None:
            return None
        return [make_leg(c, "CALL", +1), make_leg(p, "PUT", -1)]
    raise KeyError(key)


def leg_exit_price(path: dict, quotes: dict, sessions: np.ndarray, leg: Leg,
                   offset: int | None, monthly_expiry: str) -> float:
    """Traded exit price of one leg, or NaN when the contract is not quoted near the exit.

    A two-minute grace is allowed at the exit clock, matching the convention already used
    in ``gate_b_common.rule_return``.
    """
    i = spot_index_at(path, offset)
    if leg.kind == "FUT":
        S = float(path["spots"][i])
        return futures_price(S, path["date"], path["entry_minute"] + int(path["elapsed"][i]),
                             sessions, monthly_expiry)
    series = quotes.get(path["date"], {}).get((leg.kind, leg.strike))
    if not series:
        return float("nan")
    for back in range(0, 3):
        j = i - back
        if j < 0:
            break
        c = path["clocks"][j]
        if c in series:
            return float(series[c][0])
    return float("nan")


def structure_value(legs: list[Leg], prices: list[float]) -> float:
    """Signed value of the structure in index points.  Positive = the position is an asset."""
    return float(sum(l.qty * px for l, px in zip(legs, prices)))


# ============================================================ costs, per leg, in rupees
def leg_cost_rupees(leg: Leg, entry_px: float, exit_px: float, pessimistic: bool) -> float:
    """Round-trip transaction cost of ONE leg, in rupees, for one lot of ``LOT_SIZE``.

    Every leg is opened and closed, so every leg pays the spread twice, brokerage twice and
    the statutory charges on both sides.  Multi-leg structures therefore pay these costs
    once per leg, which is the point of counting them this way.
    """
    if leg.kind == "FUT":
        hs = FUT_HALF_SPREAD_PTS_PESS if pessimistic else FUT_HALF_SPREAD_PTS
        buy_turn = entry_px * LOT_SIZE if leg.qty > 0 else exit_px * LOT_SIZE
        sell_turn = exit_px * LOT_SIZE if leg.qty > 0 else entry_px * LOT_SIZE
        spread = hs * LOT_SIZE * 2
        brokerage = 2 * BROKERAGE_PER_ORDER
        txn = FUT_TXN_RATE * (buy_turn + sell_turn)
        stt = FUT_STT_SELL * sell_turn
        stamp = FUT_STAMP_BUY * buy_turn
        sebi = SEBI_RATE * (buy_turn + sell_turn)
        return spread + brokerage + txn + stt + stamp + sebi + GST_RATE * (brokerage + txn)

    pct = OPT_HALF_SPREAD_PCT_PESS if pessimistic else OPT_HALF_SPREAD_PCT
    floor = OPT_HALF_SPREAD_FLOOR_PESS if pessimistic else OPT_HALF_SPREAD_FLOOR
    hs_in = max(floor, pct * max(entry_px, 0.0))
    hs_out = max(floor, pct * max(exit_px, 0.0))
    buy_val = entry_px * LOT_SIZE if leg.qty > 0 else exit_px * LOT_SIZE
    sell_val = exit_px * LOT_SIZE if leg.qty > 0 else entry_px * LOT_SIZE
    buy_val, sell_val = max(buy_val, 0.0), max(sell_val, 0.0)
    spread = (hs_in + hs_out) * LOT_SIZE
    brokerage = 2 * BROKERAGE_PER_ORDER
    txn = OPT_TXN_RATE * (buy_val + sell_val)
    stt = OPT_STT_SELL * sell_val
    stamp = OPT_STAMP_BUY * buy_val
    sebi = SEBI_RATE * (buy_val + sell_val)
    return spread + brokerage + txn + stt + stamp + sebi + GST_RATE * (brokerage + txn)


def structure_costs(legs: list[Leg], exits: list[float], pessimistic: bool) -> float:
    return float(sum(leg_cost_rupees(l, l.entry_px, px, pessimistic)
                     for l, px in zip(legs, exits)))


# ============================================================ capital required, in rupees
def capital_required(legs: list[Leg], S0: float) -> dict:
    """Rupees that must be available before the trade can be placed, for one lot.

    * Net-debit structures (every leg long, or a debit spread whose short leg is fully
      covered by a long leg at a lower strike) require the debit only.
    * Any structure carrying a NAKED short option, or a futures position, requires
      SPAN + exposure margin, taken here as ``MARGIN_FRAC_OF_NOTIONAL`` of notional.
      That fraction is an ASSUMPTION, not a measurement from this dataset.
    """
    notional = S0 * LOT_SIZE
    net_debit = sum(l.qty * l.entry_px for l in legs) * LOT_SIZE

    has_fut = any(l.kind == "FUT" for l in legs)
    shorts = [l for l in legs if l.qty < 0 and l.kind in ("CALL", "PUT")]
    longs = [l for l in legs if l.qty > 0 and l.kind in ("CALL", "PUT")]

    covered = True
    for s in shorts:
        same = [l for l in longs if l.kind == s.kind]
        if s.kind == "CALL":
            ok = any(l.strike <= s.strike for l in same)
        else:
            ok = any(l.strike >= s.strike for l in same)
        if not ok:
            covered = False
            break

    if has_fut:
        return {"kind": "margin", "rupees": MARGIN_FRAC_OF_NOTIONAL * notional,
                "net_debit": net_debit}
    if shorts and not covered:
        margin = MARGIN_FRAC_OF_NOTIONAL * notional
        # a credit received reduces the cash that must be found
        return {"kind": "margin", "rupees": max(margin + net_debit, 0.0),
                "net_debit": net_debit}
    return {"kind": "debit", "rupees": max(net_debit, 0.0), "net_debit": net_debit}


# ============================================================ B. the break-even hurdle
def breakeven_move(legs: list[Leg], S0: float, T0: float, T_H: float,
                   cost_rupees: float, fut_mult: float = 1.0) -> float:
    """Spot move in INDEX POINTS required for the structure to break even at horizon H.

    Scenario assumption, stated: implied volatility of every leg is held at its ENTRY value
    and time is advanced from ``T0`` to ``T_H`` in TRADING time.  Every structure here is
    long delta, so structure value is monotone increasing in spot and the break-even is the
    unique root.  ``cost_rupees`` is added so the hurdle is the move required to clear
    transaction costs too; pass 0.0 for the gross hurdle.

    ``fut_mult`` is F/S at the HORIZON.  A futures leg is closed at a futures price, not at
    spot, so its horizon value is ``S * fut_mult``.  Without this the root-finder equates an
    entry FUTURES price against an exit SPOT level and returns the whole cost-of-carry basis
    (~19 index points here) as a phantom hurdle.  Options need no such factor: they are
    settled on the index itself.
    """
    entry_value = sum(l.qty * l.entry_px for l in legs)

    def value_at(S: float) -> float:
        tot = 0.0
        for l in legs:
            if l.kind == "FUT":
                tot += l.qty * S * fut_mult
            else:
                tot += l.qty * bs_price(S, l.strike, max(T_H, 1e-9), RISK_FREE_RATE,
                                        l.iv, l.kind)
        return tot

    target = entry_value + cost_rupees / LOT_SIZE
    f = lambda S: value_at(S) - target
    lo, hi = S0 * 0.80, S0 * 1.25
    try:
        if f(lo) > 0:          # already profitable at the low bound
            return float(lo - S0)
        if f(hi) < 0:          # unreachable inside +-25%
            return float("nan")
        return float(brentq(f, lo, hi, xtol=1e-6) - S0)
    except ValueError:
        return float("nan")


# ============================================================ the per-trade evaluation
def monthly_expiries() -> list[pd.Timestamp]:
    """Last weekly expiry of each calendar month, i.e. the index-futures expiry."""
    cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
    e = cal["actual_expiry"].dt.normalize()
    by_month = e.groupby([e.dt.year, e.dt.month]).max()
    return sorted(by_month.tolist())


def next_monthly(date_str: str, months: list[pd.Timestamp]) -> str:
    d = pd.Timestamp(date_str).normalize()
    for m in months:
        if m >= d:
            return str(m.date())
    return str(months[-1].date())


def evaluate(paths: list[dict], quotes: dict, sessions: np.ndarray,
             months: list[pd.Timestamp], key: str, offset: int | None,
             pessimistic: bool = False, next_weekly: bool = False) -> pd.DataFrame:
    """One structure at one horizon, evaluated on every path.

    ``next_weekly=True`` re-prices the SAME strikes on the following weekly expiry using
    each leg's entry implied volatility and a trading-time maturity five sessions longer.
    The archive contains WEEK1 contracts only, so that arm is MODEL-BASED (scenario), and
    it is reported separately from the traded-premium arms and never pooled with them.
    """
    rows = []
    for p in paths:
        mexp = next_monthly(p["date"], months)
        legs = build_structure(p, quotes, sessions, key, mexp)
        if legs is None:
            rows.append({"date": p["date"], "ok": False})
            continue

        S0 = float(p["spots"][0])
        i_exit = spot_index_at(p, offset)
        S_H = float(p["spots"][i_exit])
        held = float(p["elapsed"][i_exit])
        exit_min = p["entry_minute"] + int(held)
        T0 = trading_T(p["date"], p["entry_minute"], p["expiry"], sessions)
        T_H = trading_T(p["date"], exit_min, p["expiry"], sessions)

        if next_weekly:
            # shift both maturities forward by one weekly cycle (5 sessions)
            shift = 5 * TRADING_MINUTES_PER_DAY / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR)
            T0n, T_Hn = T0 + shift, T_H + shift
            new_legs, entries, exits = [], [], []
            for l in legs:
                if l.kind == "FUT":
                    new_legs.append(l)
                    entries.append(l.entry_px)
                    exits.append(leg_exit_price(p, quotes, sessions, l, offset, mexp))
                    continue
                e_px = bs_price(S0, l.strike, T0n, RISK_FREE_RATE, l.iv, l.kind)
                x_px = bs_price(S_H, l.strike, T_Hn, RISK_FREE_RATE, l.iv, l.kind)
                g = bs_greeks(S0, l.strike, T0n, RISK_FREE_RATE, l.iv, l.kind)
                new_legs.append(Leg(l.kind, l.strike, l.qty, e_px, l.iv, T0n, g))
                entries.append(e_px)
                exits.append(x_px)
            legs = new_legs
            T0, T_H = T0n, T_Hn
        else:
            entries = [l.entry_px for l in legs]
            exits = [leg_exit_price(p, quotes, sessions, l, offset, mexp) for l in legs]

        if not all(np.isfinite(x) for x in exits):
            rows.append({"date": p["date"], "ok": False})
            continue

        entry_value = structure_value(legs, entries)
        exit_value = structure_value(legs, exits)
        gross = (exit_value - entry_value) * LOT_SIZE
        cost = structure_costs(legs, exits, False)
        cost_pess = structure_costs(legs, exits, True)
        cap = capital_required(legs, S0)

        fut_mult = carry_mult(p["date"], exit_min, mexp)
        h_gross = breakeven_move(legs, S0, T0, T_H, 0.0, fut_mult)
        h_net = breakeven_move(legs, S0, T0, T_H, cost, fut_mult)

        rows.append({
            "date": p["date"], "ok": True, "is_gate_b": p["is_gate_b"],
            "entry_clock": p["entry_clock"], "S0": S0, "S_H": S_H,
            "spot_move_pts": S_H - S0, "minutes_held": held,
            "n_legs": len(legs),
            "strikes": "/".join("FUT" if l.kind == "FUT" else f"{l.kind[0]}{l.strike:.0f}"
                                for l in legs),
            "entry_value_pts": entry_value,
            "exit_value_pts": exit_value,
            "entry_delta": float(sum(l.qty * l.greeks["delta"] for l in legs)),
            "entry_gamma": float(sum(l.qty * l.greeks["gamma"] for l in legs)),
            "entry_vega": float(sum(l.qty * l.greeks["vega"] for l in legs)),
            "entry_theta_min": float(sum(l.qty * l.greeks["theta_min"] for l in legs)),
            "gross_rupees": gross,
            "cost_rupees": cost,
            "net_rupees": gross - cost,
            "cost_pess_rupees": cost_pess,
            "net_pess_rupees": gross - cost_pess,
            "capital_kind": cap["kind"],
            "capital_rupees": cap["rupees"],
            "hurdle_gross_pts": h_gross,
            "hurdle_net_pts": h_net,
            "cleared_gross": bool(np.isfinite(h_gross) and (S_H - S0) >= h_gross),
            "cleared_net": bool(np.isfinite(h_net) and (S_H - S0) >= h_net),
            "T0_trading_days": T0 * TRADING_DAYS_PER_YEAR,
        })
    return pd.DataFrame(rows)


def summarise_rupees(df: pd.DataFrame, col: str) -> dict:
    if df.empty or "ok" not in df:
        return {"n": 0}
    d = df[df["ok"] == True]
    v = d[col].to_numpy(dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 2:
        return {"n": int(len(v))}
    return {
        "n": int(len(v)),
        "mean": float(v.mean()), "median": float(np.median(v)),
        "sd": float(v.std(ddof=1)),
        "win_pct": float((v > 0).mean() * 100.0),
        "p": float(stats.ttest_1samp(v, 0.0).pvalue),
        "wilcoxon_p": float(stats.wilcoxon(v).pvalue) if np.any(v != 0) else float("nan"),
        "total": float(v.sum()),
    }


# ============================================================ D. Greek decomposition
def decompose(paths: list[dict], quotes: dict, sessions: np.ndarray,
              months: list[pd.Timestamp], key: str, offset: int | None) -> pd.DataFrame:
    """Split realised structure P&L into delta, gamma, theta and vega, in RUPEES per lot.

    Greeks are taken at entry under a TRADING-TIME maturity.  Each leg's exit implied
    volatility is re-inverted from its own traded exit price at the trading-time maturity
    remaining, so the vega leg is measured, not assumed.

        delta_pnl = D0 * dS
        gamma_pnl = 0.5 * G0 * dS^2
        theta_pnl = Theta_per_trading_minute * trading minutes elapsed
        vega_pnl  = V0 * (sigma_H - sigma_0)
        residual  = realised - (delta + gamma + theta + vega)

    The residual carries higher-order and cross terms and any Black-Scholes
    mis-specification.  It is reported, never assumed away.
    """
    rows = []
    for p in paths:
        mexp = next_monthly(p["date"], months)
        legs = build_structure(p, quotes, sessions, key, mexp)
        if legs is None:
            continue
        S0 = float(p["spots"][0])
        i = spot_index_at(p, offset)
        S_H = float(p["spots"][i])
        dS = S_H - S0
        held = float(p["elapsed"][i])
        exit_min = p["entry_minute"] + int(held)
        T_H = trading_T(p["date"], exit_min, p["expiry"], sessions)

        d_pnl = g_pnl = t_pnl = v_pnl = real = 0.0
        bad = False
        for l in legs:
            x = leg_exit_price(p, quotes, sessions, l, offset, mexp)
            if not np.isfinite(x):
                bad = True
                break
            real += l.qty * (x - l.entry_px)
            if l.kind == "FUT":
                d_pnl += l.qty * dS
                continue
            iv_H = implied_vol(x, S_H, l.strike, T_H, RISK_FREE_RATE, l.kind)
            d_pnl += l.qty * l.greeks["delta"] * dS
            g_pnl += l.qty * 0.5 * l.greeks["gamma"] * dS * dS
            t_pnl += l.qty * l.greeks["theta_min"] * held
            if np.isfinite(iv_H):
                v_pnl += l.qty * l.greeks["vega"] * (iv_H - l.iv)
        if bad:
            continue
        rows.append({
            "date": p["date"], "minutes_held": held, "spot_move_pts": dS,
            "delta_rs": d_pnl * LOT_SIZE, "gamma_rs": g_pnl * LOT_SIZE,
            "theta_rs": t_pnl * LOT_SIZE, "vega_rs": v_pnl * LOT_SIZE,
            "realised_rs": real * LOT_SIZE,
            "residual_rs": (real - d_pnl - g_pnl - t_pnl - v_pnl) * LOT_SIZE,
            "gamma_theta_carry_rs": (g_pnl + t_pnl) * LOT_SIZE,
        })
    return pd.DataFrame(rows)


# ============================================================ F. placebo, best-of-grid
def best_of_grid_p(mat: np.ndarray, idx: np.ndarray) -> float:
    """Smallest two-sided one-sample p-value across the grid for the selected rows."""
    best = 1.0
    for j in range(mat.shape[1]):
        v = mat[idx, j]
        v = v[np.isfinite(v)]
        if len(v) < 3 or np.allclose(v, v[0]):
            continue
        p = float(stats.ttest_1samp(v, 0.0).pvalue)
        if p < best:
            best = p
    return best


def best_of_grid_mean(mat: np.ndarray, idx: np.ndarray) -> tuple[float, int]:
    """Largest cell MEAN across the grid for the selected rows, and which cell it was.

    The SIGNED counterpart of ``best_of_grid_p``.  It is the statistic that answers "what is
    the best P&L a search of this size can find on this population", which the min-p
    statistic does not: min-p is won by whichever cell has the smallest variance, and on
    this grid those cells are reliable LOSSES.
    """
    means = np.full(mat.shape[1], -np.inf)
    for j in range(mat.shape[1]):
        v = mat[idx, j]
        v = v[np.isfinite(v)]
        if len(v) >= 3:
            means[j] = float(v.mean())
    j = int(np.argmax(means))
    return float(means[j]), j


def placebo_test(mat: np.ndarray, observed_idx: np.ndarray, n_pool: int,
                 n_draw: int, headline_col: int, rng: np.random.Generator) -> dict:
    obs_best = best_of_grid_p(mat, observed_idx)
    obs_head = np.nanmean(mat[observed_idx, headline_col])
    obs_bm, obs_bm_j = best_of_grid_mean(mat, observed_idx)
    bests, heads, bmeans = [], [], []
    for _ in range(n_draw):
        idx = rng.choice(n_pool, size=len(observed_idx), replace=False)
        bests.append(best_of_grid_p(mat, idx))
        heads.append(np.nanmean(mat[idx, headline_col]))
        bmeans.append(best_of_grid_mean(mat, idx)[0])
    bests = np.asarray(bests, dtype=float)
    heads = np.asarray(heads, dtype=float)
    bmeans = np.asarray(bmeans, dtype=float)
    return {
        "observed_best_of_grid_mean_rs": obs_bm,
        "observed_best_of_grid_mean_col": obs_bm_j,
        "placebo_best_of_grid_mean_median_rs": float(np.median(bmeans)),
        "placebo_best_of_grid_mean_95th_rs": float(np.percentile(bmeans, 95)),
        "empirical_p_best_of_grid_mean": float((bmeans >= obs_bm).mean()),
        "n_draws": n_draw,
        "observed_best_of_grid_p": obs_best,
        "placebo_best_p_median": float(np.median(bests)),
        "placebo_best_p_5th": float(np.percentile(bests, 5)),
        "empirical_best_of_grid_p": float((bests <= obs_best).mean()),
        "share_draws_reaching_p05": float((bests < 0.05).mean()),
        "observed_headline_mean_rs": float(obs_head),
        "placebo_headline_mean_rs": float(np.nanmean(heads)),
        "placebo_headline_5th": float(np.nanpercentile(heads, 5)),
        "placebo_headline_95th": float(np.nanpercentile(heads, 95)),
        "share_placebo_at_or_above_observed": float((heads >= obs_head).mean()),
    }


def bh_reject(pvals: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    p = np.asarray(pvals, dtype=float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), dtype=bool)
    if ok.sum() == 0:
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(p[idx])]
    m = len(order)
    thresh = alpha * (np.arange(1, m + 1) / m)
    passed = p[order] <= thresh
    if passed.any():
        k = np.max(np.flatnonzero(passed))
        out[order[: k + 1]] = True
    return out


# ============================================================ G. power
def required_d(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    from scipy.optimize import brentq as _b

    def f(d):
        nc = d * math.sqrt(n)
        crit = stats.t.ppf(1 - alpha / 2, n - 1)
        return (1 - stats.nct.cdf(crit, n - 1, nc)) + stats.nct.cdf(-crit, n - 1, nc) - power

    return float(_b(f, 1e-4, 5.0))


# ============================================================================== main
def fmt_pts(d: dict) -> str:
    if not d or d.get("n", 0) == 0:
        return "   -- no data --"
    return (f"{d['n']:>4} {d['mean']:>9.1f} {d['median']:>9.1f} {d['q1']:>9.1f} "
            f"{d['q3']:>9.1f} {d['p10']:>9.1f} {d['p90']:>9.1f} {d['up_pct']:>7.1f} "
            f"{d['p']:>8.4f}")


def main() -> None:
    rng = np.random.default_rng(SEED)
    sessions = session_dates()
    months = monthly_expiries()
    paths = gfp.load_full_paths()
    quotes = load_quotes()

    pool = paths                                                   # 264 gap-fill days
    mid = [p for p in paths if p["is_gate_b"] == 1]                # N = 33
    pooled = [p for p in paths if p["vix_rose"] == 1]              # N = 120
    gbc.reproduction_guard(mid)

    print("=" * 118)
    print("GATE B: WHICH OPTION STRUCTURE, IF ANY, MONETISES THE DIRECTIONAL SPOT EDGE?")
    print("=" * 118)
    print(f"placebo pool (non-expiry gap-down days whose gap fills after 09:17): {len(pool)}")
    print(f"mid-IV Gate B (published population)  N = {len(mid)}")
    print(f"pooled Gate B (all IV buckets)        N = {len(pooled)}")
    print("Reproduction guard on the published mid-IV construction: PASSED")
    print("Maturity convention for every implied volatility and every Greek below: "
          "TRADING TIME\n(375-minute session, 252-session year).  Not comparable to the "
          "calendar-convention IVs in\nGATE_B_REAL_PREMIUM_VALIDATION.md -- see "
          "CORRECTION_GATE_B_VOL_CRUSH.md.\n")

    results: dict = {"convention": "trading-time maturity, 375 min/session, 252 sessions/yr",
                     "populations": {"mid_iv_N": len(mid), "pooled_N": len(pooled),
                                     "placebo_pool_N": len(pool)}}

    # ------------------------------------------------------------------ A. the spot edge
    print("=" * 118)
    print("A.  THE DIRECTIONAL SPOT EDGE, OPTIONS ENTIRELY ASIDE -- ALL FIGURES IN INDEX POINTS")
    print("=" * 118)
    sec_a = {}
    for label, pop in (("mid-IV N=33", mid), ("pooled N=120", pooled)):
        a = section_a(pop, label)
        sec_a[label] = a
        print(f"\n--- {label} ---")
        print(f"{'horizon':>8} {'held':>6} {'N':>4} {'mean':>9} {'median':>9} {'Q1':>9} "
              f"{'Q3':>9} {'p10':>9} {'p90':>9} {'up%':>7} {'p':>8}")
        for r in a["horizon_distribution"]:
            print(f"{r['horizon']:>8} {r['mean_minutes_held']:>6.0f} " + fmt_pts(r))
        print(f"\n  MFE  points: mean {a['mfe']['mean']:>7.1f}  median {a['mfe']['median']:>7.1f}"
              f"  Q3 {a['mfe']['q3']:>7.1f}  p90 {a['mfe']['p90']:>7.1f}"
              f"   | timing median {a['mfe_minutes']['median']:.0f} min")
        print(f"  MAE  points: mean {a['mae']['mean']:>7.1f}  median {a['mae']['median']:>7.1f}"
              f"  Q1 {a['mae']['q1']:>7.1f}  p10 {a['mae']['p10']:>7.1f}"
              f"   | timing median {a['mae_minutes']['median']:.0f} min")
        print(f"\n  {'threshold':>10} {'ever reached':>14} {'n':>5} "
              f"{'median min to touch':>22}   |  {'adverse':>9} {'ever reached':>14}")
        for r, adv in zip(a["favourable_thresholds"], a["adverse_thresholds"]):
            print(f"  {'+' + str(r['threshold_pts']):>10} {r['ever_reached_pct']:>13.1f}% "
                  f"{r['n_reached']:>5} {r['median_minutes_to_first_touch']:>22.0f}"
                  f"   |  {adv['threshold_pts']:>9} {adv['ever_reached_pct']:>13.1f}%")
        print(f"\n  {'bucket':>13} {'N':>4} {'mean pts':>9} {'median':>9} {'pts/min':>9} {'p':>8}")
        for r in a["session_rate"]:
            if r.get("n", 0) < 2:
                continue
            print(f"  {r['bucket']:>13} {r['n']:>4} {r['mean']:>9.2f} {r['median']:>9.2f} "
                  f"{r['pts_per_min']:>9.4f} {r['p']:>8.4f}")
        print(f"\n  entry spot level: median {a['entry_spot']['median']:.0f}  "
              f"(so 100 points is {100/a['entry_spot']['median']*100:.2f}% of the index)")
    results["A_spot_edge"] = sec_a

    # ------------------------------------------------- B/C. structures, hurdles, P&L
    print("\n" + "=" * 118)
    print("B/C.  CANDIDATE STRUCTURES -- REAL STRIKE-TRACKED TRADED PREMIUMS")
    print("=" * 118)

    # Evaluate every structure x horizon once on the FULL pool, then slice by population.
    # This is also what makes the 5,000-draw placebo affordable.
    cells: list[dict] = []
    frames: dict[tuple, pd.DataFrame] = {}
    for name, key in STRUCTURES:
        for h in HORIZONS:
            df = evaluate(pool, quotes, sessions, months, key, h)
            frames[(key, h, False)] = df
            cells.append({"name": name, "key": key, "horizon": HORIZON_LABEL[h],
                          "offset": h, "next_weekly": False})
    for name, key in STRUCTURES:
        if key == "futures":
            continue                      # futures has no weekly expiry to roll
        for h in HORIZONS:
            df = evaluate(pool, quotes, sessions, months, key, h, next_weekly=True)
            frames[(key, h, True)] = df
            cells.append({"name": name + " [next weekly]", "key": key,
                          "horizon": HORIZON_LABEL[h], "offset": h, "next_weekly": True})

    date_index = {p["date"]: i for i, p in enumerate(pool)}
    mid_idx = np.asarray([date_index[p["date"]] for p in mid])
    pooled_idx = np.asarray([date_index[p["date"]] for p in pooled])

    def slice_df(df: pd.DataFrame, idx: np.ndarray) -> pd.DataFrame:
        return df.iloc[idx].reset_index(drop=True)

    # ---------------------------------------------------------------- the hurdle table
    print("\n--- B. THE HURDLE: spot move in POINTS required to break even, and how often "
          "spot clears it ---")
    print("Hurdle is computed per trade with each leg's implied volatility held at its entry")
    print("value and trading time advanced to the horizon.  'P(clear)' is the share of trades")
    print("whose ACTUAL spot move at that horizon reached that trade's own hurdle.\n")
    hurdle_rows = []
    for label, idx in (("mid-IV N=33", mid_idx), ("pooled N=120", pooled_idx)):
        print(f"\n  === {label} ===")
        print(f"  {'structure':>30} {'horizon':>8} {'N':>4} {'hurdle gross':>13} "
              f"{'hurdle net':>11} {'P(clear) gross':>15} {'P(clear) net':>13} "
              f"{'median |move|':>13}")
        for c in cells:
            if c["next_weekly"]:
                continue
            df = slice_df(frames[(c["key"], c["offset"], False)], idx)
            d = df[df["ok"] == True]
            if d.empty:
                continue
            hg = d["hurdle_gross_pts"].to_numpy(dtype=float)
            hn = d["hurdle_net_pts"].to_numpy(dtype=float)
            row = {
                "population": label, "structure": c["name"], "horizon": c["horizon"],
                "n": int(len(d)),
                "hurdle_gross_median_pts": float(np.nanmedian(hg)),
                "hurdle_net_median_pts": float(np.nanmedian(hn)),
                "p_clear_gross": float(d["cleared_gross"].mean() * 100.0),
                "p_clear_net": float(d["cleared_net"].mean() * 100.0),
                "median_abs_move_pts": float(np.nanmedian(np.abs(d["spot_move_pts"]))),
            }
            hurdle_rows.append(row)
            print(f"  {c['name']:>30} {c['horizon']:>8} {row['n']:>4} "
                  f"{row['hurdle_gross_median_pts']:>13.1f} {row['hurdle_net_median_pts']:>11.1f} "
                  f"{row['p_clear_gross']:>14.1f}% {row['p_clear_net']:>12.1f}% "
                  f"{row['median_abs_move_pts']:>13.1f}")
    results["B_hurdles"] = hurdle_rows
    pd.DataFrame(hurdle_rows).to_csv("gate_b_structure_hurdles.csv", index=False)

    # ------------------------------------------------------------- the structure ranking
    print("\n\n--- C. STRUCTURE RANKING -- P&L in RUPEES per lot of 75, gross and net ---")
    rank_rows = []
    for label, idx in (("mid-IV N=33", mid_idx), ("pooled N=120", pooled_idx)):
        print(f"\n  === {label} ===")
        print(f"  {'structure':>32} {'horizon':>8} {'N':>4} {'cov':>5} "
              f"{'gross mean':>11} {'net mean':>10} {'net median':>11} {'win%':>6} "
              f"{'p vs 0':>8} {'net pess':>10} {'capital Rs':>11} {'fit?':>5}")
        for c in cells:
            df = slice_df(frames[(c["key"], c["offset"], c["next_weekly"])], idx)
            d = df[df["ok"] == True]
            if len(d) < 3:
                continue
            g = summarise_rupees(df, "gross_rupees")
            n_ = summarise_rupees(df, "net_rupees")
            pess = summarise_rupees(df, "net_pess_rupees")
            cap_med = float(np.nanmedian(d["capital_rupees"]))
            cap_kind = d["capital_kind"].iloc[0]
            fits = cap_med <= BUDGET_RUPEES
            row = {
                "population": label, "structure": c["name"], "horizon": c["horizon"],
                "n": n_.get("n", 0), "coverage_pct": float(len(d) / len(df) * 100.0),
                "gross_mean_rs": g.get("mean"), "gross_p": g.get("p"),
                "net_mean_rs": n_.get("mean"), "net_median_rs": n_.get("median"),
                "net_win_pct": n_.get("win_pct"), "net_p": n_.get("p"),
                "net_wilcoxon_p": n_.get("wilcoxon_p"),
                "net_sd_rs": n_.get("sd"), "net_total_rs": n_.get("total"),
                "net_pess_mean_rs": pess.get("mean"), "net_pess_p": pess.get("p"),
                "capital_kind": cap_kind, "capital_median_rs": cap_med,
                "fits_budget": bool(fits),
                "mean_entry_delta": float(d["entry_delta"].mean()),
                "median_strikes": d["strikes"].iloc[len(d) // 2],
                "next_weekly_modelled": c["next_weekly"],
            }
            rank_rows.append(row)
            print(f"  {c['name']:>32} {c['horizon']:>8} {row['n']:>4} "
                  f"{row['coverage_pct']:>4.0f}% {row['gross_mean_rs']:>11.0f} "
                  f"{row['net_mean_rs']:>10.0f} {row['net_median_rs']:>11.0f} "
                  f"{row['net_win_pct']:>5.1f}% {row['net_p']:>8.4f} "
                  f"{row['net_pess_mean_rs']:>10.0f} {cap_med:>11.0f} "
                  f"{'YES' if fits else 'no':>5}")
    results["C_ranking"] = rank_rows
    pd.DataFrame(rank_rows).to_csv("gate_b_structure_ranking.csv", index=False)

    # ------------------------------------------------------- D. the Greek decomposition
    print("\n\n" + "=" * 118)
    print("D.  GREEK DECOMPOSITION -- TRADING-TIME GREEKS, RUPEES PER LOT")
    print("=" * 118)
    print("Aryan's two named hypotheses, tested by name:")
    print("  (i)  gamma-theta carry is unfavourable  ->  is (gamma_pnl + theta_pnl) < 0?")
    print("  (ii) spot does not move fast enough to outrun theta  ->  is |delta_pnl| "
          "< |theta_pnl|?\n")
    dec_rows = []
    for label, pop in (("mid-IV N=33", mid), ("pooled N=120", pooled)):
        print(f"\n  === {label} ===")
        print(f"  {'structure':>32} {'horizon':>8} {'N':>4} {'realised':>10} {'delta':>9} "
              f"{'gamma':>9} {'theta':>9} {'vega':>9} {'resid':>9} {'g+t carry':>10} "
              f"{'p carry':>8}")
        for name, key in STRUCTURES:
            for h in (30, 60, 120, None):
                d = decompose(pop, quotes, sessions, months, key, h)
                if len(d) < 3:
                    continue
                carry = d["gamma_theta_carry_rs"].to_numpy(dtype=float)
                row = {
                    "population": label, "structure": name, "horizon": HORIZON_LABEL[h],
                    "n": int(len(d)),
                    "realised_rs": float(d["realised_rs"].mean()),
                    "delta_rs": float(d["delta_rs"].mean()),
                    "gamma_rs": float(d["gamma_rs"].mean()),
                    "theta_rs": float(d["theta_rs"].mean()),
                    "vega_rs": float(d["vega_rs"].mean()),
                    "residual_rs": float(d["residual_rs"].mean()),
                    "gamma_theta_carry_rs": float(carry.mean()),
                    "carry_p": float(stats.ttest_1samp(carry, 0.0).pvalue),
                    "delta_beats_theta_pct": float(
                        (d["delta_rs"].abs() > d["theta_rs"].abs()).mean() * 100.0),
                    "delta_covers_theta_pct": float(
                        (d["delta_rs"] + d["theta_rs"] > 0).mean() * 100.0),
                    "mean_minutes_held": float(d["minutes_held"].mean()),
                }
                dec_rows.append(row)
                print(f"  {name:>32} {HORIZON_LABEL[h]:>8} {row['n']:>4} "
                      f"{row['realised_rs']:>10.0f} {row['delta_rs']:>9.0f} "
                      f"{row['gamma_rs']:>9.0f} {row['theta_rs']:>9.0f} "
                      f"{row['vega_rs']:>9.0f} {row['residual_rs']:>9.0f} "
                      f"{row['gamma_theta_carry_rs']:>10.0f} {row['carry_p']:>8.4f}")
    results["D_decomposition"] = dec_rows
    pd.DataFrame(dec_rows).to_csv("gate_b_structure_decomposition.csv", index=False)

    # --------------------------------------------------------- E. capital feasibility
    print("\n\n" + "=" * 118)
    print(f"E.  CAPITAL FEASIBILITY AT Rs {BUDGET_RUPEES:,.0f} PER WEEK, LOT SIZE {LOT_SIZE}")
    print("=" * 118)
    print(f"Margin assumption for naked short options and futures: "
          f"{MARGIN_FRAC_OF_NOTIONAL:.0%} of notional.  This is an")
    print("ASSUMPTION carried through the study, not a measurement from this dataset.\n")
    cap_rows = []
    print(f"  {'structure':>32} {'capital kind':>13} {'median Rs':>11} {'Q1':>10} "
          f"{'Q3':>10} {'max':>11} {'affordable at Rs 10k':>21}")
    for name, key in STRUCTURES:
        df = frames[(key, None, False)]
        d = df[df["ok"] == True]
        if d.empty:
            continue
        cap = d["capital_rupees"].to_numpy(dtype=float)
        share = float((cap <= BUDGET_RUPEES).mean() * 100.0)
        row = {"structure": name, "capital_kind": d["capital_kind"].iloc[0],
               "median_rs": float(np.median(cap)), "q1_rs": float(np.percentile(cap, 25)),
               "q3_rs": float(np.percentile(cap, 75)), "max_rs": float(cap.max()),
               "share_of_fires_affordable_pct": share,
               "verdict": "AVAILABLE" if share >= 50 else "OUT OF BUDGET"}
        cap_rows.append(row)
        print(f"  {name:>32} {row['capital_kind']:>13} {row['median_rs']:>11,.0f} "
              f"{row['q1_rs']:>10,.0f} {row['q3_rs']:>10,.0f} {row['max_rs']:>11,.0f} "
              f"{share:>19.1f}%  {row['verdict']}")
    results["E_capital"] = cap_rows
    pd.DataFrame(cap_rows).to_csv("gate_b_structure_capital.csv", index=False)

    # ------------------------------------------------------ F. multiplicity and placebo
    print("\n\n" + "=" * 118)
    print("F.  MULTIPLE COMPARISONS AND THE SHUFFLED-LABEL PLACEBO")
    print("=" * 118)
    n_cells = len(cells)
    print(f"Structure x horizon combinations tested in this script: {n_cells} per population, "
          f"{2 * n_cells} in total.")
    print(f"  of which priced on REAL traded premiums : "
          f"{sum(1 for c in cells if not c['next_weekly'])}")
    print(f"  of which MODEL-BASED (next weekly, no WEEK2 tape in the archive): "
          f"{sum(1 for c in cells if c['next_weekly'])}\n")

    # net-P&L matrix over the whole pool, one column per cell -- the placebo resamples rows
    mat = np.full((len(pool), n_cells), np.nan)
    for j, c in enumerate(cells):
        df = frames[(c["key"], c["offset"], c["next_weekly"])]
        v = df["net_rupees"].to_numpy(dtype=float) if "net_rupees" in df else None
        if v is None:
            continue
        ok = (df["ok"] == True).to_numpy()
        mat[ok, j] = v[ok]

    head_j = next(j for j, c in enumerate(cells)
                  if c["key"] == "atm_call" and c["horizon"] == "close"
                  and not c["next_weekly"])

    mc = {}
    for label, idx in (("mid-IV N=33", mid_idx), ("pooled N=120", pooled_idx)):
        sub = [r for r in rank_rows if r["population"] == label]
        praw = np.asarray([r["net_p"] for r in sub], dtype=float)
        pos = np.asarray([(r["net_mean_rs"] or 0) > 0 for r in sub])
        bonf = 0.05 / max(len(praw), 1)
        bh = bh_reject(praw, 0.05)
        pl = placebo_test(mat, idx, len(pool), N_PLACEBO, head_j, rng)
        mc[label] = {
            "n_cells": len(praw),
            "raw_p_lt_05": int(np.sum(praw < 0.05)),
            "raw_p_lt_05_and_positive": int(np.sum((praw < 0.05) & pos)),
            "bonferroni_alpha": bonf,
            "bonferroni_survivors": int(np.sum(praw < bonf)),
            "bonferroni_survivors_positive": int(np.sum((praw < bonf) & pos)),
            "bh_survivors": int(bh.sum()),
            "bh_survivors_positive": int(np.sum(bh & pos)),
            "best_cell": sub[int(np.nanargmin(praw))]["structure"] + " @ "
                         + sub[int(np.nanargmin(praw))]["horizon"],
            "best_cell_mean_rs": sub[int(np.nanargmin(praw))]["net_mean_rs"],
            "best_cell_p": float(np.nanmin(praw)),
            "best_positive_cell": (max((r for r in sub if (r["net_mean_rs"] or 0) > 0),
                                       key=lambda r: r["net_mean_rs"],
                                       default={"structure": None})["structure"]),
            "placebo": pl,
        }
        print(f"\n  === {label} ===")
        print(f"  cells: {len(praw)}   raw p<0.05: {mc[label]['raw_p_lt_05']} "
              f"(positive-mean among them: {mc[label]['raw_p_lt_05_and_positive']})")
        print(f"  Bonferroni alpha = {bonf:.2e}: {mc[label]['bonferroni_survivors']} survive "
              f"({mc[label]['bonferroni_survivors_positive']} of them positive)")
        print(f"  Benjamini-Hochberg: {mc[label]['bh_survivors']} survive "
              f"({mc[label]['bh_survivors_positive']} of them positive)")
        print(f"  smallest-p cell: {mc[label]['best_cell']}  "
              f"mean Rs {mc[label]['best_cell_mean_rs']:.0f}  p = {mc[label]['best_cell_p']:.5f}")
        print(f"  best-of-grid placebo ({N_PLACEBO} draws): observed best p = "
              f"{pl['observed_best_of_grid_p']:.5f}, placebo median = "
              f"{pl['placebo_best_p_median']:.5f}")
        print(f"    EMPIRICAL best-of-grid p = {pl['empirical_best_of_grid_p']:.4f}   "
              f"(a random label reaches p<0.05 somewhere in the grid in "
              f"{pl['share_draws_reaching_p05']*100:.1f}% of draws)")
        print(f"  gate conditioning, headline cell (long ATM call, hold to close):")
        print(f"    observed mean Rs {pl['observed_headline_mean_rs']:.0f} vs placebo mean "
              f"Rs {pl['placebo_headline_mean_rs']:.0f} "
              f"[5th {pl['placebo_headline_5th']:.0f}, 95th {pl['placebo_headline_95th']:.0f}]")
        print(f"    share of random labels at or above the observed value: "
              f"{pl['share_placebo_at_or_above_observed']*100:.1f}%")
        bmj = int(pl["observed_best_of_grid_mean_col"])
        print(f"  SIGNED best-of-grid MEAN (the statistic that matters, min-p is won by the")
        print(f"    lowest-variance cell and those are losses here):")
        print(f"    observed best cell = {cells[bmj]['name']} @ {cells[bmj]['horizon']}, "
              f"mean Rs {pl['observed_best_of_grid_mean_rs']:.0f}")
        print(f"    placebo best-of-grid mean: median Rs "
              f"{pl['placebo_best_of_grid_mean_median_rs']:.0f}, 95th Rs "
              f"{pl['placebo_best_of_grid_mean_95th_rs']:.0f}   "
              f"EMPIRICAL p = {pl['empirical_p_best_of_grid_mean']:.4f}")
    results["F_multiplicity"] = mc

    # ---------------------------------------------------------------------- G. power
    print("\n\n" + "=" * 118)
    print("G.  POWER")
    print("=" * 118)
    pw = {}
    for label, idx in (("mid-IV N=33", mid_idx), ("pooled N=120", pooled_idx)):
        n = len(idx)
        d_req = required_d(n)
        sub = [r for r in rank_rows if r["population"] == label and not r["next_weekly_modelled"]]
        sds = {r["structure"] + " @ " + r["horizon"]: r["net_sd_rs"] for r in sub}
        head = next(r for r in sub if r["structure"] == "long ATM call"
                    and r["horizon"] == "close")
        fut = next(r for r in sub if r["structure"] == "long NIFTY futures"
                   and r["horizon"] == "close")
        boot = []
        v = mat[idx, head_j]
        v = v[np.isfinite(v)]
        for _ in range(10000):
            boot.append(np.mean(rng.choice(v, size=len(v), replace=True)))
        pw[label] = {
            "n": int(n), "required_standardised_effect": d_req,
            "atm_call_close_sd_rs": head["net_sd_rs"],
            "smallest_detectable_mean_rs_atm_call": d_req * head["net_sd_rs"],
            "futures_close_sd_rs": fut["net_sd_rs"],
            "smallest_detectable_mean_rs_futures": d_req * fut["net_sd_rs"],
            "atm_call_close_mean_rs": head["net_mean_rs"],
            "atm_call_close_ci95_rs": [float(np.percentile(boot, 2.5)),
                                       float(np.percentile(boot, 97.5))],
            "futures_close_mean_rs": fut["net_mean_rs"],
        }
        print(f"\n  === {label} (N = {n}) ===")
        print(f"  standardised effect detectable at 5% size / 80% power: {d_req:.3f} sd")
        print(f"  long ATM call, hold to close : sd Rs {head['net_sd_rs']:,.0f}  ->  "
              f"smallest detectable mean Rs {d_req * head['net_sd_rs']:,.0f}")
        print(f"  long NIFTY futures, to close : sd Rs {fut['net_sd_rs']:,.0f}  ->  "
              f"smallest detectable mean Rs {d_req * fut['net_sd_rs']:,.0f}")
        print(f"  observed ATM-call mean Rs {head['net_mean_rs']:,.0f}  "
              f"bootstrap 95% CI [{np.percentile(boot, 2.5):,.0f}, "
              f"{np.percentile(boot, 97.5):,.0f}]")
        print(f"  observed futures mean  Rs {fut['net_mean_rs']:,.0f}")
    results["G_power"] = pw

    with open("gate_b_structure_search_results.json", "w") as fh:
        json.dump(results, fh, indent=2, default=float)
    print("\n\nWrote gate_b_structure_search_results.json, "
          "gate_b_structure_hurdles.csv, gate_b_structure_ranking.csv,\n"
          "gate_b_structure_decomposition.csv, gate_b_structure_capital.csv")


if __name__ == "__main__":
    main()
