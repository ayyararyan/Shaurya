"""Evaluate one frozen, validation-selected surface candidate on a final session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from surface_alpha_benchmark import (
    baseline,
    block_bootstrap_p_value,
    context_features,
    finite_rows,
    fit_predict,
    load_session,
    mae_skill,
    targets,
    valid_ends,
)


def run(
    discovery_path: Path,
    validation_path: Path,
    final_path: Path,
    selection_path: Path,
    candidate_name: str,
    output_path: Path,
) -> dict[str, Any]:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    candidates = {item["name"]: item for item in selection["candidates"]}
    candidate = candidates[candidate_name]
    if not candidate["holm_promoted"]:
        raise ValueError("candidate was not promoted by the frozen validation family")
    model_name = str(candidate["model"])
    if model_name not in {"ridge", "hist_gradient_boosting"}:
        raise ValueError("this evaluator supports the frozen supervised candidates only")

    discovery = load_session(discovery_path)
    validation = load_session(validation_path)
    final = load_session(final_path)
    if not (discovery.columns == validation.columns == final.columns):
        raise ValueError("surface-state schemas differ")

    horizon = int(candidate["horizon_seconds"]) // 5
    representation = str(candidate["representation"])
    target_name = str(candidate["target"])
    sessions = (discovery, validation, final)
    ends = [valid_ends(session, horizon) for session in sessions]
    features = [
        context_features(session, observed_ends, representation)
        for session, observed_ends in zip(sessions, ends, strict=True)
    ]
    target_sets = [
        targets(session, observed_ends, horizon)[target_name]
        for session, observed_ends in zip(sessions, ends, strict=True)
    ]
    split = int(len(ends[0]) * 0.60)
    train_mask = finite_rows(features[0][:split], target_sets[0][:split])
    validation_mask = finite_rows(features[1], target_sets[1])
    final_mask = finite_rows(features[2], target_sets[2])
    train_x = features[0][:split][train_mask]
    train_y = target_sets[0][:split][train_mask]
    validation_y = target_sets[1][validation_mask]
    final_y = target_sets[2][final_mask]
    validation_prediction, final_prediction = fit_predict(
        model_name,
        train_x,
        train_y,
        [features[1][validation_mask], features[2][final_mask]],
        seed=42,
    )
    validation_base = baseline(train_y, len(validation_y))
    final_base = baseline(train_y, len(final_y))
    result: dict[str, Any] = {
        "status": "frozen_candidate_final_evaluation_complete",
        "candidate": candidate_name,
        "selection_sessions": selection["sessions"],
        "final_session": final.date,
        "training_refit_after_selection": False,
        "validation_skill_reproduced": mae_skill(
            validation_y, validation_prediction, validation_base
        ),
        "final_skill_vs_discovery_constant": mae_skill(final_y, final_prediction, final_base),
        "final_p_value": block_bootstrap_p_value(
            np.abs(final_y - final_prediction), np.abs(final_y - final_base)
        ),
        "final_samples": len(final_y),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.discovery,
        args.validation,
        args.final,
        args.selection,
        args.candidate,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
