"""Frozen primitives for the one-shot prospective Market-JEPA outer test."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import balanced_accuracy_score, mean_absolute_error, r2_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

FloatArray = NDArray[np.float64]

H1_REPRESENTATIONS = (
    "base",
    "base_pca",
    "base_jepa",
    "base_random",
    "base_shuffled_jepa",
    "jepa_only",
    "flattened_context",
    "base_no_time",
    "base_no_time_jepa",
)
H3_MODELS = (
    "recent_only",
    "recent_base",
    "recent_base_pca",
    "recent_base_jepa",
    "recent_base_jepa_interaction",
)


def fit_discovery_normalization(discovery: FloatArray) -> tuple[FloatArray, FloatArray]:
    center = np.nanmean(discovery, axis=0)
    scale = np.nanstd(discovery, axis=0, ddof=1)
    center = np.where(np.isfinite(center), center, 0.0)
    scale = np.where(np.isfinite(scale) & (scale > 0.0), scale, 1.0)
    return center.astype(np.float64), scale.astype(np.float64)


def apply_frozen_normalization(
    values: FloatArray, center: FloatArray, scale: FloatArray
) -> FloatArray:
    filled = np.where(np.isfinite(values), values, center)
    return np.clip((filled - center) / scale, -10.0, 10.0).astype(np.float64)


def require_complete_endpoint_count(observed: int, minimum: int) -> None:
    if observed < minimum:
        raise ValueError(f"incomplete session: {observed} endpoints, require at least {minimum}")


@dataclass(frozen=True)
class FrozenRidge:
    """A StandardScaler + Ridge probe represented without a fitted sklearn object."""

    feature_mean: FloatArray
    feature_scale: FloatArray
    coefficients: FloatArray
    intercept: float
    target_median: float
    alpha: float

    def predict(self, features: FloatArray) -> FloatArray:
        if features.ndim != 2 or features.shape[1] != len(self.coefficients):
            raise ValueError("probe feature dimension mismatch")
        scaled = (features - self.feature_mean) / self.feature_scale
        return (scaled @ self.coefficients + self.intercept).astype(np.float64)

    def save(self, path: Path) -> None:
        np.savez_compressed(
            path,
            feature_mean=self.feature_mean,
            feature_scale=self.feature_scale,
            coefficients=self.coefficients,
            intercept=np.asarray([self.intercept], dtype=np.float64),
            target_median=np.asarray([self.target_median], dtype=np.float64),
            alpha=np.asarray([self.alpha], dtype=np.float64),
        )

    @classmethod
    def load(cls, path: Path) -> FrozenRidge:
        with np.load(path, allow_pickle=False) as payload:
            return cls(
                feature_mean=payload["feature_mean"].astype(np.float64),
                feature_scale=payload["feature_scale"].astype(np.float64),
                coefficients=payload["coefficients"].astype(np.float64),
                intercept=float(payload["intercept"][0]),
                target_median=float(payload["target_median"][0]),
                alpha=float(payload["alpha"][0]),
            )


def recent_atm_iv_change(
    raw: FloatArray, ends: NDArray[np.int64], columns: list[str], lag_steps: int = 6
) -> FloatArray:
    index = columns.index("surface__atm_iv__near")
    return np.asarray(raw[ends, index] - raw[ends - lag_steps, index], dtype=np.float64)


def prospective_feature_sets(
    representation: dict[str, FloatArray],
    recent_iv: FloatArray,
    shuffle_permutation: NDArray[np.int64],
) -> tuple[dict[str, FloatArray], dict[str, FloatArray]]:
    """Build the preregistered H1 and H3 features using information available at t."""
    base = representation["handcrafted_base"]
    base_no_time = base[:, :-3]
    jepa = representation["jepa"]
    pca = representation["pca"]
    random = representation["random_encoder"]
    shuffled = jepa[shuffle_permutation]
    recent = recent_iv[:, None]
    h1 = {
        "base": base,
        "base_pca": np.column_stack((base, pca)),
        "base_jepa": np.column_stack((base, jepa)),
        "base_random": np.column_stack((base, random)),
        "base_shuffled_jepa": np.column_stack((base, shuffled)),
        "jepa_only": jepa,
        "flattened_context": representation["flattened_context"],
        "base_no_time": base_no_time,
        "base_no_time_jepa": np.column_stack((base_no_time, jepa)),
    }
    h3 = {
        "recent_only": recent,
        "recent_base": np.column_stack((recent, base)),
        "recent_base_pca": np.column_stack((recent, base, pca)),
        "recent_base_jepa": np.column_stack((recent, base, jepa)),
        "recent_base_jepa_interaction": np.column_stack((recent, base, jepa, jepa * recent)),
    }
    return h1, h3


def fit_frozen_ridge(features: FloatArray, target: FloatArray, alpha: float) -> FrozenRidge:
    """Fit once on locked development rows for later apply-only evaluation."""
    finite = np.isfinite(target) & np.all(np.isfinite(features), axis=1)
    if finite.sum() < 50:
        raise ValueError("insufficient finite development rows")
    clean_features = features[finite]
    clean_target = target[finite]
    scaler = StandardScaler().fit(clean_features)
    transformed = scaler.transform(clean_features)
    ridge = Ridge(alpha=alpha).fit(transformed, clean_target)
    scale = np.asarray(scaler.scale_, dtype=np.float64)
    return FrozenRidge(
        feature_mean=np.asarray(scaler.mean_, dtype=np.float64),
        feature_scale=np.where(scale > 0.0, scale, 1.0),
        coefficients=np.asarray(ridge.coef_, dtype=np.float64),
        intercept=float(ridge.intercept_),
        target_median=float(np.median(clean_target)),
        alpha=float(alpha),
    )


def select_frozen_ridge(
    discovery_features: FloatArray,
    validation_features: FloatArray,
    discovery_target: FloatArray,
    validation_target: FloatArray,
    alphas: tuple[float, ...],
) -> tuple[FrozenRidge, float]:
    """Select alpha on validation, then refit once on discovery plus validation."""
    validation_mae: dict[float, float] = {}
    for alpha in alphas:
        candidate = fit_frozen_ridge(discovery_features, discovery_target, alpha)
        finite = np.isfinite(validation_target) & np.all(np.isfinite(validation_features), axis=1)
        validation_mae[alpha] = float(
            mean_absolute_error(
                validation_target[finite], candidate.predict(validation_features[finite])
            )
        )
    selected = min(alphas, key=validation_mae.__getitem__)
    frozen = fit_frozen_ridge(
        np.concatenate((discovery_features, validation_features)),
        np.concatenate((discovery_target, validation_target)),
        selected,
    )
    return frozen, validation_mae[selected]


def frozen_probe_outputs(
    probe: FrozenRidge, features: FloatArray, target: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    finite = np.isfinite(target) & np.all(np.isfinite(features), axis=1)
    if finite.sum() < 50:
        raise ValueError("insufficient finite outer-test rows")
    actual = target[finite]
    prediction = probe.predict(features[finite])
    return actual, prediction, np.abs(actual - prediction)


def score_frozen_probe(
    probe: FrozenRidge, features: FloatArray, target: FloatArray
) -> dict[str, Any]:
    actual, prediction, losses = frozen_probe_outputs(probe, features, target)
    test_mae = float(mean_absolute_error(actual, prediction))
    constant_mae = float(mean_absolute_error(actual, np.full_like(actual, probe.target_median)))
    labels = actual > 0.0
    balanced: float | None = None
    auc: float | None = None
    if len(np.unique(labels)) == 2:
        balanced = float(balanced_accuracy_score(labels, prediction > 0.0))
        auc = float(roc_auc_score(labels, prediction))
    return {
        "samples": int(len(actual)),
        "mae": test_mae,
        "constant_mae": constant_mae,
        "mae_skill": 1.0 - test_mae / constant_mae,
        "r2": float(r2_score(actual, prediction)),
        "balanced_accuracy": balanced,
        "roc_auc": auc,
        "sign_hit_rate": float(np.mean((actual > 0.0) == (prediction > 0.0))),
        "conditional_slope": conditional_slope(prediction, actual),
    }


def conditional_slope(predictor: FloatArray, target: FloatArray) -> float:
    finite = np.isfinite(predictor) & np.isfinite(target)
    left = predictor[finite]
    right = target[finite]
    if len(left) < 2:
        return 0.0
    variance = float(np.var(left))
    if not np.isfinite(variance) or variance <= 0.0:
        return 0.0
    return float(np.mean((left - left.mean()) * (right - right.mean())) / variance)


def paired_block_comparison(
    pca_losses: FloatArray,
    jepa_losses: FloatArray,
    *,
    block_rows: int,
    minimum_overlap_rows: int,
    draws: int = 1000,
    seed: int = 20260828,
) -> dict[str, float | int]:
    """Compare paired absolute losses; positive values mean JEPA beats PCA."""
    if block_rows < minimum_overlap_rows:
        raise ValueError("bootstrap block is shorter than target overlap")
    if len(pca_losses) != len(jepa_losses):
        raise ValueError("paired loss arrays differ in length")
    difference = pca_losses - jepa_losses
    finite = np.isfinite(difference)
    if finite.sum() < 50:
        raise ValueError("insufficient paired finite losses")
    blocks = [
        difference[start : start + block_rows] for start in range(0, len(difference), block_rows)
    ]
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    for draw in range(draws):
        selected = rng.integers(0, len(blocks), size=len(blocks))
        sample = np.concatenate([blocks[index] for index in selected])
        estimates[draw] = float(np.nanmean(sample))
    clean = difference[finite]
    return {
        "mean_pca_minus_jepa_loss": float(clean.mean()),
        "median_pca_minus_jepa_loss": float(np.median(clean)),
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "positive_probability": float(np.mean(estimates > 0.0)),
        "block_rows": block_rows,
        "draws": draws,
    }


def fit_quantile_boundaries(values: FloatArray, quantiles: int = 5) -> FloatArray:
    finite = values[np.isfinite(values)]
    if len(finite) < quantiles * 10:
        raise ValueError("insufficient development values for shock quantiles")
    return np.asarray(np.quantile(finite, np.arange(1, quantiles) / quantiles), dtype=np.float64)


def shock_quantile_summary(
    shock: FloatArray, target: FloatArray, boundaries: FloatArray
) -> dict[str, Any]:
    finite = np.isfinite(shock) & np.isfinite(target)
    buckets = np.digitize(shock[finite], boundaries)
    actual = target[finite]
    rows: list[dict[str, float | int | None]] = []
    means: list[float] = []
    for bucket in range(len(boundaries) + 1):
        selected = actual[buckets == bucket]
        mean = float(np.mean(selected)) if len(selected) else float("nan")
        means.append(mean)
        rows.append(
            {
                "quantile": bucket + 1,
                "samples": int(len(selected)),
                "mean": mean if np.isfinite(mean) else None,
            }
        )
    finite_means = np.asarray(means, dtype=np.float64)
    monotonic = (
        bool(np.all(np.diff(finite_means) >= 0.0)) if np.all(np.isfinite(finite_means)) else False
    )
    rank = spearmanr(np.arange(1, len(means) + 1), finite_means).statistic
    return {
        "buckets": rows,
        "monotonic_non_decreasing": monotonic,
        "bucket_mean_spearman": float(rank) if np.isfinite(rank) else None,
    }


def block_bootstrap_spearman(
    predictor: FloatArray,
    target: FloatArray,
    *,
    block_rows: int,
    minimum_overlap_rows: int,
    draws: int = 1000,
    seed: int = 20260828,
) -> dict[str, float | int | None]:
    if block_rows < minimum_overlap_rows:
        raise ValueError("bootstrap block is shorter than target overlap")
    if len(predictor) != len(target):
        raise ValueError("correlation arrays differ in length")
    indices = [
        np.arange(start, min(start + block_rows, len(target)))
        for start in range(0, len(target), block_rows)
    ]
    finite = np.isfinite(predictor) & np.isfinite(target)
    observed = spearmanr(predictor[finite], target[finite]).statistic
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    for draw in range(draws):
        chosen = rng.integers(0, len(indices), size=len(indices))
        sample = np.concatenate([indices[index] for index in chosen])
        valid = np.isfinite(predictor[sample]) & np.isfinite(target[sample])
        estimates[draw] = spearmanr(predictor[sample][valid], target[sample][valid]).statistic
    estimates = estimates[np.isfinite(estimates)]
    return {
        "spearman": float(observed) if np.isfinite(observed) else None,
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "positive_probability": float(np.mean(estimates > 0.0)),
        "block_rows": block_rows,
        "draws": draws,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_bundle(bundle: Path, manifest: dict[str, Any]) -> None:
    expected_fingerprint = manifest.get("semantic_sha256")
    semantic = {key: value for key, value in manifest.items() if key != "semantic_sha256"}
    if semantic_sha256(semantic) != expected_fingerprint:
        raise ValueError("bundle manifest fingerprint mismatch")
    for relative, expected in manifest["artifact_sha256"].items():
        path = bundle / relative
        if not path.is_file() or file_sha256(path) != expected:
            raise ValueError(f"bundle artifact hash mismatch: {relative}")


def prospective_decision(
    seed_metrics: dict[str, Any], paired: dict[str, Any], required_seeds: int = 4
) -> dict[str, Any]:
    """Return the preregistered A/B/C scientific decision for signed ATM-IV."""
    positive = sorted(
        int(seed)
        for seed, metrics in seed_metrics.items()
        if metrics["base_jepa"]["mae_skill"] > metrics["base_pca"]["mae_skill"]
    )
    confidence_supported = sorted(
        int(seed)
        for seed, blocks in paired.items()
        if all(result["ci_low"] > 0.0 for result in blocks.values())
    )
    if len(positive) >= required_seeds and len(confidence_supported) >= required_seeds:
        decision = "A"
        conclusion = "Promote JEPA to experimental Shaurya state feature"
    elif len(positive) >= 3:
        decision = "B"
        conclusion = "Keep JEPA as exploratory research only"
    else:
        decision = "C"
        conclusion = "Drop JEPA from the active research stack"
    return {
        "decision": decision,
        "conclusion": conclusion,
        "required_seeds_per_horizon": required_seeds,
        "positive_seeds": positive,
        "confidence_supported_seeds": confidence_supported,
        "rule": (
            "A requires Base+JEPA to beat Base+PCA in MAE skill and have positive paired "
            "95% intervals at 60s, 120s, and 300s blocks in at least 4/5 seeds; "
            "B requires a positive point estimate in at least 3/5 seeds; otherwise C"
        ),
    }
