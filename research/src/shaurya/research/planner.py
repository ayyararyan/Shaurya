"""Pre-outcome search-space accounting and compute planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from shaurya.research.contracts import canonical_sha256
from shaurya.research.registry import (
    FrozenRegistry,
    declared_feature_ids,
    declared_target_ids,
    expand_hypotheses,
    registry_by_version,
)


@dataclass(frozen=True, slots=True)
class AlphaPlan:
    through: date
    feature_registry_version: str
    target_registry_version: str
    hypothesis_registry_version: str
    policy_registry_version: str
    predictor_specifications: int
    target_specifications: int
    horizons: int
    regime_conditions: int
    models: int
    interactions: int
    sampling_clocks: int
    pooling_coordinates: int
    fitting_windows: int
    training_cadences: int
    selection_methods: int
    total_raw_hypothesis_count: int
    total_effective_hypothesis_count: int
    effective_family_count: int
    excluded_before_target_inspection: tuple[dict[str, str], ...]
    estimated_model_fits_per_outer_fold: int
    registry_fingerprints: tuple[tuple[str, str], ...]
    eligible_hypothesis_ids: tuple[str, ...]
    plan_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_hash(self) -> AlphaPlan:
        payload = asdict(self)
        payload["plan_hash"] = ""
        return replace(self, plan_hash=canonical_sha256(payload))


def _policy_values(policy: FrozenRegistry, key: str) -> set[str]:
    raw = policy.payload.get(key)
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"policy {key} must be a list")
    return {str(value) for value in raw}


def _require_policy_mapping(policy: FrozenRegistry, key: str) -> Mapping[str, Any]:
    value = policy.payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"policy {key} must be an object")
    return value


def _validate_nested_policy(policy: FrozenRegistry) -> None:
    validation = _require_policy_mapping(policy, "validation")
    outer = _require_policy_mapping(policy, "outer_test")
    multiplicity = _require_policy_mapping(policy, "multiplicity")
    promotion = _require_policy_mapping(policy, "promotion")
    decay = _require_policy_mapping(policy, "decay")
    reactivation = _require_policy_mapping(policy, "reactivation")
    nulls = _require_policy_mapping(policy, "null_simulation")
    regimes = _require_policy_mapping(policy, "regime_rules")
    robustness = _require_policy_mapping(policy, "robustness")
    minimum = _require_policy_mapping(policy, "minimum_evidence")
    if (
        validation.get("scheme") != "expanding"
        or int(validation.get("minimum_inner_sessions", 0)) < 2
    ):
        raise ValueError("policy validation scheme is unsupported")
    if int(outer.get("sessions_per_block", 0)) != 1:
        raise ValueError("only one-session prospective outer blocks are executable")
    if float(outer.get("purge_seconds", -1)) < 0 or float(outer.get("embargo_seconds", -1)) < 0:
        raise ValueError("purge and embargo must be non-negative")
    if multiplicity.get("method") not in {"benjamini_hochberg", "benjamini_yekutieli"}:
        raise ValueError("unsupported multiplicity method")
    if not 0 < float(multiplicity.get("fdr", 0)) < 1 or multiplicity.get(
        "family_level"
    ) is not True:
        raise ValueError("multiplicity FDR must lie in (0,1)")
    observations = int(minimum.get("observations", 0))
    effective_sample_size = float(minimum.get("effective_sample_size", 0))
    if (
        observations < 1
        or not 0 < effective_sample_size <= observations
        or int(minimum.get("sessions_for_provisional", 0)) < 2
        or int(minimum.get("sessions_for_stable", 0))
        < int(minimum.get("sessions_for_provisional", 0))
        or int(minimum.get("outer_folds_for_stable", 0)) < 1
    ):
        raise ValueError("minimum evidence policy is invalid")
    if promotion.get("single_day_promotion") is not False:
        raise ValueError("default policy must forbid single-day promotion")
    for key in (
        "minimum_sign_consistency",
        "minimum_neighbor_robustness",
        "minimum_adjusted_evidence",
    ):
        if not 0 <= float(promotion.get(key, -1)) <= 1:
            raise ValueError(f"promotion {key} must lie in [0,1]")
    if float(promotion.get("minimum_abs_score", -1)) < 0:
        raise ValueError("promotion minimum_abs_score must be non-negative")
    if (
        int(decay.get("decaying_consecutive_sessions", 0)) < 1
        or int(decay.get("dormant_consecutive_sessions", 0)) < 1
        or int(decay.get("dormant_consecutive_sessions", 0))
        < int(decay.get("decaying_consecutive_sessions", 0))
        or not 0 < float(decay.get("weakening_ratio", 0)) < 1
    ):
        raise ValueError("decay policy is invalid")
    if (
        reactivation.get("retrospective_reactivation") is not False
        or int(reactivation.get("minimum_new_confirmatory_sessions", 0)) < 1
    ):
        raise ValueError("retrospective reactivation must be forbidden")
    if (
        nulls.get("rerun_complete_miner") is not True
        or nulls.get("method") != "circular_shift"
        or nulls.get("statistic") != "maximum_absolute_score"
        or int(nulls.get("minimum_shift_blocks", 0)) < 1
        or int(nulls.get("replicates", 0)) < 1
        or not isinstance(nulls.get("seed"), int)
    ):
        raise ValueError("empirical null must rerun the complete miner")
    definitions = regimes.get("definitions")
    if regimes.get("causal_only") is not True or not isinstance(definitions, Mapping):
        raise ValueError("regimes require explicit causal executable definitions")
    for name, raw in definitions.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise ValueError("regime definition is malformed")
        if raw.get("strategy") not in {"always", "threshold"}:
            raise ValueError("unsupported regime strategy")
        if raw.get("strategy") == "threshold" and (
            not isinstance(raw.get("feature_id"), str)
            or raw.get("operator") not in {"le", "ge"}
            or not isinstance(raw.get("value"), (int, float))
        ):
            raise ValueError("threshold regime is incomplete")
    if (
        robustness.get("require_complete_surface") is not True
        or robustness.get("block_bootstrap") is not True
        or int(robustness.get("block_bootstrap_replicates", 0)) < 2
        or float(robustness.get("block_bootstrap_mean_length", 0)) < 1
        or not isinstance(robustness.get("block_bootstrap_seed"), int)
        or not 0 <= float(robustness.get("isolated_spike_penalty", -1)) <= 1
    ):
        raise ValueError("policy must require complete surfaces")


def _regularization_is_executable(model_class: str, values: Mapping[str, object]) -> bool:
    if model_class == "ridge":
        penalty = values.get("ridge_penalty")
        return isinstance(penalty, (int, float)) and float(penalty) >= 0
    if model_class == "elastic_net":
        alpha = values.get("elastic_alpha")
        ratio = values.get("elastic_l1_ratio")
        return (
            isinstance(alpha, (int, float))
            and float(alpha) > 0
            and isinstance(ratio, (int, float))
            and 0 <= float(ratio) <= 1
        )
    return False


def plan_alpha(
    *,
    through: date,
    feature_registry: FrozenRegistry,
    target_registry: FrozenRegistry,
    hypothesis_registry: FrozenRegistry,
    policy_registry: FrozenRegistry,
) -> AlphaPlan:
    if policy_registry.registry_type != "policy":
        raise ValueError("a policy registry is required")
    required_policy_sections = {
        "permitted_model_classes",
        "selection_methods",
        "training_windows_sessions",
        "training_cadences_seconds",
        "sampling_clocks",
        "pooling_coordinates",
        "selection_thresholds",
        "validation",
        "outer_test",
        "minimum_evidence",
        "multiplicity",
        "promotion",
        "decay",
        "reactivation",
        "null_simulation",
        "regime_rules",
        "robustness",
    }
    if not required_policy_sections <= set(policy_registry.payload):
        raise ValueError("policy registry is missing required research controls")
    _validate_nested_policy(policy_registry)
    features = set(declared_feature_ids(feature_registry))
    executable_exact = {
        "book.spread_ticks",
        "book.depth_imbalance_l5",
        "book.log1p_l1_depth",
        "regime.trailing_volatility",
        "regime.trailing_activity",
        "regime.minutes_from_open",
        "control.source_keyed_ar1_phi_0_8",
        "surface.front_skew_ew_innovation",
        "interaction.ofi_w10_d10_x_spread",
        "interaction.ofi_w10_d10_x_inverse_l1_depth",
        "interaction.ofi_w10_d10_x_trailing_volatility",
        "interaction.front_skew_innovation_x_ofi_w10_d10",
    }
    unsupported_features = {
        identity
        for identity in features
        if not identity.startswith("ofi.cumulative.depth=")
        and identity not in executable_exact
    }
    if unsupported_features:
        raise ValueError(
            "feature definitions have no executable construction strategy: "
            f"{sorted(unsupported_features)}"
        )
    targets = set(declared_target_ids(target_registry))
    raw_targets = target_registry.payload.get("targets")
    assert isinstance(raw_targets, (tuple, list))
    target_horizons = {
        str(item["target_id"]): float(item["horizon_seconds"])
        for item in raw_targets
        if isinstance(item, Mapping)
    }
    permitted_models = _policy_values(policy_registry, "permitted_model_classes")
    permitted_windows = {
        int(value) for value in _policy_values(policy_registry, "training_windows_sessions")
    }
    permitted_cadences = {
        float(value) for value in _policy_values(policy_registry, "training_cadences_seconds")
    }
    permitted_clocks = _policy_values(policy_registry, "sampling_clocks")
    permitted_pooling = _policy_values(policy_registry, "pooling_coordinates")
    permitted_selection = _policy_values(policy_registry, "selection_methods")
    permitted_thresholds = {
        float(value) for value in _policy_values(policy_registry, "selection_thresholds")
    }
    minimum_evidence = policy_registry.payload.get("minimum_evidence")
    if not isinstance(minimum_evidence, dict) and not isinstance(minimum_evidence, Mapping):
        raise ValueError("policy minimum_evidence must be an object")
    required_minimum = {"observations", "effective_sample_size"}
    if not required_minimum <= set(minimum_evidence):
        raise ValueError("policy minimum_evidence is incomplete")
    hypotheses = expand_hypotheses(hypothesis_registry)
    supported_models = {"ridge", "elastic_net"}
    supported_clocks = {"event", "calendar_1s"}
    supported_pooling = {"instrument"}
    supported_metrics = {"pearson_correlation"}
    supported_selection = {"nested_past_only"}
    regime_definitions = _require_policy_mapping(policy_registry, "regime_rules").get("definitions")
    assert isinstance(regime_definitions, Mapping)
    for raw in regime_definitions.values():
        assert isinstance(raw, Mapping)
        feature_id = raw.get("feature_id")
        if raw.get("strategy") == "threshold" and feature_id not in features:
            raise ValueError("causal regime references a feature absent from the frozen registry")
    exclusions: list[dict[str, str]] = []
    eligible = []
    for hypothesis in hypotheses:
        reason: str | None = None
        if not set(hypothesis.predictor_feature_ids) <= features:
            reason = "predictor_not_in_feature_registry"
        elif not set(hypothesis.conditioning_variables) <= features:
            reason = "conditioning_variable_not_in_feature_registry"
        elif hypothesis.target_id not in targets:
            reason = "target_not_in_target_registry"
        elif target_horizons.get(hypothesis.target_id) != hypothesis.target_horizon_seconds:
            reason = "target_horizon_differs_from_registered_target"
        elif hypothesis.first_registration_date > through:
            reason = "registered_after_cutoff"
        elif hypothesis.model_class not in permitted_models:
            reason = "model_not_permitted_by_policy"
        elif hypothesis.model_class not in supported_models:
            reason = "model_has_no_executable_strategy"
        elif not _regularization_is_executable(
            hypothesis.model_class, dict(hypothesis.regularization)
        ):
            reason = "model_regularization_has_no_executable_strategy"
        elif hypothesis.fitting_window_sessions not in permitted_windows:
            reason = "fitting_window_not_permitted_by_policy"
        elif hypothesis.training_cadence_seconds not in permitted_cadences:
            reason = "training_cadence_not_permitted_by_policy"
        elif hypothesis.sampling_clock not in permitted_clocks:
            reason = "sampling_clock_not_permitted_by_policy"
        elif hypothesis.sampling_clock not in supported_clocks:
            reason = "sampling_clock_has_no_executable_strategy"
        elif hypothesis.pooling_coordinate not in permitted_pooling:
            reason = "pooling_coordinate_not_permitted_by_policy"
        elif hypothesis.pooling_coordinate not in supported_pooling:
            reason = "pooling_coordinate_has_no_executable_strategy"
        elif hypothesis.selection_method not in permitted_selection:
            reason = "selection_method_not_permitted_by_policy"
        elif hypothesis.selection_method not in supported_selection:
            reason = "selection_method_has_no_executable_strategy"
        elif hypothesis.evaluation_metric not in supported_metrics:
            reason = "evaluation_metric_has_no_executable_strategy"
        elif hypothesis.admissible_regime not in regime_definitions:
            reason = "regime_has_no_executable_strategy"
        elif hypothesis.selection_threshold not in permitted_thresholds:
            reason = "selection_threshold_not_permitted_by_policy"
        elif hypothesis.minimum_observations != int(minimum_evidence["observations"]):
            reason = "minimum_observations_not_permitted_by_policy"
        elif hypothesis.minimum_effective_sample_size != float(
            minimum_evidence["effective_sample_size"]
        ):
            reason = "minimum_effective_sample_size_not_permitted_by_policy"
        if reason is None:
            eligible.append(hypothesis)
        else:
            exclusions.append({"hypothesis_id": hypothesis.hypothesis_id, "reason": reason})
    families = {hypothesis.family for hypothesis in eligible}
    horizons = {hypothesis.target_horizon_seconds for hypothesis in eligible}
    regimes = {hypothesis.admissible_regime for hypothesis in eligible}
    models = {hypothesis.model_class for hypothesis in eligible}
    predictors = {hypothesis.predictor_feature_ids for hypothesis in eligible}
    clocks = {hypothesis.sampling_clock for hypothesis in eligible}
    pooling = {hypothesis.pooling_coordinate for hypothesis in eligible}
    windows = {hypothesis.fitting_window_sessions for hypothesis in eligible}
    cadences = {hypothesis.training_cadence_seconds for hypothesis in eligible}
    selection_methods = {hypothesis.selection_method for hypothesis in eligible}
    interactions = sum(feature_id.startswith("interaction.") for feature_id in features)
    fingerprints = tuple(
        sorted(
            (
                (feature_registry.version, feature_registry.fingerprint_sha256),
                (target_registry.version, target_registry.fingerprint_sha256),
                (hypothesis_registry.version, hypothesis_registry.fingerprint_sha256),
                (policy_registry.version, policy_registry.fingerprint_sha256),
            )
        )
    )
    if not eligible:
        raise ValueError("empty effective hypothesis universe")
    plan = AlphaPlan(
        through,
        feature_registry.version,
        target_registry.version,
        hypothesis_registry.version,
        policy_registry.version,
        len(predictors),
        len({hypothesis.target_id for hypothesis in eligible}),
        len(horizons),
        len(regimes),
        len(models),
        interactions,
        len(clocks),
        len(pooling),
        len(windows),
        len(cadences),
        len(selection_methods),
        len(hypotheses),
        len(eligible),
        len(families),
        tuple(exclusions),
        len(eligible)
        * (1 + int(_require_policy_mapping(policy_registry, "null_simulation")["replicates"])),
        fingerprints,
        tuple(sorted(hypothesis.hypothesis_id for hypothesis in eligible)),
        "",
    )
    return plan.with_hash()


def plan_from_directory(
    directory: Path,
    *,
    through: date,
    feature_version: str,
    target_version: str,
    hypothesis_version: str = "alpha_hypotheses_v1",
    policy_version: str = "alpha_research_policy_v1",
) -> AlphaPlan:
    return plan_alpha(
        through=through,
        feature_registry=registry_by_version(directory, feature_version, expected_type="features"),
        target_registry=registry_by_version(directory, target_version, expected_type="targets"),
        hypothesis_registry=registry_by_version(
            directory, hypothesis_version, expected_type="hypotheses"
        ),
        policy_registry=registry_by_version(directory, policy_version, expected_type="policy"),
    )


def validate_plan_registries(
    plan: AlphaPlan,
    *,
    feature_registry: FrozenRegistry,
    target_registry: FrozenRegistry,
    hypothesis_registry: FrozenRegistry,
    policy_registry: FrozenRegistry,
) -> None:
    """Reject version aliases or edited registry bytes after a plan was frozen."""

    observed = tuple(
        sorted(
            (
                (feature_registry.version, feature_registry.fingerprint_sha256),
                (target_registry.version, target_registry.fingerprint_sha256),
                (hypothesis_registry.version, hypothesis_registry.fingerprint_sha256),
                (policy_registry.version, policy_registry.fingerprint_sha256),
            )
        )
    )
    if observed != plan.registry_fingerprints:
        raise ValueError("runtime registries do not match the exact plan-frozen fingerprints")
    expanded_ids = tuple(
        sorted(item.hypothesis_id for item in expand_hypotheses(hypothesis_registry))
    )
    excluded = {str(item["hypothesis_id"]) for item in plan.excluded_before_target_inspection}
    if tuple(sorted((*plan.eligible_hypothesis_ids, *excluded))) != expanded_ids:
        raise ValueError("runtime hypothesis universe differs from the plan-frozen universe")
    rebuilt = plan_alpha(
        through=plan.through,
        feature_registry=feature_registry,
        target_registry=target_registry,
        hypothesis_registry=hypothesis_registry,
        policy_registry=policy_registry,
    )
    if rebuilt != plan:
        raise ValueError("persisted alpha plan fields differ from the complete frozen plan")


def alpha_plan_from_mapping(raw: Mapping[str, Any]) -> AlphaPlan:
    """Reconstruct and verify a persisted plan without consulting later registries."""

    values = dict(raw)
    values["through"] = date.fromisoformat(str(values["through"]))
    for name in (
        "excluded_before_target_inspection",
        "registry_fingerprints",
        "eligible_hypothesis_ids",
    ):
        values[name] = tuple(
            tuple(item) if isinstance(item, list) else item for item in values[name]
        )
    plan = AlphaPlan(**values)
    if len(plan.plan_hash) != 64 or not plan.eligible_hypothesis_ids:
        raise ValueError("persisted alpha plan is incomplete")
    if plan.with_hash().plan_hash != plan.plan_hash:
        raise ValueError("persisted alpha plan hash does not match its complete payload")
    return plan
