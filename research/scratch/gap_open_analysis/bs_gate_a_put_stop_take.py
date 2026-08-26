#!/usr/bin/env python3
"""Gate A (expiry + VIX-rise continuation), PUT-side only: stop-loss / take-profit grid
layered on top of the existing gap-fill exit rule.

Baseline (gap-fill exit only, no stop/target): the fill-triggered exit rule restricted to
PUT-side trades (gap-down expiry+VIX-rise days) shows a promising but not-quite-significant
edge (N=55, mean +39.0%, median -13.4%, win_rate 38.2%, p=0.055) -- see bs_gate_a_pnl.py.
This script asks: does capping the downside (stop-loss) and locking in the upside
(take-profit) before the gap-fill/close exit improve on that baseline, and is the improvement
robust across the grid or a lucky best-cell pick?

Exit priority at each minute, in order: stop-loss hit -> take-profit hit -> gap-fill ->
(else) hold to close. All three checked against the same running BS premium path used in
bs_gate_a_pnl.py.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from analyze_still_water_spot import load_spot
from ml_gated_put_call import build_dataset
from bs_gap_fill_pnl import bs_call, RISK_FREE_RATE, STRIKE_STEP

ENTRY_CLOCK = "09:17"
STOP_LOSSES = [0.30, 0.50, 0.60]
TAKE_PROFITS = [0.50, 0.75, 1.00]


def bs_put(S, K, T, r, sigma):
    return bs_call(S, K, T, r, sigma) - S + K * np.exp(-r * T)


def build_put_paths():
    cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
    df = build_dataset()
    gate_a = df[(df["is_expiry_day"] == 1) & (df["vix_rose"] == 1)].copy().sort_values("date").reset_index(drop=True)
    gate_a["date_str"] = gate_a["date"].dt.strftime("%Y-%m-%d")
    gate_a = gate_a[gate_a["gap_dir"] == "down"].copy()  # PUT side only

    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    dm["date_str"] = dm["date"].dt.strftime("%Y-%m-%d")
    gate_a = gate_a.merge(dm[["date_str", "prior_session_1529_spot"]], on="date_str", how="left")

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")].copy()

    paths = []
    for _, day in gate_a.iterrows():
        d = day["date_str"]
        prior_close = day["prior_session_1529_spot"]
        opening_iv = day["opening_iv"] / 100.0
        path = spot[spot["date"] == d].sort_values("clock")
        if path.empty or pd.isna(prior_close):
            continue
        entry_row = path.loc[path["clock"] == ENTRY_CLOCK]
        if entry_row.empty:
            continue
        S0 = float(entry_row["spot"].iloc[0])
        K = round(S0 / STRIKE_STEP) * STRIKE_STEP
        expiry_dt = pd.Timestamp(f"{d} 15:30:00")
        entry_dt = pd.Timestamp(f"{d} {ENTRY_CLOCK}:00")
        T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)
        if T0 <= 0:
            continue
        C0 = bs_put(S0, K, T0, RISK_FREE_RATE, opening_iv)
        if C0 <= 0:
            continue

        rest = path[path["clock"] >= ENTRY_CLOCK].reset_index(drop=True)
        prices, clocks = [], []
        for _, r in rest.iterrows():
            t_dt = pd.Timestamp(f"{d} {r['clock']}:00")
            T = max((expiry_dt - t_dt).total_seconds() / (365.0 * 24 * 3600), 1e-6)
            prices.append(bs_put(float(r["spot"]), K, T, RISK_FREE_RATE, opening_iv))
            clocks.append(r["clock"])
        gap_fill_idx = None
        for i, r in enumerate(rest.itertuples()):
            if float(r.spot) >= prior_close:
                gap_fill_idx = i
                break
        paths.append({"date": d, "C0": C0, "prices": np.array(prices), "gap_fill_idx": gap_fill_idx})
    return paths


def rets_for_rule(paths, stop=None, target=None):
    rets = []
    for p in paths:
        C0 = p["C0"]
        prices = p["prices"]
        exit_i = len(prices) - 1  # default: hold to close
        for i, C in enumerate(prices):
            r = (C - C0) / C0
            if stop is not None and r <= -stop:
                exit_i = i
                break
            if target is not None and r >= target:
                exit_i = i
                break
            if p["gap_fill_idx"] is not None and i == p["gap_fill_idx"]:
                exit_i = i
                break
        rets.append((prices[exit_i] - C0) / C0 * 100)
    return np.array(rets)


def main():
    paths = build_put_paths()
    print(f"N Gate A PUT-side trades = {len(paths)}")
    print()

    base = rets_for_rule(paths)
    t, pv = stats.ttest_1samp(base, 0)
    print(f"Baseline (gap-fill exit only, no cap): N={len(base)} mean={base.mean():.1f}% "
          f"median={np.median(base):.1f}% win_rate={(base>0).mean()*100:.1f}% p={pv:.4f}")
    print()

    print(f"{'stop':>6} {'target':>7} {'mean':>8} {'median':>8} {'win_rate':>9} {'p':>8}")
    for sl in STOP_LOSSES:
        for tp in TAKE_PROFITS:
            r = rets_for_rule(paths, stop=sl, target=tp)
            t, pv = stats.ttest_1samp(r, 0)
            print(f"{-sl*100:5.0f}% {tp*100:6.0f}% {r.mean():7.1f}% {np.median(r):7.1f}% "
                  f"{(r>0).mean()*100:8.1f}% {pv:8.4f}")


if __name__ == "__main__":
    main()
