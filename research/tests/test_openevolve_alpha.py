from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from shaurya.research.openevolve_alpha import FEATURE_NAMES, _load_score


def _program(tmp_path: Path, expression: str) -> Path:
    arguments = ", ".join(FEATURE_NAMES)
    path = tmp_path / "candidate.py"
    path.write_text(f"def alpha_score({arguments}):\n    return {expression}\n", encoding="utf-8")
    return path


def test_restricted_formula_executes(tmp_path: Path) -> None:
    path = _program(tmp_path, "np.tanh(ret_5 + ret_15)")
    features = np.arange(42, dtype=float).reshape(3, 14)
    score, complexity = _load_score(path, features)
    np.testing.assert_allclose(score, np.tanh(features[:, 1] + features[:, 2]))
    assert complexity <= 80


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').getcwd()", "np.load('secret.npy')", "open('secret')"],
)
def test_file_and_import_access_is_rejected(tmp_path: Path, expression: str) -> None:
    with pytest.raises(ValueError):
        _load_score(_program(tmp_path, expression), np.ones((3, 14)))


def test_constant_formula_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="constant"):
        _load_score(_program(tmp_path, "ret_1 * 0.0"), np.ones((3, 14)))
