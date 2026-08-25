#!/usr/bin/env python3
"""Shuffled-label placebo for the expiry + VIX-up + gap-UP reversal cell surfaced by the
Gate C/D scan.

The gap-fill event does not depend on the VIX label, so the placebo permutes which of the
136 expiry gap-up days carry the observed VIX-rose label (53 of them), holds everything
else fixed -- expiry membership, gap direction, the fill machinery, the spot paths -- and
re-computes the same two statistics.  This is the same discipline used in
WALKFORWARD_GATE_A_VALIDATION.md and GATE_B_EXIT_CEILING_TEST.md.

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

SEED = 20260823
DRAWS = 5000


def main() -> None:
    df = build_dataset()
    df = df[df["vix_known_by_decision"].astype(str).str.lower() == "true"].copy()
    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    df = df.merge(dm[["date", "prior_session_1529_spot"]], on="date", how="left")

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")].copy()

    pop = df[(df["is_expiry_day"] == 1) & (df["gap_dir"] == "up")].copy()
    recs = []
    for _, day in pop.iterrows():
        d = day["date"].strftime("%Y-%m-%d")
        prior = day["prior_session_1529_spot"]
        if pd.isna(prior):
            continue
        path = spot[spot["date"] == d].sort_values("clock")
        after = path[path["clock"] > "09:17"].reset_index(drop=True)
        if after.empty:
            continue
        fill = after[after["spot"] <= prior]
        if fill.empty:
            continue
        recs.append({
            "vix_rose": int(day["vix_rose"]),
            "pts": float(fill.iloc[0]["spot"]) - float(after.iloc[-1]["spot"]),
        })
    r = pd.DataFrame(recs)
    n_label = int(r["vix_rose"].sum())
    print(f"expiry gap-up days with a fill: {len(r)}   carrying the VIX-rose label: {n_label}")

    obs = r[r["vix_rose"] == 1]["pts"].to_numpy()
    obs_win = float((obs > 0).mean())
    obs_mean = float(obs.mean())
    obs_tp = float(stats.ttest_1samp(obs, 0.0).pvalue)
    print(f"OBSERVED  win={100*obs_win:.1f}%  mean={obs_mean:+.2f} pts  t-p={obs_tp:.4f}\n")

    rng = np.random.default_rng(SEED)
    pts = r["pts"].to_numpy()
    idx = np.arange(len(pts))
    wins, means = np.empty(DRAWS), np.empty(DRAWS)
    for i in range(DRAWS):
        pick = rng.choice(idx, size=n_label, replace=False)
        s = pts[pick]
        wins[i] = (s > 0).mean()
        means[i] = s.mean()

    print(f"placebo win rate   median={100*np.median(wins):.1f}%  "
          f"95th pct={100*np.quantile(wins,0.95):.1f}%  "
          f"empirical p (>= observed) = {float((wins >= obs_win).mean()):.4f}")
    print(f"placebo mean pts   median={np.median(means):+.2f}  "
          f"95th pct={np.quantile(means,0.95):+.2f}  "
          f"empirical p (>= observed) = {float((means >= obs_mean).mean()):.4f}")

    comp = r[r["vix_rose"] == 0]["pts"].to_numpy()
    print(f"\ncomplement (expiry gap-up, VIX FELL = Gate C, filled): n={len(comp)}  "
          f"win={100*(comp>0).mean():.1f}%  mean={comp.mean():+.2f} pts")
    print(f"difference in means: {obs_mean - comp.mean():+.2f} pts, "
          f"Welch p={float(stats.ttest_ind(obs, comp, equal_var=False).pvalue):.4f}")


if __name__ == "__main__":
    main()
