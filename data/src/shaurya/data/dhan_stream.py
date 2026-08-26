"""DAT-02/DAT-10: supervised Dhan tick, 5-level, 20-level, and 200-level live market-data
streams. The 20-level and 200-level deep-book wire formats are identical (same 12-byte
header, same 16-byte-per-level layout, same response codes 41/51) per TASKS.md §7.1 — they
differ only in endpoint URL, subscription batching (200-level allows exactly one instrument
per subscription message), and the depth cap itself.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import struct
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentKind,
)
from shaurya.contracts.tape import DepthLevel, QualityFlag, TapeRow
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.trade_direction import CaptureTradeDirectionClassifier

# D33 (2026-08-19): the depth tier is a property of the instrument class, not a default.
# The 200-level ladder exists to expose a deep, densely populated futures book; an NSE option
# book is quoted only a few rupees wide and never justifies a 200-level subscription, and each
# depth200 subscription consumes an entire socket. Options are therefore capped at 20 levels
# module-wide. This is enforced here, at the single socket-construction choke point, so no
# caller can bypass it by forgetting a check.
DEPTH200_ELIGIBLE_KINDS = frozenset({InstrumentKind.EQUITY, InstrumentKind.FUTURE})
OPTION_MAX_DEPTH_LEVELS = 20


class DhanProtocolError(RuntimeError):
    pass


class DhanFatalStreamError(RuntimeError):
    """A non-retryable, sanitized stream rejection."""


class HeartbeatTimeout(TimeoutError):
    pass


SEGMENT_CODE = {
    ExchangeSegment.IDX_I: 0,
    ExchangeSegment.NSE_EQ: 1,
    ExchangeSegment.NSE_FNO: 2,
}
SEGMENT_NAME = {value: key for key, value in SEGMENT_CODE.items()}

STANDARD_STRUCTS = {
    2: struct.Struct("<BHBIfI"),
    3: struct.Struct("<BHBIf100s"),
    4: struct.Struct("<BHBIfHIfIIIffff"),
    5: struct.Struct("<BHBII"),
    6: struct.Struct("<BHBIfI"),
    7: struct.Struct("<BHBI"),
    8: struct.Struct("<BHBIfHIfIIIIIIffff100s"),
}
FIVE_LEVEL_STRUCT = struct.Struct("<IIHHff")
DEEP_HEADER = struct.Struct("<hBBiI")
DEEP_LEVEL = struct.Struct("<dII")


@dataclass(frozen=True, slots=True)
class ParsedMarketPacket:
    response_code: int
    event_type: str
    exchange_segment_code: int
    security_id: int
    raw_size: int
    exchange_timestamp: datetime | None = None
    last_price: float | None = None
    last_quantity: int | None = None
    cumulative_volume: int | None = None
    open_interest: int | None = None
    bids: tuple[DepthLevel, ...] = ()
    asks: tuple[DepthLevel, ...] = ()
    source_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDeepPacket:
    response_code: int
    exchange_segment_code: int
    security_id: int
    side: str
    levels: tuple[DepthLevel, ...]
    raw_size: int
    source_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDisconnect:
    reason_code: int
    raw_size: int


def _exchange_time(epoch_seconds: int) -> datetime | None:
    if epoch_seconds <= 0:
        return None
    return datetime.fromtimestamp(epoch_seconds, tz=UTC)


def _five_level_books(raw: bytes) -> tuple[tuple[DepthLevel, ...], tuple[DepthLevel, ...]]:
    if len(raw) != FIVE_LEVEL_STRUCT.size * 5:
        raise DhanProtocolError("Dhan 5-level block has an invalid length")
    bids: list[DepthLevel] = []
    asks: list[DepthLevel] = []
    for offset in range(0, len(raw), FIVE_LEVEL_STRUCT.size):
        bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = FIVE_LEVEL_STRUCT.unpack(
            raw[offset : offset + FIVE_LEVEL_STRUCT.size]
        )
        if math.isfinite(bid_price) and bid_price > 0:
            bids.append(DepthLevel(float(bid_price), int(bid_qty), int(bid_orders)))
        if math.isfinite(ask_price) and ask_price > 0:
            asks.append(DepthLevel(float(ask_price), int(ask_qty), int(ask_orders)))
    return (
        tuple(sorted(bids, key=lambda level: level.price, reverse=True)),
        tuple(sorted(asks, key=lambda level: level.price)),
    )


def parse_standard_packet(data: bytes) -> ParsedMarketPacket | ParsedDisconnect | None:
    """Parse one v2 main-feed packet without invoking the SDK's token-printing helpers."""

    if not data:
        raise DhanProtocolError("empty Dhan standard-feed packet")
    response_code = data[0]
    if response_code == 50:
        if len(data) < 10:
            raise DhanProtocolError("truncated Dhan disconnect packet")
        reason = struct.unpack("<BHBIH", data[:10])[4]
        return ParsedDisconnect(reason_code=int(reason), raw_size=len(data))
    packet_struct = STANDARD_STRUCTS.get(response_code)
    if packet_struct is None:
        return None
    if len(data) < packet_struct.size:
        raise DhanProtocolError(f"truncated Dhan response code {response_code}: {len(data)} bytes")
    values = packet_struct.unpack(data[: packet_struct.size])
    segment = int(values[2])
    security_id = int(values[3]) if response_code != 7 else 0
    if response_code == 2:
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="ticker",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
            last_price=float(values[4]),
            exchange_timestamp=_exchange_time(int(values[5])),
        )
    if response_code == 3:
        bids, asks = _five_level_books(values[5])
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="depth5",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
            last_price=float(values[4]),
            bids=bids,
            asks=asks,
        )
    if response_code == 4:
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="quote",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
            last_price=float(values[4]),
            last_quantity=int(values[5]),
            exchange_timestamp=_exchange_time(int(values[6])),
            cumulative_volume=int(values[8]),
        )
    if response_code == 5:
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="open_interest",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
            open_interest=int(values[4]),
        )
    if response_code == 6:
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="previous_close",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
        )
    if response_code == 7:
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="market_status",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
        )
    if response_code == 8:
        bids, asks = _five_level_books(values[18])
        return ParsedMarketPacket(
            response_code=response_code,
            event_type="full",
            exchange_segment_code=segment,
            security_id=security_id,
            raw_size=len(data),
            last_price=float(values[4]),
            last_quantity=int(values[5]),
            exchange_timestamp=_exchange_time(int(values[6])),
            cumulative_volume=int(values[8]),
            open_interest=int(values[11]),
            bids=bids,
            asks=asks,
        )
    raise AssertionError("unreachable standard response code")


