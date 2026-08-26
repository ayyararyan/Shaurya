#!/usr/bin/env python3
"""Retain per-packet timestamps for a read-only depth200 multi-subscription probe."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import ParsedDeepPacket, ParsedDisconnect, parse_deep_packets

DEPTH200_URL = "wss://full-depth-api.dhan.co/"


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._handle = os.fdopen(descriptor, "w", encoding="utf-8", closefd=True)

    def write(self, row: dict[str, Any]) -> None:
        self._handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        self._handle.flush()

    def close(self) -> None:
        os.fsync(self._handle.fileno())
        self._handle.close()


async def _capture(args: argparse.Namespace) -> dict[str, Any]:
    from websockets.asyncio.client import connect

    credentials = DhanCredentials.from_env_file(args.credentials)
    master = DhanInstrumentMaster(args.security_master)
    mappings = [master.find_by_security_id(value) for value in args.security_ids]
    writer = JsonlWriter(args.output)
    counts: Counter[str] = Counter()
    books: dict[str, dict[str, list[dict[str, int | float]]]] = {}
    started_at = datetime.now(UTC)
    writer.write(
        {
            "event_type": "run_started",
            "receive_ts": started_at.isoformat(),
            "security_ids": args.security_ids,
            "duration_seconds_requested": args.duration_seconds,
        }
    )
    url = (
        f"{DEPTH200_URL}?token={credentials.access_token}"
        f"&clientId={credentials.client_id}&authType=2"
    )
    disconnects = 0
    deadline = time.monotonic() + args.duration_seconds
    try:
        async with connect(
            url,
            ping_interval=None,
            open_timeout=10,
            close_timeout=1,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            for mapping in mappings:
                await websocket.send(
                    json.dumps(
                        {
                            "RequestCode": 23,
                            "ExchangeSegment": mapping.exchange_segment.value,
                            "SecurityId": mapping.security_id,
                        }
                    )
                )
                await asyncio.sleep(0.05)
            while time.monotonic() < deadline:
                try:
                    message = await asyncio.wait_for(
                        websocket.recv(), timeout=max(deadline - time.monotonic(), 0.001)
                    )
                except TimeoutError:
                    break
                if not isinstance(message, bytes):
                    continue
                receive_ts = datetime.now(UTC).isoformat()
                for packet in parse_deep_packets(message, depth_levels=200):
                    if isinstance(packet, ParsedDisconnect):
                        disconnects += 1
                        continue
                    if not isinstance(packet, ParsedDeepPacket):
                        continue
                    security_id = str(packet.security_id)
                    counts[security_id] += 1
                    levels = [
                        {"price": level.price, "quantity": level.quantity, "orders": level.orders}
                        for level in packet.levels
                    ]
                    book = books.setdefault(security_id, {"bids": [], "asks": []})
                    book["bids" if packet.side == "bid" else "asks"] = levels
                    writer.write(
                        {
                            "event_type": "depth200_probe",
                            "receive_ts": receive_ts,
                            "broker_security_id": security_id,
                            "update_side": packet.side,
                            "best_bid": book["bids"][0]["price"] if book["bids"] else None,
                            "best_ask": book["asks"][0]["price"] if book["asks"] else None,
                            "bids": book["bids"][:1],
                            "asks": book["asks"][:1],
                        }
                    )
    finally:
        finished_at = datetime.now(UTC)
        summary = {
            "event_type": "run_completed",
            "receive_ts": finished_at.isoformat(),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_seconds": (finished_at - started_at).total_seconds(),
            "packet_counts": dict(counts),
            "disconnects": disconnects,
        }
        writer.write(summary)
        writer.close()
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--security-master", type=Path, required=True)
    parser.add_argument("--security-ids", required=True, type=lambda value: value.split(","))
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.duration_seconds <= 0 or not args.security_ids:
        raise ValueError("duration and security IDs must be non-empty")
    try:
        summary = asyncio.run(_capture(args))
    except BaseException as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"status": "completed", "summary": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
