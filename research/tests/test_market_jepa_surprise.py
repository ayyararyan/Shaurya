from __future__ import annotations

import numpy as np
import pytest

from shaurya.research.market_jepa_surprise import (
    aligned_latent_surprise,
    block_bootstrap_spearman,
    conditional_means_by_development_quintile,
)


def test_prediction_realization_alignment_for_surprise() -> None:
    prediction_ends = np.asarray([10, 11, 12], dtype=np.int64)
    realization_ends = prediction_ends + 6
    predictions = np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    realizations = predictions + np.asarray([[3.0, 4.0], [0.0, 2.0], [0.0, 0.0]])
    surprise = aligned_latent_surprise(
        predictions, realizations, prediction_ends, realization_ends, 6
    )
    np.testing.assert_allclose(surprise["l2"], [5.0, 2.0, 0.0])
    assert np.all((surprise["cosine"] >= 0.0) & (surprise["cosine"] <= 2.0))


def test_surprise_rejects_future_or_misaligned_prediction() -> None:
    vectors = np.ones((3, 2))
    prediction_ends = np.asarray([10, 11, 12], dtype=np.int64)
    with pytest.raises(ValueError, match="not causal"):
        aligned_latent_surprise(
            vectors,
            vectors,
            prediction_ends,
            np.asarray([15, 17, 18], dtype=np.int64),
            6,
        )


def test_normalized_surprise_is_not_embedding_norm_drift() -> None:
    predictions = np.asarray([[1.0, 0.0], [2.0, 0.0]])
    realizations = np.asarray([[2.0, 0.0], [4.0, 0.0]])
    ends = np.asarray([5, 6], dtype=np.int64)
    surprise = aligned_latent_surprise(predictions, realizations, ends, ends + 1, 1)
    np.testing.assert_allclose(surprise["unit_l2"], 0.0)
    np.testing.assert_allclose(surprise["cosine"], 0.0)
    assert np.all(surprise["l2"] > 0.0)


def test_block_bootstrap_preserves_pairs_and_is_reproducible() -> None:
    signal = np.arange(240, dtype=np.float64)
    target = signal * 3.0
    first = block_bootstrap_spearman(signal, target, block_rows=12, draws=100, seed=17)
    second = block_bootstrap_spearman(signal, target, block_rows=12, draws=100, seed=17)
    assert first == second
    assert first["spearman"] == pytest.approx(1.0)
    assert first["ci_low"] == pytest.approx(1.0)


def test_quintile_thresholds_are_fit_on_development_only() -> None:
    development = np.linspace(0.0, 99.0, 100)
    test = np.linspace(1000.0, 1009.0, 10)
    target = np.arange(10, dtype=np.float64)
    summary = conditional_means_by_development_quintile(development, test, target)
    assert max(summary["edges"]) < 100.0
    assert summary["rows"][-1]["samples"] == 10
