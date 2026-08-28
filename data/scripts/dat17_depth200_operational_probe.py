#!/usr/bin/env python3
"""DAT-17 live probe for first-versus-later depth200 delivery on one socket."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.instruments import (
    DhanInstrumentMaster,
    ExchangeSegment,
    InstrumentKind,
)
from shaurya.contracts.timing import IST
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import (
    DhanLiveStream,
    ParsedDeepPacket,
    ParsedDisconnect,
    parse_deep_packets,
)


def _csv_ids(value: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in value.split(",") if item.strip())
    if not result or len(result) != len(set(result)):
        raise argparse.ArgumentTypeError("security IDs must be a non-empty unique CSV list")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--security-master", required=True, type=Path)
    parser.add_argument("--security-ids", required=True, type=_csv_ids)
    parser.add_argument("--exchange-segment", type=ExchangeSegment, choices=tuple(ExchangeSegment))
    parser.add_argument("--instrument-kind", type=InstrumentKind, choices=tuple(InstrumentKind))
    parser.add_argument("--duration-seconds", type=float, default=90.0)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _instrument_summary(
    receive_offsets: list[float], packets_per_burst: list[int], elapsed: float
) -> dict[str, Any]:
    gaps_ms = [
        (later - earlier) * 1_000.0
        for earlier, later in zip(receive_offsets, receive_offsets[1:], strict=False)
    ]
    cadence = None
    if gaps_ms:
        cadence = {
            "gap_min_ms": min(gaps_ms),
            "gap_p05_ms": _percentile(gaps_ms, 0.05),
            "gap_p50_ms": _percentile(gaps_ms, 0.50),
            "gap_p95_ms": _percentile(gaps_ms, 0.95),
            "gap_max_ms": max(gaps_ms),
            "transition_rate_per_second": (len(receive_offsets) - 1)
            / (receive_offsets[-1] - receive_offsets[0]),
        }
    return {
        "packet_count": sum(packets_per_burst),
        "distinct_receive_timestamps": len(receive_offsets),
        "effective_burst_rate_over_full_window_per_second": len(receive_offsets) / elapsed,
        "first_receive_offset_seconds": receive_offsets[0] if receive_offsets else None,
        "last_receive_offset_seconds": receive_offsets[-1] if receive_offsets else None,
        "silence_after_last_receive_seconds": (
            elapsed - receive_offsets[-1] if receive_offsets else elapsed
        ),
        "packets_per_burst": packets_per_burst,
        "receive_offsets_seconds": receive_offsets,
        "cadence_when_multiple_bursts_exist": cadence,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.duration_seconds <= 0:
        raise ValueError("duration-seconds must be positive")
    credentials = DhanCredentials.from_env_file(args.credentials)
    master = DhanInstrumentMaster(args.security_master)
    mappings = [
        master.find_by_security_id(
            value,
            exchange_segment=args.exchange_segment,
            instrument_kind=args.instrument_kind,
        )
        for value in args.security_ids
    ]
    from websockets.asyncio.client import connect

    url = (
        f"{DhanLiveStream.DEPTH200_URL}?token={credentials.access_token}"
        f"&clientId={credentials.client_id}&authType=2"
    )
    started_wall = datetime.now(IST)
    started = time.monotonic()
    offsets_by_security: dict[str, list[float]] = defaultdict(list)
    packets_by_security_burst: dict[str, list[int]] = defaultdict(list)
    disconnect_reasons: Counter[int] = Counter()
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
        end = started + args.duration_seconds
        while time.monotonic() < end:
            try:
                message = await asyncio.wait_for(
                    websocket.recv(), timeout=max(end - time.monotonic(), 0.001)
                )
            except TimeoutError:
                break
            if not isinstance(message, bytes):
                continue
            received_offset = time.monotonic() - started
            frame_counts: Counter[str] = Counter()
            for packet in parse_deep_packets(message, depth_levels=200):
                if isinstance(packet, ParsedDeepPacket):
                    frame_counts[str(packet.security_id)] += 1
                elif isinstance(packet, ParsedDisconnect):
                    disconnect_reasons[packet.reason_code] += 1
            for security_id, packet_count in frame_counts.items():
                offsets_by_security[security_id].append(received_offset)
                packets_by_security_burst[security_id].append(packet_count)
    elapsed = time.monotonic() - started
    return {
        "task": "DAT-17",
        "object": "depth200 first-versus-later subscription delivery on one socket",
        "started_at_ist": started_wall.isoformat(),
        "finished_at_ist": datetime.now(IST).isoformat(),
        "duration_seconds_requested": args.duration_seconds,
        "elapsed_seconds": elapsed,
        "security_ids_in_subscription_order": list(args.security_ids),
        "instruments": {
            mapping.security_id: {
                "trading_symbol": mapping.trading_symbol,
                "subscription_position": position,
                **_instrument_summary(
                    offsets_by_security.get(mapping.security_id, []),
                    packets_by_security_burst.get(mapping.security_id, []),
                    elapsed,
                ),
            }
            for position, mapping in enumerate(mappings, start=1)
        },
        "disconnect_reasons": dict(disconnect_reasons),
    }


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    args = _parser().parse_args()
    result = asyncio.run(_run(args))
    _write_exclusive(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