def parse_deep_packets(
    data: bytes, *, depth_levels: int = 20
) -> list[ParsedDeepPacket | ParsedDisconnect]:
    """Parse every side packet in a single deep-feed WebSocket message."""

    if depth_levels not in (20, 200):
        raise ValueError(
            "Dhan deep-feed parsing only supports depth_levels of 20 (DAT-02) or 200 (DAT-10)"
        )
    results: list[ParsedDeepPacket | ParsedDisconnect] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < DEEP_HEADER.size:
            raise DhanProtocolError("truncated Dhan deep-feed header")
        message_length, response_code, segment, security_id, row_count = DEEP_HEADER.unpack(
            data[offset : offset + DEEP_HEADER.size]
        )
        if message_length < DEEP_HEADER.size or offset + message_length > len(data):
            raise DhanProtocolError("invalid Dhan deep-feed message length")
        message = data[offset : offset + message_length]
        if response_code == 50:
            results.append(ParsedDisconnect(reason_code=int(row_count), raw_size=message_length))
        elif response_code in {41, 51}:
            available = (message_length - DEEP_HEADER.size) // DEEP_LEVEL.size
            expected = min(depth_levels, int(row_count) if row_count else depth_levels)
            count = min(available, expected)
            levels: list[DepthLevel] = []
            for index in range(count):
                start = DEEP_HEADER.size + index * DEEP_LEVEL.size
                price, quantity, orders = DEEP_LEVEL.unpack(
                    message[start : start + DEEP_LEVEL.size]
                )
                if math.isfinite(price) and price > 0:
                    levels.append(DepthLevel(float(price), int(quantity), int(orders)))
            side = "bid" if response_code == 41 else "ask"
            levels.sort(key=lambda level: level.price, reverse=side == "bid")
            results.append(
                ParsedDeepPacket(
                    response_code=int(response_code),
                    exchange_segment_code=int(segment),
                    security_id=int(security_id),
                    side=side,
                    levels=tuple(levels),
                    raw_size=int(message_length),
                )
            )
        offset += message_length
    return results


