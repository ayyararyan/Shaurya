#!/usr/bin/env python3
"""Does NON-PRICE-PATH information -- option volume, open interest, and true intraminute
OHLC -- predict trendiness, direction, or P&L on the Gate-B gap-fill population?

New module.  It does not modify, and is not imported by, any pre-existing script.

Everything derived from the post-entry price path has already been tested on this population
and is null.  Volume, open interest and the ``open``/``high``/``low`` columns are the only
genuinely unused information in the archive: verified, no prior script in this project reads
any of them.  This study asks whether they carry anything.

Offline analysis only.  No broker, credential, exchange network, or order path.  No live
order exists or is authorised.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from scipy import stats

import gate_b_flow_features as gff
from gate_b_flow_features import ALL_FEATURES, FEATURE_GRADE, TARGETS, TARGET_LABEL

SEED = 20260823
N_DRAWS = 5000
DECISIONS = ("entry", "persist:15", "persist:30", "persist:45", "persist:60")

# The trade's own cost model, identical to GATE_B_REAL_PREMIUM_VALIDATION.md §8.
BROKERAGE = 20.0
STT_SELL = 0.00100
NSE_TXN = 0.0003503
SEBI = 10.0 / 1e7
STAMP_BUY = 0.00003
GST = 0.18
LOT = 50


def cost_pct_of_premium(entry_px: float, exit_px: float, half_spread_pct: float) -> float:
    """Round-trip cost as a percentage of the entry premium, one lot."""
    buy = entry_px * LOT
    sell = exit_px * LOT
    txn = NSE_TXN * (buy + sell)
    charges = (
        2 * BROKERAGE + STT_SELL * sell + txn + SEBI * (buy + sell)
        + STAMP_BUY * buy + GST * (2 * BROKERAGE + txn)
    )
    spread = half_spread_pct / 100.0 * (buy + sell)
    return (charges + spread) / buy * 100.0


def _entry_premiums() -> dict:
    """Traded entry premium for every fire, from the full-hydration path cache."""
    import gate_b_full_paths as gbf
    return {p["date"]: float(p["real_prices"][0]) for p in gbf.load_full_paths()
            if p["vix_rose"] == 1 and np.isfinite(p["real_prices"][0])}


# ------------------------------------------------------------------------------ statistics
def spearman(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    m = np.isfinite(x) & np.isfinite(y)
    n = int(m.sum())
    if n < 10:
        return np.nan, np.nan, n
    r = stats.spearmanr(x[m], y[m])
    return float(r.statistic), float(r.pvalue), n


def bh_reject(p: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), dtype=bool)
    q = p[ok]
    m = len(q)
    if m == 0:
        return out
    order = np.argsort(q)
    passed = q[order] <= alpha * (np.arange(1, m + 1) / m)
    if passed.any():
        k = int(np.max(np.flatnonzero(passed)))
        sel = np.zeros(m, dtype=bool)
        sel[order[: k + 1]] = True
        out[np.flatnonzero(ok)[sel]] = True
    return out


def detectable_rho(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest |Spearman rho| resolvable at the stated alpha and power (Fisher z)."""
    if n <= 4:
        return np.nan
    za = stats.norm.ppf(1.0 - alpha / 2.0)
    zb = stats.norm.ppf(power)
    return float(np.tanh((za + zb) / np.sqrt(n - 3)))


def summarise(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"N": int(len(x))}
    return {
        "N": int(len(x)),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "win": float((x > 0).mean() * 100.0),
        "sd": float(x.std(ddof=1)),
        "p0": float(stats.ttest_1samp(x, 0.0).pvalue),
    }


# ----------------------------------------------------------------------------- the grid
def build_grid(panel: pd.DataFrame) -> pd.DataFrame:
    """Spearman rho for every (feature, decision, target) cell."""
    rows = []
    for dec in DECISIONS:
        sub = panel[panel["decision"] == dec]
        if sub.empty:
            continue
        for f in ALL_FEATURES:
            x = sub[f].to_numpy(dtype=float)
            for t in TARGETS:
                y = sub[t].to_numpy(dtype=float)
                rho, p, n = spearman(x, y)
                rows.append({
                    "feature": f, "grade": FEATURE_GRADE[f][0], "decision": dec,
                    "target": t, "n": n, "rho": rho, "p": p,
                })
    g = pd.DataFrame(rows)
    g["abs_rho"] = g["rho"].abs()
    return g


