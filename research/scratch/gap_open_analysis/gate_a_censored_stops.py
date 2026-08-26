#!/usr/bin/env python3
"""(C)(D)(E) Stops and targets INSIDE the censored Gate-A PUT design.

Design decisions, stated before the numbers:

* The trade is censored at a hard holding horizon H measured from the 09:17 entry.  Three
  horizons are carried: H=15 (the best t-statistic against zero in the horizon scan),
  H=20 (the best median and win rate in the horizon scan), and H=30 (the horizon Aryan
  specified), so the mandated horizon is always reported even if another scores better.
* Within a horizon the benchmark is the PURE CENSORED BASELINE at that horizon: no stop,
  no target, no gap-fill exit.  Every variant is tested both against zero and, paired
  trade-by-trade, against that benchmark.  A variant that beats zero but not the benchmark
  has not earned its place -- the exact failure mode found in
  ``WALKFORWARD_GATE_A_VALIDATION.md``.
* Exit priority within a minute is unchanged from ``bs_gate_a_put_stop_take.py``:
  stop-loss, then take-profit, then gap-fill (when that family is active), else carry on
  to the horizon.

Multiple comparisons: the full variant count is reported, Bonferroni and Benjamini-Hochberg
adjustments are applied, and -- the binding test -- a shuffled-label placebo estimates the
distribution of the BEST-OF-GRID p-value under the null, so the winner is judged against
best-of-grid chance rather than a single-test null (a Westfall-Young style max-statistic
correction).

Walk-forward uses the identical protocol as ``walkforward_gate_a_put_stop_take.py``:
most-recent 15% held out untouched, oldest 40% of the remainder seeds an expanding window,
seven consecutive out-of-fold validation folds.

Offline analysis only.  No broker, credential, network, or order path.
"""
from __future__ import annotations

import json
from collections import Counter

import numpy as np
from scipy import stats

from gate_a_censoring_common import (
    gate_a_subset,
    horizon_exit_index,
    load_paths,
    reproduction_guard,
)

CENSOR_HORIZONS = (15, 20, 30)
STOPS = (0.15, 0.20, 0.25, 0.30, 0.40, 0.50)
TARGETS = (0.20, 0.30, 0.50, 0.75, 1.00)
GAP_FILL_MODES = (False, True)

HELD_OUT_FRACTION = 0.15
N_WALKFORWARD_FOLDS = 7
INITIAL_TRAIN_FRACTION = 0.40

PLACEBO_SEED = 20260822
N_PLACEBO = 5000
N_PLACEBO_WF = 5000


def build_variants() -> list[dict]:
    """Enumerate every tested exit rule.  Order is the disclosed deterministic tie-break."""
    variants: list[dict] = []
    for horizon in CENSOR_HORIZONS:
        for gap_fill in GAP_FILL_MODES:
            combos: list[tuple[float | None, float | None]] = [(None, None)]
            combos += [(s, None) for s in STOPS]
            combos += [(None, t) for t in TARGETS]
            combos += [(s, t) for s in STOPS for t in TARGETS]
            for stop, target in combos:
                variants.append(
                    {
                        "horizon": horizon,
                        "gap_fill": gap_fill,
                        "stop": stop,
                        "target": target,
                        "is_baseline": stop is None and target is None and not gap_fill,
                    }
                )
    return variants


def variant_label(v: dict) -> str:
    stop = "none" if v["stop"] is None else f"-{v['stop']*100:.0f}%"
    target = "none" if v["target"] is None else f"+{v['target']*100:.0f}%"
    return f"H={v['horizon']:>2}m stop={stop:>5} target={target:>5} gapfill={'on' if v['gap_fill'] else 'off'}"


def variant_returns(paths: list[dict], v: dict) -> np.ndarray:
    stop, target, gap_fill, horizon = v["stop"], v["target"], v["gap_fill"], v["horizon"]
    out = []
    for p in paths:
        C0 = p["C0"]
        prices = p["prices"]
        last = horizon_exit_index(p, horizon)
        exit_i = last
        gf = p["gap_fill_idx"]
        for i in range(last + 1):
            ret = (prices[i] - C0) / C0
            if stop is not None and ret <= -stop:
                exit_i = i
                break
            if target is not None and ret >= target:
                exit_i = i
                break
            if gap_fill and gf is not None and i == gf:
                exit_i = i
                break
        out.append((prices[exit_i] - C0) / C0 * 100.0)
    return np.asarray(out)


