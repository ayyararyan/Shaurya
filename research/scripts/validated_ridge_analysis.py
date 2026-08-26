#!/usr/bin/env python3
"""Chronologically validate incremental futures features on a derived panel."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CONTROL_NAMES = (
    "option_log_mid",
    "option_relative_spread",
    "option_microprice_dislocation",
    "option_depth_imbalance",
    "option_return_5s",
    "option_is_call",
    "option_strike_scaled",
    "time_sin",
    "time_cos",
)
FUTURES_NAMES = (
    "futures_log_mid",
    "futures_relative_spread",
    "futures_microprice_dislocation",
    "futures_depth_imbalance",
    "futures_log_trade_intensity_10s",
    "futures_realized_volatility_30s",
)
TARGETS = (
    "markout_5s",
    "adverse_proxy_5s",
    "markout_30s",
    "adverse_proxy_30s",
)
ALPHAS_PER_ROW = (0.0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0)
EMBARGO_SECONDS = 30
GRID_SECONDS = 5
HAC_LAGS = 12
BOOTSTRAP_REPLICATES = 400


@dataclass(frozen=True)
class Preprocessor:
    lower: np.ndarray
    upper: np.ndarray
    mean: np.ndarray
    scale: np.ndarray


def fit_preprocessor(x: np.ndarray) -> Preprocessor:
    lower = np.quantile(x, 0.005, axis=0)
    upper = np.quantile(x, 0.995, axis=0)
    clipped = np.clip(x, lower, upper)
    mean = clipped.mean(axis=0)
    scale = clipped.std(axis=0)
    scale[scale < 1e-12] = 1.0
    return Preprocessor(lower, upper, mean, scale)


def transform(preprocessor: Preprocessor, x: np.ndarray) -> np.ndarray:
    clipped = np.clip(x, preprocessor.lower, preprocessor.upper)
    return (clipped - preprocessor.mean) / preprocessor.scale


def fit_ridge(z: np.ndarray, y: np.ndarray, alpha_per_row: float) -> np.ndarray:
    design = np.column_stack([np.ones(z.shape[0]), z])
    penalty = np.eye(design.shape[1]) * alpha_per_row * z.shape[0]
    penalty[0, 0] = 0.0
    return np.linalg.pinv(design.T @ design + penalty) @ design.T @ y


def predict(beta: np.ndarray, z: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(z.shape[0]), z]) @ beta


def r2(y: np.ndarray, prediction: np.ndarray) -> float:
    denominator = float(np.sum((y - y.mean()) ** 2))
    if denominator <= 0:
        return float("nan")
    return float(1.0 - np.sum((y - prediction) ** 2) / denominator)


def chronological_split(timestamps: np.ndarray) -> dict[str, np.ndarray | int]:
    unique = np.unique(timestamps)
    train_boundary = unique[int(0.60 * unique.size)]
    test_boundary = unique[int(0.80 * unique.size)]
    embargo_ns = EMBARGO_SECONDS * 1_000_000_000
    train = np.flatnonzero(timestamps < train_boundary)
    validation = np.flatnonzero(
        (timestamps > train_boundary + embargo_ns) & (timestamps < test_boundary)
    )
    development = np.flatnonzero(timestamps < test_boundary)
    test = np.flatnonzero(timestamps > test_boundary + embargo_ns)
    first_embargo = np.flatnonzero(
        (timestamps >= train_boundary) & (timestamps <= train_boundary + embargo_ns)
    )
    second_embargo = np.flatnonzero(
        (timestamps >= test_boundary) & (timestamps <= test_boundary + embargo_ns)
    )
    if min(train.size, validation.size, test.size) < 1_000:
        raise ValueError("chronological split has insufficient rows")
    if (
        min(
            np.unique(timestamps[train]).size,
            np.unique(timestamps[validation]).size,
            np.unique(timestamps[test]).size,
        )
        < 100
    ):
        raise ValueError("chronological split has insufficient unique times")
    return {
        "train": train,
        "validation": validation,
        "development": development,
        "test": test,
        "first_embargo": first_embargo,
        "second_embargo": second_embargo,
        "train_boundary_ts_ns": int(train_boundary),
        "test_boundary_ts_ns": int(test_boundary),
    }


def choose_alpha(
    x: np.ndarray,
    y: np.ndarray,
    train: np.ndarray,
    validation: np.ndarray,
) -> tuple[float, list[dict[str, float]]]:
    preprocessor = fit_preprocessor(x[train])
    train_z = transform(preprocessor, x[train])
    validation_z = transform(preprocessor, x[validation])
    scores = []
    for alpha in ALPHAS_PER_ROW:
        beta = fit_ridge(train_z, y[train], alpha)
        prediction = predict(beta, validation_z)
        scores.append(
            {
                "alpha_per_row": alpha,
                "validation_mse": float(np.mean((y[validation] - prediction) ** 2)),
                "validation_mae": float(np.mean(np.abs(y[validation] - prediction))),
            }
        )
    selected = min(scores, key=lambda item: (item["validation_mse"], item["alpha_per_row"]))
    return float(selected["alpha_per_row"]), scores


def hac_interval(contributions: np.ndarray, denominator: float) -> list[float]:
    centered = contributions - contributions.mean()
    count = centered.size
    long_run_variance = float(centered @ centered / count)
    for lag in range(1, min(HAC_LAGS, count - 1) + 1):
        weight = 1.0 - lag / (HAC_LAGS + 1.0)
        covariance = float(centered[lag:] @ centered[:-lag] / count)
        long_run_variance += 2.0 * weight * covariance
    standard_error = np.sqrt(max(count * long_run_variance, 0.0)) / denominator
    point = float(contributions.sum() / denominator)
    return [point - 1.96 * standard_error, point + 1.96 * standard_error]


def aggregate_by_timestamp(
    timestamps: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    unique, inverse = np.unique(timestamps, return_inverse=True)
    sums = np.zeros(unique.size, dtype=float)
    counts = np.zeros(unique.size, dtype=float)
    np.add.at(sums, inverse, values)
    np.add.at(counts, inverse, 1.0)
    return unique, sums, counts


def block_reweight_intervals(
    y: np.ndarray,
    baseline: np.ndarray,
    augmented: np.ndarray,
    timestamps: np.ndarray,
    *,
    seed: int,
) -> dict[str, list[float] | float]:
    unique = np.unique(timestamps)
    block_width = max(1, 60 // GRID_SECONDS)
    blocks = [unique[index : index + block_width] for index in range(0, unique.size, block_width)]
    indices = [np.flatnonzero(np.isin(timestamps, block)) for block in blocks if block.size]
    rng = np.random.default_rng(seed)
    delta_r2 = []
    mae_improvement = []
    for _ in range(BOOTSTRAP_REPLICATES):
        selected = rng.integers(0, len(indices), size=len(indices))
        sample = np.concatenate([indices[item] for item in selected])
        yy = y[sample]
        base = baseline[sample]
        aug = augmented[sample]
        delta_r2.append(r2(yy, aug) - r2(yy, base))
        mae_improvement.append(float(np.mean(np.abs(yy - base)) - np.mean(np.abs(yy - aug))))
    return {
        "delta_oos_r2_block_reweight_interval95": [
            float(np.quantile(delta_r2, 0.025)),
            float(np.quantile(delta_r2, 0.975)),
        ],
        "delta_oos_r2_block_reweight_median": float(np.median(delta_r2)),
        "mae_improvement_block_reweight_interval95": [
            float(np.quantile(mae_improvement, 0.025)),
            float(np.quantile(mae_improvement, 0.975)),
        ],
        "mae_improvement_block_reweight_median": float(np.median(mae_improvement)),
    }


def uncertainty(
    y: np.ndarray,
    baseline: np.ndarray,
    augmented: np.ndarray,
    timestamps: np.ndarray,
    *,
    seed: int,
) -> dict[str, object]:
    squared_gain = (y - baseline) ** 2 - (y - augmented) ** 2
    absolute_gain = np.abs(y - baseline) - np.abs(y - augmented)
    _, squared_sums, _ = aggregate_by_timestamp(timestamps, squared_gain)
    _, absolute_sums, _ = aggregate_by_timestamp(timestamps, absolute_gain)
    total_variation = float(np.sum((y - y.mean()) ** 2))
    return {
        "delta_oos_r2_cluster_hac_ci95": hac_interval(squared_sums, total_variation),
        "mae_improvement_cluster_hac_ci95": hac_interval(absolute_sums, float(y.size)),
        **block_reweight_intervals(
            y,
            baseline,
            augmented,
            timestamps,
            seed=seed,
        ),
    }


def fit_target(
    control: np.ndarray,
    augmented: np.ndarray,
    y: np.ndarray,
    timestamps: np.ndarray,
    split: dict[str, np.ndarray | int],
    feature_names: tuple[str, ...],
    *,
    seed: int,
) -> dict[str, object]:
    train = split["train"]
    validation = split["validation"]
    development = split["development"]
    test = split["test"]
    assert isinstance(train, np.ndarray)
    assert isinstance(validation, np.ndarray)
    assert isinstance(development, np.ndarray)
    assert isinstance(test, np.ndarray)
    base_alpha, base_path = choose_alpha(control, y, train, validation)
    aug_alpha, aug_path = choose_alpha(augmented, y, train, validation)
    base_preprocessor = fit_preprocessor(control[development])
    aug_preprocessor = fit_preprocessor(augmented[development])
    base_beta = fit_ridge(
        transform(base_preprocessor, control[development]),
        y[development],
        base_alpha,
    )
    aug_beta = fit_ridge(
        transform(aug_preprocessor, augmented[development]),
        y[development],
        aug_alpha,
    )
    base_prediction = predict(base_beta, transform(base_preprocessor, control[test]))
    aug_prediction = predict(aug_beta, transform(aug_preprocessor, augmented[test]))
    baseline_r2 = r2(y[test], base_prediction)
    augmented_r2 = r2(y[test], aug_prediction)
    baseline_mae = float(np.mean(np.abs(y[test] - base_prediction)))
    augmented_mae = float(np.mean(np.abs(y[test] - aug_prediction)))
    coefficients = [
        {
            "feature": feature,
            "standardized_ridge_coefficient": float(aug_beta[offset]),
        }
        for offset, feature in enumerate(feature_names, 1)
    ]
    return {
        "baseline_alpha_per_row": base_alpha,
        "augmented_alpha_per_row": aug_alpha,
        "baseline_validation_path": base_path,
        "augmented_validation_path": aug_path,
        "baseline_oos_r2": baseline_r2,
        "augmented_oos_r2": augmented_r2,
        "delta_oos_r2": augmented_r2 - baseline_r2,
        "baseline_oos_mae": baseline_mae,
        "augmented_oos_mae": augmented_mae,
        "mae_improvement": baseline_mae - augmented_mae,
        "augmented_standardized_ridge_coefficients": coefficients,
        **uncertainty(
            y[test],
            base_prediction,
            aug_prediction,
            timestamps[test],
            seed=seed,
        ),
    }


def load_panel(path: Path) -> dict[str, np.ndarray]:
    names = ("timestamp_ns", "eligible_buffer_60s") + CONTROL_NAMES + FUTURES_NAMES + TARGETS
    columns: dict[str, list[float]] = {name: [] for name in names}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            for name in names:
                if name == "eligible_buffer_60s":
                    columns[name].append(float(row[name] == "True"))
                else:
                    columns[name].append(float(row[name]))
    return {name: np.asarray(items) for name, items in columns.items()}


def serial_split(split: dict[str, np.ndarray | int]) -> dict[str, int]:
    output = {
        "embargo_seconds": EMBARGO_SECONDS,
        "train_boundary_ts_ns": int(split["train_boundary_ts_ns"]),
        "test_boundary_ts_ns": int(split["test_boundary_ts_ns"]),
    }
    for name in (
        "train",
        "validation",
        "development",
        "test",
        "first_embargo",
        "second_embargo",
    ):
        values = split[name]
        assert isinstance(values, np.ndarray)
        output[f"{name}_rows"] = int(values.size)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prior = json.loads(args.results.read_text(encoding="utf-8"))
    data = load_panel(args.panel)
    timestamps_all = data["timestamp_ns"].astype(np.int64)
    control_all = np.column_stack([data[name] for name in CONTROL_NAMES])
    augmented_all = np.column_stack([data[name] for name in CONTROL_NAMES + FUTURES_NAMES])
    analyses = {}
    specifications = (
        ("primary_30s_raw", np.ones(timestamps_all.size, dtype=bool), False),
        ("primary_30s_winsorized_target", np.ones(timestamps_all.size, dtype=bool), True),
        ("strict_60s_raw", data["eligible_buffer_60s"].astype(bool), False),
    )
    for spec_number, (name, mask, winsorize_target) in enumerate(specifications):
        timestamps = timestamps_all[mask]
        control = control_all[mask]
        augmented = augmented_all[mask]
        split = chronological_split(timestamps)
        target_results = []
        for target_number, target_name in enumerate(TARGETS):
            y = data[target_name][mask].copy()
            target_bounds = None
            if winsorize_target:
                development = split["development"]
                assert isinstance(development, np.ndarray)
                lower, upper = np.quantile(y[development], (0.005, 0.995))
                y = np.clip(y, lower, upper)
                target_bounds = [float(lower), float(upper)]
            result = fit_target(
                control,
                augmented,
                y,
                timestamps,
                split,
                CONTROL_NAMES + FUTURES_NAMES,
                seed=20260826 + 10 * spec_number + target_number,
            )
            target_results.append(
                {
                    "target": target_name,
                    "target_winsorization_bounds": target_bounds,
                    **result,
                }
            )
        analyses[name] = {
            "quality_buffer_seconds": 60 if name.startswith("strict") else 30,
            "target_winsorized": winsorize_target,
            "rows": int(mask.sum()),
            "split": serial_split(split),
            "results": target_results,
        }
    output = {
        "status": "exploratory_single_session_chronological_validation",
        "dataset_id": prior["dataset_id"],
        "tape_sha256": prior["tape_sha256"],
        "panel_sha256": prior["panel_sha256"],
        "features": {
            "option_state_controls": CONTROL_NAMES,
            "futures_increment": FUTURES_NAMES,
        },
        "targets": TARGETS,
        "estimator": {
            "model": "ridge regression with unpenalized intercept",
            "split": "60/20/20 chronological train/validation/test with 30s embargoes",
            "alpha_selection": "validation MSE over declared alpha-per-row grid",
            "refit": "selected alpha refit on pre-test development sample",
            "feature_preprocessing": "development-only percentile clipping and standardization",
            "uncertainty": "grid-time HAC plus 60s block reweighting, 400 replicates",
        },
        "analyses": analyses,
        "claim_limits": prior["claim_limits"],
    }
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
