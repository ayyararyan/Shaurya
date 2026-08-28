from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetHandle, DatasetRequest, DatasetStatus
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data import DataCaptureSession, DataCatalog
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


def _parquet_handle(tmp_path: Path) -> tuple[Path, DatasetHandle]:
    catalog_path = tmp_path / "catalog"
    request = DatasetRequest(
        consumer="CLI-TEST",
        purpose="CLI acceptance coverage",
        trading_date=date(2026, 8, 26),
        channels=(DataChannel.DEPTH20,),
        instrument_ids=("NSE:NSE_FNO:NIFTY:future:2026-08-27",),
    )
    session = DataCaptureSession.create(
        catalog=DataCatalog(catalog_path),
        request=request,
        output_root=tmp_path / "raw",
        run_id=RunId("sha-20260826T034500.000000Z-cafebabe"),
        segment_max_rows=1,
    )
    session.write(
        TapeRow(
            run_id=session.dataset_id,
            receive_sequence=1,
            connection_epoch=1,
            source="synthetic",
            event_type="depth20",
            instrument_id=request.instrument_ids[0],
            broker_security_id="58072",
            exchange_segment="NSE_FNO",
            receive_ts=datetime(2026, 8, 26, 3, 45, tzinfo=UTC),
            raw_message_size_bytes=100,
            update_side="both",
            bids=(DepthLevel(25_000, 10, 1),),
            asks=(DepthLevel(25_001, 11, 1),),
        )
    )
    return catalog_path, session.close()


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


def test_list_inspect_validate_preview_replay_and_export(tmp_path: Path, capsys: Any) -> None:
    catalog_path, handle = _parquet_handle(tmp_path)

    assert main(["catalog", "list", "--catalog", str(catalog_path)]) == 0
    assert handle.dataset_name in capsys.readouterr().out
    assert main(["inspect", "--catalog", str(catalog_path), "--dataset-id", handle.dataset_id]) == 0
    assert "segmented_parquet" in capsys.readouterr().out
    assert (
        main(["validate", "--catalog", str(catalog_path), "--dataset-id", handle.dataset_id]) == 0
    )
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["preview", "--catalog", str(catalog_path), "--dataset-id", handle.dataset_id]) == 0
    assert "SEQ\tRECEIVE_TS" in capsys.readouterr().out
    assert main(["replay", "--catalog", str(catalog_path), "--dataset-id", handle.dataset_id]) == 0
    assert json.loads(capsys.readouterr().out)["receive_sequence"] == 1
    export = tmp_path / "export.csv"
    assert (
        main(
            [
                "export",
                "--catalog",
                str(catalog_path),
                "--dataset-id",
                handle.dataset_id,
                "--output",
                str(export),
            ]
        )
        == 0
    )
    assert "receive_sequence" in export.read_text(encoding="utf-8")
