#!/usr/bin/env python3
"""Walk-forward money test: can the two-leg gamma model be traded in real time?

New module.  Modifies nothing.

Sorting on raw gamma imbalance is the brief's money test and it is reported in
``nge_path_quality.py``.  This is the STRONGER version of the same question, and the only
one that corresponds to something a trader could actually have done: at the open of session
t, fit the free-coefficient model on sessions 1..t-1 ONLY, predict session t's path quality,
and sort on that prediction.  No future information enters the coefficients, the
standardisation, or the sort.

Two dependent variables are carried through: rho1 (path shape) and the realised absolute
displacement (volatility magnitude), because they are the two channels the association tests
separate.  The traded outcome is the real strike-tracked ATM straddle, entered at the 09:15
traded bar close and exited at the 15:29 traded bar close.

Offline analysis only.  No broker, credential, exchange network, or order path.  No live
order exists or is authorised.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import nge_stats as ns
import nge_path_quality as npq

warnings.filterwarnings("ignore", category=RuntimeWarning)

TAG = npq.PRIMARY
OUT = Path("nge_walkforward_results.json")
MIN_TRAIN = 250          # one year of sessions before the first live prediction


def walk_forward(panel: pd.DataFrame, dv: str) -> pd.DataFrame:
    p = panel.sort_values("date").reset_index(drop=True)
    y = p[dv].to_numpy(dtype=float)
    C = p[f"zC_{TAG}"].to_numpy(dtype=float)
    P = p[f"zP_{TAG}"].to_numpy(dtype=float)
    G = p[f"gimb_{TAG}"].to_numpy(dtype=float)
    pred_free = np.full(len(p), np.nan)
    pred_gimb = np.full(len(p), np.nan)
    for t in range(MIN_TRAIN, len(p)):
        m = np.isfinite(y[:t]) & np.isfinite(C[:t]) & np.isfinite(P[:t])
        if m.sum() < MIN_TRAIN // 2:
            continue
        r = ns.ols(y[:t][m], np.column_stack([C[:t][m], P[:t][m]]))
        pred_free[t] = r["beta"][0] + r["beta"][1] * C[t] + r["beta"][2] * P[t]
        rg = ns.ols(y[:t][m], G[:t][m])
        pred_gimb[t] = rg["beta"][0] + rg["beta"][1] * G[t]
    return p.assign(**{f"pred_free_{dv}": pred_free, f"pred_gimb_{dv}": pred_gimb})


def evaluate(p: pd.DataFrame, dv: str, pred_col: str) -> dict:
    d = p[[pred_col, dv, "atm_straddle_ret_pct", "date"]].dropna()
    if len(d) < 100:
        return {"n": int(len(d)), "insufficient": True}
    rho, prho = stats.spearmanr(d[pred_col], d[dv])
    r = np.corrcoef(d[pred_col], d[dv])[0, 1]
    ss_res = float(np.sum((d[dv] - d[pred_col]) ** 2))
    ss_tot = float(np.sum((d[dv] - d[dv].mean()) ** 2))
    out = {
        "n": int(len(d)), "range": [d["date"].min(), d["date"].max()],
        "pearson_pred_vs_actual": float(r), "spearman": float(rho), "spearman_p": float(prho),
        "oos_r2_pct": 100.0 * (1.0 - ss_res / ss_tot),
        "label_quartiles": npq.quartile_ladder(d, pred_col, dv),
        "money_quartiles_straddle": npq.quartile_ladder(d, pred_col, "atm_straddle_ret_pct"),
    }
    # the tradeable rule the sign implies: buy the straddle only in the top predicted quartile
    ranks = d[pred_col].rank(method="first")
    q = pd.qcut(ranks, 4, labels=False)
    top = d["atm_straddle_ret_pct"][q == 3].to_numpy()
    allr = d["atm_straddle_ret_pct"].to_numpy()
    tt = stats.ttest_ind(top, allr[q != 3], equal_var=False)
    out["top_quartile_rule"] = {
        "n_trades": int(len(top)), "mean_pct": float(np.mean(top)),
        "median_pct": float(np.median(top)), "win_rate_pct": 100.0 * float(np.mean(top > 0)),
        "mean_pct_per_minute": float(np.mean(top) / 374.0),
        "vs_rest_t": float(tt.statistic), "vs_rest_p": float(tt.pvalue),
        "unconditional_mean_pct": float(np.mean(allr)),
        "improvement_pp": float(np.mean(top) - np.mean(allr)),
        "smallest_detectable_improvement_pp": ns.detectable_mean(
            float(np.std(allr, ddof=1)) * np.sqrt(2), int(len(top))),
    }
    return out


def main() -> None:
    panel = npq.build_panel()
    pops = npq.populations(panel)
    res: dict = {"min_train_sessions": MIN_TRAIN}
    for popname in ("ALL_SESSIONS", "NONEXPIRY"):
        block = {}
        p = pops[popname]
        for dv in ("rho1", "abs_disp_pct"):
            p = walk_forward(p, dv)
            for spec in ("free", "gimb"):
                block[f"{dv}::{spec}"] = evaluate(p, dv, f"pred_{spec}_{dv}")
        res[popname] = block

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
