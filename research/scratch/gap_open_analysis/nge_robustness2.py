#!/usr/bin/env python3
"""Second robustness pass: does the rho1 finding survive the tests that usually kill things?

New module.  Modifies nothing.

Four questions, each of which the first pass leaves open:

1.  **Sampling frequency.**  Barbon & Buraschi sample at five minutes.  If the association
    exists only at five minutes it is a microstructure artefact of that particular grid, not
    a property of the session's shape.  rho1 is rebuilt at 1, 3, 5, 10, 15 and 30 minutes.
2.  **Leave-one-year-out.**  The first pass shows the coefficient is concentrated in 2023.
    Dropping each year in turn says how much of the five-year result one year carries.
3.  **A genuine out-of-sample split.**  Estimate the sign contrast on the first half only,
    then evaluate it on the second half, which was never used to choose anything.
4.  **A second-half-only permutation test.**  The whole-sample placebo tests against chance
    ALIGNMENT; it does not test against the effect living in one year.  Running the same
    targeted placebo inside each half does.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import nge_common as nc
import nge_stats as ns
import nge_path_quality as npq
import nge_robustness as nr

warnings.filterwarnings("ignore", category=RuntimeWarning)

TAG = npq.PRIMARY
OUT = Path("nge_robustness2_results.json")
FREQS = (1, 3, 5, 10, 15, 30)


def rho1_at_frequencies() -> pd.DataFrame:
    """Rebuild rho1 (and the variance ratio) on several sampling grids."""
    from analyze_still_water_spot import load_spot
    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= nc.SESSION_OPEN) & (spot["clock"] <= nc.SESSION_LAST)]
    rows = []
    for date, g in spot.groupby("date"):
        g = g.sort_values("clock")
        clocks = [str(c) for c in g["clock"]]
        spots = g["spot"].to_numpy(dtype=float)
        if len(spots) < 200:
            continue
        row = {"date": date}
        for f in FREQS:
            lab = nc.path_labels(clocks, spots, bar_minutes=f)
            row[f"rho1_{f}m"] = lab["rho1"]
            row[f"vr3_{f}m"] = lab["vr3"]
            row[f"nbars_{f}m"] = lab["n_bars"]
        rows.append(row)
    return pd.DataFrame(rows)


def frequency_sensitivity(panel: pd.DataFrame, freq: pd.DataFrame) -> dict:
    df = panel.merge(freq, on="date", how="inner")
    rows = []
    for f in FREQS:
        y = df[f"rho1_{f}m"].to_numpy(dtype=float)
        r = ns.ols(y, df[f"zGIMB_{TAG}"].to_numpy())
        X = np.column_stack([df[f"zC_{TAG}"].to_numpy(), df[f"zP_{TAG}"].to_numpy()])
        rf = ns.ols(y, X)
        rows.append({
            "bars_minutes": f, "n": r["n"],
            "mean_rho1": float(np.nanmean(y)), "median_bars_per_day": float(
                np.nanmedian(df[f"nbars_{f}m"])),
            "beta_gimb": float(r["beta"][1]), "t_gimb": float(r["t_nw"][1]),
            "p_gimb": float(r["p_nw"][1]), "r2_pct": 100 * float(r["r2"]),
            "b_call": float(rf["beta"][1]), "t_call": float(rf["t_nw"][1]),
            "b_put": float(rf["beta"][2]), "t_put": float(rf["t_nw"][2]),
            "contrast_put_minus_call": float(rf["beta"][2] - rf["beta"][1]),
            "sign_pattern": ("+" if rf["beta"][1] >= 0 else "-")
                            + ("+" if rf["beta"][2] >= 0 else "-")})
    # the variance-ratio label, as an independent re-expression of the same axis
    vr = []
    for f in FREQS:
        y = df[f"vr3_{f}m"].to_numpy(dtype=float)
        r = ns.ols(y, df[f"zGIMB_{TAG}"].to_numpy())
        vr.append({"bars_minutes": f, "n": r["n"], "mean_vr3": float(np.nanmean(y)),
                   "beta": float(r["beta"][1]), "t": float(r["t_nw"][1]),
                   "p": float(r["p_nw"][1])})
    return {"rho1": rows, "variance_ratio_q3": vr}


def leave_one_year_out(panel: pd.DataFrame) -> dict:
    rows = []
    full = ns.ols(panel["rho1"].to_numpy(dtype=float), panel[f"zGIMB_{TAG}"].to_numpy())
    for yr in sorted(panel["year"].unique()):
        sub = panel[panel["year"] != yr]
        r = ns.ols(sub["rho1"].to_numpy(dtype=float), sub[f"zGIMB_{TAG}"].to_numpy())
        X = np.column_stack([sub[f"zC_{TAG}"].to_numpy(), sub[f"zP_{TAG}"].to_numpy()])
        rf = ns.ols(sub["rho1"].to_numpy(dtype=float), X)
        rows.append({"year_dropped": int(yr), "n": r["n"],
                     "beta": float(r["beta"][1]), "t_nw": float(r["t_nw"][1]),
                     "p_nw": float(r["p_nw"][1]),
                     "contrast_put_minus_call": float(rf["beta"][2] - rf["beta"][1]),
                     "pct_of_full_beta": 100.0 * float(r["beta"][1]) / float(full["beta"][1])})
    return {"full_beta": float(full["beta"][1]), "full_t": float(full["t_nw"][1]),
            "rows": rows}


def out_of_sample(panel: pd.DataFrame) -> dict:
    """Fit the two-leg model on the first half; score the second half with FROZEN weights."""
    panel = panel.sort_values("date").reset_index(drop=True)
    cut = len(panel) // 2
    tr, te = panel.iloc[:cut], panel.iloc[cut:]
    X_tr = np.column_stack([tr[f"zC_{TAG}"].to_numpy(), tr[f"zP_{TAG}"].to_numpy()])
    fit = ns.ols(tr["rho1"].to_numpy(dtype=float), X_tr)
    b0, bc, bp = [float(x) for x in fit["beta"]]
    pred = b0 + bc * te[f"zC_{TAG}"].to_numpy() + bp * te[f"zP_{TAG}"].to_numpy()
    y = te["rho1"].to_numpy(dtype=float)
    m = np.isfinite(pred) & np.isfinite(y)
    ss_res = float(np.sum((y[m] - pred[m]) ** 2))
    ss_tot = float(np.sum((y[m] - np.mean(tr["rho1"])) ** 2))
    from scipy import stats as st
    corr, pcorr = st.pearsonr(pred[m], y[m])
    # tercile sort on the frozen prediction
    q = pd.qcut(pd.Series(pred[m]).rank(method="first"), 3, labels=False)
    terciles = [{"tercile": int(g) + 1, "n": int((q == g).sum()),
                 "mean_rho1": float(np.mean(y[m][q == g]))} for g in range(3)]
    return {
        "train": {"range": [tr["date"].min(), tr["date"].max()], "n": int(len(tr)),
                  "b_call": bc, "b_put": bp, "contrast": bp - bc},
        "test": {"range": [te["date"].min(), te["date"].max()], "n": int(m.sum()),
                 "oos_r2_pct": 100.0 * (1.0 - ss_res / ss_tot),
                 "pearson_pred_vs_actual": float(corr), "p": float(pcorr),
                 "terciles_of_frozen_prediction": terciles,
                 "tercile_spread": terciles[-1]["mean_rho1"] - terciles[0]["mean_rho1"]},
    }


def half_sample_placebos(panel: pd.DataFrame, draws: int = 5000) -> dict:
    panel = panel.sort_values("date").reset_index(drop=True)
    cut = len(panel) // 2
    return {
        "first_half": nr.targeted_rho1_placebo(panel.iloc[:cut], draws=draws),
        "second_half": nr.targeted_rho1_placebo(panel.iloc[cut:], draws=draws),
    }


def main() -> None:
    panel = npq.build_panel()
    pops = npq.populations(panel)
    freq = rho1_at_frequencies()
    freq.to_csv("nge_rho1_frequencies.csv", index=False)

    res = {
        "frequency_sensitivity_ALL": frequency_sensitivity(pops["ALL_SESSIONS"], freq),
        "frequency_sensitivity_NONEXPIRY": frequency_sensitivity(pops["NONEXPIRY"], freq),
        "leave_one_year_out": leave_one_year_out(pops["ALL_SESSIONS"]),
        "out_of_sample": out_of_sample(pops["ALL_SESSIONS"]),
        "half_sample_placebos": half_sample_placebos(pops["ALL_SESSIONS"]),
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
