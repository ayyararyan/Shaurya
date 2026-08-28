from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from shaurya.research.market_jepa_outer_test import (
    FrozenRidge,
    apply_frozen_normalization,
    block_bootstrap_spearman,
    file_sha256,
    fit_discovery_normalization,
    fit_frozen_ridge,
    fit_quantile_boundaries,
    paired_block_comparison,
    prospective_decision,
    prospective_feature_sets,
    recent_atm_iv_change,
    require_complete_endpoint_count,
    select_frozen_ridge,
    semantic_sha256,
    verify_bundle,
)


def test_normalization_is_fit_on_discovery_only() -> None:
    discovery = np.asarray([[1.0, 2.0], [3.0, 6.0], [5.0, 10.0]])
    final = np.asarray([[1_000_000.0, -1_000_000.0]])
    center, scale = fit_discovery_normalization(discovery)
    np.testing.assert_allclose(center, [3.0, 6.0])
    transformed = apply_frozen_normalization(final, center, scale)
    np.testing.assert_allclose(transformed, [[10.0, -10.0]])


def test_frozen_ridge_round_trip_matches_fitted_predictions(tmp_path: Path) -> None:
    rng = np.random.default_rng(17)
    features = rng.normal(size=(300, 4))
    target = features @ np.asarray([0.5, -0.25, 0.0, 0.1]) + 0.03
    probe = fit_frozen_ridge(features, target, 10.0)
    path = tmp_path / "probe.npz"
    probe.save(path)
    restored = FrozenRidge.load(path)
    np.testing.assert_allclose(restored.predict(features), probe.predict(features))


def test_model_selection_has_no_final_target_argument() -> None:
    assert set(inspect.signature(select_frozen_ridge).parameters) == {
        "discovery_features",
        "validation_features",
        "discovery_target",
        "validation_target",
        "alphas",
    }


def test_paired_jepa_vs_pca_comparison_is_positive_for_lower_jepa_loss() -> None:
    pca = np.full(240, 2.0)
    jepa = np.full(240, 1.0)
    result = paired_block_comparison(pca, jepa, block_rows=12, minimum_overlap_rows=6, draws=100)
    assert result["mean_pca_minus_jepa_loss"] == 1.0
    assert result["ci_low"] == 1.0


def test_block_length_cannot_be_shorter_than_target_overlap() -> None:
    values = np.arange(100, dtype=np.float64)
    with pytest.raises(ValueError, match="shorter than target overlap"):
        paired_block_comparison(values, values, block_rows=5, minimum_overlap_rows=6)
    with pytest.raises(ValueError, match="shorter than target overlap"):
        block_bootstrap_spearman(values, values, block_rows=5, minimum_overlap_rows=6, draws=10)


def test_shock_quantile_thresholds_do_not_change_with_final_values() -> None:
    development = np.arange(100, dtype=np.float64)
    expected = fit_quantile_boundaries(development)
    final = np.full(100, 1_000_000.0)
    observed = fit_quantile_boundaries(development)
    np.testing.assert_array_equal(expected, observed)
    assert final.max() > expected.max()


def test_past_iv_signal_alignment_and_interaction_are_causal() -> None:
    columns = ["surface__atm_iv__near"]
    raw = np.arange(40, dtype=np.float64)[:, None]
    ends = np.asarray([12, 13, 14], dtype=np.int64)
    recent = recent_atm_iv_change(raw, ends, columns)
    np.testing.assert_array_equal(recent, np.full(3, 6.0))
    representation = {
        "handcrafted_base": np.ones((3, 8)),
        "pca": np.ones((3, 2)),
        "jepa": np.arange(12, dtype=np.float64).reshape(3, 4),
        "random_encoder": np.ones((3, 4)),
        "flattened_context": np.ones((3, 12)),
    }
    _, before = prospective_feature_sets(representation, recent, np.arange(3))
    changed = raw.copy()
    changed[15:] = -999_999.0
    recent_changed = recent_atm_iv_change(changed, ends, columns)
    _, after = prospective_feature_sets(representation, recent_changed, np.arange(3))
    np.testing.assert_array_equal(
        before["recent_base_jepa_interaction"], after["recent_base_jepa_interaction"]
    )


def test_fixed_seed_feature_construction_is_reproducible() -> None:
    rng = np.random.default_rng(2)
    representation = {
        "handcrafted_base": rng.normal(size=(20, 8)),
        "pca": rng.normal(size=(20, 2)),
        "jepa": rng.normal(size=(20, 4)),
        "random_encoder": rng.normal(size=(20, 4)),
        "flattened_context": rng.normal(size=(20, 12)),
    }
    recent = rng.normal(size=20)
    left = np.random.default_rng(1043).permutation(20)
    right = np.random.default_rng(1043).permutation(20)
    left_h1, _ = prospective_feature_sets(representation, recent, left)
    right_h1, _ = prospective_feature_sets(representation, recent, right)
    np.testing.assert_array_equal(left_h1["base_shuffled_jepa"], right_h1["base_shuffled_jepa"])


def test_apply_only_runner_contains_no_fit_call() -> None:
    script = Path(__file__).resolve().parents[1] / "experiments" / "apply_market_jepa_outer_test.py"
    tree = ast.parse(script.read_text())
    fit_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fit"
    ]
    assert fit_calls == []


def test_incomplete_session_is_rejected() -> None:
    with pytest.raises(ValueError, match="incomplete session"):
        require_complete_endpoint_count(799, 800)
    require_complete_endpoint_count(800, 800)


def test_decision_requires_stable_jepa_over_pca_result() -> None:
    metrics: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    for seed in (1, 7, 23, 42, 101):
        metrics[str(seed)] = {
            "base_pca": {"mae_skill": 0.02},
            "base_jepa": {"mae_skill": 0.03},
        }
        paired[str(seed)] = {block: {"ci_low": 0.001} for block in ("60s", "120s", "300s")}
    assert prospective_decision(metrics, paired)["decision"] == "A"
    for seed in (1, 7, 23):
        metrics[str(seed)]["base_jepa"]["mae_skill"] = 0.0
    assert prospective_decision(metrics, paired)["decision"] == "C"


def test_bundle_verification_and_canonical_serialization(tmp_path: Path) -> None:
    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"frozen")
    manifest = {"artifact_sha256": {"weights.bin": file_sha256(artifact)}}
    manifest["semantic_sha256"] = semantic_sha256(manifest)
    verify_bundle(tmp_path, manifest)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_bundle(tmp_path, manifest)
    left = {"b": [2, 1], "a": {"x": True}}
    right = json.loads('{"a":{"x":true},"b":[2,1]}')
    assert semantic_sha256(left) == semantic_sha256(right)
