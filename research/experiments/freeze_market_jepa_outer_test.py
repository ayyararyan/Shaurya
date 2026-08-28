"""Create the immutable development bundle for the prospective Market-JEPA test."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from market_jepa_20260826 import Config, MarketJepa
from market_jepa_regime_analysis import (
    aligned_representations,
    contiguous_ends,
    load_state,
    normalize_sessions,
    stable_model_columns,
)
from sklearn.decomposition import PCA

from shaurya.research.market_jepa_outer_test import (
    file_sha256,
    fit_frozen_ridge,
    semantic_sha256,
)
from shaurya.research.market_jepa_regimes import downstream_targets, random_projection

SEEDS = (1, 7, 23, 42, 101)
HORIZONS = (6, 60)
REPRESENTATIONS = ("handcrafted_base", "base_plus_jepa", "base_plus_pca", "base_plus_random")


def _source_hashes(repo: Path) -> dict[str, str]:
    relative_paths = (
        "research/experiments/market_jepa_20260826.py",
        "research/experiments/market_jepa_regime_analysis.py",
        "research/experiments/apply_market_jepa_outer_test.py",
        "research/src/shaurya/research/market_jepa_regimes.py",
        "research/src/shaurya/research/market_jepa_outer_test.py",
    )
    return {path: file_sha256(repo / path) for path in relative_paths}


def _selected_alphas(results: dict[str, Any]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for horizon in ("30s", "300s"):
        diagnostic_1 = results["probes"]["diagnostic_1"][horizon]["signed_atm_iv_change"]
        diagnostic_2 = results["probes"]["diagnostic_2"][horizon]["signed_atm_iv_change"]
        output[horizon] = {}
        for representation in REPRESENTATIONS:
            left = float(diagnostic_1[representation]["selected_alpha"])
            right = float(diagnostic_2[representation]["selected_alpha"])
            if left != right:
                raise ValueError("validation-selected alpha unexpectedly differs by diagnostic")
            output[horizon][representation] = left
    return output


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
    normalized, center, scale = normalize_sessions(sessions, model_columns)
    summary = json.loads((args.results_root / "results.json").read_text())
    seen_dates = sorted(
        {session["trading_date"] for session in summary["sessions"].values()}
        | {sessions[name]["trading_date"] for name in sessions}
    )

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
    (temporary / "checkpoints").mkdir()
    (temporary / "probes").mkdir()
    np.savez_compressed(
        temporary / "normalization.npz",
        center=center,
        scale=scale,
        model_columns=np.asarray(model_columns),
        raw_columns=np.asarray(raw_columns),
    )

    config_template: dict[str, Any] | None = None
    pca_model: PCA | None = None
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
        state = torch.load(temporary / checkpoint_relative, map_location=device, weights_only=True)
        model.load_state_dict(state)

        ends = {
            name: contiguous_ends(session["timestamps"], config.context_steps, max(HORIZONS))
            for name, session in sessions.items()
        }
        representations = {
            name: aligned_representations(
                model, session, normalized[name], ends[name], config, device
            )
            for name, session in sessions.items()
        }
        if pca_model is None:
            flat = representations["discovery"]["flattened_context"]
            component_count = min(32, flat.shape[0] - 1, flat.shape[1])
            pca_model = PCA(n_components=component_count, random_state=0).fit(flat)
            np.savez_compressed(
                temporary / "pca.npz",
                mean=np.asarray(pca_model.mean_, dtype=np.float64),
                components=np.asarray(pca_model.components_, dtype=np.float64),
                explained_variance_ratio=np.asarray(
                    pca_model.explained_variance_ratio_, dtype=np.float64
                ),
            )
        for name in sessions:
            current = representations[name]
            current["pca"] = pca_model.transform(current["flattened_context"])
        rng = np.random.default_rng(seed)
        flattened_dimension = representations["discovery"]["flattened_context"].shape[1]
        projection = rng.normal(
            0.0,
            1.0 / np.sqrt(flattened_dimension),
            size=(flattened_dimension, config.embedding_dim),
        )
        np.save(temporary / f"random-projection-seed-{seed}.npy", projection)
        for name in sessions:
            current = representations[name]
            current["random_encoder"] = random_projection(current["flattened_context"], projection)
            current["base_plus_jepa"] = np.column_stack(
                (current["handcrafted_base"], current["jepa"])
            )
            current["base_plus_pca"] = np.column_stack(
                (current["handcrafted_base"], current["pca"])
            )
            current["base_plus_random"] = np.column_stack(
                (current["handcrafted_base"], current["random_encoder"])
            )
        targets = {
            name: {
                horizon: downstream_targets(session["values"], ends[name], raw_columns, horizon)[
                    "signed_atm_iv_change"
                ]
                for horizon in HORIZONS
            }
            for name, session in sessions.items()
        }
        selected = _selected_alphas(seed_results)
        for horizon in HORIZONS:
            horizon_name = f"{horizon * 5}s"
            target = np.concatenate((targets["discovery"][horizon], targets["validation"][horizon]))
            for representation in REPRESENTATIONS:
                features = np.concatenate(
                    (
                        representations["discovery"][representation],
                        representations["validation"][representation],
                    )
                )
                probe = fit_frozen_ridge(features, target, selected[horizon_name][representation])
                probe.save(
                    temporary / "probes" / f"seed-{seed}-{horizon_name}-{representation}.npz"
                )

    if config_template is None or pca_model is None:
        raise RuntimeError("no seeds were frozen")
    artifacts = sorted(
        path.relative_to(temporary).as_posix() for path in temporary.rglob("*") if path.is_file()
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "one-shot prospective falsification of JEPA for signed near-ATM IV movement",
        "frozen_on": "2026-08-28",
        "freeze_cutoff": args.freeze_cutoff,
        "development_dates": {
            "discovery": sessions["discovery"]["trading_date"],
            "validation": sessions["validation"]["trading_date"],
        },
        "prohibited_seen_dates": seen_dates,
        "seeds": list(SEEDS),
        "horizons_seconds": [30, 300],
        "target": "signed_atm_iv_change",
        "representations": list(REPRESENTATIONS),
        "config": config_template,
        "decision_rule": {
            "required_seeds_per_horizon": 4,
            "criterion": "base+JEPA MAE skill > handcrafted base and base+PCA MAE skill",
            "required_horizons_seconds": [30, 300],
            "failure_action": "drop JEPA from alpha research",
        },
        "source_sha256": _source_hashes(repo),
        "artifact_sha256": {relative: file_sha256(temporary / relative) for relative in artifacts},
    }
    manifest["semantic_sha256"] = semantic_sha256(manifest)
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    temporary.rename(output)
    print(
        json.dumps(
            {"status": "frozen", "bundle": str(output), "fingerprint": manifest["semantic_sha256"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
