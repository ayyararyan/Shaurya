#!/usr/bin/env python3
"""Gate C/D exploratory scan: VIX FELL overnight + gap UP, expiry vs non-expiry.

Reports the FULL 2x2x2 cell design (expiry x gap_dir x vix_rose) so the requested
cells are readable against Gate A and Gate B, and so the size of the search that
produced any result is visible.

Two distinct outcomes, deliberately kept apart -- the project has already shown they
diverge (Effect 1 CALL side: 81.8% hit rate, -0.4% expectancy):

  SEQ  order-of-extremes persistence: target_high_first == initial_high_first.
       This is the object Gate A's "66.7%" and Gate B's "84.8%" actually measure.
  RET  continuation on returns: sign(r_after_r2_to_0945) == gap direction.

Offline. No broker, credential, network or order path. No tracked file modified.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from ml_gated_put_call import build_dataset


def binom_p(k: int, n: int) -> float:
    if n == 0:
        return float("nan")
    return float(stats.binomtest(k, n, 0.5, alternative="two-sided").pvalue)


def cell_stats(g: pd.DataFrame) -> dict:
    n = len(g)
    seq_k = int((g["target_high_first"] == g["initial_high_first"]).sum())
    up = g["gap_dir"].eq("up")
    ret_k = int(((g["r_after_r2_to_0945"] > 0) == up).sum())
    return {
        "N": n,
        "SEQ_persist_%": 100.0 * seq_k / n if n else np.nan,
        "SEQ_p": binom_p(seq_k, n),
        "RET_cont_%": 100.0 * ret_k / n if n else np.nan,
        "RET_p": binom_p(ret_k, n),
        "mean_gap_%": 100.0 * g["gap"].mean(),
        "mean_r0945_%": 100.0 * g["r_after_r2_to_0945"].mean(),
    }


def main() -> None:
    df = build_dataset()
    df = df[df["vix_known_by_decision"].astype(str).str.lower() == "true"].copy()
    print(f"days with a VIX reading known by 09:17: {len(df)}\n")

    rows = []
    for exp in (1, 0):
        for gd in ("down", "up"):
            for vr in (1, 0):
                g = df[(df["is_expiry_day"] == exp) & (df["gap_dir"] == gd) & (df["vix_rose"] == vr)]
                if g.empty:
                    continue
                label = {
                    (1, "down", 1): "GATE A  expiry + VIX up + gap down",
                    (0, "down", 1): "GATE B* expiry-no + VIX up + gap down (all IV)",
                    (1, "up", 0): "GATE C  expiry + VIX DOWN + gap UP",
                    (0, "up", 0): "GATE D  expiry-no + VIX DOWN + gap UP",
                }.get((exp, gd, vr), f"        expiry={exp} vix_rose={vr} gap={gd}")
                rows.append({"cell": label, **cell_stats(g)})

    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200, "display.max_columns", 50)
    print(out.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))

    print("\n\nIV-bucket split of the two requested cells (Gate B needed mid-IV to work):")
    for exp, name in ((1, "GATE C  expiry + VIX DOWN + gap UP"), (0, "GATE D  non-expiry + VIX DOWN + gap UP")):
        g = df[(df["is_expiry_day"] == exp) & (df["gap_dir"] == "up") & (df["vix_rose"] == 0)]
        print(f"\n{name}   (N={len(g)})")
        sub = []
        for bucket, gb in g.groupby("iv_bucket"):
            sub.append({"iv_bucket": bucket, **cell_stats(gb)})
        print(pd.DataFrame(sub).to_string(index=False, float_format=lambda v: f"{v:8.3f}"))


if __name__ == "__main__":
    main()
