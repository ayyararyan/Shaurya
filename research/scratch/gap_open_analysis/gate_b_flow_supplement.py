#!/usr/bin/env python3
"""Supplementary diagnostics for GATE_B_VOLUME_OI_STUDY.md.

New module.  Modifies nothing.  Three things the headline grid cannot show on its own:

1.  **How endogenous the flow features actually are.**  The brief flags that volume and open
    interest at a strike are partly caused by where spot went.  This measures it directly,
    by correlating every feature with the spot move over its own measurement window, instead
    of asserting it as a caveat.
2.  **Whether the true intraminute OHLC rebuild changed anything relative to the close-only
    proxy that earlier work used.**  Best |rho| of the true-OHLC indicators against the best
    |rho| of the matched close-only ones, per population.
3.  **The strongest NON-PRICE-PATH association specifically**, since the trend/chop family is
    a price-path family with better inputs and does not answer the brief's question.

Offline analysis only.  No broker, credential, exchange network, or order path.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

import gate_b_flow_features as gff
from gate_b_flow_features import ALL_FEATURES, FEATURE_GRADE

TRUE_OHLC = ("chop_call", "adx_call", "dmi_call")
CLOSE_PROXY = ("chop_spotproxy", "adx_spotproxy")
NON_PATH = gff.VOLUME_FEATURES + gff.OI_FEATURES + gff.PCR_FEATURES


def main() -> None:
    panel = pd.read_csv("gate_b_flow_panel.csv")
    fires = panel[panel["vix_rose"] == 1]
    mid = fires[fires["iv_bucket"] == "middle_14_18"]
    out = {}

    # ---------------- 1. endogeneity ----------------
    print("=" * 104)
    print("1.  HOW ENDOGENOUS IS EACH FEATURE?  Spearman rho vs the spot move over its own")
    print("    measurement window (entry -> decision minute).  Persist decisions only;")
    print("    at the entry decision there is no post-entry window by construction.")
    print("=" * 104)
    rows = []
    for dec in ("persist:15", "persist:30", "persist:45", "persist:60"):
        s = fires[fires["decision"] == dec]
        move = s["spot_todate"].to_numpy(dtype=float)
        for f in ALL_FEATURES:
            x = s[f].to_numpy(dtype=float)
            m = np.isfinite(x) & np.isfinite(move)
            if m.sum() < 10:
                continue
            r = stats.spearmanr(x[m], move[m])
            rows.append({"decision": dec, "feature": f, "grade": FEATURE_GRADE[f][0],
                         "n": int(m.sum()), "rho_vs_window_spot_move": float(r.statistic),
                         "p": float(r.pvalue),
                         "rho_vs_abs_move": float(stats.spearmanr(
                             x[m], np.abs(move[m])).statistic)})
    E = pd.DataFrame(rows)
    piv = E.pivot_table(index="feature", columns="decision",
                        values="rho_vs_window_spot_move").round(3)
    pab = E.pivot_table(index="feature", columns="decision",
                        values="rho_vs_abs_move").round(3)
    print("\nsigned spot move over the window:")
    print(piv.to_string())
    print("\nABSOLUTE spot move over the window (how much the strike was 'come to'):")
    print(pab.to_string())
    worst = E.reindex(E["rho_vs_abs_move"].abs().sort_values(ascending=False).index).head(10)
    print("\nmost endogenous 10 (by |rho| against the absolute window move):")
    print(worst[["decision", "feature", "grade", "n", "rho_vs_abs_move"]]
          .round(3).to_string(index=False))
    E.to_csv("gate_b_flow_endogeneity.csv", index=False)
    out["endogeneity"] = E.to_dict(orient="records")

    # ---------------- 2. true OHLC vs close proxy ----------------
    print("\n" + "=" * 104)
    print("2.  DID THE TRUE-OHLC REBUILD CHANGE THE ANSWER RELATIVE TO THE CLOSE-ONLY PROXY?")
    print("=" * 104)
    comp = []
    for pop_name in ("pooled_fires", "midIV_fires", "pooled_controls", "midIV_controls"):
        g = pd.read_csv(f"gate_b_flow_grid_{pop_name}.csv")
        for label, feats in (("true OHLC (option high/low)", TRUE_OHLC),
                             ("close-only proxy (spot)", CLOSE_PROXY),
                             ("non-price-path (vol/OI/PCR)", NON_PATH)):
            s = g[g["feature"].isin(feats)].dropna(subset=["rho"])
            comp.append({"population": pop_name, "family": label, "cells": len(s),
                         "best_abs_rho": round(float(s["abs_rho"].max()), 3),
                         "best_p": float(s.loc[s["abs_rho"].idxmax(), "p"]),
                         "mean_abs_rho": round(float(s["abs_rho"].mean()), 3),
                         "raw_p_lt_05": int((s["p"] < 0.05).sum()),
                         "expected": round(0.05 * len(s), 1)})
    C = pd.DataFrame(comp)
    print(C.to_string(index=False))
    C.to_csv("gate_b_flow_family_compare.csv", index=False)
    out["true_ohlc_vs_proxy"] = C.to_dict(orient="records")

    # ---------------- 3. strongest NON-price-path association ----------------
    print("\n" + "=" * 104)
    print("3.  STRONGEST NON-PRICE-PATH ASSOCIATIONS (volume / open interest / put-call only)")
    print("=" * 104)
    best = {}
    for pop_name, ctrl_name in (("pooled_fires", "pooled_controls"),
                                ("midIV_fires", "midIV_controls")):
        g = pd.read_csv(f"gate_b_flow_grid_{pop_name}.csv")
        c = pd.read_csv(f"gate_b_flow_grid_{ctrl_name}.csv").set_index(
            ["feature", "decision", "target"])
        s = g[g["feature"].isin(NON_PATH)].dropna(subset=["rho"])
        top = s.sort_values("abs_rho", ascending=False).head(8)
        print(f"\n{pop_name}:")
        print(f"{'feature':>15} {'grade':>21} {'decision':>11} {'target':>9} "
              f"{'n':>4} {'rho':>7} {'p':>8} {'ctrl rho':>9} {'ctrl p':>8}")
        recs = []
        for _, r in top.iterrows():
            k = (r["feature"], r["decision"], r["target"])
            cr = float(c.loc[k, "rho"]) if k in c.index else np.nan
            cp = float(c.loc[k, "p"]) if k in c.index else np.nan
            print(f"{r['feature']:>15} {r['grade']:>21} {r['decision']:>11} {r['target']:>9} "
                  f"{int(r['n']):>4} {r['rho']:>7.3f} {r['p']:>8.4f} {cr:>9.3f} {cp:>8.4f}")
            recs.append({**r.to_dict(), "ctrl_rho": cr, "ctrl_p": cp})
        best[pop_name] = recs
    out["strongest_non_price_path"] = best

    # ---------------- 4. exogenous-only subgrid ----------------
    print("\n" + "=" * 104)
    print("4.  THE FULLY EXOGENOUS SUBGRID -- 09:15 open-interest snapshots only.")
    print("    Nothing about the intraday path can have caused these, so an association here")
    print("    would be the only genuinely clean predictive claim available in this study.")
    print("=" * 104)
    exo = [f for f, (gr, _) in FEATURE_GRADE.items() if gr == "exogenous"]
    ex = {}
    for pop_name in ("pooled_fires", "midIV_fires", "pooled_controls", "midIV_controls"):
        g = pd.read_csv(f"gate_b_flow_grid_{pop_name}.csv")
        s = g[g["feature"].isin(exo)].dropna(subset=["rho"])
        b = s.loc[s["abs_rho"].idxmax()]
        ex[pop_name] = {"cells": len(s), "raw_p_lt_05": int((s["p"] < 0.05).sum()),
                        "expected": round(0.05 * len(s), 1),
                        "best_feature": b["feature"], "best_decision": b["decision"],
                        "best_target": b["target"], "best_rho": round(float(b["rho"]), 3),
                        "best_p": float(b["p"])}
        e = ex[pop_name]
        print(f"{pop_name:>16}: {e['cells']} cells, {e['raw_p_lt_05']} at raw p<0.05 "
              f"(chance {e['expected']}); best = {e['best_feature']} / {e['best_decision']} / "
              f"{e['best_target']}  rho={e['best_rho']:+.3f}  p={e['best_p']:.4f}")
    out["exogenous_subgrid"] = ex

    with open("gate_b_flow_supplement_results.json", "w") as fh:
        json.dump(out, fh, indent=2, default=float)
    print("\nwrote gate_b_flow_supplement_results.json")


if __name__ == "__main__":
    main()
