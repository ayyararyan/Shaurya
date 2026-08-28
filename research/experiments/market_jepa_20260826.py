"""Small JEPA-style market-state learner for the 2026-08-26 NIFTY tape.

This is a representation benchmark, not a trading backtest. It filters the
input to ``sample_role == train`` before any state construction, leaving the
official strategy holdout untouched.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from torch import Tensor, nn
from torch.utils.data import DataLoader, Dataset

NS = 1_000_000_000
STEP_SECONDS = 5
HORIZONS = (1, 6, 12)  # 5, 30, 60 seconds on a five-second grid.


@dataclass(frozen=True)
class Config:
    seed: int = 42
    context_steps: int = 12
    embedding_dim: int = 96
    transformer_layers: int = 3
    attention_heads: int = 4
    feedforward_dim: int = 256
    batch_size: int = 64
    epochs: int = 80
    patience: int = 12
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    ema_decay: float = 0.99
    variance_weight: float = 0.10
    split_train: float = 0.50
    split_validation: float = 0.25
    embargo_steps: int = 6


class SequenceDataset(Dataset):
    def __init__(
        self,
        normalized: np.ndarray,
        ends: np.ndarray,
        context_steps: int,
        horizons: Sequence[int],
    ) -> None:
        self.values = torch.from_numpy(normalized.astype(np.float32, copy=False))
        self.ends = ends.astype(np.int64, copy=False)
        self.context_steps = context_steps
        self.horizons = tuple(horizons)

    def __len__(self) -> int:
        return int(len(self.ends))

    def __getitem__(self, item: int) -> tuple[Tensor, Tensor, Tensor]:
        end = int(self.ends[item])
        context = self.values[end - self.context_steps + 1 : end + 1]
        target = torch.stack([self.values[end + horizon] for horizon in self.horizons])
        return context, target, torch.tensor(end, dtype=torch.long)


class StateEncoder(nn.Module):
    def __init__(self, input_dim: int, embedding_dim: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.LayerNorm(128),
            nn.GELU(),
            nn.Linear(128, embedding_dim),
            nn.LayerNorm(embedding_dim),
        )

    def forward(self, values: Tensor) -> Tensor:
        return self.network(values)


class MarketJepa(nn.Module):
    def __init__(self, input_dim: int, config: Config) -> None:
        super().__init__()
        self.config = config
        self.state_encoder = StateEncoder(input_dim, config.embedding_dim)
        self.target_encoder = copy.deepcopy(self.state_encoder)
        for parameter in self.target_encoder.parameters():
            parameter.requires_grad = False
        layer = nn.TransformerEncoderLayer(
            d_model=config.embedding_dim,
            nhead=config.attention_heads,
            dim_feedforward=config.feedforward_dim,
            dropout=0.10,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.context_encoder = nn.TransformerEncoder(
            layer, num_layers=config.transformer_layers, norm=nn.LayerNorm(config.embedding_dim)
        )
        self.position = nn.Parameter(torch.zeros(1, config.context_steps, config.embedding_dim))
        self.horizon_embedding = nn.Parameter(torch.zeros(1, len(HORIZONS), config.embedding_dim))
        self.predictor = nn.Sequential(
            nn.Linear(config.embedding_dim * 2, config.feedforward_dim),
            nn.GELU(),
            nn.Linear(config.feedforward_dim, config.embedding_dim),
        )
        nn.init.trunc_normal_(self.position, std=0.02)
        nn.init.trunc_normal_(self.horizon_embedding, std=0.02)

    def context_representation(self, context: Tensor) -> Tensor:
        encoded = self.state_encoder(context) + self.position
        return self.context_encoder(encoded)[:, -1]

    def forward(self, context: Tensor, targets: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        representation = self.context_representation(context)
        repeated = representation[:, None, :].expand(-1, len(HORIZONS), -1)
        horizon = self.horizon_embedding.expand(len(context), -1, -1)
        predictions = self.predictor(torch.cat([repeated, horizon], dim=-1))
        with torch.no_grad():
            target_embeddings = self.target_encoder(targets)
        return predictions, target_embeddings, representation

    @torch.no_grad()
    def update_target(self) -> None:
        decay = self.config.ema_decay
        for online, target in zip(  # noqa: B905 - research environment uses Python 3.9.
            self.state_encoder.parameters(), self.target_encoder.parameters()
        ):
            target.data.mul_(decay).add_(online.data, alpha=1.0 - decay)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame.columns = [
        "__".join(str(part) for part in column if str(part))
        if isinstance(column, tuple)
        else str(column)
        for column in frame.columns
    ]
    return frame


def build_market_states(panel_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    panel = pd.read_csv(panel_path)
    source_rows = len(panel)
    panel = panel[panel["sample_role"].eq("train") & panel["eligible_buffer_30s"]].copy()
    if panel.empty:
        raise ValueError("no eligible training rows")
    parts = panel["instrument_id"].str.split(":")
    panel["expiry_date"] = parts.str[4]
    panel["strike"] = pd.to_numeric(parts.str[5])
    panel["option_kind"] = parts.str[6]
    expiries = sorted(panel["expiry_date"].unique())
    panel["expiry_bucket"] = panel["expiry_date"].map({expiries[0]: "near", expiries[1]: "far"})
    panel["future_mid"] = np.exp(panel["futures_log_mid"])
    panel["option_mid"] = np.exp(panel["option_log_mid"])
    panel["moneyness"] = (panel["strike"] / panel["future_mid"] - 1.0).abs()
    panel["option_mid_to_future"] = panel["option_mid"] / panel["future_mid"]

    future_columns = [
        "futures_log_mid",
        "futures_relative_spread",
        "futures_microprice_dislocation",
        "futures_depth_imbalance",
        "futures_log_trade_intensity_10s",
        "futures_realized_volatility_30s",
    ]
    states = (
        panel[["timestamp_ns", *future_columns]]
        .drop_duplicates("timestamp_ns")
        .sort_values("timestamp_ns")
        .set_index("timestamp_ns")
    )
    states["futures_return_5s"] = states["futures_log_mid"].diff()

    aggregate_columns = [
        "option_mid_to_future",
        "option_relative_spread",
        "option_microprice_dislocation",
        "option_depth_imbalance",
        "option_return_5s",
    ]
    aggregate = panel.groupby(["timestamp_ns", "expiry_bucket", "option_kind"], observed=True)[
        aggregate_columns
    ].median()
    aggregate = aggregate.unstack(["expiry_bucket", "option_kind"])
    aggregate = _flatten_columns(aggregate)
    states = states.join(aggregate, how="left")

    atm_rows = panel.loc[
        panel.groupby(["timestamp_ns", "expiry_bucket", "option_kind"], observed=True)[
            "moneyness"
        ].idxmin()
    ]
    atm = atm_rows.pivot(
        index="timestamp_ns",
        columns=["expiry_bucket", "option_kind"],
        values=[
            "option_mid_to_future",
            "option_relative_spread",
            "option_depth_imbalance",
        ],
    )
    atm = _flatten_columns(atm)
    states = states.join(atm.add_prefix("atm__"), how="left")
    for bucket in ("near", "far"):
        call = states[f"atm__option_mid_to_future__{bucket}__CE"]
        put = states[f"atm__option_mid_to_future__{bucket}__PE"]
        states[f"atm_{bucket}_straddle_to_future"] = call + put
        states[f"atm_{bucket}_call_put_skew"] = call - put

    states = states.replace([np.inf, -np.inf], np.nan)
    metadata = {
        "source_rows": source_rows,
        "eligible_training_rows": int(len(panel)),
        "official_holdout_rows_read_into_state_builder": 0,
        "expiry_dates": expiries,
        "state_rows": int(len(states)),
        "state_features": list(states.columns),
    }
    return states, metadata


def valid_sequence_ends(
    timestamps: np.ndarray, config: Config
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    maximum_horizon = max(HORIZONS)
    possible = np.arange(config.context_steps - 1, len(timestamps) - maximum_horizon)
    valid: list[int] = []
    expected = STEP_SECONDS * NS
    for end in possible:
        window = timestamps[end - config.context_steps + 1 : end + maximum_horizon + 1]
        if np.all(np.diff(window) == expected):
            valid.append(int(end))
    valid_array = np.asarray(valid, dtype=np.int64)
    if len(valid_array) < 3:
        return valid_array, valid_array[:0], valid_array[:0]
    train_boundary = int(valid_array[int(len(valid_array) * config.split_train)])
    validation_boundary = int(
        valid_array[int(len(valid_array) * (config.split_train + config.split_validation))]
    )
    discovery = valid_array[valid_array + maximum_horizon < train_boundary]
    validation = valid_array[
        (valid_array - config.context_steps + 1 >= train_boundary + config.embargo_steps)
        & (valid_array + maximum_horizon < validation_boundary)
    ]
    test = valid_array[
        valid_array - config.context_steps + 1 >= validation_boundary + config.embargo_steps
    ]
    return discovery, validation, test


def loss_function(
    predictions: Tensor, targets: Tensor, variance_weight: float
) -> tuple[Tensor, dict[str, float]]:
    normalized_predictions = nn.functional.normalize(predictions, dim=-1)
    normalized_targets = nn.functional.normalize(targets, dim=-1)
    cosine_loss = (1.0 - (normalized_predictions * normalized_targets).sum(dim=-1)).mean()
    flat_predictions = predictions.reshape(-1, predictions.shape[-1])
    standard_deviation = torch.sqrt(flat_predictions.var(dim=0) + 1e-4)
    variance_loss = nn.functional.relu(0.5 - standard_deviation).mean()
    loss = cosine_loss + variance_weight * variance_loss
    return loss, {
        "loss": float(loss.detach().cpu()),
        "cosine_loss": float(cosine_loss.detach().cpu()),
        "variance_loss": float(variance_loss.detach().cpu()),
    }


@torch.no_grad()
def evaluate_jepa(model: MarketJepa, loader: DataLoader, device: torch.device) -> float:
    model.eval()
    losses: list[float] = []
    counts: list[int] = []
    for context, targets, _ in loader:
        context = context.to(device)
        targets = targets.to(device)
        predictions, target_embeddings, _ = model(context, targets)
        loss, _ = loss_function(predictions, target_embeddings, model.config.variance_weight)
        losses.append(float(loss.cpu()))
        counts.append(len(context))
    return float(np.average(losses, weights=counts))


def train_jepa(
    model: MarketJepa,
    train_loader: DataLoader,
    validation_loader: DataLoader,
    device: torch.device,
    output_dir: Path,
) -> dict[str, Any]:
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=model.config.learning_rate,
        weight_decay=model.config.weight_decay,
    )
    best_loss = math.inf
    best_epoch = -1
    stale_epochs = 0
    log_path = output_dir / "training_log.jsonl"
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        for epoch in range(model.config.epochs):
            model.train()
            batch_metrics: list[dict[str, float]] = []
            batch_sizes: list[int] = []
            for context, targets, _ in train_loader:
                context = context.to(device)
                targets = targets.to(device)
                optimizer.zero_grad(set_to_none=True)
                predictions, target_embeddings, _ = model(context, targets)
                loss, metrics = loss_function(
                    predictions, target_embeddings, model.config.variance_weight
                )
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                model.update_target()
                batch_metrics.append(metrics)
                batch_sizes.append(len(context))
            validation_loss = evaluate_jepa(model, validation_loader, device)
            record = {
                "epoch": epoch + 1,
                "train_loss": float(
                    np.average([item["loss"] for item in batch_metrics], weights=batch_sizes)
                ),
                "validation_loss": validation_loss,
                "elapsed_seconds": time.perf_counter() - started,
            }
            log.write(json.dumps(record, sort_keys=True) + "\n")
            log.flush()
            print(json.dumps(record, sort_keys=True), flush=True)
            if validation_loss < best_loss - 1e-5:
                best_loss = validation_loss
                best_epoch = epoch + 1
                stale_epochs = 0
                torch.save(model.state_dict(), output_dir / "best_model.pt")
            else:
                stale_epochs += 1
                if stale_epochs >= model.config.patience:
                    break
    model.load_state_dict(torch.load(output_dir / "best_model.pt", map_location=device))
    return {
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "epochs_run": epoch + 1,
        "training_seconds": time.perf_counter() - started,
    }


@torch.no_grad()
def embeddings_for(
    model: MarketJepa, dataset: SequenceDataset, device: torch.device
) -> tuple[np.ndarray, np.ndarray]:
    loader = DataLoader(dataset, batch_size=256, shuffle=False)
    model.eval()
    embeddings: list[np.ndarray] = []
    ends: list[np.ndarray] = []
    for context, _, batch_ends in loader:
        representation = model.context_representation(context.to(device))
        embeddings.append(representation.cpu().numpy())
        ends.append(batch_ends.numpy())
    return np.concatenate(embeddings), np.concatenate(ends)


def downstream_targets(
    raw: np.ndarray, ends: np.ndarray, columns: list[str]
) -> dict[str, np.ndarray]:
    future_index = columns.index("futures_log_mid")
    straddle_index = columns.index("atm_near_straddle_to_future")
    near_call_spread = columns.index("atm__option_relative_spread__near__CE")
    near_put_spread = columns.index("atm__option_relative_spread__near__PE")
    future = raw[:, future_index]
    one_step = np.diff(future, prepend=future[0])
    targets: dict[str, np.ndarray] = {}
    targets["absolute_future_return_30s"] = np.abs(future[ends + 6] - future[ends])
    targets["realized_volatility_30s"] = np.asarray(
        [math.sqrt(float(np.square(one_step[end + 1 : end + 7]).sum())) for end in ends]
    )
    targets["absolute_atm_straddle_change_30s"] = np.abs(
        raw[ends + 6, straddle_index] - raw[ends, straddle_index]
    )
    current_spread = (raw[ends, near_call_spread] + raw[ends, near_put_spread]) / 2.0
    future_spread = (raw[ends + 6, near_call_spread] + raw[ends + 6, near_put_spread]) / 2.0
    targets["near_atm_spread_change_30s"] = future_spread - current_spread
    return targets


def effective_rank(values: np.ndarray) -> float:
    centered = values - values.mean(axis=0, keepdims=True)
    singular = np.linalg.svd(centered, compute_uv=False)
    probabilities = singular / singular.sum()
    return float(np.exp(-(probabilities * np.log(probabilities + 1e-12)).sum()))


def probe(
    train_features: np.ndarray,
    validation_features: np.ndarray,
    test_features: np.ndarray,
    train_target: np.ndarray,
    validation_target: np.ndarray,
    test_target: np.ndarray,
) -> dict[str, Any]:
    alphas = (0.01, 0.1, 1.0, 10.0, 100.0)
    validation_scores: dict[str, float] = {}
    for alpha in alphas:
        estimator = Ridge(alpha=alpha).fit(train_features, train_target)
        prediction = estimator.predict(validation_features)
        validation_scores[str(alpha)] = float(mean_absolute_error(validation_target, prediction))
    selected_alpha = min(alphas, key=lambda item: validation_scores[str(item)])
    combined_features = np.concatenate([train_features, validation_features])
    combined_target = np.concatenate([train_target, validation_target])
    estimator = Ridge(alpha=selected_alpha).fit(combined_features, combined_target)
    prediction = estimator.predict(test_features)
    constant = np.full_like(test_target, np.median(combined_target))
    model_mae = float(mean_absolute_error(test_target, prediction))
    constant_mae = float(mean_absolute_error(test_target, constant))
    return {
        "selected_alpha": selected_alpha,
        "validation_mae_by_alpha": validation_scores,
        "test_mae": model_mae,
        "test_constant_mae": constant_mae,
        "test_mae_skill_vs_constant": 1.0 - model_mae / constant_mae,
        "test_r2": float(r2_score(test_target, prediction)),
    }


def benchmark(
    model: MarketJepa,
    normalized: np.ndarray,
    raw: np.ndarray,
    columns: list[str],
    split_ends: dict[str, np.ndarray],
    config: Config,
    device: torch.device,
) -> dict[str, Any]:
    representations: dict[str, dict[str, np.ndarray]] = {
        "last_state": {},
        "flattened_context": {},
        "jepa_embedding": {},
    }
    targets: dict[str, dict[str, np.ndarray]] = {}
    for split, ends in split_ends.items():
        dataset = SequenceDataset(normalized, ends, config.context_steps, HORIZONS)
        embeddings, observed_ends = embeddings_for(model, dataset, device)
        if not np.array_equal(ends, observed_ends):
            raise RuntimeError("embedding order differs from requested sequence order")
        representations["last_state"][split] = normalized[ends]
        representations["flattened_context"][split] = np.stack(
            [normalized[end - config.context_steps + 1 : end + 1].reshape(-1) for end in ends]
        )
        representations["jepa_embedding"][split] = embeddings
        targets[split] = downstream_targets(raw, ends, columns)

    results: dict[str, Any] = {}
    for target_name in targets["discovery"]:
        results[target_name] = {}
        for representation_name, split_features in representations.items():
            results[target_name][representation_name] = probe(
                split_features["discovery"],
                split_features["validation"],
                split_features["internal_test"],
                targets["discovery"][target_name],
                targets["validation"][target_name],
                targets["internal_test"][target_name],
            )
    internal_embeddings = representations["jepa_embedding"]["internal_test"]
    return {
        "targets": results,
        "embedding_diagnostics": {
            "mean_dimension_std": float(internal_embeddings.std(axis=0).mean()),
            "minimum_dimension_std": float(internal_embeddings.std(axis=0).min()),
            "effective_rank": effective_rank(internal_embeddings),
            "embedding_dimension": int(internal_embeddings.shape[1]),
        },
    }


def write_readme(result: dict[str, Any], path: Path) -> None:
    diagnostics = result["benchmark"]["embedding_diagnostics"]
    lines = [
        "# Market-JEPA prototype — 2026-08-26",
        "",
        "This is a representation benchmark, not a trading strategy or profitability claim.",
        "The official `sample_role=test` segment was excluded before state construction.",
        "",
        "## Training",
        "",
        f"- Device: `{result['device']}`",
        f"- Parameters: {result['parameter_count']:,}",
        f"- Best epoch: {result['training']['best_epoch']}",
        f"- Training seconds: {result['training']['training_seconds']:.1f}",
        f"- Internal-test embedding effective rank: {diagnostics['effective_rank']:.2f} / "
        f"{diagnostics['embedding_dimension']}",
        "",
        "## Frozen linear-probe results",
        "",
        "MAE skill is relative to a discovery+validation median forecast. Positive is better.",
        "",
        "| target | last state | flattened context | JEPA embedding |",
        "|---|---:|---:|---:|",
    ]
    for target, representations in result["benchmark"]["targets"].items():
        lines.append(
            f"| {target} | {representations['last_state']['test_mae_skill_vs_constant']:+.2%} | "
            f"{representations['flattened_context']['test_mae_skill_vs_constant']:+.2%} | "
            f"{representations['jepa_embedding']['test_mae_skill_vs_constant']:+.2%} |"
        )
    lines.extend(
        [
            "",
            (
                "The internal test is a later slice of the original training region only. "
                "Results from one"
            ),
            "afternoon cannot establish generalisation across sessions or economic value.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("panel", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=Config.epochs)
    parser.add_argument("--seed", type=int, default=Config.seed)
    args = parser.parse_args()
    config = Config(epochs=args.epochs, seed=args.seed)
    set_seed(config.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    states, state_metadata = build_market_states(args.panel)
    columns = list(states.columns)
    timestamps = states.index.to_numpy(dtype=np.int64)
    discovery_ends, validation_ends, test_ends = valid_sequence_ends(timestamps, config)
    if min(len(discovery_ends), len(validation_ends), len(test_ends)) < 30:
        raise ValueError(
            "insufficient chronological sequences after embargoes: "
            f"states={len(states)}, discovery={len(discovery_ends)}, "
            f"validation={len(validation_ends)}, internal_test={len(test_ends)}"
        )

    discovery_boundary = int(len(states) * config.split_train)
    discovery_values = states.iloc[:discovery_boundary]
    medians = discovery_values.median()
    filled = states.fillna(medians).fillna(0.0)
    center = discovery_values.fillna(medians).fillna(0.0).mean().to_numpy()
    scale = discovery_values.fillna(medians).fillna(0.0).std().replace(0.0, 1.0).to_numpy()
    raw = filled.to_numpy(dtype=np.float64)
    normalized = np.clip((raw - center) / scale, -10.0, 10.0).astype(np.float32)

    train_dataset = SequenceDataset(normalized, discovery_ends, config.context_steps, HORIZONS)
    validation_dataset = SequenceDataset(
        normalized, validation_ends, config.context_steps, HORIZONS
    )
    generator = torch.Generator().manual_seed(config.seed)
    train_loader = DataLoader(
        train_dataset, batch_size=config.batch_size, shuffle=True, generator=generator
    )
    validation_loader = DataLoader(validation_dataset, batch_size=config.batch_size, shuffle=False)

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = MarketJepa(normalized.shape[1], config).to(device)
    training = train_jepa(model, train_loader, validation_loader, device, args.output_dir)
    split_ends = {
        "discovery": discovery_ends,
        "validation": validation_ends,
        "internal_test": test_ends,
    }
    benchmark_results = benchmark(model, normalized, raw, columns, split_ends, config, device)
    result = {
        "status": "prototype_complete",
        "interpretation": "representation benchmark only; no tradable-alpha claim",
        "official_holdout_accessed": False,
        "device": str(device),
        "torch_version": torch.__version__,
        "config": asdict(config),
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "state_metadata": state_metadata,
        "split_sequences": {name: int(len(ends)) for name, ends in split_ends.items()},
        "training": training,
        "benchmark": benchmark_results,
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    np.savez_compressed(
        args.output_dir / "market_states.npz",
        timestamps=timestamps,
        values=raw,
        normalized=normalized,
        columns=np.asarray(columns),
    )
    write_readme(result, args.output_dir / "README.md")
    print(json.dumps({"status": result["status"], "device": result["device"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
