from __future__ import annotations

import json
from pathlib import Path

import pytest

from shaurya.cli.research import main


def test_plan_cli_is_deterministic_and_reports_complete_cardinality(
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "plan-alpha",
        "--through",
        "2026-08-26",
        "--registry-dir",
        "registries",
    ]
    assert main(arguments) == 0
    first = capsys.readouterr().out
    assert main(arguments) == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["total_raw_hypothesis_count"] == 22_681
    assert payload["interactions"] == 4


def test_inspection_commands_report_missing_evidence_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "missing.jsonl"
    assert main(["alpha-ledger", "--ledger", str(ledger)]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["explain-alpha", "alpha-missing", "--ledger", str(ledger)]) == 0
    explanation = json.loads(capsys.readouterr().out)
    assert explanation["missing"]
    assert not ledger.exists()


def test_cli_exposes_every_frozen_research_operation(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])
    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    for command in (
        "plan-alpha",
        "mine-alpha",
        "evaluate-alpha",
        "alpha-ledger",
        "explain-alpha",
        "mechanism-status",
        "predictive-surface",
        "alpha-state",
    ):
        assert command in help_text
