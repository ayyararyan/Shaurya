"""Cross-session option-surface benchmark with an untouched conditional final test."""

# ruff: noqa: UP006, UP007, UP017 - Apple research environment is Python 3.9.

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from torch import nn

from shaurya.research.option_surface_alpha import (
    block_bootstrap_p_value,
    holm_rejections,
    mae_skill,
)

NS = 1_000_000_000
STEP_NS = 5 * NS
HORIZONS = (6, 12, 60)
SEEDS = (1, 7, 23, 42, 101)
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class Session:
    timestamps: NDArray[np.int64]
    values: FloatArray
    columns: tuple[str, ...]
    date: str


@dataclass(frozen=True)
class CandidateResult:
    name: str
    target: str
    horizon_seconds: int
    representation: str
    model: str
    discovery_skill: float
    validation_skill: float
    validation_p_value: float
    validation_samples: int
    promoted_before_holm: bool
    holm_promoted: bool


class MaskedAutoencoder(nn.Module):
    def __init__(self, dimension: int, latent: int = 32) -> None:
        super().__init__()
        hidden = max(64, min(192, dimension * 2))
        self.encoder = nn.Sequential(
            nn.Linear(dimension, hidden), nn.GELU(), nn.Linear(hidden, latent)
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent, hidden), nn.GELU(), nn.Linear(hidden, dimension)
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(values))


def load_session(path: Path) -> Session:
    loaded = np.load(path, allow_pickle=False)
    return Session(
        timestamps=loaded["timestamps"].astype(np.int64),
        values=loaded["values"].astype(np.float64),
        columns=tuple(str(item) for item in loaded["columns"].tolist()),
        date=str(loaded["trading_date"].tolist()[0]),
    )


def valid_ends(session: Session, horizon: int, context: int = 12) -> NDArray[np.int64]:
    valid = []
    for end in range(context - 1, len(session.timestamps) - horizon):
        window = session.timestamps[end - context + 1 : end + horizon + 1]
        if np.all(np.diff(window) == STEP_NS):
            valid.append(end)
    return np.asarray(valid, dtype=np.int64)


def _indices(columns: tuple[str, ...], representation: str) -> NDArray[np.int64]:
    surface = np.asarray(
        [
            index
            for index, column in enumerate(columns)
            if column.startswith("surface__")
            or column.startswith("atm__straddle_")
            or column.startswith("atm__strike__")
        ],
        dtype=np.int64,
    )
    base = np.asarray(
        [index for index, column in enumerate(columns) if not column.startswith("surface__")],
        dtype=np.int64,
    )
    if representation == "base":
        return base
    if representation == "surface":
        return surface
    return np.arange(len(columns), dtype=np.int64)


def context_features(session: Session, ends: NDArray[np.int64], representation: str) -> FloatArray:
    indices = _indices(session.columns, representation)
    current = session.values[ends][:, indices]
    lag_30 = session.values[ends - 6][:, indices]
    lag_60 = session.values[ends - 11][:, indices]
    return np.concatenate((current, current - lag_30, current - lag_60), axis=1)


def targets(session: Session, ends: NDArray[np.int64], horizon: int) -> dict[str, FloatArray]:
    column = {name: index for index, name in enumerate(session.columns)}
    future = ends + horizon
    futures_change = session.values[future, column["futures_log_mid"]] - session.values[
        ends, column["futures_log_mid"]
    ]
    straddle = session.values[:, column["atm_near_straddle_to_future"]]
    straddle_change = (straddle[future] - straddle[ends]) * 10_000.0
    atm_iv = session.values[:, column["surface__atm_iv__near"]]
    iv_change = atm_iv[future] - atm_iv[ends]
    returns = session.values[:, column["futures_return_5s"]]
    realized = np.asarray(
        [math.sqrt(float(np.square(returns[end + 1 : end + horizon + 1]).sum())) for end in ends]
    )
    stable_strike = session.values[future, column["atm__strike__near"]] == session.values[
        ends, column["atm__strike__near"]
    ]
    return {
        "abs_futures_return": np.abs(futures_change),
        "realized_futures_volatility": realized,
        "abs_straddle_change_bps": np.where(stable_strike, np.abs(straddle_change), np.nan),
        "signed_straddle_change_bps": np.where(stable_strike, straddle_change, np.nan),
        "abs_atm_iv_change": np.abs(iv_change),
    }


def finite_rows(features: FloatArray, target: FloatArray) -> NDArray[np.bool_]:
    return np.isfinite(target) & np.all(np.isfinite(features), axis=1)


