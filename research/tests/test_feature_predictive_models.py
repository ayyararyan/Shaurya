from __future__ import annotations

import math

import numpy as np
import pytest

from shaurya.signals.feature_selection import (
    BOOSTED_TREE_CONFIG_GRID,
    ELASTIC_NET_CONFIG_GRID,
    BoostedTreeConfig,
    ElasticNetConfig,
    RegressionTreeNode,
    apply_model_transform,
    fit_elastic_net,
    fit_model_transform,
    fit_shallow_gradient_boosting,
    fit_state_linear_baseline,
    fit_training_mean_baseline,
    predict_model,
    predictive_model_from_json,
    predictive_model_to_json,
    regression_metrics,
    zero_return_baseline,
)


def _interaction_rows(count: int, *, offset: int = 0) -> tuple[list[dict[str, float]], list[float]]:
    rows: list[dict[str, float]] = []
    targets: list[float] = []
    for index in range(offset, offset + count):
        x1 = -1.0 + 2.0 * ((index * 37) % 997) / 996.0
        x2 = -1.0 + 2.0 * ((index * 101 + 17) % 991) / 990.0
        rows.append({"x1": x1, "x2": x2})
        targets.append(3.0 if x1 * x2 >= 0.0 else -3.0)
    return rows, targets


def _tree_shape(node: RegressionTreeNode) -> tuple[int, int]:
    if node.is_leaf:
        return 0, 1
    assert node.left is not None and node.right is not None
    left_depth, left_leaves = _tree_shape(node.left)
    right_depth, right_leaves = _tree_shape(node.right)
    return 1 + max(left_depth, right_depth), left_leaves + right_leaves


def test_boosted_tree_captures_nonlinear_interaction_beyond_elastic_net() -> None:
    training_rows, training_targets = _interaction_rows(600)
    validation_rows, validation_targets = _interaction_rows(200, offset=2_000)
    test_rows, test_targets = _interaction_rows(300, offset=4_000)
    elastic = fit_elastic_net(
        training_rows,
        training_targets,
        feature_names=("x1", "x2"),
        config=ElasticNetConfig(alpha=0.0001, l1_ratio=0.1),
    )
    boosted = fit_shallow_gradient_boosting(
        training_rows,
        training_targets,
        feature_names=("x1", "x2"),
        validation_rows=validation_rows,
        validation_targets=validation_targets,
        config=BoostedTreeConfig(
            maximum_depth=2,
            maximum_leaves=4,
            learning_rate=0.1,
            minimum_leaf_size=10,
            maximum_estimators=150,
            early_stopping_patience=15,
        ),
    )
    elastic_error = np.mean(
        (np.asarray(test_targets) - np.asarray(predict_model(elastic, test_rows).predictions)) ** 2
    )
    boosted_error = np.mean(
        (np.asarray(test_targets) - np.asarray(predict_model(boosted, test_rows).predictions)) ** 2
    )
    assert boosted_error < 0.45 * elastic_error
    assert 0 < boosted.best_iteration <= boosted.config.maximum_estimators


def test_elastic_net_keeps_correlated_predictors_and_is_predictive() -> None:
    rows = [
        {"x": float(index), "x_near_copy": float(index) + 0.001 * (index % 3)}
        for index in range(1, 101)
    ]
    targets = [2.0 * row["x"] + 3.0 * row["x_near_copy"] for row in rows]
    model = fit_elastic_net(
        rows,
        targets,
        feature_names=("x", "x_near_copy"),
        config=ElasticNetConfig(alpha=0.0001, l1_ratio=0.1),
    )
    assert model.transform.input_features == ("x", "x_near_copy")
    assert model.transform.output_features == (
        "x",
        "x_near_copy",
        "missing__x",
        "missing__x_near_copy",
    )
    assert len(model.coefficients) == 4
    prediction = np.asarray(predict_model(model, rows).predictions)
    assert np.mean((prediction - np.asarray(targets)) ** 2) < 0.1


