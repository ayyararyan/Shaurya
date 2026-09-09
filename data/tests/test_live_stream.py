from __future__ import annotations

import asyncio
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetStatus,
    StorageFormat,
)
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data.access import DataAccess, DataCatalog
from shaurya.data.live_stream import (
    LiveRowPublisher,
    LiveRowSubscriber,
    live_stream_endpoint_path,
)

DATASET_ID = "sha-20260902T033000.000000Z-livefeed"
INSTRUMENT = "NSE:NSE_FNO:NIFTY:future:2026-09-29"


def _handle(tmp_path: Path) -> DatasetHandle:
    operational = tmp_path / "operational" / DATASET_ID
    operational.mkdir(parents=True)
    return DatasetHandle(
        schema_version="2.0.0",
        dataset_id=DATASET_ID,
        acquisition_fingerprint="live-test-fingerprint",
        source="dhan",
        status=DatasetStatus.ACTIVE,
        producer_pid=1,
        trading_date=date(2026, 9, 2),
        channels=(DataChannel.STANDARD,),
        instrument_ids=(INSTRUMENT,),
        storage_format=StorageFormat.SEGMENTED_PARQUET,
        storage_format_version="2.0.0",
        row_schema_version="2.0.0",
        dataset_name="nse-standard-live-test",
        row_run_id=DATASET_ID,
        dataset_path=str(tmp_path / "raw" / DATASET_ID),
        manifest_path=str(operational),
        started_at=datetime(2026, 9, 2, 3, 30, tzinfo=UTC),
    )


def _row(sequence: int) -> TapeRow:
    return TapeRow(
        run_id=DATASET_ID,
        receive_sequence=sequence,
        connection_epoch=1,
        source="dhan",
        event_type="quote",
        instrument_id=INSTRUMENT,
        broker_security_id="58072",
        exchange_segment="NSE_FNO",
        receive_ts=datetime(2026, 9, 2, 3, 30, tzinfo=UTC)
        + timedelta(milliseconds=sequence),
        raw_message_size_bytes=332,
        update_side="both",
        bids=(DepthLevel(25_000.0 + sequence, 100, 2),),
        asks=(DepthLevel(25_001.0 + sequence, 120, 3),),
    )


async def _subscriber(handle: DatasetHandle) -> LiveRowSubscriber:
    return await asyncio.to_thread(
        LiveRowSubscriber,
        handle,
        connect_timeout_seconds=1.0,
    )


async def _poll(subscriber: LiveRowSubscriber):  # type: ignore[no-untyped-def]
    return await asyncio.to_thread(subscriber.poll, timeout_seconds=1.0)


async def test_live_stream_delivers_rows_without_segment_publication(tmp_path: Path) -> None:
    handle = _handle(tmp_path)
    publisher = LiveRowPublisher(
        dataset_id=DATASET_ID,
        endpoint_path=live_stream_endpoint_path(handle),
        max_instruments=1,
    )
    await publisher.start()
    subscriber = await _subscriber(handle)
    try:
        snapshot = await _poll(subscriber)
        assert snapshot.message_type == "snapshot"
        assert snapshot.rows == ()

        publisher.publish(_row(1))
        update = await _poll(subscriber)
        assert update.message_type == "rows"
        assert [row.receive_sequence for row in update.rows] == [1]
        assert update.source_sequence == 1
        assert update.source_rows == 1
    finally:
        subscriber.close()
        await publisher.close()

    assert not live_stream_endpoint_path(handle).exists()


async def test_data_access_exposes_the_active_live_stream_facade(tmp_path: Path) -> None:
    handle = _handle(tmp_path)
    catalog = DataCatalog(tmp_path / "catalog" / "datasets")
    catalog.register(handle)
    publisher = LiveRowPublisher(
        dataset_id=DATASET_ID,
        endpoint_path=live_stream_endpoint_path(handle),
        max_instruments=1,
    )
    await publisher.start()
    subscriber = await asyncio.to_thread(
        DataAccess(catalog).live,
        handle,
        connect_timeout_seconds=1.0,
    )
    try:
        await _poll(subscriber)
        publisher.publish(_row(1))
        assert [row.receive_sequence for row in (await _poll(subscriber)).rows] == [1]
    finally:
        subscriber.close()
        await publisher.close()


async def test_late_subscriber_bootstraps_from_latest_row_per_instrument(
    tmp_path: Path,
) -> None:
    handle = _handle(tmp_path)
    publisher = LiveRowPublisher(
        dataset_id=DATASET_ID,
        endpoint_path=live_stream_endpoint_path(handle),
        max_instruments=1,
    )
    endpoint = await publisher.start()
    publisher.publish(_row(1))
    publisher.publish(_row(2))
    subscriber = await _subscriber(handle)
    try:
        snapshot = await _poll(subscriber)
        assert [row.receive_sequence for row in snapshot.rows] == [2]
        assert snapshot.source_sequence == 2
        assert snapshot.source_rows == 2
        assert stat.S_IMODE(live_stream_endpoint_path(handle).stat().st_mode) == 0o600
        assert endpoint.token not in repr(snapshot)
    finally:
        subscriber.close()
        await publisher.close()


async def test_slow_subscriber_is_coalesced_without_blocking_capture(tmp_path: Path) -> None:
    handle = _handle(tmp_path)
    publisher = LiveRowPublisher(
        dataset_id=DATASET_ID,
        endpoint_path=live_stream_endpoint_path(handle),
        max_instruments=1,
    )
    await publisher.start()
    subscriber = await _subscriber(handle)
    try:
        await _poll(subscriber)
        publisher.publish(_row(1))
        publisher.publish(_row(2))
        publisher.publish(_row(3))
        update = await _poll(subscriber)
        assert [row.receive_sequence for row in update.rows] == [3]
        assert update.coalesced_rows == 2
        assert publisher.metrics()["dropped_client_instruments"] == 0
    finally:
        subscriber.close()
        await publisher.close()
