from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from shaurya.contracts.artifacts import ArtifactManifest, RunId
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
)
from shaurya.contracts.tape import QualityFlag
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import (
    DEEP_HEADER,
    DEEP_LEVEL,
    FIVE_LEVEL_STRUCT,
    STANDARD_STRUCTS,
    DhanFatalStreamError,
    DhanLiveStream,
    DhanStreamConfig,
    HeartbeatTimeout,
    ParsedDeepPacket,
    ParsedMarketPacket,
    SequenceGapDetector,
    StreamMetrics,
    parse_deep_packets,
    parse_standard_packet,
)
from shaurya.data.tape import JsonlTapeWriter
from shaurya.data_cli.capture_dhan import _required_channels


def _mapping() -> DhanInstrumentMapping:
    instrument = InstrumentId(
        exchange="NSE",
        segment=ExchangeSegment.NSE_FNO,
        underlying="NIFTY",
        kind=InstrumentKind.FUTURE,
        expiry=date(2026, 8, 25),
    )
    return DhanInstrumentMapping(
        instrument=instrument,
        security_id="58072",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol="NIFTY-Aug2026-FUT",
        lot_size=65,
        tick_size_paise=Decimal("10"),
        as_of_date=date(2026, 8, 18),
        source="fixture",
    )


def _depth5() -> bytes:
    return b"".join(
        FIVE_LEVEL_STRUCT.pack(100 + index, 120 + index, 2, 3, 25000 - index, 25000.5 + index)
        for index in range(5)
    )


def test_standard_full_packet_parser_preserves_five_levels() -> None:
    packet_struct = STANDARD_STRUCTS[8]
    packet = packet_struct.pack(
        8,
        packet_struct.size,
        2,
        58072,
        25000.25,
        65,
        1787031000,
        24999.9,
        100000,
        2000,
        1900,
        800000,
        820000,
        780000,
        24900.0,
        24850.0,
        25100.0,
        24700.0,
        _depth5(),
    )
    parsed = parse_standard_packet(packet)
    assert parsed is not None
    assert parsed.event_type == "full"
    assert len(parsed.bids) == 5
    assert len(parsed.asks) == 5
    assert parsed.bids[0].price == 25000.0
    assert parsed.asks[0].price == 25000.5
    assert parsed.raw_size == packet_struct.size


def _deep_message(code: int, levels: int = 20) -> bytes:
    body = b"".join(
        DEEP_LEVEL.pack(
            25000.0 - index if code == 41 else 25000.5 + index,
            100 + index,
            2 + index,
        )
        for index in range(levels)
    )
    return DEEP_HEADER.pack(DEEP_HEADER.size + len(body), code, 2, 58072, levels) + body


def test_deep_parser_handles_bid_and_ask_packets_in_one_message() -> None:
    parsed = parse_deep_packets(_deep_message(41) + _deep_message(51))
    assert len(parsed) == 2
    assert isinstance(parsed[0], ParsedDeepPacket)
    assert parsed[0].side == "bid"
    assert parsed[1].side == "ask"
    assert len(parsed[0].levels) == 20
    assert parsed[0].raw_size == 332
    assert parsed[1].raw_size == 332


def test_deep_parser_handles_200_level_packets() -> None:
    parsed = parse_deep_packets(_deep_message(41, levels=200), depth_levels=200)
    assert len(parsed) == 1
    assert isinstance(parsed[0], ParsedDeepPacket)
    assert len(parsed[0].levels) == 200
    assert parsed[0].raw_size == DEEP_HEADER.size + 200 * DEEP_LEVEL.size


def test_deep_parser_rejects_unsupported_depth_levels() -> None:
    with pytest.raises(ValueError):
        parse_deep_packets(_deep_message(41), depth_levels=5)


