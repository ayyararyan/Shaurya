#!/usr/bin/env python3
"""Minute OHLC for the FIXED contracts an iron butterfly actually trades, for spread estimation.

Per session: the 09:20 ATM strike, and ATM+-150 / ATM+-200 (the w=3 and w=4 wings), both sides,
resolved on ABSOLUTE strikes and pulled from whichever rolling rel_strike file carries them.
"""
from __future__ import annotations
import glob, pickle
from pathlib import Path
import numpy as np, pandas as pd
import nge_common as nc

OUT = Path("spread_paths.pkl")
ENTRY, EXIT = "09:20", "15:29"
OFFSETS = [0.0, 150.0, -150.0, 200.0, -200.0]


def targets() -> dict[str, set[float]]:
    q = pickle.load(open("folklore_required_quotes_20260823.pkl", "rb"))["quotes"]
    e = q[q["clock"] == ENTRY]
    out = {}
    for d, g in e.groupby("date"):
        ks = sorted(set(g[g["side"] == "CALL"]["strike"]) & set(g[g["side"] == "PUT"]["strike"]))
        if not ks:
            continue
        S = float(g["spot"].iloc[0])
        atm = float(min(ks, key=lambda k: abs(k - S)))
        out[d] = {atm + o for o in OFFSETS}
    return out


def build() -> pd.DataFrame:
    tg = targets()
    keep = []
    for f in sorted(glob.glob(str(nc.CACHE / "*" / "*.csv"))):
        side = "CALL" if "__CALL__" in f else "PUT" if "__PUT__" in f else None
        if side is None:
            continue
        fr = pd.read_csv(f, usecols=["open", "high", "low", "close", "strike", "datetime", "volume"])
        date = fr["datetime"].str.slice(0, 10)
        ok = np.array([(d in tg) and (float(k) in tg[d])
                       for d, k in zip(date.to_numpy(), fr["strike"].to_numpy())])
        if not ok.any():
            continue
        sub = fr[ok].copy()
        sub["date"] = date[ok]
        sub["clock"] = sub["datetime"].str.slice(11, 16)
        sub["side"] = side
        keep.append(sub[["date", "clock", "side", "strike", "open", "high", "low", "close", "volume"]])
    t = pd.concat(keep, ignore_index=True)
    t = t[(t["clock"] >= ENTRY) & (t["clock"] <= EXIT) & (t["close"] > 0)]
    t = t.sort_values(["date", "clock", "side", "strike", "volume"], ascending=[True] * 4 + [False])
    return t.drop_duplicates(["date", "clock", "side", "strike"], keep="first").reset_index(drop=True)


if __name__ == "__main__":
    t = build()
    t.to_pickle(OUT)
    print("rows", len(t), "dates", t["date"].nunique(), "contracts/day",
          round(t.groupby("date").apply(lambda g: g.groupby(["side", "strike"]).ngroups).mean(), 2))
