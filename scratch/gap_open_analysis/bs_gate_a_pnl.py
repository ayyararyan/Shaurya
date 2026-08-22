#!/usr/bin/env python3
"""Black-Scholes theoretical option P&L for Gate A (expiry + VIX-rise continuation).

Trade definition: enter at 09:17 on ALL 108 Gate A days (no gap-fill gating needed to
enter -- Gate A's condition is already just is_expiry_day & vix_rose). Direction follows
today's own gap: buy CALL if gap up, PUT if gap down (continuation bet). The gap-fill
event is used here as an EXIT signal (not an entry signal, unlike Gate B) -- filling back
to prior close is evidence the continuation thesis has failed, per the earlier finding
(continuation success drops from 66.7% to 28.3% once the gap fills).

Tests, mirroring the Gate B methodology exactly:
1. Exit immediately when the gap fills, else hold to close ("fill-triggered exit").
2. Fixed-clock exits at 10:00 through close, no fill logic at all.
3. Immediate trailing stops (30/40/50/60%) for completeness / comparison to Gate B.
4. Hold-to-close-always baseline (ignore gap-fill entirely).
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from analyze_still_water_spot import load_spot
from ml_gated_put_call import build_dataset
from bs_gap_fill_pnl import bs_call, next_expiry, RISK_FREE_RATE, STRIKE_STEP

ENTRY_CLOCK = "09:17"
EXIT_CLOCKS = ["10:00", "10:30", "11:00", "12:00", "13:00", "14:00", "15:29"]


def bs_put(S, K, T, r, sigma):
    # put-call parity from the existing bs_call
    return bs_call(S, K, T, r, sigma) - S + K * np.exp(-r * T)


def price_of(option_type, S, K, T, r, sigma):
    return bs_call(S, K, T, r, sigma) if option_type == "CALL" else bs_put(S, K, T, r, sigma)


def main():
    cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
    expiry_dates = sorted(cal["actual_expiry"].dt.date.tolist())

    df = build_dataset()
    gate_a = df[(df["is_expiry_day"] == 1) & (df["vix_rose"] == 1)].copy().sort_values("date").reset_index(drop=True)
    gate_a["date_str"] = gate_a["date"].dt.strftime("%Y-%m-%d")

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
        gap_dir = day["gap_dir"]
        option_type = "CALL" if gap_dir == "up" else "PUT"
        path = spot[spot["date"] == d].sort_values("clock")
        if path.empty or pd.isna(prior_close):
            continue
        entry_row = path.loc[path["clock"] == ENTRY_CLOCK]
        if entry_row.empty:
            continue
        S0 = float(entry_row["spot"].iloc[0])
        K = round(S0 / STRIKE_STEP) * STRIKE_STEP
        # is expiry day itself -> expiry is TODAY, not next week's date
        expiry_dt = pd.Timestamp(f"{d} 15:30:00")
        entry_dt = pd.Timestamp(f"{d} {ENTRY_CLOCK}:00")
        T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)
        if T0 <= 0:
            continue
        C0 = price_of(option_type, S0, K, T0, RISK_FREE_RATE, opening_iv)
        if C0 <= 0:
            continue

        rest = path[path["clock"] >= ENTRY_CLOCK].reset_index(drop=True)
        prices, clocks, spots = [], [], []
        for _, r in rest.iterrows():
            t_dt = pd.Timestamp(f"{d} {r['clock']}:00")
            T = max((expiry_dt - t_dt).total_seconds() / (365.0 * 24 * 3600), 1e-6)
            prices.append(price_of(option_type, float(r["spot"]), K, T, RISK_FREE_RATE, opening_iv))
            clocks.append(r["clock"])
            spots.append(float(r["spot"]))
        gap_fill_clock = None
        for c, s in zip(clocks, spots):
            if (gap_dir == "down" and s >= prior_close) or (gap_dir == "up" and s <= prior_close):
                gap_fill_clock = c
                break
        paths.append({
            "date": d, "gap_dir": gap_dir, "option_type": option_type, "C0": C0,
            "prices": np.array(prices), "clocks": clocks, "gap_fill_clock": gap_fill_clock,
        })

    print(f"N Gate A trades = {len(paths)}")
    print()

    # 1) fill-triggered exit
    rets = []
    for p in paths:
        if p["gap_fill_clock"] is None:
            exit_p = p["prices"][-1]
        else:
            idx = p["clocks"].index(p["gap_fill_clock"])
            exit_p = p["prices"][idx]
        rets.append((exit_p - p["C0"]) / p["C0"] * 100)
    rets = np.array(rets)
    t, pv = stats.ttest_1samp(rets, 0)
    print(f"--- Exit immediately on gap-fill, else hold to close ---")
    print(f"N={len(rets)} mean={rets.mean():.2f}% median={np.median(rets):.2f}% "
          f"win_rate={(rets>0).mean()*100:.1f}% t={t:.2f} p={pv:.4f}")
    print()

    # 2) fixed-clock exits, ignoring gap-fill
    for ec in EXIT_CLOCKS:
        rets = []
        for p in paths:
            valid_idx = [i for i, c in enumerate(p["clocks"]) if c <= ec]
            if not valid_idx:
                continue
            exit_p = p["prices"][valid_idx[-1]]
            rets.append((exit_p - p["C0"]) / p["C0"] * 100)
        rets = np.array(rets)
        if len(rets) < 2:
            continue
        t, pv = stats.ttest_1samp(rets, 0)
        print(f"Fixed exit {ec}: N={len(rets)} mean={rets.mean():.2f}% median={np.median(rets):.2f}% "
              f"win_rate={(rets>0).mean()*100:.1f}% t={t:.2f} p={pv:.4f}")
    print()

    # 3) immediate trailing stops
    for stop in [0.30, 0.40, 0.50, 0.60]:
        rets = []
        for p in paths:
            peak = p["C0"]
            exit_p = p["prices"][-1]
            for C in p["prices"]:
                if C > peak:
                    peak = C
                if peak > 0 and (peak - C) / peak >= stop:
                    exit_p = C
                    break
            rets.append((exit_p - p["C0"]) / p["C0"] * 100)
        rets = np.array(rets)
        t, pv = stats.ttest_1samp(rets, 0)
        print(f"Trailing stop {stop*100:.0f}%: N={len(rets)} mean={rets.mean():.2f}% "
              f"median={np.median(rets):.2f}% win_rate={(rets>0).mean()*100:.1f}% t={t:.2f} p={pv:.4f}")
    print()

    # 4) hold to close always (ignore gap fill entirely)
    rets = np.array([(p["prices"][-1] - p["C0"]) / p["C0"] * 100 for p in paths])
    t, pv = stats.ttest_1samp(rets, 0)
    print(f"--- Hold to close always (ignore gap-fill) --- N={len(rets)} mean={rets.mean():.2f}% "
          f"median={np.median(rets):.2f}% win_rate={(rets>0).mean()*100:.1f}% t={t:.2f} p={pv:.4f}")

    # split by gap direction for the fill-triggered rule (rule 1) to check CALL vs PUT asymmetry
    print()
    print("--- Fill-triggered exit rule, split by option type ---")
    for opt in ["CALL", "PUT"]:
        rets = []
        for p in paths:
            if p["option_type"] != opt:
                continue
            if p["gap_fill_clock"] is None:
                exit_p = p["prices"][-1]
            else:
                idx = p["clocks"].index(p["gap_fill_clock"])
                exit_p = p["prices"][idx]
            rets.append((exit_p - p["C0"]) / p["C0"] * 100)
        rets = np.array(rets)
        if len(rets) < 2:
            continue
        t, pv = stats.ttest_1samp(rets, 0)
        print(f"{opt}: N={len(rets)} mean={rets.mean():.2f}% median={np.median(rets):.2f}% "
              f"win_rate={(rets>0).mean()*100:.1f}% t={t:.2f} p={pv:.4f}")


if __name__ == "__main__":
    main()
