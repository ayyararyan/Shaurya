#!/usr/bin/env python3
"""Panel construction for VRP_FORECAST_SPEC.md.

One row per trading session: the ATM implied volatility observed at 09:15, the realised
volatility actually delivered between that minute and the WEEK1 expiry close, and a set of
strictly past-only predictors.

Every volatility is annualised in the project's TRADING-TIME convention (375 minutes per
session, 252 sessions per year).  Calendar-time maturity is forbidden here; see
CORRECTION_GATE_B_VOL_CRUSH.md.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

import nge_common as nc
from analyze_still_water_spot import load_spot

PANEL_CACHE = Path("vrp_forecast_panel.pkl")
PANEL_AUDIT = Path("vrp_forecast_panel_audit.json")

SESSIONS_PER_YEAR = nc.SESSIONS_PER_YEAR
RATE = nc.RISK_FREE_RATE


# ----------------------------------------------------------------------------------
# Black-Scholes price and inversion (same convention as vrp_breakout_test.py)
# ----------------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(side: str, spot: float, strike: float, T: float, r: float, sigma: float) -> float:
    if not (spot > 0 and strike > 0 and T > 0 and sigma > 0):
        return float("nan")
    sqrtT = math.sqrt(T)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    disc = math.exp(-r * T)
    if side == "CALL":
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def invert_iv(side: str, price: float, spot: float, strike: float, T: float,
              r: float = RATE) -> float:
    """Bisection on sigma in [1e-4, 5.0].  Returns NaN outside the no-arbitrage bounds."""
    if not (price > 0 and spot > 0 and strike > 0 and T > 0):
        return float("nan")
    disc = math.exp(-r * T)
    intrinsic = max(spot - strike * disc, 0.0) if side == "CALL" else max(strike * disc - spot, 0.0)
    upper = spot if side == "CALL" else strike * disc
    if price <= intrinsic + 1e-9 or price >= upper - 1e-9:
        return float("nan")
    lo, hi = 1e-4, 5.0
    f_lo = bs_price(side, spot, strike, T, r, lo) - price
    f_hi = bs_price(side, spot, strike, T, r, hi) - price
    if not (f_lo < 0 < f_hi):
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = bs_price(side, spot, strike, T, r, mid) - price
        if abs(f_mid) < 1e-10:
            return mid
        if f_mid < 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ----------------------------------------------------------------------------------
# per-session realised variance from the spot tape
# ----------------------------------------------------------------------------------

def session_variances() -> pd.DataFrame:
    """Per session: intraday realised variance at 1-minute and 5-minute sampling, plus the
    09:15 spot and the 15:29 spot needed for the overnight term."""
    spot_df, _ = load_spot()
    spot_df = spot_df[(spot_df["clock"] >= nc.SESSION_OPEN) & (spot_df["clock"] <= nc.SESSION_LAST)]
    spot_df = spot_df.drop_duplicates(subset=["date", "clock"]).sort_values(["date", "clock"])

    rows = []
    for date, g in spot_df.groupby("date", sort=True):
        px = g["spot"].to_numpy(dtype=float)
        mins = np.asarray([int(c[:2]) * 60 + int(c[3:]) for c in g["clock"]], dtype=int)
        if len(px) < 200:
            continue
        r1 = np.diff(np.log(px))
        rvar1 = float(np.sum(r1 * r1))
        # 5-minute grid on the same path
        grid = np.arange(mins[0], mins[-1] + 1, 5)
        idx = np.unique(np.searchsorted(mins, grid, side="left"))
        idx = idx[idx < len(px)]
        r5 = np.diff(np.log(px[idx]))
        rvar5 = float(np.sum(r5 * r5))
        rows.append({"date": date, "open_spot": float(px[0]), "close_spot": float(px[-1]),
                     "rvar1": rvar1, "rvar5": rvar5, "n_minutes": int(len(px))})
    sv = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    prev_close = sv["close_spot"].shift(1)
    on = np.log(sv["open_spot"] / prev_close)
    # overnight variance ATTRIBUTED TO THE NIGHT THAT PRECEDES THIS SESSION
    sv["overnight_var"] = (on * on).fillna(0.0)
    return sv


def _cum(arr: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(arr)])


def build_panel() -> tuple[pd.DataFrame, dict]:
    snap = nc.load_snapshot()
    op = snap[snap["clock"] == nc.SESSION_OPEN].copy()
    sessions = sorted(snap["date"].unique().tolist())
    expiries = nc._expiry_dates()

    sv = session_variances()
    sv = sv[sv["date"].isin(sessions)].reset_index(drop=True)
    sess = sv["date"].tolist()
    pos = {d: i for i, d in enumerate(sess)}
    c_rvar1 = _cum(sv["rvar1"].to_numpy())
    c_rvar5 = _cum(sv["rvar5"].to_numpy())
    c_on = _cum(sv["overnight_var"].to_numpy())

    diag = {"dates_seen": 0, "no_expiry": 0, "no_spot": 0, "expiry_past_archive": 0,
            "iv_failed": 0, "kept": 0}
    out: list[dict] = []

    for date, day in op.groupby("date", sort=True):
        diag["dates_seen"] += 1
        if date not in pos:
            diag["no_spot"] += 1
            continue
        expiry = nc._next_expiry(date, expiries)
        if expiry is None:
            diag["no_expiry"] += 1
            continue
        if expiry not in pos:
            # expiry falls outside the hydrated archive -> the target is not observable
            diag["expiry_past_archive"] += 1
            continue

        i, j = pos[date], pos[expiry]
        n_sess = float(j - i + 1)
        T = n_sess / SESSIONS_PER_YEAR

        S0 = float(day["spot"].iloc[0])
        strikes = day["strike"].to_numpy(dtype=float)
        atm = float(strikes[np.argmin(np.abs(strikes - S0))])
        atm_rows = day[day["strike"] == atm]

        ivs, vend = [], []
        for side in ("CALL", "PUT"):
            r = atm_rows[atm_rows["side"] == side]
            if r.empty:
                continue
            px = float(r["close"].iloc[0])
            s = invert_iv(side, px, S0, atm, T)
            if np.isfinite(s):
                ivs.append(s)
            v = float(r["iv"].iloc[0])
            if v > 0:
                vend.append(v)
        if not ivs:
            diag["iv_failed"] += 1
            continue
        iv = float(np.mean(ivs)) * 100.0

        # ---- target: realised variance from 09:15 on `date` to 15:29 on `expiry` ----
        # intraday sessions i..j inclusive; nights are those PRECEDING sessions i+1..j
        intra1 = float(c_rvar1[j + 1] - c_rvar1[i])
        intra5 = float(c_rvar5[j + 1] - c_rvar5[i])
        night = float(c_on[j + 1] - c_on[i + 1])

        def ann(v: float) -> float:
            return float(np.sqrt(max(v, 0.0) / T)) * 100.0

        row = {
            "date": date, "expiry": expiry, "n_sess": n_sess, "T_trading": T,
            "spot_open": S0, "atm_strike": atm,
            "iv": iv,
            "iv_vendor": float(np.mean(vend)) if vend else np.nan,
            "n_iv_sides": len(ivs),
            "rv_incl": ann(intra1 + night),      # HEADLINE  (STATE-06)
            "rv_intra": ann(intra1),             # SECONDARY (STATE-07)
            "rv_incl5": ann(intra5 + night),     # 5-minute sampling sensitivity
            "overnight_share": night / (intra1 + night) if (intra1 + night) > 0 else np.nan,
            "is_expiry_day": int(expiry == date),
        }
        row["vrp_incl"] = row["rv_incl"] - iv
        row["vrp_intra"] = row["rv_intra"] - iv
        row["vrp_incl5"] = row["rv_incl5"] - iv

        # ---- predictors: trailing windows ending 15:29 of session i-1 ----
        for w in (1, 5, 22):
            a = i - w
            if a < 0:
                row[f"rv{w}"] = np.nan
                continue
            v = float(c_rvar1[i] - c_rvar1[a]) + float(c_on[i] - c_on[a + 1])
            row[f"rv{w}"] = float(np.sqrt(max(v, 0.0) / (w / SESSIONS_PER_YEAR))) * 100.0

        prev_close = float(sv["close_spot"].iloc[i - 1]) if i >= 1 else np.nan
        row["gap"] = (S0 / prev_close - 1.0) * 100.0 if np.isfinite(prev_close) else np.nan
        row["dow"] = pd.Timestamp(date).dayofweek
        out.append(row)
        diag["kept"] += 1

    panel = pd.DataFrame(out).sort_values("date").reset_index(drop=True)
    panel["carry"] = panel["rv22"] - panel["iv"]
    panel["abs_gap"] = panel["gap"].abs()
    panel["year"] = panel["date"].str.slice(0, 4).astype(int)

    # India VIX block (reduced sample, DATA-05)
    k2 = pd.read_csv("k2_expiry_vix_rose_panel.csv")
    k2["date"] = pd.to_datetime(k2["date"]).dt.strftime("%Y-%m-%d")
    keep = k2[["date", "vix_open", "vix_prior_session_close", "vix_known_by_decision"]].copy()
    keep["vix_open"] = pd.to_numeric(keep["vix_open"], errors="coerce")
    keep["vix_prior_session_close"] = pd.to_numeric(keep["vix_prior_session_close"], errors="coerce")
    keep["vix_ok"] = keep["vix_known_by_decision"].astype(str).str.lower().eq("true")
    keep.loc[~keep["vix_ok"], ["vix_open", "vix_prior_session_close"]] = np.nan
    keep["vix_on_gap"] = keep["vix_open"] - keep["vix_prior_session_close"]
    panel = panel.merge(keep[["date", "vix_open", "vix_on_gap"]], on="date", how="left")

    # expiry-cycle id, for the non-overlapping subsample (OOS-05)
    panel["cycle"] = panel["expiry"]

    diag["date_min"] = panel["date"].min()
    diag["date_max"] = panel["date"].max()
    diag["n_rows"] = int(len(panel))
    diag["vix_rows"] = int(panel["vix_open"].notna().sum())
    return panel, diag


def load_panel(rebuild: bool = False) -> pd.DataFrame:
    if PANEL_CACHE.exists() and not rebuild:
        return pd.read_pickle(PANEL_CACHE)
    panel, diag = build_panel()
    tmp = PANEL_CACHE.with_suffix(".incoming")
    panel.to_pickle(tmp)
    os.replace(tmp, PANEL_CACHE)
    PANEL_AUDIT.write_text(json.dumps(diag, indent=2, default=str))
    return panel


if __name__ == "__main__":
    p = load_panel(rebuild=True)
    print(PANEL_AUDIT.read_text())
    print(p[["date", "expiry", "n_sess", "iv", "rv_incl", "rv_intra", "vrp_incl"]].head(8).to_string())
    print(p[["iv", "rv_incl", "rv_intra", "vrp_incl", "vrp_intra", "overnight_share"]].describe().to_string())
