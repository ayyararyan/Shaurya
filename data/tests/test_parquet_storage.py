from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from shaurya.contracts.artifacts import RunId, sha256_file
from shaurya.contracts.data import (
    DataChannel,
    DatasetHandle,
    DatasetRequest,
    DatasetStatus,
    StorageFormat,
)
from shaurya.contracts.tape import DepthLevel, QualityFlag, TapeRow, TradeSide
from shaurya.data import (
    MARKET_EVENT_SCHEMA,
    DataAccess,
    DataCaptureSession,
    DataCatalog,
    LegacySourceState,
    SegmentedParquetWriter,
    TapeIntegrityError,
    iter_parquet_rows,
)
from shaurya.data.metadata import ParquetCaptureManifest, decode_mapping_fields
from shaurya.data.parquet import (
    human_dataset_name,
    inventory_recovery,
    validate_parquet_schema,
)

RUN_ID = RunId("sha-20260827T034500.000000Z-1234abcd")
INSTRUMENT = "NSE:NSE_FNO:NIFTY:future:2026-08-27"


def test_operational_parquet_round_trip_preserves_empty_and_populated_mappings(
    tmp_path: Path,
) -> None:
    payloads = (
        {"run_id": "empty", "reconnect_attempts": {}, "source_packets": {}},
        {
            "run_id": "populated",
            "reconnect_attempts": {"depth20": 2},
            "source_packets": {"standard": 17},
        },
    )
    tables: list[pa.Table] = []
    for payload in payloads:
        manifest = ParquetCaptureManifest(
            tmp_path / str(payload["run_id"]), run_id=str(payload["run_id"])
        )
        path = manifest.write_record("capture_metrics", payload)
        table = pq.read_table(path)
        tables.append(table)
        restored = decode_mapping_fields(table.to_pylist()[0], table.schema.metadata or {})
        assert restored == payload

    assert tables[0].schema.field("reconnect_attempts").type == pa.string()
    assert (
        tables[0].schema.field("reconnect_attempts").type
        == tables[1].schema.field("reconnect_attempts").type
    )


def test_operational_parquet_round_trip_preserves_list_and_list_of_struct_fields(
    tmp_path: Path,
) -> None:
    """Regression for chain-capture's ``chain_coverage`` record.

    PyArrow silently renames a Parquet list's child field from ``item`` to
    ``element`` on every write/read round trip. Left un-encoded, any top-level
    list payload field (flat or list-of-dict) previously failed
    ``ParquetCaptureManifest.write_record``'s post-write schema-equality check.
    """

    payload = {
        "run_id": "chain-shape",
        "silent_instruments": ["NSE:NSE_FNO:NIFTY:option:2026-09-24:25000:CE"],
        "universes": [
            {
                "underlying": "NIFTY",
                "spot_reference": 25000.0,
                "expiries": ["2026-09-24"],
                "strike_window_fraction": 0.06,
                "future_count": 1,
                "option_count": 2,
                "total_instruments": 3,
                "futures": ["NSE:NSE_FNO:NIFTY:future:2026-09-24"],
                "options": [
                    "NSE:NSE_FNO:NIFTY:option:2026-09-24:25000:CE",
                    "NSE:NSE_FNO:NIFTY:option:2026-09-24:25000:PE",
                ],
            }
        ],
    }
    manifest = ParquetCaptureManifest(tmp_path / "chain-shape", run_id="chain-shape")
    path = manifest.write_record("chain_coverage", payload)
    table = pq.read_table(path)
    restored = decode_mapping_fields(table.to_pylist()[0], table.schema.metadata or {})
    assert restored == payload


def _request(*, allow_active: bool = True) -> DatasetRequest:
    return DatasetRequest(
        consumer="TEST",
        purpose="segmented parquet acceptance",
        trading_date=date(2026, 8, 27),
        channels=(DataChannel.STANDARD, DataChannel.DEPTH20, DataChannel.DEPTH200),
        instrument_ids=(INSTRUMENT,),
        allow_active=allow_active,
    )


