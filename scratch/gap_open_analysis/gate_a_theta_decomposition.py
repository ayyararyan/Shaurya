#!/usr/bin/env python3
"""(B) Direct theta diagnostic for the Gate-A PUT trade.

Aryan's hypothesis is a claim about *why* the trade underperforms: expiry-day time decay
eats a directional edge that is only measured over 09:18-09:45.  This script tests the
claim rather than assuming it, by decomposing the Black-Scholes proxy return into
additive components.

With premium P(S, T) at spot S and time-to-expiry T (implied volatility held constant at
the opening value, as in the source construction), and entry values (S0, T0):

    total(H)      = [P(S_H, T_H) - P(S0, T0)] / P(S0, T0)
    spot_only(H)  = [P(S_H, T0)  - P(S0, T0)] / P(S0, T0)     <- underlying move alone
    decay_only(H) = [P(S0,  T_H) - P(S0, T0)] / P(S0, T0)     <- time decay alone
    cross(H)      = total(H) - spot_only(H) - decay_only(H)   <- interaction (gamma x theta)

Interpretation gate stated up front:
  * If spot_only holds up across horizons while total decays, the theta story is confirmed.
  * If spot_only ALSO decays with H, the directional edge itself dies and theta is secondary.

IDENTIFICATION LIMIT, stated explicitly: this proxy holds implied volatility constant at
the day's opening value.  An implied-volatility-change component therefore does NOT exist
in this decomposition and is **not identified** by it.  ``decay_only`` is pure calendar
time decay under a frozen volatility surface, not "decay plus IV change".  A real
expiry-day option would additionally gain or lose from the intraday volatility path, which
this construction cannot see.

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


def components(paths: list[dict], horizon: int | None) -> dict[str, np.ndarray]:
    total, spot_only, decay_only, spot_move = [], [], [], []
    for p in paths:
        i = horizon_exit_index(p, horizon)
        C0 = p["C0"]
        total.append((p["prices"][i] - C0) / C0 * 100.0)
        spot_only.append((p["prices_spot_only"][i] - C0) / C0 * 100.0)
        decay_only.append((p["prices_decay_only"][i] - C0) / C0 * 100.0)
        spot_move.append(p["spots"][i] - p["S0"])
    total = np.asarray(total)
    spot_only = np.asarray(spot_only)
    decay_only = np.asarray(decay_only)
    return {
        "total": total,
        "spot_only": spot_only,
        "decay_only": decay_only,
        "cross": total - spot_only - decay_only,
        "spot_move": np.asarray(spot_move),
    }


def label(horizon: int | None) -> str:
    return "close" if horizon is None else f"{horizon}m"


def main() -> None:
    paths = load_paths()
    gate = gate_a_subset(paths)
    reproduction_guard(gate)

    print("Gate-A PUT return decomposition (Black-Scholes proxy, constant opening IV)")
    print(f"N = {len(gate)} trades.  All figures are percentage points of entry premium,")
    print("except 'spot move' which is NIFTY index points (negative = favourable for a PUT).\n")

    header = (
        f"{'H':>7} {'total':>9} {'spot-only':>10} {'decay-only':>11} {'cross':>9} "
        f"{'spot move':>10} {'p spot-only':>12} {'p total':>9}"
    )
    print("MEANS")
    print(header)
    print("-" * len(header))
    for horizon in HORIZONS:
        c = components(gate, horizon)
        p_spot = stats.ttest_1samp(c["spot_only"], 0.0).pvalue
        p_tot = stats.ttest_1samp(c["total"], 0.0).pvalue
        print(
            f"{label(horizon):>7} {np.mean(c['total']):>+8.2f}% {np.mean(c['spot_only']):>+9.2f}% "
            f"{np.mean(c['decay_only']):>+10.2f}% {np.mean(c['cross']):>+8.2f}% "
            f"{np.mean(c['spot_move']):>+9.1f} {p_spot:>12.4f} {p_tot:>9.4f}"
        )

    print("\nMEDIANS")
    print(f"{'H':>7} {'total':>9} {'spot-only':>10} {'decay-only':>11} {'cross':>9} {'spot move':>10}")
    print("-" * 58)
    for horizon in HORIZONS:
        c = components(gate, horizon)
        print(
            f"{label(horizon):>7} {np.median(c['total']):>+8.2f}% {np.median(c['spot_only']):>+9.2f}% "
            f"{np.median(c['decay_only']):>+10.2f}% {np.median(c['cross']):>+8.2f}% "
            f"{np.median(c['spot_move']):>+9.1f}"
        )

    print("\nWIN RATES (share of trades with a positive component)")
    print(f"{'H':>7} {'total':>9} {'spot-only':>10} {'decay-only':>11}")
    print("-" * 40)
    for horizon in HORIZONS:
        c = components(gate, horizon)
        print(
            f"{label(horizon):>7} {np.mean(c['total'] > 0)*100:>8.1f}% "
            f"{np.mean(c['spot_only'] > 0)*100:>9.1f}% {np.mean(c['decay_only'] > 0)*100:>10.1f}%"
        )

    print("\nDECAY DRAG PER UNIT TIME (mean decay-only return, and its per-minute rate)")
    print(f"{'H':>7} {'decay-only':>11} {'per minute':>12}")
    print("-" * 32)
    for horizon in HORIZONS:
        c = components(gate, horizon)
        minutes = (
            float(np.mean([p["elapsed"][horizon_exit_index(p, horizon)] for p in gate]))
        )
        drag = float(np.mean(c["decay_only"]))
        rate = drag / minutes if minutes > 0 else float("nan")
        print(f"{label(horizon):>7} {drag:>+10.2f}% {rate:>+11.3f}%")

    print("\nDECOMPOSITION SANITY CHECK: does total = spot-only + decay-only + cross?")
    worst = 0.0
    for horizon in HORIZONS:
        c = components(gate, horizon)
        worst = max(worst, float(np.max(np.abs(c["total"] - c["spot_only"] - c["decay_only"] - c["cross"]))))
    print(f"  max absolute residual across all horizons and trades: {worst:.10f} pp (exact by construction)")

    print("\nHOW OFTEN IS THE SPOT-ONLY LEG STILL POSITIVE AT LONGER HORIZONS,")
    print("CONDITIONAL ON HAVING BEEN POSITIVE AT 20 MINUTES?")
    base = components(gate, 20)["spot_only"] > 0
    for horizon in (30, 45, 60, 90, None):
        c = components(gate, horizon)["spot_only"] > 0
        keep = float(np.mean(c[base]) * 100.0)
        print(f"  positive at 20m and still positive at {label(horizon):>5}: {keep:5.1f}% "
              f"(of {int(base.sum())} trades)")

    print("\nCOUNTERFACTUAL: what would the trade have earned with NO time decay at all?")
    print("(spot-only leg = the same directional bet priced with time to expiry frozen at 09:17)")
    print(f"{'H':>7} {'N':>4} {'mean':>9} {'median':>9} {'win%':>7} {'p vs 0':>9}")
    print("-" * 50)
    for horizon in HORIZONS:
        c = components(gate, horizon)["spot_only"]
        p = stats.ttest_1samp(c, 0.0).pvalue
        print(
            f"{label(horizon):>7} {len(c):>4} {np.mean(c):>+8.2f}% {np.median(c):>+8.2f}% "
            f"{np.mean(c > 0)*100:>6.1f}% {p:>9.4f}"
        )


if __name__ == "__main__":
    main()
