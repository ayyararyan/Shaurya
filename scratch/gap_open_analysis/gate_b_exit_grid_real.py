#!/usr/bin/env python3
"""Gate B exit grid on REAL traded premiums, with placebo, multiplicity, power and costs.

Covers parts D, E, F and G of the Gate-B real-premium validation brief.

Every return in this file is computed on the traded one-minute bar close of the ACTUAL
entry strike, tracked through the session.  Stops and targets are evaluated on the same
traded series they are valued on, so each rule is executable within that series (subject to
the bar-close-not-a-fill caveat, which part G prices).  The Black-Scholes proxy is run
through the identical grid purely for comparison.

The benchmark for every variant is the plain hold-to-close trade on real premiums -- the
incumbent Gate-B exit.  A variant that beats zero but not that baseline has earned nothing;
that lesson is already twice-learned in this project (WALKFORWARD_GATE_A_VALIDATION.md and
GATE_A_HORIZON_CENSORING.md) and it is the binding test here too.

Offline analysis only.  No broker, credential, exchange network, or order path.  No live
order exists or is authorised.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from gate_b_common import (
    CACHE,
    cached_path,
    clock_exit_index,
    gate_b_subset,
    load_paths,
    manifest_rows,
    reproduction_guard,
    rule_return,
    rule_returns,
)

CLOCKS = ("10:00", "10:30", "11:00", "12:00", "13:00", "14:00", "15:00", None)
STOPS = (0.20, 0.30, 0.40, 0.50)
TARGETS = (0.30, 0.50, 0.75, 1.00)
# Elapsed-time horizons measured from the fill, NOT from the open.  Not in the brief's
# grid, added so Gate B is not judged only on absolute-clock exits: because the fill time
# varies from 09:18 to 14:04, an absolute clock is a different holding period on every
# trade, and a short post-fill horizon is the natural way to ask whether the reversal pays
# quickly.  Declared here and carried in the multiplicity count and the placebo.
HORIZONS = (10, 20, 30, 45, 60, 90, 120)
N_PLACEBO = 5000
SEED_GRID = 20260822
SEED_COST = 20260824

# ---------------------------------------------------------------------------- cost model
# NIFTY weekly ATM options, 1 lot = 75.  Statutory rates as of the 2024-10-01 STT revision.
LOT_SIZE = 75
BROKERAGE_PER_ORDER = 20.0        # flat, discount broker, two orders per round trip
STT_SELL_RATE = 0.001             # 0.10% of premium value on the sell leg
EXCHANGE_TXN_RATE = 0.0003503     # NSE F&O options, % of premium value, each leg
SEBI_RATE = 0.000001              # Rs 10 per crore of premium value, each leg
STAMP_BUY_RATE = 0.00003          # 0.003% of premium value, buy leg only
GST_RATE = 0.18                   # on brokerage + exchange transaction charges


def variant_grid() -> list[dict]:
    """Every exit rule tested.  ``kind`` is only used for reporting."""
    out: list[dict] = []
    for c in CLOCKS:
        out.append(
            {
                "name": "hold to close" if c is None else f"clock exit {c}",
                "kind": "baseline" if c is None else "clock",
                "stop": None,
                "target": None,
                "clock": c,
                "offset": None,
            }
        )
    for h in HORIZONS:
        out.append(
            {"name": f"hold {h}m after fill", "kind": "horizon", "stop": None,
             "target": None, "clock": None, "offset": h}
        )
    for s in STOPS:
        out.append(
            {"name": f"stop -{s:.0%}", "kind": "stop", "stop": s, "target": None,
             "clock": None, "offset": None}
        )
    for t in TARGETS:
        out.append(
            {"name": f"target +{t:.0%}", "kind": "target", "stop": None, "target": t,
             "clock": None, "offset": None}
        )
    for s in STOPS:
        for t in TARGETS:
            out.append(
                {
                    "name": f"stop -{s:.0%} / target +{t:.0%}",
                    "kind": "cross",
                    "stop": s,
                    "target": t,
                    "clock": None,
                    "offset": None,
                }
            )
    return out


def matrix(paths: list[dict], series: str, variants: list[dict]) -> np.ndarray:
    """``[variant, path]`` return matrix."""
    return np.vstack(
        [
            rule_returns(paths, series, v["stop"], v["target"], v["clock"], v.get("offset"))
            for v in variants
        ]
    )


# ---------------------------------------------------------------- vectorised inference
def t_p_vs_zero(rows: np.ndarray) -> np.ndarray:
    """Two-sided one-sample t-test p-value for each row of a ``[k, n]`` matrix."""
    n = rows.shape[1]
    if n < 2:
        return np.full(rows.shape[0], np.nan)
    m = rows.mean(axis=1)
    sd = rows.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = m / (sd / np.sqrt(n))
    p = 2.0 * stats.t.sf(np.abs(t), df=n - 1)
    p[~np.isfinite(t)] = 1.0
    return p


def bh_reject(p: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p)
    thresh = alpha * (np.arange(1, m + 1) / m)
    passed = p[order] <= thresh
    out = np.zeros(m, dtype=bool)
    if passed.any():
        k = np.max(np.flatnonzero(passed))
        out[order[: k + 1]] = True
    return out


def summarise(x: np.ndarray) -> dict:
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"N": len(x)}
    t = stats.ttest_1samp(x, 0.0)
    return {
        "N": int(len(x)),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "win": float((x > 0).mean() * 100.0),
        "sd": float(x.std(ddof=1)),
        "p0": float(t.pvalue),
    }


# --------------------------------------------------------------------------- G. costs
def measure_spread_proxies(gate: list[dict]) -> dict:
    """Two data-driven bounds on the round-trip bid-ask cost, plus the assumption used.

    There is no order book in this dataset -- only one-minute OHLC bars -- so the true
    quoted spread is UNIDENTIFIED here.  Two bounds are measured instead:

    * upper bound: the traded contract's own one-minute high-low range at the entry minute
      and at a mid-session minute, as a share of the bar close.  A one-minute range on a
      liquid contract contains the spread plus genuine price movement, so it overstates.
    * lower bound: Roll's (1984) effective-spread estimator on the same contract's
      one-minute closes, ``2*sqrt(-cov(dP_t, dP_{t-1}))``.  One-minute aggregation averages
      away most of the bid-ask bounce, so it understates.

    The cost applied in the headline is stated explicitly and sits between the two.
    """
    wanted = {(p["date"], p["K"]) for p in gate}
    dates = {d for d, _ in wanted}
    frames = []
    for row in manifest_rows():
        if row.get("drv_option_type") != "CALL":
            continue
        path = cached_path(row)
        if not path.exists():
            continue
        fr = pd.read_csv(path, usecols=["high", "low", "close", "strike", "datetime"])
        fr["datetime"] = pd.to_datetime(fr["datetime"], errors="coerce")
        fr["date"] = fr["datetime"].dt.strftime("%Y-%m-%d")
        fr = fr[fr["date"].isin(dates)]
        if not fr.empty:
            frames.append(fr)
    bars = pd.concat(frames, ignore_index=True)
    bars["clock"] = bars["datetime"].dt.strftime("%H:%M")
    bars = bars[bars["close"] > 0]
    bars = bars.drop_duplicates(subset=["date", "clock", "strike"], keep="first")

    entry_rng, mid_rng, roll = [], [], []
    for p in gate:
        sub = bars[(bars["date"] == p["date"]) & (bars["strike"] == p["K"])].sort_values("clock")
        if sub.empty:
            continue
        e = sub[sub["clock"] == p["entry_clock"]]
        if not e.empty:
            r = float(e["high"].iloc[0] - e["low"].iloc[0]) / float(e["close"].iloc[0])
            entry_rng.append(r * 100.0)
        m = sub[sub["clock"] == "12:00"]
        if not m.empty and float(m["close"].iloc[0]) > 0:
            mid_rng.append(float(m["high"].iloc[0] - m["low"].iloc[0])
                           / float(m["close"].iloc[0]) * 100.0)
        px = sub["close"].to_numpy(dtype=float)
        if len(px) > 30:
            d = np.diff(px)
            cov = np.cov(d[:-1], d[1:])[0, 1]
            if cov < 0:
                roll.append(2.0 * np.sqrt(-cov) / float(px[0]) * 100.0)
    return {
        "entry_minute_range_pct_median": float(np.median(entry_rng)) if entry_rng else np.nan,
        "entry_minute_range_pct_mean": float(np.mean(entry_rng)) if entry_rng else np.nan,
        "midday_range_pct_median": float(np.median(mid_rng)) if mid_rng else np.nan,
        "roll_effective_spread_pct_median": float(np.median(roll)) if roll else np.nan,
        "n_entry": len(entry_rng),
        "n_roll": len(roll),
    }


def cost_pct_of_premium(entry_premium: float, exit_premium: float,
                        half_spread_pct: float) -> float:
    """Round-trip cost as a percentage of the ENTRY premium, for one lot of 75."""
    entry_value = entry_premium * LOT_SIZE
    exit_value = max(exit_premium, 0.0) * LOT_SIZE
    spread = (half_spread_pct / 100.0) * (entry_value + exit_value)
    brokerage = 2 * BROKERAGE_PER_ORDER
    txn = EXCHANGE_TXN_RATE * (entry_value + exit_value)
    stt = STT_SELL_RATE * exit_value
    sebi = SEBI_RATE * (entry_value + exit_value)
    stamp = STAMP_BUY_RATE * entry_value
    gst = GST_RATE * (brokerage + txn)
    total = spread + brokerage + txn + stt + sebi + stamp + gst
    return total / entry_value * 100.0


def net_of_costs(paths: list[dict], series: str, variant: dict,
                 half_spread_pct: float) -> np.ndarray:
    out = []
    for p in paths:
        gross = rule_return(p, series, variant["stop"], variant["target"],
                            variant["clock"], variant.get("offset"))
        if not np.isfinite(gross):
            out.append(np.nan)
            continue
        C0 = float(p[series][0])
        exit_px = C0 * (1.0 + gross / 100.0)
        out.append(gross - cost_pct_of_premium(C0, exit_px, half_spread_pct))
    return np.asarray(out, dtype=float)


# ------------------------------------------------------------------------------- main
def main() -> None:
    paths = load_paths()
    gate = gate_b_subset(paths)
    reproduction_guard(gate)
    variants = variant_grid()
    base_i = next(i for i, v in enumerate(variants) if v["kind"] == "baseline")

    print("=" * 108)
    print("GATE B EXIT GRID ON REAL TRADED PREMIUMS")
    print("=" * 108)
    print(f"Gate-B fires: {len(gate)}   variants tested in this script: {len(variants)}")
    print("Convention for a clock exit that has already passed at entry (4 of the 33 fires")
    print("enter at 12:50 or later): the position runs to the close, so N stays at 33 for")
    print("every clock variant.  The traded-only convention is reported as a sensitivity.\n")

    R = matrix(gate, "real_prices", variants)
    B = matrix(gate, "bs_prices", variants)
    base_real = R[base_i]
    base_bs = B[base_i]

    # ------------------------------------------------------------------- D. the grid
    print("=" * 108)
    print("D.  THE GRID -- REAL PREMIUMS (primary) with the Black-Scholes proxy alongside")
    print("=" * 108)
    print(f"{'variant':>28} {'N':>3} {'mean':>9} {'med':>9} {'win%':>6} {'p vs 0':>8} "
          f"{'d vs base':>10} {'p vs base':>10} | {'BS mean':>8} {'BS p':>7}")
    print("-" * 108)

    rows = []
    for i, v in enumerate(variants):
        r = R[i]
        ok = np.isfinite(r) & np.isfinite(base_real)
        s = summarise(r)
        if s.get("N", 0) < 2:
            continue
        d = (r - base_real)[ok]
        if i == base_i or np.allclose(d, 0.0):
            pb, dm = np.nan, 0.0
        else:
            pb = float(stats.ttest_1samp(d, 0.0).pvalue)
            dm = float(d.mean())
        sb = summarise(B[i])
        rows.append(
            {
                "name": v["name"], "kind": v["kind"], "idx": i,
                **s, "d_vs_base": dm, "p_vs_base": pb,
                "bs_mean": sb.get("mean", np.nan), "bs_p0": sb.get("p0", np.nan),
            }
        )
        tag = "  <- baseline" if i == base_i else ""
        print(
            f"{v['name']:>28} {s['N']:>3} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% "
            f"{s['win']:>5.1f}% {s['p0']:>8.4f} {dm:>+9.2f}pp "
            f"{('n/a' if not np.isfinite(pb) else f'{pb:.4f}'):>10} | "
            f"{sb.get('mean', np.nan):>+7.2f}% {sb.get('p0', np.nan):>7.4f}{tag}"
        )

    grid = pd.DataFrame(rows)
    grid.to_csv("gate_b_exit_grid_real.csv", index=False)

    non_base = grid[grid["kind"] != "baseline"]
    print(f"\n  Baseline (hold to close, real premiums): mean {base_real.mean():+.2f}%, "
          f"median {np.median(base_real):+.2f}%, win {np.mean(base_real>0)*100:.1f}%, "
          f"p={summarise(base_real)['p0']:.4f}")
    print(f"  Non-baseline variants: {len(non_base)}")
    print(f"  Mean improvement over the baseline across all of them: "
          f"{non_base['d_vs_base'].mean():+.2f}pp")
    print(f"  Share that improve on the baseline at all: "
          f"{(non_base['d_vs_base'] > 0).mean()*100:.1f}%")
    print(f"  Best improvement {non_base['d_vs_base'].max():+.2f}pp, "
          f"worst {non_base['d_vs_base'].min():+.2f}pp")
    print(f"  Variants with a POSITIVE mean return at all: "
          f"{(grid['mean'] > 0).sum()} of {len(grid)}")

    # traded-only convention: the one the module spec's published numbers use
    print("\n  Clock exits under the TRADED-ONLY convention -- a day whose gap fills after")
    print("  the exit clock is simply not traded, so N falls.  This is the convention that")
    print("  reproduces GAP_FILL_SIGNAL_MODULE_SPEC.md's published Black-Scholes figures to")
    print("  the decimal, so it is the like-for-like comparison against what the project has")
    print("  been relying on:")
    print(f"    {'variant':>16} {'N':>3} {'REAL mean':>10} {'median':>9} {'win%':>6} "
          f"{'p vs 0':>8} | {'BS mean':>8} {'BS p':>7} {'published':>10}")
    print("    " + "-" * 84)
    published = {"10:00": "-11.9 / .013", "10:30": "-13.2 / .006", "11:00": "-10.9 / .018",
                 "12:00": "-13.1 / .045", "13:00": "-13.2 / .044", "14:00": " -7.7 / .282",
                 "15:00": "not quoted"}
    for v in variants:
        if v["kind"] != "clock":
            continue
        keep = [p for p in gate
                if p["entry_minute"] < 60 * int(v["clock"][:2]) + int(v["clock"][3:])]
        if len(keep) < 3:
            continue
        s = summarise(rule_returns(keep, "real_prices", None, None, v["clock"]))
        sb = summarise(rule_returns(keep, "bs_prices", None, None, v["clock"]))
        print(f"    {v['name']:>16} {s['N']:>3} {s['mean']:>+9.2f}% {s['median']:>+8.2f}% "
              f"{s['win']:>5.1f}% {s['p0']:>8.4f} | {sb['mean']:>+7.2f}% {sb['p0']:>7.4f} "
              f"{published.get(v['clock'], ''):>10}")
    sc = summarise(rule_returns(gate, "real_prices"))
    sbc = summarise(rule_returns(gate, "bs_prices"))
    print(f"    {'hold to close':>16} {sc['N']:>3} {sc['mean']:>+9.2f}% {sc['median']:>+8.2f}% "
          f"{sc['win']:>5.1f}% {sc['p0']:>8.4f} | {sbc['mean']:>+7.2f}% {sbc['p0']:>7.4f} "
          f"{'+1.8 / .82':>10}")

    # --------------------------------------------- E. multiplicity and placebo
    print("\n" + "=" * 108)
    print("E.  MULTIPLE COMPARISONS AND SHUFFLED-LABEL PLACEBO")
    print("=" * 108)
    p0 = grid["p0"].to_numpy()
    pb = grid["p_vs_base"].to_numpy()
    pb_valid = pb[np.isfinite(pb)]
    k = len(grid)
    print(f"  Total exit rules examined in this script                 : {k}")
    print(f"  Variants with raw p vs zero < 0.05                       : {(p0 < 0.05).sum()} of {k}")
    print(f"  Surviving Bonferroni vs zero (alpha/{k} = {0.05/k:.2e})     : "
          f"{(p0 < 0.05/k).sum()}")
    print(f"  Surviving Benjamini-Hochberg vs zero                     : {bh_reject(p0).sum()}")
    print(f"  Variants with raw p vs the baseline < 0.05               : "
          f"{(pb_valid < 0.05).sum()} of {len(pb_valid)}")
    print(f"  Surviving Bonferroni vs baseline                         : "
          f"{(pb_valid < 0.05/len(pb_valid)).sum()}")
    print(f"  Surviving Benjamini-Hochberg vs baseline                 : "
          f"{bh_reject(pb_valid).sum()}")

    best0_i = int(np.nanargmin(p0))
    best0 = grid.iloc[best0_i]
    if len(pb_valid):
        bidx = grid.index[np.isfinite(pb)][int(np.nanargmin(pb_valid))]
        bestb = grid.loc[bidx]
    else:
        bestb = None
    bestm_i = int(grid["mean"].idxmax())
    bestm = grid.loc[bestm_i]
    print(f"\n  Smallest p vs zero    : {best0['name']}  (mean {best0['mean']:+.2f}%, "
          f"p={best0['p0']:.4f})")
    if best0["mean"] < 0:
        print("    NOTE: that p-value is two-sided and this variant's mean is NEGATIVE, so")
        print("    the smallest p in the grid marks the most reliably LOSING rule, not a")
        print("    winner.  Selecting on |t| would pick a loss-maker here.")
    print(f"  Highest mean return   : {bestm['name']}  (mean {bestm['mean']:+.2f}%, "
          f"p={bestm['p0']:.4f}, {bestm['d_vs_base']:+.2f}pp vs baseline)")
    if bestb is not None:
        print(f"  Smallest p vs baseline: {bestb['name']}  "
              f"(diff {bestb['d_vs_base']:+.2f}pp, p={bestb['p_vs_base']:.4f})")

    # placebo universe: all non-expiry gap-down fill days priceable on real premiums
    pool = [p for p in paths if np.isfinite(rule_return(p, "real_prices"))]
    print(f"\n  Placebo pool (non-expiry gap-down days whose gap fills after 09:17 and")
    print(f"  which are priceable on real traded premiums)             : {len(pool)}")
    print(f"  Gate-B fires inside that pool                            : "
          f"{sum(p['is_gate_b'] for p in pool)}")
    P = matrix(pool, "real_prices", variants)
    finite_all = np.isfinite(P).all(axis=0)
    P = P[:, finite_all]
    print(f"  Pool paths priceable under EVERY variant                 : {P.shape[1]}")

    rng = np.random.default_rng(SEED_GRID)
    n_draw = len(gate)
    best_p0_null = np.empty(N_PLACEBO)
    best_pb_null = np.empty(N_PLACEBO)
    any_sig_0 = 0
    any_sig_b = 0
    for d in range(N_PLACEBO):
        idx = rng.choice(P.shape[1], size=n_draw, replace=False)
        sub = P[:, idx]
        pz = t_p_vs_zero(sub)
        diffs = sub - sub[base_i]
        mask = np.ones(len(variants), dtype=bool)
        mask[base_i] = False
        dd = diffs[mask]
        keep = ~np.all(np.isclose(dd, 0.0), axis=1)
        pbn = np.full(dd.shape[0], 1.0)
        if keep.any():
            pbn[keep] = t_p_vs_zero(dd[keep])
        best_p0_null[d] = np.nanmin(pz)
        best_pb_null[d] = np.nanmin(pbn)
        any_sig_0 += int(np.nanmin(pz) < 0.05)
        any_sig_b += int(np.nanmin(pbn) < 0.05)

    obs_best_p0 = float(np.nanmin(p0))
    obs_best_pb = float(np.nanmin(pb_valid)) if len(pb_valid) else np.nan
    emp_p0 = float(np.mean(best_p0_null <= obs_best_p0))
    emp_pb = float(np.mean(best_pb_null <= obs_best_pb)) if np.isfinite(obs_best_pb) else np.nan

    print(f"\n  {N_PLACEBO:,} draws, each reassigning Gate-B membership at random within the")
    print("  pool and re-running the whole grid.  This preserves N, the CALL direction, the")
    print("  gap-fill entry mechanism and the entire exit machinery, and destroys only the")
    print("  association with an overnight VIX rise and the mid opening-IV bucket.")
    print(f"\n    {'test':>22} {'observed best p':>16} {'placebo median':>16} "
          f"{'placebo 5th pct':>17} {'empirical p':>13}")
    print("    " + "-" * 88)
    print(f"    {'vs zero':>22} {obs_best_p0:>16.6f} {np.median(best_p0_null):>16.6f} "
          f"{np.percentile(best_p0_null,5):>17.6f} {emp_p0:>13.4f}")
    print(f"    {'vs the baseline':>22} {obs_best_pb:>16.6f} {np.median(best_pb_null):>16.6f} "
          f"{np.percentile(best_pb_null,5):>17.6f} {emp_pb:>13.4f}")
    print(f"\n  At least one variant reaches nominal p<0.05 vs zero in "
          f"{any_sig_0/N_PLACEBO*100:.1f}% of placebo draws.")
    print(f"  At least one beats its own baseline at p<0.05 in "
          f"{any_sig_b/N_PLACEBO*100:.1f}% of placebo draws.")
    print("  Those two shares are the scale of the search being corrected for.")

    # Where does the real Gate-B baseline itself sit against the placebo?
    base_null = np.empty(N_PLACEBO)
    rng2 = np.random.default_rng(SEED_GRID + 1)
    for d in range(N_PLACEBO):
        idx = rng2.choice(P.shape[1], size=n_draw, replace=False)
        base_null[d] = P[base_i, idx].mean()
    obs_base = float(base_real.mean())
    print(f"\n  The Gate-B population itself, before any exit search:")
    print(f"    observed hold-to-close mean on real premiums : {obs_base:+.2f}%")
    print(f"    placebo mean of that same statistic          : {base_null.mean():+.2f}%")
    print(f"    placebo 5th / 95th percentile                : "
          f"{np.percentile(base_null,5):+.2f}% / {np.percentile(base_null,95):+.2f}%")
    print(f"    share of placebo draws at or above observed   : "
          f"{np.mean(base_null >= obs_base)*100:.1f}%")

    # --------------------------------------------------------------------- F. power
    print("\n" + "=" * 108)
    print("F.  POWER")
    print("=" * 108)
    from scipy.optimize import brentq

    def required_d(n: int, alpha: float = 0.05, power: float = 0.80) -> float:
        crit = stats.t.ppf(1 - alpha / 2, df=n - 1)

        def f(d):
            nc = d * np.sqrt(n)
            return stats.nct.sf(crit, df=n - 1, nc=nc) + stats.nct.cdf(-crit, df=n - 1, nc=nc) - power

        return brentq(f, 1e-4, 3.0)

    for n in (33, 28, 5):
        d = required_d(n)
        print(f"  N={n:>3}: two-sided t-test at 5% with 80% power needs {d:.3f} sd")
    sd_base = base_real.std(ddof=1)
    d33 = required_d(33)
    print(f"\n  Baseline sd on real premiums: {sd_base:.1f}pp")
    print(f"  => at N=33 this design can detect a mean of "
          f"{d33*sd_base:.1f} percentage points or larger, and nothing smaller.")
    paired_sds = []
    for i, v in enumerate(variants):
        if i == base_i:
            continue
        d_ = (R[i] - base_real)
        d_ = d_[np.isfinite(d_)]
        if len(d_) > 2 and d_.std(ddof=1) > 0:
            paired_sds.append(d_.std(ddof=1))
    if paired_sds:
        msd = float(np.median(paired_sds))
        print(f"  Median paired sd of an overlay against the baseline: {msd:.1f}pp")
        print(f"  => an overlay would have to add {d33*msd:.1f}pp or more to be visible here.")
    print(f"\n  Observed baseline mean is {base_real.mean():+.2f}% with a 95% CI of "
          f"[{base_real.mean() - stats.t.ppf(0.975, 32)*sd_base/np.sqrt(33):+.2f}%, "
          f"{base_real.mean() + stats.t.ppf(0.975, 32)*sd_base/np.sqrt(33):+.2f}%].")

    # --------------------------------------------------------------------- G. costs
    print("\n" + "=" * 108)
    print("G.  COSTS")
    print("=" * 108)
    sp = measure_spread_proxies(gate)
    print("  There is no order book in this dataset -- only one-minute OHLC bars -- so the")
    print("  true quoted spread is UNIDENTIFIED here.  Two bounds, measured on the traded")
    print("  contract itself:")
    print(f"    upper bound, one-minute high-low range at the ENTRY minute, median "
          f"{sp['entry_minute_range_pct_median']:.2f}% of premium (N={sp['n_entry']})")
    print(f"    upper bound, same at 12:00, median "
          f"{sp['midday_range_pct_median']:.2f}% of premium")
    print(f"    lower bound, Roll (1984) effective spread on one-minute closes, median "
          f"{sp['roll_effective_spread_pct_median']:.2f}% of premium (N={sp['n_roll']})")
    print("\n  ASSUMPTION USED (stated, not derived): a half-spread of 0.35% of premium paid")
    print("  on entry and again on exit -- 0.70% round trip -- for a NIFTY weekly ATM option.")
    print("  On the median traded entry premium of ~101 points that is about 0.35 points a")
    print("  side, or roughly 7 ticks of the 0.05 tick.  A pessimistic case at 1.00% a side")
    print("  is carried alongside because 30% of Gate-B fires enter before 09:20, when the")
    print("  book is at its widest.")
    print("\n  Statutory and brokerage, per lot of 75, both legs:")
    print(f"    brokerage Rs {BROKERAGE_PER_ORDER:.0f} per order x 2, "
          f"STT {STT_SELL_RATE:.3%} of premium on the sell leg,")
    print(f"    NSE transaction {EXCHANGE_TXN_RATE:.5%} each leg, SEBI Rs 10/crore, "
          f"stamp {STAMP_BUY_RATE:.4%} buy leg, GST {GST_RATE:.0%}.")
    med_c0 = float(np.median([p["real_prices"][0] for p in gate]))
    for hs in (0.0, 0.35, 1.00):
        c = cost_pct_of_premium(med_c0, med_c0, hs)
        print(f"    round-trip cost at a {hs:.2f}% half-spread, median trade: "
              f"{c:.2f}% of entry premium (Rs {c/100*med_c0*LOT_SIZE:.0f} on one lot)")

    print("\n  Net-of-cost results:")
    print(f"    {'variant':>28} {'spread':>7} {'N':>3} {'mean':>9} {'median':>9} "
          f"{'win%':>6} {'p vs 0':>8}")
    print("    " + "-" * 76)
    winners = [variants[base_i], variants[bestm_i], variants[best0_i]]
    if bestb is not None:
        winners.append(variants[int(bestb["idx"])])
    seen = set()
    net_summary = {}
    for v in winners:
        if v["name"] in seen:
            continue
        seen.add(v["name"])
        for hs in (0.35, 1.00):
            net = net_of_costs(gate, "real_prices", v, hs)
            s = summarise(net)
            net_summary[(v["name"], hs)] = s
            print(f"    {v['name']:>28} {hs:>6.2f}% {s['N']:>3} {s['mean']:>+8.2f}% "
                  f"{s['median']:>+8.2f}% {s['win']:>5.1f}% {s['p0']:>8.4f}")

    print("\n  Aryan trades at most 1-2 lots of 75.  Cost is close to proportional in premium,")
    print("  so lot count barely changes the percentage figures above; the flat Rs 40")
    print("  brokerage is the only fixed component and it is under 0.6% of a one-lot")
    print(f"  premium of Rs {med_c0*LOT_SIZE:,.0f}.")

    results = {
        "n_fires": len(gate),
        "n_variants": len(variants),
        "baseline_real": summarise(base_real),
        "baseline_bs": summarise(base_bs),
        "best_vs_zero": {"name": best0["name"], "mean": float(best0["mean"]),
                         "p0": float(best0["p0"]),
                         "d_vs_base": float(best0["d_vs_base"]),
                         "p_vs_base": (None if not np.isfinite(best0["p_vs_base"])
                                       else float(best0["p_vs_base"]))},
        "best_vs_baseline": (None if bestb is None else
                             {"name": bestb["name"], "mean": float(bestb["mean"]),
                              "d_vs_base": float(bestb["d_vs_base"]),
                              "p_vs_base": float(bestb["p_vs_base"])}),
        "bonferroni_vs_zero": int((p0 < 0.05 / k).sum()),
        "bh_vs_zero": int(bh_reject(p0).sum()),
        "bonferroni_vs_baseline": int((pb_valid < 0.05 / len(pb_valid)).sum()),
        "bh_vs_baseline": int(bh_reject(pb_valid).sum()),
        "placebo": {
            "draws": N_PLACEBO,
            "pool": int(P.shape[1]),
            "empirical_p_vs_zero": emp_p0,
            "empirical_p_vs_baseline": emp_pb,
            "share_any_sig_vs_zero": any_sig_0 / N_PLACEBO,
            "share_any_sig_vs_baseline": any_sig_b / N_PLACEBO,
            "baseline_placebo_mean": float(base_null.mean()),
            "baseline_share_ge_observed": float(np.mean(base_null >= obs_base)),
        },
        "spread_proxies": sp,
        "net_of_costs": {f"{k2[0]} @ {k2[1]:.2f}%": v2 for k2, v2 in net_summary.items()},
    }
    Path("gate_b_exit_grid_real_results.json").write_text(json.dumps(results, indent=2))
    print("\nWrote gate_b_exit_grid_real.csv, gate_b_exit_grid_real_results.json")


if __name__ == "__main__":
    main()
