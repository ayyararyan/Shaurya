#!/usr/bin/env python3
"""Does ex-ante dealer Net Gamma Exposure predict intraday path quality on NIFTY?

New module.  It does not modify, and is not imported by, any pre-existing script.  Every
artifact it writes carries a new ``nge_`` filename.

The five tests, as briefed
--------------------------
1.  Each path-quality measure regressed on ex-ante NGE, with the CALL and PUT gamma-weighted
    open-interest legs entered as SEPARATE regressors with FREE coefficients, so the data
    -- not a US-calibrated assumption -- decides the effective Indian dealer position.
2.  The money test: the quartile ladder previously sorted on REALISED path quality, re-sorted
    on ex-ante NGE.
3.  Baltussen, Da, Lammers & Martens (2021) Table 7: last-half-hour return on rest-of-day
    return, split by the sign of NGE.
4.  Truncation sensitivity: NGE recomputed at chain widths +-3, 5, 7, 9, 10.
5.  Ahmed's critique: does NGE predict realised path quality INCREMENTALLY beyond the
    opening implied volatility?  A mechanism already priced by the option market is not an
    edge to a buyer of options.

Populations
-----------
Dealer gamma is a market-wide mechanism, not a property of the Gate-B signal, so the primary
population is every session in the archive.  Gate slices are secondary and never merged into
a headline.  An effect that ALSO appears on control days is confirming, not a failed placebo.

Offline analysis only.  No broker, credential, exchange network, or order path is used
anywhere in this module.  No live order exists or is authorised.
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

warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 20260823
RESULTS = Path("nge_path_quality_results.json")

# Primary construction: OTM-side implied volatility, TRADING-time maturity, +-10 strikes.
PRIMARY = "otm_trade_w10"

LABELS = {
    "rho1": "5-minute return autocorrelation (Barbon-Buraschi)",
    "r2_line": "straight-line R^2 of the minute path",
    "kaufman_er": "Kaufman Efficiency Ratio",
    "abs_disp_pct": "realised absolute displacement, %",
}

# Every hypothesis test run anywhere in this script is registered here for the multiplicity
# accounting in section 9.  Nothing is exempted.
REGISTRY: list[dict] = []


def register(family: str, name: str, p: float, extra: dict | None = None) -> None:
    REGISTRY.append({"family": family, "test": name, "p": float(p), **(extra or {})})


# ======================================================================================
# panel assembly
# ======================================================================================

def atm_open_close_pnl(snap: pd.DataFrame) -> pd.DataFrame:
    """Real traded 09:15 -> 15:29 P&L on the ATM CALL, ATM PUT and ATM straddle.

    Strike is the 09:15 at-the-money strike, held FIXED and looked up by ABSOLUTE value, so
    this does not repeat the rolling-``rel_strike`` defect documented in
    ``gate_b_flow_common.py``.  Entry and exit are traded one-minute bar CLOSES from the
    archive: model-free, no Black-Scholes anywhere in the number.

    This is the money variable on the FULL population.  The strike-tracked Gate-B trade
    (buy an ATM CALL at the gap-fill minute) is priced separately from the project's own
    path cache and is used for the gate slices.
    """
    op = snap[snap["clock"] == nc.SESSION_OPEN]
    cl = snap[snap["clock"] == nc.SESSION_LAST]
    op = op.assign(atm=(op["spot"] / nc.STRIKE_STEP).round() * nc.STRIKE_STEP)
    op = op[np.isclose(op["strike"], op["atm"])][["date", "side", "strike", "close", "iv"]]
    op = op.rename(columns={"close": "px_open", "iv": "iv_open"})
    m = op.merge(cl[["date", "side", "strike", "close"]].rename(columns={"close": "px_close"}),
                 on=["date", "side", "strike"], how="left")
    wide = m.pivot_table(index="date", columns="side",
                         values=["px_open", "px_close", "strike"], aggfunc="first")
    out = pd.DataFrame(index=wide.index)
    for side, tag in (("CALL", "call"), ("PUT", "put")):
        o = wide[("px_open", side)] if ("px_open", side) in wide else np.nan
        c = wide[("px_close", side)] if ("px_close", side) in wide else np.nan
        out[f"atm_{tag}_open"] = o
        out[f"atm_{tag}_close"] = c
        out[f"atm_{tag}_ret_pct"] = (c - o) / o * 100.0
    prem = out["atm_call_open"] + out["atm_put_open"]
    exit_ = out["atm_call_close"] + out["atm_put_close"]
    out["atm_straddle_prem"] = prem
    out["atm_straddle_ret_pct"] = (exit_ - prem) / prem * 100.0
    return out.reset_index()


def gate_b_trade_returns() -> pd.DataFrame:
    """The project's own Gate-B trade, priced on real strike-tracked traded premiums."""
    import gate_b_common as gbc
    import gate_b_full_paths as gbf

    paths = gbf.load_full_paths()
    gbc.reproduction_guard(gbc.gate_b_subset(paths))
    rows = []
    for p in paths:
        rows.append({
            "date": p["date"],
            "in_pool264": 1,
            "is_gate_b": int(p["is_gate_b"]),
            "pool_vix_rose": int(p["vix_rose"]),
            "gate_real_ret_pct": gbc.rule_return(p, "real_prices"),
            "gate_bs_ret_pct": gbc.rule_return(p, "bs_prices"),
            "gate_entry_minute": p["entry_minute"],
        })
    return pd.DataFrame(rows)


