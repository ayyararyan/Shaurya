from __future__ import annotations

import ast
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetRequest,
    DatasetStatus,
)
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data.access import (
    DataAccess,
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
    DatasetUnavailableError,
)
from shaurya.data.tape import TapeIntegrityError

RUN_ID = RunId("sha-20260821T030000.000000Z-1234abcd")
INSTRUMENT = "NSE:NSE_FNO:NIFTY:future:2026-08-25"


def _request(
    consumer: str = "SUR-09",
    *,
    channels: tuple[DataChannel, ...] = (DataChannel.STANDARD, DataChannel.DEPTH20),
    allow_active: bool = True,
) -> DatasetRequest:
    return DatasetRequest(
        consumer=consumer,
        purpose=f"{consumer} test",
        trading_date=date(2026, 8, 21),
        channels=channels,
        instrument_ids=(INSTRUMENT,),
        allow_active=allow_active,
    )


def _row(sequence: int, *, channel: DataChannel, seconds: int) -> TapeRow:
    event_type = "quote" if channel is DataChannel.STANDARD else str(channel)
    return TapeRow(
        run_id=str(RUN_ID),
        receive_sequence=sequence,
        connection_epoch=1,
        source="dhan",
        event_type=event_type,
        instrument_id=INSTRUMENT,
        broker_security_id="58072",
        exchange_segment="NSE_FNO",
        receive_ts=datetime(2026, 8, 21, 3, 0, tzinfo=UTC) + timedelta(seconds=seconds),
        raw_message_size_bytes=332,
        update_side="both",
        bids=(DepthLevel(25_000.0 + seconds, 100, 2),),
        asks=(DepthLevel(25_001.0 + seconds, 120, 3),),
    )


def _completed_dataset(
    tmp_path: Path, *, archive: bool = False
) -> tuple[DataAccess, DatasetHandle]:
    catalog = DataCatalog(tmp_path / "catalog" / "datasets.jsonl")
    session = DataCaptureSession.create(
        catalog=catalog,
        request=_request(),
        output_root=tmp_path / "raw",
        run_id=RUN_ID,
        fsync_every=1,
        index_stride_rows=2,
    )
    session.write(_row(1, channel=DataChannel.STANDARD, seconds=0))
    session.write(_row(2, channel=DataChannel.DEPTH20, seconds=1))
    session.write(_row(3, channel=DataChannel.DEPTH20, seconds=2))
    return DataAccess(catalog), session.close(archive=archive)


def test_request_fingerprint_excludes_consumer_and_purpose() -> None:
    surface = _request("SUR-09")
    signal = _request("SIG-23")
    assert surface.acquisition_fingerprint == signal.acquisition_fingerprint
    assert surface.consumer != signal.consumer


def test_handle_coverage_reuses_active_superset() -> None:
    request = _request("SIG-23", channels=(DataChannel.DEPTH20,))
    handle = DatasetHandle(
        dataset_id=str(RUN_ID),
        acquisition_fingerprint=_request().acquisition_fingerprint,
        source="dhan",
        status=DatasetStatus.ACTIVE,
        producer_pid=1,
        trading_date=request.trading_date,
        channels=(DataChannel.STANDARD, DataChannel.DEPTH20),
        instrument_ids=(INSTRUMENT,),
        tape_path="/tmp/test-tape.jsonl",
        started_at=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
    )
    assert handle.satisfies(request)
    assert not handle.satisfies(_request(allow_active=False))


def test_capture_claim_is_published_and_duplicate_is_blocked(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path / "catalog" / "datasets.jsonl")
    session = DataCaptureSession.create(
        catalog=catalog,
        request=_request("SUR-09"),
        output_root=tmp_path / "raw",
        run_id=RUN_ID,
    )
    resolved = DataAccess(catalog).request(_request("SIG-23"))
    assert resolved.dataset_id == str(RUN_ID)
    assert resolved.status is DatasetStatus.ACTIVE
    with pytest.raises(DatasetAlreadyActiveError) as error:
        DataCaptureSession.create(
            catalog=catalog,
            request=_request("ANL-08"),
            output_root=tmp_path / "other-raw",
        )
    assert error.value.handle.dataset_id == str(RUN_ID)
    session.close(invalidation_reason="test cleanup")


def test_active_dataset_follow_reads_rows_written_after_handle_resolution(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path / "catalog" / "datasets.jsonl")
    session = DataCaptureSession.create(
        catalog=catalog,
        request=_request("SUR-09"),
        output_root=tmp_path / "raw",
        run_id=RUN_ID,
        fsync_every=1,
    )
    access = DataAccess(catalog)
    signal_handle = access.request(_request("SIG-23"))
    follower = access.follow(signal_handle)
    session.write(_row(1, channel=DataChannel.STANDARD, seconds=0))

    batch = follower.poll()

    assert [row["receive_sequence"] for row in batch.rows] == [1]
    assert signal_handle.dataset_id == session.dataset_id
    session.close(invalidation_reason="test cleanup")


