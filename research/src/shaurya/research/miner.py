"""Complete-universe fitted mining procedures."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from random import Random

import numpy as np

from shaurya.research.contracts import (
    EvaluationRow,
    HypothesisDefinition,
    ResearchMode,
    canonical_sha256,
)
from shaurya.research.models import fit_ridge, predict_ridge
from shaurya.research.nulls import MinerRefitResult, nested_walkforward_empirical_null
from shaurya.research.source import DerivedResearchDataset
from shaurya.research.walkforward import freeze_historical_folds
from shaurya.signals.feature_selection import (
    ElasticNetConfig,
    fit_elastic_net,
    predict_model,
    predictive_model_to_json,
)


@dataclass(frozen=True, slots=True)
class RegisteredRidgeMiner:
    """A deterministic reference miner that genuinely refits each registered atom."""

    hypotheses: tuple[HypothesisDefinition, ...]
    training_fraction: float = 0.7

    def __post_init__(self) -> None:
        ids = tuple(item.hypothesis_id for item in self.hypotheses)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("miner hypotheses must be sorted and semantically unique")
        if not 0.5 <= self.training_fraction < 1:
            raise ValueError("training fraction must lie in [0.5,1)")

    def refit_select_score(
        self,
        feature_rows: Sequence[Mapping[str, float | None]],
        targets: Sequence[float],
        *,
        replicate_id: str,
    ) -> MinerRefitResult:
        if len(feature_rows) != len(targets) or len(targets) < 6:
            raise ValueError("aligned feature rows and sufficient targets are required")
        if any(not isfinite(value) for value in targets):
            raise ValueError("miner targets must be finite")
        split = max(3, min(len(targets) - 3, int(len(targets) * self.training_fraction)))
        training_rows = feature_rows[:split]
        evaluation_rows = feature_rows[split:]
        training_targets = targets[:split]
        evaluation_targets = np.asarray(targets[split:], dtype=np.float64)
        scores: list[tuple[str, float]] = []
        models: list[tuple[str, str]] = []
        preprocessing: list[tuple[str, object]] = []
        for hypothesis in self.hypotheses:
            penalty_raw = dict(hypothesis.regularization).get("ridge_penalty", 1.0)
            if not isinstance(penalty_raw, (int, float)):
                raise ValueError("registered ridge penalty must be numeric")
            model = fit_ridge(
                training_rows,
                training_targets,
                feature_names=hypothesis.predictor_feature_ids,
                penalty=float(penalty_raw),
            )
            predictions = np.asarray(predict_ridge(model, evaluation_rows), dtype=np.float64)
            if np.std(predictions) == 0 or np.std(evaluation_targets) == 0:
                score = 0.0
            else:
                score = float(np.corrcoef(predictions, evaluation_targets)[0, 1])
            if not isfinite(score):
                raise ValueError("fitted miner produced a nonfinite score")
            scores.append((hypothesis.hypothesis_id, score))
            models.append((hypothesis.hypothesis_id, canonical_sha256(asdict(model))))
            preprocessing.append(
                (hypothesis.hypothesis_id, (model.means, model.scales, model.feature_names))
            )
        score_tuple = tuple(scores)
        best = max(abs(score) for _, score in score_tuple)
        selected = tuple(
            identity
            for identity, score in score_tuple
            if abs(score)
            >= best
            * (
                1
                - dict((h.hypothesis_id, h.selection_threshold) for h in self.hypotheses)[identity]
            )
        )
        return MinerRefitResult(
            scores=score_tuple,
            feature_matrix_hash=canonical_sha256(feature_rows),
            fitted_target_hash=canonical_sha256(targets),
            preprocessing_hash=canonical_sha256(preprocessing),
            selection_hash=canonical_sha256(
                {"replicate_id": replicate_id, "scores": score_tuple, "selected_region": selected}
            ),
            model_hashes=tuple(models),
        )


@dataclass(frozen=True, slots=True)
class SourceBoundMiningResult:
    candidate_ids: tuple[str, ...]
    observed_scores: tuple[tuple[str, float], ...]
    adjusted_empirical_p_values: tuple[tuple[str, float], ...]
    null_best_discoveries: tuple[float, ...]
    observed_phase_hash: str
    null_phase_hashes: tuple[str, ...]
    source_derivation_hash: str
    plan_hash: str
    registry_fingerprints: tuple[tuple[str, str], ...]
    complete_miner_rerun: bool
    candidate_terminal_statuses: tuple[tuple[str, str, str | None], ...]
    result_hash: str


def _clocked_rows(
    rows: Sequence[EvaluationRow], hypothesis: HypothesisDefinition
) -> list[EvaluationRow]:
    if hypothesis.pooling_coordinate != "instrument":
        raise ValueError(f"unsupported pooling coordinate {hypothesis.pooling_coordinate}")
    if hypothesis.evaluation_metric != "pearson_correlation":
        raise ValueError(f"unsupported evaluation metric {hypothesis.evaluation_metric}")
    if hypothesis.selection_method != "nested_past_only":
        raise ValueError(f"unsupported selection method {hypothesis.selection_method}")
    eligible = [
        row
        for row in rows
        if row.target.target_id == hypothesis.target_id
        and row.target.value is not None
        and all(
            row.feature.value_map.get(name) is not None for name in hypothesis.predictor_feature_ids
        )
    ]
    eligible.sort(key=lambda row: (row.feature.session_date, row.feature.anchor_ts_ns))
    dates = sorted({row.feature.session_date for row in eligible})
    if len(dates) > hypothesis.fitting_window_sessions:
        keep = set(dates[-hypothesis.fitting_window_sessions :])
        eligible = [row for row in eligible if row.feature.session_date in keep]
    if hypothesis.sampling_clock == "calendar_1s":
        buckets: dict[tuple[str, int], EvaluationRow] = {}
        for row in eligible:
            source_bucket = row.feature.observation_id.rsplit(":", 1)[0]
            buckets[(source_bucket, row.feature.anchor_ts_ns // 1_000_000_000)] = row
        eligible = sorted(
            buckets.values(), key=lambda row: (row.feature.session_date, row.feature.anchor_ts_ns)
        )
    elif hypothesis.sampling_clock != "event":
        raise ValueError(f"unsupported sampling clock {hypothesis.sampling_clock}")
    cadence_ns = round(hypothesis.training_cadence_seconds * 1_000_000_000)
    sampled: list[EvaluationRow] = []
    previous: dict[str, int] = {}
    for row in eligible:
        source = row.feature.source_dataset_id
        prior = previous.get(source)
        if prior is None or row.feature.anchor_ts_ns - prior >= cadence_ns:
            sampled.append(row)
            previous[source] = row.feature.anchor_ts_ns
    return sampled


def _correlation(actual: Sequence[float], predicted: Sequence[float]) -> float:
    left = np.asarray(actual, dtype=np.float64)
    right = np.asarray(predicted, dtype=np.float64)
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return 0.0
    value = float(np.corrcoef(left, right)[0, 1])
    return value if isfinite(value) else 0.0


def _fit_score(
    hypothesis: HypothesisDefinition,
    rows: Sequence[EvaluationRow],
    targets: Mapping[tuple[str, str], float],
    regime: Callable[[Mapping[str, float | None]], bool],
) -> tuple[float, str, str]:
    eligible = [row for row in _clocked_rows(rows, hypothesis) if regime(row.feature.value_map)]
    if len(eligible) < max(6, hypothesis.minimum_observations):
        return 0.0, canonical_sha256({"insufficient": len(eligible)}), canonical_sha256(())
    split = max(3, min(len(eligible) - 3, int(0.7 * len(eligible))))
    training = eligible[:split]
    testing = eligible[split:]
    training_targets = [
        targets[(row.feature.observation_id, row.target.target_id)] for row in training
    ]
    testing_targets = [
        targets[(row.feature.observation_id, row.target.target_id)] for row in testing
    ]
    regularization = dict(hypothesis.regularization)
    training_features = [row.feature.value_map for row in training]
    testing_features = [row.feature.value_map for row in testing]
    if hypothesis.model_class == "ridge":
        penalty = regularization.get("ridge_penalty", 1.0)
        if not isinstance(penalty, (int, float)):
            raise ValueError("ridge penalty must be numeric")
        ridge = fit_ridge(
            training_features,
            training_targets,
            feature_names=hypothesis.predictor_feature_ids,
            penalty=float(penalty),
        )
        predictions = predict_ridge(ridge, testing_features)
        model_hash = canonical_sha256(asdict(ridge))
    elif hypothesis.model_class == "elastic_net":
        alpha = regularization.get("elastic_alpha", 0.01)
        l1_ratio = regularization.get("elastic_l1_ratio", 0.5)
        if not isinstance(alpha, (int, float)) or not isinstance(l1_ratio, (int, float)):
            raise ValueError("elastic-net settings must be numeric")
        elastic = fit_elastic_net(
            training_features,
            training_targets,
            feature_names=hypothesis.predictor_feature_ids,
            config=ElasticNetConfig(alpha=float(alpha), l1_ratio=float(l1_ratio)),
        )
        predictions = predict_model(elastic, testing_features).predictions
        model_hash = canonical_sha256(predictive_model_to_json(elastic))
    else:
        raise ValueError(f"unsupported registered model {hypothesis.model_class}")
    phase_hash = canonical_sha256(
        {
            "hypothesis": hypothesis.semantic_payload(),
            "training_features": [row.feature.feature_run_hash for row in training],
            "testing_features": [row.feature.feature_run_hash for row in testing],
            "targets": training_targets,
            "model_hash": model_hash,
        }
    )
    return _correlation(testing_targets, predictions), model_hash, phase_hash


def _target_values(dataset: DerivedResearchDataset) -> dict[tuple[str, str], float]:
    return {
        (row.feature.observation_id, row.target.target_id): float(row.target.value)
        for row in dataset.rows
        if row.target.value is not None
    }


def _session_circular_null(
    dataset: DerivedResearchDataset,
    observed: Mapping[tuple[str, str], float],
    *,
    generator: Random,
    minimum_shift: int,
) -> dict[tuple[str, str], float]:
    groups: dict[tuple[object, str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in dataset.rows:
        key = (row.feature.observation_id, row.target.target_id)
        if key in observed:
            groups[
                (row.feature.session_date, row.feature.source_dataset_id, row.target.target_id)
            ].append(key)
    result = dict(observed)
    for keys in groups.values():
        if len(keys) < 2 * minimum_shift + 1:
            offset = max(1, len(keys) // 2)
        else:
            offset = generator.randrange(minimum_shift, len(keys) - minimum_shift + 1)
        values = [observed[key] for key in keys]
        shifted = values[offset:] + values[:offset]
        result.update(zip(keys, shifted, strict=True))
    return result


def run_source_bound_mining(
    dataset: DerivedResearchDataset,
    hypotheses: tuple[HypothesisDefinition, ...],
    *,
    policy: Mapping[str, object],
    plan_hash: str,
    registry_fingerprints: tuple[tuple[str, str], ...],
) -> SourceBoundMiningResult:
    """Run genuine session-frozen nested mining and the exact registered null procedure."""

    ids = tuple(item.hypothesis_id for item in hypotheses)
    if ids != tuple(sorted(ids)) or not ids or len(ids) != len(set(ids)):
        raise ValueError("miner requires the exact sorted semantic candidate universe")
    validation = policy.get("validation")
    outer = policy.get("outer_test")
    if not isinstance(validation, Mapping) or not isinstance(outer, Mapping):
        raise ValueError("nested mining policy is incomplete")
    session_dates = tuple(item.trading_date for item in dataset.sources)
    folds = freeze_historical_folds(
        session_dates,
        through=max(session_dates),
        minimum_training_sessions=int(validation["minimum_inner_sessions"]),
        validation_sessions=1,
        purge_seconds=float(outer["purge_seconds"]),
        embargo_seconds=float(outer["embargo_seconds"]),
    )
    observed, empirical = nested_walkforward_empirical_null(
        dataset,
        hypotheses,
        folds,
        policy=policy,
        mode=ResearchMode.EXPLORATORY,
    )
    statuses: list[tuple[str, str, str | None]] = []
    by_id = {item.hypothesis_id: item for item in hypotheses}
    for identity in ids:
        completed = [
            item
            for item in observed.candidate_results
            if item.hypothesis_id == identity
            and item.selected_for_outer
            and item.outer_score is not None
            and item.model_hash is not None
            and item.effective_sample_size
            >= by_id[identity].minimum_effective_sample_size
        ]
        statuses.append(
            (
                identity,
                "completed" if completed else "skipped",
                None if completed else "insufficient_registered_support",
            )
        )
    payload = {
        "candidate_ids": ids,
        "observed_scores": empirical.observed_scores,
        "adjusted_empirical_p_values": empirical.candidate_adjusted_p_values,
        "null_best_discoveries": empirical.null_best_discoveries,
        "observed_phase_hash": observed.result_hash,
        "null_phase_hashes": empirical.replicate_walkforward_hashes,
        "source_derivation_hash": dataset.derivation_hash,
        "plan_hash": plan_hash,
        "registry_fingerprints": registry_fingerprints,
        "complete_miner_rerun": True,
        "candidate_terminal_statuses": statuses,
    }
    return SourceBoundMiningResult(
        ids,
        empirical.observed_scores,
        empirical.candidate_adjusted_p_values,
        empirical.null_best_discoveries,
        observed.result_hash,
        empirical.replicate_walkforward_hashes,
        dataset.derivation_hash,
        plan_hash,
        registry_fingerprints,
        True,
        tuple(statuses),
        canonical_sha256(payload),
    )
