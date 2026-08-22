#!/usr/bin/env python3
"""Extended-window version of analyze_reversal_timing.py.

Re-measures the mid-IV Gate B reversal-day moves using the FULL day's minute tape (not
cut off at 09:45), to check whether the late/boundary resolution found in the 09:45-bounded
version was a real late-but-finished move or a censoring artifact of stopping too early.

For each of the 39 "reversed" days, tracks the running extreme (in the direction that
matters for the naive-continuation trader) at successive checkpoints: 09:45, 10:00, 10:30,
11:00, 12:00, and end of day, plus the exact clock time/level where the running extreme
stops improving (a proxy for "when did the move actually finish").
"""
from __future__ import annotations

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
from analyze_still_water_spot import load_spot
from ml_gated_put_call import build_dataset

DECISION_CLOCK = "09:17"
CHECKPOINTS = ["09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "15:29"]


def running_extreme(path: pd.DataFrame, cont_dir: str, upto_clock: str) -> tuple[float, str]:
    seg = path[(path["clock"] > "09:17") & (path["clock"] <= upto_clock)]
    if seg.empty:
        return float("nan"), ""
    if cont_dir == "up":
        idx = seg["spot"].idxmax()
    else:
        idx = seg["spot"].idxmin()
    return float(seg.loc[idx, "spot"]), str(seg.loc[idx, "clock"])


def main() -> None:
    df = build_dataset()
    gate_b = df[(df["is_expiry_day"] == 0) & (df["gap_dir"] == "down") & (df["vix_rose"] == 1)].copy()
    mid = gate_b[gate_b["iv_bucket"] == "middle_14_18"].copy().sort_values("date").reset_index(drop=True)
    mid["date_str"] = mid["date"].dt.strftime("%Y-%m-%d")

    detail = pd.read_csv("reversal_timing_detail.csv")
    reversed_dates = detail[detail["reversed"] == True]["date"].tolist()

    spot, _audit = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")].copy()

    rows = []
    for d in reversed_dates:
        day = mid[mid["date_str"] == d].iloc[0]
        cont_dir = "up" if day["initial_high_first"] == 1 else "down"
        path = spot[spot["date"] == d].sort_values("clock")
        if path.empty:
            continue
        p0_series = path.loc[path["clock"] == DECISION_CLOCK, "spot"]
        if p0_series.empty:
            continue
        p0 = float(p0_series.iloc[0])

        row = {"date": d, "cont_dir": cont_dir, "p0": p0}
        prev_val = None
        for cp in CHECKPOINTS:
            val, clock = running_extreme(path, cont_dir, cp)
            row[f"extreme_at_{cp}"] = val
            row[f"extreme_clock_at_{cp}"] = clock
            move_pts = (val - p0) if cont_dir == "up" else (p0 - val)
            row[f"move_pts_at_{cp}"] = move_pts
            prev_val = val
        rows.append(row)

    out = pd.DataFrame(rows)
    print(f"Extended-window reconstruction for {len(out)} of {len(reversed_dates)} reversed days\n")

    print("=== Move magnitude (points, favorable direction) at each checkpoint, across all reversed days ===")
    for cp in CHECKPOINTS:
        col = f"move_pts_at_{cp}"
        print(f"{cp:>6}: mean={out[col].mean():7.2f}  median={out[col].median():7.2f}  "
              f"n_still_improving_after_prior_checkpoint=", end="")
        print()

    print("\n=== Did the running extreme keep improving from 09:45 -> end of day? ===")
    out["improved_0945_to_eod"] = out["move_pts_at_15:29"] > out["move_pts_at_09:45"] + 0.01
    print(out["improved_0945_to_eod"].value_counts())
    print(f"Mean additional move past 09:45 (points): {(out['move_pts_at_15:29'] - out['move_pts_at_09:45']).mean():.2f}")
    print(f"Median additional move past 09:45 (points): {(out['move_pts_at_15:29'] - out['move_pts_at_09:45']).median():.2f}")

    print("\n=== When (which checkpoint) does the running extreme LAST improve, per day? ===")
    def last_improving_checkpoint(r):
        vals = [r[f"move_pts_at_{cp}"] for cp in CHECKPOINTS]
        last_idx = 0
        for i in range(1, len(vals)):
            if vals[i] > vals[i - 1] + 0.01:
                last_idx = i
        return CHECKPOINTS[last_idx]
    out["last_improving_checkpoint"] = out.apply(last_improving_checkpoint, axis=1)
    print(out["last_improving_checkpoint"].value_counts())

    out.to_csv("reversal_timing_extended_detail.csv", index=False)
    print("\nSaved detail to reversal_timing_extended_detail.csv")
    print(out[["date", "cont_dir", "move_pts_at_09:45", "move_pts_at_10:00", "move_pts_at_10:30",
               "move_pts_at_11:00", "move_pts_at_12:00", "move_pts_at_15:29"]].to_string())


if __name__ == "__main__":
    main()
