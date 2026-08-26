from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_research_distribution_version_matches_project_metadata() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert importlib.metadata.version("shaurya-research") == metadata["project"]["version"]


def test_research_declares_data_as_a_dependency() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "shaurya-data>=0.2.0" in metadata["project"]["dependencies"]
