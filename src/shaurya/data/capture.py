"""DAT-09: capture-universe contracts and multi-socket 20-level orchestration."""

from __future__ import annotations

import asyncio
import itertools
import math
from collections.abc import Callable, Iterable
from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from shaurya.contracts.base import ContractModel
from shaurya.contracts.instruments import DhanInstrumentMapping, InstrumentKind
from shaurya.contracts.tape import TapeRow
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import (
    ConnectFactory,
    DhanLiveStream,
    DhanStreamConfig,
    StreamMetrics,
)

SAFE_DEPTH20_INSTRUMENTS_PER_SOCKET = 50


class CaptureUnderlying(StrEnum):
    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"
    FINNIFTY = "FINNIFTY"
    MIDCPNIFTY = "MIDCPNIFTY"


class CaptureUniversePlan(ContractModel):
    """A dated explicit selection; it never fabricates an unresolved strike-band rule."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_id: str
    trading_date: date
    instrument_master_date: date
    underlyings: tuple[CaptureUnderlying, ...]
    depth20_security_ids: tuple[str, ...]
    depth200_security_ids: tuple[str, ...] = ()
    retention: Literal["permanent"] = "permanent"
    exact_depth20_ceiling: int | None = None
    depth200_skew_status: Literal["pending_live_control", "measured"] = "pending_live_control"
    strike_band_rule: None = None

    @field_validator("plan_id")
    @classmethod
    def _plan_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("capture plan_id is required")
        return value.strip()

    @model_validator(mode="after")
    def _valid_plan(self) -> Self:
        if self.instrument_master_date != self.trading_date:
            raise ValueError("capture plans require the same trading-day instrument master")
        if not self.underlyings or not self.depth20_security_ids:
            raise ValueError("capture plan requires underlyings and 20-level instruments")
        for field_name, values in (
            ("underlyings", self.underlyings),
            ("depth20_security_ids", self.depth20_security_ids),
            ("depth200_security_ids", self.depth200_security_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"capture plan has duplicate {field_name}")
        if self.exact_depth20_ceiling is not None and self.exact_depth20_ceiling < 1:
            raise ValueError("exact depth20 ceiling must be positive when measured")
        return self

    def depth20_socket_count(
        self, operational_limit: int = SAFE_DEPTH20_INSTRUMENTS_PER_SOCKET
    ) -> int:
        if operational_limit < 1:
            raise ValueError("operational socket limit must be positive")
        return math.ceil(len(self.depth20_security_ids) / operational_limit)


def partition_depth20_instruments(
    instruments: Iterable[DhanInstrumentMapping],
    *,
    per_socket_limit: int = SAFE_DEPTH20_INSTRUMENTS_PER_SOCKET,
) -> tuple[tuple[DhanInstrumentMapping, ...], ...]:
    if per_socket_limit < 1:
        raise ValueError("per-socket instrument limit must be positive")
    eligible = tuple(
        mapping
        for mapping in instruments
        if mapping.instrument.kind
        in {InstrumentKind.EQUITY, InstrumentKind.FUTURE, InstrumentKind.OPTION}
    )
    if not eligible:
        raise ValueError("depth20 capture pool has no eligible instruments")
    return tuple(
        eligible[start : start + per_socket_limit]
        for start in range(0, len(eligible), per_socket_limit)
    )


class DhanDepth20CapturePool:
    """Run one first-and-only subscription message on each 20-level socket."""

    def __init__(
        self,
        credentials: DhanCredentials,
        instruments: Iterable[DhanInstrumentMapping],
        sink: Callable[[TapeRow], None],
        *,
        run_id: str,
        per_socket_limit: int = SAFE_DEPTH20_INSTRUMENTS_PER_SOCKET,
        metrics: StreamMetrics | None = None,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        self.credentials = credentials
        self.batches = partition_depth20_instruments(
            instruments, per_socket_limit=per_socket_limit
        )
        self.sink = sink
        self.run_id = run_id
        self.per_socket_limit = per_socket_limit
        self.metrics = metrics or StreamMetrics()
        self.connect_factory = connect_factory
        self._sequences = itertools.count(1)

    def streams(self) -> tuple[DhanLiveStream, ...]:
        config = DhanStreamConfig(
            enable_standard_feed=False,
            enable_20_level_depth=True,
            enable_200_level_depth=False,
            depth20_instruments_per_socket_limit=self.per_socket_limit,
        )
        return tuple(
            DhanLiveStream(
                self.credentials,
                batch,
                self.sink,
                run_id=self.run_id,
                config=config,
                metrics=self.metrics,
                connect_factory=self.connect_factory,
                connection_id=f"depth20-{index:04d}",
                next_receive_sequence=lambda: next(self._sequences),
            )
            for index, batch in enumerate(self.batches, start=1)
        )

    async def run(self) -> None:
        tasks = [asyncio.create_task(stream.run()) for stream in self.streams()]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
