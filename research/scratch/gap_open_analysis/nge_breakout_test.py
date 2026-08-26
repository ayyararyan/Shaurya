"""
Does ex-ante dealer net gamma predict BREAKOUT FOLLOW-THROUGH on NIFTY?

Motivation (Aryan, 2026-08-23): the NGE study tested a LINEAR, UNCONDITIONAL association
between gamma imbalance and session-average 5-minute return autocorrelation.  The
practitioner claim is different and CONDITIONAL: given that price breaks a level, dealers
short gamma amplify the move (breakout extends) and dealers long gamma suppress it
(breakout fails).  That object was never tested.  This file tests it.

Ex-ante: every regressor is read off the 09:15 option snapshot already audited in
nge_common.load_snapshot / build_daily.  Outcomes use spot minute closes only.
Offline analysis.  No broker, no order path.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from scipy import stats

SEED = 20260823
RNG = np.random.default_rng(SEED)

PANEL = "nge_panel.csv"
GCOLS = {"g10": "gimb_otm_trade_w10", "g3": "gimb_otm_trade_w3"}
GEX10 = "gex_otm_trade_w10"


def load_spot_by_date() -> dict[str, pd.DataFrame]:
    from analyze_still_water_spot import load_spot
    sp, _ = load_spot()
    sp = sp[(sp["clock"] >= "09:15") & (sp["clock"] <= "15:29")]
    return {d: g.sort_values("clock").reset_index(drop=True) for d, g in sp.groupby("date")}


def breakout_row(path: pd.DataFrame, or_end: str, start: str) -> dict | None:
    """First-passage breakout of the opening range, and what happens after it."""
    rng = path[path["clock"] <= or_end]
    post = path[path["clock"] >= start].reset_index(drop=True)
    if len(rng) < 10 or len(post) < 60:
        return None
    hi, lo = float(rng["spot"].max()), float(rng["spot"].min())
    s = post["spot"].to_numpy(dtype=float)
    up = np.where(s > hi)[0]
    dn = np.where(s < lo)[0]
    iu = up[0] if len(up) else 10**9
    idn = dn[0] if len(dn) else 10**9
    if iu == idn:
        return None                      # no breakout all session
    i = min(iu, idn)
    d = 1 if iu < idn else -1
    entry = s[i]
    fwd = s[i:]
    close = s[-1]
    ft = d * (close - entry)
    mfe = d * (np.max(fwd) - entry) if d > 0 else d * (np.min(fwd) - entry)
    mae = d * (np.min(fwd) - entry) if d > 0 else d * (np.max(fwd) - entry)
    # failure = price returns fully back inside the opening range after the break
    back = (fwd < hi) if d > 0 else (fwd > lo)
    return {
        "or_hi": hi, "or_lo": lo, "or_width": hi - lo,
        "bo_dir": d, "bo_idx": int(i), "bo_clock": str(post["clock"].iloc[i]),
        "bo_price": entry, "close": close,
        "ft_pts": ft, "ft_pct": 100.0 * ft / entry,
        "mfe_pts": mfe, "mae_pts": mae,
        "failed": int(back.any()),
        "minutes_held": int(len(fwd) - 1),
    }


def ols(x: np.ndarray, y: np.ndarray) -> dict:
    b1, b0 = np.polyfit(x, y, 1)
    res = y - (b0 + b1 * x)
    n = len(x)
    se = float(np.sqrt((res @ res / (n - 2)) / ((x - x.mean()) ** 2).sum()))
    t = float(b1 / se)
    r2 = 1.0 - (res @ res) / ((y - y.mean()) ** 2).sum()
    return {"beta": float(b1), "se": se, "t": t,
            "p": float(2 * (1 - stats.t.cdf(abs(t), n - 2))), "r2_pct": 100 * float(r2), "n": n}


def main() -> None:
    panel = pd.read_csv(PANEL, parse_dates=["date"])
    panel["dstr"] = panel["date"].dt.strftime("%Y-%m-%d")
    panel["yr"] = panel["date"].dt.year
    spot = load_spot_by_date()

    res: dict = {"seed": SEED, "registered_tests": [], "specs": {}}
    for spec, (or_end, start) in {"OR15": ("09:29", "09:30"),
                                  "OR30": ("09:44", "09:45")}.items():
        rows = []
        for _, r in panel.iterrows():
            p = spot.get(r["dstr"])
            if p is None:
                continue
            b = breakout_row(p, or_end, start)
            if b is None:
                continue
            b["date"] = r["dstr"]; b["yr"] = int(r["yr"])
            b["is_expiry_day"] = int(r["is_expiry_day"])
            b["atm_iv_open"] = float(r["atm_iv_open"])
            for k, c in GCOLS.items():
                b[k] = float(r[c])
            b["gex10"] = float(r[GEX10])
            rows.append(b)
        df = pd.DataFrame(rows).dropna(subset=["g10", "ft_pct"])
        df["neg_gamma"] = (df["gex10"] < 0).astype(int)
        out: dict = {"n_sessions_in_panel": int(len(panel)),
                     "n_with_breakout": int(len(df)),
                     "breakout_share_pct": round(100 * len(df) / len(panel), 1),
                     "up_share_pct": round(100 * float((df["bo_dir"] > 0).mean()), 1),
                     "mean_ft_pct": round(float(df["ft_pct"].mean()), 4),
                     "median_ft_pct": round(float(df["ft_pct"].median()), 4),
                     "fail_rate_pct": round(100 * float(df["failed"].mean()), 1)}

        # T1 primary: follow-through on gamma imbalance (w10)
        out["T1_ft_on_g10"] = ols(df["g10"].to_numpy(), df["ft_pct"].to_numpy())
        sp = stats.spearmanr(df["g10"], df["ft_pct"])
        out["T1_spearman"] = {"rho": float(sp.statistic), "p": float(sp.pvalue)}
        # T2 near-ATM measure
        out["T2_ft_on_g3"] = ols(df["g3"].to_numpy(), df["ft_pct"].to_numpy())
        # T3 regime: negative vs positive net gamma
        a = df.loc[df.neg_gamma == 1, "ft_pct"]; b_ = df.loc[df.neg_gamma == 0, "ft_pct"]
        tt = stats.ttest_ind(a, b_, equal_var=False)
        mw = stats.mannwhitneyu(a, b_)
        out["T3_regime"] = {"neg_n": int(len(a)), "neg_mean": round(float(a.mean()), 4),
                            "pos_n": int(len(b_)), "pos_mean": round(float(b_.mean()), 4),
                            "diff": round(float(a.mean() - b_.mean()), 4),
                            "welch_p": float(tt.pvalue), "mw_p": float(mw.pvalue)}
        # T4 quintile ladder on follow-through, and failure rate
        df["q"] = pd.qcut(df["g10"], 5, labels=[1, 2, 3, 4, 5])
        lad = df.groupby("q", observed=True).agg(ft=("ft_pct", "mean"),
                                                 med=("ft_pct", "median"),
                                                 fail=("failed", "mean"),
                                                 n=("ft_pct", "size"))
        out["T4_quintile_ladder"] = {int(i): {"ft_pct": round(float(lad.loc[i, "ft"]), 4),
                                              "median": round(float(lad.loc[i, "med"]), 4),
                                              "fail_pct": round(100 * float(lad.loc[i, "fail"]), 1),
                                              "n": int(lad.loc[i, "n"])} for i in lad.index}
        # T5 failure rate on gamma (extreme terciles, Fisher)
        df["t3"] = pd.qcut(df["g10"], 3, labels=[1, 2, 3])
        lo_ = df[df.t3 == 1]; hi_ = df[df.t3 == 3]
        tab = [[int(lo_.failed.sum()), int((1 - lo_.failed).sum())],
               [int(hi_.failed.sum()), int((1 - hi_.failed).sum())]]
        out["T5_failure_lowvhigh_gamma"] = {
            "low_gamma_fail_pct": round(100 * float(lo_.failed.mean()), 1),
            "high_gamma_fail_pct": round(100 * float(hi_.failed.mean()), 1),
            "fisher_p": float(stats.fisher_exact(tab)[1])}
        # T6 magnitude channel: absolute follow-through (does gamma predict move size?)
        out["T6_absft_on_g10"] = ols(df["g10"].to_numpy(),
                                     df["ft_pct"].abs().to_numpy())
        # T7 MFE beyond the break
        out["T7_mfe_on_g10"] = ols(df["g10"].to_numpy(),
                                   (100 * df["mfe_pts"] / df["bo_price"]).to_numpy())
        # per-year, primary
        out["by_year"] = {}
        for y, g in df.groupby("yr"):
            if len(g) < 40:
                continue
            out["by_year"][int(y)] = ols(g["g10"].to_numpy(), g["ft_pct"].to_numpy())
        # placebo on the primary statistic: shuffle gamma across days
        obs_t = abs(out["T1_ft_on_g10"]["t"])
        gv = df["g10"].to_numpy().copy(); yv = df["ft_pct"].to_numpy()
        draws = []
        for _ in range(2000):
            draws.append(abs(ols(RNG.permutation(gv), yv)["t"]))
        out["T1_placebo"] = {"draws": 2000, "obs_abs_t": round(obs_t, 3),
                             "placebo_median_abs_t": round(float(np.median(draws)), 3),
                             "empirical_p": round(float(np.mean(np.array(draws) >= obs_t)), 4)}
        res["specs"][spec] = out
        df.to_csv(f"nge_breakout_panel_{spec}.csv", index=False)

    res["registered_tests"] = ["T1 ft~g10", "T2 ft~g3", "T3 regime neg/pos", "T4 quintile ladder",
                               "T5 failure low vs high gamma", "T6 |ft|~g10", "T7 mfe~g10"]
    res["n_registered_per_spec"] = 7
    res["bonferroni_alpha_14_tests"] = 0.05 / 14
    with open("nge_breakout_results.json", "w") as fh:
        json.dump(res, fh, indent=2, default=float)
    print(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
