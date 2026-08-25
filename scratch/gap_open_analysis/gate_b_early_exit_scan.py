#!/usr/bin/env python3
"""Fine-grained EARLY-EXIT scan for Gate B on the pooled N=120 population.

New module.  It does not modify, and is not imported by, any pre-existing script.  It
reuses ``gate_b_common.py`` (path construction, exit machinery, reproduction guard),
``gate_b_full_paths.py`` (the full-hydration 264-path cache) and the inference helpers in
``gate_b_exit_grid_real.py``.

The hypothesis under test
-------------------------
Aryan's claim: the published conclusion "hold to close, or at least past 14:00" is wrong.
He believes the market turns choppy somewhere mid-morning (he suggested 10:30-11:30) and
that the correct rule is to EXIT BEFORE that period rather than sit through it.

What the existing evidence already says, so it is not rediscovered as if new: on the
mid-IV N=33 grid at real premiums the short holds and early clock exits were among the
WORST variants (hold 20m -10.83% p=0.0002, hold 30m -11.00% p=0.0002, clock 10:00 -10.76%
p=0.025, clock 10:30 -12.51% p=0.0033), and on the pooled N=120 grid zero of 39 variants
had a positive mean.  This script does not try to confirm that.  It tests Aryan's specific
idea at a resolution the existing grid did not have (12 elapsed holds and 16 wall clocks
instead of 7 and 7), on the larger sample, under BOTH sample conventions, and reports what
is actually there.

Sections
--------
A. Fine early-exit grid, pooled N=120, real strike-tracked traded premiums, under both the
   traded-only convention (a day whose gap fills after the clock is dropped) and the
   full-sample convention (those days fall back to hold-to-close).
B. The choppiness claim tested directly on the NIFTY SPOT path -- realised volatility,
   signed drift in the trade's favour, and directional efficiency (net move / path length)
   per half-hour bucket.  Spot only, no option, so no decay contaminates the measurement.
C. Decay-versus-delta split per exit horizon, with implied volatility inverted under a
   TRADING-TIME maturity convention (see CORRECTION_GATE_B_VOL_CRUSH.md -- the calendar
   convention in ``gate_b_common.py`` line 186 mechanically depresses IV across a session
   and the "vol crush" story built on it is retracted).
D. Multiplicity discipline: variant count, Bonferroni, Benjamini-Hochberg, and a 5,000-draw
   shuffled-label placebo scored against the BEST-OF-GRID p-value, not a single-test null.
E. Power.

Offline analysis only.  No broker, credential, exchange network, or order path is used.
No live order exists or is authorised.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq

from bs_gap_fill_pnl import RISK_FREE_RATE, bs_call
from gate_b_common import (
    clock_exit_index,
    clock_to_minutes,
    gate_b_subset,
    horizon_exit_index,
    reproduction_guard,
    rule_return,
)
from gate_b_exit_grid_real import bh_reject, net_of_costs, summarise
from gate_b_full_paths import load_full_paths

# ------------------------------------------------------------------ the fine exit grid
# Much finer than the published 7+7.  Both ends deliberately dense, because Aryan's
# hypothesis is specifically about the 10:30-11:30 window and about short holds.
ELAPSED = (5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 90, 120)
CLOCKS = (
    "09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00",
)

SESSION_OPEN_MIN = 9 * 60 + 15      # 09:15
SESSION_CLOSE_MIN = 15 * 60 + 30    # 15:30, contract expiry stamp
TRADING_MINUTES_PER_DAY = SESSION_CLOSE_MIN - SESSION_OPEN_MIN   # 375
TRADING_DAYS_PER_YEAR = 252

N_PLACEBO = 5000
SEED = 20260823

# Half-hour wall-clock buckets for the choppiness measurement.  The first is 15 minutes
# because the session opens at 09:15; its length is carried so per-minute rates compare.
BUCKETS = (
    ("09:15", "09:30"), ("09:30", "10:00"), ("10:00", "10:30"), ("10:30", "11:00"),
    ("11:00", "11:30"), ("11:30", "12:00"), ("12:00", "12:30"), ("12:30", "13:00"),
    ("13:00", "13:30"), ("13:30", "14:00"), ("14:00", "14:30"), ("14:30", "15:00"),
    ("15:00", "15:29"),
)


# ====================================================================== trading-time T
def session_dates() -> list[pd.Timestamp]:
    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    return sorted(dm["date"].dt.normalize().unique())


def trading_minutes_to_expiry(date_str: str, clock_min: int, expiry_str: str,
                              sessions: np.ndarray) -> float:
    """Trading minutes from ``clock_min`` on ``date_str`` to 15:30 on the expiry date.

    Price variance accrues only while the market is open.  Calendar time does not.  This
    is the convention CORRECTION_GATE_B_VOL_CRUSH.md requires for any implied-volatility
    work in this project.
    """
    d = np.datetime64(pd.Timestamp(date_str).normalize())
    e = np.datetime64(pd.Timestamp(expiry_str).normalize())
    today = max(0.0, float(SESSION_CLOSE_MIN - clock_min))
    if e <= d:
        return today
    # trading sessions strictly after d and up to and including e
    between = sessions[(sessions > d) & (sessions <= e)]
    return today + TRADING_MINUTES_PER_DAY * float(len(between))


def trading_T(date_str: str, clock_min: int, expiry_str: str, sessions: np.ndarray) -> float:
    m = trading_minutes_to_expiry(date_str, clock_min, expiry_str, sessions)
    return max(m / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR), 1e-9)


def implied_vol_call(price: float, S: float, K: float, T: float, r: float) -> float:
    """Invert Black-Scholes for sigma.  Returns NaN when the price is outside no-arb bounds."""
    lo, hi = max(S - K * math.exp(-r * T), 0.0), S
    if not (lo + 1e-8 < price < hi - 1e-8):
        return float("nan")
    try:
        return float(brentq(lambda s: bs_call(S, K, T, r, s) - price, 1e-4, 5.0, xtol=1e-10))
    except ValueError:
        return float("nan")


# ============================================================================ A. grid
def variant_grid() -> list[dict]:
    """Every exit rule tested in section A.

    ``conv`` is ``"both"`` for rules where the two sample conventions coincide (the
    baseline and every elapsed hold: an elapsed hold is always feasible, it is merely
    truncated at the close on a late fill), ``"full"`` for the fall-back-to-close clock
    convention and ``"traded"`` for the drop-the-day clock convention.
    """
    out = [{"name": "hold to close", "kind": "baseline", "clock": None, "offset": None,
            "conv": "both"}]
    for h in ELAPSED:
        out.append({"name": f"hold {h}m after fill", "kind": "elapsed", "clock": None,
                    "offset": h, "conv": "both"})
    for c in CLOCKS:
        out.append({"name": f"clock {c}", "kind": "clock", "clock": c, "offset": None,
                    "conv": "full"})
    for c in CLOCKS:
        out.append({"name": f"clock {c}", "kind": "clock", "clock": c, "offset": None,
                    "conv": "traded"})
    return out


def variant_values(paths: list[dict], v: dict) -> tuple[np.ndarray, np.ndarray]:
    """``(returns, eligible)`` for one variant over ``paths``.

    Under the traded-only convention a fire whose entry is at or after the exit clock is
    marked ineligible rather than silently held to the close.
    """
    r = np.asarray(
        [rule_return(p, "real_prices", None, None, v["clock"], v["offset"]) for p in paths],
        dtype=float,
    )
    if v["conv"] == "traded":
        limit = clock_to_minutes(v["clock"])
        elig = np.asarray([p["entry_minute"] < limit for p in paths], dtype=bool)
    else:
        elig = np.ones(len(paths), dtype=bool)
    elig &= np.isfinite(r)
    return r, elig


def masked_stats(vals: np.ndarray, mask: np.ndarray) -> dict:
    x = vals[mask]
    if len(x) < 3:
        return {"N": int(len(x))}
    t = stats.ttest_1samp(x, 0.0)
    return {"N": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)),
            "win": float((x > 0).mean() * 100.0), "sd": float(x.std(ddof=1)),
            "p0": float(t.pvalue)}


def build_grid(paths: list[dict], variants: list[dict]) -> pd.DataFrame:
    base_r, base_e = variant_values(paths, variants[0])
    rows = []
    for v in variants:
        r, e = variant_values(paths, v)
        use = e & base_e
        s = masked_stats(r, use)
        if s.get("N", 0) < 3:
            continue
        d = (r - base_r)[use]
        if v["kind"] == "baseline" or np.allclose(d, 0.0):
            dmean, pb = 0.0, np.nan
        else:
            dmean = float(d.mean())
            pb = float(stats.ttest_1samp(d, 0.0).pvalue)
        rows.append({"name": v["name"], "kind": v["kind"], "conv": v["conv"],
                     "clock": v["clock"], "offset": v["offset"],
                     "mean_entry_min": float(np.mean([p["entry_minute"] for p, u
                                                      in zip(paths, use) if u])),
                     **s, "d_vs_base": dmean, "p_vs_base": pb})
    return pd.DataFrame(rows)


def print_grid(grid: pd.DataFrame, title: str) -> None:
    print(f"\n{title}")
    hdr = (f"{'variant':>22} {'conv':>7} {'N':>4} {'mean':>9} {'median':>9} {'win%':>6} "
           f"{'sd':>6} {'p vs 0':>8} {'vs base':>9} {'p vs base':>10} {'mean entry':>11}")
    print(hdr)
    print("-" * len(hdr))
    for _, r in grid.iterrows():
        pb = "n/a" if not np.isfinite(r["p_vs_base"]) else f"{r['p_vs_base']:.4f}"
        entry = f"{int(r['mean_entry_min'])//60:02d}:{int(r['mean_entry_min'])%60:02d}"
        tag = "  <- baseline" if r["kind"] == "baseline" else ""
        print(f"{r['name']:>22} {r['conv']:>7} {r['N']:>4} {r['mean']:>+8.2f}% "
              f"{r['median']:>+8.2f}% {r['win']:>5.1f}% {r['sd']:>6.1f} {r['p0']:>8.4f} "
              f"{r['d_vs_base']:>+8.2f}pp {pb:>10} {entry:>11}{tag}")


# ============================================================== B. spot-only choppiness
def spot_bucket_stats(paths: list[dict]) -> pd.DataFrame:
    """Realised volatility, signed drift and directional efficiency per wall-clock bucket.

    Only days whose entry is at or before the bucket start are counted, so every measured
    bucket is genuinely post-entry.  "Favourable" means UP, because the trade is a CALL.

    directional efficiency = net move over the bucket / total path length walked inside it.
    +1 is a clean one-way rally, 0 is pure chop, -1 is a clean one-way sell-off.  This is
    the actual definition of choppiness, as distinct from low volatility.
    """
    rows = []
    for lo, hi in BUCKETS:
        lo_m, hi_m = clock_to_minutes(lo), clock_to_minutes(hi)
        drift, eff, abseff, rv, plen, nets = [], [], [], [], [], []
        for p in paths:
            if p["entry_minute"] > lo_m:
                continue
            mins = p["entry_minute"] + p["elapsed"]
            sel = np.flatnonzero((mins >= lo_m) & (mins <= hi_m))
            if len(sel) < 5:
                continue
            s = p["spots"][sel]
            steps = np.diff(s)
            path_len = float(np.abs(steps).sum())
            if path_len <= 0:
                continue
            net = float(s[-1] - s[0])
            lr = np.diff(np.log(s))
            drift.append(net / s[0] * 100.0)
            nets.append(net)
            plen.append(path_len / s[0] * 100.0)
            eff.append(net / path_len)
            abseff.append(abs(net) / path_len)
            rv.append(float(np.sqrt(np.sum(lr ** 2)) * 100.0))
        if len(drift) < 5:
            continue
        drift = np.asarray(drift)
        rows.append({
            "bucket": f"{lo}-{hi}", "minutes": hi_m - lo_m, "N": len(drift),
            "drift_mean_pct": float(drift.mean()),
            "drift_median_pct": float(np.median(drift)),
            "drift_up_share": float((drift > 0).mean() * 100.0),
            "drift_p": float(stats.ttest_1samp(drift, 0.0).pvalue),
            "net_points_mean": float(np.mean(nets)),
            "rv_pct_mean": float(np.mean(rv)),
            "rv_per_min_bp": float(np.mean(rv)) * 100.0 / (hi_m - lo_m),
            "path_len_pct_mean": float(np.mean(plen)),
            "signed_eff_mean": float(np.mean(eff)),
            "abs_eff_mean": float(np.mean(abseff)),
            "abs_eff_median": float(np.median(abseff)),
        })
    return pd.DataFrame(rows)


def window_efficiency_test(paths: list[dict],
                           window=("10:30", "11:30")) -> dict:
    """Formal test of the mid-morning collapse: is directional efficiency inside Aryan's
    10:30-11:30 window lower than in the rest of the post-entry session?

    One observation per (day, half-hour bucket), so the two groups are compared on the
    same measurement unit.  Welch t-test, plus the same comparison for realised volatility
    per minute.
    """
    lo, hi = clock_to_minutes(window[0]), clock_to_minutes(window[1])
    inside_e, outside_e, inside_v, outside_v = [], [], [], []
    for b_lo, b_hi in BUCKETS:
        bl, bh = clock_to_minutes(b_lo), clock_to_minutes(b_hi)
        is_in = (bl >= lo) and (bh <= hi)
        for p in paths:
            if p["entry_minute"] > bl:
                continue
            mins = p["entry_minute"] + p["elapsed"]
            sel = np.flatnonzero((mins >= bl) & (mins <= bh))
            if len(sel) < 5:
                continue
            s = p["spots"][sel]
            plen = float(np.abs(np.diff(s)).sum())
            if plen <= 0:
                continue
            eff = abs(float(s[-1] - s[0])) / plen
            rv = float(np.sqrt(np.sum(np.diff(np.log(s)) ** 2))) * 100.0 / (bh - bl) * 100.0
            (inside_e if is_in else outside_e).append(eff)
            (inside_v if is_in else outside_v).append(rv)
    ie, oe = np.asarray(inside_e), np.asarray(outside_e)
    iv, ov = np.asarray(inside_v), np.asarray(outside_v)
    te, pe = stats.ttest_ind(ie, oe, equal_var=False)
    tv, pv = stats.ttest_ind(iv, ov, equal_var=False)
    return {"window": f"{window[0]}-{window[1]}",
            "n_inside": int(len(ie)), "n_outside": int(len(oe)),
            "eff_inside": float(ie.mean()), "eff_outside": float(oe.mean()),
            "eff_diff": float(ie.mean() - oe.mean()), "eff_p": float(pe),
            "rv_bp_min_inside": float(iv.mean()), "rv_bp_min_outside": float(ov.mean()),
            "rv_diff": float(iv.mean() - ov.mean()), "rv_p": float(pv)}


def cumulative_spot_drift(paths: list[dict]) -> pd.DataFrame:
    """Mean SPOT return from entry to each wall clock, days entered before that clock."""
    rows = []
    for c in CLOCKS + ("15:29",):
        limit = clock_to_minutes(c)
        vals = []
        for p in paths:
            if p["entry_minute"] >= limit:
                continue
            i = clock_exit_index(p, None if c == "15:29" else c)
            vals.append((p["spots"][i] - p["S0"]) / p["S0"] * 100.0)
        if len(vals) < 5:
            continue
        v = np.asarray(vals)
        rows.append({"clock": c, "N": len(v), "mean_pct": float(v.mean()),
                     "median_pct": float(np.median(v)),
                     "up_share": float((v > 0).mean() * 100.0),
                     "p": float(stats.ttest_1samp(v, 0.0).pvalue)})
    return pd.DataFrame(rows)


def elapsed_spot_drift(paths: list[dict]) -> pd.DataFrame:
    """Mean SPOT return from entry at each elapsed horizon, all 120 days, plus the
    incremental drift earned inside each elapsed interval."""
    rows = []
    prev = np.zeros(len(paths))
    for h in ELAPSED + (10_000,):
        vals = np.asarray([
            (p["spots"][horizon_exit_index(p, h)] - p["S0"]) / p["S0"] * 100.0
            for p in paths
        ])
        inc = vals - prev
        rows.append({"horizon": "close" if h == 10_000 else f"{h}m", "N": len(vals),
                     "cum_mean_pct": float(vals.mean()),
                     "cum_median_pct": float(np.median(vals)),
                     "cum_up_share": float((vals > 0).mean() * 100.0),
                     "cum_p": float(stats.ttest_1samp(vals, 0.0).pvalue),
                     "incremental_mean_pct": float(inc.mean()),
                     "incremental_p": float(stats.ttest_1samp(inc, 0.0).pvalue)})
        prev = vals
    return pd.DataFrame(rows)


def premium_path_by_clock(paths: list[dict]) -> pd.DataFrame:
    """Mean REAL premium return from entry to each wall clock, days entered before it.

    This is the direct P&L analogue of the spot table: if there is a clean early-exit
    window it has to show up as a hump here.
    """
    rows = []
    for c in ("09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15",
              "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00",
              "15:29"):
        limit = clock_to_minutes(c)
        vals = []
        for p in paths:
            if p["entry_minute"] >= limit:
                continue
            i = clock_exit_index(p, None if c == "15:29" else c)
            C0 = p["real_prices"][0]
            vals.append((p["real_prices"][i] - C0) / C0 * 100.0)
        v = np.asarray(vals)
        rows.append({"clock": c, "N": len(v), "mean_pct": float(v.mean()),
                     "median_pct": float(np.median(v)),
                     "win": float((v > 0).mean() * 100.0)})
    return pd.DataFrame(rows)


def peak_timing(paths: list[dict]) -> dict:
    """When during the session does each trade's premium actually peak?"""
    peak_clocks, peak_rets, close_rets, peak_elapsed = [], [], [], []
    for p in paths:
        C0 = p["real_prices"][0]
        r = (p["real_prices"] - C0) / C0 * 100.0
        i = int(np.nanargmax(r))
        peak_clocks.append(p["entry_minute"] + int(p["elapsed"][i]))
        peak_elapsed.append(int(p["elapsed"][i]))
        peak_rets.append(float(r[i]))
        close_rets.append(float(r[-1]))
    pc = np.asarray(peak_clocks)
    return {
        "median_peak_clock_min": float(np.median(pc)),
        "share_peak_before_1100": float((pc < clock_to_minutes("11:00")).mean() * 100.0),
        "share_peak_before_1200": float((pc < clock_to_minutes("12:00")).mean() * 100.0),
        "share_peak_after_1400": float((pc >= clock_to_minutes("14:00")).mean() * 100.0),
        "median_peak_elapsed_min": float(np.median(peak_elapsed)),
        "mean_peak_return": float(np.mean(peak_rets)),
        "mean_close_return": float(np.mean(close_rets)),
        "mean_giveback": float(np.mean(np.asarray(peak_rets) - np.asarray(close_rets))),
        "peak_clock_deciles": [float(np.percentile(pc, q)) for q in range(10, 100, 10)],
    }