def build_matrix(paths: list[dict], variants: list[dict]) -> np.ndarray:
    return np.column_stack([variant_returns(paths, v) for v in variants])


def baseline_column(variants: list[dict], horizon: int) -> int:
    for j, v in enumerate(variants):
        if v["horizon"] == horizon and v["is_baseline"]:
            return j
    raise KeyError(horizon)


def vectorized_p(values: np.ndarray) -> np.ndarray:
    """Two-sided one-sample t-test p-values, column-wise; degenerate columns give p=1."""
    n = values.shape[0]
    mean = values.mean(axis=0)
    sd = values.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = mean / (sd / np.sqrt(n))
    p = 2.0 * stats.t.sf(np.abs(t), n - 1)
    p = np.where(np.isfinite(p), p, 1.0)
    return p


def paired_p(values: np.ndarray, baselines: np.ndarray) -> np.ndarray:
    return vectorized_p(values - baselines)


def benjamini_hochberg(p: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    m = len(p)
    order = np.argsort(p)
    thresholds = alpha * (np.arange(1, m + 1) / m)
    passed = p[order] <= thresholds
    reject = np.zeros(m, dtype=bool)
    if passed.any():
        k = int(np.flatnonzero(passed)[-1])
        reject[order[: k + 1]] = True
    return reject


def wilcoxon_p(values: np.ndarray) -> float:
    if len(values) == 0 or np.allclose(values, 0.0):
        return float("nan")
    try:
        return float(stats.wilcoxon(values, alternative="two-sided").pvalue)
    except ValueError:
        return float("nan")


def summarize(values: np.ndarray) -> dict:
    t, p = stats.ttest_1samp(values, 0.0)
    return {
        "n": int(len(values)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values, ddof=1)),
        "win": float(np.mean(values > 0) * 100.0),
        "t": float(t),
        "p": float(p),
        "wilcoxon": wilcoxon_p(values),
    }


def split_protocol(n: int) -> dict:
    n_held_out = int(round(n * HELD_OUT_FRACTION))
    n_pool = n - n_held_out
    initial_train_n = int(round(n_pool * INITIAL_TRAIN_FRACTION))
    fold_size = (n_pool - initial_train_n) // N_WALKFORWARD_FOLDS
    folds: list[tuple[int, int]] = []
    cursor = initial_train_n
    for fold_i in range(N_WALKFORWARD_FOLDS):
        fold_end = cursor + fold_size if fold_i < N_WALKFORWARD_FOLDS - 1 else n_pool
        if fold_end > cursor:
            folds.append((cursor, fold_end))
        cursor = fold_end
    return {
        "n": n, "n_held_out": n_held_out, "n_pool": n_pool,
        "initial_train_n": initial_train_n, "folds": folds,
    }


def score_columns(train: np.ndarray, criterion: str) -> np.ndarray:
    if criterion == "mean":
        return train.mean(axis=0)
    if criterion == "median":
        return np.median(train, axis=0)
    means = train.mean(axis=0)
    stds = train.std(axis=0, ddof=1)
    return np.divide(means, stds, out=np.full_like(means, -np.inf), where=stds > 0)


def select_cell(train: np.ndarray, criterion: str) -> int:
    scores = score_columns(train, criterion)
    best = np.nanmax(scores)
    return int(np.flatnonzero(np.isclose(scores, best, rtol=1e-12, atol=1e-12))[0])


def walk_forward(grid: np.ndarray, baseline: np.ndarray, criterion: str) -> dict:
    protocol = split_protocol(grid.shape[0])
    chosen_returns, chosen_baseline, chosen_idx = [], [], []
    for start, end in protocol["folds"]:
        cell = select_cell(grid[:start, :], criterion)
        chosen_idx.append(cell)
        chosen_returns.extend(grid[start:end, cell].tolist())
        chosen_baseline.extend(baseline[start:end].tolist())
    return {
        "returns": np.asarray(chosen_returns),
        "baseline": np.asarray(chosen_baseline),
        "cells": chosen_idx,
        "protocol": protocol,
    }


