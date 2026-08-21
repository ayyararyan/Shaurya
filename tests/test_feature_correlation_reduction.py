from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal

import pytest

from shaurya.signals.feature_selection import (
    CORRELATION_SENSITIVITY_THRESHOLDS,
    GATE_ARTIFACT_VERSION,
    REGISTRY_VERSION,
    SPECIFICATION_ID,
    CorrelatedFeatureReductionArtifact,
    CorrelationReductionConfig,
    FeatureQualityGateArtifact,
    FeatureQualityGateConfig,
    GatedFeatureRow,
    apply_correlated_feature_reduction,
    fit_correlated_feature_reduction,
)


def _gate_artifact(
    values_by_row: Sequence[Mapping[str, float | None]],
    *,
    training: tuple[int, ...],
) -> FeatureQualityGateArtifact:
    names = tuple(sorted({name for row in values_by_row for name in row}))
    rows = tuple(
        GatedFeatureRow(
            source_row_index=index,
            row_valid=True,
            feature_values={name: row.get(name) for name in names},
            missing_indicators={name: row.get(name) is None for name in names},
            validity_indicators={name: row.get(name) is not None for name in names},
        )
        for index, row in enumerate(values_by_row)
    )
    return FeatureQualityGateArtifact(
        version=GATE_ARTIFACT_VERSION,
        specification_id=SPECIFICATION_ID,
        registry_version=REGISTRY_VERSION,
        config=FeatureQualityGateConfig(),
        maximum_age_seconds_by_family={},
        input_fingerprint_sha256="full-input-is-deliberately-not-used-by-step-3",
        training_row_indices=training,
        eligible_features=names,
        excluded_features=(),
        findings=(),
        training_diagnostics=(),
        rows=rows,
        reason_counts={},
    )


def _cluster_members(
    reduction: CorrelatedFeatureReductionArtifact, threshold: float
) -> set[tuple[str, ...]]:
    cluster_map = next(
        item
        for item in reduction.sensitivity_maps
        if item.absolute_correlation_threshold == threshold
    )
    return {cluster.members for cluster in cluster_map.clusters}


def test_perfect_positive_and_negative_substitutes_share_one_cluster() -> None:
    gate = _gate_artifact(
        [
            {"alpha": 1.0, "beta": 10.0, "gamma": -1.0},
            {"alpha": 2.0, "beta": 20.0, "gamma": -2.0},
            {"alpha": 3.0, "beta": 30.0, "gamma": -3.0},
            {"alpha": 4.0, "beta": 40.0, "gamma": -4.0},
        ],
        training=(0, 1, 2, 3),
    )
    artifact = fit_correlated_feature_reduction(
        gate,
        config=CorrelationReductionConfig(measurement_quality_by_feature={"beta": 2.0}),
    )
    assert _cluster_members(artifact, 0.90) == {("alpha", "beta", "gamma")}
    cluster = artifact.primary_map.clusters[0]
    assert cluster.representative == "beta"
    assert all(
        item.rho is not None and abs(item.rho) == pytest.approx(1.0)
        for item in artifact.pairwise_diagnostics
    )


def test_missing_pair_support_is_explicit_and_cannot_create_a_merge() -> None:
    gate = _gate_artifact(
        [
            {"left": 1.0, "right": None},
            {"left": 2.0, "right": None},
            {"left": None, "right": 3.0},
            {"left": None, "right": 4.0},
        ],
        training=(0, 1, 2, 3),
    )
    artifact = fit_correlated_feature_reduction(
        gate, config=CorrelationReductionConfig(minimum_pair_count=3)
    )
    pair = artifact.pairwise_diagnostics[0]
    assert pair.pair_count == 0
    assert pair.rho is None
    assert pair.distance == 1.0
    assert pair.status == "insufficient_pairs"
    assert _cluster_members(artifact, 0.85) == {("left",), ("right",)}


def test_held_out_values_cannot_change_clustering_or_training_fingerprint() -> None:
    training_rows = [
        {"a": 1.0, "b": 2.0},
        {"a": 2.0, "b": 4.0},
        {"a": 3.0, "b": 6.0},
    ]
    first = _gate_artifact([*training_rows, {"a": 4.0, "b": 8.0}], training=(0, 1, 2))
    second = _gate_artifact(
        [*training_rows, {"a": -999_999.0, "b": None}], training=(0, 1, 2)
    )
    first_fit = fit_correlated_feature_reduction(first)
    second_fit = fit_correlated_feature_reduction(second)
    assert first_fit == second_fit
    assert (
        first_fit.training_input_fingerprint_sha256
        == second_fit.training_input_fingerprint_sha256
    )


def test_first_pc_is_fit_on_complete_training_rows_and_only_applied_later() -> None:
    gate = _gate_artifact(
        [
            {"x": 1.0, "y": 2.0},
            {"x": 2.0, "y": 4.0},
            {"x": 3.0, "y": 6.0},
            {"x": 4.0, "y": 8.0},
            {"x": 5.0, "y": None},
        ],
        training=(0, 1, 2),
    )
    artifact = fit_correlated_feature_reduction(
        gate, config=CorrelationReductionConfig(representation="first_pc")
    )
    transform = artifact.first_pc_transforms[0]
    assert transform.members == ("x", "y")
    assert transform.center == pytest.approx((2.0, 4.0))
    anchor_index = transform.members.index(transform.sign_anchor_feature)
    assert transform.loadings[anchor_index] > 0.0
    assert math.isclose(sum(value**2 for value in transform.loadings), 1.0)
    applied = apply_correlated_feature_reduction(artifact, gate.rows[3:])
    expected = sum(
        (value - center) * loading
        for value, center, loading in zip(
            (4.0, 8.0), transform.center, transform.loadings, strict=True
        )
    )
    cluster_name = transform.cluster_id
    assert applied[0].values[cluster_name] == pytest.approx(expected)
    assert applied[1].values[cluster_name] is None
    assert applied[1].missing_indicators[cluster_name]
    assert not applied[1].validity_indicators[cluster_name]


def test_repeated_fit_is_deterministic_and_emits_all_frozen_sensitivity_maps() -> None:
    gate = _gate_artifact(
        [
            {"z": 1.0, "a": 5.0, "m": 9.0},
            {"z": 3.0, "a": 4.0, "m": 7.0},
            {"z": 2.0, "a": 3.0, "m": 8.0},
            {"z": 4.0, "a": 2.0, "m": 6.0},
        ],
        training=(0, 1, 2, 3),
    )
    first = fit_correlated_feature_reduction(gate)
    second = fit_correlated_feature_reduction(gate)
    assert first == second
    assert tuple(item.absolute_correlation_threshold for item in first.sensitivity_maps) == (
        CORRELATION_SENSITIVITY_THRESHOLDS
    )
    assert first.importance_unit == "cluster"


@pytest.mark.parametrize("representation", ["representative", "first_pc"])
def test_singleton_cluster_has_a_valid_deterministic_transform(
    representation: Literal["representative", "first_pc"],
) -> None:
    gate = _gate_artifact([{"only": 2.0}, {"only": 4.0}, {"only": 8.0}], training=(0, 1, 2))
    artifact = fit_correlated_feature_reduction(
        gate,
        config=CorrelationReductionConfig(representation=representation),
    )
    assert artifact.primary_map.clusters[0].members == ("only",)
    applied = apply_correlated_feature_reduction(artifact, gate.rows[-1:])[0]
    cluster_name = artifact.primary_map.clusters[0].cluster_id
    expected = 8.0 if representation == "representative" else 8.0 - 14.0 / 3.0
    assert applied.values[cluster_name] == pytest.approx(expected)
