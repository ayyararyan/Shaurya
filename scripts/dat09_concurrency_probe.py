"""Read-only live probes for DAT-11, DAT-12, and DAT-13.

The probe requires an explicit credential handle and dated master path at invocation. It never
contains a default credential location, places orders, or logs an authenticated URL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from shaurya.contracts.instruments import DhanInstrumentMapping, DhanInstrumentMaster
from shaurya.contracts.timing import IST
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import ParsedDeepPacket, parse_deep_packets

DEPTH20_URL = "wss://depth-api-feed.dhan.co/twentydepth"
DEPTH200_URL = "wss://full-depth-api.dhan.co/"


class ProbeSocket(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> bytes | str: ...


ConnectFactory = Callable[..., AbstractAsyncContextManager[ProbeSocket]]


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    requested_count: int
    packet_counts: dict[str, int]
    control_security_ids: tuple[str, ...]
    elapsed_seconds: float
    started_at_ist: str | None = None
    finished_at_ist: str | None = None

    def __post_init__(self) -> None:
        if self.requested_count < 1 or self.elapsed_seconds <= 0:
            raise ValueError("probe count and duration must be positive")
        if not self.control_security_ids:
            raise ValueError("probe requires at least one liquid control")

    @property
    def accepted(self) -> bool:
        return bool(self.control_security_ids) and all(
            self.packet_counts.get(security_id, 0) > 0
            for security_id in self.control_security_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_count": self.requested_count,
            "packet_counts": self.packet_counts,
            "control_security_ids": list(self.control_security_ids),
            "elapsed_seconds": self.elapsed_seconds,
            "started_at_ist": self.started_at_ist,
            "finished_at_ist": self.finished_at_ist,
            "accepted": self.accepted,
        }


@dataclass(frozen=True, slots=True)
class SoloRateAddendum:
    """Repeated fresh-socket comparison against a prior many-instrument packet count."""

    security_id: str
    reference_packet_count: int
    observations: tuple[ProbeObservation, ...]

    def __post_init__(self) -> None:
        if self.reference_packet_count < 1 or len(self.observations) < 2:
            raise ValueError("solo-rate addendum requires a positive reference and two runs")
        if any(
            value.requested_count != 1
            or value.control_security_ids != (self.security_id,)
            for value in self.observations
        ):
            raise ValueError("every solo-rate observation must contain only the target security")

    @property
    def packet_counts(self) -> tuple[int, ...]:
        return tuple(value.packet_counts.get(self.security_id, 0) for value in self.observations)

    @property
    def ratios_to_reference(self) -> tuple[float, ...]:
        return tuple(value / self.reference_packet_count for value in self.packet_counts)

    @property
    def row_rate_result(self) -> str:
        ratios = self.ratios_to_reference
        if all(0.9 <= value <= 1.1 for value in ratios):
            return "unchanged-solo-row-rate"
        if all(value >= 1.25 for value in ratios):
            return "materially-higher-solo-row-rate"
        return "mixed-solo-row-rate"

    @property
    def conclusion(self) -> str:
        # A parsed depth row is not necessarily a distinct publication event. DAT-16 found
        # multiple same-timestamp rows per fixed 500 ms snapshot, so row counts alone cannot
        # discriminate a packet cap from a true event rate.
        return "not-discriminated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "reference_packet_count": self.reference_packet_count,
            "comparison_rule": (
                "both solo counts within +/-10% of the reference => unchanged-solo-row-rate; "
                "both at least 25% above => materially-higher-solo-row-rate; otherwise mixed. "
                "Parsed row counts do not identify publication bursts or exchange event rate."
            ),
            "packet_counts": list(self.packet_counts),
            "ratios_to_reference": list(self.ratios_to_reference),
            "row_rate_result": self.row_rate_result,
            "conclusion": self.conclusion,
            "observations": [value.to_dict() for value in self.observations],
        }


@dataclass(frozen=True, slots=True)
class CeilingSearchResult:
    known_working: int
    known_failing: int
    exact_ceiling: int
    observations: tuple[ProbeObservation, ...]

    @property
    def monotonic_on_tested_candidates(self) -> bool:
        ordered = sorted(self.observations, key=lambda value: value.requested_count)
        seen_rejection = False
        for observation in ordered:
            if not observation.accepted:
                seen_rejection = True
            elif seen_rejection:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_working": self.known_working,
            "known_failing": self.known_failing,
            "exact_ceiling": self.exact_ceiling,
            "monotonic_on_tested_candidates": self.monotonic_on_tested_candidates,
            "observations": [observation.to_dict() for observation in self.observations],
        }


ProbeCount = Callable[[int], Awaitable[ProbeObservation]]


async def bisect_twenty_level_ceiling(
    probe: ProbeCount,
    *,
    known_working: int = 52,
    known_failing: int = 206,
) -> CeilingSearchResult:
    """Find the largest accepted count under the measured monotone working/failing bracket."""

    if known_working < 1 or known_failing <= known_working:
        raise ValueError("invalid working/failing ceiling bracket")
    low = known_working
    high = known_failing
    working_observation = await probe(low)
    failing_observation = await probe(high)
    if not working_observation.accepted:
        raise ValueError("known-working endpoint did not accept in this live run")
    if failing_observation.accepted:
        raise ValueError("known-failing endpoint accepted in this live run")
    observations: list[ProbeObservation] = [working_observation, failing_observation]
    while high - low > 1:
        candidate = (low + high) // 2
        observation = await probe(candidate)
        if observation.requested_count != candidate:
            raise ValueError("ceiling probe returned an observation for the wrong count")
        observations.append(observation)
        if observation.accepted:
            low = candidate
        else:
            high = candidate
    return CeilingSearchResult(
        known_working=known_working,
        known_failing=known_failing,
        exact_ceiling=low,
        observations=tuple(observations),
    )


@dataclass(frozen=True, slots=True)
class ReconnectExperiment:
    first_security_ids: tuple[str, ...]
    second_security_ids: tuple[str, ...]
    same_socket_counts: dict[str, int]
    fresh_socket_counts: dict[str, int]

    def __post_init__(self) -> None:
        if not self.first_security_ids or not self.second_security_ids:
            raise ValueError("reconnect experiment requires two non-empty instrument sets")
        if set(self.first_security_ids) & set(self.second_security_ids):
            raise ValueError("reconnect experiment instrument sets must be disjoint")

    @property
    def first_message_worked(self) -> bool:
        return any(self.same_socket_counts.get(value, 0) > 0 for value in self.first_security_ids)

    @property
    def second_message_same_socket_worked(self) -> bool:
        return any(self.same_socket_counts.get(value, 0) > 0 for value in self.second_security_ids)

    @property
    def second_message_after_reconnect_worked(self) -> bool:
        return any(self.fresh_socket_counts.get(value, 0) > 0 for value in self.second_security_ids)

    @property
    def socket_reset_supported(self) -> bool:
        return (
            self.first_message_worked
            and not self.second_message_same_socket_worked
            and self.second_message_after_reconnect_worked
        )

    @property
    def conclusion(self) -> str:
        if self.socket_reset_supported:
            return "socket-scoped"
        if (
            self.first_message_worked
            and not self.second_message_same_socket_worked
            and not self.second_message_after_reconnect_worked
        ):
            return "account-scoped"
        return "not discriminated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_security_ids": list(self.first_security_ids),
            "second_security_ids": list(self.second_security_ids),
            "same_socket_counts": self.same_socket_counts,
            "fresh_socket_counts": self.fresh_socket_counts,
            "first_message_worked": self.first_message_worked,
            "second_message_same_socket_worked": self.second_message_same_socket_worked,
            "second_message_after_reconnect_worked": self.second_message_after_reconnect_worked,
            "socket_reset_supported": self.socket_reset_supported,
            "conclusion": self.conclusion,
        }


@dataclass(frozen=True, slots=True)
class Depth200Control:
    security_ids: tuple[str, ...]
    packet_counts: dict[str, int]

    def __post_init__(self) -> None:
        if not self.security_ids or len(self.security_ids) != len(set(self.security_ids)):
            raise ValueError("depth200 control requires unique security IDs")

    @property
    def all_received(self) -> bool:
        return all(self.packet_counts.get(value, 0) > 0 for value in self.security_ids)

    @property
    def max_min_packet_ratio(self) -> float | None:
        values = [self.packet_counts.get(value, 0) for value in self.security_ids]
        if not values or min(values) == 0:
            return None
        return max(values) / min(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_ids": list(self.security_ids),
            "packet_counts": self.packet_counts,
            "all_received": self.all_received,
            "max_min_packet_ratio": self.max_min_packet_ratio,
            "interpretation": "pending_live_review",
        }


class DhanDepthProbeClient:
    def __init__(
        self,
        credentials: DhanCredentials,
        *,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        self.credentials = credentials
        if connect_factory is None:
            from websockets.asyncio.client import connect

            connect_factory = connect
        self._connect = connect_factory

    def _url(self, base: str) -> str:
        return (
            f"{base}?token={self.credentials.access_token}"
            f"&clientId={self.credentials.client_id}&authType=2"
        )

    @staticmethod
    def _twenty_message(instruments: Sequence[DhanInstrumentMapping]) -> str:
        items = [
            {
                "ExchangeSegment": mapping.exchange_segment.value,
                "SecurityId": mapping.security_id,
            }
            for mapping in instruments
        ]
        return json.dumps(
            {"RequestCode": 23, "InstrumentCount": len(items), "InstrumentList": items}
        )

    async def observe_twenty(
        self,
        messages: Sequence[Sequence[DhanInstrumentMapping]],
        *,
        duration_seconds: float,
        inter_message_delay_seconds: float = 1.0,
    ) -> dict[str, int]:
        if duration_seconds <= 0 or not messages:
            raise ValueError("probe duration and messages must be non-empty")
        counts: Counter[str] = Counter()
        async with self._connect(
            self._url(DEPTH20_URL),
            ping_interval=None,
            open_timeout=10,
            close_timeout=1,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            for index, instruments in enumerate(messages):
                await websocket.send(self._twenty_message(instruments))
                if index + 1 < len(messages):
                    await asyncio.sleep(inter_message_delay_seconds)
            await self._collect(websocket, counts, duration_seconds, depth_levels=20)
        return dict(counts)

    async def observe_200(
        self,
        instruments: Sequence[DhanInstrumentMapping],
        *,
        duration_seconds: float,
    ) -> dict[str, int]:
        counts: Counter[str] = Counter()
        async with self._connect(
            self._url(DEPTH200_URL),
            ping_interval=None,
            open_timeout=10,
            close_timeout=1,
            max_size=4 * 1024 * 1024,
        ) as websocket:
            for mapping in instruments:
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
            await self._collect(websocket, counts, duration_seconds, depth_levels=200)
        return dict(counts)

    @staticmethod
    async def _collect(
        websocket: ProbeSocket,
        counts: Counter[str],
        duration_seconds: float,
        *,
        depth_levels: int,
    ) -> None:
        end = time.monotonic() + duration_seconds
        while time.monotonic() < end:
            try:
                message = await asyncio.wait_for(
                    websocket.recv(), timeout=max(end - time.monotonic(), 0.001)
                )
            except TimeoutError:
                break
            if not isinstance(message, bytes):
                continue
            for packet in parse_deep_packets(message, depth_levels=depth_levels):
                if isinstance(packet, ParsedDeepPacket):
                    counts[str(packet.security_id)] += 1


def _load_mappings(
    master_path: Path, security_ids: Iterable[str]
) -> tuple[DhanInstrumentMapping, ...]:
    master = DhanInstrumentMaster(master_path)
    return tuple(master.find_by_security_id(value) for value in security_ids)


def _csv_ids(value: str) -> tuple[str, ...]:
    ids = tuple(item.strip() for item in value.split(",") if item.strip())
    if not ids:
        raise argparse.ArgumentTypeError("at least one security ID is required")
    return ids


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--security-master", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=40.0)
    commands = parser.add_subparsers(dest="command", required=True)
    ceiling = commands.add_parser("ceiling")
    ceiling.add_argument("--ordered-security-ids", type=_csv_ids, required=True)
    ceiling.add_argument("--control-security-ids", type=_csv_ids, required=True)
    ceiling.add_argument("--known-working", type=int, default=52)
    ceiling.add_argument("--known-failing", type=int, default=206)
    reconnect = commands.add_parser("reconnect")
    reconnect.add_argument("--first-security-ids", type=_csv_ids, required=True)
    reconnect.add_argument("--second-security-ids", type=_csv_ids, required=True)
    control = commands.add_parser("control", aliases=["depth200-control"])
    control.add_argument("--comparable-liquid-security-ids", type=_csv_ids, required=True)
    solo_rate = commands.add_parser("solo-rate")
    solo_rate.add_argument("--security-id", required=True)
    solo_rate.add_argument("--reference-packet-count", type=int, required=True)
    solo_rate.add_argument("--runs", type=int, default=2)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    credentials = DhanCredentials.from_env_file(args.credentials)
    client = DhanDepthProbeClient(credentials)
    if args.command == "ceiling":
        universe = _load_mappings(args.security_master, args.ordered_security_ids)
        controls = tuple(args.control_security_ids)

        async def probe(count: int) -> ProbeObservation:
            selected = universe[:count]
            if len(selected) != count:
                raise ValueError("ordered universe is too small for ceiling candidate")
            selected_ids = {mapping.security_id for mapping in selected}
            if not set(controls).issubset(selected_ids):
                raise ValueError("every ceiling candidate must include every liquid control")
            started_at = datetime.now(IST)
            counts = await client.observe_twenty(
                (selected,), duration_seconds=args.duration_seconds
            )
            finished_at = datetime.now(IST)
            return ProbeObservation(
                count,
                counts,
                controls,
                args.duration_seconds,
                started_at.isoformat(),
                finished_at.isoformat(),
            )

        ceiling_result = await bisect_twenty_level_ceiling(
            probe,
            known_working=args.known_working,
            known_failing=args.known_failing,
        )
        return {"task": "DAT-11", **ceiling_result.to_dict()}
    if args.command == "reconnect":
        first = _load_mappings(args.security_master, args.first_security_ids)
        second = _load_mappings(args.security_master, args.second_security_ids)
        same_counts = await client.observe_twenty(
            (first, second), duration_seconds=args.duration_seconds
        )
        fresh_counts = await client.observe_twenty(
            (second,), duration_seconds=args.duration_seconds
        )
        reconnect_result = ReconnectExperiment(
            tuple(args.first_security_ids),
            tuple(args.second_security_ids),
            same_counts,
            fresh_counts,
        )
        return {"task": "DAT-12", **reconnect_result.to_dict()}
    if args.command == "solo-rate":
        if args.runs < 2:
            raise ValueError("solo-rate requires at least two runs")
        mapping = _load_mappings(args.security_master, (args.security_id,))[0]
        observations: list[ProbeObservation] = []
        for _ in range(args.runs):
            started_at = datetime.now(IST)
            counts = await client.observe_twenty(
                ((mapping,),), duration_seconds=args.duration_seconds
            )
            finished_at = datetime.now(IST)
            observations.append(
                ProbeObservation(
                    1,
                    counts,
                    (args.security_id,),
                    args.duration_seconds,
                    started_at.isoformat(),
                    finished_at.isoformat(),
                )
            )
        result = SoloRateAddendum(
            args.security_id,
            args.reference_packet_count,
            tuple(observations),
        )
        return {"task": "DAT-11-addendum", **result.to_dict()}
    instruments = _load_mappings(args.security_master, args.comparable_liquid_security_ids)
    counts = await client.observe_200(instruments, duration_seconds=args.duration_seconds)
    control_result = Depth200Control(tuple(args.comparable_liquid_security_ids), counts)
    return {"task": "DAT-13", **control_result.to_dict()}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = asyncio.run(_run(args))
        _write_result(args.output, payload)
    except BaseException as exc:
        # Never print exception text: network exceptions may contain an authenticated URL.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"status": "completed", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
