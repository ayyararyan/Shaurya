"""Date-frozen nested walk-forward selection and outer evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import ceil, isfinite, sqrt
from types import MappingProxyType

import numpy as np

from shaurya.research.contracts import (
    EvaluationRow,
    HypothesisDefinition,
    ResearchMode,
    canonical_sha256,
)
from shaurya.research.models import fit_ridge, predict_ridge
from shaurya.signals.feature_selection import (
    ElasticNetConfig,
    fit_elastic_net,
    predict_model,
    predictive_model_to_json,
)


@dataclass(frozen=True, slots=True)
class FrozenWalkForwardFold:
    fold_id: str
    inner_training_dates: tuple[date, ...]
    inner_validation_dates: tuple[date, ...]
    outer_evaluation_dates: tuple[date, ...]
    selection_information_ts: str
    evaluation_period_start: str
    fold_hash: str
    purge_seconds: float = 300.5
    embargo_seconds: float = 300.5

    def __post_init__(self) -> None:
        if (
            not self.inner_training_dates
            or not self.inner_validation_dates
            or not self.outer_evaluation_dates
        ):
            raise ValueError("walk-forward fold partitions must be non-empty")
        partitions = (
            self.inner_training_dates,
            self.inner_validation_dates,
            self.outer_evaluation_dates,
        )
        if any(values != tuple(sorted(set(values))) for values in partitions):
            raise ValueError("walk-forward fold dates must be sorted and unique")
        if len(self.outer_evaluation_dates) != 1:
            raise ValueError("only one-session prospective outer folds are executable")
        if not (
            max(self.inner_training_dates) < min(self.inner_validation_dates)
            and max(self.inner_validation_dates) < min(self.outer_evaluation_dates)
        ):
            raise ValueError("walk-forward fold partitions must be strictly ordered")
        if any(
            set(left) & set(right)
            for index, left in enumerate(partitions)
            for right in partitions[index + 1 :]
        ):
            raise ValueError("walk-forward fold partitions must be pairwise disjoint")
        selection = datetime.fromisoformat(self.selection_information_ts)
        evaluation = datetime.fromisoformat(self.evaluation_period_start)
        if selection >= evaluation:
            raise ValueError("selection_information_ts must precede evaluation_period_start")
        if evaluation.date() != self.outer_evaluation_dates[0]:
            raise ValueError("fold evaluation timestamp and outer session date disagree")
        if set(self.inner_training_dates) & set(self.outer_evaluation_dates):
            raise ValueError("outer rows cannot enter inner training")
        if set(self.inner_validation_dates) & set(self.outer_evaluation_dates):
            raise ValueError("outer rows cannot enter inner validation")
        if self.purge_seconds < 0 or self.embargo_seconds < 0:
            raise ValueError("purge and embargo must be non-negative")
        expected = canonical_sha256(self.identity_payload())
        if self.fold_hash != expected:
            raise ValueError("fold hash does not match the frozen split")

    def identity_payload(self) -> Mapping[str, object]:
        return {
            "training": [item.isoformat() for item in self.inner_training_dates],
            "validation": [item.isoformat() for item in self.inner_validation_dates],
            "evaluation": [item.isoformat() for item in self.outer_evaluation_dates],
            "selection_information_ts": self.selection_information_ts,
            "evaluation_period_start": self.evaluation_period_start,
            "purge_seconds": self.purge_seconds,
            "embargo_seconds": self.embargo_seconds,
        }


def freeze_historical_folds(
    session_dates: Sequence[date],
    *,
    through: date,
    minimum_training_sessions: int = 5,
    validation_sessions: int = 1,
    purge_seconds: float = 300.5,
    embargo_seconds: float = 300.5,
) -> tuple[FrozenWalkForwardFold, ...]:
    """Freeze folds from dates at or before cutoff; appended future dates cannot change them."""

    dates = tuple(sorted(set(value for value in session_dates if value <= through)))
    if len(dates) <= minimum_training_sessions + validation_sessions:
        raise ValueError("insufficient historical sessions for nested walk-forward")
    folds: list[FrozenWalkForwardFold] = []
    first_outer = minimum_training_sessions + validation_sessions
    for outer_index in range(first_outer, len(dates)):
        evaluation_date = dates[outer_index]
        validation = dates[outer_index - validation_sessions : outer_index]
        training = dates[: outer_index - validation_sessions]
        evaluation_start = datetime.combine(evaluation_date, time.min, tzinfo=UTC)
        selection_ts = evaluation_start - timedelta(microseconds=1)
        payload: dict[str, object] = {
            "training": [item.isoformat() for item in training],
            "validation": [item.isoformat() for item in validation],
            "evaluation": [evaluation_date.isoformat()],
            "selection_information_ts": selection_ts.isoformat(),
            "evaluation_period_start": evaluation_start.isoformat(),
            "purge_seconds": purge_seconds,
            "embargo_seconds": embargo_seconds,
        }
        digest = canonical_sha256(payload)
        folds.append(
            FrozenWalkForwardFold(
                f"fold-{evaluation_date.isoformat()}-{digest[:8]}",
                training,
                validation,
                (evaluation_date,),
                selection_ts.isoformat(),
                evaluation_start.isoformat(),
                digest,
                purge_seconds,
                embargo_seconds,
            )
        )
    return tuple(folds)


def freeze_prospective_fold(
    historical_dates: Sequence[date],
    *,
    evaluation_date: date,
    minimum_training_sessions: int,
    validation_sessions: int = 1,
    purge_seconds: float = 300.5,
    embargo_seconds: float = 300.5,
) -> FrozenWalkForwardFold:
    """Freeze one next-session fold from dates strictly before its unseen outer session."""

    dates = tuple(sorted(set(historical_dates)))
    if any(value >= evaluation_date for value in dates):
        raise ValueError("prospective fold history must strictly precede evaluation")
    if len(dates) < minimum_training_sessions + validation_sessions:
        raise ValueError("insufficient history for the prospective nested fold")
    training = dates[:-validation_sessions]
    validation = dates[-validation_sessions:]
    evaluation_start = datetime.combine(evaluation_date, time.min, tzinfo=UTC)
    selection_ts = evaluation_start - timedelta(microseconds=1)
    payload: dict[str, object] = {
        "training": [item.isoformat() for item in training],
        "validation": [item.isoformat() for item in validation],
        "evaluation": [evaluation_date.isoformat()],
        "selection_information_ts": selection_ts.isoformat(),
        "evaluation_period_start": evaluation_start.isoformat(),
        "purge_seconds": purge_seconds,
        "embargo_seconds": embargo_seconds,
    }
    digest = canonical_sha256(payload)
    return FrozenWalkForwardFold(
        f"fold-{evaluation_date.isoformat()}-{digest[:8]}",
        training,
        validation,
        (evaluation_date,),
        selection_ts.isoformat(),
        evaluation_start.isoformat(),
        digest,
        purge_seconds,
        embargo_seconds,
    )


@dataclass(frozen=True, slots=True)
class CandidateFoldResult:
    hypothesis_id: str
    fold_id: str
    validation_score: float | None
    outer_score: float | None
    coefficient: float | None
    outer_observations: int
    selected_for_outer: bool
    training_metadata_hash: str
    model_hash: str | None
    selection_weight: float = 0.0
    effective_sample_size: float = 0.0
    economic_magnitude: float | None = None
    coefficients: tuple[tuple[str, str, float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class NestedWalkForwardResult:
    mode: ResearchMode
    folds: tuple[FrozenWalkForwardFold, ...]
    candidate_results: tuple[CandidateFoldResult, ...]
    candidate_ids: tuple[str, ...]
    result_hash: str

    def __post_init__(self) -> None:
        if not self.folds or not self.candidate_ids or not self.candidate_results:
            raise ValueError("walk-forward result cannot be empty")
        if self.candidate_ids != tuple(sorted(set(self.candidate_ids))):
            raise ValueError("walk-forward candidate universe is not canonical")
        fold_ids = tuple(fold.fold_id for fold in self.folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("walk-forward folds must be unique")
        outer_dates = tuple(date_ for fold in self.folds for date_ in fold.outer_evaluation_dates)
        if len(outer_dates) != len(set(outer_dates)):
            raise ValueError("walk-forward outer evaluation dates must be unique across folds")
        expected_pairs = {
            (fold_id, hypothesis_id)
            for fold_id in fold_ids
            for hypothesis_id in self.candidate_ids
        }
        observed_pairs = {
            (result.fold_id, result.hypothesis_id) for result in self.candidate_results
        }
        if observed_pairs != expected_pairs or len(observed_pairs) != len(self.candidate_results):
            raise ValueError("walk-forward result lacks exact fold/candidate accounting")
        payload = {
            "mode": self.mode.value,
            "folds": [asdict(fold) for fold in self.folds],
            "candidate_ids": self.candidate_ids,
            "results": [asdict(result) for result in self.candidate_results],
        }
        if canonical_sha256(payload) != self.result_hash:
            raise ValueError("walk-forward result hash is invalid")


def regime_predicates_from_policy(
    policy: Mapping[str, object],
) -> Mapping[str, Callable[[Mapping[str, float | None]], bool]]:
    """Compile only fixed, anchor-observable regime rules from the frozen policy."""

    raw_rules = policy.get("regime_rules")
    if not isinstance(raw_rules, Mapping) or raw_rules.get("causal_only") is not True:
        raise ValueError("causal regime rules are required")
    definitions = raw_rules.get("definitions")
    if not isinstance(definitions, Mapping):
        raise ValueError("regime definitions must be an object")
    predicates: dict[str, Callable[[Mapping[str, float | None]], bool]] = {}

    def always(_: Mapping[str, float | None]) -> bool:
        return True

    def threshold_predicate(
        feature_id: str, operator: str, limit: float
    ) -> Callable[[Mapping[str, float | None]], bool]:
        def predicate(values: Mapping[str, float | None]) -> bool:
            value = values.get(feature_id)
            return value is not None and (value <= limit if operator == "le" else value >= limit)

        return predicate

    for name, raw in definitions.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise ValueError("regime definition is malformed")
        strategy = raw.get("strategy")
        if strategy == "always":
            predicates[name] = always
        elif strategy == "threshold":
            feature_id = raw.get("feature_id")
            operator = raw.get("operator")
            threshold = raw.get("value")
            if (
                not isinstance(feature_id, str)
                or operator not in {"le", "ge"}
                or not isinstance(threshold, (int, float))
            ):
                raise ValueError("threshold regime definition is incomplete")
            limit = float(threshold)
            predicates[name] = threshold_predicate(feature_id, str(operator), limit)
        else:
            raise ValueError(f"unsupported regime strategy {strategy}")
    return MappingProxyType(predicates)


def _correlation(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    if len(actual) < 3:
        return None
    left = np.asarray(actual, dtype=np.float64)
    right = np.asarray(predicted, dtype=np.float64)
    if np.std(left) == 0 or np.std(right) == 0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if isfinite(value) else None


def _coefficient_standard_errors(
    rows: Sequence[Mapping[str, float | None]],
    targets: Sequence[float],
    *,
    feature_names: Sequence[str],
    predictions: Sequence[float],
    l2_penalty: float,
) -> tuple[float, ...]:
    """Model-matrix covariance for each fitted coefficient, preserving its identity."""

    names = tuple(feature_names)
    def numeric(row: Mapping[str, float | None], name: str) -> float:
        value = row.get(name)
        return np.nan if value is None else float(value)

    matrix = np.asarray(
        [[numeric(row, name) for name in names] for row in rows],
        dtype=np.float64,
    )
    medians = np.nanmedian(matrix, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    filled = np.where(np.isfinite(matrix), matrix, medians)
    scales = np.std(filled, axis=0)
    scales = np.where(scales > 0, scales, 1.0)
    design = (filled - medians) / scales
    residuals = np.asarray(targets, dtype=np.float64) - np.asarray(predictions, dtype=np.float64)
    degrees = max(1, len(targets) - len(names) - 1)
    residual_variance = float(residuals @ residuals / degrees)
    gram = design.T @ design
    inverse = np.linalg.pinv(gram + l2_penalty * np.eye(len(names)))
    covariance = residual_variance * inverse @ gram @ inverse
    return tuple(float(sqrt(max(0.0, value))) for value in np.diag(covariance))


def _eligible_rows(
    rows: Sequence[EvaluationRow],
    hypothesis: HypothesisDefinition,
    dates: set[date],
    regime_predicate: Callable[[Mapping[str, float | None]], bool],
) -> list[EvaluationRow]:
    if hypothesis.pooling_coordinate != "instrument":
        raise ValueError(
            f"unsupported registered pooling coordinate {hypothesis.pooling_coordinate}"
        )
    if hypothesis.evaluation_metric != "pearson_correlation":
        raise ValueError(f"unsupported registered evaluation metric {hypothesis.evaluation_metric}")
    if hypothesis.selection_method != "nested_past_only":
        raise ValueError(f"unsupported registered selection method {hypothesis.selection_method}")
    eligible = [
        row
        for row in rows
        if row.feature.session_date in dates
        and row.target.target_id == hypothesis.target_id
        and row.target.value is not None
        and all(
            row.feature.value_map.get(name) is not None
            for name in (*hypothesis.predictor_feature_ids, *hypothesis.conditioning_variables)
        )
        and regime_predicate(row.feature.value_map)
    ]
    eligible.sort(key=lambda row: (row.feature.session_date, row.feature.anchor_ts_ns))
    if len(dates) > hypothesis.fitting_window_sessions:
        keep_dates = set(sorted(dates)[-hypothesis.fitting_window_sessions :])
        eligible = [row for row in eligible if row.feature.session_date in keep_dates]
    if hypothesis.sampling_clock not in {"event", "calendar_1s"}:
        raise ValueError(f"unsupported registered sampling clock {hypothesis.sampling_clock}")
    if hypothesis.sampling_clock == "calendar_1s":
        buckets: dict[tuple[str, str, str, int, int, date, int], EvaluationRow] = {}
        for row in eligible:
            buckets[
                (
                    row.feature.instrument_id,
                    row.feature.channel,
                    row.feature.connection_id,
                    row.feature.connection_epoch,
                    row.feature.break_segment,
                    row.feature.session_date,
                    row.feature.anchor_ts_ns // 1_000_000_000,
                )
            ] = row
        eligible = sorted(
            buckets.values(), key=lambda row: (row.feature.session_date, row.feature.anchor_ts_ns)
        )
    cadence_ns = round(hypothesis.training_cadence_seconds * 1_000_000_000)
    sampled: list[EvaluationRow] = []
    previous_by_session: dict[tuple[str, str, str, int, int, date], int] = {}
    for row in eligible:
        partition = (
            row.feature.instrument_id,
            row.feature.channel,
            row.feature.connection_id,
            row.feature.connection_epoch,
            row.feature.break_segment,
            row.feature.session_date,
        )
        previous = previous_by_session.get(partition)
        if previous is None or row.feature.anchor_ts_ns - previous >= cadence_ns:
            sampled.append(row)
            previous_by_session[partition] = row.feature.anchor_ts_ns
    return sampled


def _score_candidate(
    hypothesis: HypothesisDefinition,
    rows: Sequence[EvaluationRow],
    fold: FrozenWalkForwardFold,
    regime_predicate: Callable[[Mapping[str, float | None]], bool],
) -> tuple[
    float | None,
    float | None,
    float | None,
    int,
    str,
    str | None,
    float,
    float | None,
    tuple[tuple[str, str, float, float], ...],
]:
    training = _eligible_rows(rows, hypothesis, set(fold.inner_training_dates), regime_predicate)
    validation = _eligible_rows(
        rows, hypothesis, set(fold.inner_validation_dates), regime_predicate
    )
    outer = _eligible_rows(rows, hypothesis, set(fold.outer_evaluation_dates), regime_predicate)
    separation_ns = round(max(fold.purge_seconds, fold.embargo_seconds) * 1_000_000_000)
    validation_boundary_ns = int(
        datetime.combine(min(fold.inner_validation_dates), time.min, tzinfo=UTC).timestamp() * 1e9
    )
    outer_boundary_ns = int(datetime.fromisoformat(fold.evaluation_period_start).timestamp() * 1e9)
    training = [
        row
        for row in training
        if row.target.interval_end_ts_ns <= validation_boundary_ns - separation_ns
    ]
    validation = [
        row
        for row in validation
        if row.target.interval_end_ts_ns <= outer_boundary_ns - separation_ns
    ]
    selection_ns = int(datetime.fromisoformat(fold.selection_information_ts).timestamp() * 1e9)
    if any(row.target.available_ts_ns > selection_ns for row in (*training, *validation)):
        raise ValueError("selection fold contains a target unavailable at selection time")
    metadata = {
        "fold": fold.fold_hash,
        "training_feature_hashes": [row.feature.feature_run_hash for row in training],
        "predictors": (
            *hypothesis.predictor_feature_ids,
            *hypothesis.conditioning_variables,
        ),
        "pooling_coordinate": hypothesis.pooling_coordinate,
    }
    metadata_hash = canonical_sha256(metadata)
    minimum = hypothesis.minimum_observations
    if len(training) < minimum or len(validation) < minimum or len(outer) < minimum:
        return None, None, None, len(outer), metadata_hash, None, 0.0, None, ()
    regularization = dict(hypothesis.regularization)
    feature_names = (*hypothesis.predictor_feature_ids, *hypothesis.conditioning_variables)

    def instrument(row: EvaluationRow) -> tuple[str, str, str, int, int]:
        return (
            row.feature.instrument_id or "__legacy_single_instrument__",
            row.feature.channel,
            row.feature.connection_id,
            row.feature.connection_epoch,
            row.feature.break_segment,
        )

    training_by_instrument: dict[tuple[str, str, str, int, int], list[EvaluationRow]] = {}
    validation_by_instrument: dict[tuple[str, str, str, int, int], list[EvaluationRow]] = {}
    outer_by_instrument: dict[tuple[str, str, str, int, int], list[EvaluationRow]] = {}
    for collection, grouped in (
        (training, training_by_instrument),
        (validation, validation_by_instrument),
        (outer, outer_by_instrument),
    ):
        for row in collection:
            grouped.setdefault(instrument(row), []).append(row)
    if not outer_by_instrument or any(
        len(training_by_instrument.get(identity, ())) < minimum
        or len(validation_by_instrument.get(identity, ())) < minimum
        or len(values) < minimum
        for identity, values in outer_by_instrument.items()
    ):
        return None, None, None, len(outer), metadata_hash, None, 0.0, None, ()
    validation_actual: list[float] = []
    validation_predictions: list[float] = []
    outer_actual: list[float] = []
    outer_predictions: list[float] = []
    outer_rows: list[EvaluationRow] = []
    model_hashes: list[tuple[str, str]] = []
    coefficients: list[float] = []
    coefficient_artifacts: list[tuple[str, str, float, float]] = []
    for identity, instrument_outer in sorted(outer_by_instrument.items()):
        instrument_training = training_by_instrument[identity]
        instrument_validation = validation_by_instrument[identity]
        training_features = [row.feature.value_map for row in instrument_training]
        training_targets = [
            float(row.target.value)
            for row in instrument_training
            if row.target.value is not None
        ]
        if hypothesis.model_class == "ridge":
            raw_penalty = regularization.get("ridge_penalty")
            if not isinstance(raw_penalty, (int, float)) or float(raw_penalty) < 0:
                raise ValueError("ridge_penalty must be non-negative and numeric")
            model = fit_ridge(
                training_features,
                training_targets,
                feature_names=feature_names,
                penalty=float(raw_penalty),
            )
            validation_prediction = predict_ridge(
                model, [row.feature.value_map for row in instrument_validation]
            )
            outer_prediction = predict_ridge(
                model, [row.feature.value_map for row in instrument_outer]
            )
            fitted_hash = canonical_sha256(asdict(model))
            fitted_coefficients = model.coefficients
            fitted_feature_names = model.feature_names
            training_predictions = predict_ridge(model, training_features)
            coefficient_errors = _coefficient_standard_errors(
                training_features,
                training_targets,
                feature_names=fitted_feature_names,
                predictions=training_predictions,
                l2_penalty=float(raw_penalty),
            )
        elif hypothesis.model_class == "elastic_net":
            raw_alpha = regularization.get("elastic_alpha")
            raw_l1_ratio = regularization.get("elastic_l1_ratio")
            if (
                not isinstance(raw_alpha, (int, float))
                or float(raw_alpha) <= 0
                or not isinstance(raw_l1_ratio, (int, float))
                or not 0 <= float(raw_l1_ratio) <= 1
            ):
                raise ValueError("elastic-net regularization is invalid")
            elastic = fit_elastic_net(
                training_features,
                training_targets,
                feature_names=feature_names,
                config=ElasticNetConfig(alpha=float(raw_alpha), l1_ratio=float(raw_l1_ratio)),
            )
            validation_prediction = predict_model(
                elastic, [row.feature.value_map for row in instrument_validation]
            ).predictions
            outer_prediction = predict_model(
                elastic, [row.feature.value_map for row in instrument_outer]
            ).predictions
            fitted_hash = canonical_sha256(predictive_model_to_json(elastic))
            fitted_coefficients = elastic.coefficients
            fitted_feature_names = elastic.transform.output_features
            training_predictions = predict_model(elastic, training_features).predictions
            coefficient_errors = _coefficient_standard_errors(
                training_features,
                training_targets,
                feature_names=fitted_feature_names,
                predictions=training_predictions,
                l2_penalty=float(raw_alpha) * (1.0 - float(raw_l1_ratio)),
            )
        else:
            raise ValueError(f"unsupported registered model class {hypothesis.model_class}")
        validation_actual.extend(
            float(row.target.value)
            for row in instrument_validation
            if row.target.value is not None
        )
        validation_predictions.extend(validation_prediction)
        outer_actual.extend(
            float(row.target.value) for row in instrument_outer if row.target.value is not None
        )
        outer_predictions.extend(outer_prediction)
        outer_rows.extend(instrument_outer)
        model_hashes.append((canonical_sha256(identity)[:16], fitted_hash))
        coefficients.extend(float(value) for value in fitted_coefficients)
        partition_label = canonical_sha256(identity)[:16]
        coefficient_artifacts.extend(
            (partition_label, feature_name, float(value), float(error))
            for feature_name, value, error in zip(
                fitted_feature_names, fitted_coefficients, coefficient_errors, strict=True
            )
        )
    model_hash = canonical_sha256(model_hashes)
    validation_score = _correlation(
        validation_actual,
        validation_predictions,
    )
    outer_score = _correlation(outer_actual, outer_predictions)
    coefficient = coefficients[0] if len(coefficients) == 1 else None
    effective_sample_size = _dependence_aware_effective_size(
        outer_rows,
        outer_actual,
        outer_predictions,
        maximum_lag=max(
            1,
            ceil(hypothesis.target_horizon_seconds / hypothesis.training_cadence_seconds),
        ),
    )
    economic_values = [
        abs(prediction) * float(row.feature.reference_midpoint) / float(row.feature.spread_price)
        for row, prediction in zip(outer_rows, outer_predictions, strict=True)
        if row.feature.reference_midpoint is not None
        and row.feature.tick_size is not None
        and row.feature.spread_price is not None
    ]
    economic_magnitude = (
        sum(economic_values) / len(economic_values) if economic_values else None
    )
    return (
        validation_score,
        outer_score,
        coefficient,
        len(outer),
        metadata_hash,
        model_hash,
        effective_sample_size,
        economic_magnitude,
        tuple(sorted(coefficient_artifacts)),
    )


def _dependence_aware_effective_size(
    rows: Sequence[EvaluationRow],
    actual: Sequence[float],
    predicted: Sequence[float],
    *,
    maximum_lag: int,
) -> float:
    count = min(len(actual), len(predicted))
    if count != len(rows) or count < 3:
        return float(count)
    grouped: dict[tuple[date, str, str, str, int, int], list[tuple[float, float]]] = {}
    for row, actual_value, predicted_value in zip(rows, actual, predicted, strict=True):
        key = (
            row.feature.session_date,
            row.feature.instrument_id,
            row.feature.channel,
            row.feature.connection_id,
            row.feature.connection_epoch,
            row.feature.break_segment,
        )
        grouped.setdefault(key, []).append((actual_value, predicted_value))
    total = 0.0
    for values in grouped.values():
        left_values = np.asarray([item[0] for item in values], dtype=np.float64)
        right_values = np.asarray([item[1] for item in values], dtype=np.float64)
        contribution = (left_values - left_values.mean()) * (
            right_values - right_values.mean()
        )
        usable_lag = min(maximum_lag, len(values) - 1)
        penalty = 1.0
        for lag in range(1, usable_lag + 1):
            before, after = contribution[:-lag], contribution[lag:]
            if np.std(before) == 0 or np.std(after) == 0:
                continue
            rho = float(np.corrcoef(before, after)[0, 1])
            if isfinite(rho):
                penalty += 2.0 * (1.0 - lag / (usable_lag + 1)) * max(0.0, rho)
        total += max(1.0, min(float(len(values)), len(values) / penalty))
    return min(float(count), total)


def run_nested_walk_forward(
    rows: Sequence[EvaluationRow],
    hypotheses: Sequence[HypothesisDefinition],
    folds: Sequence[FrozenWalkForwardFold],
    *,
    mode: ResearchMode,
    regime_predicates: Mapping[str, Callable[[Mapping[str, float | None]], bool]] | None = None,
) -> NestedWalkForwardResult:
    """Score all candidates; validation may select, outer outcomes may only evaluate."""

    if not rows or not hypotheses or not folds:
        raise ValueError("nested walk-forward requires non-empty rows, candidates, and folds")
    if len({row.feature.registry_version for row in rows}) > 1:
        raise ValueError("walk-forward rows mix feature registry versions")
    if len({row.target.registry_version for row in rows}) > 1:
        raise ValueError("walk-forward rows mix target registry versions")
    candidate_ids = tuple(sorted(hypothesis.hypothesis_id for hypothesis in hypotheses))
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("duplicate semantic hypotheses cannot enter one experiment")
    by_id = {hypothesis.hypothesis_id: hypothesis for hypothesis in hypotheses}
    predicates = dict(regime_predicates or {"global": lambda _: True})
    missing_regimes = {hypothesis.admissible_regime for hypothesis in hypotheses} - set(predicates)
    if missing_regimes:
        raise ValueError(f"missing predeclared causal regime predicates: {sorted(missing_regimes)}")
    results: list[CandidateFoldResult] = []
    for fold in folds:
        if canonical_sha256(fold.identity_payload()) != fold.fold_hash:
            raise ValueError("forged walk-forward fold hash")
        evaluation_date = min(fold.outer_evaluation_dates)
        if any(hypothesis.first_registration_date >= evaluation_date for hypothesis in hypotheses):
            raise ValueError("hypothesis registration must precede every OOS session")
        scored: list[
            tuple[
                str,
                tuple[
                    float | None,
                    float | None,
                    float | None,
                    int,
                    str,
                    str | None,
                    float,
                    float | None,
                    tuple[tuple[str, str, float, float], ...],
                ],
            ]
        ] = []
        for hypothesis_id in candidate_ids:
            hypothesis = by_id[hypothesis_id]
            scored.append(
                (
                    hypothesis_id,
                    _score_candidate(
                        hypothesis,
                        rows,
                        fold,
                        predicates[hypothesis.admissible_regime],
                    ),
                )
            )
        selectable = [
            (hypothesis_id, abs(float(values[0])))
            for hypothesis_id, values in scored
            if values[0] is not None
        ]
        weights: dict[str, float] = {}
        if selectable:
            # Registered negative controls traverse the identical selector, but in their own
            # diagnostic family so a chance control score cannot suppress real-alpha candidates.
            selection_groups = (
                [
                    item
                    for item in selectable
                    if not by_id[item[0]].family.upper().startswith("NEGATIVE_CONTROL")
                ],
                [
                    item
                    for item in selectable
                    if by_id[item[0]].family.upper().startswith("NEGATIVE_CONTROL")
                ],
            )
            for group in selection_groups:
                if not group:
                    continue
                best = max(score for _, score in group)
                region = [
                    (identity, score)
                    for identity, score in group
                    if score >= best * (1 - by_id[identity].selection_threshold)
                ]
                total = sum(score for _, score in region)
                weights.update(
                    {
                        identity: (score / total if total > 0 else 1.0 / len(region))
                        for identity, score in region
                    }
                )
        for hypothesis_id, values in scored:
            (
                validation,
                outer,
                coefficient,
                support,
                metadata_hash,
                model_hash,
                effective_sample_size,
                economic_magnitude,
                coefficients,
            ) = values
            results.append(
                CandidateFoldResult(
                    hypothesis_id,
                    fold.fold_id,
                    validation,
                    outer,
                    coefficient,
                    support,
                    hypothesis_id in weights,
                    metadata_hash,
                    model_hash,
                    weights.get(hypothesis_id, 0.0),
                    effective_sample_size,
                    economic_magnitude,
                    coefficients,
                )
            )
    payload = {
        "mode": mode.value,
        "folds": [asdict(fold) for fold in folds],
        "candidate_ids": candidate_ids,
        "results": [asdict(result) for result in results],
    }
    return NestedWalkForwardResult(
        mode, tuple(folds), tuple(results), candidate_ids, canonical_sha256(payload)
    )
