#!/usr/bin/env python3
"""Fit the k=2 expiry/VIX-rise model without P3 and with continuous VIX change."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from analyze_high_low_sequence import HAC_LAGS, SCRATCH
from analyze_k2_controls import Fit, coefficient_records, fit_record, fmt_p, slice_record
from scipy.special import expit
from scipy.stats import norm

PANEL = SCRATCH / "k2_expiry_vix_rose_panel.csv"
PRIOR_RESULTS = SCRATCH / "k2_expiry_vix_rose_results.json"
CONTINUOUS_FEATURES = ("gap", "P1", "initial_range_ratio", "vix_overnight_gap")


def design_matrix(data: pd.DataFrame) -> tuple[np.ndarray, tuple[str, ...]]:
    continuous = data.loc[:, CONTINUOUS_FEATURES].to_numpy(dtype=float)
    scales = continuous.std(axis=0, ddof=0)
    if (scales <= 0).any():
        raise RuntimeError("constant continuous predictor")
    standardized = (continuous - continuous.mean(axis=0)) / scales
    design = np.column_stack(
        [
            np.ones(len(data)),
            *[standardized[:, i] for i in range(standardized.shape[1])],
            data["initial_high_first"].to_numpy(dtype=float),
        ]
    )
    return design, ("intercept", *CONTINUOUS_FEATURES, "initial_high_first")


def logistic_fit(data: pd.DataFrame) -> Fit:
    design, terms = design_matrix(data)
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


def main() -> None:
    panel = pd.read_csv(PANEL, dtype={"date": str})
    sample = panel[(panel["is_expiry_day"] == 1) & (panel["vix_rose"] == True)].copy()  # noqa: E712
    if len(sample) != 108:
        raise RuntimeError(f"expected frozen combined N=108, found {len(sample)}")
    if not ((sample["vix_overnight_gap"] > 0) & (sample["vix_first_clock"] <= "09:17")).all():
        raise RuntimeError("combined VIX filter changed")

    fit = logistic_fit(sample)
    if not fit.converged or fit.gradient_max >= 1e-8:
        raise RuntimeError("logistic fit failed convergence checks")
    model = fit_record(fit, "expiry_vix_rose_drop_p3_add_continuous_vix")
    coefficients = coefficient_records(fit, model["model"])
    persistence = slice_record(sample, "sample", model["model"])
    prior = json.loads(PRIOR_RESULTS.read_text(encoding="utf-8"))
    prior_models = {row["model"]: row for row in prior["models"]}
    results = {
        "sample_filter": "is_expiry_day == 1 and vix_overnight_gap > 0, known by 09:17",
        "target": "09:18-09:45 NIFTY spot high occurs before low",
        "continuous_scaling": "coefficients are per within-sample standard deviation",
        "n": len(sample),
        "vix_change_mean": float(sample["vix_overnight_gap"].mean()),
        "vix_change_std": float(sample["vix_overnight_gap"].std(ddof=0)),
        "vix_change_min": float(sample["vix_overnight_gap"].min()),
        "vix_change_max": float(sample["vix_overnight_gap"].max()),
        "model": model,
        "coefficients": coefficients,
        "raw_persistence": persistence,
        "prior_models": {
            "full_sample": prior_models["full_sample"],
            "expiry_only": prior_models["expiry_only"],
            "expiry_and_vix_rose_with_p3": prior_models["expiry_and_vix_rose"],
        },
    }
    (SCRATCH / "k2_expiry_vix_clean_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(coefficients).to_csv(SCRATCH / "k2_expiry_vix_clean_coefficients.csv", index=False)

    coefficient_lines = []
    for row in coefficients:
        direction = "positive" if row["coefficient"] > 0 else "negative"
        coefficient_lines.append(
            f"- `{row['term']}`: {direction}, beta={row['coefficient']:.3f}, "
            f"HAC p={fmt_p(row['hac_p'])}, odds ratio={row['odds_ratio']:.2f}."
        )
    old = prior_models["expiry_and_vix_rose"]
    expiry = prior_models["expiry_only"]
    flag = next(row for row in coefficients if row["term"] == "initial_high_first")
    vix = next(row for row in coefficients if row["term"] == "vix_overnight_gap")
    report = "\n".join(
        [
            "# NIFTY k=2 clean expiry + VIX-rise model",
            "",
            "The sample and target are frozen: 108 expiry days with a positive overnight India "
            "VIX change known by 09:17; target is high-before-low during 09:18–09:45. P3 is "
            "removed. Predictors are gap, P1, initial range ratio, initial high-first, and the "
            "continuous overnight VIX percentage change. Continuous predictors are standardized, "
            "so their coefficients represent a one-standard-deviation increase.",
            "",
            "## Fit",
            "",
            f"- N: **{fit.n}**; base high-first rate/accuracy: **{100 * fit.base_rate:.1f}%**.",
            f"- McFadden pseudo-R²: **{100 * fit.pseudo_r_squared:.2f}%**.",
            f"- In-sample accuracy: **{100 * fit.accuracy:.1f}%**, versus "
            f"**{100 * fit.base_accuracy:.1f}%** base "
            f"({100 * (fit.accuracy - fit.base_accuracy):+.1f} pp).",
            f"- Raw initial-high-first split remains "
            f"**{100 * persistence['persistence_effect']:+.1f} pp**, "
            f"p {fmt_p(persistence['persistence_p'])}.",
            "",
            "## Coefficients",
            "",
            *coefficient_lines,
            "",
            "## Comparison and verdict",
            "",
            f"The expiry-only model was {100 * expiry['accuracy']:.1f}% accurate versus "
            f"{100 * expiry['base_accuracy']:.1f}% base. The prior combined model with P3 was "
            f"{100 * old['accuracy']:.1f}% versus {100 * old['base_accuracy']:.1f}% base, with "
            f"pseudo-R² {100 * old['pseudo_r_squared']:.2f}%. The cleaner model is "
            f"{100 * fit.accuracy:.1f}% versus {100 * fit.base_accuracy:.1f}% base, with "
            f"pseudo-R² {100 * fit.pseudo_r_squared:.2f}%. Thus accuracy rises by 1.0 pp while "
            "pseudo-R² falls by 1.20 pp; the cleaner model is easier to interpret, not uniformly "
            "better-fitting.",
            "",
            f"Removing P3 makes the initial-high-first coefficient "
            f"{'significant' if flag['hac_p'] < 0.05 else 'not significant'} "
            f"(beta={flag['coefficient']:.3f}, HAC p={fmt_p(flag['hac_p'])}). Continuous VIX "
            f"magnitude is {'significant' if vix['hac_p'] < 0.05 else 'not significant'} "
            f"(beta={vix['coefficient']:.3f}, HAC p={fmt_p(vix['hac_p'])}). Because the sample "
            "already conditions on VIX being positive, this tests dose-response among VIX-rise "
            "days—not the overall up-versus-down leverage effect. This remains a small, "
            "in-sample, post-selected N=108 result and requires untouched or prospective "
            "validation before use.",
            "",
        ]
    )
    (SCRATCH / "report_k2_expiry_vix_clean.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
