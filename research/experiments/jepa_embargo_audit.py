"""Apply frozen JEPA embeddings to delayed surface-movement targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from market_jepa_latent_dynamics_analysis import (
    SEEDS,
    STEP_SECONDS,
    encode_all,
    frozen_normalize,
    load_global_seed,
    load_state,
)
from scipy.stats import spearmanr

NS = 1_000_000_000


def valid_ends(timestamps: np.ndarray, history: int, future: int) -> np.ndarray:
    output = []
    for end in range(history, len(timestamps) - future):
        window = timestamps[end - history : end + future + 1]
        if np.all(np.diff(window) == STEP_SECONDS * NS):
            output.append(end)
    return np.asarray(output, dtype=np.int64)


def targets(
    session: dict[str, Any], ends: np.ndarray, embargo: int, horizon: int
) -> dict[str, np.ndarray]:
    values = session["values"]
    columns = session["columns"]
    index = {name: position for position, name in enumerate(columns)}
    start = ends + embargo
    future = start + horizon
    surface_names = [
        name
        for name in columns
        if name.startswith("surface__")
        and "quote_count" not in name
        and "median_relative_spread" not in name
    ]
    surface_indices = [index[name] for name in surface_names]
    change = values[future][:, surface_indices] - values[start][:, surface_indices]
    near_iv = values[:, index["surface__atm_iv__near"]]
    return {
        "surface_displacement": np.sqrt(np.nanmean(np.square(change), axis=1)),
        "absolute_atm_iv_change": np.abs(near_iv[future] - near_iv[start]),
    }


def rho(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    finite = np.isfinite(x) & np.isfinite(y)
    return float(spearmanr(x[finite], y[finite]).statistic), int(finite.sum())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sessions", nargs=4, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roles = ("discovery", "validation", "diagnostic_1", "diagnostic_2")
    sessions = {role: load_state(path) for role, path in zip(roles, args.sessions, strict=True)}
    normalized, model_columns = frozen_normalize(sessions, args.bundle)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    embeddings: dict[int, dict[str, np.ndarray]] = {}
    for seed in SEEDS:
        model, _ = load_global_seed(seed, args.bundle, len(model_columns), device)
        embeddings[seed] = {
            role: encode_all(model, normalized[role], device) for role in roles
        }
    results = []
    for embargo in (0, 1, 2):
        for velocity_lag in (1, 6, 12):
            for role in roles:
                session = sessions[role]
                ends = valid_ends(session["timestamps"], velocity_lag, embargo + 6)
                target_sets = targets(session, ends, embargo, 6)
                for target_name, target in target_sets.items():
                    seed_rows = []
                    for seed in SEEDS:
                        encoded = embeddings[seed][role]
                        velocity = np.linalg.norm(
                            encoded[ends] - encoded[ends - velocity_lag], axis=1
                        )
                        correlation, count = rho(velocity, target)
                        seed_rows.append(
                            {"seed": seed, "samples": count, "spearman_rho": correlation}
                        )
                    values = [row["spearman_rho"] for row in seed_rows]
                    results.append(
                        {
                            "date": session["trading_date"],
                            "role": role,
                            "target": target_name,
                            "target_horizon_seconds": 30,
                            "target_start_embargo_seconds": embargo * 5,
                            "velocity_window_seconds": velocity_lag * 5,
                            "median_spearman_rho": float(np.median(values)),
                            "minimum_spearman_rho": float(np.min(values)),
                            "maximum_spearman_rho": float(np.max(values)),
                            "positive_seeds": int(np.sum(np.asarray(values) > 0)),
                            "seed_results": seed_rows,
                        }
                    )
    payload = {
        "status": "frozen_jepa_embargo_audit_complete",
        "claim_boundary": "Retrospective forecast diagnostic; no execution or PnL claim.",
        "bundle": str(args.bundle),
        "device": str(device),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": payload["status"], "rows": len(results)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
