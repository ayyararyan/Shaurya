"""Ordered post-market workflow bound to a pre-session plan and immutable state."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from shaurya.research.artifacts import (
    CandidateGateArtifact,
    build_candidate_gate_artifacts,
    candidate_gate_from_mapping,
)
from shaurya.research.contracts import (
    ExperimentStatus,
    HypothesisDefinition,
    HypothesisStatus,
    ResearchMode,
    canonical_sha256,
)
from shaurya.research.evidence import (
    EvidenceAuthority,
    EvidenceRecord,
    LifecycleAssessment,
    assess_lifecycle,
    evidence_authority_from_mapping,
    evidence_record_from_mapping,
    winners_curse,
)
from shaurya.research.ledger import (
    EvidenceLedger,
    LedgerEnvelope,
    _sha256_path,
    materialize_snapshot,
    verify_snapshot,
)
from shaurya.research.mechanisms import MechanismSummary, summarize_mechanism
from shaurya.research.models import family_shrinkage, past_only_ensemble_weights
from shaurya.research.multiplicity import (
    CandidateBootstrapArtifact,
    adjust_hierarchical,
    build_candidate_bootstrap_artifacts,
    candidate_bootstrap_from_mapping,
)
from shaurya.research.nulls import (
    NestedEmpiricalNullResult,
    negative_control_warning,
    nested_walkforward_empirical_null,
)
from shaurya.research.planner import AlphaPlan
from shaurya.research.reports import daily_report, write_daily_report
from shaurya.research.source import DerivedResearchDataset, derivation_hash_for_sources
from shaurya.research.stability import regime_comparison, stability_summary
from shaurya.research.state import ResearchState, StateStore
from shaurya.research.surfaces import (
    PredictiveSurface,
    SurfaceRobustness,
    candidate_neighbors,
    parameter_movement,
    partitioned_hypothesis_surfaces,
    validate_surface_artifacts,
)
from shaurya.research.walkforward import NestedWalkForwardResult

_R = TypeVar("_R")


def _robustness_from_mapping(raw: Mapping[str, Any]) -> SurfaceRobustness:
    coordinates = raw.get("best_coordinates")
    return SurfaceRobustness(
        None if raw.get("best_hypothesis_id") is None else str(raw["best_hypothesis_id"]),
        None
        if coordinates is None
        else tuple((str(item[0]), item[1]) for item in coordinates),
        int(raw["neighbor_count"]),
        None
        if raw.get("neighbor_sign_agreement") is None
        else float(raw["neighbor_sign_agreement"]),
        None
        if raw.get("local_rank_stability") is None
        else float(raw["local_rank_stability"]),
        int(raw["predictive_region_width"]),
        bool(raw["isolated_spike"]),
        float(raw["robustness_score"]),
        tuple(str(value) for value in raw["indistinguishable_hypothesis_ids"]),
        tuple(str(value) for value in raw.get("axes", ())),
        None
        if raw.get("region_average_score") is None
        else float(raw["region_average_score"]),
        str(raw["robustness_hash"]),
    )


def _workflow_locked(function: Callable[..., _R]) -> Callable[..., _R]:
    """Serialize the entire read/validate/publish transaction for one ledger."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> _R:
        ledger = kwargs.get("ledger")
        if not isinstance(ledger, EvidenceLedger):
            raise TypeError("execute_daily requires an explicit EvidenceLedger")
        lock_path = ledger.path.with_suffix(ledger.path.suffix + ".workflow.lock")
        lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            return function(*args, **kwargs)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    return wrapped


@dataclass(frozen=True, slots=True)
class FrozenDailyUniverse:
    evaluation_date: date
    plan_hash: str
    pre_session_state_hash: str
    hypothesis_ids: tuple[str, ...]
    pre_session_ledger_hash: str
    universe_hash: str = ""

    def with_hash(self) -> FrozenDailyUniverse:
        payload = asdict(self)
        payload["universe_hash"] = ""
        return FrozenDailyUniverse(**{**payload, "universe_hash": canonical_sha256(payload)})


def freeze_daily_universe(
    *, plan: AlphaPlan, evaluation_date: date, pre_session_state: ResearchState | None
) -> FrozenDailyUniverse:
    if plan.through >= evaluation_date:
        raise ValueError("daily universe plan must be frozen before the evaluation session")
    candidates = plan.eligible_hypothesis_ids
    state_hash = "0" * 64
    if pre_session_state is not None:
        if pre_session_state.with_hash().state_hash != pre_session_state.state_hash:
            raise ValueError("pre-session state hash is invalid")
        if pre_session_state.intended_for_session != evaluation_date:
            raise ValueError("state was not frozen for this evaluation session")
        if pre_session_state.plan_hash and pre_session_state.plan_hash != plan.plan_hash:
            raise ValueError("pre-session state and plan disagree")
        if pre_session_state.planned_hypothesis_ids:
            if pre_session_state.planned_hypothesis_ids != candidates:
                raise ValueError("pre-session state universe and plan disagree")
            candidates = pre_session_state.planned_hypothesis_ids
        state_hash = pre_session_state.state_hash
    if (
        not candidates
        or candidates != tuple(sorted(candidates))
        or len(candidates) != len(set(candidates))
    ):
        raise ValueError("pre-session universe must be complete, sorted, and unique")
    ledger_hash = "0" * 64 if pre_session_state is None else pre_session_state.source_ledger_hash
    if len(ledger_hash) != 64:
        raise ValueError("pre-session state ledger tail is invalid")
    return FrozenDailyUniverse(
        evaluation_date, plan.plan_hash, state_hash, candidates, ledger_hash
    ).with_hash()


@dataclass(frozen=True, slots=True)
class DailyExecutionResult:
    evaluation_date: date
    evaluated_count: int
    exploratory_count: int
    state_path: Path
    report_path: Path
    snapshot_path: Path
    state_hash: str


