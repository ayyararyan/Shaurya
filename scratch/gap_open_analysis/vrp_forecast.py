#!/usr/bin/env python3
"""Out-of-sample forecastability of RV - IV to WEEK1 expiry.  Frozen spec: VRP_FORECAST_SPEC.md.

Exploratory.  No Gate A / Gate B change, no gate armed, no broker or order path.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import Ridge

import vrp_forecast_common as vfc

SEED = 20260823
N_PLACEBO = 2000
TEST_MONTHS = 12

TARGETS = {
    "vrp_incl": "RV includes overnight gaps (headline, STATE-06)",
    "vrp_intra": "RV intraday only (project's incumbent convention, STATE-07)",
}

HAR = ["iv", "rv1", "rv5", "rv22"]
STRUCT = HAR + ["n_sess", "is_expiry_day", "abs_gap", "carry"]
ALL_FEATURES = STRUCT + ["gap", "dow"]


# ----------------------------------------------------------------------------------
# estimators
# ----------------------------------------------------------------------------------

def ols_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def ols_predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def ridge_forward_cv(Xtr: np.ndarray, ytr: np.ndarray, alphas=(0.1, 1, 10, 100, 1000)) -> float:
    """Forward-chaining CV inside the training window only.  Never shuffled."""
    n = len(ytr)
    folds = [(int(n * f), int(n * (f + 0.2))) for f in (0.4, 0.6, 0.8)]
    best, best_sse = alphas[0], np.inf
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = (Xtr - mu) / sd
    for a in alphas:
        sse = 0.0
        for lo, hi in folds:
            if lo < 10 or hi <= lo:
                continue
            m = Ridge(alpha=a).fit(Z[:lo], ytr[:lo])
            sse += float(np.sum((ytr[lo:hi] - m.predict(Z[lo:hi])) ** 2))
        if sse < best_sse:
            best, best_sse = a, sse
    return best


def fit_predict(name: str, tr: pd.DataFrame, te: pd.DataFrame, target: str) -> np.ndarray:
    ytr = tr[target].to_numpy()
    if name == "MOD-00 constant":
        return np.full(len(te), float(ytr.mean()))
    if name == "MOD-00b meanRV - observed IV":
        # No realised-volatility forecasting skill whatsoever: assume RV lands on its
        # training-sample average and subtract the IV that is actually observed at the
        # origin.  This isolates the purely MECHANICAL component of any apparent skill,
        # because the target contains -IV by construction and IV is observed (ID-01).
        rv_col = "rv_incl" if target == "vrp_incl" else "rv_intra"
        return float(tr[rv_col].mean()) - te["iv"].to_numpy()
    if name == "MOD-01 iv+rv5":
        cols = ["iv", "rv5"]
    elif name == "MOD-02 HAR":
        cols = HAR
    elif name == "MOD-03 HAR+structure":
        cols = STRUCT
    elif name == "MOD-04 ridge(all)":
        cols = ALL_FEATURES
        Xtr, Xte = tr[cols].to_numpy(float), te[cols].to_numpy(float)
        a = ridge_forward_cv(Xtr, ytr)
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd = np.where(sd > 0, sd, 1.0)
        m = Ridge(alpha=a).fit((Xtr - mu) / sd, ytr)
        return m.predict((Xte - mu) / sd)
    elif name == "MOD-05 logRV HAR then subtract IV":
        rv_col = "rv_incl" if target == "vrp_incl" else "rv_intra"
        cols = ["rv1", "rv5", "rv22", "iv"]
        beta = ols_fit(np.log(tr[cols].to_numpy(float)), np.log(tr[rv_col].to_numpy()))
        rv_hat = np.exp(ols_predict(beta, np.log(te[cols].to_numpy(float))))
        return rv_hat - te["iv"].to_numpy()
    elif name == "MOD-06 HAR+structure+VIX":
        cols = STRUCT + ["vix_open", "vix_on_gap"]
    else:
        raise ValueError(name)
    beta = ols_fit(tr[cols].to_numpy(float), ytr)
    return ols_predict(beta, te[cols].to_numpy(float))


# ----------------------------------------------------------------------------------
# evaluation
# ----------------------------------------------------------------------------------

def newey_west_t(x: np.ndarray, lags: int) -> tuple[float, float]:
    """t-statistic for mean(x) = 0 with Newey-West (Bartlett) HAC standard errors."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    e = x - x.mean()
    g0 = float(np.dot(e, e) / n)
    s = g0
    for L in range(1, min(lags, n - 1) + 1):
        g = float(np.dot(e[L:], e[:-L]) / n)
        s += 2.0 * (1.0 - L / (lags + 1.0)) * g
    se = np.sqrt(max(s, 1e-18) / n)
    t = float(x.mean() / se)
    return t, float(2 * (1 - stats.norm.cdf(abs(t))))


