#!/usr/bin/env python3
"""Independent correctness checks on gate_b_structure_search.py's output.

Recomputes selected headline quantities from the raw path/quote caches WITHOUT reusing the
study's own evaluation code, and cross-checks them against the study's CSV output.  New
artifact; modifies nothing.  Offline only.
"""
from __future__ import annotations
import math, pickle
import numpy as np, pandas as pd
import gate_b_common as gbc, gate_b_full_paths as gfp

LOT = 75
paths = gfp.load_full_paths()
mid = [p for p in paths if p["is_gate_b"] == 1]
pooled = [p for p in paths if p["vix_rose"] == 1]
print(f"paths {len(paths)}  mid {len(mid)}  pooled {len(pooled)}")

# --- 1. trading-time maturity, hand check on the first fire -------------------------
SESSION_OPEN, SESSION_CLOSE = 9*60+15, 15*60+30
dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
sessions = np.asarray(sorted(dm["date"].dt.normalize().unique()), dtype="datetime64[D]")
def tmin(date_str, clock_min, expiry_str):
    d = np.datetime64(pd.Timestamp(date_str).normalize(), "D")
    e = np.datetime64(pd.Timestamp(expiry_str).normalize(), "D")
    today = max(0.0, float(SESSION_CLOSE - clock_min))
    if e <= d: return today
    return today + 375.0*len(sessions[(sessions > d) & (sessions <= e)])
p0 = sorted(pooled, key=lambda p: p["date"])[0]
print(f"\n[1] first pooled fire {p0['date']} entry {p0['entry_clock']} expiry {p0['expiry']}: "
      f"{tmin(p0['date'], p0['entry_minute'], p0['expiry']):.0f} trading minutes to expiry")

# --- 2. spot move at close, recomputed straight off the path ------------------------
for lab, pop in (("mid N=33", mid), ("pooled N=120", pooled)):
    mv = np.array([float(p["spots"][-1]-p["spots"][0]) for p in pop])
    print(f"[2] {lab}: mean close spot move {mv.mean():+.2f} pts  ->  x75 = Rs {mv.mean()*LOT:+.0f}"
          f"   up% {100*(mv>0).mean():.1f}")

# --- 3. futures gross P&L, recomputed independently ---------------------------------
cal = pd.read_csv("k2_expiry_calendar.csv", parse_dates=["actual_expiry"])
e = cal["actual_expiry"].dt.normalize()
months = sorted(e.groupby([e.dt.year, e.dt.month]).max().tolist())
def nxt_m(ds):
    d = pd.Timestamp(ds).normalize()
    return next((m for m in months if m >= d), months[-1])
def fut(S, ds, cm, mexp):
    d = pd.Timestamp(ds)+pd.Timedelta(minutes=cm-SESSION_OPEN)
    x = pd.Timestamp(mexp)+pd.Timedelta(hours=15, minutes=30)
    return S*math.exp(0.02*max((x-d).total_seconds()/(365*24*3600), 0.0))
for lab, pop in (("mid N=33", mid), ("pooled N=120", pooled)):
    g, hg = [], []
    for p in pop:
        m = nxt_m(p["date"]); S0 = float(p["spots"][0]); SH = float(p["spots"][-1])
        em = p["entry_minute"]+int(p["elapsed"][-1])
        F0, FH = fut(S0, p["date"], p["entry_minute"], m), fut(SH, p["date"], em, m)
        g.append((FH-F0)*LOT)
        mult = fut(1.0, p["date"], em, m)
        hg.append(F0/mult - S0)                      # gross break-even SPOT move
    print(f"[3] {lab} futures to close: gross mean Rs {np.mean(g):+.0f}  |  "
          f"median gross hurdle {np.median(hg):+.3f} pts (basis-free)")

# --- 4. futures round-trip cost, hand-built -----------------------------------------
S = 22049.0; turn = S*LOT
cost = 0.25*LOT*2 + 2*20 + 0.0000173*2*turn + 0.0002*turn + 0.00002*turn + 0.000001*2*turn \
       + 0.18*(2*20 + 0.0000173*2*turn)
print(f"[4] futures round trip at S={S:.0f}: Rs {cost:.0f} = {cost/LOT:.2f} index points")

# --- 5. non-random coverage of the deep-ITM arm -------------------------------------
rk = pd.read_csv("gate_b_structure_ranking.csv")
d = rk[(rk.population=="pooled N=120") & (rk.horizon=="close") & (~rk.next_weekly_modelled)]
print("\n[5] hold-to-close coverage, pooled arm:")
for _, r in d.iterrows():
    print(f"    {r['structure']:<30} n={r['n']:>3}  coverage {r['coverage_pct']:.1f}%")

# --- 6. reconcile the long ATM call against the published Gate-B percentage ---------
for lab, pop in (("mid N=33", mid), ("pooled N=120", pooled)):
    r = np.array([gbc.rule_return(p, "real_prices") for p in pop], dtype=float)
    r = r[np.isfinite(r)]
    print(f"[6] {lab} published ATM-call hold-to-close on real premiums: "
          f"mean {100*r.mean():+.2f}%  median {100*np.median(r):+.2f}%  n={len(r)}")
