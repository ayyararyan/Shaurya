#!/usr/bin/env python3
"""Predict whether the remaining first-hour high occurs before its low."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import norm

SCRATCH = Path(__file__).resolve().parent
MANIFEST = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options/manifest.jsonl"
)
K_VALUES = (2, 5, 10, 15, 20, 30, 45)
CONTINUOUS_FEATURES = ("gap", "P1", "P3", "initial_range_ratio")
FEATURES = (*CONTINUOUS_FEATURES, "initial_high_first")
HAC_LAGS = 5


@dataclass(frozen=True)
class LogisticFit:
    beta: np.ndarray
    hac_se: np.ndarray
    z_stat: np.ndarray
    p_value: np.ndarray
    pseudo_r_squared: float
    accuracy: float
    base_accuracy: float
    base_high_first_rate: float
    converged: bool
    iterations: int
    n: int


def load_spot() -> tuple[pd.DataFrame, dict[str, object]]:
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    selected = [
        row for row in rows if row.get("strike") == "ATM" and row.get("drv_option_type") == "CALL"
    ]
    if len(selected) != 66:
        raise RuntimeError(f"expected 66 ATM/CALL files, found {len(selected)}")
    frames: list[pd.DataFrame] = []
    mismatches: list[dict[str, object]] = []
    for row in selected:
        path = MANIFEST.parent / str(row["from_date"])[:4] / Path(str(row["path"])).name
        frame = pd.read_csv(path, usecols=["spot", "datetime"])
        if len(frame) != int(row["rows"]):
            mismatches.append(
                {"file": path.name, "observed": len(frame), "manifest": int(row["rows"])}
            )
        frames.append(frame)
    if mismatches:
        raise RuntimeError(f"cached files differ from manifest: {mismatches}")
    spot = pd.concat(frames, ignore_index=True)
    spot["datetime"] = pd.to_datetime(spot["datetime"], errors="raise")
    spot["date"] = spot["datetime"].dt.strftime("%Y-%m-%d")
    spot["clock"] = spot["datetime"].dt.strftime("%H:%M")
    audit = {
        "source_files": len(selected),
        "rows": len(spot),
        "unique_dates": int(spot["date"].nunique()),
        "duplicate_timestamps": int(spot.duplicated("datetime").sum()),
        "first_timestamp": spot["datetime"].min().isoformat(),
        "last_timestamp": spot["datetime"].max().isoformat(),
    }
    return spot, audit


def clock_at(minutes_after_0915: int) -> str:
    start = pd.Timestamp("2000-01-01 09:15")
    return (start + pd.Timedelta(minutes=minutes_after_0915)).strftime("%H:%M")


def build_hour_levels(spot: pd.DataFrame) -> pd.DataFrame:
    clocks = pd.date_range("2000-01-01 09:15", "2000-01-01 10:15", freq="min").strftime("%H:%M")
    series: list[pd.Series] = []
    for clock in clocks:
        values = (
            spot.loc[spot["clock"] == clock, ["date", "spot"]]
            .drop_duplicates("date", keep="last")
            .set_index("date")["spot"]
            .rename(clock)
        )
        series.append(values)
    return pd.concat(series, axis=1).sort_index()


def build_panels(
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
            pd.date_range(f"2000-01-01 {target_start}", "2000-01-01 10:15", freq="min")
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
        frame["target_end"] = "10:15"
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
            "target_end": "10:15",
            "target_window_minutes": len(target_clocks),
            "raw_complete_hour_days": raw_n,
            "initial_ties": initial_ties,
            "target_ties": target_ties,
            "analysis_n": len(frame),
            "first_date": frame.index.min(),
            "last_date": frame.index.max(),
        }
    audit["panels"] = diagnostics
    return panels


def logistic_fit(data: pd.DataFrame) -> LogisticFit:
    continuous = data.loc[:, CONTINUOUS_FEATURES].to_numpy(dtype=float)
    means = continuous.mean(axis=0)
    scales = continuous.std(axis=0, ddof=0)
    standardized = (continuous - means) / scales
    design = np.column_stack(
        [np.ones(len(data)), standardized, data["initial_high_first"].to_numpy(dtype=float)]
    )
    y = data["target_high_first"].to_numpy(dtype=float)
    base_rate = float(y.mean())
    beta = np.zeros(design.shape[1])
    beta[0] = math.log(base_rate / (1.0 - base_rate))
    converged = False
    iterations = 0
    for iteration in range(1, 101):
        probability = np.clip(expit(design @ beta), 1e-9, 1.0 - 1e-9)
        weights = probability * (1.0 - probability)
        hessian = design.T @ (weights[:, None] * design)
        step = np.linalg.pinv(hessian) @ design.T @ (y - probability)
        beta += step
        iterations = iteration
        if float(np.max(np.abs(step))) < 1e-10:
            converged = True
            break
    probability = np.clip(expit(design @ beta), 1e-9, 1.0 - 1e-9)
    weights = probability * (1.0 - probability)
    bread = np.linalg.pinv(design.T @ (weights[:, None] * design))
    scores = design * (y - probability)[:, None]
    meat = scores.T @ scores
    for lag in range(1, HAC_LAGS + 1):
        gamma = scores[lag:].T @ scores[:-lag]
        meat += (1.0 - lag / (HAC_LAGS + 1)) * (gamma + gamma.T)
    covariance = bread @ meat @ bread
    robust_se = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    z_stat = beta / robust_se
    p_value = 2.0 * norm.sf(np.abs(z_stat))
    log_likelihood = float(np.sum(y * np.log(probability) + (1.0 - y) * np.log(1.0 - probability)))
    null_log_likelihood = float(
        np.sum(y * math.log(base_rate) + (1.0 - y) * math.log(1.0 - base_rate))
    )
    prediction = (probability >= 0.5).astype(int)
    accuracy = float(np.mean(prediction == y))
    return LogisticFit(
        beta=beta,
        hac_se=robust_se,
        z_stat=z_stat,
        p_value=p_value,
        pseudo_r_squared=1.0 - log_likelihood / null_log_likelihood,
        accuracy=accuracy,
        base_accuracy=max(base_rate, 1.0 - base_rate),
        base_high_first_rate=base_rate,
        converged=converged,
        iterations=iterations,
        n=len(data),
    )


def two_proportion_p(success_a: int, n_a: int, success_b: int, n_b: int) -> float | None:
    if min(n_a, n_b) == 0:
        return None
    pooled = (success_a + success_b) / (n_a + n_b)
    variance = pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b)
    if variance <= 0:
        return None
    z_stat = (success_a / n_a - success_b / n_b) / math.sqrt(variance)
    return float(2.0 * norm.sf(abs(z_stat)))


def split_rows(data: pd.DataFrame, *, k: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    definitions = [
        ("gap_sign", "gap", lambda series: series > 0, "positive", "negative"),
        ("P1_sign", "P1", lambda series: series > 0, "positive", "negative"),
        ("P3_sign", "P3", lambda series: series > 0, "positive", "negative"),
        (
            "initial_sequence",
            "initial_high_first",
            lambda series: series == 1,
            "high_first",
            "low_first",
        ),
    ]
    for split_name, column, positive, positive_label, negative_label in definitions:
        eligible = data[data[column] != 0] if split_name.endswith("_sign") else data
        mask = positive(eligible[column])
        group_a = eligible[mask]
        group_b = eligible[~mask]
        p_value = two_proportion_p(
            int(group_a["target_high_first"].sum()),
            len(group_a),
            int(group_b["target_high_first"].sum()),
            len(group_b),
        )
        for label, group in ((positive_label, group_a), (negative_label, group_b)):
            rows.append(
                {
                    "k": k,
                    "split": split_name,
                    "group": label,
                    "n": len(group),
                    "high_first_rate": float(group["target_high_first"].mean()),
                    "contrast_rate_difference": float(
                        group_a["target_high_first"].mean() - group_b["target_high_first"].mean()
                    ),
                    "contrast_p": p_value,
                }
            )
    return rows


def logit_rows(fit: LogisticFit, *, k: int) -> list[dict[str, object]]:
    terms = ("intercept", *CONTINUOUS_FEATURES, "initial_high_first")
    return [
        {
            "k": k,
            "n": fit.n,
            "term": term,
            "coefficient": float(fit.beta[index]),
            "hac_se": float(fit.hac_se[index]),
            "hac_z": float(fit.z_stat[index]),
            "hac_p": float(fit.p_value[index]),
            "pseudo_r_squared": fit.pseudo_r_squared,
            "accuracy": fit.accuracy,
            "base_accuracy": fit.base_accuracy,
            "accuracy_uplift": fit.accuracy - fit.base_accuracy,
            "base_high_first_rate": fit.base_high_first_rate,
            "converged": fit.converged,
            "iterations": fit.iterations,
        }
        for index, term in enumerate(terms)
    ]


def p_fmt(value: float | None) -> str:
    if value is None:
        return "NA"
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def report_markdown(results: dict[str, object]) -> str:
    audit = results["audit"]
    summaries = results["summary"]
    splits = results["splits"]
    coefficients = results["logistic_coefficients"]
    split_lookup = {(row["k"], row["split"], row["group"]): row for row in splits}
    coefficient_lookup = {(row["k"], row["term"]): row for row in coefficients}

    lines = [
        "# NIFTY first-hour high-before-low sequence test",
        "",
        "**Exploratory full-sample scan.** Predictors use 09:15 through the k-minute decision "
        "boundary. The binary target uses strictly future minute stamps from decision+1 through "
        "10:15, preventing the known boundary level from mechanically becoming the target "
        "high/low.",
        "",
        "## Sample and label",
        "",
        f"The same 66 cached Still_Water files provide {audit['rows']:,} minute stamps. "
        "There are 1,317 usable days for k=2–30 and 1,315 for k=45. One otherwise eligible "
        "first-hour day lacks a required stamp relative to the prior 1,318-day panel; the first "
        "two historical dates lack two lagged closes. Initial-window ties are zero. Target ties "
        "are zero except two at k=45, which are dropped.",
        "",
        "The first occurrence of the window maximum/minimum is used. `high_first=1` when the "
        "maximum's first index precedes the minimum's first index. P3 is the full initial-window "
        "return, 09:15→decision. Logistic continuous predictors are standardized; significance "
        "uses Newey-West HAC(5). Accuracy is in-sample, per Aryan's requested full-sample design.",
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
        "Base rates stay near 50/50; there is no stable high-first drift to exploit. No target "
        "window is under ten minutes; k=45 is shortest at 15 minutes and deserves the most "
        "caution.",
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
        "The most direct hypothesis does not persist reliably. Differences are small, never "
        "conventionally significant, and reverse sign at k=45.",
        "",
        "## All univariate sign splits",
        "",
        "Each cell is target high-first rate for positive/high-first versus negative/low-first, "
        "followed by the rate difference and two-proportion p-value.",
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
        "P1 is the only split with a consistent direction: after a negative prior day, high-first "
        "is more common at every k. The contrast grows from 2.4 pp at k=2 to 7.4 pp at k=45; "
        "only k=45 is clearly significant univariately, after searching seven k values.",
        "",
        "## Logistic coefficients",
        "",
        "Continuous-feature coefficients are per one-standard-deviation increase; the sequence "
        "flag is high-first versus low-first. Each cell is coefficient / HAC z / p.",
        "",
        "| k | gap | P1 | P3 | Initial range ratio | Initial high-first flag |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        cells = []
        for term in FEATURES:
            row = coefficient_lookup[(k, term)]
            cells.append(f"{row['coefficient']:.3f} / {row['hac_z']:.2f} / {p_fmt(row['hac_p'])}")
        lines.append(f"| {k} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Only three coefficient cells reach unadjusted p<.05: initial range at k=10 and k=15 "
        "(both negative), and P1 at k=45 (negative). None represents a broad, stable improvement "
        "across the sweep, and all seven pseudo-R² values are below 0.4%.",
        "",
        "## Verdict",
        "",
        "**No sizeable general sequencing edge appears.** The cheap persistence rule—initial "
        "high-first predicts remaining-hour high-first—does not work consistently. Logistic "
        "accuracy improves on the majority-class base rate by at most 2.7 percentage points and "
        "pseudo-R² never reaches 0.4%.",
        "",
        "The one plausible lead is **k=45 with P1**: following a positive prior day, target "
        "high-first is 45.4%; following a negative prior day it is 52.8% (7.4 pp contrast, "
        "unadjusted p≈.007). The multivariate P1 coefficient is −0.109 (HAC p=.049), and the "
        "full model improves accuracy from 51.1% to 53.8%. That is noticeable but not convincing "
        "after selecting the best of seven k values, especially because only a 15-minute target "
        "remains. Treat it as a pre-specification candidate for a fresh sample, not a current "
        "edge.",
        "",
        "## Caveats",
        "",
        "- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.",
        "- Ties use first argmax/argmin; only flat-window same-index ties are dropped.",
        "- Accuracy and coefficient inference are full-sample by explicit request. They are not "
        "out-of-sample performance claims.",
        "- Seven k values and multiple predictors/splits are scanned without multiple-testing "
        "adjustment; isolated p≈.04–.05 results may be chance.",
        "- P0 is the previous session's final available spot stamp, a close proxy rather than an "
        "official NSE closing index value.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    spot, audit = load_spot()
    levels = build_hour_levels(spot)
    panels = build_panels(spot, levels, audit)
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
        if k == 45:
            standout = "P1 sign; caution: shortest target"
        elif k in {10, 15}:
            standout = "initial range coefficient p<.05"
        else:
            standout = "none"
        summary = {
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
        summaries.append(summary)
        output = panel.reset_index().rename(columns={"index": "date"})
        keep = [
            "date",
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
        output["k"] = k
        long_panels.append(output.loc[:, ["date", "k", *keep[1:]]])

    results: dict[str, object] = {
        "source": {
            "manifest": str(MANIFEST),
            "selection": {"strike": "ATM", "drv_option_type": "CALL"},
        },
        "definitions": {
            "initial_window": "inclusive minute levels from 09:15 through decision 09:15+k",
            "target_window": "strictly future minute levels from decision+1 through 10:15",
            "high_first": "first argmax index precedes first argmin index",
            "P3": "spot(decision)/spot(09:15)-1",
            "range_ratio": "initial max spot / initial min spot",
        },
        "audit": audit,
        "summary": summaries,
        "splits": split_results,
        "logistic_coefficients": logit_results,
    }
    pd.concat(long_panels, ignore_index=True).to_csv(SCRATCH / "sequence_panel.csv", index=False)
    pd.DataFrame(summaries).to_csv(SCRATCH / "sequence_summary.csv", index=False)
    pd.DataFrame(split_results).to_csv(SCRATCH / "sequence_splits.csv", index=False)
    pd.DataFrame(logit_results).to_csv(SCRATCH / "sequence_logit.csv", index=False)
    (SCRATCH / "sequence_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = report_markdown(results)
    (SCRATCH / "report_sequence.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
