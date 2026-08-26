#!/usr/bin/env python3
"""Gate B "can any exit rule exist?" ceiling test.

New module.  It does not modify, and is not imported by, any pre-existing script.  It
reuses ``gate_b_common.py`` for path construction, the strike-tracking convention, the
control-day population and the reproduction guard.

This is NOT a fifth exit-rule grid search.  Four have been run and all are null
(``GATE_B_REAL_PREMIUM_VALIDATION.md`` 39 rules, ``gate_b_pooled_grid.py`` 32,
``gate_b_early_exit_scan.py`` 45, ``gate_b_structure_search.py`` 147).  This asks the
prior question: is there any extractable money in the post-fill path at all, and is the
observed perfect-hindsight ceiling special to Gate B or is it simply what the running
maximum of any option premium path looks like.

Four tests, exactly as briefed:

T1  Oracle ceiling on fires versus the control population, with a permutation p-value,
    raw and stratified on entry time (the ceiling mechanically grows with how long the
    position is held, and fires and controls do not fill at the same clock).
T2  Kolmogorov-Smirnov test of the normalised time of the post-entry maximum against the
    arcsine law  F(x) = (2/pi) arcsin(sqrt(x)),  the argmax law of a driftless path.  Run
    on SPOT (the clean test -- spot carries no theta drift) and on the premium.
T3  The ceiling on the win rate of ANY exit rule.  Two constructions: a model-free exact
    one (the share of days whose traded premium ever trades above its own entry premium)
    and the briefed breakeven-move decomposition on spot.
T4  Aryan's premise re-verified on the raw spot tape: fill-to-close SIGNED and ABSOLUTE
    move, fires versus controls, against the hindsight-MFE convention the spec quotes.

Conventions that bind this run
------------------------------
* Real strike-tracked traded premiums only for every headline number.  The Black-Scholes
  series is used in exactly one place -- the T3(b) breakeven-move decomposition, which is
  a scenario object by construction -- and is labelled as such there.
* Any implied-volatility inversion uses a TRADING-TIME maturity (375 minutes per session,
  252 sessions per year), per ``CORRECTION_GATE_B_VOL_CRUSH.md``.  The calendar-time
  convention in ``gate_b_common.py`` line 186 is NOT used anywhere in this module.
* The mid-IV cell (N=33) and the pooled cell (N=120) are reported separately throughout.
* Loss-per-minute-held is reported alongside total return wherever horizons differ.

Offline analysis only.  No broker, credential, exchange network, or order path is used.
No live order exists or is authorised.  No gate is armed.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq

from bs_gap_fill_pnl import RISK_FREE_RATE, bs_call
from gate_b_common import CACHE as CACHE_GLOB
from gate_b_common import clock_to_minutes, load_paths, reproduction_guard

SESSION_OPEN_MIN = 9 * 60 + 15       # 09:15
SESSION_CLOSE_MIN = 15 * 60 + 30     # 15:30, the contract expiry stamp
TRADING_MINUTES_PER_DAY = SESSION_CLOSE_MIN - SESSION_OPEN_MIN     # 375
TRADING_DAYS_PER_YEAR = 252

N_PERM = 20000
SEED = 20260823

# Minimum minutes from entry to 15:29 for a day to enter the arcsine test.  A trade that
# fills at 14:04 has 85 minutes of path; the normalised argmax is still defined but the
# discretisation is coarse, so the main T2 test is run on the >=120-minute subset and the
# full sample is reported as a declared sensitivity.
T2_MIN_MINUTES = 120


# ============================================================ trading-time maturity
def session_dates() -> np.ndarray:
    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    return np.asarray(sorted(dm["date"].dt.normalize().unique()), dtype="datetime64[ns]")


def trading_minutes_to_expiry(date_str: str, clock_min: int, expiry_str: str,
                              sessions: np.ndarray) -> float:
    """Trading minutes from ``clock_min`` on ``date_str`` to 15:30 on the expiry date."""
    d = np.datetime64(pd.Timestamp(date_str).normalize())
    e = np.datetime64(pd.Timestamp(expiry_str).normalize())
    today = max(0.0, float(SESSION_CLOSE_MIN - clock_min))
    if e <= d:
        return today
    between = sessions[(sessions > d) & (sessions <= e)]
    return today + TRADING_MINUTES_PER_DAY * float(len(between))


def trading_T(date_str: str, clock_min: int, expiry_str: str, sessions: np.ndarray) -> float:
    m = trading_minutes_to_expiry(date_str, clock_min, expiry_str, sessions)
    return max(m / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR), 1e-9)


def implied_vol_call(price: float, S: float, K: float, T: float, r: float) -> float:
    """Invert a CALL price for implied volatility.  NaN if it cannot be bracketed."""
    intrinsic = max(S - K * math.exp(-r * T), 0.0)
    if not np.isfinite(price) or price <= intrinsic + 1e-9 or T <= 0:
        return float("nan")
    try:
        return float(brentq(lambda s: bs_call(S, K, T, r, s) - price, 1e-4, 5.0,
                            xtol=1e-8, maxiter=200))
    except ValueError:
        return float("nan")


# ============================================================ populations
def populations(paths: list[dict]) -> dict[str, list[dict]]:
    """Fire and control cells.  Every cell uses the SAME entry-minute convention: each
    day's own gap-fill minute, the first minute strictly after 09:17 at which spot has
    returned to or through the prior session's 15:29 close.  This is enforced by
    construction -- ``gate_b_common.build_paths`` runs one code path for all 264 days.
    """
    return {
        "fires_mid": [p for p in paths if p["is_gate_b"] == 1],
        "fires_pooled": [p for p in paths if p["vix_rose"] == 1],
        "ctrl_nonfire": [p for p in paths if p["is_gate_b"] == 0],
        "ctrl_ivmiss": [p for p in paths if p["vix_rose"] == 1 and p["is_gate_b"] == 0],
        "ctrl_novix": [p for p in paths if p["vix_rose"] == 0],
        "all": list(paths),
    }


# ============================================================ per-day panel
def build_panel(paths: list[dict], sessions: np.ndarray) -> pd.DataFrame:
    """One row per day.  Every premium quantity is a REAL traded one-minute bar close for
    the tracked entry strike; every spot quantity is the NIFTY minute tape."""
    rows = []
    for p in paths:
        px = np.asarray(p["real_prices"], dtype=float)
        sp = np.asarray(p["spots"], dtype=float)
        el = np.asarray(p["elapsed"], dtype=int)
        C0 = float(px[0])
        S0 = float(sp[0])
        K = float(p["K"])
        n_min = int(el[-1])                        # minutes from entry to 15:29

        ret = (px - C0) / C0 * 100.0               # premium return path, %
        i_pk = int(np.nanargmax(ret))
        peak_ret = float(ret[i_pk])
        peak_elapsed = int(el[i_pk])
        peak_clock_min = int(p["entry_minute"] + peak_elapsed)
        # Exit at 15:29 valued on the last PRICED minute, with the two-minute grace the
        # rest of this project uses (``gate_b_common.rule_return``).  Exactly one of the
        # 264 days (2026-02-01, a control) is not quoted at 15:29 itself.
        priced = np.flatnonzero(np.isfinite(px))
        i_close = int(priced[-1])
        close_ret = float(ret[i_close])
        close_minutes_short = int(el[-1] - el[i_close])

        i_smax = int(np.argmax(sp))
        i_smin = int(np.argmin(sp))
        mfe_pts = float(sp[i_smax] - S0)
        mae_pts = float(sp[i_smin] - S0)
        mfe_elapsed = int(el[i_smax])

        close_move = float(sp[i_close] - S0)

        # realised volatility from entry to close, annualised in trading time
        lr = np.diff(np.log(sp))
        lr = lr[np.isfinite(lr)]
        rv = (float(np.std(lr, ddof=1)) * math.sqrt(TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR)
              if len(lr) > 1 else float("nan"))

        # entry implied volatility, TRADING-TIME maturity, inverted from the TRADED price
        T0 = trading_T(p["date"], int(p["entry_minute"]), p["expiry"], sessions)
        iv0 = implied_vol_call(C0, S0, K, T0, RISK_FREE_RATE)

        rows.append({
            "date": p["date"],
            "is_gate_b": int(p["is_gate_b"]),
            "vix_rose": int(p["vix_rose"]),
            "iv_bucket": p["iv_bucket"],
            "reversed": bool(p["reversed"]),
            "entry_clock": p["entry_clock"],
            "entry_minute": int(p["entry_minute"]),
            "minutes_to_close": n_min,
            "K": K,
            "S0": S0,
            "expiry": p["expiry"],
            "entry_premium": C0,
            "close_premium": float(px[i_close]),
            "close_minutes_short": close_minutes_short,
            "entry_iv_tradingtime": iv0,
            "T0_trading_years": T0,
            "close_ret_pct": close_ret,
            "oracle_peak_ret_pct": peak_ret,
            "oracle_peak_elapsed_min": peak_elapsed,
            "oracle_peak_clock_min": peak_clock_min,
            "oracle_peak_u": (peak_elapsed / n_min) if n_min > 0 else float("nan"),
            "giveback_pp": peak_ret - close_ret,
            "spot_argmax_elapsed_min": mfe_elapsed,
            "spot_argmax_u": (mfe_elapsed / n_min) if n_min > 0 else float("nan"),
            "mfe_pts": mfe_pts,
            "mae_pts": mae_pts,
            "close_move_pts": close_move,
            "abs_close_move_pts": abs(close_move),
            "realised_vol_entry_close": rv,
            "minute_cov": float(np.isfinite(px).mean()),
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


# ============================================================ inference helpers
def describe(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"N": 0}
    return {
        "N": int(len(x)),
        "mean": float(x.mean()),
        "sd": float(x.std(ddof=1)) if len(x) > 1 else float("nan"),
        "p10": float(np.percentile(x, 10)),
        "q1": float(np.percentile(x, 25)),
        "median": float(np.median(x)),
        "q3": float(np.percentile(x, 75)),
        "p90": float(np.percentile(x, 90)),
        "min": float(x.min()),
        "max": float(x.max()),
        "share_positive": float((x > 0).mean() * 100.0),
    }


def perm_mean_diff(a: np.ndarray, b: np.ndarray, n: int = N_PERM, seed: int = SEED) -> dict:
    """Two-sided permutation test on the difference in means, labels shuffled in the pool."""
    a = np.asarray(a, float); a = a[np.isfinite(a)]
    b = np.asarray(b, float); b = b[np.isfinite(b)]
    obs = float(a.mean() - b.mean())
    pool = np.concatenate([a, b])
    na = len(a)
    rng = np.random.default_rng(seed)
    draws = np.empty(n)
    for i in range(n):
        rng.shuffle(pool)
        draws[i] = pool[:na].mean() - pool[na:].mean()
    p = float((np.abs(draws) >= abs(obs) - 1e-12).mean())
    return {"obs_diff": obs, "p_perm": p, "perm_mean": float(draws.mean()),
            "perm_p5": float(np.percentile(draws, 5)),
            "perm_p95": float(np.percentile(draws, 95)),
            "n_draws": n, "n_a": na, "n_b": int(len(b))}


ENTRY_STRATA = ((0, 9 * 60 + 30), (9 * 60 + 30, 10 * 60), (10 * 60, 11 * 60), (11 * 60, 24 * 60))


def stratum_of(entry_minute: int) -> int:
    for i, (lo, hi) in enumerate(ENTRY_STRATA):
        if lo <= entry_minute < hi:
            return i
    return len(ENTRY_STRATA) - 1


def perm_mean_diff_stratified(va: np.ndarray, sa: np.ndarray, vb: np.ndarray, sb: np.ndarray,
                              n: int = N_PERM, seed: int = SEED) -> dict:
    """Permutation on the difference in means with labels shuffled WITHIN entry-time strata.

    The oracle ceiling grows mechanically with how long the position is held, and fires
    and controls do not fill at the same clock, so the raw test conflates a holding-period
    difference with a Gate-B effect.  This one does not.
    """
    va = np.asarray(va, float); vb = np.asarray(vb, float)
    ok_a = np.isfinite(va); ok_b = np.isfinite(vb)
    va, sa = va[ok_a], np.asarray(sa)[ok_a]
    vb, sb = vb[ok_b], np.asarray(sb)[ok_b]
    obs = float(va.mean() - vb.mean())
    vals = np.concatenate([va, vb])
    strat = np.concatenate([sa, sb])
    lab = np.concatenate([np.ones(len(va), bool), np.zeros(len(vb), bool)])
    rng = np.random.default_rng(seed)
    idx_by_s = {s: np.flatnonzero(strat == s) for s in np.unique(strat)}
    draws = np.empty(n)
    lab_perm = lab.copy()
    for i in range(n):
        for s, idx in idx_by_s.items():
            sub = lab[idx].copy()
            rng.shuffle(sub)
            lab_perm[idx] = sub
        draws[i] = vals[lab_perm].mean() - vals[~lab_perm].mean()
    p = float((np.abs(draws) >= abs(obs) - 1e-12).mean())
    return {"obs_diff": obs, "p_perm_stratified": p, "n_draws": n,
            "n_a": int(len(va)), "n_b": int(len(vb)),
            "strata_counts_a": {int(s): int((sa == s).sum()) for s in np.unique(strat)},
            "strata_counts_b": {int(s): int((sb == s).sum()) for s in np.unique(strat)}}



def mde(sd: float, n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """Two-sided one-sample minimum detectable mean at the stated alpha and power."""
    z_a = stats.norm.ppf(1 - alpha / 2.0)
    z_b = stats.norm.ppf(power)
    return float((z_a + z_b) * sd / math.sqrt(n))


def mde_two_sample(sd_a: float, n_a: int, sd_b: float, n_b: int,
                   alpha: float = 0.05, power: float = 0.80) -> float:
    z_a = stats.norm.ppf(1 - alpha / 2.0)
    z_b = stats.norm.ppf(power)
    se = math.sqrt(sd_a ** 2 / n_a + sd_b ** 2 / n_b)
    return float((z_a + z_b) * se)


def prop_ci(k: int, n: int) -> tuple[float, float]:
    lo, hi = stats.beta.ppf(0.025, k, n - k + 1), stats.beta.ppf(0.975, k + 1, n - k)
    return (float(0.0 if k == 0 else lo) * 100.0, float(1.0 if k == n else hi) * 100.0)


def perm_prop_diff(a: np.ndarray, b: np.ndarray, n: int = N_PERM, seed: int = SEED) -> dict:
    """Permutation test on the difference in the share of days exceeding zero."""
    a = np.asarray(a, float); a = a[np.isfinite(a)]
    b = np.asarray(b, float); b = b[np.isfinite(b)]
    ba, bb = (a > 0).astype(float), (b > 0).astype(float)
    obs = float(ba.mean() - bb.mean()) * 100.0
    pool = np.concatenate([ba, bb]); na = len(ba)
    rng = np.random.default_rng(seed)
    draws = np.empty(n)
    for i in range(n):
        rng.shuffle(pool)
        draws[i] = (pool[:na].mean() - pool[na:].mean()) * 100.0
    return {"obs_diff_pp": obs, "p_perm": float((np.abs(draws) >= abs(obs) - 1e-12).mean())}


def raw_tape_hand_check(paths: list[dict], date_str: str, sessions: np.ndarray) -> dict:
    """Recompute one day's entry, close, peak and MFE straight from the source CSVs.

    Deliberately bypasses ``gate_b_common``'s pickled quote cache and re-reads the raw
    archive files for the tracked strike, so a cache or merge defect would show up here.
    """
    import glob
    p = next(q for q in paths if q["date"] == date_str)
    K = float(p["K"])
    frames = []
    for f in sorted(glob.glob(f"{CACHE_GLOB}/{date_str[:4]}/*.csv")):
        try:
            df = pd.read_csv(f, usecols=["close", "strike", "datetime", "option_type", "spot"])
        except (ValueError, OSError):
            continue
        # the archive labels calls "CE"
        df = df[(df["option_type"].astype(str).str.upper().isin(("CE", "CALL")))
                & (np.isclose(df["strike"].astype(float), K))]
        if df.empty:
            continue
        df = df[df["datetime"].astype(str).str.startswith(date_str)]
        if not df.empty:
            frames.append(df)
    if not frames:
        return {"date": date_str, "found": False}
    raw = pd.concat(frames, ignore_index=True)
    raw["clock"] = pd.to_datetime(raw["datetime"]).dt.strftime("%H:%M")
    raw = raw[raw["close"] > 0].drop_duplicates(subset=["clock"]).sort_values("clock")
    entry_clock = p["entry_clock"]
    win = raw[(raw["clock"] >= entry_clock) & (raw["clock"] <= "15:29")]
    c0 = float(win[win["clock"] == entry_clock]["close"].iloc[0])
    c_last = float(win["close"].iloc[-1])
    c_max = float(win["close"].max())
    clk_max = str(win.loc[win["close"].idxmax(), "clock"])
    px = np.asarray(p["real_prices"], float)
    priced = np.flatnonzero(np.isfinite(px))
    return {
        "date": date_str, "found": True, "strike": K, "entry_clock": entry_clock,
        "raw_files_matched": True,
        "raw_entry_premium": c0, "panel_entry_premium": float(px[0]),
        "raw_close_premium": c_last, "panel_close_premium": float(px[priced[-1]]),
        "raw_max_premium": c_max, "raw_max_clock": clk_max,
        "panel_max_premium": float(np.nanmax(px)),
        "raw_close_ret_pct": (c_last - c0) / c0 * 100.0,
        "raw_oracle_peak_ret_pct": (c_max - c0) / c0 * 100.0,
        "raw_minutes_in_window": int(len(win)),
        "entry_matches": bool(np.isclose(c0, px[0])),
        "close_matches": bool(np.isclose(c_last, px[priced[-1]])),
        "peak_matches": bool(np.isclose(c_max, np.nanmax(px))),
    }


# ============================================================ T2 arcsine
def arcsine_cdf(x: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    return (2.0 / math.pi) * np.arcsin(np.sqrt(x))


def ks_arcsine(u: np.ndarray) -> dict:
    u = np.asarray(u, float)
    u = u[np.isfinite(u)]
    if len(u) < 5:
        return {"N": int(len(u))}
    res = stats.kstest(u, arcsine_cdf)
    # where and in which direction the empirical CDF departs
    us = np.sort(u)
    emp = np.arange(1, len(us) + 1) / len(us)
    emp_lo = np.arange(0, len(us)) / len(us)
    theo = arcsine_cdf(us)
    dplus = float(np.max(emp - theo))
    dminus = float(np.max(theo - emp_lo))
    i = int(np.argmax(np.maximum(emp - theo, theo - emp_lo)))
    return {
        "N": int(len(u)),
        "ks_D": float(res.statistic),
        "ks_p": float(res.pvalue),
        "D_plus": dplus,
        "D_minus": dminus,
        "u_at_max_gap": float(us[i]),
        "empirical_cdf_at_max_gap": float(emp[i]),
        "arcsine_cdf_at_max_gap": float(theo[i]),
        "mean_u": float(u.mean()),
        "median_u": float(np.median(u)),
        "share_u_lt_0.25": float((u < 0.25).mean() * 100.0),
        "share_u_in_0.25_0.75": float(((u >= 0.25) & (u <= 0.75)).mean() * 100.0),
        "share_u_gt_0.75": float((u > 0.75).mean() * 100.0),
        "arcsine_share_lt_0.25": float(arcsine_cdf(np.array([0.25]))[0] * 100.0),
        "arcsine_share_mid": float((arcsine_cdf(np.array([0.75]))[0]
                                    - arcsine_cdf(np.array([0.25]))[0]) * 100.0),
        "arcsine_share_gt_0.75": float((1.0 - arcsine_cdf(np.array([0.75]))[0]) * 100.0),
    }


# ============================================================ T3 breakeven move
def breakeven_analysis(paths: list[dict], panel: pd.DataFrame,
                       sessions: np.ndarray) -> pd.DataFrame:
    """Spot move required for the option to return to its entry premium, minute by minute.

    SCENARIO OBJECT, declared: implied volatility is held at the trading-time entry value
    inverted from the TRADED entry premium, and the Black-Scholes map converts a spot level
    into a premium.  Used ONLY here, to express the ceiling in index points; it does not
    enter any headline number.  The model-free exact ceiling is computed separately in
    ``t3_model_free``.
    """
    by_date = {p["date"]: p for p in paths}
    rows = []
    for _, r in panel.iterrows():
        p = by_date[r["date"]]
        sp = np.asarray(p["spots"], float)
        el = np.asarray(p["elapsed"], int)
        S0, K, C0 = float(r["S0"]), float(r["K"]), float(r["entry_premium"])
        sig = float(r["entry_iv_tradingtime"])
        if not np.isfinite(sig):
            rows.append({"date": r["date"], "breakeven_ok": np.nan})
            continue
        entry_min = int(r["entry_minute"])

        be_move = np.full(len(el), np.nan)
        be_sigma = np.full(len(el), np.nan)
        for i in range(len(el)):
            tmin = entry_min + int(el[i])
            T = trading_T(r["date"], tmin, r["expiry"], sessions)
            if T <= 1e-9:
                be_move[i] = max(K + C0 - S0, 0.0)          # at expiry: intrinsic must equal C0
                continue
            f = lambda s: bs_call(s, K, T, RISK_FREE_RATE, sig) - C0
            lo, hi = S0 * 0.85, S0 * 1.25
            try:
                s_star = float(brentq(f, lo, hi, xtol=1e-6, maxiter=200))
            except ValueError:
                continue
            be_move[i] = s_star - S0
            denom = S0 * sig * math.sqrt(T)
            be_sigma[i] = (s_star - S0) / denom if denom > 0 else np.nan

        excess = (sp - S0) - be_move                        # >=0 => a break-even exit existed
        ok = bool(np.nanmax(excess) >= 0.0) if np.isfinite(excess).any() else False
        i_smax = int(np.argmax(sp))
        rows.append({
            "date": r["date"],
            "entry_iv_tradingtime": sig,
            "breakeven_ok": ok,
            "breakeven_at_mfe_minute_pts": float(be_move[i_smax]),
            "breakeven_at_mfe_sigma": float(be_sigma[i_smax]),
            "mfe_exceeds_breakeven_at_its_minute": bool(
                (sp[i_smax] - S0) >= be_move[i_smax]) if np.isfinite(be_move[i_smax]) else False,
            "breakeven_at_close_pts": float(be_move[-1]),
            "breakeven_at_close_sigma": float(be_sigma[-1]),
            "breakeven_at_60min_pts": float(be_move[np.searchsorted(el, 60)])
            if el[-1] >= 60 else np.nan,
            "min_breakeven_pts_after_entry": float(np.nanmin(be_move[1:]))
            if len(be_move) > 1 and np.isfinite(be_move[1:]).any() else np.nan,
            "max_excess_pts": float(np.nanmax(excess)) if np.isfinite(excess).any() else np.nan,
        })
    return pd.DataFrame(rows)


def t3_model_free(panel: pd.DataFrame) -> dict:
    """EXACT, model-free ceiling on the win rate of any exit rule.

    No rule can exit above the running maximum of the traded premium, so the share of days
    whose premium EVER trades strictly above its own entry premium is an upper bound on the
    win rate of every exit rule that exists, has ever been tested, or could be written.
    """
    pk = panel["oracle_peak_ret_pct"].to_numpy(float)
    out = {
        "N": int(np.isfinite(pk).sum()),
        "ceiling_win_rate_gross_pct": float((pk > 0).mean() * 100.0),
        "ceiling_win_rate_after_2pct_costs": float((pk > 2.0).mean() * 100.0),
        "ceiling_win_rate_after_5pct_costs": float((pk > 5.0).mean() * 100.0),
        "ceiling_win_rate_gt_10pct": float((pk > 10.0).mean() * 100.0),
        "ceiling_win_rate_gt_25pct": float((pk > 25.0).mean() * 100.0),
        "actual_hold_to_close_win_rate_pct": float(
            (panel["close_ret_pct"].to_numpy(float) > 0).mean() * 100.0),
    }
    return out


# ============================================================ main
def main() -> None:
    rng_note = f"permutation draws {N_PERM}, seed {SEED}"
    sessions = session_dates()
    paths = load_paths()
    pops = populations(paths)
    reproduction_guard(pops["fires_mid"])

    panel_all = build_panel(paths, sessions)
    panel_all.to_csv("gate_b_exit_ceiling_panel.csv", index=False)

    def sub(name: str) -> pd.DataFrame:
        dates = {p["date"] for p in pops[name]}
        return panel_all[panel_all["date"].isin(dates)].reset_index(drop=True)

    P = {k: sub(k) for k in ("fires_mid", "fires_pooled", "ctrl_nonfire",
                             "ctrl_ivmiss", "ctrl_novix")}

    results: dict = {
        "meta": {
            "run_date": "2026-08-23",
            "panel_rows": int(len(panel_all)),
            "populations": {k: int(len(v)) for k, v in P.items()},
            "premium_series": "real strike-tracked traded one-minute bar closes",
            "iv_convention": "trading time, 375 min/session, 252 sessions/year",
            "entry_convention": "each day's own gap-fill minute, first minute strictly after "
                                "09:17 at which spot >= prior session 15:29 close; identical "
                                "code path for fires and controls",
            "minute_coverage_min_pct": float(panel_all["minute_cov"].min() * 100.0),
            "inference": rng_note,
        }
    }

    # ------------------------------------------------------------------ T1
    print("=" * 88)
    print("T1  ORACLE CEILING: FIRES vs CONTROLS")
    print("=" * 88)
    t1: dict = {}
    for k, d in P.items():
        t1[k] = {
            "oracle_peak_ret_pct": describe(d["oracle_peak_ret_pct"].to_numpy()),
            "close_ret_pct": describe(d["close_ret_pct"].to_numpy()),
            "giveback_pp": describe(d["giveback_pp"].to_numpy()),
            "minutes_to_close": describe(d["minutes_to_close"].to_numpy()),
            "oracle_peak_per_minute_held_pct": float(
                np.nanmean(d["oracle_peak_ret_pct"].to_numpy()
                           / np.maximum(d["oracle_peak_elapsed_min"].to_numpy(), 1))),
            "close_ret_per_minute_held_pct": float(
                np.nanmean(d["close_ret_pct"].to_numpy() / d["minutes_to_close"].to_numpy())),
            "mean_minutes_held_to_peak": float(np.nanmean(d["oracle_peak_elapsed_min"].to_numpy())),
        }
        s = t1[k]["oracle_peak_ret_pct"]
        print(f"  {k:14s} N={s['N']:4d}  oracle peak mean {s['mean']:+7.2f}%  "
              f"median {s['median']:+7.2f}%  q1 {s['q1']:+7.2f}%  q3 {s['q3']:+7.2f}%  "
              f"close mean {t1[k]['close_ret_pct']['mean']:+7.2f}%  "
              f"giveback {t1[k]['giveback_pp']['mean']:6.2f}pp")

    comparisons = {
        "mid_vs_nonfire": ("fires_mid", "ctrl_nonfire"),
        "mid_vs_ivmiss": ("fires_mid", "ctrl_ivmiss"),
        "pooled_vs_novix": ("fires_pooled", "ctrl_novix"),
        "pooled_vs_nonfire_excl": ("fires_pooled", "ctrl_novix"),
    }
    t1["comparisons"] = {}
    for label, (a, b) in comparisons.items():
        if label == "pooled_vs_nonfire_excl":
            continue
        A, B = P[a], P[b]
        raw = perm_mean_diff(A["oracle_peak_ret_pct"].to_numpy(),
                             B["oracle_peak_ret_pct"].to_numpy())
        strat = perm_mean_diff_stratified(
            A["oracle_peak_ret_pct"].to_numpy(),
            [stratum_of(m) for m in A["entry_minute"]],
            B["oracle_peak_ret_pct"].to_numpy(),
            [stratum_of(m) for m in B["entry_minute"]])
        mw = stats.mannwhitneyu(A["oracle_peak_ret_pct"], B["oracle_peak_ret_pct"],
                                alternative="two-sided")
        t1["comparisons"][label] = {"raw": raw, "stratified": strat,
                                    "mannwhitney_p": float(mw.pvalue)}
        print(f"  {label:22s} diff {raw['obs_diff']:+7.2f}pp  perm p={raw['p_perm']:.4f}  "
              f"stratified perm p={strat['p_perm_stratified']:.4f}  "
              f"Mann-Whitney p={mw.pvalue:.4f}")

    # horizon-normalised ceiling: peak return per sqrt(minute), removes the mechanical
    # dependence of a running maximum on how long the path runs
    for k, d in P.items():
        z = d["oracle_peak_ret_pct"].to_numpy() / np.sqrt(d["minutes_to_close"].to_numpy())
        t1[k]["oracle_peak_per_sqrt_minute"] = describe(z)
    for label, (a, b) in (("mid_vs_nonfire", ("fires_mid", "ctrl_nonfire")),
                          ("pooled_vs_novix", ("fires_pooled", "ctrl_novix"))):
        za = (P[a]["oracle_peak_ret_pct"].to_numpy()
              / np.sqrt(P[a]["minutes_to_close"].to_numpy()))
        zb = (P[b]["oracle_peak_ret_pct"].to_numpy()
              / np.sqrt(P[b]["minutes_to_close"].to_numpy()))
        t1["comparisons"][label]["per_sqrt_minute"] = perm_mean_diff(za, zb)
        print(f"  {label:22s} per-sqrt-minute diff "
              f"{t1['comparisons'][label]['per_sqrt_minute']['obs_diff']:+.4f}  "
              f"perm p={t1['comparisons'][label]['per_sqrt_minute']['p_perm']:.4f}")
    t1["power"] = {}
    for label, (a, b) in (("mid_vs_nonfire", ("fires_mid", "ctrl_nonfire")),
                          ("mid_vs_ivmiss", ("fires_mid", "ctrl_ivmiss")),
                          ("pooled_vs_novix", ("fires_pooled", "ctrl_novix"))):
        sa = t1[a]["oracle_peak_ret_pct"]["sd"]; na = t1[a]["oracle_peak_ret_pct"]["N"]
        sb = t1[b]["oracle_peak_ret_pct"]["sd"]; nb = t1[b]["oracle_peak_ret_pct"]["N"]
        t1["power"][label] = {
            "mde_80pct_pp": mde_two_sample(sa, na, sb, nb),
            "observed_diff_pp": t1["comparisons"][label]["raw"]["obs_diff"],
            "sd_a": sa, "n_a": na, "sd_b": sb, "n_b": nb,
        }
        print(f"  POWER {label:20s} smallest difference resolvable at 80% power: "
              f"{t1['power'][label]['mde_80pct_pp']:.2f}pp  "
              f"(observed {t1['power'][label]['observed_diff_pp']:+.2f}pp)")
    results["T1_oracle_ceiling"] = t1

    # ------------------------------------------------------------------ T2
    print()
    print("=" * 88)
    print("T2  IS THE ARGMAX ARCSINE-DISTRIBUTED?")
    print("=" * 88)
    t2: dict = {}
    for k, d in P.items():
        long_enough = d[d["minutes_to_close"] >= T2_MIN_MINUTES]
        t2[k] = {
            "spot_argmax_restricted": ks_arcsine(long_enough["spot_argmax_u"].to_numpy()),
            "spot_argmax_full": ks_arcsine(d["spot_argmax_u"].to_numpy()),
            "premium_peak_restricted": ks_arcsine(long_enough["oracle_peak_u"].to_numpy()),
            "premium_peak_full": ks_arcsine(d["oracle_peak_u"].to_numpy()),
            "n_restricted": int(len(long_enough)),
        }
        s = t2[k]["spot_argmax_restricted"]
        q = t2[k]["premium_peak_restricted"]
        print(f"  {k:14s} SPOT  N={s.get('N', 0):4d} D={s.get('ks_D', float('nan')):.4f} "
              f"p={s.get('ks_p', float('nan')):.4f}   |   "
              f"PREMIUM N={q.get('N', 0):4d} D={q.get('ks_D', float('nan')):.4f} "
              f"p={q.get('ks_p', float('nan')):.4f}")
    results["T2_arcsine"] = t2

    # ------------------------------------------------------------------ T3
    print()
    print("=" * 88)
    print("T3  CEILING ON THE WIN RATE OF ANY EXIT RULE")
    print("=" * 88)
    t3: dict = {"model_free": {}, "breakeven": {}}
    for k, d in P.items():
        t3["model_free"][k] = t3_model_free(d)
        m = t3["model_free"][k]
        print(f"  {k:14s} N={m['N']:4d}  CEILING win rate {m['ceiling_win_rate_gross_pct']:5.1f}%  "
              f"(net 2% costs {m['ceiling_win_rate_after_2pct_costs']:5.1f}%, "
              f"net 5% {m['ceiling_win_rate_after_5pct_costs']:5.1f}%)   "
              f"actual hold-to-close win {m['actual_hold_to_close_win_rate_pct']:5.1f}%")

    for k, d in P.items():
        pk = d["oracle_peak_ret_pct"].to_numpy(float)
        pk = pk[np.isfinite(pk)]
        kk = int((pk > 0).sum())
        lo, hi = prop_ci(kk, len(pk))
        t3["model_free"][k]["ceiling_win_rate_95ci"] = [lo, hi]
        t3["model_free"][k]["k_over_n"] = f"{kk}/{len(pk)}"
    t3["ceiling_comparisons"] = {}
    for label, (a, b) in (("mid_vs_nonfire", ("fires_mid", "ctrl_nonfire")),
                          ("mid_vs_ivmiss", ("fires_mid", "ctrl_ivmiss")),
                          ("pooled_vs_novix", ("fires_pooled", "ctrl_novix"))):
        t3["ceiling_comparisons"][label] = perm_prop_diff(
            P[a]["oracle_peak_ret_pct"].to_numpy(float),
            P[b]["oracle_peak_ret_pct"].to_numpy(float))
        c = t3["ceiling_comparisons"][label]
        print(f"  CEILING {label:20s} diff {c['obs_diff_pp']:+5.1f}pp  perm p={c['p_perm']:.4f}")

    be_frames = {}
    for k in ("fires_mid", "fires_pooled", "ctrl_novix"):
        be = breakeven_analysis(paths, P[k], sessions)
        be_frames[k] = be
        d = P[k].merge(be, on="date", how="left")
        t3["breakeven"][k] = {
            "N": int(len(d)),
            "share_breakeven_reachable_any_minute_pct": float(
                d["breakeven_ok"].astype(float).mean() * 100.0),
            "share_mfe_exceeds_breakeven_at_its_minute_pct": float(
                d["mfe_exceeds_breakeven_at_its_minute"].astype(float).mean() * 100.0),
            "median_breakeven_at_mfe_minute_pts": float(
                np.nanmedian(d["breakeven_at_mfe_minute_pts"])),
            "median_breakeven_at_mfe_sigma": float(np.nanmedian(d["breakeven_at_mfe_sigma"])),
            "median_breakeven_at_close_pts": float(np.nanmedian(d["breakeven_at_close_pts"])),
            "median_breakeven_at_close_sigma": float(np.nanmedian(d["breakeven_at_close_sigma"])),
            "median_breakeven_at_60min_pts": float(np.nanmedian(d["breakeven_at_60min_pts"])),
            "median_min_breakeven_after_entry_pts": float(
                np.nanmedian(d["min_breakeven_pts_after_entry"])),
            "median_mfe_pts": float(np.nanmedian(d["mfe_pts"])),
            "mean_mfe_pts": float(np.nanmean(d["mfe_pts"])),
            "median_close_move_pts": float(np.nanmedian(d["close_move_pts"])),
            "mean_close_move_pts": float(np.nanmean(d["close_move_pts"])),
            "median_entry_iv_tradingtime_pct": float(
                np.nanmedian(d["entry_iv_tradingtime_y"] if "entry_iv_tradingtime_y" in d
                             else d["entry_iv_tradingtime"]) * 100.0),
        }
        b = t3["breakeven"][k]
        print(f"  {k:14s} breakeven reachable {b['share_breakeven_reachable_any_minute_pct']:5.1f}%  "
              f"MFE>breakeven at its own minute {b['share_mfe_exceeds_breakeven_at_its_minute_pct']:5.1f}%  "
              f"| median breakeven at MFE minute {b['median_breakeven_at_mfe_minute_pts']:6.1f} pts "
              f"({b['median_breakeven_at_mfe_sigma']:.2f} sigma)  median MFE {b['median_mfe_pts']:6.1f} pts  "
              f"median close move {b['median_close_move_pts']:+6.1f} pts")
        be.to_csv(f"gate_b_exit_ceiling_breakeven_{k}.csv", index=False)
    results["T3_win_rate_ceiling"] = t3

    # ------------------------------------------------------------------ T4
    print()
    print("=" * 88)
    print("T4  THE PREMISE, ON SPOT: FILL-TO-CLOSE MOVE vs HINDSIGHT MFE")
    print("=" * 88)
    t4: dict = {}
    for k, d in P.items():
        signed = d["close_move_pts"].to_numpy(float)
        t4[k] = {
            "signed_close_move_pts": describe(signed),
            "abs_close_move_pts": describe(d["abs_close_move_pts"].to_numpy(float)),
            "mfe_pts": describe(d["mfe_pts"].to_numpy(float)),
            "mae_pts": describe(d["mae_pts"].to_numpy(float)),
            "realised_vol_entry_close": describe(d["realised_vol_entry_close"].to_numpy(float)),
            "sign_test_p_up": float(stats.binomtest(int((signed > 0).sum()), len(signed), 0.5).pvalue),
            "share_up_pct": float((signed > 0).mean() * 100.0),
            "t_p_vs_zero": float(stats.ttest_1samp(signed, 0.0).pvalue),
        }
        s = t4[k]
        print(f"  {k:14s} signed close move mean {s['signed_close_move_pts']['mean']:+7.1f} "
              f"median {s['signed_close_move_pts']['median']:+7.1f} pts  up {s['share_up_pct']:5.1f}% "
              f"(sign p={s['sign_test_p_up']:.3f}, t p={s['t_p_vs_zero']:.3f})  |  "
              f"MFE mean {s['mfe_pts']['mean']:6.1f} median {s['mfe_pts']['median']:6.1f}  |  "
              f"|move| median {s['abs_close_move_pts']['median']:6.1f}  |  "
              f"RV {s['realised_vol_entry_close']['mean']*100:5.2f}%")

    t4["comparisons"] = {}
    for label, (a, b) in (("mid_vs_nonfire", ("fires_mid", "ctrl_nonfire")),
                          ("mid_vs_ivmiss", ("fires_mid", "ctrl_ivmiss")),
                          ("pooled_vs_novix", ("fires_pooled", "ctrl_novix"))):
        entry = {}
        for col in ("close_move_pts", "abs_close_move_pts", "mfe_pts",
                    "realised_vol_entry_close"):
            entry[col] = perm_mean_diff(P[a][col].to_numpy(float), P[b][col].to_numpy(float))
        entry["close_move_stratified"] = perm_mean_diff_stratified(
            P[a]["close_move_pts"].to_numpy(float),
            [stratum_of(m) for m in P[a]["entry_minute"]],
            P[b]["close_move_pts"].to_numpy(float),
            [stratum_of(m) for m in P[b]["entry_minute"]])
        t4["comparisons"][label] = entry
        print(f"  {label:18s} signed close diff {entry['close_move_pts']['obs_diff']:+7.1f} pts "
              f"perm p={entry['close_move_pts']['p_perm']:.4f}  |  "
              f"MFE diff {entry['mfe_pts']['obs_diff']:+6.1f} pts perm p={entry['mfe_pts']['p_perm']:.4f}")

    # driftless benchmark for the MFE, using each day's own realised volatility
    for k, d in P.items():
        rv = d["realised_vol_entry_close"].to_numpy(float)
        n_min = d["minutes_to_close"].to_numpy(float)
        S0 = d["S0"].to_numpy(float)
        sd_pts = S0 * rv * np.sqrt(n_min / (TRADING_MINUTES_PER_DAY * TRADING_DAYS_PER_YEAR))
        e_max = sd_pts * math.sqrt(2.0 / math.pi)          # E[max of driftless BM on [0,T]]
        t4[k]["driftless_expected_max_pts"] = describe(e_max)
        t4[k]["observed_over_driftless_max_ratio"] = float(
            np.nanmean(d["mfe_pts"].to_numpy(float)) / np.nanmean(e_max))
        print(f"  {k:14s} driftless E[max] {np.nanmean(e_max):6.1f} pts vs observed MFE "
              f"{np.nanmean(d['mfe_pts']):6.1f} pts  ratio "
              f"{t4[k]['observed_over_driftless_max_ratio']:.3f}")
    results["T4_premise"] = t4

    # ------------------------------------------------------ IV convention verification
    print()
    print("=" * 88)
    print("VERIFICATION: THE IMPLIED-VOLATILITY INVERSION")
    print("=" * 88)
    fires = pops["fires_mid"]
    cal_iv, trad_iv, tape_iv = [], [], []
    for q in fires:
        S0, K, C0 = float(q["spots"][0]), float(q["K"]), float(q["real_prices"][0])
        cal_iv.append(implied_vol_call(C0, S0, K, float(q["T0_days"]) / 365.0, RISK_FREE_RATE))
        trad_iv.append(implied_vol_call(
            C0, S0, K, trading_T(q["date"], int(q["entry_minute"]), q["expiry"], sessions),
            RISK_FREE_RATE))
        tape_iv.append(float(q["real_iv"][0]))
    cal_iv = np.asarray(cal_iv) * 100.0
    trad_iv = np.asarray(trad_iv) * 100.0
    tape_iv = np.asarray(tape_iv)
    iv_check = {
        "N": int(len(fires)),
        "vendor_tape_iv_mean": float(np.nanmean(tape_iv)),
        "our_calendar_inversion_mean": float(np.nanmean(cal_iv)),
        "corr_calendar_inversion_vs_vendor": float(np.corrcoef(cal_iv, tape_iv)[0, 1]),
        "median_ratio_calendar_inversion_over_vendor": float(np.nanmedian(cal_iv / tape_iv)),
        "our_trading_time_inversion_mean": float(np.nanmean(trad_iv)),
        "our_trading_time_inversion_median": float(np.nanmedian(trad_iv)),
        "note": ("the trading-time number is NOT comparable to a vendor quote; it is the same "
                 "price under a different maturity convention.  sigma*sqrt(T) is identical, so "
                 "the breakeven-move map in T3(b) is convention-invariant."),
    }
    results["iv_convention_check"] = iv_check
    print(f"  vendor tape IV at entry            : {iv_check['vendor_tape_iv_mean']:.2f}")
    print(f"  our CALENDAR-time inversion        : {iv_check['our_calendar_inversion_mean']:.2f}  "
          f"corr with vendor {iv_check['corr_calendar_inversion_vs_vendor']:.4f}, "
          f"median ratio {iv_check['median_ratio_calendar_inversion_over_vendor']:.4f}")
    print(f"  our TRADING-time inversion (used)  : {iv_check['our_trading_time_inversion_mean']:.2f} "
          f"(median {iv_check['our_trading_time_inversion_median']:.2f})")

    # ------------------------------------------------------------------ hand check
    print()
    print("=" * 88)
    print("HAND CHECK AGAINST THE RAW ARCHIVE CSVs")
    print("=" * 88)
    checks = []
    for date_str in (P["fires_mid"]["date"].iloc[0], P["fires_mid"]["date"].iloc[16],
                     P["fires_mid"]["date"].iloc[-1]):
        c = raw_tape_hand_check(paths, date_str, sessions)
        checks.append(c)
        if c.get("found"):
            print(f"  {c['date']}  K={c['strike']:.0f}  entry {c['entry_clock']}  "
                  f"raw entry {c['raw_entry_premium']:.2f} vs panel {c['panel_entry_premium']:.2f} "
                  f"[{'OK' if c['entry_matches'] else 'MISMATCH'}]  "
                  f"raw close {c['raw_close_premium']:.2f} vs panel {c['panel_close_premium']:.2f} "
                  f"[{'OK' if c['close_matches'] else 'MISMATCH'}]  "
                  f"raw max {c['raw_max_premium']:.2f} at {c['raw_max_clock']} vs panel "
                  f"{c['panel_max_premium']:.2f} [{'OK' if c['peak_matches'] else 'MISMATCH'}]  "
                  f"=> raw close ret {c['raw_close_ret_pct']:+.2f}%, raw oracle peak "
                  f"{c['raw_oracle_peak_ret_pct']:+.2f}%")
        else:
            print(f"  {date_str}: raw files not matched")
    results["hand_check"] = checks

    with open("gate_b_exit_ceiling_results.json", "w") as fh:
        json.dump(results, fh, indent=2, default=float)
    print()
    print("wrote gate_b_exit_ceiling_results.json and gate_b_exit_ceiling_panel.csv")


if __name__ == "__main__":
    main()