def oos_r2_vec(y: np.ndarray, yhat: np.ndarray, bench) -> float:
    sse = float(np.sum((y - yhat) ** 2))
    sst = float(np.sum((y - np.asarray(bench)) ** 2))
    return 1.0 - sse / sst if sst > 0 else np.nan


def oos_r2(y: np.ndarray, yhat: np.ndarray, bench: float) -> float:
    sse = float(np.sum((y - yhat) ** 2))
    sst = float(np.sum((y - bench) ** 2))
    return 1.0 - sse / sst if sst > 0 else np.nan


def placebo_r2(y: np.ndarray, yhat: np.ndarray, bench: float, rng: np.random.Generator) -> dict:
    """Circular shifts of the forecast series: preserves its autocorrelation, destroys the
    alignment with the outcome.  A plain i.i.d. shuffle would flatter the model."""
    n = len(y)
    obs = oos_r2(y, yhat, bench)
    draws = np.empty(N_PLACEBO)
    for k in range(N_PLACEBO):
        s = int(rng.integers(1, n))
        draws[k] = oos_r2(y, np.roll(yhat, s), bench)
    return {"observed": obs, "placebo_median": float(np.median(draws)),
            "placebo_p95": float(np.quantile(draws, 0.95)),
            "empirical_p": float(np.mean(draws >= obs))}


def evaluate(y: np.ndarray, yhat: np.ndarray, bench: float, lags: int,
             rng: np.random.Generator) -> dict:
    err = y - yhat
    berr = y - bench
    t_nw, p_nw = newey_west_t(berr ** 2 - err ** 2, lags)   # H0: no SSE improvement
    dev_true = y - bench
    dev_hat = yhat - bench
    sign_ok = float(np.mean(np.sign(dev_true) == np.sign(dev_hat)))
    order = np.argsort(yhat)
    k = len(y) // 3
    bot, top = y[order[:k]], y[order[-k:]]
    return {
        "n": int(len(y)),
        "oos_r2": oos_r2(y, yhat, bench),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "rmse_bench": float(np.sqrt(np.mean(berr ** 2))),
        "mae": float(np.mean(np.abs(err))),
        "corr": float(np.corrcoef(y, yhat)[0, 1]) if np.std(yhat) > 0 else np.nan,
        "sign_of_deviation_acc": sign_ok,
        "dm_like_t_nw": t_nw, "dm_like_p_nw": p_nw,
        "tercile_bottom_mean": float(bot.mean()),
        "tercile_top_mean": float(top.mean()),
        "tercile_spread": float(top.mean() - bot.mean()),
        "share_positive_all": float(np.mean(y > 0)),
        "share_positive_top_tercile": float(np.mean(top > 0)),
        "forecast_positive_share": float(np.mean(yhat > 0)),
        "placebo": placebo_r2(y, yhat, bench, rng),
    }


