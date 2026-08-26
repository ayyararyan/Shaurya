from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from shaurya.contracts.data import DataChannel, DatasetHandle, DatasetStatus
from shaurya.data import DataCatalog
from shaurya.data_cli.main import main


def _handle(tmp_path: Path) -> DatasetHandle:
    return DatasetHandle(
        dataset_id="sha-20260826T034500.000000Z-example",
        acquisition_fingerprint="a" * 64,
        source="dhan",
        status=DatasetStatus.COMPLETED,
        trading_date=date(2026, 8, 26),
        channels=(DataChannel.DEPTH20,),
        instrument_ids=("NSE:NSE_FNO:NIFTY:future:2026-08-27",),
        tape_path=str(tmp_path / "tape.jsonl"),
        started_at=datetime(2026, 8, 26, 3, 45, tzinfo=UTC),
        completed_at=datetime(2026, 8, 26, 10, 10, tzinfo=UTC),
        coverage_start=datetime(2026, 8, 26, 3, 45, tzinfo=UTC),
        coverage_end=datetime(2026, 8, 26, 10, 10, tzinfo=UTC),
        rows=1,
        bytes=1,
        tape_sha256="b" * 64,
    )


def test_catalog_get_resolves_by_date(tmp_path: Path, capsys: object) -> None:
    catalog_path = tmp_path / "datasets.jsonl"
    handle = _handle(tmp_path)
    DataCatalog(catalog_path).register(handle)

    result = main(
        [
            "catalog",
            "get",
            "--catalog",
            str(catalog_path),
            "--date",
            "2026-08-26",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["dataset_id"] == handle.dataset_id


def test_replay_rejects_nonpositive_limit(tmp_path: Path) -> None:
    catalog_path = tmp_path / "datasets.jsonl"
    handle = _handle(tmp_path)
    DataCatalog(catalog_path).register(handle)

    try:
        main(
            [
                "replay",
                "--catalog",
                str(catalog_path),
                "--dataset-id",
                handle.dataset_id,
                "--limit",
                "0",
            ]
        )
    except ValueError as exc:
        assert str(exc) == "replay limit must be positive"
    else:
        raise AssertionError("nonpositive replay limit was accepted")
