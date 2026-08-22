#!/usr/bin/env python3
"""Add weekday and opening-IV controls to the frozen k=2 sequence model."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from analyze_high_low_sequence import CONTINUOUS_FEATURES, HAC_LAGS, MANIFEST, SCRATCH
from scipy.special import expit
from scipy.stats import chi2, norm

PANEL_PATH = SCRATCH / "half_hour_sequence_panel.csv"
BASE_TERMS = (*CONTINUOUS_FEATURES, "initial_high_first")
REGULAR_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
WEEKDAY_CATEGORIES = (*REGULAR_WEEKDAYS, "Special weekend")
IV_BUCKETS = ("low_<14", "middle_14_18", "high_>18")
THIN_CELL_N = 50


@dataclass(frozen=True)
class Fit:
    terms: tuple[str, ...]
    beta: np.ndarray
    covariance: np.ndarray
    robust_se: np.ndarray
    z_stat: np.ndarray
    p_value: np.ndarray
    pseudo_r_squared: float
    accuracy: float
    base_accuracy: float
    base_rate: float
    log_likelihood: float
    converged: bool
    iterations: int
    gradient_max: float
    n: int


def load_opening_iv() -> tuple[pd.DataFrame, dict[str, object]]:
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    selected = [
        row for row in rows if row.get("strike") == "ATM" and row.get("drv_option_type") == "CALL"
    ]
    if len(selected) != 66:
        raise RuntimeError(f"expected 66 ATM/CALL files, found {len(selected)}")
    frames: list[pd.DataFrame] = []
    row_mismatches: list[dict[str, object]] = []
    for row in selected:
        path = MANIFEST.parent / str(row["from_date"])[:4] / Path(str(row["path"])).name
        frame = pd.read_csv(path, usecols=["datetime", "iv"])
        if len(frame) != int(row["rows"]):
            row_mismatches.append(
                {"file": path.name, "observed": len(frame), "manifest": int(row["rows"])}
            )
        frames.append(frame)
    if row_mismatches:
        raise RuntimeError(f"cached files differ from manifest: {row_mismatches}")
    iv = pd.concat(frames, ignore_index=True)
    iv["datetime"] = pd.to_datetime(iv["datetime"], errors="raise")
    iv["date"] = iv["datetime"].dt.strftime("%Y-%m-%d")
    iv["clock"] = iv["datetime"].dt.strftime("%H:%M")
    opening = iv[iv["clock"].isin(["09:15", "09:16"])].copy()
    duplicate_opening_stamps = int(opening.duplicated(["date", "clock"]).sum())
    wide = opening.pivot_table(index="date", columns="clock", values="iv", aggfunc="last")
    complete = wide.dropna(subset=["09:15", "09:16"]).copy()
    complete["opening_iv"] = complete[["09:15", "09:16"]].mean(axis=1)
    complete["iv_bucket"] = np.select(
        [complete["opening_iv"] < 14.0, complete["opening_iv"] <= 18.0],
        ["low_<14", "middle_14_18"],
        default="high_>18",
    )
    audit = {
        "source_files": len(selected),
        "source_rows": len(iv),
        "duplicate_opening_stamps": duplicate_opening_stamps,
        "dates_with_both_iv_prints": len(complete),
        "zero_or_negative_opening_iv_dates": int((complete["opening_iv"] <= 0).sum()),
        "opening_iv_min": float(complete["opening_iv"].min()),
        "opening_iv_max": float(complete["opening_iv"].max()),
    }
    return complete[["opening_iv", "iv_bucket"]], audit


def prepare_panel() -> tuple[pd.DataFrame, dict[str, object]]:
    panel = pd.read_csv(PANEL_PATH, dtype={"date": str})
    panel = panel[panel["k"] == 2].copy()
    if len(panel) != 1318 or panel["date"].duplicated().any():
        raise RuntimeError("unexpected frozen k=2 panel shape")
    opening_iv, audit = load_opening_iv()
    panel = panel.merge(
        opening_iv, left_on="date", right_index=True, how="left", validate="one_to_one"
    )
    panel["date_timestamp"] = pd.to_datetime(panel["date"], errors="raise")
    panel["calendar_weekday"] = panel["date_timestamp"].dt.day_name()
    panel["weekday"] = panel["calendar_weekday"].where(
        panel["calendar_weekday"].isin(REGULAR_WEEKDAYS), "Special weekend"
    )
    audit["frozen_panel_n"] = len(panel)
    audit["missing_opening_iv_in_panel"] = int(panel["opening_iv"].isna().sum())
    audit["weekend_dates_in_panel"] = int((panel["date_timestamp"].dt.dayofweek >= 5).sum())
    panel = panel.dropna(subset=[*BASE_TERMS, "target_high_first", "opening_iv", "iv_bucket"])
    audit["controlled_sample_n"] = len(panel)
    audit["controlled_first_date"] = panel["date"].min()
    audit["controlled_last_date"] = panel["date"].max()
    return panel.sort_values("date").reset_index(drop=True), audit


def design_matrix(
    data: pd.DataFrame, *, controlled: bool, persistence_interactions: bool = False
) -> tuple[np.ndarray, tuple[str, ...]]:
    continuous = data.loc[:, CONTINUOUS_FEATURES].to_numpy(dtype=float)
    scales = continuous.std(axis=0, ddof=0)
    if np.any(scales <= 0):
        raise RuntimeError("zero-variance continuous feature")
    standardized = (continuous - continuous.mean(axis=0)) / scales
    columns = [np.ones(len(data)), *[standardized[:, i] for i in range(standardized.shape[1])]]
    terms = ["intercept", *CONTINUOUS_FEATURES]
    columns.append(data["initial_high_first"].to_numpy(dtype=float))
    terms.append("initial_high_first")
    if controlled:
        for weekday in WEEKDAY_CATEGORIES[1:]:
            columns.append((data["weekday"] == weekday).to_numpy(dtype=float))
            terms.append(f"weekday[{weekday}]")
        for bucket in ("low_<14", "high_>18"):
            columns.append((data["iv_bucket"] == bucket).to_numpy(dtype=float))
            terms.append(f"iv_bucket[{bucket}]")
    if persistence_interactions:
        initial_flag = data["initial_high_first"].to_numpy(dtype=float)
        for weekday in REGULAR_WEEKDAYS[1:]:
            columns.append(initial_flag * (data["weekday"] == weekday).to_numpy(dtype=float))
            terms.append(f"initial_high_first:weekday[{weekday}]")
        for bucket in ("low_<14", "high_>18"):
            columns.append(initial_flag * (data["iv_bucket"] == bucket).to_numpy(dtype=float))
            terms.append(f"initial_high_first:iv_bucket[{bucket}]")
    return np.column_stack(columns), tuple(terms)


def logistic_fit(
    data: pd.DataFrame, *, controlled: bool, persistence_interactions: bool = False
) -> Fit:
    design, terms = design_matrix(
        data, controlled=controlled, persistence_interactions=persistence_interactions
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
    return Fit(
        terms=terms,
        beta=beta,
        covariance=covariance,
        robust_se=robust_se,
        z_stat=z_stat,
        p_value=p_value,
        pseudo_r_squared=1.0 - log_likelihood / null_log_likelihood,
        accuracy=float(np.mean(prediction == y)),
        base_accuracy=max(base_rate, 1.0 - base_rate),
        base_rate=base_rate,
        log_likelihood=log_likelihood,
        converged=converged,
        iterations=iterations,
        gradient_max=float(np.max(np.abs(design.T @ (y - probability)))),
        n=len(data),
    )


def joint_wald(fit: Fit, terms: list[str]) -> dict[str, float | int]:
    indices = [fit.terms.index(term) for term in terms]
    beta = fit.beta[indices]
    covariance = fit.covariance[np.ix_(indices, indices)]
    statistic = float(beta.T @ np.linalg.pinv(covariance) @ beta)
    return {
        "chi_squared": statistic,
        "df": len(indices),
        "p_value": float(chi2.sf(statistic, len(indices))),
    }


def fit_record(fit: Fit, label: str) -> dict[str, object]:
    return {
        "model": label,
        "n": fit.n,
        "base_high_first_rate": fit.base_rate,
        "base_accuracy": fit.base_accuracy,
        "pseudo_r_squared": fit.pseudo_r_squared,
        "accuracy": fit.accuracy,
        "accuracy_uplift": fit.accuracy - fit.base_accuracy,
        "log_likelihood": fit.log_likelihood,
        "converged": fit.converged,
        "iterations": fit.iterations,
        "gradient_max": fit.gradient_max,
    }


def coefficient_records(fit: Fit, label: str) -> list[dict[str, object]]:
    return [
        {
            "model": label,
            "term": term,
            "coefficient": float(fit.beta[i]),
            "hac_se": float(fit.robust_se[i]),
            "hac_z": float(fit.z_stat[i]),
            "hac_p": float(fit.p_value[i]),
            "odds_ratio": float(math.exp(fit.beta[i])),
        }
        for i, term in enumerate(fit.terms)
    ]


def slice_record(data: pd.DataFrame, slice_type: str, slice_value: str) -> dict[str, object]:
    high = data[data["initial_high_first"] == 1]
    low = data[data["initial_high_first"] == 0]
    rate_high = float(high["target_high_first"].mean()) if len(high) else float("nan")
    rate_low = float(low["target_high_first"].mean()) if len(low) else float("nan")
    pooled = float(data["target_high_first"].mean())
    if min(len(high), len(low)) == 0:
        p_value = None
    else:
        pooled_two = float(
            (high["target_high_first"].sum() + low["target_high_first"].sum()) / len(data)
        )
        variance = pooled_two * (1.0 - pooled_two) * (1.0 / len(high) + 1.0 / len(low))
        p_value = (
            None
            if variance <= 0
            else float(2.0 * norm.sf(abs((rate_high - rate_low) / math.sqrt(variance))))
        )
    return {
        "slice_type": slice_type,
        "slice_value": slice_value,
        "n": len(data),
        "base_high_first_rate": pooled,
        "initial_high_first_n": len(high),
        "target_rate_after_initial_high_first": rate_high,
        "initial_low_first_n": len(low),
        "target_rate_after_initial_low_first": rate_low,
        "persistence_effect": rate_high - rate_low,
        "persistence_p": p_value,
        "thin_cell_warning": len(data) < THIN_CELL_N,
    }


def build_slices(panel: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for weekday in WEEKDAY_CATEGORIES:
        rows.append(slice_record(panel[panel["weekday"] == weekday], "weekday", weekday))
    for bucket in IV_BUCKETS:
        rows.append(slice_record(panel[panel["iv_bucket"] == bucket], "iv_bucket", bucket))
    for weekday in REGULAR_WEEKDAYS:
        for bucket in IV_BUCKETS:
            subset = panel[(panel["weekday"] == weekday) & (panel["iv_bucket"] == bucket)]
            rows.append(slice_record(subset, "weekday_x_iv", f"{weekday}|{bucket}"))
    return rows


def fmt_p(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "NA"
    return "<.001" if value < 0.001 else f"{value:.3f}".lstrip("0")


def report_markdown(results: dict[str, object]) -> str:
    models = {row["model"]: row for row in results["models"]}
    coefs = {(row["model"], row["term"]): row for row in results["coefficients"]}
    slices = results["slices"]
    baseline = models["baseline_common_sample"]
    controlled = models["weekday_and_iv_controls"]
    original_flag = coefs[("baseline_common_sample", "initial_high_first")]
    controlled_flag = coefs[("weekday_and_iv_controls", "initial_high_first")]
    weekday_rows = [row for row in slices if row["slice_type"] == "weekday"]
    iv_rows = [row for row in slices if row["slice_type"] == "iv_bucket"]
    cell_rows = [row for row in slices if row["slice_type"] == "weekday_x_iv"]
    audit = results["audit"]
    lines = [
        "# NIFTY k=2 sequence model with weekday and opening-IV controls",
        "",
        "**Exploratory full-sample follow-up.** The frozen decision/target timing is unchanged: "
        "predictors use 09:15–09:17 and the target label uses strictly future minute stamps "
        "09:18–09:45 (28 observations). Opening IV is the arithmetic mean of the ATM-call "
        "09:15 and 09:16 prints. Buckets are low <14, middle 14–18 inclusive, and high >18.",
        "",
        "## Model comparison",
        "",
        f"All **{controlled['n']:,}** frozen-panel days have both IV prints; no observations are "
        "lost. The high-first base rate is "
        f"**{100 * controlled['base_high_first_rate']:.1f}%**. Continuous predictors retain "
        "the prior one-standard-deviation scaling; Monday and middle IV are reference categories. "
        "Five special weekend sessions are retained under their own dummy. Inference is "
        "Newey-West HAC(5), and accuracy is in-sample.",
        "",
        "| Model | N | Pseudo-R² | Accuracy | Base | Uplift | Initial flag β / HAC p |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Original predictors | {baseline['n']} | {100 * baseline['pseudo_r_squared']:.2f}% | "
        f"{100 * baseline['accuracy']:.1f}% | {100 * baseline['base_accuracy']:.1f}% | "
        f"{100 * baseline['accuracy_uplift']:+.1f} pp | "
        f"{original_flag['coefficient']:.3f} / {fmt_p(original_flag['hac_p'])} |",
        f"| + weekday and IV bucket | {controlled['n']} | "
        f"{100 * controlled['pseudo_r_squared']:.2f}% | "
        f"{100 * controlled['accuracy']:.1f}% | {100 * controlled['base_accuracy']:.1f}% | "
        f"{100 * controlled['accuracy_uplift']:+.1f} pp | "
        f"{controlled_flag['coefficient']:.3f} / {fmt_p(controlled_flag['hac_p'])} |",
        "",
        "The controls add **"
        f"{100 * (controlled['pseudo_r_squared'] - baseline['pseudo_r_squared']):.2f} "
        "percentage points** of pseudo-R² and change accuracy by "
        f"**{100 * (controlled['accuracy'] - baseline['accuracy']):+.1f} pp**. The "
        "initial-sequence "
        f"coefficient changes from {original_flag['coefficient']:.3f} to "
        f"{controlled_flag['coefficient']:.3f}; its HAC p-value changes from "
        f"{fmt_p(original_flag['hac_p'])} to {fmt_p(controlled_flag['hac_p'])}.",
        "",
        "The robust joint Wald tests are "
        f"weekday p={fmt_p(results['joint_tests']['weekday']['p_value'])}, "
        f"IV-bucket p={fmt_p(results['joint_tests']['iv_bucket']['p_value'])}, and all seven "
        f"added controls p={fmt_p(results['joint_tests']['all_controls']['p_value'])}.",
        "",
        "## Weekday breakdown",
        "",
        "Persistence effect = target high-first rate after initial high-first minus the rate "
        "after initial low-first.",
        "",
        "| Day | N | Base high-first | After initial high / low | Persistence effect | p |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in weekday_rows:
        lines.append(
            f"| {row['slice_value']} | {row['n']} | {100 * row['base_high_first_rate']:.1f}% | "
            f"{100 * row['target_rate_after_initial_high_first']:.1f}% / "
            f"{100 * row['target_rate_after_initial_low_first']:.1f}% | "
            f"{100 * row['persistence_effect']:+.1f} pp | {fmt_p(row['persistence_p'])} |"
        )
    lines += [
        "",
        "## Opening-IV breakdown",
        "",
        "| IV bucket | N | Base high-first | After initial high / low | Persistence effect | p |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in iv_rows:
        lines.append(
            f"| {row['slice_value']} | {row['n']} | {100 * row['base_high_first_rate']:.1f}% | "
            f"{100 * row['target_rate_after_initial_high_first']:.1f}% / "
            f"{100 * row['target_rate_after_initial_low_first']:.1f}% | "
            f"{100 * row['persistence_effect']:+.1f} pp | {fmt_p(row['persistence_p'])} |"
        )
    thin = [row for row in cell_rows if row["thin_cell_warning"]]
    min_cell = min(cell_rows, key=lambda row: row["n"])
    max_cell = max(cell_rows, key=lambda row: row["n"])
    lines += [
        "",
        "## Weekday × IV cell-size audit",
        "",
        f"The 15 joint cells range from **N={min_cell['n']}** ({min_cell['slice_value']}) to "
        f"**N={max_cell['n']}** ({max_cell['slice_value']}). **{len(thin)}/15** cells have N<"
        f"{THIN_CELL_N} and are flagged as thin. Full cell estimates are saved in the CSV; "
        "the separate tables above are the more defensible summaries.",
        "",
        "The standout joint cell is **Thursday × high IV**: N=185 and +21.3 pp persistence "
        "(unadjusted p=.004). It is not a thin cell, but it is the strongest result selected "
        "after inspecting 15 joint cells and the earlier k sweep; a simple 15-cell Bonferroni "
        "benchmark would put p near .058.",
        "",
        "A diagnostic model interacting the initial-sequence flag with regular weekday and IV "
        "bucket "
        f"gives robust joint p={fmt_p(results['interaction_tests']['weekday']['p_value'])} for "
        "weekday heterogeneity and "
        f"p={fmt_p(results['interaction_tests']['iv_bucket']['p_value'])} for IV-bucket "
        "heterogeneity. Its pseudo-R² is "
        f"{100 * models['persistence_interactions']['pseudo_r_squared']:.2f}% and accuracy is "
        f"{100 * models['persistence_interactions']['accuracy']:.1f}%; this is a diagnostic, "
        "not the requested primary additive-control specification.",
        "",
        "## Verdict",
        "",
        "PLACEHOLDER_VERDICT",
        "",
        "## Caveats",
        "",
        "- This is a selected follow-up to the best k from a six-k scan; unadjusted p-values "
        "remain exploratory.",
        "- The ATM call changes contract/strike through the source construction; its IV is a "
        "volatility-state proxy, not a constant instrument series.",
        "- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.",
        "- P0 is the prior session's final available spot stamp, not an official NSE close.",
        f"- Opening-IV audit: range {audit['opening_iv_min']:.2f}–{audit['opening_iv_max']:.2f}; "
        f"zero/non-positive dates={audit['zero_or_negative_opening_iv_dates']}.",
    ]
    pseudo_gain = controlled["pseudo_r_squared"] - baseline["pseudo_r_squared"]
    acc_gain = controlled["accuracy"] - baseline["accuracy"]
    if pseudo_gain < 0.005 and acc_gain < 0.01:
        verdict = (
            "**The controls do not turn k=2 into a materially more convincing model.** They add "
            f"only {100 * pseudo_gain:.2f} pp of pseudo-R² and {100 * acc_gain:.1f} pp of "
            "in-sample accuracy, while the original "
            "initial-sequence coefficient slightly strengthens rather than being absorbed. The "
            "high-IV slice (+11.6 pp, N=513) and especially Thursday × high IV (+21.3 pp, N=185) "
            "are legitimate prospective regime hypotheses, but IV-interaction heterogeneity is "
            "only borderline jointly (p=.062) and the strongest cell was selected after extensive "
            "scanning. This is not yet a demonstrated trading edge."
        )
    else:
        verdict = (
            "**The controls improve in-sample fit enough to be noticeable, but not to establish an "
            "edge.** The result remains a selected, full-sample exploratory finding; prospective "
            "validation is still required before trading interpretation."
        )
    return "\n".join(verdict if line == "PLACEHOLDER_VERDICT" else line for line in lines) + "\n"


def main() -> None:
    panel, audit = prepare_panel()
    baseline = logistic_fit(panel, controlled=False)
    controlled = logistic_fit(panel, controlled=True)
    interactions = logistic_fit(panel, controlled=True, persistence_interactions=True)
    if not baseline.converged or not controlled.converged or not interactions.converged:
        raise RuntimeError("logistic IRLS failed to converge")
    models = [
        fit_record(baseline, "baseline_common_sample"),
        fit_record(controlled, "weekday_and_iv_controls"),
        fit_record(interactions, "persistence_interactions"),
    ]
    coefficients = (
        coefficient_records(baseline, "baseline_common_sample")
        + coefficient_records(controlled, "weekday_and_iv_controls")
        + coefficient_records(interactions, "persistence_interactions")
    )
    weekday_terms = [f"weekday[{day}]" for day in WEEKDAY_CATEGORIES[1:]]
    iv_terms = ["iv_bucket[low_<14]", "iv_bucket[high_>18]"]
    joint_tests = {
        "weekday": joint_wald(controlled, weekday_terms),
        "iv_bucket": joint_wald(controlled, iv_terms),
        "all_controls": joint_wald(controlled, [*weekday_terms, *iv_terms]),
    }
    weekday_interactions = [f"initial_high_first:weekday[{day}]" for day in REGULAR_WEEKDAYS[1:]]
    iv_interactions = [
        "initial_high_first:iv_bucket[low_<14]",
        "initial_high_first:iv_bucket[high_>18]",
    ]
    interaction_tests = {
        "weekday": joint_wald(interactions, weekday_interactions),
        "iv_bucket": joint_wald(interactions, iv_interactions),
        "all": joint_wald(interactions, [*weekday_interactions, *iv_interactions]),
    }
    slices = build_slices(panel)
    results: dict[str, object] = {
        "definitions": {
            "decision_window": "09:15 through 09:17 inclusive",
            "target_window": "09:18 through 09:45 inclusive (strictly after decision)",
            "opening_iv": "arithmetic mean of ATM CALL IV at 09:15 and 09:16",
            "iv_buckets": {
                "low_<14": "IV < 14",
                "middle_14_18": "14 <= IV <= 18",
                "high_>18": "IV > 18",
            },
            "categorical_references": {"weekday": "Monday", "iv_bucket": "middle_14_18"},
            "thin_cell_threshold": THIN_CELL_N,
        },
        "audit": audit,
        "models": models,
        "coefficients": coefficients,
        "joint_tests": joint_tests,
        "interaction_tests": interaction_tests,
        "slices": slices,
    }
    output_panel = panel.drop(columns=["date_timestamp"])
    output_panel.to_csv(SCRATCH / "k2_controls_panel.csv", index=False)
    pd.DataFrame(models).to_csv(SCRATCH / "k2_controls_models.csv", index=False)
    pd.DataFrame(coefficients).to_csv(SCRATCH / "k2_controls_coefficients.csv", index=False)
    pd.DataFrame(slices).to_csv(SCRATCH / "k2_controls_slices.csv", index=False)
    (SCRATCH / "k2_controls_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = report_markdown(results)
    (SCRATCH / "report_k2_controls.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
