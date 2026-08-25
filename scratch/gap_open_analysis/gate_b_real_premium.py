#!/usr/bin/env python3
"""Gate B on REAL traded option premiums: entry timing, the implied-volatility path, and
the hold-to-close headline test.

Covers parts A, B and C of the Gate-B real-premium validation brief.

The primary object here is the **traded one-minute bar close of the actual entry strike**,
tracked through the session -- not Dhan's labelled-ATM series, which rolls strike
mid-session and manufactured spurious losses in an earlier pass of this project.  The
Black-Scholes proxy that ``bs_gap_fill_pnl.py`` relies on is carried alongside as the
comparison, restricted to identical days so the two are directly comparable.

``bs_gap_fill_pnl.py`` prices every minute with ``bs_call(spot, K, T, r, opening_iv)``.
Implied volatility is therefore frozen at the day's OPENING value for the whole session,
and that construction is structurally incapable of showing any intraday volatility change,
including the opening volatility crush.  Confirmed by direct reading of that file, and
re-confirmed numerically here: the reproduction guard recovers its published trailing-stop
means from a rebuilt constant-IV series.

Offline analysis only.  No broker, credential, exchange network, or order path.  No live
order exists or is authorised.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from bs_gap_fill_pnl import RISK_FREE_RATE, bs_call
from gate_b_common import (
    CLOCK_EXITS,
    clock_to_minutes,
    gate_b_subset,
    load_paths,
    reproduction_guard,
    rule_return,
    rule_returns,
)

IV_OFFSETS = (0, 5, 10, 15, 20, 30, 45, 60, 90, 120)


def describe(x: np.ndarray, label: str) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"label": label, "N": len(x)}
    t = stats.ttest_1samp(x, 0.0)
    try:
        w = stats.wilcoxon(x).pvalue
    except ValueError:
        w = np.nan
    return {
        "label": label,
        "N": int(len(x)),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "win": float((x > 0).mean() * 100.0),
        "sd": float(x.std(ddof=1)),
        "p": float(t.pvalue),
        "wilcoxon": float(w),
    }


def print_row(d: dict) -> None:
    if d.get("N", 0) < 2:
        print(f"{d['label']:>34} {d.get('N', 0):>4}   -- too few usable days --")
        return
    print(
        f"{d['label']:>34} {d['N']:>4} {d['mean']:>+9.2f}% {d['median']:>+9.2f}% "
        f"{d['win']:>7.1f}% {d['sd']:>8.1f} {d['p']:>9.4f} {d['wilcoxon']:>10.4f}"
    )


def header() -> None:
    print(
        f"{'variant':>34} {'N':>4} {'mean':>10} {'median':>10} {'win%':>8} {'sd':>8} "
        f"{'p vs 0':>9} {'Wilcoxon':>10}"
    )
    print("-" * 100)


def index_at_offset(path: dict, offset: int) -> int | None:
    """Last observed minute at or before ``offset`` minutes after entry."""
    eligible = np.flatnonzero(path["elapsed"] <= offset)
    if len(eligible) == 0:
        return None
    i = int(eligible[-1])
    if path["elapsed"][i] < offset - 2:
        return None
    return i


def main() -> None:
    paths = load_paths()
    gate = gate_b_subset(paths)
    reproduction_guard(gate)

    print("=" * 100)
    print("GATE B ON REAL TRADED PREMIUMS -- entry timing, implied-volatility path, "
          "hold-to-close")
    print("=" * 100)
    print(f"Gate-B fires                                   : {len(gate)}")
    print(f"Wider non-expiry gap-down fill universe        : {len(paths)}")
    print(f"Date range                                     : {gate[0]['date']} .. {gate[-1]['date']}")
    print("Reproduction guard                             : PASSED "
          "(fire set, entry clocks, strikes, BS entry premiums,\n"
          "                                                  and all three published "
          "trailing-stop means recovered)")

    # ------------------------------------------------------------------ A. entry timing
    print("\n" + "=" * 100)
    print("A.  GAP-FILL ENTRY TIMING")
    print("=" * 100)
    mins = np.asarray([p["entry_minute"] for p in gate], dtype=float)

    def as_clock(m: float) -> str:
        m = int(round(m))
        return f"{m // 60:02d}:{m % 60:02d}"

    qs = np.percentile(mins, [0, 25, 50, 75, 100])
    print(f"  N = {len(gate)}")
    print(f"  min      {as_clock(qs[0])}")
    print(f"  Q1       {as_clock(qs[1])}")
    print(f"  median   {as_clock(qs[2])}")
    print(f"  Q3       {as_clock(qs[3])}")
    print(f"  max      {as_clock(qs[4])}")
    print(f"  mean     {as_clock(mins.mean())}")
    print("\n  Minutes elapsed from 09:15 open to entry:")
    el = mins - clock_to_minutes("09:15")
    print(f"    min={el.min():.0f}  Q1={np.percentile(el,25):.0f}  median={np.median(el):.0f}  "
          f"Q3={np.percentile(el,75):.0f}  max={el.max():.0f}")
    print("\n  Cumulative share of fires by clock:")
    for c in ("09:20", "09:30", "09:45", "10:00", "10:30", "11:00", "12:00", "13:00", "14:30"):
        n = int((mins <= clock_to_minutes(c)).sum())
        print(f"    by {c}: {n:>2}/{len(gate)}  ({n/len(gate)*100:>5.1f}%)")
    print("\n  Full sorted list of entry clocks:")
    print("   ", ", ".join(sorted(p["entry_clock"] for p in gate)))

    # -------------------------------------------------- B. implied-volatility at entry
    print("\n" + "=" * 100)
    print("B.  THE IMPLIED-VOLATILITY PATH AT AND AFTER GATE-B ENTRY")
    print("=" * 100)
    print("All figures are the OBSERVED implied volatility of the ACTUAL traded contract")
    print("bought at entry (the tracked strike), from the Dhan minute tape.  The")
    print("Black-Scholes series used by bs_gap_fill_pnl.py cannot produce any of this: it")
    print("freezes IV at the day's opening value.\n")

    iv_rows = []
    for p in gate:
        iv = p["real_iv"]
        if not np.isfinite(iv[0]):
            continue
        row = {
            "date": p["date"],
            "entry_clock": p["entry_clock"],
            "opening_iv_pct": p["opening_iv"] * 100.0,
            "entry_iv": float(iv[0]),
        }
        for off in IV_OFFSETS:
            i = index_at_offset(p, off)
            row[f"iv_{off}m"] = float(iv[i]) if (i is not None and np.isfinite(iv[i])) else np.nan
        finite = np.flatnonzero(np.isfinite(iv))
        row["iv_close"] = float(iv[finite[-1]]) if len(finite) else np.nan
        row["exit_clock"] = p["clocks"][finite[-1]] if len(finite) else None
        iv_rows.append(row)
    ivdf = pd.DataFrame(iv_rows)

    print(f"  Fires with an observed entry IV on the traded contract: {len(ivdf)}/{len(gate)}")
    print(f"\n  Opening IV (the gate's own mid_14_18 bucket variable), mean "
          f"{ivdf['opening_iv_pct'].mean():.2f}, median {ivdf['opening_iv_pct'].median():.2f}")
    print(f"  IV of the contract actually bought at entry,        mean "
          f"{ivdf['entry_iv'].mean():.2f}, median {ivdf['entry_iv'].median():.2f}")

    print("\n  IV of the traded contract, level and change from entry (IV points):")
    print(f"    {'offset':>8} {'N':>4} {'mean IV':>9} {'median IV':>11} "
          f"{'mean dIV':>10} {'median dIV':>12} {'share rising':>14}")
    print("    " + "-" * 74)
    for off in IV_OFFSETS:
        col = ivdf[f"iv_{off}m"].dropna()
        if len(col) < 3:
            continue
        d = (ivdf[f"iv_{off}m"] - ivdf["entry_iv"]).dropna()
        print(f"    {off:>6}m {len(col):>4} {col.mean():>9.2f} {col.median():>11.2f} "
              f"{d.mean():>+10.2f} {d.median():>+12.2f} {(d > 0).mean()*100:>13.1f}%")
    dclose = (ivdf["iv_close"] - ivdf["entry_iv"]).dropna()
    print(f"    {'close':>7} {len(dclose):>4} {ivdf['iv_close'].mean():>9.2f} "
          f"{ivdf['iv_close'].median():>11.2f} {dclose.mean():>+10.2f} "
          f"{dclose.median():>+12.2f} {(dclose > 0).mean()*100:>13.1f}%")
    t = stats.ttest_1samp(dclose, 0.0)
    print(f"\n    entry-to-close change in the traded contract's own IV: "
          f"mean {dclose.mean():+.2f} vol points, t={t.statistic:+.2f}, p={t.pvalue:.4f}")

    # session-level ATM IV shape: does the crush happen before or after a typical entry?
    print("\n  Session shape of at-the-money implied volatility on these 33 days")
    print("  (running-ATM contract, so it does not depend on the tracked strike surviving):")
    grid = ("09:15", "09:17", "09:20", "09:25", "09:30", "09:45", "10:00", "10:30",
            "11:00", "12:00", "13:00", "14:00", "15:00", "15:25")
    levels = {c: [] for c in grid}
    for p in gate:
        m = dict(zip(p["atm_iv_clocks"], p["atm_iv_vals"]))
        for c in grid:
            if c in m:
                levels[c].append(m[c])
    base = np.asarray(levels["09:17"], dtype=float)
    print(f"    {'clock':>7} {'N':>4} {'mean ATM IV':>13} {'median':>9} "
          f"{'mean vs 09:17':>15}")
    print("    " + "-" * 52)
    ref = {}
    for p in gate:
        m = dict(zip(p["atm_iv_clocks"], p["atm_iv_vals"]))
        ref[p["date"]] = m.get("09:17", np.nan)
    for c in grid:
        vals, diffs = [], []
        for p in gate:
            m = dict(zip(p["atm_iv_clocks"], p["atm_iv_vals"]))
            if c in m:
                vals.append(m[c])
                if np.isfinite(ref[p["date"]]):
                    diffs.append(m[c] - ref[p["date"]])
        if len(vals) < 3:
            continue
        vals = np.asarray(vals)
        dm = np.mean(diffs) if diffs else np.nan
        print(f"    {c:>7} {len(vals):>4} {vals.mean():>13.2f} {np.median(vals):>9.2f} "
              f"{dm:>+15.2f}")
    del base

    # --- what the IV move is worth, in premium terms, on the actual trade ---
    print("\n  WHAT THE IV MOVE COSTS, IN PREMIUM TERMS")
    print("  Repricing the tracked contract at every minute with (a) the OBSERVED IV of")
    print("  that minute and (b) the IV frozen at its entry value.  The difference is the")
    print("  volatility leg of the trade, expressed in points and as a share of the traded")
    print("  entry premium.  Both legs use observed spot and observed time to expiry, so")
    print("  the only thing that differs between them is the volatility path.")
    vol_rows = []
    for p in gate:
        iv = p["real_iv"]
        if not np.isfinite(iv[0]) or not np.isfinite(p["real_prices"][0]):
            continue
        iv0 = iv[0] / 100.0
        entry_dt = pd.Timestamp(f"{p['date']} {p['entry_clock']}:00")
        expiry_dt = pd.Timestamp(p["expiry"]) + pd.Timedelta(hours=15, minutes=30)
        finite = np.flatnonzero(np.isfinite(iv) & np.isfinite(p["real_prices"]))
        if len(finite) < 2:
            continue
        j = int(finite[-1])
        S = float(p["spots"][j])
        T = max(
            (expiry_dt - pd.Timestamp(f"{p['date']} {p['clocks'][j]}:00")).total_seconds()
            / (365.0 * 24 * 3600),
            1e-6,
        )
        px_obs = bs_call(S, p["K"], T, RISK_FREE_RATE, iv[j] / 100.0)
        px_frozen = bs_call(S, p["K"], T, RISK_FREE_RATE, iv0)
        C0_real = float(p["real_prices"][0])
        vol_rows.append(
            {
                "date": p["date"],
                "entry_clock": p["entry_clock"],
                "C0_real": C0_real,
                "iv_entry": iv[0],
                "iv_exit": iv[j],
                "d_iv": iv[j] - iv[0],
                "vol_leg_pts": px_obs - px_frozen,
                "vol_leg_pct_of_entry": (px_obs - px_frozen) / C0_real * 100.0,
                "bs_fit_err_pct": (bs_call(p["S0"], p["K"],
                                           max((expiry_dt - entry_dt).total_seconds()
                                               / (365.0 * 24 * 3600), 1e-6),
                                           RISK_FREE_RATE, iv0) - C0_real) / C0_real * 100.0,
            }
        )
    vdf = pd.DataFrame(vol_rows)
    print(f"\n    N = {len(vdf)}")
    print(f"    entry-to-close IV change      : mean {vdf['d_iv'].mean():+.2f} pts, "
          f"median {vdf['d_iv'].median():+.2f} pts")
    print(f"    volatility leg, premium points: mean {vdf['vol_leg_pts'].mean():+.2f}, "
          f"median {vdf['vol_leg_pts'].median():+.2f}")
    print(f"    volatility leg, % of the traded entry premium: "
          f"mean {vdf['vol_leg_pct_of_entry'].mean():+.2f}%, "
          f"median {vdf['vol_leg_pct_of_entry'].median():+.2f}%")
    tv = stats.ttest_1samp(vdf["vol_leg_pct_of_entry"], 0.0)
    print(f"    t = {tv.statistic:+.2f}, p = {tv.pvalue:.4f}, "
          f"share negative = {(vdf['vol_leg_pct_of_entry'] < 0).mean()*100:.1f}%")
    print(f"\n    Sanity check on the repricing: Black-Scholes at the observed entry IV")
    print(f"    misprices the traded entry premium by a median of "
          f"{vdf['bs_fit_err_pct'].median():+.2f}% "
          f"(IQR {vdf['bs_fit_err_pct'].quantile(0.25):+.2f}% to "
          f"{vdf['bs_fit_err_pct'].quantile(0.75):+.2f}%).")
    vdf.to_csv("gate_b_iv_decomposition.csv", index=False)
    ivdf.to_csv("gate_b_iv_path.csv", index=False)

    # ------------------------------------------------------- C. hold-to-close headline
    print("\n" + "=" * 100)
    print("C.  HOLD-TO-CLOSE ON REAL TRADED PREMIUMS vs THE BLACK-SCHOLES PROXY")
    print("=" * 100)
    real_close = rule_returns(gate, "real_prices")
    bs_close = rule_returns(gate, "bs_prices")
    usable = np.isfinite(real_close)
    print(f"  Fires priceable on real premiums, entry to 15:29: "
          f"{int(usable.sum())}/{len(gate)}")

    header()
    print_row(describe(real_close, "REAL premium, hold to close"))
    print_row(describe(bs_close[usable], "BS proxy, same days"))
    print_row(describe(bs_close, "BS proxy, all 33"))
    diff = (real_close - bs_close)[usable]
    td = stats.ttest_1samp(diff, 0.0)
    print(f"\n  Paired real minus proxy: mean {diff.mean():+.2f}pp, "
          f"median {np.median(diff):+.2f}pp, t={td.statistic:+.2f}, p={td.pvalue:.4f}")
    rho = stats.spearmanr(real_close[usable], bs_close[usable]).statistic
    same = np.mean(np.sign(real_close[usable]) == np.sign(bs_close[usable])) * 100.0
    print(f"  Agreement: Spearman rho={rho:+.3f}, same-sign={same:.1f}%")

    print("\n  Entry-premium level check (the mechanical channel):")
    c0r = np.asarray([p["real_prices"][0] for p in gate], dtype=float)
    c0b = np.asarray([p["C0_bs"] for p in gate], dtype=float)
    ratio = c0b / c0r
    print(f"    median BS/real entry premium ratio = {np.median(ratio):.3f}  "
          f"(IQR {np.percentile(ratio,25):.3f} to {np.percentile(ratio,75):.3f})")
    print(f"    median traded entry premium = {np.median(c0r):.1f} pts; "
          f"median modelled = {np.median(c0b):.1f} pts")
    rescaled = bs_close * ratio
    print(f"    BS return rescaled to the traded entry price: mean "
          f"{np.nanmean(rescaled[usable]):+.2f}%")
    print(f"    entry-price level channel  : "
          f"{np.nanmean((rescaled - bs_close)[usable]):+.2f}pp")
    print(f"    IV path / everything else  : "
          f"{np.nanmean((real_close - rescaled)[usable]):+.2f}pp")

    print("\n  Split by whether the day was a true reversal (the gate's own claim):")
    header()
    rev = np.asarray([p["reversed"] for p in gate])
    print_row(describe(real_close[rev], f"REAL, true reversal days"))
    print_row(describe(real_close[~rev], f"REAL, false fires"))
    print_row(describe(bs_close[rev], f"BS proxy, true reversal days"))
    print_row(describe(bs_close[~rev], f"BS proxy, false fires"))

    print("\n  Chronological quartile stability of the real hold-to-close return:")
    order = np.argsort([p["date"] for p in gate])
    quarts = np.array_split(order, 4)
    for i, q in enumerate(quarts, 1):
        v = real_close[q]
        v = v[np.isfinite(v)]
        print(f"    Q{i} ({gate[q[0]]['date']} .. {gate[q[-1]]['date']}, N={len(v)}): "
              f"mean {v.mean():+7.2f}%  median {np.median(v):+7.2f}%  "
              f"win {np.mean(v>0)*100:5.1f}%")

    out = pd.DataFrame(
        {
            "date": [p["date"] for p in gate],
            "entry_clock": [p["entry_clock"] for p in gate],
            "K": [p["K"] for p in gate],
            "reversed": [p["reversed"] for p in gate],
            "real_C0": c0r,
            "bs_C0": c0b,
            "real_hold_to_close_pct": real_close,
            "bs_hold_to_close_pct": bs_close,
        }
    )
    out.to_csv("gate_b_real_premium.csv", index=False)
    print("\nWrote gate_b_real_premium.csv, gate_b_iv_path.csv, gate_b_iv_decomposition.csv")


if __name__ == "__main__":
    main()