def _row(sequence: int, *, event_type: str = "depth20", seconds: float | None = None) -> TapeRow:
    depth = 200 if event_type == "depth200" else 20 if event_type == "depth20" else 5
    stamp = datetime(2026, 8, 27, 3, 45, tzinfo=UTC) + timedelta(
        seconds=sequence if seconds is None else seconds
    )
    classified = event_type == "full"
    return TapeRow(
        run_id=str(RUN_ID),
        receive_sequence=sequence,
        source_sequence=sequence * 10,
        connection_epoch=2,
        source="dhan",
        event_type=event_type,
        instrument_id=INSTRUMENT,
        broker_security_id="58072",
        exchange_segment="NSE_FNO",
        exchange_ts=stamp - timedelta(milliseconds=2),
        receive_ts=stamp,
        raw_message_size_bytes=4096,
        connection_id="depth-primary",
        update_side="both",
        last_price=25000.123456789012,
        last_quantity=75,
        cumulative_volume=12_345,
        cumulative_volume_increment=25 if classified else None,
        open_interest=98_765,
        trade_quote_bid=24999.123456789012 if classified else None,
        trade_quote_ask=25001.123456789012 if classified else None,
        trade_quote_channel="depth20" if classified else None,
        trade_quote_bid_receive_ts=stamp - timedelta(milliseconds=10) if classified else None,
        trade_quote_ask_receive_ts=stamp - timedelta(milliseconds=9) if classified else None,
        trade_quote_receive_ts=stamp - timedelta(milliseconds=9) if classified else None,
        trade_quote_age_ms=10.0 if classified else None,
        trade_quote_freshness_bound_ms=1000.0 if classified else None,
        trade_side=TradeSide.BUY if classified else None,
        trade_classifier_version="quote-mid-tick-v1" if classified else None,
        trade_alignment_version=("latest-complete-depth-before-print-v1" if classified else None),
        trade_classification_degraded=False if classified else None,
        trade_classification_reason="quote_rule" if classified else None,
        trade_coalesced=False if classified else None,
        bids=tuple(
            DepthLevel(25000.123456789012 - level * 0.05, 100 + level, level + 1)
            for level in range(depth)
        ),
        asks=tuple(
            DepthLevel(25001.123456789012 + level * 0.05, 120 + level, level + 2)
            for level in range(depth)
        ),
        quality_flags=(QualityFlag.RECONNECTED, QualityFlag.PARTIAL_BOOK),
    )