class SequenceGapDetector:
    """Detect source-sequence discontinuities when the source exposes a sequence.

    Current Dhan v2 packet layouts expose no source sequence. DAT-02 records that limitation
    explicitly on every such row and also marks reconnect boundaries as connection gaps.
    """

    def __init__(self) -> None:
        self._last: dict[str, int] = {}

    def observe(self, key: str, source_sequence: int | None) -> set[QualityFlag]:
        if source_sequence is None:
            return {QualityFlag.SOURCE_SEQUENCE_UNAVAILABLE}
        previous = self._last.get(key)
        self._last[key] = source_sequence
        if previous is None or source_sequence == previous + 1:
            return set()
        if source_sequence == previous:
            return {QualityFlag.DUPLICATE_SEQUENCE}
        if source_sequence < previous:
            return {QualityFlag.SEQUENCE_REGRESSION}
        return {QualityFlag.SEQUENCE_GAP}

    def reset(self, key_prefix: str) -> None:
        for key in tuple(self._last):
            if key.startswith(key_prefix):
                del self._last[key]


@dataclass(slots=True)
class StreamMetrics:
    started_monotonic: float = field(default_factory=time.monotonic)
    websocket_messages: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    source_packets: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    raw_bytes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    message_sizes: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    rows: int = 0
    connections: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reconnect_attempts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reconnect_error_types: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reconnect_close_codes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    heartbeats_sent: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    heartbeats_ok: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    heartbeat_timeouts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    quality_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    first_packet_monotonic: float | None = None
    last_packet_monotonic: float | None = None

    def record_websocket_message(self, channel: str, size: int) -> None:
        self.websocket_messages[channel] += 1
        self.raw_bytes[channel] += size

    def record_source_packet(self, channel: str, size: int) -> None:
        now = time.monotonic()
        if self.first_packet_monotonic is None:
            self.first_packet_monotonic = now
        self.last_packet_monotonic = now
        self.source_packets[channel] += 1
        self.message_sizes[channel].append(size)

    def record_row(self, row: TapeRow) -> None:
        self.rows += 1
        for flag in row.quality_flags:
            self.quality_counts[str(flag)] += 1

    @staticmethod
    def _sizes(values: list[int]) -> dict[str, float | int | None]:
        if not values:
            return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
        ordered = sorted(values)

        def percentile(proportion: float) -> int:
            return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]

        return {
            "min": ordered[0],
            "mean": sum(ordered) / len(ordered),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "max": ordered[-1],
        }

    def snapshot(self, elapsed_seconds: float | None = None) -> dict[str, Any]:
        elapsed = (
            elapsed_seconds
            if elapsed_seconds is not None
            else time.monotonic() - self.started_monotonic
        )
        elapsed = max(elapsed, 1e-9)
        total_packets = sum(self.source_packets.values())
        active_span = None
        active_rate = None
        if self.first_packet_monotonic is not None and self.last_packet_monotonic is not None:
            active_span = max(self.last_packet_monotonic - self.first_packet_monotonic, 0.0)
            if active_span > 0 and total_packets > 1:
                active_rate = (total_packets - 1) / active_span
        return {
            "elapsed_seconds": elapsed,
            "active_packet_span_seconds": active_span,
            "active_packet_rate_per_second": active_rate,
            "source_packets": dict(self.source_packets),
            "websocket_messages": dict(self.websocket_messages),
            "raw_bytes": dict(self.raw_bytes),
            "rows": self.rows,
            "packet_rate_per_second": total_packets / elapsed,
            "packet_rate_per_second_by_channel": {
                channel: count / elapsed for channel, count in self.source_packets.items()
            },
            "message_size_bytes_by_channel": {
                channel: self._sizes(values) for channel, values in self.message_sizes.items()
            },
            "connections": dict(self.connections),
            "reconnect_attempts": dict(self.reconnect_attempts),
            "reconnect_error_types": dict(self.reconnect_error_types),
            "reconnect_close_codes": dict(self.reconnect_close_codes),
            "heartbeats_sent": dict(self.heartbeats_sent),
            "heartbeats_ok": dict(self.heartbeats_ok),
            "heartbeat_timeouts": dict(self.heartbeat_timeouts),
            "quality_counts": dict(self.quality_counts),
        }