def test_sequence_gap_detector_distinguishes_missing_duplicate_regression_and_gap() -> None:
    detector = SequenceGapDetector()
    assert detector.observe("key", None) == {QualityFlag.SOURCE_SEQUENCE_UNAVAILABLE}
    assert detector.observe("key", 10) == set()
    assert detector.observe("key", 11) == set()
    assert detector.observe("key", 11) == {QualityFlag.DUPLICATE_SEQUENCE}
    assert detector.observe("key", 9) == {QualityFlag.SEQUENCE_REGRESSION}
    assert detector.observe("key", 15) == {QualityFlag.SEQUENCE_GAP}


def test_capture_acceptance_requires_every_enabled_channel() -> None:
    both = DhanStreamConfig(enable_standard_feed=True, enable_20_level_depth=True)
    depth_only = DhanStreamConfig(enable_standard_feed=False, enable_20_level_depth=True)
    depth200_only = DhanStreamConfig(
        enable_standard_feed=False, enable_20_level_depth=False, enable_200_level_depth=True
    )
    assert _required_channels(both) == {"standard", "depth20"}
    assert _required_channels(depth_only) == {"depth20"}
    assert _required_channels(depth200_only) == {"depth200"}


@pytest.mark.asyncio
async def test_depth200_subscribe_uses_flat_message_not_instrument_list() -> None:
    # Regression: the 200-level endpoint silently drops the batched InstrumentList shape
    # (connection + heartbeats stay healthy, zero packets ever arrive) — confirmed live
    # 2026-08-18 and against Dhan's own fulldepth.FullDepth.subscribe_instruments reference.
    class RecordingSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, value: str) -> None:
            self.sent.append(value)

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    socket = RecordingSocket()
    await stream._subscribe(socket, "depth200")
    assert len(socket.sent) == 1
    payload = json.loads(socket.sent[0])
    assert payload == {"RequestCode": 23, "ExchangeSegment": "NSE_FNO", "SecurityId": "58072"}

    socket_20 = RecordingSocket()
    await stream._subscribe(socket_20, "depth20")
    payload_20 = json.loads(socket_20.sent[0])
    assert payload_20["InstrumentList"] == [{"ExchangeSegment": "NSE_FNO", "SecurityId": "58072"}]


@pytest.mark.asyncio
async def test_depth20_sends_exactly_one_subscription_message() -> None:
    class RecordingSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, value: str) -> None:
            self.sent.append(value)

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    socket = RecordingSocket()
    await stream._subscribe(socket, "depth20")
    assert len(socket.sent) == 1
    assert json.loads(socket.sent[0])["InstrumentCount"] == 1


def test_depth200_url_is_the_full_depth_endpoint() -> None:
    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    assert stream._url("depth200").startswith(DhanLiveStream.DEPTH200_URL)
    assert stream._url("depth20").startswith(DhanLiveStream.DEPTH20_URL)


@pytest.mark.asyncio
async def test_depth200_rejects_more_than_one_instrument() -> None:
    second = DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="BANKNIFTY",
            kind=InstrumentKind.FUTURE,
            expiry=date(2026, 8, 25),
        ),
        security_id="99999",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol="BANKNIFTY-Aug2026-FUT",
        lot_size=15,
        tick_size_paise=Decimal("10"),
        as_of_date=date(2026, 8, 18),
        source="fixture",
    )
    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping(), second],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
        config=DhanStreamConfig(
            enable_standard_feed=False, enable_20_level_depth=False, enable_200_level_depth=True
        ),
    )
    with pytest.raises(ValueError, match="exactly one instrument"):
        await stream.run()


def test_depth20_and_depth200_books_do_not_collide_for_the_same_instrument() -> None:
    rows = []
    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        rows.append,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    stream._epochs["depth20"] = 1
    stream._epochs["depth200"] = 1
    bid20, ask20 = parse_deep_packets(_deep_message(41) + _deep_message(51))
    bid200, ask200 = parse_deep_packets(
        _deep_message(41, levels=200) + _deep_message(51, levels=200), depth_levels=200
    )
    stream._emit_deep(bid20, stream_time(), channel="depth20")
    stream._emit_deep(ask20, stream_time(), channel="depth20")
    stream._emit_deep(bid200, stream_time(), channel="depth200")
    stream._emit_deep(ask200, stream_time(), channel="depth200")
    depth20_row = rows[1]
    depth200_row = rows[3]
    assert depth20_row.event_type == "depth20"
    assert len(depth20_row.bids) == 20
    assert depth200_row.event_type == "depth200"
    assert len(depth200_row.bids) == 200