def test_completed_capture_has_index_hashes_and_filtered_retrieval(tmp_path: Path) -> None:
    access, handle = _completed_dataset(tmp_path)
    assert handle.status is DatasetStatus.COMPLETED
    assert handle.rows == 3
    assert handle.tape_sha256
    assert handle.index_sha256
    assert handle.index_path is not None
    payload = json.loads(Path(handle.index_path).read_text(encoding="utf-8"))
    assert payload["channel_rows"] == {"depth20": 2, "standard": 1}

    rows = tuple(
        access.rows(
            handle,
            start=datetime(2026, 8, 21, 3, 0, 1, tzinfo=UTC),
            channels=(DataChannel.DEPTH20,),
        )
    )
    assert [row.receive_sequence for row in rows] == [2, 3]
    resolved = access.request(_request("SIG-23", allow_active=False))
    assert resolved.dataset_id == handle.dataset_id


def test_lossless_cold_archive_remains_replayable_without_warm_copy(tmp_path: Path) -> None:
    access, handle = _completed_dataset(tmp_path, archive=True)
    assert handle.archive_path is not None
    warm = Path(handle.tape_path)
    warm.unlink()
    replayed = tuple(access.rows(handle))
    assert [row.receive_sequence for row in replayed] == [1, 2, 3]


def test_published_hashes_fail_closed_after_tape_or_index_tampering(tmp_path: Path) -> None:
    access, handle = _completed_dataset(tmp_path)
    index_path = Path(handle.index_path or "")
    index_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(TapeIntegrityError, match="index hash"):
        tuple(access.rows(handle))

    access, handle = _completed_dataset(tmp_path / "second")
    with Path(handle.tape_path).open("ab") as target:
        target.write(b"{}\n")
    with pytest.raises(TapeIntegrityError, match="tape hash"):
        tuple(access.rows(handle))


def test_dead_active_producer_is_not_reused(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path / "catalog.jsonl")
    request = _request()
    catalog.register(
        DatasetHandle(
            dataset_id=str(RUN_ID),
            acquisition_fingerprint=request.acquisition_fingerprint,
            source="dhan",
            status=DatasetStatus.ACTIVE,
            producer_pid=999_999_999,
            trading_date=request.trading_date,
            channels=request.channels,
            instrument_ids=request.instrument_ids,
            tape_path=str(tmp_path / "orphan.jsonl"),
            started_at=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
        )
    )
    with pytest.raises(DatasetUnavailableError):
        DataAccess(catalog).request(request)


def test_legacy_tape_is_adopted_indexed_and_then_read_through_dat(tmp_path: Path) -> None:
    tape = tmp_path / "legacy.jsonl"
    tape.write_text(
        "".join(
            json.dumps(_row(index, channel=DataChannel.DEPTH20, seconds=index).to_dict()) + "\n"
            for index in (1, 2)
        ),
        encoding="utf-8",
    )
    access = DataAccess(DataCatalog(tmp_path / "catalog.jsonl"))
    handle = access.adopt_legacy_tape(tape, consumer="SIG-23", purpose="legacy evidence")
    assert handle.source == "legacy_tape"
    assert Path(handle.index_path or "").is_file()
    assert [row.receive_sequence for row in access.rows(handle)] == [1, 2]


def test_active_legacy_tape_is_registered_and_torn_tail_is_not_consumed(tmp_path: Path) -> None:
    tape = tmp_path / "active-legacy.jsonl"
    with tape.open("wb") as target:
        for index in (1, 2):
            target.write(
                (
                    json.dumps(_row(index, channel=DataChannel.DEPTH20, seconds=index).to_dict())
                    + "\n"
                ).encode()
            )
        target.write(b'{"run_id":')
    access = DataAccess(DataCatalog(tmp_path / "catalog.jsonl"))

    handle = access.adopt_active_legacy_tape(
        tape,
        consumer="ANL-06-LIVE-D38-D39-D40",
        purpose="live complete-prefix test",
        producer_pid=os.getpid(),
    )

    assert handle.status is DatasetStatus.ACTIVE
    assert handle.producer_pid == os.getpid()
    assert handle.tape_sha256 is None
    assert handle.index_path is None
    assert [row["receive_sequence"] for row in access.follow(handle).poll().rows] == [1, 2]


def test_only_dat_boundary_imports_dhan_adapters() -> None:
    root = Path(__file__).parents[1] / "src" / "shaurya"
    permitted = {
        root / "cli" / "capture_dhan.py",
        root / "cli" / "capture_chain.py",
    }
    forbidden_prefixes = ("shaurya.data.dhan_client", "shaurya.data.dhan_stream")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        if path in permitted or (root / "data") in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
            if module is not None and module.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(root)} imports {module}")
            for name in names:
                if name.startswith(forbidden_prefixes):
                    violations.append(f"{path.relative_to(root)} imports {name}")
    assert violations == []


def test_surface_ofi_and_controller_select_data_through_dat() -> None:
    root = Path(__file__).parents[1]
    surface = (root / "src/shaurya/cli/surface_dashboard.py").read_text(encoding="utf-8")
    ofi = (root / "src/shaurya/cli/ofi_dashboard.py").read_text(encoding="utf-8")
    live_ofi = (root / "src/shaurya/cli/live_ofi_studies.py").read_text(encoding="utf-8")
    controller = (root / "scripts/ofi_full_session_controller.py").read_text(encoding="utf-8")
    for source in (surface, ofi, live_ofi, controller):
        assert "DataAccess" in source
        assert "DataCatalog" in source
        assert "DhanCredentials" not in source
        assert "DhanLiveStream" not in source
        assert "JsonlTapeWriter" not in source
    assert "capture_root.glob" not in controller
    assert '"--data-catalog"' in controller
