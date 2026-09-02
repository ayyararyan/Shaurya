"""Authenticated localhost fan-out for low-latency consumers of canonical DAT rows.

The immutable segmented-Parquet dataset remains the source of record.  This module is a
bounded operational transport: capture publishes each row only after ``DataCaptureSession``
accepts it, while read-only consumers receive the most recent row per instrument without
waiting for a Parquet segment to close.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import select
import socket
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DatasetHandle
from shaurya.contracts.tape import TapeRow

LIVE_STREAM_SCHEMA_VERSION = "1.0.0"
LIVE_STREAM_DESCRIPTOR = "live-stream.json"
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class LiveStreamUnavailableError(RuntimeError):
    """The active dataset has no reachable low-latency row publisher."""


class LiveStreamProtocolError(RuntimeError):
    """A live-row peer violated the versioned localhost protocol."""


@dataclass(frozen=True, slots=True)
class LiveStreamEndpoint:
    schema_version: str
    dataset_id: str
    host: str
    port: int
    token: str
    producer_pid: int
    published_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != LIVE_STREAM_SCHEMA_VERSION:
            raise ValueError(f"unsupported live-stream schema {self.schema_version!r}")
        if self.host not in {"127.0.0.1", "::1"}:
            raise ValueError("live-row transport must bind only to localhost")
        if not 0 < self.port <= 65_535:
            raise ValueError("live-stream port must be in [1, 65535]")
        if not self.dataset_id or not self.token:
            raise ValueError("live-stream endpoint requires dataset identity and token")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "producer_pid": self.producer_pid,
            "published_at": self.published_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LiveStreamEndpoint:
        return cls(
            schema_version=str(payload["schema_version"]),
            dataset_id=str(payload["dataset_id"]),
            host=str(payload["host"]),
            port=int(payload["port"]),
            token=str(payload["token"]),
            producer_pid=int(payload["producer_pid"]),
            published_at=datetime.fromisoformat(str(payload["published_at"])),
        )


@dataclass(frozen=True, slots=True)
class LiveRowBatch:
    """One snapshot, coalesced update batch, heartbeat, or local poll timeout."""

    rows: tuple[TapeRow, ...]
    source_sequence: int
    source_rows: int
    coalesced_rows: int
    message_type: str
    timed_out: bool = False


@dataclass(eq=False, slots=True)
class _ClientState:
    writer: asyncio.StreamWriter
    max_pending_instruments: int
    pending: dict[str, TapeRow] = field(default_factory=dict)
    event: asyncio.Event = field(default_factory=asyncio.Event)
    coalesced_rows: int = 0
    dropped_instruments: int = 0

    def offer(self, row: TapeRow) -> None:
        if row.instrument_id in self.pending:
            self.coalesced_rows += 1
        elif len(self.pending) >= self.max_pending_instruments:
            self.dropped_instruments += 1
            return
        self.pending[row.instrument_id] = row
        self.event.set()

    def drain(self) -> tuple[tuple[TapeRow, ...], int, int]:
        rows = tuple(sorted(self.pending.values(), key=lambda row: row.receive_sequence))
        coalesced = self.coalesced_rows
        dropped = self.dropped_instruments
        self.pending.clear()
        self.coalesced_rows = 0
        self.dropped_instruments = 0
        self.event.clear()
        return rows, coalesced, dropped


def live_stream_endpoint_path(handle: DatasetHandle) -> Path:
    """Return the operational descriptor path associated with a version-2 handle."""

    if not handle.manifest_path:
        raise LiveStreamUnavailableError(
            f"dataset {handle.dataset_id} has no operational metadata directory"
        )
    return Path(handle.manifest_path) / LIVE_STREAM_DESCRIPTOR


def _write_endpoint(path: Path, endpoint: LiveStreamEndpoint) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = path.parent / f"{path.name}.partial-{uuid.uuid4().hex}"
    encoded = json.dumps(endpoint.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
        os.chmod(path, 0o600)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _encode_message(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


class LiveRowPublisher:
    """Non-blocking latest-value fan-out owned by one active DAT capture."""

    def __init__(
        self,
        *,
        dataset_id: str,
        endpoint_path: Path,
        host: str = "127.0.0.1",
        port: int = 0,
        max_instruments: int = 10_000,
        heartbeat_seconds: float = 1.0,
    ) -> None:
        if host not in {"127.0.0.1", "::1"}:
            raise ValueError("live-row publisher may bind only to localhost")
        if not 0 <= port <= 65_535:
            raise ValueError("port must be in [0, 65535]")
        if max_instruments < 1 or heartbeat_seconds <= 0:
            raise ValueError("live-row publisher bounds must be positive")
        self.dataset_id = dataset_id
        self.endpoint_path = endpoint_path
        self.host = host
        self.port = port
        self.max_instruments = max_instruments
        self.heartbeat_seconds = heartbeat_seconds
        self.token = secrets.token_urlsafe(32)
        self.source_rows = 0
        self.source_sequence = 0
        self.coalesced_rows = 0
        self.dropped_instruments = 0
        self._latest: dict[str, TapeRow] = {}
        self._clients: set[_ClientState] = set()
        self._server: asyncio.Server | None = None
        self._closed = False

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def start(self) -> LiveStreamEndpoint:
        if self._server is not None:
            raise RuntimeError("live-row publisher is already started")
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        sockets = self._server.sockets or ()
        if len(sockets) != 1:
            await self.close()
            raise RuntimeError("live-row publisher did not acquire exactly one listener")
        bound = sockets[0].getsockname()
        endpoint = LiveStreamEndpoint(
            schema_version=LIVE_STREAM_SCHEMA_VERSION,
            dataset_id=self.dataset_id,
            host=self.host,
            port=int(bound[1]),
            token=self.token,
            producer_pid=os.getpid(),
            published_at=datetime.now(UTC),
        )
        try:
            _write_endpoint(self.endpoint_path, endpoint)
        except BaseException:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            raise
        return endpoint

    def publish(self, row: TapeRow) -> None:
        """Offer a canonical row without awaiting or blocking the capture callback."""

        if self._server is None or self._closed:
            raise RuntimeError("live-row publisher is not running")
        if row.run_id != self.dataset_id:
            raise ValueError("live row run_id does not match publisher dataset")
        if row.receive_sequence <= self.source_sequence:
            raise LiveStreamProtocolError("live row receive sequence did not advance")
        if row.instrument_id not in self._latest and len(self._latest) >= self.max_instruments:
            raise LiveStreamProtocolError("live row exceeded the bounded instrument universe")
        self.source_rows += 1
        self.source_sequence = row.receive_sequence
        self._latest[row.instrument_id] = row
        for client in tuple(self._clients):
            before = client.coalesced_rows
            dropped_before = client.dropped_instruments
            client.offer(row)
            self.coalesced_rows += client.coalesced_rows - before
            self.dropped_instruments += client.dropped_instruments - dropped_before

    def metrics(self) -> dict[str, int]:
        return {
            "source_rows": self.source_rows,
            "source_sequence": self.source_sequence,
            "connected_clients": self.client_count,
            "coalesced_client_rows": self.coalesced_rows,
            "dropped_client_instruments": self.dropped_instruments,
        }

    async def _send(
        self,
        writer: asyncio.StreamWriter,
        *,
        message_type: str,
        rows: tuple[TapeRow, ...] = (),
        coalesced_rows: int = 0,
        dropped_instruments: int = 0,
    ) -> None:
        writer.write(
            _encode_message(
                {
                    "schema_version": LIVE_STREAM_SCHEMA_VERSION,
                    "type": message_type,
                    "dataset_id": self.dataset_id,
                    "source_sequence": self.source_sequence,
                    "source_rows": self.source_rows,
                    "coalesced_rows": coalesced_rows,
                    "dropped_instruments": dropped_instruments,
                    "rows": [row.to_dict() for row in rows],
                }
            )
        )
        await writer.drain()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        client: _ClientState | None = None
        try:
            raw_auth = await asyncio.wait_for(reader.readline(), timeout=5.0)
            auth = json.loads(raw_auth)
            if not isinstance(auth, dict) or not secrets.compare_digest(
                str(auth.get("token", "")), self.token
            ):
                raise LiveStreamProtocolError("live-row authentication failed")
            if auth.get("dataset_id") != self.dataset_id:
                raise LiveStreamProtocolError("live-row dataset identity differs")
            client = _ClientState(writer, self.max_instruments)
            self._clients.add(client)
            snapshot = tuple(
                sorted(self._latest.values(), key=lambda row: row.receive_sequence)
            )
            await self._send(writer, message_type="snapshot", rows=snapshot)
            while not self._closed:
                try:
                    await asyncio.wait_for(
                        client.event.wait(), timeout=self.heartbeat_seconds
                    )
                except TimeoutError:
                    await self._send(writer, message_type="heartbeat")
                    continue
                rows, coalesced, dropped = client.drain()
                await self._send(
                    writer,
                    message_type="rows",
                    rows=rows,
                    coalesced_rows=coalesced,
                    dropped_instruments=dropped,
                )
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        except (json.JSONDecodeError, LiveStreamProtocolError):
            pass
        finally:
            if client is not None:
                self._clients.discard(client)
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for client in tuple(self._clients):
            rows, coalesced, dropped = client.drain()
            if rows:
                with suppress(ConnectionError):
                    await self._send(
                        client.writer,
                        message_type="rows",
                        rows=rows,
                        coalesced_rows=coalesced,
                        dropped_instruments=dropped,
                    )
        for client in tuple(self._clients):
            client.writer.close()
        for client in tuple(self._clients):
            with suppress(ConnectionError):
                await client.writer.wait_closed()
        self._clients.clear()
        try:
            payload = json.loads(self.endpoint_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            payload = {}
        if payload.get("token") == self.token:
            self.endpoint_path.unlink(missing_ok=True)

    async def __aenter__(self) -> LiveRowPublisher:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc, traceback
        await self.close()


class LiveRowSubscriber:
    """Synchronous bounded reader used by broker-independent dashboard processes."""

    def __init__(
        self,
        handle: DatasetHandle,
        *,
        connect_timeout_seconds: float = 15.0,
    ) -> None:
        if connect_timeout_seconds <= 0:
            raise ValueError("connect timeout must be positive")
        self.dataset_id = handle.dataset_id
        self.endpoint_path = live_stream_endpoint_path(handle)
        self._socket = self._connect(connect_timeout_seconds)
        self._buffer = bytearray()
        self._closed = False
        self._last_source_sequence = 0
        self._last_source_rows = 0

    def _connect(self, timeout_seconds: float) -> socket.socket:
        deadline = time.monotonic() + timeout_seconds
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            try:
                endpoint = LiveStreamEndpoint.from_dict(
                    json.loads(self.endpoint_path.read_text(encoding="utf-8"))
                )
                if endpoint.dataset_id != self.dataset_id:
                    raise LiveStreamProtocolError("live endpoint belongs to another dataset")
                connection = socket.create_connection(
                    (endpoint.host, endpoint.port),
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                connection.settimeout(None)
                connection.sendall(
                    _encode_message(
                        {
                            "schema_version": LIVE_STREAM_SCHEMA_VERSION,
                            "dataset_id": self.dataset_id,
                            "token": endpoint.token,
                        }
                    )
                )
                return connection
            except (
                FileNotFoundError,
                ConnectionError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        detail = f": {type(last_error).__name__}" if last_error is not None else ""
        raise LiveStreamUnavailableError(
            f"no reachable live stream for dataset {self.dataset_id}{detail}"
        ) from last_error

    def _read_message(self, timeout_seconds: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise LiveStreamProtocolError("live stream emitted invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise LiveStreamProtocolError("live stream message must be an object")
                return payload
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select((self._socket,), (), (), remaining)
            if not readable:
                return None
            chunk = self._socket.recv(65_536)
            if not chunk:
                raise LiveStreamUnavailableError(
                    f"live stream for dataset {self.dataset_id} closed"
                )
            self._buffer.extend(chunk)
            if len(self._buffer) > MAX_MESSAGE_BYTES:
                raise LiveStreamProtocolError("live stream message exceeded the safety bound")

    def poll(self, *, timeout_seconds: float = 0.2) -> LiveRowBatch:
        if self._closed:
            raise ValueError("cannot poll a closed live-row subscriber")
        if timeout_seconds <= 0:
            raise ValueError("poll timeout must be positive")
        payload = self._read_message(timeout_seconds)
        if payload is None:
            return LiveRowBatch(
                (),
                self._last_source_sequence,
                self._last_source_rows,
                0,
                "timeout",
                timed_out=True,
            )
        if payload.get("schema_version") != LIVE_STREAM_SCHEMA_VERSION:
            raise LiveStreamProtocolError("live stream schema differs")
        if payload.get("dataset_id") != self.dataset_id:
            raise LiveStreamProtocolError("live stream dataset identity differs")
        message_type = str(payload.get("type"))
        if message_type not in {"snapshot", "rows", "heartbeat"}:
            raise LiveStreamProtocolError(f"unknown live stream message type {message_type!r}")
        source_sequence = int(payload.get("source_sequence", 0))
        source_rows = int(payload.get("source_rows", 0))
        if source_sequence < self._last_source_sequence or source_rows < self._last_source_rows:
            raise LiveStreamProtocolError("live stream source counters regressed")
        raw_rows = payload.get("rows", [])
        if not isinstance(raw_rows, list):
            raise LiveStreamProtocolError("live stream rows must be a list")
        rows = tuple(TapeRow.from_dict(item) for item in raw_rows)
        if any(row.run_id != self.dataset_id for row in rows):
            raise LiveStreamProtocolError("live stream row belongs to another dataset")
        if any(row.receive_sequence > source_sequence for row in rows):
            raise LiveStreamProtocolError("live stream row exceeds its source watermark")
        self._last_source_sequence = source_sequence
        self._last_source_rows = source_rows
        return LiveRowBatch(
            rows=rows,
            source_sequence=source_sequence,
            source_rows=source_rows,
            coalesced_rows=int(payload.get("coalesced_rows", 0)),
            message_type=message_type,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._socket.close()

    def __enter__(self) -> LiveRowSubscriber:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc, traceback
        self.close()
