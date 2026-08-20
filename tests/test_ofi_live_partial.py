from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.cks_l1_ofi_scan import _parser as cks_parser
from scripts.cks_l1_ofi_scan import code_commit as cks_code_commit
from scripts.deepbook_ofi_scan import _parser as scalar_parser
from scripts.deepbook_ofi_scan import code_commit as scalar_code_commit
from scripts.ofi_horserace import _parser as horse_parser
from scripts.ofi_horserace import code_commit as horse_code_commit
from shaurya.contracts.timing import IST
from shaurya.data.ofi_live_partial import (
    EXPECTED_INSTRUMENT_ID,
    EXPECTED_RUN_ID,
    PROTOCOL_ID,
    inspect_late_partial_snapshot,
    iter_late_partial_rows,
    partial_claim,
)


def _row(event_type: str, stamp: datetime) -> dict[str, object]:
    depth = {"full": 5, "depth20": 20, "depth200": 200}.get(event_type, 0)
    return {
        "run_id": EXPECTED_RUN_ID,
        "instrument_id": EXPECTED_INSTRUMENT_ID,
        "broker_security_id": "58072",
        "event_type": event_type,
        "receive_ts": stamp.isoformat(),
        "bids": [{"price": 25_000 - index * 0.05} for index in range(depth)],
        "asks": [{"price": 25_001 + index * 0.05} for index in range(depth)],
    }


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_partial_snapshot_validates_identity_channels_and_final_clip(tmp_path: Path) -> None:
    started = datetime(2026, 8, 20, 9, 21, 46, 898569, tzinfo=IST)
    tape = tmp_path / f"tape_{EXPECTED_RUN_ID}.jsonl"
    rows = [
        _row("full", started),
        _row("depth20", started + timedelta(milliseconds=1)),
        _row("depth200", started + timedelta(milliseconds=2)),
        _row("depth200", datetime(2026, 8, 20, 15, 40, 1, tzinfo=IST)),
    ]
    _write(tape, rows)

    snapshot = inspect_late_partial_snapshot(tape)

    assert snapshot.rows == 3
    assert snapshot.channel_rows == {"full": 1, "depth20": 1, "depth200": 1}
    assert snapshot.complete_depth20_rows == 1
    assert snapshot.complete_depth200_rows == 1
    assert len(list(iter_late_partial_rows(tape))) == 3
    claim = partial_claim("source", snapshot)
    assert claim["protocol_id"] == PROTOCOL_ID
    assert claim["confirmatory_eligible"] is False
    assert claim["registered_replication_eligible"] is False
    assert claim["sig21_calibration_eligible"] is False
    assert claim["order_entry_enabled"] is False


def test_partial_snapshot_rejects_mixed_run_identity(tmp_path: Path) -> None:
    started = datetime(2026, 8, 20, 9, 21, 46, 898569, tzinfo=IST)
    tape = tmp_path / f"tape_{EXPECTED_RUN_ID}.jsonl"
    rows = [
        _row("full", started),
        _row("depth20", started + timedelta(milliseconds=1)),
        {**_row("depth200", started + timedelta(milliseconds=2)), "run_id": "wrong"},
    ]
    _write(tape, rows)

    with pytest.raises(ValueError, match="outside expected run"):
        inspect_late_partial_snapshot(tape)


@pytest.mark.parametrize("parser_factory", [scalar_parser, cks_parser, horse_parser])
def test_partial_and_registered_scopes_are_mutually_exclusive(parser_factory: object) -> None:
    parser = parser_factory()  # type: ignore[operator]
    with pytest.raises(SystemExit):
        parser.parse_args(["--full-session-replication", "--late-partial-exploratory"])


@pytest.mark.parametrize(
    "commit_reader",
    [scalar_code_commit, cks_code_commit, horse_code_commit],
)
def test_partial_scan_provenance_resolves_repo_commit_from_other_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commit_reader: object,
) -> None:
    monkeypatch.chdir(tmp_path)

    commit = commit_reader()  # type: ignore[operator]

    assert commit is not None
    assert len(commit) == 40


@pytest.mark.parametrize(
    "commit_reader",
    [scalar_code_commit, cks_code_commit, horse_code_commit],
)
def test_partial_scan_provenance_honours_validated_pinned_commit(
    monkeypatch: pytest.MonkeyPatch,
    commit_reader: object,
) -> None:
    pinned = "a" * 40
    monkeypatch.setenv("SHAURYA_CODE_COMMIT", pinned)

    assert commit_reader() == pinned  # type: ignore[operator]


def test_partial_scan_provenance_rejects_invalid_pinned_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHAURYA_CODE_COMMIT", "not-a-commit")

    with pytest.raises(ValueError, match="lowercase 40-character"):
        scalar_code_commit()
