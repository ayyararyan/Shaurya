from __future__ import annotations

from dataclasses import replace

from shaurya.signals.feature_selection import (
    BoostedTreeConfig,
    FeatureSelectionRow,
    ModelTransform,
    RegressionMetrics,
    RegressionTreeNode,
    ShallowGradientBoostingModel,
)
from shaurya.signals.feature_selection_walkforward import (
    CandidateScore,
    FoldModelResult,
    NestedWalkForwardArtifact,
    NestedWalkForwardConfig,
    _resolved_candidate_config,
    construct_nested_expanding_folds,
    nested_walk_forward_artifact_from_json,
    nested_walk_forward_artifact_to_json,
    sample_on_grid,
)

NS = 1_000_000_000


def _rows(count: int = 1_000) -> tuple[FeatureSelectionRow, ...]:
    return tuple(
        FeatureSelectionRow(
            anchor_ts_ns=index * NS,
            connection_epoch=1,
            target_start_ts_ns=index * NS + NS // 2,
            target_end_ts_ns=index * NS + 10_500_000_000,
            target_ticks=float(index % 7 - 3),
            feature_values={},
            feature_available_ts_ns={},
        )
        for index in range(count)
    )


def test_grid_sampling_is_deterministic_and_epoch_safe() -> None:
    rows = list(_rows(20))
    rows.insert(
        2,
        replace(
            rows[1],
            anchor_ts_ns=1_900_000_000,
            target_start_ts_ns=2_400_000_000,
            target_end_ts_ns=12_400_000_000,
        ),
    )
    assert [row.anchor_ts_ns for row in sample_on_grid(rows, grid_seconds=5)] == [
        0,
        5 * NS,
        10 * NS,
        15 * NS,
    ]


def test_nested_folds_are_chronological_purged_embargoed_and_test_once() -> None:
    rows = _rows()
    policy = NestedWalkForwardConfig()
    folds = construct_nested_expanding_folds(rows, config=policy)
    all_tests: set[int] = set()
    for fold in folds:
        assert set(fold.outer_training_indices).isdisjoint(fold.outer_test_indices)
        assert set(fold.inner_training_indices).isdisjoint(fold.inner_validation_indices)
        assert all_tests.isdisjoint(fold.outer_test_indices)
        all_tests.update(fold.outer_test_indices)
        last_train = rows[fold.outer_training_indices[-1]]
        first_test = rows[fold.outer_test_indices[0]]
        assert last_train.target_end_ts_ns < first_test.anchor_ts_ns
        assert first_test.anchor_ts_ns - last_train.anchor_ts_ns >= 120 * NS
        last_inner = rows[fold.inner_training_indices[-1]]
        first_validation = rows[fold.inner_validation_indices[0]]
        assert last_inner.target_end_ts_ns < first_validation.anchor_ts_ns
        assert first_validation.anchor_ts_ns - last_inner.anchor_ts_ns >= 120 * NS
    assert [fold.outer_test_start_ts_ns for fold in folds] == sorted(
        fold.outer_test_start_ts_ns for fold in folds
    )


def test_future_target_mutation_cannot_change_fold_boundaries() -> None:
    rows = _rows()
    baseline = construct_nested_expanding_folds(rows)
    mutated = tuple(
        replace(row, target_ticks=1_000_000.0 - row.target_ticks) if index >= 400 else row
        for index, row in enumerate(rows)
    )
    assert construct_nested_expanding_folds(mutated) == baseline


def test_inner_selected_tree_stopping_count_is_carried_into_outer_config() -> None:
    config = BoostedTreeConfig(
        maximum_depth=1,
        maximum_leaves=2,
        learning_rate=0.05,
        minimum_leaf_size=10,
        maximum_estimators=80,
        threshold_candidates=15,
        early_stopping_patience=10,
    )
    fitted = ShallowGradientBoostingModel(
        "d51-predictive-model-v1",
        ModelTransform((), (), (), (), (), 20),
        config,
        0.0,
        (RegressionTreeNode(0.0),) * 7,
        7,
        tuple(float(index) for index in range(7)),
    )
    resolved = _resolved_candidate_config(
        {
            "maximum_depth": 1,
            "maximum_leaves": 2,
            "learning_rate": 0.05,
            "minimum_leaf_size": 10,
            "maximum_estimators": 80,
            "threshold_candidates": 15,
            "early_stopping_patience": 10,
        },
        fitted,
    )
    assert resolved["maximum_estimators"] == 7


def test_walk_forward_artifact_exact_readback() -> None:
    policy = NestedWalkForwardConfig()
    metric = RegressionMetrics(2, 1.0, 1.0, 0.0, -0.5, 0.25, 0.5)
    artifact = NestedWalkForwardArtifact(
        "1.0.0",
        policy,
        "exploratory_insufficient_sessions",
        1,
        1_000,
        0,
        999 * NS,
        "a" * 64,
        (CandidateScore("candidate", "elastic_net", {"alpha": 0.01}, 1.0),),
        (
            FoldModelResult(
                "outer_01",
                "elastic_net",
                "elastic_net",
                {"alpha": 0.01},
                100,
                20,
                30,
                4,
                4,
                100 * NS,
                220 * NS,
                metric,
                (0.0, 1.0),
                ("a", "b"),
                "b" * 64,
            ),
        ),
    )
    encoded = nested_walk_forward_artifact_to_json(artifact)
    assert nested_walk_forward_artifact_from_json(encoded) == artifact
    assert (
        nested_walk_forward_artifact_to_json(nested_walk_forward_artifact_from_json(encoded))
        == encoded
    )
