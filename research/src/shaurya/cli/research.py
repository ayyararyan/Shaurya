"""Installed, source-derived command group for post-market alpha research."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DatasetHandle
from shaurya.data import DataCatalog

from shaurya.research.artifacts import build_candidate_gate_artifacts
from shaurya.research.contracts import (
    HypothesisDefinition,
    ResearchMode,
    canonical_json,
    canonical_sha256,
)
from shaurya.research.evidence import EvidenceAuthority, EvidenceRecord, SelectionProvenance
from shaurya.research.executor import execute_daily, freeze_daily_universe
from shaurya.research.ledger import (
    EvidenceLedger,
    _atomic_create_once,
    _sha256_path,
    materialize_snapshot,
)
from shaurya.research.mechanisms import summarize_mechanism
from shaurya.research.miner import run_source_bound_mining
from shaurya.research.multiplicity import (
    adjust_hierarchical,
    build_candidate_bootstrap_artifacts,
)
from shaurya.research.nulls import nested_walkforward_empirical_null
from shaurya.research.planner import (
    AlphaPlan,
    alpha_plan_from_mapping,
    plan_from_directory,
    validate_plan_registries,
)
from shaurya.research.registry import FrozenRegistry, expand_hypotheses, registry_by_version
from shaurya.research.source import (
    DerivedResearchDataset,
    derivation_hash_for_sources,
    derive_research_dataset,
    verify_completed_source,
)
from shaurya.research.state import ResearchState, StateStore
from shaurya.research.surfaces import candidate_neighbors, partitioned_hypothesis_surfaces
from shaurya.research.walkforward import (
    CandidateFoldResult,
    NestedWalkForwardResult,
    freeze_prospective_fold,
)

DEFAULT_REGISTRY_DIRECTORY = Path("registries")
DEFAULT_LEDGER = Path("derived/research/alpha-evidence-ledger.jsonl")
DEFAULT_STATE_DIRECTORY = Path("derived/research/state")
DEFAULT_REPORT_DIRECTORY = Path("derived/research/reports")
DEFAULT_SNAPSHOT_DIRECTORY = Path("derived/research/snapshots")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY_DIRECTORY)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)


def _registry_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--feature-registry", default="microstructure_features_v1")
    parser.add_argument("--target-registry", default="microstructure_targets_v1")
    parser.add_argument("--hypothesis-registry", default="alpha_hypotheses_v1")
    parser.add_argument("--policy", default="alpha_research_policy_v1")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shaurya-research")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan-alpha")
    _common(plan)
    _registry_args(plan)
    plan.add_argument("--through", type=date.fromisoformat, required=True)
    plan.add_argument("--output", type=Path)

    mine = commands.add_parser("mine-alpha")
    _common(mine)
    _registry_args(mine)
    mine.add_argument("--through", type=date.fromisoformat, required=True)
    mine.add_argument("--source-handle", type=Path, action="append", required=True)
    mine.add_argument("--catalog", type=Path, required=True)
    mine.add_argument("--plan", type=Path, required=True)
    mine.add_argument("--state", type=Path, required=True)

    evaluate = commands.add_parser("evaluate-alpha")
    _common(evaluate)
    _registry_args(evaluate)
    evaluate.add_argument("--date", type=date.fromisoformat, required=True)
    evaluate.add_argument("--next-session", type=date.fromisoformat, required=True)
    evaluate.add_argument("--source-handle", type=Path, action="append", required=True)
    evaluate.add_argument("--catalog", type=Path, required=True)
    evaluate.add_argument("--plan", type=Path, required=True)
    evaluate.add_argument("--state", type=Path, required=True)
    evaluate.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIRECTORY)
    evaluate.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIRECTORY)
    evaluate.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIRECTORY)
    evaluate.add_argument("--crash-after", help=argparse.SUPPRESS)
    evaluate.add_argument(
        "--mode",
        choices=(ResearchMode.CONFIRMATORY.value, ResearchMode.LIVE_SHADOW.value),
        default=ResearchMode.CONFIRMATORY.value,
    )

    initialize = commands.add_parser("init-alpha-state")
    _common(initialize)
    _registry_args(initialize)
    initialize.add_argument("--plan", type=Path, required=True)
    initialize.add_argument("--as-of", type=date.fromisoformat, required=True)
    initialize.add_argument("--intended-for-session", type=date.fromisoformat, required=True)
    initialize.add_argument("--source-handle", type=Path, action="append", required=True)
    initialize.add_argument("--catalog", type=Path, required=True)
    initialize.add_argument(
        "--mode",
        choices=(ResearchMode.CONFIRMATORY.value, ResearchMode.LIVE_SHADOW.value),
        default=ResearchMode.CONFIRMATORY.value,
    )
    initialize.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIRECTORY)

    ledger = commands.add_parser("alpha-ledger")
    _common(ledger)
    ledger.add_argument("--snapshot-dir", type=Path)
    ledger.add_argument("--parquet", action="store_true")
    state = commands.add_parser("alpha-state")
    state.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIRECTORY)
    state.add_argument("--as-of", type=date.fromisoformat, required=True)
    explain = commands.add_parser("explain-alpha")
    _common(explain)
    explain.add_argument("hypothesis_id")
    mechanism = commands.add_parser("mechanism-status")
    _common(mechanism)
    _registry_args(mechanism)
    surface = commands.add_parser("predictive-surface")
    _common(surface)
    surface.add_argument("selector")
    return parser


def _print(value: object) -> None:
    print(canonical_json(value))


def _load_plan(path: Path) -> AlphaPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("plan artifact must be an object")
    return alpha_plan_from_mapping(raw)


def _registries(
    directory: Path,
    *,
    feature: str,
    target: str,
    hypothesis: str,
    policy: str,
) -> tuple[FrozenRegistry, FrozenRegistry, FrozenRegistry, FrozenRegistry]:
    return (
        registry_by_version(directory, feature, expected_type="features"),
        registry_by_version(directory, target, expected_type="targets"),
        registry_by_version(directory, hypothesis, expected_type="hypotheses"),
        registry_by_version(directory, policy, expected_type="policy"),
    )


def _load_dataset(
    paths: Sequence[Path],
    *,
    through: date,
    feature_registry: FrozenRegistry,
    target_registry: FrozenRegistry,
    catalog_path: Path,
) -> DerivedResearchDataset:
    catalog = DataCatalog(catalog_path)
    sources = []
    for path in paths:
        handle = DatasetHandle.model_validate_json(path.read_text(encoding="utf-8"))
        sources.append(verify_completed_source(handle, through=through, catalog=catalog))
    frozen = tuple(sorted(sources, key=lambda item: (item.trading_date, item.dataset_id)))
    return derive_research_dataset(
        frozen, feature_registry=feature_registry, target_registry=target_registry
    )


def _exact_hypotheses(
    plan: AlphaPlan, registry: FrozenRegistry
) -> tuple[HypothesisDefinition, ...]:
    by_id = {item.hypothesis_id: item for item in expand_hypotheses(registry)}
    if not set(plan.eligible_hypothesis_ids) <= set(by_id):
        raise ValueError("plan contains a hypothesis absent from the frozen runtime registry")
    return tuple(by_id[identity] for identity in plan.eligible_hypothesis_ids)


def _validate_runtime(
    plan: AlphaPlan,
    registries: tuple[FrozenRegistry, FrozenRegistry, FrozenRegistry, FrozenRegistry],
) -> None:
    validate_plan_registries(
        plan,
        feature_registry=registries[0],
        target_registry=registries[1],
        hypothesis_registry=registries[2],
        policy_registry=registries[3],
    )


def _mine(args: argparse.Namespace) -> None:
    plan = _load_plan(args.plan)
    if plan.through != args.through:
        raise ValueError("mine cutoff must match the frozen plan cutoff")
    registries = _registries(
        args.registry_dir,
        feature=args.feature_registry,
        target=args.target_registry,
        hypothesis=args.hypothesis_registry,
        policy=args.policy,
    )
    _validate_runtime(plan, registries)
    state = StateStore(args.state.parent).load_exact(args.state)
    if (
        state.plan_hash != plan.plan_hash
        or state.as_of_date > args.through
        or state.planned_hypothesis_ids != plan.eligible_hypothesis_ids
        or state.policy_fingerprint != registries[3].fingerprint_sha256
    ):
        raise ValueError("mine state is not the exact plan-frozen pre-session state")
    ledger = EvidenceLedger(args.ledger)
    envelopes = ledger.read()
    ledger_tail = envelopes[-1].event_hash if envelopes else "0" * 64
    if state.source_ledger_hash != ledger_tail:
        start = 0
        if state.source_ledger_hash != "0" * 64:
            matches = [
                index
                for index, envelope in enumerate(envelopes)
                if envelope.event_hash == state.source_ledger_hash
            ]
            if len(matches) != 1:
                raise ValueError("mine ledger tail differs from the exact input state")
            start = matches[0] + 1
        if any(
            envelope.event_type
            not in {"mining_candidate", "mining_empirical_null", "mining_candidate_failed"}
            or envelope.event.get("plan_hash") != plan.plan_hash
            or envelope.event.get("state_hash") != state.state_hash
            for envelope in envelopes[start:]
        ):
            raise ValueError("mine ledger tail differs from the exact input state")
    dataset = _load_dataset(
        args.source_handle,
        through=args.through,
        feature_registry=registries[0],
        target_registry=registries[1],
        catalog_path=args.catalog,
    )
    observed_prefix = tuple(
        (item.trading_date.isoformat(), item.dataset_id, item.source_identity_hash)
        for item in dataset.sources
    )
    historical_count = len(state.source_prefix_manifest)
    if observed_prefix[:historical_count] != state.source_prefix_manifest:
        raise ValueError("mining source history is not the immutable state prefix")
    if state.derivation_prefixes and derivation_hash_for_sources(
        dataset, dataset.sources[:historical_count]
    ) != state.derivation_prefixes[-1][1]:
        raise ValueError("mining historical rows were re-derived under different sources")
    hypotheses = _exact_hypotheses(plan, registries[2])
    result = run_source_bound_mining(
        dataset,
        hypotheses,
        policy=registries[3].payload,
        plan_hash=plan.plan_hash,
        registry_fingerprints=plan.registry_fingerprints,
    )
    events: list[tuple[str, object]] = [
        (
            "mining_candidate",
            {
                "hypothesis_id": identity,
                "through": args.through,
                "score": score,
                "candidate_ids": result.candidate_ids,
                "terminal_status": {
                    item[0]: item[1] for item in result.candidate_terminal_statuses
                }[identity],
                "terminal_reason": {
                    item[0]: item[2] for item in result.candidate_terminal_statuses
                }[identity],
                "mode": ResearchMode.EXPLORATORY.value,
                "plan_hash": plan.plan_hash,
                "state_hash": state.state_hash,
                "source_derivation_hash": dataset.derivation_hash,
                "mining_result_hash": result.result_hash,
            },
        )
        for identity, score in result.observed_scores
    ]
    events.append(
        (
            "mining_empirical_null",
            {
                **asdict(result),
                "mode": ResearchMode.EXPLORATORY.value,
                "state_hash": state.state_hash,
            },
        )
    )
    ledger.append_many(events)
    _print(asdict(result))


def _initialize_state(args: argparse.Namespace) -> None:
    plan = _load_plan(args.plan)
    registries = _registries(
        args.registry_dir,
        feature=args.feature_registry,
        target=args.target_registry,
        hypothesis=args.hypothesis_registry,
        policy=args.policy,
    )
    _validate_runtime(plan, registries)
    if args.as_of != plan.through or args.as_of >= args.intended_for_session:
        raise ValueError("bootstrap state must be plan-bound and strictly pre-session")
    dataset = _load_dataset(
        args.source_handle,
        through=args.as_of,
        feature_registry=registries[0],
        target_registry=registries[1],
        catalog_path=args.catalog,
    )
    if max(item.trading_date for item in dataset.sources) != args.as_of:
        raise ValueError("bootstrap sources must freeze the complete through-date prefix")
    envelopes = EvidenceLedger(args.ledger).read()
    ledger_tail = envelopes[-1].event_hash if envelopes else "0" * 64
    state = ResearchState(
        as_of_date=args.as_of,
        intended_for_session=args.intended_for_session,
        active_hypotheses=plan.eligible_hypothesis_ids,
        lifecycle=tuple((identity, "UNTESTED") for identity in plan.eligible_hypothesis_ids),
        evidence_grades=tuple(
            (identity, "E0_UNTESTED") for identity in plan.eligible_hypothesis_ids
        ),
        coefficient_estimates=(),
        shrinkage_state=(),
        regime_models=(),
        performance_history_hash=canonical_sha256([]),
        dormant_hypotheses=(),
        parameter_surface_hashes=(),
        model_weights=(),
        source_ledger_hash=ledger_tail,
        plan_hash=plan.plan_hash,
        planned_hypothesis_ids=plan.eligible_hypothesis_ids,
        source_prefix_manifest=tuple(
            (item.trading_date.isoformat(), item.dataset_id, item.source_identity_hash)
            for item in dataset.sources
        ),
        derivation_prefixes=((args.as_of.isoformat(), dataset.derivation_hash),),
        policy_fingerprint=registries[3].fingerprint_sha256,
        evidence_mode=args.mode,
    ).with_hash()
    path = StateStore(args.state_dir).write(state)
    _print({"state_path": path, "state": asdict(state)})


def _interval_for_dates(values: Sequence[date]) -> tuple[str, str]:
    start = datetime.combine(min(values), time.min, tzinfo=UTC)
    end = datetime.combine(max(values) + timedelta(days=1), time.min, tzinfo=UTC) - timedelta(
        microseconds=1
    )
    return start.isoformat(), end.isoformat()


def _last_fold_results(result: NestedWalkForwardResult) -> dict[str, CandidateFoldResult]:
    fold_id = result.folds[-1].fold_id
    values = {
        item.hypothesis_id: item for item in result.candidate_results if item.fold_id == fold_id
    }
    if tuple(sorted(values)) != result.candidate_ids:
        raise ValueError("walk-forward result lacks complete final-fold accounting")
    return values


def _evaluate(args: argparse.Namespace) -> None:
    plan = _load_plan(args.plan)
    if plan.through >= args.date:
        raise ValueError("evaluation requires a plan frozen before the unseen session")
    registries = _registries(
        args.registry_dir,
        feature=args.feature_registry,
        target=args.target_registry,
        hypothesis=args.hypothesis_registry,
        policy=args.policy,
    )
    _validate_runtime(plan, registries)
    if args.state.parent.resolve() != args.state_dir.resolve():
        raise ValueError("evaluation state must come from the bound output state directory")
    state = StateStore(args.state_dir).load_exact(args.state)
    if args.mode != state.evidence_mode:
        raise ValueError("evaluation mode differs from the exact pre-session state")
    if ResearchMode(args.mode) is ResearchMode.LIVE_SHADOW:
        intended_start = datetime.combine(state.intended_for_session, time.min, tzinfo=UTC)
        if datetime.now(UTC) >= intended_start:
            raise ValueError("live-shadow evidence must be durably run before its intended session")
    universe = freeze_daily_universe(plan=plan, evaluation_date=args.date, pre_session_state=state)
    dataset = _load_dataset(
        args.source_handle,
        through=args.date,
        feature_registry=registries[0],
        target_registry=registries[1],
        catalog_path=args.catalog,
    )
    source_dates = {item.trading_date for item in dataset.sources}
    if args.date not in source_dates or any(value > args.date for value in source_dates):
        raise ValueError("canonical sources must include exactly the requested outer session")
    hypotheses = _exact_hypotheses(plan, registries[2])
    validation = registries[3].payload["validation"]
    outer = registries[3].payload["outer_test"]
    if not isinstance(validation, Mapping) or not isinstance(outer, Mapping):
        raise ValueError("walk-forward policy is malformed")
    fold = freeze_prospective_fold(
        tuple(value for value in source_dates if value < args.date),
        evaluation_date=args.date,
        minimum_training_sessions=int(validation["minimum_inner_sessions"]),
        validation_sessions=1,
        purge_seconds=float(outer["purge_seconds"]),
        embargo_seconds=float(outer["embargo_seconds"]),
    )
    evaluation_mode = ResearchMode(args.mode)
    nested, null = nested_walkforward_empirical_null(
        dataset,
        hypotheses,
        (fold,),
        policy=registries[3].payload,
        mode=evaluation_mode,
    )
    final = _last_fold_results(nested)
    empirical = dict(null.candidate_adjusted_p_values)
    adjusted = adjust_hierarchical(
        empirical,
        {item.hypothesis_id: item.family for item in hypotheses},
        method=str(registries[3].payload["multiplicity"]["method"]),
        declared_candidate_ids=universe.hypothesis_ids,
    )
    multiplicity = {
        "hypotheses_considered": len(universe.hypothesis_ids),
        "effective_families": len({item.family for item in hypotheses}),
        "raw_significant_findings": sum(value <= 0.05 for value in empirical.values()),
        "adjusted_findings": sum(item.experiment_adjusted_p_value <= 0.05 for item in adjusted),
        "candidate_results": tuple(
            (
                item.hypothesis_id,
                item.raw_p_value,
                item.family_adjusted_p_value,
                item.experiment_adjusted_p_value,
            )
            for item in adjusted
        ),
        "method": adjusted[0].method,
        "artifact_inputs": {
            "plan_hash": plan.plan_hash,
            "source_derivation_hash": dataset.derivation_hash,
            "walkforward_hash": nested.result_hash,
            "empirical_null_hash": null.fingerprint,
        },
    }
    scores = {identity: final[identity].outer_score for identity in universe.hypothesis_ids}
    support = {identity: final[identity].outer_observations for identity in universe.hypothesis_ids}
    surfaces = partitioned_hypothesis_surfaces(
        hypotheses, scores=scores, support=support
    )
    mechanisms = tuple(
        summarize_mechanism(
            name,
            {
                cell.hypothesis_id: float(cell.score)
                for cell in surface.cells
                if cell.score is not None
            },
            {
                identity: values
                for identity, values in state.historical_effects
                if identity in {cell.hypothesis_id for cell in surface.cells}
            },
            adjusted_p_values={
                item.hypothesis_id: item.experiment_adjusted_p_value
                for item in adjusted
            },
        )
        for name, (surface, _) in sorted(surfaces.items())
    )
    adjusted_by_id = {
        item.hypothesis_id: item.experiment_adjusted_p_value for item in adjusted
    }
    robustness_policy = registries[3].payload["robustness"]
    assert isinstance(robustness_policy, Mapping)
    block_bootstrap = build_candidate_bootstrap_artifacts(
        nested,
        replicates=int(robustness_policy["block_bootstrap_replicates"]),
        mean_block_length=float(robustness_policy["block_bootstrap_mean_length"]),
        seed=int(robustness_policy["block_bootstrap_seed"]),
    )
    block_bootstrap_by_id = {item.hypothesis_id: item for item in block_bootstrap}
    gates = build_candidate_gate_artifacts(
        hypotheses=hypotheses,
        walkforward=nested,
        empirical_null=null,
        adjusted_p_values=adjusted_by_id,
        surfaces=surfaces,
        block_bootstrap=block_bootstrap_by_id,
        policy=registries[3].payload,
    )
    authority = EvidenceAuthority(
        plan.plan_hash,
        universe.pre_session_state_hash,
        dataset.derivation_hash,
        universe.hypothesis_ids,
        plan.registry_fingerprints,
        registries[3].fingerprint_sha256,
        nested.result_hash,
        canonical_sha256(multiplicity),
        null.fingerprint,
        tuple(sorted((name, value[0].surface_hash) for name, value in surfaces.items())),
        tuple(sorted((name, value[1].robustness_hash) for name, value in surfaces.items())),
        tuple((item.hypothesis_id, item.gate_hash) for item in gates),
        tuple((item.hypothesis_id, item.bootstrap_hash) for item in block_bootstrap),
        mechanism_hashes=tuple(
            (item.mechanism, canonical_sha256(asdict(item))) for item in mechanisms
        ),
    ).with_hash()
    validation_scores = tuple(
        sorted((identity, final[identity].validation_score) for identity in universe.hypothesis_ids)
    )
    ranked_validation = sorted(
        validation_scores,
        key=lambda item: (
            -(abs(item[1]) if item[1] is not None else -1.0),
            item[0],
        ),
    )
    ranks = {
        identity: rank
        for rank, (identity, _) in enumerate(ranked_validation, start=1)
    }
    differences: dict[str, float | None] = {}
    for index, (identity, score) in enumerate(ranked_validation):
        next_score = ranked_validation[index + 1][1] if index + 1 < len(ranked_validation) else None
        differences[identity] = (
            None
            if score is None or next_score is None
            else abs(float(score)) - abs(float(next_score))
        )
    adjusted_result_by_id = {item.hypothesis_id: item for item in adjusted}
    hypothesis_by_id = {item.hypothesis_id: item for item in hypotheses}
    gate_by_id = {item.hypothesis_id: item for item in gates}
    records: list[EvidenceRecord] = []
    for identity in universe.hypothesis_ids:
        item = final[identity]
        hypothesis = hypothesis_by_id[identity]
        gate = gate_by_id[identity]
        outer_feature_hashes = tuple(
            sorted(
                {
                    row.feature.feature_run_hash
                    for row in dataset.rows
                    if row.feature.session_date == args.date
                    and row.target.target_id == hypothesis.target_id
                }
            )
        )
        selection = SelectionProvenance(
            universe.hypothesis_ids,
            hypothesis.evaluation_metric,
            fold.selection_information_ts,
            fold.evaluation_period_start,
            ranks[identity] if item.selected_for_outer else None,
            validation_scores,
            differences[identity],
            candidate_neighbors(
                next(
                    surface
                    for surface, _ in surfaces.values()
                    if identity in {cell.hypothesis_id for cell in surface.cells}
                ),
                identity,
            ),
            adjusted_result_by_id[identity].method,
            evaluation_mode,
        )
        records.append(
            EvidenceRecord(
                identity,
                args.date,
                evaluation_mode,
                _interval_for_dates(fold.inner_training_dates),
                _interval_for_dates(fold.inner_validation_dates),
                _interval_for_dates(fold.outer_evaluation_dates),
                item.outer_observations,
                gate.effective_sample_size,
                hypothesis.model_class,
                hypothesis.regularization,
                registries[0].version,
                registries[1].version,
                registries[3].version,
                outer_feature_hashes,
                (
                    ("score", gate.score),
                    ("coefficient", gate.coefficient),
                    ("neighbor_robustness", gate.local_robustness),
                    ("economic_magnitude", gate.economic_magnitude),
                    ("score_gate_pass", gate.score_gate_pass),
                    ("economic_gate_pass", gate.economic_gate_pass),
                    ("regime_comparison_pass", gate.regime_comparison_pass),
                    ("block_bootstrap_gate_pass", gate.block_bootstrap_gate_pass),
                    (
                        "surface_hash",
                        next(
                            surface.surface_hash
                            for surface, _ in surfaces.values()
                            if identity in {cell.hypothesis_id for cell in surface.cells}
                        ),
                    ),
                    ("model_hash", gate.model_hash),
                    ("candidate_gate_hash", gate.gate_hash),
                ),
                (
                    ("adjusted_p_value", gate.adjusted_p_value),
                    ("empirical_null_p_value", gate.empirical_null_p_value),
                    ("block_bootstrap_estimate", gate.block_bootstrap_estimate),
                    ("block_bootstrap_lower", gate.block_bootstrap_lower),
                    ("block_bootstrap_upper", gate.block_bootstrap_upper),
                    ("block_bootstrap_standard_error", gate.block_bootstrap_standard_error),
                    ("block_bootstrap_hash", gate.block_bootstrap_hash),
                ),
                selection,
                len(universe.hypothesis_ids),
                gate.terminal_status,
                gate.terminal_reason,
                plan.plan_hash,
                universe.pre_session_state_hash,
                dataset.derivation_hash,
                (fold.fold_hash,),
                authority.authority_hash,
                coefficient_estimates=gate.coefficients,
                selected_for_outer=gate.selected_for_outer,
            )
        )
    result = execute_daily(
        evaluation_date=args.date,
        plan=plan,
        pre_session_state=state,
        universe=universe,
        evaluation_records=tuple(records),
        exploratory_records=(),
        ledger=EvidenceLedger(args.ledger),
        state_store=StateStore(args.state_dir),
        report_directory=args.report_dir,
        snapshot_directory=args.snapshot_dir,
        lifecycle_policy=registries[3].payload,
        surfaces=surfaces,
        mechanisms=mechanisms,
        multiplicity=multiplicity,
        authority=authority,
        source_derivation=dataset,
        hypotheses=hypotheses,
        walkforward=nested,
        empirical_null=null,
        block_bootstrap=block_bootstrap,
        policy_fingerprint=registries[3].fingerprint_sha256,
        next_session_date=args.next_session,
        warnings=(
            "isolated parameter spike"
            if any(value[1].isolated_spike for value in surfaces.values())
            else "complete surface retained",
        ),
        crash_after=args.crash_after,
    )
    _print(asdict(result))


def _account_failed_command(args: argparse.Namespace, error: Exception) -> None:
    """Durably account every frozen candidate even when construction fails early."""

    if isinstance(error, RuntimeError) and str(error).startswith(
        "injected daily publication crash"
    ):
        # The scientific experiment has already been deterministically accounted; this is only
        # a publication-boundary recovery probe and must not contaminate lifecycle evidence.
        return

    try:
        plan = _load_plan(args.plan)
        state = StateStore(args.state.parent).load_exact(args.state)
    except Exception:
        return
    if args.command == "evaluate-alpha":
        published = StateStore(args.state_dir).load_as_of(args.date)
        if published is not None and published.as_of_date == args.date:
            return
    universe_hash = ""
    if args.command == "evaluate-alpha":
        try:
            universe_hash = freeze_daily_universe(
                plan=plan,
                evaluation_date=args.date,
                pre_session_state=state,
            ).universe_hash
        except Exception:
            return
    cutoff = args.date if args.command == "evaluate-alpha" else args.through
    reason = f"{type(error).__name__}:{error}"
    event_type = (
        "evaluation_candidate_failed"
        if args.command == "evaluate-alpha"
        else "mining_candidate_failed"
    )
    events = [
        (
            event_type,
            {
                "event_id": canonical_sha256(
                    {
                        "command": args.command,
                        "cutoff": cutoff,
                        "hypothesis_id": identity,
                        "plan_hash": plan.plan_hash,
                        "reason": reason,
                    }
                ),
                "hypothesis_id": identity,
                "through": cutoff,
                "terminal_status": "failed",
                "terminal_reason": reason,
                "mode": (
                    args.mode
                    if args.command == "evaluate-alpha"
                    else ResearchMode.EXPLORATORY.value
                ),
                "plan_hash": plan.plan_hash,
                "state_hash": state.state_hash,
                "universe_hash": universe_hash,
            },
        )
        for identity in plan.eligible_hypothesis_ids
    ]
    EvidenceLedger(args.ledger).append_many(events)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "plan-alpha":
        plan = plan_from_directory(
            args.registry_dir,
            through=args.through,
            feature_version=args.feature_registry,
            target_version=args.target_registry,
            hypothesis_version=args.hypothesis_registry,
            policy_version=args.policy,
        )
        payload = plan.to_dict()
        if args.output is not None:
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _atomic_create_once(args.output, (canonical_json(payload) + "\n").encode())
            _atomic_create_once(
                args.output.with_suffix(args.output.suffix + ".manifest.json"),
                (
                    canonical_json(
                        {
                            "artifact": args.output.name,
                            "artifact_sha256": _sha256_path(args.output),
                            "plan_hash": plan.plan_hash,
                        }
                    )
                    + "\n"
                ).encode(),
            )
        _print(payload)
    elif args.command == "mine-alpha":
        try:
            _mine(args)
        except Exception as exc:
            _account_failed_command(args, exc)
            raise
    elif args.command == "init-alpha-state":
        _initialize_state(args)
    elif args.command == "evaluate-alpha":
        try:
            _evaluate(args)
        except Exception as exc:
            _account_failed_command(args, exc)
            raise
    elif args.command == "alpha-ledger":
        ledger = EvidenceLedger(args.ledger)
        if args.snapshot_dir is not None:
            _print(
                {"snapshot": materialize_snapshot(ledger, args.snapshot_dir, parquet=args.parquet)}
            )
        else:
            _print([asdict(item) for item in ledger.read()])
    elif args.command == "alpha-state":
        state = StateStore(args.state_dir).load_as_of(args.as_of)
        _print(
            {
                "as_of": args.as_of,
                "state": None if state is None else asdict(state),
                "missing": state is None,
            }
        )
    elif args.command == "explain-alpha":
        events = [
            event
            for event in EvidenceLedger(args.ledger).events()
            if event.get("hypothesis_id") == args.hypothesis_id
        ]
        _print({"hypothesis_id": args.hypothesis_id, "events": events, "missing": not events})
    elif args.command == "mechanism-status":
        hypotheses = expand_hypotheses(
            registry_by_version(
                args.registry_dir, args.hypothesis_registry, expected_type="hypotheses"
            )
        )
        family_by_id = {item.hypothesis_id: item.family for item in hypotheses}
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for event in EvidenceLedger(args.ledger).events():
            identity = event.get("hypothesis_id")
            if isinstance(identity, str) and identity in family_by_id:
                grouped.setdefault(family_by_id[identity], []).append(event)
        _print({"mechanisms": {key: value for key, value in sorted(grouped.items())}})
    elif args.command == "predictive-surface":
        surfaces = [
            event
            for event in EvidenceLedger(args.ledger).events(event_type="predictive_surface")
            if event.get("selector") == args.selector
        ]
        _print({"selector": args.selector, "surfaces": surfaces, "missing": not surfaces})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
