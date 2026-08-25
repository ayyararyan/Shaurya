#!/usr/bin/env python3
"""CONFIRMATORY re-run of the day-selection signal found in RANGE_FORECAST_TEST.md section 3.

PRE-REGISTERED BEFORE RUNNING (the whole point of this script):
  Direction : trade only when  signal = credit_pts - forecast_range  is in its LOWEST tercile.
  Threshold : EXPANDING quantile -- the 33.3rd percentile of the signal over PRIOR sessions only.
              No full-sample quantile anywhere.
  Headline  : IF(w=4), the 200-point butterfly, which FAILED in the holdout last time.
              IF(w=3) is the secondary.
  Windows   : (a) full walk-forward panel, (b) the untouched year from 2025-05-13, reported apart.
  Decision  : the signal is confirmed only if the holdout difference is positive AND clears its
              permutation placebo at 5% on the PRE-REGISTERED w=4 cell.

Also asks the mechanism question the last report flagged as unanswered: is the signal really about
the SMILE (wings expensive relative to the ATM), rather than about the range forecast at all?

Exploratory.  No gate change, no gate armed, no broker or order path.
"""
from __future__ import annotations
import json, pickle, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

src = open("range_forecast_test.py").read().replace('if __name__ == "__main__":\n    main()', '')
rf = type(sys)("rf"); exec(compile(src, "rf", "exec"), rf.__dict__)

SEED = 20260823
N_PERM = 5000
TEST_START = rf.TEST_START
COST_BAR_RS = 160.0
LOT = 75


def expanding_quantile(x: pd.Series, q: float, min_obs: int = 120) -> pd.Series:
    """Quantile of PRIOR observations only.  Value at i uses x[:i], never x[i]."""
    out = np.full(len(x), np.nan)
    v = x.to_numpy(float)
    for i in range(min_obs, len(v)):
        out[i] = np.quantile(v[:i], q)
    return pd.Series(out, index=x.index)


def smile_features(dates: list[str], widths=(150.0, 200.0)) -> pd.DataFrame:
    """Wing-to-ATM implied-volatility ratio at 09:20, from the cached chain."""
    import nge_common as nc, vrp_forecast_common as vfc
    q = pickle.load(open("folklore_required_quotes_20260823.pkl", "rb"))["quotes"]
    e = q[q["clock"] == "09:20"]
    daily = nc.load_daily().set_index("date")
    sessions = sorted(daily.index.tolist())
    expiries = nc._expiry_dates()
    rows = []
    want = set(dates)
    for d, g in e.groupby("date"):
        if d not in want or d not in daily.index:
            continue
        S = float(g["spot"].iloc[0])
        ks = sorted(set(g[g["side"] == "CALL"]["strike"]) & set(g[g["side"] == "PUT"]["strike"]))
        if not ks:
            continue
        atm = float(min(ks, key=lambda k: abs(k - S)))
        exp = nc._next_expiry(d, expiries)
        if exp is None:
            continue
        T = nc.trading_sessions_between(d, exp, sessions) / nc.SESSIONS_PER_YEAR
        if T <= 0:
            continue
        px = {s_: dict(zip(gg["strike"].astype(float), gg["close"].astype(float)))
              for s_, gg in g.groupby("side")}

        def iv(side, k):
            p = px.get(side, {}).get(k)
            return vfc.invert_iv(side, float(p), S, k, T) if p and p > 0 else np.nan

        ivc, ivp = iv("CALL", atm), iv("PUT", atm)
        atm_iv = np.nanmean([ivc, ivp])
        rec = {"date": d, "atm_iv_0920": atm_iv}
        for w in widths:
            wc, wp = iv("CALL", atm + w), iv("PUT", atm - w)
            rec[f"wing_iv_{int(w)}"] = np.nanmean([wc, wp])
            rec[f"smile_ratio_{int(w)}"] = np.nanmean([wc, wp]) / atm_iv if atm_iv > 0 else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def run_cell(df: pd.DataFrame, label: str, rng) -> dict:
    """df must carry date, signal, thr (expanding), pnl_rs, max_loss_rs."""
    d = df.dropna(subset=["thr"]).copy()
    d["sel"] = d["signal"] <= d["thr"]
    res = {"label": label, "n": int(len(d)), "n_selected": int(d["sel"].sum()),
           "selected_share": float(d["sel"].mean())}
    for win, sub in (("full walk-forward", d), ("untouched year", d[d["date"] >= TEST_START])):
        s = sub[sub["sel"]]["pnl_rs"].to_numpy()
        r = sub[~sub["sel"]]["pnl_rs"].to_numpy()
        if len(s) < 10 or len(r) < 10:
            continue
        obs = float(s.mean() - r.mean())
        sig = sub["signal"].to_numpy(); thr = sub["thr"].to_numpy(); pnl = sub["pnl_rs"].to_numpy()
        draws = np.empty(N_PERM)
        for i in range(N_PERM):
            sh = rng.permutation(sig)
            m = sh <= thr
            draws[i] = pnl[m].mean() - pnl[~m].mean() if 5 < m.sum() < len(m) - 5 else np.nan
        draws = draws[np.isfinite(draws)]
        ml = sub[sub["sel"]]["max_loss_rs"].to_numpy()
        res[win] = {
            "n": int(len(sub)), "n_selected": int(len(s)),
            "selected_mean_rs": float(s.mean()), "rest_mean_rs": float(r.mean()),
            "difference_rs": obs,
            "selected_median_rs": float(np.median(s)),
            "selected_win": float((s > 0).mean()),
            "selected_mean_ror_pct": float(100 * np.mean(s / ml)),
            "welch_p": float(stats.ttest_ind(s, r, equal_var=False).pvalue),
            "placebo_one_sided_p": float(np.mean(draws >= obs)),
            "placebo_two_sided_p": float(np.mean(np.abs(draws) >= abs(obs))),
            "clears_cost_bar_160": bool(s.mean() > COST_BAR_RS),
            "breakeven_half_spread_rs_per_unit_per_leg": float(s.mean() / (4 * 2 * LOT)),
        }
    return res


