from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data import (
    DataCaptureSession,
    DataCatalog,
    DatasetUnavailableError,
    TapeIntegrityError,
)

from shaurya.cli.research import main as research_main
from shaurya.research.contracts import (
    ExperimentStatus,
    HypothesisDefinition,
    HypothesisStatus,
    ResearchMode,
    canonical_sha256,
)
from shaurya.research.evidence import EvidenceRecord, SelectionProvenance, assess_lifecycle
from shaurya.research.executor import freeze_daily_universe
from shaurya.research.ledger import EvidenceLedger
from shaurya.research.nulls import MinerRefitResult, complete_miner_empirical_null
from shaurya.research.planner import AlphaPlan, plan_from_directory
from shaurya.research.source import verify_completed_source
from shaurya.research.state import ResearchState, StateStore
from shaurya.research.surfaces import (
    SurfaceCell,
    build_complete_surface,
    parameter_movement,
    surface_robustness,
)
from shaurya.research.walkforward import (
    CandidateFoldResult,
    FrozenWalkForwardFold,
    NestedWalkForwardResult,
    freeze_historical_folds,
)


def _hypothesis(
    *, version: str = "v1", registered: date = date(2025, 1, 1)
) -> HypothesisDefinition:
    return HypothesisDefinition(
        display_name="alias",
        family="OFI",
        predictor_feature_ids=("x",),
        target_id="future_mid_return.horizon=1s",
        target_horizon_seconds=1,
        conditioning_variables=(),
        admissible_regime="global",
        model_class="ridge",
        fitting_window_sessions=20,
        training_cadence_seconds=1,
        regularization=(("ridge_penalty", 1.0),),
        evaluation_metric="pearson_correlation",
        transaction_cost_relevance="diagnostic_only",
        first_registration_date=registered,
        registry_version=version,
    )


def _record(session: date, *, mode: ResearchMode = ResearchMode.CONFIRMATORY) -> EvidenceRecord:
    start = datetime.combine(session, datetime.min.time(), tzinfo=UTC)
    selection = SelectionProvenance(
        candidate_ids=("alpha-a",),
        selection_metric="correlation",
        selection_information_ts=(start - timedelta(microseconds=1)).isoformat(),
        evaluation_period_start=start.isoformat(),
        selected_rank=1,
        candidate_scores=(("alpha-a", 0.2),),
        score_difference_from_next=None,
        neighboring_results=(),
        multiplicity_method="benjamini_yekutieli",
        mode=mode,
    )
    return EvidenceRecord(
        hypothesis_id="alpha-a",
        evaluation_date=session,
        mode=mode,
        training_interval=("2025-01-01", "2025-06-01"),
        validation_interval=("2025-06-02", "2025-06-03"),
        test_interval=(start.isoformat(), (start + timedelta(days=1)).isoformat()),
        observation_count=200,
        effective_sample_size=100,
        model_class="ridge",
        hyperparameters=(("ridge_penalty", 1.0),),
        feature_registry_version="features-v1",
        target_registry_version="targets-v1",
        policy_registry_version="policy-v1",
        feature_run_hashes=("a" * 64,),
        metrics=(
            ("score", 0.2),
            ("coefficient", 0.2),
            ("neighbor_robustness", 0.8),
            ("score_gate_pass", True),
            ("economic_gate_pass", True),
            ("block_bootstrap_gate_pass", True),
        ),
        uncertainty=(("adjusted_p_value", 0.01), ("empirical_null_p_value", 0.01)),
        selection=selection,
        competing_hypotheses=1,
        terminal_status=ExperimentStatus.COMPLETED,
        plan_hash="b" * 64,
        pre_session_state_hash="c" * 64,
        source_identity_hash="d" * 64,
        fold_hashes=(f"{session.toordinal():064x}",),
        selected_for_outer=True,
    )


def _completed_source(tmp_path: Path):
    run_id = RunId("sha-20260821T030000.000000Z-abcd1234")
    instrument = "NSE:NSE_FNO:NIFTY:future:2026-08-25"
    request = DatasetRequest(
        consumer="SIG",
        purpose="post-market research test",
        trading_date=date(2026, 8, 21),
        channels=(DataChannel.DEPTH20,),
        instrument_ids=(instrument,),
        allow_active=False,
    )
    session = DataCaptureSession.create(
        catalog=DataCatalog(tmp_path / "catalog.jsonl"),
        request=request,
        output_root=tmp_path / "raw",
        run_id=run_id,
        fsync_every=1,
        index_stride_rows=1,
    )
    for index in range(2):
        session.write(
            TapeRow(
                run_id=str(run_id),
                receive_sequence=index + 1,
                connection_epoch=1,
                source="dhan",
                event_type="depth20",
                instrument_id=instrument,
                broker_security_id="58072",
                exchange_segment="NSE_FNO",
                receive_ts=datetime(2026, 8, 21, 3, 0, index, tzinfo=UTC),
                raw_message_size_bytes=100,
                update_side="both",
                bids=(DepthLevel(25_000.0, 100, 2),),
                asks=(DepthLevel(25_001.0, 100, 2),),
            )
        )
    return session.close()