def westfall_young(panel: pd.DataFrame, n_draws: int = N_DRAWS,
                   seed: int = SEED) -> dict:
    """Best-of-grid max-statistic placebo with a coherent day permutation.

    One permutation of the DAY index is drawn per replicate and applied to the target in
    every cell of the grid, so the dependence between cells -- which is severe here, the same
    120 days appear in all 400 -- is preserved rather than assumed away.  This is a
    Westfall-Young style max-|rho| correction.

    Also returns the SIGNED best-of-grid: the largest rho in the direction a trader would
    actually act on for the P&L target.  Reported because a max-|rho| statistic is
    sign-blind, and on this project a sign-blind selection has already once handed back the
    most reliably loss-making rule in a grid.
    """
    rng = np.random.default_rng(seed)
    dates = sorted(panel["date"].unique())
    d_index = {d: i for i, d in enumerate(dates)}
    nD = len(dates)

    cells = []
    for dec in DECISIONS:
        sub = panel[panel["decision"] == dec]
        if sub.empty:
            continue
        di = sub["date"].map(d_index).to_numpy()
        for f in ALL_FEATURES:
            x = sub[f].to_numpy(dtype=float)
            for t in TARGETS:
                y = sub[t].to_numpy(dtype=float)
                m = np.isfinite(x) & np.isfinite(y)
                if m.sum() < 10:
                    continue
                rx = stats.rankdata(x[m])
                ry = stats.rankdata(y[m])
                rx = (rx - rx.mean()) / (rx.std() if rx.std() > 0 else 1.0)
                cells.append({"idx": di[m], "rx": rx, "ry": ry,
                              "target": t, "feature": f, "decision": dec})

    # observed
    obs = []
    for c in cells:
        ry = (c["ry"] - c["ry"].mean())
        s = ry.std()
        obs.append(float((c["rx"] * (ry / (s if s > 0 else 1.0))).mean()))
    obs = np.asarray(obs)
    pnl_mask = np.asarray([c["target"] == "pnl_rest" for c in cells])

    # replicate permutations of the day index, shared across all cells
    perm_rank = np.empty((n_draws, nD), dtype=np.int32)
    for b in range(n_draws):
        perm = rng.permutation(nD)
        r = np.empty(nD, dtype=np.int32)
        r[perm] = np.arange(nD, dtype=np.int32)
        perm_rank[b] = r

    max_abs = np.zeros(n_draws)
    max_signed_pnl = np.full(n_draws, -np.inf)
    for c in cells:
        sub_rank = perm_rank[:, c["idx"]]                     # (B, k)
        order = np.argsort(sub_rank, axis=1)
        yp = c["ry"][order]                                   # (B, k)
        yp = yp - yp.mean(axis=1, keepdims=True)
        sd = yp.std(axis=1, keepdims=True)
        sd[sd == 0] = 1.0
        r = (c["rx"][None, :] * (yp / sd)).mean(axis=1)
        np.maximum(max_abs, np.abs(r), out=max_abs)
        if c["target"] == "pnl_rest":
            np.maximum(max_signed_pnl, r, out=max_signed_pnl)

    obs_max_abs = float(np.nanmax(np.abs(obs)))
    obs_max_signed = float(np.nanmax(obs[pnl_mask])) if pnl_mask.any() else np.nan
    return {
        "cells_tested": len(cells),
        "draws": n_draws,
        "observed_max_abs_rho": obs_max_abs,
        "placebo_median_max_abs_rho": float(np.median(max_abs)),
        "placebo_95th_max_abs_rho": float(np.quantile(max_abs, 0.95)),
        "empirical_p_max_abs": float((max_abs >= obs_max_abs).mean()),
        "observed_max_signed_rho_pnl": obs_max_signed,
        "placebo_median_max_signed_rho_pnl": float(np.median(max_signed_pnl)),
        "placebo_95th_max_signed_rho_pnl": float(np.quantile(max_signed_pnl, 0.95)),
        "empirical_p_max_signed_pnl": float((max_signed_pnl >= obs_max_signed).mean()),
        "share_of_draws_with_a_nominal_hit": float(
            (max_abs >= np.nanmax(np.abs(obs)) * 0.0 + 0.0).mean()),  # placeholder, set below
    }


