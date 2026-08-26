from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from shaurya.signals.feature_selection import (
    ConditionalUsefulnessArtifact,
    ConditionalUsefulnessConfig,
    ImportanceClusterDefinition,
    conditional_usefulness_artifact_from_json,
    conditional_usefulness_artifact_to_json,
    evaluate_conditional_oos_usefulness,
    paired_common_row_loss_comparison,
)


def _panel(
    count: int, *, seed: int
) -> tuple[list[dict[str, float]], list[float], list[str]]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=count)
    noise = rng.normal(size=count)
    noise_two = rng.normal(size=count)
    target_noise = rng.normal(scale=0.05, size=count)
    rows = [
        {
            "signal_a": float(value),
            "signal_substitute": float(value + 1e-5 * ((index % 3) - 1)),
            "noise": float(noise[index]),
            "noise_two": float(noise_two[index]),
        }
        for index, value in enumerate(x)
    ]
    targets = [float(4.0 * value + target_noise[index]) for index, value in enumerate(x)]
    ids = [f"seed-{seed}-row-{index}" for index in range(count)]
    return rows, targets, ids


def _clusters() -> tuple[ImportanceClusterDefinition, ...]:
    return (
        ImportanceClusterDefinition(
            "cluster__signal",
            ("signal_a", "signal_substitute"),
            ("signal_a", "signal_substitute"),
            "ofi",
        ),
        ImportanceClusterDefinition(
            "cluster__noise", ("noise",), ("noise",), "surface"
        ),
        ImportanceClusterDefinition(
            "cluster__noise_two", ("noise_two",), ("noise_two",), "surface"
        ),
    )


def _artifact() -> ConditionalUsefulnessArtifact:
    training_rows, training_targets, training_ids = _panel(500, seed=10)
    evaluation_rows, evaluation_targets, evaluation_ids = _panel(240, seed=20)
    return evaluate_conditional_oos_usefulness(
        training_rows=training_rows,
        training_targets=training_targets,
        training_row_ids=training_ids,
        evaluation_rows=evaluation_rows,
        evaluation_targets=evaluation_targets,
        evaluation_row_ids=evaluation_ids,
        cluster_definitions=_clusters(),
        config=ConditionalUsefulnessConfig(
            permutation_block_size=20,
            permutation_repeats=3,
            permutation_seed=1234,
            loss_block_size=30,
        ),
    )


def test_signal_cluster_is_positive_and_redundant_credit_is_joint() -> None:
    artifact = _artifact()
    comparisons = {
        item.comparison_id: item for item in artifact.cluster_ablation_comparisons
    }
    signal = comparisons["cluster__signal"]
    noise = comparisons["cluster__noise"]
    assert signal.cluster_ids == ("cluster__signal",)
    assert signal.model_features == ("signal_a", "signal_substitute")
    assert signal.delta_oos_r_squared > 0.95
    assert signal.direction == "positive"
    assert abs(noise.delta_oos_r_squared) < 0.01
    assert {item.comparison_id for item in artifact.cluster_ablation_comparisons} == {
        "cluster__signal",
        "cluster__noise",
        "cluster__noise_two",
    }
    assert all(
        item.comparison_id not in {"signal_a", "signal_substitute"}
        for item in artifact.cluster_ablation_comparisons
    )


def test_feature_family_ablation_drops_whole_clusters_only() -> None:
    artifact = _artifact()
    families = {item.comparison_id: item for item in artifact.family_ablation_comparisons}
    assert families["ofi"].cluster_ids == ("cluster__signal",)
    assert families["ofi"].model_features == ("signal_a", "signal_substitute")
    assert families["ofi"].delta_oos_r_squared > 0.95
    assert families["surface"].cluster_ids == (
        "cluster__noise",
        "cluster__noise_two",
    )
    assert families["surface"].model_features == ("noise", "noise_two")