# ================================================================ C. decay vs delta
def decay_delta_split(paths: list[dict], sessions: np.ndarray) -> pd.DataFrame:
    """Split each exit horizon's real return into spot, decay, cross and residual legs.

    Implied volatility is inverted ONCE per trade, from the TRADED entry premium, under a
    trading-time maturity.  The model price at entry therefore equals the traded entry
    premium exactly, so the decomposition is anchored on the real trade rather than on a
    proxy.  With P(S, T) = BS(S, K, T, r, sigma_entry):

        spot_only = [P(S_H, T_0) - P(S_0, T_0)] / C0_real
        decay     = [P(S_0, T_H) - P(S_0, T_0)] / C0_real
        cross     = [P(S_H, T_H) - P(S_0, T_0)] / C0_real - spot_only - decay
        residual  = [real_H     - P(S_H, T_H)] / C0_real      <- implied-vol change + basis
        total     = spot_only + decay + cross + residual      <- exact by construction

    ``residual`` is the only leg that is not model-determined; it collects any genuine
    change in the contract's implied volatility between entry and exit, plus any
    Black-Scholes mis-specification.  It is reported, not assumed away.
    """
    prepared = []
    for p in paths:
        T0 = trading_T(p["date"], p["entry_minute"], p["expiry"], sessions)
        C0 = float(p["real_prices"][0])
        iv = implied_vol_call(C0, p["S0"], p["K"], T0, RISK_FREE_RATE)
        if not np.isfinite(iv):
            continue
        prepared.append((p, T0, C0, iv))

    rows = []
    horizons = [("elapsed", h) for h in ELAPSED] + [("clock", c) for c in CLOCKS] + \
               [("close", None)]
    for kind, h in horizons:
        so, dc, cr, rs, tt, mins = [], [], [], [], [], []
        for p, T0, C0, iv in prepared:
            if kind == "elapsed":
                i = horizon_exit_index(p, h)
            elif kind == "clock":
                i = clock_exit_index(p, h)
            else:
                i = len(p["clocks"]) - 1
            exit_min = p["entry_minute"] + int(p["elapsed"][i])
            TH = trading_T(p["date"], exit_min, p["expiry"], sessions)
            SH = float(p["spots"][i])
            K = p["K"]
            p_ss = bs_call(SH, K, T0, RISK_FREE_RATE, iv)
            p_tt = bs_call(p["S0"], K, TH, RISK_FREE_RATE, iv)
            p_hh = bs_call(SH, K, TH, RISK_FREE_RATE, iv)
            spot_leg = (p_ss - C0) / C0 * 100.0
            decay_leg = (p_tt - C0) / C0 * 100.0
            cross_leg = (p_hh - C0) / C0 * 100.0 - spot_leg - decay_leg
            resid = (float(p["real_prices"][i]) - p_hh) / C0 * 100.0
            so.append(spot_leg); dc.append(decay_leg); cr.append(cross_leg)
            rs.append(resid); tt.append((float(p["real_prices"][i]) - C0) / C0 * 100.0)
            mins.append(int(p["elapsed"][i]))
        name = "close" if kind == "close" else (f"hold {h}m" if kind == "elapsed"
                                                else f"clock {h}")
        rows.append({"horizon": name, "kind": kind, "N": len(tt),
                     "mean_held_min": float(np.mean(mins)),
                     "total": float(np.mean(tt)), "spot_leg": float(np.mean(so)),
                     "decay_leg": float(np.mean(dc)), "cross_leg": float(np.mean(cr)),
                     "resid_leg": float(np.mean(rs)),
                     "decay_per_min": float(np.mean(dc)) / max(np.mean(mins), 1e-9),
                     "spot_p": float(stats.ttest_1samp(so, 0.0).pvalue),
                     "resid_p": float(stats.ttest_1samp(rs, 0.0).pvalue)})
    entry_ivs = np.asarray([iv for _, _, _, iv in prepared])
    return pd.DataFrame(rows), entry_ivs, len(prepared)


