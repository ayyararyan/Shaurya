#!/usr/bin/env python3
"""Timing structure of the order-of-extremes reversal effect, mid-IV Gate B cell (N=56).

For each day, pulls the actual minute-by-minute spot path 09:15-09:45 and finds:
- clock time and level of the initial (09:15-09:17) high/low
- clock time and level of the target-window (09:18-09:45) high/low
- how many minutes elapse before each target-window extreme is reached
- the worst adverse move (in the direction the initial 2-minute signal implied) before
  the window's "real" extreme is reached -- i.e. how far/long you'd be underwater if you
  entered immediately at 09:17 in the naive continuation direction
"""
from __future__ import annotations

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
from analyze_still_water_spot import load_spot
from ml_gated_put_call import build_dataset

TARGET_START = "09:18"
TARGET_END = "09:45"
DECISION_CLOCK = "09:17"


def main() -> None:
    df = build_dataset()
    gate_b = df[(df["is_expiry_day"] == 0) & (df["gap_dir"] == "down") & (df["vix_rose"] == 1)].copy()
    mid = gate_b[gate_b["iv_bucket"] == "middle_14_18"].copy().sort_values("date").reset_index(drop=True)
    mid["date_str"] = mid["date"].dt.strftime("%Y-%m-%d")

    spot, _audit = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "09:45")].copy()

    rows = []
    for _, day in mid.iterrows():
        d = day["date_str"]
        path = spot[spot["date"] == d].sort_values("clock")
        if path.empty:
            continue
        p0 = path.loc[path["clock"] == DECISION_CLOCK, "spot"]
        if p0.empty:
            continue
        p0 = float(p0.iloc[0])

        window = path[(path["clock"] >= TARGET_START) & (path["clock"] <= TARGET_END)]
        if window.empty:
            continue
        hi_idx = window["spot"].idxmax()
        lo_idx = window["spot"].idxmin()
        hi_clock = window.loc[hi_idx, "clock"]
        lo_clock = window.loc[lo_idx, "clock"]
        hi_val = window.loc[hi_idx, "spot"]
        lo_val = window.loc[lo_idx, "spot"]
        hi_minute = int(hi_clock[3:5]) - int(TARGET_START[3:5]) if hi_clock[:2] == TARGET_START[:2] else (60 - int(TARGET_START[3:5]) + int(hi_clock[3:5]))
        lo_minute = int(lo_clock[3:5]) - int(TARGET_START[3:5]) if lo_clock[:2] == TARGET_START[:2] else (60 - int(TARGET_START[3:5]) + int(lo_clock[3:5]))

        # naive continuation direction implied by the initial 09:15-09:17 sequence
        cont_dir = "up" if day["initial_high_first"] == 1 else "down"
        # worst adverse excursion if you entered at p0 immediately in the continuation direction
        if cont_dir == "up":
            adverse = p0 - window["spot"].min()  # how far it drops below entry before (if ever) rallying
            favorable_extreme_clock = hi_clock
            favorable_extreme_minute = hi_minute
        else:
            adverse = window["spot"].max() - p0  # how far it rallies above entry before (if ever) dropping
            favorable_extreme_clock = lo_clock
            favorable_extreme_minute = lo_minute

        rows.append({
            "date": d,
            "reversed": bool(day["initial_high_first"] != day["target_high_first"]),
            "p0_close": p0,
            "target_high": hi_val, "target_high_clock": hi_clock, "target_high_minute": hi_minute,
            "target_low": lo_val, "target_low_clock": lo_clock, "target_low_minute": lo_minute,
            "cont_dir": cont_dir,
            "adverse_excursion_pts": adverse,
            "favorable_extreme_clock": favorable_extreme_clock,
            "favorable_extreme_minute": favorable_extreme_minute,
        })

    out = pd.DataFrame(rows)
    print(f"Reconstructed {len(out)} of {len(mid)} days from raw minute tape\n")

    rev = out[out["reversed"]]
    cont = out[~out["reversed"]]
    print(f"N reversed = {len(rev)}, N continued = {len(cont)}\n")

    print("=== REVERSED days: minute (into 09:18-09:45 window) the FAVORABLE (actual-direction) extreme is reached ===")
    print(rev["favorable_extreme_minute"].describe())
    print()
    print("=== REVERSED days: adverse excursion in points (how far price still moves in the ORIGINAL predicted "
          "direction before turning) ===")
    print(rev["adverse_excursion_pts"].describe())
    print()
    print("=== REVERSED days: clock time of the actual favorable extreme (histogram) ===")
    print(rev["favorable_extreme_clock"].value_counts().sort_index())
    print()
    print("=== CONTINUED (non-reversed) days: minute the favorable extreme is reached, for contrast ===")
    print(cont["favorable_extreme_minute"].describe())
    print()
    out.to_csv("reversal_timing_detail.csv", index=False)
    print("Saved full per-day detail to reversal_timing_detail.csv")


if __name__ == "__main__":
    main()