@dataclass(frozen=True, slots=True)
class DhanStreamConfig:
    enable_standard_feed: bool = True
    enable_20_level_depth: bool = True
    enable_200_level_depth: bool = False
    heartbeat_interval_seconds: float = 10.0
    heartbeat_timeout_seconds: float = 5.0
    reconnect_initial_seconds: float = 0.5
    reconnect_max_seconds: float = 30.0
    open_timeout_seconds: float = 10.0
    stale_quote_after_seconds: float = 5.0
    trade_quote_freshness_seconds: float = 1.0
    depth20_instruments_per_socket_limit: int = 50
    channel_start_stagger_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            not self.enable_standard_feed
            and not self.enable_20_level_depth
            and not self.enable_200_level_depth
        ):
            raise ValueError("at least one Dhan stream channel must be enabled")
        positive = (
            self.heartbeat_interval_seconds,
            self.heartbeat_timeout_seconds,
            self.reconnect_initial_seconds,
            self.reconnect_max_seconds,
            self.open_timeout_seconds,
            self.stale_quote_after_seconds,
            self.trade_quote_freshness_seconds,
        )
        if min(positive) <= 0:
            raise ValueError("stream timeouts and reconnect delays must be positive")
        if self.depth20_instruments_per_socket_limit < 1:
            raise ValueError("depth20 instrument limit must be positive")
        if self.channel_start_stagger_seconds < 0:
            raise ValueError("channel start stagger must be non-negative")


ConnectFactory = Callable[..., AbstractAsyncContextManager[Any]]