def _validate_scientific_artifact(
    event: Mapping[str, Any], *, plan: AlphaPlan, policy_fingerprint: str
) -> tuple[EvidenceAuthority, dict[str, CandidateGateArtifact]]:
    raw_authority = event.get("authority")
    if not isinstance(raw_authority, Mapping):
        raise ValueError("ledger scientific artifact lacks an evidence authority")
    authority = evidence_authority_from_mapping(raw_authority)
    if authority.with_hash() != authority:
        raise ValueError("ledger scientific artifact authority is invalid")
    if (
        authority.plan_hash != plan.plan_hash
        or authority.registry_fingerprints != plan.registry_fingerprints
        or authority.policy_fingerprint != policy_fingerprint
    ):
        raise ValueError("historical scientific artifact differs from the exact plan/policy")
    source = event.get("source_derivation")
    walkforward = event.get("walkforward")
    empirical_null = event.get("empirical_null")
    multiplicity = event.get("multiplicity")
    surfaces = event.get("surfaces")
    mechanisms = event.get("mechanisms")
    raw_gates = event.get("candidate_gates")
    raw_bootstrap = event.get("block_bootstrap")
    if not all(
        isinstance(value, Mapping)
        for value in (source, walkforward, empirical_null, multiplicity, surfaces)
    ) or not all(
        isinstance(value, list) for value in (mechanisms, raw_gates, raw_bootstrap)
    ):
        raise ValueError("ledger scientific artifact bundle is incomplete")
    assert isinstance(mechanisms, list)
    assert isinstance(raw_gates, list)
    assert isinstance(raw_bootstrap, list)
    assert isinstance(source, Mapping)
    sources = source.get("sources")
    features = source.get("features")
    targets = source.get("targets")
    rows = source.get("rows")
    if not all(isinstance(value, list) for value in (sources, features, targets, rows)):
        raise ValueError("ledger source derivation is incomplete")
    assert isinstance(sources, list)
    assert isinstance(features, list)
    assert isinstance(targets, list)
    assert isinstance(rows, list)
    source_manifest_hash = canonical_sha256(sources)
    derivation_hash = canonical_sha256(
        {
            "source_manifest_hash": source_manifest_hash,
            "feature_registry": (
                source["feature_registry_version"],
                source["feature_registry_fingerprint"],
            ),
            "target_registry": (
                source["target_registry_version"],
                source["target_registry_fingerprint"],
            ),
            "feature_run_hash": canonical_sha256(
                [item["feature_run_hash"] for item in features]
            ),
            "target_hashes": [item["target_run_hash"] for item in targets],
            "join_count": len(rows),
        }
    )
    if (
        source.get("source_manifest_hash") != source_manifest_hash
        or source.get("derivation_hash") != derivation_hash
        or derivation_hash != authority.source_derivation_hash
    ):
        raise ValueError("ledger source derivation hash is invalid")
    assert isinstance(walkforward, Mapping)
    walkforward_hash = canonical_sha256(
        {
            "mode": walkforward["mode"],
            "folds": walkforward["folds"],
            "candidate_ids": walkforward["candidate_ids"],
            "results": walkforward["candidate_results"],
        }
    )
    if (
        walkforward.get("result_hash") != walkforward_hash
        or walkforward_hash != authority.walkforward_hash
    ):
        raise ValueError("ledger walk-forward artifact hash is invalid")
    assert isinstance(empirical_null, Mapping)
    null_payload = {
        "candidates": empirical_null["candidate_ids"],
        "observed_scores": empirical_null["observed_scores"],
        "adjusted": empirical_null["candidate_adjusted_p_values"],
        "null_best": empirical_null["null_best_discoveries"],
        "observed_walkforward_hash": empirical_null["observed_walkforward_hash"],
        "replicate_walkforward_hashes": empirical_null["replicate_walkforward_hashes"],
        "method": empirical_null["method"],
        "seed": empirical_null["seed"],
        "minimum_shift_blocks": empirical_null["minimum_shift_blocks"],
        "replicates": empirical_null["replicates"],
        "complete_miner_rerun": empirical_null["complete_miner_rerun"],
    }
    if (
        empirical_null.get("fingerprint") != canonical_sha256(null_payload)
        or empirical_null.get("fingerprint") != authority.empirical_null_hash
    ):
        raise ValueError("ledger empirical-null artifact hash is invalid")
    assert isinstance(multiplicity, Mapping)
    if canonical_sha256(dict(multiplicity)) != authority.multiplicity_hash:
        raise ValueError("ledger multiplicity artifact hash is invalid")
    assert isinstance(surfaces, Mapping)
    observed_surfaces: list[tuple[str, str]] = []
    observed_robustness: list[tuple[str, str]] = []
    for name, pair in surfaces.items():
        if not isinstance(name, str) or not isinstance(pair, Mapping):
            raise ValueError("ledger predictive surface is malformed")
        surface = pair.get("surface")
        robustness = pair.get("robustness")
        if not isinstance(surface, Mapping) or not isinstance(robustness, Mapping):
            raise ValueError("ledger predictive surface bundle is incomplete")
        surface_payload = {
            "mechanism": surface["mechanism"],
            "axes": surface["axes"],
            "expected": surface["expected_coordinates"],
            "cells": surface["cells"],
            "axis_adjacency": surface.get("axis_adjacency", ()),
        }
        if canonical_sha256(surface_payload) != surface.get("surface_hash"):
            raise ValueError("ledger predictive surface hash is invalid")
        robustness_payload = dict(robustness)
        robustness_payload["robustness_hash"] = ""
        expected_robustness = canonical_sha256(
            {
                "surface_hash": surface["surface_hash"],
                "tolerance": 0.15,
                "result": robustness_payload,
            }
        )
        if robustness.get("robustness_hash") != expected_robustness:
            raise ValueError("ledger surface robustness hash is invalid")
        observed_surfaces.append((name, str(surface["surface_hash"])))
        observed_robustness.append((name, str(robustness["robustness_hash"])))
    if tuple(sorted(observed_surfaces)) != authority.surface_hashes or tuple(
        sorted(observed_robustness)
    ) != authority.surface_robustness_hashes:
        raise ValueError("ledger surface authority differs from artifact content")
    mechanism_hashes = tuple(
        sorted(
            (str(item["mechanism"]), canonical_sha256(item))
            for item in mechanisms
            if isinstance(item, Mapping)
        )
    )
    if len(mechanism_hashes) != len(mechanisms) or mechanism_hashes != authority.mechanism_hashes:
        raise ValueError("ledger mechanism authority differs from artifact content")
    gates = {
        gate.hypothesis_id: gate
        for raw in raw_gates
        if isinstance(raw, Mapping)
        for gate in (candidate_gate_from_mapping(raw),)
    }
    if len(gates) != len(raw_gates) or tuple(
        (identity, gates[identity].gate_hash) for identity in sorted(gates)
    ) != authority.candidate_gate_hashes:
        raise ValueError("ledger candidate gate authority differs from artifact content")
    bootstraps = {
        item.hypothesis_id: item
        for raw in raw_bootstrap
        if isinstance(raw, Mapping)
        for item in (candidate_bootstrap_from_mapping(raw),)
    }
    if len(bootstraps) != len(raw_bootstrap) or tuple(
        (identity, bootstraps[identity].bootstrap_hash) for identity in sorted(bootstraps)
    ) != authority.block_bootstrap_hashes:
        raise ValueError("ledger block-bootstrap authority differs from artifact content")
    if any(
        gates[identity].block_bootstrap_hash != item.bootstrap_hash
        for identity, item in bootstraps.items()
    ):
        raise ValueError("candidate gates differ from their block-bootstrap artifacts")
    return authority, gates