def _plan(identity: str, *, through: date = date(2026, 1, 1)) -> AlphaPlan:
    payload = {
        "through": through.isoformat(),
        "registries": (("r", "e" * 64),),
        "raw_ids": (identity,),
        "eligible_ids": (identity,),
        "exclusions": (),
    }
    return AlphaPlan(
        through=through,
        feature_registry_version="f",
        target_registry_version="t",
        hypothesis_registry_version="h",
        policy_registry_version="p",
        predictor_specifications=1,
        target_specifications=1,
        horizons=1,
        regime_conditions=1,
        models=1,
        interactions=0,
        sampling_clocks=1,
        pooling_coordinates=1,
        fitting_windows=1,
        training_cadences=1,
        selection_methods=1,
        total_raw_hypothesis_count=1,
        total_effective_hypothesis_count=1,
        effective_family_count=1,
        excluded_before_target_inspection=(),
        estimated_model_fits_per_outer_fold=1,
        registry_fingerprints=(("r", "e" * 64),),
        eligible_hypothesis_ids=(identity,),
        plan_hash=canonical_sha256(payload),
    )


def test_cross_registry_alias_is_the_same_semantic_atom() -> None:
    first = _hypothesis(version="registry-v1")
    second = replace(first, display_name="renamed", registry_version="registry-v2")
    assert first.hypothesis_id == second.hypothesis_id


def test_selection_mode_and_oos_timing_mismatches_fail_closed() -> None:
    record = _record(date(2026, 1, 2))
    with pytest.raises(ValueError, match="modes must match"):
        replace(record, mode=ResearchMode.LIVE_SHADOW)
    with pytest.raises(ValueError, match="precede"):
        replace(
            record.selection,
            selection_information_ts=record.selection.evaluation_period_start,
        )


def test_registered_cutoff_and_forged_fold_are_rejected() -> None:
    folds = freeze_historical_folds(
        [date(2026, 1, index) for index in range(1, 9)],
        through=date(2026, 1, 8),
    )
    with pytest.raises(ValueError, match="fold hash"):
        replace(folds[0], inner_training_dates=(date(2025, 1, 1),))
    assert (
        _hypothesis(registered=date(2026, 1, 8)).first_registration_date
        >= folds[-1].outer_evaluation_dates[0]
    )
    with pytest.raises(ValueError, match="empty effective hypothesis universe"):
        plan_from_directory(
            Path("registries"),
            through=date(2026, 8, 25),
            feature_version="microstructure_features_v2",
            target_version="microstructure_targets_v2",
        )


def test_source_requires_completed_hash_and_index_bound_full_replay(tmp_path: Path) -> None:
    handle = _completed_source(tmp_path)
    catalog = DataCatalog(tmp_path / "catalog.jsonl")
    verified = verify_completed_source(
        handle, through=date(2026, 8, 21), catalog=catalog
    )
    assert verified.rows == 2 and len(verified.source_identity_hash) == 64
    with pytest.raises(DatasetUnavailableError, match="unknown DAT dataset"):
        verify_completed_source(
            handle.model_copy(update={"dataset_id": "relabelled"}), catalog=catalog
        )
    with pytest.raises(ValueError, match="catalog authority"):
        verify_completed_source(
            handle.model_copy(update={"instrument_ids": ("NSE:FORGED",)}),
            catalog=catalog,
        )
    with pytest.raises(ValueError, match="completed"):
        verify_completed_source(
            handle.model_copy(update={"status": "active", "completed_at": None, "producer_pid": 1}),
            catalog=catalog,
        )
    segment_path = Path(handle.segments[0].path)
    with segment_path.open("ab") as segment:
        segment.write(b"tamper")
    with pytest.raises(TapeIntegrityError, match="hash or byte count"):
        verify_completed_source(handle, catalog=catalog)


def test_walkforward_rejects_duplicate_outer_dates_across_distinct_folds() -> None:
    folds = freeze_historical_folds(
        [date(2026, 1, index) for index in range(1, 9)],
        through=date(2026, 1, 8),
    )
    first = folds[0]
    duplicate = FrozenWalkForwardFold(
        "duplicate-outer",
        first.inner_training_dates,
        first.inner_validation_dates,
        first.outer_evaluation_dates,
        first.selection_information_ts,
        first.evaluation_period_start,
        first.fold_hash,
        first.purge_seconds,
        first.embargo_seconds,
    )
    with pytest.raises(ValueError, match="outer evaluation dates"):
        NestedWalkForwardResult(
            ResearchMode.CONFIRMATORY,
            (first, duplicate),
            tuple(
                CandidateFoldResult(
                    "alpha-a",
                    fold.fold_id,
                    0.1,
                    0.1,
                    0.1,
                    10,
                    True,
                    "a" * 64,
                    "b" * 64,
                )
                for fold in (first, duplicate)
            ),
            ("alpha-a",),
            "0" * 64,
        )


