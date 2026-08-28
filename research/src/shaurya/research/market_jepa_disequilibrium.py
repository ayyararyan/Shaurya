"""Subsystem feature contracts and development-only latent mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

FloatArray = NDArray[np.float64]


def subsystem_feature_lists(columns: list[str]) -> dict[str, list[str]]:
    """Build economically separated feature lists from the frozen state schema."""
    futures = [
        name for name in columns if name.startswith("futures_") and name != "futures_log_mid"
    ]
    options = [
        name
        for name in columns
        if not name.startswith("futures_")
        and "strike" not in name
        and name not in {"atm_near_call_put_skew", "atm_far_call_put_skew"}
    ]
    near = [
        name
        for name in options
        if "__near" in name or "_near_" in name or name.startswith("atm_near_")
    ]
    far = [
        name
        for name in options
        if "__far" in name or "_far_" in name or name.startswith("atm_far_")
    ]
    call = [name for name in options if name.endswith("__CE")]
    put = [name for name in options if name.endswith("__PE")]
    groups = {
        "futures": futures,
        "options": options,
        "near": near,
        "far": far,
        "call": call,
        "put": put,
    }
    if any(not values for values in groups.values()):
        raise ValueError("one or more subsystem feature lists are empty")
    if set(futures) & set(options):
        raise ValueError("futures and options subsystem features overlap")
    if set(near) & set(far):
        raise ValueError("near and far subsystem features overlap")
    if set(call) & set(put):
        raise ValueError("call and put subsystem features overlap")
    return groups


@dataclass(frozen=True)
class DevelopmentRidgeMap:
    """A regularized latent map whose provenance excludes diagnostic samples."""

    source_mean: FloatArray
    source_scale: FloatArray
    coefficients: FloatArray
    intercept: FloatArray
    alpha: float
    fit_roles: tuple[str, ...]
    discovery_samples: int
    validation_samples: int

    def predict(self, source: FloatArray) -> FloatArray:
        if source.ndim != 2 or source.shape[1] != len(self.source_mean):
            raise ValueError("mapping source feature dimension mismatch")
        scaled = (source - self.source_mean) / self.source_scale
        return (scaled @ self.coefficients.T + self.intercept).astype(np.float64)


def fit_development_ridge_map(
    discovery_source: FloatArray,
    discovery_target: FloatArray,
    validation_source: FloatArray,
    validation_target: FloatArray,
    *,
    alphas: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0),
) -> DevelopmentRidgeMap:
    """Select on validation, then refit on discovery+validation only."""
    if discovery_source.ndim != 2 or validation_source.ndim != 2:
        raise ValueError("mapping source arrays must be two-dimensional")
    if discovery_target.ndim != 2 or validation_target.ndim != 2:
        raise ValueError("mapping target arrays must be two-dimensional")
    if len(discovery_source) != len(discovery_target) or len(validation_source) != len(
        validation_target
    ):
        raise ValueError("mapping source/target rows differ")
    if discovery_source.shape[1] != validation_source.shape[1]:
        raise ValueError("mapping source dimensions differ by split")
    if discovery_target.shape[1] != validation_target.shape[1]:
        raise ValueError("mapping target dimensions differ by split")
    if min(len(discovery_source), len(validation_source)) < 30:
        raise ValueError("insufficient development rows for latent mapping")
    finite_discovery = np.all(np.isfinite(discovery_source), axis=1) & np.all(
        np.isfinite(discovery_target), axis=1
    )
    finite_validation = np.all(np.isfinite(validation_source), axis=1) & np.all(
        np.isfinite(validation_target), axis=1
    )
    scaler = StandardScaler().fit(discovery_source[finite_discovery])
    validation_error: dict[float, float] = {}
    for alpha in alphas:
        ridge = Ridge(alpha=alpha).fit(
            scaler.transform(discovery_source[finite_discovery]),
            discovery_target[finite_discovery],
        )
        prediction = ridge.predict(scaler.transform(validation_source[finite_validation]))
        validation_error[alpha] = float(
            np.mean(np.linalg.norm(validation_target[finite_validation] - prediction, axis=1))
        )
    selected = min(alphas, key=validation_error.__getitem__)
    source = np.concatenate(
        (discovery_source[finite_discovery], validation_source[finite_validation]), axis=0
    )
    target = np.concatenate(
        (discovery_target[finite_discovery], validation_target[finite_validation]), axis=0
    )
    final_scaler = StandardScaler().fit(source)
    final = Ridge(alpha=selected).fit(final_scaler.transform(source), target)
    scale = np.asarray(final_scaler.scale_, dtype=np.float64)
    return DevelopmentRidgeMap(
        source_mean=np.asarray(final_scaler.mean_, dtype=np.float64),
        source_scale=np.where(scale > 0.0, scale, 1.0),
        coefficients=np.asarray(final.coef_, dtype=np.float64),
        intercept=np.asarray(final.intercept_, dtype=np.float64),
        alpha=float(selected),
        fit_roles=("discovery", "validation"),
        discovery_samples=int(finite_discovery.sum()),
        validation_samples=int(finite_validation.sum()),
    )


def latent_disequilibrium(
    mapping: DevelopmentRidgeMap, source: FloatArray, target: FloatArray
) -> FloatArray:
    if len(source) != len(target):
        raise ValueError("mapping source and target lengths differ")
    prediction = mapping.predict(source)
    if prediction.shape != target.shape:
        raise ValueError("mapping prediction and target shapes differ")
    return np.linalg.norm(target - prediction, axis=1).astype(np.float64)


def correction_decomposition(
    source: FloatArray,
    target: FloatArray,
    future_source: FloatArray,
    future_target: FloatArray,
    source_to_target: DevelopmentRidgeMap,
    target_to_source: DevelopmentRidgeMap,
) -> dict[str, FloatArray]:
    """Attribute convergence to target-side, source-side, joint, or persistent movement."""
    lengths = {len(source), len(target), len(future_source), len(future_target)}
    if len(lengths) != 1:
        raise ValueError("correction arrays differ in length")
    implied_target = source_to_target.predict(source)
    implied_source = target_to_source.predict(target)
    initial_forward = np.linalg.norm(target - implied_target, axis=1)
    initial_reverse = np.linalg.norm(source - implied_source, axis=1)
    target_progress = initial_forward - np.linalg.norm(future_target - implied_target, axis=1)
    source_progress = initial_reverse - np.linalg.norm(future_source - implied_source, axis=1)
    future_forward = latent_disequilibrium(source_to_target, future_source, future_target)
    future_reverse = latent_disequilibrium(target_to_source, future_target, future_source)
    return {
        "initial_forward": initial_forward,
        "initial_reverse": initial_reverse,
        "future_forward": future_forward,
        "future_reverse": future_reverse,
        "forward_change": future_forward - initial_forward,
        "reverse_change": future_reverse - initial_reverse,
        "target_progress": target_progress,
        "source_progress": source_progress,
        "target_motion": np.linalg.norm(future_target - target, axis=1),
        "source_motion": np.linalg.norm(future_source - source, axis=1),
    }


def classify_corrections(
    correction: dict[str, FloatArray],
    *,
    high_forward: float,
    motion_threshold: float,
) -> NDArray[np.str_]:
    """Classify only initially large forward disequilibria with fixed thresholds."""
    required = {
        "initial_forward",
        "future_forward",
        "target_progress",
        "source_progress",
        "target_motion",
        "source_motion",
    }
    if not required.issubset(correction):
        raise ValueError("correction decomposition is incomplete")
    labels = np.full(len(correction["initial_forward"]), "not_large", dtype="U32")
    large = correction["initial_forward"] >= high_forward
    target_led = large & (correction["target_progress"] > 0.0)
    source_led = large & (correction["source_progress"] > 0.0)
    joint = (
        large
        & target_led
        & source_led
        & (correction["target_motion"] >= motion_threshold)
        & (correction["source_motion"] >= motion_threshold)
    )
    labels[large] = "persistent_disagreement"
    labels[target_led & ~source_led] = "source_led_correction"
    labels[source_led & ~target_led] = "target_led_correction"
    labels[joint] = "joint_information_shock"
    converged = large & (correction["future_forward"] < correction["initial_forward"])
    labels[large & converged & target_led & source_led & ~joint] = "both_correct"
    return labels


def mapping_metadata(mapping: DevelopmentRidgeMap) -> dict[str, Any]:
    return {
        "alpha": mapping.alpha,
        "fit_roles": list(mapping.fit_roles),
        "discovery_samples": mapping.discovery_samples,
        "validation_samples": mapping.validation_samples,
        "source_dimension": int(len(mapping.source_mean)),
        "target_dimension": int(len(mapping.intercept)),
    }
