#!/usr/bin/env python3
"""VAL-02: hand-check three sessions of vrp_forecast_panel.pkl against the raw archive CSVs."""
from __future__ import annotations
import glob, json, math
import numpy as np, pandas as pd
import nge_common as nc, vrp_forecast_common as vfc

CHECK = ["2021-09-08", "2024-02-20", "2026-01-29"]   # same three days the project hand-checked before
panel = vfc.load_panel().set_index("date")
files = sorted(glob.glob(str(nc.CACHE / "*" / "*.csv")))
out = {}

for d in CHECK:
    row = panel.loc[d]
    year = d[:4]
    frames = []
    for f in [x for x in files if f"/{year}/" in x]:
        head = pd.read_csv(f, usecols=["datetime"], nrows=1)
        frames.append(f)
    # read only files whose window covers d
    keep = [f for f in frames if f.split("/")[-1].split("__")[0].split("_")[0] <= d <= f.split("/")[-1].split("__")[0].split("_")[1]]
    raw = pd.concat([pd.read_csv(f, usecols=nc.USE_COLS).assign(
        side="CALL" if "__CALL__" in f else "PUT") for f in keep], ignore_index=True)
    raw["date"] = raw["datetime"].str.slice(0, 10)
    raw["clock"] = raw["datetime"].str.slice(11, 16)
    day0915 = raw[(raw["date"] == d) & (raw["clock"] == "09:15") & (raw["close"] > 0)]
    S0 = float(day0915["spot"].iloc[0])
    strikes = day0915["strike"].to_numpy(float)
    atm = float(strikes[np.argmin(np.abs(strikes - S0))])
    rec = {"panel_spot_open": float(row["spot_open"]), "raw_spot_open": S0,
           "panel_atm": float(row["atm_strike"]), "raw_atm": atm,
           "panel_expiry": row["expiry"], "panel_n_sess": float(row["n_sess"])}
    ivs = {}
    for side in ("CALL", "PUT"):
        r = day0915[(day0915["side"] == side) & (day0915["strike"] == atm)]
        if r.empty:
            continue
        px = float(r.sort_values("volume", ascending=False)["close"].iloc[0])
        ivs[side] = {"price": px,
                     "iv": vfc.invert_iv(side, px, S0, atm, float(row["T_trading"])) * 100.0}
    rec["raw_iv_sides"] = ivs
    rec["raw_iv_mean"] = float(np.mean([v["iv"] for v in ivs.values()]))
    rec["panel_iv"] = float(row["iv"])
    rec["iv_abs_diff"] = abs(rec["raw_iv_mean"] - rec["panel_iv"])

    # realised variance from 09:15 on d to 15:29 on expiry, straight off the raw spot column
    # VAL-02 spot source: the ATM/CALL files, i.e. exactly what load_spot() reads.  The wider
    # archive is NOT safe for this: some option CSVs carry a different index's spot (see
    # vrp_forecast_archive_spot_audit.json), which is what produced the 2021-09-08 blow-up in
    # the first draft of this check.
    atm_files = [f for f in keep if "__ATM__" in f and "__CALL__" in f]
    spot_raw = pd.concat([pd.read_csv(f, usecols=["spot", "datetime"]) for f in atm_files],
                         ignore_index=True)
    spot_raw["date"] = spot_raw["datetime"].str.slice(0, 10)
    spot_raw["clock"] = spot_raw["datetime"].str.slice(11, 16)
    spot = spot_raw[["date", "clock", "spot"]].drop_duplicates(["date", "clock"]).sort_values(["date", "clock"])
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")]
    win = spot[(spot["date"] >= d) & (spot["date"] <= row["expiry"])]
    tot_intra = 0.0; tot_on = 0.0; prev_close = None
    for dt, g in win.groupby("date", sort=True):
        px = g["spot"].to_numpy(float)
        if prev_close is not None:
            tot_on += math.log(px[0] / prev_close) ** 2
        tot_intra += float(np.sum(np.diff(np.log(px)) ** 2))
        prev_close = float(px[-1])
    T = float(row["T_trading"])
    rec["raw_rv_intra"] = math.sqrt(tot_intra / T) * 100
    rec["panel_rv_intra"] = float(row["rv_intra"])
    rec["raw_rv_incl"] = math.sqrt((tot_intra + tot_on) / T) * 100
    rec["panel_rv_incl"] = float(row["rv_incl"])
    rec["rv_intra_abs_diff"] = abs(rec["raw_rv_intra"] - rec["panel_rv_intra"])
    rec["rv_incl_abs_diff"] = abs(rec["raw_rv_incl"] - rec["panel_rv_incl"])
    out[d] = rec

print(json.dumps(out, indent=2, default=str))
worst = max(max(v["iv_abs_diff"], v["rv_intra_abs_diff"], v["rv_incl_abs_diff"]) for v in out.values())
print(f"\nWORST ABSOLUTE DISCREPANCY ACROSS ALL THREE DAYS: {worst:.10f} volatility points")
json.dump(out, open("vrp_forecast_handcheck.json", "w"), indent=2, default=str)
