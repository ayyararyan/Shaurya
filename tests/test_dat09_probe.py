from __future__ import annotations

from datetime import date
from decimal import Decimal

from scripts.dat09_concurrency_probe import (
    Depth200Control,
    DhanDepthProbeClient,
    ProbeObservation,
    ReconnectExperiment,
    bisect_twenty_level_ceiling,
)
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
)
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import DEEP_HEADER, DEEP_LEVEL


def _mapping() -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="NIFTY",
            kind=InstrumentKind.FUTURE,
            expiry=date(2026, 8, 25),
        ),
        security_id="58072",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol="NIFTY-Aug2026-FUT",
        lot_size=65,
        tick_size_paise=Decimal("10"),
        as_of_date=date(2026, 8, 19),
        source="fixture",
    )


def _packet() -> bytes:
    body = b"".join(DEEP_LEVEL.pack(25000.0 - value, 100, 2) for value in range(20))
    return DEEP_HEADER.pack(DEEP_HEADER.size + len(body), 41, 2, 58072, 20) + body


async def test_ceiling_binary_search_returns_largest_accepted_count() -> None:
    tested: list[int] = []

    async def probe(count: int) -> ProbeObservation:
        tested.append(count)
        counts = {"liquid-control": 1} if count <= 87 else {}
        return ProbeObservation(count, counts, ("liquid-control",), 1.0)

    result = await bisect_twenty_level_ceiling(
        probe, known_working=52, known_failing=206
    )
    assert result.exact_ceiling == 87
    assert len(tested) <= 8
    assert all(52 < value < 206 for value in tested)


def test_reconnect_experiment_requires_same_socket_failure_and_fresh_success() -> None:
    result = ReconnectExperiment(
        first_security_ids=("first",),
        second_security_ids=("second",),
        same_socket_counts={"first": 100},
        fresh_socket_counts={"second": 90},
    )
    assert result.socket_reset_supported
    payload = result.to_dict()
    assert payload["second_message_same_socket_worked"] is False
    assert payload["second_message_after_reconnect_worked"] is True


def test_depth200_control_surfaces_zero_and_packet_skew_without_guessing_cause() -> None:
    complete = Depth200Control(("a", "b", "c"), {"a": 100, "b": 50, "c": 25})
    assert complete.all_received
    assert complete.max_min_packet_ratio == 4.0
    assert complete.to_dict()["interpretation"] == "pending_live_review"
    missing = Depth200Control(("a", "b"), {"a": 10})
    assert not missing.all_received
    assert missing.max_min_packet_ratio is None


async def test_probe_client_uses_injected_socket_and_parses_packet_counts() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.responses = [_packet()]

        async def send(self, message: str) -> None:
            self.sent.append(message)

        async def recv(self) -> bytes:
            if self.responses:
                return self.responses.pop()
            raise TimeoutError

    socket = FakeSocket()

    class Connection:
        async def __aenter__(self) -> FakeSocket:
            return socket

        async def __aexit__(self, *args: object) -> None:
            return None

    def connect(*args: object, **kwargs: object) -> Connection:
        assert "token-secret" in str(args[0])
        return Connection()

    client = DhanDepthProbeClient(
        DhanCredentials("client", "token-secret"), connect_factory=connect
    )
    counts = await client.observe_twenty(((_mapping(),),), duration_seconds=0.01)
    assert counts == {"58072": 1}
    assert len(socket.sent) == 1
