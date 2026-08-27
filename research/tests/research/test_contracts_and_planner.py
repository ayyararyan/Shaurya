from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path

import pytest

from shaurya.research.contracts import (
    FeatureObservation,
    FeatureValue,
    HypothesisDefinition,
)
from shaurya.research.features import fit_training_only_redundancy
from shaurya.research.planner import plan_from_directory
from shaurya.research.registry import expand_hypotheses, registry_by_version

REGISTRIES = Path("registries")


def test_feature_observation_is_deeply_immutable_target_blind_and_future_safe() -> None:
    row = FeatureObservation(
        "row-1",
        date(2026, 8, 1),
        1_000,
        1,
        "features-v1",
        "dataset",
        "a" * 64,
        (FeatureValue("ofi", 2.0, 999),),
    )
    original_hash = row.feature_run_hash
    with pytest.raises(TypeError):
        row.value_map["ofi"] = 4.0  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        row.anchor_ts_ns = 2_000  # type: ignore[misc]
    assert not hasattr(row, "target")
    assert row.feature_run_hash == original_hash
    with pytest.raises(ValueError, match="after the anchor"):
        replace(row, values=(FeatureValue("ofi", 2.0, 1_001),))


def test_plan_knows_the_complete_search_cardinality_before_outcomes() -> None:
    plan = plan_from_directory(
        REGISTRIES,
        through=date(2026, 8, 26),
        feature_version="microstructure_features_v1",
        target_version="microstructure_targets_v1",
    )
    assert plan.total_raw_hypothesis_count == 22_681
    assert plan.total_effective_hypothesis_count == 7_561
    assert plan.predictor_specifications == 64
    assert plan.effective_family_count == 2
    assert plan.horizons == 10
    assert plan.regime_conditions == 3
    assert plan.interactions == 4
    assert plan.sampling_clocks == 2
    assert plan.pooling_coordinates == 1
    assert len(plan.excluded_before_target_inspection) == 15_120
    assert {item["reason"] for item in plan.excluded_before_target_inspection} == {
        "pooling_coordinate_has_no_executable_strategy",
        "sampling_clock_has_no_executable_strategy",
    }
    assert len(plan.plan_hash) == 64


def test_semantic_hypothesis_identity_ignores_alias_and_duplicates_are_one_atom() -> None:
    original = expand_hypotheses(
        registry_by_version(REGISTRIES, "alpha_hypotheses_v1", expected_type="hypotheses")
    )[0]
    alias = HypothesisDefinition(
        display_name="a fresh attractive label",
        family=original.family,
        predictor_feature_ids=original.predictor_feature_ids,
        target_id=original.target_id,
        target_horizon_seconds=original.target_horizon_seconds,
        conditioning_variables=original.conditioning_variables,
        admissible_regime=original.admissible_regime,
        model_class=original.model_class,
        fitting_window_sessions=original.fitting_window_sessions,
        training_cadence_seconds=original.training_cadence_seconds,
        regularization=original.regularization,
        evaluation_metric=original.evaluation_metric,
        transaction_cost_relevance=original.transaction_cost_relevance,
        first_registration_date=date(2026, 8, 27),
        registry_version="later-registry-version",
    )
    assert alias.hypothesis_id == original.hypothesis_id


def test_redundancy_metadata_uses_only_declared_target_free_training_rows() -> None:
    rows = tuple(
        FeatureObservation(
            f"row-{index}",
            date(2026, 8, 1),
            index,
            1,
            "features-v1",
            "dataset",
            f"{index + 1:064x}",
            (
                FeatureValue("a", float(index), index),
                FeatureValue("a_copy", -float(index), index),
                FeatureValue("noise", float(index % 2), index),
            ),
        )
        for index in range(6)
    )
    baseline = fit_training_only_redundancy(
        rows, training_observation_ids=("row-0", "row-1", "row-2", "row-3")
    )
    mutated_future = (
        *rows[:4],
        replace(rows[4], values=(FeatureValue("future_only", 999.0, 4),)),
        rows[5],
    )
    changed = fit_training_only_redundancy(
        mutated_future, training_observation_ids=("row-0", "row-1", "row-2", "row-3")
    )
    assert baseline == changed
    assert ("a", "a_copy") in baseline.clusters
