#!/usr/bin/env python3
"""CROSS-CHECK ONLY: strike-tracked REAL PUT premiums for the censored Gate-A trade.

This is a secondary, clearly-labelled cross-check of the Black-Scholes proxy used
everywhere else in this study.  It is NOT the primary evidence and it is NOT a clean
replication, for two reasons stated up front:

1. Only the ATM and ATM+/-1 PUT minute files are hydrated in the local cache.  A day is
   usable only if the 09:17 entry strike is still carried by one of those three series at
   the exit minute.  Days where the running ATM has rolled by two or more strikes drop
   out, and those are disproportionately the biggest-mover days -- so the surviving
   subsample is biased towards smaller moves.
2. These are minute-bar closes, not executable bid/ask fills.  No spread, slippage, or
   brokerage.

The whole point of the exercise is that the 09:17 strike is TRACKED through the exit, so
this does NOT repeat the earlier data bug in which the labelled "ATM" premium series rolled
strike mid-session and manufactured spurious losses.

It additionally reports the realized change in the option's own implied volatility over the
holding window.  The Black-Scholes proxy freezes implied volatility at the opening value, so
an IV-change component is structurally absent there; this is the only place in the study
where that component is observable at all.

Offline analysis only.  No broker, credential, network, or order path.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from gate_a_censoring_common import gate_a_subset, load_paths, reproduction_guard

CACHE = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options"
)
MANIFEST = CACHE / "manifest.jsonl"
REL_STRIKES = ("ATM-1", "ATM", "ATM+1")
HORIZONS = (10, 15, 20, 25, 30, 45, 60, None)
ENTRY_CLOCK = "09:17"


def manifest_rows() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def cached_path(row: dict) -> Path:
    return CACHE / str(row["from_date"])[:4] / Path(str(row["path"])).name


def load_put_quotes() -> pd.DataFrame:
    frames = []
    for row in manifest_rows():
        if row.get("drv_option_type") != "PUT" or row.get("strike") not in REL_STRIKES:
            continue
        path = cached_path(row)
        if not path.exists():
            continue
        frame = pd.read_csv(path, usecols=["close", "iv", "strike", "datetime", "rel_strike"])
        frames.append(frame)
    if not frames:
        raise FileNotFoundError("no hydrated ATM/ATM+/-1 PUT files found in the local cache")
    quotes = pd.concat(frames, ignore_index=True)
    quotes["datetime"] = pd.to_datetime(quotes["datetime"], errors="raise")
    quotes["date"] = quotes["datetime"].dt.strftime("%Y-%m-%d")
    quotes["clock"] = quotes["datetime"].dt.strftime("%H:%M")
    quotes["minutes"] = quotes["datetime"].dt.hour * 60 + quotes["datetime"].dt.minute
    quotes = quotes[quotes["close"] > 0]
    return quotes.drop_duplicates(subset=["date", "clock", "strike"], keep="first")


def label(horizon: int | None) -> str:
    return "close" if horizon is None else f"{horizon}m"


def main() -> None:
    paths = load_paths()
    gate = gate_a_subset(paths)
    reproduction_guard(gate)

    quotes = load_put_quotes()
    print("CROSS-CHECK: strike-tracked REAL PUT minute-bar closes (ATM / ATM+/-1 hydration only)")
    print(f"hydrated PUT quote rows: {len(quotes):,}")
    print(f"Gate-A PUT trade days   : {len(gate)}\n")

    entry_minute = 9 * 60 + 17
    records = []
    for p in gate:
        d = p["date"]
        day = quotes[quotes["date"] == d]
        if day.empty:
            continue
        entry_bar = day[(day["clock"] == ENTRY_CLOCK) & (day["rel_strike"] == "ATM")]
        if entry_bar.empty:
            continue
        strike = float(entry_bar["strike"].iloc[0])
        entry_price = float(entry_bar["close"].iloc[0])
        entry_iv = float(entry_bar["iv"].iloc[0])
        if entry_price <= 0:
            continue
        tracked = day[day["strike"] == strike].sort_values("minutes")
        row = {
            "date": d,
            "strike": strike,
            "bs_C0": p["C0"],
            "real_C0": entry_price,
            "entry_iv": entry_iv,
        }
        for horizon in HORIZONS:
            cutoff = entry_minute + horizon if horizon is not None else 15 * 60 + 29
            avail = tracked[(tracked["minutes"] >= entry_minute) & (tracked["minutes"] <= cutoff)]
            if avail.empty:
                row[f"real_{label(horizon)}"] = np.nan
                row[f"iv_{label(horizon)}"] = np.nan
                continue
            last = avail.iloc[-1]
            # Require the tracked strike to still be quoted at (or within 2 min of) the horizon.
            if horizon is not None and int(last["minutes"]) < cutoff - 2:
                row[f"real_{label(horizon)}"] = np.nan
                row[f"iv_{label(horizon)}"] = np.nan
                continue
            row[f"real_{label(horizon)}"] = (float(last["close"]) - entry_price) / entry_price * 100.0
            row[f"iv_{label(horizon)}"] = float(last["iv"]) - entry_iv
        records.append(row)

    real = pd.DataFrame(records)
    real.to_csv("gate_a_real_premium_crosscheck.csv", index=False)
    print(f"days with a usable 09:17 ATM entry quote: {len(real)} of {len(gate)}")

    print("\nENTRY PREMIUM LEVEL: does the Black-Scholes proxy price the option sensibly?")
    both = real.dropna(subset=["bs_C0", "real_C0"])
    ratio = both["bs_C0"] / both["real_C0"]
    print(f"  N={len(both)}  median BS/real entry premium ratio = {ratio.median():.3f}  "
          f"mean = {ratio.mean():.3f}  IQR = [{ratio.quantile(0.25):.3f}, {ratio.quantile(0.75):.3f}]")
    print(f"  median real entry premium = {both['real_C0'].median():.1f} pts; "
          f"median BS entry premium = {both['bs_C0'].median():.1f} pts")

    print("\nCENSORED RETURN, REAL STRIKE-TRACKED PREMIUM vs the Black-Scholes proxy")
    print("(no stop, no target, no gap-fill exit -- the same pure censoring rule)")
    from gate_a_horizon_scan import censored_returns

    header = (f"{'H':>7} {'N real':>7} {'real mean':>10} {'real med':>10} {'real win%':>10} "
              f"{'real p':>9} | {'BS mean':>9} {'BS med':>9} {'BS win%':>8} {'BS p':>8}")
    print(header)
    print("-" * len(header))
    for horizon in HORIZONS:
        col = real[f"real_{label(horizon)}"].dropna()
        bs_all = censored_returns(gate, horizon)
        keep = real[f"real_{label(horizon)}"].notna().to_numpy()
        dates_kept = set(real.loc[keep, "date"])
        bs_matched = np.asarray([
            r for p, r in zip(gate, censored_returns(gate, horizon)) if p["date"] in dates_kept
        ])
        if len(col) < 3:
            print(f"{label(horizon):>7} {len(col):>7}  -- too few usable days --")
            continue
        p_real = stats.ttest_1samp(col, 0.0).pvalue
        p_bs = stats.ttest_1samp(bs_matched, 0.0).pvalue
        print(
            f"{label(horizon):>7} {len(col):>7} {col.mean():>+9.2f}% {col.median():>+9.2f}% "
            f"{(col > 0).mean()*100:>9.1f}% {p_real:>9.4f} | {bs_matched.mean():>+8.2f}% "
            f"{np.median(bs_matched):>+8.2f}% {np.mean(bs_matched>0)*100:>7.1f}% {p_bs:>8.4f}"
        )
        del bs_all

    print("\n  (The 'BS' columns are restricted to the SAME days that survive hydration, so the")
    print("   two sides are comparable.  Differences are the joint effect of the intraday implied")
    print("   volatility path, discrete bar closes, and the constant-IV assumption.)")

    print("\nREALIZED IMPLIED-VOLATILITY CHANGE ON THE TRACKED CONTRACT")
    print("(the component the constant-IV Black-Scholes proxy cannot see, in IV points)")
    print(f"{'H':>7} {'N':>5} {'mean dIV':>10} {'median dIV':>12} {'share rising':>14}")
    print("-" * 52)
    for horizon in HORIZONS:
        col = real[f"iv_{label(horizon)}"].dropna()
        if len(col) < 3:
            continue
        print(f"{label(horizon):>7} {len(col):>5} {col.mean():>+9.2f} {col.median():>+11.2f} "
              f"{(col > 0).mean()*100:>13.1f}%")

    print("\nAgreement between the two return series, on days where both exist:")
    for horizon in HORIZONS:
        keep = real[f"real_{label(horizon)}"].notna().to_numpy()
        dates_kept = set(real.loc[keep, "date"])
        bs_matched = np.asarray([
            r for p, r in zip(gate, censored_returns(gate, horizon)) if p["date"] in dates_kept
        ])
        col = real.loc[keep, f"real_{label(horizon)}"].to_numpy()
        if len(col) < 5:
            continue
        rho = stats.spearmanr(col, bs_matched).statistic
        same_sign = np.mean(np.sign(col) == np.sign(bs_matched)) * 100.0
        d = col - bs_matched
        print(f"  H={label(horizon):>5}: N={len(col):>3} Spearman rho={rho:+.3f} "
              f"same-sign={same_sign:5.1f}% mean(real-BS)={d.mean():+6.2f}pp "
              f"paired p={stats.ttest_1samp(d, 0.0).pvalue:.4f}")

    print("\nHOW MUCH OF THE PROXY'S OPTIMISM IS JUST AN ENTRY-PRICE LEVEL ERROR?")
    print("The proxy prices the 09:17 entry premium below the traded price (median ratio above),")
    print("which mechanically inflates any percentage return computed on it.  Rescaling the")
    print("proxy return by the per-day BS/real entry-premium ratio removes that channel; what")
    print("survives is attributable to the intraday implied-volatility path and bar mechanics.")
    print(f"  {'H':>7} {'real':>9} {'BS':>9} {'BS rescaled':>13} {'level channel':>14} {'IV/other':>10}")
    print("  " + "-" * 66)
    for horizon in HORIZONS:
        keep = real[f"real_{label(horizon)}"].notna().to_numpy()
        dates_kept = set(real.loc[keep, "date"])
        bs_matched = np.asarray([
            r for p, r in zip(gate, censored_returns(gate, horizon)) if p["date"] in dates_kept
        ])
        col = real.loc[keep, f"real_{label(horizon)}"].to_numpy()
        scale = (real.loc[keep, "bs_C0"] / real.loc[keep, "real_C0"]).to_numpy()
        if len(col) < 5:
            continue
        rescaled = bs_matched * scale
        print(f"  {label(horizon):>7} {col.mean():>+8.2f}% {bs_matched.mean():>+8.2f}% "
              f"{rescaled.mean():>+12.2f}% {(rescaled - bs_matched).mean():>+13.2f}pp "
              f"{(col - rescaled).mean():>+9.2f}pp")

    print("\nWrote gate_a_real_premium_crosscheck.csv")


if __name__ == "__main__":
    main()
