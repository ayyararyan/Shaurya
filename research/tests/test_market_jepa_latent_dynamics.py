from __future__ import annotations

import json

import numpy as np
import pytest

from shaurya.research.market_jepa_latent_dynamics import (
    classify_stress_states,
    contiguous_analysis_ends,
    cross_seed_disagreement,
    fit_orthogonal_alignment,
    fit_stress_thresholds,
    latent_dynamics,
    write_frozen_config,
)


def test_velocity_and_acceleration_alignment() -> None:
    ends = np.arange(10, dtype=np.int64)
    embedding = np.column_stack((ends.astype(float) ** 2, np.zeros(10)))
    values = latent_dynamics(embedding, ends, np.asarray([4, 5]), lag_steps=2)
    np.testing.assert_allclose(values["velocity"], [12.0, 16.0])
    np.testing.assert_allclose(values["acceleration"], [8.0, 8.0])


def test_curvature_is_numerically_stable_for_zero_motion() -> None:
    ends = np.arange(8, dtype=np.int64)
    embedding = np.ones((8, 3))
    values = latent_dynamics(embedding, ends, np.asarray([4, 5, 6]), lag_steps=2)
    np.testing.assert_allclose(values["curvature"], 0.0)
    assert np.all(np.isfinite(values["curvature"]))


def test_cross_seed_uncertainty_alignment_and_reproducibility() -> None:
    rng = np.random.default_rng(7)
    reference = rng.normal(size=(100, 3))
    rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    source = reference @ rotation.T + 4.0
    alignment = fit_orthogonal_alignment(source, reference)
    aligned = alignment.transform(source)
    first = cross_seed_disagreement([reference, aligned])
    second = cross_seed_disagreement([reference, aligned])
    np.testing.assert_allclose(first, second)
    assert float(first.mean()) < 1e-20


def test_stress_thresholds_use_development_and_do_not_force_states() -> None:
    development = {
        name: np.arange(100, dtype=np.float64)
        for name in ("velocity", "surprise", "uncertainty", "disequilibrium")
    }
    thresholds = fit_stress_thresholds(development)
    values = {name: np.asarray([50.0]) for name in development}
    labels = classify_stress_states(values, thresholds)
    assert labels.tolist() == ["unclassified"]
    assert thresholds["velocity"]["high"] < 70.0


def test_incomplete_latent_history_is_rejected() -> None:
    with pytest.raises(ValueError, match="exact latent-history"):
        latent_dynamics(
            np.ones((4, 2)),
            np.asarray([0, 1, 3, 4], dtype=np.int64),
            np.asarray([4], dtype=np.int64),
            lag_steps=2,
        )


def test_incomplete_session_handling_rejects_gapped_tape() -> None:
    timestamps = np.arange(80, dtype=np.int64) * 5
    timestamps[30:] += 5
    with pytest.raises(ValueError, match="incomplete session"):
        contiguous_analysis_ends(
            timestamps,
            history_steps=20,
            future_steps=6,
            step_ns=5,
            minimum_samples=60,
        )


def test_frozen_config_serialization_is_deterministic_and_no_overwrite(tmp_path) -> None:
    path = tmp_path / "frozen_config.json"
    write_frozen_config(path, {"seeds": (1, 7), "array": np.asarray([2.0, 3.0])})
    assert json.loads(path.read_text()) == {"array": [2.0, 3.0], "seeds": [1, 7]}
    with pytest.raises(FileExistsError):
        write_frozen_config(path, {"changed": True})