def _ledger_history(
    ledger: EvidenceLedger, *, plan: AlphaPlan, policy_fingerprint: str
) -> tuple[list[EvidenceRecord], dict[str, list[date]]]:
    artifacts: dict[str, tuple[EvidenceAuthority, dict[str, CandidateGateArtifact]]] = {}
    history: list[EvidenceRecord] = []
    failures: dict[str, list[date]] = {}
    for envelope in ledger.read():
        if envelope.event_type == "daily_scientific_artifacts":
            authority, gates = _validate_scientific_artifact(
                envelope.event, plan=plan, policy_fingerprint=policy_fingerprint
            )
            if authority.authority_hash in artifacts:
                raise ValueError("ledger repeats a scientific artifact authority")
            artifacts[authority.authority_hash] = (authority, gates)
        elif envelope.event_type == "hypothesis_evidence":
            record = evidence_record_from_mapping(envelope.event)
            bound = artifacts.get(record.authority_hash)
            if bound is None:
                raise ValueError("ledger evidence lacks a preceding validated artifact authority")
            authority, gates = bound
            gate = gates.get(record.hypothesis_id)
            metrics = dict(record.metrics)
            uncertainty = dict(record.uncertainty)
            if (
                gate is None
                or record.plan_hash != authority.plan_hash
                or record.source_identity_hash != authority.source_derivation_hash
                or record.selection.candidate_ids != authority.candidate_ids
                or metrics.get("candidate_gate_hash") != gate.gate_hash
                or metrics.get("score") != gate.score
                or metrics.get("coefficient") != gate.coefficient
                or metrics.get("neighbor_robustness") != gate.local_robustness
                or metrics.get("economic_magnitude") != gate.economic_magnitude
                or metrics.get("score_gate_pass") is not gate.score_gate_pass
                or metrics.get("economic_gate_pass") is not gate.economic_gate_pass
                or metrics.get("regime_comparison_pass") is not gate.regime_comparison_pass
                or metrics.get("block_bootstrap_gate_pass")
                is not gate.block_bootstrap_gate_pass
                or uncertainty.get("adjusted_p_value") != gate.adjusted_p_value
                or uncertainty.get("empirical_null_p_value")
                != gate.empirical_null_p_value
                or uncertainty.get("block_bootstrap_hash") != gate.block_bootstrap_hash
                or uncertainty.get("block_bootstrap_estimate")
                != gate.block_bootstrap_estimate
                or uncertainty.get("block_bootstrap_lower") != gate.block_bootstrap_lower
                or uncertainty.get("block_bootstrap_upper") != gate.block_bootstrap_upper
                or uncertainty.get("block_bootstrap_standard_error")
                != gate.block_bootstrap_standard_error
                or record.observation_count != gate.observations
                or record.effective_sample_size != gate.effective_sample_size
                or record.fold_hashes != (gate.fold_hash,)
                or record.coefficient_estimates != gate.coefficients
                or record.selected_for_outer is not gate.selected_for_outer
                or record.terminal_status is not gate.terminal_status
                or record.terminal_reason != gate.terminal_reason
                or record.mode not in {ResearchMode.CONFIRMATORY, ResearchMode.LIVE_SHADOW}
            ):
                raise ValueError("ledger evidence differs from its validated scientific artifacts")
            history.append(record)
        elif envelope.event_type == "evaluation_candidate_failed":
            event = envelope.event
            identity = str(event.get("hypothesis_id", ""))
            try:
                failed_date = date.fromisoformat(str(event["through"]))
            except (KeyError, ValueError) as exc:
                raise ValueError("ledger failure record has an invalid evaluation date") from exc
            if (
                identity not in plan.eligible_hypothesis_ids
                or event.get("plan_hash") != plan.plan_hash
                or event.get("terminal_status") != ExperimentStatus.FAILED.value
                or event.get("mode")
                not in {ResearchMode.CONFIRMATORY.value, ResearchMode.LIVE_SHADOW.value}
                or not event.get("terminal_reason")
            ):
                raise ValueError("ledger failure record differs from the frozen experiment")
            failures.setdefault(identity, []).append(failed_date)
    return history, failures


def _tail_is_resumable(
    ledger_events: Sequence[LedgerEnvelope],
    *,
    pre_session_tail: str,
    universe_hash: str,
    authority_hash: str,
    plan_hash: str,
    state_hash: str,
    historical_derivation_hash: str,
) -> bool:
    envelopes = list(ledger_events)
    if not envelopes:
        return pre_session_tail == "0" * 64
    start = 0
    if pre_session_tail != "0" * 64:
        matches = [
            index for index, item in enumerate(envelopes) if item.event_hash == pre_session_tail
        ]
        if len(matches) != 1:
            return False
        start = matches[0] + 1
    for envelope in envelopes[start:]:
        event = envelope.event
        if event.get("universe_hash") == universe_hash:
            continue
        if event.get("authority_hash") == authority_hash:
            continue
        if envelope.event_type in {"mining_candidate", "mining_empirical_null"} and (
            event.get("plan_hash") == plan_hash
            and event.get("state_hash") == state_hash
            and event.get("source_derivation_hash") == historical_derivation_hash
            and event.get("mode") == ResearchMode.EXPLORATORY.value
        ):
            continue
        return False
    return True


def _inject_crash(requested: str | None, boundary: str) -> None:
    if requested == boundary:
        raise RuntimeError(f"injected daily publication crash at {boundary}")


