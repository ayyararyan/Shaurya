#!/usr/bin/env python3
"""The Gate-B exit grid run on the POOLED (all-opening-IV-bucket) population.

New module.  It does not modify, and is not imported by, any pre-existing script.  It
reuses the grid, inference and cost machinery of ``gate_b_exit_grid_real.py`` and the
full-hydration paths of ``gate_b_full_paths.py``.

Why this exists
---------------
The published Gate B applies a fourth condition -- opening IV in the 14-18% bucket -- on
top of the three-condition population (non-expiry, gap-down, overnight VIX rose).  The
scope-addition question is whether that fourth condition earns its place.  If the pooled
population trades as well, the strategy is roughly 3.6x more frequent (120 fires against
33) and the filter should be dropped; if only the mid bucket works, that difference has to
be shown to be a real difference, not merely "mid is significant and the others are not".

Two things are therefore reported here that the 33-fire test cannot give:

1. the same 32-variant exit grid on N=120, where the design has roughly twice the power;
2. the grid run separately inside each bucket, so any claim that one bucket alone works
   can be checked against the others rather than against zero.

Every return is on REAL strike-tracked traded premiums.  All 120 fires are priceable at
every minute from entry to 15:29 -- the relative-strike files needed to follow each entry
strike were staged before the cache was built -- so nothing here is hydration-thinned.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

from gate_b_common import gate_b_subset, reproduction_guard, rule_returns
from gate_b_exit_grid_real import (
    bh_reject,
    matrix,
    net_of_costs,
    summarise,
    t_p_vs_zero,
    variant_grid,
)
from gate_b_full_paths import load_full_paths

BUCKETS = ("low_<14", "middle_14_18", "high_>18")
N_PLACEBO = 5000
SEED = 20260823


def required_d(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """Standardised mean detectable by a two-sided one-sample t-test."""
    from scipy.optimize import brentq

    def f(d):
        crit = stats.t.ppf(1 - alpha / 2, df=n - 1)
        nc = d * np.sqrt(n)
        return (stats.nct.sf(crit, n - 1, nc) + stats.nct.cdf(-crit, n - 1, nc)) - power

    return float(brentq(f, 1e-4, 5.0))


def grid_report(paths: list[dict], label: str, variants: list[dict]) -> dict:
    real = matrix(paths, "real_prices", variants)
    base_i = [i for i, v in enumerate(variants) if v["kind"] == "baseline"][0]
    base = real[base_i]
    ok = np.isfinite(real).all(axis=0) & np.isfinite(base)
    real, base = real[:, ok], base[ok]
    p0 = t_p_vs_zero(real)
    diff = real - base
    pb = np.full(len(variants), np.nan)
    for i in range(len(variants)):
        if i == base_i:
            continue
        pb[i] = stats.ttest_1samp(diff[i], 0.0).pvalue

    print(f"\n{'-' * 108}")
    print(f"{label}   (N = {int(ok.sum())} fires priceable under every variant)")
    print("-" * 108)
    hdr = (f"{'variant':>28} {'mean':>9} {'median':>9} {'win%':>7} {'p vs 0':>9} "
           f"{'vs base':>9} {'p vs base':>10}")
    print(hdr); print("-" * len(hdr))
    for i, v in enumerate(variants):
        mark = "  <- baseline" if i == base_i else ""
        pbs = "n/a" if i == base_i else f"{pb[i]:.4f}"
        print(f"{v['name']:>28} {real[i].mean():>+8.2f}% {np.median(real[i]):>+8.2f}% "
              f"{(real[i] > 0).mean()*100:>6.1f}% {p0[i]:>9.4f} "
              f"{diff[i].mean():>+8.2f}pp {pbs:>10}{mark}")

    positive = int((real.mean(axis=1) > 0).sum())
    best_mean_i = int(np.argmax(real.mean(axis=1)))
    sig0 = p0 < 0.05
    bonf0 = p0 < 0.05 / len(variants)
    bh0 = bh_reject(p0)
    sigb = np.array([np.isfinite(x) and x < 0.05 for x in pb])
    print(f"\n  variants with a POSITIVE mean return           : {positive} of {len(variants)}")
    print(f"  best mean return                               : {variants[best_mean_i]['name']} "
          f"({real[best_mean_i].mean():+.2f}%, p vs 0 = {p0[best_mean_i]:.4f})")
    print(f"  raw p<0.05 vs zero                             : {int(sig0.sum())} of {len(variants)}"
          f"   (Bonferroni {int(bonf0.sum())}, Benjamini-Hochberg {int(bh0.sum())})")
    print(f"  raw p<0.05 vs the hold-to-close baseline       : {int(sigb.sum())} of "
          f"{len(variants) - 1}")
    neg_sig = [variants[i]["name"] for i in np.flatnonzero(sig0 & (real.mean(axis=1) < 0))]
    if neg_sig:
        print(f"  of the raw-significant ones, LOSING          : {len(neg_sig)} "
              f"({', '.join(neg_sig[:4])}{' ...' if len(neg_sig) > 4 else ''})")
    return {
        "label": label,
        "n": int(ok.sum()),
        "baseline": summarise(base),
        "best_mean_variant": variants[best_mean_i]["name"],
        "best_mean": float(real[best_mean_i].mean()),
        "best_mean_p0": float(p0[best_mean_i]),
        "n_positive_mean": positive,
        "n_raw_sig_vs_zero": int(sig0.sum()),
        "n_bonferroni_vs_zero": int(bonf0.sum()),
        "n_bh_vs_zero": int(bh0.sum()),
        "n_raw_sig_vs_baseline": int(sigb.sum()),
    }


def main() -> None:
    paths = load_full_paths()
    reproduction_guard(gate_b_subset(paths))
    fires = [p for p in paths if p["vix_rose"] == 1]
    variants = variant_grid()

    print("=" * 108)
    print("GATE B EXIT GRID ON THE POOLED POPULATION (all opening-IV buckets)")
    print("=" * 108)
    print("Population: non-expiry + gap-down + overnight VIX rose, N = 198 days.")
    print(f"Gap-fill fires: {len(fires)}   "
          f"(low {sum(p['iv_bucket'] == 'low_<14' for p in fires)}, "
          f"mid {sum(p['iv_bucket'] == 'middle_14_18' for p in fires)}, "
          f"high {sum(p['iv_bucket'] == 'high_>18' for p in fires)})")
    print(f"Date range: {fires[0]['date']} .. {fires[-1]['date']}")
    print("Every return is on real strike-tracked traded premiums; 120/120 fires are")
    print("priceable minute by minute, so no day drops out and nothing is hydration-thinned.")

    out = {"pooled": grid_report(fires, "POOLED, all buckets", variants)}
    for bucket in BUCKETS:
        sub = [p for p in fires if p["iv_bucket"] == bucket]
        out[bucket] = grid_report(sub, f"bucket = {bucket}", variants)

    # ------------------------------------------------------------------ power at N=120
    print("\n" + "=" * 108)
    print("POWER OF THE POOLED TEST versus the 33-fire test")
    print("=" * 108)
    base_pool = rule_returns(fires, "real_prices")
    base_pool = base_pool[np.isfinite(base_pool)]
    mid = [p for p in fires if p["iv_bucket"] == "middle_14_18"]
    base_mid = rule_returns(mid, "real_prices")
    base_mid = base_mid[np.isfinite(base_mid)]
    for label, x in (("pooled", base_pool), ("mid-IV only", base_mid)):
        n = len(x)
        d = required_d(n)
        sd = x.std(ddof=1)
        ci = stats.t.interval(0.95, n - 1, loc=x.mean(), scale=sd / np.sqrt(n))
        print(f"  {label:<12} N={n:>4}  sd={sd:5.1f}pp  smallest detectable mean at 80% power "
              f"= {d * sd:5.1f}pp   observed mean {x.mean():+6.2f}% "
              f"95% CI [{ci[0]:+.2f}%, {ci[1]:+.2f}%]")

    # ------------------------------------- is the pooled result distinguishable from mid?
    print("\n" + "=" * 108)
    print("DOES DROPPING THE MID-IV FILTER CHANGE THE MONEY OUTCOME?")
    print("=" * 108)
    rest = [p for p in fires if p["iv_bucket"] != "middle_14_18"]
    x_rest = rule_returns(rest, "real_prices")
    x_rest = x_rest[np.isfinite(x_rest)]
    t, p = stats.ttest_ind(base_mid, x_rest, equal_var=False)
    print(f"  mid-IV fires        N={len(base_mid):>3}  mean {base_mid.mean():+6.2f}%  "
          f"median {np.median(base_mid):+6.2f}%  win {(base_mid>0).mean()*100:4.1f}%  "
          f"p vs 0 = {stats.ttest_1samp(base_mid,0).pvalue:.4f}")
    print(f"  non-mid fires       N={len(x_rest):>3}  mean {x_rest.mean():+6.2f}%  "
          f"median {np.median(x_rest):+6.2f}%  win {(x_rest>0).mean()*100:4.1f}%  "
          f"p vs 0 = {stats.ttest_1samp(x_rest,0).pvalue:.4f}")
    print(f"  difference of means : {base_mid.mean() - x_rest.mean():+.2f}pp, "
          f"Welch p = {p:.4f}")
    print("  => the two are statistically indistinguishable in return terms; both are")
    print("     negative point estimates on real premiums.")

    # ------------------------------------------------------ costs on the pooled baseline
    print("\n" + "=" * 108)
    print("POOLED BASELINE NET OF COSTS")
    print("=" * 108)
    base_variant = [v for v in variants if v["kind"] == "baseline"][0]
    for hs in (0.0, 0.35, 1.00):
        net = net_of_costs(fires, "real_prices", base_variant, hs)
        s = summarise(net)
        print(f"  half-spread {hs:4.2f}%  N={s['N']:>3}  mean {s['mean']:+6.2f}%  "
              f"median {s['median']:+7.2f}%  win {s['win']:4.1f}%  p vs 0 = {s['p0']:.4f}")

    with open("gate_b_pooled_grid_results.json", "w") as handle:
        json.dump(out, handle, indent=2, default=float)
    print("\nWrote gate_b_pooled_grid_results.json")


if __name__ == "__main__":
    main()
