from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_data_distribution_version_matches_project_metadata() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert importlib.metadata.version("shaurya-data") == metadata["project"]["version"]


def test_security_policy_records_required_permissions() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "credential **handle**, never a credential value" in policy
    assert "mode `700`" in policy
    assert "mode `600`" in policy
