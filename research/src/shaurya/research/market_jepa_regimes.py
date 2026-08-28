"""Reusable diagnostics for learned high-frequency market-state representations.

The functions in this module are deliberately model-agnostic: callers provide causal
representations aligned to frozen sequence endpoints.  All fitting occurs on explicitly
named discovery/validation arrays; diagnostic sessions are apply-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    balanced_accuracy_score,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


@dataclass(frozen=True)
class ProbeResult:
    selected_alpha: float
    validation_mae: float
    test_mae: float
    constant_mae: float
    mae_skill: float
    r2: float
    balanced_accuracy: float | None
    roc_auc: float | None
    predictions: FloatArray
    losses: FloatArray
    constant_losses: FloatArray


def causal_context_features(values: FloatArray, ends: IntArray, context_steps: int) -> FloatArray:
    """Summarise only observations at or before each sequence endpoint."""
    if context_steps < 12:
        raise ValueError("context_steps must cover at least 60 seconds")
    rows: list[FloatArray] = []
    for end in ends:
        window = values[int(end) - context_steps + 1 : int(end) + 1]
        if len(window) != context_steps:
            raise ValueError("endpoint does not have a complete causal context")
        rows.append(
            np.concatenate(
                (
                    window[-1],
                    window[-1] - window[-7],
                    window[-1] - window[-12],
                    np.mean(window, axis=0),
                    np.std(window, axis=0),
                )
            )
        )
    return np.asarray(rows, dtype=np.float64)


def flattened_context(values: FloatArray, ends: IntArray, context_steps: int) -> FloatArray:
    return np.stack(
        [values[int(end) - context_steps + 1 : int(end) + 1].reshape(-1) for end in ends]
    ).astype(np.float64)


def downstream_targets(
    raw: FloatArray,
    ends: IntArray,
    columns: list[str],
    horizon_steps: int,
) -> dict[str, FloatArray]:
    """Construct causal-at-t targets whose right edge is t + horizon_steps."""
    index = {name: position for position, name in enumerate(columns)}
    future = raw[:, index["futures_log_mid"]]
    straddle = raw[:, index["atm_near_straddle_to_future"]]
    atm_iv = raw[:, index["surface__atm_iv__near"]]
    call_spread_index = index["atm__option_relative_spread__near__CE"]
    put_spread_index = index["atm__option_relative_spread__near__PE"]
    current = ends
    future_rows = ends + horizon_steps
    future_return = future[future_rows] - future[current]
    straddle_change = straddle[future_rows] - straddle[current]
    iv_change = atm_iv[future_rows] - atm_iv[current]
    current_spread = 0.5 * (raw[current, call_spread_index] + raw[current, put_spread_index])
    later_spread = 0.5 * (raw[future_rows, call_spread_index] + raw[future_rows, put_spread_index])
    one_step = np.diff(future, prepend=future[0])
    realised = np.asarray(
        [
            np.sqrt(np.square(one_step[int(end) + 1 : int(end) + horizon_steps + 1]).sum())
            for end in ends
        ]
    )
    surface_names = [
        name
        for name in columns
        if name.startswith("surface__")
        and not name.startswith("surface__quote_count")
        and not name.startswith("surface__median_relative_spread")
    ]
    surface_indices = [index[name] for name in surface_names]
    surface_change = raw[future_rows][:, surface_indices] - raw[current][:, surface_indices]
    surface_displacement = np.sqrt(np.nanmean(np.square(surface_change), axis=1))
    return {
        "signed_futures_return": future_return,
        "absolute_futures_return": np.abs(future_return),
        "realized_futures_volatility": realised,
        "signed_atm_straddle_change": straddle_change,
        "absolute_atm_straddle_change": np.abs(straddle_change),
        "near_atm_spread_change": later_spread - current_spread,
        "signed_atm_iv_change": iv_change,
        "absolute_atm_iv_change": np.abs(iv_change),
        "surface_displacement": surface_displacement,
    }


def _finite_rows(features: FloatArray, target: FloatArray) -> NDArray[np.bool_]:
    mask = np.isfinite(target) & np.all(np.isfinite(features), axis=1)
    return cast(NDArray[np.bool_], mask)


def fit_ridge_probe(
    discovery_features: FloatArray,
    validation_features: FloatArray,
    test_features: FloatArray,
    discovery_target: FloatArray,
    validation_target: FloatArray,
    test_target: FloatArray,
    *,
    signed: bool,
    alphas: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0, 1000.0),
) -> ProbeResult:
    """Select regularisation on validation and evaluate once on an apply-only session."""
    discovery_mask = _finite_rows(discovery_features, discovery_target)
    validation_mask = _finite_rows(validation_features, validation_target)
    test_mask = _finite_rows(test_features, test_target)
    if min(discovery_mask.sum(), validation_mask.sum(), test_mask.sum()) < 50:
        raise ValueError("insufficient finite rows for probe")
    validation_mae: dict[float, float] = {}
    for alpha in alphas:
        model = Pipeline((("scale", StandardScaler()), ("ridge", Ridge(alpha=alpha)))).fit(
            discovery_features[discovery_mask], discovery_target[discovery_mask]
        )
        prediction = model.predict(validation_features[validation_mask])
        validation_mae[alpha] = float(
            mean_absolute_error(validation_target[validation_mask], prediction)
        )
    selected = min(alphas, key=validation_mae.__getitem__)
    development_features = np.concatenate(
        (discovery_features[discovery_mask], validation_features[validation_mask])
    )
    development_target = np.concatenate(
        (discovery_target[discovery_mask], validation_target[validation_mask])
    )
    model = Pipeline((("scale", StandardScaler()), ("ridge", Ridge(alpha=selected)))).fit(
        development_features, development_target
    )
    prediction = model.predict(test_features[test_mask]).astype(np.float64)
    actual = test_target[test_mask]
    constant = np.full_like(actual, np.median(development_target))
    losses = np.abs(actual - prediction)
    constant_losses = np.abs(actual - constant)
    constant_mae = float(constant_losses.mean())
    balanced: float | None = None
    auc: float | None = None
    if signed and len(np.unique(actual > 0.0)) == 2:
        labels = actual > 0.0
        balanced = float(balanced_accuracy_score(labels, prediction > 0.0))
        auc = float(roc_auc_score(labels, prediction))
    return ProbeResult(
        selected_alpha=selected,
        validation_mae=validation_mae[selected],
        test_mae=float(losses.mean()),
        constant_mae=constant_mae,
        mae_skill=1.0 - float(losses.mean()) / constant_mae,
        r2=float(r2_score(actual, prediction)),
        balanced_accuracy=balanced,
        roc_auc=auc,
        predictions=prediction,
        losses=losses,
        constant_losses=constant_losses,
    )


def probe_to_dict(result: ProbeResult) -> dict[str, Any]:
    return {
        "selected_alpha": result.selected_alpha,
        "validation_mae": result.validation_mae,
        "test_mae": result.test_mae,
        "constant_mae": result.constant_mae,
        "mae_skill": result.mae_skill,
        "r2": result.r2,
        "balanced_accuracy": result.balanced_accuracy,
        "roc_auc": result.roc_auc,
        "samples": int(len(result.losses)),
    }


def pca_representations(
    discovery: FloatArray,
    validation: FloatArray,
    tests: dict[str, FloatArray],
    components: int = 32,
) -> tuple[FloatArray, FloatArray, dict[str, FloatArray], dict[str, Any]]:
    count = min(components, discovery.shape[0] - 1, discovery.shape[1])
    model = PCA(n_components=count, random_state=0).fit(discovery)
    return (
        model.transform(discovery),
        model.transform(validation),
        {name: model.transform(values) for name, values in tests.items()},
        {
            "components": count,
            "explained_variance": float(model.explained_variance_ratio_.sum()),
            "curve": model.explained_variance_ratio_.tolist(),
        },
    )


def random_projection(features: FloatArray, matrix: FloatArray) -> FloatArray:
    return (features @ matrix).astype(np.float64)


def representation_diagnostics(embedding: FloatArray) -> dict[str, Any]:
    centered = embedding - embedding.mean(axis=0, keepdims=True)
    singular = np.linalg.svd(centered, compute_uv=False)
    probabilities = singular / max(float(singular.sum()), 1e-12)
    rank = float(np.exp(-(probabilities * np.log(probabilities + 1e-12)).sum()))
    norms = np.linalg.norm(embedding, axis=1, keepdims=True)
    unit = embedding / np.maximum(norms, 1e-12)
    adjacent_cosine = np.sum(unit[1:] * unit[:-1], axis=1)
    return {
        "embedding_dimension": int(embedding.shape[1]),
        "effective_rank": rank,
        "mean_dimension_std": float(embedding.std(axis=0).mean()),
        "minimum_dimension_std": float(embedding.std(axis=0).min()),
        "adjacent_cosine_median": float(np.median(adjacent_cosine)),
        "adjacent_cosine_p05": float(np.quantile(adjacent_cosine, 0.05)),
        "adjacent_cosine_p95": float(np.quantile(adjacent_cosine, 0.95)),
    }


def fit_regimes(discovery_embedding: FloatArray, clusters: int, seed: int) -> KMeans:
    return KMeans(n_clusters=clusters, random_state=seed, n_init=20).fit(discovery_embedding)


def regime_statistics(
    labels: IntArray,
    raw: FloatArray,
    ends: IntArray,
    columns: list[str],
) -> list[dict[str, Any]]:
    index = {name: position for position, name in enumerate(columns)}
    names = [
        "futures_realized_volatility_30s",
        "futures_relative_spread",
        "futures_depth_imbalance",
        "futures_microprice_dislocation",
        "atm_near_straddle_to_future",
        "surface__atm_iv__near",
        "surface__variance_skew__near",
        "surface__variance_curvature__near",
        "surface__fit_rmse_iv__near",
        "surface__parity_residual_rms_to_forward__far",
    ]
    output: list[dict[str, Any]] = []
    for label in sorted(np.unique(labels)):
        mask = labels == label
        output.append(
            {
                "regime": int(label),
                "samples": int(mask.sum()),
                "share": float(mask.mean()),
                "means": {name: float(np.nanmean(raw[ends[mask], index[name]])) for name in names},
            }
        )
    return output


def transition_statistics(labels: IntArray, clusters: int) -> dict[str, Any]:
    counts = np.zeros((clusters, clusters), dtype=np.int64)
    for left, right in zip(labels[:-1], labels[1:], strict=True):
        counts[int(left), int(right)] += 1
    probabilities = counts / np.maximum(counts.sum(axis=1, keepdims=True), 1)
    runs: list[int] = []
    start = 0
    for position in range(1, len(labels) + 1):
        if position == len(labels) or labels[position] != labels[start]:
            runs.append(position - start)
            start = position
    return {
        "counts": counts.tolist(),
        "probabilities": probabilities.tolist(),
        "median_duration_seconds": float(np.median(runs) * 5.0),
        "mean_duration_seconds": float(np.mean(runs) * 5.0),
    }


def transition_shock(embedding: FloatArray, lag_steps: int) -> FloatArray:
    shock = np.full(len(embedding), np.nan, dtype=np.float64)
    shock[lag_steps:] = np.linalg.norm(embedding[lag_steps:] - embedding[:-lag_steps], axis=1)
    return shock


def shock_correlations(
    shock: FloatArray, targets: dict[str, FloatArray]
) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for name, target in targets.items():
        if not (
            name.startswith("absolute")
            or name in {"realized_futures_volatility", "surface_displacement"}
        ):
            continue
        mask = np.isfinite(shock) & np.isfinite(target)
        correlation = spearmanr(shock[mask], target[mask]).statistic
        output[name] = float(correlation) if np.isfinite(correlation) else None
    return output


def block_bootstrap_increment(
    base_losses: FloatArray,
    augmented_losses: FloatArray,
    *,
    block_rows: int = 12,
    draws: int = 2000,
    seed: int = 20260828,
) -> dict[str, float]:
    """Bootstrap the paired MAE reduction using contiguous one-minute blocks."""
    if len(base_losses) != len(augmented_losses):
        raise ValueError("paired losses differ in length")
    difference = base_losses - augmented_losses
    blocks = [
        difference[start : start + block_rows] for start in range(0, len(difference), block_rows)
    ]
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=np.float64)
    for draw in range(draws):
        chosen = rng.integers(0, len(blocks), size=len(blocks))
        estimates[draw] = np.concatenate([blocks[index] for index in chosen]).mean()
    return {
        "mean_mae_reduction": float(difference.mean()),
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "positive_probability": float(np.mean(estimates > 0.0)),
        "block_rows": block_rows,
        "draws": draws,
    }