def main() -> None:
    rng = np.random.default_rng(SEED)
    panel = rf.build_panel()
    panel = panel[panel["is_expiry_day"] == 0].reset_index(drop=True)
    fc_rng = rf.walk_forward(panel, "rng", rf.BLOCKS["HAR + implied"])
    panel = panel.assign(fc=fc_rng.values)

    smile = smile_features(panel["date"].tolist())
    panel = panel.merge(smile, on="date", how="left")

    out = {"preregistered": {
        "direction": "LOWEST tercile of signal = credit_pts - forecast_range",
        "threshold": "expanding 33.3rd percentile of prior sessions only, min 120 obs",
        "headline_cell": "IF(w=4)", "secondary_cell": "IF(w=3)",
        "decision_rule": "confirmed iff holdout difference > 0 AND placebo two-sided p < 0.05 on w=4",
        "seed": SEED, "n_permutations": N_PERM},
        "cells": {}}

    for w in (4, 3):
        fly = rf.structure_pnl(w)
        d = panel.merge(fly, on="date", how="inner").dropna(subset=["fc"]).reset_index(drop=True)
        d["signal"] = d["credit_pts"] - d["fc"]
        d = d[d["date"] >= panel["date"].iloc[rf.MIN_TRAIN]].reset_index(drop=True)
        d["thr"] = expanding_quantile(d["signal"], 1 / 3)
        out["cells"][f"IF(w={w})"] = run_cell(d, f"IF(w={w})", rng)
        if w == 4:
            keep = d

    # ---- mechanism: is the signal a smile variable in disguise? ----
    m = keep.dropna(subset=["thr", "smile_ratio_200"]).copy()
    m["sel"] = m["signal"] <= m["thr"]
    mech = {"corr_signal_smile_ratio_200": float(m[["signal", "smile_ratio_200"]].corr().iloc[0, 1]),
            "corr_signal_atm_iv": float(m[["signal", "atm_iv_0920"]].corr().iloc[0, 1]),
            "corr_signal_n_sess": float(m[["signal", "n_sess"]].corr().iloc[0, 1]),
            "corr_signal_credit": float(m[["signal", "credit_pts"]].corr().iloc[0, 1]),
            "mean_smile_ratio_selected": float(m[m["sel"]]["smile_ratio_200"].mean()),
            "mean_smile_ratio_rest": float(m[~m["sel"]]["smile_ratio_200"].mean()),
            "mean_n_sess_selected": float(m[m["sel"]]["n_sess"].mean()),
            "mean_n_sess_rest": float(m[~m["sel"]]["n_sess"].mean()),
            "mean_atm_iv_selected": float(m[m["sel"]]["atm_iv_0920"].mean()),
            "mean_atm_iv_rest": float(m[~m["sel"]]["atm_iv_0920"].mean())}
    # horse race: sort by the smile ratio alone, and by days-to-expiry alone
    for nm, col, low_is_signal in (("smile_ratio_200", "smile_ratio_200", False),
                                   ("n_sess", "n_sess", False),
                                   ("atm_iv_0920", "atm_iv_0920", False)):
        thr = m[col].quantile(1 / 3)
        a = m[m[col] <= thr]["pnl_rs"].to_numpy(); b = m[m[col] > thr]["pnl_rs"].to_numpy()
        mech[f"sort_by_{nm}"] = {"low_third_mean_rs": float(a.mean()),
                                 "rest_mean_rs": float(b.mean()),
                                 "difference_rs": float(a.mean() - b.mean()),
                                 "welch_p": float(stats.ttest_ind(a, b, equal_var=False).pvalue)}
    # does the signal survive controlling for days-to-expiry?
    mech["within_n_sess"] = {}
    for ns, g in m.groupby("n_sess"):
        if len(g) < 60:
            continue
        s = g[g["sel"]]["pnl_rs"].to_numpy(); r = g[~g["sel"]]["pnl_rs"].to_numpy()
        if len(s) < 10 or len(r) < 10:
            continue
        mech["within_n_sess"][f"n_sess={int(ns)}"] = {
            "n": int(len(g)), "n_sel": int(len(s)),
            "selected_rs": float(s.mean()), "rest_rs": float(r.mean()),
            "difference_rs": float(s.mean() - r.mean()),
            "welch_p": float(stats.ttest_ind(s, r, equal_var=False).pvalue)}
    out["mechanism"] = mech

    Path("selection_confirm_results.json").write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
