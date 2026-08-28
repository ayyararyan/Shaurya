from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from shaurya.research.market_jepa_outer_test import (
    FrozenRidge,
    file_sha256,
    fit_frozen_ridge,
    prospective_decision,
    semantic_sha256,
    verify_bundle,
)


def test_frozen_ridge_round_trip_matches_fitted_predictions(tmp_path: Path) -> None:
    rng = np.random.default_rng(17)
    features = rng.normal(size=(300, 4))
    target = features @ np.asarray([0.5, -0.25, 0.0, 0.1]) + 0.03
    probe = fit_frozen_ridge(features, target, 10.0)
    path = tmp_path / "probe.npz"
    probe.save(path)
    restored = FrozenRidge.load(path)
    np.testing.assert_allclose(restored.predict(features), probe.predict(features))
    assert restored.target_median == probe.target_median


def test_decision_requires_four_seeds_at_both_horizons() -> None:
    metrics: dict[str, object] = {}
    for seed in (1, 7, 23, 42, 101):
        metrics[str(seed)] = {
            horizon: {
                "handcrafted_base": {"mae_skill": 0.01},
                "base_plus_pca": {"mae_skill": 0.02},
                "base_plus_jepa": {"mae_skill": 0.03},
            }
            for horizon in ("30s", "300s")
        }
    assert prospective_decision(metrics)["verdict"] == "KEEP_JEPA"
    for seed in (1, 7):
        metrics[str(seed)]["300s"]["base_plus_jepa"]["mae_skill"] = 0.0  # type: ignore[index]
    result = prospective_decision(metrics)
    assert result["verdict"] == "DROP_JEPA"
    assert result["qualifying_seed_counts"]["300s"] == 3


def test_bundle_verification_detects_artifact_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"frozen")
    manifest = {"artifact_sha256": {"weights.bin": file_sha256(artifact)}}
    manifest["semantic_sha256"] = semantic_sha256(manifest)
    verify_bundle(tmp_path, manifest)
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_bundle(tmp_path, manifest)


def test_manifest_semantics_are_canonical() -> None:
    left = {"b": [2, 1], "a": {"x": True}}
    right = json.loads('{"a":{"x":true},"b":[2,1]}')
    assert semantic_sha256(left) == semantic_sha256(right)
