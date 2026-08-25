#!/usr/bin/env python3
"""Gate C/D stage 2: the REVERSAL reading, mirroring Gate B exactly.

Gate B: non-expiry, gap DOWN, VIX up, mid-IV; wait for the gap to FILL (spot returns UP
through yesterday's close) after 09:17, then go long.  The mirror for a gap-UP day is:
wait for spot to fall back THROUGH yesterday's close, then go short (buy a PUT).

Outcome definitions, all on SPOT (no option pricing, no Black-Scholes -- the project has
established that any premium claim needs strike-tracked traded quotes):

  fill_rate     share of days whose gap fills after 09:17
  cont_%        of filled days, share where 15:29 is BELOW the fill price
                (the reversal continues -- the trade works)
  pts_to_close  mean / median spot points from the fill to 15:29, signed so that
                POSITIVE = favourable to the short

Offline. No broker, credential, network or order path. No tracked file modified.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from ml_gated_put_call import build_dataset
from analyze_still_water_spot import load_spot

ENTRY_FLOOR = "09:17"
SESSION_END = "15:29"


def run(df: pd.DataFrame, spot: pd.DataFrame, label: str) -> dict:
    rows = []
    for _, day in df.iterrows():
        d = day["date"].strftime("%Y-%m-%d")
        prior = day["prior_close"]
        if pd.isna(prior):
            continue
        path = spot[spot["date"] == d].sort_values("clock")
        if path.empty:
            continue
        after = path[path["clock"] > ENTRY_FLOOR].reset_index(drop=True)
        if after.empty:
            continue
        # gap UP fills when spot falls back to/through yesterday's close
        fill = after[after["spot"] <= prior]
        filled = not fill.empty
        rec = {"date": d, "filled": filled}
        if filled:
            entry = fill.iloc[0]
            close_row = after.iloc[-1]
            rec["fill_clock"] = str(entry["clock"])
            rec["pts_to_close"] = float(entry["spot"]) - float(close_row["spot"])
        rows.append(rec)

    r = pd.DataFrame(rows)
    n = len(r)
    nf = int(r["filled"].sum())
    f = r[r["filled"]]
    k = int((f["pts_to_close"] > 0).sum()) if nf else 0
    p = float(stats.binomtest(k, nf, 0.5).pvalue) if nf else np.nan
    tp = float(stats.ttest_1samp(f["pts_to_close"], 0.0).pvalue) if nf > 1 else np.nan
    print(
        f"{label:<52} N={n:4d}  fill={100.0*nf/n:5.1f}% (n={nf:3d})  "
        f"cont={100.0*k/nf if nf else float('nan'):5.1f}% p={p:.3f}  "
        f"pts mean={f['pts_to_close'].mean():+7.2f} median={f['pts_to_close'].median():+7.2f} p={tp:.3f}"
    )
    return {"label": label, "N": n, "n_filled": nf}


def main() -> None:
    df = build_dataset()
    df = df[df["vix_known_by_decision"].astype(str).str.lower() == "true"].copy()
    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    df = df.merge(dm[["date", "prior_session_1529_spot"]], on="date", how="left")
    df = df.rename(columns={"prior_session_1529_spot": "prior_close"})

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= SESSION_END)].copy()

    print("REVERSAL reading on gap-UP days: fill = spot falls back through yesterday's close\n")
    up = df[df["gap_dir"] == "up"]
    run(up[(up["is_expiry_day"] == 1) & (up["vix_rose"] == 0)], spot, "GATE C  expiry + VIX DOWN + gap UP")
    run(up[(up["is_expiry_day"] == 0) & (up["vix_rose"] == 0)], spot, "GATE D  non-expiry + VIX DOWN + gap UP")
    print()
    run(up[(up["is_expiry_day"] == 1) & (up["vix_rose"] == 1)], spot, "  ctrl  expiry + VIX up + gap UP")
    run(up[(up["is_expiry_day"] == 0) & (up["vix_rose"] == 1)], spot, "  ctrl  non-expiry + VIX up + gap UP")
    run(up, spot, "  ctrl  ALL gap-UP days")

    print("\nGate C/D mid-IV only (the bucket Gate B needed):")
    midc = up[(up["is_expiry_day"] == 1) & (up["vix_rose"] == 0) & (up["iv_bucket"] == "middle_14_18")]
    midd = up[(up["is_expiry_day"] == 0) & (up["vix_rose"] == 0) & (up["iv_bucket"] == "middle_14_18")]
    run(midc, spot, "GATE C  mid-IV")
    run(midd, spot, "GATE D  mid-IV")


if __name__ == "__main__":
    main()
