"""Content-verified scientific artifacts used by daily evidence publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from shaurya.research.contracts import ExperimentStatus, HypothesisDefinition, canonical_sha256
from shaurya.research.multiplicity import CandidateBootstrapArtifact
from shaurya.research.nulls import NestedEmpiricalNullResult
from shaurya.research.surfaces import (
    PredictiveSurface,
    SurfaceRobustness,
    candidate_local_robustness,
    validate_surface_artifacts,
)
from shaurya.research.walkforward import CandidateFoldResult, NestedWalkForwardResult


@dataclass(frozen=True, slots=True)
class CandidateGateArtifact:
    hypothesis_id: str
    fold_hash: str
    validation_score: float | None
    score: float | None
    coefficient: float | None
    observations: int
    effective_sample_size: float
    economic_magnitude: float | None
    local_robustness: float
    empirical_null_p_value: float
    adjusted_p_value: float
    model_hash: str | None
    selected_for_outer: bool
    coefficients: tuple[tuple[str, str, float, float], ...]
    observation_gate_pass: bool
    effective_sample_size_gate_pass: bool
    neighborhood_gate_pass: bool
    score_gate_pass: bool
    economic_gate_pass: bool
    regime_comparison_pass: bool
    block_bootstrap_hash: str
    block_bootstrap_estimate: float | None
    block_bootstrap_lower: float | None
    block_bootstrap_upper: float | None
    block_bootstrap_standard_error: float | None
    block_bootstrap_gate_pass: bool
    terminal_status: ExperimentStatus
    terminal_reason: str | None
    gate_hash: str = ""

    def with_hash(self) -> CandidateGateArtifact:
        payload = asdict(self)
        payload["gate_hash"] = ""
        return CandidateGateArtifact(**{**payload, "gate_hash": canonical_sha256(payload)})

    def __post_init__(self) -> None:
        if len(self.block_bootstrap_hash) != 64:
            raise ValueError("candidate gate requires a bound block-bootstrap artifact")
        if self.block_bootstrap_gate_pass and self.block_bootstrap_estimate is None:
            raise ValueError("passing block-bootstrap gate requires an interval")
        if self.gate_hash:
            payload = asdict(self)
            payload["gate_hash"] = ""
            if canonical_sha256(payload) != self.gate_hash:
                raise ValueError("candidate gate artifact hash is invalid")
        if self.terminal_status is ExperimentStatus.COMPLETED:
            if not self.selected_for_outer:
                raise ValueError("unselected nested candidate cannot publish confirmatory evidence")
            if not self.observation_gate_pass or not self.effective_sample_size_gate_pass:
                raise ValueError("completed gate artifact lacks required statistical support")
            if self.score is None or self.model_hash is None or self.terminal_reason is not None:
                raise ValueError("completed gate artifact lacks a fitted OOS result")
        elif not self.terminal_reason:
            raise ValueError("non-completed gate artifact requires an exact reason")


def candidate_gate_from_mapping(raw: Mapping[str, Any]) -> CandidateGateArtifact:
    return CandidateGateArtifact(
        hypothesis_id=str(raw["hypothesis_id"]),
        fold_hash=str(raw["fold_hash"]),
        validation_score=(
            None if raw["validation_score"] is None else float(raw["validation_score"])
        ),
        score=None if raw["score"] is None else float(raw["score"]),
        coefficient=None if raw["coefficient"] is None else float(raw["coefficient"]),
        observations=int(raw["observations"]),
        effective_sample_size=float(raw["effective_sample_size"]),
        economic_magnitude=(
            None if raw["economic_magnitude"] is None else float(raw["economic_magnitude"])
        ),
        local_robustness=float(raw["local_robustness"]),
        empirical_null_p_value=float(raw["empirical_null_p_value"]),
        adjusted_p_value=float(raw["adjusted_p_value"]),
        model_hash=None if raw["model_hash"] is None else str(raw["model_hash"]),
        selected_for_outer=bool(raw["selected_for_outer"]),
        coefficients=tuple(
            (str(item[0]), str(item[1]), float(item[2]), float(item[3]))
            for item in raw["coefficients"]
        ),
        observation_gate_pass=bool(raw["observation_gate_pass"]),
        effective_sample_size_gate_pass=bool(raw["effective_sample_size_gate_pass"]),
        neighborhood_gate_pass=bool(raw["neighborhood_gate_pass"]),
        score_gate_pass=bool(raw["score_gate_pass"]),
        economic_gate_pass=bool(raw["economic_gate_pass"]),
        regime_comparison_pass=bool(raw["regime_comparison_pass"]),
        block_bootstrap_hash=str(raw["block_bootstrap_hash"]),
        block_bootstrap_estimate=(
            None
            if raw["block_bootstrap_estimate"] is None
            else float(raw["block_bootstrap_estimate"])
        ),
        block_bootstrap_lower=(
            None if raw["block_bootstrap_lower"] is None else float(raw["block_bootstrap_lower"])
        ),
        block_bootstrap_upper=(
            None if raw["block_bootstrap_upper"] is None else float(raw["block_bootstrap_upper"])
        ),
        block_bootstrap_standard_error=(
            None
            if raw["block_bootstrap_standard_error"] is None
            else float(raw["block_bootstrap_standard_error"])
        ),
        block_bootstrap_gate_pass=bool(raw["block_bootstrap_gate_pass"]),
        terminal_status=ExperimentStatus(str(raw["terminal_status"])),
        terminal_reason=(
            None if raw["terminal_reason"] is None else str(raw["terminal_reason"])
        ),
        gate_hash=str(raw["gate_hash"]),
    )


def build_candidate_gate_artifacts(
    *,
    hypotheses: Sequence[HypothesisDefinition],
    walkforward: NestedWalkForwardResult,
    empirical_null: NestedEmpiricalNullResult,
    adjusted_p_values: Mapping[str, float],
    surfaces: Mapping[str, tuple[PredictiveSurface, SurfaceRobustness]],
    block_bootstrap: Mapping[str, CandidateBootstrapArtifact],
    policy: Mapping[str, object],
) -> tuple[CandidateGateArtifact, ...]:
    """Recompute candidate-local gates exclusively from verified scientific artifacts."""

    candidate_ids = walkforward.candidate_ids
    by_hypothesis = {item.hypothesis_id: item for item in hypotheses}
    if tuple(sorted(by_hypothesis)) != candidate_ids:
        raise ValueError("gate hypotheses do not exactly cover the walk-forward universe")
    if empirical_null.candidate_ids != candidate_ids:
        raise ValueError("gate null universe differs from the walk-forward universe")
    if empirical_null.observed_walkforward_hash != walkforward.result_hash:
        raise ValueError("gate null evidence is not bound to the observed walk-forward")
    if tuple(sorted(adjusted_p_values)) != candidate_ids:
        raise ValueError("adjusted p-values do not exactly cover the candidate universe")
    if tuple(sorted(block_bootstrap)) != candidate_ids:
        raise ValueError("block-bootstrap evidence does not exactly cover the candidate universe")
    if not surfaces:
        raise ValueError("candidate gates require a non-empty predictive surface")
    local_values: dict[str, float] = {}
    for surface, robustness in surfaces.values():
        validate_surface_artifacts(surface, robustness)
        for identity, value in candidate_local_robustness(surface):
            if identity in local_values:
                raise ValueError("a candidate occurs in more than one predictive surface")
            local_values[identity] = value
    if tuple(sorted(local_values)) != candidate_ids:
        raise ValueError("predictive surfaces do not exactly cover the candidate universe")
    final_fold = walkforward.folds[-1]
    final_results = {
        item.hypothesis_id: item
        for item in walkforward.candidate_results
        if item.fold_id == final_fold.fold_id
    }
    if tuple(sorted(final_results)) != candidate_ids:
        raise ValueError("final fold does not exactly cover the candidate universe")
    empirical = dict(empirical_null.candidate_adjusted_p_values)
    promotion = policy.get("promotion")
    if not isinstance(promotion, Mapping):
        raise ValueError("candidate gates require the frozen promotion policy")
    minimum_neighbor = float(promotion.get("minimum_neighbor_robustness", -1))
    minimum_abs_score = float(promotion.get("minimum_abs_score", -1))
    if minimum_neighbor < 0 or minimum_abs_score < 0:
        raise ValueError("candidate gate policy thresholds are invalid")
    regime_rules = policy.get("regime_rules")
    if not isinstance(regime_rules, Mapping):
        raise ValueError("candidate gates require the frozen regime policy")
    minimum_bucket = int(regime_rules.get("minimum_bucket_observations", 0))
    if minimum_bucket < 1:
        raise ValueError("regime minimum bucket observations must be positive")

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

    global_scores = {
        counterpart_key(item): final_results[item.hypothesis_id].outer_score
        for item in hypotheses
        if item.admissible_regime == "global"
    }

    def build(
        identity: str, result: CandidateFoldResult, hypothesis: HypothesisDefinition
    ) -> CandidateGateArtifact:
        observation_pass = result.outer_observations >= hypothesis.minimum_observations
        neff_pass = result.effective_sample_size >= hypothesis.minimum_effective_sample_size
        local = local_values[identity]
        neighborhood_pass = local >= minimum_neighbor
        score_pass = result.outer_score is not None and abs(result.outer_score) >= minimum_abs_score
        economic_pass = hypothesis.transaction_cost_relevance == "diagnostic_only" or (
            result.economic_magnitude is not None
            and result.economic_magnitude >= 1.0
        )
        global_score = global_scores.get(counterpart_key(hypothesis))
        regime_pass = hypothesis.admissible_regime == "global" or (
            result.outer_score is not None
            and global_score is not None
            and result.outer_observations >= minimum_bucket
            and result.outer_score > global_score
        )
        bootstrap = block_bootstrap[identity]
        if bootstrap.hypothesis_id != identity or not bootstrap.bootstrap_hash:
            raise ValueError("candidate bootstrap evidence is not identity-bound")
        negative_control = hypothesis.family.upper().startswith("NEGATIVE_CONTROL")
        if negative_control:
            score_pass = False
            economic_pass = False
            regime_pass = False
        fitted = result.model_hash is not None and result.outer_score is not None
        completed = result.selected_for_outer and fitted and observation_pass and neff_pass
        reason = None
        if not completed:
            failed = []
            if not result.selected_for_outer:
                failed.append("not_selected_by_nested_validation")
            if not fitted:
                failed.append("fitted_oos_result")
            if not observation_pass:
                failed.append("registered_observation_support")
            if not neff_pass:
                failed.append("registered_effective_sample_size")
            reason = "insufficient:" + ",".join(failed)
        return CandidateGateArtifact(
            identity,
            final_fold.fold_hash,
            result.validation_score,
            result.outer_score,
            result.coefficient,
            result.outer_observations,
            result.effective_sample_size,
            result.economic_magnitude,
            local,
            empirical[identity],
            adjusted_p_values[identity],
            result.model_hash,
            result.selected_for_outer,
            result.coefficients,
            observation_pass,
            neff_pass,
            neighborhood_pass,
            score_pass,
            economic_pass,
            regime_pass,
            bootstrap.bootstrap_hash,
            bootstrap.estimate,
            bootstrap.lower,
            bootstrap.upper,
            bootstrap.standard_error,
            bootstrap.gate_pass,
            ExperimentStatus.COMPLETED if completed else ExperimentStatus.SKIPPED,
            reason,
        ).with_hash()

    return tuple(
        build(identity, final_results[identity], by_hypothesis[identity])
        for identity in candidate_ids
    )
