from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetRequest,
    DatasetStatus,
    StorageFormat,
)
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data.access import (
    DataAccess,
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
    DatasetUnavailableError,
    LegacySourceState,
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


def _write_completed_legacy(path: Path, rows: tuple[TapeRow, ...]) -> None:
    path.write_text("".join(json.dumps(row.to_dict()) + "\n" for row in rows), encoding="utf-8")
    events = (
        {"event_type": "run_started"},
        {
            "event_type": "artifact_closed",
            "artifact": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        {"event_type": "run_completed"},
    )
    manifest = path.parent / f"manifest_{RUN_ID}.jsonl"
    manifest.write_text(
        "".join(
            json.dumps(
                {
                    "run_id": str(RUN_ID),
                    "manifest_sequence": sequence,
                    **event,
                }
            )
            + "\n"
            for sequence, event in enumerate(events, 1)
        ),
        encoding="utf-8",
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
        segment_max_rows=2,
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


def test_concurrent_exact_acquisitions_create_only_one_active_dataset(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path / "catalog" / "datasets")

    def create() -> DataCaptureSession | DatasetAlreadyActiveError:
        try:
            return DataCaptureSession.create(
                catalog=catalog,
                request=_request("CONCURRENT"),
                output_root=tmp_path / "raw",
            )
        except DatasetAlreadyActiveError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _item: create(), range(2)))
    sessions = [item for item in outcomes if isinstance(item, DataCaptureSession)]
    conflicts = [item for item in outcomes if isinstance(item, DatasetAlreadyActiveError)]

    assert len(sessions) == 1
    assert len(conflicts) == 1
    assert conflicts[0].handle.dataset_id == sessions[0].dataset_id
    sessions[0].close(invalidation_reason="test cleanup")


def test_dead_local_claim_publishes_orphaned_terminal_state(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path / "catalog")
    request = _request("ORPHAN")
    handle = DatasetHandle(
        dataset_id=str(RUN_ID),
        acquisition_fingerprint=request.acquisition_fingerprint,
        source="dhan",
        status=DatasetStatus.ACTIVE,
        producer_pid=999_999_999,
        producer_host=socket.gethostname(),
        trading_date=request.trading_date,
        channels=request.channels,
        instrument_ids=request.instrument_ids,
        tape_path=str(tmp_path / "orphan.jsonl"),
        started_at=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
    )
    catalog.register(handle)
    catalog.acquire_claim(request, dataset_id=handle.dataset_id, producer_pid=999_999_999)

    assert catalog.claim_handle(request) is None
    assert catalog.get(handle.dataset_id).status is DatasetStatus.ORPHANED


def test_active_dataset_follow_reads_rows_written_after_handle_resolution(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path / "catalog" / "datasets.jsonl")
    session = DataCaptureSession.create(
        catalog=catalog,
        request=_request("SUR-09"),
        output_root=tmp_path / "raw",
        run_id=RUN_ID,
        fsync_every=1,
        segment_max_rows=1,
    )
    access = DataAccess(catalog)
    signal_handle = access.request(_request("SIG-23"))
    follower = access.follow(signal_handle)
    session.write(_row(1, channel=DataChannel.STANDARD, seconds=0))

    batch = follower.poll()

    assert [row["receive_sequence"] for row in batch.rows] == [1]
    assert signal_handle.dataset_id == session.dataset_id
    session.close(invalidation_reason="test cleanup")


def test_completed_capture_has_segment_hashes_and_filtered_retrieval(tmp_path: Path) -> None:
    access, handle = _completed_dataset(tmp_path)
    assert handle.status is DatasetStatus.COMPLETED
    assert handle.rows == 3
    assert handle.storage_format is StorageFormat.SEGMENTED_PARQUET
    assert handle.dataset_digest
    assert len(handle.segments) == 2
    assert all(segment.sha256 for segment in handle.segments)
    assert handle.tape_path is None
    assert handle.index_path is None

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


def test_parquet_capture_is_already_compressed_and_archive_promotion_is_noop(
    tmp_path: Path,
) -> None:
    access, handle = _completed_dataset(tmp_path, archive=True)
    assert handle.archive_path is None
    assert access.promote_archive(handle) == handle
    replayed = tuple(access.rows(handle))
    assert [row.receive_sequence for row in replayed] == [1, 2, 3]


def test_published_hashes_fail_closed_after_segment_or_dataset_tampering(tmp_path: Path) -> None:
    access, handle = _completed_dataset(tmp_path)
    with Path(handle.segments[0].path).open("ab") as target:
        target.write(b"tamper")
    with pytest.raises(TapeIntegrityError, match="segment hash"):
        tuple(access.rows(handle))

    access, handle = _completed_dataset(tmp_path / "second")
    forged = DatasetHandle.model_validate(
        handle.model_copy(update={"dataset_digest": "0" * 64}).model_dump()
    )
    with pytest.raises(TapeIntegrityError, match="dataset digest"):
        tuple(access.rows(forged))


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
    _write_completed_legacy(
        tape,
        tuple(_row(index, channel=DataChannel.DEPTH20, seconds=index) for index in (1, 2)),
    )
    access = DataAccess(DataCatalog(tmp_path / "catalog.jsonl"))
    handle = access.adopt_legacy_tape(
        tape,
        source_state=LegacySourceState.COMPLETED,
        consumer="SIG-23",
        purpose="legacy evidence",
    )
    assert handle.source == "legacy_tape"
    assert Path(handle.index_path or "").is_file()
    assert [row.receive_sequence for row in access.rows(handle)] == [1, 2]


def test_completed_legacy_adoption_rejects_torn_or_noncompleted_evidence(
    tmp_path: Path,
) -> None:
    tape = tmp_path / "legacy.jsonl"
    tape.write_text(json.dumps(_row(1, channel=DataChannel.DEPTH20, seconds=1).to_dict()))
    access = DataAccess(DataCatalog(tmp_path / "catalog.jsonl"))

    with pytest.raises(TapeIntegrityError, match="torn"):
        access.adopt_legacy_tape(
            tape,
            source_state=LegacySourceState.COMPLETED,
            consumer="SIG-23",
            purpose="legacy evidence",
        )
    with pytest.raises(ValueError, match="explicitly completed"):
        access.adopt_legacy_tape(
            tape,
            source_state=LegacySourceState.CANCELLED,
            consumer="SIG-23",
            purpose="legacy evidence",
        )


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
        root / "data_cli" / "capture_dhan.py",
        root / "data_cli" / "capture_chain.py",
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


def test_catalog_resolves_latest_completed_dataset_by_trading_date(tmp_path: Path) -> None:
    access, handle = _completed_dataset(tmp_path)

    resolved = access.catalog.get_dataset(trading_date=date(2026, 8, 21))

    assert resolved.dataset_id == handle.dataset_id


def test_data_source_never_imports_research() -> None:
    root = Path(__file__).parents[1] / "src"
    forbidden = ("shaurya.analytics", "shaurya.signals", "shaurya.surfaces")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
            if module is not None and module.startswith(forbidden):
                violations.append(f"{path.relative_to(root)} imports {module}")
            violations.extend(
                f"{path.relative_to(root)} imports {name}"
                for name in names
                if name.startswith(forbidden)
            )
    assert violations == []
