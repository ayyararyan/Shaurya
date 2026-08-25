#!/usr/bin/env python3
"""(A) Gate-A PUT holding-horizon scan: does a short hard exit beat holding to close?

Population: expiry day AND overnight India-VIX rise AND gap down (the existing Gate-A PUT
population, N=55).  Entry 09:17.  Premium proxy: the same Black-Scholes construction as
``bs_gate_a_put_stop_take.py``.

Each horizon H is a pure censoring rule: enter at 09:17, exit at the last observed minute
at or before H minutes later.  NO stop-loss, NO take-profit, NO gap-fill exit.  Two
incumbent comparators are also reported: hold-to-close with no rules at all, and the
specification's gap-fill-triggered exit.

Every horizon is tested against zero AND paired against hold-to-close, because a rule that
beats zero but not the incumbent has not earned its place.  All ten horizons are nested on
the same 55 days, so they are ten correlated views of one sample, not ten independent tests.

Offline analysis only.  No broker, credential, network, or order path.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from gate_a_censoring_common import (
    HORIZONS,
    gate_a_subset,
    horizon_exit_index,
    load_paths,
    reproduction_guard,
)


def censored_returns(paths: list[dict], horizon: int | None) -> np.ndarray:
    out = []
    for p in paths:
        i = horizon_exit_index(p, horizon)
        out.append((p["prices"][i] - p["C0"]) / p["C0"] * 100.0)
    return np.asarray(out)


def gap_fill_returns(paths: list[dict]) -> np.ndarray:
    """The specification's incumbent exit: exit on gap-fill, else hold to close."""
    out = []
    for p in paths:
        i = p["gap_fill_idx"] if p["gap_fill_idx"] is not None else len(p["prices"]) - 1
        out.append((p["prices"][i] - p["C0"]) / p["C0"] * 100.0)
    return np.asarray(out)


def wilcoxon_p(values: np.ndarray) -> float:
    if len(values) == 0 or np.allclose(values, 0.0):
        return float("nan")
    try:
        return float(stats.wilcoxon(values, alternative="two-sided").pvalue)
    except ValueError:
        return float("nan")


def summarize(values: np.ndarray) -> dict:
    t, p = stats.ttest_1samp(values, 0.0)
    return {
        "n": len(values),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values, ddof=1)),
        "win": float(np.mean(values > 0) * 100.0),
        "t": float(t),
        "p": float(p),
        "wilcoxon": wilcoxon_p(values),
    }


def label(horizon: int | None) -> str:
    return "close" if horizon is None else f"{horizon}m"


def main() -> None:
    paths = load_paths()
    gate = gate_a_subset(paths)
    reproduction_guard(gate)

    hold_close = censored_returns(gate, None)
    gap_fill = gap_fill_returns(gate)

    print("Gate-A PUT holding-horizon scan (Black-Scholes proxy return, percentage points)")
    print(f"N = {len(gate)} trades, {gate[0]['date']} .. {gate[-1]['date']}")
    print("Pure censoring: no stop, no target, no gap-fill exit.\n")

    header = (
        f"{'H':>7} {'N':>4} {'mean':>9} {'median':>9} {'win%':>7} {'sd':>8} "
        f"{'t':>7} {'p vs 0':>9} {'Wilcox p':>9} {'vs close':>10} {'p vs close':>11}"
    )
    print(header)
    print("-" * len(header))
    rows = []
    for horizon in HORIZONS:
        r = censored_returns(gate, horizon)
        s = summarize(r)
        diff = r - hold_close
        if np.allclose(diff, 0.0):
            dp, dm = float("nan"), 0.0
        else:
            dm = float(np.mean(diff))
            dp = float(stats.ttest_1samp(diff, 0.0).pvalue)
        rows.append((horizon, s, dm, dp))
        print(
            f"{label(horizon):>7} {s['n']:>4} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% "
            f"{s['win']:>6.1f}% {s['std']:>7.1f} {s['t']:>+7.2f} {s['p']:>9.4f} "
            f"{s['wilcoxon']:>9.4f} {dm:>+9.2f}pp {dp:>11.4f}"
        )

    s = summarize(gap_fill)
    diff = gap_fill - hold_close
    print(
        f"{'gapfill':>7} {s['n']:>4} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% "
        f"{s['win']:>6.1f}% {s['std']:>7.1f} {s['t']:>+7.2f} {s['p']:>9.4f} "
        f"{s['wilcoxon']:>9.4f} {np.mean(diff):>+9.2f}pp "
        f"{stats.ttest_1samp(diff, 0.0).pvalue:>11.4f}"
    )
    print("\n('gapfill' is the module spec's incumbent exit: exit on gap-fill, else hold to close.)")

    # How much of the population has already gap-filled by each horizon?  Relevant because
    # the censored design deliberately discards the gap-fill exit.
    print("\nGap-fill timing within the censored windows:")
    fill_minutes = [
        p["elapsed"][p["gap_fill_idx"]] if p["gap_fill_idx"] is not None else None
        for p in gate
    ]
    n_fill = sum(m is not None for m in fill_minutes)
    print(f"  days whose gap ever fills after 09:17: {n_fill} of {len(gate)}")
    for horizon in (10, 15, 20, 25, 30, 40, 45, 60, 90):
        k = sum(m is not None and m <= horizon for m in fill_minutes)
        print(f"  filled within {horizon:>3d} minutes: {k:>3d} ({k/len(gate)*100:5.1f}% of all trades)")

    # Minute-by-minute mean/median profile, to see whether the decline is smooth.
    print("\nMean and median censored return by minute since entry (no rules):")
    print(f"{'minute':>7} {'mean':>9} {'median':>9} {'win%':>7}")
    for minute in range(0, 121, 5):
        r = censored_returns(gate, minute)
        print(f"{minute:>7} {np.mean(r):>+8.2f}% {np.median(r):>+8.2f}% {np.mean(r > 0)*100:>6.1f}%")

    # Chronological stability of the best short horizon versus hold-to-close.
    print("\nChronological quartile stability (mean censored return):")
    order = np.argsort([p["date"] for p in gate])
    quartiles = np.array_split(order, 4)
    print(f"{'H':>7} " + " ".join(f"{'Q'+str(i+1):>10}" for i in range(4)))
    for horizon in (15, 20, 25, 30, 45, None):
        r = censored_returns(gate, horizon)
        cells = " ".join(f"{np.mean(r[q]):>+9.2f}%" for q in quartiles)
        print(f"{label(horizon):>7} {cells}")


if __name__ == "__main__":
    main()
