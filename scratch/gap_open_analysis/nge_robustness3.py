#!/usr/bin/env python3
"""Third robustness pass: the leading ALTERNATIVE explanations for the sign finding.

New module.  Modifies nothing.

The finding under attack: regressing 5-minute return autocorrelation on gamma-weighted CALL
and PUT open interest with free coefficients gives b_call < 0 and b_put > 0, which reads as
"the US dealer-position convention holds in NIFTY weeklies".  Three ways that could be an
artefact rather than a dealer position:

A.  **The legs are a recent-return proxy.**  Call open interest builds above spot and put
    open interest below it, so the call/put split may simply encode where the market has
    recently been.  If so the result is return-conditioned mean reversion, a long-known
    effect, and has nothing to do with dealers.  Tested by controlling for prior 1-, 5- and
    22-session returns and prior realised volatility.
B.  **It is a moneyness-placement artefact.**  Gamma weights peak at the money; if the
    call and put open-interest DISTRIBUTIONS sit at systematically different distances from
    spot, the two legs differ in what part of the chain they sample rather than in position.
C.  **It is the total size of the option market, not its imbalance.**  Controlled already
    by the scale regressor; re-checked here with the two legs orthogonalised against their
    own sum.

Also recorded: the exact sign pattern in every population, so no reader has to infer it.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import nge_common as nc
import nge_stats as ns
import nge_path_quality as npq

warnings.filterwarnings("ignore", category=RuntimeWarning)

TAG = npq.PRIMARY
OUT = Path("nge_robustness3_results.json")


def add_history(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.sort_values("date").reset_index(drop=True).copy()
    p["session_ret_pct"] = p["signed_disp_pct"]
    for k in (1, 5, 22):
        p[f"prior_ret_{k}"] = p["session_ret_pct"].rolling(k).sum().shift(1)
    p["prior_rv_5"] = p["rv_pct"].rolling(5).mean().shift(1)
    p["prior_rho1_5"] = p["rho1"].rolling(5).mean().shift(1)
    p["prior_absdisp_5"] = p["abs_disp_pct"].rolling(5).mean().shift(1)
    return p


def leg_moneyness(snap: pd.DataFrame) -> pd.DataFrame:
    """Where does each side's open interest actually sit, relative to spot?"""
    op = snap[snap["clock"] == nc.SESSION_OPEN].copy()
    op["atm"] = (op["spot"] / nc.STRIKE_STEP).round() * nc.STRIKE_STEP
    op["off"] = ((op["strike"] - op["atm"]) / nc.STRIKE_STEP).round()
    op = op[op["off"].abs() <= 10]
    rows = []
    for (date, side), g in op.groupby(["date", "side"]):
        w = g["oi"].to_numpy(dtype=float)
        o = g["off"].to_numpy(dtype=float)
        if w.sum() <= 0:
            continue
        rows.append({"date": date, "side": side,
                     "oi_weighted_offset": float(np.sum(w * o) / w.sum()),
                     "oi_weighted_abs_offset": float(np.sum(w * np.abs(o)) / w.sum()),
                     "oi_total": float(w.sum())})
    d = pd.DataFrame(rows).pivot(index="date", columns="side",
                                 values=["oi_weighted_offset", "oi_weighted_abs_offset",
                                         "oi_total"])
    d.columns = [f"{a}_{b.lower()}" for a, b in d.columns]
    return d.reset_index()


def test_A_return_proxy(p: pd.DataFrame) -> dict:
    out: dict = {}
    C, P = p[f"zC_{TAG}"].to_numpy(), p[f"zP_{TAG}"].to_numpy()
    out["leg_correlations_with_history"] = {}
    for nm, v in (("zC", C), ("zP", P), ("zC_minus_zP", C - P),
                  ("gimb", p[f"gimb_{TAG}"].to_numpy())):
        d = {}
        for h in ("prior_ret_1", "prior_ret_5", "prior_ret_22", "prior_rv_5",
                  "prior_rho1_5", "prior_absdisp_5", "atm_iv_open"):
            x = p[h].to_numpy(dtype=float)
            m = np.isfinite(x) & np.isfinite(v)
            d[h] = {"pearson": float(np.corrcoef(x[m], v[m])[0, 1]),
                    "spearman": float(stats.spearmanr(x[m], v[m]).statistic)}
        out["leg_correlations_with_history"][nm] = d

    ctrl_sets = {
        "none": [],
        "prior_returns": ["prior_ret_1", "prior_ret_5", "prior_ret_22"],
        "prior_returns_plus_vol": ["prior_ret_1", "prior_ret_5", "prior_ret_22",
                                   "prior_rv_5", "atm_iv_open"],
        "prior_returns_vol_and_own_lagged_rho1": ["prior_ret_1", "prior_ret_5", "prior_ret_22",
                                                  "prior_rv_5", "atm_iv_open", "prior_rho1_5"],
    }
    rows = []
    for name, cols in ctrl_sets.items():
        X = [C, P] + [p[c].to_numpy(dtype=float) for c in cols]
        r = ns.ols(p["rho1"].to_numpy(dtype=float), np.column_stack(X))
        rows.append({"controls": name, "n": r["n"],
                     "b_call": float(r["beta"][1]), "t_call": float(r["t_nw"][1]),
                     "p_call": float(r["p_nw"][1]),
                     "b_put": float(r["beta"][2]), "t_put": float(r["t_nw"][2]),
                     "p_put": float(r["p_nw"][2]),
                     "contrast": float(r["beta"][2] - r["beta"][1]),
                     "r2_pct": 100 * float(r["r2"]),
                     "sign_pattern": ("+" if r["beta"][1] >= 0 else "-")
                                     + ("+" if r["beta"][2] >= 0 else "-")})
    out["rho1_with_controls"] = rows
    return out


