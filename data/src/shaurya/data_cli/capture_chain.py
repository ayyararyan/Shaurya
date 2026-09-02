"""Read-only Dhan option-chain capture on the Quote/Full channel (`RequestCode` 21).

Two jobs in one command, because they need the same subscription:

1. Capture an option-chain tape that the ANL-03 surface dashboard can replay.
2. Measure the Quote/Full channel's *empirical* instrument ceiling. Dhan's documented
   5,000 was disproved for the 20-level depth channel on 2026-08-19 (real ceiling: 50 per
   subscription message), so this command reports, per requested instrument, whether any
   packet ever arrived — the ceiling is read off that coverage, never assumed.

This command never places, modifies, or influences an order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST
from shaurya.data.access import (
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
)
from shaurya.data.dhan_client import DhanClient, DhanCredentials
from shaurya.data.dhan_stream import DhanLiveStream, DhanStreamConfig, StreamMetrics
from shaurya.data.storage import resolve_data_catalog, resolve_raw_capture_root
from shaurya.data.universe import select_chain_universe

UNDERLYING_INDEX_SECURITY_ID: dict[str, int] = {"NIFTY": 13, "BANKNIFTY": 25}
DEFAULT_MINIMUM_COVERAGE_FRACTION = 0.95


@dataclass(frozen=True, slots=True)
class ChainCaptureSpec:
    """One independently resolved chain carried on the shared Standard/Full socket."""

    underlying: str
    spot: float
    expiries: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = self.underlying.strip().upper()
        if normalized not in UNDERLYING_INDEX_SECURITY_ID:
            raise ValueError(f"unknown chain-spec underlying {self.underlying!r}")
        if self.spot <= 0:
            raise ValueError("chain-spec spot must be positive")
        if not self.expiries:
            raise ValueError("chain-spec requires at least one expiry")
        parsed = tuple(sorted({date.fromisoformat(value).isoformat() for value in self.expiries}))
        object.__setattr__(self, "underlying", normalized)
        object.__setattr__(self, "expiries", parsed)

    @classmethod
    def parse(cls, value: str) -> ChainCaptureSpec:
        """Parse ``UNDERLYING:SPOT:EXPIRY[,EXPIRY...]`` from the production launcher."""

        try:
            underlying, spot_text, expiry_text = value.split(":", maxsplit=2)
            expiries = tuple(item.strip() for item in expiry_text.split(",") if item.strip())
            return cls(underlying=underlying, spot=float(spot_text), expiries=expiries)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "chain-spec must be UNDERLYING:SPOT:EXPIRY[,EXPIRY...]"
            ) from exc

    def to_cli(self) -> str:
        return f"{self.underlying}:{self.spot}:{','.join(self.expiries)}"


def resolve_live_spot_and_expiries(
    client: DhanClient, underlying: str, *, expiry_count: int
) -> tuple[float, list[str]]:
    """Fetch the live spot and nearest ``expiry_count`` expiries for one underlying.

    Kept separate from ``select_chain_universe`` so a live capture command can omit
    ``--spot``/``--expiry`` for the common single-underlying case without ever guessing a
    strike band: the values here come straight off the exchange, never a fabricated default.
    """

    normalized = underlying.strip().upper()
    security_id = UNDERLYING_INDEX_SECURITY_ID.get(normalized)
    if security_id is None:
        raise ValueError(
            f"no index security id configured for underlying {underlying!r}; "
            f"known underlyings are {sorted(UNDERLYING_INDEX_SECURITY_ID)}"
        )
    if expiry_count <= 0:
        raise ValueError("expiry_count must be positive")
    available = client.expiry_list(underlying_security_id=security_id)
    if len(available) < expiry_count:
        raise ValueError(
            f"{normalized} offered only {len(available)} live expiries; requested {expiry_count}"
        )
    chosen = list(available[:expiry_count])
    chain = client.option_chain(expiry=chosen[0], underlying_security_id=security_id)
    spot = float(chain.get("last_price") or 0.0)
    if spot <= 0:
        raise ValueError(f"{normalized} option chain returned no positive underlying price")
    return spot, chosen


def coverage_failure_reason(
    *,
    requested_count: int,
    covered_count: int,
    minimum_coverage_fraction: float,
    stream_error_type: str | None = None,
    stream_error_reason_code: int | None = None,
    coverage_by_underlying: Mapping[str, tuple[int, int]] | None = None,
) -> str | None:
    """Return the terminal invalidation reason for a chain capture, if any.

    A capture is not considered successful merely because *some* rows arrived. Production
    chain data is useful only when instrument coverage clears an explicit floor; otherwise a
    silently ignored subscription batch could leave a plausible-looking but incomplete surface.
    """

    if not 0 < minimum_coverage_fraction <= 1:
        raise ValueError("minimum-coverage-fraction must lie in (0, 1]")
    if requested_count <= 0:
        raise ValueError("requested_count must be positive")
    if not 0 <= covered_count <= requested_count:
        raise ValueError("covered_count must lie between zero and requested_count")
    if stream_error_type is not None:
        suffix = (
            f" (reason_code={stream_error_reason_code})"
            if stream_error_reason_code is not None
            else ""
        )
        return f"stream failed: {stream_error_type}{suffix}"
    for underlying, (underlying_requested, underlying_covered) in (
        coverage_by_underlying or {}
    ).items():
        if underlying_requested <= 0 or not 0 <= underlying_covered <= underlying_requested:
            raise ValueError(f"invalid {underlying} coverage counts")
        underlying_fraction = underlying_covered / underlying_requested
        if underlying_fraction < minimum_coverage_fraction:
            return (
                f"{underlying} instrument coverage {underlying_covered}/{underlying_requested} "
                f"({underlying_fraction:.2%}) below required {minimum_coverage_fraction:.2%}"
            )
    coverage_fraction = covered_count / requested_count
    if coverage_fraction < minimum_coverage_fraction:
        return (
            f"instrument coverage {covered_count}/{requested_count} "
            f"({coverage_fraction:.2%}) below required {minimum_coverage_fraction:.2%}"
        )
    return None


def resolve_capture_specs(
    args: argparse.Namespace, client: DhanClient
) -> tuple[ChainCaptureSpec, ...]:
    """Resolve every requested underlying independently for one shared stream."""

    if args.chain_spec:
        if args.underlying or args.spot is not None or args.expiry:
            raise ValueError("--chain-spec cannot be combined with --underlying/--spot/--expiry")
        specs = tuple(ChainCaptureSpec.parse(value) for value in args.chain_spec)
    else:
        underlyings = tuple(value.strip().upper() for value in (args.underlying or ["NIFTY"]))
        if len(set(underlyings)) != len(underlyings):
            raise ValueError("underlyings must be unique")
        if len(underlyings) > 1 and (args.spot is not None or args.expiry):
            raise ValueError(
                "--spot/--expiry are single-underlying options; use --chain-spec or omit them "
                "to resolve each repeated --underlying independently"
            )
        resolved: list[ChainCaptureSpec] = []
        for underlying in underlyings:
            spot = args.spot
            expiry_values = args.expiry
            if spot is None or not expiry_values:
                live_spot, live_expiries = resolve_live_spot_and_expiries(
                    client, underlying, expiry_count=args.expiry_count
                )
                spot = spot if spot is not None else live_spot
                expiry_values = expiry_values or live_expiries
            resolved.append(ChainCaptureSpec(underlying, spot, tuple(expiry_values)))
        specs = tuple(resolved)
    spec_underlyings = [spec.underlying for spec in specs]
    if len(set(spec_underlyings)) != len(spec_underlyings):
        raise ValueError("chain-spec underlyings must be unique")
    return specs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--security-master", required=True, type=Path)
    parser.add_argument(
        "--underlying",
        action="append",
        default=None,
        help="Repeat to probe a universe wider than one underlying can supply.",
    )
    parser.add_argument(
        "--chain-spec",
        action="append",
        default=None,
        help=(
            "Pinned UNDERLYING:SPOT:EXPIRY[,EXPIRY...] specification; repeat to carry "
            "multiple independently resolved chains on one Standard/Full socket."
        ),
    )
    parser.add_argument(
        "--expiry",
        action="append",
        default=None,
        help=(
            "ISO expiry date; repeat for several maturities. Omit to auto-resolve the "
            "nearest --expiry-count live expiries from Dhan (single-underlying runs only)."
        ),
    )
    parser.add_argument(
        "--expiry-count",
        type=int,
        default=2,
        help="Nearest live expiries to auto-resolve when --expiry is omitted.",
    )
    parser.add_argument(
        "--spot",
        type=float,
        default=None,
        help=(
            "Omit to auto-resolve the live underlying price from Dhan "
            "(single-underlying runs only)."
        ),
    )
    parser.add_argument("--strike-window-fraction", type=float, default=0.06)
    parser.add_argument("--max-options", type=int, default=120)
    parser.add_argument(
        "--minimum-coverage-fraction",
        type=float,
        default=DEFAULT_MINIMUM_COVERAGE_FRACTION,
        help=(
            "Minimum requested-instrument fraction that must emit at least one packet for the "
            "dataset to be completed; lower coverage invalidates the run and returns nonzero."
        ),
    )
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Override the capture root for a controlled test. By default DAT writes to "
            "/Volumes/Aryan/NSE/YYYY-MM-DD/raw after verifying the SMB mount."
        ),
    )
    parser.add_argument(
        "--allow-nonarchive-output",
        action="store_true",
        help="Permit an intentional isolated test capture outside the configured NSE archive.",
    )
    parser.add_argument(
        "--data-catalog",
        type=Path,
        default=None,
    )
    parser.add_argument("--archive-on-close", action="store_true")
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=10.0)
    parser.add_argument("--heartbeat-timeout-seconds", type=float, default=5.0)
    return parser


async def _capture(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.duration_seconds <= 0:
        raise ValueError("duration-seconds must be positive")
    if not 0 < args.minimum_coverage_fraction <= 1:
        raise ValueError("minimum-coverage-fraction must lie in (0, 1]")
    master = DhanInstrumentMaster(args.security_master)
    mappings = list(master.mappings())
    credentials = DhanCredentials.from_env_file(args.credentials)
    specs = resolve_capture_specs(args, DhanClient(credentials))
    universes = [
        select_chain_universe(
            mappings,
            underlying=spec.underlying,
            expiries=[date.fromisoformat(value) for value in spec.expiries],
            spot_reference=spec.spot,
            strike_window_fraction=args.strike_window_fraction,
            max_options=args.max_options,
        )
        for spec in specs
    ]
    empty_underlyings = [universe.underlying for universe in universes if not universe.instruments]
    if empty_underlyings:
        raise ValueError(f"the requested universe selected no instruments for {empty_underlyings}")
    instruments: list[Any] = []
    seen_ids: set[str] = set()
    for universe in universes:
        for mapping in universe.instruments:
            if mapping.security_id in seen_ids:
                continue
            seen_ids.add(mapping.security_id)
            instruments.append(mapping)
    if not instruments:
        raise ValueError("the requested universe selected no instruments")

    trading_date = instruments[0].as_of_date
    output_root = resolve_raw_capture_root(
        args.output_root,
        trading_date=trading_date,
        allow_nonarchive=args.allow_nonarchive_output,
    )
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=trading_date,
        allow_nonarchive=args.allow_nonarchive_output,
        nonarchive_capture_root=output_root,
    )

    metrics = StreamMetrics()
    request = DatasetRequest(
        consumer="DAT-chain-capture",
        purpose="shared option-chain Standard/Full capture",
        trading_date=trading_date,
        channels=(DataChannel.STANDARD,),
        instrument_ids=tuple(item.instrument.canonical for item in instruments),
        allow_active=True,
    )
    session = DataCaptureSession.create(
        catalog=DataCatalog(catalog_path),
        request=request,
        output_root=output_root,
        fsync_every=200,
    )
    args._active_session = session
    manifest = session.manifest
    writer = session.writer
    seen: Counter[str] = Counter()
    first_seen: dict[str, str] = {}

    def consume(row: TapeRow) -> None:
        session.write(row)
        seen[row.instrument_id] += 1
        first_seen.setdefault(row.instrument_id, row.receive_ts.astimezone(IST).isoformat())

    config = DhanStreamConfig(
        enable_standard_feed=True,
        enable_20_level_depth=False,
        enable_200_level_depth=False,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
    )
    stream = DhanLiveStream(
        credentials,
        instruments,
        consume,
        run_id=session.dataset_id,
        config=config,
        metrics=metrics,
    )
    started = time.monotonic()
    stream_error: BaseException | None = None
    task = asyncio.create_task(stream.run())
    done, _ = await asyncio.wait({task}, timeout=args.duration_seconds)
    elapsed = time.monotonic() - started
    if task not in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        try:
            task.result()
            stream_error = RuntimeError("Dhan stream ended unexpectedly")
        except BaseException as exc:  # noqa: BLE001 - recorded, then reported
            stream_error = exc
    requested = [mapping.instrument.canonical for mapping in instruments]
    covered = [name for name in requested if seen[name] > 0]
    silent = [name for name in requested if seen[name] == 0]
    coverage_fraction = len(covered) / len(requested)
    stream_error_type = type(stream_error).__name__ if stream_error else None
    stream_error_reason_code = getattr(stream_error, "reason_code", None)
    coverage_by_underlying: dict[str, tuple[int, int]] = {}
    underlying_coverage_report: dict[str, dict[str, float | int]] = {}
    for universe in universes:
        universe_ids = [mapping.instrument.canonical for mapping in universe.instruments]
        universe_covered = sum(seen[name] > 0 for name in universe_ids)
        coverage_by_underlying[universe.underlying] = (len(universe_ids), universe_covered)
        underlying_coverage_report[universe.underlying] = {
            "requested_instruments": len(universe_ids),
            "instruments_with_packets": universe_covered,
            "coverage_fraction": universe_covered / len(universe_ids),
        }
    reason = coverage_failure_reason(
        requested_count=len(requested),
        covered_count=len(covered),
        minimum_coverage_fraction=args.minimum_coverage_fraction,
        stream_error_type=stream_error_type,
        stream_error_reason_code=stream_error_reason_code,
        coverage_by_underlying=coverage_by_underlying,
    )
    report: dict[str, Any] = {
        "run_id": str(manifest.run_id),
        "dataset_id": session.dataset_id,
        "generated_at": datetime.now(tz=IST).isoformat(),
        "channel": "standard_quote_full_request_code_21",
        "subscription_batch_size": 100,
        "standard_websocket_connections": 1,
        "elapsed_seconds": elapsed,
        "universes": [item.to_dict() for item in universes],
        "requested_instruments": len(requested),
        "instruments_with_packets": len(covered),
        "instruments_without_packets": len(silent),
        "coverage_fraction": coverage_fraction,
        "minimum_coverage_fraction": args.minimum_coverage_fraction,
        "coverage_ok": reason is None,
        "coverage_by_underlying": underlying_coverage_report,
        "first_silent_request_index": (requested.index(silent[0]) if silent else None),
        "silent_instruments": silent,
        "rows": metrics.rows,
        "reconnect_attempts": dict(metrics.reconnect_attempts),
        "connections": dict(metrics.connections),
        "heartbeat_timeouts": dict(metrics.heartbeat_timeouts),
        "disconnect_reason_codes": dict(metrics.disconnect_reason_codes),
        "packets_per_instrument": dict(seen),
        "first_packet_ist_per_instrument": first_seen,
        "stream_error": stream_error_type,
        "stream_error_reason_code": stream_error_reason_code,
        "dataset_directory": str(writer.dataset_dir),
    }
    manifest.write_record("chain_coverage", report)
    handle = session.close(
        invalidation_reason=reason,
        archive=args.archive_on_close,
    )
    report["dataset_handle"] = handle.model_dump(mode="json")
    return (0 if reason is None else 1), report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, report = asyncio.run(_capture(args))
    except DatasetAlreadyActiveError as exc:
        code = 0
        report = {
            "status": "reused_active_dataset",
            "dataset_handle": exc.handle.model_dump(mode="json"),
        }
    except BaseException as exc:
        active_session = getattr(args, "_active_session", None)
        if isinstance(active_session, DataCaptureSession):
            # DataCaptureSession retains its claim if failure publication also fails.
            with suppress(BaseException):
                active_session.close(
                    invalidation_reason=f"unexpected capture failure: {type(exc).__name__}"
                )
        report = {"status": "preflight_failed", "error_type": type(exc).__name__}
        code = 1
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