def build_panel() -> pd.DataFrame:
    daily = nc.load_daily()
    snap = nc.load_snapshot()
    daily = daily.merge(atm_open_close_pnl(snap), on="date", how="left")
    daily = daily.merge(gate_b_trade_returns(), on="date", how="left")
    for c in ("in_pool264", "is_gate_b", "pool_vix_rose"):
        daily[c] = daily[c].fillna(0).astype(int)

    # ---- regressor transforms, for every construction variant -------------------------
    for mode in nc.IV_MODES:
        for tname in ("trade", "cal"):
            for w in nc.CHAIN_WIDTHS:
                tag = f"{mode}_{tname}_w{w}"
                gc, gp = daily[f"gcall_{tag}"].to_numpy(), daily[f"gput_{tag}"].to_numpy()
                yr = daily["year"].to_numpy()
                daily[f"zC_{tag}"] = ns.zscore_by(np.log(np.where(gc > 0, gc, np.nan)), yr)
                daily[f"zP_{tag}"] = ns.zscore_by(np.log(np.where(gp > 0, gp, np.nan)), yr)
                daily[f"zGEX_{tag}"] = ns.zscore_by(daily[f"gex_{tag}"].to_numpy(), yr)
                daily[f"zGIMB_{tag}"] = ns.zscore_by(daily[f"gimb_{tag}"].to_numpy(), yr)
                daily[f"zGTOT_{tag}"] = ns.zscore_by(
                    np.log(np.where(gc + gp > 0, gc + gp, np.nan)), yr)
    daily["z_atm_iv"] = ns.zscore_by(daily["atm_iv_open"].to_numpy(), daily["year"].to_numpy())
    return daily


