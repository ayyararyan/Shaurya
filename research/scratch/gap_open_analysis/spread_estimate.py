#!/usr/bin/env python3
"""Effective bid-ask spreads for the four contracts an iron butterfly trades.

The archive carries OHLC + volume, NOT quotes -- there is no bid or ask column anywhere in it.
So the spread is an UNIDENTIFIED quantity here and must be estimated.  Three independent
estimators are used, and they are labelled proxies throughout:

  Roll (1984)            2*sqrt(-cov(dP_t, dP_{t-1})) on transaction prices.  Undefined when the
                         serial covariance is positive, which is common in options; the share of
                         undefined contract-days is reported and is itself informative.
  Corwin-Schultz (2012)  from consecutive bars' highs and lows.  Designed for daily data; applied
                         here to consecutive 1-minute bars.
  Bar-range floor        median 1-minute high-low on LOW-activity minutes (<= 5 trades' worth of
                         volume), which is close to pure bid-ask bounce.

Exploratory.  No gate change, no gate armed.
"""
from __future__ import annotations
import json, pickle
from pathlib import Path
import numpy as np, pandas as pd

LOT = 75
K = 3 - 2 * np.sqrt(2)


def roll_half_spread(p: np.ndarray) -> float:
    d = np.diff(p)
    if len(d) < 30:
        return np.nan
    g = float(np.cov(d[1:], d[:-1])[0, 1])
    return np.sqrt(-g) if g < 0 else np.nan          # HALF spread = sqrt(-gamma)


def corwin_schultz(h: np.ndarray, l: np.ndarray) -> float:
    """Proportional spread; returns the median over consecutive bar pairs."""
    ok = (h > 0) & (l > 0)
    h, l = h[ok], l[ok]
    if len(h) < 30:
        return np.nan
    hl = np.log(h / l) ** 2
    beta = hl[:-1] + hl[1:]
    hi = np.maximum(h[:-1], h[1:]); lo = np.minimum(l[:-1], l[1:])
    gamma = np.log(hi / lo) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / K - np.sqrt(gamma / K)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = s[np.isfinite(s) & (s > 0)]
    return float(np.median(s)) if len(s) else np.nan


def main() -> None:
    t = pd.read_pickle("spread_paths.pkl")
    q = pickle.load(open("folklore_required_quotes_20260823.pkl", "rb"))["quotes"]
    e = q[q["clock"] == "09:20"]
    atm_of = {}
    for d, g in e.groupby("date"):
        ks = sorted(set(g[g["side"] == "CALL"]["strike"]) & set(g[g["side"] == "PUT"]["strike"]))
        if ks:
            atm_of[d] = float(min(ks, key=lambda k: abs(k - float(g["spot"].iloc[0]))))

    rows = []
    for (d, side, k), g in t.groupby(["date", "side", "strike"], sort=False):
        atm = atm_of.get(d)
        if atm is None:
            continue
        off = float(k) - atm
        g = g.sort_values("clock")
        p = g["close"].to_numpy(float)
        if len(p) < 60 or np.nanmedian(p) <= 0:
            continue
        lowvol = g["volume"].to_numpy(float) <= np.nanquantile(g["volume"].to_numpy(float), 0.25)
        bar_rng = (g["high"].to_numpy(float) - g["low"].to_numpy(float))[lowvol]
        rows.append({
            "date": d, "side": side, "offset": off, "med_price": float(np.median(p)),
            "roll_half_rs": roll_half_spread(p),
            "cs_prop": corwin_schultz(g["high"].to_numpy(float), g["low"].to_numpy(float)),
            "bar_range_half_rs": float(np.median(bar_rng)) / 2 if len(bar_rng) else np.nan,
        })
    df = pd.DataFrame(rows)
    df["cs_half_rs"] = df["cs_prop"] * df["med_price"] / 2.0

    def leg_label(r):
        if r["offset"] == 0:
            return "ATM"
        if abs(r["offset"]) == 150:
            return "wing 150 (w=3)"
        if abs(r["offset"]) == 200:
            return "wing 200 (w=4)"
        return "other"
    df["leg"] = df.apply(leg_label, axis=1)
    df = df[df["leg"] != "other"]

    out = {"n_contract_days": int(len(df)), "dates": int(df["date"].nunique()),
           "note": "the archive has NO bid/ask column; every number here is an estimator, not a quote",
           "roll_undefined_share_pct": float(100 * df["roll_half_rs"].isna().mean()),
           "by_leg": {}}
    for leg, g in df.groupby("leg"):
        out["by_leg"][leg] = {
            "n": int(len(g)),
            "median_price_rs": float(g["med_price"].median()),
            "roll_half_rs_median": float(g["roll_half_rs"].median()),
            "roll_undefined_pct": float(100 * g["roll_half_rs"].isna().mean()),
            "corwin_schultz_half_rs_median": float(g["cs_half_rs"].median()),
            "corwin_schultz_prop_pct": float(100 * g["cs_prop"].median()),
            "bar_range_half_rs_median": float(g["bar_range_half_rs"].median()),
        }

    # ---- cost model for the four-leg structure ----
    def total_cost(atm_half, wing_half, brokerage_per_order=20.0):
        legs_half = 2 * atm_half + 2 * wing_half        # 2 ATM legs + 2 wing legs
        spread_rs = legs_half * 2 * LOT                 # entry AND exit
        return {"spread_rs": spread_rs,
                "brokerage_rs": 8 * brokerage_per_order,
                "total_rs": spread_rs + 8 * brokerage_per_order}

    est = {}
    for name, col in (("Roll", "roll_half_rs"), ("Corwin-Schultz", "cs_half_rs"),
                      ("bar-range floor", "bar_range_half_rs")):
        a = float(df[df["leg"] == "ATM"][col].median())
        for wname, wleg in (("w=3", "wing 150 (w=3)"), ("w=4", "wing 200 (w=4)")):
            w_ = float(df[df["leg"] == wleg][col].median())
            est[f"{name} | {wname}"] = {"atm_half_rs": a, "wing_half_rs": w_,
                                        **total_cost(a, w_)}
    out["cost_model"] = est
    out["edges_to_compare_rs"] = {
        "IF(w=3) unconditional mean": 89.1, "IF(w=4) unconditional mean": 157.6,
        "IF(w=3) selected third, untouched year": 189.4,
        "IF(w=4) selected third, untouched year": 222.6,
        "IF(w=4) selected third, full walk-forward": 309.7,
    }
    verdict = {}
    for k_, v in est.items():
        verdict[k_] = {ek: bool(ev > v["total_rs"]) for ek, ev in out["edges_to_compare_rs"].items()}
    out["survives_cost"] = verdict

    Path("spread_estimate_results.json").write_text(json.dumps(out, indent=2, default=str))
    df.to_csv("spread_estimate_panel.csv", index=False)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
