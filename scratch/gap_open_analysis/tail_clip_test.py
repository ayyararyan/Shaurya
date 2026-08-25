#!/usr/bin/env python3
"""Defined-risk conversion of H3 (09:20 short ATM straddle, non-expiry).  Spec: TAIL_CLIP_SPEC.md.

Exploratory.  No gate change, no gate armed, no broker or order path.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import nge_common as nc

LOT = 75
STEP = 50.0
QUOTES = Path("folklore_required_quotes_20260823.pkl")
ENTRY, EXIT = "09:20", "15:29"
BUDGET = 10_000.0

IF_WIDTHS = [1, 2, 3, 4, 5, 6, 8, 10]
IC_SPECS = [(1, 2), (1, 3), (1, 4), (2, 2), (2, 3), (2, 4)]
STOPS = [0.25, 0.50, 1.00]


def load_quotes() -> dict:
    q = pickle.load(open(QUOTES, "rb"))["quotes"]
    q = q[q["clock"].isin((ENTRY, EXIT))]
    out: dict = {}
    for (d, c), g in q.groupby(["date", "clock"], sort=False):
        px = {}
        for side, gg in g.groupby("side"):
            px[side] = dict(zip(gg["strike"].astype(float), gg["close"].astype(float)))
        out[(d, c)] = {"px": px, "spot": float(g["spot"].iloc[0])}
    return out


def build() -> pd.DataFrame:
    qq = load_quotes()
    expiries = set(nc._expiry_dates())
    daily = nc.load_daily().set_index("date")
    dates = sorted({d for (d, c) in qq})

    rows = []
    drops = {"no_entry": 0, "no_exit": 0, "expiry_day": 0, "no_daily": 0}
    for d in dates:
        if (d, ENTRY) not in qq:
            drops["no_entry"] += 1
            continue
        if (d, EXIT) not in qq:
            drops["no_exit"] += 1
            continue
        if d not in daily.index:
            drops["no_daily"] += 1
            continue
        if d in expiries:
            drops["expiry_day"] += 1        # H3 is the non-expiry arm
            continue
        e, x = qq[(d, ENTRY)], qq[(d, EXIT)]
        S = e["spot"]
        ks = sorted(set(e["px"].get("CALL", {})) & set(e["px"].get("PUT", {})))
        if not ks:
            drops["no_entry"] += 1
            continue
        atm = min(ks, key=lambda k: abs(k - S))
        rows.append({"date": d, "spot_entry": S, "spot_exit": x["spot"], "atm": atm,
                     "e": e["px"], "x": x["px"],
                     "n_sess": float(daily.loc[d, "sessions_to_expiry"])})
    return pd.DataFrame(rows), drops


def leg(px: dict, side: str, k: float) -> float:
    v = px.get(side, {}).get(k)
    return float(v) if v is not None and v > 0 else np.nan


def value(px: dict, legs: list[tuple[str, float, int]]) -> float:
    """legs = [(side, strike, qty)] with qty +1 long, -1 short.  Returns net value per unit."""
    tot = 0.0
    for side, k, q in legs:
        p = leg(px, side, k)
        if not np.isfinite(p):
            return np.nan
        tot += q * p
    return tot


def structure_legs(name: str, atm: float) -> list[tuple[str, float, int]]:
    if name == "S0 naked straddle":
        return [("CALL", atm, -1), ("PUT", atm, -1)]
    if name.startswith("IF"):
        w = int(name.split("w=")[1].rstrip(")"))
        return [("CALL", atm, -1), ("PUT", atm, -1),
                ("CALL", atm + STEP * w, +1), ("PUT", atm - STEP * w, +1)]
    if name.startswith("IC"):
        b, w = (int(t) for t in name.split("(")[1].rstrip(")").replace("b=", "").replace("w=", "").split(","))
        return [("CALL", atm + STEP * b, -1), ("PUT", atm - STEP * b, -1),
                ("CALL", atm + STEP * (b + w), +1), ("PUT", atm - STEP * (b + w), +1)]
    raise ValueError(name)


def wing_width(name: str) -> float:
    if name == "S0 naked straddle":
        return np.nan
    if name.startswith("IF"):
        return STEP * int(name.split("w=")[1].rstrip(")"))
    b, w = (int(t) for t in name.split("(")[1].rstrip(")").replace("b=", "").replace("w=", "").split(","))
    return STEP * w


def evaluate_structure(panel: pd.DataFrame, name: str) -> dict:
    width = wing_width(name)
    recs = []
    for _, r in panel.iterrows():
        legs = structure_legs(name, r["atm"])
        v_in = value(r["e"], legs)      # short-heavy -> negative value = credit received
        v_out = value(r["x"], legs)
        if not (np.isfinite(v_in) and np.isfinite(v_out)):
            continue
        credit = -v_in                  # rupees per unit received at entry
        pnl_unit = v_out - v_in         # value change of the position we hold
        pnl = pnl_unit * LOT
        entry_prem = None
        if name == "S0 naked straddle":
            entry_prem = credit
            max_loss = np.nan
        else:
            max_loss = (width - credit) * LOT
            entry_prem = credit
        recs.append({"date": r["date"], "year": int(r["date"][:4]), "credit_unit": credit,
                     "credit_rs": credit * LOT, "pnl": pnl, "max_loss": max_loss,
                     "pnl_pct_entry": 100.0 * pnl_unit / credit if credit > 0 else np.nan,
                     "ror": pnl / max_loss if np.isfinite(max_loss) and max_loss > 0 else np.nan})
    df = pd.DataFrame(recs)
    if df.empty:
        return {"name": name, "n": 0}, df

    # Non-synchronous-quote quarantine.  ``close`` is the last TRADED price in the minute, not a
    # quote, so two strikes 50 points apart can be stamped seconds or minutes apart.  When the
    # measured credit equals or exceeds the wing width the structure is a riskless arbitrage,
    # which does not exist; those sessions are a price-stamping artifact, not a trade.
    n_arb = 0
    if np.isfinite(width):
        arb = df["credit_unit"] >= width
        n_arb = int(arb.sum())
        df = df[~arb].reset_index(drop=True)
        if df.empty:
            return {"name": name, "n": 0, "arbitrage_sessions_dropped": n_arb}, df

    pnl = df["pnl"].to_numpy()
    cum = np.cumsum(pnl)
    dd = float(np.min(cum - np.maximum.accumulate(cum)))
    t, p = stats.ttest_1samp(pnl, 0.0)
    try:
        wp = float(stats.wilcoxon(pnl).pvalue)
    except Exception:
        wp = np.nan
    n_legs = len(structure_legs(name, 20000.0))
    worst5 = df.nsmallest(5, "pnl")[["date", "pnl"]].values.tolist()

    out = {
        "name": name, "n": int(len(df)), "n_legs": n_legs,
        "arbitrage_sessions_dropped": n_arb,
        "mean_pnl_rs": float(pnl.mean()), "median_pnl_rs": float(np.median(pnl)),
        "sd_pnl_rs": float(pnl.std(ddof=1)), "win_rate": float((pnl > 0).mean()),
        "t": float(t), "p": float(p), "wilcoxon_p": wp,
        "mean_credit_rs": float(df["credit_rs"].mean()),
        "mean_pct_entry": float(df["pnl_pct_entry"].mean()),
        "worst_pnl_rs": float(pnl.min()), "worst5": worst5,
        "p1_rs": float(np.percentile(pnl, 1)), "p99_rs": float(np.percentile(pnl, 99)),
        "max_drawdown_rs": dd,
        "breakeven_cost_per_leg_rs": float(pnl.mean() / n_legs),
        "by_year": {str(y): {"n": int(len(g)), "mean_rs": float(g["pnl"].mean()),
                             "t": float(stats.ttest_1samp(g["pnl"], 0.0).statistic) if len(g) > 2 else np.nan}
                    for y, g in df.groupby("year")},
    }
    if np.isfinite(width):
        ml = df["max_loss"].to_numpy()
        out.update({
            "wing_width_pts": float(width),
            "median_max_loss_rs": float(np.median(ml)),
            "p90_max_loss_rs": float(np.percentile(ml, 90)),
            "max_max_loss_rs": float(ml.max()),
            "fits_10k_budget_median": bool(np.median(ml) <= BUDGET),
            "share_sessions_within_10k": float(np.mean(ml <= BUDGET)),
            "mean_ror_pct": float(100.0 * df["ror"].mean()),
            "sd_ror_pct": float(100.0 * df["ror"].std(ddof=1)),
            "mean_over_sd_ror": float(df["ror"].mean() / df["ror"].std(ddof=1)),
            "worst_ror_pct": float(100.0 * df["ror"].min()),
            "max_dd_in_maxloss_units": float(dd / np.median(ml)),
            "sessions_to_ruin_10k_worst_case": float(BUDGET / abs(pnl.min())) if pnl.min() < 0 else np.inf,
            "accounting_violations": int(np.sum(pnl < -ml - 1e-6)),
        })
    return out, df


def stop_loss_variants(panel: pd.DataFrame) -> dict:
    """ROB-01: naked S0 and a defined-risk fly, each with an intraday stop on the SHORT straddle.

    Uses ``tail_clip_paths.pkl`` -- the minute path of the ONE contract that was at the money at
    09:20, not the rolling ``rel_strike == ATM`` file.  The rolling file is a straddle re-struck
    every minute; it decays without ever losing and produces a fictitious edge.
    """
    tape = pd.read_pickle("tail_clip_paths.pkl")
    want = set(panel["date"])
    tape = tape[tape["date"].isin(want)]
    out: dict[str, list] = {f"stop_{int(s * 100)}pct": [] for s in STOPS}
    out["no_stop"] = []
    n_paths = 0
    for d, g in tape.groupby("date"):
        c = g[g["side"] == "CALL"].set_index("clock")["close"]
        p = g[g["side"] == "PUT"].set_index("clock")["close"]
        comb = c.add(p, fill_value=np.nan).dropna().sort_index()
        if len(comb) < 100 or ENTRY not in comb.index:
            continue
        n_paths += 1
        entry = float(comb.loc[ENTRY])
        path = comb.loc[ENTRY:]
        final = float(path.iloc[-1])
        out["no_stop"].append((entry - final) * LOT)
        for s_ in STOPS:
            trig = path[path >= entry * (1.0 + s_)]
            exitp = float(trig.iloc[0]) if len(trig) else final
            out[f"stop_{int(s_ * 100)}pct"].append((entry - exitp) * LOT)

    res = {"n_paths": n_paths,
           "note": "margin is UNCHANGED by a stop: a naked short straddle is margined on its "
                   "worst case, not on the trader's intention to exit early"}
    for k, v in out.items():
        a = np.asarray(v, dtype=float)
        if len(a) < 10:
            continue
        cum = np.cumsum(a)
        res[k] = {"n": int(len(a)), "mean_rs": float(a.mean()), "median_rs": float(np.median(a)),
                  "win_rate": float((a > 0).mean()),
                  "t": float(stats.ttest_1samp(a, 0.0).statistic),
                  "p": float(stats.ttest_1samp(a, 0.0).pvalue),
                  "worst_rs": float(a.min()),
                  "p1_rs": float(np.percentile(a, 1)),
                  "max_drawdown_rs": float(np.min(cum - np.maximum.accumulate(cum)))}
    return res


def main() -> None:
    panel, drops = build()
    names = (["S0 naked straddle"] + [f"IF(w={w})" for w in IF_WIDTHS]
             + [f"IC(b={b},w={w})" for b, w in IC_SPECS])
    family = len(names) - 1                       # the incumbent is not a discovery
    alpha = 0.05 / family

    results = {"spec": "TAIL_CLIP_SPEC.md", "lot": LOT, "budget_rs": BUDGET,
               "panel_n": int(len(panel)), "drops": drops,
               "registered_family_size": family, "bonferroni_alpha": alpha,
               "structures": {}}
    frames = {}
    for nm in names:
        ev = evaluate_structure(panel, nm)
        if isinstance(ev, tuple):
            ev, df = ev
            frames[nm] = df
        results["structures"][nm] = ev

    # ---- matched-sample comparison: what did the wings actually cost? ----
    s0_by_date = frames["S0 naked straddle"].set_index("date")["pnl"]
    for nm, df in frames.items():
        if nm == "S0 naked straddle" or df.empty:
            continue
        common = df["date"][df["date"].isin(s0_by_date.index)]
        a = df.set_index("date").loc[common, "pnl"]
        b = s0_by_date.loc[common]
        d = (a - b).to_numpy()
        results["structures"][nm]["matched_vs_S0"] = {
            "n": int(len(d)),
            "s0_mean_on_same_dates_rs": float(b.mean()),
            "structure_mean_rs": float(a.mean()),
            "cost_of_wings_rs": float(-d.mean()),
            "paired_t": float(stats.ttest_rel(a, b).statistic),
            "paired_p": float(stats.ttest_rel(a, b).pvalue),
            "share_structure_better": float(np.mean(d > 0)),
        }

    # ---- common sample across the affordable structures ----
    core = [nm for nm in names if nm != "S0 naked straddle" and not frames[nm].empty
            and frames[nm]["max_loss"].median() <= 12_000]
    if core:
        common = set.intersection(*[set(frames[nm]["date"]) for nm in core])
        results["common_sample"] = {"n": len(common), "structures": core, "rows": {}}
        for nm in core + ["S0 naked straddle"]:
            df = frames[nm]
            sub = df[df["date"].isin(common)]
            pnl = sub["pnl"].to_numpy()
            ml = sub["max_loss"].to_numpy() if "max_loss" in sub else np.array([np.nan])
            results["common_sample"]["rows"][nm] = {
                "n": int(len(sub)), "mean_rs": float(pnl.mean()),
                "median_rs": float(np.median(pnl)), "win": float((pnl > 0).mean()),
                "t": float(stats.ttest_1samp(pnl, 0.0).statistic),
                "p": float(stats.ttest_1samp(pnl, 0.0).pvalue),
                "worst_rs": float(pnl.min()),
                "median_max_loss_rs": float(np.nanmedian(ml)),
                "mean_ror_pct": float(100.0 * np.nanmean(pnl / ml)) if np.isfinite(ml).any() else np.nan,
                "ror_mean_over_sd": float(np.nanmean(pnl / ml) / np.nanstd(pnl / ml, ddof=1)) if np.isfinite(ml).any() else np.nan,
                "sessions_to_ruin_10k": float(BUDGET / abs(pnl.min())) if pnl.min() < 0 else np.inf,
            }

    # VAL-01 reproduction guard against H3
    s0 = results["structures"]["S0 naked straddle"]
    results["reproduction_guard"] = {
        "h3_published_mean_pct_entry": 2.235224,
        "s0_mean_pct_entry": s0["mean_pct_entry"],
        "abs_diff_pp": abs(s0["mean_pct_entry"] - 2.235224),
        "h3_published_n": 1040, "s0_n": s0["n"],
    }
    # VAL-02 accounting
    results["accounting_violations_total"] = int(sum(
        v.get("accounting_violations", 0) for v in results["structures"].values()
        if isinstance(v, dict)))

    results["stop_loss_comparator"] = stop_loss_variants(panel)

    Path("tail_clip_results.json").write_text(json.dumps(results, indent=2, default=str))
    for nm, df in frames.items():
        df.assign(structure=nm).to_csv("tail_clip_panel.csv", mode="a",
                                       header=not Path("tail_clip_panel.csv").exists(), index=False)

    print(json.dumps({k: results[k] for k in ("panel_n", "drops", "registered_family_size",
                                              "bonferroni_alpha", "reproduction_guard",
                                              "accounting_violations_total")}, indent=2))
    print("\n%-16s %5s %9s %8s %7s %9s %10s %9s %8s %9s" % (
        "structure", "n", "mean Rs", "win%", "t", "p", "medMaxLoss", "meanRoR%", "worstRs", "maxDD Rs"))
    for nm in names:
        v = results["structures"][nm]
        print("%-16s %5d %9.1f %8.1f %7.2f %9.5f %10s %9s %8.0f %9.0f" % (
            nm, v["n"], v["mean_pnl_rs"], 100 * v["win_rate"], v["t"], v["p"],
            f"{v.get('median_max_loss_rs', float('nan')):.0f}",
            f"{v.get('mean_ror_pct', float('nan')):.2f}",
            v["worst_pnl_rs"], v["max_drawdown_rs"]))
    print("\n--- stop-loss comparator (naked, margin unchanged) ---")
    print(json.dumps(results["stop_loss_comparator"], indent=2))


if __name__ == "__main__":
    Path("tail_clip_panel.csv").unlink(missing_ok=True)
    main()
