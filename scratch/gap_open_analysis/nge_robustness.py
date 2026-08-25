#!/usr/bin/env python3
"""Robustness layer for the NGE path-quality test: confounds, stability, targeted placebo.

New module.  It does not modify, and is not imported by, any pre-existing script.

Four things the main script does not settle, each of which could overturn its headline:

1.  **Days-to-expiry.**  Gamma imbalance is mechanically a function of how far the nearest
    weekly is from expiry, and NIFTY intraday path shape is also a function of it (expiry-day
    pinning is a documented chop mechanism -- Ni, Pearson & Poteshman 2005).  If both move
    with the expiry clock, the whole rho1 result could be an expiry-proximity effect wearing
    a gamma costume.  Tested with expiry-bucket fixed effects and within-bucket demeaning.
2.  **Sub-period stability.**  A five-year in-sample coefficient that lives in one half of
    the sample is not a finding.  Split at the midpoint, and by year.
3.  **A TARGETED placebo on rho1 alone.**  The best-of-grid placebo in the main script
    maximises over four dependent variables, and its winner is the volatility label, not the
    path-shape label.  The path-shape claim needs its own permutation test.
4.  **Newey-West at small N.**  A 5-lag HAC covariance on N=33 is not trustworthy; classical
    standard errors are reported alongside wherever N < 300.

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
OUT = Path("nge_robustness_results.json")


def expiry_confound(panel: pd.DataFrame) -> dict:
    out: dict = {}
    b = panel["sessions_to_expiry"].clip(upper=6).astype(int)
    panel = panel.assign(dte_bucket=b)
    out["profile_by_sessions_to_expiry"] = json.loads(
        panel.groupby("dte_bucket")[["rho1", "r2_line", "kaufman_er", "abs_disp_pct",
                                     f"gimb_{TAG}", "atm_iv_open"]]
        .agg(["mean", "size"]).to_json())

    rows = []
    for dv in npq.LABELS:
        y = panel[dv].to_numpy(dtype=float)
        g = panel[f"zGIMB_{TAG}"].to_numpy()
        base = ns.ols(y, g)
        # (a) expiry-bucket dummies as controls
        D = pd.get_dummies(panel["dte_bucket"], drop_first=True).to_numpy(dtype=float)
        withfe = ns.ols(y, np.column_stack([g, D]))
        # (b) within-bucket demeaning of BOTH sides -- the strictest version
        gw = g - panel.groupby("dte_bucket")[f"zGIMB_{TAG}"].transform("mean").to_numpy()
        yw = y - panel.groupby("dte_bucket")[dv].transform("mean").to_numpy()
        within = ns.ols(yw, gw)
        rows.append({
            "dv": dv, "n": base["n"],
            "beta_raw": float(base["beta"][1]), "t_raw": float(base["t_nw"][1]),
            "p_raw": float(base["p_nw"][1]),
            "beta_with_dte_fe": float(withfe["beta"][1]), "t_with_dte_fe": float(withfe["t_nw"][1]),
            "p_with_dte_fe": float(withfe["p_nw"][1]),
            "beta_within_dte": float(within["beta"][1]), "t_within_dte": float(within["t_nw"][1]),
            "p_within_dte": float(within["p_nw"][1]),
            "attenuation_pct": 100.0 * (1 - abs(float(within["beta"][1]))
                                        / max(abs(float(base["beta"][1])), 1e-12)),
        })
    out["controls"] = rows

    # the same for the free-coefficient specification, which is the design point
    free = []
    for dv in npq.LABELS:
        y = panel[dv].to_numpy(dtype=float)
        C = panel[f"zC_{TAG}"].to_numpy()
        P = panel[f"zP_{TAG}"].to_numpy()
        D = pd.get_dummies(panel["dte_bucket"], drop_first=True).to_numpy(dtype=float)
        r = ns.ols(y, np.column_stack([C, P, D]))
        free.append({"dv": dv, "n": r["n"],
                     "b_call": float(r["beta"][1]), "t_call": float(r["t_nw"][1]),
                     "p_call": float(r["p_nw"][1]),
                     "b_put": float(r["beta"][2]), "t_put": float(r["t_nw"][2]),
                     "p_put": float(r["p_nw"][2]),
                     "sign_pattern": ("+" if r["beta"][1] >= 0 else "-")
                                     + ("+" if r["beta"][2] >= 0 else "-")})
    out["free_call_put_with_dte_fe"] = free
    return out


def stability(panel: pd.DataFrame) -> dict:
    out: dict = {"halves": [], "by_year": [], "by_population_slice": []}
    mid = panel["date"].quantile(0.5) if panel["date"].dtype != object else \
        sorted(panel["date"])[len(panel) // 2]
    for name, sub in (("first_half", panel[panel["date"] < mid]),
                      ("second_half", panel[panel["date"] >= mid])):
        for dv in npq.LABELS:
            r = ns.ols(sub[dv].to_numpy(dtype=float), sub[f"zGIMB_{TAG}"].to_numpy())
            X = np.column_stack([sub[f"zC_{TAG}"].to_numpy(), sub[f"zP_{TAG}"].to_numpy()])
            rf = ns.ols(sub[dv].to_numpy(dtype=float), X)
            out["halves"].append({
                "half": name, "range": [sub["date"].min(), sub["date"].max()], "dv": dv,
                "n": r["n"], "beta": float(r["beta"][1]), "t_nw": float(r["t_nw"][1]),
                "t_ols": float(r["t_ols"][1]), "p_nw": float(r["p_nw"][1]),
                "b_call": float(rf["beta"][1]), "b_put": float(rf["beta"][2]),
                "sign_pattern": ("+" if rf["beta"][1] >= 0 else "-")
                                + ("+" if rf["beta"][2] >= 0 else "-")})
    for yr, sub in panel.groupby("year"):
        for dv in ("rho1", "abs_disp_pct"):
            r = ns.ols(sub[dv].to_numpy(dtype=float), sub[f"zGIMB_{TAG}"].to_numpy())
            out["by_year"].append({"year": int(yr), "dv": dv, "n": r["n"],
                                   "beta": float(r["beta"][1]), "t_nw": float(r["t_nw"][1]),
                                   "t_ols": float(r["t_ols"][1]),
                                   "p_ols": float(r["p_ols"][1])})
    return out


def classical_vs_hac(pops: dict) -> dict:
    """Newey-West against classical standard errors, everywhere N is small."""
    rows = []
    for pname, df in pops.items():
        for dv in npq.LABELS:
            X = np.column_stack([df[f"zC_{TAG}"].to_numpy(), df[f"zP_{TAG}"].to_numpy()])
            r = ns.ols(df[dv].to_numpy(dtype=float), X)
            rows.append({"population": pname, "dv": dv, "n": r["n"],
                         "b_call": float(r["beta"][1]),
                         "t_call_nw": float(r["t_nw"][1]), "t_call_ols": float(r["t_ols"][1]),
                         "p_call_nw": float(r["p_nw"][1]), "p_call_ols": float(r["p_ols"][1]),
                         "b_put": float(r["beta"][2]),
                         "t_put_nw": float(r["t_nw"][2]), "t_put_ols": float(r["t_ols"][2]),
                         "p_put_nw": float(r["p_nw"][2]), "p_put_ols": float(r["p_ols"][2])})
    return {"rows": rows}


def targeted_rho1_placebo(panel: pd.DataFrame, draws: int = 5000) -> dict:
    """Permutation test on the rho1 claim alone, with no maximisation over labels.

    Statistic: the free-coefficient contrast (b_put - b_call) on rho1 at the primary chain
    width.  Under the US convention plus the Baltussen/Barbon mechanism this contrast is
    POSITIVE; under an inverted Indian dealer position it is negative.  A one-statistic test
    needs no best-of-grid correction, which makes it the cleanest single number available.
    """
    df = panel.reset_index(drop=True)
    n = len(df)
    y = df["rho1"].to_numpy(dtype=float)
    C = df[f"zC_{TAG}"].to_numpy()
    P = df[f"zP_{TAG}"].to_numpy()

    def contrast(perm):
        r = ns.ols(y, np.column_stack([C[perm], P[perm]]))
        return float(r["beta"][2] - r["beta"][1]), abs(float(r["t_nw"][2]))

    base = np.arange(n)
    obs_c, obs_t = contrast(base)
    rng = np.random.default_rng(npq.SEED + 7)
    out = {"observed_contrast_b_put_minus_b_call": obs_c, "observed_abs_t_put": obs_t,
           "draws": draws}
    for scheme in ("circular_rotation", "random_shuffle"):
        cs, ts = [], []
        for _ in range(draws):
            perm = (np.roll(base, int(rng.integers(1, n))) if scheme == "circular_rotation"
                    else rng.permutation(n))
            c, t = contrast(perm)
            cs.append(c)
            ts.append(t)
        cs, ts = np.asarray(cs), np.asarray(ts)
        out[scheme] = {
            "placebo_mean_contrast": float(cs.mean()),
            "placebo_sd_contrast": float(cs.std(ddof=1)),
            "placebo_95th_pct_contrast": float(np.percentile(cs, 95)),
            "empirical_p_one_sided": float(np.mean(cs >= obs_c)),
            "empirical_p_two_sided": float(np.mean(np.abs(cs) >= abs(obs_c))),
            "empirical_p_abs_t": float(np.mean(ts >= obs_t)),
        }
    return out


def per_minute(panel: pd.DataFrame, pops: dict) -> dict:
    """Loss per minute held, so series with different holding periods are comparable."""
    rows = []
    for pname, ret, minutes in (
            ("ALL_SESSIONS", "atm_straddle_ret_pct", None),
            ("ALL_SESSIONS", "atm_call_ret_pct", None),
            ("POOL264", "gate_real_ret_pct", "gate"),
            ("FIRES120", "gate_real_ret_pct", "gate"),
            ("MIDIV33", "gate_real_ret_pct", "gate")):
        df = pops[pname]
        r = df[ret].to_numpy(dtype=float)
        if minutes == "gate":
            held = (929 - df["gate_entry_minute"]).to_numpy(dtype=float)
        else:
            held = np.full(len(df), 374.0)
        m = np.isfinite(r) & np.isfinite(held) & (held > 0)
        rows.append({"population": pname, "series": ret, "n": int(m.sum()),
                     "mean_pct": float(np.mean(r[m])),
                     "median_held_minutes": float(np.median(held[m])),
                     "mean_pct_per_minute": float(np.mean(r[m] / held[m])),
                     "median_pct_per_minute": float(np.median(r[m] / held[m]))})
    # per-minute ladder on the ex-ante sort, ALL_SESSIONS straddle
    df = pops["ALL_SESSIONS"].assign(
        straddle_per_min=pops["ALL_SESSIONS"]["atm_straddle_ret_pct"] / 374.0)
    lad = npq.quartile_ladder(df, f"gimb_{TAG}", "straddle_per_min")
    return {"rows": rows, "per_minute_quartile_ladder_straddle": lad}


def main() -> None:
    panel = npq.build_panel()
    pops = npq.populations(panel)
    res = {
        "expiry_confound": expiry_confound(pops["ALL_SESSIONS"]),
        "stability": stability(pops["ALL_SESSIONS"]),
        "classical_vs_hac": classical_vs_hac(pops),
        "targeted_rho1_placebo_ALL": targeted_rho1_placebo(pops["ALL_SESSIONS"]),
        "targeted_rho1_placebo_NONEXPIRY": targeted_rho1_placebo(pops["NONEXPIRY"]),
        "per_minute": per_minute(panel, pops),
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
