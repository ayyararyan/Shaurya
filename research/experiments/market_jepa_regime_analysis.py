"""Run the frozen multi-session Market-JEPA regime benchmark on the Office Mac."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from market_jepa_20260826 import (
    HORIZONS,
    NS,
    Config,
    MarketJepa,
    SequenceDataset,
    embeddings_for,
    set_seed,
    train_jepa,
)
from numpy.typing import NDArray
from scipy.stats import spearmanr
from torch.utils.data import DataLoader

from shaurya.research.market_jepa_regimes import (
    block_bootstrap_increment,
    causal_context_features,
    downstream_targets,
    fit_regimes,
    fit_ridge_probe,
    flattened_context,
    pca_representations,
    probe_to_dict,
    random_projection,
    regime_statistics,
    representation_diagnostics,
    shock_correlations,
    transition_shock,
    transition_statistics,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
SEEDS = (1, 7, 23, 42, 101)
HORIZON_STEPS = (6, 12, 60)
SIGNED_TARGETS = {
    "signed_futures_return",
    "signed_atm_straddle_change",
    "near_atm_spread_change",
    "signed_atm_iv_change",
}


def load_state(path: Path) -> dict[str, Any]:
    payload = np.load(path, allow_pickle=False)
    return {
        "timestamps": payload["timestamps"].astype(np.int64),
        "values": payload["values"].astype(np.float64),
        "columns": [str(item) for item in payload["columns"].tolist()],
        "trading_date": str(payload["trading_date"].tolist()[0]),
        "path": str(path),
    }


def contiguous_ends(timestamps: IntArray, context_steps: int, maximum_horizon: int) -> IntArray:
    possible = range(context_steps - 1, len(timestamps) - maximum_horizon)
    valid: list[int] = []
    for end in possible:
        window = timestamps[end - context_steps + 1 : end + maximum_horizon + 1]
        if np.all(np.diff(window) == 5 * NS):
            valid.append(end)
    return np.asarray(valid, dtype=np.int64)


def stable_model_columns(columns: list[str]) -> list[str]:
    """Remove absolute price and contract identifiers that cannot transfer by date."""
    return [
        name
        for name in columns
        if name != "futures_log_mid" and not name.startswith("atm__strike__")
    ]


def normalize_sessions(
    sessions: dict[str, dict[str, Any]], model_columns: list[str]
) -> tuple[dict[str, FloatArray], FloatArray, FloatArray]:
    raw_columns = sessions["discovery"]["columns"]
    indices = [raw_columns.index(name) for name in model_columns]
    discovery = sessions["discovery"]["values"][:, indices]
    center = np.nanmean(discovery, axis=0)
    scale = np.nanstd(discovery, axis=0, ddof=1)
    center = np.where(np.isfinite(center), center, 0.0)
    scale = np.where(np.isfinite(scale) & (scale > 0.0), scale, 1.0)
    normalized: dict[str, FloatArray] = {}
    for name, session in sessions.items():
        values = session["values"][:, indices]
        filled = np.where(np.isfinite(values), values, center)
        normalized[name] = np.clip((filled - center) / scale, -10.0, 10.0)
    return normalized, center, scale


def time_features(timestamps: IntArray, ends: IntArray) -> FloatArray:
    seconds = (timestamps[ends] // NS + 5.5 * 3600) % 86400
    minute = seconds / 60.0
    angle = 2.0 * math.pi * minute / 1440.0
    session_fraction = np.clip((minute - 555.0) / 375.0, 0.0, 1.0)
    return np.column_stack((np.sin(angle), np.cos(angle), session_fraction)).astype(np.float64)


def aligned_representations(
    model: MarketJepa,
    session: dict[str, Any],
    normalized: FloatArray,
    ends: IntArray,
    config: Config,
    device: torch.device,
) -> dict[str, FloatArray]:
    dataset = SequenceDataset(normalized.astype(np.float32), ends, config.context_steps, HORIZONS)
    embedding, observed = embeddings_for(model, dataset, device)
    if not np.array_equal(ends, observed):
        raise RuntimeError("embedding extraction changed endpoint alignment")
    flat = flattened_context(normalized, ends, config.context_steps)
    base = np.column_stack(
        (
            causal_context_features(normalized, ends, config.context_steps),
            time_features(session["timestamps"], ends),
        )
    )
    return {
        "last_state": np.column_stack(
            (normalized[ends], time_features(session["timestamps"], ends))
        ),
        "handcrafted_base": base,
        "flattened_context": flat,
        "jepa": embedding.astype(np.float64),
    }


def signal_values(
    normalized: FloatArray, ends: IntArray, columns: list[str]
) -> dict[str, FloatArray]:
    index = {name: position for position, name in enumerate(columns)}

    def level(name: str) -> FloatArray:
        return normalized[ends, index[name]]

    def delta(name: str, lag: int) -> FloatArray:
        return normalized[ends, index[name]] - normalized[ends - lag, index[name]]

    return {
        "far_parity_delta_60s": delta("surface__parity_residual_rms_to_forward__far", 12),
        "far_fit_error_delta_60s": delta("surface__fit_rmse_iv__far", 12),
        "near_iv_delta_30s": delta("surface__atm_iv__near", 6),
        "near_curvature_delta_30s": delta("surface__variance_curvature__near", 6),
        "futures_microprice": level("futures_microprice_dislocation"),
        "futures_depth_imbalance": level("futures_depth_imbalance"),
        "futures_realized_volatility": level("futures_realized_volatility_30s"),
    }


def conditional_correlations(
    labels: IntArray,
    signals: dict[str, FloatArray],
    targets: dict[str, FloatArray],
) -> list[dict[str, Any]]:
    pairs = (
        ("far_parity_delta_60s", "signed_futures_return"),
        ("far_fit_error_delta_60s", "signed_futures_return"),
        ("futures_microprice", "signed_futures_return"),
        ("futures_depth_imbalance", "signed_futures_return"),
        ("near_iv_delta_30s", "signed_atm_iv_change"),
        ("near_curvature_delta_30s", "signed_atm_iv_change"),
    )
    output: list[dict[str, Any]] = []
    for signal_name, target_name in pairs:
        for regime in sorted(np.unique(labels)):
            mask = (
                (labels == regime)
                & np.isfinite(signals[signal_name])
                & np.isfinite(targets[target_name])
            )
            rho = spearmanr(signals[signal_name][mask], targets[target_name][mask]).statistic
            output.append(
                {
                    "signal": signal_name,
                    "target": target_name,
                    "regime": int(regime),
                    "samples": int(mask.sum()),
                    "spearman": float(rho) if np.isfinite(rho) else None,
                }
            )
    return output


def run_seed(
    sessions: dict[str, dict[str, Any]],
    normalized: dict[str, FloatArray],
    model_columns: list[str],
    output_dir: Path,
    seed: int,
    epochs: int,
) -> dict[str, Any]:
    set_seed(seed)
    raw_columns = sessions["discovery"]["columns"]
    config = Config(seed=seed, context_steps=24, batch_size=128, epochs=epochs, patience=12)
    training_ends = {
        name: contiguous_ends(session["timestamps"], config.context_steps, max(HORIZONS))
        for name, session in sessions.items()
    }
    evaluation_ends = {
        name: contiguous_ends(session["timestamps"], config.context_steps, max(HORIZON_STEPS))
        for name, session in sessions.items()
    }
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = MarketJepa(len(model_columns), config).to(device)
    seed_dir = output_dir / f"seed-{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    generator = torch.Generator().manual_seed(seed)
    train_dataset = SequenceDataset(
        normalized["discovery"].astype(np.float32),
        training_ends["discovery"],
        config.context_steps,
        HORIZONS,
    )
    validation_dataset = SequenceDataset(
        normalized["validation"].astype(np.float32),
        training_ends["validation"],
        config.context_steps,
        HORIZONS,
    )
    training = train_jepa(
        model,
        DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True, generator=generator),
        DataLoader(validation_dataset, batch_size=config.batch_size, shuffle=False),
        device,
        seed_dir,
    )
    representations = {
        name: aligned_representations(
            model, session, normalized[name], evaluation_ends[name], config, device
        )
        for name, session in sessions.items()
    }
    flat_tests = {
        name: representations[name]["flattened_context"]
        for name in ("diagnostic_1", "diagnostic_2")
    }
    pca_discovery, pca_validation, pca_tests, pca_info = pca_representations(
        representations["discovery"]["flattened_context"],
        representations["validation"]["flattened_context"],
        flat_tests,
    )
    representations["discovery"]["pca"] = pca_discovery
    representations["validation"]["pca"] = pca_validation
    for name, values in pca_tests.items():
        representations[name]["pca"] = values
    rng = np.random.default_rng(seed)
    projection = rng.normal(
        0.0,
        1.0 / np.sqrt(representations["discovery"]["flattened_context"].shape[1]),
        size=(representations["discovery"]["flattened_context"].shape[1], config.embedding_dim),
    )
    for name in sessions:
        representation = representations[name]
        representation["random_encoder"] = random_projection(
            representation["flattened_context"], projection
        )
        shuffle = np.random.default_rng(seed + len(name)).permutation(len(representation["jepa"]))
        representation["shuffled_jepa"] = representation["jepa"][shuffle]
        representation["base_plus_jepa"] = np.column_stack(
            (representation["handcrafted_base"], representation["jepa"])
        )
        representation["base_plus_pca"] = np.column_stack(
            (representation["handcrafted_base"], representation["pca"])
        )
        representation["base_plus_random"] = np.column_stack(
            (representation["handcrafted_base"], representation["random_encoder"])
        )
        representation["base_plus_shuffled_jepa"] = np.column_stack(
            (representation["handcrafted_base"], representation["shuffled_jepa"])
        )

    targets = {
        name: {
            horizon: downstream_targets(
                session["values"], evaluation_ends[name], raw_columns, horizon
            )
            for horizon in HORIZON_STEPS
        }
        for name, session in sessions.items()
    }
    representation_names = (
        "last_state",
        "handcrafted_base",
        "flattened_context",
        "pca",
        "random_encoder",
        "shuffled_jepa",
        "jepa",
        "base_plus_jepa",
        "base_plus_pca",
        "base_plus_random",
        "base_plus_shuffled_jepa",
    )
    probes: dict[str, Any] = {}
    paired_intervals: dict[str, Any] = {}
    for diagnostic in ("diagnostic_1", "diagnostic_2"):
        probes[diagnostic] = {}
        paired_intervals[diagnostic] = {}
        for horizon in HORIZON_STEPS:
            horizon_name = f"{horizon * 5}s"
            probes[diagnostic][horizon_name] = {}
            paired_intervals[diagnostic][horizon_name] = {}
            for target_name in targets["discovery"][horizon]:
                probes[diagnostic][horizon_name][target_name] = {}
                fitted: dict[str, Any] = {}
                for representation_name in representation_names:
                    fitted[representation_name] = fit_ridge_probe(
                        representations["discovery"][representation_name],
                        representations["validation"][representation_name],
                        representations[diagnostic][representation_name],
                        targets["discovery"][horizon][target_name],
                        targets["validation"][horizon][target_name],
                        targets[diagnostic][horizon][target_name],
                        signed=target_name in SIGNED_TARGETS,
                    )
                    probes[diagnostic][horizon_name][target_name][representation_name] = (
                        probe_to_dict(fitted[representation_name])
                    )
                paired_intervals[diagnostic][horizon_name][target_name] = block_bootstrap_increment(
                    fitted["handcrafted_base"].losses,
                    fitted["base_plus_jepa"].losses,
                    seed=20260828 + seed,
                )

    regime_model = fit_regimes(representations["discovery"]["jepa"], 4, seed)
    regime_output: dict[str, Any] = {}
    shock_output: dict[str, Any] = {}
    interactions: dict[str, Any] = {}
    for name in sessions:
        embedding = representations[name]["jepa"]
        labels = regime_model.predict(embedding).astype(np.int64)
        signals = signal_values(normalized[name], evaluation_ends[name], model_columns)
        summary = regime_statistics(
            labels, sessions[name]["values"], evaluation_ends[name], raw_columns
        )
        session_fraction = time_features(sessions[name]["timestamps"], evaluation_ends[name])[:, 2]
        for row in summary:
            mask = labels == row["regime"]
            row["mean_session_fraction"] = float(np.mean(session_fraction[mask]))
        regime_output[name] = {
            "summary": summary,
            "transitions": transition_statistics(labels, 4),
            "conditional_correlations_30s": conditional_correlations(
                labels, signals, targets[name][6]
            ),
            "labels": labels.tolist(),
        }
        shock_output[name] = {
            f"{lag * 5}s": shock_correlations(transition_shock(embedding, lag), targets[name][6])
            for lag in (1, 6, 12)
        }
    for diagnostic in ("diagnostic_1", "diagnostic_2"):
        interactions[diagnostic] = {}
        discovery_signals = signal_values(
            normalized["discovery"], evaluation_ends["discovery"], model_columns
        )
        validation_signals = signal_values(
            normalized["validation"], evaluation_ends["validation"], model_columns
        )
        test_signals = signal_values(
            normalized[diagnostic], evaluation_ends[diagnostic], model_columns
        )
        for signal_name in discovery_signals:
            base = {name: representations[name]["base_plus_jepa"] for name in sessions}
            interaction = {
                "discovery": np.column_stack(
                    (
                        base["discovery"],
                        representations["discovery"]["jepa"]
                        * discovery_signals[signal_name][:, None],
                    )
                )
            }
            interaction["validation"] = np.column_stack(
                (
                    base["validation"],
                    representations["validation"]["jepa"]
                    * validation_signals[signal_name][:, None],
                )
            )
            interaction[diagnostic] = np.column_stack(
                (
                    base[diagnostic],
                    representations[diagnostic]["jepa"] * test_signals[signal_name][:, None],
                )
            )
            target_name = (
                "signed_atm_iv_change"
                if "iv_delta" in signal_name or "curvature" in signal_name
                else "signed_futures_return"
            )
            baseline_probe = fit_ridge_probe(
                base["discovery"],
                base["validation"],
                base[diagnostic],
                targets["discovery"][6][target_name],
                targets["validation"][6][target_name],
                targets[diagnostic][6][target_name],
                signed=True,
            )
            interaction_probe = fit_ridge_probe(
                interaction["discovery"],
                interaction["validation"],
                interaction[diagnostic],
                targets["discovery"][6][target_name],
                targets["validation"][6][target_name],
                targets[diagnostic][6][target_name],
                signed=True,
            )
            interactions[diagnostic][signal_name] = {
                "target": target_name,
                "base_plus_jepa": probe_to_dict(baseline_probe),
                "with_interaction": probe_to_dict(interaction_probe),
                "incremental_mae_skill": (baseline_probe.test_mae - interaction_probe.test_mae)
                / baseline_probe.constant_mae,
            }

    time_target = {
        name: time_features(session["timestamps"], evaluation_ends[name])[:, 2]
        for name, session in sessions.items()
    }
    time_predictability = {
        diagnostic: probe_to_dict(
            fit_ridge_probe(
                representations["discovery"]["jepa"],
                representations["validation"]["jepa"],
                representations[diagnostic]["jepa"],
                time_target["discovery"],
                time_target["validation"],
                time_target[diagnostic],
                signed=False,
            )
        )
        for diagnostic in ("diagnostic_1", "diagnostic_2")
    }
    result = {
        "seed": seed,
        "device": str(device),
        "config": asdict(config),
        "training": training,
        "sequence_counts": {name: int(len(ends)) for name, ends in evaluation_ends.items()},
        "pca": pca_info,
        "embedding_diagnostics": {
            name: representation_diagnostics(representations[name]["jepa"]) for name in sessions
        },
        "probes": probes,
        "paired_increment_intervals": paired_intervals,
        "regimes": regime_output,
        "transition_shocks": shock_output,
        "interactions": interactions,
        "time_predictability": time_predictability,
    }
    (seed_dir / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def aggregate(results: list[dict[str, Any]], sessions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for diagnostic, horizons in result["probes"].items():
            for horizon, targets in horizons.items():
                for target, representations in targets.items():
                    base = representations["handcrafted_base"]
                    augmented = representations["base_plus_jepa"]
                    rows.append(
                        {
                            "seed": result["seed"],
                            "diagnostic": diagnostic,
                            "horizon": horizon,
                            "target": target,
                            "base_skill": base["mae_skill"],
                            "jepa_skill": representations["jepa"]["mae_skill"],
                            "base_plus_jepa_skill": augmented["mae_skill"],
                            "incremental_jepa_skill": augmented["mae_skill"] - base["mae_skill"],
                            "base_r2": base["r2"],
                            "base_plus_jepa_r2": augmented["r2"],
                            "incremental_r2": augmented["r2"] - base["r2"],
                            "base_plus_jepa_auc": augmented["roc_auc"],
                            "base_plus_jepa_balanced_accuracy": augmented["balanced_accuracy"],
                        }
                    )
    grouped: list[dict[str, Any]] = []
    keys = sorted({(row["diagnostic"], row["horizon"], row["target"]) for row in rows})
    for diagnostic, horizon, target in keys:
        selected = [
            row
            for row in rows
            if (row["diagnostic"], row["horizon"], row["target"]) == (diagnostic, horizon, target)
        ]
        increments = np.asarray([row["incremental_jepa_skill"] for row in selected])
        grouped.append(
            {
                "diagnostic": diagnostic,
                "trading_date": sessions[diagnostic]["trading_date"],
                "horizon": horizon,
                "target": target,
                "median_base_skill": float(np.median([row["base_skill"] for row in selected])),
                "median_jepa_skill": float(np.median([row["jepa_skill"] for row in selected])),
                "median_base_plus_jepa_skill": float(
                    np.median([row["base_plus_jepa_skill"] for row in selected])
                ),
                "median_incremental_jepa_skill": float(np.median(increments)),
                "incremental_range": [float(increments.min()), float(increments.max())],
                "positive_seeds": int((increments > 0.0).sum()),
                "median_incremental_r2": float(
                    np.median([row["incremental_r2"] for row in selected])
                ),
                "median_auc": None
                if selected[0]["base_plus_jepa_auc"] is None
                else float(np.median([row["base_plus_jepa_auc"] for row in selected])),
                "median_balanced_accuracy": None
                if selected[0]["base_plus_jepa_balanced_accuracy"] is None
                else float(
                    np.median([row["base_plus_jepa_balanced_accuracy"] for row in selected])
                ),
            }
        )
    return {
        "status": "retrospective_market_jepa_regime_analysis_complete",
        "interpretation": "representation and regime research only; no trading claim",
        "outer_test_untouched": True,
        "seeds": list(SEEDS),
        "sessions": {
            name: {"trading_date": session["trading_date"], "path": session["path"]}
            for name, session in sessions.items()
        },
        "rows": rows,
        "summary": grouped,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--diagnostic-1", type=Path, required=True)
    parser.add_argument("--diagnostic-2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()
    sessions = {
        "discovery": load_state(args.discovery),
        "validation": load_state(args.validation),
        "diagnostic_1": load_state(args.diagnostic_1),
        "diagnostic_2": load_state(args.diagnostic_2),
    }
    columns = sessions["discovery"]["columns"]
    if any(session["columns"] != columns for session in sessions.values()):
        raise ValueError("state columns differ across sessions")
    model_columns = stable_model_columns(columns)
    normalized, center, scale = normalize_sessions(sessions, model_columns)
    args.output.mkdir(parents=True, exist_ok=True)
    results = [
        run_seed(sessions, normalized, model_columns, args.output, seed, args.epochs)
        for seed in SEEDS
    ]
    summary = aggregate(results, sessions)
    summary["normalization"] = {
        "fit_session": sessions["discovery"]["trading_date"],
        "columns": model_columns,
        "excluded_nonstationary_columns": sorted(set(columns) - set(model_columns)),
        "center": center.tolist(),
        "scale": scale.tolist(),
    }
    (args.output / "results.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": summary["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
