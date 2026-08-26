#!/usr/bin/env python3
"""Does the FIRST 30 minutes of the NIFTY session predict the LAST 30 minutes?

Aryan, 2026-08-23 (voice): "does the first 30 minutes return in the day predict the last 30
minutes return of the day -- the sign and the magnitude.  As simple as it gets."

This is the Gao, Han, Li & Zhou (2018, JFE) "Market Intraday Momentum" object, tested on the
NIFTY minute-spot archive.  Deliberately simple: OLS, sign agreement, and one naive trading
rule.  No option leg, no costs, no gating.  Offline analysis; no broker, no order path.

Definitions (NIFTY session 09:15-15:30; archive last minute bar is 15:29):
    r_first_open  = log(S_09:44 / S_09:15)          intra-session only
    r_first_gap   = log(S_09:44 / S_prev_15:29)     includes the overnight gap (Gao et al.)
    r_last        = log(S_15:29 / S_15:00)
Predictive regression:  r_last = a + b * r_first + e
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

FIRST_START, FIRST_END = "09:15", "09:44"
LAST_START, LAST_END = "15:00", "15:29"


def at(g: pd.DataFrame, clock: str) -> float:
    """Spot at `clock`, or the last quote at/before it (handles a missing minute bar)."""
    s = g[g["clock"] <= clock]
    return float(s["spot"].iloc[-1]) if len(s) else np.nan


def build() -> pd.DataFrame:
    from analyze_still_water_spot import load_spot
    sp, _ = load_spot()
    sp = sp[(sp["clock"] >= "09:15") & (sp["clock"] <= "15:29")]
    rows = []
    for d, g in sp.groupby("date"):
        g = g.sort_values("clock")
        if len(g) < 200:                      # skip badly truncated sessions
            continue
        rows.append({"date": d,
                     "s_open": at(g, FIRST_START), "s_f_end": at(g, FIRST_END),
                     "s_l_beg": at(g, LAST_START), "s_close": at(g, LAST_END),
                     "n_min": len(g)})
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["prev_close"] = df["s_close"].shift(1)
    df["r_first_open"] = 100 * np.log(df["s_f_end"] / df["s_open"])
    df["r_first_gap"] = 100 * np.log(df["s_f_end"] / df["prev_close"])
    df["r_last"] = 100 * np.log(df["s_close"] / df["s_l_beg"])
    df["r_mid"] = 100 * np.log(df["s_l_beg"] / df["s_f_end"])
    df["yr"] = df["date"].str.slice(0, 4)
    return df.dropna(subset=["r_first_open", "r_last"])


def ols(x: np.ndarray, y: np.ndarray) -> dict:
    b1, b0 = np.polyfit(x, y, 1)
    res = y - (b0 + b1 * x)
    n = len(x)
    se = float(np.sqrt((res @ res / (n - 2)) / ((x - x.mean()) ** 2).sum()))
    t = float(b1 / se)
    return {"n": n, "beta": round(float(b1), 4), "se": round(se, 4), "t": round(t, 3),
            "p": round(float(2 * (1 - stats.t.cdf(abs(t), n - 2))), 5),
            "r2_pct": round(100.0 * (1 - (res @ res) / ((y - y.mean()) ** 2).sum()), 3),
            "alpha_bp": round(float(b0) * 100, 2)}


def sign_rule(x: np.ndarray, y: np.ndarray) -> dict:
    """Naive rule: at 15:00 go long if the first 30 min was up, short if down."""
    pos = np.sign(x)
    r = pos * y
    n = len(r)
    t = float(r.mean() / (r.std(ddof=1) / np.sqrt(n)))
    agree = float((np.sign(x) == np.sign(y)).mean())
    return {"n": n, "mean_pct": round(float(r.mean()), 4),
            "median_pct": round(float(np.median(r)), 4),
            "t": round(t, 3), "p": round(float(2 * (1 - stats.t.cdf(abs(t), n - 1))), 5),
            "win_pct": round(100.0 * float((r > 0).mean()), 1),
            "sign_agree_pct": round(100.0 * agree, 1),
            "ann_pct": round(float(r.mean()) * 252, 1)}


def main() -> None:
    df = build()
    print(f"sessions: {len(df)}   span: {df['date'].iloc[0]} .. {df['date'].iloc[-1]}\n")

    print("=== descriptives (percent) ===")
    for c in ("r_first_open", "r_first_gap", "r_mid", "r_last"):
        s = df[c].dropna()
        print(f"  {c:14s} mean {s.mean():+7.4f}  sd {s.std():6.4f}  "
              f"median {s.median():+7.4f}  n {len(s)}")

    print("\n=== A. r_last = a + b * r_first  (the hypothesis) ===")
    for pred in ("r_first_open", "r_first_gap"):
        d = df.dropna(subset=[pred, "r_last"])
        print(f"  {pred:14s} -> r_last   {ols(d[pred].to_numpy(), d['r_last'].to_numpy())}")

    print("\n=== B. controls / placebos ===")
    d = df.dropna(subset=["r_mid", "r_last"])
    print(f"  r_mid (11:45-15:00) -> r_last   {ols(d['r_mid'].to_numpy(), d['r_last'].to_numpy())}")
    d = df.dropna(subset=["r_first_open", "r_mid"])
    print(f"  r_first_open -> r_mid           {ols(d['r_first_open'].to_numpy(), d['r_mid'].to_numpy())}")
    sh = df.dropna(subset=["r_first_open", "r_last"]).copy()
    rng = np.random.default_rng(20260823)
    ts = [abs(ols(rng.permutation(sh["r_first_open"].to_numpy()), sh["r_last"].to_numpy())["t"])
          for _ in range(2000)]
    obs = abs(ols(sh["r_first_open"].to_numpy(), sh["r_last"].to_numpy())["t"])
    print(f"  shuffled-label placebo: obs |t| {obs:.3f} vs placebo median {np.median(ts):.3f}, "
          f"empirical p {float(np.mean(np.array(ts) >= obs)):.4f}")

    print("\n=== C. naive sign rule: at 15:00 trade the sign of the first 30 min ===")
    for pred in ("r_first_open", "r_first_gap"):
        d = df.dropna(subset=[pred, "r_last"])
        print(f"  {pred:14s} {sign_rule(d[pred].to_numpy(), d['r_last'].to_numpy())}")
    d = df.dropna(subset=["r_last"])
    alw = d["r_last"].to_numpy()
    t = float(alw.mean() / (alw.std(ddof=1) / np.sqrt(len(alw))))
    print(f"  always-long benchmark   mean {alw.mean():+.4f}%  t {t:+.3f}  "
          f"win {100 * (alw > 0).mean():.1f}%")

    print("\n=== D. by year (r_first_open -> r_last) ===")
    for yr, g in df.groupby("yr"):
        g = g.dropna(subset=["r_first_open", "r_last"])
        if len(g) < 30:
            continue
        o = ols(g["r_first_open"].to_numpy(), g["r_last"].to_numpy())
        s = sign_rule(g["r_first_open"].to_numpy(), g["r_last"].to_numpy())
        print(f"  {yr}  n {o['n']:4d}  beta {o['beta']:+.4f}  t {o['t']:+6.3f}  "
              f"rule mean {s['mean_pct']:+.4f}%  agree {s['sign_agree_pct']:.1f}%")

    print("\n=== E. magnitude: does a BIG first 30 min predict more? (quintiles of |r_first|) ===")
    d = df.dropna(subset=["r_first_open", "r_last"]).copy()
    d["q"] = pd.qcut(d["r_first_open"].abs(), 5, labels=False)
    for q, g in d.groupby("q"):
        s = sign_rule(g["r_first_open"].to_numpy(), g["r_last"].to_numpy())
        print(f"  |r_first| Q{q + 1}  n {s['n']:4d}  rule mean {s['mean_pct']:+.4f}%  "
              f"t {s['t']:+6.3f}  agree {s['sign_agree_pct']:.1f}%")

    d.to_csv("intraday_momentum_panel.csv", index=False)
    print("\nwrote intraday_momentum_panel.csv")


if __name__ == "__main__":
    main()