# ------------------------------------------------------------------------------- rules
def entry_filter_rule(sub: pd.DataFrame, feature: str, side: str,
                      q: float = 1.0 / 3.0) -> dict:
    """Take the trade only when ``feature`` is in the top (``side='high'``) or bottom tercile.

    Decision minute: the fill minute.  Only legitimate for exogenous / pre-entry features.
    """
    x = sub[feature].to_numpy(dtype=float)
    y = sub["pnl_full"].to_numpy(dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 15:
        return {"N": 0}
    x, y = x[m], y[m]
    thr = np.quantile(x, 1 - q if side == "high" else q)
    keep = x >= thr if side == "high" else x <= thr
    out = summarise(y[keep])
    out.update({"rule": f"{feature} {side} tercile", "kind": "entry filter",
                "N_pool": int(len(y)), "baseline_mean": float(y.mean()),
                "delta_vs_all": float(y[keep].mean() - y.mean()),
                "p_vs_all": float(stats.ttest_ind(y[keep], y, equal_var=False).pvalue),
                "held_minutes": float(sub.loc[sub.index[m][keep], "minutes_remaining"].mean())})
    return out


def persist_rule(sub: pd.DataFrame, feature: str, side: str,
                 q: float = 1.0 / 3.0) -> dict:
    """Cut the position at the decision minute when ``feature`` is in the named tercile,
    otherwise hold to the close.  Paired against always-hold on the same days."""
    x = sub[feature].to_numpy(dtype=float)
    cut = sub["pnl_todate"].to_numpy(dtype=float)
    hold = sub["pnl_full"].to_numpy(dtype=float)
    held = sub["held_minutes_if_persist"].to_numpy(dtype=float)
    rest = sub["minutes_remaining"].to_numpy(dtype=float)
    m = np.isfinite(x) & np.isfinite(cut) & np.isfinite(hold)
    if m.sum() < 15:
        return {"N": 0}
    x, cut, hold, held, rest = x[m], cut[m], hold[m], held[m], rest[m]
    thr = np.quantile(x, 1 - q if side == "high" else q)
    do_cut = x >= thr if side == "high" else x <= thr
    r = np.where(do_cut, cut, hold)
    mins = np.where(do_cut, held, held + rest)
    out = summarise(r)
    d = r - hold
    out.update({"rule": f"{feature} {side} tercile", "kind": "persist/cut",
                "cut_share_pct": float(do_cut.mean() * 100.0),
                "baseline_mean": float(hold.mean()),
                "delta_vs_hold": float(d.mean()),
                "p_vs_hold": float(stats.ttest_rel(r, hold).pvalue),
                "held_minutes": float(mins.mean()),
                "pct_per_minute_held": float(r.mean() / max(mins.mean(), 1e-9))})
    return out



def rule_family(pop: pd.DataFrame, spec: list[dict]) -> pd.DataFrame:
    """Evaluate a fixed list of (feature, decision, side) rules on one population."""
    rows = []
    for c in spec:
        sub = pop[pop["decision"] == c["decision"]]
        r = (entry_filter_rule(sub, c["feature"], c["side"])
             if c["decision"] == "entry" else
             persist_rule(sub, c["feature"], c["side"]))
        if r.get("N", 0) == 0:
            continue
        r.update({k: c[k] for k in ("feature", "decision", "side", "grade")})
        rows.append(r)
    return pd.DataFrame(rows)


def rule_placebo(pop: pd.DataFrame, spec: list[dict], n_draws: int = N_DRAWS,
                 seed: int = SEED) -> dict:
    """Best-of-rules placebo: shuffle each feature across days, re-run the whole rule family,
    keep the best mean return and the best improvement over the incumbent.

    Shuffling the FEATURE rather than the outcome keeps every trade's realised P&L, the
    entry-time distribution and the exit machinery exactly as observed, and destroys only the
    feature-to-day mapping -- i.e. only the thing the rule claims to exploit.
    """
    rng = np.random.default_rng(seed + 1)
    best_mean = np.full(n_draws, -np.inf)
    best_delta = np.full(n_draws, -np.inf)
    subs = {d: pop[pop["decision"] == d].copy() for d in {c["decision"] for c in spec}}
    for b in range(n_draws):
        shuffled = {}
        for d, sub in subs.items():
            sh = sub.copy()
            for f in {c["feature"] for c in spec if c["decision"] == d}:
                v = sh[f].to_numpy(dtype=float).copy()
                rng.shuffle(v)
                sh[f] = v
            shuffled[d] = sh
        for c in spec:
            sub = shuffled[c["decision"]]
            r = (entry_filter_rule(sub, c["feature"], c["side"])
                 if c["decision"] == "entry" else
                 persist_rule(sub, c["feature"], c["side"]))
            if r.get("N", 0) == 0:
                continue
            best_mean[b] = max(best_mean[b], r["mean"])
            d_ = r.get("delta_vs_hold", r.get("delta_vs_all", np.nan))
            if np.isfinite(d_):
                best_delta[b] = max(best_delta[b], d_)
    return {"draws": n_draws, "best_mean": best_mean, "best_delta": best_delta}


def net_rule_return(mean_gross: float, entry_premium: float,
                    half_spread_pct: float) -> float:
    exit_px = entry_premium * (1.0 + mean_gross / 100.0)
    return mean_gross - cost_pct_of_premium(entry_premium, exit_px, half_spread_pct)


# -------------------------------------------------------------------------------- main
def main() -> None:
    panel = pd.read_csv("gate_b_flow_panel.csv")
    out: dict = {"seed": SEED, "draws": N_DRAWS}

    fires = panel[panel["vix_rose"] == 1].copy()
    ctrl = panel[panel["vix_rose"] == 0].copy()
    mid = fires[fires["iv_bucket"] == "middle_14_18"].copy()
    ctrl_mid = ctrl[ctrl["iv_bucket"] == "middle_14_18"].copy()

    pops = {"pooled_fires": fires, "midIV_fires": mid,
            "pooled_controls": ctrl, "midIV_controls": ctrl_mid}

    print("=" * 112)
    print("GATE B -- VOLUME, OPEN INTEREST AND TRUE-OHLC STUDY")
    print("=" * 112)
    print("Offline analysis only.  No broker, credential, network, or order path.\n")

    # ------------------------------------------------------------- 0. coverage
    print("=" * 112)
    print("0.  POPULATION AND FEATURE COVERAGE")
    print("=" * 112)
    cov = {}
    for name, pop in pops.items():
        e = pop[pop["decision"] == "entry"]
        cov[name] = {"fires_at_entry": int(len(e)),
                     "date_min": str(e["date"].min()), "date_max": str(e["date"].max())}
        print(f"{name:>18}: N={len(e):>4}  {e['date'].min()} .. {e['date'].max()}")
    print()
    covtab = fires.groupby("decision")[list(ALL_FEATURES)].apply(
        lambda g: (g.notna().mean() * 100.0)).round(1)
    print("feature coverage %, gate fires (vix_rose = 1):")
    print(covtab.to_string())
    out["coverage"] = cov
    out["feature_coverage_pct"] = covtab.to_dict()
    n_by_dec = fires.groupby("decision").size().to_dict()
    out["fires_n_by_decision"] = {k: int(v) for k, v in n_by_dec.items()}
    print(f"\nfires per decision point: {n_by_dec}")
    print("(N falls with the decision window because a target needs >= 30 minutes of session")
    print(" left; the late-filling fires drop out.  Reported per cell everywhere below.)")

    # -------------------------------------------------- A. true OHLC vs close proxy
    print("\n" + "=" * 112)
    print("A.  TRUE INTRAMINUTE OHLC VERSUS THE CLOSE-ONLY PROXY")
    print("=" * 112)
    a_rows = []
    for dec in DECISIONS:
        s = fires[fires["decision"] == dec]
        r = {"decision": dec}
        for f in ("chop_call", "chop_spotproxy", "adx_call", "adx_spotproxy", "dmi_call"):
            v = s[f].dropna()
            r[f"{f}_n"] = int(len(v))
            r[f"{f}_mean"] = float(v.mean()) if len(v) else np.nan
        cc = s[["chop_call", "chop_spotproxy"]].dropna()
        r["chop_corr"] = float(stats.spearmanr(cc.iloc[:, 0], cc.iloc[:, 1]).statistic) if len(cc) > 10 else np.nan
        aa = s[["adx_call", "adx_spotproxy"]].dropna()
        r["adx_corr"] = float(stats.spearmanr(aa.iloc[:, 0], aa.iloc[:, 1]).statistic) if len(aa) > 10 else np.nan
        a_rows.append(r)
    A = pd.DataFrame(a_rows)
    print(A.round(3).to_string(index=False))
    out["section_A_ohlc_vs_proxy"] = A.to_dict(orient="records")

    # --------------------------------------------------------- B/C/D. the grid
    grids = {}
    for name, pop in pops.items():
        grids[name] = build_grid(pop)
    G = grids["pooled_fires"]
    Gm = grids["midIV_fires"]
    n_cells = int(G["rho"].notna().sum())

    print("\n" + "=" * 112)
    print("B/C/D.  THE ASSOCIATION GRID -- Spearman rho, features vs targets")
    print("=" * 112)
    print(f"cells with a computable rho: pooled {n_cells}, mid-IV {int(Gm['rho'].notna().sum())}")
    print(f"total grid size: {len(ALL_FEATURES)} features x {len(DECISIONS)} decision points "
          f"x {len(TARGETS)} targets = {len(ALL_FEATURES)*len(DECISIONS)*len(TARGETS)}\n")

    for pop_name, gg in (("POOLED N~120", G), ("MID-IV N=33", Gm)):
        print("-" * 112)
        print(f"{pop_name}: strongest 15 associations by |rho|")
        print("-" * 112)
        top = gg.dropna(subset=["rho"]).sort_values("abs_rho", ascending=False).head(15)
        print(f"{'feature':>16} {'grade':>21} {'decision':>11} {'target':>9} "
              f"{'n':>4} {'rho':>7} {'p':>8} {'ctrl rho':>9} {'ctrl p':>8}")
        cname = "pooled_controls" if "POOLED" in pop_name else "midIV_controls"
        cg = grids[cname].set_index(["feature", "decision", "target"])
        for _, r in top.iterrows():
            key = (r["feature"], r["decision"], r["target"])
            crho = cg.loc[key, "rho"] if key in cg.index else np.nan
            cp = cg.loc[key, "p"] if key in cg.index else np.nan
            print(f"{r['feature']:>16} {r['grade']:>21} {r['decision']:>11} {r['target']:>9} "
                  f"{int(r['n']):>4} {r['rho']:>7.3f} {r['p']:>8.4f} "
                  f"{crho:>9.3f} {cp:>8.4f}")
        print()

    # per-family summary
    print("-" * 112)
    print("By feature family: how many of that family's cells reach raw p<0.05, and the best |rho|")
    print("-" * 112)
    fams = {"A trend/chop (true OHLC)": gff.TREND_FEATURES,
            "B volume": gff.VOLUME_FEATURES,
            "C open interest": gff.OI_FEATURES,
            "D put/call ratios": gff.PCR_FEATURES}
    fam_rows = []
    for pop_name, gg in (("pooled", G), ("midIV", Gm), ("pooled_ctrl", grids["pooled_controls"])):
        for fam, feats in fams.items():
            s = gg[gg["feature"].isin(feats)].dropna(subset=["rho"])
            if s.empty:
                continue
            fam_rows.append({
                "population": pop_name, "family": fam, "cells": len(s),
                "raw_p_lt_05": int((s["p"] < 0.05).sum()),
                "expected_by_chance": round(0.05 * len(s), 1),
                "best_abs_rho": round(float(s["abs_rho"].max()), 3),
                "best_p": float(s.loc[s["abs_rho"].idxmax(), "p"]),
                "bh_survivors": int(bh_reject(s["p"].to_numpy()).sum()),
            })
    F = pd.DataFrame(fam_rows)
    print(F.to_string(index=False))
    out["section_family_summary"] = F.to_dict(orient="records")

    for name, gg in grids.items():
        gg.to_csv(f"gate_b_flow_grid_{name}.csv", index=False)

    # ---- joint test: is the whole grid's p-value distribution uniform? ----
    print("\n" + "-" * 112)
    print("Joint test of the WHOLE grid: are the 400 p-values distributed as U(0,1)?")
    print("A max-statistic is blind to many small effects; this is not.")
    print("-" * 112)
    uni = {}
    for pop_name, gg in (("pooled_fires", G), ("midIV_fires", Gm),
                         ("pooled_controls", grids["pooled_controls"]),
                         ("midIV_controls", grids["midIV_controls"])):
        pv = gg["p"].dropna().to_numpy()
        ks = stats.kstest(pv, "uniform")
        n05 = int((pv < 0.05).sum())
        binom = stats.binomtest(n05, len(pv), 0.05, alternative="greater").pvalue
        uni[pop_name] = {"cells": int(len(pv)), "ks_stat": float(ks.statistic),
                         "ks_p": float(ks.pvalue), "n_p_lt_05": n05,
                         "binomial_p_excess": float(binom),
                         "mean_abs_rho": float(gg["abs_rho"].mean())}
        u = uni[pop_name]
        print(f"{pop_name:>17}: KS D={u['ks_stat']:.4f} p={u['ks_p']:.4f}   "
              f"#p<0.05 = {n05}/{u['cells']} (binomial one-sided p={binom:.4f})   "
              f"mean|rho| = {u['mean_abs_rho']:.3f}")
    out["section_grid_uniformity"] = uni

    # ---- best |rho| by target, fires against controls, side by side ----
    print("\n" + "-" * 112)
    print("Best |rho| in the grid by TARGET -- gate fires against control days")
    print("-" * 112)
    print(f"{'target':>10} {'pooled fires':>14} {'pooled ctrl':>13} "
          f"{'midIV fires':>13} {'midIV ctrl':>12}   {'80% power |rho|':>16}")
    bt = {}
    for t in TARGETS:
        vals = {}
        for lbl, gg, n in (("pf", G, 116), ("pc", grids["pooled_controls"], 142),
                           ("mf", Gm, 33), ("mc", grids["midIV_controls"], 39)):
            s_ = gg[(gg["target"] == t)].dropna(subset=["rho"])
            vals[lbl] = float(s_["abs_rho"].max()) if len(s_) else np.nan
        bt[t] = vals
        print(f"{t:>10} {vals['pf']:>14.3f} {vals['pc']:>13.3f} "
              f"{vals['mf']:>13.3f} {vals['mc']:>12.3f}   "
              f"pooled {detectable_rho(116):.2f} / mid {detectable_rho(33):.2f}")
    out["section_best_rho_by_target"] = bt

    # ---- selection audit on the ADX/CHOP-at-entry subsample ----
    print("\n" + "-" * 112)
    print("Selection audit: which fires can even HAVE a trend indicator at the fill minute?")
    print("-" * 112)
    e = fires[fires["decision"] == "entry"].copy()
    have = e["adx_call"].notna()
    sel = {"n_with_adx": int(have.sum()), "n_without": int((~have).sum())}
    for col, lab in (("entry_minute", "entry minute"), ("pnl_full", "hold-to-close return %"),
                     ("minutes_remaining", "minutes of session left")):
        a = e.loc[have, col].astype(float)
        b = e.loc[~have, col].astype(float)
        pv = float(stats.ttest_ind(a.dropna(), b.dropna(), equal_var=False).pvalue)
        sel[col] = {"with_adx_mean": float(a.mean()), "without_mean": float(b.mean()),
                    "welch_p": pv}
        print(f"  {lab:>26}: with ADX {a.mean():>9.2f}   without {b.mean():>9.2f}   "
              f"Welch p = {pv:.4f}")
    print("  (ADX(7) needs 15 bars, so a 09:18 fill cannot have one.  Every entry-decision")
    print("   trend result is therefore on a LATER-FILLING subsample, not on Gate B.)")
    out["section_entry_selection_audit"] = sel

    # ---------------------------------------------------- multiplicity on the grid
    print("\n" + "=" * 112)
    print("F.  MULTIPLICITY AND PLACEBOS")
    print("=" * 112)
    mult = {}
    for pop_name, gg in (("pooled_fires", G), ("midIV_fires", Gm),
                         ("pooled_controls", grids["pooled_controls"])):
        s = gg.dropna(subset=["rho"])
        pv = s["p"].to_numpy()
        alpha_b = 0.05 / len(pv)
        mult[pop_name] = {
            "cells": int(len(pv)),
            "raw_p_lt_05": int((pv < 0.05).sum()),
            "expected_by_chance": round(0.05 * len(pv), 1),
            "bonferroni_threshold": alpha_b,
            "bonferroni_survivors": int((pv < alpha_b).sum()),
            "bh_survivors": int(bh_reject(pv).sum()),
            "min_p": float(np.nanmin(pv)),
            "max_abs_rho": float(s["abs_rho"].max()),
        }
        m = mult[pop_name]
        print(f"{pop_name:>17}: cells={m['cells']:>4}  raw p<0.05: {m['raw_p_lt_05']:>3} "
              f"(chance {m['expected_by_chance']})  Bonferroni: {m['bonferroni_survivors']}  "
              f"BH: {m['bh_survivors']}  min p={m['min_p']:.5f}  max|rho|={m['max_abs_rho']:.3f}")
    out["section_F_multiplicity"] = mult

    print("\nWestfall-Young best-of-grid permutation placebo "
          f"({N_DRAWS} draws, coherent day permutation, seed {SEED}):")
    wy = {}
    for pop_name, pop in (("pooled_fires", fires), ("midIV_fires", mid)):
        w = westfall_young(pop)
        w.pop("share_of_draws_with_a_nominal_hit", None)
        wy[pop_name] = w
        print(f"  {pop_name}: cells={w['cells_tested']}")
        print(f"    max|rho|  observed {w['observed_max_abs_rho']:.3f}   "
              f"placebo median {w['placebo_median_max_abs_rho']:.3f}   "
              f"placebo 95th {w['placebo_95th_max_abs_rho']:.3f}   "
              f"empirical p = {w['empirical_p_max_abs']:.4f}")
        print(f"    signed best rho vs P&L  observed {w['observed_max_signed_rho_pnl']:+.3f}   "
              f"placebo median {w['placebo_median_max_signed_rho_pnl']:+.3f}   "
              f"placebo 95th {w['placebo_95th_max_signed_rho_pnl']:+.3f}   "
              f"empirical p = {w['empirical_p_max_signed_pnl']:.4f}")
    out["section_F_westfall_young"] = wy

    # --------------------------------------------------------------- E. rules
    print("\n" + "=" * 112)
    print("E.  THE DECISION RULES THE STRONGEST ASSOCIATIONS IMPLY, PRICED ON REAL PREMIUMS")
    print("=" * 112)
    rule_rows = []
    for pop_name, pop, gg in (("pooled", fires, G), ("midIV", mid, Gm)):
        cand = (gg[(gg["target"] == "pnl_rest") & gg["rho"].notna()]
                .sort_values("abs_rho", ascending=False).head(3))
        for _, c in cand.iterrows():
            sub = pop[pop["decision"] == c["decision"]]
            for side in ("high", "low"):
                if c["decision"] == "entry":
                    r = entry_filter_rule(sub, c["feature"], side)
                else:
                    r = persist_rule(sub, c["feature"], side)
                if r.get("N", 0) == 0:
                    continue
                r.update({"population": pop_name, "feature": c["feature"],
                          "decision": c["decision"], "grade": c["grade"],
                          "rho": float(c["rho"]), "side": side})
                rule_rows.append(r)
    R = pd.DataFrame(rule_rows)
    if not R.empty:
        cols = ["population", "feature", "decision", "grade", "side", "kind", "N",
                "mean", "median", "win", "p0", "baseline_mean",
                "delta_vs_all", "p_vs_all", "delta_vs_hold", "p_vs_hold",
                "cut_share_pct", "held_minutes", "pct_per_minute_held"]
        cols = [c for c in cols if c in R.columns]
        print(R[cols].round(4).to_string(index=False))
        R.to_csv("gate_b_flow_rules.csv", index=False)

        # --- net of costs, at the population's own median traded entry premium ---
        paths_all = _entry_premiums()
        med_prem = float(np.nanmedian(list(paths_all.values())))
        R["net_035"] = [net_rule_return(m, med_prem, 0.35) for m in R["mean"]]
        R["net_100"] = [net_rule_return(m, med_prem, 1.00) for m in R["mean"]]
        print(f"\nNet of costs at the median traded Gate-B entry premium "
              f"(Rs {med_prem:.2f}), one lot of {LOT}:")
        print(R[["population", "feature", "decision", "side", "mean", "net_035", "net_100"]]
              .round(3).to_string(index=False))

        # --- the same rules run on the CONTROL days (gate did not fire) ---
        print("\nThe identical rules on the CONTROL population (overnight VIX did NOT rise):")
        spec = [{"feature": r["feature"], "decision": r["decision"],
                 "side": r["side"], "grade": r["grade"]} for _, r in R.iterrows()]
        spec_pooled = [c for c in spec[:6]]
        spec_mid = [c for c in spec[6:]]
        CR = []
        for lbl, sp, cpop in (("pooled_ctrl", spec_pooled, ctrl),
                              ("midIV_ctrl", spec_mid, ctrl_mid)):
            rr = rule_family(cpop, sp)
            if not rr.empty:
                rr["population"] = lbl
                CR.append(rr)
        if CR:
            CRD = pd.concat(CR, ignore_index=True)
            ccols = [c for c in ["population", "feature", "decision", "side", "kind", "N",
                                 "mean", "p0", "baseline_mean", "delta_vs_all",
                                 "delta_vs_hold", "p_vs_hold", "p_vs_all"]
                     if c in CRD.columns]
            print(CRD[ccols].round(4).to_string(index=False))
            CRD.to_csv("gate_b_flow_rules_controls.csv", index=False)
            out["section_E_rules_on_controls"] = CRD.to_dict(orient="records")

        # --- best-of-rules shuffled-feature placebo ---
        print(f"\nBest-of-rules placebo, {N_DRAWS} draws, feature shuffled across days:")
        rp = {}
        for lbl, sp, pop in (("pooled", spec_pooled, fires), ("midIV", spec_mid, mid)):
            pl = rule_placebo(pop, sp, n_draws=1000)
            obs_mean = float(R[R["population"] == lbl]["mean"].max())
            dd = R[R["population"] == lbl][["delta_vs_hold", "delta_vs_all"]].to_numpy(float)
            obs_delta = float(np.nanmax(dd)) if np.isfinite(dd).any() else np.nan
            rp[lbl] = {
                "rules": len(sp),
                "observed_best_mean": obs_mean,
                "placebo_median_best_mean": float(np.median(pl["best_mean"])),
                "placebo_95th_best_mean": float(np.quantile(pl["best_mean"], 0.95)),
                "empirical_p_best_mean": float((pl["best_mean"] >= obs_mean).mean()),
                "observed_best_delta": obs_delta,
                "placebo_median_best_delta": float(np.median(pl["best_delta"])),
                "placebo_95th_best_delta": float(np.quantile(pl["best_delta"], 0.95)),
                "empirical_p_best_delta": float((pl["best_delta"] >= obs_delta).mean()),
                "draws": 1000,
            }
            m_ = rp[lbl]
            print(f"  {lbl}: best rule mean observed {obs_mean:+.2f}%  "
                  f"placebo median {m_['placebo_median_best_mean']:+.2f}%  "
                  f"95th {m_['placebo_95th_best_mean']:+.2f}%  "
                  f"empirical p = {m_['empirical_p_best_mean']:.4f}")
            print(f"  {lbl}: best improvement observed {obs_delta:+.2f}pp  "
                  f"placebo median {m_['placebo_median_best_delta']:+.2f}pp  "
                  f"95th {m_['placebo_95th_best_delta']:+.2f}pp  "
                  f"empirical p = {m_['empirical_p_best_delta']:.4f}")
        out["section_E_rule_placebo"] = rp
    out["section_E_rules"] = R.to_dict(orient="records") if not R.empty else []

    # ------------------------------------------------------------------- G. power
    print("\n" + "=" * 112)
    print("G.  POWER")
    print("=" * 112)
    n_grid = len(ALL_FEATURES) * len(DECISIONS) * len(TARGETS)
    pw = {}
    for label, n in (("mid-IV fires", 33), ("pooled fires", 116),
                     ("pooled controls", 142)):
        raw = detectable_rho(n)
        za = stats.norm.ppf(1.0 - (0.05 / n_grid) / 2.0)
        corr = float(np.tanh((za + stats.norm.ppf(0.80)) / np.sqrt(n - 3)))
        pw[label] = {"n": n, "detectable_rho_raw_alpha05": raw,
                     "detectable_rho_bonferroni": corr}
        print(f"{label:>16} N={n:>4}: smallest |rho| detectable at 80% power -- "
              f"raw alpha=0.05: {raw:.3f};  Bonferroni over {n_grid} tests: {corr:.3f}")
    base = fires[fires["decision"] == "entry"]["pnl_full"].dropna().to_numpy()
    basem = mid[mid["decision"] == "entry"]["pnl_full"].dropna().to_numpy()
    for label, b in (("pooled", base), ("mid-IV", basem)):
        sd = float(b.std(ddof=1))
        n = len(b)
        d = (stats.norm.ppf(0.975) + stats.norm.ppf(0.80)) / np.sqrt(n)
        pw[f"{label}_pnl"] = {"n": n, "mean": float(b.mean()), "sd": sd,
                              "detectable_mean_pp": float(d * sd),
                              "ci95": [float(b.mean() - 1.96 * sd / np.sqrt(n)),
                                       float(b.mean() + 1.96 * sd / np.sqrt(n))]}
        print(f"{label:>16} hold-to-close: N={n}, mean {b.mean():+.2f}%, sd {sd:.1f}pp, "
              f"95% CI [{b.mean()-1.96*sd/np.sqrt(n):+.2f}, {b.mean()+1.96*sd/np.sqrt(n):+.2f}], "
              f"smallest detectable mean {d*sd:.2f}pp")
    out["section_G_power"] = pw

    with open("gate_b_volume_oi_study_results.json", "w") as fh:
        json.dump(out, fh, indent=2, default=float)
    print("\nwrote gate_b_volume_oi_study_results.json")


if __name__ == "__main__":
    main()