def test_B_moneyness(p: pd.DataFrame) -> dict:
    have = [c for c in p.columns if c.startswith("oi_weighted")]
    out = {"leg_placement": {c: {"mean": float(p[c].mean()), "median": float(p[c].median()),
                                 "sd": float(p[c].std())} for c in have}}
    X = [p[f"zC_{TAG}"].to_numpy(), p[f"zP_{TAG}"].to_numpy()] + \
        [p[c].to_numpy(dtype=float) for c in have]
    r = ns.ols(p["rho1"].to_numpy(dtype=float), np.column_stack(X))
    out["rho1_controlling_for_leg_placement"] = {
        "n": r["n"], "b_call": float(r["beta"][1]), "t_call": float(r["t_nw"][1]),
        "p_call": float(r["p_nw"][1]), "b_put": float(r["beta"][2]),
        "t_put": float(r["t_nw"][2]), "p_put": float(r["p_nw"][2]),
        "contrast": float(r["beta"][2] - r["beta"][1]), "r2_pct": 100 * float(r["r2"]),
        "sign_pattern": ("+" if r["beta"][1] >= 0 else "-")
                        + ("+" if r["beta"][2] >= 0 else "-")}
    # raw open-interest legs with NO gamma weighting at all: does gamma add anything?
    for nm, cols in (("raw_oi_legs", ("oi_total_call", "oi_total_put")),):
        if all(c in p.columns for c in cols):
            zc = ns.zscore_by(np.log(p[cols[0]].to_numpy(dtype=float)), p["year"].to_numpy())
            zp = ns.zscore_by(np.log(p[cols[1]].to_numpy(dtype=float)), p["year"].to_numpy())
            r = ns.ols(p["rho1"].to_numpy(dtype=float), np.column_stack([zc, zp]))
            out[nm] = {"n": r["n"], "b_call": float(r["beta"][1]),
                       "t_call": float(r["t_nw"][1]), "b_put": float(r["beta"][2]),
                       "t_put": float(r["t_nw"][2]),
                       "contrast": float(r["beta"][2] - r["beta"][1]),
                       "r2_pct": 100 * float(r["r2"]),
                       "note": "open interest summed WITHOUT gamma weights.  If this "
                               "reproduces the gamma-weighted result, gamma is decorative."}
    return out


def sign_table(pops: dict) -> list[dict]:
    rows = []
    for pname, df in pops.items():
        for dv in npq.LABELS:
            X = np.column_stack([df[f"zC_{TAG}"].to_numpy(), df[f"zP_{TAG}"].to_numpy()])
            r = ns.ols(df[dv].to_numpy(dtype=float), X)
            bc, bp = float(r["beta"][1]), float(r["beta"][2])
            rows.append({"population": pname, "n": r["n"], "dv": dv,
                         "b_call": bc, "b_put": bp,
                         "sign": ("+" if bc >= 0 else "-") + ("+" if bp >= 0 else "-"),
                         "matches_US_convention_plus_mechanism": bool(bc < 0 and bp > 0),
                         "t_call_ols": float(r["t_ols"][1]), "t_put_ols": float(r["t_ols"][2])})
    return rows


def main() -> None:
    panel = npq.build_panel()
    snap = nc.load_snapshot()
    panel = add_history(panel).merge(leg_moneyness(snap), on="date", how="left")
    pops = npq.populations(panel)
    res = {
        "A_return_proxy": test_A_return_proxy(pops["ALL_SESSIONS"]),
        "B_moneyness_and_gamma_value_added": test_B_moneyness(pops["ALL_SESSIONS"]),
        "C_sign_table": sign_table(pops),
    }

    def default(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
        return str(o)

    OUT.write_text(json.dumps(res, indent=2, default=default))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
