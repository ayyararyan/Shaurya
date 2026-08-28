"""Frozen primitives for the one-shot prospective Market-JEPA outer test."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge
from sklearn.metrics import balanced_accuracy_score, mean_absolute_error, r2_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

FloatArray = NDArray[np.float64]


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


def score_frozen_probe(
    probe: FrozenRidge, features: FloatArray, target: FloatArray
) -> dict[str, Any]:
    finite = np.isfinite(target) & np.all(np.isfinite(features), axis=1)
    if finite.sum() < 50:
        raise ValueError("insufficient finite outer-test rows")
    actual = target[finite]
    prediction = probe.predict(features[finite])
    test_mae = float(mean_absolute_error(actual, prediction))
    constant_mae = float(mean_absolute_error(actual, np.full_like(actual, probe.target_median)))
    labels = actual > 0.0
    balanced: float | None = None
    auc: float | None = None
    if len(np.unique(labels)) == 2:
        balanced = float(balanced_accuracy_score(labels, prediction > 0.0))
        auc = float(roc_auc_score(labels, prediction))
    return {
        "samples": int(finite.sum()),
        "mae": test_mae,
        "constant_mae": constant_mae,
        "mae_skill": 1.0 - test_mae / constant_mae,
        "r2": float(r2_score(actual, prediction)),
        "balanced_accuracy": balanced,
        "roc_auc": auc,
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


def prospective_decision(seed_metrics: dict[str, Any], required_seeds: int = 4) -> dict[str, Any]:
    """Apply the predeclared JEPA hurdle at both 30-second and 300-second horizons."""
    horizon_counts: dict[str, int] = {}
    qualifying: dict[str, list[int]] = {}
    for horizon in ("30s", "300s"):
        seeds: list[int] = []
        for seed_text, metrics in seed_metrics.items():
            jepa = metrics[horizon]["base_plus_jepa"]["mae_skill"]
            base = metrics[horizon]["handcrafted_base"]["mae_skill"]
            pca = metrics[horizon]["base_plus_pca"]["mae_skill"]
            if jepa > base and jepa > pca:
                seeds.append(int(seed_text))
        qualifying[horizon] = sorted(seeds)
        horizon_counts[horizon] = len(seeds)
    keep = all(count >= required_seeds for count in horizon_counts.values())
    return {
        "verdict": "KEEP_JEPA" if keep else "DROP_JEPA",
        "required_seeds_per_horizon": required_seeds,
        "qualifying_seeds": qualifying,
        "qualifying_seed_counts": horizon_counts,
        "rule": (
            "base+JEPA MAE skill must exceed both handcrafted base and base+PCA "
            "at 30s and 300s in at least 4/5 seeds"
        ),
    }
