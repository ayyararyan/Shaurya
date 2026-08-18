from __future__ import annotations

import re
import tomllib
from pathlib import Path

import shaurya

ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_agree() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = metadata["project"]["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_versions = re.findall(r"^## v([^ ]+) —", changelog, flags=re.MULTILINE)

    assert shaurya.__version__ == project_version
    assert release_versions[0] == project_version


def test_secret_policy_records_required_permissions() -> None:
    policy = (ROOT / "docs" / "SECRETS.md").read_text(encoding="utf-8")

    assert "credential **handle**, never a credential value" in policy
    assert "mode `700`" in policy
    assert "mode `600`" in policy