def test_metrics_rate_uses_explicit_capture_window() -> None:
    metrics = StreamMetrics()
    metrics.source_packets["depth20"] = 300
    snapshot = metrics.snapshot(elapsed_seconds=30.0)
    assert snapshot["packet_rate_per_second"] == 10.0


@pytest.mark.asyncio
async def test_heartbeat_timeout_is_detected() -> None:
    class NoPong:
        async def ping(self):
            return asyncio.get_running_loop().create_future()

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
        config=DhanStreamConfig(
            heartbeat_interval_seconds=0.001,
            heartbeat_timeout_seconds=0.001,
            reconnect_initial_seconds=0.001,
            reconnect_max_seconds=0.002,
        ),
    )
    with pytest.raises(HeartbeatTimeout):
        await asyncio.wait_for(stream._heartbeat_loop(NoPong(), "standard"), timeout=0.1)


@pytest.mark.asyncio
async def test_supervisor_reconnects_after_transient_failure() -> None:
    class ProbeStream(DhanLiveStream):
        calls = 0

        async def _connection_once(self, channel: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("transient")
            raise DhanFatalStreamError("stop test")

    stream = ProbeStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
        config=DhanStreamConfig(
            reconnect_initial_seconds=0.001,
            reconnect_max_seconds=0.002,
        ),
    )
    with pytest.raises(DhanFatalStreamError):
        await stream._supervise("standard")
    assert stream.calls == 2
    assert stream.metrics.reconnect_attempts["standard"] == 1
    assert QualityFlag.CONNECTION_GAP in stream._pending_flags["standard"]


def test_bid_then_ask_side_packets_emit_partial_then_complete_book() -> None:
    rows = []
    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        rows.append,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    stream._epochs["depth20"] = 1
    bid, ask = parse_deep_packets(_deep_message(41) + _deep_message(51))
    stream._emit_deep(bid, stream_time(), channel="depth20")
    stream._emit_deep(ask, stream_time(), channel="depth20")
    assert QualityFlag.PARTIAL_BOOK in rows[0].quality_flags
    assert len(rows[1].bids) == 20
    assert len(rows[1].asks) == 20
    assert QualityFlag.PARTIAL_BOOK not in rows[1].quality_flags
    assert QualityFlag.EXCHANGE_TIMESTAMP_MISSING in rows[1].quality_flags


def test_live_emit_path_writes_trade_classification_fields() -> None:
    rows = []
    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        rows.append,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    stream._epochs["standard"] = 1
    stream._epochs["depth20"] = 1
    bid, ask = parse_deep_packets(_deep_message(41) + _deep_message(51))
    now = stream_time()
    stream._emit_deep(bid, now, channel="depth20")
    stream._emit_deep(ask, now, channel="depth20")
    baseline = ParsedMarketPacket(
        response_code=8,
        event_type="full",
        exchange_segment_code=2,
        security_id=58072,
        raw_size=STANDARD_STRUCTS[8].size,
        last_price=25000.0,
        last_quantity=65,
        cumulative_volume=1000,
    )
    stream._emit_standard(baseline, now)
    stream._emit_standard(
        ParsedMarketPacket(
            response_code=8,
            event_type="full",
            exchange_segment_code=2,
            security_id=58072,
            raw_size=STANDARD_STRUCTS[8].size,
            last_price=25000.5,
            last_quantity=65,
            cumulative_volume=1065,
        ),
        now,
    )
    classified = rows[-1]
    assert classified.trade_side == "buy"
    assert classified.trade_quote_channel == "depth20"
    assert classified.cumulative_volume_increment == 65
    assert classified.trade_classifier_version == "quote-mid-tick-v1"


