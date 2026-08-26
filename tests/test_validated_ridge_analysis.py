from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "validated_ridge_analysis.py"
SPEC = importlib.util.spec_from_file_location("validated_ridge", MODULE_PATH)
assert SPEC and SPEC.loader
validated = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validated
SPEC.loader.exec_module(validated)


def test_ridge_recovers_stable_signal() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(size=(1_000, 2))
    y = 1.5 * x[:, 0] - 0.5 * x[:, 1] + rng.normal(scale=0.05, size=1_000)
    prep = validated.fit_preprocessor(x[:800])
    beta = validated.fit_ridge(validated.transform(prep, x[:800]), y[:800], 1e-4)
    prediction = validated.predict(beta, validated.transform(prep, x[800:]))
    assert validated.r2(y[800:], prediction) > 0.99


def test_hac_interval_is_centered_on_point() -> None:
    contributions = np.asarray([1.0, 2.0, 3.0, 4.0])
    interval = validated.hac_interval(contributions, 10.0)
    point = contributions.sum() / 10.0
    assert interval[0] <= point <= interval[1]


def test_chronological_split_has_two_embargoes() -> None:
    second = 1_000_000_000
    timestamps = np.repeat(np.arange(600, dtype=np.int64) * 5 * second, 10)
    split = validated.chronological_split(timestamps)
    train = split["train"]
    validation = split["validation"]
    test = split["test"]
    assert isinstance(train, np.ndarray)
    assert isinstance(validation, np.ndarray)
    assert isinstance(test, np.ndarray)
    assert timestamps[train].max() < timestamps[validation].min()
    assert timestamps[validation].max() < timestamps[test].min()
