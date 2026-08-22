#!/usr/bin/env python3
"""Opening-half-hour high-before-low sequencing scan."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from analyze_high_low_sequence import (
    FEATURES,
    MANIFEST,
    SCRATCH,
    build_hour_levels,
    clock_at,
    load_spot,
    logistic_fit,
    logit_rows,
    p_fmt,
    split_rows,
)

K_VALUES = (2, 5, 10, 15, 20, 25)
TARGET_CEILING = "09:45"


def build_half_hour_panels(
    spot: pd.DataFrame, levels: pd.DataFrame, audit: dict[str, object]
) -> dict[int, pd.DataFrame]:
    daily_close = spot.drop_duplicates("date", keep="last").set_index("date")["spot"].sort_index()
    prior_close = daily_close.shift(1)
    prior_return = daily_close.shift(1) / daily_close.shift(2) - 1.0
    panels: dict[int, pd.DataFrame] = {}
    diagnostics: dict[str, object] = {}
    for k in K_VALUES:
        decision = clock_at(k)
        target_start = clock_at(k + 1)
        initial_clocks = (
            pd.date_range("2000-01-01 09:15", f"2000-01-01 {decision}", freq="min")
            .strftime("%H:%M")
            .tolist()
        )
        target_clocks = (
            pd.date_range(f"2000-01-01 {target_start}", f"2000-01-01 {TARGET_CEILING}", freq="min")
            .strftime("%H:%M")
            .tolist()
        )
        frame = levels.dropna(subset=[*initial_clocks, *target_clocks]).copy()
        initial = frame[initial_clocks].to_numpy(dtype=float)
        target = frame[target_clocks].to_numpy(dtype=float)
        initial_high_index = np.argmax(initial, axis=1)
        initial_low_index = np.argmin(initial, axis=1)
        target_high_index = np.argmax(target, axis=1)
        target_low_index = np.argmin(target, axis=1)
        frame["initial_tie"] = initial_high_index == initial_low_index
        frame["target_tie"] = target_high_index == target_low_index
        frame["initial_high_first"] = (initial_high_index < initial_low_index).astype(int)
        frame["target_high_first"] = (target_high_index < target_low_index).astype(int)
        frame["P0_close"] = prior_close.reindex(frame.index)
        frame["P1"] = prior_return.reindex(frame.index)
        frame["gap"] = frame["09:15"] / frame["P0_close"] - 1.0
        frame["P3"] = frame[decision] / frame["09:15"] - 1.0
        frame["initial_high"] = initial.max(axis=1)
        frame["initial_low"] = initial.min(axis=1)
        frame["initial_range_ratio"] = frame["initial_high"] / frame["initial_low"]
        frame["initial_range_magnitude"] = frame["initial_range_ratio"] - 1.0
        frame["target_high"] = target.max(axis=1)
        frame["target_low"] = target.min(axis=1)
        frame["decision_time"] = decision
        frame["target_start"] = target_start
        frame["target_end"] = TARGET_CEILING
        frame["target_window_minutes"] = len(target_clocks)
        raw_n = len(frame)
        initial_ties = int(frame["initial_tie"].sum())
        target_ties = int(frame["target_tie"].sum())
        frame = frame[(~frame["initial_tie"]) & (~frame["target_tie"])]
        frame = frame.dropna(subset=[*FEATURES, "target_high_first"])
        panels[k] = frame
        diagnostics[str(k)] = {
            "decision_time": decision,
            "target_start": target_start,
            "target_end": TARGET_CEILING,
            "target_window_minutes": len(target_clocks),
            "raw_complete_days": raw_n,
            "initial_ties": initial_ties,
            "target_ties": target_ties,
            "analysis_n": len(frame),
            "first_date": frame.index.min(),
            "last_date": frame.index.max(),
        }
    audit["half_hour_panels"] = diagnostics
    return panels


def report_markdown(results: dict[str, object]) -> str:
    audit = results["audit"]
    summaries = results["summary"]
    splits = results["splits"]
    coefficients = results["logistic_coefficients"]
    split_lookup = {(row["k"], row["split"], row["group"]): row for row in splits}
    coefficient_lookup = {(row["k"], row["term"]): row for row in coefficients}

    lines = [
        "# NIFTY opening-half-hour high-before-low sequence test",
        "",
        "**Exploratory full-sample scan, capped at 09:45.** Predictors include minute levels "
        "through the k-minute decision boundary. Targets begin at decision+1 and end at 09:45, "
        "so the known boundary level cannot mechanically become the target high or low.",
        "",
        "## Sample",
        "",
        f"The same 66 cached Still_Water files provide {audit['rows']:,} minute stamps. Every "
        "k panel has **1,318 days** after requiring two lagged close proxies and all opening-half-"
        "hour levels. Initial- and target-window tie counts are zero at every k.",
        "",
        "The target windows are 28, 25, 20, 15, 10 and 5 minutes for k=2,5,10,15,20,25. "
        "No k is below the five-minute floor, but k=25 is exactly at it and is flagged as thin. "
        "The label uses first argmax/argmin indices of minute-stamped spot levels.",
        "",
        "## Per-k summary",
        "",
        "| k | N | Future minutes | Base high/low first | Best univariate contrast | "
        "Pseudo-R² | Logistic accuracy vs base | Standout |",
        "|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['k']} | {row['n']} | {row['target_window_minutes']} | "
            f"{100 * row['base_high_first_rate']:.1f}% / "
            f"{100 * (1 - row['base_high_first_rate']):.1f}% | "
            f"{row['best_split_label']} | {100 * row['pseudo_r_squared']:.2f}% | "
            f"{100 * row['accuracy']:.1f}% vs {100 * row['base_accuracy']:.1f}% "
            f"({100 * row['accuracy_uplift']:+.1f} pp) | {row['standout']} |"
        )

    lines += [
        "",
        "Base rates remain close to 50/50, ranging from 48.6% to 51.6% high-first. No "
        "structural opening-half-hour ordering bias dominates the classification null.",
        "",
        "## Direct initial-sequence persistence",
        "",
        "| k | Target high-first after initial high-first | After initial low-first | "
        "Difference | p |",
        "|---:|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        high = split_lookup[(k, "initial_sequence", "high_first")]
        low = split_lookup[(k, "initial_sequence", "low_first")]
        lines.append(
            f"| {k} | {100 * high['high_first_rate']:.1f}% (N={high['n']}) | "
            f"{100 * low['high_first_rate']:.1f}% (N={low['n']}) | "
            f"{100 * high['contrast_rate_difference']:+.1f} pp | "
            f"{p_fmt(high['contrast_p'])} |"
        )

    lines += [
        "",
        "The direct persistence effect is largest at k=2: 52.5% after an initial high-first "
        "versus 47.6% after initial low-first (+4.9 pp, p=.078). It vanishes or reverses at "
        "k=5–25, so it is not a stable univariate rule.",
        "",
        "## All univariate sign splits",
        "",
        "Each cell is high-first rate for positive/high-first versus negative/low-first, then "
        "the rate difference and two-proportion p-value.",
        "",
        "| k | gap +/− | P1 +/− | P3 +/− | Initial high/low first |",
        "|---:|---:|---:|---:|---:|",
    ]
    split_specs = [
        ("gap_sign", "positive", "negative"),
        ("P1_sign", "positive", "negative"),
        ("P3_sign", "positive", "negative"),
        ("initial_sequence", "high_first", "low_first"),
    ]
    for k in K_VALUES:
        cells: list[str] = []
        for split_name, a_name, b_name in split_specs:
            a = split_lookup[(k, split_name, a_name)]
            b = split_lookup[(k, split_name, b_name)]
            cells.append(
                f"{100 * a['high_first_rate']:.1f}/{100 * b['high_first_rate']:.1f}, "
                f"Δ{100 * a['contrast_rate_difference']:+.1f}, p={p_fmt(a['contrast_p'])}"
            )
        lines.append(f"| {k} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "P1 again has the most consistent direction: negative prior days are followed by more "
        "high-first labels at every k. The largest contrast is k=15: 51.8% after P1− versus "
        "45.7% after P1+ (6.1 pp, unadjusted p=.027), but P1 is not significant in the "
        "multivariate model at that k.",
        "",
        "## Logistic coefficients",
        "",
        "Continuous coefficients are per one-standard-deviation increase; the flag is initial "
        "high-first versus low-first. Each cell is coefficient / HAC z / p.",
        "",
        "| k | gap | P1 | P3 | Initial range ratio | Initial high-first flag |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        cells: list[str] = []
        for term in FEATURES:
            row = coefficient_lookup[(k, term)]
            cells.append(f"{row['coefficient']:.3f} / {row['hac_z']:.2f} / {p_fmt(row['hac_p'])}")
        lines.append(f"| {k} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Only one multivariate coefficient reaches unadjusted p<.05: the initial high-first "
        "flag at k=2 (coefficient 0.384, HAC p=.017). Its implied conditional odds ratio is "
        "about 1.47, but the full model's pseudo-R² is only 0.37% and accuracy uplift is 2.9 pp. "
        "This is the best candidate in the tighter window, not proof of a stable effect.",
        "",
        "## Verdict",
        "",
        "**The half-hour cap produces one plausible local lead, but still no broad sequencing "
        "edge.** At k=2, the initial high/low ordering has the expected persistence direction, "
        "and its conditional logistic coefficient is significant. Yet the univariate contrast "
        "is only borderline, no adjacent k confirms it, pseudo-R² remains below 0.4%, and the "
        "largest accuracy uplift is only 2.9 percentage points in sample.",
        "",
        "The k=15 P1 sign split is also noticeable but does not survive multivariate conditioning. "
        "Because six k values and several predictors were scanned, neither result should be called "
        "real without pre-specifying it and testing a fresh period. If choosing one candidate, "
        "freeze **k=2 initial-sequence persistence** for prospective validation; do not optimize "
        "further on this sample.",
        "",
        "## Caveats",
        "",
        "- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.",
        "- Accuracy and coefficient inference use the full sample by explicit instruction; they "
        "are not OOS performance claims.",
        "- Six k values and multiple splits/coefficient tests are unadjusted for multiple "
        "scanning.",
        "- k=25 has only a five-minute target; its ordering label is especially sensitive to "
        "one-minute resolution.",
        "- P0 is the previous session's final available spot stamp, not an official NSE close.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    spot, audit = load_spot()
    levels = build_hour_levels(spot)
    panels = build_half_hour_panels(spot, levels, audit)
    split_results: list[dict[str, object]] = []
    logit_results: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    long_panels: list[pd.DataFrame] = []

    for k, panel in panels.items():
        splits = split_rows(panel, k=k)
        split_results.extend(splits)
        fit = logistic_fit(panel)
        if not fit.converged:
            raise RuntimeError(f"logistic IRLS did not converge for k={k}")
        logit_results.extend(logit_rows(fit, k=k))
        base_rate = fit.base_high_first_rate
        group_rows = [row for row in splits if row["n"] > 0]
        best = max(group_rows, key=lambda row: abs(row["high_first_rate"] - base_rate))
        counterpart = next(
            row for row in splits if row["split"] == best["split"] and row["group"] != best["group"]
        )
        best_label = (
            f"{best['split']} {best['group']}: {100 * best['high_first_rate']:.1f}% "
            f"vs {100 * counterpart['high_first_rate']:.1f}% "
            f"(Δ{100 * abs(best['contrast_rate_difference']):.1f} pp, "
            f"p={p_fmt(best['contrast_p'])})"
        )
        if k == 2:
            standout = "conditional initial-sequence flag p=.017"
        elif k == 15:
            standout = "P1 sign split p=.027 only"
        elif k == 25:
            standout = "minimum 5-minute target"
        else:
            standout = "none"
        summaries.append(
            {
                "k": k,
                "n": len(panel),
                "target_window_minutes": int(panel["target_window_minutes"].iloc[0]),
                "base_high_first_rate": base_rate,
                "base_accuracy": fit.base_accuracy,
                "pseudo_r_squared": fit.pseudo_r_squared,
                "accuracy": fit.accuracy,
                "accuracy_uplift": fit.accuracy - fit.base_accuracy,
                "best_split_label": best_label,
                "standout": standout,
            }
        )
        output = panel.reset_index().rename(columns={"index": "date"})
        output["k"] = k
        keep = [
            "date",
            "k",
            "decision_time",
            "target_start",
            "target_end",
            "target_window_minutes",
            "P0_close",
            "gap",
            "P1",
            "P3",
            "initial_high",
            "initial_low",
            "initial_range_ratio",
            "initial_range_magnitude",
            "initial_high_first",
            "target_high",
            "target_low",
            "target_high_first",
        ]
        long_panels.append(output.loc[:, keep])

    results: dict[str, object] = {
        "source": {
            "manifest": str(MANIFEST),
            "selection": {"strike": "ATM", "drv_option_type": "CALL"},
        },
        "definitions": {
            "total_scope": "09:15 through 09:45",
            "initial_window": "inclusive 09:15 through decision 09:15+k",
            "target_window": "strictly future decision+1 through 09:45",
            "high_first": "first argmax index precedes first argmin index",
        },
        "audit": audit,
        "summary": summaries,
        "splits": split_results,
        "logistic_coefficients": logit_results,
    }
    pd.concat(long_panels, ignore_index=True).to_csv(
        SCRATCH / "half_hour_sequence_panel.csv", index=False
    )
    pd.DataFrame(summaries).to_csv(SCRATCH / "half_hour_sequence_summary.csv", index=False)
    pd.DataFrame(split_results).to_csv(SCRATCH / "half_hour_sequence_splits.csv", index=False)
    pd.DataFrame(logit_results).to_csv(SCRATCH / "half_hour_sequence_logit.csv", index=False)
    (SCRATCH / "half_hour_sequence_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = report_markdown(results)
    (SCRATCH / "report_half_hour_sequence.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
