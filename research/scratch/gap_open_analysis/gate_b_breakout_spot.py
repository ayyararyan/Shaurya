#!/usr/bin/env python3
"""Separating test: is the breakout folklore wrong, or is the OPTION the wrong instrument?

The threshold-breakout entry loses on real CALL premiums.  Two very different reasons are
possible and they have opposite implications:

  (a) the folklore is wrong -- spot does not trend after first exceeding yesterday's close
      by X, so there is nothing to capture in any instrument;
  (b) the folklore is right about SPOT, and the loss comes from paying up for the option
      after the move has already happened.

This measures the SPOT leg alone: points from the trigger minute to 15:29, no option, no
premium, no decay.  If (b) is true this is positive while the premium version is negative.

Offline. No broker, credential, network or order path. No tracked file modified.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from gate_b_full_paths import load_full_paths
from gate_b_entry_timing_common import (
    DaySession, session_spot, quote_book, LAST_ENTRY_MIN, clock_to_minutes,
)

PT_GRID = [0, 10, 20, 30, 40, 50, 75, 100]
FILL_FLOOR = clock_to_minutes("09:17")


def main() -> None:
    paths = load_full_paths()
    dates = {p["date"] for p in paths}
    spots = session_spot(dates)
    px, vol = quote_book(dates)
    sessions = {p["date"]: DaySession(p, spots[p["date"]], px.get(p["date"], {}), vol.get(p["date"], {}))
                for p in paths if p["date"] in spots}
    groups = {
        "VIX ROSE (no IV filter), N=120": {p["date"] for p in paths if int(p["vix_rose"]) == 1},
        "  mid-IV only (Gate B), N=33  ": {p["date"] for p in paths if int(p["is_gate_b"]) == 1},
        "PLACEBO VIX FELL, N=144       ": {p["date"] for p in paths if int(p["vix_rose"]) == 0},
    }
    print("SPOT points from the trigger minute to 15:29 (no option, no premium, no decay)\n")
    print(f"{'population':<32}{'X':>5}{'n':>6}{'mean':>9}{'median':>9}{'up%':>8}{'p':>8}")
    for tag, keep in groups.items():
        for X in PT_GRID:
            pts = []
            for d in keep:
                s = sessions.get(d)
                if s is None:
                    continue
                lvl = s.prior_close + X
                ok = (s.minutes > FILL_FLOOR) & (s.spot >= lvl)
                if not ok.any():
                    continue
                tm = int(s.minutes[np.argmax(ok)])
                if tm > LAST_ENTRY_MIN:
                    continue
                i = s.idx[tm]
                pts.append(float(s.spot[-1] - s.spot[i]))
            a = np.asarray(pts)
            if len(a) < 3:
                continue
            p = float(stats.ttest_1samp(a, 0.0).pvalue)
            print(f"{tag:<32}{X:>5}{len(a):>6}{a.mean():>+9.1f}{np.median(a):>+9.1f}"
                  f"{100.0*(a>0).mean():>8.1f}{p:>8.3f}")
        print()


if __name__ == "__main__":
    main()