def populations(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    pool = panel[panel["in_pool264"] == 1]
    return {
        "ALL_SESSIONS": panel,
        "POOL264": pool,
        "FIRES120": pool[pool["pool_vix_rose"] == 1],
        "MIDIV33": pool[pool["is_gate_b"] == 1],
        "CONTROLS": pool[pool["pool_vix_rose"] == 0],
        "NONEXPIRY": panel[panel["is_expiry_day"] == 0],
        "EXPIRY": panel[panel["is_expiry_day"] == 1],
    }


# ======================================================================================
# TEST 1 -- path quality on ex-ante NGE, with FREE call/put coefficients
# ======================================================================================

SIGN_QUADRANTS = {
    # (sign b_C, sign b_P) -> what it implies, for rho1 as the dependent variable.
    ("-", "+"): "US convention holds AND the mechanism holds: dealers long calls / short "
                "puts, so call gamma stabilises (mean reversion) and put gamma destabilises "
                "(momentum).  Fitted vector anti-parallel to the GEX weights (+1,-1).",
    ("+", "-"): "INVERTED Indian dealer position: dealers effectively SHORT calls / LONG "
                "puts, consistent with a retail-option-selling market.  Fitted vector "
                "parallel to the GEX weights.",
    ("+", "+"): "No sign separation: both legs push path quality the same way.  Consistent "
                "with the regressors proxying total option-market size or activity, not "
                "with a directional dealer-gamma position.",
    ("-", "-"): "No sign separation, opposite direction.  Same reading as (+,+): a scale "
                "effect, not a gamma-position effect.",
}


def quadrant(bc: float, bp: float) -> str:
    return SIGN_QUADRANTS[("+" if bc >= 0 else "-", "+" if bp >= 0 else "-")]


def test1_regressions(pops: dict, tag: str = PRIMARY) -> dict:
    out: dict = {}
    for pname, df in pops.items():
        rows = []
        for dv in LABELS:
            y = df[dv].to_numpy(dtype=float)

            # (a) composite: standard-convention GEX, within-year z-scored
            r = ns.ols(y, df[f"zGEX_{tag}"].to_numpy())
            rows.append({"dv": dv, "spec": "gex_composite", "n": r["n"],
                         "beta": float(r["beta"][1]), "t": float(r["t_nw"][1]),
                         "p": float(r["p_nw"][1]), "r2_pct": 100 * float(r["r2"])})
            if pname in ("ALL_SESSIONS", "POOL264"):
                register("T1_composite", f"{pname}/{dv}/gex", r["p_nw"][1])

            # (b) normalised gamma imbalance -- scale-free, immune to lot size and to the
            #     secular growth in NIFTY option open interest
            r = ns.ols(y, df[f"zGIMB_{tag}"].to_numpy())
            rows.append({"dv": dv, "spec": "gamma_imbalance", "n": r["n"],
                         "beta": float(r["beta"][1]), "t": float(r["t_nw"][1]),
                         "p": float(r["p_nw"][1]), "r2_pct": 100 * float(r["r2"])})
            if pname in ("ALL_SESSIONS", "POOL264"):
                register("T1_imbalance", f"{pname}/{dv}/gimb", r["p_nw"][1])

            # (c) THE DESIGN POINT: free coefficients on the two legs
            X = np.column_stack([df[f"zC_{tag}"].to_numpy(), df[f"zP_{tag}"].to_numpy()])
            r = ns.ols(y, X)
            bc, bp = float(r["beta"][1]), float(r["beta"][2])
            rows.append({"dv": dv, "spec": "free_call_put", "n": r["n"],
                         "b_call": bc, "t_call": float(r["t_nw"][1]),
                         "p_call": float(r["p_nw"][1]),
                         "b_put": bp, "t_put": float(r["t_nw"][2]),
                         "p_put": float(r["p_nw"][2]),
                         "r2_pct": 100 * float(r["r2"]),
                         "sign_pattern": ("+" if bc >= 0 else "-") + ("+" if bp >= 0 else "-"),
                         "implies": quadrant(bc, bp)})
            if pname in ("ALL_SESSIONS", "POOL264"):
                register("T1_free", f"{pname}/{dv}/b_call", r["p_nw"][1])
                register("T1_free", f"{pname}/{dv}/b_put", r["p_nw"][2])

            # (d) free coefficients PLUS the total-gamma scale control, so the two legs are
            #     forced to speak about their IMBALANCE rather than about market size
            X = np.column_stack([df[f"zC_{tag}"].to_numpy(), df[f"zP_{tag}"].to_numpy(),
                                 df[f"zGTOT_{tag}"].to_numpy()])
            r = ns.ols(y, X)
            rows.append({"dv": dv, "spec": "free_call_put_plus_scale", "n": r["n"],
                         "b_call": float(r["beta"][1]), "t_call": float(r["t_nw"][1]),
                         "p_call": float(r["p_nw"][1]),
                         "b_put": float(r["beta"][2]), "t_put": float(r["t_nw"][2]),
                         "p_put": float(r["p_nw"][2]),
                         "r2_pct": 100 * float(r["r2"])})

            # Spearman, for comparability with the earlier association scans on this project
            m = np.isfinite(y) & np.isfinite(df[f"gimb_{tag}"].to_numpy())
            if m.sum() > 10:
                rho, p = stats.spearmanr(df[f"gimb_{tag}"].to_numpy()[m], y[m])
                rows.append({"dv": dv, "spec": "spearman_gimb", "n": int(m.sum()),
                             "beta": float(rho), "t": np.nan, "p": float(p),
                             "r2_pct": 100 * float(rho ** 2)})
        out[pname] = rows
    return out


# ======================================================================================
# TEST 2 -- the money test: the quartile ladder, sorted EX ANTE
# ======================================================================================

def quartile_ladder(df: pd.DataFrame, sort_col: str, ret_col: str, q: int = 4) -> dict:
    d = df[[sort_col, ret_col]].dropna()
    if len(d) < 4 * q:
        return {"n": int(len(d)), "insufficient": True}
    ranks = d[sort_col].rank(method="first")
    grp = pd.qcut(ranks, q, labels=False)
    rows = []
    for g in range(q):
        r = d[ret_col][grp == g].to_numpy()
        rows.append({"quartile": g + 1, "n": int(len(r)), "mean_pct": float(np.mean(r)),
                     "median_pct": float(np.median(r)),
                     "win_rate_pct": 100.0 * float(np.mean(r > 0)),
                     "sort_lo": float(d[sort_col][grp == g].min()),
                     "sort_hi": float(d[sort_col][grp == g].max())})
    lo = d[ret_col][grp == 0].to_numpy()
    hi = d[ret_col][grp == q - 1].to_numpy()
    tt = stats.ttest_ind(hi, lo, equal_var=False)
    means = [r["mean_pct"] for r in rows]
    mono_up = all(means[i] <= means[i + 1] for i in range(q - 1))
    mono_dn = all(means[i] >= means[i + 1] for i in range(q - 1))
    rho, prho = stats.spearmanr(d[sort_col], d[ret_col])
    return {"n": int(len(d)), "quartiles": rows,
            "spread_pct": float(means[-1] - means[0]),
            "spread_t": float(tt.statistic), "spread_p": float(tt.pvalue),
            "monotone": bool(mono_up or mono_dn),
            "monotone_direction": "increasing" if mono_up else ("decreasing" if mono_dn else "none"),
            "spearman_rho": float(rho), "spearman_p": float(prho)}


def test2_money(pops: dict, tag: str = PRIMARY) -> dict:
    out: dict = {}
    jobs = [
        ("ALL_SESSIONS", "atm_straddle_ret_pct", "ATM straddle, real traded 09:15 -> 15:29"),
        ("ALL_SESSIONS", "atm_call_ret_pct", "ATM CALL, real traded 09:15 -> 15:29"),
        ("ALL_SESSIONS", "atm_put_ret_pct", "ATM PUT, real traded 09:15 -> 15:29"),
        ("NONEXPIRY", "atm_straddle_ret_pct", "ATM straddle, non-expiry sessions only"),
        ("POOL264", "gate_real_ret_pct", "Gate-B trade, real strike-tracked premiums"),
        ("FIRES120", "gate_real_ret_pct", "Gate-B trade, the 120 pooled fires"),
        ("MIDIV33", "gate_real_ret_pct", "Gate-B trade, the published 33 mid-IV fires"),
        ("CONTROLS", "gate_real_ret_pct", "Gate-B trade, control days (vix_rose == 0)"),
    ]
    for pname, ret, desc in jobs:
        df = pops[pname]
        block = {"description": desc}
        for sort_name, sort_col in (("ex_ante_gimb", f"gimb_{tag}"),
                                    ("ex_ante_gex_z", f"zGEX_{tag}"),
                                    ("realised_r2_BENCHMARK", "r2_line"),
                                    ("realised_rho1_BENCHMARK", "rho1")):
            lad = quartile_ladder(df, sort_col, ret)
            block[sort_name] = lad
            if not lad.get("insufficient") and sort_name.startswith("ex_ante"):
                register("T2_money", f"{pname}/{ret}/{sort_name}", lad["spread_p"])
        out[f"{pname}::{ret}"] = block
    return out


# ======================================================================================
# TEST 3 -- Baltussen et al. (2021) Table 7
# ======================================================================================

def test3_baltussen(pops: dict, tag: str = PRIMARY) -> dict:
    out: dict = {}
    for pname in ("ALL_SESSIONS", "NONEXPIRY", "POOL264"):
        df = pops[pname]
        block: dict = {}
        for split_name, col, cut in (("sign_of_GEX", f"gex_{tag}", 0.0),
                                     ("sign_of_gamma_imbalance", f"gimb_{tag}", 0.0),
                                     ("median_gamma_imbalance", f"gimb_{tag}", None)):
            v = df[col].to_numpy(dtype=float)
            thr = float(np.nanmedian(v)) if cut is None else cut
            for side, m in (("gamma_high_(>=thr)", v >= thr), ("gamma_low_(<thr)", v < thr)):
                sub = df[m]
                r = ns.ols(sub["r_last30_pct"].to_numpy(), sub["r_rod_pct"].to_numpy())
                block[f"{split_name}::{side}"] = {
                    "n": r["n"], "threshold": thr,
                    "beta_x100": 100 * float(r["beta"][1]),
                    "t_nw": float(r["t_nw"][1]), "p_nw": float(r["p_nw"][1]),
                    "r2_pct": 100 * float(r["r2"]),
                }
                if pname == "ALL_SESSIONS":
                    register("T3_baltussen", f"{pname}/{split_name}/{side}", r["p_nw"][1])
        # Table 8 continuous version: interact scaled NGE with the rest-of-day return
        x1 = df["r_rod_pct"].to_numpy()
        x2 = df[f"gimb_{tag}"].to_numpy()
        r = ns.ols(df["r_last30_pct"].to_numpy(), np.column_stack([x1, x2, x1 * x2]))
        block["table8_interaction"] = {
            "n": r["n"], "beta_rod": float(r["beta"][1]), "t_rod": float(r["t_nw"][1]),
            "beta_gimb": float(r["beta"][2]), "t_gimb": float(r["t_nw"][2]),
            "beta_interaction": float(r["beta"][3]), "t_interaction": float(r["t_nw"][3]),
            "p_interaction": float(r["p_nw"][3]), "r2_pct": 100 * float(r["r2"]),
        }
        if pname == "ALL_SESSIONS":
            register("T3_baltussen", f"{pname}/table8_interaction", r["p_nw"][3])
        out[pname] = block
    return out


# ======================================================================================
# TEST 4 -- truncation sensitivity
# ======================================================================================

def test4_truncation(pops: dict) -> dict:
    df = pops["ALL_SESSIONS"]
    out: dict = {"convergence": [], "rank_agreement": {}, "level": []}
    ref = f"gimb_otm_trade_w10"
    for mode in nc.IV_MODES:
        for tname in ("trade", "cal"):
            for w in nc.CHAIN_WIDTHS:
                tag = f"{mode}_{tname}_w{w}"
                for dv in LABELS:
                    r = ns.ols(df[dv].to_numpy(), df[f"zGIMB_{tag}"].to_numpy())
                    out["convergence"].append({
                        "iv_mode": mode, "maturity": tname, "width": w, "dv": dv,
                        "n": r["n"], "beta": float(r["beta"][1]), "t": float(r["t_nw"][1]),
                        "p": float(r["p_nw"][1]), "r2_pct": 100 * float(r["r2"])})
                    if mode == "otm" and tname == "trade":
                        register("T4_truncation", f"w{w}/{dv}", r["p_nw"][1])
                a = df[f"gimb_{tag}"].to_numpy()
                b = df[ref].to_numpy()
                m = np.isfinite(a) & np.isfinite(b)
                out["rank_agreement"][tag] = {
                    "spearman_vs_w10_otm_trade": float(stats.spearmanr(a[m], b[m]).statistic),
                    "pearson_vs_w10_otm_trade": float(np.corrcoef(a[m], b[m])[0, 1]),
                    "sign_agreement_pct": 100.0 * float(np.mean(np.sign(a[m]) == np.sign(b[m]))),
                }
                out["level"].append({
                    "iv_mode": mode, "maturity": tname, "width": w,
                    "mean_gimb": float(np.nanmean(a)), "median_gimb": float(np.nanmedian(a)),
                    "share_gex_negative_pct": 100.0 * float(
                        np.nanmean(df[f"gex_{tag}"].to_numpy() < 0)),
                    "mean_gcall": float(np.nanmean(df[f"gcall_{tag}"])),
                    "mean_gput": float(np.nanmean(df[f"gput_{tag}"])),
                })
    # width-to-width increments on the primary construction: does the estimate settle?
    prim = [r for r in out["convergence"] if r["iv_mode"] == "otm" and r["maturity"] == "trade"]
    for dv in LABELS:
        seq = [r for r in prim if r["dv"] == dv]
        seq.sort(key=lambda r: r["width"])
        out.setdefault("increments", {})[dv] = [
            {"from_w": seq[i]["width"], "to_w": seq[i + 1]["width"],
             "d_beta": seq[i + 1]["beta"] - seq[i]["beta"],
             "d_beta_rel_pct": 100.0 * (seq[i + 1]["beta"] - seq[i]["beta"])
                               / abs(seq[i]["beta"]) if seq[i]["beta"] else np.nan}
            for i in range(len(seq) - 1)]
    return out


# ======================================================================================
# TEST 5 -- Ahmed's critique: incremental to implied volatility?
# ======================================================================================

def test5_ahmed(pops: dict, tag: str = PRIMARY) -> dict:
    out: dict = {}
    for pname in ("ALL_SESSIONS", "NONEXPIRY", "POOL264"):
        df = pops[pname]
        rows = []
        for dv in LABELS:
            y = df[dv].to_numpy(dtype=float)
            g = df[f"zGIMB_{tag}"].to_numpy()
            iv = df["z_atm_iv"].to_numpy()
            r_g = ns.ols(y, g)
            r_iv = ns.ols(y, iv)
            r_both = ns.ols(y, np.column_stack([g, iv]))
            rows.append({
                "dv": dv, "n": r_both["n"],
                "gamma_alone_beta": float(r_g["beta"][1]), "gamma_alone_t": float(r_g["t_nw"][1]),
                "gamma_alone_p": float(r_g["p_nw"][1]), "gamma_alone_r2_pct": 100 * float(r_g["r2"]),
                "iv_alone_beta": float(r_iv["beta"][1]), "iv_alone_t": float(r_iv["t_nw"][1]),
                "iv_alone_p": float(r_iv["p_nw"][1]), "iv_alone_r2_pct": 100 * float(r_iv["r2"]),
                "gamma_ctrl_beta": float(r_both["beta"][1]), "gamma_ctrl_t": float(r_both["t_nw"][1]),
                "gamma_ctrl_p": float(r_both["p_nw"][1]),
                "iv_ctrl_beta": float(r_both["beta"][2]), "iv_ctrl_t": float(r_both["t_nw"][2]),
                "iv_ctrl_p": float(r_both["p_nw"][2]),
                "joint_r2_pct": 100 * float(r_both["r2"]),
                "incremental_r2_pct": 100 * float(r_both["r2"] - r_iv["r2"]),
                "attenuation_pct": 100.0 * (1.0 - abs(float(r_both["beta"][1]))
                                            / max(abs(float(r_g["beta"][1])), 1e-12)),
            })
            if pname == "ALL_SESSIONS":
                register("T5_ahmed", f"{pname}/{dv}/gamma_given_iv", r_both["p_nw"][1])
        out[pname] = rows

    # The variable a BUYER of options actually needs: realised minus implied.
    df = pops["ALL_SESSIONS"]
    sess = df["sessions_to_expiry"].to_numpy(dtype=float)
    iv_day = df["atm_iv_open"].to_numpy(dtype=float) / 100.0 / np.sqrt(252.0) * 100.0
    rv_day = df["rv_pct"].to_numpy(dtype=float)
    spread = rv_day - iv_day
    df = df.assign(iv_daily_pct=iv_day, rv_minus_iv=spread)
    block = {"definition": "realised 5-min session volatility, %, minus the opening ATM "
                           "implied volatility rescaled to one trading day (iv/sqrt(252)); "
                           "positive means the session delivered more movement than the "
                           "option market charged for at the open",
             "mean_rv_pct": float(np.nanmean(rv_day)),
             "mean_iv_daily_pct": float(np.nanmean(iv_day)),
             "mean_spread_pct": float(np.nanmean(spread)),
             "share_spread_positive_pct": 100.0 * float(np.nanmean(spread > 0))}
    for regname, col in (("gamma_imbalance", f"zGIMB_{tag}"), ("gex_z", f"zGEX_{tag}")):
        r = ns.ols(spread, df[col].to_numpy())
        block[regname] = {"n": r["n"], "beta": float(r["beta"][1]), "t": float(r["t_nw"][1]),
                          "p": float(r["p_nw"][1]), "r2_pct": 100 * float(r["r2"])}
        register("T5_ahmed", f"rv_minus_iv/{regname}", r["p_nw"][1])
    X = np.column_stack([df[f"zC_{tag}"].to_numpy(), df[f"zP_{tag}"].to_numpy()])
    r = ns.ols(spread, X)
    block["free_call_put"] = {
        "n": r["n"], "b_call": float(r["beta"][1]), "t_call": float(r["t_nw"][1]),
        "p_call": float(r["p_nw"][1]), "b_put": float(r["beta"][2]),
        "t_put": float(r["t_nw"][2]), "p_put": float(r["p_nw"][2]),
        "r2_pct": 100 * float(r["r2"])}
    block["quartile_ladder_on_spread"] = quartile_ladder(df, f"gimb_{tag}", "rv_minus_iv")
    out["realised_minus_implied"] = block
    return out


# ======================================================================================
# PLACEBO -- best-of-grid under a coherent day permutation
# ======================================================================================

GRID_SPECS = ("gex_composite", "gamma_imbalance", "free_call_put")


def _grid_best(df: pd.DataFrame, perm: np.ndarray | None = None) -> dict:
    """Smallest p-value and largest |t| anywhere in the association grid.

    The grid is ALL_SESSIONS x 4 path-quality labels x 5 chain widths x 3 specifications =
    60 cells.  ``perm`` reindexes the NGE regressor block ONLY -- the dependent variables
    keep their own dates -- so a permutation destroys the day alignment of dealer gamma
    while leaving every other feature of both series intact.
    """
    best_p, best_t, best_cell = 1.0, 0.0, None
    for w in nc.CHAIN_WIDTHS:
        tag = f"otm_trade_w{w}"
        cols = {k: df[f"{k}_{tag}"].to_numpy(dtype=float)
                for k in ("zGEX", "zGIMB", "zC", "zP")}
        if perm is not None:
            cols = {k: v[perm] for k, v in cols.items()}
        for dv in LABELS:
            y = df[dv].to_numpy(dtype=float)
            cands = [
                ("gex_composite", ns.ols(y, cols["zGEX"]), 1),
                ("gamma_imbalance", ns.ols(y, cols["zGIMB"]), 1),
                ("free_call_put", ns.ols(y, np.column_stack([cols["zC"], cols["zP"]])), None),
            ]
            for spec, r, j in cands:
                idxs = [1] if j == 1 else [1, 2]
                for i in idxs:
                    p, t = float(r["p_nw"][i]), abs(float(r["t_nw"][i]))
                    if p < best_p:
                        best_p, best_cell = p, f"w{w}/{dv}/{spec}/b{i}"
                    best_t = max(best_t, t)
    return {"best_p": best_p, "best_abs_t": best_t, "best_cell": best_cell}


def placebo(pops: dict, draws: int = 2000) -> dict:
    df = pops["ALL_SESSIONS"].reset_index(drop=True)
    n = len(df)
    obs = _grid_best(df)
    rng = np.random.default_rng(SEED)

    out = {"grid_cells": len(nc.CHAIN_WIDTHS) * len(LABELS) * 4, "draws": draws,
           "observed": obs}
    for scheme in ("circular_rotation", "random_shuffle"):
        ps, ts = [], []
        for _ in range(draws):
            if scheme == "circular_rotation":
                # COHERENT permutation: rotate the whole NGE series by a random offset.  This
                # preserves its very strong day-to-day autocorrelation and its secular trend
                # -- a plain shuffle destroys both and would make the placebo far too easy to
                # beat, overstating any observed result.
                k = int(rng.integers(1, n))
                perm = np.roll(np.arange(n), k)
            else:
                perm = rng.permutation(n)
            b = _grid_best(df, perm)
            ps.append(b["best_p"])
            ts.append(b["best_abs_t"])
        ps, ts = np.asarray(ps), np.asarray(ts)
        out[scheme] = {
            "placebo_median_best_p": float(np.median(ps)),
            "placebo_5th_pct_best_p": float(np.percentile(ps, 5)),
            "empirical_p_for_best_p": float(np.mean(ps <= obs["best_p"])),
            "placebo_median_best_abs_t": float(np.median(ts)),
            "placebo_95th_pct_best_abs_t": float(np.percentile(ts, 95)),
            "empirical_p_for_best_abs_t": float(np.mean(ts >= obs["best_abs_t"])),
            "share_of_draws_with_a_raw_hit_pct": 100.0 * float(np.mean(ps < 0.05)),
        }
    return out


def money_placebo(pops: dict, tag: str = PRIMARY, draws: int = 2000) -> dict:
    """Best-of-grid quartile spread under the same coherent permutation."""
    jobs = [("ALL_SESSIONS", "atm_straddle_ret_pct"), ("ALL_SESSIONS", "atm_call_ret_pct"),
            ("ALL_SESSIONS", "atm_put_ret_pct"), ("POOL264", "gate_real_ret_pct"),
            ("FIRES120", "gate_real_ret_pct")]
    frames = {p: pops[p].reset_index(drop=True) for p, _ in jobs}
    rng = np.random.default_rng(SEED + 1)

    def best(perm_by_pop) -> float:
        b = 0.0
        for pname, ret in jobs:
            d = frames[pname]
            s = d[f"gimb_{tag}"].to_numpy(dtype=float)
            if perm_by_pop is not None:
                s = s[perm_by_pop[pname]]
            lad = quartile_ladder(d.assign(_s=s), "_s", ret)
            if not lad.get("insufficient"):
                b = max(b, abs(lad["spread_pct"]))
        return b

    obs = best(None)
    draws_out = []
    for _ in range(draws):
        pm = {}
        for pname in frames:
            m = len(frames[pname])
            pm[pname] = np.roll(np.arange(m), int(rng.integers(1, m)))
        draws_out.append(best(pm))
    d = np.asarray(draws_out)
    return {"jobs": [f"{p}::{r}" for p, r in jobs],
            "observed_best_abs_spread_pct": float(obs),
            "placebo_median_pct": float(np.median(d)),
            "placebo_95th_pct": float(np.percentile(d, 95)),
            "empirical_p": float(np.mean(d >= obs)), "draws": draws}


# ======================================================================================
# POWER
# ======================================================================================

def power(pops: dict) -> dict:
    out = {"association": [], "pnl": []}
    for pname, df in pops.items():
        for dv in LABELS:
            n = int(np.isfinite(df[dv].to_numpy(dtype=float)).sum())
            out["association"].append({
                "population": pname, "dv": dv, "n": n,
                "smallest_detectable_abs_r_at_80pct_power": ns.detectable_r(n)})
    for pname, ret in (("ALL_SESSIONS", "atm_straddle_ret_pct"),
                       ("ALL_SESSIONS", "atm_call_ret_pct"),
                       ("POOL264", "gate_real_ret_pct"),
                       ("FIRES120", "gate_real_ret_pct"),
                       ("MIDIV33", "gate_real_ret_pct")):
        r = pops[pname][ret].to_numpy(dtype=float)
        r = r[np.isfinite(r)]
        n, sd = len(r), float(np.std(r, ddof=1)) if len(r) > 2 else np.nan
        q = n // 4
        out["pnl"].append({
            "population": pname, "series": ret, "n": n, "sd_pct": sd,
            "mean_pct": float(np.mean(r)) if n else np.nan,
            "ci95_pct": [float(np.mean(r) - 1.96 * sd / np.sqrt(n)),
                         float(np.mean(r) + 1.96 * sd / np.sqrt(n))] if n > 2 else None,
            "smallest_detectable_mean_pct": ns.detectable_mean(sd, n),
            "quartile_n": q,
            "smallest_detectable_quartile_spread_pct": ns.detectable_mean(sd * np.sqrt(2), q),
        })
    return out


# ======================================================================================
# MULTIPLICITY
# ======================================================================================

def multiplicity() -> dict:
    ps = [r["p"] for r in REGISTRY]
    overall = ns.bonferroni_bh(ps)
    by_family = {}
    for fam in sorted({r["family"] for r in REGISTRY}):
        fp = [r["p"] for r in REGISTRY if r["family"] == fam]
        by_family[fam] = ns.bonferroni_bh(fp)
    reg = sorted(REGISTRY, key=lambda r: r["p"])
    return {"registered_tests": len(REGISTRY), "overall": overall, "by_family": by_family,
            "ten_smallest_p": reg[:10]}


# ======================================================================================
# DESCRIPTIVES + data audits
# ======================================================================================

def descriptives(panel: pd.DataFrame, pops: dict, tag: str = PRIMARY) -> dict:
    out: dict = {}
    out["coverage"] = {
        "sessions": int(len(panel)),
        "date_range": [panel["date"].min(), panel["date"].max()],
        "expiry_day_sessions": int(panel["is_expiry_day"].sum()),
        "sessions_per_population": {k: int(len(v)) for k, v in pops.items()},
        "median_strikes_in_0915_chain": float(panel["n_strikes"].median()),
        "median_sessions_to_expiry": float(panel["sessions_to_expiry"].median()),
    }
    out["path_quality_labels"] = {
        dv: {"mean": float(panel[dv].mean()), "median": float(panel[dv].median()),
             "sd": float(panel[dv].std()), "p10": float(panel[dv].quantile(0.10)),
             "p90": float(panel[dv].quantile(0.90)),
             "share_positive_pct": 100.0 * float((panel[dv] > 0).mean())}
        for dv in LABELS}
    corr = panel[list(LABELS) + ["vr3", "rv_pct"]].corr(method="spearman")
    out["label_cross_correlation_spearman"] = json.loads(corr.to_json())
    g = panel[f"gimb_{tag}"]
    out["nge"] = {
        "gamma_imbalance_mean": float(g.mean()), "median": float(g.median()),
        "sd": float(g.std()),
        "share_positive_pct": 100.0 * float((g > 0).mean()),
        "gex_share_negative_pct": 100.0 * float((panel[f"gex_{tag}"] < 0).mean()),
        "mean_gcall": float(panel[f"gcall_{tag}"].mean()),
        "mean_gput": float(panel[f"gput_{tag}"].mean()),
        "autocorrelation_lag1": float(panel[f"gimb_{tag}"].autocorr(1)),
        "autocorrelation_lag5": float(panel[f"gimb_{tag}"].autocorr(5)),
        "by_year": json.loads(panel.groupby("year")[[f"gimb_{tag}", f"gex_{tag}",
                                                     "atm_iv_open"]].mean().to_json()),
        "by_sessions_to_expiry": json.loads(
            panel.groupby(panel["sessions_to_expiry"].clip(upper=6))[f"gimb_{tag}"]
            .agg(["mean", "median", "size"]).to_json()),
    }
    out["money_series"] = {
        c: {"n": int(panel[c].notna().sum()), "mean_pct": float(panel[c].mean()),
            "median_pct": float(panel[c].median()), "sd_pct": float(panel[c].std()),
            "win_rate_pct": 100.0 * float((panel[c] > 0).mean())}
        for c in ("atm_call_ret_pct", "atm_put_ret_pct", "atm_straddle_ret_pct")}
    # loss per minute held, for comparability across the differing holding periods
    out["money_series"]["holding_minutes"] = {
        "atm_open_to_close": 374, "gate_b_trade_median": float(
            (929 - pops["POOL264"]["gate_entry_minute"]).median())}
    return out


def oi_staleness_audit(sample_years: tuple[str, ...] = ("2021", "2023", "2025")) -> dict:
    """Is the 09:15 open-interest reading a carried-forward PRIOR-SESSION figure?

    Decisive check for the ex-ante claim.  Reads full-day open interest for a sample of
    windows and asks three questions: does oi(09:15) equal oi(09:16); how far is oi(09:15)
    from the PREVIOUS session's close; and how far is it from its OWN session's close.
    """
    rows = nc.manifest_rows()
    sub = [r for r in rows if str(r["from_date"])[:4] in sample_years
           and str(r["from_date"])[5:7] in ("03", "09")]
    frames = []
    for r in sub:
        p = nc.cached_path(r)
        if not p.exists():
            continue
        f = pd.read_csv(p, usecols=["datetime", "strike", "oi", "close"])
        f["side"] = r["drv_option_type"]
        frames.append(f)
    q = pd.concat(frames, ignore_index=True)
    q["clock"] = q["datetime"].str.slice(11, 16)
    q["date"] = q["datetime"].str.slice(0, 10)
    q = q[q["close"] > 0]
    q = q.sort_values(["date", "side", "strike", "clock"]).drop_duplicates(
        ["date", "side", "strike", "clock"])

    piv = q.pivot_table(index=["date", "side", "strike"], columns="clock", values="oi",
                        aggfunc="first")
    have = [c for c in ("09:15", "09:16", "09:20", "10:00", "15:29") if c in piv.columns]
    piv = piv[have].dropna(subset=["09:15"])
    res = {"contract_days": int(len(piv)), "windows_read": len(sub)}
    for c in have[1:]:
        d = piv.dropna(subset=[c])
        res[f"share_oi_0915_equals_{c.replace(':','')}_pct"] = round(
            100.0 * float((d["09:15"] == d[c]).mean()), 2)

    op = piv.reset_index()[["date", "side", "strike", "09:15"]].rename(columns={"09:15": "o"})
    cl = piv.reset_index()[["date", "side", "strike", "15:29"]].rename(columns={"15:29": "c"})
    dates = sorted(op["date"].unique())
    prev = {d: p for p, d in zip(dates[:-1], dates[1:])}
    op["prev"] = op["date"].map(prev)
    m = op.merge(cl, on=["date", "side", "strike"], how="inner")
    m = m.merge(cl.rename(columns={"date": "prev", "c": "c_prev"}),
                on=["prev", "side", "strike"], how="inner")
    m = m[(m["c_prev"] > 0) & (m["c"] > 0)]
    res["matched_contract_days"] = int(len(m))
    res["median_abs_pct_0915_vs_PRIOR_close"] = round(
        100.0 * float((m["o"] / m["c_prev"] - 1).abs().median()), 3)
    res["median_abs_pct_0915_vs_OWN_close"] = round(
        100.0 * float((m["o"] / m["c"] - 1).abs().median()), 3)
    res["verdict"] = (
        "09:15 open interest tracks the PRIOR session's close and not its own; "
        "the measure is ex ante."
        if res["median_abs_pct_0915_vs_PRIOR_close"] < res["median_abs_pct_0915_vs_OWN_close"] / 3
        else "INCONCLUSIVE -- 09:15 open interest is not clearly a prior-session quantity.")
    return res


def gamma_invariance_check(panel: pd.DataFrame) -> dict:
    """How much does the maturity convention actually move the gamma weights?

    Black-Scholes gamma depends on (sigma, T) essentially through sigma*sqrt(T).  The archive
    quotes an implied volatility that was inverted under SOME convention; pairing it with a
    trading-time T rescales sigma*sqrt(T) by sqrt(365/252) ~ 1.204 and therefore flattens the
    gamma profile across strikes.  It is a real change, but if the CROSS-SECTIONAL ranking of
    days survives it, the truncation and sign conclusions do not depend on the choice.
    """
    out = {}
    for w in nc.CHAIN_WIDTHS:
        a = panel[f"gimb_otm_trade_w{w}"].to_numpy()
        b = panel[f"gimb_otm_cal_w{w}"].to_numpy()
        c = panel[f"gimb_own_trade_w{w}"].to_numpy()
        m = np.isfinite(a) & np.isfinite(b) & np.isfinite(c)
        out[f"w{w}"] = {
            "spearman_trading_vs_calendar": float(stats.spearmanr(a[m], b[m]).statistic),
            "spearman_otm_iv_vs_own_iv": float(stats.spearmanr(a[m], c[m]).statistic),
            "mean_gimb_trading": float(np.nanmean(a)), "mean_gimb_calendar": float(np.nanmean(b)),
            "mean_gimb_own_iv": float(np.nanmean(c)),
        }
    return out


# ======================================================================================
# runner
# ======================================================================================

def main() -> None:
    panel = build_panel()
    panel.to_csv("nge_panel.csv", index=False)
    pops = populations(panel)

    print(f"panel: {len(panel)} sessions {panel['date'].min()} .. {panel['date'].max()}")
    for k, v in pops.items():
        print(f"  {k:14s} N={len(v)}")

    results: dict = {
        "meta": {
            "primary_construction": PRIMARY,
            "primary_construction_note":
                "OTM-side per-contract implied volatility supplies Gamma(K); TRADING-time "
                "maturity (375 min/session, 252 sessions/year); chain width +-10 strikes; "
                "risk-free rate 6.5%; NO lot-size multiplier applied (see the report).",
            "seed": SEED,
        },
        "descriptives": descriptives(panel, pops),
        "audit_oi_staleness": oi_staleness_audit(),
        "audit_ex_ante_full": nc.audit_ex_ante(nc.load_snapshot()),
        "audit_gamma_invariance": gamma_invariance_check(panel),
    }
    print("descriptives + audits done")

    results["test1_regressions"] = test1_regressions(pops)
    print("test 1 done")
    results["test2_money"] = test2_money(pops)
    print("test 2 done")
    results["test3_baltussen"] = test3_baltussen(pops)
    print("test 3 done")
    results["test4_truncation"] = test4_truncation(pops)
    print("test 4 done")
    results["test5_ahmed"] = test5_ahmed(pops)
    print("test 5 done")

    results["placebo_association"] = placebo(pops, draws=2000)
    print("association placebo done")
    results["placebo_money"] = money_placebo(pops, draws=2000)
    print("money placebo done")

    results["power"] = power(pops)
    results["multiplicity"] = multiplicity()
    results["registry"] = REGISTRY

    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.bool_,)):
            return bool(o)
        return str(o)

    RESULTS.write_text(json.dumps(results, indent=2, default=default))
    print(f"wrote {RESULTS} ({RESULTS.stat().st_size/1024:.0f} KB)")
    print(f"registered tests: {len(REGISTRY)}")
    print(json.dumps(results["multiplicity"]["overall"], indent=2, default=default))


if __name__ == "__main__":
    main()
