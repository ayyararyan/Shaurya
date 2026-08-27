"""Execute the D51 same-day exploratory nested walk-forward experiment."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypeVar

from shaurya.contracts.data import DatasetStatus
from shaurya.contracts.timing import IST, nse_equity_derivatives_session_bounds
from shaurya.data import DataAccess, DataCatalog

from shaurya.analytics.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    build_states_streaming,
    parse_receive_ts_ns,
)
from shaurya.analytics.ofi_replication import iter_session_rows
from shaurya.analytics.surface_feed import SurfaceEngine, default_log_moneyness_grid
from shaurya.signals.feature_selection import (
    FeatureSelectionRow,
    build_feature_selection_rows,
    conditional_usefulness_artifact_from_json,
    conditional_usefulness_artifact_to_json,
    elastic_net_cluster_stability_artifact_from_json,
    elastic_net_cluster_stability_artifact_to_json,
    regression_metrics,
    stability_selection_artifact_from_json,
    stability_selection_artifact_to_json,
)
from shaurya.signals.feature_selection_walkforward import (
    NestedWalkForwardConfig,
    build_complete_walk_forward_evidence,
    construct_nested_expanding_folds,
    nested_walk_forward_artifact_from_json,
    nested_walk_forward_artifact_to_json,
    run_nested_walk_forward,
    sample_on_grid,
)
from shaurya.signals.ofi_horserace import build_horserace_observations
from shaurya.signals.surface_futures_predictive import EXPIRIES, frame_draft

FUTURES_RUN_ID = "sha-20260821T030335.366578Z-2038e775"
FUTURES_SHA256 = "d28d69c1d8fe627ac8553b02a4d75ee02915797594ff31ffbecd7ebe9beafc88"
SURFACE_DATASET_ID = "sha-20260821T080612.138551Z-9b5bd89e"
TRADING_DATE = date(2026, 8, 21)
MATERIALIZATION_CACHE_VERSION = "d51-common-rows-v1"
COMPUTE_CHECKPOINT_VERSION = "d51-compute-checkpoint-v1"
CheckpointValue = TypeVar("CheckpointValue")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--futures-tape", type=Path, required=True)
    parser.add_argument("--data-catalog", type=Path, required=True)
    parser.add_argument("--surface-dataset-id", default=SURFACE_DATASET_ID)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--materialization-cache",
        type=Path,
        help="SHA-bound gzip JSON cache of the exact common constructed rows.",
    )
    parser.add_argument("--grid-seconds", type=int, choices=(1, 5), default=1)
    parser.add_argument(
        "--fast-tree-grid",
        action="store_true",
        help="Predeclared runtime sensitivity: evaluate all depth/leaf/min-leaf arms at lr=0.05.",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _surface_frames(access: DataAccess, dataset_id: str) -> tuple[list[Any], Mapping[str, Any]]:
    handle = access.handle(dataset_id)
    if handle.status is not DatasetStatus.COMPLETED or handle.tape_sha256 is None:
        raise ValueError("surface DAT handle must be completed and SHA-pinned")
    engine = SurfaceEngine(
        run_id=handle.dataset_id,
        surface_id="D51-10S-FEATURE-SELECTION-2026-08-21",
        expiries=EXPIRIES,
        log_moneyness_grid=default_log_moneyness_grid(),
        fit_interval_seconds=5.0,
        wall_clock=False,
        history_limit=2,
    )
    frames: list[Any] = []
    previous_levels: dict[str, float] | None = None
    previous_ts_ns: int | None = None
    attempted = 0
    failed = 0
    for row in access.rows(handle):
        engine.ingest(row)
        stamp = row.receive_ts.astimezone(IST)
        if not engine.due_for_fit(stamp):
            continue
        attempted += 1
        snapshot = engine.fit(stamp)
        if not snapshot.fit_ok:
            failed += 1
            continue
        draft, current = frame_draft(snapshot, previous_levels, previous_ts_ns)
        if current is None:
            failed += 1
            continue
        if draft is not None:
            frames.append(draft)
        previous_levels = current
        previous_ts_ns = int(round(snapshot.fit_timestamp.timestamp() * 1_000_000_000))
    if not frames:
        raise ValueError("completed surface DAT dataset produced no usable canonical eSSVI frames")
    return frames, {
        "dataset_id": handle.dataset_id,
        "storage_format": str(handle.storage_format),
        "dataset_digest": handle.dataset_digest or handle.tape_sha256,
        "rows": handle.rows,
        "bytes": handle.bytes,
        "coverage_start": handle.coverage_start.isoformat() if handle.coverage_start else None,
        "coverage_end": handle.coverage_end.isoformat() if handle.coverage_end else None,
        "attempted_surface_fits": attempted,
        "failed_surface_fits": failed,
        "usable_surface_frames": len(frames),
        "first_surface_frame_ts_ns": frames[0].receive_ts_ns,
        "last_surface_frame_ts_ns": frames[-1].receive_ts_ns,
    }


def _futures_materialization(
    tape: Path, *, common_start_ts_ns: int, common_end_ts_ns: int, grid_seconds: int
) -> tuple[list[Any], list[Any], Mapping[str, Any]]:
    computed = _sha256(tape)
    if computed != FUTURES_SHA256:
        raise ValueError(f"futures tape SHA-256 changed: {computed}")
    history_start = common_start_ts_ns - 30 * 1_000_000_000

    def common_rows() -> Iterable[dict[str, Any]]:
        yield from _bounded_session_rows(
            tape,
            start_ts_ns=history_start,
            end_ts_ns=common_end_ts_ns + 11 * 1_000_000_000,
        )

    depth200 = build_states_streaming(common_rows(), DEPTH200)
    depth20 = build_states_streaming(common_rows(), DEPTH20)
    standard = [row for row in common_rows() if row.get("event_type") == "full"]
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=standard,
        tape_index=0,
        run_id=FUTURES_RUN_ID,
        level_counts=(1, 5, 10, 20, 50, 100, 200),
        response_horizons=(10.0,),
        anchor_grid_seconds=float(grid_seconds),
        anchor_start_ts_ns=common_start_ts_ns,
        anchor_end_ts_ns=common_end_ts_ns,
    )
    return (
        observations,
        depth20,
        {
            "run_id": FUTURES_RUN_ID,
            "tape_path": str(tape.resolve()),
            "tape_sha256": computed,
            "bytes": tape.stat().st_size,
            "depth200_states": len(depth200),
            "depth20_states": len(depth20),
            "standard_rows": len(standard),
            "horse_observations": len(observations),
            "construction_failures": failures,
        },
    )


def _bounded_session_rows(
    tape: Path, *, start_ts_ns: int, end_ts_ns: int
) -> Iterable[dict[str, Any]]:
    """Read the D51 date explicitly, never the older replication module's frozen default."""

    for row in iter_session_rows(tape, trading_date=TRADING_DATE):
        timestamp = row.get("receive_ts")
        if not isinstance(timestamp, str):
            continue
        stamp = parse_receive_ts_ns(timestamp)
        if start_ts_ns <= stamp <= end_ts_ns:
            yield row