def train_autoencoder(
    train: FloatArray,
    sessions: list[FloatArray],
    *,
    seed: int,
) -> list[FloatArray]:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    center = np.nanmedian(train, axis=0)
    filled_train = np.where(np.isfinite(train), train, center)
    scale = np.nanstd(filled_train, axis=0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    normalized = np.clip((filled_train - center) / scale, -10.0, 10.0).astype(np.float32)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = MaskedAutoencoder(normalized.shape[1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    values = torch.from_numpy(normalized).to(device)
    model.train()
    for _ in range(80):
        permutation = rng.permutation(len(normalized))
        for start in range(0, len(normalized), 256):
            batch = values[torch.as_tensor(permutation[start : start + 256], device=device)]
            mask = torch.rand_like(batch) < 0.30
            prediction = model(batch.masked_fill(mask, 0.0))
            loss = torch.square(prediction[mask] - batch[mask]).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
    model.eval()
    outputs = []
    with torch.no_grad():
        for raw in sessions:
            filled = np.where(np.isfinite(raw), raw, center)
            normalized_session = np.clip((filled - center) / scale, -10.0, 10.0).astype(
                np.float32
            )
            encoded = model.encoder(torch.from_numpy(normalized_session).to(device))
            outputs.append(encoded.cpu().numpy().astype(np.float64))
    return outputs


def fit_predict(
    model_name: str,
    train_x: FloatArray,
    train_y: FloatArray,
    test_sets: list[FloatArray],
    seed: int,
) -> list[FloatArray]:
    scaler = StandardScaler().fit(train_x)
    scaled_train = scaler.transform(train_x)
    if model_name == "ridge":
        model: Any = Ridge(alpha=10.0)
    else:
        model = HistGradientBoostingRegressor(
            max_iter=150,
            learning_rate=0.04,
            max_leaf_nodes=15,
            l2_regularization=3.0,
            random_state=seed,
        )
    model.fit(scaled_train, train_y)
    return [model.predict(scaler.transform(values)) for values in test_sets]


def baseline(train_y: FloatArray, count: int) -> FloatArray:
    return np.full(count, np.median(train_y), dtype=np.float64)


def run(paths: list[Path], output: Path) -> dict[str, Any]:
    discovery, validation, final = [load_session(path) for path in paths]
    if not (discovery.columns == validation.columns == final.columns):
        raise ValueError("surface-state schemas differ")
    all_results: list[CandidateResult] = []
    cached: dict[tuple[int, str], tuple[FloatArray, FloatArray, FloatArray]] = {}
    for horizon in HORIZONS:
        ends = [valid_ends(session, horizon) for session in (discovery, validation, final)]
        target_sets = [
            targets(session, observed_ends, horizon)
            for session, observed_ends in zip(  # noqa: B905 - remote Python 3.9
                (discovery, validation), ends[:2]
            )
        ]
        split = int(len(ends[0]) * 0.60)
        for representation in ("base", "surface", "all"):
            feature_sets = [
                context_features(session, observed_ends, representation)
                for session, observed_ends in zip(  # noqa: B905 - remote Python 3.9
                    (discovery, validation, final), ends
                )
            ]
            cached[(horizon, representation)] = tuple(feature_sets)  # type: ignore[assignment]
            for target_name in target_sets[0]:
                raw_y = target_sets[0][target_name]
                train_mask = finite_rows(feature_sets[0][:split], raw_y[:split])
                discovery_mask = finite_rows(feature_sets[0][split:], raw_y[split:])
                validation_mask = finite_rows(feature_sets[1], target_sets[1][target_name])
                if min(train_mask.sum(), discovery_mask.sum(), validation_mask.sum()) < 100:
                    continue
                train_x = feature_sets[0][:split][train_mask]
                train_y = raw_y[:split][train_mask]
                discovery_x = feature_sets[0][split:][discovery_mask]
                discovery_y = raw_y[split:][discovery_mask]
                validation_x = feature_sets[1][validation_mask]
                validation_y = target_sets[1][target_name][validation_mask]
                for model_name in ("ridge", "hist_gradient_boosting"):
                    predictions = fit_predict(
                        model_name, train_x, train_y, [discovery_x, validation_x], seed=42
                    )
                    discovery_base = baseline(train_y, len(discovery_y))
                    validation_base = baseline(train_y, len(validation_y))
                    candidate_losses = np.abs(validation_y - predictions[1])
                    baseline_losses = np.abs(validation_y - validation_base)
                    p_value = block_bootstrap_p_value(candidate_losses, baseline_losses)
                    validation_skill = mae_skill(validation_y, predictions[1], validation_base)
                    name = f"{representation}__{model_name}__{target_name}__h{horizon * 5}"
                    all_results.append(
                        CandidateResult(
                            name=name,
                            target=target_name,
                            horizon_seconds=horizon * 5,
                            representation=representation,
                            model=model_name,
                            discovery_skill=mae_skill(discovery_y, predictions[0], discovery_base),
                            validation_skill=validation_skill,
                            validation_p_value=p_value,
                            validation_samples=len(validation_y),
                            promoted_before_holm=validation_skill > 0.0 and p_value <= 0.05,
                            holm_promoted=False,
                        )
                    )

        # A masked autoencoder is tested only on all factors to limit the search family.
        all_features = cached[(horizon, "all")]
        target_name = "abs_straddle_change_bps"
        target_arrays = [item[target_name] for item in target_sets]
        split_features = all_features[0][:split]
        seed_predictions: list[FloatArray] = []
        discovery_predictions: list[FloatArray] = []
        masks = [
            finite_rows(values, target)
            for values, target in zip(  # noqa: B905 - remote Python 3.9
                all_features, target_arrays
            )
        ]
        train_mask = masks[0][:split]
        discovery_mask = masks[0][split:]
        for seed in SEEDS:
            encoded = train_autoencoder(split_features[train_mask], list(all_features), seed=seed)
            predictions = fit_predict(
                "ridge",
                encoded[0][:split][train_mask],
                target_arrays[0][:split][train_mask],
                [encoded[0][split:][discovery_mask], encoded[1][masks[1]]],
                seed,
            )
            discovery_predictions.append(predictions[0])
            seed_predictions.append(predictions[1])
        train_y = target_arrays[0][:split][train_mask]
        discovery_y = target_arrays[0][split:][discovery_mask]
        validation_y = target_arrays[1][masks[1]]
        discovery_prediction = np.median(np.stack(discovery_predictions), axis=0)
        validation_prediction = np.median(np.stack(seed_predictions), axis=0)
        discovery_base = baseline(train_y, len(discovery_y))
        validation_base = baseline(train_y, len(validation_y))
        validation_skill = mae_skill(validation_y, validation_prediction, validation_base)
        p_value = block_bootstrap_p_value(
            np.abs(validation_y - validation_prediction), np.abs(validation_y - validation_base)
        )
        all_results.append(
            CandidateResult(
                name=f"all__masked_autoencoder_ridge__{target_name}__h{horizon * 5}",
                target=target_name,
                horizon_seconds=horizon * 5,
                representation="all",
                model="masked_autoencoder_ridge_5_seed_median",
                discovery_skill=mae_skill(discovery_y, discovery_prediction, discovery_base),
                validation_skill=validation_skill,
                validation_p_value=p_value,
                validation_samples=len(validation_y),
                promoted_before_holm=validation_skill > 0.0 and p_value <= 0.05,
                holm_promoted=False,
            )
        )

    p_values = {item.name: item.validation_p_value for item in all_results}
    rejected = holm_rejections(p_values)
    finalized = [
        CandidateResult(**{**asdict(item), "holm_promoted": item.name in rejected})
        for item in all_results
    ]
    promoted = [item for item in finalized if item.holm_promoted and item.validation_skill > 0]
    # The final target is intentionally not read unless a validation candidate survives Holm.
    final_evaluation: dict[str, Any] = {
        "accessed": False,
        "reason": "no Holm-corrected validation survivor",
    }
    if promoted:
        final_evaluation = {
            "accessed": False,
            "reason": "eligible: at least one candidate passed the frozen validation family",
            "note": "final refit/evaluation is deliberately a separate command after review",
        }
    result: dict[str, Any] = {
        "status": "validation_complete",
        "sessions": {
            "discovery": discovery.date,
            "validation": validation.date,
            "conditional_final": final.date,
        },
        "candidate_count": len(finalized),
        "holm_family_size": len(finalized),
        "promoted_candidates": [item.name for item in promoted],
        "final_evaluation": final_evaluation,
        "candidates": [asdict(item) for item in finalized],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    summary_keys = ("status", "candidate_count", "promoted_candidates", "final_evaluation")
    print(json.dumps({key: result[key] for key in summary_keys}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sessions", nargs=3, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.sessions, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
