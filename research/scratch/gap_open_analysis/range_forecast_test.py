#!/usr/bin/env python3
"""Is the intraday range forecastable, and if so does it let you size the wings?

Aryan (voice, 14:09): "if we have to do this we have to be able to forecast an intraday range...
if we can do that then we can select the optimal wings and mostly our problem should be sorted."

Two separate questions, answered separately:
  Q1  Is the 09:20 -> 15:29 range (and terminal displacement) forecastable out of sample?
  Q2  Does that forecast, used to select DAYS or to select WING WIDTH, produce an iron butterfly
      that clears its transaction-cost bar?

Exploratory.  No Gate A / Gate B change, no gate armed, no broker or order path.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import nge_common as nc
import vrp_forecast_common as vfc
from analyze_still_water_spot import load_spot

LOT = 75
STEP = 50.0
ENTRY, EXIT = "09:20", "15:29"
TEST_START = "2025-05-13"
SEED = 20260823
N_PLACEBO = 2000
COST_BAR_RS = 160.0          # 8 orders x ~Rs 20 discount brokerage, spread excluded
REFIT_EVERY = 21
MIN_TRAIN = 250


# ----------------------------------------------------------------------------------
# panel
# ----------------------------------------------------------------------------------

def build_panel() -> pd.DataFrame:
    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= EXIT)]
    spot = spot.drop_duplicates(["date", "clock"]).sort_values(["date", "clock"])

    rows = []
    for d, g in spot.groupby("date", sort=True):
        px = g.set_index("clock")["spot"]
        if ENTRY not in px.index or len(px) < 200:
            continue
        seg = px.loc[ENTRY:]
        s0, s1 = float(seg.iloc[0]), float(seg.iloc[-1])
        rows.append({"date": d, "spot_0920": s0, "spot_1529": s1,
                     "rng": float(seg.max() - seg.min()),
                     "disp": abs(s1 - s0),
                     "rng_full": float(px.max() - px.min())})
    df = pd.DataFrame(rows)

    q = pickle.load(open("folklore_required_quotes_20260823.pkl", "rb"))["quotes"]
    e = q[q["clock"] == ENTRY]
    daily = nc.load_daily().set_index("date")
    sessions = sorted(daily.index.tolist())
    expiries = nc._expiry_dates()

    iv_rows = []
    for d, g in e.groupby("date"):
        if d not in daily.index:
            continue
        S = float(g["spot"].iloc[0])
        ks = sorted(set(g[g["side"] == "CALL"]["strike"]) & set(g[g["side"] == "PUT"]["strike"]))
        if not ks:
            continue
        atm = float(min(ks, key=lambda k: abs(k - S)))
        exp = nc._next_expiry(d, expiries)
        n_sess = nc.trading_sessions_between(d, exp, sessions) if exp else np.nan
        if not np.isfinite(n_sess) or n_sess < 1:
            continue
        T = n_sess / nc.SESSIONS_PER_YEAR
        ivs = []
        for side in ("CALL", "PUT"):
            r = g[(g["side"] == side) & (g["strike"] == atm)]
            if r.empty:
                continue
            s_ = vfc.invert_iv(side, float(r["close"].iloc[0]), S, atm, T)
            if np.isfinite(s_):
                ivs.append(s_)
        if not ivs:
            continue
        iv_rows.append({"date": d, "atm": atm, "iv": float(np.mean(ivs)),
                        "n_sess": n_sess, "is_expiry_day": int(exp == d)})
    ivdf = pd.DataFrame(iv_rows)

    df = df.merge(ivdf, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df = df[df["rng"] > 0].reset_index(drop=True)
    # a handful of sessions close exactly at the 09:20 price, giving disp == 0 and log(0).
    # Floored at 0.05 index points; the count is reported.
    df.attrs["zero_disp_days"] = int((df["disp"] <= 0).sum())
    df["disp"] = df["disp"].clip(lower=0.05)
    df["rng"] = df["rng"].clip(lower=0.05)


    # implied one-session expected move: sigma * S * sqrt(1/252) * E|Z|,  E|Z| = sqrt(2/pi)
    df["imp_sd_pts"] = df["iv"] * df["spot_0920"] * np.sqrt(1.0 / nc.SESSIONS_PER_YEAR)
    df["imp_disp_pts"] = df["imp_sd_pts"] * np.sqrt(2.0 / np.pi)
    # E[range] of a driftless Brownian path over one session = sigma*sqrt(T)*sqrt(8/pi)
    df["imp_rng_pts"] = df["imp_sd_pts"] * np.sqrt(8.0 / np.pi)

    for c in ("imp_sd_pts", "imp_disp_pts", "imp_rng_pts"):
        df[c] = df[c].clip(lower=0.05)
    for col in ("rng", "disp"):
        for w in (1, 5, 22):
            df[f"{col}_lag{w}"] = df[col].shift(1).rolling(w).mean()
    df["year"] = df["date"].str.slice(0, 4).astype(int)
    df["dow"] = pd.to_datetime(df["date"]).dt.dayofweek
    return df.dropna(subset=["rng_lag22", "disp_lag22"]).reset_index(drop=True)


# ----------------------------------------------------------------------------------
# forecasting
# ----------------------------------------------------------------------------------

def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    return b


def pred(b: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ b


BLOCKS = {
    "implied only": ["imp"],
    "past only (HAR)": ["l1", "l5", "l22"],
    "HAR + implied": ["l1", "l5", "l22", "imp"],
}


def design(df: pd.DataFrame, target: str, cols: list[str]) -> np.ndarray:
    m = {"imp": f"imp_{'rng' if target == 'rng' else 'disp'}_pts",
         "l1": f"{target}_lag1", "l5": f"{target}_lag5", "l22": f"{target}_lag22"}
    return np.log(df[[m[c] for c in cols]].to_numpy(float))


def r2(y, yhat, bench) -> float:
    return 1.0 - float(np.sum((y - yhat) ** 2)) / float(np.sum((y - np.asarray(bench)) ** 2))


def q1_accuracy(df: pd.DataFrame) -> dict:
    tr, te = df[df["date"] < TEST_START], df[df["date"] >= TEST_START]
    out = {"n_train": int(len(tr)), "n_test": int(len(te)), "test_start": TEST_START, "targets": {}}
    for target in ("rng", "disp"):
        y_tr, y_te = tr[target].to_numpy(float), te[target].to_numpy(float)
        bench_const = float(y_tr.mean())
        imp_te = te[f"imp_{target}_pts"].to_numpy(float)
        res = {"mean_train": bench_const, "mean_test": float(y_te.mean()),
               "mean_implied_test": float(imp_te.mean()),
               "raw_implied_r2_vs_const": r2(y_te, imp_te, bench_const)}
        for name, cols in BLOCKS.items():
            b = ols(design(tr, target, cols), np.log(y_tr))
            yhat = np.exp(pred(b, design(te, target, cols)))
            res[name] = {
                "oos_r2_vs_const": r2(y_te, yhat, bench_const),
                "corr": float(np.corrcoef(y_te, yhat)[0, 1]),
                "rmse": float(np.sqrt(np.mean((y_te - yhat) ** 2))),
                "rmse_const": float(np.sqrt(np.mean((y_te - bench_const) ** 2))),
                "mean_abs_pct_err": float(np.mean(np.abs(yhat - y_te) / y_te) * 100),
            }
        # does past information add anything BEYOND the option price?
        b_imp = ols(design(tr, target, BLOCKS["implied only"]), np.log(y_tr))
        yhat_imp = np.exp(pred(b_imp, design(te, target, BLOCKS["implied only"])))
        b_all = ols(design(tr, target, BLOCKS["HAR + implied"]), np.log(y_tr))
        yhat_all = np.exp(pred(b_all, design(te, target, BLOCKS["HAR + implied"])))
        res["incremental_r2_of_HAR_over_implied"] = r2(y_te, yhat_all, yhat_imp)
        out["targets"][target] = res
    return out


def walk_forward(df: pd.DataFrame, target: str, cols: list[str]) -> pd.Series:
    """Expanding window, refit every REFIT_EVERY sessions.  Every forecast is strictly OOS."""
    yhat = np.full(len(df), np.nan)
    X = design(df, target, cols)
    y = np.log(df[target].to_numpy(float))
    b = None
    for i in range(MIN_TRAIN, len(df)):
        if b is None or (i - MIN_TRAIN) % REFIT_EVERY == 0:
            b = ols(X[:i], y[:i])
        yhat[i] = np.exp(pred(b, X[i:i + 1]))[0]
    return pd.Series(yhat, index=df.index)


# ----------------------------------------------------------------------------------
# Q2: does the forecast help the iron butterfly?
# ----------------------------------------------------------------------------------

def structure_pnl(width_steps: int) -> pd.DataFrame:
    """Iron butterfly P&L per lot for every non-expiry session, keyed on date."""
    q = pickle.load(open("folklore_required_quotes_20260823.pkl", "rb"))["quotes"]
    q = q[q["clock"].isin((ENTRY, EXIT))]
    book: dict = {}
    for (d, c), g in q.groupby(["date", "clock"], sort=False):
        book[(d, c)] = ({s: dict(zip(gg["strike"].astype(float), gg["close"].astype(float)))
                         for s, gg in g.groupby("side")}, float(g["spot"].iloc[0]))
    expiries = set(nc._expiry_dates())
    rows = []
    for d in sorted({dd for (dd, _) in book}):
        if d in expiries or (d, ENTRY) not in book or (d, EXIT) not in book:
            continue
        pe, S = book[(d, ENTRY)]
        px_, _ = book[(d, EXIT)]
        ks = sorted(set(pe.get("CALL", {})) & set(pe.get("PUT", {})))
        if not ks:
            continue
        atm = float(min(ks, key=lambda k: abs(k - S)))
        w = STEP * width_steps
        legs = [("CALL", atm, -1), ("PUT", atm, -1), ("CALL", atm + w, 1), ("PUT", atm - w, 1)]
        try:
            vin = sum(qy * pe[sd][k] for sd, k, qy in legs)
            vout = sum(qy * px_[sd][k] for sd, k, qy in legs)
        except KeyError:
            continue
        credit = -vin
        if credit <= 0 or credit >= w:
            continue
        rows.append({"date": d, "credit_pts": credit, "max_loss_rs": (w - credit) * LOT,
                     "pnl_rs": (vout - vin) * LOT, "width_pts": w})
    return pd.DataFrame(rows)


def selection_test(panel: pd.DataFrame, fly: pd.DataFrame, fc: pd.Series, rng_state) -> dict:
    """Sort sessions by (implied cushion - forecast move) and read the P&L off the sort."""
    df = panel.assign(fc=fc.values).merge(fly, on="date", how="inner").dropna(subset=["fc"])
    df = df[df["date"] >= panel["date"].iloc[MIN_TRAIN]]
    # the fly is profitable at expiry-of-the-day if |move| < credit; "cushion" is that credit
    df["signal"] = df["credit_pts"] - df["fc"]
    out = {"n": int(len(df)),
           "date_min": df["date"].min(), "date_max": df["date"].max(),
           "mean_all_rs": float(df["pnl_rs"].mean()),
           "cost_bar_rs": COST_BAR_RS}
    q = df["signal"].quantile([1 / 3, 2 / 3]).tolist()
    for label, sub in (("bottom third", df[df["signal"] <= q[0]]),
                       ("middle third", df[(df["signal"] > q[0]) & (df["signal"] <= q[1])]),
                       ("top third", df[df["signal"] > q[1]])):
        p = sub["pnl_rs"].to_numpy()
        out[label] = {"n": int(len(p)), "mean_rs": float(p.mean()),
                      "median_rs": float(np.median(p)), "win": float((p > 0).mean()),
                      "mean_ror_pct": float(100 * np.mean(p / sub["max_loss_rs"].to_numpy())),
                      "clears_cost_bar": bool(p.mean() > COST_BAR_RS)}
    top = df[df["signal"] > q[1]]["pnl_rs"].to_numpy()
    rest = df[df["signal"] <= q[1]]["pnl_rs"].to_numpy()
    out["top_minus_rest_rs"] = float(top.mean() - rest.mean())
    out["welch_p"] = float(stats.ttest_ind(top, rest, equal_var=False).pvalue)
    # placebo: shuffle the signal, keep the outcome
    sig = df["signal"].to_numpy()
    pnl = df["pnl_rs"].to_numpy()
    draws = np.empty(N_PLACEBO)
    for i in range(N_PLACEBO):
        s = rng_state.permutation(sig)
        thr = np.quantile(s, 2 / 3)
        draws[i] = pnl[s > thr].mean() - pnl[s <= thr].mean()
    out["placebo_median"] = float(np.median(draws))
    out["placebo_p"] = float(np.mean(draws >= out["top_minus_rest_rs"]))
    return out


def conditional_width(panel: pd.DataFrame, flies: dict[int, pd.DataFrame], fc: pd.Series) -> dict:
    """Choose w = 3 or 4 by the forecast, against always-3 and always-4 on the SAME sessions."""
    common = set(flies[3]["date"]) & set(flies[4]["date"])
    base = panel.assign(fc=fc.values)
    base = base[base["date"].isin(common)].dropna(subset=["fc"])
    base = base[base["date"] >= panel["date"].iloc[MIN_TRAIN]]
    f3 = flies[3].set_index("date"); f4 = flies[4].set_index("date")
    d = base["date"].tolist()
    med = base["fc"].median()
    rows = {"always w=3": [], "always w=4": [], "wide when forecast is high": [],
            "wide when forecast is low (inverted control)": []}
    ml = {"always w=3": [], "always w=4": [], "wide when forecast is high": [],
          "wide when forecast is low (inverted control)": []}
    for dt, f in zip(d, base["fc"].tolist()):
        rows["always w=3"].append(f3.loc[dt, "pnl_rs"]); ml["always w=3"].append(f3.loc[dt, "max_loss_rs"])
        rows["always w=4"].append(f4.loc[dt, "pnl_rs"]); ml["always w=4"].append(f4.loc[dt, "max_loss_rs"])
        hi = f4 if f > med else f3
        lo = f3 if f > med else f4
        rows["wide when forecast is high"].append(hi.loc[dt, "pnl_rs"]); ml["wide when forecast is high"].append(hi.loc[dt, "max_loss_rs"])
        rows["wide when forecast is low (inverted control)"].append(lo.loc[dt, "pnl_rs"]); ml["wide when forecast is low (inverted control)"].append(lo.loc[dt, "max_loss_rs"])
    out = {"n": len(d)}
    for k, v in rows.items():
        a = np.asarray(v, dtype=float); m = np.asarray(ml[k], dtype=float)
        out[k] = {"mean_rs": float(a.mean()), "median_rs": float(np.median(a)),
                  "win": float((a > 0).mean()), "mean_ror_pct": float(100 * np.mean(a / m)),
                  "worst_rs": float(a.min()),
                  "t_vs_zero": float(stats.ttest_1samp(a, 0.0).statistic),
                  "clears_cost_bar": bool(a.mean() > COST_BAR_RS)}
    a = np.asarray(rows["wide when forecast is high"], float)
    b = np.asarray(rows["always w=4"], float)
    out["conditional_minus_always4"] = {"mean_rs": float((a - b).mean()),
                                        "paired_p": float(stats.ttest_rel(a, b).pvalue)}
    return out


def main() -> None:
    rng_state = np.random.default_rng(SEED)
    panel = build_panel()
    panel = panel[panel["is_expiry_day"] == 0].reset_index(drop=True)

    res = {"spec": "inline (answers Aryan 14:09)", "seed": SEED,
           "panel_n": int(len(panel)), "date_min": panel["date"].min(),
           "date_max": panel["date"].max(),
           "note": "non-expiry sessions only, the H3 population; 09:20 origin",
           "zero_displacement_days_floored": int((panel["disp"] <= 0.0500001).sum())}

    res["Q1_accuracy"] = q1_accuracy(panel)

    fc_disp = walk_forward(panel, "disp", BLOCKS["HAR + implied"])
    fc_rng = walk_forward(panel, "rng", BLOCKS["HAR + implied"])
    res["walk_forward_r2"] = {}
    for nm, fc, tgt in (("disp", fc_disp, "disp"), ("rng", fc_rng, "rng")):
        m = fc.notna()
        y = panel.loc[m, tgt].to_numpy(float)
        res["walk_forward_r2"][nm] = {
            "n": int(m.sum()),
            "r2_vs_expanding_mean": r2(y, fc[m].to_numpy(),
                                       panel.loc[m, tgt].expanding().mean().to_numpy()),
            "r2_vs_implied": r2(y, fc[m].to_numpy(),
                                panel.loc[m, f"imp_{tgt}_pts"].to_numpy(float)),
            "corr": float(np.corrcoef(y, fc[m].to_numpy())[0, 1]),
        }

    flies = {w: structure_pnl(w) for w in (3, 4)}
    res["fly_n"] = {w: int(len(v)) for w, v in flies.items()}
    res["Q2_day_selection"] = {
        f"IF(w={w}) by forecast displacement": selection_test(panel, flies[w], fc_disp, rng_state)
        for w in (3, 4)}
    res["Q2_day_selection"]["IF(w=3) by forecast RANGE"] = selection_test(
        panel, flies[3], fc_rng, rng_state)
    res["Q2_conditional_width"] = conditional_width(panel, flies, fc_disp)

    Path("range_forecast_results.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
