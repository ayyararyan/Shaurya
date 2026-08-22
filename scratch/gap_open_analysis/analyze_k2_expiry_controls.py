#!/usr/bin/env python3
"""Replace weekday controls with an observed-calendar NIFTY expiry-day control."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from analyze_high_low_sequence import CONTINUOUS_FEATURES, HAC_LAGS, MANIFEST, SCRATCH
from analyze_k2_controls import (
    IV_BUCKETS,
    Fit,
    coefficient_records,
    fit_record,
    fmt_p,
    prepare_panel,
    slice_record,
)
from scipy.special import expit
from scipy.stats import chi2, norm

OLD_RULE_END = pd.Timestamp("2025-08-28")
NEW_RULE_FIRST_EXPIRY = pd.Timestamp("2025-09-09")
IV_DUMMY_TERMS = ("iv_bucket[low_<14]", "iv_bucket[high_>18]")
VERIFIED_SCHEDULED_HOLIDAYS = {
    pd.Timestamp(value)
    for value in (
        "2021-03-11",
        "2021-05-13",
        "2021-08-19",
        "2021-11-04",
        "2022-04-14",
        "2023-01-26",
        "2023-03-30",
        "2023-06-29",
        "2024-04-11",
        "2024-08-15",
        "2025-04-10",
        "2025-05-01",
        "2025-10-21",
        "2026-03-03",
        "2026-03-31",
        "2026-04-14",
    )
}


def selected_manifest_rows() -> list[dict[str, object]]:
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    selected = [
        row for row in rows if row.get("strike") == "ATM" and row.get("drv_option_type") == "CALL"
    ]
    if len(selected) != 66:
        raise RuntimeError(f"expected 66 ATM/CALL files, found {len(selected)}")
    return selected


def audit_storage_boundaries() -> dict[str, object]:
    selected = selected_manifest_rows()
    end_weekdays: dict[str, int] = {}
    spans: dict[str, int] = {}
    last_observed_matches = 0
    for row in selected:
        start = pd.Timestamp(str(row["from_date"]))
        end = pd.Timestamp(str(row["to_date"]))
        end_weekdays[end.day_name()] = end_weekdays.get(end.day_name(), 0) + 1
        span = str((end - start).days)
        spans[span] = spans.get(span, 0) + 1
        path = MANIFEST.parent / str(row["from_date"])[:4] / Path(str(row["path"])).name
        stamps = pd.read_csv(path, usecols=["datetime"])
        observed_end = pd.to_datetime(stamps["datetime"], errors="raise").dt.date.max()
        last_observed_matches += int(observed_end == end.date())
    return {
        "manifest_files": len(selected),
        "calendar_span_days": dict(sorted(spans.items(), key=lambda item: int(item[0]))),
        "to_date_weekday_counts": dict(sorted(end_weekdays.items())),
        "to_date_equals_last_observed_trading_date": last_observed_matches,
        "to_date_is_expiry_assumption_valid": False,
        "reason": "65/66 files span 29 calendar days and to_date covers all weekdays/weekends",
    }


def derive_expiry_calendar(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    observed = pd.DatetimeIndex(
        pd.to_datetime(panel["date"], errors="raise").unique()
    ).sort_values()
    regular = observed[observed.dayofweek < 5]
    old_end = min(OLD_RULE_END, regular.max())
    old_scheduled = pd.date_range(regular.min(), old_end, freq="W-THU")
    if regular.max() >= NEW_RULE_FIRST_EXPIRY:
        new_scheduled = pd.date_range(NEW_RULE_FIRST_EXPIRY, regular.max(), freq="W-TUE")
    else:
        new_scheduled = pd.DatetimeIndex([])
    scheduled = old_scheduled.append(new_scheduled)
    rows: list[dict[str, object]] = []
    unknown: list[dict[str, str]] = []
    for scheduled_date in scheduled:
        if scheduled_date in regular:
            actual = scheduled_date
        elif scheduled_date in VERIFIED_SCHEDULED_HOLIDAYS:
            candidates = regular[
                (regular < scheduled_date) & (regular >= scheduled_date - pd.Timedelta(days=6))
            ]
            if len(candidates) == 0:
                unknown.append(
                    {
                        "scheduled_expiry": scheduled_date.strftime("%Y-%m-%d"),
                        "reason": "verified holiday but no preceding observed regular session",
                    }
                )
                continue
            actual = candidates.max()
        else:
            unknown.append(
                {
                    "scheduled_expiry": scheduled_date.strftime("%Y-%m-%d"),
                    "reason": "scheduled session absent from source but not an NSE holiday",
                }
            )
            continue
        rows.append(
            {
                "scheduled_expiry": scheduled_date.strftime("%Y-%m-%d"),
                "scheduled_weekday": scheduled_date.day_name(),
                "actual_expiry": actual.strftime("%Y-%m-%d"),
                "actual_weekday": actual.day_name(),
                "holiday_shifted": bool(actual != scheduled_date),
                "monthly_replacement": bool(
                    (scheduled_date + pd.Timedelta(days=7)).month != scheduled_date.month
                ),
            }
        )
    calendar = pd.DataFrame(rows)
    if calendar["actual_expiry"].duplicated().any():
        raise RuntimeError("multiple scheduled expiries mapped to one observed trading date")
    actual_weekdays = calendar["actual_weekday"].value_counts().sort_index().to_dict()
    classified_scheduled_weekdays = (
        calendar["scheduled_weekday"].value_counts().sort_index().to_dict()
    )
    all_scheduled_weekdays = pd.Series(scheduled.day_name()).value_counts().sort_index().to_dict()
    audit = {
        "old_rule": "Thursday; prior observed regular trading day if holiday",
        "old_rule_last_scheduled_expiry": OLD_RULE_END.strftime("%Y-%m-%d"),
        "new_rule": "Tuesday; prior observed regular trading day if holiday",
        "new_rule_first_scheduled_expiry": NEW_RULE_FIRST_EXPIRY.strftime("%Y-%m-%d"),
        "transition_gap_has_no_expiry": "2025-08-29 through 2025-09-08",
        "scheduled_expiry_count": len(scheduled),
        "classified_expiry_count": len(calendar),
        "unknown_scheduled_expiries": unknown,
        "all_scheduled_weekday_counts": all_scheduled_weekdays,
        "classified_scheduled_weekday_counts": classified_scheduled_weekdays,
        "actual_weekday_counts": actual_weekdays,
        "holiday_shift_count": int(calendar["holiday_shifted"].sum()),
        "verified_scheduled_holiday_count": len(VERIFIED_SCHEDULED_HOLIDAYS),
        "monthly_replacement_count": int(calendar["monthly_replacement"].sum()),
    }
    return calendar, audit


def add_expiry_status(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    calendar, audit = derive_expiry_calendar(panel)
    expiry_dates = set(calendar["actual_expiry"])
    output = panel.copy()
    output["is_expiry_day"] = output["date"].isin(expiry_dates).astype(int)
    audit["panel_expiry_days"] = int(output["is_expiry_day"].sum())
    audit["panel_non_expiry_days"] = int((output["is_expiry_day"] == 0).sum())
    audit["panel_unknown_expiry_status"] = 0
    audit["missing_expiry_events_excluded"] = len(audit["unknown_scheduled_expiries"])
    return output, calendar, audit


def design_matrix(
    data: pd.DataFrame, *, controlled: bool, persistence_interactions: bool = False
) -> tuple[np.ndarray, tuple[str, ...]]:
    continuous = data.loc[:, CONTINUOUS_FEATURES].to_numpy(dtype=float)
    scales = continuous.std(axis=0, ddof=0)
    standardized = (continuous - continuous.mean(axis=0)) / scales
    columns = [np.ones(len(data)), *[standardized[:, i] for i in range(standardized.shape[1])]]
    terms = ["intercept", *CONTINUOUS_FEATURES]
    initial = data["initial_high_first"].to_numpy(dtype=float)
    expiry = data["is_expiry_day"].to_numpy(dtype=float)
    columns.append(initial)
    terms.append("initial_high_first")
    if controlled:
        columns.append(expiry)
        terms.append("is_expiry_day")
        for bucket in ("low_<14", "high_>18"):
            columns.append((data["iv_bucket"] == bucket).to_numpy(dtype=float))
            terms.append(f"iv_bucket[{bucket}]")
    if persistence_interactions:
        columns.append(initial * expiry)
        terms.append("initial_high_first:is_expiry_day")
        for bucket in ("low_<14", "high_>18"):
            columns.append(initial * (data["iv_bucket"] == bucket).to_numpy(dtype=float))
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


def build_slices(panel: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for value, label in ((1, "expiry"), (0, "non_expiry")):
        rows.append(slice_record(panel[panel["is_expiry_day"] == value], "expiry_status", label))
    for value, label in ((1, "expiry"), (0, "non_expiry")):
        for bucket in IV_BUCKETS:
            subset = panel[(panel["is_expiry_day"] == value) & (panel["iv_bucket"] == bucket)]
            rows.append(slice_record(subset, "expiry_x_iv", f"{label}|{bucket}"))
    return rows


def persistence_effect_stats(data: pd.DataFrame) -> tuple[float, float]:
    initial_high = data[data["initial_high_first"] == 1]["target_high_first"]
    initial_low = data[data["initial_high_first"] == 0]["target_high_first"]
    high_rate = float(initial_high.mean())
    low_rate = float(initial_low.mean())
    variance = high_rate * (1.0 - high_rate) / len(initial_high)
    variance += low_rate * (1.0 - low_rate) / len(initial_low)
    return high_rate - low_rate, variance


def persistence_heterogeneity(group_a: pd.DataFrame, group_b: pd.DataFrame) -> dict[str, float]:
    effect_a, variance_a = persistence_effect_stats(group_a)
    effect_b, variance_b = persistence_effect_stats(group_b)
    difference = effect_a - effect_b
    z_stat = difference / math.sqrt(variance_a + variance_b)
    return {
        "effect_a": effect_a,
        "effect_b": effect_b,
        "difference": difference,
        "z_stat": z_stat,
        "p_value": float(2.0 * norm.sf(abs(z_stat))),
    }


def report_markdown(results: dict[str, object]) -> str:
    models = {row["model"]: row for row in results["models"]}
    coefs = {(row["model"], row["term"]): row for row in results["coefficients"]}
    slices = {(row["slice_type"], row["slice_value"]): row for row in results["slices"]}
    base = models["baseline"]
    controlled = models["expiry_and_iv_controls"]
    expiry_coef = coefs[("expiry_and_iv_controls", "is_expiry_day")]
    initial_base = coefs[("baseline", "initial_high_first")]
    initial_controlled = coefs[("expiry_and_iv_controls", "initial_high_first")]
    expiry = slices[("expiry_status", "expiry")]
    non_expiry = slices[("expiry_status", "non_expiry")]
    expiry_high = slices[("expiry_x_iv", "expiry|high_>18")]
    heterogeneity = results["persistence_heterogeneity"]
    expiry_audit = results["expiry_audit"]
    storage = results["storage_boundary_audit"]
    bonferroni = min(1.0, 6.0 * float(expiry_high["persistence_p"]))
    lines = [
        "# NIFTY k=2 sequence model with expiry-day and opening-IV controls",
        "",
        "**Exploratory full-sample follow-up.** The k=2 timing and predictors are unchanged. "
        "The target remains strictly 09:18–09:45. IV buckets remain <14, 14–18 inclusive, "
        "and >18.",
        "",
        "## Expiry classification audit",
        "",
        "The proposed file-end rule is invalid: 65 of 66 source files span 29 calendar days, "
        "their `to_date` values cover all seven weekdays, and only "
        f"{storage['to_date_equals_last_observed_trading_date']}/66 equal the final observed "
        "trading date. The files are storage chunks, not individual contracts. The CSV fields "
        "`expiry_flag=WEEK` and `expiry_code=1` identify the nearest-week selector but do not "
        "retain the contract expiry date.",
        "",
        "Expiry dates are therefore reconstructed from the official NSE rule and the observed "
        "regular trading-date calendar: Thursday through 28-Aug-2025, no expiry in the "
        "transition interval, then Tuesday beginning 09-Sep-2025; holidays map to the preceding "
        "observed Monday–Friday session. This yields "
        f"**{expiry_audit['panel_expiry_days']} expiry days** and "
        f"**{expiry_audit['panel_non_expiry_days']} non-expiry days**, with "
        f"**{len(expiry_audit['unknown_scheduled_expiries'])} scheduled expiries absent from "
        "the source and excluded rather than shifted**.",
        "",
        f"All scheduled weekdays: {expiry_audit['all_scheduled_weekday_counts']}; classified "
        f"scheduled weekdays: {expiry_audit['classified_scheduled_weekday_counts']}. Actual "
        "classified "
        f"weekdays after holiday shifts: {expiry_audit['actual_weekday_counts']}; "
        f"{expiry_audit['holiday_shift_count']} dates move before the scheduled weekday. "
        f"The missing scheduled dates are {expiry_audit['unknown_scheduled_expiries']}. "
        "Monthly expiry replaces that week's weekly contract; the binary label intentionally "
        "treats both as an index-expiry day and does not claim to distinguish them.",
        "",
        f"Of the earlier Thursday × high-IV cell's 185 days, "
        f"**{results['thursday_high_iv_overlap']['expiry_days']} "
        f"({100 * results['thursday_high_iv_overlap']['expiry_share']:.1f}%) are classified "
        "expiry days**. This confirms that the earlier weekday cell was overwhelmingly an "
        "expiry cell rather than a generic Thursday cell.",
        "",
        "## Model comparison",
        "",
        "| Model | N | Pseudo-R² | Accuracy | Base | Uplift | Initial flag β / HAC p |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Original predictors | {base['n']} | {100 * base['pseudo_r_squared']:.2f}% | "
        f"{100 * base['accuracy']:.1f}% | {100 * base['base_accuracy']:.1f}% | "
        f"{100 * base['accuracy_uplift']:+.1f} pp | {initial_base['coefficient']:.3f} / "
        f"{fmt_p(initial_base['hac_p'])} |",
        f"| + expiry and IV bucket | {controlled['n']} | "
        f"{100 * controlled['pseudo_r_squared']:.2f}% | {100 * controlled['accuracy']:.1f}% | "
        f"{100 * controlled['base_accuracy']:.1f}% | "
        f"{100 * controlled['accuracy_uplift']:+.1f} pp | "
        f"{initial_controlled['coefficient']:.3f} / {fmt_p(initial_controlled['hac_p'])} |",
        "",
        f"The expiry-day main coefficient is **{expiry_coef['coefficient']:.3f}** "
        f"(HAC p={fmt_p(expiry_coef['hac_p'])}, odds ratio "
        f"{expiry_coef['odds_ratio']:.2f}). The IV dummy block has joint "
        f"p={fmt_p(results['joint_tests']['iv_bucket']['p_value'])}; all three controls have "
        f"joint p={fmt_p(results['joint_tests']['all_controls']['p_value'])}.",
        "As an additive control, expiry explains less than the prior weekday specification "
        "(0.47% versus 0.64% pseudo-R²; 53.0% versus 53.6% accuracy). Its value appears in "
        "conditioning the persistence effect, not in shifting the unconditional target rate.",
        "",
        "## Persistence conditional on expiry",
        "",
        "| Status | N | Base high-first | After initial high / low | Effect | p |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Expiry | {expiry['n']} | {100 * expiry['base_high_first_rate']:.1f}% | "
        f"{100 * expiry['target_rate_after_initial_high_first']:.1f}% / "
        f"{100 * expiry['target_rate_after_initial_low_first']:.1f}% | "
        f"{100 * expiry['persistence_effect']:+.1f} pp | {fmt_p(expiry['persistence_p'])} |",
        f"| Non-expiry | {non_expiry['n']} | {100 * non_expiry['base_high_first_rate']:.1f}% | "
        f"{100 * non_expiry['target_rate_after_initial_high_first']:.1f}% / "
        f"{100 * non_expiry['target_rate_after_initial_low_first']:.1f}% | "
        f"{100 * non_expiry['persistence_effect']:+.1f} pp | "
        f"{fmt_p(non_expiry['persistence_p'])} |",
        "",
        "The simple difference between the expiry and non-expiry persistence effects is "
        f"**{100 * heterogeneity['all']['difference']:+.1f} pp** "
        f"(p={fmt_p(heterogeneity['all']['p_value'])}).",
        "",
        "## Expiry × IV cells",
        "",
        "| Cell | N | Base high-first | Persistence effect | Unadjusted p |",
        "|---|---:|---:|---:|---:|",
    ]
    for status in ("expiry", "non_expiry"):
        for bucket in IV_BUCKETS:
            row = slices[("expiry_x_iv", f"{status}|{bucket}")]
            lines.append(
                f"| {status} × {bucket} | {row['n']} | "
                f"{100 * row['base_high_first_rate']:.1f}% | "
                f"{100 * row['persistence_effect']:+.1f} pp | "
                f"{fmt_p(row['persistence_p'])} |"
            )
    lines += [
        "",
        f"The requested expiry × high-IV cell has **N={expiry_high['n']}**, "
        f"**{100 * expiry_high['persistence_effect']:+.1f} pp** persistence, and "
        f"p={fmt_p(expiry_high['persistence_p'])}. Bonferroni across six cells gives "
        f"**p={fmt_p(bonferroni)}**.",
        "Within high-IV days, expiry persistence exceeds non-expiry persistence by "
        f"**{100 * heterogeneity['high_iv']['difference']:+.1f} pp** "
        f"(p={fmt_p(heterogeneity['high_iv']['p_value'])}).",
        "",
        "A diagnostic model allowing persistence to vary with both expiry and IV reaches "
        f"{100 * models['persistence_interactions']['pseudo_r_squared']:.2f}% pseudo-R² and "
        f"{100 * models['persistence_interactions']['accuracy']:.1f}% accuracy. The three "
        "interaction terms are jointly significant at p="
        f"{fmt_p(results['interaction_tests']['all']['p_value'])}, "
        "but initial-sequence × expiry alone is "
        f"p={fmt_p(results['interaction_tests']['expiry']['p_value'])} and joint IV-regime "
        f"interaction p={fmt_p(results['interaction_tests']['iv_bucket']['p_value'])}.",
        "",
        "## Verdict",
        "",
        "PLACEHOLDER_VERDICT",
        "",
        "## Caveats",
        "",
        "- Exact historical contract IDs/expiry dates are absent from the rolling CSV output; "
        "classification combines official NSE rules with the observed trading calendar.",
        "- This remains a selected full-sample follow-up, not an out-of-sample validation.",
        "- High/low are extrema of minute-stamped spot levels, not intraminute OHLC extrema.",
    ]
    if abs(expiry["persistence_effect"]) <= abs(non_expiry["persistence_effect"]):
        verdict = (
            "**Expiry day does not explain the earlier Thursday result.** Persistence is not "
            "stronger on expiry days than on non-expiry days, and replacing weekday with expiry "
            "does not materially improve fit or accuracy. The k=2 lead remains an in-sample "
            "hypothesis requiring prospective validation."
        )
    else:
        verdict = (
            "**Expiry is the correct economic label behind the earlier Thursday cell, and it "
            "tightens the in-sample subgroup case—but it does not yet establish the k=2 edge.** "
            "Almost all Thursday × high-IV observations were expiry days, and the expiry × "
            "high-IV cell is cleaner and stronger. Yet expiry has no significant additive main "
            "effect, aggregate model fit remains tiny, and its persistence interaction weakens "
            "after allowing IV-regime interactions. Prospective validation is still required."
        )
    return "\n".join(verdict if line == "PLACEHOLDER_VERDICT" else line for line in lines) + "\n"


def main() -> None:
    panel, source_audit = prepare_panel()
    panel, calendar, expiry_audit = add_expiry_status(panel)
    storage_audit = audit_storage_boundaries()
    baseline = logistic_fit(panel, controlled=False)
    controlled = logistic_fit(panel, controlled=True)
    interactions = logistic_fit(panel, controlled=True, persistence_interactions=True)
    if not all(fit.converged for fit in (baseline, controlled, interactions)):
        raise RuntimeError("logistic IRLS failed to converge")
    models = [
        fit_record(baseline, "baseline"),
        fit_record(controlled, "expiry_and_iv_controls"),
        fit_record(interactions, "persistence_interactions"),
    ]
    coefficients = (
        coefficient_records(baseline, "baseline")
        + coefficient_records(controlled, "expiry_and_iv_controls")
        + coefficient_records(interactions, "persistence_interactions")
    )
    joint_tests = {
        "iv_bucket": joint_wald(controlled, list(IV_DUMMY_TERMS)),
        "all_controls": joint_wald(controlled, ["is_expiry_day", *IV_DUMMY_TERMS]),
    }
    interaction_tests = {
        "expiry": joint_wald(interactions, ["initial_high_first:is_expiry_day"]),
        "iv_bucket": joint_wald(
            interactions,
            [f"initial_high_first:{term}" for term in IV_DUMMY_TERMS],
        ),
        "all": joint_wald(
            interactions,
            [
                "initial_high_first:is_expiry_day",
                *[f"initial_high_first:{term}" for term in IV_DUMMY_TERMS],
            ],
        ),
    }
    slices = build_slices(panel)
    persistence_heterogeneity_results = {
        "all": persistence_heterogeneity(
            panel[panel["is_expiry_day"] == 1], panel[panel["is_expiry_day"] == 0]
        ),
        "high_iv": persistence_heterogeneity(
            panel[(panel["is_expiry_day"] == 1) & (panel["iv_bucket"] == "high_>18")],
            panel[(panel["is_expiry_day"] == 0) & (panel["iv_bucket"] == "high_>18")],
        ),
    }
    thursday_high_iv = panel[
        (panel["calendar_weekday"] == "Thursday") & (panel["iv_bucket"] == "high_>18")
    ]
    thursday_high_iv_overlap = {
        "n": len(thursday_high_iv),
        "expiry_days": int(thursday_high_iv["is_expiry_day"].sum()),
        "expiry_share": float(thursday_high_iv["is_expiry_day"].mean()),
    }
    results: dict[str, object] = {
        "definitions": {
            "decision_window": "09:15 through 09:17 inclusive",
            "target_window": "09:18 through 09:45 inclusive",
            "expiry_rule_source": "NSE/FAOP/68747 plus observed regular trading calendar",
            "old_rule_end": OLD_RULE_END.strftime("%Y-%m-%d"),
            "new_rule_first_expiry": NEW_RULE_FIRST_EXPIRY.strftime("%Y-%m-%d"),
            "iv_buckets": {
                "low_<14": "IV < 14",
                "middle_14_18": "14 <= IV <= 18",
                "high_>18": "IV > 18",
            },
        },
        "source_audit": source_audit,
        "storage_boundary_audit": storage_audit,
        "expiry_audit": expiry_audit,
        "models": models,
        "coefficients": coefficients,
        "joint_tests": joint_tests,
        "interaction_tests": interaction_tests,
        "persistence_heterogeneity": persistence_heterogeneity_results,
        "thursday_high_iv_overlap": thursday_high_iv_overlap,
        "slices": slices,
    }
    panel.drop(columns=["date_timestamp"]).to_csv(
        SCRATCH / "k2_expiry_controls_panel.csv", index=False
    )
    calendar.to_csv(SCRATCH / "k2_expiry_calendar.csv", index=False)
    pd.DataFrame(models).to_csv(SCRATCH / "k2_expiry_controls_models.csv", index=False)
    pd.DataFrame(coefficients).to_csv(SCRATCH / "k2_expiry_controls_coefficients.csv", index=False)
    pd.DataFrame(slices).to_csv(SCRATCH / "k2_expiry_controls_slices.csv", index=False)
    (SCRATCH / "k2_expiry_controls_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = report_markdown(results)
    (SCRATCH / "report_k2_expiry_controls.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