class DhanLiveStream:
    STANDARD_URL = "wss://api-feed.dhan.co"
    DEPTH20_URL = "wss://depth-api-feed.dhan.co/twentydepth"
    DEPTH200_URL = "wss://full-depth-api.dhan.co/"
    FATAL_REASONS = {806, 807, 808, 809}

    def __init__(
        self,
        credentials: DhanCredentials,
        instruments: Iterable[DhanInstrumentMapping],
        sink: Callable[[TapeRow], None],
        *,
        run_id: str,
        config: DhanStreamConfig | None = None,
        metrics: StreamMetrics | None = None,
        connect_factory: ConnectFactory | None = None,
        connection_id: str = "primary",
        next_receive_sequence: Callable[[], int] | None = None,
        trade_direction_classifier: CaptureTradeDirectionClassifier | None = None,
    ) -> None:
        self.credentials = credentials
        self.instruments = tuple(instruments)
        if not self.instruments:
            raise ValueError("at least one instrument mapping is required")
        self.sink = sink
        self.run_id = run_id
        self.config = config or DhanStreamConfig()
        self.metrics = metrics or StreamMetrics()
        if not connection_id.strip():
            raise ValueError("connection_id is required")
        self.connection_id = connection_id
        if connect_factory is None:
            from websockets.asyncio.client import connect

            connect_factory = connect
        self._connect_factory = connect_factory
        self._mappings = {
            (SEGMENT_CODE[mapping.exchange_segment], int(mapping.security_id)): mapping
            for mapping in self.instruments
        }
        self._receive_sequence = 0
        self._external_next_receive_sequence = next_receive_sequence
        self._trade_direction_classifier = (
            trade_direction_classifier
            or CaptureTradeDirectionClassifier(
                quote_freshness_seconds=self.config.trade_quote_freshness_seconds
            )
        )
        self._epochs: dict[str, int] = defaultdict(int)
        self._ever_connected: dict[str, bool] = defaultdict(bool)
        self._pending_flags: dict[str, set[QualityFlag]] = defaultdict(set)
        self.channel_start_order: list[str] = []
        # Keyed by (channel, segment, security_id): depth20 and depth200 books for the same
        # instrument are tracked independently so a reconnect on one never clears the other.
        self._books: dict[tuple[str, int, int], dict[str, tuple[DepthLevel, ...]]] = defaultdict(
            dict
        )
        self._latest_standard: dict[tuple[int, int], ParsedMarketPacket] = {}
        self._book_side_received_at: dict[tuple[str, int, int, str], datetime] = {}
        self._last_exchange_ts: dict[tuple[str, int, int], datetime] = {}
        self._sequence_detector = SequenceGapDetector()

    async def run(self) -> None:
        channels = []
        if self.config.enable_standard_feed:
            channels.append("standard")
        if self.config.enable_20_level_depth:
            deep = [
                mapping
                for mapping in self.instruments
                if mapping.exchange_segment in {ExchangeSegment.NSE_EQ, ExchangeSegment.NSE_FNO}
            ]
            if not deep:
                raise ValueError("20-level depth requires an NSE_EQ or NSE_FNO instrument")
            limit = self.config.depth20_instruments_per_socket_limit
            if len(deep) > limit:
                raise ValueError(
                    "20-level depth permits one subscription message per socket; "
                    f"configured safe limit={limit}, eligible instruments={len(deep)}"
                )
            channels.append("depth20")
        if self.config.enable_200_level_depth:
            deep200 = [
                mapping
                for mapping in self.instruments
                if mapping.exchange_segment in {ExchangeSegment.NSE_EQ, ExchangeSegment.NSE_FNO}
            ]
            if not deep200:
                raise ValueError("200-level depth requires an NSE_EQ or NSE_FNO instrument")
            ineligible = [
                mapping
                for mapping in deep200
                if mapping.instrument.kind not in DEPTH200_ELIGIBLE_KINDS
            ]
            if ineligible:
                kinds = sorted({str(mapping.instrument.kind) for mapping in ineligible})
                raise ValueError(
                    "200-level depth is restricted to futures and equity books (D33); "
                    f"options are capped at {OPTION_MAX_DEPTH_LEVELS} levels — got "
                    f"{', '.join(kinds)}: "
                    + ", ".join(mapping.trading_symbol for mapping in ineligible)
                )
            if len(deep200) > 1:
                raise ValueError(
                    "200-level depth allows exactly one instrument per subscription "
                    "(Dhan batching rule, TASKS.md §7.1) — got "
                    f"{len(deep200)} eligible instruments"
                )
            channels.append("depth200")
        # DAT-20: channels may be brought up one at a time so that the concurrent socket
        # count rises in observable single steps rather than all at once. A zero stagger
        # preserves the original simultaneous behaviour.
        tasks: list[asyncio.Task[None]] = []
        stagger = self.config.channel_start_stagger_seconds
        for index, channel in enumerate(channels):
            if index and stagger:
                await asyncio.sleep(stagger)
            tasks.append(asyncio.create_task(self._supervise(channel)))
            self.channel_start_order.append(channel)
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            error: BaseException | None = None
            for task in done:
                if task.cancelled():
                    continue
                error = task.exception() or RuntimeError("Dhan stream supervisor exited")
                if error:
                    break
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if error:
                raise error
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _supervise(self, channel: str) -> None:
        delay = self.config.reconnect_initial_seconds
        while True:
            connections_before = self.metrics.connections[channel]
            try:
                await self._connection_once(channel)
                raise ConnectionError("Dhan WebSocket closed")
            except asyncio.CancelledError:
                raise
            except DhanFatalStreamError:
                raise
            except Exception as exc:
                if self.metrics.connections[channel] > connections_before:
                    # A completed handshake resets exponential backoff for a later outage.
                    delay = self.config.reconnect_initial_seconds
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in {401, 403}:
                    raise DhanFatalStreamError(
                        f"Dhan {channel} authentication failed; HTTP {status}"
                    ) from None
                self.metrics.reconnect_attempts[channel] += 1
                self.metrics.reconnect_error_types[f"{channel}:{type(exc).__name__}"] += 1
                close_code = getattr(getattr(exc, "rcvd", None), "code", None)
                if close_code is not None:
                    self.metrics.reconnect_close_codes[f"{channel}:{close_code}"] += 1
                self._pending_flags[channel].add(QualityFlag.CONNECTION_GAP)
                if isinstance(exc, HeartbeatTimeout):
                    self.metrics.heartbeat_timeouts[channel] += 1
                    self._pending_flags[channel].add(QualityFlag.HEARTBEAT_TIMEOUT)
                jittered = random.uniform(delay * 0.8, delay * 1.2)
                await asyncio.sleep(jittered)
                delay = min(delay * 2.0, self.config.reconnect_max_seconds)

    def _url(self, channel: str) -> str:
        if channel == "standard":
            base = self.STANDARD_URL
        elif channel == "depth20":
            base = self.DEPTH20_URL
        else:
            base = self.DEPTH200_URL
        version = "?version=2&" if channel == "standard" else "?"
        # This authenticated URL must never be logged or placed in an exception message.
        return (
            f"{base}{version}token={self.credentials.access_token}"
            f"&clientId={self.credentials.client_id}&authType=2"
        )

    async def _connection_once(self, channel: str) -> None:
        async with self._connect_factory(
            self._url(channel),
            ping_interval=None,
            open_timeout=self.config.open_timeout_seconds,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            await self._subscribe(websocket, channel)
            reconnected = self._ever_connected[channel]
            self._ever_connected[channel] = True
            self._epochs[channel] += 1
            self.metrics.connections[channel] += 1
            if reconnected:
                self._pending_flags[channel].update(
                    {QualityFlag.RECONNECTED, QualityFlag.CONNECTION_GAP}
                )
                self._sequence_detector.reset(f"{channel}:")
                if channel in {"depth20", "depth200"}:
                    for book_key in [key for key in self._books if key[0] == channel]:
                        del self._books[book_key]
                    side_time_keys = [
                        key for key in self._book_side_received_at if key[0] == channel
                    ]
                    for side_time_key in side_time_keys:
                        del self._book_side_received_at[side_time_key]
            receive_task = asyncio.create_task(self._receive_loop(websocket, channel))
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket, channel))
            child_tasks = {receive_task, heartbeat_task}
            try:
                done, pending = await asyncio.wait(child_tasks, return_when=asyncio.FIRST_COMPLETED)
                error: BaseException | None = None
                for task in done:
                    if not task.cancelled():
                        error = task.exception()
                        if error:
                            break
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if error:
                    raise error
                raise ConnectionError("Dhan WebSocket receive loop ended")
            finally:
                for task in child_tasks:
                    if not task.done():
                        task.cancel()
                # Retrieve every child result so shutdown cannot leak a task exception.
                await asyncio.gather(*child_tasks, return_exceptions=True)

    async def _subscribe(self, websocket: Any, channel: str) -> None:
        if channel == "standard":
            items = [
                {
                    "ExchangeSegment": mapping.exchange_segment.value,
                    "SecurityId": mapping.security_id,
                }
                for mapping in self.instruments
            ]
            for start in range(0, len(items), 100):
                batch = items[start : start + 100]
                await websocket.send(
                    json.dumps(
                        {"RequestCode": 21, "InstrumentCount": len(batch), "InstrumentList": batch}
                    )
                )
            return
        deep_instruments = [
            mapping
            for mapping in self.instruments
            if mapping.exchange_segment in {ExchangeSegment.NSE_EQ, ExchangeSegment.NSE_FNO}
        ]
        if channel == "depth200":
            # The 200-level endpoint does NOT use the InstrumentList batch envelope — it takes
            # one flat {RequestCode, ExchangeSegment, SecurityId} message per instrument.
            # Confirmed against Dhan's own reference implementation (dhanhq.fulldepth.FullDepth
            # .subscribe_instruments); the InstrumentList shape silently produces zero packets
            # on this endpoint even though the connection and heartbeats stay healthy.
            mapping = deep_instruments[0]
            await websocket.send(
                json.dumps(
                    {
                        "RequestCode": 23,
                        "ExchangeSegment": mapping.exchange_segment.value,
                        "SecurityId": mapping.security_id,
                    }
                )
            )
            return
        items = [
            {"ExchangeSegment": mapping.exchange_segment.value, "SecurityId": mapping.security_id}
            for mapping in deep_instruments
        ]
        # Live tests on 2026-08-18 showed that a second message on the same socket is silently
        # ignored. Each stream therefore sends exactly one message; larger universes are split
        # across DhanDepth20CapturePool sockets.
        await websocket.send(
            json.dumps({"RequestCode": 23, "InstrumentCount": len(items), "InstrumentList": items})
        )

    async def _heartbeat_loop(self, websocket: Any, channel: str) -> None:
        while True:
            await asyncio.sleep(self.config.heartbeat_interval_seconds)
            self.metrics.heartbeats_sent[channel] += 1
            try:
                waiter = await websocket.ping()
                await asyncio.wait_for(waiter, timeout=self.config.heartbeat_timeout_seconds)
            except TimeoutError as exc:
                raise HeartbeatTimeout(f"Dhan {channel} heartbeat timed out") from exc
            self.metrics.heartbeats_ok[channel] += 1

    async def _receive_loop(self, websocket: Any, channel: str) -> None:
        async for message in websocket:
            if not isinstance(message, bytes):
                raise DhanProtocolError(f"Dhan {channel} emitted a non-binary message")
            self.metrics.record_websocket_message(channel, len(message))
            received_at = datetime.now(UTC)
            if channel == "standard":
                standard_packet = parse_standard_packet(message)
                if standard_packet is None:
                    continue
                self.metrics.record_source_packet(channel, standard_packet.raw_size)
                if isinstance(standard_packet, ParsedDisconnect):
                    self._raise_disconnect(channel, standard_packet)
                if standard_packet.security_id == 0:
                    continue
                self._emit_standard(standard_packet, received_at)
            else:
                depth_levels = 200 if channel == "depth200" else 20
                for deep_packet in parse_deep_packets(message, depth_levels=depth_levels):
                    self.metrics.record_source_packet(channel, deep_packet.raw_size)
                    if isinstance(deep_packet, ParsedDisconnect):
                        self._raise_disconnect(channel, deep_packet)
                    self._emit_deep(deep_packet, received_at, channel=channel)

    @classmethod
    def _raise_disconnect(cls, channel: str, packet: ParsedDisconnect) -> NoReturn:
        if packet.reason_code in cls.FATAL_REASONS:
            raise DhanFatalStreamError(
                f"Dhan {channel} rejected the stream; reason_code={packet.reason_code}"
            )
        raise ConnectionError(f"Dhan {channel} disconnected; reason_code={packet.reason_code}")

    def _mapping(self, segment: int, security_id: int) -> DhanInstrumentMapping:
        try:
            return self._mappings[(segment, security_id)]
        except KeyError as exc:
            raise DhanProtocolError(
                f"Dhan emitted unsubscribed instrument segment={segment} security_id={security_id}"
            ) from exc

    def _flags(
        self,
        channel: str,
        segment: int,
        security_id: int,
        source_sequence: int | None,
        exchange_ts: datetime | None,
        bids: tuple[DepthLevel, ...],
        asks: tuple[DepthLevel, ...],
    ) -> set[QualityFlag]:
        key = f"{channel}:{segment}:{security_id}"
        flags = self._sequence_detector.observe(key, source_sequence)
        flags.update(self._pending_flags[channel])
        self._pending_flags[channel].clear()
        if exchange_ts is None:
            flags.add(QualityFlag.EXCHANGE_TIMESTAMP_MISSING)
        else:
            timestamp_key = (channel, segment, security_id)
            prior = self._last_exchange_ts.get(timestamp_key)
            if prior and exchange_ts < prior:
                flags.add(QualityFlag.EXCHANGE_TIME_REGRESSION)
            self._last_exchange_ts[timestamp_key] = exchange_ts
        if not bids or not asks:
            flags.add(QualityFlag.PARTIAL_BOOK)
        if bids and any(
            bids[index].price <= bids[index + 1].price for index in range(len(bids) - 1)
        ):
            flags.add(QualityFlag.INVALID_DEPTH)
        if asks and any(
            asks[index].price >= asks[index + 1].price for index in range(len(asks) - 1)
        ):
            flags.add(QualityFlag.INVALID_DEPTH)
        if bids and asks and bids[0].price >= asks[0].price:
            flags.add(QualityFlag.CROSSED_BOOK)
        return flags

    def _next_sequence(self) -> int:
        if self._external_next_receive_sequence is not None:
            return self._external_next_receive_sequence()
        self._receive_sequence += 1
        return self._receive_sequence

    def _emit_standard(self, packet: ParsedMarketPacket, received_at: datetime) -> None:
        mapping = self._mapping(packet.exchange_segment_code, packet.security_id)
        key = (packet.exchange_segment_code, packet.security_id)
        if packet.event_type in {"full", "quote", "ticker", "depth5"}:
            self._latest_standard[key] = packet
        flags = self._flags(
            "standard",
            packet.exchange_segment_code,
            packet.security_id,
            packet.source_sequence,
            packet.exchange_timestamp,
            packet.bids,
            packet.asks,
        )
        row = TapeRow(
            run_id=self.run_id,
            receive_sequence=self._next_sequence(),
            source_sequence=packet.source_sequence,
            connection_epoch=self._epochs["standard"],
            source="dhan",
            event_type=packet.event_type,
            instrument_id=mapping.instrument.canonical,
            broker_security_id=mapping.security_id,
            exchange_segment=mapping.exchange_segment.value,
            exchange_ts=packet.exchange_timestamp,
            receive_ts=received_at,
            raw_message_size_bytes=packet.raw_size,
            connection_id=self.connection_id,
            update_side="both" if packet.bids and packet.asks else None,
            last_price=packet.last_price,
            last_quantity=packet.last_quantity,
            cumulative_volume=packet.cumulative_volume,
            open_interest=packet.open_interest,
            bids=packet.bids,
            asks=packet.asks,
            quality_flags=tuple(flags),
        )
        classified_row = self._trade_direction_classifier.process(row)
        self.sink(classified_row)
        self.metrics.record_row(classified_row)

    def _emit_deep(self, packet: ParsedDeepPacket, received_at: datetime, *, channel: str) -> None:
        mapping = self._mapping(packet.exchange_segment_code, packet.security_id)
        book_key = (channel, packet.exchange_segment_code, packet.security_id)
        latest_key = (packet.exchange_segment_code, packet.security_id)
        self._books[book_key][packet.side] = packet.levels
        side_time_key = (
            channel,
            packet.exchange_segment_code,
            packet.security_id,
            packet.side,
        )
        self._book_side_received_at[side_time_key] = received_at
        bids = self._books[book_key].get("bid", ())
        asks = self._books[book_key].get("ask", ())
        latest = self._latest_standard.get(latest_key)
        flags = self._flags(
            channel,
            packet.exchange_segment_code,
            packet.security_id,
            packet.source_sequence,
            None,
            bids,
            asks,
        )
        other_side = "ask" if packet.side == "bid" else "bid"
        other_side_time = self._book_side_received_at.get(
            (channel, packet.exchange_segment_code, packet.security_id, other_side)
        )
        if (
            other_side_time is not None
            and (received_at - other_side_time).total_seconds()
            > self.config.stale_quote_after_seconds
        ):
            flags.add(QualityFlag.STALE_QUOTE)
        row = TapeRow(
            run_id=self.run_id,
            receive_sequence=self._next_sequence(),
            source_sequence=packet.source_sequence,
            connection_epoch=self._epochs[channel],
            source="dhan",
            event_type=channel,
            instrument_id=mapping.instrument.canonical,
            broker_security_id=mapping.security_id,
            exchange_segment=mapping.exchange_segment.value,
            exchange_ts=None,
            receive_ts=received_at,
            raw_message_size_bytes=packet.raw_size,
            connection_id=self.connection_id,
            update_side=packet.side,
            last_price=latest.last_price if latest else None,
            cumulative_volume=latest.cumulative_volume if latest else None,
            open_interest=latest.open_interest if latest else None,
            bids=bids,
            asks=asks,
            quality_flags=tuple(flags),
        )
        classified_row = self._trade_direction_classifier.process(row)
        self.sink(classified_row)
        self.metrics.record_row(classified_row)
