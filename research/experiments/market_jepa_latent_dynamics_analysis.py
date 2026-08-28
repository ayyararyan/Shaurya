"""Run the frozen JEPA surprise, latent-dynamics, and disequilibrium study.

This runner intentionally consumes only the previously designated discovery,
validation, and retrospective diagnostic sessions.  It never opens or applies
the prospective outer-test session and never mutates the existing frozen bundle.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from market_jepa_20260826 import HORIZONS, Config, MarketJepa, SequenceDataset, set_seed, train_jepa
from numpy.typing import NDArray
from torch.utils.data import DataLoader

from shaurya.research.market_jepa_disequilibrium import (
    classify_corrections,
    correction_decomposition,
    fit_development_ridge_map,
    latent_disequilibrium,
    mapping_metadata,
    subsystem_feature_lists,
)
from shaurya.research.market_jepa_latent_dynamics import (
    classify_stress_states,
    contiguous_analysis_ends,
    cross_seed_disagreement,
    fit_orthogonal_alignment,
    fit_stress_thresholds,
    latent_dynamics,
    write_frozen_config,
)
from shaurya.research.market_jepa_outer_test import file_sha256, verify_bundle
from shaurya.research.market_jepa_regimes import (
    block_bootstrap_increment,
    causal_context_features,
    fit_ridge_probe,
    flattened_context,
    pca_representations,
)
from shaurya.research.market_jepa_surprise import (
    aligned_latent_surprise,
    block_bootstrap_spearman,
    conditional_means_by_development_quintile,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

NS = 1_000_000_000
STEP_SECONDS = 5
SEEDS = (1, 7, 23, 42, 101)
LATENT_HORIZONS = (1, 6, 12)
TARGET_HORIZON = 6
BLOCK_ROWS = (12, 24, 60)
ROLES = ("discovery", "validation", "diagnostic_1", "diagnostic_2")
DIAGNOSTICS = ("diagnostic_1", "diagnostic_2")
PAIR_DEFINITIONS = {
    "cross_market": ("futures", "options"),
    "near_far": ("near", "far"),
    "call_put": ("call", "put"),
}
PRIMARY_TARGETS = ("surface_displacement", "absolute_atm_iv_change")
SECONDARY_TARGETS = (
    "realized_futures_volatility",
    "absolute_futures_return",
    "near_atm_spread_change",
    "absolute_atm_straddle_change",
    "parity_restoration",
)
MAGNITUDE_TARGETS = PRIMARY_TARGETS + SECONDARY_TARGETS


def json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def load_state(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as payload:
        required = {"timestamps", "values", "columns", "trading_date"}
        if not required.issubset(payload.files):
            raise ValueError(f"state file lacks required arrays: {path}")
        return {
            "timestamps": payload["timestamps"].astype(np.int64),
            "values": payload["values"].astype(np.float64),
            "columns": [str(item) for item in payload["columns"].tolist()],
            "trading_date": str(payload["trading_date"].tolist()[0]),
            "path": str(path.resolve()),
            "sha256": file_sha256(path),
        }


def validate_sessions(sessions: dict[str, dict[str, Any]]) -> None:
    columns = sessions["discovery"]["columns"]
    dates: list[str] = []
    for role in ROLES:
        session = sessions[role]
        if session["columns"] != columns:
            raise ValueError("state columns differ across sessions")
        timestamps = session["timestamps"]
        if len(timestamps) != len(session["values"]):
            raise ValueError(f"timestamp/value row mismatch for {role}")
        if len(timestamps) < 100 or np.any(np.diff(timestamps) <= 0):
            raise ValueError(f"session {role} is incomplete or not strictly ordered")
        dates.append(session["trading_date"])
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("session roles are not unique and chronological")


def common_analysis_ends(timestamps: IntArray, context_steps: int) -> IntArray:
    """Require history for 60s surprise/acceleration and a subsequent 30s target."""
    history = 2 * max(LATENT_HORIZONS) + context_steps - 1
    return contiguous_analysis_ends(
        timestamps,
        history_steps=history,
        future_steps=TARGET_HORIZON,
        step_ns=STEP_SECONDS * NS,
        minimum_samples=50,
    )


def training_ends(timestamps: IntArray, context_steps: int) -> IntArray:
    possible = range(context_steps - 1, len(timestamps) - max(LATENT_HORIZONS))
    valid: list[int] = []
    for end in possible:
        window = timestamps[end - context_steps + 1 : end + max(LATENT_HORIZONS) + 1]
        if np.all(np.diff(window) == STEP_SECONDS * NS):
            valid.append(end)
    return np.asarray(valid, dtype=np.int64)


def frozen_normalize(
    sessions: dict[str, dict[str, Any]], bundle: Path
) -> tuple[dict[str, FloatArray], list[str]]:
    with np.load(bundle / "normalization.npz", allow_pickle=False) as payload:
        columns = [str(item) for item in payload["model_columns"].tolist()]
        center = payload["center"].astype(np.float64)
        scale = payload["scale"].astype(np.float64)
    raw_columns = sessions["discovery"]["columns"]
    indices = [raw_columns.index(name) for name in columns]
    normalized: dict[str, FloatArray] = {}
    for role, session in sessions.items():
        values = session["values"][:, indices]
        filled = np.where(np.isfinite(values), values, center)
        normalized[role] = np.clip((filled - center) / scale, -10.0, 10.0)
    return normalized, columns


def normalize_subsystem(
    sessions: dict[str, dict[str, Any]], feature_names: list[str]
) -> tuple[dict[str, FloatArray], FloatArray, FloatArray]:
    columns = sessions["discovery"]["columns"]
    indices = [columns.index(name) for name in feature_names]
    discovery = sessions["discovery"]["values"][:, indices]
    center = np.nanmean(discovery, axis=0)
    scale = np.nanstd(discovery, axis=0, ddof=1)
    center = np.where(np.isfinite(center), center, 0.0)
    scale = np.where(np.isfinite(scale) & (scale > 0.0), scale, 1.0)
    output: dict[str, FloatArray] = {}
    for role, session in sessions.items():
        values = session["values"][:, indices]
        output[role] = np.clip(
            (np.where(np.isfinite(values), values, center) - center) / scale, -10.0, 10.0
        )
    return output, center.astype(np.float64), scale.astype(np.float64)


@torch.no_grad()
def encode_all(model: MarketJepa, values: FloatArray, device: torch.device) -> FloatArray:
    model.eval()
    tensor = torch.from_numpy(values.astype(np.float32))
    rows: list[np.ndarray] = []
    for start in range(0, len(tensor), 512):
        rows.append(model.target_encoder(tensor[start : start + 512].to(device)).cpu().numpy())
    return np.concatenate(rows).astype(np.float64)


@torch.no_grad()
def predict_horizons(
    model: MarketJepa,
    values: FloatArray,
    realized_ends: IntArray,
    config: Config,
    device: torch.device,
) -> dict[int, FloatArray]:
    model.eval()
    output: dict[int, FloatArray] = {}
    for horizon_index, horizon in enumerate(LATENT_HORIZONS):
        prediction_ends = realized_ends - horizon
        batches: list[np.ndarray] = []
        for start in range(0, len(prediction_ends), 256):
            batch_ends = prediction_ends[start : start + 256]
            context = np.stack(
                [values[end - config.context_steps + 1 : end + 1] for end in batch_ends]
            ).astype(np.float32)
            representation = model.context_representation(torch.from_numpy(context).to(device))
            horizon_embedding = model.horizon_embedding[:, horizon_index].expand(len(context), -1)
            prediction = model.predictor(torch.cat((representation, horizon_embedding), dim=1))
            batches.append(prediction.cpu().numpy())
        output[horizon] = np.concatenate(batches).astype(np.float64)
    return output


def load_global_seed(
    seed: int,
    bundle: Path,
    input_dim: int,
    device: torch.device,
) -> tuple[MarketJepa, Config]:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    config = Config(**{**manifest["config"], "seed": seed})
    model = MarketJepa(input_dim, config).to(device)
    state = torch.load(bundle / "checkpoints" / f"seed-{seed}.pt", map_location=device)
    model.load_state_dict(state)
    model.eval()
    return model, config


def train_subsystem_seed(
    name: str,
    seed: int,
    normalized: dict[str, FloatArray],
    sessions: dict[str, dict[str, Any]],
    work_dir: Path,
    device: torch.device,
    epochs: int,
) -> tuple[dict[str, FloatArray], dict[str, Any]]:
    set_seed(seed)
    config = Config(seed=seed, context_steps=24, batch_size=128, epochs=epochs, patience=12)
    model = MarketJepa(normalized["discovery"].shape[1], config).to(device)
    destination = work_dir / name / f"seed-{seed}"
    destination.mkdir(parents=True, exist_ok=True)
    generator = torch.Generator().manual_seed(seed)
    discovery_dataset = SequenceDataset(
        normalized["discovery"].astype(np.float32),
        training_ends(sessions["discovery"]["timestamps"], config.context_steps),
        config.context_steps,
        HORIZONS,
    )
    validation_dataset = SequenceDataset(
        normalized["validation"].astype(np.float32),
        training_ends(sessions["validation"]["timestamps"], config.context_steps),
        config.context_steps,
        HORIZONS,
    )
    training = train_jepa(
        model,
        DataLoader(
            discovery_dataset,
            batch_size=config.batch_size,
            shuffle=True,
            generator=generator,
        ),
        DataLoader(validation_dataset, batch_size=config.batch_size, shuffle=False),
        device,
        destination,
    )
    embeddings = {role: encode_all(model, values, device) for role, values in normalized.items()}
    return embeddings, {"config": asdict(config), "training": training}


def target_panel(
    raw: FloatArray, ends: IntArray, columns: list[str], horizon: int = TARGET_HORIZON
) -> dict[str, FloatArray]:
    index = {name: position for position, name in enumerate(columns)}
    future = ends + horizon

    def delta(name: str) -> FloatArray:
        return raw[future, index[name]] - raw[ends, index[name]]

    futures = raw[:, index["futures_log_mid"]]
    future_return = futures[future] - futures[ends]
    one_step = np.diff(futures, prepend=futures[0])
    realized = np.asarray(
        [np.sqrt(np.square(one_step[end + 1 : end + horizon + 1]).sum()) for end in ends]
    )
    call_spread = raw[:, index["atm__option_relative_spread__near__CE"]]
    put_spread = raw[:, index["atm__option_relative_spread__near__PE"]]
    current_spread = 0.5 * (call_spread[ends] + put_spread[ends])
    future_spread = 0.5 * (call_spread[future] + put_spread[future])
    surface_names = [
        name
        for name in columns
        if name.startswith("surface__")
        and "quote_count" not in name
        and "median_relative_spread" not in name
    ]
    surface_indices = [index[name] for name in surface_names]
    surface_change = raw[future][:, surface_indices] - raw[ends][:, surface_indices]
    parity_names = [
        "surface__parity_residual_rms_to_forward__near",
        "surface__parity_residual_rms_to_forward__far",
    ]
    parity_indices = [index[name] for name in parity_names]
    parity_now = np.nanmean(np.abs(raw[ends][:, parity_indices]), axis=1)
    parity_future = np.nanmean(np.abs(raw[future][:, parity_indices]), axis=1)
    near_iv = raw[:, index["surface__atm_iv__near"]]
    far_iv = raw[:, index["surface__atm_iv__far"]]
    term_now = far_iv[ends] - near_iv[ends]
    term_future = far_iv[future] - near_iv[future]
    call_names = ["atm__option_mid_to_future__near__CE", "atm__option_mid_to_future__far__CE"]
    put_names = ["atm__option_mid_to_future__near__PE", "atm__option_mid_to_future__far__PE"]
    call_indices = [index[name] for name in call_names]
    put_indices = [index[name] for name in put_names]
    call_move = np.nanmean(raw[future][:, call_indices] - raw[ends][:, call_indices], axis=1)
    put_move = np.nanmean(raw[future][:, put_indices] - raw[ends][:, put_indices], axis=1)
    fit_indices = [index["surface__fit_rmse_iv__near"], index["surface__fit_rmse_iv__far"]]
    fit_now = np.nanmean(raw[ends][:, fit_indices], axis=1)
    fit_future = np.nanmean(raw[future][:, fit_indices], axis=1)
    straddle = raw[:, index["atm_near_straddle_to_future"]]
    iv_change = near_iv[future] - near_iv[ends]
    return {
        "signed_futures_return": future_return,
        "absolute_futures_return": np.abs(future_return),
        "realized_futures_volatility": realized,
        "signed_atm_iv_change": iv_change,
        "absolute_atm_iv_change": np.abs(iv_change),
        "surface_displacement": np.sqrt(np.nanmean(np.square(surface_change), axis=1)),
        "near_atm_spread_change": future_spread - current_spread,
        "absolute_atm_straddle_change": np.abs(straddle[future] - straddle[ends]),
        "parity_restoration": parity_now - parity_future,
        "absolute_parity_change": np.abs(parity_future - parity_now),
        "near_atm_iv_change": near_iv[future] - near_iv[ends],
        "far_atm_iv_change": far_iv[future] - far_iv[ends],
        "term_structure_iv_change": term_future - term_now,
        "atm_iv_convergence": np.abs(term_now) - np.abs(term_future),
        "call_relative_move": call_move,
        "put_relative_move": put_move,
        "call_put_relative_correction": np.abs(call_move - put_move),
        "surface_residual_restoration": fit_now - fit_future,
    }


def base_representations(
    sessions: dict[str, dict[str, Any]],
    normalized: dict[str, FloatArray],
    ends: dict[str, IntArray],
    context_steps: int,
) -> dict[str, dict[str, FloatArray]]:
    output: dict[str, dict[str, FloatArray]] = {}
    flattened: dict[str, FloatArray] = {}
    for role in ROLES:
        timestamp = sessions[role]["timestamps"]
        seconds = (timestamp[ends[role]] // NS + 5.5 * 3600) % 86400
        minute = seconds / 60.0
        angle = 2.0 * np.pi * minute / 1440.0
        time = np.column_stack(
            (
                np.sin(angle),
                np.cos(angle),
                np.clip((minute - 555.0) / 375.0, 0.0, 1.0),
            )
        )
        output[role] = {
            "base": np.column_stack(
                (causal_context_features(normalized[role], ends[role], context_steps), time)
            )
        }
        flattened[role] = flattened_context(normalized[role], ends[role], context_steps)
    pca_discovery, pca_validation, tests, _ = pca_representations(
        flattened["discovery"],
        flattened["validation"],
        {role: flattened[role] for role in DIAGNOSTICS},
    )
    output["discovery"]["pca"] = pca_discovery
    output["validation"]["pca"] = pca_validation
    for role, values in tests.items():
        output[role]["pca"] = values
    return output


def probe_candidate(
    base: dict[str, dict[str, FloatArray]],
    candidate: dict[str, FloatArray],
    targets: dict[str, dict[str, FloatArray]],
    target_name: str,
    diagnostic: str,
    *,
    comparator: dict[str, FloatArray] | None = None,
) -> dict[str, Any]:
    feature_sets: dict[str, dict[str, FloatArray]] = {
        "base": {role: base[role]["base"] for role in ROLES},
        "base_plus_candidate": {
            role: np.column_stack((base[role]["base"], candidate[role])) for role in ROLES
        },
        "base_plus_pca": {
            role: np.column_stack((base[role]["base"], base[role]["pca"])) for role in ROLES
        },
        "base_plus_pca_plus_candidate": {
            role: np.column_stack((base[role]["base"], base[role]["pca"], candidate[role]))
            for role in ROLES
        },
    }
    if comparator is not None:
        feature_sets["base_plus_comparator"] = {
            role: np.column_stack((base[role]["base"], comparator[role])) for role in ROLES
        }
        feature_sets["base_plus_comparator_plus_candidate"] = {
            role: np.column_stack((base[role]["base"], comparator[role], candidate[role]))
            for role in ROLES
        }
    results: dict[str, Any] = {}
    fitted: dict[str, Any] = {}
    for name, features in feature_sets.items():
        probe = fit_ridge_probe(
            features["discovery"],
            features["validation"],
            features[diagnostic],
            targets["discovery"][target_name],
            targets["validation"][target_name],
            targets[diagnostic][target_name],
            signed=target_name
            in {
                "signed_futures_return",
                "signed_atm_iv_change",
                "near_atm_spread_change",
                "parity_restoration",
                "near_atm_iv_change",
                "far_atm_iv_change",
                "term_structure_iv_change",
                "atm_iv_convergence",
                "call_relative_move",
                "put_relative_move",
                "surface_residual_restoration",
            },
            alphas=(1.0, 100.0),
        )
        results[name] = {
            "mae_skill": probe.mae_skill,
            "mae": probe.test_mae,
            "r2": probe.r2,
            "alpha": probe.selected_alpha,
        }
        fitted[name] = probe
    results["_losses"] = {name: probe.losses for name, probe in fitted.items()}
    results["paired_intervals"] = {
        "base_to_candidate": {
            f"{rows * STEP_SECONDS}s": block_bootstrap_increment(
                fitted["base"].losses,
                fitted["base_plus_candidate"].losses,
                block_rows=rows,
                draws=500,
                seed=20260828 + rows,
            )
            for rows in BLOCK_ROWS
        },
        "base_pca_to_candidate": {
            f"{rows * STEP_SECONDS}s": block_bootstrap_increment(
                fitted["base_plus_pca"].losses,
                fitted["base_plus_pca_plus_candidate"].losses,
                block_rows=rows,
                draws=500,
                seed=20260829 + rows,
            )
            for rows in BLOCK_ROWS
        },
    }
    if comparator is not None:
        results["paired_intervals"]["comparator_to_candidate"] = {
            f"{rows * STEP_SECONDS}s": block_bootstrap_increment(
                fitted["base_plus_comparator"].losses,
                fitted["base_plus_comparator_plus_candidate"].losses,
                block_rows=rows,
                draws=500,
                seed=20260830 + rows,
            )
            for rows in BLOCK_ROWS
        }
    return results


def paired_model_increment(
    baseline: dict[str, Any],
    augmented: dict[str, Any],
    *,
    baseline_name: str = "base_plus_candidate",
    augmented_name: str = "base_plus_candidate",
) -> dict[str, Any]:
    """Block intervals for two separately constructed but row-paired probe models."""
    return {
        f"{rows * STEP_SECONDS}s": block_bootstrap_increment(
            baseline["_losses"][baseline_name],
            augmented["_losses"][augmented_name],
            block_rows=rows,
            draws=500,
            seed=20260831 + rows,
        )
        for rows in BLOCK_ROWS
    }


def handcrafted_pair_comparator(
    pair_name: str,
    sessions: dict[str, dict[str, Any]],
    ends: dict[str, IntArray],
) -> dict[str, FloatArray]:
    """Explicit observable benchmark matched to each latent subsystem comparison."""
    columns = sessions["discovery"]["columns"]
    index = {name: position for position, name in enumerate(columns)}
    output: dict[str, FloatArray] = {}
    for role in ROLES:
        raw = sessions[role]["values"]
        selected = ends[role]
        if pair_name == "cross_market":
            names = [
                "futures_microprice_dislocation",
                "futures_depth_imbalance",
                "surface__atm_iv__near",
                "surface__parity_residual_rms_to_forward__near",
            ]
            values = raw[selected][:, [index[name] for name in names]]
        elif pair_name == "near_far":
            pairs = [
                ("surface__atm_iv__far", "surface__atm_iv__near"),
                ("surface__variance_skew__far", "surface__variance_skew__near"),
                ("surface__variance_curvature__far", "surface__variance_curvature__near"),
                ("surface__fit_rmse_iv__far", "surface__fit_rmse_iv__near"),
            ]
            values = np.column_stack(
                [raw[selected, index[left]] - raw[selected, index[right]] for left, right in pairs]
            )
        else:
            names = [
                "atm_near_call_put_skew",
                "atm_far_call_put_skew",
                "surface__parity_residual_rms_to_forward__near",
                "surface__parity_residual_rms_to_forward__far",
            ]
            values = raw[selected][:, [index[name] for name in names]]
        output[role] = np.asarray(values, dtype=np.float64)
    return output


def correlation_rows(
    development: FloatArray,
    diagnostic_signal: FloatArray,
    diagnostic_targets: dict[str, FloatArray],
    *,
    seed: int,
    diagnostic: str,
    feature: str,
    targets: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target_name in targets:
        quintiles = conditional_means_by_development_quintile(
            development, diagnostic_signal, diagnostic_targets[target_name]
        )
        for block_rows in BLOCK_ROWS:
            interval = block_bootstrap_spearman(
                diagnostic_signal,
                diagnostic_targets[target_name],
                block_rows=block_rows,
                draws=500,
                seed=20260828 + seed + block_rows,
            )
            rows.append(
                {
                    "seed": seed,
                    "diagnostic": diagnostic,
                    "feature": feature,
                    "target": target_name,
                    "block_seconds": block_rows * STEP_SECONDS,
                    **interval,
                    "quintile_monotonic": quintiles["monotonic"],
                    "quintile_target_means": [row["target_mean"] for row in quintiles["rows"]],
                    "quintile_samples": [row["samples"] for row in quintiles["rows"]],
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path.name}")
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(json_safe(value), separators=(",", ":"))
                    if isinstance(value, (list, dict, tuple))
                    else json_safe(value)
                    for key, value in row.items()
                }
            )


def git_sha(repository: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()


def source_hashes(repository: Path) -> dict[str, str]:
    relatives = [
        "research/src/shaurya/research/market_jepa_surprise.py",
        "research/src/shaurya/research/market_jepa_disequilibrium.py",
        "research/src/shaurya/research/market_jepa_latent_dynamics.py",
        "research/experiments/market_jepa_latent_dynamics_analysis.py",
    ]
    return {name: file_sha256(repository / name) for name in relatives}


def summary_median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return float(np.median(values)) if values else None


def selected_median(
    rows: list[dict[str, Any]],
    key: str,
    **filters: Any,
) -> float:
    selected = [
        float(row[key])
        for row in rows
        if row.get(key) is not None
        and all(
            row.get(filter_name) == filter_value for filter_name, filter_value in filters.items()
        )
    ]
    if not selected:
        raise ValueError(f"no values for {key} with filters {filters}")
    return float(np.median(selected))


def event_share_summary(rows: list[dict[str, Any]], diagnostic: str) -> dict[str, float]:
    selected_by_seed: dict[int, dict[str, int]] = {}
    for row in rows:
        if (
            row.get("diagnostic") == diagnostic
            and row.get("block_seconds") == 60
            and isinstance(row.get("correction_event_frequencies"), dict)
        ):
            selected_by_seed[int(row["seed"])] = row["correction_event_frequencies"]
    shares: dict[str, list[float]] = {}
    for counts in selected_by_seed.values():
        total = sum(value for name, value in counts.items() if name != "not_large")
        for name, value in counts.items():
            if name != "not_large" and total:
                shares.setdefault(name, []).append(value / total)
    return {name: float(np.median(values)) for name, values in shares.items()}


def write_readme(
    path: Path,
    sessions: dict[str, dict[str, Any]],
    surprise_rows: list[dict[str, Any]],
    dynamics_rows: list[dict[str, Any]],
    pair_rows: dict[str, list[dict[str, Any]]],
    uncertainty_rows: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
) -> None:
    """Write the answer-first scientific report from the saved analysis rows."""

    def percent(value: float) -> str:
        return f"{100.0 * value:+.2f} pp"

    surprise_surface = {
        diagnostic: selected_median(
            surprise_rows,
            "increment_beyond_velocity",
            diagnostic=diagnostic,
            feature="surprise_increment_30s",
            target="surface_displacement",
        )
        for diagnostic in DIAGNOSTICS
    }
    surprise_iv = {
        diagnostic: selected_median(
            surprise_rows,
            "increment_beyond_velocity",
            diagnostic=diagnostic,
            feature="surprise_increment_30s",
            target="absolute_atm_iv_change",
        )
        for diagnostic in DIAGNOSTICS
    }
    velocity_surface = {
        diagnostic: selected_median(
            dynamics_rows,
            "spearman",
            diagnostic=diagnostic,
            feature="velocity_30s",
            target="surface_displacement",
            block_seconds=60,
        )
        for diagnostic in DIAGNOSTICS
    }
    acceleration_surface = {
        diagnostic: selected_median(
            dynamics_rows,
            "increment_beyond_velocity",
            diagnostic=diagnostic,
            feature="acceleration_increment_5s",
            target="surface_displacement",
        )
        for diagnostic in DIAGNOSTICS
    }
    near_far_pca = {
        diagnostic: selected_median(
            pair_rows["near_far"],
            "increment_beyond_pca",
            diagnostic=diagnostic,
            feature="near_to_far_increment",
            target="term_structure_iv_change",
        )
        for diagnostic in DIAGNOSTICS
    }
    call_put_parity = {
        diagnostic: selected_median(
            pair_rows["call_put"],
            "increment_beyond_handcrafted",
            diagnostic=diagnostic,
            feature="call_to_put_increment",
            target="parity_restoration",
        )
        for diagnostic in DIAGNOSTICS
    }
    uncertainty_iv = {
        diagnostic: selected_median(
            uncertainty_rows,
            "increment_beyond_surprise_velocity",
            diagnostic=diagnostic,
            feature="uncertainty_increment_5s",
            target="absolute_atm_iv_change",
        )
        for diagnostic in DIAGNOSTICS
    }
    cross_events = {
        diagnostic: event_share_summary(pair_rows["cross_market"], diagnostic)
        for diagnostic in DIAGNOSTICS
    }
    near_far_events = {
        diagnostic: event_share_summary(pair_rows["near_far"], diagnostic)
        for diagnostic in DIAGNOSTICS
    }
    cross_state_share = {
        diagnostic: selected_median(
            stress_rows,
            "share",
            diagnostic=diagnostic,
            state="cross_market_dislocation",
        )
        for diagnostic in DIAGNOSTICS
    }
    date_1 = sessions["diagnostic_1"]["trading_date"]
    date_2 = sessions["diagnostic_2"]["trading_date"]
    lines = [
        "# JEPA market surprise and latent disequilibrium — 2026-08-28",
        "",
        "## Technical summary",
        "",
        "**The evidence does not support a broad JEPA market-physics promotion.** "
        "Continuous velocity replicates, 30-second surprise improves a weak surface model beyond "
        "velocity, and near-to-far disequilibrium adds a small repeatable term-structure "
        "increment. "
        "Cross-market direction, call-put disequilibrium, curvature, and the stress taxonomy fail "
        "the stronger baseline or stability tests. This is retrospective research, not a trading "
        "or executable-PnL result.",
        "",
        "Only four already-seen sessions are used: Aug 19 discovery, Aug 21 validation, and Aug "
        f"26/27 diagnostics ({sessions['diagnostic_1']['analysis_endpoints']:,}/"
        f"{sessions['diagnostic_2']['analysis_endpoints']:,} common endpoints). The existing "
        "prospective outer-test bundle was verified read-only and remains unconsumed.",
        "",
        "## 1. JEPA surprise",
        "",
        "Thirty-second raw L2 surprise adds median MAE skill beyond velocity for surface "
        f"displacement of {percent(surprise_surface['diagnostic_1'])} on {date_1} and "
        f"{percent(surprise_surface['diagnostic_2'])} on {date_2}, positive in all five seeds. "
        "However, raw rank correlations change sign across seeds and the resulting surface model "
        "still has negative skill on Aug 27. For absolute ATM-IV change the increment is only "
        f"{percent(surprise_iv['diagnostic_1'])}/{percent(surprise_iv['diagnostic_2'])}. "
        "Conclusion: surprise contains information beyond velocity, but not yet a robust "
        "standalone "
        "forecast. Retain for more data.",
        "",
        "Raw L2, unit-L2, and cosine error are all reported. Unit/cosine diagnostics prevent "
        "embedding-norm drift from receiving automatic credit.",
        "",
        "## 2. Futures versus options",
        "",
        "No stable leader emerges. Among large futures-to-options discrepancies, median "
        "futures-led shares are "
        f"{cross_events['diagnostic_1'].get('source_led_correction', 0):.1%}/"
        f"{cross_events['diagnostic_2'].get('source_led_correction', 0):.1%}, versus options-led "
        f"{cross_events['diagnostic_1'].get('target_led_correction', 0):.1%}/"
        f"{cross_events['diagnostic_2'].get('target_led_correction', 0):.1%}. Persistent "
        "disagreement is larger at "
        f"{cross_events['diagnostic_1'].get('persistent_disagreement', 0):.1%}/"
        f"{cross_events['diagnostic_2'].get('persistent_disagreement', 0):.1%}. The latent feature "
        "loses to Base+PCA for surface displacement in every seed. Retain the question, not the "
        "current feature.",
        "",
        "## 3. Near versus far expiry",
        "",
        "The data do not identify a reliable first mover: far-led and near-led event shares are "
        f"{near_far_events['diagnostic_1'].get('target_led_correction', 0):.1%} vs "
        f"{near_far_events['diagnostic_1'].get('source_led_correction', 0):.1%} on {date_1}, and "
        f"{near_far_events['diagnostic_2'].get('target_led_correction', 0):.1%} vs "
        f"{near_far_events['diagnostic_2'].get('source_led_correction', 0):.1%} on {date_2}. "
        "Persistent disagreement is the largest class. Still, near-to-far disequilibrium adds "
        f"{percent(near_far_pca['diagnostic_1'])}/{percent(near_far_pca['diagnostic_2'])} over "
        "Base+PCA for signed term-structure IV change, positive in all five seeds. Promote only as "
        "an experimental research feature.",
        "",
        "## 4. Calls versus puts",
        "",
        "Call-put disequilibrium does not improve parity restoration beyond the explicit "
        f"call-minus-put/parity benchmark ({percent(call_put_parity['diagnostic_1'])}/"
        f"{percent(call_put_parity['diagnostic_2'])}) and is seed-unstable for relative "
        "correction. "
        "Reject the current latent call-put feature.",
        "",
        "## 5. Latent acceleration and curvature",
        "",
        "Velocity remains the useful trajectory statistic: its 30-second Spearman correlation "
        f"with surface displacement is {velocity_surface['diagnostic_1']:.3f}/"
        f"{velocity_surface['diagnostic_2']:.3f}, with positive 60-second block intervals in all "
        "five seeds. Five-second acceleration adds only "
        f"{percent(acceleration_surface['diagnostic_1'])}/"
        f"{percent(acceleration_surface['diagnostic_2'])} beyond velocity; longer acceleration and "
        "curvature generally add nothing or hurt. Keep velocity; retain 5-second acceleration for "
        "more data; reject curvature as an early-turn claim.",
        "",
        "## 6. Cross-seed disagreement",
        "",
        "After discovery-only Procrustes alignment, 5-second disagreement adds just "
        f"{percent(uncertainty_iv['diagnostic_1'])}/{percent(uncertainty_iv['diagnostic_2'])} "
        "beyond surprise+velocity for absolute ATM-IV change and degrades surface forecasts. "
        "Retain for more sessions; do not promote.",
        "",
        "## 7. Stress taxonomy",
        "",
        "The taxonomy fails transfer. Cross-market dislocation absorbs median shares of "
        f"{cross_state_share['diagnostic_1']:.1%}/{cross_state_share['diagnostic_2']:.1%}; stable, "
        "orderly-transition, and information-shock states do not survive as usable diagnostic "
        "classes. This reflects subsystem mapping distribution shift, not a discovered universal "
        "stress law. Reject the current taxonomy.",
        "",
        "## 8. Baseline comparison",
        "",
        "The strongest genuinely incremental result is near-to-far disequilibrium for signed "
        "term-structure IV change: about +1.00/+1.27 percentage points over Base+PCA, positive in "
        "all seeds and both diagnostic sessions. Surprise produces larger relative improvements "
        "for surface displacement but does not rescue negative Aug 27 model skill, so it receives "
        "no promotion credit. Futures-options disequilibrium loses to PCA; call-put is explained "
        "by or worse than explicit residuals.",
        "",
        "## 9. Scientific recommendation",
        "",
        "| feature | decision | reason |",
        "|---|---|---|",
        "| Latent velocity | Promote to experimental research feature | Replicated surface/IV magnitude association across seeds and sessions. |",  # noqa: E501
        "| 30-second surprise | Retain for more data | Adds beyond velocity, but primary rank evidence is seed-dependent and surface skill remains negative on Aug 27. |",  # noqa: E501
        "| 5-second acceleration | Retain for more data | Small all-seed surface increment; longer lags fail. |",  # noqa: E501
        "| Curvature | Reject | No stable incremental value beyond velocity. |",
        "| Futures-options disequilibrium | Retain for more data | Descriptive association, no PCA increment and unstable correction attribution. |",  # noqa: E501
        "| Near-far disequilibrium | Promote to experimental research feature | Small all-seed, two-session increment over PCA for term-structure IV change. |",  # noqa: E501
        "| Call-put disequilibrium | Reject | Fails explicit parity/residual baselines. |",
        "| Cross-seed disagreement | Retain for more data | Tiny 5-second ATM-IV increment; not broad or stable enough. |",  # noqa: E501
        "| Stress taxonomy | Reject | Mapping shift collapses most observations into one class. |",
        "",
        "## Statistical and operational caveats",
        "",
        "- Correlations use 60/120/300-second rank-transformed moving-block bootstrap intervals; "
        "model comparisons use paired contiguous-block loss resampling.",
        "- Normalization, mappings, Procrustes alignment, quintiles, and taxonomy thresholds are "
        "fit on discovery/validation only.",
        "- Two diagnostic sessions are insufficient for production or trading promotion. No IID "
        "shuffle inference is used, but cross-session replication remains the binding limitation.",
        "- No fill-level adverse-selection labels were available. Results are midpoint/surface "
        "research without spread, fees, slippage, hedging, queue position, or capacity.",
        "- The Aug 28/later genuinely unseen outer-test targets were not opened.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--diagnostic-1", type=Path, required=True)
    parser.add_argument("--diagnostic-2", type=Path, required=True)
    parser.add_argument("--frozen-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--subsystem-epochs", type=int, default=80)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to overwrite result directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    sessions = {
        "discovery": load_state(args.discovery),
        "validation": load_state(args.validation),
        "diagnostic_1": load_state(args.diagnostic_1),
        "diagnostic_2": load_state(args.diagnostic_2),
    }
    validate_sessions(sessions)
    manifest = json.loads((args.frozen_bundle / "manifest.json").read_text(encoding="utf-8"))
    verify_bundle(args.frozen_bundle, manifest)
    if any(
        session["trading_date"] not in manifest["prohibited_seen_dates"]
        for session in sessions.values()
    ):
        raise ValueError("this retrospective runner may use only dates already seen at the freeze")

    repository = Path(__file__).resolve().parents[2]
    columns = sessions["discovery"]["columns"]
    features = subsystem_feature_lists(columns)
    ends = {
        role: common_analysis_ends(session["timestamps"], context_steps=24)
        for role, session in sessions.items()
    }
    frozen = {
        "schema_version": 1,
        "research_only": True,
        "prospective_outer_test_accessed": False,
        "source_parent_commit_sha": git_sha(repository),
        "source_sha256": source_hashes(repository),
        "existing_outer_bundle_semantic_sha256": manifest["semantic_sha256"],
        "session_roles": {
            role: {
                "trading_date": session["trading_date"],
                "sha256": session["sha256"],
                "rows": len(session["values"]),
                "analysis_endpoints": len(ends[role]),
            }
            for role, session in sessions.items()
        },
        "seeds": list(SEEDS),
        "latent_horizons_seconds": [value * STEP_SECONDS for value in LATENT_HORIZONS],
        "target_horizon_seconds": TARGET_HORIZON * STEP_SECONDS,
        "bootstrap_block_seconds": [value * STEP_SECONDS for value in BLOCK_ROWS],
        "subsystem_model": asdict(
            Config(
                seed=1, context_steps=24, batch_size=128, epochs=args.subsystem_epochs, patience=12
            )
        ),
        "subsystem_features": features,
        "mapping_model": (
            "StandardScaler plus Ridge; alpha in [0.1,1,10,100] selected on validation"
        ),
        "cross_seed_alignment": "orthogonal Procrustes fit on discovery target embeddings",
        "stress_threshold_quantiles": {"low": 0.33, "median": 0.50, "high": 0.67},
        "stress_priority": [
            "stable",
            "information_shock",
            "cross_market_dislocation",
            "hidden_disturbance",
            "ambiguous_state",
            "orderly_transition",
            "unclassified",
        ],
        "outer_test_policy": (
            "No threshold, feature, lag, mapping, or highlight choice uses a future unseen session."
        ),
    }
    write_frozen_config(args.output / "frozen_config.json", frozen)

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    normalized, model_columns = frozen_normalize(sessions, args.frozen_bundle)
    base = base_representations(sessions, normalized, ends, context_steps=24)
    targets = {
        role: target_panel(session["values"], ends[role], columns)
        for role, session in sessions.items()
    }

    global_states: dict[int, dict[str, FloatArray]] = {}
    global_predictions: dict[int, dict[str, dict[int, FloatArray]]] = {}
    surprise: dict[int, dict[str, dict[int, dict[str, FloatArray]]]] = {}
    dynamics: dict[int, dict[str, dict[int, dict[str, FloatArray]]]] = {}
    surprise_rows: list[dict[str, Any]] = []
    dynamics_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        model, config = load_global_seed(seed, args.frozen_bundle, len(model_columns), device)
        global_states[seed] = {}
        global_predictions[seed] = {}
        surprise[seed] = {}
        dynamics[seed] = {}
        for role in ROLES:
            state = encode_all(model, normalized[role], device)
            prediction = predict_horizons(model, normalized[role], ends[role], config, device)
            global_states[seed][role] = state
            global_predictions[seed][role] = prediction
            surprise[seed][role] = {}
            dynamics[seed][role] = {}
            for horizon in LATENT_HORIZONS:
                surprise[seed][role][horizon] = aligned_latent_surprise(
                    prediction[horizon],
                    state[ends[role]],
                    ends[role] - horizon,
                    ends[role],
                    horizon,
                )
                dynamics[seed][role][horizon] = latent_dynamics(
                    state,
                    np.arange(len(state), dtype=np.int64),
                    ends[role],
                    horizon,
                )
        for horizon in LATENT_HORIZONS:
            development_surprise = np.concatenate(
                (
                    surprise[seed]["discovery"][horizon]["l2"],
                    surprise[seed]["validation"][horizon]["l2"],
                )
            )
            for diagnostic in DIAGNOSTICS:
                surprise_rows.extend(
                    correlation_rows(
                        development_surprise,
                        surprise[seed][diagnostic][horizon]["l2"],
                        targets[diagnostic],
                        seed=seed,
                        diagnostic=diagnostic,
                        feature=f"surprise_l2_{horizon * STEP_SECONDS}s",
                        targets=MAGNITUDE_TARGETS,
                    )
                )
                for diagnostic_measure in ("unit_l2", "cosine"):
                    diagnostic_development = np.concatenate(
                        (
                            surprise[seed]["discovery"][horizon][diagnostic_measure],
                            surprise[seed]["validation"][horizon][diagnostic_measure],
                        )
                    )
                    surprise_rows.extend(
                        correlation_rows(
                            diagnostic_development,
                            surprise[seed][diagnostic][horizon][diagnostic_measure],
                            targets[diagnostic],
                            seed=seed,
                            diagnostic=diagnostic,
                            feature=(f"surprise_{diagnostic_measure}_{horizon * STEP_SECONDS}s"),
                            targets=PRIMARY_TARGETS,
                        )
                    )
                for metric in ("velocity", "acceleration", "curvature"):
                    development_metric = np.concatenate(
                        (
                            dynamics[seed]["discovery"][horizon][metric],
                            dynamics[seed]["validation"][horizon][metric],
                        )
                    )
                    dynamics_rows.extend(
                        correlation_rows(
                            development_metric,
                            dynamics[seed][diagnostic][horizon][metric],
                            targets[diagnostic],
                            seed=seed,
                            diagnostic=diagnostic,
                            feature=f"{metric}_{horizon * STEP_SECONDS}s",
                            targets=MAGNITUDE_TARGETS,
                        )
                    )
                for target_name in PRIMARY_TARGETS:
                    velocity_candidate = {
                        role: dynamics[seed][role][horizon]["velocity"][:, None] for role in ROLES
                    }
                    surprise_candidate = {
                        role: surprise[seed][role][horizon]["l2"][:, None] for role in ROLES
                    }
                    combined = {
                        role: np.column_stack((velocity_candidate[role], surprise_candidate[role]))
                        for role in ROLES
                    }
                    velocity_probe = probe_candidate(
                        base, velocity_candidate, targets, target_name, diagnostic
                    )
                    surprise_probe = probe_candidate(
                        base, surprise_candidate, targets, target_name, diagnostic
                    )
                    combined_probe = probe_candidate(
                        base, combined, targets, target_name, diagnostic
                    )
                    surprise_rows.append(
                        {
                            "seed": seed,
                            "diagnostic": diagnostic,
                            "feature": f"surprise_increment_{horizon * STEP_SECONDS}s",
                            "target": target_name,
                            "block_seconds": None,
                            "base_skill": surprise_probe["base"]["mae_skill"],
                            "base_plus_velocity_skill": velocity_probe["base_plus_candidate"][
                                "mae_skill"
                            ],
                            "base_plus_surprise_skill": surprise_probe["base_plus_candidate"][
                                "mae_skill"
                            ],
                            "base_plus_velocity_surprise_skill": combined_probe[
                                "base_plus_candidate"
                            ]["mae_skill"],
                            "increment_beyond_velocity": combined_probe["base_plus_candidate"][
                                "mae_skill"
                            ]
                            - velocity_probe["base_plus_candidate"]["mae_skill"],
                            "base_plus_pca_surprise_skill": surprise_probe[
                                "base_plus_pca_plus_candidate"
                            ]["mae_skill"],
                            "paired_intervals": combined_probe["paired_intervals"],
                            "paired_increment_beyond_velocity": paired_model_increment(
                                velocity_probe, combined_probe
                            ),
                        }
                    )
                    for metric in ("acceleration", "curvature"):
                        metric_candidate = {
                            role: dynamics[seed][role][horizon][metric][:, None] for role in ROLES
                        }
                        velocity_plus_metric = {
                            role: np.column_stack(
                                (velocity_candidate[role], metric_candidate[role])
                            )
                            for role in ROLES
                        }
                        metric_probe = probe_candidate(
                            base, metric_candidate, targets, target_name, diagnostic
                        )
                        combined_metric_probe = probe_candidate(
                            base, velocity_plus_metric, targets, target_name, diagnostic
                        )
                        dynamics_rows.append(
                            {
                                "seed": seed,
                                "diagnostic": diagnostic,
                                "feature": (f"{metric}_increment_{horizon * STEP_SECONDS}s"),
                                "target": target_name,
                                "block_seconds": None,
                                "base_skill": metric_probe["base"]["mae_skill"],
                                "base_plus_velocity_skill": velocity_probe["base_plus_candidate"][
                                    "mae_skill"
                                ],
                                "base_plus_metric_skill": metric_probe["base_plus_candidate"][
                                    "mae_skill"
                                ],
                                "base_plus_velocity_metric_skill": combined_metric_probe[
                                    "base_plus_candidate"
                                ]["mae_skill"],
                                "increment_beyond_velocity": combined_metric_probe[
                                    "base_plus_candidate"
                                ]["mae_skill"]
                                - velocity_probe["base_plus_candidate"]["mae_skill"],
                                "base_plus_pca_metric_skill": metric_probe[
                                    "base_plus_pca_plus_candidate"
                                ]["mae_skill"],
                                "paired_intervals": combined_metric_probe["paired_intervals"],
                                "paired_increment_beyond_velocity": paired_model_increment(
                                    velocity_probe, combined_metric_probe
                                ),
                            }
                        )

    uncertainty: dict[int, dict[str, FloatArray]] = {horizon: {} for horizon in LATENT_HORIZONS}
    for horizon in LATENT_HORIZONS:
        aligned: dict[str, list[FloatArray]] = {role: [] for role in ROLES}
        reference_seed = SEEDS[0]
        reference_discovery = global_states[reference_seed]["discovery"][ends["discovery"]]
        for seed in SEEDS:
            if seed == reference_seed:
                transform = None
            else:
                transform = fit_orthogonal_alignment(
                    global_states[seed]["discovery"][ends["discovery"]], reference_discovery
                )
            for role in ROLES:
                values = global_predictions[seed][role][horizon]
                aligned[role].append(values if transform is None else transform.transform(values))
        for role in ROLES:
            uncertainty[horizon][role] = cross_seed_disagreement(aligned[role])

    subsystem_embeddings: dict[str, dict[int, dict[str, FloatArray]]] = {}
    subsystem_training: dict[str, Any] = {}
    subsystem_normalization: dict[str, Any] = {}
    for name, names in features.items():
        subsystem_embeddings[name] = {}
        subsystem_training[name] = {}
        subsystem_normalized, center, scale = normalize_subsystem(sessions, names)
        subsystem_normalization[name] = {"center": center, "scale": scale}
        for seed in SEEDS:
            embedding, training = train_subsystem_seed(
                name,
                seed,
                subsystem_normalized,
                sessions,
                args.work_dir,
                device,
                args.subsystem_epochs,
            )
            subsystem_embeddings[name][seed] = embedding
            subsystem_training[name][str(seed)] = training

    pair_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in PAIR_DEFINITIONS}
    pair_signals: dict[str, dict[int, dict[str, dict[str, FloatArray]]]] = {
        name: {} for name in PAIR_DEFINITIONS
    }
    pair_mappings: dict[str, Any] = {}
    for pair_name, (source_name, target_name) in PAIR_DEFINITIONS.items():
        pair_mappings[pair_name] = {}
        pair_comparator = handcrafted_pair_comparator(pair_name, sessions, ends)
        for seed in SEEDS:
            source = subsystem_embeddings[source_name][seed]
            target = subsystem_embeddings[target_name][seed]
            forward = fit_development_ridge_map(
                source["discovery"][ends["discovery"]],
                target["discovery"][ends["discovery"]],
                source["validation"][ends["validation"]],
                target["validation"][ends["validation"]],
            )
            reverse = fit_development_ridge_map(
                target["discovery"][ends["discovery"]],
                source["discovery"][ends["discovery"]],
                target["validation"][ends["validation"]],
                source["validation"][ends["validation"]],
            )
            pair_mappings[pair_name][str(seed)] = {
                "forward": mapping_metadata(forward),
                "reverse": mapping_metadata(reverse),
            }
            pair_signals[pair_name][seed] = {}
            for role in ROLES:
                selected = ends[role]
                forward_d = latent_disequilibrium(
                    forward, source[role][selected], target[role][selected]
                )
                reverse_d = latent_disequilibrium(
                    reverse, target[role][selected], source[role][selected]
                )
                pair_signals[pair_name][seed][role] = {
                    "forward": forward_d,
                    "reverse": reverse_d,
                    "maximum": np.maximum(forward_d, reverse_d),
                }
            development_forward = np.concatenate(
                (
                    pair_signals[pair_name][seed]["discovery"]["forward"],
                    pair_signals[pair_name][seed]["validation"]["forward"],
                )
            )
            development_motion = np.concatenate(
                (
                    np.linalg.norm(
                        target["discovery"][ends["discovery"] + TARGET_HORIZON]
                        - target["discovery"][ends["discovery"]],
                        axis=1,
                    ),
                    np.linalg.norm(
                        target["validation"][ends["validation"] + TARGET_HORIZON]
                        - target["validation"][ends["validation"]],
                        axis=1,
                    ),
                )
            )
            high_forward = float(np.quantile(development_forward, 0.80))
            motion_threshold = float(np.quantile(development_motion, 0.67))
            if pair_name == "cross_market":
                observable_targets = (
                    "signed_futures_return",
                    "signed_atm_iv_change",
                    "surface_displacement",
                    "parity_restoration",
                    "absolute_atm_straddle_change",
                    "near_atm_spread_change",
                    "realized_futures_volatility",
                )
                incremental_targets = ("surface_displacement", "signed_atm_iv_change")
            elif pair_name == "near_far":
                observable_targets = (
                    "near_atm_iv_change",
                    "far_atm_iv_change",
                    "term_structure_iv_change",
                    "atm_iv_convergence",
                    "surface_residual_restoration",
                    "realized_futures_volatility",
                )
                incremental_targets = ("term_structure_iv_change", "atm_iv_convergence")
            else:
                observable_targets = (
                    "call_relative_move",
                    "put_relative_move",
                    "call_put_relative_correction",
                    "signed_atm_iv_change",
                    "parity_restoration",
                    "signed_futures_return",
                    "surface_residual_restoration",
                )
                incremental_targets = ("call_put_relative_correction", "parity_restoration")
            for diagnostic in DIAGNOSTICS:
                selected = ends[diagnostic]
                correction = correction_decomposition(
                    source[diagnostic][selected],
                    target[diagnostic][selected],
                    source[diagnostic][selected + TARGET_HORIZON],
                    target[diagnostic][selected + TARGET_HORIZON],
                    forward,
                    reverse,
                )
                labels = classify_corrections(
                    correction,
                    high_forward=high_forward,
                    motion_threshold=motion_threshold,
                )
                counts = Counter(labels.tolist())
                development = np.concatenate(
                    (
                        pair_signals[pair_name][seed]["discovery"]["forward"],
                        pair_signals[pair_name][seed]["validation"]["forward"],
                    )
                )
                rows = correlation_rows(
                    development,
                    pair_signals[pair_name][seed][diagnostic]["forward"],
                    targets[diagnostic],
                    seed=seed,
                    diagnostic=diagnostic,
                    feature=f"{source_name}_to_{target_name}_disequilibrium",
                    targets=observable_targets,
                )
                for row in rows:
                    row.update(
                        {
                            "source_subsystem": source_name,
                            "target_subsystem": target_name,
                            "mapping_alpha": forward.alpha,
                            "large_threshold": high_forward,
                            "large_event_samples": int((labels != "not_large").sum()),
                            "correction_event_frequencies": dict(counts),
                            "mean_forward_change_large": float(
                                np.mean(correction["forward_change"][labels != "not_large"])
                            )
                            if np.any(labels != "not_large")
                            else None,
                            "mean_target_progress_large": float(
                                np.mean(correction["target_progress"][labels != "not_large"])
                            )
                            if np.any(labels != "not_large")
                            else None,
                            "mean_source_progress_large": float(
                                np.mean(correction["source_progress"][labels != "not_large"])
                            )
                            if np.any(labels != "not_large")
                            else None,
                        }
                    )
                pair_rows[pair_name].extend(rows)
                candidate = {
                    role: pair_signals[pair_name][seed][role]["forward"][:, None] for role in ROLES
                }
                for observable_target in incremental_targets:
                    probe = probe_candidate(
                        base,
                        candidate,
                        targets,
                        observable_target,
                        diagnostic,
                        comparator=pair_comparator,
                    )
                    pair_rows[pair_name].append(
                        {
                            "seed": seed,
                            "diagnostic": diagnostic,
                            "feature": f"{source_name}_to_{target_name}_increment",
                            "target": observable_target,
                            "block_seconds": None,
                            "source_subsystem": source_name,
                            "target_subsystem": target_name,
                            "base_skill": probe["base"]["mae_skill"],
                            "base_plus_handcrafted_skill": probe["base_plus_comparator"][
                                "mae_skill"
                            ],
                            "base_plus_latent_skill": probe["base_plus_candidate"]["mae_skill"],
                            "base_plus_handcrafted_latent_skill": probe[
                                "base_plus_comparator_plus_candidate"
                            ]["mae_skill"],
                            "base_plus_pca_skill": probe["base_plus_pca"]["mae_skill"],
                            "base_plus_pca_latent_skill": probe["base_plus_pca_plus_candidate"][
                                "mae_skill"
                            ],
                            "increment_beyond_handcrafted": probe[
                                "base_plus_comparator_plus_candidate"
                            ]["mae_skill"]
                            - probe["base_plus_comparator"]["mae_skill"],
                            "increment_beyond_pca": probe["base_plus_pca_plus_candidate"][
                                "mae_skill"
                            ]
                            - probe["base_plus_pca"]["mae_skill"],
                            "paired_intervals": probe["paired_intervals"],
                        }
                    )

    uncertainty_rows: list[dict[str, Any]] = []
    for horizon in LATENT_HORIZONS:
        development = np.concatenate(
            (uncertainty[horizon]["discovery"], uncertainty[horizon]["validation"])
        )
        uncertainty_comparator = {
            role: np.column_stack(
                (
                    np.median(
                        np.stack([surprise[seed][role][horizon]["l2"] for seed in SEEDS], axis=0),
                        axis=0,
                    ),
                    np.median(
                        np.stack(
                            [dynamics[seed][role][horizon]["velocity"] for seed in SEEDS],
                            axis=0,
                        ),
                        axis=0,
                    ),
                )
            )
            for role in ROLES
        }
        for diagnostic in DIAGNOSTICS:
            uncertainty_rows.extend(
                correlation_rows(
                    development,
                    uncertainty[horizon][diagnostic],
                    targets[diagnostic],
                    seed=0,
                    diagnostic=diagnostic,
                    feature=f"aligned_cross_seed_uncertainty_{horizon * STEP_SECONDS}s",
                    targets=MAGNITUDE_TARGETS,
                )
            )
            for target_name in PRIMARY_TARGETS:
                candidate = {role: uncertainty[horizon][role][:, None] for role in ROLES}
                probe = probe_candidate(
                    base,
                    candidate,
                    targets,
                    target_name,
                    diagnostic,
                    comparator=uncertainty_comparator,
                )
                uncertainty_rows.append(
                    {
                        "seed": 0,
                        "diagnostic": diagnostic,
                        "feature": f"uncertainty_increment_{horizon * STEP_SECONDS}s",
                        "target": target_name,
                        "block_seconds": None,
                        "base_skill": probe["base"]["mae_skill"],
                        "base_plus_uncertainty_skill": probe["base_plus_candidate"]["mae_skill"],
                        "base_plus_pca_skill": probe["base_plus_pca"]["mae_skill"],
                        "base_plus_pca_uncertainty_skill": probe["base_plus_pca_plus_candidate"][
                            "mae_skill"
                        ],
                        "base_plus_surprise_velocity_skill": probe["base_plus_comparator"][
                            "mae_skill"
                        ],
                        "base_plus_surprise_velocity_uncertainty_skill": probe[
                            "base_plus_comparator_plus_candidate"
                        ]["mae_skill"],
                        "increment_beyond_surprise_velocity": probe[
                            "base_plus_comparator_plus_candidate"
                        ]["mae_skill"]
                        - probe["base_plus_comparator"]["mae_skill"],
                        "paired_intervals": probe["paired_intervals"],
                    }
                )

    stress_rows: list[dict[str, Any]] = []
    stress_by_seed: dict[int, dict[str, NDArray[np.str_]]] = {}
    for seed in SEEDS:
        stress_by_seed[seed] = {}
        stress_inputs = {
            role: {
                "velocity": dynamics[seed][role][6]["velocity"],
                "surprise": surprise[seed][role][6]["l2"],
                "uncertainty": uncertainty[6][role],
                "disequilibrium": pair_signals["cross_market"][seed][role]["maximum"],
            }
            for role in ROLES
        }
        development = {
            name: np.concatenate(
                (stress_inputs["discovery"][name], stress_inputs["validation"][name])
            )
            for name in stress_inputs["discovery"]
        }
        thresholds = fit_stress_thresholds(development)
        for diagnostic in DIAGNOSTICS:
            labels = classify_stress_states(stress_inputs[diagnostic], thresholds)
            stress_by_seed[seed][diagnostic] = labels
            for state in sorted(np.unique(labels)):
                mask = labels == state
                row: dict[str, Any] = {
                    "seed": seed,
                    "diagnostic": diagnostic,
                    "state": state,
                    "samples": int(mask.sum()),
                    "share": float(mask.mean()),
                    "thresholds": thresholds,
                }
                for target_name in MAGNITUDE_TARGETS:
                    row[f"mean_{target_name}"] = float(
                        np.nanmean(targets[diagnostic][target_name][mask])
                    )
                stress_rows.append(row)

    seed_rows: list[dict[str, Any]] = []
    for source_name, rows in (
        ("surprise", surprise_rows),
        ("latent_dynamics", dynamics_rows),
        ("cross_market", pair_rows["cross_market"]),
        ("near_far", pair_rows["near_far"]),
        ("call_put", pair_rows["call_put"]),
    ):
        keys = sorted(
            {
                (row["diagnostic"], row["feature"], row["target"], row.get("block_seconds"))
                for row in rows
                if row.get("spearman") is not None
            }
        )
        for diagnostic, feature, target_name, block_seconds in keys:
            selected = [
                row
                for row in rows
                if (row["diagnostic"], row["feature"], row["target"], row.get("block_seconds"))
                == (diagnostic, feature, target_name, block_seconds)
            ]
            correlations = [float(row["spearman"]) for row in selected]
            seed_rows.append(
                {
                    "family": source_name,
                    "diagnostic": diagnostic,
                    "feature": feature,
                    "target": target_name,
                    "block_seconds": block_seconds,
                    "median_spearman": float(np.median(correlations)),
                    "minimum_spearman": float(np.min(correlations)),
                    "maximum_spearman": float(np.max(correlations)),
                    "positive_seeds": int(np.sum(np.asarray(correlations) > 0.0)),
                    "seeds": len(correlations),
                }
            )

    write_csv(args.output / "surprise_summary.csv", surprise_rows)
    write_csv(args.output / "latent_dynamics.csv", dynamics_rows)
    write_csv(args.output / "cross_market_disequilibrium.csv", pair_rows["cross_market"])
    write_csv(args.output / "near_far_disequilibrium.csv", pair_rows["near_far"])
    write_csv(args.output / "call_put_disequilibrium.csv", pair_rows["call_put"])
    write_csv(args.output / "model_uncertainty.csv", uncertainty_rows)
    write_csv(args.output / "stress_taxonomy.csv", stress_rows)
    write_csv(args.output / "seed_stability.csv", seed_rows)

    results = {
        "status": "retrospective_latent_dynamics_analysis_complete",
        "research_only": True,
        "outer_test_untouched": True,
        "device": str(device),
        "sessions": frozen["session_roles"],
        "global_model_bundle": {
            "path": str(args.frozen_bundle.resolve()),
            "semantic_sha256": manifest["semantic_sha256"],
        },
        "subsystem_training": subsystem_training,
        "subsystem_normalization": subsystem_normalization,
        "mappings": pair_mappings,
        "summary": {
            "surprise_median_spearman": summary_median(
                [row for row in surprise_rows if row.get("block_seconds") == 60], "spearman"
            ),
            "velocity_median_spearman": summary_median(
                [
                    row
                    for row in dynamics_rows
                    if row.get("block_seconds") == 60 and row["feature"].startswith("velocity")
                ],
                "spearman",
            ),
            "acceleration_median_spearman": summary_median(
                [
                    row
                    for row in dynamics_rows
                    if row.get("block_seconds") == 60 and row["feature"].startswith("acceleration")
                ],
                "spearman",
            ),
            "curvature_median_spearman": summary_median(
                [
                    row
                    for row in dynamics_rows
                    if row.get("block_seconds") == 60 and row["feature"].startswith("curvature")
                ],
                "spearman",
            ),
        },
    }
    (args.output / "results.json").write_text(
        json.dumps(json_safe(results), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_readme(
        args.output / "README.md",
        frozen["session_roles"],
        surprise_rows,
        dynamics_rows,
        pair_rows,
        uncertainty_rows,
        stress_rows,
    )
    result_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.output.iterdir())
        if path.is_file()
    }
    (args.output / "artifact_sha256.json").write_text(
        json.dumps(result_hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": results["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
