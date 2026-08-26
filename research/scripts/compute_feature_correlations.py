#!/usr/bin/env python3
"""Compute aggregate feature/target correlations from a derived Shaurya panel."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np

FEATURES = (
    "option_log_mid",
    "option_relative_spread",
    "option_microprice_dislocation",
    "option_depth_imbalance",
    "option_return_5s",
    "option_is_call",
    "option_strike_scaled",
    "time_sin",
    "time_cos",
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


def correlation(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 3 or np.std(x) < 1e-15 or np.std(y) < 1e-15:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.results.read_text(encoding="utf-8"))
    values = {name: [] for name in FEATURES + TARGETS}
    roles: list[str] = []
    epochs: list[int] = []
    with gzip.open(args.panel, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            for name in values:
                values[name].append(float(row[name]))
            roles.append(row["sample_role"])
            epochs.append(int(row["connection_epoch"]))
    arrays = {name: np.asarray(items, dtype=float) for name, items in values.items()}
    role_array = np.asarray(roles)
    samples = {
        "all_primary_clean": np.ones(role_array.size, dtype=bool),
        "train": role_array == "train",
        "test": role_array == "test",
    }
    associations = []
    for sample_name, mask in samples.items():
        for feature in FEATURES:
            for target in TARGETS:
                associations.append(
                    {
                        "sample": sample_name,
                        "rows": int(mask.sum()),
                        "feature": feature,
                        "target": target,
                        "pearson_correlation": correlation(
                            arrays[feature][mask], arrays[target][mask]
                        ),
                    }
                )
    target_distributions = {}
    for target in TARGETS:
        target_distributions[target] = {
            "mean": float(np.mean(arrays[target])),
            "standard_deviation": float(np.std(arrays[target])),
            "p01": float(np.quantile(arrays[target], 0.01)),
            "p50": float(np.quantile(arrays[target], 0.50)),
            "p99": float(np.quantile(arrays[target], 0.99)),
            "maximum_absolute": float(np.max(np.abs(arrays[target]))),
        }
    augmented_coefficients = {}
    for result in metadata["results"]:
        augmented_coefficients[result["target"]] = [
            item
            for item in result["augmented_standardized_coefficients"]
            if item["feature"].startswith("futures_")
        ]
    output = {
        "status": "descriptive_correlations_and_training_coefficient_associations",
        "dataset_id": metadata["dataset_id"],
        "tape_sha256": metadata["tape_sha256"],
        "panel_sha256": metadata["panel_sha256"],
        "primary_quality_buffer_seconds": 30,
        "panel_rows": len(roles),
        "sample_rows": {name: int(mask.sum()) for name, mask in samples.items()},
        "panel_rows_by_epoch": dict(sorted(Counter(epochs).items())),
        "features": FEATURES,
        "targets": TARGETS,
        "pearson_associations": associations,
        "target_distributions": target_distributions,
        "augmented_training_standardized_coefficients_with_hac_uncertainty": (
            augmented_coefficients
        ),
        "interpretation": [
            "Pearson correlations are descriptive, univariate, and not predictive validation.",
            "Train/test correlations are stability diagnostics, not fitted-model performance.",
            "Only held-out baseline-versus-augmented results are predictive evidence.",
        ],
    }
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
