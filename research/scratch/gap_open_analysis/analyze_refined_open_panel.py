#!/usr/bin/env python3
"""Refined, non-overlapping NIFTY open-feature/next-window analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr, ttest_1samp
from scipy.stats import t as student_t

SCRATCH = Path(__file__).resolve().parent
MANIFEST = Path(
    "/Users/maheit/.cache/openclaw/gdrive/My Drive/Dhandho/strategy/Still_Water/"
    "data/options/dhan_fresh_2021_2026/options/manifest.jsonl"
)
K_VALUES = (5, 10, 20, 30)
FEATURES = ("P1", "gap", "P2", "P3")
MODEL_TARGETS = ("T_ret", "T_range_magnitude")
HAC_LAGS = 5


@dataclass(frozen=True)
class FittedOLS:
    features: tuple[str, ...]
    target: str
    x_mean: np.ndarray
    x_scale: np.ndarray
    y_mean: float
    y_scale: float
    beta: np.ndarray
    robust_se: np.ndarray
    t_stat: np.ndarray
    p_value: np.ndarray
    r_squared: float
    n: int

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        x = frame.loc[:, self.features].to_numpy(dtype=float)
        standardized = (x - self.x_mean) / self.x_scale
        design = np.column_stack([np.ones(len(frame)), standardized])
        return (design @ self.beta) * self.y_scale + self.y_mean


def load_spot() -> tuple[pd.DataFrame, dict[str, object]]:
    manifest_rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    selected = [
        row
        for row in manifest_rows
        if row.get("strike") == "ATM" and row.get("drv_option_type") == "CALL"
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
    if spot["spot"].isna().any() or (spot["spot"] <= 0).any():
        raise RuntimeError("spot contains missing or non-positive values")
    audit = {
        "source_files": len(selected),
        "rows": len(spot),
        "manifest_row_mismatches": mismatches,
        "duplicate_timestamps": int(spot.duplicated("datetime").sum()),
        "unique_dates": int(spot["date"].nunique()),
        "first_timestamp": spot["datetime"].min().isoformat(),
        "last_timestamp": spot["datetime"].max().isoformat(),
    }
    return spot, audit


def clock_at(minutes_after_0915: int) -> str:
    start = pd.Timestamp("2000-01-01 09:15")
    return (start + pd.Timedelta(minutes=minutes_after_0915)).strftime("%H:%M")


def build_level_panel(spot: pd.DataFrame) -> pd.DataFrame:
    clocks = pd.date_range("2000-01-01 09:15", "2000-01-01 09:55", freq="min").strftime("%H:%M")
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


def build_feature_panels(
    spot: pd.DataFrame, levels: pd.DataFrame, audit: dict[str, object]
) -> dict[int, pd.DataFrame]:
    # Files and rows are chronological; the final stamp is the best available daily-close proxy.
    daily_close = spot.drop_duplicates("date", keep="last").set_index("date")["spot"].sort_index()
    p0 = daily_close.shift(1)
    p1 = daily_close.shift(1) / daily_close.shift(2) - 1.0
    panels: dict[int, pd.DataFrame] = {}
    for k in K_VALUES:
        p3_end = clock_at(k)
        target_end = clock_at(k + 10)
        target_clocks = (
            pd.date_range(f"2000-01-01 {p3_end}", f"2000-01-01 {target_end}", freq="min")
            .strftime("%H:%M")
            .tolist()
        )
        required = list(dict.fromkeys(["09:15", "09:16", p3_end, target_end, *target_clocks]))
        frame = levels.dropna(subset=required).copy()
        frame["P0_close"] = p0.reindex(frame.index)
        frame["P1"] = p1.reindex(frame.index)
        frame["gap"] = frame["09:15"] / frame["P0_close"] - 1.0
        frame["P2"] = frame["09:16"] / frame["09:15"] - 1.0
        frame["P3"] = frame[p3_end] / frame["09:16"] - 1.0
        frame["T_ret"] = frame[target_end] / frame[p3_end] - 1.0
        frame["T_high"] = frame[target_clocks].max(axis=1)
        frame["T_low"] = frame[target_clocks].min(axis=1)
        frame["T_range_ratio"] = frame["T_high"] / frame["T_low"]
        frame["T_range_magnitude"] = (frame["T_range_ratio"] - 1.0).abs()
        frame["k"] = k
        frame["P3_end"] = p3_end
        frame["target_end"] = target_end
        frame = frame.dropna(subset=[*FEATURES, *MODEL_TARGETS])
        panels[k] = frame
    audit["panel_counts"] = {str(k): len(panel) for k, panel in panels.items()}
    audit["panel_date_ranges"] = {
        str(k): [panel.index.min(), panel.index.max()] for k, panel in panels.items()
    }
    return panels


def marginal(
    data: pd.DataFrame, predictor: str, target: str, *, k: int, sample: str
) -> dict[str, object]:
    pair = data[[predictor, target]].dropna()
    pearson = pearsonr(pair[predictor], pair[target])
    spearman = spearmanr(pair[predictor], pair[target])
    return {
        "k": k,
        "sample": sample,
        "predictor": predictor,
        "target": target,
        "n": len(pair),
        "pearson_r": float(pearson.statistic),
        "pearson_p": float(pearson.pvalue),
        "spearman_rho": float(spearman.statistic),
        "spearman_p": float(spearman.pvalue),
    }


def fit_standardized_ols(
    data: pd.DataFrame,
    target: str,
    *,
    features: tuple[str, ...] = FEATURES,
    hac_lags: int = HAC_LAGS,
) -> FittedOLS:
    clean = data.loc[:, [*features, target]].dropna()
    x = clean.loc[:, features].to_numpy(dtype=float)
    y = clean[target].to_numpy(dtype=float)
    x_mean = x.mean(axis=0)
    x_scale = x.std(axis=0, ddof=0)
    y_mean = float(y.mean())
    y_scale = float(y.std(ddof=0))
    if np.any(x_scale <= 0) or y_scale <= 0:
        raise RuntimeError("OLS received a zero-variance feature or target")
    z_x = (x - x_mean) / x_scale
    z_y = (y - y_mean) / y_scale
    design = np.column_stack([np.ones(len(clean)), z_x])
    xtx_inv = np.linalg.pinv(design.T @ design)
    beta = xtx_inv @ design.T @ z_y
    residual = z_y - design @ beta

    # Newey-West/Bartlett HAC covariance on chronologically ordered daily observations.
    meat = np.zeros((design.shape[1], design.shape[1]))
    for index in range(len(clean)):
        meat += residual[index] ** 2 * np.outer(design[index], design[index])
    for lag in range(1, hac_lags + 1):
        gamma = np.zeros_like(meat)
        weight = 1.0 - lag / (hac_lags + 1)
        for index in range(lag, len(clean)):
            gamma += (
                residual[index]
                * residual[index - lag]
                * np.outer(design[index], design[index - lag])
            )
        meat += weight * (gamma + gamma.T)
    covariance = xtx_inv @ meat @ xtx_inv
    robust_se = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    t_stat = beta / robust_se
    degrees_freedom = len(clean) - design.shape[1]
    p_value = 2.0 * student_t.sf(np.abs(t_stat), degrees_freedom)
    fitted = (design @ beta) * y_scale + y_mean
    r_squared = 1.0 - float(np.sum((y - fitted) ** 2) / np.sum((y - y.mean()) ** 2))
    return FittedOLS(
        features,
        target,
        x_mean,
        x_scale,
        y_mean,
        y_scale,
        beta,
        robust_se,
        t_stat,
        p_value,
        r_squared,
        len(clean),
    )


def ols_rows(model: FittedOLS, *, k: int, sample: str, partition: str) -> list[dict[str, object]]:
    terms = ("intercept", *model.features)
    return [
        {
            "k": k,
            "sample": sample,
            "partition": partition,
            "target": model.target,
            "n": model.n,
            "r_squared": model.r_squared,
            "term": term,
            "standardized_beta": float(model.beta[index]),
            "hac_se": float(model.robust_se[index]),
            "hac_t": float(model.t_stat[index]),
            "hac_p": float(model.p_value[index]),
        }
        for index, term in enumerate(terms)
    ]


def chronological_validation(
    data: pd.DataFrame, target: str, *, k: int, sample: str
) -> tuple[dict[str, object], FittedOLS]:
    split = int(0.70 * len(data))
    train = data.iloc[:split]
    test = data.iloc[split:]
    model = fit_standardized_ols(train, target)
    prediction = model.predict(test)
    actual = test[target].to_numpy(dtype=float)
    denominator = np.sum((actual - model.y_mean) ** 2)
    oos_r_squared = 1.0 - float(np.sum((actual - prediction) ** 2) / denominator)
    pearson = pearsonr(prediction, actual)
    spearman = spearmanr(prediction, actual)
    if target == "T_ret":
        nonzero = (prediction != 0) & (actual != 0)
        direction_hit = float(np.mean(np.sign(prediction[nonzero]) == np.sign(actual[nonzero])))
    else:
        direction_hit = None
    return (
        {
            "k": k,
            "sample": sample,
            "target": target,
            "train_n": len(train),
            "test_n": len(test),
            "train_first_date": train.index.min(),
            "train_last_date": train.index.max(),
            "test_first_date": test.index.min(),
            "test_last_date": test.index.max(),
            "train_r_squared": model.r_squared,
            "oos_r_squared_vs_train_mean": oos_r_squared,
            "oos_pearson_r": float(pearson.statistic),
            "oos_pearson_p": float(pearson.pvalue),
            "oos_spearman_rho": float(spearman.statistic),
            "oos_spearman_p": float(spearman.pvalue),
            "oos_direction_hit": direction_hit,
            "train_target_mean": model.y_mean,
            "test_target_mean": float(actual.mean()),
            "prediction_mean": float(prediction.mean()),
        },
        model,
    )


def bucket_rows(data: pd.DataFrame, *, k: int, sample: str) -> tuple[list[dict[str, object]], int]:
    nonzero = data[(data["P1"] != 0) & (data["P2"] != 0) & (data["P3"] != 0)].copy()
    excluded = len(data) - len(nonzero)
    nonzero["bucket"] = [
        "".join("+" if value > 0 else "-" for value in row)
        for row in nonzero.loc[:, ["P1", "P2", "P3"]].to_numpy(dtype=float)
    ]
    rows: list[dict[str, object]] = []
    for bucket in ("---", "--+", "-+-", "-++", "+--", "+-+", "++-", "+++"):
        subset = nonzero[nonzero["bucket"] == bucket]
        majority_sign = 1 if bucket.count("+") >= 2 else -1
        target = subset["T_ret"]
        directional = target[target != 0]
        test = ttest_1samp(target, popmean=0.0) if len(target) >= 2 else None
        rows.append(
            {
                "k": k,
                "sample": sample,
                "bucket_P1_P2_P3": bucket,
                "majority_sign": "+" if majority_sign > 0 else "-",
                "n": len(subset),
                "mean_T_ret": float(target.mean()) if len(target) else None,
                "mean_T_ret_bps": float(target.mean() * 10_000) if len(target) else None,
                "mean_t_p": float(test.pvalue) if test is not None else None,
                "majority_sign_consistency": (
                    float(np.mean(np.sign(directional) == majority_sign))
                    if len(directional)
                    else None
                ),
            }
        )
    return rows, excluded


def p_fmt(value: float) -> str:
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def rp(row: dict[str, object], prefix: str) -> str:
    return f"{row[prefix]:.3f} ({p_fmt(float(row[prefix.replace('r', 'p')]))})"


def report_markdown(results: dict[str, object]) -> str:
    audit = results["audit"]
    marginals = results["marginals"]
    ols = results["ols"]
    oos = results["oos"]
    buckets = results["buckets"]
    tail = results["tail_cutoffs"]

    marginal_lookup = {
        (row["k"], row["sample"], row["predictor"], row["target"]): row for row in marginals
    }
    oos_lookup = {(row["k"], row["sample"], row["target"]): row for row in oos}
    full_ols_r2: dict[tuple[int, str, str], float] = {}
    coefficients: dict[tuple[int, str, str, str], dict[str, object]] = {}
    for row in ols:
        if row["partition"] == "full_sample":
            full_ols_r2[(row["k"], row["sample"], row["target"])] = row["r_squared"]
            coefficients[(row["k"], row["sample"], row["target"], row["term"])] = row

    lines = [
        "# Refined NIFTY opening-state → next-10-minute panel",
        "",
        "**Exploratory, non-overlapping design.** All predictors are known at the target-window "
        "boundary. The source is the already-staged Still_Water Dhan-derived NIFTY `spot` series; "
        "no API or order path was used.",
        "",
        "## Design and sample",
        "",
        f"The source has {audit['rows']:,} minute stamps from {audit['first_timestamp']} through "
        f"{audit['last_timestamp']}. Each k panel has **1,318 days** after requiring two prior "
        "daily closes and all intraday endpoints.",
        "",
        "- `P1`: yesterday's final spot / day-before-yesterday's final spot − 1.",
        "- `gap`: today's 09:15 spot / yesterday's final spot − 1; `P0_close` is retained in "
        "the panel as context.",
        "- `P2`: 09:15→09:16 return. `P3`: 09:16→09:(15+k) return.",
        "- Target: the strictly subsequent 10-minute close-to-close return. Range uses the "
        "maximum/minimum of the 11 stamped boundary levels from target start through target end. "
        "Because `T_range_ratio-1` is an affine transform of the ratio, its correlations, "
        "standardized betas and R² are identical.",
        "- OLS variables are standardized; coefficient p-values use Newey-West HAC(5). The "
        "70/30 split is chronological and OOS R² uses the training target mean as baseline.",
        "",
        "## Marginal correlations — full sample",
        "",
        "| k | Predictor | T_ret Pearson (p) | T_ret Spearman (p) | "
        "T_range Pearson (p) | T_range Spearman (p) |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        for predictor in FEATURES:
            ret = marginal_lookup[(k, "full", predictor, "T_ret")]
            ran = marginal_lookup[(k, "full", predictor, "T_range_ratio")]
            lines.append(
                f"| {k} | {predictor} | {ret['pearson_r']:.3f} ({p_fmt(ret['pearson_p'])}) | "
                f"{ret['spearman_rho']:.3f} ({p_fmt(ret['spearman_p'])}) | "
                f"{ran['pearson_r']:.3f} ({p_fmt(ran['pearson_p'])}) | "
                f"{ran['spearman_rho']:.3f} ({p_fmt(ran['spearman_p'])}) |"
            )

    lines += [
        "",
        "Return marginals are small and inconsistent. Range magnitude is more systematic: "
        "negative P1, gap and P3 tend to precede larger next-window ranges, while P2 contributes "
        "little on its own.",
        "",
        "## Multivariate and chronological validation",
        "",
        "| k | Target | Full R² | Train-70% R² | OOS R² | OOS Pearson (p) | "
        "OOS Spearman (p) | OOS direction hit |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        for target in MODEL_TARGETS:
            row = oos_lookup[(k, "full", target)]
            hit = (
                "—"
                if row["oos_direction_hit"] is None
                else f"{100 * row['oos_direction_hit']:.1f}%"
            )
            lines.append(
                f"| {k} | {target} | {100 * full_ols_r2[(k, 'full', target)]:.2f}% | "
                f"{100 * row['train_r_squared']:.2f}% | "
                f"{100 * row['oos_r_squared_vs_train_mean']:.2f}% | "
                f"{row['oos_pearson_r']:.3f} ({p_fmt(row['oos_pearson_p'])}) | "
                f"{row['oos_spearman_rho']:.3f} ({p_fmt(row['oos_spearman_p'])}) | {hit} |"
            )

    lines += [
        "",
        "All four return models fail calibrated OOS validation: OOS R² is negative and "
        "direction hit is only 42.8–51.3%. Range predictions retain positive OOS ranking "
        "correlations at every k, but calibrated OOS R² is weak: only k=10 is slightly positive.",
        "",
        "## Full-sample standardized OLS coefficients",
        "",
        "Each cell is beta / HAC t / p.",
        "",
        "| k | Target | P1 | gap | P2 | P3 |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        for target in MODEL_TARGETS:
            cells: list[str] = []
            for feature in FEATURES:
                row = coefficients[(k, "full", target, feature)]
                cells.append(
                    f"{row['standardized_beta']:.3f} / {row['hac_t']:.2f} / {p_fmt(row['hac_p'])}"
                )
            lines.append(f"| {k} | {target} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Top-1% |T_ret| exclusion",
        "",
        "The cutoff is descriptive and computed within each full k panel; 14 of 1,318 days "
        "are removed. This prevents election/crash days from dominating, but the trimmed OOS "
        "figures are not a deployable ex-ante filter because future target size is unknowable.",
        "",
        "| k | cutoff | Return full/OOS R², OOS corr/hit | "
        "Range full/OOS R², OOS Pearson/Spearman |",
        "|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        ret = oos_lookup[(k, "trimmed", "T_ret")]
        ran = oos_lookup[(k, "trimmed", "T_range_magnitude")]
        lines.append(
            f"| {k} | {tail[str(k)]['abs_T_ret_99pct'] * 10_000:.2f} bp | "
            f"{100 * full_ols_r2[(k, 'trimmed', 'T_ret')]:.2f}% / "
            f"{100 * ret['oos_r_squared_vs_train_mean']:.2f}%, "
            f"{ret['oos_pearson_r']:.3f}/{100 * ret['oos_direction_hit']:.1f}% | "
            f"{100 * full_ols_r2[(k, 'trimmed', 'T_range_magnitude')]:.2f}% / "
            f"{100 * ran['oos_r_squared_vs_train_mean']:.2f}%, "
            f"{ran['oos_pearson_r']:.3f}/{ran['oos_spearman_rho']:.3f} |"
        )

    lines += [
        "",
        "After tail removal, return R² falls to 0.3–0.7%. Range full-sample R² remains "
        "5.6–6.0%. The k=10/20/30 trimmed range models retain small positive OOS R² "
        "(1.06%, 0.65%, 2.20%) and OOS Pearson correlations of 0.162, 0.133 and 0.175; "
        "k=5's Pearson ranking does not survive trimming.",
        "",
        "## Sign-interaction buckets",
        "",
        "Bucket order is sign(P1), sign(P2), sign(P3). Consistency compares T_ret with the "
        "three-sign majority. Exact-zero predictors are excluded from this eight-bucket view.",
        "",
        "| k | Bucket | N | Mean T_ret (bp) | Mean p | Majority consistency | "
        "Trimmed N / mean (bp) / consistency |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    bucket_lookup = {(row["k"], row["sample"], row["bucket_P1_P2_P3"]): row for row in buckets}
    for k in K_VALUES:
        for bucket in ("---", "--+", "-+-", "-++", "+--", "+-+", "++-", "+++"):
            full = bucket_lookup[(k, "full", bucket)]
            trimmed = bucket_lookup[(k, "trimmed", bucket)]
            lines.append(
                f"| {k} | {bucket} | {full['n']} | {full['mean_T_ret_bps']:.2f} | "
                f"{p_fmt(full['mean_t_p'])} | {100 * full['majority_sign_consistency']:.1f}% | "
                f"{trimmed['n']} / {trimmed['mean_T_ret_bps']:.2f} / "
                f"{100 * trimmed['majority_sign_consistency']:.1f}% |"
            )

    lines += [
        "",
        "Bucket means change sign across k and weaken materially after tail removal. No fixed "
        "P1×P2×P3 sign combination is a stable directional rule across target start times.",
        "",
        "## Verdict",
        "",
        "**Direction:** no robust linear or sign-combination edge in this specification. Small "
        "in-sample return relationships do not survive the chronological holdout.",
        "",
        "**Range/magnitude:** there is a modest, non-mechanical signal worth a prospective test, "
        "especially for k=10–30. Negative prior-day return, negative overnight gap and negative "
        "P3 generally predict a wider following 10-minute window. The ranking relationship "
        "survives OOS and the 1% tail check at k=10/20/30, but calibration is weak—OOS R² is only "
        "about 0.6–2.2% after trimming. This supports a volatility/range-screening hypothesis, "
        "not yet a tradable directional rule or a proven net-of-cost edge.",
        "",
        "## Caveats",
        "",
        "- `spot` is a Dhan-derived level embedded in ATM option files. T_high/T_low are extrema "
        "of minute-stamped spot levels, not intraminute index OHLC extrema.",
        "- P0 is the prior session's final available spot stamp; this is a close proxy, including "
        "special evening sessions, rather than an official NSE closing index value.",
        "- Marginal p-values are unadjusted for the 32 scans. HAC inference addresses short daily "
        "serial dependence but not all regime changes or data-snooping.",
        "- The 70/30 split is one holdout, not repeated walk-forward validation. Any next step "
        "should freeze the selected k/range rule before prospective testing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    spot, audit = load_spot()
    levels = build_level_panel(spot)
    panels = build_feature_panels(spot, levels, audit)
    marginals: list[dict[str, object]] = []
    ols: list[dict[str, object]] = []
    oos: list[dict[str, object]] = []
    buckets: list[dict[str, object]] = []
    tail_cutoffs: dict[str, object] = {}
    long_panels: list[pd.DataFrame] = []

    for k, panel in panels.items():
        tail_cutoff = float(panel["T_ret"].abs().quantile(0.99))
        trimmed = panel[panel["T_ret"].abs() <= tail_cutoff].copy()
        tail_cutoffs[str(k)] = {
            "abs_T_ret_99pct": tail_cutoff,
            "full_n": len(panel),
            "trimmed_n": len(trimmed),
            "removed_n": len(panel) - len(trimmed),
        }
        for sample, data in (("full", panel), ("trimmed", trimmed)):
            for predictor in FEATURES:
                for target in ("T_ret", "T_range_ratio"):
                    marginals.append(marginal(data, predictor, target, k=k, sample=sample))
            bucket_result, excluded = bucket_rows(data, k=k, sample=sample)
            buckets.extend(bucket_result)
            audit[f"bucket_zero_sign_excluded_k{k}_{sample}"] = excluded
            for target in MODEL_TARGETS:
                full_model = fit_standardized_ols(data, target)
                ols.extend(ols_rows(full_model, k=k, sample=sample, partition="full_sample"))
                validation, train_model = chronological_validation(data, target, k=k, sample=sample)
                oos.append(validation)
                ols.extend(ols_rows(train_model, k=k, sample=sample, partition="train_70pct"))
        output = panel.reset_index().rename(columns={"index": "date"})
        keep = [
            "date",
            "k",
            "P3_end",
            "target_end",
            "P0_close",
            *FEATURES,
            "T_ret",
            "T_high",
            "T_low",
            "T_range_ratio",
            "T_range_magnitude",
        ]
        long_panels.append(output.loc[:, keep])

    results: dict[str, object] = {
        "source": {
            "manifest": str(MANIFEST),
            "selection": {"strike": "ATM", "drv_option_type": "CALL"},
        },
        "definitions": {
            "P1": "close[t-1]/close[t-2]-1 using final available daily spot stamps",
            "gap": "spot[t,09:15]/close[t-1]-1",
            "P2": "spot[t,09:16]/spot[t,09:15]-1",
            "P3": "spot[t,09:15+k]/spot[t,09:16]-1",
            "T_ret": "spot[t,09:15+k+10]/spot[t,09:15+k]-1",
            "T_range_ratio": "max/min over inclusive minute stamps from target start to end",
        },
        "audit": audit,
        "tail_cutoffs": tail_cutoffs,
        "marginals": marginals,
        "ols": ols,
        "oos": oos,
        "buckets": buckets,
    }
    pd.concat(long_panels, ignore_index=True).to_csv(SCRATCH / "refined_panel.csv", index=False)
    pd.DataFrame(marginals).to_csv(SCRATCH / "refined_marginals.csv", index=False)
    pd.DataFrame(ols).to_csv(SCRATCH / "refined_ols.csv", index=False)
    pd.DataFrame(oos).to_csv(SCRATCH / "refined_oos.csv", index=False)
    pd.DataFrame(buckets).to_csv(SCRATCH / "refined_buckets.csv", index=False)
    (SCRATCH / "refined_results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = report_markdown(results)
    (SCRATCH / "report_refined.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
