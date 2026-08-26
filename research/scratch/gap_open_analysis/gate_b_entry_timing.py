#!/usr/bin/env python3
"""Gate B ENTRY-TIMING test: separate "the day is confirmed" from "buy the option now".

New module.  It does not modify, and is not imported by, any pre-existing script.

Every Gate-B P&L number in this project enters at the gap-fill minute.  The gap fill is
the moment the day is CLASSIFIED as a reversal day -- a regime confirmation.  Whether it is
also the right moment to BUY has never been tested separately.  This script unwelds the two
decisions and runs four pre-declared tests:

E1  Unconditional entry-time scan.  Buy the ATM CALL at the fill, at fill+15/30/45/60/90,
    and at fixed clocks 10:00 .. 14:30; hold to 15:29 throughout.
E1b Volatility overpayment by entry clock (supplementary, trading-time IV inversion).
E2  Conditional entry: at clock t, buy only if the trend has confirmed by t; otherwise skip
    the day, P&L exactly zero, still in the denominator.  Benchmarked against the E1
    UNCONDITIONAL cell AT THE SAME CLOCK, and decomposed exactly into a SELECTION and a
    TIMING component.
E3  Intraday drift profile: fill-to-close signed spot move by half-hour bucket, fires vs
    matched controls, permutation p-values, Bonferroni corrected.
E4  Placebo: the entire E2 grid re-run unchanged on the control population, plus a
    shuffled-label permutation of the whole search.

Standing rules obeyed here, all of them load-bearing:
* Real strike-tracked traded premiums only.  No Black-Scholes proxy price enters any return.
* The ATM strike is RE-PICKED AT THE ENTRY MINUTE (see ``gate_b_entry_timing_common.py``).
* Any implied-volatility inversion uses TRADING-TIME maturity (CORRECTION_GATE_B_VOL_CRUSH).
* The mid-IV cell (N=33) and the pooled cell (N=120) are reported separately, never merged.
* Loss-per-minute-held is reported beside every total return, because holding periods differ
  by construction in this test and the latest entry would otherwise always look safest.
* N is reported for every cell.  The established resolution limit stands: at N=120 the grid
  spread this sample can resolve is ~9.69pp, so small differences between cells carry no
  information.

Offline analysis only.  No broker, credential, exchange network, or order path is used.  No
gate is armed and no live order exists or is authorised.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq

from bs_gap_fill_pnl import RISK_FREE_RATE, bs_call
from gate_b_common import clock_to_minutes, reproduction_guard, rule_return
import gate_b_entry_timing_common as C

RESULTS = Path("gate_b_entry_timing_results.json")
PANEL_CSV = Path("gate_b_entry_timing_panel.csv")

# ------------------------------------------------------------------ pre-declared grids
FILL_OFFSETS = (0, 15, 30, 45, 60, 90)
# NOT part of the pre-declared E1 grid and not counted in its multiplicity.  A separate
# execution-realism / microstructure diagnostic: the gap fill is detected ON a one-minute
# bar close, so the earliest minute a live system could actually buy is fill+1, and a
# one-bar spike at the fill would show up as the whole effect appearing by fill+1..fill+3.
MICRO_OFFSETS = (1, 2, 3, 5, 10)
FIXED_CLOCKS = (
    "10:00", "10:30", "11:00", "11:30", "12:00",
    "12:30", "13:00", "13:30", "14:00", "14:30",
)
CONFIRMATIONS = (
    "move>=0", "move>=10", "move>=20", "move>=30", "move>=50",
    "above_vwap", "higher_high_15", "higher_high_30", "r2_30_above_median",
)
# Same half-hour bucket grid already used by gate_b_early_exit_scan.py.  The first bucket is
# 15 minutes because the session opens at 09:15 and the last is 29 because 15:29 is the exit
# convention; every bucket's length is carried so per-minute rates are comparable.
BUCKETS = (
    ("09:15", "09:30"), ("09:30", "10:00"), ("10:00", "10:30"), ("10:30", "11:00"),
    ("11:00", "11:30"), ("11:30", "12:00"), ("12:00", "12:30"), ("12:30", "13:00"),
    ("13:00", "13:30"), ("13:30", "14:00"), ("14:00", "14:30"), ("14:30", "15:00"),
    ("15:00", "15:29"),
)
N_PERM = 5000
SEED = 20260823


def cells() -> list[dict]:
    """The 16 candidate entry clocks.  Offsets are day-relative; fixed clocks are absolute."""
    out = [{"name": f"fill+{o}" if o else "fill (baseline)", "kind": "offset", "value": o}
           for o in FILL_OFFSETS]
    out += [{"name": c, "kind": "fixed", "value": clock_to_minutes(c)} for c in FIXED_CLOCKS]
    return out


# ------------------------------------------------------------------ small helpers
def summary(r: np.ndarray, held: np.ndarray | None = None) -> dict:
    r = np.asarray(r, dtype=float)
    f = np.isfinite(r)
    r = r[f]
    if len(r) == 0:
        return {"n": 0}
    out = {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(np.median(r)),
        "win_rate": float((r > 0).mean() * 100.0),
        "sd": float(r.std(ddof=1)) if len(r) > 1 else float("nan"),
        "p_vs_zero": float(stats.ttest_1samp(r, 0.0).pvalue) if len(r) > 1 else float("nan"),
    }
    if held is not None:
        h = np.asarray(held, dtype=float)[f]
        ok = np.isfinite(h) & (h > 0)
        out["mean_held_minutes"] = float(h[ok].mean()) if ok.any() else float("nan")
        out["mean_ret_per_min"] = float((r[ok] / h[ok]).mean()) if ok.any() else float("nan")
    return out


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "   n=0"
    core = (f"N={s['n']:3d}  mean {s['mean']:+7.2f}%  med {s['median']:+7.2f}%  "
            f"win {s['win_rate']:4.1f}%  p={s['p_vs_zero']:.4f}")
    if "mean_ret_per_min" in s and np.isfinite(s["mean_ret_per_min"]):
        core += f"  held {s['mean_held_minutes']:5.1f}m  {s['mean_ret_per_min']:+.4f}%/min"
    return core


# ============================================================ panel
def build_panel(sessions: dict, pool: list[dict]) -> pd.DataFrame:
    """One row per (day, candidate entry clock).  This is the object everything else uses."""
    grid = cells()
    # cross-sectional 30-minute R^2 medians, one per FIXED clock, computed on the whole
    # 120-day pool so fires and controls face an identical threshold.  In-sample by
    # construction and declared as such.
    r2_med: dict[int, float] = {}
    for c in grid:
        if c["kind"] != "fixed":
            continue
        vals = []
        for p in pool:
            ds = sessions[p["date"]]
            i = ds.idx.get(c["value"])
            if i is not None and np.isfinite(ds.r2_30[i]):
                vals.append(float(ds.r2_30[i]))
        r2_med[c["value"]] = float(np.median(vals)) if vals else float("nan")
    # day-relative offsets get a single pooled median of the r2 seen at those entry minutes
    off_med: dict[int, float] = {}
    for c in grid:
        if c["kind"] != "offset":
            continue
        vals = []
        for p in pool:
            ds = sessions[p["date"]]
            i = ds.idx.get(ds.fill_minute + c["value"])
            if i is not None and np.isfinite(ds.r2_30[i]):
                vals.append(float(ds.r2_30[i]))
        off_med[c["value"]] = float(np.median(vals)) if vals else float("nan")

    rows = []
    for p in pool:
        ds = sessions[p["date"]]
        base = ds.trade(ds.fill_minute)
        ret_fill = base["ret"] if base else np.nan
        for c in grid:
            minute = ds.fill_minute + c["value"] if c["kind"] == "offset" else c["value"]
            thr = off_med[c["value"]] if c["kind"] == "offset" else r2_med[c["value"]]
            row = {
                "date": ds.date, "is_fire": ds.is_fire, "iv_bucket": ds.iv_bucket,
                "fill_minute": ds.fill_minute, "cell": c["name"], "cell_kind": c["kind"],
                "entry_minute": minute, "eligible": 0, "ret_fill_entry": ret_fill,
                "K": np.nan, "spot_at_entry": np.nan, "entry_px": np.nan,
                "exit_px": np.nan, "exit_minute": -1, "held": np.nan,
                "ret": np.nan, "ret_per_min": np.nan, "unpriceable": "ineligible",
                "r2_threshold": thr,
            }
            t = ds.trade(minute)
            if t is not None:
                row["eligible"] = 1
                row.update({
                    "K": t["K"], "spot_at_entry": t["spot"], "entry_px": t["entry_px"],
                    "exit_px": t["exit_px"], "exit_minute": t["exit_minute"],
                    "held": t["held"], "ret": t["ret"], "ret_per_min": t["ret_per_min"],
                    "entry_iv_quoted": t["entry_iv"], "unpriceable": t["unpriceable"],
                })
                for v in CONFIRMATIONS:
                    got = ds.confirmed(minute, v, thr)
                    row[f"conf::{v}"] = np.nan if got is None else int(got)
            else:
                for v in CONFIRMATIONS:
                    row[f"conf::{v}"] = np.nan
            rows.append(row)
    return pd.DataFrame(rows)


# ============================================================ E1
def e1(panel: pd.DataFrame, label: str, mask: pd.Series, n_pop: int) -> dict:
    grid = cells()
    out = {"label": label, "population_n": int(n_pop), "cells": []}
    sub = panel[mask]
    priced_by_cell = {}
    for c in grid:
        g = sub[sub["cell"] == c["name"]]
        elig = int(g["eligible"].sum())
        r = g["ret"].to_numpy(dtype=float)
        h = g["held"].to_numpy(dtype=float)
        s = summary(r, h)
        s.update({
            "cell": c["name"], "kind": c["kind"],
            "n_population": int(n_pop), "n_eligible": elig,
            "n_dropped_fill_after_clock": int(n_pop - elig),
            "n_unpriceable": int(elig - s.get("n", 0)),
        })
        out["cells"].append(s)
        priced_by_cell[c["name"]] = set(g.loc[np.isfinite(g["ret"]), "date"])

    common = set.intersection(*priced_by_cell.values()) if priced_by_cell else set()
    out["common_sample_dates"] = sorted(common)
    out["common_sample_n"] = len(common)
    out["common_cells"] = []
    for c in grid:
        g = sub[(sub["cell"] == c["name"]) & (sub["date"].isin(common))]
        s = summary(g["ret"].to_numpy(float), g["held"].to_numpy(float))
        s["cell"] = c["name"]
        out["common_cells"].append(s)
    return out


def e1_paired(panel: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    """Does WAITING help, on the SAME days?  Paired difference vs the fill-minute entry.

    This is the composition-free version of E1: every cell is compared against the fill
    baseline on exactly the days priceable in both, so a cell can never win merely because
    the late-filling days dropped out of it.
    """
    sub = panel[mask]
    base = sub[sub["cell"] == "fill (baseline)"].set_index("date")["ret"]
    out = {"label": label, "cells": []}
    for c in cells():
        if c["name"] == "fill (baseline)":
            continue
        g = sub[sub["cell"] == c["name"]].set_index("date")["ret"]
        j = pd.concat([base.rename("fill"), g.rename("late")], axis=1).dropna()
        if len(j) < 5:
            out["cells"].append({"cell": c["name"], "n_paired": int(len(j))})
            continue
        d = (j["late"] - j["fill"]).to_numpy(dtype=float)
        out["cells"].append({
            "cell": c["name"], "n_paired": int(len(j)),
            "mean_fill_pct": float(j["fill"].mean()),
            "mean_late_pct": float(j["late"].mean()),
            "mean_difference_pp": float(d.mean()),
            "median_difference_pp": float(np.median(d)),
            "share_improved_pct": float((d > 0).mean() * 100.0),
            "p_paired": float(stats.ttest_rel(j["late"], j["fill"]).pvalue),
            "p_wilcoxon": float(stats.wilcoxon(d).pvalue) if np.any(d != 0) else float("nan"),
        })
    n_tests = sum(1 for c in out["cells"] if c.get("n_paired", 0) >= 5)
    for c in out["cells"]:
        if "p_paired" in c:
            c["p_paired_bonferroni"] = min(1.0, c["p_paired"] * n_tests)
            c["p_wilcoxon_bonferroni"] = min(1.0, c["p_wilcoxon"] * n_tests)
    out["n_tests_in_family"] = n_tests
    return out


def e1_micro_shift(sessions: dict, days: list[dict], label: str) -> dict:
    """Paired return of entering ``k`` minutes after the fill, for very small ``k``.

    Two questions at once.  (1) Execution realism: the fill is observed at a bar close, so
    fill+1 is the earliest entry a live monitor could achieve; how much of the published
    fill-minute loss is an unexecutable price?  (2) Microstructure: if the whole
    late-entry advantage is already present at fill+1..fill+3 the effect is a single spiky
    bar at the crossing, not drift.
    """
    rows = []
    for p_ in days:
        ds = sessions[p_["date"]]
        base = ds.trade(ds.fill_minute)
        if base is None or not np.isfinite(base["ret"]):
            continue
        for k in MICRO_OFFSETS:
            t = ds.trade(ds.fill_minute + k)
            if t is None or not np.isfinite(t["ret"]):
                continue
            i0 = ds.idx[ds.fill_minute]
            i1 = ds.idx.get(ds.fill_minute + k)
            rows.append({"k": k, "diff": t["ret"] - base["ret"], "late": t["ret"],
                         "fill": base["ret"],
                         "d_spot": float(ds.spot[i1] - ds.spot[i0]) if i1 is not None
                         else np.nan})
    df = pd.DataFrame(rows)
    out = {"label": label, "offsets": []}
    for k in MICRO_OFFSETS:
        g = df[df["k"] == k]
        if len(g) < 5:
            continue
        out["offsets"].append({
            "offset_minutes": k, "n": int(len(g)),
            "mean_fill_pct": float(g["fill"].mean()),
            "mean_late_pct": float(g["late"].mean()),
            "mean_difference_pp": float(g["diff"].mean()),
            "median_difference_pp": float(g["diff"].median()),
            "p_paired": float(stats.ttest_rel(g["late"], g["fill"]).pvalue),
            "mean_spot_change_points": float(g["d_spot"].mean()),
            "p_spot_vs_zero": float(stats.ttest_1samp(g["d_spot"].dropna(), 0.0).pvalue),
        })
    return out


def e1_paired_placebo(panel: pd.DataFrame, n_perm: int = N_PERM) -> dict:
    """Is "waiting after the fill helps" a GATE-B property, or a property of the fill event?

    For every entry cell, the paired (late - fill) difference is computed per day and the
    fires' mean is compared with the controls' mean, with a permutation test that reassigns
    the 33-day fire label at random among the 120 pool days.  This is the placebo the E1
    finding needs: both arms are defined by the identical first-crossing rule on the
    identical spot series, so any mechanical first-passage artifact cancels in the
    difference.
    """
    rng = np.random.default_rng(SEED + 3)
    base = panel[panel["cell"] == "fill (baseline)"].set_index("date")["ret"]
    out = {"cells": [], "n_permutations": n_perm}
    for c in cells():
        if c["name"] == "fill (baseline)":
            continue
        g = panel[panel["cell"] == c["name"]].set_index("date")
        j = pd.concat([base.rename("fill"), g["ret"].rename("late"),
                       g["is_fire"].rename("is_fire")], axis=1).dropna()
        if len(j) < 20:
            continue
        d = (j["late"] - j["fill"]).to_numpy(dtype=float)
        lab = j["is_fire"].to_numpy(dtype=int) == 1
        if lab.sum() < 5 or (~lab).sum() < 5:
            continue
        obs = float(d[lab].mean() - d[~lab].mean())
        draws = np.empty(n_perm)
        k = int(lab.sum())
        for i in range(n_perm):
            m = np.zeros(len(d), bool)
            m[rng.choice(len(d), k, replace=False)] = True
            draws[i] = d[m].mean() - d[~m].mean()
        out["cells"].append({
            "cell": c["name"], "n_fires": int(lab.sum()), "n_controls": int((~lab).sum()),
            "fire_mean_diff_pp": float(d[lab].mean()),
            "control_mean_diff_pp": float(d[~lab].mean()),
            "difference_in_differences_pp": obs,
            "welch_p": float(stats.ttest_ind(d[lab], d[~lab], equal_var=False).pvalue),
            "perm_p": float((np.abs(draws) >= abs(obs)).mean()),
        })
    return out


def e1_entry_price_decomposition(sessions: dict, days: list[dict]) -> dict:
    """Where does a later entry's advantage come from -- a lower spot, or a cheaper option?

    Reports, for each fill-relative offset, the mean spot change since the fill and the mean
    change in the ATM CALL premium since the fill, both on the same days.  A premium that
    falls while spot is flat is the option getting cheaper for reasons other than direction.
    """
    rows = []
    for p in days:
        ds = sessions[p["date"]]
        base = ds.trade(ds.fill_minute)
        if base is None or not np.isfinite(base["ret"]):
            continue
        s0 = base["spot"]
        for o in FILL_OFFSETS:
            t = ds.trade(ds.fill_minute + o)
            if t is None or not np.isfinite(t["ret"]):
                continue
            rows.append({
                "offset": o, "d_spot": t["spot"] - s0,
                "d_premium_pct": (t["entry_px"] - base["entry_px"]) / base["entry_px"] * 100.0,
                "atm_premium_at_entry": t["entry_px"],
            })
    df = pd.DataFrame(rows)
    out = []
    for o in FILL_OFFSETS:
        g = df[df["offset"] == o]
        if g.empty:
            continue
        out.append({
            "offset_minutes": o, "n": int(len(g)),
            "mean_spot_change_points": float(g["d_spot"].mean()),
            "median_spot_change_points": float(g["d_spot"].median()),
            "p_spot_vs_zero": float(stats.ttest_1samp(g["d_spot"], 0.0).pvalue),
            "mean_atm_premium_change_pct": float(g["d_premium_pct"].mean()),
            "mean_atm_premium": float(g["atm_premium_at_entry"].mean()),
        })
    return {"offsets": out}


# ============================================================ E1b volatility overpayment
def implied_vol(price: float, S: float, K: float, T: float) -> float:
    try:
        return float(brentq(lambda v: bs_call(S, K, T, RISK_FREE_RATE, v) - price,
                            1e-4, 5.0, maxiter=200, xtol=1e-8))
    except Exception:
        return float("nan")


def e1b(sessions: dict, pool: list[dict], label_mask, label: str) -> dict:
    tdates = C.trading_dates()
    grid = cells()
    rows = []
    for p in pool:
        if not label_mask(p):
            continue
        ds = sessions[p["date"]]
        for c in grid:
            minute = ds.fill_minute + c["value"] if c["kind"] == "offset" else c["value"]
            t = ds.trade(minute)
            if t is None or not np.isfinite(t["ret"]):
                continue
            T = C.trading_T(ds.date, minute, ds.expiry, tdates)
            iv = implied_vol(t["entry_px"], t["spot"], t["K"], T)
            # diagnostic ONLY: the retracted calendar convention, carried so the two
            # conventions can be reconciled in the report.  It enters no headline.
            t_cal = max((pd.Timestamp(ds.expiry) + pd.Timedelta(hours=15, minutes=30)
                         - pd.Timestamp(f"{ds.date} {minute//60:02d}:{minute%60:02d}:00")
                         ).total_seconds() / (365.0 * 24 * 3600), 1e-9)
            iv_cal = implied_vol(t["entry_px"], t["spot"], t["K"], t_cal)
            i = ds.idx[minute]
            fwd = ds.spot[i:]
            if len(fwd) < 20:
                continue
            lr = np.diff(np.log(fwd))
            rv = float(np.std(lr, ddof=1) * np.sqrt(C.TRADING_MINUTES_PER_DAY
                                                    * C.TRADING_DAYS_PER_YEAR))
            rows.append({"cell": c["name"], "iv": iv * 100.0, "rv": rv * 100.0,
                         "gap": (iv - rv) * 100.0, "held": t["held"],
                         "iv_calendar_diagnostic": iv_cal * 100.0})
    df = pd.DataFrame(rows)
    out = {"label": label, "cells": []}
    for c in grid:
        g = df[df["cell"] == c["name"]].dropna(subset=["iv", "rv"])
        if g.empty:
            out["cells"].append({"cell": c["name"], "n": 0})
            continue
        out["cells"].append({
            "cell": c["name"], "n": int(len(g)),
            "mean_implied_pct": float(g["iv"].mean()),
            "mean_realised_pct": float(g["rv"].mean()),
            "mean_gap_pp": float(g["gap"].mean()),
            "p_gap_vs_zero": float(stats.ttest_1samp(g["gap"], 0.0).pvalue),
            "mean_held_minutes": float(g["held"].mean()),
            "mean_implied_pct_CALENDAR_diagnostic_only": float(
                g["iv_calendar_diagnostic"].mean()),
        })
    return out


# ============================================================ E2
def e2_cell(g: pd.DataFrame, variant: str) -> dict | None:
    """One (entry clock x confirmation) cell for one population.

    ``g`` is the panel slice for one population and one entry clock.  The cell sample is
    the set of days that are eligible at that clock AND priceable there; the conditional
    arm and the same-clock unconditional benchmark share that denominator exactly.
    """
    col = f"conf::{variant}"
    g = g[np.isfinite(g["ret"]) & np.isfinite(g[col])]
    n = len(g)
    if n < 5:
        return None
    conf = g[col].to_numpy(dtype=float) > 0.5
    ret_t = g["ret"].to_numpy(dtype=float)
    ret_fill = g["ret_fill_entry"].to_numpy(dtype=float)
    held = g["held"].to_numpy(dtype=float)

    cond = np.where(conf, ret_t, 0.0)          # skipped day = exactly zero, still counted
    uncond_t = ret_t
    n_sel, n_skip = int(conf.sum()), int((~conf).sum())

    # exact additive decomposition of (conditional at t) - (unconditional at the FILL)
    timing = (n_sel / n) * (float(np.mean(ret_t[conf] - ret_fill[conf])) if n_sel else 0.0)
    selection = -(n_skip / n) * (float(np.mean(ret_fill[~conf])) if n_skip else 0.0)
    delta_vs_fill = float(cond.mean() - np.nanmean(ret_fill))
    delta_same_clock = float(cond.mean() - uncond_t.mean())

    diff = cond - uncond_t
    p_paired = (float(stats.ttest_rel(cond, uncond_t).pvalue)
                if np.std(diff) > 0 else float("nan"))

    out = {
        "variant": variant, "n_cell": n,
        "n_selected": n_sel, "n_skipped": n_skip,
        "skip_rate_pct": float(n_skip / n * 100.0),
        "conditional": summary(cond),
        "conditional_traded_only": summary(ret_t[conf], held[conf]) if n_sel else {"n": 0},
        "unconditional_same_clock": summary(uncond_t, held),
        "unconditional_at_fill": summary(ret_fill),
        "delta_same_clock_pp": delta_same_clock,
        "p_paired_vs_same_clock": p_paired,
        "delta_vs_fill_entry_pp": delta_vs_fill,
        "component_timing_pp": timing,
        "component_selection_pp": selection,
        "decomposition_residual_pp": float(delta_vs_fill - timing - selection),
        "skipped_days_would_have_earned_at_t": summary(ret_t[~conf]) if n_skip else {"n": 0},
        "skipped_days_would_have_earned_at_fill": (summary(ret_fill[~conf]) if n_skip
                                                   else {"n": 0}),
        "selected_days_fill_entry": summary(ret_fill[conf]) if n_sel else {"n": 0},
    }
    return out


def e2(panel: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    sub = panel[mask]
    out = {"label": label, "grid": []}
    for c in cells():
        g = sub[sub["cell"] == c["name"]]
        for v in CONFIRMATIONS:
            r = e2_cell(g, v)
            if r is None:
                continue
            r["cell"] = c["name"]
            r["kind"] = c["kind"]
            out["grid"].append(r)
    out["n_cells_tested"] = len(out["grid"])
    if out["grid"]:
        best = max(out["grid"], key=lambda r: r["conditional"]["mean"])
        out["best_by_conditional_mean"] = {
            k: best[k] for k in ("cell", "variant", "n_cell", "n_selected", "skip_rate_pct",
                                 "delta_same_clock_pp", "component_timing_pp",
                                 "component_selection_pp", "delta_vs_fill_entry_pp")
        }
        out["best_by_conditional_mean"]["conditional_mean"] = best["conditional"]["mean"]
        out["best_by_conditional_mean"]["conditional_p"] = best["conditional"]["p_vs_zero"]
        bd = max(out["grid"], key=lambda r: r["delta_same_clock_pp"])
        out["best_by_delta_same_clock"] = {
            k: bd[k] for k in ("cell", "variant", "n_cell", "delta_same_clock_pp",
                               "p_paired_vs_same_clock")
        }
        out["n_positive_conditional_means"] = sum(
            1 for r in out["grid"] if r["conditional"]["mean"] > 0)
        out["n_beating_same_clock_unconditional"] = sum(
            1 for r in out["grid"] if r["delta_same_clock_pp"] > 0)
        ps = [r["p_paired_vs_same_clock"] for r in out["grid"]
              if np.isfinite(r["p_paired_vs_same_clock"])]
        out["min_p_vs_same_clock"] = float(min(ps)) if ps else float("nan")
        out["min_p_vs_same_clock_bonferroni"] = (
            min(1.0, float(min(ps)) * len(out["grid"])) if ps else float("nan"))
        out["n_significant_vs_same_clock_raw_5pct"] = sum(1 for x in ps if x < 0.05)
        out["n_degenerate_never_trade_cells"] = sum(1 for r in out["grid"]
                                                    if r["n_selected"] == 0)
        live = [r for r in out["grid"] if r["n_selected"] > 0]
        if live:
            bl = max(live, key=lambda r: r["delta_same_clock_pp"])
            out["best_by_delta_same_clock_excluding_never_trade_cells"] = {
                k: bl[k] for k in ("cell", "variant", "n_cell", "n_selected",
                                   "delta_same_clock_pp", "p_paired_vs_same_clock")}
    return out


# ============================================================ E3 drift profile
def bucket_matrix(sessions: dict, days: list[dict], full_only: bool) -> tuple[np.ndarray, np.ndarray]:
    """``[day, bucket]`` signed spot move in points, and matching bucket lengths in minutes.

    ``full_only``: keep only buckets that lie ENTIRELY after the fill, so every retained
    observation is a full-length bucket and lengths are comparable across days.  Otherwise
    a partially-elapsed bucket is measured from max(bucket start, fill).
    """
    nb = len(BUCKETS)
    M = np.full((len(days), nb), np.nan)
    L = np.full((len(days), nb), np.nan)
    for r, p in enumerate(days):
        ds = sessions[p["date"]]
        for b, (a, z) in enumerate(BUCKETS):
            lo, hi = clock_to_minutes(a), clock_to_minutes(z)
            start = lo if full_only else max(lo, ds.fill_minute)
            if full_only and ds.fill_minute > lo:
                continue
            if start >= hi or ds.fill_minute > hi:
                continue
            i0, i1 = ds.idx.get(start), ds.idx.get(hi)
            if i0 is None or i1 is None:
                continue
            M[r, b] = float(ds.spot[i1] - ds.spot[i0])
            L[r, b] = float(hi - start)
    return M, L


def e3(sessions: dict, fires: list[dict], controls: list[dict]) -> dict:
    warnings.filterwarnings("ignore", message="Mean of empty slice")
    rng = np.random.default_rng(SEED)
    out = {"buckets": [b[0] + "-" + b[1] for b in BUCKETS], "n_buckets": len(BUCKETS)}
    for tag, full_only in (("buckets_entirely_after_fill", True),
                           ("buckets_from_max_of_start_and_fill", False)):
        Mf, Lf = bucket_matrix(sessions, fires, full_only)
        Mc, Lc = bucket_matrix(sessions, controls, full_only)
        M = np.vstack([Mf, Mc])
        L = np.vstack([Lf, Lc])
        lab = np.r_[np.ones(len(fires), bool), np.zeros(len(controls), bool)]

        def stat(mask: np.ndarray) -> np.ndarray:
            with np.errstate(invalid="ignore"):
                A = np.where(mask[:, None], M, np.nan)
                B = np.where((~mask)[:, None], M, np.nan)
                a = np.where(np.isfinite(A).sum(0) > 0, np.nansum(A, 0)
                             / np.maximum(np.isfinite(A).sum(0), 1), np.nan)
                b = np.where(np.isfinite(B).sum(0) > 0, np.nansum(B, 0)
                             / np.maximum(np.isfinite(B).sum(0), 1), np.nan)
            return a - b

        usable = (np.isfinite(Mf).sum(0) > 0) & (np.isfinite(Mc).sum(0) > 0)

        obs = stat(lab)
        draws = np.full((N_PERM, len(BUCKETS)), np.nan)
        for i in range(N_PERM):
            draws[i] = stat(rng.permutation(lab))
        with np.errstate(invalid="ignore"):
            hit = np.abs(draws) >= np.abs(obs)[None, :]
            p = np.where(usable, np.nanmean(np.where(np.isfinite(draws), hit, np.nan), axis=0),
                         np.nan)
        n_usable = int(usable.sum())
        rows = []
        for b, name in enumerate(out["buckets"]):
            nf = int(np.isfinite(Mf[:, b]).sum())
            nc = int(np.isfinite(Mc[:, b]).sum())
            mf = float(np.nanmean(Mf[:, b])) if nf else float("nan")
            mc = float(np.nanmean(Mc[:, b])) if nc else float("nan")
            lf = float(np.nanmean(Lf[:, b])) if nf else float("nan")
            rows.append({
                "bucket": name, "minutes": lf,
                "n_fires": nf, "mean_fire_points": mf,
                "fire_points_per_min": mf / lf if nf and lf else float("nan"),
                "n_controls": nc, "mean_control_points": mc,
                "diff_points": float(obs[b]) if np.isfinite(obs[b]) else float("nan"),
                "perm_p": float(p[b]) if np.isfinite(p[b]) else float("nan"),
                "perm_p_bonferroni": (min(1.0, float(p[b]) * n_usable)
                                      if np.isfinite(p[b]) else float("nan")),
                "p_fire_vs_zero": (float(stats.ttest_1samp(
                    Mf[np.isfinite(Mf[:, b]), b], 0.0).pvalue) if nf > 1 else float("nan")),
            })
        out[tag] = rows
        out[tag + "__n_usable_buckets_for_bonferroni"] = n_usable

    # common-sample version: days whose fill is at or before the first bucket end, so all
    # 13 buckets exist for the same days.
    cut = clock_to_minutes(BUCKETS[0][1])
    cf = [p for p in fires if sessions[p["date"]].fill_minute <= cut]
    cc = [p for p in controls if sessions[p["date"]].fill_minute <= cut]
    Mf, Lf = bucket_matrix(sessions, cf, True)
    out["common_sample"] = {
        "cut_clock": BUCKETS[0][1], "n_fires": len(cf), "n_controls": len(cc),
        "fire_mean_points_by_bucket": [
            float(np.nanmean(Mf[:, b])) if np.isfinite(Mf[:, b]).any() else None
            for b in range(len(BUCKETS))],
    }
    # the single most important context number for E3: what IS the fill-to-close move?
    def f2c(days):
        return np.asarray([float(sessions[q["date"]].spot[-1]
                                 - sessions[q["date"]].spot[sessions[q["date"]].idx[
                                     sessions[q["date"]].fill_minute]]) for q in days])
    ff, fc = f2c(fires), f2c(controls)
    out["fill_to_close_spot_move"] = {
        "fires": {"n": int(len(ff)), "mean_points": float(ff.mean()),
                  "median_points": float(np.median(ff)),
                  "share_up_pct": float((ff > 0).mean() * 100.0),
                  "p_vs_zero": float(stats.ttest_1samp(ff, 0.0).pvalue)},
        "controls": {"n": int(len(fc)), "mean_points": float(fc.mean()),
                     "median_points": float(np.median(fc)),
                     "share_up_pct": float((fc > 0).mean() * 100.0),
                     "p_vs_zero": float(stats.ttest_1samp(fc, 0.0).pvalue)},
        "difference_points": float(ff.mean() - fc.mean()),
        "welch_p": float(stats.ttest_ind(ff, fc, equal_var=False).pvalue),
    }

    # cumulative MEAN signed move from the fill, by wall clock, on a common sample.  This
    # is the robust version of the share table below: a ratio to a near-zero denominator
    # (the fill-to-close move averages a handful of points) is not a usable statistic.
    cum_cut = clock_to_minutes("10:00")
    cum = []
    cf2 = [q for q in fires if sessions[q["date"]].fill_minute <= cum_cut]
    cc2 = [q for q in controls if sessions[q["date"]].fill_minute <= cum_cut]
    for m in range(cum_cut, C.END_MIN + 1, 30):
        def cmean(days):
            v = []
            for q in days:
                ds = sessions[q["date"]]
                i = ds.idx.get(m)
                if i is not None:
                    v.append(float(ds.spot[i] - ds.spot[ds.idx[ds.fill_minute]]))
            return (float(np.mean(v)), int(len(v))) if v else (float("nan"), 0)
        mf, nf = cmean(cf2)
        mc, nc = cmean(cc2)
        cum.append({"clock": f"{m//60:02d}:{m%60:02d}",
                    "fires_cum_points": mf, "n_fires": nf,
                    "controls_cum_points": mc, "n_controls": nc})
    out["cumulative_signed_move_from_fill"] = {
        "common_sample_rule": "gap filled at or before 10:00",
        "n_fires": len(cf2), "n_controls": len(cc2), "rows": cum}

    # cumulative share of the whole fill-to-close move by clock, fires only, on a COMMON
    # sample (fill at or before 10:00) so the denominator does not change across clocks.
    share_cut = clock_to_minutes("10:00")
    shares = []
    for p in [q for q in fires if sessions[q["date"]].fill_minute <= share_cut]:
        ds = sessions[p["date"]]
        i0 = ds.idx[ds.fill_minute]
        tot = float(ds.spot[-1] - ds.spot[i0])
        if abs(tot) < 1e-9:
            continue
        row = {}
        for m in range(600, C.END_MIN + 1, 30):
            i = ds.idx.get(m)
            if i is None or m < ds.fill_minute:
                continue
            row[f"{m//60:02d}:{m%60:02d}"] = float((ds.spot[i] - ds.spot[i0]) / tot * 100.0)
        shares.append(row)
    sh = pd.DataFrame(shares)
    out["median_pct_of_fill_to_close_move_achieved_by"] = {
        c: float(sh[c].median()) for c in sh.columns if sh[c].notna().sum() >= 10}
    out["n_fires_in_share_table"] = int(len(sh))
    out["share_table_common_sample_rule"] = "fires whose gap filled at or before 10:00"

    # post-fill spot drift by elapsed horizon: the direct, option-free test of whether the
    # gate-day move is back-loaded, and of whether spot pulls back right after the fill.
    horizons = (5, 10, 15, 20, 30, 45, 60, 90, 120, 180)
    rng2 = np.random.default_rng(SEED + 2)
    drift = []
    for h in horizons:
        def moves(days):
            v = []
            for p in days:
                ds = sessions[p["date"]]
                i0 = ds.idx[ds.fill_minute]
                i1 = ds.idx.get(ds.fill_minute + h)
                if i1 is None:
                    continue
                v.append(float(ds.spot[i1] - ds.spot[i0]))
            return np.asarray(v, dtype=float)
        mf, mc = moves(fires), moves(controls)
        both = np.r_[mf, mc]
        lab = np.r_[np.ones(len(mf), bool), np.zeros(len(mc), bool)]
        obs_d = float(mf.mean() - mc.mean()) if len(mf) and len(mc) else float("nan")
        dd = np.empty(N_PERM)
        for i in range(N_PERM):
            s_ = rng2.permutation(lab)
            dd[i] = both[s_].mean() - both[~s_].mean()
        drift.append({
            "horizon_minutes": h,
            "n_fires": int(len(mf)), "mean_fire_points": float(mf.mean()),
            "median_fire_points": float(np.median(mf)),
            "p_fire_vs_zero": float(stats.ttest_1samp(mf, 0.0).pvalue) if len(mf) > 1 else None,
            "n_controls": int(len(mc)), "mean_control_points": float(mc.mean()),
            "diff_points": obs_d,
            "perm_p": float((np.abs(dd) >= abs(obs_d)).mean()),
        })
    out["post_fill_spot_drift"] = drift
    return out


def e1_stability(panel: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    """Split-half and by-year stability of the paired late-minus-fill difference.

    A 33-day sample spanning five years can hide a result that lives in one period.  Every
    Gate-B finding in this project that looked strong and then died (the mid-IV filter, the
    dealer-gamma coefficient) died on exactly this check, so it is run here up front.
    """
    sub = panel[mask]
    base = sub[sub["cell"] == "fill (baseline)"].set_index("date")["ret"]
    out = {"label": label, "cells": []}
    for c in cells():
        if c["name"] == "fill (baseline)":
            continue
        g = sub[sub["cell"] == c["name"]].set_index("date")["ret"]
        j = pd.concat([base.rename("fill"), g.rename("late")], axis=1).dropna().sort_index()
        if len(j) < 12:
            continue
        d = (j["late"] - j["fill"])
        half = len(j) // 2
        first, second = d.iloc[:half], d.iloc[half:]
        by_year = {y: float(v.mean()) for y, v in d.groupby(
            pd.Index([x[:4] for x in d.index], name="year"))}
        n_year = {y: int(v.size) for y, v in d.groupby(
            pd.Index([x[:4] for x in d.index], name="year"))}
        out["cells"].append({
            "cell": c["name"], "n": int(len(d)),
            "first_half_mean_pp": float(first.mean()), "first_half_n": int(len(first)),
            "second_half_mean_pp": float(second.mean()), "second_half_n": int(len(second)),
            "both_halves_positive": bool(first.mean() > 0 and second.mean() > 0),
            "by_year_mean_pp": by_year, "by_year_n": n_year,
            "years_positive": int(sum(1 for v in by_year.values() if v > 0)),
            "years_total": len(by_year),
        })
    return out


# ============================================================ E4 placebo
def e4(panel: pd.DataFrame, sessions: dict, pool: list[dict],
       fire_grid: dict, control_grid: dict) -> dict:
    out = {
        "fires_best": fire_grid.get("best_by_conditional_mean"),
        "controls_best": control_grid.get("best_by_conditional_mean"),
        "fires_n_positive": fire_grid.get("n_positive_conditional_means"),
        "controls_n_positive": control_grid.get("n_positive_conditional_means"),
        "fires_n_cells": fire_grid.get("n_cells_tested"),
        "controls_n_cells": control_grid.get("n_cells_tested"),
    }
    # shuffled-label placebo over the WHOLE search: reassign the 33-day "fire" label at
    # random among the 120 pool days and re-run every cell, scoring the best-of-grid mean.
    rng = np.random.default_rng(SEED + 1)
    dates = np.asarray(sorted({p["date"] for p in pool}))
    n_fire = sum(1 for p in pool if int(p["is_gate_b"]) == 1)
    grid = cells()
    ret = {}
    conf = {}
    for c in grid:
        g = panel[panel["cell"] == c["name"]].set_index("date")
        ret[c["name"]] = g["ret"].reindex(dates).to_numpy(dtype=float)
        for v in CONFIRMATIONS:
            conf[(c["name"], v)] = g[f"conf::{v}"].reindex(dates).to_numpy(dtype=float)

    def best_mean(sel: np.ndarray, statistic: str = "conditional_mean") -> float:
        best = -np.inf
        for c in grid:
            r = ret[c["name"]]
            for v in CONFIRMATIONS:
                cf = conf[(c["name"], v)]
                ok = sel & np.isfinite(r) & np.isfinite(cf)
                n = int(ok.sum())
                if n < 5:
                    continue
                picked = cf[ok] > 0.5
                if statistic == "delta_same_clock" and picked.sum() == 0:
                    continue      # a never-trade cell is not a timing discovery
                m = float(np.where(picked, r[ok], 0.0).mean())
                if statistic == "delta_same_clock":
                    m -= float(r[ok].mean())
                best = max(best, m)
        return best

    real = np.asarray([1 if any(p["date"] == d and int(p["is_gate_b"]) == 1 for p in pool)
                       else 0 for d in dates], dtype=bool)
    obs = best_mean(real)
    draws = np.empty(2000)
    for i in range(2000):
        s = np.zeros(len(dates), bool)
        s[rng.choice(len(dates), n_fire, replace=False)] = True
        draws[i] = best_mean(s)
    out["shuffled_label_placebo"] = {
        "draws": int(len(draws)),
        "observed_best_of_grid_mean": float(obs),
        "placebo_median": float(np.median(draws)),
        "placebo_p90": float(np.percentile(draws, 90)),
        "empirical_p": float((draws >= obs).mean()),
        "share_of_draws_with_positive_best": float((draws > 0).mean()),
    }
    obs_d = best_mean(real, "delta_same_clock")
    dd = np.empty(2000)
    for i in range(2000):
        s_ = np.zeros(len(dates), bool)
        s_[rng.choice(len(dates), n_fire, replace=False)] = True
        dd[i] = best_mean(s_, "delta_same_clock")
    out["shuffled_label_placebo_on_the_benchmark_disciplined_statistic"] = {
        "statistic": ("best-of-grid (conditional mean - SAME-CLOCK unconditional mean), "
                      "never-trade cells excluded"),
        "draws": int(len(dd)),
        "observed": float(obs_d),
        "placebo_median": float(np.median(dd)),
        "placebo_p90": float(np.percentile(dd, 90)),
        "empirical_p": float((dd >= obs_d).mean()),
    }
    return out


def power(panel: pd.DataFrame) -> dict:
    """Minimum detectable mean return at 80% power, and for the paired late-minus-fill test.

    Stated because a null in this project has repeatedly turned out to be a sample-size
    statement rather than an economic one: the established resolution limit is that at
    N=120 the exit-grid SPREAD that can be resolved is ~9.69pp, so cell-to-cell rankings
    carry no information -- only the sign pattern does.
    """
    out = {"alpha": 0.05, "target_power": 0.80, "cells": []}
    base = panel[panel["cell"] == "fill (baseline)"].set_index("date")["ret"]
    for label, m in (("mid-IV N=33", panel["is_fire"] == 1),
                     ("pooled N=120", panel["date"].notna()),
                     ("controls N=87", panel["is_fire"] == 0)):
        sub = panel[m]
        for cell in ("fill (baseline)", "12:30"):
            g = sub[sub["cell"] == cell]["ret"].dropna()
            if len(g) < 5:
                continue
            n = len(g)
            crit = stats.t.ppf(0.975, n - 1) + stats.norm.ppf(0.80)
            out["cells"].append({
                "population": label, "cell": cell, "n": int(n),
                "sd_pct": float(g.std(ddof=1)),
                "min_detectable_mean_pct_at_80pct_power": float(
                    crit * g.std(ddof=1) / np.sqrt(n)),
            })
        j = pd.concat([base.rename("f"), sub[sub["cell"] == "12:30"].set_index("date")["ret"]
                       .rename("l")], axis=1).dropna()
        if len(j) >= 5:
            d = (j["l"] - j["f"])
            n = len(d)
            crit = stats.t.ppf(0.975, n - 1) + stats.norm.ppf(0.80)
            out["cells"].append({
                "population": label, "cell": "PAIRED 12:30 minus fill", "n": int(n),
                "sd_pct": float(d.std(ddof=1)),
                "min_detectable_mean_pct_at_80pct_power": float(
                    crit * d.std(ddof=1) / np.sqrt(n)),
                "observed_mean_pp": float(d.mean()),
            })
    return out


# ============================================================ verification
def verification(sessions: dict, panel: pd.DataFrame, fires: list[dict]) -> dict:
    out: dict = {}
    # 1. the ATM strike really is re-picked at the entry minute
    ex = []
    for p in fires:
        ds = sessions[p["date"]]
        k_fill = ds.atm_strike(ds.fill_minute)
        m12 = clock_to_minutes("12:00")
        if m12 < ds.fill_minute or m12 not in ds.idx:
            continue
        k12 = ds.atm_strike(m12)
        ex.append({
            "date": ds.date,
            "fill_clock": f"{ds.fill_minute//60:02d}:{ds.fill_minute%60:02d}",
            "spot_at_fill": float(ds.spot[ds.idx[ds.fill_minute]]),
            "strike_at_fill": k_fill,
            "spot_at_1200": float(ds.spot[ds.idx[m12]]),
            "strike_at_1200": k12,
            "strike_differs": bool(abs(k12 - k_fill) > 1e-9),
            "strike_gap_points": float(k12 - k_fill),
        })
    diff = [e for e in ex if e["strike_differs"]]
    out["strike_repick"] = {
        "fires_with_a_1200_entry": len(ex),
        "of_which_1200_strike_differs_from_fill_strike": len(diff),
        "share_pct": float(len(diff) / len(ex) * 100.0) if ex else float("nan"),
        "largest_gap_example": max(diff, key=lambda e: abs(e["strike_gap_points"]))
        if diff else None,
        "worked_examples": diff[:3],
    }
    # 2. no calendar-time maturity anywhere except the explicitly labelled diagnostic
    files = {"gate_b_entry_timing_common.py": Path("gate_b_entry_timing_common.py").read_text(),
             "gate_b_entry_timing.py": Path(__file__).read_text()}
    cal_lines, cal_ctx = [], []
    for f, txt in files.items():
        L = txt.splitlines()
        for i, ln in enumerate(L):
            if "365" not in ln or "AUDIT-SELF" in ln or ln.strip().startswith("#"):
                continue
            cal_lines.append(f"{f}:{i+1}: {ln.strip()}")
            cal_ctx.append(" ".join(L[max(0, i - 3):i + 2]))
    out["no_calendar_time_iv"] = {
        "code_lines_containing_a_365_day_year": cal_lines,   # AUDIT-SELF
        "all_of_them_inside_the_labelled_calendar_diagnostic": bool(cal_ctx) and all(
            "t_cal" in ctx or "iv_cal" in ctx for ctx in cal_ctx),
        "n_such_lines": len(cal_lines),
        "maturity_used_for_every_reported_implied_vol": "trading time",
        "trading_minutes_per_day": C.TRADING_MINUTES_PER_DAY,
        "trading_days_per_year": C.TRADING_DAYS_PER_YEAR,
    }
    # 3. no Black-Scholes price in any headline return
    bs_lines = [f"{f}:{i+1}: {ln.strip()}"   # AUDIT-SELF
                for f, txt in files.items()
                for i, ln in enumerate(txt.splitlines())
                if ("bs_prices" in ln or "C0_bs" in ln) and "AUDIT-SELF" not in ln]
    out["no_bs_proxy_in_returns"] = {
        "bs_call_used_for": "implied-volatility inversion in E1b only, never for a return",
        "returns_source": "traded one-minute bar close of the tracked absolute strike",
        "code_lines_touching_a_black_scholes_price_series": bs_lines,
        "count": len(bs_lines),
    }
    # 4. baseline reproduces the published real-premium Gate-B numbers
    r_mine, r_pub = [], []
    for p in fires:
        ds = sessions[p["date"]]
        t = ds.trade(ds.fill_minute)
        r_mine.append(t["ret"] if t else np.nan)
        r_pub.append(rule_return(p, "real_prices"))
    r_mine, r_pub = np.asarray(r_mine), np.asarray(r_pub)
    out["baseline_reproduction"] = {
        "published_mean_pct": -6.08,
        "this_pipeline_mean_pct": float(np.nanmean(r_mine)),
        "published_median_pct": -13.46,
        "this_pipeline_median_pct": float(np.nanmedian(r_mine)),
        "max_abs_per_day_difference_pp": float(np.nanmax(np.abs(r_mine - r_pub))),
        "days_compared": int(np.isfinite(r_mine - r_pub).sum()),
    }
    return out


def hand_check(sessions: dict, date: str, minute: int) -> dict:
    """Re-read the RAW archive CSVs for one day and re-derive that trade from scratch.

    Nothing cached is consulted: the manifest is re-read, every CALL file whose date range
    covers ``date`` is re-parsed from disk, and the entry and exit bars for the entry-minute
    ATM strike are located and differenced by hand.
    """
    from gate_b_common import cached_path, manifest_rows

    ds = sessions[date]
    K = ds.atm_strike(minute)
    frames, names = [], []
    for row in manifest_rows():
        if row.get("drv_option_type") != "CALL":
            continue
        if not (str(row["from_date"]) <= date <= str(row["to_date"])):
            continue
        f = cached_path(row)
        if not f.exists():
            continue
        df = pd.read_csv(f, usecols=["close", "strike", "datetime", "spot", "iv", "volume"])
        df = df[df["datetime"].astype(str).str.startswith(date)]
        df = df[np.isclose(df["strike"].astype(float), K)]
        if not df.empty:
            frames.append(df)
            names.append(f.name)
    if not frames:
        return {"date": date, "found": False, "strike": K}
    df = pd.concat(frames, ignore_index=True)
    dt = pd.to_datetime(df["datetime"])
    df["clock"] = dt.dt.strftime("%H:%M")
    df["minutes"] = dt.dt.hour * 60 + dt.dt.minute
    df = df[df["close"] > 0]
    # same de-duplication rule the panel uses: one row per minute, highest volume wins
    df = df.sort_values(["minutes", "volume"], ascending=[True, False]).drop_duplicates(
        "minutes", keep="first")

    entry = df[df["minutes"] == minute]
    exits = df[df["minutes"] <= C.END_MIN]
    if entry.empty or exits.empty:
        return {"date": date, "found": False, "strike": K,
                "raw_files": names, "reason": "entry or exit bar absent in the raw files"}
    ex = exits.sort_values("minutes").iloc[-1]
    t = ds.trade(minute)
    e_px = float(entry["close"].iloc[0])
    x_px = float(ex["close"])
    raw_ret = (x_px - e_px) / e_px * 100.0
    return {
        "date": date, "found": True, "raw_files_read": names, "strike": K,
        "strike_source": "round(spot at the entry minute / 50) * 50, re-picked at entry",
        "entry_clock": f"{minute//60:02d}:{minute%60:02d}",
        "raw_spot_at_entry": float(entry["spot"].iloc[0]),
        "panel_spot_at_entry": float(t["spot"]),
        "raw_entry_close": e_px, "panel_entry_px": float(t["entry_px"]),
        "raw_exit_clock": str(ex["clock"]), "panel_exit_minute": int(t["exit_minute"]),
        "raw_exit_close": x_px, "panel_exit_px": float(t["exit_px"]),
        "raw_return_pct": float(raw_ret), "panel_return_pct": float(t["ret"]),
        "raw_minus_panel_pp": float(raw_ret - t["ret"]),
        "match": bool(abs(raw_ret - t["ret"]) < 1e-6),
    }


# ============================================================ main
def main() -> None:
    pool, fires, controls = C.population()
    reproduction_guard(fires)
    sessions = C.build_sessions()
    panel = build_panel(sessions, pool)
    panel.to_csv(PANEL_CSV, index=False)

    is_fire = panel["is_fire"] == 1
    is_ctrl = panel["is_fire"] == 0
    all_days = panel["date"].notna()

    res: dict = {
        "population": {
            "pool_n": len(pool), "fires_n": len(fires), "controls_n": len(controls),
            "definition": ("non-expiry, gap-down, overnight VIX rise, gap fills after 09:17; "
                           "fires additionally sit in the mid (14-18%) opening-IV bucket"),
        },
        "grids": {
            "entry_cells": [c["name"] for c in cells()],
            "confirmations": list(CONFIRMATIONS),
            "n_e2_cells_per_population": len(cells()) * len(CONFIRMATIONS),
        },
    }
    res["E1_mid_iv_N33"] = e1(panel, "mid-IV Gate B (N=33)", is_fire, len(fires))
    res["E1_pooled_N120"] = e1(panel, "pooled VIX-rose gap-down fills (N=120)", all_days,
                               len(pool))
    res["E1_controls_N87"] = e1(panel, "controls, not Gate B (N=87)", is_ctrl, len(controls))

    res["E1_paired_mid_iv_N33"] = e1_paired(panel, is_fire, "mid-IV Gate B (N=33)")
    res["E1_paired_pooled_N120"] = e1_paired(panel, all_days, "pooled (N=120)")
    res["E1_paired_controls_N87"] = e1_paired(panel, is_ctrl, "controls (N=87)")
    res["E1_micro_shift_mid_iv"] = e1_micro_shift(sessions, fires, "mid-IV Gate B (N=33)")
    res["E1_micro_shift_controls"] = e1_micro_shift(sessions, controls, "controls (N=87)")
    res["E1_paired_placebo"] = e1_paired_placebo(panel)
    res["E1_stability_mid_iv"] = e1_stability(panel, is_fire, "mid-IV Gate B (N=33)")
    res["E1_stability_pooled"] = e1_stability(panel, all_days, "pooled (N=120)")
    res["E1_entry_price_decomposition_mid_iv"] = e1_entry_price_decomposition(sessions, fires)
    res["E1_entry_price_decomposition_controls"] = e1_entry_price_decomposition(
        sessions, controls)
    res["E1b_vol_overpayment_mid_iv"] = e1b(sessions, pool, lambda p: int(p["is_gate_b"]) == 1,
                                            "mid-IV Gate B (N=33)")
    res["E1b_vol_overpayment_pooled"] = e1b(sessions, pool, lambda p: True,
                                            "pooled (N=120)")

    fire_grid = e2(panel, is_fire, "mid-IV Gate B (N=33)")
    pooled_grid = e2(panel, all_days, "pooled (N=120)")
    ctrl_grid = e2(panel, is_ctrl, "controls (N=87)")
    res["E2_mid_iv_N33"] = fire_grid
    res["E2_pooled_N120"] = pooled_grid
    res["E4_controls_N87"] = ctrl_grid

    res["E3_drift_profile"] = e3(sessions, fires, controls)
    res["E4_placebo"] = e4(panel, sessions, pool, fire_grid, ctrl_grid)
    res["power"] = power(panel)
    res["verification"] = verification(sessions, panel, fires)
    ex = res["verification"]["strike_repick"]["largest_gap_example"]
    hc_date = ex["date"] if ex else fires[0]["date"]
    res["verification"]["hand_check_1200_entry"] = hand_check(
        sessions, hc_date, clock_to_minutes("12:00"))
    res["verification"]["hand_check_fill_entry"] = hand_check(
        sessions, hc_date, sessions[hc_date].fill_minute)

    RESULTS.write_text(json.dumps(res, indent=2, default=float))

    # ------------------------------------------------------------------ console report
    print("=" * 100)
    print("GATE B ENTRY-TIMING TEST -- real strike-tracked traded premiums, ATM re-picked "
          "at the entry minute")
    print("=" * 100)
    print(f"pool {len(pool)}  fires(mid-IV) {len(fires)}  controls {len(controls)}")
    for key in ("E1_mid_iv_N33", "E1_pooled_N120"):
        b = res[key]
        print(f"\nE1  {b['label']}   hold to 15:29 in every cell")
        for s in b["cells"]:
            print(f"  {s['cell']:<16} drop{s['n_dropped_fill_after_clock']:3d} "
                  f"unpx{s['n_unpriceable']:2d}  {fmt(s)}")
        print(f"  common sample across all cells: N={b['common_sample_n']}")
        for s in b["common_cells"]:
            print(f"    {s['cell']:<16} {fmt(s)}")
    for key in ("E1_paired_mid_iv_N33", "E1_paired_pooled_N120", "E1_paired_controls_N87"):
        b = res[key]
        print(f"\nE1 paired vs the fill-minute entry, SAME DAYS -- {b['label']}")
        for s_ in b["cells"]:
            if s_.get("n_paired", 0) < 5:
                continue
            print(f"  {s_['cell']:<16} n={s_['n_paired']:3d}  fill {s_['mean_fill_pct']:+7.2f}% "
                  f"-> late {s_['mean_late_pct']:+7.2f}%  diff {s_['mean_difference_pp']:+7.2f}pp "
                  f"(med {s_['median_difference_pp']:+6.2f})  better on {s_['share_improved_pct']:4.1f}% "
                  f"of days  p={s_['p_paired']:.4f} (Bonf {s_['p_paired_bonferroni']:.4f})"
                  f"  wilcoxon p={s_['p_wilcoxon']:.4f} (Bonf {s_['p_wilcoxon_bonferroni']:.4f})")
    for key in ("E1_micro_shift_mid_iv", "E1_micro_shift_controls"):
        print(f"\nE1 micro-shift diagnostic (NOT in the pre-declared grid) -- {res[key]['label']}")
        for r_ in res[key]["offsets"]:
            print(f"  fill+{r_['offset_minutes']:<2d} n={r_['n']:3d}  fill {r_['mean_fill_pct']:+7.2f}% "
                  f"-> {r_['mean_late_pct']:+7.2f}%  diff {r_['mean_difference_pp']:+6.2f}pp "
                  f"(med {r_['median_difference_pp']:+6.2f}) p={r_['p_paired']:.4f}  "
                  f"spot {r_['mean_spot_change_points']:+6.2f}pt p={r_['p_spot_vs_zero']:.4f}")
    print("\nE1 PLACEBO -- is the wait-after-the-fill gain a Gate-B property? "
          "(difference in differences vs controls)")
    for r_ in res["E1_paired_placebo"]["cells"]:
        print(f"  {r_['cell']:<16} fires {r_['fire_mean_diff_pp']:+7.2f}pp  "
              f"controls {r_['control_mean_diff_pp']:+7.2f}pp  DiD "
              f"{r_['difference_in_differences_pp']:+7.2f}pp  welch p={r_['welch_p']:.4f}  "
              f"perm p={r_['perm_p']:.4f}")
    for key in ("E1_entry_price_decomposition_mid_iv", "E1_entry_price_decomposition_controls"):
        print(f"\n{key}")
        for r_ in res[key]["offsets"]:
            print(f"  fill+{r_['offset_minutes']:<3d} n={r_['n']:3d}  spot {r_['mean_spot_change_points']:+7.2f}pt "
                  f"(med {r_['median_spot_change_points']:+6.2f}, p={r_['p_spot_vs_zero']:.4f})  "
                  f"ATM premium {r_['mean_atm_premium_change_pct']:+7.2f}%")
    for key in ("E1b_vol_overpayment_mid_iv", "E1b_vol_overpayment_pooled"):
        print(f"\nE1b implied vs realised volatility by entry clock -- {res[key]['label']}")
        for s in res[key]["cells"]:
            if not s.get("n"):
                continue
            print(f"  {s['cell']:<16} N={s['n']:3d} implied {s['mean_implied_pct']:5.2f}%  "
                  f"realised {s['mean_realised_pct']:5.2f}%  gap {s['mean_gap_pp']:+6.2f}pp  "
                  f"p={s['p_gap_vs_zero']:.4f}  held {s['mean_held_minutes']:5.1f}m")
    for key in ("E2_mid_iv_N33", "E2_pooled_N120", "E4_controls_N87"):
        b = res[key]
        print(f"\nE2/E4 grid -- {b['label']}: {b['n_cells_tested']} cells, "
              f"{b['n_positive_conditional_means']} with a positive conditional mean")
        print(f"       {b['n_beating_same_clock_unconditional']}/{b['n_cells_tested']} beat the "
              f"SAME-CLOCK unconditional benchmark; smallest p vs it "
              f"{b['min_p_vs_same_clock']:.4f} "
              f"(Bonferroni {b['min_p_vs_same_clock_bonferroni']:.3f}), "
              f"{b['n_significant_vs_same_clock_raw_5pct']} significant at a raw 5%")
        bd = b["best_by_delta_same_clock"]
        print(f"       best vs same-clock: {bd['cell']} / {bd['variant']} "
              f"D={bd['delta_same_clock_pp']:+.2f}pp p={bd['p_paired_vs_same_clock']:.4f}")
        top = sorted(b["grid"], key=lambda r: -r["conditional"]["mean"])[:8]
        for r in top:
            print(f"  {r['cell']:<14} {r['variant']:<20} N={r['n_cell']:3d} "
                  f"sel={r['n_selected']:3d} skip={r['skip_rate_pct']:5.1f}%  "
                  f"cond {r['conditional']['mean']:+7.2f}%  "
                  f"uncond@t {r['unconditional_same_clock']['mean']:+7.2f}%  "
                  f"D {r['delta_same_clock_pp']:+6.2f}pp p={r['p_paired_vs_same_clock']:.3f} "
                  f"| timing {r['component_timing_pp']:+6.2f} "
                  f"selection {r['component_selection_pp']:+6.2f}")
    print("\nE3 intraday drift profile, buckets entirely after the fill")
    for r in res["E3_drift_profile"]["buckets_entirely_after_fill"]:
        print(f"  {r['bucket']:<14} nF={r['n_fires']:3d} fire {r['mean_fire_points']:+7.2f}pt "
              f"({r['fire_points_per_min']:+.3f}/min)  nC={r['n_controls']:3d} "
              f"ctrl {r['mean_control_points']:+7.2f}pt  diff {r['diff_points']:+7.2f}pt  "
              f"perm p={r['perm_p']:.4f} (Bonf {r['perm_p_bonferroni']:.3f})")
    f2 = res["E3_drift_profile"]["fill_to_close_spot_move"]
    print(f"\n  fill-to-close SPOT move: fires {f2['fires']['mean_points']:+.2f}pt "
          f"(med {f2['fires']['median_points']:+.2f}, up on {f2['fires']['share_up_pct']:.1f}% "
          f"of days, p={f2['fires']['p_vs_zero']:.4f}); controls "
          f"{f2['controls']['mean_points']:+.2f}pt (med {f2['controls']['median_points']:+.2f}, "
          f"p={f2['controls']['p_vs_zero']:.4f}); difference "
          f"{f2['difference_points']:+.2f}pt welch p={f2['welch_p']:.4f}")
    cm = res["E3_drift_profile"]["cumulative_signed_move_from_fill"]
    print(f"\n  cumulative mean signed spot move FROM THE FILL, common sample "
          f"(fires N={cm['n_fires']}, controls N={cm['n_controls']}):")
    for r in cm["rows"]:
        print(f"    {r['clock']}  fires {r['fires_cum_points']:+8.2f}pt   "
              f"controls {r['controls_cum_points']:+8.2f}pt")
    print("\n  post-fill SPOT drift by elapsed horizon (option-free)")
    for r in res["E3_drift_profile"]["post_fill_spot_drift"]:
        print(f"    +{r['horizon_minutes']:<4d}m  fires n={r['n_fires']:3d} "
              f"{r['mean_fire_points']:+7.2f}pt (med {r['median_fire_points']:+6.2f}, "
              f"p={r['p_fire_vs_zero']:.4f})  controls n={r['n_controls']:3d} "
              f"{r['mean_control_points']:+7.2f}pt  diff {r['diff_points']:+7.2f}pt "
              f"perm p={r['perm_p']:.4f}")
    print("\n  median share of the whole fill-to-close move achieved by "
          f"(common sample, N={res['E3_drift_profile']['n_fires_in_share_table']}):")
    for k, v in res["E3_drift_profile"]["median_pct_of_fill_to_close_move_achieved_by"].items():
        print(f"    {k}  {v:6.1f}%")
    pl = res["E4_placebo"]["shuffled_label_placebo"]
    print(f"\nE4 placebo: fires best-of-grid conditional mean "
          f"{res['E4_placebo']['fires_best']['conditional_mean']:+.2f}% "
          f"({res['E4_placebo']['fires_best']['cell']} / "
          f"{res['E4_placebo']['fires_best']['variant']})")
    print(f"   controls best-of-grid            "
          f"{res['E4_placebo']['controls_best']['conditional_mean']:+.2f}% "
          f"({res['E4_placebo']['controls_best']['cell']} / "
          f"{res['E4_placebo']['controls_best']['variant']})")
    print(f"   shuffled-label placebo: observed {pl['observed_best_of_grid_mean']:+.2f}%, "
          f"median draw {pl['placebo_median']:+.2f}%, empirical p={pl['empirical_p']:.4f}")
    pd_ = res["E4_placebo"]["shuffled_label_placebo_on_the_benchmark_disciplined_statistic"]
    print(f"   same statistic but benchmark-disciplined (cond - uncond at the SAME clock): "
          f"observed {pd_['observed']:+.2f}pp, median draw {pd_['placebo_median']:+.2f}pp, "
          f"empirical p={pd_['empirical_p']:.4f}")
    for key in ("E2_mid_iv_N33", "E2_pooled_N120", "E4_controls_N87"):
        b = res[key]
        k = b.get("best_by_delta_same_clock_excluding_never_trade_cells")
        print(f"   {b['label']}: {b['n_degenerate_never_trade_cells']} of "
              f"{b['n_cells_tested']} cells never trade at all; best cell that DOES trade "
              f"vs its same-clock benchmark: {k['cell']} / {k['variant']} "
              f"D={k['delta_same_clock_pp']:+.2f}pp p={k['p_paired_vs_same_clock']:.4f} "
              f"(trades on {k['n_selected']}/{k['n_cell']} days)")
    for key in ("E1_stability_mid_iv", "E1_stability_pooled"):
        b = res[key]
        print(f"\nE1 stability of the late-minus-fill gain -- {b['label']}")
        for r_ in b["cells"]:
            yrs = " ".join(f"{y}:{v:+.0f}" for y, v in sorted(r_["by_year_mean_pp"].items()))
            print(f"  {r_['cell']:<16} n={r_['n']:3d}  H1 {r_['first_half_mean_pp']:+7.2f}pp "
                  f"(n={r_['first_half_n']:3d})  H2 {r_['second_half_mean_pp']:+7.2f}pp "
                  f"(n={r_['second_half_n']:3d})  both+={str(r_['both_halves_positive']):5s} "
                  f"years+ {r_['years_positive']}/{r_['years_total']}  [{yrs}]")
    print("\nPOWER (alpha 5%, 80% power)")
    for r_ in res["power"]["cells"]:
        extra = (f"  observed {r_['observed_mean_pp']:+.2f}pp"
                 if "observed_mean_pp" in r_ else "")
        print(f"  {r_['population']:<14} {r_['cell']:<24} n={r_['n']:3d} sd={r_['sd_pct']:6.2f} "
              f"min detectable {r_['min_detectable_mean_pct_at_80pct_power']:6.2f}pp{extra}")
    v = res["verification"]
    print("\nVERIFICATION")
    sr = v["strike_repick"]
    print(f"  ATM re-pick: {sr['of_which_1200_strike_differs_from_fill_strike']}/"
          f"{sr['fires_with_a_1200_entry']} fires have a 12:00 strike different from the "
          f"fill strike ({sr['share_pct']:.1f}%)")
    if sr["largest_gap_example"]:
        e = sr["largest_gap_example"]
        print(f"    worked example {e['date']}: fill {e['fill_clock']} spot "
              f"{e['spot_at_fill']:.1f} -> K {e['strike_at_fill']:.0f}; "
              f"12:00 spot {e['spot_at_1200']:.1f} -> K {e['strike_at_1200']:.0f} "
              f"({e['strike_gap_points']:+.0f})")
    br = v["baseline_reproduction"]
    print(f"  baseline reproduction: published {br['published_mean_pct']}% vs this pipeline "
          f"{br['this_pipeline_mean_pct']:.2f}%, max per-day diff "
          f"{br['max_abs_per_day_difference_pp']:.2e}pp over {br['days_compared']} days")
    for tag in ("hand_check_fill_entry", "hand_check_1200_entry"):
        hc = v[tag]
        print(f"  {tag} {hc['date']} {hc.get('entry_clock')} K={hc.get('strike'):.0f}: raw CSV "
              f"{hc.get('raw_entry_close')} -> {hc.get('raw_exit_close')} "
              f"({hc.get('raw_exit_clock')}) = {hc.get('raw_return_pct', float('nan')):+.4f}%, "
              f"panel {hc.get('panel_return_pct', float('nan')):+.4f}%, "
              f"match={hc.get('match')}")
    print(f"\nwrote {RESULTS} and {PANEL_CSV}")


if __name__ == "__main__":
    main()
