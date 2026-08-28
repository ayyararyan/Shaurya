"""Freeze the complete three-hypothesis prospective Market-JEPA protocol."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeAlias

import numpy as np
import torch
from market_jepa_20260826 import HORIZONS, Config, MarketJepa
from market_jepa_regime_analysis import (
    aligned_representations,
    contiguous_ends,
    load_state,
    stable_model_columns,
)
from numpy.typing import NDArray
from sklearn.decomposition import PCA

from shaurya.research.market_jepa_outer_test import (
    H1_REPRESENTATIONS,
    H3_MODELS,
    apply_frozen_normalization,
    file_sha256,
    fit_discovery_normalization,
    fit_quantile_boundaries,
    prospective_feature_sets,
    recent_atm_iv_change,
    select_frozen_ridge,
    semantic_sha256,
)
from shaurya.research.market_jepa_regimes import (
    downstream_targets,
    random_projection,
    transition_shock,
)

SEEDS = (1, 7, 23, 42, 101)
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
SHOCK_LAGS = (1, 6, 12)
BLOCK_SECONDS = (60, 120, 300)
SHUFFLE_OFFSETS = {"discovery": 1001, "validation": 1002, "prospective": 1003}
TARGET_STEPS = 6
FloatArray: TypeAlias = NDArray[np.float64]


def _source_hashes(repo: Path) -> dict[str, str]:
    relative_paths = (
        "research/experiments/market_jepa_20260826.py",
        "research/experiments/market_jepa_regime_analysis.py",
        "research/experiments/freeze_market_jepa_outer_test.py",
        "research/experiments/apply_market_jepa_outer_test.py",
        "research/src/shaurya/research/market_jepa_regimes.py",
        "research/src/shaurya/research/market_jepa_outer_test.py",
    )
    return {path: file_sha256(repo / path) for path in relative_paths}


def _git_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze-cutoff", default="2026-08-28")
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite frozen bundle: {output}")
    repo = Path(__file__).resolve().parents[2]
    sessions = {
        "discovery": load_state(args.discovery),
        "validation": load_state(args.validation),
    }
    raw_columns = sessions["discovery"]["columns"]
    if sessions["validation"]["columns"] != raw_columns:
        raise ValueError("development state columns differ")
    model_columns = stable_model_columns(raw_columns)
    indices = [raw_columns.index(name) for name in model_columns]
    center, scale = fit_discovery_normalization(sessions["discovery"]["values"][:, indices])
    normalized = {
        name: apply_frozen_normalization(session["values"][:, indices], center, scale)
        for name, session in sessions.items()
    }
    prior_summary = json.loads((args.results_root / "results.json").read_text())
    seen_dates = sorted(
        {session["trading_date"] for session in prior_summary["sessions"].values()}
        | {session["trading_date"] for session in sessions.values()}
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    for directory in ("checkpoints", "h1-probes", "h3-probes"):
        (temporary / directory).mkdir()
    np.savez_compressed(
        temporary / "normalization.npz",
        center=center,
        scale=scale,
        model_columns=np.asarray(model_columns),
        raw_columns=np.asarray(raw_columns),
    )

    config_template: dict[str, Any] | None = None
    pca_model: PCA | None = None
    endpoint_counts: dict[str, int] = {}
    shock_thresholds: dict[str, FloatArray] = {}
    selected_probes: dict[str, Any] = {}
    device = torch.device("cpu")
    for seed in SEEDS:
        seed_root = args.results_root / f"seed-{seed}"
        seed_results = json.loads((seed_root / "results.json").read_text())
        config = Config(**seed_results["config"])
        if config_template is None:
            config_template = asdict(config)
        checkpoint_relative = Path("checkpoints") / f"seed-{seed}.pt"
        shutil.copy2(seed_root / "best_model.pt", temporary / checkpoint_relative)
        model = MarketJepa(len(model_columns), config).to(device)
        model.load_state_dict(
            torch.load(temporary / checkpoint_relative, map_location=device, weights_only=True)
        )
        ends = {
            name: contiguous_ends(session["timestamps"], config.context_steps, max(HORIZONS))
            for name, session in sessions.items()
        }
        endpoint_counts = {name: int(len(value)) for name, value in ends.items()}
        representations = {
            name: aligned_representations(
                model, session, normalized[name], ends[name], config, device
            )
            for name, session in sessions.items()
        }
        if pca_model is None:
            flat = representations["discovery"]["flattened_context"]
            pca_model = PCA(n_components=min(32, flat.shape[0] - 1, flat.shape[1]), random_state=0)
            pca_model.fit(flat)
            np.savez_compressed(
                temporary / "pca.npz",
                mean=np.asarray(pca_model.mean_, dtype=np.float64),
                components=np.asarray(pca_model.components_, dtype=np.float64),
                explained_variance_ratio=np.asarray(
                    pca_model.explained_variance_ratio_, dtype=np.float64
                ),
            )
        projection = np.random.default_rng(seed).normal(
            0.0,
            1.0 / np.sqrt(representations["discovery"]["flattened_context"].shape[1]),
            size=(
                representations["discovery"]["flattened_context"].shape[1],
                config.embedding_dim,
            ),
        )
        np.save(temporary / f"random-projection-seed-{seed}.npy", projection)
        h1: dict[str, dict[str, FloatArray]] = {}
        h3: dict[str, dict[str, FloatArray]] = {}
        targets: dict[str, FloatArray] = {}
        for name, session in sessions.items():
            representation = representations[name]
            representation["pca"] = pca_model.transform(representation["flattened_context"])
            representation["random_encoder"] = random_projection(
                representation["flattened_context"], projection
            )
            recent = recent_atm_iv_change(session["values"], ends[name], raw_columns)
            permutation = np.random.default_rng(seed + SHUFFLE_OFFSETS[name]).permutation(
                len(ends[name])
            )
            h1[name], h3[name] = prospective_feature_sets(representation, recent, permutation)
            targets[name] = downstream_targets(
                session["values"], ends[name], raw_columns, TARGET_STEPS
            )["signed_atm_iv_change"]
        selected_probes[str(seed)] = {"h1": {}, "h3": {}}
        for name in H1_REPRESENTATIONS:
            probe, validation_mae = select_frozen_ridge(
                h1["discovery"][name],
                h1["validation"][name],
                targets["discovery"],
                targets["validation"],
                ALPHAS,
            )
            probe.save(temporary / "h1-probes" / f"seed-{seed}-{name}.npz")
            selected_probes[str(seed)]["h1"][name] = {
                "alpha": probe.alpha,
                "validation_mae": validation_mae,
            }
        for name in H3_MODELS:
            probe, validation_mae = select_frozen_ridge(
                h3["discovery"][name],
                h3["validation"][name],
                targets["discovery"],
                targets["validation"],
                ALPHAS,
            )
            probe.save(temporary / "h3-probes" / f"seed-{seed}-{name}.npz")
            selected_probes[str(seed)]["h3"][name] = {
                "alpha": probe.alpha,
                "validation_mae": validation_mae,
            }
        for lag in SHOCK_LAGS:
            development_shock = np.concatenate(
                [transition_shock(representations[name]["jepa"], lag) for name in sessions]
            )
            shock_thresholds[f"seed_{seed}_lag_{lag}"] = fit_quantile_boundaries(development_shock)

    if config_template is None or pca_model is None:
        raise RuntimeError("no seeds were frozen")
    np.savez_compressed(
        temporary / "shock-quantile-thresholds.npz",
        **shock_thresholds,
    )
    artifacts = sorted(
        path.relative_to(temporary).as_posix() for path in temporary.rglob("*") if path.is_file()
    )
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "purpose": "prospective validation of JEPA latent state and state velocity",
        "analysis_git_sha": _git_sha(repo),
        "frozen_on": "2026-08-28",
        "freeze_cutoff": args.freeze_cutoff,
        "development_dates": {
            "discovery": sessions["discovery"]["trading_date"],
            "validation": sessions["validation"]["trading_date"],
        },
        "prohibited_seen_dates": seen_dates,
        "seeds": list(SEEDS),
        "config": config_template,
        "frozen_protocol": {
            "primary_target": "signed_atm_iv_change_30s",
            "target_steps": TARGET_STEPS,
            "pca_components": int(len(pca_model.components_)),
            "ridge_alpha_grid": list(ALPHAS),
            "h1_representations": list(H1_REPRESENTATIONS),
            "h3_models": list(H3_MODELS),
            "shock_lag_seconds": [lag * 5 for lag in SHOCK_LAGS],
            "shock_quantiles": 5,
            "bootstrap_block_seconds": list(BLOCK_SECONDS),
            "bootstrap_draws": 1000,
            "shuffle_offsets": SHUFFLE_OFFSETS,
            "time_controls": ["cyclic_sine", "cyclic_cosine", "session_fraction"],
        },
        "feature_definitions": {
            "recent_iv": "surface__atm_iv__near[t] - surface__atm_iv__near[t-30s]",
            "future_iv": "surface__atm_iv__near[t+30s] - surface__atm_iv__near[t]",
            "transition_shock": "L2 norm of frozen JEPA z[t] - z[t-lag]",
            "interaction": "recent_iv multiplied coordinatewise by frozen JEPA z[t]",
        },
        "decision_rule": {
            "A": "JEPA beats PCA in >=4/5 seeds and all three block CIs are positive in >=4/5",
            "B": "JEPA point estimate beats PCA in >=3/5 seeds but A fails",
            "C": "JEPA point estimate beats PCA in fewer than 3/5 seeds",
        },
        "data_quality": {
            "development_endpoint_counts": endpoint_counts,
            "minimum_contiguous_endpoints": int(0.8 * min(endpoint_counts.values())),
            "must_be_prior_completed_india_date": True,
            "exact_column_schema_required": True,
        },
        "selected_probes": selected_probes,
        "source_sha256": _source_hashes(repo),
        "artifact_sha256": {relative: file_sha256(temporary / relative) for relative in artifacts},
    }
    manifest["semantic_sha256"] = semantic_sha256(manifest)
    (temporary / "frozen_config.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    temporary.rename(output)
    print(
        json.dumps(
            {
                "status": "frozen",
                "bundle": str(output),
                "analysis_git_sha": manifest["analysis_git_sha"],
                "fingerprint": manifest["semantic_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