def test_null_requires_target_bound_refits_for_every_replicate() -> None:
    rows = tuple({"x": float(index)} for index in range(40))
    targets = tuple(float(index % 7) for index in range(40))

    class FraudulentProcedure:
        def refit_select_score(self, feature_rows, values, *, replicate_id):
            return MinerRefitResult(
                (("alpha-a", 0.1),),
                canonical_sha256(feature_rows),
                canonical_sha256(targets),
                "a" * 64,
                "b" * 64,
                (("alpha-a", "c" * 64),),
            )

    with pytest.raises(ValueError, match="did not refit"):
        complete_miner_empirical_null(
            rows,
            targets,
            procedure=FraudulentProcedure(),
            replicates=2,
            seed=1,
            block_size=10,
        )


def test_ledger_batch_is_prevalidated_atomic_and_retry_idempotent(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(TypeError):
        ledger.append_many((("ok", {"event_id": "one"}), ("bad", {"value": object()})))
    assert not ledger.path.exists()
    first = ledger.append_many((("ok", {"event_id": "one", "value": 1}),))
    retry = ledger.append_many((("ok", {"event_id": "one", "value": 1}),))
    assert first == retry
    assert len(ledger.read()) == 1


def test_lifecycle_uses_all_policy_gates_and_unique_oos_sessions() -> None:
    policy = {
        "minimum_evidence": {
            "observations": 100,
            "effective_sample_size": 50,
            "sessions_for_provisional": 5,
            "sessions_for_stable": 20,
            "outer_folds_for_stable": 5,
        },
        "promotion": {
            "minimum_sign_consistency": 0.7,
            "minimum_neighbor_robustness": 0.5,
            "minimum_adjusted_evidence": 0.95,
        },
    }
    one = assess_lifecycle(
        "alpha-a", [_record(date(2026, 1, 2))], as_of=date(2026, 1, 2), policy=policy
    )
    assert one.status is HypothesisStatus.EXPLORATORY
    history = [_record(date(2026, 1, 2) + timedelta(days=index)) for index in range(20)]
    stable = assess_lifecycle("alpha-a", history, as_of=date(2026, 1, 21), policy=policy)
    assert stable.status is HypothesisStatus.STABLE
    failed_economic = replace(
        history[-1],
        metrics=tuple(
            (name, False if name == "economic_gate_pass" else value)
            for name, value in history[-1].metrics
        ),
    )
    rejected = assess_lifecycle(
        "alpha-a", [*history[:-1], failed_economic], as_of=date(2026, 1, 21), policy=policy
    )
    assert rejected.status is HypothesisStatus.REJECTED


def test_surface_region_is_connected_and_axis_movement_is_validated() -> None:
    cells = [
        SurfaceCell((("w", w),), str(w), score, 1, 100)
        for w, score in ((1, 1.0), (2, 0.2), (3, 0.95))
    ]
    surface = build_complete_surface(
        mechanism="ofi", axes=("w",), axis_values={"w": (1, 2, 3)}, cells=cells
    )
    diagnostic = surface_robustness(surface, tolerance=0.1)
    assert diagnostic.region_average_score is not None
    assert diagnostic.indistinguishable_hypothesis_ids == ("1",)
    other = build_complete_surface(
        mechanism="ofi",
        axes=("h",),
        axis_values={"h": (1,)},
        cells=(SurfaceCell((("h", 1),), "1", 1.0, 1, 10),),
    )
    with pytest.raises(ValueError, match="axes"):
        parameter_movement(diagnostic, surface_robustness(other))


def test_daily_universe_comes_from_pre_session_plan_and_state(tmp_path: Path) -> None:
    plan = _plan("alpha-a")
    state = ResearchState(
        as_of_date=date(2026, 1, 1),
        intended_for_session=date(2026, 1, 2),
        active_hypotheses=("alpha-a",),
        lifecycle=(),
        evidence_grades=(),
        coefficient_estimates=(),
        shrinkage_state=(),
        regime_models=(),
        performance_history_hash="a" * 64,
        dormant_hypotheses=(),
        parameter_surface_hashes=(),
        model_weights=(),
        source_ledger_hash="b" * 64,
        plan_hash=plan.plan_hash,
        planned_hypothesis_ids=("alpha-a",),
    ).with_hash()
    path = StateStore(tmp_path).write(state)
    loaded = StateStore(tmp_path).load_exact(path)
    universe = freeze_daily_universe(
        plan=plan, evaluation_date=date(2026, 1, 2), pre_session_state=loaded
    )
    assert universe.hypothesis_ids == ("alpha-a",)
    with pytest.raises(ValueError, match="universe"):
        freeze_daily_universe(
            plan=plan,
            evaluation_date=date(2026, 1, 2),
            pre_session_state=replace(
                state, planned_hypothesis_ids=("alpha-b",), state_hash=""
            ).with_hash(),
        )


def test_cli_rejects_caller_authored_evidence_and_array_inputs(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        research_main(
            [
                "evaluate-alpha",
                "--date",
                "2026-08-22",
                "--next-session",
                "2026-08-25",
                "--evidence",
                str(tmp_path / "forged.json"),
            ]
        )
    with pytest.raises(SystemExit):
        research_main(
            [
                "mine-alpha",
                "--through",
                "2026-08-22",
                "--input",
                str(tmp_path / "caller-arrays.json"),
            ]
        )