# =========================================================== D. placebo / multiplicity
def placebo(pool: list[dict], variants: list[dict], n_draw: int,
            obs_best_p0: float, obs_best_pb: float, obs_best_mean: float) -> dict:
    """Westfall-Young style max-statistic placebo.

    Each draw reassigns the pooled Gate-B label at random among all non-expiry gap-down
    days whose gap fills after 09:17 and which are priceable on real traded premiums, then
    re-runs the ENTIRE fine grid and records the best-of-grid statistic.  This preserves N,
    the CALL direction, the gap-fill entry mechanism, the entry-time distribution and the
    whole exit machinery; it destroys only the association with an overnight VIX rise.
    """
    V = np.vstack([variant_values(pool, v)[0] for v in variants])
    M = np.vstack([variant_values(pool, v)[1] for v in variants])
    base_v, base_m = V[0], M[0]
    M &= base_m[None, :]
    keep = M.any(axis=0)
    V, M = V[:, keep], M[:, keep]
    base_v = base_v[keep]
    V = np.nan_to_num(V, nan=0.0)

    rng = np.random.default_rng(SEED)
    k = len(variants)
    best_p0 = np.empty(N_PLACEBO)
    best_pb = np.empty(N_PLACEBO)
    best_mean = np.empty(N_PLACEBO)
    any0 = anyb = 0
    for d in range(N_PLACEBO):
        idx = rng.choice(V.shape[1], size=n_draw, replace=False)
        sub, m = V[:, idx], M[:, idx].astype(float)
        n = m.sum(axis=1)
        mean = (sub * m).sum(axis=1) / np.maximum(n, 1)
        var = (((sub - mean[:, None]) ** 2) * m).sum(axis=1) / np.maximum(n - 1, 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = mean / np.sqrt(np.maximum(var, 1e-12) / np.maximum(n, 1))
        p0 = 2.0 * stats.t.sf(np.abs(t), df=np.maximum(n - 1, 1))
        p0[n < 3] = 1.0

        dd = (sub - base_v[idx][None, :])
        dmean = (dd * m).sum(axis=1) / np.maximum(n, 1)
        dvar = (((dd - dmean[:, None]) ** 2) * m).sum(axis=1) / np.maximum(n - 1, 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            tb = dmean / np.sqrt(np.maximum(dvar, 1e-12) / np.maximum(n, 1))
        pb = 2.0 * stats.t.sf(np.abs(tb), df=np.maximum(n - 1, 1))
        pb[n < 3] = 1.0
        pb[dvar <= 1e-12] = 1.0
        pb[0] = 1.0                       # the baseline cannot beat itself

        best_p0[d] = np.nanmin(p0)
        best_pb[d] = np.nanmin(pb)
        best_mean[d] = np.nanmax(mean)
        any0 += int(np.nanmin(p0) < 0.05)
        anyb += int(np.nanmin(pb) < 0.05)
    return {
        "pool_n": int(V.shape[1]), "draws": N_PLACEBO,
        "obs_best_p0": obs_best_p0, "obs_best_pb": obs_best_pb,
        "obs_best_mean": obs_best_mean,
        "placebo_best_p0_median": float(np.median(best_p0)),
        "placebo_best_p0_5pct": float(np.percentile(best_p0, 5)),
        "empirical_p_best_p0": float(np.mean(best_p0 <= obs_best_p0)),
        "placebo_best_pb_median": float(np.median(best_pb)),
        "placebo_best_pb_5pct": float(np.percentile(best_pb, 5)),
        "empirical_p_best_pb": float(np.mean(best_pb <= obs_best_pb)),
        "placebo_best_mean_median": float(np.median(best_mean)),
        "placebo_best_mean_95pct": float(np.percentile(best_mean, 95)),
        "empirical_p_best_mean": float(np.mean(best_mean >= obs_best_mean)),
        "share_any_sig_vs_zero": float(any0 / N_PLACEBO * 100.0),
        "share_any_sig_vs_base": float(anyb / N_PLACEBO * 100.0),
    }


def required_d(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    crit = stats.t.ppf(1 - alpha / 2, df=n - 1)

    def f(d):
        nc = d * np.sqrt(n)
        return (stats.nct.sf(crit, n - 1, nc) + stats.nct.cdf(-crit, n - 1, nc)) - power

    return float(brentq(f, 1e-4, 5.0))


# ======================================================= B2. the give-back mechanism test
def giveback_test(paths: list[dict], clocks=("10:00", "10:30", "11:00", "11:30")) -> pd.DataFrame:
    """Aryan's mechanism, stated as a testable proposition.

    If the trade earns its money early and then gives it back through a choppy period,
    then trades that are UP at an early clock should LOSE ground between that clock and
    the close, reliably.  If instead the winners keep running, taking profit early is
    destroying the trade rather than saving it.

    Only fires already entered before the clock are used.  These are conditional
    diagnostics, not exit rules, and they are counted separately from the 45 grid
    variants in section D.
    """
    rows = []
    for c in clocks:
        limit = clock_to_minutes(c)
        up, dn = [], []
        for p in paths:
            if p["entry_minute"] >= limit:
                continue
            i = clock_exit_index(p, c)
            C0, Ci, Cn = (float(p["real_prices"][0]), float(p["real_prices"][i]),
                          float(p["real_prices"][-1]))
            r_to_c = (Ci - C0) / C0 * 100.0
            r_c_to_close = (Cn - Ci) / Ci * 100.0
            (up if r_to_c > 0 else dn).append(r_c_to_close)
        for label, x in (("up at clock", up), ("down at clock", dn)):
            x = np.asarray(x)
            if len(x) < 5:
                continue
            rows.append({"clock": c, "group": label, "N": len(x),
                         "mean_clock_to_close": float(x.mean()),
                         "median_clock_to_close": float(np.median(x)),
                         "share_positive": float((x > 0).mean() * 100.0),
                         "p": float(stats.ttest_1samp(x, 0.0).pvalue)})
    return pd.DataFrame(rows)


def bleed_rate(grid: pd.DataFrame, paths: list[dict], variants: list[dict]) -> pd.DataFrame:
    """Loss per minute held, for every variant.

    An early exit that loses less in total may simply be a smaller bet rather than a
    better one.  Dividing by the minutes actually held distinguishes the two.
    """
    rows = []
    for v in variants:
        r, e = variant_values(paths, v)
        held = []
        for p, ok in zip(paths, e):
            if not ok:
                continue
            i = (horizon_exit_index(p, v["offset"]) if v["offset"] is not None
                 else clock_exit_index(p, v["clock"]))
            held.append(int(p["elapsed"][i]))
        if len(held) < 3:
            continue
        m = float(np.mean(held))
        mean = float(r[e].mean())
        rows.append({"name": v["name"], "conv": v["conv"], "N": int(e.sum()),
                     "mean_held_min": m, "mean": mean,
                     "pct_per_min": mean / max(m, 1e-9)})
    return pd.DataFrame(rows)


# ==================================================================================
def main() -> None:
    paths = load_full_paths()
    reproduction_guard(gate_b_subset(paths))
    fires = [p for p in paths if p["vix_rose"] == 1]
    sessions = np.asarray([np.datetime64(d) for d in session_dates()])

    print("=" * 116)
    print("GATE B FINE EARLY-EXIT SCAN -- POOLED N=120, REAL STRIKE-TRACKED TRADED PREMIUMS")
    print("=" * 116)
    print("Hypothesis under test (Aryan): the market turns choppy mid-morning, roughly")
    print("10:30-11:30, and the right rule is to EXIT BEFORE it rather than hold to close.")
    print(f"\nPopulation: non-expiry + gap-down + overnight VIX rose + gap filled after 09:17.")
    print(f"Fires: {len(fires)}  (low {sum(p['iv_bucket']=='low_<14' for p in fires)}, "
          f"mid {sum(p['iv_bucket']=='middle_14_18' for p in fires)}, "
          f"high {sum(p['iv_bucket']=='high_>18' for p in fires)})   "
          f"{fires[0]['date']} .. {fires[-1]['date']}")
    nan_free = sum(int(not np.isnan(p["real_prices"]).any()) for p in fires)
    print(f"Fires priceable on real traded premiums at EVERY minute from entry to 15:29: "
          f"{nan_free}/{len(fires)}")
    ent = np.asarray([p["entry_minute"] for p in fires])
    print(f"Entry clock: min {ent.min()//60:02d}:{ent.min()%60:02d}, "
          f"median {int(np.median(ent))//60:02d}:{int(np.median(ent))%60:02d}, "
          f"max {ent.max()//60:02d}:{ent.max()%60:02d}   "
          f"share entering before 10:30: {(ent < 630).mean()*100:.1f}%")

    variants = variant_grid()
    grid = build_grid(fires, variants)
    grid.to_csv("gate_b_early_exit_grid.csv", index=False)

    print("\n" + "=" * 116)
    print("A.  THE FINE EARLY-EXIT GRID")
    print("=" * 116)
    print("Convention (i) FULL SAMPLE: a fire entering at or after the exit clock falls back")
    print("to hold-to-close, so N stays at 120 and the sample never changes composition.")
    print("Convention (ii) TRADED ONLY: those fires are dropped.  N falls and the surviving")
    print("sample tilts toward EARLY fills -- the published Gate-B figures use this one, and")
    print("it is a real confound for an early-exit hypothesis, so both are reported.")
    print_grid(grid[grid["conv"].isin(("both", "full"))],
               "(i) elapsed holds and clock exits, FULL-SAMPLE convention, N=120 throughout")
    print_grid(grid[grid["conv"] == "traded"],
               "(ii) clock exits, TRADED-ONLY convention (N falls as the clock moves earlier)")

    pos = grid[grid["mean"] > 0]
    print(f"\n  Variants tested in section A: {len(grid)} "
          f"(1 baseline + {len(ELAPSED)} elapsed holds + {len(CLOCKS)} clocks x 2 conventions)")
    print(f"  Variants with a POSITIVE mean return: {len(pos)} of {len(grid)}"
          + ("" if pos.empty else "  -> " + ", ".join(
              f"{r['name']} [{r['conv']}] {r['mean']:+.2f}%" for _, r in pos.iterrows())))
    best = grid.loc[grid["mean"].idxmax()]
    worst = grid.loc[grid["mean"].idxmin()]
    print(f"  Best mean : {best['name']} [{best['conv']}]  {best['mean']:+.2f}%  "
          f"(N={best['N']}, p vs 0 = {best['p0']:.4f}, {best['d_vs_base']:+.2f}pp vs baseline)")
    print(f"  Worst mean: {worst['name']} [{worst['conv']}] {worst['mean']:+.2f}%  "
          f"(N={worst['N']}, p vs 0 = {worst['p0']:.4f})")
    early = grid[(grid["kind"] == "clock") & (grid["conv"] == "full") &
                 (grid["clock"] <= "11:30")]
    late = grid[(grid["kind"] == "clock") & (grid["conv"] == "full") &
                (grid["clock"] > "11:30")]
    print(f"\n  Aryan's window, full-sample convention:")
    print(f"    mean of clock exits at or before 11:30 : {early['mean'].mean():+.2f}% "
          f"({len(early)} variants)")
    print(f"    mean of clock exits after 11:30        : {late['mean'].mean():+.2f}% "
          f"({len(late)} variants)")
    print(f"    hold to close                          : "
          f"{grid[grid['kind']=='baseline']['mean'].iloc[0]:+.2f}%")

    print("\n  BEST 8 AND WORST 5 ACROSS BOTH CONVENTIONS")
    ranked = grid.sort_values("mean", ascending=False)
    print_grid(ranked.head(8), "  best 8 by mean")
    print_grid(ranked.tail(5).iloc[::-1], "  worst 5 by mean")

    # ------------------------------------------------------------------- B. choppiness
    print("\n" + "=" * 116)
    print("B.  THE CHOPPINESS CLAIM, MEASURED DIRECTLY ON THE NIFTY SPOT PATH")
    print("=" * 116)
    print("Spot only.  No option, therefore no time decay and no volatility path can")
    print("contaminate this.  Only days already entered at the bucket start are counted.")
    print("Directional efficiency = net move / total path length walked: +1 is a clean")
    print("one-way rally, 0 is pure chop, -1 is a clean one-way sell-off.\n")
    bs = spot_bucket_stats(fires)
    bs.to_csv("gate_b_early_exit_spot_buckets.csv", index=False)
    hdr = (f"{'bucket':>13} {'min':>4} {'N':>4} {'drift %':>9} {'median':>8} {'up%':>6} "
           f"{'p':>7} {'net pts':>8} {'RV %':>7} {'RV bp/min':>10} {'path %':>7} "
           f"{'signed eff':>11} {'|eff|':>7}")
    print(hdr); print("-" * len(hdr))
    for _, r in bs.iterrows():
        print(f"{r['bucket']:>13} {int(r['minutes']):>4} {int(r['N']):>4} "
              f"{r['drift_mean_pct']:>+8.3f}% {r['drift_median_pct']:>+7.3f}% "
              f"{r['drift_up_share']:>5.1f}% {r['drift_p']:>7.3f} "
              f"{r['net_points_mean']:>+8.1f} {r['rv_pct_mean']:>6.3f}% "
              f"{r['rv_per_min_bp']:>10.2f} {r['path_len_pct_mean']:>6.3f}% "
              f"{r['signed_eff_mean']:>+11.4f} {r['abs_eff_mean']:>7.4f}")

    we = window_efficiency_test(fires)
    print(f"\n  IS THERE A MID-MORNING COLLAPSE IN DIRECTIONAL EFFICIENCY?  "
          f"(window {we['window']})")
    print(f"    |efficiency| inside the window : {we['eff_inside']:.4f} "
          f"(n={we['n_inside']} day-buckets)")
    print(f"    |efficiency| outside it        : {we['eff_outside']:.4f} "
          f"(n={we['n_outside']})")
    print(f"    difference                     : {we['eff_diff']:+.4f}, Welch p = {we['eff_p']:.4f}")
    print(f"    realised vol inside, bp/min    : {we['rv_bp_min_inside']:.3f}")
    print(f"    realised vol outside, bp/min   : {we['rv_bp_min_outside']:.3f}")
    print(f"    difference                     : {we['rv_diff']:+.3f}, Welch p = {we['rv_p']:.4f}")

    print("\n  CUMULATIVE SPOT DRIFT FROM ENTRY, BY WALL CLOCK (favourable = positive)")
    cd = cumulative_spot_drift(fires)
    cd.to_csv("gate_b_early_exit_spot_cumulative.csv", index=False)
    print(f"    {'clock':>7} {'N':>4} {'mean %':>9} {'median %':>9} {'up%':>6} {'p':>8}")
    print("    " + "-" * 46)
    for _, r in cd.iterrows():
        print(f"    {r['clock']:>7} {int(r['N']):>4} {r['mean_pct']:>+8.3f}% "
              f"{r['median_pct']:>+8.3f}% {r['up_share']:>5.1f}% {r['p']:>8.4f}")

    print("\n  SPOT DRIFT BY ELAPSED TIME FROM ENTRY (all 120 fires, no sample change)")
    ed = elapsed_spot_drift(fires)
    ed.to_csv("gate_b_early_exit_spot_elapsed.csv", index=False)
    print(f"    {'H':>7} {'N':>4} {'cum mean %':>11} {'median %':>9} {'up%':>6} {'cum p':>8} "
          f"{'increment':>11} {'inc p':>8}")
    print("    " + "-" * 70)
    for _, r in ed.iterrows():
        print(f"    {r['horizon']:>7} {int(r['N']):>4} {r['cum_mean_pct']:>+10.3f}% "
              f"{r['cum_median_pct']:>+8.3f}% {r['cum_up_share']:>5.1f}% {r['cum_p']:>8.4f} "
              f"{r['incremental_mean_pct']:>+10.3f}% {r['incremental_p']:>8.4f}")

    print("\n  MEAN REAL PREMIUM RETURN FROM ENTRY, BY WALL CLOCK (the P&L analogue)")
    pp = premium_path_by_clock(fires)
    pp.to_csv("gate_b_early_exit_premium_path.csv", index=False)
    print(f"    {'clock':>7} {'N':>4} {'mean %':>9} {'median %':>9} {'win%':>6}")
    print("    " + "-" * 40)
    for _, r in pp.iterrows():
        print(f"    {r['clock']:>7} {int(r['N']):>4} {r['mean_pct']:>+8.2f}% "
              f"{r['median_pct']:>+8.2f}% {r['win']:>5.1f}%")

    pk = peak_timing(fires)
    print("\n  WHEN DOES EACH TRADE'S PREMIUM ACTUALLY PEAK? (perfect-hindsight exit)")
    mp = int(pk["median_peak_clock_min"])
    print(f"    median peak clock                : {mp//60:02d}:{mp%60:02d}")
    print(f"    median elapsed minutes to peak   : {pk['median_peak_elapsed_min']:.0f}")
    print(f"    share peaking before 11:00       : {pk['share_peak_before_1100']:.1f}%")
    print(f"    share peaking before 12:00       : {pk['share_peak_before_1200']:.1f}%")
    print(f"    share peaking at or after 14:00  : {pk['share_peak_after_1400']:.1f}%")
    print(f"    mean perfect-hindsight peak return: {pk['mean_peak_return']:+.2f}%   "
          f"mean close return {pk['mean_close_return']:+.2f}%   "
          f"giveback {pk['mean_giveback']:.2f}pp")

    print("\n  DOES THE TRADE GIVE BACK EARLY GAINS?  (Aryan's mechanism, stated as a test)")
    print("  Return from the stated clock to the close, split by whether the trade was")
    print("  already in profit at that clock.  If early gains are given back through a")
    print("  choppy period, the 'up at clock' rows must be reliably negative.")
    gb = giveback_test(fires)
    gb.to_csv("gate_b_early_exit_giveback.csv", index=False)
    print(f"    {'clock':>7} {'group':>15} {'N':>4} {'mean to close':>14} {'median':>9} "
          f"{'pos%':>6} {'p':>8}")
    print("    " + "-" * 68)
    for _, r in gb.iterrows():
        print(f"    {r['clock']:>7} {r['group']:>15} {int(r['N']):>4} "
              f"{r['mean_clock_to_close']:>+13.2f}% {r['median_clock_to_close']:>+8.2f}% "
              f"{r['share_positive']:>5.1f}% {r['p']:>8.4f}")

    print("\n  LOSS PER MINUTE HELD -- is a short hold a better trade or just a smaller one?")
    br = bleed_rate(grid, fires, variants)
    br.to_csv("gate_b_early_exit_bleed_rate.csv", index=False)
    brs = br.sort_values("mean_held_min")
    print(f"    {'variant':>22} {'conv':>7} {'N':>4} {'held min':>9} {'mean':>9} "
          f"{'% per minute held':>18}")
    print("    " + "-" * 74)
    for _, r in brs.iterrows():
        print(f"    {r['name']:>22} {r['conv']:>7} {int(r['N']):>4} "
              f"{r['mean_held_min']:>9.1f} {r['mean']:>+8.2f}% {r['pct_per_min']:>+17.4f}")

    print("\n  NET OF COSTS, top variants by gross mean (base case 0.35% half-spread each")
    print("  way, plus brokerage, STT, exchange, SEBI, stamp and GST -- the same cost model")
    print("  as GATE_B_REAL_PREMIUM_VALIDATION.md section 8.  The round trip is paid once")
    print("  regardless of how long the position is held, so a short hold gets no discount.")
    print(f"    {'variant':>22} {'conv':>7} {'N':>4} {'gross':>9} {'net 0.35%':>10} "
          f"{'net 1.00%':>10} {'p (net 0.35%)':>14}")
    print("    " + "-" * 80)
    by_key = {(v["name"], v["conv"]): v for v in variants}
    for _, r in grid.sort_values("mean", ascending=False).head(8).iterrows():
        src_v = by_key[(r["name"], r["conv"])]
        # Build the variant dict from the canonical list, NOT from the DataFrame row:
        # pandas coerces a None offset to NaN on a mixed column, and NaN is not None, so
        # rule_return would take the elapsed-horizon branch and exit at the entry minute.
        v = {"stop": None, "target": None, "clock": src_v["clock"],
             "offset": src_v["offset"]}
        sel = fires
        if r["conv"] == "traded":
            sel = [p for p in fires if p["entry_minute"] < clock_to_minutes(r["clock"])]
        nets = {}
        for hs in (0.35, 1.00):
            x = net_of_costs(sel, "real_prices", v, hs)
            nets[hs] = x[np.isfinite(x)]
        print(f"    {r['name']:>22} {r['conv']:>7} {len(nets[0.35]):>4} {r['mean']:>+8.2f}% "
              f"{nets[0.35].mean():>+9.2f}% {nets[1.00].mean():>+9.2f}% "
              f"{stats.ttest_1samp(nets[0.35], 0.0).pvalue:>14.4f}")

    # ------------------------------------------------------------- C. decay vs delta
    print("\n" + "=" * 116)
    print("C.  DECAY VERSUS DELTA, TRADING-TIME MATURITY CONVENTION")
    print("=" * 116)
    dd, ivs, n_iv = decay_delta_split(fires, sessions)
    dd.to_csv("gate_b_early_exit_decay_split.csv", index=False)
    print(f"Implied volatility inverted once per trade from the TRADED entry premium under a")
    print(f"trading-time maturity (375 min/session, 252 sessions/year).  N = {n_iv}/{len(fires)}")
    print(f"invertible.  Mean entry IV {ivs.mean()*100:.2f}%, median {np.median(ivs)*100:.2f}%.")
    print("Legs are percentage points of the traded entry premium and sum to the total")
    print("exactly.  'residual' is the only non-model leg: genuine implied-vol change plus")
    print("Black-Scholes mis-specification.  It is reported, not assumed away.\n")
    hdr = (f"{'horizon':>12} {'held min':>9} {'total':>9} {'spot leg':>10} {'decay leg':>10} "
           f"{'cross':>8} {'residual':>9} {'decay/min':>10} {'p spot':>8} {'p resid':>8}")
    print(hdr); print("-" * len(hdr))
    for _, r in dd.iterrows():
        print(f"{r['horizon']:>12} {r['mean_held_min']:>9.1f} {r['total']:>+8.2f}% "
              f"{r['spot_leg']:>+9.2f}% {r['decay_leg']:>+9.2f}% {r['cross_leg']:>+7.2f}% "
              f"{r['resid_leg']:>+8.2f}% {r['decay_per_min']:>+10.4f} {r['spot_p']:>8.4f} "
              f"{r['resid_p']:>8.4f}")

    # -------------------------------------------------------- D. multiplicity/placebo
    print("\n" + "=" * 116)
    print("D.  MULTIPLE COMPARISONS AND SHUFFLED-LABEL PLACEBO")
    print("=" * 116)
    p0 = grid["p0"].to_numpy()
    pb = grid["p_vs_base"].to_numpy()
    pbv = pb[np.isfinite(pb)]
    k = len(grid)
    print(f"  Total exit variants tested in section A                  : {k}")
    print(f"  Raw p<0.05 vs zero                                       : {(p0<0.05).sum()} of {k}")
    losing = int(((p0 < 0.05) & (grid['mean'].to_numpy() < 0)).sum())
    print(f"     of which the mean is NEGATIVE (a reliable loss)       : {losing}")
    print(f"  Surviving Bonferroni vs zero (alpha/{k} = {0.05/k:.2e})      : {(p0<0.05/k).sum()}")
    print(f"  Surviving Benjamini-Hochberg vs zero                     : {bh_reject(p0).sum()}")
    print(f"  Raw p<0.05 vs the hold-to-close baseline                 : "
          f"{(pbv<0.05).sum()} of {len(pbv)}")
    if (pbv < 0.05).any():
        sig = grid[np.isfinite(pb) & (pb < 0.05)]
        for _, r in sig.iterrows():
            print(f"     {r['name']:>20} [{r['conv']}]  {r['d_vs_base']:+.2f}pp vs baseline, "
                  f"p={r['p_vs_base']:.4f}, own mean {r['mean']:+.2f}%")
    print(f"  Surviving Bonferroni vs baseline                         : "
          f"{(pbv < 0.05/len(pbv)).sum()}")
    print(f"  Surviving Benjamini-Hochberg vs baseline                 : "
          f"{bh_reject(pbv).sum()}")

    obs_best_p0 = float(np.nanmin(p0))
    obs_best_pb = float(np.nanmin(pbv))
    obs_best_mean = float(grid["mean"].max())
    pool = [p for p in paths if np.isfinite(rule_return(p, "real_prices"))]
    print(f"\n  Placebo pool (all non-expiry gap-down fill days priceable on real premiums)"
          f": {len(pool)}")
    pl = placebo(pool, variants, len(fires), obs_best_p0, obs_best_pb, obs_best_mean)
    print(f"  Pool paths usable under the whole grid                   : {pl['pool_n']}")
    print(f"  {N_PLACEBO:,} draws, each reassigning the pooled Gate-B label at random and")
    print(f"  re-running the ENTIRE {k}-variant grid; the best-of-grid statistic is recorded.\n")
    print(f"    {'statistic':>26} {'observed':>12} {'placebo median':>16} "
          f"{'placebo tail':>14} {'empirical p':>13}")
    print("    " + "-" * 86)
    print(f"    {'best-of-grid p vs zero':>26} {pl['obs_best_p0']:>12.6f} "
          f"{pl['placebo_best_p0_median']:>16.6f} {pl['placebo_best_p0_5pct']:>14.6f} "
          f"{pl['empirical_p_best_p0']:>13.4f}")
    print(f"    {'best-of-grid p vs baseline':>26} {pl['obs_best_pb']:>12.6f} "
          f"{pl['placebo_best_pb_median']:>16.6f} {pl['placebo_best_pb_5pct']:>14.6f} "
          f"{pl['empirical_p_best_pb']:>13.4f}")
    print(f"    {'best-of-grid MEAN return':>26} {pl['obs_best_mean']:>11.2f}% "
          f"{pl['placebo_best_mean_median']:>15.2f}% {pl['placebo_best_mean_95pct']:>13.2f}% "
          f"{pl['empirical_p_best_mean']:>13.4f}")
    print(f"\n  At least one variant reaches nominal p<0.05 vs zero in "
          f"{pl['share_any_sig_vs_zero']:.1f}% of placebo draws.")
    print(f"  At least one beats its own baseline at p<0.05 in "
          f"{pl['share_any_sig_vs_base']:.1f}% of placebo draws.")

    # ------------------------------------------------------------------------ E. power
    print("\n" + "=" * 116)
    print("E.  POWER")
    print("=" * 116)
    base = np.asarray([rule_return(p, "real_prices") for p in fires])
    base = base[np.isfinite(base)]
    n = len(base)
    sd = base.std(ddof=1)
    d = required_d(n)
    ci = stats.t.interval(0.95, n - 1, loc=base.mean(), scale=sd / np.sqrt(n))
    print(f"  Baseline hold-to-close: N={n}, mean {base.mean():+.2f}%, sd {sd:.1f}pp, "
          f"95% CI [{ci[0]:+.2f}%, {ci[1]:+.2f}%]")
    print(f"  Two-sided t at 5% with 80% power needs {d:.3f} sd => "
          f"{d*sd:.1f} percentage points.  Nothing smaller is detectable at N={n}.")
    paired = []
    base_r, base_e = variant_values(fires, variants[0])
    for v in variants[1:]:
        r, e = variant_values(fires, v)
        use = e & base_e
        x = (r - base_r)[use]
        if len(x) > 3 and x.std(ddof=1) > 0:
            paired.append(x.std(ddof=1))
    msd = float(np.median(paired))
    print(f"  Median paired sd of an early exit against the baseline: {msd:.1f}pp")
    print(f"  => an early-exit overlay must add {d*msd:.1f}pp or more to be visible here.")
    for nn in (120, 60, 30):
        print(f"    N={nn:>3}: smallest detectable mean at 80% power = "
              f"{required_d(nn)*sd:.1f}pp")

    out = {
        "population": {"n_fires": len(fires), "n_priceable_all_minutes": nan_free,
                       "date_min": fires[0]["date"], "date_max": fires[-1]["date"]},
        "n_variants": int(k),
        "grid": grid.to_dict(orient="records"),
        "spot_buckets": bs.to_dict(orient="records"),
        "window_efficiency_test": we,
        "spot_cumulative": cd.to_dict(orient="records"),
        "spot_elapsed": ed.to_dict(orient="records"),
        "premium_path": pp.to_dict(orient="records"),
        "peak_timing": pk,
        "giveback": gb.to_dict(orient="records"),
        "bleed_rate": br.to_dict(orient="records"),
        "decay_split": dd.to_dict(orient="records"),
        "entry_iv_trading_time": {"n": int(n_iv), "mean": float(ivs.mean()),
                                  "median": float(np.median(ivs))},
        "multiplicity": {
            "raw_sig_vs_zero": int((p0 < 0.05).sum()),
            "raw_sig_vs_zero_losing": losing,
            "bonferroni_vs_zero": int((p0 < 0.05 / k).sum()),
            "bh_vs_zero": int(bh_reject(p0).sum()),
            "raw_sig_vs_baseline": int((pbv < 0.05).sum()),
            "bonferroni_vs_baseline": int((pbv < 0.05 / len(pbv)).sum()),
            "bh_vs_baseline": int(bh_reject(pbv).sum()),
        },
        "placebo": pl,
        "power": {"n": int(n), "mean": float(base.mean()), "sd": float(sd),
                  "ci95": [float(ci[0]), float(ci[1])],
                  "detectable_pp": float(d * sd),
                  "overlay_detectable_pp": float(d * msd)},
    }
    with open("gate_b_early_exit_scan_results.json", "w") as handle:
        json.dump(out, handle, indent=2, default=float)
    print("\nWrote gate_b_early_exit_scan_results.json, gate_b_early_exit_grid.csv and the")
    print("four supporting CSVs.")


if __name__ == "__main__":
    main()
