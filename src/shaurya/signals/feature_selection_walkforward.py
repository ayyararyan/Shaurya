"""D51 Step 7 deterministic nested expanding walk-forward orchestration.

The module is deliberately data-source agnostic.  DAT replay and canonical feature
construction live in the CLI; this layer receives already constructed D51 rows and makes
all learned decisions inside each outer training fold.  Outer tests are apply/score only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import partial
from typing import Any, Literal, cast

import numpy as np

from shaurya.signals.feature_selection import (
    BOOSTED_TREE_CONFIG_GRID,
    ELASTIC_NET_CONFIG_GRID,
    BoostedTreeConfig,
    ClusterFoldStabilityResult,
    ConditionalUsefulnessArtifact,
    ConditionalUsefulnessConfig,
    CorrelationReductionConfig,
    ElasticNetClusterStabilityArtifact,
    ElasticNetConfig,
    ElasticNetStabilityConfig,
    FeatureConstructionResult,
    FeatureQualityGateConfig,
    FeatureSelectionRow,
    ImportanceClusterDefinition,
    ModelKind,
    PredictiveModel,
    RegressionMetrics,
    ShallowGradientBoostingModel,
    StabilitySelectionArtifact,
    aggregate_cluster_stability_selection,
    apply_correlated_feature_reduction,
    apply_feature_quality_gates,
    build_registry,
    evaluate_conditional_oos_usefulness,
    fit_cluster_elastic_net_stability,
    fit_correlated_feature_reduction,
    fit_elastic_net,
    fit_shallow_gradient_boosting,
    fit_state_linear_baseline,
    fit_training_mean_baseline,
    predict_model,
    regression_metrics,
    zero_return_baseline,
)

NANOSECONDS_PER_SECOND = 1_000_000_000
WALK_FORWARD_ARTIFACT_VERSION = "1.0.0"
PRIMARY_GRID_SECONDS = 1
SENSITIVITY_GRID_SECONDS = 5


@dataclass(frozen=True, slots=True)
class NestedWalkForwardConfig:
    outer_fold_count: int = 3
    initial_training_fraction: float = 0.40
    inner_validation_fraction: float = 0.20
    purge_seconds: float = 10.5
    embargo_seconds: float = 120.0
    sampling_grid_seconds: int = PRIMARY_GRID_SECONDS

    def __post_init__(self) -> None:
        if self.outer_fold_count < 2:
            raise ValueError("at least two outer folds are required")
        if not 0.0 < self.initial_training_fraction < 1.0:
            raise ValueError("initial training fraction must lie in (0, 1)")
        if not 0.0 < self.inner_validation_fraction < 0.5:
            raise ValueError("inner validation fraction must lie in (0, 0.5)")
        if self.purge_seconds < 10.5:
            raise ValueError("purge must cover the complete D51 target interval")
        if self.embargo_seconds < max(120.0, self.purge_seconds):
            raise ValueError("embargo must be at least max(120s, Z+h)")
        if self.sampling_grid_seconds not in (PRIMARY_GRID_SECONDS, SENSITIVITY_GRID_SECONDS):
            raise ValueError("D51 engineering grids are frozen at one or five seconds")


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    outer_training_indices: tuple[int, ...]
    inner_training_indices: tuple[int, ...]
    inner_validation_indices: tuple[int, ...]
    outer_test_indices: tuple[int, ...]
    outer_test_start_ts_ns: int
    outer_test_end_ts_ns: int


@dataclass(frozen=True, slots=True)
class CandidateScore:
    model_id: str
    model_kind: Literal["elastic_net", "shallow_gradient_boosting"]
    config: Mapping[str, float | int]
    validation_mse: float


@dataclass(frozen=True, slots=True)
class FoldModelResult:
    fold_id: str
    model_id: str
    model_kind: ModelKind
    selected_config: Mapping[str, float | int | str]
    training_rows: int
    validation_rows: int
    test_rows: int
    feature_count: int
    cluster_count: int
    training_end_ts_ns: int
    test_start_ts_ns: int
    metrics: RegressionMetrics
    predictions: tuple[float, ...]
    test_row_ids: tuple[str, ...]
    model_fingerprint_sha256: str


@dataclass(frozen=True, slots=True)
class NestedWalkForwardArtifact:
    version: str
    config: NestedWalkForwardConfig
    evidence_status: Literal["exploratory_insufficient_sessions"]
    distinct_session_count: int
    sampled_row_count: int
    sampled_first_ts_ns: int
    sampled_last_ts_ns: int
    fold_fingerprint_sha256: str
    candidate_scores: tuple[CandidateScore, ...]
    model_results: tuple[FoldModelResult, ...]


@dataclass(frozen=True, slots=True)
class FoldEmpiricalEvidence:
    fold_id: str
    eligible_features: tuple[str, ...]
    excluded_features: tuple[str, ...]
    gate_reason_counts: Mapping[str, int]
    training_feature_diagnostics: tuple[Mapping[str, float | int | str | bool | None], ...]
    cluster_definitions: tuple[ImportanceClusterDefinition, ...]
    volatility_regimes: tuple[str, ...]
    spread_regimes: tuple[str, ...]
    time_phases: tuple[str, ...]
    usefulness_artifacts: tuple[ConditionalUsefulnessArtifact, ...]
    elastic_net_stability: ElasticNetClusterStabilityArtifact


@dataclass(frozen=True, slots=True)
class CompleteWalkForwardEvidence:
    fold_evidence: tuple[FoldEmpiricalEvidence, ...]
    stability_selection: StabilitySelectionArtifact


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def sample_on_grid(
    rows: Sequence[FeatureSelectionRow], *, grid_seconds: int
) -> tuple[FeatureSelectionRow, ...]:
    """Keep the first causal row in each UTC-aligned engineering bucket."""

    if grid_seconds not in (PRIMARY_GRID_SECONDS, SENSITIVITY_GRID_SECONDS):
        raise ValueError("grid must be one or five seconds")
    ordered = tuple(sorted(rows, key=lambda item: (item.anchor_ts_ns, item.connection_epoch)))
    width = grid_seconds * NANOSECONDS_PER_SECOND
    sampled: list[FeatureSelectionRow] = []
    seen: set[tuple[int, int]] = set()
    for row in ordered:
        key = (row.connection_epoch, row.anchor_ts_ns // width)
        if key not in seen:
            seen.add(key)
            sampled.append(row)
    return tuple(sampled)


def construct_nested_expanding_folds(
    rows: Sequence[FeatureSelectionRow], *, config: NestedWalkForwardConfig | None = None
) -> tuple[WalkForwardFold, ...]:
    """Construct chronological expanding folds with target purge and a 120-second embargo."""

    policy = config or NestedWalkForwardConfig()
    sampled = sample_on_grid(rows, grid_seconds=policy.sampling_grid_seconds)
    if len(sampled) < 30:
        raise ValueError("at least 30 sampled labelled rows are required")
    timestamps = np.asarray([row.anchor_ts_ns for row in sampled], dtype=np.int64)
    initial = max(10, math.floor(len(sampled) * policy.initial_training_fraction))
    remaining = len(sampled) - initial
    test_size = remaining // policy.outer_fold_count
    if test_size < 2:
        raise ValueError("insufficient rows for requested outer folds")
    embargo_ns = int(round(policy.embargo_seconds * NANOSECONDS_PER_SECOND))
    folds: list[WalkForwardFold] = []
    for fold_number in range(policy.outer_fold_count):
        test_start = initial + fold_number * test_size
        test_stop = (
            len(sampled) if fold_number == policy.outer_fold_count - 1 else test_start + test_size
        )
        test_indices = tuple(range(test_start, test_stop))
        test_start_ts = int(timestamps[test_start])
        outer_train = tuple(
            index
            for index in range(test_start)
            if sampled[index].target_end_ts_ns < test_start_ts
            and sampled[index].anchor_ts_ns <= test_start_ts - embargo_ns
        )
        if len(outer_train) < 10:
            raise ValueError("purge/embargo leaves insufficient outer training support")
        raw_validation_count = max(
            2, math.floor(len(outer_train) * policy.inner_validation_fraction)
        )
        validation_start_position = len(outer_train) - raw_validation_count
        validation_start_index = outer_train[validation_start_position]
        validation_start_ts = sampled[validation_start_index].anchor_ts_ns
        inner_train = tuple(
            index
            for index in outer_train[:validation_start_position]
            if sampled[index].target_end_ts_ns < validation_start_ts
            and sampled[index].anchor_ts_ns <= validation_start_ts - embargo_ns
        )
        inner_validation = tuple(outer_train[validation_start_position:])
        if not inner_train or not inner_validation:
            raise ValueError("purge/embargo leaves an empty inner split")
        folds.append(
            WalkForwardFold(
                f"outer_{fold_number + 1:02d}",
                outer_train,
                inner_train,
                inner_validation,
                test_indices,
                int(timestamps[test_start]),
                int(timestamps[test_stop - 1]),
            )
        )
    return tuple(folds)


def _fit_candidate(
    kind: Literal["elastic_net", "shallow_gradient_boosting"],
    config: Mapping[str, float | int],
    training_rows: Sequence[Mapping[str, float | None]],
    training_targets: Sequence[float],
    validation_rows: Sequence[Mapping[str, float | None]] | None,
    validation_targets: Sequence[float] | None,
    feature_names: Sequence[str],
) -> PredictiveModel:
    if kind == "elastic_net":
        return fit_elastic_net(
            training_rows,
            training_targets,
            feature_names=feature_names,
            config=ElasticNetConfig(
                alpha=float(config["alpha"]), l1_ratio=float(config["l1_ratio"])
            ),
        )
    return fit_shallow_gradient_boosting(
        training_rows,
        training_targets,
        feature_names=feature_names,
        config=BoostedTreeConfig(
            maximum_depth=int(config["maximum_depth"]),
            maximum_leaves=int(config["maximum_leaves"]),
            learning_rate=float(config["learning_rate"]),
            minimum_leaf_size=int(config["minimum_leaf_size"]),
            maximum_estimators=int(config.get("maximum_estimators", 80)),
            threshold_candidates=int(config.get("threshold_candidates", 15)),
            early_stopping_patience=int(config.get("early_stopping_patience", 10)),
        ),
        validation_rows=validation_rows,
        validation_targets=validation_targets,
    )


def _resolved_candidate_config(
    candidate: Mapping[str, float | int], model: PredictiveModel
) -> dict[str, float | int]:
    """Carry validation-selected tree stopping state into every later refit."""

    resolved = dict(candidate)
    if isinstance(model, ShallowGradientBoostingModel):
        resolved["maximum_estimators"] = len(model.trees)
    return resolved


def _candidate_registry(
    *, fast_tree_grid: bool
) -> tuple[
    tuple[
        str,
        Literal["elastic_net", "shallow_gradient_boosting"],
        dict[str, float | int],
    ],
    ...,
]:
    candidates: list[
        tuple[
            str,
            Literal["elastic_net", "shallow_gradient_boosting"],
            dict[str, float | int],
        ]
    ] = []
    for alpha, ratio in ELASTIC_NET_CONFIG_GRID:
        candidates.append(
            (
                f"elastic_net__a{alpha:g}__l1{ratio:g}",
                "elastic_net",
                {"alpha": alpha, "l1_ratio": ratio},
            )
        )
    tree_grid = BOOSTED_TREE_CONFIG_GRID
    if fast_tree_grid:
        tree_grid = tuple(item for item in tree_grid if item[2] == 0.05)
    for depth, leaves, rate, minimum_leaf in tree_grid:
        candidates.append(
            (
                f"boosted_tree__d{depth}__l{leaves}__lr{rate:g}__n{minimum_leaf}",
                "shallow_gradient_boosting",
                {
                    "maximum_depth": depth,
                    "maximum_leaves": leaves,
                    "learning_rate": rate,
                    "minimum_leaf_size": minimum_leaf,
                    "maximum_estimators": 80,
                    "threshold_candidates": 15,
                    "early_stopping_patience": 10,
                },
            )
        )
    return tuple(candidates)


def run_nested_walk_forward(
    rows: Sequence[FeatureSelectionRow],
    *,
    session_id: str,
    config: NestedWalkForwardConfig | None = None,
    gate_config: FeatureQualityGateConfig | None = None,
    fast_tree_grid: bool = False,
) -> NestedWalkForwardArtifact:
    """Fit gates, clusters, configuration selection and predictors strictly inside folds."""

    policy = config or NestedWalkForwardConfig()
    sampled = sample_on_grid(rows, grid_seconds=policy.sampling_grid_seconds)
    folds = construct_nested_expanding_folds(sampled, config=policy)
    registry = build_registry()
    construction = FeatureConstructionResult(
        registry, sampled, {"source": "caller_supplied_constructed_rows"}
    )
    all_scores: list[CandidateScore] = []
    all_results: list[FoldModelResult] = []
    for fold in folds:
        # Inner model selection gets its own quality/reduction state.  Outer test is never in a
        # training-row index passed to either learned constructor.
        inner_gate = apply_feature_quality_gates(
            construction,
            training_row_indices=fold.inner_training_indices,
            config=gate_config,
        )
        inner_reduction = fit_correlated_feature_reduction(
            inner_gate, config=CorrelationReductionConfig(representation="representative")
        )
        inner_rows = apply_correlated_feature_reduction(inner_reduction, inner_gate.rows)
        names = tuple(cluster.cluster_id for cluster in inner_reduction.primary_map.clusters)
        train_rows = tuple(inner_rows[index].values for index in fold.inner_training_indices)
        train_targets = tuple(sampled[index].target_ticks for index in fold.inner_training_indices)
        validation_rows = tuple(inner_rows[index].values for index in fold.inner_validation_indices)
        validation_targets = tuple(
            sampled[index].target_ticks for index in fold.inner_validation_indices
        )
        fold_scores: list[CandidateScore] = []
        for model_id, raw_kind, candidate in _candidate_registry(fast_tree_grid=fast_tree_grid):
            kind = raw_kind
            model = _fit_candidate(
                kind,
                candidate,
                train_rows,
                train_targets,
                validation_rows,
                validation_targets,
                names,
            )
            predictions = predict_model(model, validation_rows).predictions
            score = float(np.mean((np.asarray(validation_targets) - np.asarray(predictions)) ** 2))
            # Inner validation selects the stopping count.  Persist that learned count in the
            # candidate record so the outer-training refit cannot silently reset to the
            # predeclared maximum and inspect no outer-test outcome to choose it.
            resolved_candidate = _resolved_candidate_config(candidate, model)
            fold_scores.append(
                CandidateScore(
                    f"{fold.fold_id}__{model_id}", kind, resolved_candidate, score
                )
            )
        all_scores.extend(fold_scores)
        selected: dict[str, CandidateScore] = {}
        for kind in ("elastic_net", "shallow_gradient_boosting"):
            selected[kind] = min(
                (item for item in fold_scores if item.model_kind == kind),
                key=lambda item: (item.validation_mse, item.model_id),
            )

        outer_gate = apply_feature_quality_gates(
            construction,
            training_row_indices=fold.outer_training_indices,
            config=gate_config,
        )
        outer_reduction = fit_correlated_feature_reduction(
            outer_gate, config=CorrelationReductionConfig(representation="representative")
        )
        outer_rows = apply_correlated_feature_reduction(outer_reduction, outer_gate.rows)
        outer_names = tuple(cluster.cluster_id for cluster in outer_reduction.primary_map.clusters)
        outer_train_rows = tuple(outer_rows[index].values for index in fold.outer_training_indices)
        outer_targets = tuple(sampled[index].target_ticks for index in fold.outer_training_indices)
        test_rows = tuple(outer_rows[index].values for index in fold.outer_test_indices)
        test_targets = tuple(sampled[index].target_ticks for index in fold.outer_test_indices)
        test_ids = tuple(
            f"{session_id}:{sampled[index].anchor_ts_ns}" for index in fold.outer_test_indices
        )

        state_names = tuple(
            name
            for name in outer_names
            if any(
                member.startswith(("price__", "book__", "regime__"))
                for member in next(
                    cluster.members
                    for cluster in outer_reduction.primary_map.clusters
                    if cluster.cluster_id == name
                )
            )
        )
        models: list[tuple[str, Mapping[str, float | int | str], PredictiveModel]] = [
            ("zero_return", {}, zero_return_baseline()),
            ("training_mean", {}, fit_training_mean_baseline(outer_targets)),
        ]
        if state_names:
            models.append(
                (
                    "simple_state",
                    {"ridge_penalty": 1e-6},
                    fit_state_linear_baseline(
                        outer_train_rows, outer_targets, state_feature_names=state_names
                    ),
                )
            )
        for selected_kind, choice in selected.items():
            narrowed_kind = cast(Literal["elastic_net", "shallow_gradient_boosting"], selected_kind)
            model = _fit_candidate(
                narrowed_kind,
                choice.config,
                outer_train_rows,
                outer_targets,
                None,
                None,
                outer_names,
            )
            resolved_model_id = choice.model_id.split("__", 1)[1]
            if narrowed_kind == "shallow_gradient_boosting":
                resolved_model_id += f"__stop{int(choice.config['maximum_estimators'])}"
            models.append((resolved_model_id, choice.config, model))
        training_mean = float(np.mean(np.asarray(outer_targets)))
        for model_id, selected_config, model in models:
            predictions = predict_model(model, test_rows).predictions
            metrics = regression_metrics(test_targets, predictions, training_mean=training_mean)
            models_payload = {
                "kind": model.model_kind,
                "config": selected_config,
                "predictions": predictions,
            }
            all_results.append(
                FoldModelResult(
                    fold.fold_id,
                    model_id,
                    model.model_kind,
                    selected_config,
                    len(outer_train_rows),
                    len(fold.inner_validation_indices),
                    len(test_rows),
                    len(outer_names),
                    len(outer_reduction.primary_map.clusters),
                    sampled[fold.outer_training_indices[-1]].anchor_ts_ns,
                    fold.outer_test_start_ts_ns,
                    metrics,
                    predictions,
                    test_ids,
                    _sha256(models_payload),
                )
            )
    return NestedWalkForwardArtifact(
        WALK_FORWARD_ARTIFACT_VERSION,
        policy,
        "exploratory_insufficient_sessions",
        1,
        len(sampled),
        sampled[0].anchor_ts_ns,
        sampled[-1].anchor_ts_ns,
        _sha256(tuple(asdict(fold) for fold in folds)),
        tuple(all_scores),
        tuple(all_results),
    )


def _regime_coverage(
    rows: Sequence[FeatureSelectionRow], indices: Sequence[int]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    volatility: set[str] = set()
    spread: set[str] = set()
    phases: set[str] = set()
    for index in indices:
        values = rows[index].feature_values
        move = values.get("regime__abs_lag_return_10s_per_sqrt_second")
        if move is not None:
            volatility.add(
                "zero"
                if move == 0.0
                else "low_le_1"
                if move <= 1.0
                else "medium_le_5"
                if move <= 5.0
                else "high_gt_5"
            )
        spread_ticks = values.get("regime__spread_ticks")
        if spread_ticks is not None:
            spread.add(
                "tight_le_1"
                if spread_ticks <= 1.0
                else "normal_le_2"
                if spread_ticks <= 2.0
                else "wide_gt_2"
            )
        minutes = values.get("regime__minutes_from_open")
        if minutes is not None:
            phases.add(
                "open_first_60m"
                if minutes < 60.0
                else "mid_session_60_300m"
                if minutes < 300.0
                else "close_after_300m"
            )
    return tuple(sorted(volatility)), tuple(sorted(spread)), tuple(sorted(phases))


def _evaluate_fold_usefulness(
    *,
    training_rows: Sequence[Mapping[str, float | None]],
    training_targets: Sequence[float],
    training_ids: Sequence[str],
    evaluation_rows: Sequence[Mapping[str, float | None]],
    evaluation_targets: Sequence[float],
    evaluation_ids: Sequence[str],
    clusters: Sequence[ImportanceClusterDefinition],
    config: ConditionalUsefulnessConfig,
) -> ConditionalUsefulnessArtifact:
    return evaluate_conditional_oos_usefulness(
        training_rows=training_rows,
        training_targets=training_targets,
        training_row_ids=training_ids,
        evaluation_rows=evaluation_rows,
        evaluation_targets=evaluation_targets,
        evaluation_row_ids=evaluation_ids,
        cluster_definitions=clusters,
        config=config,
    )


def _fit_fold_elastic_stability(
    *,
    training_rows: Sequence[Mapping[str, float | None]],
    training_targets: Sequence[float],
    clusters: Sequence[ImportanceClusterDefinition],
    config: ElasticNetStabilityConfig,
) -> ElasticNetClusterStabilityArtifact:
    return fit_cluster_elastic_net_stability(
        training_rows,
        training_targets,
        cluster_definitions=clusters,
        config=config,
    )


def build_complete_walk_forward_evidence(
    rows: Sequence[FeatureSelectionRow],
    *,
    session_id: str,
    walk_forward: NestedWalkForwardArtifact,
    gate_config: FeatureQualityGateConfig | None = None,
    importance_provider: Callable[
        [
            str,
            Literal["elastic_net", "shallow_gradient_boosting"],
            Callable[[], ConditionalUsefulnessArtifact],
        ],
        ConditionalUsefulnessArtifact,
    ]
    | None = None,
    elastic_stability_provider: Callable[
        [str, Callable[[], ElasticNetClusterStabilityArtifact]],
        ElasticNetClusterStabilityArtifact,
    ]
    | None = None,
) -> CompleteWalkForwardEvidence:
    """Run Step-5/6 evidence on the exact already-frozen Step-7 folds and configs."""

    sampled = sample_on_grid(rows, grid_seconds=walk_forward.config.sampling_grid_seconds)
    folds = construct_nested_expanding_folds(sampled, config=walk_forward.config)
    if _sha256(tuple(asdict(fold) for fold in folds)) != walk_forward.fold_fingerprint_sha256:
        raise ValueError("walk-forward fold identity changed before Step-5/6 evidence")
    construction = FeatureConstructionResult(
        build_registry(), sampled, {"source": "caller_supplied_constructed_rows"}
    )
    fold_evidence: list[FoldEmpiricalEvidence] = []
    stability_inputs: list[ClusterFoldStabilityResult] = []
    for fold in folds:
        gate = apply_feature_quality_gates(
            construction,
            training_row_indices=fold.outer_training_indices,
            config=gate_config,
        )
        reduction = fit_correlated_feature_reduction(
            gate, config=CorrelationReductionConfig(representation="representative")
        )
        raw_reduced = apply_correlated_feature_reduction(reduction, gate.rows)
        raw_clusters = importance_clusters_from_reduction(reduction)
        stable_name_by_raw = {
            cluster.cluster_id: f"cluster__{_sha256(cluster.members)[:16]}"
            for cluster in raw_clusters
        }
        clusters = tuple(
            sorted(
                (
                    ImportanceClusterDefinition(
                        stable_name_by_raw[cluster.cluster_id],
                        cluster.members,
                        (stable_name_by_raw[cluster.cluster_id],),
                        cluster.family,
                    )
                    for cluster in raw_clusters
                ),
                key=lambda item: item.cluster_id,
            )
        )
        reduced = tuple(
            {
                stable_name_by_raw[name]: value for name, value in row.values.items()
            }
            for row in raw_reduced
        )
        training_rows = tuple(reduced[index] for index in fold.outer_training_indices)
        training_targets = tuple(
            sampled[index].target_ticks for index in fold.outer_training_indices
        )
        evaluation_rows = tuple(reduced[index] for index in fold.outer_test_indices)
        evaluation_targets = tuple(sampled[index].target_ticks for index in fold.outer_test_indices)
        training_ids = tuple(
            f"{session_id}:{sampled[index].anchor_ts_ns}"
            for index in fold.outer_training_indices
        )
        evaluation_ids = tuple(
            f"{session_id}:{sampled[index].anchor_ts_ns}" for index in fold.outer_test_indices
        )
        selected = {
            item.model_kind: item
            for item in walk_forward.model_results
            if item.fold_id == fold.fold_id
            and item.model_kind in ("elastic_net", "shallow_gradient_boosting")
        }
        if set(selected) != {"elastic_net", "shallow_gradient_boosting"}:
            raise ValueError(f"missing selected predictive model for {fold.fold_id}")
        elastic_payload = selected["elastic_net"].selected_config
        tree_payload = selected["shallow_gradient_boosting"].selected_config
        elastic = ElasticNetConfig(
            alpha=float(elastic_payload["alpha"]),
            l1_ratio=float(elastic_payload["l1_ratio"]),
        )
        tree = BoostedTreeConfig(
            maximum_depth=int(tree_payload["maximum_depth"]),
            maximum_leaves=int(tree_payload["maximum_leaves"]),
            learning_rate=float(tree_payload["learning_rate"]),
            minimum_leaf_size=int(tree_payload["minimum_leaf_size"]),
            maximum_estimators=int(tree_payload["maximum_estimators"]),
            threshold_candidates=int(tree_payload["threshold_candidates"]),
            early_stopping_patience=int(tree_payload["early_stopping_patience"]),
        )
        elastic_factory = partial(
            _evaluate_fold_usefulness,
            training_rows=training_rows,
            training_targets=training_targets,
            training_ids=training_ids,
            evaluation_rows=evaluation_rows,
            evaluation_targets=evaluation_targets,
            evaluation_ids=evaluation_ids,
            clusters=clusters,
            config=ConditionalUsefulnessConfig(
                model_kind="elastic_net", elastic_net=elastic
            ),
        )
        tree_factory = partial(
            _evaluate_fold_usefulness,
            training_rows=training_rows,
            training_targets=training_targets,
            training_ids=training_ids,
            evaluation_rows=evaluation_rows,
            evaluation_targets=evaluation_targets,
            evaluation_ids=evaluation_ids,
            clusters=clusters,
            config=ConditionalUsefulnessConfig(
                model_kind="shallow_gradient_boosting", boosted_tree=tree
            ),
        )

        usefulness = (
            elastic_factory()
            if importance_provider is None
            else importance_provider(fold.fold_id, "elastic_net", elastic_factory),
            tree_factory()
            if importance_provider is None
            else importance_provider(
                fold.fold_id, "shallow_gradient_boosting", tree_factory
            ),
        )
        expected_configs = (
            ConditionalUsefulnessConfig(model_kind="elastic_net", elastic_net=elastic),
            ConditionalUsefulnessConfig(
                model_kind="shallow_gradient_boosting", boosted_tree=tree
            ),
        )
        for artifact, expected_config in zip(usefulness, expected_configs, strict=True):
            if (
                artifact.config != expected_config
                or artifact.cluster_definitions != clusters
                or artifact.training_row_ids != training_ids
                or artifact.evaluation_row_ids != evaluation_ids
                or artifact.validation_row_ids
            ):
                raise ValueError(f"Step-5 checkpoint identity changed for {fold.fold_id}")
        volatility, spread, phases = _regime_coverage(sampled, fold.outer_test_indices)
        for artifact in usefulness:
            model_id = selected[artifact.config.model_kind].model_id
            for comparison in artifact.cluster_ablation_comparisons:
                cluster = next(
                    item for item in clusters if item.cluster_id == comparison.comparison_id
                )
                stability_inputs.append(
                    ClusterFoldStabilityResult(
                        fold.fold_id,
                        model_id,
                        cluster,
                        (session_id,),
                        True,
                        comparison.delta_oos_r_squared,
                        comparison.direction,
                        volatility,
                        spread,
                        phases,
                        ((session_id, 0.0),),
                        None,
                        None,
                        comparison.support_training_rows,
                        comparison.support_evaluation_rows,
                        comparison.paired_losses.blocks,
                    )
                )
        diagnostics = tuple(
            {
                "feature_name": item.feature_name,
                "finite_count": item.finite_count,
                "training_row_count": item.training_row_count,
                "coverage": item.coverage,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "retained": item.retained,
            }
            for item in gate.training_diagnostics
        )
        stability_factory = partial(
            _fit_fold_elastic_stability,
            training_rows=training_rows,
            training_targets=training_targets,
            clusters=clusters,
            config=ElasticNetStabilityConfig(elastic_net=elastic),
        )

        elastic_stability = (
            stability_factory()
            if elastic_stability_provider is None
            else elastic_stability_provider(fold.fold_id, stability_factory)
        )
        if (
            elastic_stability.config != ElasticNetStabilityConfig(elastic_net=elastic)
            or elastic_stability.cluster_definitions != clusters
            or elastic_stability.training_row_count != len(training_rows)
        ):
            raise ValueError(f"elastic stability checkpoint identity changed for {fold.fold_id}")
        fold_evidence.append(
            FoldEmpiricalEvidence(
                fold.fold_id,
                gate.eligible_features,
                gate.excluded_features,
                dict(gate.reason_counts),
                diagnostics,
                clusters,
                volatility,
                spread,
                phases,
                usefulness,
                elastic_stability,
            )
        )
    return CompleteWalkForwardEvidence(
        tuple(fold_evidence), aggregate_cluster_stability_selection(stability_inputs)
    )


def nested_walk_forward_artifact_to_json(artifact: NestedWalkForwardArtifact) -> str:
    return json.dumps(asdict(artifact), sort_keys=True, separators=(",", ":"), allow_nan=False)


def nested_walk_forward_artifact_from_json(encoded: str) -> NestedWalkForwardArtifact:
    """Read back the compact walk-forward artifact without refitting any fold."""

    payload = cast(dict[str, Any], json.loads(encoded))
    config = NestedWalkForwardConfig(**cast(dict[str, Any], payload["config"]))
    scores = tuple(
        CandidateScore(
            str(item["model_id"]),
            cast(Literal["elastic_net", "shallow_gradient_boosting"], item["model_kind"]),
            cast(dict[str, float | int], item["config"]),
            float(item["validation_mse"]),
        )
        for item in cast(list[dict[str, Any]], payload["candidate_scores"])
    )
    results: list[FoldModelResult] = []
    for item in cast(list[dict[str, Any]], payload["model_results"]):
        metric = cast(dict[str, Any], item["metrics"])
        results.append(
            FoldModelResult(
                str(item["fold_id"]),
                str(item["model_id"]),
                cast(ModelKind, item["model_kind"]),
                cast(dict[str, float | int | str], item["selected_config"]),
                int(item["training_rows"]),
                int(item["validation_rows"]),
                int(item["test_rows"]),
                int(item["feature_count"]),
                int(item["cluster_count"]),
                int(item["training_end_ts_ns"]),
                int(item["test_start_ts_ns"]),
                RegressionMetrics(
                    int(metric["observation_count"]),
                    float(metric["mean_squared_error"]),
                    float(metric["mean_absolute_error"]),
                    None
                    if metric["r_squared_vs_zero"] is None
                    else float(metric["r_squared_vs_zero"]),
                    None
                    if metric["r_squared_vs_training_mean"] is None
                    else float(metric["r_squared_vs_training_mean"]),
                    None
                    if metric["pearson_correlation"] is None
                    else float(metric["pearson_correlation"]),
                    float(metric["directional_accuracy"]),
                ),
                tuple(float(value) for value in item["predictions"]),
                tuple(str(value) for value in item["test_row_ids"]),
                str(item["model_fingerprint_sha256"]),
            )
        )
    return NestedWalkForwardArtifact(
        str(payload["version"]),
        config,
        "exploratory_insufficient_sessions",
        int(payload["distinct_session_count"]),
        int(payload["sampled_row_count"]),
        int(payload["sampled_first_ts_ns"]),
        int(payload["sampled_last_ts_ns"]),
        str(payload["fold_fingerprint_sha256"]),
        scores,
        tuple(results),
    )


def importance_clusters_from_reduction(
    artifact: object,
) -> tuple[ImportanceClusterDefinition, ...]:
    """Build Step-5 cluster definitions without assigning evidence to members."""

    from shaurya.signals.feature_selection import CorrelatedFeatureReductionArtifact

    if not isinstance(artifact, CorrelatedFeatureReductionArtifact):
        raise TypeError("expected a correlated-feature reduction artifact")
    registry = build_registry()
    family_by_name = {item.name: item.family for item in registry.features}
    result: list[ImportanceClusterDefinition] = []
    for cluster in artifact.primary_map.clusters:
        families = tuple(sorted({family_by_name[name] for name in cluster.members}))
        family = families[0] if len(families) == 1 else "mixed:" + "+".join(families)
        result.append(
            ImportanceClusterDefinition(
                cluster.cluster_id,
                cluster.members,
                (cluster.cluster_id,),
                family,
            )
        )
    return tuple(result)
