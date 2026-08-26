#!/usr/bin/env python3
"""Gate B: what the spot path actually DOES after the gap fill, and whether the SECOND
crossing of yesterday's close is a better trigger than the first.

Aryan's hypothesis (2026-08-23): the first touch of yesterday's close is only the
classification event.  Price then falls back below the close, and it is the *second*
upward crossing that marks the real reversal.

Structure taxonomy for every day, measured from the fill minute onward:
  clean         spot never trades back below yesterday's close
  dip_recross   spot goes back below, then crosses UP through it again  <- the hypothesis
  dip_no_recross  spot goes back below and never returns

Trades are priced on REAL traded one-minute bar closes with the ATM strike RE-PICKED at the
entry minute (gate_b_entry_timing_common.DaySession.trade).  No Black-Scholes price enters
any return here.  Long ATM CALL, held to 15:29, exactly as every other Gate B P&L.

Three benchmarks, because "later is better" is already known (E1: fill+30 = +11.00pp,
p=0.0006) and would otherwise be mistaken for the second-cross event:
  1. entry at the first fill                     -- the incumbent
  2. entry at the second cross                   -- the hypothesis
  3. entry at first fill + median recross delay  -- same clock, WITHOUT the event
Benchmark 3 is the load-bearing one: it isolates the event from the delay.

Offline. No broker, credential, network or order path. No tracked file modified.
No gate armed, no live order.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from gate_b_entry_timing_common import build_sessions, LAST_ENTRY_MIN, END_MIN


def classify(s) -> dict:
    """Structure of one day's path after its fill minute."""
    i0 = s.idx.get(s.fill_minute)
    if i0 is None:
        return {}
    m = s.minutes[i0:]
    x = s.spot[i0:]
    pc = s.prior_close

    below = np.where(x < pc)[0]
    rec = {
        "date": s.date, "is_fire": s.is_fire, "iv_bucket": s.iv_bucket,
        "fill_minute": s.fill_minute,
        "pts_fill_to_close": float(x[-1] - x[0]),
        "n_up_crossings": int(np.sum((x[:-1] < pc) & (x[1:] >= pc))) + 1,
    }
    if below.size == 0:
        rec.update(kind="clean", rebreak_minute=-1, recross_minute=-1, recross_delay=np.nan,
                   depth_below=np.nan)
        return rec

    b = int(below[0])
    rec["rebreak_minute"] = int(m[b])
    rec["depth_below"] = float(pc - x[b:].min())
    up = np.where(x[b:] >= pc)[0]
    if up.size == 0:
        rec.update(kind="dip_no_recross", recross_minute=-1, recross_delay=np.nan)
        return rec
    r = b + int(up[0])
    rec.update(kind="dip_recross", recross_minute=int(m[r]),
               recross_delay=float(m[r] - s.fill_minute))
    return rec


def summarise(tag: str, d: pd.DataFrame) -> None:
    n = len(d)
    if n == 0:
        print(f"{tag:<28} (empty)")
        return
    parts = []
    for k in ("clean", "dip_recross", "dip_no_recross"):
        c = int((d["kind"] == k).sum())
        parts.append(f"{k}={100.0*c/n:5.1f}% ({c:3d})")
    print(f"{tag:<28} N={n:4d}  " + "  ".join(parts) +
          f"   median up-crossings={d['n_up_crossings'].median():.0f}")


def paired(tag: str, a: np.ndarray, b: np.ndarray) -> None:
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 3:
        print(f"  {tag:<46} n={len(a)} -- too few to test")
        return
    diff = b - a
    t = stats.ttest_rel(b, a).pvalue
    w = stats.wilcoxon(b, a).pvalue if len(a) >= 6 else float("nan")
    print(f"  {tag:<46} n={len(a):3d}  diff={diff.mean():+7.2f}pp  "
          f"median={np.median(diff):+7.2f}  better on {100.0*(diff>0).mean():5.1f}%  "
          f"t-p={t:.4f}  wilcoxon-p={w:.4f}")