@pytest.mark.asyncio
async def test_standard_stream_to_append_only_tape_end_to_end(tmp_path: Path) -> None:
    packet_struct = STANDARD_STRUCTS[8]
    full_packet = packet_struct.pack(
        8,
        packet_struct.size,
        2,
        58072,
        25000.25,
        65,
        1787031000,
        24999.9,
        100000,
        2000,
        1900,
        800000,
        820000,
        780000,
        24900.0,
        24850.0,
        25100.0,
        24700.0,
        _depth5(),
    )
    received = asyncio.Event()

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent = []
            self._emitted = False

        async def send(self, value):
            self.sent.append(value)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._emitted:
                self._emitted = True
                return full_packet
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def ping(self):
            future = asyncio.get_running_loop().create_future()
            future.set_result(None)
            return future

    websocket = FakeWebSocket()

    class Connection:
        async def __aenter__(self):
            return websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def connect_factory(*args, **kwargs):
        return Connection()

    run_id = RunId("sha-20260818T053000.000000Z-cafefeed")
    manifest = ArtifactManifest.create(tmp_path, run_id)
    writer = JsonlTapeWriter(manifest, fsync_every=1)

    def sink(row):
        writer.write(row)
        received.set()

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        sink,
        run_id=str(run_id),
        config=DhanStreamConfig(enable_20_level_depth=False),
        connect_factory=connect_factory,
    )
    task = asyncio.create_task(stream.run())
    await asyncio.wait_for(received.wait(), timeout=1.0)
    task.cancel()
    outcomes = await asyncio.gather(task, return_exceptions=True)
    writer.close()
    manifest.complete(rows=1)

    assert writer.rows_written == 1
    assert writer.path.read_text().count("\n") == 1
    assert '"event_type":"full"' in writer.path.read_text()
    assert websocket.sent and '"RequestCode": 21' in websocket.sent[0]
    assert isinstance(outcomes[0], asyncio.CancelledError)


def stream_time():
    from datetime import UTC, datetime

    return datetime(2026, 8, 18, 5, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_channel_start_stagger_brings_channels_up_sequentially() -> None:
    # DAT-20: three tiers were captured concurrently under a hard four-socket budget, so the
    # sockets must come up in observable single steps and the order must be recorded.
    order: list[str] = []
    release = asyncio.Event()

    async def fake_supervise(channel: str) -> None:
        order.append(channel)
        await release.wait()

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260819T073000.000000Z-1234abcd",
        config=DhanStreamConfig(
            enable_standard_feed=True,
            enable_20_level_depth=True,
            enable_200_level_depth=True,
            channel_start_stagger_seconds=0.01,
        ),
    )
    stream._supervise = fake_supervise  # type: ignore[method-assign]
    task = asyncio.create_task(stream.run())
    await asyncio.sleep(0.005)
    assert order == ["standard"], "second socket must not open before the stagger elapses"
    await asyncio.sleep(0.03)
    assert order == ["standard", "depth20", "depth200"]
    assert stream.channel_start_order == ["standard", "depth20", "depth200"]
    release.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_channel_start_stagger_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        DhanStreamConfig(channel_start_stagger_seconds=-1.0)


@pytest.mark.asyncio
async def test_zero_stagger_preserves_simultaneous_channel_start() -> None:
    order: list[str] = []
    release = asyncio.Event()

    async def fake_supervise(channel: str) -> None:
        order.append(channel)
        await release.wait()

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping()],
        lambda row: None,
        run_id="sha-20260819T073000.000000Z-1234abcd",
        config=DhanStreamConfig(enable_standard_feed=True, enable_20_level_depth=True),
    )
    stream._supervise = fake_supervise  # type: ignore[method-assign]
    task = asyncio.create_task(stream.run())
    await asyncio.sleep(0.005)
    assert order == ["standard", "depth20"]
    release.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
