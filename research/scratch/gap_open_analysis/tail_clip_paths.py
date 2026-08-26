#!/usr/bin/env python3
"""Minute paths of a FIXED absolute strike, for the stop-loss comparator (ROB-01).

The archive's ``rel_strike`` label rolls with spot, so an "ATM" file is a re-struck straddle, not
a contract.  Using it produces a straddle that resets to the money every minute and cannot lose.
This module resolves the 09:20 ATM strike per session and then collects that ONE contract's
minute path from whichever rel_strike file happens to carry it.
"""
from __future__ import annotations

import glob
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

import nge_common as nc

OUT = Path("tail_clip_paths.pkl")
ENTRY, EXIT = "09:20", "15:29"


def target_strikes() -> dict[str, float]:
    q = pickle.load(open("folklore_required_quotes_20260823.pkl", "rb"))["quotes"]
    e = q[q["clock"] == ENTRY]
    out = {}
    for d, g in e.groupby("date"):
        ks = sorted(set(g[g["side"] == "CALL"]["strike"]) & set(g[g["side"] == "PUT"]["strike"]))
        if not ks:
            continue
        S = float(g["spot"].iloc[0])
        out[d] = float(min(ks, key=lambda k: abs(k - S)))
    return out


def build() -> pd.DataFrame:
    targets = target_strikes()
    keep = []
    for f in sorted(glob.glob(str(nc.CACHE / "*" / "*.csv"))):
        side = "CALL" if "__CALL__" in f else "PUT" if "__PUT__" in f else None
        if side is None:
            continue
        fr = pd.read_csv(f, usecols=["close", "strike", "datetime", "volume"])
        date = fr["datetime"].str.slice(0, 10)
        tgt = date.map(targets)
        m = (tgt.notna()) & (np.isclose(fr["strike"].to_numpy(dtype=float),
                                        tgt.fillna(-1).to_numpy(dtype=float)))
        if not m.any():
            continue
        sub = fr[m].copy()
        sub["date"] = date[m]
        sub["clock"] = sub["datetime"].str.slice(11, 16)
        sub["side"] = side
        keep.append(sub[["date", "clock", "side", "strike", "close", "volume"]])
    tape = pd.concat(keep, ignore_index=True)
    tape = tape[(tape["clock"] >= ENTRY) & (tape["clock"] <= EXIT) & (tape["close"] > 0)]
    tape = tape.sort_values(["date", "clock", "side", "volume"], ascending=[True] * 3 + [False])
    tape = tape.drop_duplicates(["date", "clock", "side"], keep="first")
    return tape.reset_index(drop=True)


if __name__ == "__main__":
    t = build()
    t.to_pickle(OUT)
    print("rows", len(t), "dates", t["date"].nunique())
    print(t.head())
