from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data import DataCaptureSession, DataCatalog

from shaurya.research.contracts import canonical_json
from shaurya.research.ledger import EvidenceLedger
from shaurya.research.planner import alpha_plan_from_mapping
from shaurya.research.state import StateStore


def _write_registries(directory: Path) -> None:
    directory.mkdir()
    registries = {
        "features_v1.yaml": {
            "registry_type": "features",
            "version": "features_v1",
            "frozen": True,
            "instrument_tick_sizes": {"NIFTY_FUTURES": 0.05},
            "templates": [
                {
                    "feature_id_pattern": "ofi.cumulative.depth={depth}.window={window}s",
                    "axes": {"depth": [1], "window": [1]},
                }
            ],
            "features": [
                {
                    "feature_id": "control.source_keyed_ar1_phi_0_8",
                    "family": "NEGATIVE_CONTROL",
                    "timing_rule": "causal source/time-keyed deterministic AR(1)",
                }
            ],
        },
        "targets_v1.yaml": {
            "registry_type": "targets",
            "version": "targets_v1",
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
        },
        "hypotheses_v1.yaml": {
            "registry_type": "hypotheses",
            "version": "hypotheses_v1",
            "frozen": True,
            "templates": [
                {
                    "display_name": "{model_class}-{sampling_clock}",
                    "family": "ORDER_FLOW/OFI",
                    "predictor_feature_ids": ["ofi.cumulative.depth={depth}.window={window}s"],
                    "target_id": "future_mid_return.horizon={target_horizon_seconds}s",
                    "target_horizon_seconds": 1,
                    "conditioning_variables": [],
                    "admissible_regime": "global",
                    "model_class": "ridge",
                    "fitting_window_sessions": 20,
                    "training_cadence_seconds": 1,
                    "regularization": {
                        "ridge_penalty": 1.0,
                        "elastic_alpha": 0.01,
                        "elastic_l1_ratio": 0.5,
                    },
                    "evaluation_metric": "pearson_correlation",
                    "transaction_cost_relevance": "diagnostic_only",
                    "selection_method": "nested_past_only",
                    "selection_threshold": 0.15,
                    "minimum_observations": 20,
                    "minimum_effective_sample_size": 10,
                    "first_registration_date": "2026-01-01",
                    "axes": {
                        "depth": [1],
                        "window": [1],
                        "target_horizon_seconds": [1],
                        "model_class": ["ridge", "elastic_net"],
                        "sampling_clock": ["event", "calendar_1s"],
                        "pooling_coordinate": ["instrument"],
                        "regime": ["global"],
                    },
                },
                {
                    "display_name": "source-keyed AR(1) negative control",
                    "family": "NEGATIVE_CONTROL/SOURCE_KEYED_AR1",
                    "predictor_feature_ids": ["control.source_keyed_ar1_phi_0_8"],
                    "target_id": "future_mid_return.horizon=1s",
                    "target_horizon_seconds": 1,
                    "conditioning_variables": [],
                    "admissible_regime": "global",
                    "model_class": "ridge",
                    "fitting_window_sessions": 20,
                    "training_cadence_seconds": 1,
                    "regularization": {"ridge_penalty": 1.0},
                    "evaluation_metric": "pearson_correlation",
                    "transaction_cost_relevance": "diagnostic_only",
                    "selection_method": "nested_past_only",
                    "selection_threshold": 0.15,
                    "minimum_observations": 20,
                    "minimum_effective_sample_size": 10,
                    "first_registration_date": "2026-01-01",
                    "axes": {},
                }
            ],
        },
        "policy_v1.yaml": {
            "registry_type": "policy",
            "version": "policy_v1",
            "frozen": True,
            "permitted_model_classes": ["ridge", "elastic_net"],
            "selection_methods": ["nested_past_only"],
            "training_windows_sessions": [20],
            "training_cadences_seconds": [1],
            "sampling_clocks": ["event", "calendar_1s"],
            "pooling_coordinates": ["instrument"],
            "selection_thresholds": [0.15],
            "validation": {"minimum_inner_sessions": 3, "scheme": "expanding"},
            "outer_test": {
                "sessions_per_block": 1,
                "purge_seconds": 5,
                "embargo_seconds": 5,
            },
            "minimum_evidence": {
                "observations": 20,
                "effective_sample_size": 10,
                "sessions_for_provisional": 3,
                "sessions_for_stable": 5,
                "outer_folds_for_stable": 3,
            },
            "multiplicity": {
                "method": "benjamini_yekutieli",
                "fdr": 0.05,
                "family_level": True,
            },
            "promotion": {
                "minimum_sign_consistency": 0.6,
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
                "replicates": 3,
                "seed": 20260826,
                "statistic": "maximum_absolute_score",
                "rerun_complete_miner": True,
            },
            "regime_rules": {
                "causal_only": True,
                "minimum_bucket_observations": 10,
                "definitions": {"global": {"strategy": "always"}},
            },
            "robustness": {
                "require_complete_surface": True,
                "isolated_spike_penalty": 0.5,
                "block_bootstrap": True,
                "block_bootstrap_replicates": 39,
                "block_bootstrap_mean_length": 4.0,
                "block_bootstrap_seed": 20260826,
            },
        },
    }
    for name, payload in registries.items():
        (directory / name).write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _source(root: Path, session_date: date, session_index: int) -> Path:
    stamp = datetime.combine(session_date, time(9), tzinfo=UTC)
    run_id = RunId(f"sha-{stamp:%Y%m%dT%H%M%S}.000000Z-{session_index:08x}")
    instrument = "NSE:NSE_FNO:NIFTY:future:2026-02-26"
    request = DatasetRequest(
        consumer="SIG",
        purpose="source-bound research acceptance",
        trading_date=session_date,
        channels=(DataChannel.DEPTH20,),
        instrument_ids=(instrument,),
    )
    capture = DataCaptureSession.create(
        catalog=DataCatalog(root / "catalog.jsonl"),
        request=request,
        output_root=root / "raw",
        run_id=run_id,
        fsync_every=1,
        index_stride_rows=5,
    )
    for index in range(84):
        signed = ((index * 7 + session_index * 3) % 11) - 5
        midpoint = 25_000.0 + 0.2 * index + 0.04 * signed
        capture.write(
            TapeRow(
                run_id=str(run_id),
                receive_sequence=index + 1,
                connection_epoch=1,
                source="synthetic_canonical_fixture",
                event_type="depth20",
                instrument_id=instrument,
                broker_security_id="58072",
                exchange_segment="NSE_FNO",
                receive_ts=stamp + timedelta(seconds=index / 2),
                raw_message_size_bytes=100,
                update_side="both",
                bids=(DepthLevel(midpoint - 0.5, 100 + 4 * signed + index, 2),),
                asks=(DepthLevel(midpoint + 0.5, 100 - 3 * signed + index, 2),),
            )
        )
    handle = capture.close()
    path = root / f"handle-{session_date.isoformat()}.json"
    path.write_text(handle.model_dump_json(), encoding="utf-8")
    return path