def main() -> None:
    paths = load_paths()
    gate = gate_a_subset(paths)
    reproduction_guard(gate)
    gate_dates = [p["date"] for p in gate]

    variants = build_variants()
    n_variants = len(variants)
    print("Gate-A PUT: stop-loss / take-profit grid INSIDE the censored holding horizon")
    print(f"Gate-A trades N={len(gate)} ({gate_dates[0]} .. {gate_dates[-1]})")
    print(f"Candidate expiry-day gap-down universe for the placebo: {len(paths)} paths")
    print(f"Horizons carried: {CENSOR_HORIZONS}  stops: {STOPS}  targets: {TARGETS}")
    print(f"TOTAL EXIT-RULE VARIANTS TESTED IN THIS SCRIPT: {n_variants}")
    print("(plus the 10 pure holding horizons already reported by gate_a_horizon_scan.py,")
    print(f" giving {n_variants + 10} exit rules examined on these same 55 trades in this study.)\n")

    all_matrix = build_matrix(paths, variants)
    gate_rows = np.asarray([i for i, p in enumerate(paths) if p["vix_rose"] == 1])
    gate_matrix = all_matrix[gate_rows, :]

    base_cols = {h: baseline_column(variants, h) for h in CENSOR_HORIZONS}
    base_for_variant = np.asarray([base_cols[v["horizon"]] for v in variants])

    obs_p0 = vectorized_p(gate_matrix)
    obs_pb = paired_p(gate_matrix, gate_matrix[:, base_for_variant])
    # A baseline compared with itself is not a test; exclude those columns from selection.
    self_compare = np.asarray([v["is_baseline"] for v in variants])
    obs_pb = np.where(self_compare, 1.0, obs_pb)

    means = gate_matrix.mean(axis=0)
    medians = np.median(gate_matrix, axis=0)
    wins = (gate_matrix > 0).mean(axis=0) * 100.0
    diffs = means - gate_matrix[:, base_for_variant].mean(axis=0)

    bonferroni_alpha = 0.05 / n_variants
    bh_zero = benjamini_hochberg(obs_p0)
    bh_base = benjamini_hochberg(np.where(self_compare, 1.0, obs_pb))

    print("=" * 118)
    print("CENSORED BASELINES (no stop, no target, no gap-fill exit) -- the benchmark every")
    print("variant at that horizon must beat:")
    print(f"{'horizon':>8} {'N':>4} {'mean':>9} {'median':>9} {'win%':>7} {'sd':>8} {'p vs 0':>9} {'Wilcox p':>9}")
    for h in CENSOR_HORIZONS:
        s = summarize(gate_matrix[:, base_cols[h]])
        print(f"{h:>7}m {s['n']:>4} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% {s['win']:>6.1f}% "
              f"{s['std']:>7.1f} {s['p']:>9.4f} {s['wilcoxon']:>9.4f}")
    print()

    print("=" * 118)
    print("FULL VARIANT GRID (in-sample, all 55 trades)")
    header = (f"{'variant':<48} {'mean':>9} {'median':>9} {'win%':>7} {'p vs 0':>9} "
              f"{'vs base':>10} {'p vs base':>10} {'Bonf':>5} {'FDR0':>5} {'FDRb':>5}")
    print(header)
    print("-" * len(header))
    for j, v in enumerate(variants):
        flag_b = "yes" if obs_p0[j] < bonferroni_alpha else "no"
        print(
            f"{variant_label(v):<48} {means[j]:>+8.2f}% {medians[j]:>+8.2f}% {wins[j]:>6.1f}% "
            f"{obs_p0[j]:>9.4f} {diffs[j]:>+9.2f}pp "
            f"{('  --  ' if self_compare[j] else f'{obs_pb[j]:10.4f}')} "
            f"{flag_b:>5} {('yes' if bh_zero[j] else 'no'):>5} "
            f"{('  -- ' if self_compare[j] else ('yes' if bh_base[j] else 'no')):>5}"
        )

    print("\n" + "=" * 118)
    print("MULTIPLE-COMPARISONS SUMMARY")
    print(f"  variants tested in this script                 : {n_variants}")
    print(f"  Bonferroni threshold (alpha=0.05)              : {bonferroni_alpha:.2e}")
    print(f"  variants with raw p vs zero < 0.05             : {int((obs_p0 < 0.05).sum())}")
    print(f"  variants surviving Bonferroni vs zero          : {int((obs_p0 < bonferroni_alpha).sum())}")
    print(f"  variants surviving Benjamini-Hochberg vs zero   : {int(bh_zero.sum())}")
    testable = ~self_compare
    print(f"  variants with raw p vs censored baseline < 0.05: {int((obs_pb[testable] < 0.05).sum())} of {int(testable.sum())}")
    print(f"  variants surviving Bonferroni vs baseline      : {int((obs_pb[testable] < bonferroni_alpha).sum())}")
    print(f"  variants surviving Benjamini-Hochberg vs base   : {int(bh_base[testable].sum())}")

    best_zero = int(np.argmin(obs_p0))
    best_base = int(np.argmin(np.where(self_compare, np.inf, obs_pb)))
    best_mean = int(np.argmax(means))
    print(f"\n  best-of-grid p vs zero      : {obs_p0[best_zero]:.6f}  [{variant_label(variants[best_zero])}]")
    print(f"  best-of-grid p vs baseline  : {obs_pb[best_base]:.6f}  [{variant_label(variants[best_base])}]")
    print(f"  highest mean variant        : {means[best_mean]:+.2f}%  [{variant_label(variants[best_mean])}]")

    print("\n" + "=" * 118)
    print("CROSS-HORIZON AND INCUMBENT COMPARISONS FOR THE BEST-OF-GRID WINNER")
    print("(the winner is judged not only against its own horizon's baseline but against every")
    print(" simpler rule already on the table, paired trade by trade)")
    winner_ret = gate_matrix[:, best_zero]
    incumbents = {}
    for h in CENSOR_HORIZONS:
        incumbents[f"plain censored H={h}m"] = gate_matrix[:, base_cols[h]]
    hold_close = np.asarray([(p["prices"][-1] - p["C0"]) / p["C0"] * 100.0 for p in gate])
    gap_only = np.asarray([
        (p["prices"][p["gap_fill_idx"] if p["gap_fill_idx"] is not None else -1] - p["C0"])
        / p["C0"] * 100.0 for p in gate
    ])
    incumbents["hold to close (no rules)"] = hold_close
    incumbents["gap-fill exit (module spec)"] = gap_only
    print(f"\n  winner: {variant_label(variants[best_zero])}")
    print(f"  winner: mean={winner_ret.mean():+.2f}% median={np.median(winner_ret):+.2f}% "
          f"win={np.mean(winner_ret>0)*100:.1f}% sd={winner_ret.std(ddof=1):.1f} p vs 0={obs_p0[best_zero]:.5f}")
    print(f"\n  {'incumbent rule':<32} {'mean':>9} {'median':>9} {'win%':>7} {'sd':>7} "
          f"{'diff':>9} {'p paired':>9}")
    print("  " + "-" * 86)
    for name, series in incumbents.items():
        d = winner_ret - series
        pv = float(vectorized_p(d.reshape(-1, 1))[0])
        print(f"  {name:<32} {series.mean():>+8.2f}% {np.median(series):>+8.2f}% "
              f"{np.mean(series>0)*100:>6.1f}% {series.std(ddof=1):>6.1f} "
              f"{d.mean():>+8.2f}pp {pv:>9.4f}")

    print("\n" + "=" * 118)
    print(f"SHUFFLED-LABEL PLACEBO, {N_PLACEBO} draws")
    print("Each draw reassigns the 55 Gate-A labels at random among the 118 expiry-day gap-down")
    print("paths.  This preserves N, expiry-day decay, PUT direction and the full exit machinery")
    print("while destroying the overnight-VIX-rise association.  For each draw the BEST p-value")
    print("across all variants is recorded, giving the null distribution of a best-of-grid search.")
    rng = np.random.default_rng(PLACEBO_SEED)
    n_gate = len(gate_rows)
    placebo_best_zero = np.empty(N_PLACEBO)
    placebo_best_base = np.empty(N_PLACEBO)
    placebo_any_005 = np.empty(N_PLACEBO, dtype=bool)
    for rep in range(N_PLACEBO):
        idx = rng.choice(all_matrix.shape[0], size=n_gate, replace=False)
        sub = all_matrix[idx, :]
        p0 = vectorized_p(sub)
        pb = np.where(self_compare, 1.0, paired_p(sub, sub[:, base_for_variant]))
        placebo_best_zero[rep] = p0.min()
        placebo_best_base[rep] = pb.min()
        placebo_any_005[rep] = bool((p0 < 0.05).any())

    emp_zero = (np.sum(placebo_best_zero <= obs_p0[best_zero]) + 1) / (N_PLACEBO + 1)
    emp_base = (np.sum(placebo_best_base <= obs_pb[best_base]) + 1) / (N_PLACEBO + 1)
    print(f"\n  observed best-of-grid p vs zero      = {obs_p0[best_zero]:.6f}")
    print(f"  placebo best-of-grid p vs zero       : median {np.median(placebo_best_zero):.6f}, "
          f"5th pct {np.percentile(placebo_best_zero, 5):.6f}")
    print(f"  ==> EMPIRICAL BEST-OF-GRID p (vs zero)     = {emp_zero:.4f}")
    print(f"\n  observed best-of-grid p vs baseline  = {obs_pb[best_base]:.6f}")
    print(f"  placebo best-of-grid p vs baseline   : median {np.median(placebo_best_base):.6f}, "
          f"5th pct {np.percentile(placebo_best_base, 5):.6f}")
    print(f"  ==> EMPIRICAL BEST-OF-GRID p (vs baseline) = {emp_base:.4f}")
    print(f"\n  at least one of the {n_variants} variants reaches nominal p<0.05 against zero in "
          f"{placebo_any_005.mean()*100:.1f}% of placebo draws")

    # ---------------------------------------------------------------- walk-forward
    print("\n" + "=" * 118)
    print("WALK-FORWARD (protocol identical to walkforward_gate_a_put_stop_take.py)")
    protocol = split_protocol(len(gate))
    held_start = protocol["n_pool"]
    print(f"  N={protocol['n']} held-out={protocol['n_held_out']} pool={protocol['n_pool']} "
          f"seed-train={protocol['initial_train_n']} folds={protocol['folds']}")
    print(f"  untouched hold-out dates: {gate_dates[held_start]} .. {gate_dates[-1]}")
    print("\n  The selection FAMILY is not chosen by full-sample p-value -- that would leak the")
    print("  hold-out into the design.  All six families (3 horizons x gap-fill on/off) are run")
    print("  and reported, and the multiplicity is carried into the placebo below.")

    families = [(h, g) for h in CENSOR_HORIZONS for g in GAP_FILL_MODES]
    family_cols = {
        (h, g): [j for j, v in enumerate(variants) if v["horizon"] == h and v["gap_fill"] == g]
        for h, g in families
    }
    criteria = ("mean", "median", "sharpe_like")

    print(f"\n  {'family':<22} {'criterion':<12} {'N':>3} {'mean':>9} {'median':>9} {'win%':>7} "
          f"{'p vs 0':>9} {'base mean':>10} {'diff':>9} {'p vs base':>10}")
    print("  " + "-" * 112)
    wf_results = {}
    wf_paired_p = []
    for h, g in families:
        cols = family_cols[(h, g)]
        grid = gate_matrix[:, cols]
        base = gate_matrix[:, base_cols[h]]
        for criterion in criteria:
            wf = walk_forward(grid, base, criterion)
            s = summarize(wf["returns"])
            b = summarize(wf["baseline"])
            d = summarize(wf["returns"] - wf["baseline"])
            counts = Counter(variant_label(variants[cols[c]]) for c in wf["cells"])
            wf_results[f"H{h}_gapfill{'on' if g else 'off'}_{criterion}"] = {
                "oof": s, "baseline": b, "paired": d,
                "cells": {k: int(v) for k, v in counts.items()},
            }
            wf_paired_p.append(d["p"])
            fam = f"H={h}m gapfill={'on' if g else 'off'}"
            print(f"  {fam:<22} {criterion:<12} {s['n']:>3} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% "
                  f"{s['win']:>6.1f}% {s['p']:>9.4f} {b['mean']:>+9.2f}% {d['mean']:>+8.2f}pp "
                  f"{d['p']:>10.4f}")
    n_wf_tests = len(wf_paired_p)
    best_wf = int(np.argmin(wf_paired_p))
    print(f"\n  walk-forward configurations reported: {n_wf_tests}")
    print(f"  best OOF p versus the censored baseline: {min(wf_paired_p):.4f}")
    print(f"  Bonferroni threshold across those {n_wf_tests} configurations: {0.05/n_wf_tests:.4f}")

    print("\n  Cell selections chosen out of fold, per configuration:")
    for key, item in wf_results.items():
        top = ", ".join(f"{k.split('stop=')[1].strip()} x{v}" for k, v in
                        sorted(item["cells"].items(), key=lambda kv: -kv[1]))
        print(f"    {key:<34} {top}")

    print("\n  UNTOUCHED MOST-RECENT HOLD-OUT (rule frozen on the 47-trade pool ONLY --")
    print("  the eight hold-out trades were not used to choose it)")
    pool_p = vectorized_p(gate_matrix[:held_start, :])
    frozen = int(np.argmin(pool_p))
    frozen_variant = variants[frozen]
    hold_ret = gate_matrix[held_start:, frozen]
    hold_base = gate_matrix[held_start:, base_cols[frozen_variant["horizon"]]]
    hs = summarize(hold_ret)
    hb = summarize(hold_base)
    hd = summarize(hold_ret - hold_base)
    print(f"    pool-selected rule: [{variant_label(frozen_variant)}] (pool p={pool_p[frozen]:.5f})")
    print(f"    N={hs['n']} mean={hs['mean']:+.2f}% median={hs['median']:+.2f}% win={hs['win']:.1f}% "
          f"p vs 0={hs['p']:.4f} Wilcoxon={hs['wilcoxon']:.4f}")
    print(f"    censored baseline same trades: mean={hb['mean']:+.2f}% median={hb['median']:+.2f}% "
          f"win={hb['win']:.1f}% p vs 0={hb['p']:.4f}")
    print(f"    paired vs baseline: mean-diff={hd['mean']:+.2f}pp p={hd['p']:.4f}")

    print("\n" + "=" * 118)
    print(f"WALK-FORWARD PLACEBO, {N_PLACEBO_WF} shuffled-label draws")
    print("Replicates the whole procedure -- all six families, three criteria, best-of-set --")
    print("under randomly reassigned Gate-A labels, to see how small the best OOF p versus the")
    print("censored baseline gets by chance.")
    rng_wf = np.random.default_rng(PLACEBO_SEED + 1)
    placebo_best_wf = np.empty(N_PLACEBO_WF)
    placebo_wf_any = np.empty(N_PLACEBO_WF, dtype=bool)
    for rep in range(N_PLACEBO_WF):
        idx = np.sort(rng_wf.choice(all_matrix.shape[0], size=n_gate, replace=False))
        sub = all_matrix[idx, :]
        best = 1.0
        for h, g in families:
            grid = sub[:, family_cols[(h, g)]]
            base = sub[:, base_cols[h]]
            for criterion in criteria:
                wf = walk_forward(grid, base, criterion)
                diff = wf["returns"] - wf["baseline"]
                p = float(vectorized_p(diff.reshape(-1, 1))[0])
                best = min(best, p)
        placebo_best_wf[rep] = best
        placebo_wf_any[rep] = best < 0.05
    emp_wf = (np.sum(placebo_best_wf <= min(wf_paired_p)) + 1) / (N_PLACEBO_WF + 1)
    print(f"\n  observed best OOF p vs baseline  = {min(wf_paired_p):.4f}")
    print(f"  placebo best OOF p vs baseline   : median {np.median(placebo_best_wf):.4f}, "
          f"5th pct {np.percentile(placebo_best_wf, 5):.4f}")
    print(f"  at least one of {n_wf_tests} configurations beats the baseline at nominal p<0.05 in "
          f"{placebo_wf_any.mean()*100:.1f}% of placebo draws")
    print(f"  ==> EMPIRICAL p FOR THE OOF INCREMENTAL EDGE = {emp_wf:.4f}")

    # ---------------------------------------------------------------- power
    print("\n" + "=" * 118)
    print("POWER")
    from scipy import optimize

    def power_at(n: int, effect: float, alpha: float = 0.05) -> float:
        df = n - 1
        crit = stats.t.ppf(1 - alpha / 2, df)
        ncp = effect * np.sqrt(n)
        return float(stats.nct.cdf(-crit, df, ncp) + stats.nct.sf(crit, df, ncp))

    def mde(n: int, power: float = 0.80) -> float:
        return float(optimize.brentq(lambda e: power_at(n, e) - power, 1e-9, 10.0))

    for n, tag in ((55, "full in-sample"), (28, "out-of-fold"), (8, "untouched hold-out")):
        d80 = mde(n)
        print(f"  N={n:>3} ({tag:<18}): 80%-power two-sided MDE = {d80:.3f} standard deviations")
    for h in CENSOR_HORIZONS:
        sd = float(np.std(gate_matrix[:, base_cols[h]], ddof=1))
        print(f"  censored baseline sd at H={h}m = {sd:.1f}pp -> detectable mean at N=55: "
              f"{mde(55)*sd:.1f}pp; at N=28: {mde(28)*sd:.1f}pp; at N=8: {mde(8)*sd:.1f}pp")
    paired_sds = {}
    for h in CENSOR_HORIZONS:
        cols = [j for j, v in enumerate(variants) if v["horizon"] == h and not v["is_baseline"]]
        d = gate_matrix[:, cols] - gate_matrix[:, [base_cols[h]] * len(cols)]
        paired_sds[h] = float(np.median(np.std(d, axis=0, ddof=1)))
        print(f"  median paired-difference sd at H={h}m = {paired_sds[h]:.1f}pp -> "
              f"detectable incremental mean at N=55: {mde(55)*paired_sds[h]:.1f}pp; "
              f"at N=28: {mde(28)*paired_sds[h]:.1f}pp")

    def clean(obj):
        if isinstance(obj, dict):
            return {str(k): clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [clean(v) for v in obj]
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return [clean(v) for v in obj.tolist()]
        return obj

    out = clean({
        "n_variants": n_variants,
        "n_exit_rules_this_study": n_variants + 10,
        "best_vs_zero": {
            "variant": variant_label(variants[best_zero]),
            "p": float(obs_p0[best_zero]),
            "empirical_best_of_grid_p": float(emp_zero),
            "summary": summarize(gate_matrix[:, best_zero]),
        },
        "best_vs_baseline": {
            "variant": variant_label(variants[best_base]),
            "p": float(obs_pb[best_base]),
            "empirical_best_of_grid_p": float(emp_base),
            "summary": summarize(gate_matrix[:, best_base]),
        },
        "bonferroni_alpha": float(bonferroni_alpha),
        "n_raw_sig_vs_zero": int((obs_p0 < 0.05).sum()),
        "n_bonferroni_sig_vs_zero": int((obs_p0 < bonferroni_alpha).sum()),
        "n_raw_sig_vs_baseline": int((obs_pb[testable] < 0.05).sum()),
        "n_bonferroni_sig_vs_baseline": int((obs_pb[testable] < bonferroni_alpha).sum()),
        "placebo_any_p005_rate": float(placebo_any_005.mean()),
        "walk_forward": wf_results,
        "walk_forward_best_paired_p": float(min(wf_paired_p)),
        "walk_forward_empirical_p": float(emp_wf),
        "walk_forward_placebo_any_rate": float(placebo_wf_any.mean()),
        "frozen_holdout": {
            "variant": variant_label(frozen_variant),
            "summary": hs, "baseline": hb, "paired": hd,
        },
        "censored_baselines": {
            str(h): summarize(gate_matrix[:, base_cols[h]]) for h in CENSOR_HORIZONS
        },
    })
    with open("gate_a_censored_stops_results.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print("\nWrote gate_a_censored_stops_results.json")


if __name__ == "__main__":
    main()