def _validate_records(
    records: Sequence[EvidenceRecord],
    *,
    evaluation_date: date,
    universe: FrozenDailyUniverse,
    authority: EvidenceAuthority,
    gates: Mapping[str, CandidateGateArtifact],
    hypotheses: Mapping[str, HypothesisDefinition],
    expected_feature_hashes: Mapping[str, tuple[str, ...]],
    plan: AlphaPlan,
    walkforward: NestedWalkForwardResult,
    surfaces: Mapping[str, tuple[PredictiveSurface, SurfaceRobustness]],
    exploratory: bool,
) -> None:
    if any(record.evaluation_date != evaluation_date for record in records):
        raise ValueError("evidence records must match the workflow date")
    if exploratory and any(record.mode.value != "exploratory" for record in records):
        raise ValueError("exploration records must retain exploratory mode")
    if not exploratory and any(record.mode.value == "exploratory" for record in records):
        raise ValueError("daily evaluation records must be confirmatory or live-shadow")
    if not exploratory and any(record.mode is not walkforward.mode for record in records):
        raise ValueError("evidence mode differs from the bound walk-forward experiment")
    final_fold = walkforward.folds[-1]
    final_results = {
        item.hypothesis_id: item
        for item in walkforward.candidate_results
        if item.fold_id == final_fold.fold_id
    }
    candidate_scores = tuple(
        sorted(
            (identity, final_results[identity].validation_score)
            for identity in authority.candidate_ids
        )
    )
    ranked = sorted(
        candidate_scores,
        key=lambda item: (-(abs(item[1]) if item[1] is not None else -1.0), item[0]),
    )
    ranks = {identity: rank for rank, (identity, _) in enumerate(ranked, start=1)}
    differences: dict[str, float | None] = {}
    for index, (identity, score) in enumerate(ranked):
        next_score = ranked[index + 1][1] if index + 1 < len(ranked) else None
        differences[identity] = (
            None if score is None or next_score is None else abs(score) - abs(next_score)
        )
    surface_by_candidate: dict[str, PredictiveSurface] = {}
    for surface, _ in surfaces.values():
        for cell in surface.cells:
            if cell.hypothesis_id in surface_by_candidate:
                raise ValueError("candidate is duplicated across predictive surfaces")
            surface_by_candidate[cell.hypothesis_id] = surface
    for record in records:
        if record.plan_hash != universe.plan_hash:
            raise ValueError("evidence is not bound to the pre-session plan")
        if record.pre_session_state_hash != universe.pre_session_state_hash:
            raise ValueError("evidence is not bound to the pre-session state")
        if not record.source_identity_hash:
            raise ValueError("evidence requires a verified canonical source identity")
        if record.source_identity_hash != authority.source_derivation_hash:
            raise ValueError("evidence source is not the artifact-bound source derivation")
        if record.authority_hash != authority.authority_hash:
            raise ValueError("evidence is not bound to the scientific artifact authority")
        if record.selection.candidate_ids != authority.candidate_ids:
            raise ValueError("evidence candidate universe differs from the authority")
        gate = gates.get(record.hypothesis_id)
        hypothesis = hypotheses.get(record.hypothesis_id)
        if gate is None:
            raise ValueError("evidence has no artifact-derived candidate gate")
        if hypothesis is None:
            raise ValueError("evidence has no exact registered hypothesis")
        if (
            record.feature_run_hashes != expected_feature_hashes[record.hypothesis_id]
            or record.model_class != hypothesis.model_class
            or record.hyperparameters != hypothesis.regularization
            or record.feature_registry_version != plan.feature_registry_version
            or record.target_registry_version != plan.target_registry_version
            or record.policy_registry_version != plan.policy_registry_version
            or record.selection.selection_metric != hypothesis.evaluation_metric
        ):
            raise ValueError("evidence copied or changed registered source/model provenance")
        result = final_results[record.hypothesis_id]
        expected_rank = ranks[record.hypothesis_id] if result.selected_for_outer else None
        if (
            record.selection.candidate_scores != candidate_scores
            or record.selection.selected_rank != expected_rank
            or record.selection.score_difference_from_next != differences[record.hypothesis_id]
            or record.selection.neighboring_results
            != candidate_neighbors(surface_by_candidate[record.hypothesis_id], record.hypothesis_id)
        ):
            raise ValueError("selection provenance differs from the exact bound outer fold")
        metrics = dict(record.metrics)
        uncertainty = dict(record.uncertainty)
        expected_metrics = {
            "score": gate.score,
            "coefficient": gate.coefficient,
            "neighbor_robustness": gate.local_robustness,
            "economic_magnitude": gate.economic_magnitude,
            "score_gate_pass": gate.score_gate_pass,
            "economic_gate_pass": gate.economic_gate_pass,
            "regime_comparison_pass": gate.regime_comparison_pass,
            "block_bootstrap_gate_pass": gate.block_bootstrap_gate_pass,
            "model_hash": gate.model_hash,
            "candidate_gate_hash": gate.gate_hash,
        }
        if any(metrics.get(name) != value for name, value in expected_metrics.items()):
            raise ValueError("evidence metrics were not derived from candidate-local artifacts")
        if (
            uncertainty.get("adjusted_p_value") != gate.adjusted_p_value
            or uncertainty.get("empirical_null_p_value") != gate.empirical_null_p_value
            or uncertainty.get("block_bootstrap_estimate") != gate.block_bootstrap_estimate
            or uncertainty.get("block_bootstrap_lower") != gate.block_bootstrap_lower
            or uncertainty.get("block_bootstrap_upper") != gate.block_bootstrap_upper
            or uncertainty.get("block_bootstrap_standard_error")
            != gate.block_bootstrap_standard_error
            or uncertainty.get("block_bootstrap_hash") != gate.block_bootstrap_hash
            or record.observation_count != gate.observations
            or record.effective_sample_size != gate.effective_sample_size
            or record.terminal_status is not gate.terminal_status
            or record.terminal_reason != gate.terminal_reason
            or record.fold_hashes != (gate.fold_hash,)
            or record.coefficient_estimates != gate.coefficients
            or record.selected_for_outer is not gate.selected_for_outer
        ):
            raise ValueError("evidence gates differ from verified scientific artifacts")


