"""Train the fixed Market-JEPA across completed NIFTY option sessions."""

# ruff: noqa: UP017 - remote PyTorch environment uses Python 3.9.

from __future__ import annotations

import argparse
import json
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
    downstream_targets,
    effective_rank,
    embeddings_for,
    probe,
    set_seed,
    train_jepa,
)
from torch.utils.data import DataLoader


def load_state_file(path: Path) -> tuple[np.ndarray, np.ndarray, list[str], str]:
    loaded = np.load(path, allow_pickle=False)
    timestamps = loaded["timestamps"].astype(np.int64)
    values = loaded["values"].astype(np.float64)
    columns = [str(item) for item in loaded["columns"].tolist()]
    trading_date = str(loaded["trading_date"].tolist()[0])
    if len(timestamps) != len(values):
        raise ValueError(f"timestamp/value mismatch in {path}")
    return timestamps, values, columns, trading_date


def contiguous_ends(timestamps: np.ndarray, context_steps: int) -> np.ndarray:
    maximum_horizon = max(HORIZONS)
    possible = range(context_steps - 1, len(timestamps) - maximum_horizon)
    valid = []
    for end in possible:
        window = timestamps[end - context_steps + 1 : end + maximum_horizon + 1]
        if np.all(np.diff(window) == 5 * NS):
            valid.append(end)
    return np.asarray(valid, dtype=np.int64)


def normalize_sessions(
    discovery: np.ndarray,
    validation: np.ndarray,
    diagnostic: np.ndarray,
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    center = np.nanmean(discovery, axis=0)
    scale = np.nanstd(discovery, axis=0, ddof=1)
    center = np.where(np.isfinite(center), center, 0.0)
    scale = np.where(np.isfinite(scale) & (scale > 0.0), scale, 1.0)
    normalized = {}
    for name, values in (
        ("discovery", discovery),
        ("validation", validation),
        ("diagnostic", diagnostic),
    ):
        filled = np.where(np.isfinite(values), values, center)
        normalized[name] = np.clip((filled - center) / scale, -10.0, 10.0).astype(np.float32)
    return normalized, center, scale


def representations_and_targets(
    model: MarketJepa,
    normalized: np.ndarray,
    raw: np.ndarray,
    ends: np.ndarray,
    columns: list[str],
    config: Config,
    device: torch.device,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    dataset = SequenceDataset(normalized, ends, config.context_steps, HORIZONS)
    embeddings, observed_ends = embeddings_for(model, dataset, device)
    if not np.array_equal(ends, observed_ends):
        raise RuntimeError("embedding extraction changed sequence order")
    representations = {
        "last_state": normalized[ends],
        "flattened_context": np.stack(
            [normalized[end - config.context_steps + 1 : end + 1].reshape(-1) for end in ends]
        ),
        "jepa_embedding": embeddings,
    }
    return representations, downstream_targets(raw, ends, columns)


def run(
    discovery_path: Path,
    validation_path: Path,
    diagnostic_path: Path,
    output_dir: Path,
    seed: int,
    epochs: int,
) -> dict[str, Any]:
    set_seed(seed)
    sessions = {}
    columns: list[str] | None = None
    for name, path in (
        ("discovery", discovery_path),
        ("validation", validation_path),
        ("diagnostic", diagnostic_path),
    ):
        timestamps, values, observed_columns, trading_date = load_state_file(path)
        if columns is None:
            columns = observed_columns
        elif columns != observed_columns:
            raise ValueError(f"feature columns differ for {path}")
        sessions[name] = {
            "timestamps": timestamps,
            "values": values,
            "trading_date": trading_date,
            "path": str(path),
        }
    assert columns is not None

    normalized, center, scale = normalize_sessions(
        sessions["discovery"]["values"],
        sessions["validation"]["values"],
        sessions["diagnostic"]["values"],
    )
    config = Config(
        seed=seed,
        context_steps=24,
        batch_size=128,
        epochs=epochs,
        patience=12,
    )
    ends = {
        name: contiguous_ends(session["timestamps"], config.context_steps)
        for name, session in sessions.items()
    }
    if min(len(item) for item in ends.values()) < 100:
        sequence_counts = {name: len(items) for name, items in ends.items()}
        raise ValueError(f"too few contiguous sequences: {sequence_counts}")

    train_dataset = SequenceDataset(
        normalized["discovery"], ends["discovery"], config.context_steps, HORIZONS
    )
    validation_dataset = SequenceDataset(
        normalized["validation"], ends["validation"], config.context_steps, HORIZONS
    )
    generator = torch.Generator().manual_seed(seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=config.batch_size,
        shuffle=True,
        generator=generator,
    )
    validation_loader = DataLoader(validation_dataset, batch_size=config.batch_size, shuffle=False)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = MarketJepa(len(columns), config).to(device)
    output_dir.mkdir(parents=True, exist_ok=True)
    training = train_jepa(model, train_loader, validation_loader, device, output_dir)

    representations = {}
    targets = {}
    for name in sessions:
        representations[name], targets[name] = representations_and_targets(
            model,
            normalized[name],
            sessions[name]["values"],
            ends[name],
            columns,
            config,
            device,
        )
    benchmark = {}
    for target_name in targets["discovery"]:
        benchmark[target_name] = {}
        for representation_name in representations["discovery"]:
            benchmark[target_name][representation_name] = probe(
                representations["discovery"][representation_name],
                representations["validation"][representation_name],
                representations["diagnostic"][representation_name],
                targets["discovery"][target_name],
                targets["validation"][target_name],
                targets["diagnostic"][target_name],
            )
    diagnostic_embedding = representations["diagnostic"]["jepa_embedding"]
    result = {
        "status": "multi_day_prototype_complete",
        "interpretation": "cross-session representation diagnostic; no trading claim",
        "diagnostic_targets_accessed": True,
        "prospective_claim": False,
        "device": str(device),
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "config": asdict(config),
        "training": training,
        "sessions": {
            name: {
                "trading_date": session["trading_date"],
                "state_rows_used": int(len(session["values"])),
                "sequence_rows": int(len(ends[name])),
                "path": session["path"],
            }
            for name, session in sessions.items()
        },
        "normalization": {
            "fit_session": sessions["discovery"]["trading_date"],
            "center": center.tolist(),
            "scale": scale.tolist(),
            "columns": columns,
        },
        "embedding_diagnostics": {
            "effective_rank": effective_rank(diagnostic_embedding),
            "embedding_dimension": int(diagnostic_embedding.shape[1]),
            "mean_dimension_std": float(diagnostic_embedding.std(axis=0).mean()),
            "minimum_dimension_std": float(diagnostic_embedding.std(axis=0).min()),
        },
        "benchmark": benchmark,
    }
    (output_dir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "seed": seed,
                "best_epoch": training["best_epoch"],
            }
        )
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()
    run(
        args.discovery,
        args.validation,
        args.diagnostic,
        args.output_dir,
        args.seed,
        args.epochs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