def _write_completed_legacy(path: Path, rows: tuple[TapeRow, ...]) -> None:
    path.write_text("".join(json.dumps(row.to_dict()) + "\n" for row in rows), encoding="utf-8")
    events = (
        {"event_type": "run_started"},
        {
            "event_type": "artifact_closed",
            "artifact": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        },
        {"event_type": "run_completed"},
    )
    (path.parent / f"manifest_{RUN_ID}.jsonl").write_text(
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


def _session(tmp_path: Path, *, max_rows: int = 2) -> tuple[DataAccess, DataCaptureSession]:
    catalog = DataCatalog(tmp_path / "metadata" / "datasets")
    session = DataCaptureSession.create(
        catalog=catalog,
        request=_request(),
        output_root=tmp_path / "raw",
        run_id=RUN_ID,
        segment_max_rows=max_rows,
        segment_max_seconds=30,
    )
    return DataAccess(catalog), session


@pytest.mark.parametrize("event_type", ["quote", "full", "depth20", "depth200"])
def test_arrow_round_trip_preserves_every_tape_field_and_depth(
    tmp_path: Path, event_type: str
) -> None:
    writer = SegmentedParquetWriter(
        tmp_path / event_type,
        dataset_id=str(RUN_ID),
        max_rows=1,
    )
    original = _row(1, event_type=event_type)
    writer.write(original)
    segment = writer.close()[0]

    restored = tuple(iter_parquet_rows(Path(segment.path)))

    assert restored == (original,)
    expected_depth = 200 if event_type == "depth200" else 20 if event_type == "depth20" else 5
    assert len(restored[0].bids) == expected_depth
    assert restored[0].receive_ts.tzinfo is not None
    assert restored[0].last_price == original.last_price


def test_float32_widened_prices_quantize_to_the_schema_scale_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """Regression for option-chain capture losing an entire in-memory segment.

    Dhan's option-chain feed carries prices as IEEE-754 single precision. Widened
    to Python's float64, the exact value can need more than the schema's declared
    12 fractional digits (e.g. an on-wire ``71.55`` arrives as
    ``71.55000305175781``) — PyArrow refuses to silently truncate that at
    Parquet-write time, which previously crashed segment finalize and discarded
    every row buffered in that segment.
    """

    writer = SegmentedParquetWriter(tmp_path / "float32-prices", dataset_id=str(RUN_ID), max_rows=1)
    float32_widened = dataclasses.replace(
        _row(1, event_type="full"),
        last_price=71.55000305175781,
        trade_quote_bid=109.8499984741211,
        trade_quote_ask=109.90000152587891,
    )
    writer.write(float32_widened)
    segment = writer.close()[0]

    restored = tuple(iter_parquet_rows(Path(segment.path)))

    assert restored[0].last_price == pytest.approx(71.55000305175781, abs=1e-12)
    assert restored[0].trade_quote_bid == pytest.approx(109.8499984741211, abs=1e-12)


def test_multiple_segments_replay_without_duplicate_or_missing_rows(tmp_path: Path) -> None:
    access, session = _session(tmp_path, max_rows=2)
    for sequence, event_type in enumerate(("quote", "depth20", "depth200", "full", "depth20"), 1):
        session.write(_row(sequence, event_type=event_type))
    handle = session.close()

    assert len(handle.segments) == 3
    assert [row.receive_sequence for row in access.rows(handle)] == [1, 2, 3, 4, 5]
    assert access.validate(handle)["valid"] is True


def test_writer_rejects_sequence_gap_across_rotation(tmp_path: Path) -> None:
    writer = SegmentedParquetWriter(tmp_path / "dataset", dataset_id=str(RUN_ID), max_rows=1)
    writer.write(_row(1))
    with pytest.raises(TapeIntegrityError, match="contiguous"):
        writer.write(_row(3))


def test_time_channel_and_instrument_filters_prune_without_changing_results(
    tmp_path: Path,
) -> None:
    access, session = _session(tmp_path, max_rows=1)
    session.write(_row(1, event_type="quote"))
    session.write(_row(2, event_type="depth20"))
    session.write(_row(3, event_type="depth200"))
    handle = session.close()

    filtered = tuple(
        access.rows(
            handle,
            start=_row(2).receive_ts,
            channels=(DataChannel.DEPTH20,),
            instrument_ids=(INSTRUMENT,),
        )
    )

    assert [row.receive_sequence for row in filtered] == [2]


def test_timestamp_regression_uses_true_segment_bounds_for_pruning(tmp_path: Path) -> None:
    access, session = _session(tmp_path, max_rows=3)
    session.write(_row(1, seconds=0))
    session.write(_row(2, seconds=20))
    session.write(_row(3, seconds=10))
    handle = session.close()

    filtered = tuple(access.rows(handle, start=_row(1, seconds=15).receive_ts))

    assert [row.receive_sequence for row in filtered] == [2]


def test_catalogue_rejects_a_missing_event_in_the_digest_chain(tmp_path: Path) -> None:
    _access, session = _session(tmp_path, max_rows=1)
    session.write(_row(1))
    session.close()
    events = sorted(session.catalog.events_root.rglob("*.parquet"))
    assert len(events) >= 3
    events[1].unlink()

    with pytest.raises(ValueError, match="non-contiguous"):
        session.catalog.handles()


@pytest.mark.parametrize(
    ("max_rows", "max_seconds", "max_bytes"),
    [(1, 30.0, 1 << 20), (100, 0.5, 1 << 20), (100, 30.0, 1)],
)
def test_rotation_by_row_time_or_estimated_size(
    tmp_path: Path, max_rows: int, max_seconds: float, max_bytes: int
) -> None:
    writer = SegmentedParquetWriter(
        tmp_path / f"rotation-{max_rows}-{max_seconds}-{max_bytes}",
        dataset_id=str(RUN_ID),
        max_rows=max_rows,
        max_duration=timedelta(seconds=max_seconds),
        max_estimated_bytes=max_bytes,
    )
    writer.write(_row(1, seconds=0))
    writer.write(_row(2, seconds=1))
    segments = writer.close()

    assert len(segments) == 2
    assert sum(segment.rows for segment in segments) == 2


def test_atomic_publication_leaves_no_partial_file(tmp_path: Path) -> None:
    writer = SegmentedParquetWriter(tmp_path / "atomic", dataset_id=str(RUN_ID), max_rows=1)
    writer.write(_row(1))
    segments = writer.close()

    assert Path(segments[0].path).is_file()
    assert not tuple((tmp_path / "atomic").glob("*.partial*"))


def test_crash_partial_is_not_discoverable_and_can_be_quarantined(tmp_path: Path) -> None:
    directory = tmp_path / "crash"
    directory.mkdir()
    partial = directory / "market-events-000001.parquet.partial-crash"
    partial.write_bytes(b"PAR1-no-footer")

    inventory = inventory_recovery(directory, (), quarantine_partials=True)

    assert inventory.partial_files == (partial,)
    assert not partial.exists()
    assert inventory.quarantined_files[0].is_file()


def test_closed_but_unpublished_file_is_reported_as_orphan(tmp_path: Path) -> None:
    writer = SegmentedParquetWriter(tmp_path / "orphan", dataset_id=str(RUN_ID), max_rows=1)
    writer.write(_row(1))
    segments = writer.close()

    inventory = inventory_recovery(tmp_path / "orphan", ())

    assert inventory.orphan_files == (Path(segments[0].path),)


def test_active_follower_reads_only_newly_published_closed_segments(tmp_path: Path) -> None:
    access, session = _session(tmp_path, max_rows=2)
    follower = access.follow(session.handle)
    session.write(_row(1))
    assert follower.poll().rows == ()
    session.write(_row(2))

    assert [row["receive_sequence"] for row in follower.poll().rows] == [1, 2]
    assert follower.poll().rows == ()
    session.close()
    assert follower.finished


def test_empty_active_dataset_is_a_valid_not_yet_published_prefix(tmp_path: Path) -> None:
    access, session = _session(tmp_path, max_rows=2)

    assert tuple(access.rows(session.handle)) == ()
    assert access.follow(session.handle).poll().rows == ()
    session.close(invalidation_reason="synthetic empty capture")


def test_unsupported_major_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unsupported.parquet"
    metadata = dict(MARKET_EVENT_SCHEMA.metadata or {})
    metadata[b"shaurya.row_schema_version"] = b"3.0.0"
    table = pa.Table.from_pylist([], MARKET_EVENT_SCHEMA.with_metadata(metadata))
    pq.write_table(table, path)

    with pytest.raises(TapeIntegrityError, match="unsupported"):
        validate_parquet_schema(path)


def test_additive_nullable_schema_is_accepted_and_ignored_by_v2_reader(tmp_path: Path) -> None:
    path = tmp_path / "additive.parquet"
    metadata = dict(MARKET_EVENT_SCHEMA.metadata or {})
    metadata[b"shaurya.row_schema_version"] = b"2.1.0"
    evolved = MARKET_EVENT_SCHEMA.append(pa.field("future_nullable_fact", pa.string()))
    evolved = evolved.with_metadata(metadata)
    values = _row(1).to_dict()
    from shaurya.data.parquet import row_to_arrow

    payload = row_to_arrow(_row(1))
    payload["future_nullable_fact"] = None
    pq.write_table(pa.Table.from_pylist([payload], evolved), path)

    validate_parquet_schema(path)
    assert tuple(iter_parquet_rows(path)) == (_row(1),)
    assert values["receive_sequence"] == 1


def test_new_capture_persists_only_parquet_and_claim_history_not_json(tmp_path: Path) -> None:
    access, session = _session(tmp_path, max_rows=1)
    session.write(_row(1))
    handle = session.close()

    assert access.validate(handle)["valid"] is True
    assert not tuple(tmp_path.rglob("*.json"))
    assert not tuple(tmp_path.rglob("*.jsonl"))
    assert tuple(tmp_path.rglob("*.parquet"))
    assert tuple(tmp_path.rglob("*.claim"))


def test_legacy_conversion_preserves_original_and_semantic_digest(tmp_path: Path) -> None:
    source = tmp_path / "legacy.jsonl"
    _write_completed_legacy(source, tuple(_row(sequence) for sequence in (1, 2, 3)))
    original = source.read_bytes()
    access = DataAccess(DataCatalog(tmp_path / "metadata" / "datasets"))

    dry_run = access.migrate_legacy_tape(
        source,
        source_state=LegacySourceState.COMPLETED,
        convert=True,
        dry_run=True,
    )
    report = access.migrate_legacy_tape(
        source,
        source_state=LegacySourceState.COMPLETED,
        output_root=tmp_path / "raw",
        convert=True,
        dry_run=False,
        segment_max_rows=2,
    )
    handle = access.handle(report["dataset_id"])

    assert dry_run["converted"] is False
    assert report["converted"] is True
    assert report["original_preserved"] is True
    assert source.read_bytes() == original
    assert handle.legacy_source_sha256 == sha256_file(source)
    assert access.validate(handle)["canonical_row_digest"] == dry_run["canonical_row_digest"]

    repeated = access.migrate_legacy_tape(
        source,
        source_state=LegacySourceState.COMPLETED,
        output_root=tmp_path / "raw",
        convert=True,
        dry_run=False,
        segment_max_rows=2,
    )
    assert repeated["dataset_id"] == handle.dataset_id
    assert repeated["resumed"] is True


def test_legacy_conversion_resumes_final_segments_left_before_catalogue_publication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "interrupted.jsonl"
    _write_completed_legacy(source, tuple(_row(sequence) for sequence in (1, 2, 3)))
    source_hash = sha256_file(source)
    dataset_id = f"legacy-converted-{source_hash[:16]}"
    name = human_dataset_name(
        trading_date=_row(1).receive_ts,
        channels=(DataChannel.DEPTH20,),
        instrument_ids=(INSTRUMENT,),
        suffix=f"legacy-{source_hash[:8]}",
    )
    interrupted = SegmentedParquetWriter(
        tmp_path / "raw" / "legacy" / "nse-fno-nifty-future" / name,
        dataset_id=dataset_id,
        expected_run_id=str(RUN_ID),
        max_rows=2,
    )
    interrupted.write(_row(1))
    interrupted.write(_row(2))

    access = DataAccess(DataCatalog(tmp_path / "catalog"))
    report = access.migrate_legacy_tape(
        source,
        source_state=LegacySourceState.COMPLETED,
        output_root=tmp_path / "raw",
        convert=True,
        dry_run=False,
        segment_max_rows=2,
    )
    handle = access.handle(report["dataset_id"])

    assert report["resumed"] is True
    assert len(handle.segments) == 2
    assert [row.receive_sequence for row in access.rows(handle)] == [1, 2, 3]


@pytest.mark.parametrize(
    "state",
    [
        LegacySourceState.ACTIVE,
        LegacySourceState.TORN_TAIL,
        LegacySourceState.FAILED,
        LegacySourceState.CANCELLED,
        LegacySourceState.INVALIDATED,
    ],
)
def test_noncompleted_legacy_states_never_convert(tmp_path: Path, state: LegacySourceState) -> None:
    source = tmp_path / f"{state}.jsonl"
    source.write_text(json.dumps(_row(1).to_dict()) + "\n", encoding="utf-8")
    access = DataAccess(DataCatalog(tmp_path / "catalog"))

    report = access.migrate_legacy_tape(
        source,
        source_state=state,
        output_root=tmp_path / "raw",
        convert=True,
        dry_run=False,
    )

    assert report["eligible_for_completion"] is False
    assert report["converted"] is False
    assert not (tmp_path / "raw").exists()


def test_human_name_is_safe_meaningful_and_internal_ids_remain_separate(tmp_path: Path) -> None:
    del tmp_path
    name = human_dataset_name(
        trading_date=datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        channels=(DataChannel.DEPTH20, DataChannel.DEPTH200),
        instrument_ids=(INSTRUMENT,),
        suffix="Morning control #1",
    )

    assert name == "nifty-future-depth20-depth200-09-15-00-morning-control-1"
    assert "nifty-future" in name
    assert "depth20-depth200" in name
    assert re.fullmatch(r"[a-z0-9-]+", name)
    assert "sha-" not in name
    assert not name.startswith("dhan-")
    assert "20260827" not in name


def test_human_name_omits_redundant_producer_prefix_and_full_date(tmp_path: Path) -> None:
    """Both were previously included but are always redundant with this name's own
    placement on disk: the leaf directory's literal parent is already ``dhan/``, and
    production captures already land under a date-partitioned ``YYYY-MM-DD/`` root."""

    del tmp_path
    name = human_dataset_name(
        trading_date=datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        channels=(DataChannel.STANDARD,),
        instrument_ids=tuple(
            f"NSE:NSE_FNO:NIFTY:option:2026-09-01:{strike}:CE" for strike in range(40)
        ),
        suffix="d49ec103",
    )

    assert name == "nse-fno-nifty-40-instruments-standard-09-15-00-d49ec103"


def test_human_name_uses_ist_not_utc_for_the_time_component() -> None:
    """The time component is read against NSE trading hours, so it must be IST, not the
    UTC wall-clock the capture process actually runs on."""

    name = human_dataset_name(
        trading_date=datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        channels=(DataChannel.STANDARD,),
        instrument_ids=(INSTRUMENT,),
    )

    assert "09-15-00" in name
    assert "03-45-00" not in name
    assert "034500" not in name


def test_human_name_distinguishes_underlyings_instead_of_a_generic_universe_scope() -> None:
    """A NIFTY option-chain capture and a BANKNIFTY option-chain capture previously both
    collapsed to the same generic ``nse-fno-N-instruments`` scope, making it impossible to
    tell them apart without opening a file. The underlying must now appear in the name."""

    nifty_name = human_dataset_name(
        trading_date=datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        channels=(DataChannel.STANDARD,),
        instrument_ids=tuple(
            f"NSE:NSE_FNO:NIFTY:option:2026-09-01:{strike}:CE" for strike in range(40)
        ),
    )
    banknifty_name = human_dataset_name(
        trading_date=datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        channels=(DataChannel.STANDARD,),
        instrument_ids=tuple(
            f"NSE:NSE_FNO:BANKNIFTY:option:2026-09-01:{strike}:CE" for strike in range(40)
        ),
    )

    assert "nifty" in nifty_name and "banknifty" not in nifty_name
    assert "banknifty" in banknifty_name
    assert nifty_name != banknifty_name


def test_human_name_marks_retries_of_the_same_capture(tmp_path: Path) -> None:
    """A crash-and-relaunch sequence must read as ``retry2``, ``retry3``... instead of
    unrelated-looking sibling folders; the first attempt is unmarked."""

    del tmp_path
    kwargs = {
        "trading_date": datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        "channels": (DataChannel.STANDARD,),
        "instrument_ids": (INSTRUMENT,),
    }
    first = human_dataset_name(**kwargs)
    second = human_dataset_name(**kwargs, attempt=2)
    third = human_dataset_name(**kwargs, attempt=3)

    assert "retry" not in first
    assert "retry2" in second
    assert "retry3" in third


def test_terminal_failure_states_require_reasons() -> None:
    common = {
        "dataset_id": "legacy-failure",
        "acquisition_fingerprint": "a" * 64,
        "source": "legacy_tape",
        "trading_date": date(2026, 8, 27),
        "channels": (DataChannel.DEPTH20,),
        "instrument_ids": (INSTRUMENT,),
        "storage_format": StorageFormat.LEGACY_JSONL,
        "tape_path": "/preserved/legacy.jsonl",
        "started_at": datetime(2026, 8, 27, 3, 45, tzinfo=UTC),
        "completed_at": datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    }
    for status in (
        DatasetStatus.FAILED,
        DatasetStatus.CANCELLED,
        DatasetStatus.INVALIDATED,
        DatasetStatus.ORPHANED,
    ):
        with pytest.raises(ValueError, match="requires a reason"):
            DatasetHandle(status=status, **common)
