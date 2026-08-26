#!/usr/bin/env python3
"""Does the published 84.8% Gate-B hit rate actually forecast anything?

New module.  It does not modify, and is not imported by, any pre-existing script.

The "reversed" label that produces the 84.8% figure is defined on the 09:18-09:45 target
window: it is true when the order of the extremes in that window is the opposite of the
order in the 09:15-09:17 window.  The Gate-B entry, however, is the gap fill, which can
occur at any minute after 09:17 -- in this sample as late as 14:04.

For a fire that occurs AFTER 09:45 the labelled outcome has already been fully determined
before the trade is entered.  For those days "P(reversed | gap fills) = 84.8%" is not a
forecast of anything; it is a statement about the past.  This module measures how much of
the published statistic is in that condition, and re-computes the hit rate separately for
fires that are genuinely forward-looking and fires that are not.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from gate_b_common import clock_to_minutes, gate_b_subset, reproduction_guard, rule_returns
from gate_b_full_paths import load_full_paths

TARGET_END = "09:45"
BUCKETS = ("low_<14", "middle_14_18", "high_>18")


def split_report(fires: list[dict], label: str) -> None:
    limit = clock_to_minutes(TARGET_END)
    early = [p for p in fires if p["entry_minute"] <= limit]
    late = [p for p in fires if p["entry_minute"] > limit]
    print(f"\n{label}  (N = {len(fires)})")
    hdr = (f"    {'entry':<34} {'N':>4} {'reversed':>9} {'hit rate':>9} {'binom p':>9} "
           f"{'real mean':>11} {'p vs 0':>8}")
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))
    for name, sub in (
        (f"at or before {TARGET_END} (forward-looking)", early),
        (f"after {TARGET_END} (outcome already known)", late),
        ("all fires", fires),
    ):
        if not sub:
            continue
        rev = sum(p["reversed"] for p in sub)
        pb = stats.binomtest(rev, len(sub), 0.5).pvalue
        r = rule_returns(sub, "real_prices")
        r = r[np.isfinite(r)]
        p0 = stats.ttest_1samp(r, 0.0).pvalue if len(r) > 2 else np.nan
        print(f"    {name:<34} {len(sub):>4} {rev:>9} {rev/len(sub)*100:>8.1f}% "
              f"{pb:>9.4f} {r.mean():>+10.2f}% {p0:>8.4f}")


def main() -> None:
    paths = load_full_paths()
    gate = gate_b_subset(paths)
    reproduction_guard(gate)
    fires = [p for p in paths if p["vix_rose"] == 1]

    print("=" * 100)
    print("AUDIT: how much of the 84.8% Gate-B hit rate is a forecast, and how much is hindsight?")
    print("=" * 100)
    print(f"The 'reversed' label is settled at {TARGET_END}.  Entry is the gap fill, whenever it")
    print("happens.  A fire after that clock cannot be forecasting its own label.")

    split_report(gate, "PUBLISHED GATE B (mid opening-IV bucket)")
    for bucket in BUCKETS:
        split_report([p for p in fires if p["iv_bucket"] == bucket], f"bucket = {bucket}")
    split_report(fires, "POOLED (all opening-IV buckets)")

    print("\n" + "-" * 100)
    print("Relationship between the label and the money, on real traded premiums")
    print("-" * 100)
    for name, sub in (("mid-IV fires", gate), ("all fires", fires)):
        rev = [p for p in sub if p["reversed"]]
        cont = [p for p in sub if not p["reversed"]]
        a = rule_returns(rev, "real_prices"); a = a[np.isfinite(a)]
        b = rule_returns(cont, "real_prices"); b = b[np.isfinite(b)]
        t, p = stats.ttest_ind(a, b, equal_var=False)
        print(f"  {name:<14} reversed N={len(a):>3} mean {a.mean():+7.2f}%  |  "
              f"continued N={len(b):>3} mean {b.mean():+7.2f}%  |  Welch p={p:.4f}")
    print("\n  A label that separates the path shape but not the P&L is not a trading signal.")


if __name__ == "__main__":
    main()
