from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "compute_feature_correlations.py"
SPEC = importlib.util.spec_from_file_location("feature_correlations", MODULE_PATH)
assert SPEC and SPEC.loader
correlations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = correlations
SPEC.loader.exec_module(correlations)


def test_correlation_reports_linear_association() -> None:
    x = np.arange(10, dtype=float)
    assert correlations.correlation(x, 2.0 * x) == pytest.approx(1.0)
    assert correlations.correlation(x, -2.0 * x) == pytest.approx(-1.0)


def test_correlation_rejects_constant_input() -> None:
    x = np.ones(10)
    assert correlations.correlation(x, np.arange(10, dtype=float)) is None