def test_train_transform_is_isolated_and_missingness_has_explicit_columns() -> None:
    training = [{"x": 1.0}, {"x": None}, {"x": 3.0}]
    transform = fit_model_transform(training, feature_names=("x",))
    assert transform.medians == (2.0,)
    assert transform.output_features == ("x", "missing__x")
    original = apply_model_transform(transform, [{"x": None}, {"x": 10.0}])
    mutated = apply_model_transform(transform, [{"x": None}, {"x": 10_000_000.0}])
    assert transform.medians == (2.0,)
    assert original[0].tolist() == mutated[0].tolist()
    assert original[0, 1] != original[1, 1]
    assert math.isfinite(float(mutated[1, 0]))


def test_validation_only_early_stops_and_never_changes_transform() -> None:
    training_rows, training_targets = _interaction_rows(500)
    validation_rows, _ = _interaction_rows(100, offset=7_000)
    validation_targets = [0.0] * len(validation_rows)
    config = BoostedTreeConfig(
        maximum_depth=2,
        maximum_leaves=4,
        learning_rate=0.1,
        minimum_leaf_size=10,
        maximum_estimators=100,
        early_stopping_patience=5,
    )
    model = fit_shallow_gradient_boosting(
        training_rows,
        training_targets,
        feature_names=("x1", "x2"),
        validation_rows=validation_rows,
        validation_targets=validation_targets,
        config=config,
    )
    expected_transform = fit_model_transform(training_rows, feature_names=("x1", "x2"))
    assert model.transform == expected_transform
    assert len(model.validation_loss_by_iteration) < config.maximum_estimators
    assert len(model.trees) == model.best_iteration
    assert all(
        depth <= config.maximum_depth and leaves <= config.maximum_leaves
        for depth, leaves in (_tree_shape(tree) for tree in model.trees)
    )


def test_boosted_tree_minimum_leaf_floor_prevents_an_unsupported_split() -> None:
    rows = [{"x": float(index)} for index in range(15)]
    targets = [-1.0] * 7 + [1.0] * 8
    model = fit_shallow_gradient_boosting(
        rows,
        targets,
        feature_names=("x",),
        config=BoostedTreeConfig(maximum_estimators=1),
    )
    assert len(model.trees) == 1
    assert model.trees[0].is_leaf


@pytest.mark.parametrize("kind", ["elastic", "boosted"])
def test_models_are_deterministic_serializable_and_finite_with_missing_values(kind: str) -> None:
    rows = [
        {"x": None if index % 7 == 0 else float(index), "z": float(index % 5)}
        for index in range(80)
    ]
    targets = [float(index % 11) - 5.0 for index in range(80)]
    if kind == "elastic":
        first = fit_elastic_net(rows, targets, feature_names=("x", "z"))
        second = fit_elastic_net(rows, targets, feature_names=("x", "z"))
    else:
        config = BoostedTreeConfig(maximum_estimators=25, early_stopping_patience=5)
        first = fit_shallow_gradient_boosting(
            rows, targets, feature_names=("x", "z"), config=config
        )
        second = fit_shallow_gradient_boosting(
            rows, targets, feature_names=("x", "z"), config=config
        )
    first_json = predictive_model_to_json(first)
    assert first_json == predictive_model_to_json(second)
    restored = predictive_model_from_json(first_json)
    expected = predict_model(first, rows).predictions
    actual = predict_model(restored, rows).predictions
    assert actual == expected
    assert all(math.isfinite(value) for value in actual)


def test_baselines_metrics_and_frozen_grids_share_contracts() -> None:
    rows = [{"state": float(index)} for index in range(8)]
    targets = [float(index - 4) for index in range(8)]
    models = (
        zero_return_baseline(),
        fit_training_mean_baseline(targets),
        fit_state_linear_baseline(rows, targets, state_feature_names=("state",)),
    )
    for model in models:
        result = predict_model(model, rows)
        metrics = regression_metrics(targets, result.predictions, training_mean=np.mean(targets))
        assert len(result.predictions) == len(rows)
        assert metrics.observation_count == len(rows)
        assert math.isfinite(metrics.mean_squared_error)
    assert (0.01, 0.5) in ELASTIC_NET_CONFIG_GRID
    assert (2, 4, 0.05, 10) in BOOSTED_TREE_CONFIG_GRID