@_workflow_locked
def execute_daily(
    *,
    evaluation_date: date,
    plan: AlphaPlan,
    pre_session_state: ResearchState,
    universe: FrozenDailyUniverse,
    evaluation_records: Sequence[EvidenceRecord],
    exploratory_records: Sequence[EvidenceRecord],
    ledger: EvidenceLedger,
    state_store: StateStore,
    report_directory: Path,
    snapshot_directory: Path,
    lifecycle_policy: Mapping[str, object],
    surfaces: Mapping[str, tuple[PredictiveSurface, SurfaceRobustness]],
    mechanisms: Sequence[MechanismSummary],
    multiplicity: Mapping[str, object],
    authority: EvidenceAuthority,
    source_derivation: DerivedResearchDataset,
    hypotheses: Sequence[HypothesisDefinition],
    walkforward: NestedWalkForwardResult,
    empirical_null: NestedEmpiricalNullResult,
    block_bootstrap: Sequence[CandidateBootstrapArtifact],
    policy_fingerprint: str,
    next_session_date: date,
    warnings: Sequence[str] = (),
    crash_after: str | None = None,
) -> DailyExecutionResult:
    """Evaluate the frozen universe before exploration, then publish tomorrow's state."""

    if universe.with_hash() != universe or universe.evaluation_date != evaluation_date:
        raise ValueError("daily universe binding is invalid")
    if plan.with_hash() != plan or plan.plan_hash != universe.plan_hash:
        raise ValueError("daily execution requires the exact frozen alpha plan")
    if pre_session_state.with_hash() != pre_session_state:
        raise ValueError("daily execution requires an exact immutable pre-session state")
    if (
        pre_session_state.as_of_date >= evaluation_date
        or pre_session_state.intended_for_session != evaluation_date
        or pre_session_state.state_hash != universe.pre_session_state_hash
        or pre_session_state.plan_hash != plan.plan_hash
        or pre_session_state.planned_hypothesis_ids != universe.hypothesis_ids
        or pre_session_state.source_ledger_hash != universe.pre_session_ledger_hash
        or pre_session_state.policy_fingerprint != policy_fingerprint
    ):
        raise ValueError("pre-session state bindings do not match this evaluation")
    if next_session_date <= evaluation_date:
        raise ValueError("next trading session must be explicitly after the evaluation date")
    if authority.with_hash() != authority:
        raise ValueError("scientific evidence authority is invalid")
    rebuilt_walkforward, rebuilt_null = nested_walkforward_empirical_null(
        source_derivation,
        tuple(hypotheses),
        tuple(walkforward.folds),
        policy=lifecycle_policy,
        mode=walkforward.mode,
    )
    if rebuilt_walkforward != walkforward or rebuilt_null != empirical_null:
        raise ValueError("walk-forward/null artifacts were not recomputed from source rows")
    if (
        authority.plan_hash != universe.plan_hash
        or authority.pre_session_state_hash != universe.pre_session_state_hash
        or authority.candidate_ids != universe.hypothesis_ids
        or authority.registry_fingerprints != plan.registry_fingerprints
        or authority.policy_fingerprint != policy_fingerprint
        or authority.source_derivation_hash != source_derivation.derivation_hash
        or authority.walkforward_hash != walkforward.result_hash
        or authority.empirical_null_hash != empirical_null.fingerprint
    ):
        raise ValueError("scientific authority differs from the frozen daily universe")
    plan_fingerprints = dict(plan.registry_fingerprints)
    if (
        plan_fingerprints.get(plan.feature_registry_version)
        != source_derivation.feature_registry_fingerprint
        or plan_fingerprints.get(plan.target_registry_version)
        != source_derivation.target_registry_fingerprint
        or plan_fingerprints.get(plan.policy_registry_version) != policy_fingerprint
    ):
        raise ValueError("source/policy artifacts differ from exact plan registry bindings")
    observed_source_manifest = tuple(
        (
            item.trading_date.isoformat(),
            item.dataset_id,
            item.source_identity_hash,
        )
        for item in source_derivation.sources
    )
    historical_count = len(pre_session_state.source_prefix_manifest)
    if observed_source_manifest[:historical_count] != pre_session_state.source_prefix_manifest:
        raise ValueError("canonical source history is not an exact immutable prefix")
    if pre_session_state.derivation_prefixes:
        previous_derivation = pre_session_state.derivation_prefixes[-1][1]
        rebuilt_previous = derivation_hash_for_sources(
            source_derivation, source_derivation.sources[:historical_count]
        )
        if rebuilt_previous != previous_derivation:
            raise ValueError("historical research rows were re-derived under different sources")
    hypothesis_by_id = {item.hypothesis_id: item for item in hypotheses}
    if tuple(sorted(hypothesis_by_id)) != universe.hypothesis_ids or any(
        item.registry_version != plan.hypothesis_registry_version for item in hypotheses
    ):
        raise ValueError("runtime hypotheses differ from the exact plan registry binding")
    initial = ledger.read()
    if not _tail_is_resumable(
        initial,
        pre_session_tail=universe.pre_session_ledger_hash,
        universe_hash=universe.universe_hash,
        authority_hash=authority.authority_hash,
        plan_hash=plan.plan_hash,
        state_hash=pre_session_state.state_hash,
        historical_derivation_hash=(
            pre_session_state.derivation_prefixes[-1][1]
            if pre_session_state.derivation_prefixes
            else ""
        ),
    ):
        raise ValueError("ledger tail differs from the exact pre-session state binding")
    if canonical_sha256(dict(multiplicity)) != authority.multiplicity_hash:
        raise ValueError("multiplicity artifact differs from the evidence authority")
    surface_hashes = tuple(
        sorted((name, value[0].surface_hash) for name, value in surfaces.items())
    )
    robustness_hashes = tuple(
        sorted((name, value[1].robustness_hash) for name, value in surfaces.items())
    )
    if surface_hashes != authority.surface_hashes or robustness_hashes != (
        authority.surface_robustness_hashes
    ):
        raise ValueError("surface artifacts differ from the evidence authority")
    if not surfaces or not mechanisms:
        raise ValueError("daily publication requires non-empty surfaces and mechanisms")
    for surface, robustness in surfaces.values():
        validate_surface_artifacts(surface, robustness)
    mechanism_names = tuple(sorted(item.mechanism for item in mechanisms))
    if mechanism_names != tuple(sorted(surfaces)) or len(mechanism_names) != len(
        set(mechanism_names)
    ):
        raise ValueError("mechanism and predictive-surface authorities disagree")
    if any(item.current_evidence is None or not item.parameter_region for item in mechanisms):
        raise ValueError("mechanism evidence cannot be empty or fabricated")
    mechanism_hashes = tuple(
        sorted((item.mechanism, canonical_sha256(asdict(item))) for item in mechanisms)
    )
    if mechanism_hashes != authority.mechanism_hashes:
        raise ValueError("mechanism summaries differ from the evidence authority")
    multiplicity_results = multiplicity.get("candidate_results")
    if not isinstance(multiplicity_results, (tuple, list)):
        raise ValueError("multiplicity artifact lacks per-candidate results")
    adjusted_p_values = {
        str(item[0]): float(item[3])
        for item in multiplicity_results
        if isinstance(item, (tuple, list)) and len(item) == 4
    }
    empirical_p_values = dict(empirical_null.candidate_adjusted_p_values)
    multiplicity_policy = lifecycle_policy.get("multiplicity")
    if not isinstance(multiplicity_policy, Mapping):
        raise ValueError("frozen multiplicity policy is malformed")
    rebuilt_adjusted = adjust_hierarchical(
        empirical_p_values,
        {item.hypothesis_id: item.family for item in hypotheses},
        method=str(multiplicity_policy["method"]),
        declared_candidate_ids=universe.hypothesis_ids,
    )
    rebuilt_multiplicity_results = tuple(
        (
            item.hypothesis_id,
            item.raw_p_value,
            item.family_adjusted_p_value,
            item.experiment_adjusted_p_value,
        )
        for item in rebuilt_adjusted
    )
    if tuple(tuple(item) for item in multiplicity_results) != rebuilt_multiplicity_results:
        raise ValueError("multiplicity results were not recomputed from the bound null evidence")
    final_fold_id = walkforward.folds[-1].fold_id
    final_results = {
        item.hypothesis_id: item
        for item in walkforward.candidate_results
        if item.fold_id == final_fold_id
    }
    rebuilt_surfaces = partitioned_hypothesis_surfaces(
        hypotheses,
        scores={
            identity: final_results[identity].outer_score
            for identity in universe.hypothesis_ids
        },
        support={
            identity: final_results[identity].outer_observations
            for identity in universe.hypothesis_ids
        },
    )
    if dict(surfaces) != rebuilt_surfaces:
        raise ValueError("predictive surface was not recomputed from the bound outer outcomes")
    rebuilt_mechanisms = tuple(
        summarize_mechanism(
            name,
            {
                cell.hypothesis_id: float(cell.score)
                for cell in surface.cells
                if cell.score is not None
            },
            {
                identity: values
                for identity, values in pre_session_state.historical_effects
                if identity in {cell.hypothesis_id for cell in surface.cells}
            },
            adjusted_p_values=adjusted_p_values,
        )
        for name, (surface, _) in sorted(surfaces.items())
    )
    if rebuilt_mechanisms != tuple(mechanisms):
        raise ValueError("mechanism summaries were not rebuilt from bound surfaces/history")
    robustness_policy = lifecycle_policy.get("robustness")
    if not isinstance(robustness_policy, Mapping):
        raise ValueError("frozen block-bootstrap policy is missing")
    rebuilt_bootstrap = build_candidate_bootstrap_artifacts(
        walkforward,
        replicates=int(robustness_policy["block_bootstrap_replicates"]),
        mean_block_length=float(robustness_policy["block_bootstrap_mean_length"]),
        seed=int(robustness_policy["block_bootstrap_seed"]),
    )
    if tuple(block_bootstrap) != rebuilt_bootstrap:
        raise ValueError("block-bootstrap evidence was not recomputed from bound OOS scores")
    bootstrap_by_id = {item.hypothesis_id: item for item in rebuilt_bootstrap}
    if tuple(
        (item.hypothesis_id, item.bootstrap_hash) for item in rebuilt_bootstrap
    ) != authority.block_bootstrap_hashes:
        raise ValueError("block-bootstrap artifacts differ from the evidence authority")
    gates_tuple = build_candidate_gate_artifacts(
        hypotheses=hypotheses,
        walkforward=walkforward,
        empirical_null=empirical_null,
        adjusted_p_values=adjusted_p_values,
        surfaces=surfaces,
        block_bootstrap=bootstrap_by_id,
        policy=lifecycle_policy,
    )
    gates = {item.hypothesis_id: item for item in gates_tuple}
    if tuple((item.hypothesis_id, item.gate_hash) for item in gates_tuple) != (
        authority.candidate_gate_hashes
    ):
        raise ValueError("candidate gate artifacts differ from the evidence authority")
    expected_feature_hashes = {
        identity: tuple(
            sorted(
                {
                    row.feature.feature_run_hash
                    for row in source_derivation.rows
                    if row.feature.session_date == evaluation_date
                    and row.target.target_id == hypothesis_by_id[identity].target_id
                }
            )
        )
        for identity in universe.hypothesis_ids
    }
    if any(not values for values in expected_feature_hashes.values()):
        raise ValueError("evaluation lacks source-derived outer-session feature evidence")
    _validate_records(
        evaluation_records,
        evaluation_date=evaluation_date,
        universe=universe,
        authority=authority,
        gates=gates,
        hypotheses=hypothesis_by_id,
        expected_feature_hashes=expected_feature_hashes,
        plan=plan,
        walkforward=walkforward,
        surfaces=surfaces,
        exploratory=False,
    )
    _validate_records(
        exploratory_records,
        evaluation_date=evaluation_date,
        universe=universe,
        authority=authority,
        gates=gates,
        hypotheses=hypothesis_by_id,
        expected_feature_hashes=expected_feature_hashes,
        plan=plan,
        walkforward=walkforward,
        surfaces=surfaces,
        exploratory=True,
    )
    expected = universe.hypothesis_ids
    observed = tuple(sorted(record.hypothesis_id for record in evaluation_records))
    if observed != expected or len(observed) != len(evaluation_records):
        ledger.append_many(
            (
                (
                    "daily_evaluation_started",
                    {
                        "evaluation_date": evaluation_date,
                        "universe_hash": universe.universe_hash,
                        "frozen_hypothesis_ids": expected,
                    },
                ),
                (
                    "daily_evaluation_failed",
                    {
                        "evaluation_date": evaluation_date,
                        "universe_hash": universe.universe_hash,
                        "expected": expected,
                        "observed": observed,
                        "reason": "partial_hypothesis_accounting",
                    },
                ),
            )
        )
        raise ValueError("daily evaluation must account for every frozen hypothesis exactly once")
    hypotheses_considered = multiplicity.get("hypotheses_considered")
    if not isinstance(hypotheses_considered, int) or hypotheses_considered != len(expected):
        raise ValueError("daily multiplicity artifact must account for the frozen universe")
    for _, (surface, _) in surfaces.items():
        if any(cell.hypothesis_id not in expected for cell in surface.cells):
            raise ValueError("daily surface contains a hypothesis outside the frozen universe")
    ledger.append(
        "daily_scientific_artifacts",
        {
            "evaluation_date": evaluation_date,
            "universe_hash": universe.universe_hash,
            "authority": asdict(authority),
            "source_derivation": asdict(source_derivation),
            "walkforward": asdict(walkforward),
            "empirical_null": asdict(empirical_null),
            "multiplicity": dict(multiplicity),
            "surfaces": {
                name: {"surface": asdict(value[0]), "robustness": asdict(value[1])}
                for name, value in sorted(surfaces.items())
            },
            "mechanisms": [asdict(item) for item in mechanisms],
            "block_bootstrap": [asdict(item) for item in rebuilt_bootstrap],
            "candidate_gates": [asdict(item) for item in gates_tuple],
        },
    )
    evaluation_batch: list[tuple[str, object]] = [
        (
            "daily_evaluation_started",
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "frozen_hypothesis_ids": expected,
            },
        )
    ]
    evaluation_batch.extend(("hypothesis_evidence", record) for record in evaluation_records)
    failed = [
        record.hypothesis_id
        for record in evaluation_records
        if record.terminal_status is ExperimentStatus.FAILED
    ]
    terminal_event = "daily_evaluation_failed" if failed else "daily_evaluation_completed"
    evaluation_batch.append(
        (
            terminal_event,
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "evaluated_count": len(evaluation_records),
                "failed_hypothesis_ids": failed,
            },
        )
    )
    ledger.append_many(evaluation_batch)
    _inject_crash(crash_after, "after_evaluation")
    if failed:
        raise ValueError("one or more frozen evaluations failed; failure evidence was preserved")
    exploration_batch: list[tuple[str, object]] = [
        ("hypothesis_evidence", record) for record in exploratory_records
    ]
    exploration_batch.append(
        (
            "daily_exploration_completed",
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "exploratory_count": len(exploratory_records),
            },
        )
    )
    ledger.append_many(exploration_batch)
    _inject_crash(crash_after, "after_exploration")
    analysis_batch: list[tuple[str, object]] = [
        (
            "daily_multiplicity",
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "multiplicity": dict(multiplicity),
            },
        )
    ]
    analysis_batch.extend(
        (
            "predictive_surface",
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "selector": name,
                "surface": asdict(surface),
                "robustness": asdict(robustness),
            },
        )
        for name, (surface, robustness) in sorted(surfaces.items())
    )
    analysis_batch.extend(
        (
            "mechanism_summary",
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "summary": asdict(summary),
            },
        )
        for summary in mechanisms
    )
    ledger.append_many(analysis_batch)
    _inject_crash(crash_after, "after_analysis")
    history, failure_dates = _ledger_history(
        ledger, plan=plan, policy_fingerprint=policy_fingerprint
    )
    previous_status = dict(pre_session_state.lifecycle)
    before: dict[str, LifecycleAssessment] = {}
    after: dict[str, LifecycleAssessment] = {}
    for hypothesis_id in expected:
        status = HypothesisStatus(previous_status.get(hypothesis_id, "UNTESTED"))
        prior = assess_lifecycle(
            hypothesis_id,
            history,
            as_of=evaluation_date - timedelta(days=1),
            previous_status=status,
            policy=lifecycle_policy,
            interrupted_dates=failure_dates.get(hypothesis_id, ()),
        )
        if prior.distinct_sessions:
            before[hypothesis_id] = prior
        after[hypothesis_id] = assess_lifecycle(
            hypothesis_id,
            history,
            as_of=evaluation_date,
            previous_status=status,
            policy=lifecycle_policy,
            interrupted_dates=failure_dates.get(hypothesis_id, ()),
        )
    coefficients = {
        f"{record.hypothesis_id}|{partition}|{feature}": float(value)
        for record in evaluation_records
        for partition, feature, value, _ in record.coefficient_estimates
    }
    coefficient_errors = {
        f"{record.hypothesis_id}|{partition}|{feature}": float(error)
        for record in evaluation_records
        for partition, feature, _, error in record.coefficient_estimates
    }
    historical_coefficients = {
        identity: list(values)
        for identity, values in pre_session_state.historical_coefficients
    }
    for record in evaluation_records:
        historical_coefficients.setdefault(record.hypothesis_id, []).extend(
            (
                record.evaluation_date.isoformat(),
                f"{partition}|{feature}",
                float(value),
                float(error),
            )
            for partition, feature, value, error in record.coefficient_estimates
        )
    shrinkage: dict[str, float] = {}
    family_by_hypothesis = {item.hypothesis_id: item.family for item in hypotheses}
    for family in sorted(set(family_by_hypothesis.values())):
        family_effects = {
            key: value
            for key, value in coefficients.items()
            if family_by_hypothesis[key.split("|", 1)[0]] == family
        }
        if family_effects:
            prior_variance = max(
                1e-12,
                sum(value * value for value in family_effects.values()) / len(family_effects),
            )
            shrinkage.update(
                family_shrinkage(
                    family_effects,
                    {key: coefficient_errors[key] for key in family_effects},
                    prior_variance=prior_variance,
                )
            )
    historical_effects = {
        identity: [
            float(score)
            for record in history
            if record.hypothesis_id == identity
            and record.terminal_status is ExperimentStatus.COMPLETED
            and isinstance((score := dict(record.metrics).get("score")), (int, float))
        ]
        for identity in expected
    }
    scores_by_model: dict[str, list[float]] = {}
    for record in history:
        score = dict(record.metrics).get("score")
        if record.terminal_status is ExperimentStatus.COMPLETED and isinstance(
            score, (int, float)
        ):
            scores_by_model.setdefault(record.model_class, []).append(float(score))
    if scores_by_model:
        model_weights = past_only_ensemble_weights(scores_by_model)
    else:
        model_names = sorted({item.model_class for item in hypotheses})
        model_weights = {name: 1.0 / len(model_names) for name in model_names}
    stability = {
        identity: asdict(
            stability_summary(
                values,
                coefficients=[
                    value
                    for _, _, value, _ in historical_coefficients.get(identity, ())
                ],
            )
        )
        for identity, values in historical_effects.items()
    }
    def counterpart_key(item: HypothesisDefinition) -> tuple[object, ...]:
        return (
            item.family,
            item.predictor_feature_ids,
            item.target_id,
            item.target_horizon_seconds,
            item.conditioning_variables,
            item.model_class,
            item.fitting_window_sessions,
            item.training_cadence_seconds,
            item.regularization,
            item.sampling_clock,
            item.pooling_coordinate,
        )

    global_by_key = {
        counterpart_key(item): item.hypothesis_id
        for item in hypotheses
        if item.admissible_regime == "global"
    }
    regime_rules = lifecycle_policy.get("regime_rules")
    if not isinstance(regime_rules, Mapping):
        raise ValueError("frozen regime policy is malformed")
    minimum_bucket = int(regime_rules["minimum_bucket_observations"])
    regime_diagnostic: dict[str, object] = {}
    for hypothesis in hypotheses:
        if hypothesis.admissible_regime == "global":
            continue
        counterpart = global_by_key.get(counterpart_key(hypothesis))
        if counterpart is None or not historical_effects[counterpart]:
            regime_diagnostic[hypothesis.hypothesis_id] = {
                "status": "missing_registered_global_counterpart"
            }
        else:
            regime_diagnostic[hypothesis.hypothesis_id] = regime_comparison(
                historical_effects[counterpart],
                {hypothesis.admissible_regime: historical_effects[hypothesis.hypothesis_id]},
                minimum_n=minimum_bucket,
            )
    selected_results = [
        item
        for item in walkforward.candidate_results
        if item.fold_id == walkforward.folds[-1].fold_id and item.selected_for_outer
    ]
    selection_bias = winners_curse(
        [
            float(item.validation_score)
            for item in selected_results
            if item.validation_score is not None
        ],
        [float(item.outer_score) for item in selected_results if item.outer_score is not None],
    )
    previous_robustness: dict[str, SurfaceRobustness] = {}
    for envelope in reversed(initial):
        if envelope.event_type != "daily_scientific_artifacts" or envelope.event.get(
            "universe_hash"
        ) == universe.universe_hash:
            continue
        raw_surfaces = envelope.event.get("surfaces")
        if isinstance(raw_surfaces, Mapping):
            for name, raw_pair in raw_surfaces.items():
                if isinstance(name, str) and isinstance(raw_pair, Mapping):
                    raw_robustness = raw_pair.get("robustness")
                    if isinstance(raw_robustness, Mapping):
                        previous_robustness[name] = _robustness_from_mapping(raw_robustness)
        break
    movement = {
        name: (
            {"classification": "first_bound_surface", "distance": None}
            if name not in previous_robustness
            else parameter_movement(
                previous_robustness[name], robustness, current_surface=surface
            )
        )
        for name, (surface, robustness) in surfaces.items()
    }
    negative_ids = tuple(
        item.hypothesis_id
        for item in hypotheses
        if item.family.upper().startswith("NEGATIVE_CONTROL")
    )
    negative_p = [
        float(value)
        for record in history
        if record.hypothesis_id in negative_ids
        and record.terminal_status is ExperimentStatus.COMPLETED
        for value in (dict(record.uncertainty).get("empirical_null_p_value"),)
        if isinstance(value, (int, float))
    ]
    minimum_evidence = lifecycle_policy.get("minimum_evidence")
    if not isinstance(minimum_evidence, Mapping):
        raise ValueError("frozen minimum-evidence policy is malformed")
    repeated_control_sessions = int(minimum_evidence["sessions_for_provisional"])
    diagnostics = {
        "stability_summary": stability,
        "regime_comparison": regime_diagnostic,
        "winners_curse": selection_bias,
        "negative_control_warning": (
            {"status": "not_registered", "warning": None}
            if not negative_ids
            else {
                "status": "evaluated",
                "candidate_ids": negative_ids,
                "completed_session_count": len(negative_p),
                "warning": len(negative_p) >= repeated_control_sessions
                and negative_control_warning(negative_p),
            }
        ),
        "parameter_movement": movement,
    }
    diagnostics_hash = canonical_sha256(diagnostics)
    ledger.append(
        "daily_stability_diagnostics",
        {
            "evaluation_date": evaluation_date,
            "universe_hash": universe.universe_hash,
            "diagnostics": diagnostics,
            "diagnostics_hash": diagnostics_hash,
        },
    )
    report = daily_report(
        report_date=evaluation_date,
        lifecycle_before=before,
        lifecycle_after=after,
        evaluated=(*evaluation_records, *exploratory_records),
        surfaces=surfaces,
        mechanisms=mechanisms,
        multiplicity=multiplicity,
        diagnostics=diagnostics,
        warnings=warnings,
    )
    report_path = write_daily_report(report, report_directory)
    report_manifest_path = report_path.with_suffix(".manifest.json")
    report_sha256 = _sha256_path(report_path)
    report_manifest_sha256 = _sha256_path(report_manifest_path)
    _inject_crash(crash_after, "after_report")
    ledger.append(
        "daily_report_published",
        {
            "evaluation_date": evaluation_date,
            "universe_hash": universe.universe_hash,
            "path": str(report_path),
            "report_sha256": report_sha256,
            "manifest_sha256": report_manifest_sha256,
        },
    )
    ledger.append(
        "daily_publication_prepared",
        {
            "evaluation_date": evaluation_date,
            "universe_hash": universe.universe_hash,
            "evaluated_count": len(evaluation_records),
            "exploratory_count": len(exploratory_records),
            "report_path": str(report_path),
            "next_session_date": next_session_date,
            "terminal": False,
            "reason": "state_and_snapshot_verification_pending",
        },
    )
    _inject_crash(crash_after, "after_completion")
    current_envelopes = ledger.read()
    snapshots = [
        (index, envelope)
        for index, envelope in enumerate(current_envelopes)
        if envelope.event_type == "daily_snapshot_published"
        and envelope.event.get("universe_hash") == universe.universe_hash
    ]
    if snapshots:
        if len(snapshots) != 1:
            raise ValueError("daily universe has conflicting snapshot publication events")
        snapshot_index, snapshot_envelope = snapshots[0]
        snapshot_path = Path(str(snapshot_envelope.event["snapshot_path"]))
        verify_snapshot(snapshot_path, current_envelopes[:snapshot_index])
    else:
        snapshot_path = materialize_snapshot(ledger, snapshot_directory, parquet=True)
        snapshot_envelope = ledger.append(
            "daily_snapshot_published",
            {
                "evaluation_date": evaluation_date,
                "universe_hash": universe.universe_hash,
                "snapshot_path": str(snapshot_path),
            },
        )
    _inject_crash(crash_after, "after_snapshot")
    ledger_hash = ledger.read()[-1].event_hash
    state = ResearchState(
        as_of_date=evaluation_date,
        intended_for_session=next_session_date,
        active_hypotheses=tuple(
            sorted(
                key
                for key, value in after.items()
                if value.status not in {HypothesisStatus.DORMANT, HypothesisStatus.REJECTED}
            )
        ),
        lifecycle=tuple(sorted((key, value.status.value) for key, value in after.items())),
        evidence_grades=tuple(sorted((key, value.grade.value) for key, value in after.items())),
        coefficient_estimates=tuple(sorted(coefficients.items())),
        shrinkage_state=tuple(sorted(shrinkage.items())),
        regime_models=tuple(
            sorted(
                (
                    identity,
                    canonical_sha256(
                        {
                            "regime": hypothesis_by_id[identity].admissible_regime,
                            "scores": historical_effects[identity],
                            "comparison_pass": gates[identity].regime_comparison_pass,
                        }
                    ),
                )
                for identity in expected
            )
        ),
        performance_history_hash=canonical_sha256([record.event_id for record in history]),
        dormant_hypotheses=tuple(
            sorted(key for key, value in after.items() if value.status is HypothesisStatus.DORMANT)
        ),
        parameter_surface_hashes=tuple(
            sorted((name, surface.surface_hash) for name, (surface, _) in surfaces.items())
        ),
        model_weights=tuple(sorted(model_weights.items())),
        source_ledger_hash=ledger_hash,
        plan_hash=universe.plan_hash,
        planned_hypothesis_ids=expected,
        source_prefix_manifest=observed_source_manifest,
        derivation_prefixes=(
            *pre_session_state.derivation_prefixes,
            (evaluation_date.isoformat(), source_derivation.derivation_hash),
        ),
        policy_fingerprint=policy_fingerprint,
        historical_effects=tuple(
            sorted((identity, tuple(values)) for identity, values in historical_effects.items())
        ),
        diagnostic_hashes=(
            *pre_session_state.diagnostic_hashes,
            (evaluation_date.isoformat(), diagnostics_hash),
        ),
        block_bootstrap_hashes=authority.block_bootstrap_hashes,
        historical_coefficients=tuple(
            sorted(
                (identity, tuple(values))
                for identity, values in historical_coefficients.items()
            )
        ),
        evidence_mode=walkforward.mode.value,
        published_at=snapshot_envelope.recorded_at,
        publication_event_hash=snapshot_envelope.event_hash,
        report_path=str(report_path),
        report_sha256=report_sha256,
        report_manifest_sha256=report_manifest_sha256,
    ).with_hash()
    state_path = state_store.write(state)
    _inject_crash(crash_after, "after_state")
    return DailyExecutionResult(
        evaluation_date,
        len(evaluation_records),
        len(exploratory_records),
        state_path,
        report_path,
        snapshot_path,
        state.state_hash,
    )