def _csv(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    fields = sorted({name for row in rows for name in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write(value)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(value)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def _feature_row_payload(row: FeatureSelectionRow) -> Mapping[str, Any]:
    return {
        "anchor_ts_ns": row.anchor_ts_ns,
        "connection_epoch": row.connection_epoch,
        "target_start_ts_ns": row.target_start_ts_ns,
        "target_end_ts_ns": row.target_end_ts_ns,
        "target_ticks": row.target_ticks,
        "feature_values": dict(row.feature_values),
        "feature_available_ts_ns": dict(row.feature_available_ts_ns),
        "registry_version": row.registry_version,
        "evidence_label": row.evidence_label,
    }


def _feature_row_from_payload(payload: Mapping[str, Any]) -> FeatureSelectionRow:
    return FeatureSelectionRow(
        anchor_ts_ns=int(payload["anchor_ts_ns"]),
        connection_epoch=int(payload["connection_epoch"]),
        target_start_ts_ns=int(payload["target_start_ts_ns"]),
        target_end_ts_ns=int(payload["target_end_ts_ns"]),
        target_ticks=float(payload["target_ticks"]),
        feature_values={
            str(name): None if value is None else float(value)
            for name, value in dict(payload["feature_values"]).items()
        },
        feature_available_ts_ns={
            str(name): None if value is None else int(value)
            for name, value in dict(payload["feature_available_ts_ns"]).items()
        },
        registry_version=str(payload["registry_version"]),
        evidence_label=str(payload["evidence_label"]),
    )


def _common_row_fingerprint(rows: Sequence[FeatureSelectionRow]) -> str:
    encoded = json.dumps(
        [_feature_row_payload(row) for row in rows],
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _materialization_cache_bytes(
    rows: Sequence[FeatureSelectionRow],
    *,
    grid_seconds: int,
    futures_source: Mapping[str, Any],
    surface_source: Mapping[str, Any],
    constructed_row_count: int,
) -> bytes:
    payload = {
        "version": MATERIALIZATION_CACHE_VERSION,
        "trading_date": TRADING_DATE.isoformat(),
        "grid_seconds": grid_seconds,
        "futures_source": dict(futures_source),
        "surface_source": dict(surface_source),
        "constructed_row_count": constructed_row_count,
        "common_row_fingerprint_sha256": _common_row_fingerprint(rows),
        "rows": [_feature_row_payload(row) for row in rows],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return gzip.compress(encoded.encode(), compresslevel=9, mtime=0)


def _materialization_cache_from_bytes(
    encoded: bytes,
    *,
    grid_seconds: int,
    futures_sha256: str,
    surface_dataset_id: str,
    surface_sha256: str,
) -> tuple[tuple[FeatureSelectionRow, ...], Mapping[str, Any], Mapping[str, Any], int]:
    payload = json.loads(gzip.decompress(encoded))
    if payload.get("version") != MATERIALIZATION_CACHE_VERSION:
        raise ValueError("unsupported D51 materialization cache version")
    if payload.get("trading_date") != TRADING_DATE.isoformat():
        raise ValueError("D51 materialization cache trading date changed")
    if int(payload.get("grid_seconds", -1)) != grid_seconds:
        raise ValueError("D51 materialization cache grid changed")
    futures_source = dict(payload["futures_source"])
    surface_source = dict(payload["surface_source"])
    if futures_source.get("tape_sha256") != futures_sha256:
        raise ValueError("D51 materialization cache futures SHA changed")
    if surface_source.get("dataset_id") != surface_dataset_id:
        raise ValueError("D51 materialization cache surface dataset changed")
    if surface_source.get("tape_sha256") != surface_sha256:
        raise ValueError("D51 materialization cache surface SHA changed")
    rows = tuple(_feature_row_from_payload(item) for item in payload["rows"])
    if not rows or _common_row_fingerprint(rows) != payload.get("common_row_fingerprint_sha256"):
        raise ValueError("D51 materialization cache row fingerprint changed")
    return rows, futures_source, surface_source, int(payload["constructed_row_count"])


def _checkpoint_text(*, kind: str, identity: Mapping[str, Any], artifact_json: str) -> str:
    payload = {
        "version": COMPUTE_CHECKPOINT_VERSION,
        "kind": kind,
        "identity": dict(identity),
        "artifact_sha256": hashlib.sha256(artifact_json.encode()).hexdigest(),
        "artifact": json.loads(artifact_json),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _checkpoint_artifact_json(encoded: str, *, kind: str, identity: Mapping[str, Any]) -> str:
    payload = json.loads(encoded)
    if payload.get("version") != COMPUTE_CHECKPOINT_VERSION:
        raise ValueError("unsupported D51 compute checkpoint version")
    if payload.get("kind") != kind:
        raise ValueError("D51 compute checkpoint kind changed")
    if payload.get("identity") != dict(identity):
        raise ValueError("D51 compute checkpoint data/config identity changed")
    artifact_json = json.dumps(
        payload["artifact"], sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if hashlib.sha256(artifact_json.encode()).hexdigest() != payload.get("artifact_sha256"):
        raise ValueError("D51 compute checkpoint artifact fingerprint changed")
    return artifact_json


def _load_or_build_checkpoint(
    path: Path,
    *,
    kind: str,
    identity: Mapping[str, Any],
    factory: Callable[[], CheckpointValue],
    serializer: Callable[[CheckpointValue], str],
    reader: Callable[[str], CheckpointValue],
) -> CheckpointValue:
    """Resume an exact identity-bound artifact or build and atomically publish it once."""

    if path.exists():
        artifact_json = _checkpoint_artifact_json(
            path.read_text(encoding="utf-8"), kind=kind, identity=identity
        )
        return reader(artifact_json)
    result = factory()
    artifact_json = serializer(result)
    if reader(artifact_json) != result:
        raise AssertionError(f"{kind} checkpoint exact readback failed")
    _write(
        path,
        _checkpoint_text(kind=kind, identity=identity, artifact_json=artifact_json) + "\n",
    )
    return result


def _model_rows(artifact: Any) -> list[dict[str, Any]]:
    return [
        {
            "fold_id": item.fold_id,
            "model_id": item.model_id,
            "model_kind": item.model_kind,
            "training_rows": item.training_rows,
            "validation_rows": item.validation_rows,
            "test_rows": item.test_rows,
            "feature_count": item.feature_count,
            "cluster_count": item.cluster_count,
            "mse": item.metrics.mean_squared_error,
            "mae": item.metrics.mean_absolute_error,
            "oos_r2_vs_zero": item.metrics.r_squared_vs_zero,
            "oos_r2_vs_training_mean": item.metrics.r_squared_vs_training_mean,
            "correlation": item.metrics.pearson_correlation,
            "directional_accuracy": item.metrics.directional_accuracy,
            "selected_config": json.dumps(item.selected_config, sort_keys=True),
        }
        for item in artifact.model_results
    ]


def _gate_rows(evidence: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for fold in evidence.fold_evidence:
        excluded = set(fold.excluded_features)
        for diagnostic in fold.training_feature_diagnostics:
            result.append(
                {
                    "fold_id": fold.fold_id,
                    **diagnostic,
                    "eligible": diagnostic["feature_name"] not in excluded,
                }
            )
        for reason, count in sorted(fold.gate_reason_counts.items()):
            result.append(
                {
                    "fold_id": fold.fold_id,
                    "feature_name": "__all__",
                    "gate_reason": reason,
                    "gate_reason_count": count,
                }
            )
    return result


def _cluster_rows(evidence: Any) -> list[dict[str, Any]]:
    return [
        {
            "fold_id": fold.fold_id,
            "cluster_id": cluster.cluster_id,
            "family": cluster.family,
            "members": json.dumps(cluster.members),
            "model_features": json.dumps(cluster.model_features),
            "member_count": len(cluster.members),
            "representation": "representative",
        }
        for fold in evidence.fold_evidence
        for cluster in fold.cluster_definitions
    ]


def _ablation_rows(evidence: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fold in evidence.fold_evidence:
        for artifact in fold.usefulness_artifacts:
            for comparison in (
                *artifact.cluster_ablation_comparisons,
                *artifact.family_ablation_comparisons,
                *artifact.block_permutation_comparisons,
            ):
                rows.append(
                    {
                        "fold_id": fold.fold_id,
                        "model_kind": artifact.config.model_kind,
                        "comparison_kind": comparison.comparison_kind,
                        "comparison_id": comparison.comparison_id,
                        "cluster_ids": json.dumps(comparison.cluster_ids),
                        "training_rows": comparison.support_training_rows,
                        "evaluation_rows": comparison.support_evaluation_rows,
                        "delta_oos_r_squared": comparison.delta_oos_r_squared,
                        "direction": comparison.direction,
                        "permutation_repeat": comparison.permutation_repeat,
                        "permutation_seed": comparison.permutation_seed,
                        "paired_loss_blocks": len(comparison.paired_losses.blocks),
                    }
                )
    return rows


def _stability_rows(evidence: Any) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": item.cluster_id,
            "model_id": item.model_id,
            "family": item.family,
            "members": json.dumps(item.members),
            "status": item.status,
            "reason_codes": json.dumps(item.reason_codes),
            "eligible_folds": item.eligible_fold_count,
            "distinct_sessions": item.distinct_eligible_session_count,
            "selection_frequency": item.selection_frequency,
            "median_delta_oos_r_squared": item.median_delta_oos_r_squared,
            "fraction_positive_folds": item.fraction_positive_folds,
            "direction_consistency": item.direction_consistency,
            "consistent_direction": item.consistent_direction,
            "volatility_regimes": json.dumps(item.volatility_regime_coverage),
            "spread_regimes": json.dumps(item.spread_regime_coverage),
            "time_phases": json.dumps(item.time_phase_coverage),
            "one_session_dominance": item.one_session_dominance,
            "past_mirror_median_delta": item.past_mirror_median_delta_oos_r_squared,
            "cost_latency_adjusted_median_value": item.cost_latency_adjusted_median_value,
            "past_mirror_guard": (
                "not_supplied"
                if item.past_mirror_median_delta_oos_r_squared is None
                else "evaluated"
            ),
            "economic_guard": (
                "not_supplied" if item.cost_latency_adjusted_median_value is None else "evaluated"
            ),
            "aggregate_comparator_minus_full_mean_squared_loss": (
                item.aggregate_comparator_minus_full_mean_squared_loss
            ),
        }
        for item in evidence.stability_selection.selections
    ]


def _row_regimes(row: FeatureSelectionRow) -> Mapping[str, str]:
    values = row.feature_values
    move = values.get("regime__abs_lag_return_10s_per_sqrt_second")
    spread = values.get("regime__spread_ticks")
    minutes = values.get("regime__minutes_from_open")
    return {
        "volatility": (
            "missing"
            if move is None
            else "zero"
            if move == 0.0
            else "low_le_1"
            if move <= 1.0
            else "medium_le_5"
            if move <= 5.0
            else "high_gt_5"
        ),
        "spread": (
            "missing"
            if spread is None
            else "tight_le_1"
            if spread <= 1.0
            else "normal_le_2"
            if spread <= 2.0
            else "wide_gt_2"
        ),
        "time_phase": (
            "missing"
            if minutes is None
            else "open_first_60m"
            if minutes < 60.0
            else "mid_session_60_300m"
            if minutes < 300.0
            else "close_after_300m"
        ),
    }


def _regime_slice_rows(
    common: Sequence[FeatureSelectionRow], artifact: Any
) -> list[dict[str, Any]]:
    sampled = sample_on_grid(common, grid_seconds=artifact.config.sampling_grid_seconds)
    folds = {
        fold.fold_id: fold
        for fold in construct_nested_expanding_folds(sampled, config=artifact.config)
    }
    result: list[dict[str, Any]] = []
    for model in artifact.model_results:
        fold = folds[model.fold_id]
        targets = tuple(sampled[index].target_ticks for index in fold.outer_test_indices)
        training_mean = sum(
            sampled[index].target_ticks for index in fold.outer_training_indices
        ) / len(fold.outer_training_indices)
        for axis in ("volatility", "spread", "time_phase"):
            labels = tuple(_row_regimes(sampled[index])[axis] for index in fold.outer_test_indices)
            for label in sorted(set(labels)):
                positions = tuple(index for index, value in enumerate(labels) if value == label)
                metrics = regression_metrics(
                    tuple(targets[index] for index in positions),
                    tuple(model.predictions[index] for index in positions),
                    training_mean=training_mean,
                )
                result.append(
                    {
                        "fold_id": model.fold_id,
                        "model_id": model.model_id,
                        "axis": axis,
                        "regime": label,
                        "rows": metrics.observation_count,
                        "mse": metrics.mean_squared_error,
                        "mae": metrics.mean_absolute_error,
                        "oos_r2_vs_zero": metrics.r_squared_vs_zero,
                        "oos_r2_vs_training_mean": metrics.r_squared_vs_training_mean,
                        "correlation": metrics.pearson_correlation,
                        "directional_accuracy": metrics.directional_accuracy,
                    }
                )
    return result


def execute(args: argparse.Namespace) -> Mapping[str, Any]:
    access = DataAccess(DataCatalog(args.data_catalog))
    cache_path = getattr(args, "materialization_cache", None)
    cache_reused = cache_path is not None and cache_path.exists()
    if cache_reused:
        handle = access.handle(args.surface_dataset_id)
        if handle.status is not DatasetStatus.COMPLETED or handle.tape_sha256 is None:
            raise ValueError("surface DAT handle must be completed and SHA-pinned")
        computed_futures_sha256 = _sha256(args.futures_tape)
        if computed_futures_sha256 != FUTURES_SHA256:
            raise ValueError(f"futures tape SHA-256 changed: {computed_futures_sha256}")
        assert cache_path is not None
        common, futures_source, surface_source, constructed_row_count = (
            _materialization_cache_from_bytes(
                cache_path.read_bytes(),
                grid_seconds=args.grid_seconds,
                futures_sha256=computed_futures_sha256,
                surface_dataset_id=args.surface_dataset_id,
                surface_sha256=handle.tape_sha256,
            )
        )
    else:
        surface_frames, surface_source = _surface_frames(access, args.surface_dataset_id)
        observations, books, futures_source = _futures_materialization(
            args.futures_tape,
            common_start_ts_ns=surface_frames[0].receive_ts_ns,
            common_end_ts_ns=surface_frames[-1].receive_ts_ns,
            grid_seconds=args.grid_seconds,
        )
        opened, closed = nse_equity_derivatives_session_bounds(TRADING_DATE)
        construction = build_feature_selection_rows(
            observations=observations,
            books=books,
            surface_frames=surface_frames,
            session_open_ts_ns=int(round(opened.timestamp() * 1_000_000_000)),
            session_close_ts_ns=int(round(closed.timestamp() * 1_000_000_000)),
        )
        first_surface = surface_frames[0].receive_ts_ns
        last_surface = surface_frames[-1].receive_ts_ns
        common = tuple(
            row
            for row in construction.rows
            if first_surface <= row.anchor_ts_ns <= last_surface
            and any(
                name.startswith("surface__") and value is not None
                for name, value in row.feature_values.items()
            )
        )
        constructed_row_count = len(construction.rows)
        if cache_path is not None:
            cache_bytes = _materialization_cache_bytes(
                common,
                grid_seconds=args.grid_seconds,
                futures_source=futures_source,
                surface_source=surface_source,
                constructed_row_count=constructed_row_count,
            )
            # Assert exact in-memory parity before publishing a reusable cache.
            cached_rows, _, _, cached_constructed_count = _materialization_cache_from_bytes(
                cache_bytes,
                grid_seconds=args.grid_seconds,
                futures_sha256=str(futures_source["tape_sha256"]),
                surface_dataset_id=args.surface_dataset_id,
                surface_sha256=str(surface_source["tape_sha256"]),
            )
            if cached_rows != common or cached_constructed_count != constructed_row_count:
                raise AssertionError("D51 materialization cache exact readback failed")
            _write_bytes(cache_path, cache_bytes)
    if len(common) < 30:
        raise ValueError("surface/futures common support is insufficient for walk-forward")
    policy = NestedWalkForwardConfig(sampling_grid_seconds=args.grid_seconds)
    output = args.output_dir
    checkpoint_dir = output / "checkpoints"
    common_fingerprint = _common_row_fingerprint(common)
    checkpoint_base_identity = {
        "specification_version": "1.6.0",
        "common_row_fingerprint_sha256": common_fingerprint,
        "futures_sha256": futures_source["tape_sha256"],
        "surface_dataset_id": surface_source["dataset_id"],
        "surface_sha256": surface_source["tape_sha256"],
        "walk_forward_config": asdict(policy),
        "fast_tree_grid": bool(args.fast_tree_grid),
    }
    walk_checkpoint = checkpoint_dir / "d51_walk_forward.json"
    artifact = _load_or_build_checkpoint(
        walk_checkpoint,
        kind="walk_forward",
        identity=checkpoint_base_identity,
        factory=lambda: run_nested_walk_forward(
            common,
            session_id="2026-08-21",
            config=policy,
            fast_tree_grid=args.fast_tree_grid,
        ),
        serializer=nested_walk_forward_artifact_to_json,
        reader=nested_walk_forward_artifact_from_json,
    )
    selected_by_fold_kind = {
        (item.fold_id, item.model_kind): item
        for item in artifact.model_results
        if item.model_kind in ("elastic_net", "shallow_gradient_boosting")
    }
    selected_rows = [
        {
            "fold_id": fold_id,
            "model_kind": model_kind,
            "model_id": item.model_id,
            "selected_config": json.dumps(item.selected_config, sort_keys=True),
            "selected_estimators": (
                item.selected_config.get("maximum_estimators")
                if model_kind == "shallow_gradient_boosting"
                else None
            ),
        }
        for (fold_id, model_kind), item in sorted(selected_by_fold_kind.items())
    ]
    _write(checkpoint_dir / "d51_selected_model_configs.csv", _csv(selected_rows))

    def importance_provider(
        fold_id: str,
        model_kind: Literal["elastic_net", "shallow_gradient_boosting"],
        factory: Callable[[], Any],
    ) -> Any:
        selected_model = selected_by_fold_kind[(fold_id, model_kind)]
        identity = {
            **checkpoint_base_identity,
            "fold_fingerprint_sha256": artifact.fold_fingerprint_sha256,
            "fold_id": fold_id,
            "model_kind": model_kind,
            "selected_model_id": selected_model.model_id,
            "selected_config": dict(selected_model.selected_config),
        }
        path = checkpoint_dir / f"d51_importance_{fold_id}_{model_kind}.json"
        return _load_or_build_checkpoint(
            path,
            kind="conditional_usefulness",
            identity=identity,
            factory=factory,
            serializer=conditional_usefulness_artifact_to_json,
            reader=conditional_usefulness_artifact_from_json,
        )

    def elastic_stability_provider(fold_id: str, factory: Callable[[], Any]) -> Any:
        selected_model = selected_by_fold_kind[(fold_id, "elastic_net")]
        identity = {
            **checkpoint_base_identity,
            "fold_fingerprint_sha256": artifact.fold_fingerprint_sha256,
            "fold_id": fold_id,
            "model_kind": "elastic_net_stability",
            "selected_model_id": selected_model.model_id,
            "selected_config": dict(selected_model.selected_config),
        }
        path = checkpoint_dir / f"d51_elastic_stability_{fold_id}.json"
        return _load_or_build_checkpoint(
            path,
            kind="elastic_net_stability",
            identity=identity,
            factory=factory,
            serializer=elastic_net_cluster_stability_artifact_to_json,
            reader=elastic_net_cluster_stability_artifact_from_json,
        )

    evidence = build_complete_walk_forward_evidence(
        common,
        session_id="2026-08-21",
        walk_forward=artifact,
        importance_provider=importance_provider,
        elastic_stability_provider=elastic_stability_provider,
    )
    model_rows = _model_rows(artifact)
    gate_rows = _gate_rows(evidence)
    cluster_rows = _cluster_rows(evidence)
    ablation_rows = _ablation_rows(evidence)
    stability_rows = _stability_rows(evidence)
    regime_rows = _regime_slice_rows(common, artifact)
    summary = {
        "specification_id": "D51-10S-FEATURE-SELECTION-2026-08-21",
        "specification_version": "1.6.0",
        "evidence_status": "exploratory_insufficient_sessions",
        "confirmatory_eligible": False,
        "distinct_sessions": 1,
        "sampling_grid_seconds": args.grid_seconds,
        "sampling_grid_role": (
            "primary_engineering_convention" if args.grid_seconds == 1 else "runtime_sensitivity"
        ),
        "estimand_changed": False,
        "futures_source": futures_source,
        "surface_source": surface_source,
        "constructed_rows_full_futures_support": constructed_row_count,
        "common_surface_futures_rows_before_grid": len(common),
        "common_row_fingerprint_sha256": common_fingerprint,
        "materialization_cache": (
            None
            if cache_path is None
            else {
                "path": str(cache_path.resolve()),
                "version": MATERIALIZATION_CACHE_VERSION,
                "reused": cache_reused,
            }
        ),
        "common_support_start_ts_ns": common[0].anchor_ts_ns,
        "common_support_end_ts_ns": common[-1].anchor_ts_ns,
        "sampled_rows": artifact.sampled_row_count,
        "fold_fingerprint_sha256": artifact.fold_fingerprint_sha256,
        "model_results": model_rows,
        "gate_table_rows": len(gate_rows),
        "cluster_table_rows": len(cluster_rows),
        "ablation_table_rows": len(ablation_rows),
        "stability_table_rows": len(stability_rows),
        "regime_slice_rows": len(regime_rows),
        "limitations": [
            "one retained session cannot establish stability or promotion",
            "surface capture starts late; no surface state is fabricated before first usable frame",
            "exploratory model/config selection only; no inference, signal, deployment "
            "or order claim",
        ],
    }
    walk_json = nested_walk_forward_artifact_to_json(artifact)
    if nested_walk_forward_artifact_from_json(walk_json) != artifact:
        raise AssertionError("walk-forward exact artifact readback failed")
    _write(output / "d51_walk_forward.json", walk_json + "\n")
    _write(output / "d51_model_table.csv", _csv(model_rows))
    _write(output / "d51_gate_table.csv", _csv(gate_rows))
    _write(output / "d51_cluster_table.csv", _csv(cluster_rows))
    _write(output / "d51_ablation_table.csv", _csv(ablation_rows))
    _write(output / "d51_stability_table.csv", _csv(stability_rows))
    _write(output / "d51_regime_slices.csv", _csv(regime_rows))
    stability_json = stability_selection_artifact_to_json(evidence.stability_selection)
    if stability_selection_artifact_from_json(stability_json) != evidence.stability_selection:
        raise AssertionError("stability-selection exact artifact readback failed")
    _write(output / "d51_stability_selection.json", stability_json + "\n")
    for fold in evidence.fold_evidence:
        for importance in fold.usefulness_artifacts:
            importance_json = conditional_usefulness_artifact_to_json(importance)
            if conditional_usefulness_artifact_from_json(importance_json) != importance:
                raise AssertionError("conditional-usefulness exact artifact readback failed")
            _write(
                output / f"d51_importance_{fold.fold_id}_{importance.config.model_kind}.json",
                importance_json + "\n",
            )
        elastic_json = elastic_net_cluster_stability_artifact_to_json(fold.elastic_net_stability)
        if (
            elastic_net_cluster_stability_artifact_from_json(elastic_json)
            != fold.elastic_net_stability
        ):
            raise AssertionError("elastic-net stability exact artifact readback failed")
        _write(output / f"d51_elastic_stability_{fold.fold_id}.json", elastic_json + "\n")
    _write(output / "d51_summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report = (
        "# D51 same-day exploratory feature selection — 2026-08-21\n\n"
        "Status: **exploratory_insufficient_sessions**. This is one-session screening evidence, "
        "not a stable feature, signal, confirmation, deployment, or order claim.\n\n"
        f"- Futures SHA-256: `{futures_source['tape_sha256']}`\n"
        f"- Surface DAT SHA-256: `{surface_source['tape_sha256']}`\n"
        f"- Exact common rows before grid: {len(common):,}\n"
        f"- Sampled {args.grid_seconds}-second rows: {artifact.sampled_row_count:,}\n"
        f"- Common support timestamps (ns): {common[0].anchor_ts_ns} to {common[-1].anchor_ts_ns}\n"
        f"- Gate/cluster/ablation/stability/regime table rows: {len(gate_rows):,} / "
        f"{len(cluster_rows):,} / {len(ablation_rows):,} / {len(stability_rows):,} / "
        f"{len(regime_rows):,}\n"
        "- Past-mirror and cost/latency guards are explicitly unavailable for this one-session "
        "same-day source; they are not imputed.\n"
        "- The sampling grid is an empirical execution convention; the frozen ten-second "
        "estimand is unchanged.\n"
    )
    _write(output / "D51-EXPLORATORY-RESULT-2026-08-21.md", report)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    execute(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
