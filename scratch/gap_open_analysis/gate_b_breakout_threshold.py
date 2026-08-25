#!/usr/bin/env python3
"""Gate B without the mid-IV filter: does a THRESHOLD BREAKOUT above yesterday's close
work as the entry trigger?

Aryan's specification (2026-08-23):
  1. drop the mid-IV (14-18) filter -- use the whole VIX-rose non-expiry gap-down population
  2. touching yesterday's close CLASSIFIES the day; it is not the breakout
  3. the real breakout is the FIRST time in the day that spot exceeds yesterday's close by a
     CERTAIN AMOUNT, and after that it "does not look back"
  4. that point can come much later in the day

This is a FIRST-PASSAGE entry rule and it has not been tested before.  E1 tested fixed
offsets from the fill; E2 tested confirmations evaluated at fixed clocks.  Neither entered
at the moment a level was first exceeded, and neither let the entry time float.

Thresholds are run in BOTH absolute points and basis points of yesterday's close, because
NIFTY roughly doubled over the sample and a fixed 30-point trigger is not the same trade in
2021 as in 2026.

Premiums: real traded one-minute bar closes, ATM strike RE-PICKED at the entry minute
(DaySession.trade).  No Black-Scholes price enters any return.  Long ATM CALL to 15:29.

Benchmarks, all on the SAME triggered days:
  fill            entry at the gap fill (the incumbent)
  trigger         entry at the first passage of close + X (the hypothesis)
  fill+d          entry at fill + the population median trigger delay -- same lateness,
                  NO event.  This is the load-bearing control; E1 already showed that
                  waiting alone is worth ~+11pp.
Plus an unconditional column: the mean over ALL classified days, scoring a day that never
triggers as 0 (no trade).  That is the strategy-level number.

Placebo: the identical rule on non-expiry gap-down fill days where VIX FELL.

Offline. No broker, credential, network or order path. No tracked file modified.
No gate armed, no live order.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
from gate_b_full_paths import load_full_paths
from gate_b_entry_timing_common import (
    DaySession, session_spot, quote_book, LAST_ENTRY_MIN, END_MIN, clock_to_minutes,
)

PT_GRID = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
BP_GRID = [0, 5, 10, 15, 20, 25, 30, 40, 50]          # basis points of yesterday's close
FILL_FLOOR = clock_to_minutes("09:17")


def build(paths: list[dict]) -> dict[str, DaySession]:
    dates = {p["date"] for p in paths}
    spots = session_spot(dates)
    px, vol = quote_book(dates)
    out = {}
    for p in paths:
        g = spots.get(p["date"])
        if g is None or g.empty:
            continue
        out[p["date"]] = DaySession(p, g, px.get(p["date"], {}), vol.get(p["date"], {}))
    return out


def trigger_minute(s: DaySession, level: float) -> int:
    """First minute strictly after 09:17 at which spot >= level."""
    m, x = s.minutes, s.spot
    ok = (m > FILL_FLOOR) & (x >= level)
    if not ok.any():
        return -1
    return int(m[np.argmax(ok)])


def lookback(s: DaySession, minute: int) -> tuple[float, bool]:
    """After entering at ``minute``: worst drawdown in spot, and whether it traded back
    below yesterday's close."""
    i = s.idx.get(minute)
    if i is None:
        return np.nan, False
    fwd = s.spot[i:]
    return float(fwd.min() - fwd[0]), bool((fwd < s.prior_close).any())


