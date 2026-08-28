from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

import shaurya.data as constructors

from shaurya.research import HIGH_FREQUENCY_REGISTRY_BINDING
from shaurya.research.planner import plan_from_directory
from shaurya.research.registry import (
    declared_feature_ids,
    declared_target_ids,
    expand_hypotheses,
    registry_by_version,
)

REGISTRIES = Path("registries")


def test_every_v2_registry_entry_points_to_a_real_constructor() -> None:
    for registry_type, version, collection in (
        ("features", HIGH_FREQUENCY_REGISTRY_BINDING.feature_registry, "features"),
        ("targets", HIGH_FREQUENCY_REGISTRY_BINDING.target_registry, "targets"),
    ):
        registry = registry_by_version(REGISTRIES, version, expected_type=registry_type)
        definitions = registry.payload[collection]
        assert isinstance(definitions, tuple)
        for definition in definitions:
            assert isinstance(definition, Mapping)
            constructor = definition.get("constructor")
            assert isinstance(constructor, str)
            assert callable(getattr(constructors, constructor, None)), constructor


def test_targets_cannot_be_registered_as_same_timestamp_inputs() -> None:
    features = registry_by_version(
        REGISTRIES, HIGH_FREQUENCY_REGISTRY_BINDING.feature_registry, expected_type="features"
    )
    targets = registry_by_version(
        REGISTRIES, HIGH_FREQUENCY_REGISTRY_BINDING.target_registry, expected_type="targets"
    )
    feature_ids = set(declared_feature_ids(features))
    target_ids = set(declared_target_ids(targets))
    assert feature_ids.isdisjoint(target_ids)
    assert all(value.startswith("target.") for value in target_ids)
    assert all(not value.startswith("target.") for value in feature_ids)


def test_v2_hypotheses_resolve_to_v2_features_and_targets() -> None:
    features = registry_by_version(
        REGISTRIES, HIGH_FREQUENCY_REGISTRY_BINDING.feature_registry, expected_type="features"
    )
    targets = registry_by_version(
        REGISTRIES, HIGH_FREQUENCY_REGISTRY_BINDING.target_registry, expected_type="targets"
    )
    hypotheses = registry_by_version(
        REGISTRIES, HIGH_FREQUENCY_REGISTRY_BINDING.hypothesis_registry, expected_type="hypotheses"
    )
    feature_ids = set(declared_feature_ids(features))
    target_ids = set(declared_target_ids(targets))
    expanded = expand_hypotheses(hypotheses)
    assert expanded
    for hypothesis in expanded:
        assert set(hypothesis.predictor_feature_ids) <= feature_ids
        assert set(hypothesis.conditioning_variables) <= feature_ids
        assert hypothesis.target_id in target_ids


def test_v2_bundle_builds_a_deterministic_plan() -> None:
    binding = HIGH_FREQUENCY_REGISTRY_BINDING
    first = plan_from_directory(
        REGISTRIES,
        through=date(2026, 8, 27),
        feature_version=binding.feature_registry,
        target_version=binding.target_registry,
        hypothesis_version=binding.hypothesis_registry,
        policy_version=binding.policy_registry,
    )
    second = plan_from_directory(
        REGISTRIES,
        through=date(2026, 8, 27),
        feature_version=binding.feature_registry,
        target_version=binding.target_registry,
        hypothesis_version=binding.hypothesis_registry,
        policy_version=binding.policy_registry,
    )
    assert first == second
    assert first.total_effective_hypothesis_count == 8