def run(panel: pd.DataFrame) -> dict:
    rng = np.random.default_rng(SEED)
    panel = panel.dropna(subset=["rv22", "rv5", "rv1", "gap"]).reset_index(drop=True)
    last = pd.Timestamp(panel["date"].max())
    test_start = (last - pd.DateOffset(months=TEST_MONTHS) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    is_test = panel["date"] >= test_start
    train_all, test = panel[~is_test], panel[is_test]

    train_windows = {
        "A all prior": train_all,
        "B two years": train_all[train_all["date"] >= (pd.Timestamp(test_start) - pd.DateOffset(years=2)).strftime("%Y-%m-%d")],
        "C one year": train_all[train_all["date"] >= (pd.Timestamp(test_start) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")],
    }

    models = ["MOD-00 constant", "MOD-00b meanRV - observed IV", "MOD-01 iv+rv5", "MOD-02 HAR",
              "MOD-03 HAR+structure", "MOD-04 ridge(all)", "MOD-05 logRV HAR then subtract IV"]
    lags = int(panel["n_sess"].max())

    results: dict = {
        "spec": "VRP_FORECAST_SPEC.md", "seed": SEED, "n_placebo": N_PLACEBO,
        "panel_n": int(len(panel)), "date_min": panel["date"].min(), "date_max": panel["date"].max(),
        "test_start": test_start, "test_n": int(len(test)),
        "train_sizes": {k: int(len(v)) for k, v in train_windows.items()},
        "nw_lags": lags,
        "descriptives": {}, "evaluations": {}, "non_overlapping": {}, "vix_block": {},
        "in_sample_fits": {},
    }

    for tgt, label in TARGETS.items():
        results["descriptives"][tgt] = {
            "label": label,
            "mean_iv": float(panel["iv"].mean()), "mean_rv": float(panel[tgt.replace("vrp", "rv")].mean()),
            "mean": float(panel[tgt].mean()), "median": float(panel[tgt].median()),
            "sd": float(panel[tgt].std()), "share_positive": float((panel[tgt] > 0).mean()),
            "train_mean": {k: float(v[tgt].mean()) for k, v in train_windows.items()},
            "test_mean": float(test[tgt].mean()),
        }

    for tgt in TARGETS:
        for wname, tr in train_windows.items():
            bench = float(tr[tgt].mean())
            rv_col = "rv_incl" if tgt == "vrp_incl" else "rv_intra"
            bench_b = float(tr[rv_col].mean()) - test["iv"].to_numpy()
            for m in models:
                yhat = fit_predict(m, tr, test, tgt)
                key = f"{tgt} | {wname} | {m}"
                ev = evaluate(test[tgt].to_numpy(), yhat, bench, lags, rng)
                y = test[tgt].to_numpy()
                ev["oos_r2_vs_MOD00b"] = oos_r2_vec(y, yhat, bench_b)
                results["evaluations"][key] = ev

    # ---- OOS-05 non-overlapping replication: one session per expiry cycle ----
    first_of_cycle = panel.groupby("cycle", sort=True)["date"].min()
    keep = set(first_of_cycle.tolist())
    for tgt in TARGETS:
        tr = train_all[train_all["date"].isin(keep)]
        te = test[test["date"].isin(keep)]
        bench = float(tr[tgt].mean())
        rv_col = "rv_incl" if tgt == "vrp_incl" else "rv_intra"
        bench_b = float(tr[rv_col].mean()) - te["iv"].to_numpy()
        for m in models:
            yhat = fit_predict(m, tr, te, tgt)
            ev = evaluate(te[tgt].to_numpy(), yhat, bench, 1, rng)
            ev["oos_r2_vs_MOD00b"] = oos_r2_vec(te[tgt].to_numpy(), yhat, bench_b)
            results["non_overlapping"][f"{tgt} | {m}"] = ev
        results["non_overlapping"][f"{tgt} | _n_train"] = int(len(tr))

    # ---- OOS-05b: every non-overlapping PHASE, not just the first session of a cycle ----
    # Session at position p inside expiry cycle c cannot share realised path with the session
    # at position p inside cycle c+1, because cycle c's horizon ends at cycle c's expiry.
    panel = panel.copy()
    panel["pos_in_cycle"] = panel.groupby("cycle").cumcount()
    test_p = panel[panel["date"] >= test_start]
    train_p = panel[panel["date"] < test_start]
    results["non_overlapping_phases"] = {}
    for tgt in TARGETS:
        rv_col = "rv_incl" if tgt == "vrp_incl" else "rv_intra"
        for phase in range(5):
            tr = train_p[train_p["pos_in_cycle"] == phase]
            te = test_p[test_p["pos_in_cycle"] == phase]
            if len(te) < 20 or len(tr) < 60:
                continue
            bench = float(tr[tgt].mean())
            for m in ("MOD-02 HAR", "MOD-05 logRV HAR then subtract IV"):
                yhat = fit_predict(m, tr, te, tgt)
                ev = evaluate(te[tgt].to_numpy(), yhat, bench, 1, rng)
                ev["n_train"] = int(len(tr))
                results["non_overlapping_phases"][f"{tgt} | phase{phase} | {m}"] = ev

    # ---- how much of the target is the unforecastable overnight jump? ----
    tr, te = train_windows["A all prior"], test
    results["overnight_component"] = {}
    for nm, col in (("overnight share of total variance", "overnight_share"),):
        results["overnight_component"][nm] = {
            "mean": float(panel[col].mean()), "median": float(panel[col].median()),
            "p90": float(panel[col].quantile(0.90)),
        }
    # forecast the overnight-only annualised vol contribution
    on_te = np.sqrt(np.maximum(te["rv_incl"] ** 2 - te["rv_intra"] ** 2, 0.0))
    on_tr = np.sqrt(np.maximum(tr["rv_incl"] ** 2 - tr["rv_intra"] ** 2, 0.0))
    cols = ["rv1", "rv5", "rv22", "iv"]
    beta = ols_fit(tr[cols].to_numpy(float), on_tr.to_numpy())
    yhat = ols_predict(beta, te[cols].to_numpy(float))
    results["overnight_component"]["forecast_of_overnight_vol"] = {
        "oos_r2_vs_mean": oos_r2(on_te.to_numpy(), yhat, float(on_tr.mean())),
        "corr": float(np.corrcoef(on_te.to_numpy(), yhat)[0, 1]),
        "mean_train": float(on_tr.mean()), "mean_test": float(on_te.mean()),
    }

    # ---- MOD-06 VIX block on the reduced sample ----
    pv = panel.dropna(subset=["vix_open", "vix_on_gap"]).reset_index(drop=True)
    tr_v, te_v = pv[pv["date"] < test_start], pv[pv["date"] >= test_start]
    results["vix_block"]["n_train"] = int(len(tr_v))
    results["vix_block"]["n_test"] = int(len(te_v))
    for tgt in TARGETS:
        bench = float(tr_v[tgt].mean())
        for m in ("MOD-00 constant", "MOD-03 HAR+structure", "MOD-06 HAR+structure+VIX"):
            yhat = fit_predict(m, tr_v, te_v, tgt)
            results["vix_block"][f"{tgt} | {m}"] = evaluate(
                te_v[tgt].to_numpy(), yhat, bench, lags, rng)

    # ---- RV-LEVEL forecastability: the honest object behind ID-01 ----
    results["rv_level"] = {}
    for rv_col in ("rv_incl", "rv_intra"):
        tr, te = train_windows["A all prior"], test
        bench = float(tr[rv_col].mean())
        y = te[rv_col].to_numpy()
        blocks = {
            "IV alone (Canina-Figlewski regression)": ["iv"],
            "HAR alone (past RV only)": ["rv1", "rv5", "rv22"],
            "HAR + IV": ["rv1", "rv5", "rv22", "iv"],
        }
        for bname, cols in blocks.items():
            beta = ols_fit(np.log(tr[cols].to_numpy(float)), np.log(tr[rv_col].to_numpy()))
            yhat = np.exp(ols_predict(beta, np.log(te[cols].to_numpy(float))))
            results["rv_level"][f"{rv_col} | {bname}"] = {
                "oos_r2_vs_mean": oos_r2(y, yhat, bench),
                "corr": float(np.corrcoef(y, yhat)[0, 1]),
                "rmse": float(np.sqrt(np.mean((y - yhat) ** 2))),
                "rmse_bench": float(np.sqrt(np.mean((y - bench) ** 2))),
                "log_slopes": dict(zip(["const"] + cols, [float(b) for b in beta])),
            }

    # ---- per-horizon breakdown of the headline model ----
    results["by_horizon"] = {}
    tr = train_windows["A all prior"]
    for tgt in TARGETS:
        bench = float(tr[tgt].mean())
        rv_col = "rv_incl" if tgt == "vrp_incl" else "rv_intra"
        bench_b = float(tr[rv_col].mean())
        yhat_all = fit_predict("MOD-02 HAR", tr, test, tgt)
        for h in sorted(test["n_sess"].unique()):
            m = (test["n_sess"] == h).to_numpy()
            if m.sum() < 15:
                continue
            y = test[tgt].to_numpy()[m]
            results["by_horizon"][f"{tgt} | n_sess={int(h)}"] = {
                "n": int(m.sum()),
                "mean_vrp": float(y.mean()),
                "oos_r2_vs_MOD00": oos_r2(y, yhat_all[m], bench),
                "oos_r2_vs_MOD00b": oos_r2_vec(y, yhat_all[m], bench_b - test["iv"].to_numpy()[m]),
            }

    # ---- in-sample coefficients, for interpretation only ----
    for tgt in TARGETS:
        tr = train_windows["A all prior"]
        beta = ols_fit(tr[STRUCT].to_numpy(float), tr[tgt].to_numpy())
        yhat_in = ols_predict(beta, tr[STRUCT].to_numpy(float))
        results["in_sample_fits"][tgt] = {
            "coefficients": dict(zip(["const"] + STRUCT, [float(b) for b in beta])),
            "in_sample_r2": float(1 - np.sum((tr[tgt] - yhat_in) ** 2) / np.sum((tr[tgt] - tr[tgt].mean()) ** 2)),
        }

    # ---- audits ----
    results["audit"] = {
        "leakage_LEAK_01": "predictors rv1/rv5/rv22 use cumulative sums ending at index i "
                           "(exclusive of session i); gap uses previous close and the 09:15 "
                           "spot only; iv uses the 09:15 bar only",
        "calendar_time_maturity_used": False,
        "overnight_share_of_variance_mean": float(panel["overnight_share"].mean()),
        "iv_own_vs_vendor_corr": float(panel[["iv", "iv_vendor"]].dropna().corr().iloc[0, 1]),
        "iv_own_mean": float(panel["iv"].mean()),
        "iv_vendor_mean": float(panel["iv_vendor"].mean()),
    }
    return results


if __name__ == "__main__":
    panel = vfc.load_panel()
    res = run(panel)
    Path("vrp_forecast_results.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: res[k] for k in ("panel_n", "date_min", "date_max", "test_start",
                                          "test_n", "train_sizes", "nw_lags", "audit")},
                     indent=2, default=str))
    print("\n--- descriptives ---")
    print(json.dumps(res["descriptives"], indent=2))
    print("\n--- headline OOS R2 (target | train | model) ---")
    for k, v in res["evaluations"].items():
        print(f"{k:62s} R2={v['oos_r2']:+.4f}  rmse={v['rmse']:.3f} vs {v['rmse_bench']:.3f} "
              f"corr={v['corr']:+.3f}  R2vs00b={v['oos_r2_vs_MOD00b']:+.4f}  "
              f"placebo_p={v['placebo']['empirical_p']:.3f}")
    print("\n--- RV level forecastability ---")
    for k, v in res["rv_level"].items():
        print(f"{k:52s} R2={v['oos_r2_vs_mean']:+.4f} corr={v['corr']:+.3f} "
              f"rmse={v['rmse']:.3f} vs {v['rmse_bench']:.3f}")
    print("\n--- non-overlapping (one session per expiry cycle) ---")
    for k, v in res["non_overlapping"].items():
        if isinstance(v, dict):
            print(f"{k:52s} n={v['n']:3d} R2={v['oos_r2']:+.4f} R2vs00b={v['oos_r2_vs_MOD00b']:+.4f} "
                  f"placebo_p={v['placebo']['empirical_p']:.3f}")
    print("\n--- non-overlapping PHASES ---")
    for k, v in res["non_overlapping_phases"].items():
        print(f"{k:56s} ntr={v['n_train']:4d} n={v['n']:3d} R2={v['oos_r2']:+.4f} "
              f"placebo_p={v['placebo']['empirical_p']:.3f}")
    print("\n--- overnight component ---")
    print(json.dumps(res["overnight_component"], indent=2))
    print("\n--- economics: top tercile (A all prior, MOD-05) ---")
    for tgt in ("vrp_incl", "vrp_intra"):
        v = res["evaluations"][f"{tgt} | A all prior | MOD-05 logRV HAR then subtract IV"]
        print(f"{tgt}: bottom {v['tercile_bottom_mean']:+.2f}  top {v['tercile_top_mean']:+.2f}  "
              f"spread {v['tercile_spread']:+.2f}  share>0 all {v['share_positive_all']:.3f} "
              f"top {v['share_positive_top_tercile']:.3f}  forecast>0 {v['forecast_positive_share']:.3f} "
              f"NW t={v['dm_like_t_nw']:+.2f} p={v['dm_like_p_nw']:.4f}")
    print("\n--- by horizon ---")
    for k, v in res["by_horizon"].items():
        print(f"{k:34s} n={v['n']:3d} mean={v['mean_vrp']:+.2f} R2vs00={v['oos_r2_vs_MOD00']:+.4f} "
              f"R2vs00b={v['oos_r2_vs_MOD00b']:+.4f}")