def _run(
    arguments: list[str], *, cwd: Path, executable: Path
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [str(executable), *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_installed_cli_derives_mining_and_evaluation_from_canonical_tapes(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data_repository = repository.parent / "data"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    installed_environment = tmp_path / "installed"
    created = subprocess.run(
        ["uv", "venv", "--system-site-packages", str(installed_environment)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    installed = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installed_environment / "bin" / "python"),
            str(data_repository),
            str(repository),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    executable = installed_environment / "bin" / "shaurya-research"
    registries = tmp_path / "registries"
    _write_registries(registries)
    dates = tuple(date(2026, 2, 2) + timedelta(days=index) for index in range(10))
    plan_date = dates[4]
    first_evaluation = dates[5]
    first_next_session = dates[6]
    handles = tuple(
        _source(tmp_path / "sources", value, index + 1)
        for index, value in enumerate(dates)
    )
    plan_path = tmp_path / "plan.json"
    plan_run = _run(
        [
            "plan-alpha",
            "--through",
            plan_date.isoformat(),
            "--registry-dir",
            str(registries),
            "--feature-registry",
            "features_v1",
            "--target-registry",
            "targets_v1",
            "--hypothesis-registry",
            "hypotheses_v1",
            "--policy",
            "policy_v1",
            "--output",
            str(plan_path),
        ],
        cwd=tmp_path,
        executable=executable,
    )
    assert plan_run.returncode == 0, plan_run.stderr
    plan = alpha_plan_from_mapping(json.loads(plan_path.read_text(encoding="utf-8")))
    assert plan.total_effective_hypothesis_count == 5
    state_dir = tmp_path / "state"
    ledger_path = tmp_path / "ledger.jsonl"
    initialized = _run(
        [
            "init-alpha-state",
            "--plan",
            str(plan_path),
            "--as-of",
            plan_date.isoformat(),
            "--intended-for-session",
            first_evaluation.isoformat(),
            "--catalog",
            str(tmp_path / "sources" / "catalog.jsonl"),
            *(value for path in handles[:5] for value in ("--source-handle", str(path))),
            "--state-dir",
            str(state_dir),
            "--ledger",
            str(ledger_path),
            "--registry-dir",
            str(registries),
            "--feature-registry",
            "features_v1",
            "--target-registry",
            "targets_v1",
            "--hypothesis-registry",
            "hypotheses_v1",
            "--policy",
            "policy_v1",
        ],
        cwd=tmp_path,
        executable=executable,
    )
    assert initialized.returncode == 0, initialized.stderr
    state_path = Path(json.loads(initialized.stdout)["state_path"])
    common = [
        "--registry-dir",
        str(registries),
        "--feature-registry",
        "features_v1",
        "--target-registry",
        "targets_v1",
        "--hypothesis-registry",
        "hypotheses_v1",
        "--policy",
        "policy_v1",
        "--plan",
        str(plan_path),
        "--state",
        str(state_path),
        "--catalog",
        str(tmp_path / "sources" / "catalog.jsonl"),
    ]
    mine = _run(
        [
            "mine-alpha",
            "--through",
            plan_date.isoformat(),
            *common,
            *(value for path in handles[:5] for value in ("--source-handle", str(path))),
            "--ledger",
            str(ledger_path),
        ],
        cwd=tmp_path,
        executable=executable,
    )
    assert mine.returncode == 0, mine.stderr
    assert len(json.loads(mine.stdout)["observed_scores"]) == 5
    forbidden_seed = _run(
        [
            "mine-alpha",
            "--through",
            plan_date.isoformat(),
            *common,
            *(value for path in handles[:5] for value in ("--source-handle", str(path))),
            "--ledger",
            str(tmp_path / "forbidden-seed-ledger.jsonl"),
            "--seed",
            "7",
        ],
        cwd=tmp_path,
        executable=executable,
    )
    assert forbidden_seed.returncode == 2
    assert "unrecognized arguments: --seed" in forbidden_seed.stderr

    evaluate_arguments = [
        "evaluate-alpha",
        "--date",
        first_evaluation.isoformat(),
        "--next-session",
        first_next_session.isoformat(),
        *common,
        *(value for path in handles[:6] for value in ("--source-handle", str(path))),
        "--ledger",
        str(ledger_path),
        "--state-dir",
        str(state_dir),
        "--report-dir",
        str(tmp_path / "reports"),
        "--snapshot-dir",
        str(tmp_path / "snapshots"),
    ]
    evaluated = _run(evaluate_arguments, cwd=tmp_path, executable=executable)
    assert evaluated.returncode == 0, evaluated.stderr
    retry = _run(evaluate_arguments, cwd=tmp_path, executable=executable)
    assert retry.returncode == 0, retry.stderr
    assert retry.stdout == evaluated.stdout
    ledger = EvidenceLedger(ledger_path)
    assert len(ledger.events(event_type="hypothesis_evidence")) == 5
    assert len(ledger.events(event_type="predictive_surface")) == 2
    assert len(ledger.events(event_type="daily_scientific_artifacts")) == 1
    result = json.loads(evaluated.stdout)
    parquet = Path(result["snapshot_path"])
    assert parquet.read_bytes()[:4] == b"PAR1" == parquet.read_bytes()[-4:]
    manifest = json.loads(
        parquet.with_suffix(parquet.suffix + ".manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["format"] == "parquet"
    assert manifest["rows"] == len(ledger.read()) - 1
    next_state = StateStore(state_dir).load_as_of(first_evaluation)
    assert next_state is not None
    assert next_state.intended_for_session == first_next_session
    assert next_state.source_ledger_hash == ledger.read()[-1].event_hash
    assert next_state.source_prefix_manifest
    assert next_state.derivation_prefixes
    assert next_state.shrinkage_state
    assert next_state.regime_models
    assert next_state.model_weights
    assert next_state.historical_effects
    assert next_state.diagnostic_hashes
    assert len(next_state.block_bootstrap_hashes) == 5
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["scientific_diagnostics"]["stability_summary"]
    assert report["scientific_diagnostics"]["negative_control_warning"]["status"] == "evaluated"
    assert isinstance(
        report["scientific_diagnostics"]["negative_control_warning"]["warning"], bool
    )
    negative_ids = tuple(
        report["scientific_diagnostics"]["negative_control_warning"]["candidate_ids"]
    )
    assert len(negative_ids) == 1
    negative_evidence = next(
        item for item in report["evaluations"] if item["hypothesis_id"] in negative_ids
    )
    negative_metrics = dict(negative_evidence["metrics"])
    negative_uncertainty = dict(negative_evidence["uncertainty"])
    assert negative_metrics["score_gate_pass"] is False
    assert negative_metrics["economic_gate_pass"] is False
    assert negative_uncertainty["block_bootstrap_hash"]
    assert report["lifecycle_after"]
    assert {item["mode"] for item in report["evaluations"]} == {
        "confirmatory_walk_forward"
    }
    assert len(ledger.events(event_type="daily_stability_diagnostics")) == 1

    for boundary in (
        "after_evaluation",
        "after_exploration",
        "after_analysis",
        "after_report",
        "after_completion",
        "after_snapshot",
        "after_state",
    ):
        boundary_root = tmp_path / boundary
        boundary_state_dir = boundary_root / "state"
        boundary_ledger_path = boundary_root / "ledger.jsonl"
        boundary_initialized = _run(
            [
                "init-alpha-state",
                "--plan",
                str(plan_path),
                "--as-of",
                plan_date.isoformat(),
                "--intended-for-session",
                first_evaluation.isoformat(),
                "--catalog",
                str(tmp_path / "sources" / "catalog.jsonl"),
                *(value for path in handles[:5] for value in ("--source-handle", str(path))),
                "--state-dir",
                str(boundary_state_dir),
                "--ledger",
                str(boundary_ledger_path),
                "--registry-dir",
                str(registries),
                "--feature-registry",
                "features_v1",
                "--target-registry",
                "targets_v1",
                "--hypothesis-registry",
                "hypotheses_v1",
                "--policy",
                "policy_v1",
            ],
            cwd=tmp_path,
            executable=executable,
        )
        assert boundary_initialized.returncode == 0, boundary_initialized.stderr
        boundary_state = Path(json.loads(boundary_initialized.stdout)["state_path"])
        boundary_arguments = [
            "evaluate-alpha",
            "--date",
            first_evaluation.isoformat(),
            "--next-session",
            first_next_session.isoformat(),
            *common[: common.index("--state")],
            "--state",
            str(boundary_state),
            "--catalog",
            str(tmp_path / "sources" / "catalog.jsonl"),
            *(value for path in handles[:6] for value in ("--source-handle", str(path))),
            "--ledger",
            str(boundary_ledger_path),
            "--state-dir",
            str(boundary_state_dir),
            "--report-dir",
            str(boundary_root / "reports"),
            "--snapshot-dir",
            str(boundary_root / "snapshots"),
        ]
        crashed = _run(
            [*boundary_arguments, "--crash-after", boundary],
            cwd=tmp_path,
            executable=executable,
        )
        assert crashed.returncode != 0 and f"at {boundary}" in crashed.stderr
        recovered = _run(boundary_arguments, cwd=tmp_path, executable=executable)
        assert recovered.returncode == 0, recovered.stderr
        boundary_ledger = EvidenceLedger(boundary_ledger_path)
        assert len(boundary_ledger.events(event_type="hypothesis_evidence")) == 5
        assert len(boundary_ledger.events(event_type="daily_scientific_artifacts")) == 1
        assert len(boundary_ledger.events(event_type="daily_snapshot_published")) == 1
        recovered_state = StateStore(boundary_state_dir).load_as_of(first_evaluation)
        assert recovered_state is not None
        assert recovered_state.source_ledger_hash == boundary_ledger.read()[-1].event_hash

    manifest_path = parquet.with_suffix(parquet.suffix + ".manifest.json")
    tampered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered_manifest["rows"] += 1
    manifest_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")
    rejected_retry = _run(evaluate_arguments, cwd=tmp_path, executable=executable)
    assert rejected_retry.returncode != 0
    assert "snapshot" in rejected_retry.stderr

    current_state_path = Path(result["state_path"])
    final_result = result
    for index in range(6, len(dates)):
        next_session = (
            dates[index + 1]
            if index + 1 < len(dates)
            else dates[index] + timedelta(days=3)
        )
        continued = _run(
            [
                "evaluate-alpha",
                "--date",
                dates[index].isoformat(),
                "--next-session",
                next_session.isoformat(),
                "--registry-dir",
                str(registries),
                "--feature-registry",
                "features_v1",
                "--target-registry",
                "targets_v1",
                "--hypothesis-registry",
                "hypotheses_v1",
                "--policy",
                "policy_v1",
                "--plan",
                str(plan_path),
                "--state",
                str(current_state_path),
                "--catalog",
                str(tmp_path / "sources" / "catalog.jsonl"),
                *(
                    value
                    for path in handles[: index + 1]
                    for value in ("--source-handle", str(path))
                ),
                "--ledger",
                str(ledger_path),
                "--state-dir",
                str(state_dir),
                "--report-dir",
                str(tmp_path / "reports"),
                "--snapshot-dir",
                str(tmp_path / "snapshots"),
            ],
            cwd=tmp_path,
            executable=executable,
        )
        assert continued.returncode == 0, continued.stderr
        final_result = json.loads(continued.stdout)
        current_state_path = Path(final_result["state_path"])
    final_state = StateStore(state_dir).load_as_of(dates[-1])
    assert final_state is not None
    assert len(final_state.derivation_prefixes) == 6  # bootstrap prefix plus five OOS sessions
    assert any(status == "STABLE" for _, status in final_state.lifecycle)
    final_report = json.loads(
        Path(final_result["report_path"]).read_text(encoding="utf-8")
    )
    assert any(
        item["status"] == "STABLE"
        for item in final_report["lifecycle_after"].values()
    )
    assert all(
        final_report["lifecycle_after"][identity]["status"] != "STABLE"
        for identity in negative_ids
    )
