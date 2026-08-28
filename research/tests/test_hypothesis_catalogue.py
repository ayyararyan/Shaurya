from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_checked_in_hypothesis_catalogue_is_self_consistent() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    validator = (
        repository_root
        / "research"
        / "hypothesis_feature_research"
        / "tools"
        / "catalogue.py"
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [sys.executable, str(validator), "--check"],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "catalogue valid:" in completed.stdout