def main() -> None:
    sessions = build_sessions()
    rows = [classify(s) for s in sessions.values()]
    df = pd.DataFrame([r for r in rows if r]).sort_values("date").reset_index(drop=True)

    print("=" * 118)
    print("1. WHAT HAPPENS AFTER THE FILL -- path structure")
    print("=" * 118)
    fires_mid = df[(df["is_fire"] == 1)]
    pooled = df[df["iv_bucket"].notna()]
    summarise("Gate B fires (mid-IV)", fires_mid)
    summarise("all non-expiry gap-down fills", pooled)
    summarise("  of which VIX rose", df[df["is_fire"] == 1])
    summarise("  controls (not a fire)", df[df["is_fire"] == 0])

    print("\nrecross delay, minutes from the fill (dip_recross days only):")
    for tag, d in (("fires (mid-IV)", fires_mid), ("all fills", pooled), ("controls", df[df["is_fire"] == 0])):
        g = d[d["kind"] == "dip_recross"]["recross_delay"]
        if len(g):
            print(f"  {tag:<20} n={len(g):3d}  median={g.median():6.1f}  mean={g.mean():6.1f}  "
                  f"p25={g.quantile(.25):6.1f}  p75={g.quantile(.75):6.1f}")
    print("\ndepth below yesterday's close before the recross (points):")
    for tag, d in (("fires (mid-IV)", fires_mid), ("all fills", pooled)):
        g = d[d["kind"] == "dip_recross"]["depth_below"]
        if len(g):
            print(f"  {tag:<20} n={len(g):3d}  median={g.median():6.1f}  mean={g.mean():6.1f}  max={g.max():6.1f}")

    print("\nspot points from the fill to 15:29, by structure:")
    for tag, d in (("fires (mid-IV)", fires_mid), ("all fills", pooled), ("controls", df[df["is_fire"] == 0])):
        line = [f"  {tag:<20}"]
        for k in ("clean", "dip_recross", "dip_no_recross"):
            g = d[d["kind"] == k]["pts_fill_to_close"]
            line.append(f"{k}: n={len(g):3d} mean={g.mean():+7.1f} median={g.median():+7.1f}" if len(g) else f"{k}: --")
        print("   ".join(line))

    print("\n" + "=" * 118)
    print("2. THE HYPOTHESIS -- enter at the SECOND crossing instead of the first")
    print("   real traded premiums, ATM re-picked at entry, long CALL held to 15:29")
    print("=" * 118)

    rec = df[df["kind"] == "dip_recross"].copy()
    delay_med = float(rec[rec["is_fire"] == 1]["recross_delay"].median())
    print(f"median recross delay used for the time-matched control: {delay_med:.0f} minutes\n")

    for tag, sub in (("Gate B fires (mid-IV)", rec[rec["is_fire"] == 1]),
                     ("all non-expiry gap-down fills", rec),
                     ("controls (not a fire)", rec[rec["is_fire"] == 0])):
        r_fill, r_cross, r_clock = [], [], []
        for _, row in sub.iterrows():
            s = sessions[row["date"]]
            t1 = s.trade(s.fill_minute)
            t2 = s.trade(int(row["recross_minute"]))
            t3 = s.trade(min(int(s.fill_minute + delay_med), LAST_ENTRY_MIN))
            r_fill.append(t1["ret"] if t1 else np.nan)
            r_cross.append(t2["ret"] if t2 else np.nan)
            r_clock.append(t3["ret"] if t3 else np.nan)
        a, b, c = map(lambda v: np.asarray(v, dtype=float), (r_fill, r_cross, r_clock))
        ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c)
        print(f"{tag}   (dip_recross days priceable on all three: {int(ok.sum())} of {len(sub)})")
        for name, v in (("entry at first fill", a), ("entry at SECOND cross", b),
                        (f"entry at fill+{delay_med:.0f}min (no event)", c)):
            w = v[ok]
            if len(w):
                p = stats.ttest_1samp(w, 0.0).pvalue
                print(f"    {name:<38} mean={w.mean():+7.2f}%  median={np.median(w):+7.2f}%  "
                      f"win={100.0*(w>0).mean():5.1f}%  p vs 0={p:.4f}")
        paired("second cross MINUS first fill", a[ok], b[ok])
        paired("second cross MINUS same-clock no-event", c[ok], b[ok])
        print()


if __name__ == "__main__":
    main()