def test_grouped_contiguous_block_permutation_is_seeded_and_deterministic() -> None:
    first = _artifact()
    second = _artifact()
    assert first.block_permutation_comparisons == second.block_permutation_comparisons
    signal = [
        item
        for item in first.block_permutation_comparisons
        if item.comparison_id == "cluster__signal"
    ]
    assert len(signal) == 3
    assert [item.permutation_seed for item in signal] == [1240, 1241, 1242]
    assert all(item.delta_oos_r_squared > 0.5 for item in signal)
    assert all(item.model_features == ("signal_a", "signal_substitute") for item in signal)
    assert all(item.comparator_model_fingerprint_sha256 is None for item in signal)
    assert all(item.comparator_input_fingerprint_sha256 is not None for item in signal)


def test_paired_loss_comparison_refuses_non_common_rows() -> None:
    with pytest.raises(ValueError, match="identical ordered common rows"):
        paired_common_row_loss_comparison(
            full_row_ids=("a", "b"),
            comparator_row_ids=("a", "c"),
            targets=(1.0, 2.0),
            full_predictions=(1.0, 2.0),
            comparator_predictions=(0.0, 0.0),
            block_size=1,
        )


def test_all_comparisons_carry_common_support_and_uncertainty_ready_block_losses() -> None:
    artifact = _artifact()
    comparisons = (
        *artifact.cluster_ablation_comparisons,
        *artifact.family_ablation_comparisons,
        *artifact.block_permutation_comparisons,
    )
    assert all(item.support_training_rows == 500 for item in comparisons)
    assert all(item.support_evaluation_rows == 240 for item in comparisons)
    assert all(item.paired_losses.common_row_count == 240 for item in comparisons)
    assert all(len(item.paired_losses.blocks) == 8 for item in comparisons)
    assert all(
        len(item.paired_losses.comparator_minus_full_squared_losses) == 240
        for item in comparisons
    )


def test_evaluation_targets_cannot_change_fitted_model_identity() -> None:
    training_rows, training_targets, training_ids = _panel(500, seed=10)
    evaluation_rows, evaluation_targets, evaluation_ids = _panel(240, seed=20)
    config = ConditionalUsefulnessConfig(
        permutation_block_size=20, permutation_repeats=1, permutation_seed=7
    )
    first = evaluate_conditional_oos_usefulness(
        training_rows=training_rows,
        training_targets=training_targets,
        training_row_ids=training_ids,
        evaluation_rows=evaluation_rows,
        evaluation_targets=evaluation_targets,
        evaluation_row_ids=evaluation_ids,
        cluster_definitions=_clusters(),
        config=config,
    )
    mutated = evaluate_conditional_oos_usefulness(
        training_rows=training_rows,
        training_targets=training_targets,
        training_row_ids=training_ids,
        evaluation_rows=evaluation_rows,
        evaluation_targets=[-value for value in evaluation_targets],
        evaluation_row_ids=evaluation_ids,
        cluster_definitions=_clusters(),
        config=config,
    )
    assert first.full_model_fingerprint_sha256 == mutated.full_model_fingerprint_sha256
    assert first.config_fingerprint_sha256 == mutated.config_fingerprint_sha256
    assert first.split_fingerprint_sha256 == mutated.split_fingerprint_sha256
    assert first.data_fingerprint_sha256 != mutated.data_fingerprint_sha256


def test_artifact_readback_is_exact_and_auditable() -> None:
    artifact = _artifact()
    encoded = conditional_usefulness_artifact_to_json(artifact)
    restored = conditional_usefulness_artifact_from_json(encoded)
    assert restored == artifact
    assert conditional_usefulness_artifact_to_json(restored) == encoded
    assert restored.importance_unit == "cluster"
    assert restored.evidence_label == "exploratory_screening_today_only"
    assert all(
        len(value) == 64
        for value in (
            restored.config_fingerprint_sha256,
            restored.split_fingerprint_sha256,
            restored.data_fingerprint_sha256,
            restored.full_model_fingerprint_sha256,
        )
    )
    assert dataclasses.asdict(restored)["cluster_definitions"][0]["members"]
