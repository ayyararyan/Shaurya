#!/usr/bin/env python3
"""Shared panel construction for the Gate-B ENTRY-TIMING test.

New module.  It does not modify, and is not imported by, any pre-existing script.  It
reuses ``gate_b_common.py`` / ``gate_b_full_paths.py`` for the population definition (the
264 non-expiry gap-down days whose gap fills after 09:17, of which 120 also had an
overnight VIX rise and 33 also sit in the mid opening-IV bucket) and for the hydrated
one-minute CALL tape.  The *panel* built here is new, because every previous Gate-B P&L in
this project entered at the gap-fill minute and therefore only ever needed one strike per
day.

The question this module exists to answer
-----------------------------------------
"The gap fill is the moment the day is CLASSIFIED.  It is not necessarily the moment to buy
the option."  Those two decisions have been welded together in every prior test.  This
module unwelds them: it prices the same long ATM CALL bought at an arbitrary entry minute
``t`` >= the fill minute, held to 15:29.

CRITICAL CONVENTION -- the ATM strike is RE-PICKED AT THE ENTRY MINUTE
---------------------------------------------------------------------
``K(t) = round(spot(t) / 50) * 50``.  A 12:00 entry buys the 12:00 ATM strike, not the
fill-minute ATM strike.  On a day where spot has travelled >= 25 points between the fill and
12:00 these are different contracts, and pricing a 12:00 entry off the fill-minute strike
would silently smuggle the intervening spot move into the entry premium.
``worked_strike_examples`` in ``gate_b_entry_timing.py`` proves the re-pick fires.

Premium convention: real traded one-minute bar CLOSES of the tracked strike, looked up by
absolute strike value, exactly as ``gate_b_common.py`` does.  No Black-Scholes proxy price
enters any return computed here.  ``bs_call`` is imported for ONE purpose only -- inverting
quoted premiums to an implied volatility in the supplementary vol-overpayment section --
and that inversion uses a TRADING-TIME maturity (375 minutes/session, 252 sessions/year) as
required by ``CORRECTION_GATE_B_VOL_CRUSH.md``.  No calendar-time maturity is computed
anywhere in this module.

Offline analysis only.  No broker, credential, exchange network, or order path is used.  No
gate is armed and no live order exists or is authorised.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analyze_still_water_spot import load_spot
from bs_gap_fill_pnl import STRIKE_STEP
from gate_b_common import clock_to_minutes
from gate_b_full_paths import FULL_QUOTE_CACHE, load_full_paths

SESSION_OPEN = "09:15"
SESSION_END = "15:29"
OPEN_MIN = clock_to_minutes(SESSION_OPEN)      # 555
END_MIN = clock_to_minutes(SESSION_END)        # 929
CLOSE_STAMP_MIN = clock_to_minutes("15:30")    # contract expiry stamp, 930

TRADING_MINUTES_PER_DAY = CLOSE_STAMP_MIN - OPEN_MIN     # 375
TRADING_DAYS_PER_YEAR = 252

# A trade must have at least this many minutes left to run, or the "entry" is not an entry.
MIN_HOLD_MINUTES = 10
LAST_ENTRY_MIN = END_MIN - MIN_HOLD_MINUTES              # 15:19
# hold-to-close is only honest if the tracked strike is still quoted near the close; the
# same two-minute grace ``gate_b_common.rule_return`` uses.
CLOSE_GRACE = 2

# ------------------------------------------------------------------ population
def population() -> tuple[list[dict], list[dict], list[dict]]:
    """``(pool, fires, controls)``.

    pool     -- 120 non-expiry gap-down days with an overnight VIX rise whose gap filled
    fires    -- the 33 that are also mid opening-IV, i.e. published Gate B
    controls -- the other 87.  This is the placebo population named in the brief:
                "non-expiry gap-down VIX-rose fill days that are NOT Gate B fires".
    """
    paths = load_full_paths()
    pool = [p for p in paths if int(p["vix_rose"]) == 1]
    fires = [p for p in pool if int(p["is_gate_b"]) == 1]
    controls = [p for p in pool if int(p["is_gate_b"]) == 0]
    if len(pool) != 120 or len(fires) != 33 or len(controls) != 87:
        raise AssertionError(
            f"population changed: pool={len(pool)} fires={len(fires)} controls={len(controls)}"
        )
    return pool, fires, controls


# ------------------------------------------------------------------ spot session paths
def session_spot(dates: set[str]) -> dict[str, pd.DataFrame]:
    """One-minute spot 09:15..15:29 per date, from the canonical project spot loader.

    ``load_spot`` reads the rolling-ATM CALL files' ``spot`` column -- the same series that
    defines the gap fill everywhere else in this project, so the fill minute recovered here
    is identical to the stored one (asserted by ``verify_fill_minutes``).
    """
    spot, _ = load_spot()
    spot = spot[spot["date"].isin(dates)].copy()
    spot["minutes"] = spot["datetime"].dt.hour * 60 + spot["datetime"].dt.minute
    spot = spot[(spot["minutes"] >= OPEN_MIN) & (spot["minutes"] <= END_MIN)]
    spot = spot.sort_values(["date", "minutes"]).drop_duplicates(
        subset=["date", "minutes"], keep="last"
    )
    return {d: g.reset_index(drop=True) for d, g in spot.groupby("date")}


def verify_fill_minutes(pool: list[dict], spots: dict[str, pd.DataFrame]) -> dict:
    """Recompute the gap-fill minute from scratch and check it against the stored one."""
    bad = []
    for p in pool:
        g = spots[p["date"]]
        after = g[g["minutes"] > clock_to_minutes("09:17")]
        hit = after[after["spot"].astype(float) >= float(p["prior_close"])]
        got = int(hit["minutes"].iloc[0]) if len(hit) else -1
        if got != int(p["entry_minute"]):
            bad.append({"date": p["date"], "stored": int(p["entry_minute"]), "recomputed": got})
    return {"checked": len(pool), "mismatches": bad}


# ------------------------------------------------------------------ traded CALL tape
def quote_book(dates: set[str]) -> tuple[dict, dict]:
    """``(px, chain_volume)``.

    ``px[date][(minute, strike)] = (close, iv)`` for every hydrated CALL bar.
    ``chain_volume[date][minute] = total traded CALL volume across the whole hydrated chain``
    -- the only genuine traded volume available for a VWAP on an index that has none.
    """
    q = pd.read_pickle(FULL_QUOTE_CACHE)
    q = q[q["date"].isin(dates)]
    q = q[(q["minutes"] >= OPEN_MIN) & (q["minutes"] <= END_MIN)]
    px: dict[str, dict] = {}
    vol: dict[str, dict] = {}
    for d, g in q.groupby("date", sort=False):
        px[d] = {
            (int(m), float(k)): (float(c), float(v))
            for m, k, c, v in zip(g["minutes"], g["strike"], g["close"], g["iv"])
        }
        vol[d] = g.groupby("minutes")["volume"].sum().to_dict()
    return px, vol


# ------------------------------------------------------------------ path statistics
def straight_line_r2(y: np.ndarray) -> float:
    """R2 of an OLS fit of ``y`` on its own index -- direction-free path smoothness.

    Same definition as ``gate_b_flow_features.straight_line_r2``; re-stated here so this
    module has no dependency on the flow study's minimum-length constant.
    """
    n = len(y)
    if n < 5:
        return np.nan
    x = np.arange(n, dtype=float)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0:
        return np.nan
    xm, ym = x.mean(), y.mean()
    den = float(((x - xm) ** 2).sum())
    if den <= 0:
        return np.nan
    b = float(((x - xm) * (y - ym)).sum() / den)
    a = float(ym - b * xm)
    resid = y - (a + b * x)
    return float(1.0 - float((resid ** 2).sum()) / ss_tot)


class DaySession:
    """Everything about one day that any entry clock needs, computed once."""

    __slots__ = (
        "date", "is_fire", "iv_bucket", "prior_close", "fill_minute", "expiry",
        "minutes", "spot", "idx", "vwap", "twap", "roll_max_15", "roll_max_30", "r2_30",
        "px", "quoted_minutes",
    )

    def __init__(self, p: dict, g: pd.DataFrame, px: dict, chain_vol: dict):
        self.date = p["date"]
        self.is_fire = int(p["is_gate_b"])
        self.iv_bucket = str(p["iv_bucket"])
        self.prior_close = float(p["prior_close"])
        self.fill_minute = int(p["entry_minute"])
        self.expiry = str(p["expiry"])
        self.minutes = g["minutes"].to_numpy(dtype=int)
        self.spot = g["spot"].to_numpy(dtype=float)
        self.idx = {int(m): i for i, m in enumerate(self.minutes)}
        self.px = px

        v = np.asarray([float(chain_vol.get(int(m), 0.0)) for m in self.minutes])
        num = np.cumsum(self.spot * v)
        den = np.cumsum(v)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.vwap = np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)
        self.twap = np.cumsum(self.spot) / np.arange(1, len(self.spot) + 1)

        self.roll_max_15 = self._rolling_max(15)
        self.roll_max_30 = self._rolling_max(30)
        self.r2_30 = self._rolling_r2(30)
        self.quoted_minutes = set(m for m, _k in px.keys()) if px else set()

    def _rolling_max(self, w: int) -> np.ndarray:
        out = np.full(len(self.spot), np.nan)
        for i in range(len(self.spot)):
            lo = max(0, i - w)
            out[i] = float(self.spot[lo:i + 1].max())
        return out

    def _rolling_r2(self, w: int) -> np.ndarray:
        out = np.full(len(self.spot), np.nan)
        for i in range(len(self.spot)):
            lo = max(0, i - w)
            if i - lo + 1 >= 10:
                out[i] = straight_line_r2(self.spot[lo:i + 1])
        return out

    # ---------------------------------------------------------------- the trade
    def atm_strike(self, minute: int) -> float | None:
        i = self.idx.get(int(minute))
        if i is None:
            return None
        return float(round(self.spot[i] / STRIKE_STEP) * STRIKE_STEP)

    def trade(self, minute: int) -> dict | None:
        """Buy the ATM CALL **as at ``minute``**, hold to 15:29.  Real traded premiums only.

        Returns ``None`` when the minute is not a legal entry (before the fill, past
        ``LAST_ENTRY_MIN``, or off the session grid).  Returns a dict with ``ret=nan`` when
        the trade is legal but the tape cannot price it.
        """
        minute = int(minute)
        if minute < self.fill_minute or minute > LAST_ENTRY_MIN or minute not in self.idx:
            return None
        K = self.atm_strike(minute)
        entry = self.px.get((minute, K))
        out = {
            "minute": minute, "K": K, "spot": float(self.spot[self.idx[minute]]),
            "entry_px": np.nan, "entry_iv": np.nan, "exit_px": np.nan,
            "exit_minute": -1, "held": np.nan, "ret": np.nan, "ret_per_min": np.nan,
            "unpriceable": "entry",
        }
        if entry is None or not np.isfinite(entry[0]) or entry[0] <= 0:
            return out
        out["entry_px"] = float(entry[0])
        out["entry_iv"] = float(entry[1]) if entry[1] > 0 else np.nan

        last_px, last_min = np.nan, -1
        for m in range(END_MIN, minute - 1, -1):
            hit = self.px.get((m, K))
            if hit is not None and np.isfinite(hit[0]) and hit[0] > 0:
                last_px, last_min = float(hit[0]), m
                break
        if last_min < 0 or (END_MIN - last_min) > CLOSE_GRACE:
            out["unpriceable"] = "exit"
            return out
        held = last_min - minute
        if held < 1:
            out["unpriceable"] = "exit"
            return out
        ret = (last_px - out["entry_px"]) / out["entry_px"] * 100.0
        out.update(
            exit_px=last_px, exit_minute=last_min, held=float(held), ret=float(ret),
            ret_per_min=float(ret / held), unpriceable="",
        )
        return out

    # ---------------------------------------------------------------- confirmations
    def confirmed(self, minute: int, variant: str, r2_threshold: float) -> bool | None:
        """Has the trend confirmed by ``minute``?  ``None`` if undecidable at that minute."""
        i = self.idx.get(int(minute))
        if i is None or minute < self.fill_minute:
            return None
        s = float(self.spot[i])
        if variant.startswith("move>="):
            x = float(variant.split(">=")[1])
            fi = self.idx.get(self.fill_minute)
            if fi is None:
                return None
            return bool(s - float(self.spot[fi]) >= x)
        if variant == "above_vwap":
            v = self.vwap[i]
            return None if not np.isfinite(v) else bool(s > v)
        if variant.startswith("higher_high_"):
            w = int(variant.rsplit("_", 1)[1])
            ref = self.roll_max_15[i] if w == 15 else self.roll_max_30[i]
            return None if not np.isfinite(ref) else bool(s >= ref - 1e-9)
        if variant == "r2_30_above_median":
            v = self.r2_30[i]
            return None if not np.isfinite(v) else bool(v > r2_threshold)
        raise ValueError(f"unknown confirmation variant {variant}")


def build_sessions() -> dict[str, DaySession]:
    """Built fresh every run (~12 s).  Deliberately NOT pickled: a cached DaySession would
    be a silent second source of truth for the panel, and the whole point of this test is
    that the strike is re-derived at each entry minute from the live spot path."""
    pool, _, _ = population()
    dates = {p["date"] for p in pool}
    spots = session_spot(dates)
    check = verify_fill_minutes(pool, spots)
    if check["mismatches"]:
        raise AssertionError(f"fill-minute recomputation disagrees: {check['mismatches']}")
    px, vol = quote_book(dates)
    return {
        p["date"]: DaySession(p, spots[p["date"]], px.get(p["date"], {}), vol.get(p["date"], {}))
        for p in pool
    }


# ------------------------------------------------------------------ trading-time maturity
def trading_T(date_str: str, minute: int, expiry_str: str, sessions: np.ndarray) -> float:
    """Years to expiry measured in TRADING time.  CORRECTION_GATE_B_VOL_CRUSH.md, mandatory.

    Calendar time is never used.  ``sessions`` is the sorted array of trading dates.
    """
    d = np.datetime64(pd.Timestamp(date_str).normalize())
    e = np.datetime64(pd.Timestamp(expiry_str).normalize())
    today = max(0.0, float(CLOSE_STAMP_MIN - minute))
    m = today if e <= d else today + TRADING_MINUTES_PER_DAY * float(
        len(sessions[(sessions > d) & (sessions <= e)])
    )
    return max(m / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR), 1e-9)


def trading_dates() -> np.ndarray:
    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    return np.sort(dm["date"].dt.normalize().unique())


if __name__ == "__main__":
    pool, fires, controls = population()
    print(f"pool {len(pool)}  fires {len(fires)}  controls {len(controls)}")
    s = build_sessions()
    print(f"sessions built: {len(s)}")
    d = fires[0]["date"]
    ds = s[d]
    print(d, "fill", ds.fill_minute, "spot minutes", len(ds.minutes))
    for m in (ds.fill_minute, clock_to_minutes("12:00")):
        t = ds.trade(m)
        print("  entry", m, t if t is None else {k: t[k] for k in ("K", "entry_px", "exit_px", "ret", "held")})
