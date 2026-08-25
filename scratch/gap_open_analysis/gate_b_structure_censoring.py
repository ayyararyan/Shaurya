#!/usr/bin/env python3
"""Censoring audit for gate_b_structure_search.py.

New artifact.  Modifies nothing.  Offline only, no broker/credential/network/order path.

Why this exists
---------------
The local minute archive stores option files by RELATIVE strike, ATM-10 .. ATM+10 of the
RUNNING at-the-money.  A structure whose entry strike sits several strikes away from spot
therefore falls OUT of the hydrated band as soon as spot travels far enough, and the trade
becomes unpriceable at the exit.  That censoring is not random: it is triggered by exactly
the large favourable moves the study is trying to measure.  This script measures the bias
and bounds it by re-pricing only the missing legs with Black-Scholes at the leg's own entry
implied volatility and the trading-time maturity remaining, which is a MODEL fill and is
labelled as such everywhere it appears.
"""
from __future__ import annotations
import numpy as np, pandas as pd
import gate_b_full_paths as gfp
import gate_b_structure_search as G

sessions = G.session_dates(); months = G.monthly_expiries(); quotes = G.load_quotes()
paths = gfp.load_full_paths()
POPS = (("mid-IV N=33", [p for p in paths if p["is_gate_b"] == 1]),
        ("pooled N=120", [p for p in paths if p["vix_rose"] == 1]))
KEYS = [k for _, k in G.STRUCTURES if k != "futures"]
NAME = dict((k, n) for n, k in G.STRUCTURES)

rows = []
for lab, pop in POPS:
    for key in KEYS:
        tr_g, fl_g, fl_n, dS_ok, dS_bad = [], [], [], [], []
        for p in pop:
            m = G.next_monthly(p["date"], months)
            legs = G.build_structure(p, quotes, sessions, key, m)
            if legs is None:
                continue
            S0, SH = float(p["spots"][0]), float(p["spots"][-1])
            held = float(p["elapsed"][-1])
            T_H = G.trading_T(p["date"], p["entry_minute"] + int(held), p["expiry"], sessions)
            ent = [l.entry_px for l in legs]
            raw = [G.leg_exit_price(p, quotes, sessions, l, None, m) for l in legs]
            fill = [x if np.isfinite(x) else
                    G.bs_price(SH, l.strike, max(T_H, 1e-9), G.RISK_FREE_RATE, l.iv, l.kind)
                    for l, x in zip(legs, raw)]
            ev = G.structure_value(legs, ent)
            gf = (G.structure_value(legs, fill) - ev) * G.LOT_SIZE
            cf = G.structure_costs(legs, fill, False)
            fl_g.append(gf); fl_n.append(gf - cf)
            if all(np.isfinite(x) for x in raw):
                tr_g.append((G.structure_value(legs, raw) - ev) * G.LOT_SIZE)
                dS_ok.append(SH - S0)
            else:
                dS_bad.append(SH - S0)
        rows.append({
            "population": lab, "structure": NAME[key],
            "n_traded": len(tr_g), "n_censored": len(dS_bad),
            "traded_gross_mean_rs": float(np.mean(tr_g)) if tr_g else np.nan,
            "bsfill_gross_mean_rs": float(np.mean(fl_g)),
            "bsfill_net_mean_rs": float(np.mean(fl_n)),
            "bsfill_net_p": float(__import__("scipy.stats", fromlist=["x"]).ttest_1samp(fl_n, 0).pvalue),
            "bsfill_net_win_pct": float(np.mean(np.asarray(fl_n) > 0) * 100),
            "mean_dS_traded": float(np.mean(dS_ok)) if dS_ok else np.nan,
            "mean_dS_censored": float(np.mean(dS_bad)) if dS_bad else np.nan,
            "bias_rs": (float(np.mean(fl_g)) - float(np.mean(tr_g))) if tr_g else np.nan,
        })

df = pd.DataFrame(rows)
df.to_csv("gate_b_structure_censoring.csv", index=False)
pd.set_option("display.width", 220)
print("HOLD-TO-CLOSE ONLY.  'BS-filled' re-prices ONLY the censored legs, at that leg's own")
print("entry implied volatility and the trading-time maturity remaining.  Model, not tape.\n")
print(df.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
