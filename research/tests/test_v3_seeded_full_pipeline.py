from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.tape import DepthLevel, QualityFlag, TapeRow
from shaurya.data import DataCaptureSession, DataCatalog, TapeIntegrityError

from shaurya.cli.research import main as research_main
from shaurya.research.contracts import ResearchMode, canonical_json
from shaurya.research.ledger import EvidenceLedger
from shaurya.research.nulls import nested_walkforward_empirical_null
from shaurya.research.registry import expand_hypotheses, load_registry
from shaurya.research.source import (
    DerivedResearchDataset,
    VerifiedResearchSource,
    derive_research_dataset,
    verify_completed_source,
)
from shaurya.research.stability import stability_summary
from shaurya.research.state import StateStore
from shaurya.research.surfaces import (
    SurfaceCell,
    build_complete_surface,
    hypothesis_surface,
    parameter_movement,
    surface_robustness,
    validate_surface_artifacts,
)
from shaurya.research.walkforward import freeze_historical_folds


def _registries(root: Path):  # type: ignore[no-untyped-def]
    feature_path = root / "features.yaml"
    target_path = root / "targets.yaml"
    feature_path.write_text(
        canonical_json(
            {
                "registry_type": "features",
                "version": "features-v1",
                "frozen": True,
                "instrument_tick_sizes": {
                    "NIFTY_FUTURES": 0.05,
                    "BANKNIFTY_FUTURES": 0.05,
                },
                "templates": [
                    {
                        "feature_id_pattern": "ofi.cumulative.depth={depth}.window={window}s",
                        "axes": {"depth": [1, 2], "window": [1]},
                    }
                ],
                "features": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    target_path.write_text(
        canonical_json(
            {
                "registry_type": "targets",
                "version": "targets-v1",
                "frozen": True,
                "targets": [
                    {
                        "target_id": "future_mid_return.horizon=1s",
                        "anchor": "receive_time",
                        "causal_gap_seconds": 0.5,
                        "horizon_seconds": 1,
                        "reference_price": "displayed_bbo_mid",
                        "availability": "interval_end",
                        "missingness": "missing if either endpoint unavailable",
                        "instruments": ["NIFTY_FUTURES"],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return load_registry(feature_path, expected_type="features"), load_registry(
        target_path, expected_type="targets"
    )


def test_source_derivation_partitions_instrument_channel_epoch_and_shallow_depth(
    tmp_path: Path,
) -> None:
    session = date(2026, 2, 2)
    stamp = datetime(2026, 2, 2, 9, tzinfo=UTC)
    nifty = "NSE:NSE_FNO:NIFTY:future:2026-02-26"
    bank = "NSE:NSE_FNO:BANKNIFTY:future:2026-02-26"
    request = DatasetRequest(
        consumer="SIG",
        purpose="partition integrity",
        trading_date=session,
        channels=(DataChannel.DEPTH20,),
        instrument_ids=(nifty, bank),
    )
    capture = DataCaptureSession.create(
        catalog=DataCatalog(tmp_path / "catalog.jsonl"),
        request=request,
        output_root=tmp_path / "raw",
        run_id=RunId("sha-20260202T090000.000000Z-deadbeef"),
        fsync_every=1,
        index_stride_rows=2,
    )
    sequence = 0
    for time_index in range(8):
        for instrument_index, instrument in enumerate((nifty, bank)):
            sequence += 1
            epoch = 1 if time_index < 4 else 2
            levels = 1 if time_index == 2 else 2
            midpoint = 25_000 + 20 * instrument_index + time_index / 10
            capture.write(
                TapeRow(
                    run_id="sha-20260202T090000.000000Z-deadbeef",
                    receive_sequence=sequence,
                    connection_epoch=epoch,
                    source="seeded-partition-fixture",
                    event_type="depth20",
                    instrument_id=instrument,
                    broker_security_id=str(100 + instrument_index),
                    exchange_segment="NSE_FNO",
                    receive_ts=stamp + timedelta(seconds=time_index / 2),
                    raw_message_size_bytes=100,
                    update_side="both",
                    bids=tuple(
                        DepthLevel(midpoint - 0.5 - level, 100 + time_index + level, 2)
                        for level in range(levels)
                    ),
                    asks=tuple(
                        DepthLevel(midpoint + 0.5 + level, 100 - time_index + level, 2)
                        for level in range(levels)
                    ),
                    quality_flags=(QualityFlag.RECONNECTED,) if time_index == 4 else (),
                )
            )
    handle = capture.close()
    features, targets = _registries(tmp_path)
    with pytest.raises(TapeIntegrityError, match="genuine depth"):
        derive_research_dataset(
            (verify_completed_source(handle, catalog=DataCatalog(tmp_path / "catalog.jsonl")),),
            feature_registry=features,
            target_registry=targets,
        )


def test_derived_dataset_constructor_and_tampered_surface_fail_closed() -> None:
    with pytest.raises(TypeError, match="catalog verification"):
        VerifiedResearchSource(
            "forged",
            date(2026, 1, 1),
            Path("catalog"),
            "segmented_parquet",
            "a" * 64,
            "b" * 64,
            "logical-run",
            1,
            1,
            "start",
            "end",
            ("instrument",),
            ("depth20",),
            "c" * 64,
        )
    with pytest.raises(TypeError, match="verified DAT derivation"):
        DerivedResearchDataset((), "f", "a" * 64, "t", "b" * 64, (), (), (), "c" * 64, "d" * 64)
    surface = build_complete_surface(
        mechanism="ORDER_FLOW_IMPACT",
        axes=("depth",),
        axis_values={"depth": (1.0, 2.0)},
        cells=(
            SurfaceCell((("depth", 1.0),), "alpha-a", 0.2, 1, 20),
            SurfaceCell((("depth", 2.0),), "alpha-b", 0.1, 1, 20),
        ),
    )
    robustness = surface_robustness(surface)
    with pytest.raises(ValueError, match="surface"):
        validate_surface_artifacts(replace(surface, surface_hash="f" * 64), robustness)


def _scenario_registries(root: Path):  # type: ignore[no-untyped-def]
    feature_path = root / "scenario-features.yaml"
    target_path = root / "scenario-targets.yaml"
    hypothesis_path = root / "scenario-hypotheses.yaml"
    feature_path.write_text(
        canonical_json(
            {
                "registry_type": "features",
                "version": "scenario-features-v1",
                "frozen": True,
                "instrument_tick_sizes": {"NIFTY_FUTURES": 0.05},
                "templates": [
                    {
                        "feature_id_pattern": "ofi.cumulative.depth={depth}.window={window}s",
                        "axes": {"depth": [1], "window": [1]},
                    }
                ],
                "features": [{"feature_id": "regime.minutes_from_open"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    target_path.write_text(
        canonical_json(
            {
                "registry_type": "targets",
                "version": "scenario-targets-v1",
                "frozen": True,
                "targets": [
                    {
                        "target_id": f"future_mid_return.horizon={horizon}s",
                        "anchor": "receive_time",
                        "causal_gap_seconds": 0.5,
                        "horizon_seconds": horizon,
                        "reference_price": "displayed_bbo_mid",
                        "availability": "interval_end",
                        "missingness": "missing if either endpoint unavailable",
                        "instruments": ["NIFTY_FUTURES"],
                    }
                    for horizon in (1, 2)
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    hypothesis_path.write_text(
        canonical_json(
            {
                "registry_type": "hypotheses",
                "version": "scenario-hypotheses-v1",
                "frozen": True,
                "templates": [
                    {
                        "display_name": "seeded-{target_horizon_seconds}s-{regime}",
                        "family": "ORDER_FLOW/OFI",
                        "predictor_feature_ids": ["ofi.cumulative.depth={depth}.window={window}s"],
                        "target_id": "future_mid_return.horizon={target_horizon_seconds}s",
                        "target_horizon_seconds": 1,
                        "conditioning_variables": [],
                        "admissible_regime": "global",
                        "model_class": "ridge",
                        "fitting_window_sessions": 20,
                        "training_cadence_seconds": 0.5,
                        "regularization": {"ridge_penalty": 1e-12},
                        "evaluation_metric": "pearson_correlation",
                        "transaction_cost_relevance": "diagnostic_only",
                        "first_registration_date": "2025-12-31",
                        "minimum_observations": 10,
                        "minimum_effective_sample_size": 5,
                        "axes": {
                            "depth": [1],
                            "window": [1],
                            "target_horizon_seconds": [1, 2],
                            "model_class": ["ridge"],
                            "sampling_clock": ["event"],
                            "pooling_coordinate": ["instrument"],
                            "regime": ["global", "early_persistent"],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return (
        load_registry(feature_path, expected_type="features"),
        load_registry(target_path, expected_type="targets"),
        load_registry(hypothesis_path, expected_type="hypotheses"),
    )


def test_seeded_canonical_tapes_run_full_null_break_horizon_and_regime_path(
    tmp_path: Path,
) -> None:
    features, targets, hypothesis_registry = _scenario_registries(tmp_path)
    hypotheses = expand_hypotheses(hypothesis_registry)
    instrument = "NSE:NSE_FNO:NIFTY:future:2026-02-26"
    start = date(2026, 1, 1)
    verified = []
    handle_paths: list[Path] = []
    for session_index in range(14):
        session = start + timedelta(days=session_index)
        stamp = datetime.combine(session, datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
        run_id = RunId(f"sha-{stamp:%Y%m%dT%H%M%S}.000000Z-{session_index + 1:08x}")
        capture = DataCaptureSession.create(
            catalog=DataCatalog(tmp_path / "scenario-catalog.jsonl"),
            request=DatasetRequest(
                consumer="SIG",
                purpose="seeded source-bound scenario",
                trading_date=session,
                channels=(DataChannel.DEPTH20,),
                instrument_ids=(instrument,),
            ),
            output_root=tmp_path / "scenario-raw",
            run_id=run_id,
            fsync_every=100,
            index_stride_rows=10,
        )
        midpoint = 25_000.0
        for index in range(50):
            block = 6 if session_index < 9 or index < 20 else 2
            direction = 1 if (index // block + session_index) % 2 == 0 else -1
            price_direction = (
                direction if session_index < 9 or index < 20 else -direction
            )
            midpoint += 0.08 * price_direction
            capture.write(
                TapeRow(
                    run_id=str(run_id),
                    receive_sequence=index + 1,
                    connection_epoch=1,
                    source="seeded-source-bound-scenario",
                    event_type="depth20",
                    instrument_id=instrument,
                    broker_security_id="58072",
                    exchange_segment="NSE_FNO",
                    receive_ts=stamp + timedelta(seconds=index / 2),
                    raw_message_size_bytes=100,
                    update_side="both",
                    bids=(DepthLevel(midpoint - 0.5, 100 + 3 * direction, 2),),
                    asks=(DepthLevel(midpoint + 0.5, 100 - 3 * direction, 2),),
                )
            )
        handle = capture.close()
        handle_path = tmp_path / f"scenario-handle-{session.isoformat()}.json"
        handle_path.write_text(handle.model_dump_json(), encoding="utf-8")
        handle_paths.append(handle_path)
        verified.append(
            verify_completed_source(
                handle, catalog=DataCatalog(tmp_path / "scenario-catalog.jsonl")
            )
        )
    dataset = derive_research_dataset(
        tuple(verified), feature_registry=features, target_registry=targets
    )
    folds = freeze_historical_folds(
        tuple(item.trading_date for item in dataset.sources),
        through=dataset.sources[-1].trading_date,
        minimum_training_sessions=5,
        validation_sessions=1,
        purge_seconds=0,
        embargo_seconds=0,
    )
    policy = {
        "regime_rules": {
            "causal_only": True,
            "definitions": {
                "global": {"strategy": "always"},
                "early_persistent": {
                    "strategy": "threshold",
                    "feature_id": "regime.minutes_from_open",
                    "operator": "le",
                    "value": 0.16,
                },
            },
        },
        "null_simulation": {
            "method": "circular_shift",
            "statistic": "maximum_absolute_score",
            "rerun_complete_miner": True,
            "replicates": 20,
            "seed": 20260826,
            "minimum_shift_blocks": 2,
        },
    }
    nested, null = nested_walkforward_empirical_null(
        dataset,
        tuple(hypotheses),
        folds,
        policy=policy,
        mode=ResearchMode.CONFIRMATORY,
    )
    assert null.observed_walkforward_hash == nested.result_hash
    assert len(null.replicate_walkforward_hashes) == 20
    assert 1 / (null.replicates + 1) < 0.05
    assert sum(value <= 0.05 for _, value in null.candidate_adjusted_p_values) <= 1
    labels = {item.display_name: item.hypothesis_id for item in hypotheses}
    global_one = labels["seeded-1s-global"]
    global_two = labels["seeded-2s-global"]
    early_one = labels["seeded-1s-early_persistent"]
    early_two = labels["seeded-2s-early_persistent"]
    fold_dates = {fold.fold_id: fold.outer_evaluation_dates[0] for fold in folds}

    def scores(identity: str, *, late: bool) -> list[float]:
        values = []
        for result in nested.candidate_results:
            if result.hypothesis_id != identity or result.outer_score is None:
                continue
            is_late = fold_dates[result.fold_id] >= start + timedelta(days=9)
            if is_late == late:
                values.append(result.outer_score)
        return values

    early_global = scores(global_one, late=False)
    late_global = scores(global_one, late=True)
    late_conditioned = scores(early_one, late=True)
    late_two = scores(global_two, late=True)
    assert early_global and late_global and late_conditioned
    assert sum(early_global) / len(early_global) > sum(late_global) / len(late_global)
    conditioned_mean = sum(late_conditioned) / len(late_conditioned)
    global_mean = sum(late_global) / len(late_global)
    assert conditioned_mean > global_mean, (conditioned_mean, global_mean)
    assert late_two and sum(late_two) / len(late_two) != sum(late_global) / len(late_global)
    by_fold = {
        (item.fold_id, item.hypothesis_id): item for item in nested.candidate_results
    }
    assert all(
        by_fold[(fold.fold_id, early_one)].outer_observations
        < by_fold[(fold.fold_id, global_one)].outer_observations
        for fold in folds
    )
    stability = stability_summary([*early_global, *late_global])
    assert stability.rolling_degradation is not None
    assert stability.rolling_degradation < 0
    early_scores = {
        identity: (
            sum(values) / len(values)
            if (values := scores(identity, late=False))
            else None
        )
        for identity in labels.values()
    }
    late_scores = {
        identity: (
            sum(values) / len(values) if (values := scores(identity, late=True)) else None
        )
        for identity in labels.values()
    }
    support = {
        identity: sum(
            item.outer_observations
            for item in nested.candidate_results
            if item.hypothesis_id == identity
        )
        for identity in labels.values()
    }
    early_surface = hypothesis_surface(hypotheses, scores=early_scores, support=support)
    late_surface = hypothesis_surface(hypotheses, scores=late_scores, support=support)
    movement = parameter_movement(
        surface_robustness(early_surface), surface_robustness(late_surface)
    )
    assert movement["classification"] == "parameter_movement_within_uncertainty", movement
    assert movement["distance"] == 1

    policy_path = tmp_path / "scenario-policy.yaml"
    policy_path.write_text(
        canonical_json(
            {
                "registry_type": "policy",
                "version": "scenario-policy-v1",
                "frozen": True,
                "permitted_model_classes": ["ridge"],
                "selection_methods": ["nested_past_only"],
                "training_windows_sessions": [20],
                "training_cadences_seconds": [0.5],
                "sampling_clocks": ["event"],
                "pooling_coordinates": ["instrument"],
                "selection_thresholds": [0.15],
                "validation": {"minimum_inner_sessions": 3, "scheme": "expanding"},
                "outer_test": {
                    "sessions_per_block": 1,
                    "purge_seconds": 0,
                    "embargo_seconds": 0,
                },
                "minimum_evidence": {
                    "observations": 10,
                    "effective_sample_size": 5,
                    "sessions_for_provisional": 3,
                    "sessions_for_stable": 4,
                    "outer_folds_for_stable": 4,
                },
                "multiplicity": {
                    "method": "benjamini_yekutieli",
                    "fdr": 0.05,
                    "family_level": True,
                },
                "promotion": {
                    "minimum_sign_consistency": 0.5,
                    "minimum_neighbor_robustness": 0.0,
                    "minimum_adjusted_evidence": 0.0,
                    "minimum_abs_score": 0.0,
                    "single_day_promotion": False,
                },
                "decay": {
                    "weakening_ratio": 0.5,
                    "decaying_consecutive_sessions": 2,
                    "dormant_consecutive_sessions": 3,
                },
                "reactivation": {
                    "minimum_new_confirmatory_sessions": 2,
                    "retrospective_reactivation": False,
                },
                "null_simulation": {
                    "method": "circular_shift",
                    "minimum_shift_blocks": 2,
                    "replicates": 20,
                    "seed": 20260826,
                    "statistic": "maximum_absolute_score",
                    "rerun_complete_miner": True,
                },
                "regime_rules": {
                    "causal_only": True,
                    "minimum_bucket_observations": 5,
                    "definitions": policy["regime_rules"]["definitions"],
                },
                "robustness": {
                    "require_complete_surface": True,
                    "isolated_spike_penalty": 0.5,
                    "block_bootstrap": True,
                    "block_bootstrap_replicates": 39,
                    "block_bootstrap_mean_length": 4.0,
                    "block_bootstrap_seed": 20260826,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    plan_path = tmp_path / "scenario-plan.json"
    plan_date = start + timedelta(days=5)
    registry_args = [
        "--registry-dir",
        str(tmp_path),
        "--feature-registry",
        "scenario-features-v1",
        "--target-registry",
        "scenario-targets-v1",
        "--hypothesis-registry",
        "scenario-hypotheses-v1",
        "--policy",
        "scenario-policy-v1",
    ]
    assert research_main(
        [
            "plan-alpha",
            "--through",
            plan_date.isoformat(),
            *registry_args,
            "--output",
            str(plan_path),
        ]
    ) == 0
    state_dir = tmp_path / "scenario-state"
    ledger_path = tmp_path / "scenario-ledger.jsonl"
    report_dir = tmp_path / "scenario-reports"
    snapshot_dir = tmp_path / "scenario-snapshots"
    source_prefix = [
        value
        for path in handle_paths[:6]
        for value in ("--source-handle", str(path))
    ]
    assert research_main(
        [
            "init-alpha-state",
            "--plan",
            str(plan_path),
            "--as-of",
            plan_date.isoformat(),
            "--intended-for-session",
            (plan_date + timedelta(days=1)).isoformat(),
            "--catalog",
            str(tmp_path / "scenario-catalog.jsonl"),
            *source_prefix,
            "--state-dir",
            str(state_dir),
            "--ledger",
            str(ledger_path),
            *registry_args,
        ]
    ) == 0
    initial_state = StateStore(state_dir).load_as_of(plan_date)
    assert initial_state is not None
    state_path = state_dir / f"{plan_date.isoformat()}-{initial_state.state_hash}.json"
    assert research_main(
        [
            "mine-alpha",
            "--through",
            plan_date.isoformat(),
            "--plan",
            str(plan_path),
            "--state",
            str(state_path),
            "--catalog",
            str(tmp_path / "scenario-catalog.jsonl"),
            *source_prefix,
            "--ledger",
            str(ledger_path),
            *registry_args,
        ]
    ) == 0
    reports: list[dict[str, Any]] = []
    for index in range(6, len(handle_paths)):
        evaluation_date = start + timedelta(days=index)
        assert research_main(
            [
                "evaluate-alpha",
                "--date",
                evaluation_date.isoformat(),
                "--next-session",
                (evaluation_date + timedelta(days=1)).isoformat(),
                "--plan",
                str(plan_path),
                "--state",
                str(state_path),
                "--catalog",
                str(tmp_path / "scenario-catalog.jsonl"),
                *(
                    value
                    for path in handle_paths[: index + 1]
                    for value in ("--source-handle", str(path))
                ),
                "--ledger",
                str(ledger_path),
                "--state-dir",
                str(state_dir),
                "--report-dir",
                str(report_dir),
                "--snapshot-dir",
                str(snapshot_dir),
                *registry_args,
            ]
        ) == 0
        current_state = StateStore(state_dir).load_as_of(evaluation_date)
        assert current_state is not None
        state_path = state_dir / (
            f"{evaluation_date.isoformat()}-{current_state.state_hash}.json"
        )
        report_path = report_dir / f"alpha-research-{evaluation_date.isoformat()}.json"
        reports.append(json.loads(report_path.read_text(encoding="utf-8")))

    ledger = EvidenceLedger(ledger_path)
    scientific = ledger.events(event_type="daily_scientific_artifacts")
    assert len(scientific) == len(reports) == 8
    assert all(int(item["empirical_null"]["replicates"]) == 20 for item in scientific)
    assert (
        max(
            int(report["multiple_testing_context"]["adjusted_findings"])
            for report in reports
        )
        <= 1
    )
    historical_states = [
        StateStore(state_dir).load_as_of(start + timedelta(days=index))
        for index in range(6, 14)
    ]
    assert any(
        state is not None and any(status == "STABLE" for _, status in state.lifecycle)
        for state in historical_states
    )
    movement_reports = [
        report["scientific_diagnostics"]["parameter_movement"] for report in reports
    ]
    assert any(
        item["ORDER_FLOW_IMPACT"]["classification"]
        == "parameter_movement_within_uncertainty"
        and item["ORDER_FLOW_IMPACT"]["distance"] == 1
        for item in movement_reports[1:]
    )
    stability_reports = [
        report["scientific_diagnostics"]["stability_summary"] for report in reports
    ]
    assert any(
        summary[global_two]["rolling_degradation"] is not None
        and summary[global_two]["rolling_degradation"] < 0
        for summary in stability_reports
    )
    assert any(
        any(
            gate["hypothesis_id"] == early_two and gate["regime_comparison_pass"]
            for gate in item["candidate_gates"]
        )
        for item in scientific
    )