def run_grid(sessions: dict[str, DaySession], keep, grid, mode: str, tag: str) -> pd.DataFrame:
    days = [s for s in sessions.values() if keep(s)]
    rows = []
    for X in grid:
        recs = []
        for s in days:
            level = s.prior_close * (1.0 + X / 10000.0) if mode == "bp" else s.prior_close + X
            tm = trigger_minute(s, level)
            if tm < 0 or tm > LAST_ENTRY_MIN:
                recs.append({"trig": False})
                continue
            t_tr = s.trade(tm)
            t_fl = s.trade(s.fill_minute)
            dd, back = lookback(s, tm)
            recs.append({
                "trig": True, "date": s.date, "tm": tm,
                "delay": tm - s.fill_minute,
                "ret_trig": t_tr["ret"] if t_tr else np.nan,
                "ret_fill": t_fl["ret"] if t_fl else np.nan,
                "drawdown": dd, "went_back_below": back,
            })
        r = pd.DataFrame(recs)
        t = r[r["trig"]]
        n_all, n_t = len(r), len(t)
        if n_t == 0:
            continue
        dmed = float(t["delay"].median())
        # time-matched control: same lateness, no event
        ctrl = []
        for _, row in t.iterrows():
            s = sessions[row["date"]]
            tc = s.trade(min(int(s.fill_minute + dmed), LAST_ENTRY_MIN))
            ctrl.append(tc["ret"] if tc else np.nan)
        t = t.assign(ret_ctrl=ctrl)
        ok = t[["ret_trig", "ret_fill", "ret_ctrl"]].notna().all(axis=1)
        u = t[ok]
        if len(u) < 3:
            continue
        d_fill = u["ret_trig"] - u["ret_fill"]
        d_ctrl = u["ret_trig"] - u["ret_ctrl"]
        uncond = float(np.nansum(u["ret_trig"]) / n_all)
        rows.append({
            "X": X, "trig_%": 100.0 * n_t / n_all, "n_trig": n_t, "n_priced": len(u),
            "delay_med": dmed,
            "mean_%": u["ret_trig"].mean(), "median_%": u["ret_trig"].median(),
            "win_%": 100.0 * (u["ret_trig"] > 0).mean(),
            "p_vs_0": float(stats.ttest_1samp(u["ret_trig"], 0.0).pvalue),
            "vs_fill": d_fill.mean(), "p_fill": float(stats.ttest_rel(u["ret_trig"], u["ret_fill"]).pvalue),
            "vs_ctrl": d_ctrl.mean(), "p_ctrl": float(stats.ttest_rel(u["ret_trig"], u["ret_ctrl"]).pvalue),
            "uncond_%": uncond,
            "backbelow_%": 100.0 * u["went_back_below"].mean(),
            "drawdn_med": float(u["drawdown"].median()),
        })
    df = pd.DataFrame(rows)
    unit = "bp" if mode == "bp" else "pt"
    print(f"\n{tag}  ({len(days)} classified days)   threshold in {unit}")
    print(df.to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    return df


def main() -> None:
    paths = load_full_paths()
    print(f"non-expiry gap-down days that fill after 09:17: {len(paths)}")
    sessions = build(paths)
    vix_up = lambda s: int(s.is_fire) >= 0 and s.date in vix_up_dates
    vix_up_dates = {p["date"] for p in paths if int(p["vix_rose"]) == 1}
    vix_dn_dates = {p["date"] for p in paths if int(p["vix_rose"]) == 0}
    mid_dates = {p["date"] for p in paths if int(p["is_gate_b"]) == 1}
    print(f"  VIX rose: {len(vix_up_dates)}   VIX fell: {len(vix_dn_dates)}   "
          f"published Gate B (mid-IV): {len(mid_dates)}")
    print("\ncolumns: vs_fill = trigger minus entry-at-fill; vs_ctrl = trigger minus "
          "entry-at-fill+median-delay (SAME lateness, no event -- the load-bearing test)")
    print("         uncond_% = mean over ALL classified days, a non-triggering day scored 0")
    print("         backbelow_% = share that trade back below yesterday's close AFTER entry "
          "('does it look back?')")

    for mode, grid in (("pt", PT_GRID), ("bp", BP_GRID)):
        run_grid(sessions, lambda s: s.date in vix_up_dates, grid, mode,
                 "=== VIX ROSE, no IV filter (Aryan's population) ===")
        run_grid(sessions, lambda s: s.date in mid_dates, grid, mode,
                 "=== published Gate B, mid-IV only (reference) ===")
        run_grid(sessions, lambda s: s.date in vix_dn_dates, grid, mode,
                 "=== PLACEBO: VIX FELL (may be hydration-thinned) ===")


if __name__ == "__main__":
    main()
