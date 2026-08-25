#!/usr/bin/env python3
"""Walk-forward validation of the Gate-A PUT stop-loss/take-profit overlay.

This script deliberately mirrors ``ml_walkforward_put_call.py``:

* chronological ordering;
* most-recent 15% held out and untouched during model/rule selection;
* the earlier 85% is a walk-forward pool;
* its oldest 40% seeds an expanding training window;
* seven consecutive validation folds are predicted out of fold.

The outcome is the Black-Scholes theoretical PUT return generated with exactly the
premium path and exit priority used by ``bs_gate_a_put_stop_take.py``.  It is a
model-dependent proxy, not an observed executable option fill.

The placebo permutes the observed overnight-VIX-rise label among all expiry-day,
gap-down candidate paths.  This preserves the number of selected trades (55), the
expiry-day time-to-expiry construction, and the exit machinery while breaking the
Gate-A association.  A fixed seed supplies one auditable placebo; repeated permutations
estimate how frequently chance produces nominally significant results.
"""
from __future__ import annotations

from collections import Counter
import math

import numpy as np
import pandas as pd
from scipy import optimize, stats

from analyze_still_water_spot import load_spot
from bs_gap_fill_pnl import RISK_FREE_RATE, STRIKE_STEP, bs_call
from ml_gated_put_call import build_dataset


ENTRY_CLOCK = "09:17"
STOP_LOSSES = (0.30, 0.50, 0.60)
TAKE_PROFITS = (0.50, 0.75, 1.00)
GRID = tuple((sl, tp) for sl in STOP_LOSSES for tp in TAKE_PROFITS)
CRITERIA = ("mean", "median", "sharpe_like")

# These constants intentionally match ml_walkforward_put_call.py.
HELD_OUT_FRACTION = 0.15
N_WALKFORWARD_FOLDS = 7
INITIAL_TRAIN_FRACTION = 0.40

PLACEBO_SEED = 20260822
N_PLACEBO_PERMUTATIONS = 5000


