"""Apply a frozen Market-JEPA bundle exactly once to one unseen completed session."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import torch
from market_jepa_20260826 import Config, MarketJepa
from market_jepa_regime_analysis import (
    aligned_representations,
    contiguous_ends,
    load_state,
)

from shaurya.research.market_jepa_outer_test import (
    FrozenRidge,
    file_sha256,
    prospective_decision,
    score_frozen_probe,
    verify_bundle,
)
from shaurya.research.market_jepa_regimes import (
    downstream_targets,
    random_projection,
    shock_correlations,
    transition_shock,
)

REPRESENTATIONS = ("handcrafted_base", "base_plus_jepa", "base_plus_pca", "base_plus_random")


def _verify_source_lock(repo: Path, manifest: dict[str, Any]) -> None:
    for relative, expected in manifest["source_sha256"].items():
        path = repo / relative
        if not path.is_file() or file_sha256(path) != expected:
            raise ValueError(f"frozen source hash mismatch: {relative}")


def _validate_session(
    session: dict[str, Any], manifest: dict[str, Any], expected_columns: list[str]
) -> date:
    if session["columns"] != expected_columns:
        raise ValueError("outer-test columns differ from the frozen schema")
    trading_date = date.fromisoformat(session["trading_date"])
    cutoff = date.fromisoformat(manifest["freeze_cutoff"])
    if trading_date <= cutoff:
        raise ValueError("outer-test date is not strictly after the freeze cutoff")
    if session["trading_date"] in manifest["prohibited_seen_dates"]:
        raise ValueError("session was already seen during development or diagnostics")
    today_india = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if trading_date >= today_india:
        raise ValueError("session is not a completed prior trading day in India")
    return trading_date


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    output = args.output.resolve()
    consumed = bundle / "CONSUMED.json"
    if consumed.exists():
        raise RuntimeError(f"one-shot bundle has already been consumed: {consumed}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite outer-test result: {output}")
    manifest = json.loads((bundle / "manifest.json").read_text())
    verify_bundle(bundle, manifest)
    repo = Path(__file__).resolve().parents[2]
    _verify_source_lock(repo, manifest)

    session_path = args.session.resolve()
    session_sha256 = file_sha256(session_path)
    session = load_state(session_path)
    with np.load(bundle / "normalization.npz", allow_pickle=False) as normalization:
        center = normalization["center"].astype(np.float64)
        scale = normalization["scale"].astype(np.float64)
        model_columns = [str(item) for item in normalization["model_columns"].tolist()]
        raw_columns = [str(item) for item in normalization["raw_columns"].tolist()]
    trading_date = _validate_session(session, manifest, raw_columns)
    indices = [raw_columns.index(name) for name in model_columns]
    selected = session["values"][:, indices]
    filled = np.where(np.isfinite(selected), selected, center)
    normalized = np.clip((filled - center) / scale, -10.0, 10.0)
    config = Config(**manifest["config"])
    ends = contiguous_ends(session["timestamps"], config.context_steps, 60)
    if len(ends) < 50:
        raise ValueError("insufficient contiguous outer-test endpoints")
    with np.load(bundle / "pca.npz", allow_pickle=False) as pca:
        pca_mean = pca["mean"].astype(np.float64)
        pca_components = pca["components"].astype(np.float64)

    device = torch.device("cpu")
    seed_metrics: dict[str, Any] = {}
    shock_diagnostics: dict[str, Any] = {}
    for seed in manifest["seeds"]:
        model = MarketJepa(len(model_columns), config).to(device)
        checkpoint = torch.load(
            bundle / "checkpoints" / f"seed-{seed}.pt",
            map_location=device,
            weights_only=True,
        )
        model.load_state_dict(checkpoint)
        representation = aligned_representations(model, session, normalized, ends, config, device)
        representation["pca"] = (representation["flattened_context"] - pca_mean) @ pca_components.T
        projection = np.load(
            bundle / f"random-projection-seed-{seed}.npy", allow_pickle=False
        ).astype(np.float64)
        representation["random_encoder"] = random_projection(
            representation["flattened_context"], projection
        )
        representation["base_plus_jepa"] = np.column_stack(
            (representation["handcrafted_base"], representation["jepa"])
        )
        representation["base_plus_pca"] = np.column_stack(
            (representation["handcrafted_base"], representation["pca"])
        )
        representation["base_plus_random"] = np.column_stack(
            (representation["handcrafted_base"], representation["random_encoder"])
        )
        seed_metrics[str(seed)] = {}
        for horizon in (6, 60):
            horizon_name = f"{horizon * 5}s"
            target = downstream_targets(session["values"], ends, raw_columns, horizon)[
                "signed_atm_iv_change"
            ]
            seed_metrics[str(seed)][horizon_name] = {}
            for name in REPRESENTATIONS:
                probe = FrozenRidge.load(
                    bundle / "probes" / f"seed-{seed}-{horizon_name}-{name}.npz"
                )
                seed_metrics[str(seed)][horizon_name][name] = score_frozen_probe(
                    probe, representation[name], target
                )
        diagnostic_targets = downstream_targets(session["values"], ends, raw_columns, 6)
        shock_diagnostics[str(seed)] = {
            f"{lag * 5}s": shock_correlations(
                transition_shock(representation["jepa"], lag), diagnostic_targets
            )
            for lag in (1, 6, 12)
        }

    decision = prospective_decision(
        seed_metrics, int(manifest["decision_rule"]["required_seeds_per_horizon"])
    )
    result = {
        "status": "prospective_outer_test_complete",
        "bundle_fingerprint": manifest["semantic_sha256"],
        "session": {
            "path": str(session_path),
            "sha256": session_sha256,
            "trading_date": trading_date.isoformat(),
            "endpoints": int(len(ends)),
        },
        "target": manifest["target"],
        "seed_metrics": seed_metrics,
        "transition_shock_diagnostics": shock_diagnostics,
        "decision": decision,
        "warning": "This is a representation falsification result, not a costed trading P&L claim.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    consumed.write_text(
        json.dumps(
            {
                "session_sha256": session_sha256,
                "trading_date": trading_date.isoformat(),
                "result_path": str(output),
                "result_sha256": file_sha256(output),
                "verdict": decision["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(
        json.dumps(
            {"status": result["status"], "verdict": decision["verdict"], "output": str(output)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