def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put via the same call-pricing helper and put-call parity."""
    return bs_call(S, K, T, r, sigma) - S + K * np.exp(-r * T)


def build_expiry_gapdown_paths() -> list[dict]:
    """Build all eligible expiry-day gap-down PUT paths, not only Gate A.

    ``vix_rose`` is retained as the observed Gate-A selection label.  The wider
    expiry-gap-down universe is needed only for the shuffled-label placebo.
    """
    df = build_dataset()
    candidates = (
        df[(df["is_expiry_day"] == 1) & (df["gap_dir"] == "down")]
        .copy()
        .sort_values("date")
        .reset_index(drop=True)
    )
    candidates["date_str"] = candidates["date"].dt.strftime("%Y-%m-%d")

    dm = pd.read_csv("daily_measures.csv", parse_dates=["date"])
    dm["date_str"] = dm["date"].dt.strftime("%Y-%m-%d")
    candidates = candidates.merge(
        dm[["date_str", "prior_session_1529_spot"]],
        on="date_str",
        how="left",
        validate="one_to_one",
    )

    spot, _ = load_spot()
    spot = spot[(spot["clock"] >= "09:15") & (spot["clock"] <= "15:29")].copy()

    paths: list[dict] = []
    for _, day in candidates.iterrows():
        date_str = day["date_str"]
        prior_close = day["prior_session_1529_spot"]
        opening_iv = day["opening_iv"] / 100.0
        path = spot[spot["date"] == date_str].sort_values("clock")
        if path.empty or pd.isna(prior_close) or pd.isna(opening_iv):
            continue
        entry_row = path.loc[path["clock"] == ENTRY_CLOCK]
        if entry_row.empty:
            continue

        S0 = float(entry_row["spot"].iloc[0])
        K = round(S0 / STRIKE_STEP) * STRIKE_STEP
        expiry_dt = pd.Timestamp(f"{date_str} 15:30:00")
        entry_dt = pd.Timestamp(f"{date_str} {ENTRY_CLOCK}:00")
        T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)
        if T0 <= 0:
            continue
        C0 = bs_put(S0, K, T0, RISK_FREE_RATE, opening_iv)
        if not np.isfinite(C0) or C0 <= 0:
            continue

        rest = path[path["clock"] >= ENTRY_CLOCK].reset_index(drop=True)
        prices: list[float] = []
        for _, row in rest.iterrows():
            now = pd.Timestamp(f"{date_str} {row['clock']}:00")
            T = max((expiry_dt - now).total_seconds() / (365.0 * 24 * 3600), 1e-6)
            prices.append(bs_put(float(row["spot"]), K, T, RISK_FREE_RATE, opening_iv))

        gap_fill_idx = None
        for i, row in enumerate(rest.itertuples()):
            if float(row.spot) >= prior_close:
                gap_fill_idx = i
                break

        paths.append(
            {
                "date": date_str,
                "vix_rose": int(day["vix_rose"]),
                "C0": C0,
                "prices": np.asarray(prices, dtype=float),
                "gap_fill_idx": gap_fill_idx,
            }
        )
    return paths


def returns_for_rule(paths: list[dict], stop: float | None, target: float | None) -> np.ndarray:
    """Apply stop -> target -> gap-fill priority at each minute, as in the source script."""
    returns: list[float] = []
    for path in paths:
        C0 = path["C0"]
        prices = path["prices"]
        exit_i = len(prices) - 1
        for i, premium in enumerate(prices):
            ret = (premium - C0) / C0
            if stop is not None and ret <= -stop:
                exit_i = i
                break
            if target is not None and ret >= target:
                exit_i = i
                break
            if path["gap_fill_idx"] is not None and i == path["gap_fill_idx"]:
                exit_i = i
                break
        returns.append((prices[exit_i] - C0) / C0 * 100.0)
    return np.asarray(returns)


def return_matrices(paths: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    grid = np.column_stack([returns_for_rule(paths, sl, tp) for sl, tp in GRID])
    baseline = returns_for_rule(paths, None, None)
    return grid, baseline


def split_protocol(n: int) -> dict:
    n_held_out = int(round(n * HELD_OUT_FRACTION))
    n_pool = n - n_held_out
    initial_train_n = int(round(n_pool * INITIAL_TRAIN_FRACTION))
    remaining = n_pool - initial_train_n
    fold_size = remaining // N_WALKFORWARD_FOLDS
    folds: list[tuple[int, int]] = []
    cursor = initial_train_n
    for fold_i in range(N_WALKFORWARD_FOLDS):
        fold_end = cursor + fold_size if fold_i < N_WALKFORWARD_FOLDS - 1 else n_pool
        if fold_end > cursor:
            folds.append((cursor, fold_end))
        cursor = fold_end
    return {
        "n": n,
        "n_held_out": n_held_out,
        "n_pool": n_pool,
        "initial_train_n": initial_train_n,
        "folds": folds,
    }


def score_columns(train_returns: np.ndarray, criterion: str) -> np.ndarray:
    if criterion == "mean":
        return np.mean(train_returns, axis=0)
    if criterion == "median":
        return np.median(train_returns, axis=0)
    if criterion == "sharpe_like":
        means = np.mean(train_returns, axis=0)
        stds = np.std(train_returns, axis=0, ddof=1)
        return np.divide(means, stds, out=np.full_like(means, -np.inf), where=stds > 0)
    raise ValueError(f"Unknown criterion: {criterion}")


def select_cell(train_returns: np.ndarray, criterion: str) -> int:
    """Select the maximum score; GRID order is the disclosed deterministic tie-break."""
    scores = score_columns(train_returns, criterion)
    return int(np.flatnonzero(np.isclose(scores, np.nanmax(scores), rtol=1e-12, atol=1e-12))[0])


def ttest_onesample(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 2 or np.std(values, ddof=1) == 0:
        return float("nan"), float("nan")
    result = stats.ttest_1samp(values, 0.0)
    return float(result.statistic), float(result.pvalue)


def wilcoxon_onesample(values: np.ndarray) -> float:
    if len(values) == 0 or np.allclose(values, 0):
        return float("nan")
    try:
        return float(stats.wilcoxon(values, alternative="two-sided").pvalue)
    except ValueError:
        return float("nan")


def summarize(values: np.ndarray) -> dict:
    t_stat, p_value = ttest_onesample(values)
    return {
        "n": len(values),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "win_rate": float(np.mean(values > 0) * 100.0),
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else float("nan"),
        "t": t_stat,
        "p": p_value,
        "wilcoxon_p": wilcoxon_onesample(values),
    }


def paired_comparison(strategy: np.ndarray, baseline: np.ndarray) -> dict:
    diff = strategy - baseline
    out = summarize(diff)
    out["mean_difference"] = out.pop("mean")
    out["median_difference"] = out.pop("median")
    return out


def walk_forward(grid_returns: np.ndarray, baseline_returns: np.ndarray, dates: list[str]) -> dict:
    protocol = split_protocol(len(dates))
    by_criterion: dict[str, dict] = {}
    for criterion in CRITERIA:
        selected_returns: list[float] = []
        selected_baseline: list[float] = []
        selected_indices: list[int] = []
        fold_reports: list[dict] = []
        for fold_i, (start, end) in enumerate(protocol["folds"], start=1):
            chosen = select_cell(grid_returns[:start, :], criterion)
            selected_indices.append(chosen)
            selected_returns.extend(grid_returns[start:end, chosen].tolist())
            selected_baseline.extend(baseline_returns[start:end].tolist())
            fold_reports.append(
                {
                    "fold": fold_i,
                    "train_n": start,
                    "val_n": end - start,
                    "val_start": dates[start],
                    "val_end": dates[end - 1],
                    "cell": GRID[chosen],
                }
            )
        strategy = np.asarray(selected_returns)
        baseline = np.asarray(selected_baseline)
        cell_counts = Counter(GRID[i] for i in selected_indices)
        jumps = sum(a != b for a, b in zip(selected_indices[:-1], selected_indices[1:]))
        by_criterion[criterion] = {
            "summary": summarize(strategy),
            "baseline": summarize(baseline),
            "paired_vs_baseline": paired_comparison(strategy, baseline),
            "cell_counts": dict(cell_counts),
            "dominant_share": max(cell_counts.values()) / len(selected_indices),
            "jumps": jumps,
            "fold_reports": fold_reports,
            "returns": strategy,
        }
    return {"protocol": protocol, "criteria": by_criterion}


def fixed_cell_test(grid_returns: np.ndarray, baseline_returns: np.ndarray, dates: list[str]) -> dict:
    protocol = split_protocol(len(dates))
    start = protocol["n_pool"]
    baseline = baseline_returns[start:]
    output = {
        "dates": (dates[start], dates[-1]),
        "baseline": summarize(baseline),
        "cells": {},
    }
    for cell in ((0.30, 0.50), (0.30, 0.75)):
        idx = GRID.index(cell)
        values = grid_returns[start:, idx]
        output["cells"][cell] = {
            "summary": summarize(values),
            "paired_vs_baseline": paired_comparison(values, baseline),
            "returns": values,
        }
    return output


def two_sided_t_power(n: int, standardized_effect: float, alpha: float = 0.05) -> float:
    df = n - 1
    critical = stats.t.ppf(1 - alpha / 2, df)
    ncp = standardized_effect * math.sqrt(n)
    return float(stats.nct.cdf(-critical, df, ncp) + stats.nct.sf(critical, df, ncp))


def standardized_mde(n: int, target_power: float = 0.80) -> float:
    return float(
        optimize.brentq(
            lambda effect: two_sided_t_power(n, effect) - target_power,
            1e-9,
            10.0,
        )
    )


def placebo_exercise(
    all_paths: list[dict],
    all_grid: np.ndarray,
    all_baseline: np.ndarray,
    rng: np.random.Generator,
) -> tuple[dict, dict, np.ndarray]:
    """Run one auditable label-shuffle placebo and repeated chance calibration."""
    n_gate_a = sum(path["vix_rose"] == 1 for path in all_paths)

    def one_draw() -> tuple[np.ndarray, list[str]]:
        chosen = np.sort(rng.choice(len(all_paths), size=n_gate_a, replace=False))
        dates = [all_paths[i]["date"] for i in chosen]
        return chosen, dates

    chosen, dates = one_draw()
    one_walk = walk_forward(all_grid[chosen, :], all_baseline[chosen], dates)
    one_fixed = fixed_cell_test(all_grid[chosen, :], all_baseline[chosen], dates)

    # Columns: three adaptive OOF p-values, two fixed-cell held-out p-values.
    permutation_p = np.empty((N_PLACEBO_PERMUTATIONS, 5), dtype=float)
    for rep in range(N_PLACEBO_PERMUTATIONS):
        indices, rep_dates = one_draw()
        wf = walk_forward(all_grid[indices, :], all_baseline[indices], rep_dates)
        fx = fixed_cell_test(all_grid[indices, :], all_baseline[indices], rep_dates)
        for j, criterion in enumerate(CRITERIA):
            permutation_p[rep, j] = wf["criteria"][criterion]["summary"]["p"]
        permutation_p[rep, 3] = fx["cells"][(0.30, 0.50)]["summary"]["p"]
        permutation_p[rep, 4] = fx["cells"][(0.30, 0.75)]["summary"]["p"]
    return one_walk, one_fixed, permutation_p


def fmt_summary(label: str, summary: dict) -> str:
    return (
        f"{label}: N={summary['n']} mean={summary['mean']:+.2f}% "
        f"median={summary['median']:+.2f}% win={summary['win_rate']:.1f}% "
        f"t={summary['t']:+.2f} p={summary['p']:.4f} "
        f"Wilcoxon-p={summary['wilcoxon_p']:.4f}"
    )


def print_walkforward(title: str, result: dict) -> None:
    protocol = result["protocol"]
    print(f"\n=== {title} ===")
    print(
        f"N={protocol['n']} held-out={protocol['n_held_out']} pool={protocol['n_pool']} "
        f"initial-train={protocol['initial_train_n']} folds={protocol['folds']}"
    )
    for criterion in CRITERIA:
        item = result["criteria"][criterion]
        print(fmt_summary(f"OOF {criterion}", item["summary"]))
        paired = item["paired_vs_baseline"]
        print(
            f"  paired vs baseline: mean-diff={paired['mean_difference']:+.2f}pp "
            f"t={paired['t']:+.2f} p={paired['p']:.4f}"
        )
        counts = ", ".join(
            f"-{sl*100:.0f}/+{tp*100:.0f}:{count}"
            for (sl, tp), count in sorted(item["cell_counts"].items())
        )
        print(
            f"  selections [{counts}], dominant={item['dominant_share']*100:.1f}%, "
            f"jumps={item['jumps']}/{len(item['fold_reports'])-1}"
        )
    print(fmt_summary("OOF baseline (same trades)", result["criteria"]["mean"]["baseline"]))


def print_fixed(title: str, result: dict) -> None:
    print(f"\n--- {title}: untouched fixed-cell test {result['dates'][0]}..{result['dates'][1]} ---")
    print(fmt_summary("Baseline", result["baseline"]))
    for cell, item in result["cells"].items():
        label = f"-{cell[0]*100:.0f}/+{cell[1]*100:.0f}"
        print(fmt_summary(label, item["summary"]))
        paired = item["paired_vs_baseline"]
        print(
            f"  paired vs baseline: mean-diff={paired['mean_difference']:+.2f}pp "
            f"t={paired['t']:+.2f} p={paired['p']:.4f}"
        )


def main() -> None:
    all_paths = build_expiry_gapdown_paths()
    all_grid, all_baseline = return_matrices(all_paths)
    gate_indices = np.asarray([i for i, path in enumerate(all_paths) if path["vix_rose"] == 1])
    gate_paths = [all_paths[i] for i in gate_indices]
    gate_grid = all_grid[gate_indices, :]
    gate_baseline = all_baseline[gate_indices]
    gate_dates = [path["date"] for path in gate_paths]

    # Reproduction assertions guard against an accidental methodology drift.
    if len(gate_paths) != 55:
        raise AssertionError(f"Expected 55 Gate-A PUT paths, got {len(gate_paths)}")
    expected_means = np.asarray([25.8, 31.2, 34.9, 22.7, 28.2, 31.6, 23.1, 29.4, 33.0])
    if not np.allclose(np.mean(gate_grid, axis=0), expected_means, atol=0.06):
        raise AssertionError("Full-sample grid no longer reproduces bs_gate_a_put_stop_take.py")
    if not np.isclose(np.mean(gate_baseline), 39.0, atol=0.06):
        raise AssertionError("Full-sample baseline no longer reproduces bs_gate_a_put_stop_take.py")

    full_grid_summaries = {cell: summarize(gate_grid[:, i]) for i, cell in enumerate(GRID)}
    full_baseline = summarize(gate_baseline)
    observed_wf = walk_forward(gate_grid, gate_baseline, gate_dates)
    observed_fixed = fixed_cell_test(gate_grid, gate_baseline, gate_dates)

    rng = np.random.default_rng(PLACEBO_SEED)
    placebo_wf, placebo_fixed, permutation_p = placebo_exercise(
        all_paths, all_grid, all_baseline, rng
    )

    print("Object labels:")
    print("  observed: dates, spot minute paths, prior close, opening IV, VIX-rise label")
    print("  derived: expiry/gap-down membership, ATM strike, gap-fill time")
    print("  model-dependent proxy: Black-Scholes theoretical premium/return")
    print("  estimated: OOF summaries, t/Wilcoxon tests, cell-selection frequencies")
    print("  scenario: stop/target/grid exit returns and shuffled-label placebo")
    print("  unidentified here: executable bid/ask fills, costs, slippage, intraday IV path")
    print(f"\nAll expiry-gap-down candidate paths: {len(all_paths)}; Gate-A paths: {len(gate_paths)}")
    print(f"Gate-A dates: {gate_dates[0]}..{gate_dates[-1]}")
    print("\nFull-sample reproduction (IN-SAMPLE):")
    print(fmt_summary("baseline", full_baseline))
    for cell in GRID:
        print(fmt_summary(f"-{cell[0]*100:.0f}/+{cell[1]*100:.0f}", full_grid_summaries[cell]))

    print_walkforward("OBSERVED GATE-A LABEL", observed_wf)
    print_fixed("OBSERVED GATE-A LABEL", observed_fixed)
    print_walkforward("ONE SHUFFLED-LABEL PLACEBO (seed 20260822)", placebo_wf)
    print_fixed("ONE SHUFFLED-LABEL PLACEBO (seed 20260822)", placebo_fixed)

    labels = ["OOF mean", "OOF median", "OOF Sharpe-like", "fixed -30/+50", "fixed -30/+75"]
    observed_p = np.asarray(
        [
            observed_wf["criteria"][criterion]["summary"]["p"]
            for criterion in CRITERIA
        ]
        + [
            observed_fixed["cells"][(0.30, 0.50)]["summary"]["p"],
            observed_fixed["cells"][(0.30, 0.75)]["summary"]["p"],
        ]
    )
    print(f"\n--- {N_PLACEBO_PERMUTATIONS} shuffled-label chance calibration ---")
    for j, label in enumerate(labels):
        finite = permutation_p[:, j][np.isfinite(permutation_p[:, j])]
        print(
            f"{label}: nominal p<0.05 in {np.mean(finite < 0.05)*100:.1f}% of permutations; "
            f"p<0.0001 in {np.mean(finite < 0.0001)*100:.2f}%; "
            f"empirical P(placebo p <= observed p)="
            f"{(np.sum(finite <= observed_p[j]) + 1) / (len(finite) + 1):.4f}"
        )
    any_sig = np.any(permutation_p < 0.05, axis=1)
    print(f"Any of five reported tests p<0.05: {np.mean(any_sig)*100:.1f}% of permutations")

    for n in (observed_wf["protocol"]["n_pool"] - observed_wf["protocol"]["initial_train_n"],
              observed_wf["protocol"]["n_held_out"]):
        print(
            f"80%-power two-sided t-test MDE at N={n}: standardized mean d={standardized_mde(n):.2f}"
        )


if __name__ == "__main__":
    main()
