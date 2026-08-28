"""ANL-03: serve the live implied-volatility surface dashboard.

Two drive modes over one engine and one dashboard:

* ``replay`` — DAT-05 replay of a completed DAT dataset. Fits run in tape time, so a ten-minute
  tape reproduces a ten-minute session deterministically.
* ``follow`` — read-only follow of an active DAT dataset. DAT owns the sole Dhan connection.

The process is read-only in both modes: it requests a `CON-10` handle from DAT, ingests canonical
rows, fits, and serves HTTP. It imports no broker adapter, credential, socket, capture manifest or
order path (D43).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DataChannel, DatasetHandle, DatasetRequest, DatasetStatus
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    DhanInstrumentMaster,
    InstrumentKind,
)
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST
from shaurya.data import (
    DataAccess,
    DataCatalog,
    LegacySourceState,
    resolve_data_catalog,
    select_chain_universe,
)

from shaurya.analytics.mispricing import InstrumentMetadata, MispricingPolicy
from shaurya.analytics.server import DashboardState, serve_in_background
from shaurya.analytics.surface_feed import (
    StalenessPolicy,
    SurfaceEngine,
    default_log_moneyness_grid,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("replay", "follow", "live"),
        required=True,
        help="'live' is retained as an alias for DAT-owned 'follow'; it never opens Dhan",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--expiry", action="append", required=True)
    parser.add_argument("--fit-interval-seconds", type=float, default=5.0)
    parser.add_argument(
        "--surface-staleness-seconds",
        type=float,
        default=480.0,
        help="SUR-07 threshold. Surface age is the age of the *oldest* contributing "
        "quote, so on a wide chain it measures wing sparsity: the 2026-08-19 live run "
        "over 452 instruments measured p50 200 s and p95 421 s. Supply a smaller value "
        "for a narrow, uniformly liquid universe.",
    )
    parser.add_argument("--fit-stale-seconds", type=float, default=20.0)
    parser.add_argument(
        "--post-stream-seconds",
        type=float,
        default=0.0,
        help="live mode: keep serving after the stream stops, so feed death is observable.",
    )
    parser.add_argument("--feed-slow-seconds", type=float, default=1.0)
    parser.add_argument("--feed-dead-seconds", type=float, default=2.0)
    parser.add_argument("--moneyness-half-width", type=float, default=0.08)
    parser.add_argument("--moneyness-points", type=int, default=33)
    parser.add_argument("--min-quotes-per-slice", type=int, default=5)
    parser.add_argument("--risk-free-rate", type=float, default=0.0)
    parser.add_argument(
        "--disable-mispricing",
        action="store_true",
        help="Disable the approved read-only ANL-07 surface-relative mispricing monitor.",
    )
    parser.add_argument("--mispricing-cross-fit-folds", type=int, default=5)
    parser.add_argument("--mispricing-quote-max-age-seconds", type=float, default=3.0)
    parser.add_argument("--mispricing-fit-max-age-seconds", type=float, default=10.0)
    parser.add_argument("--mispricing-min-residual-history", type=int, default=100)
    parser.add_argument("--mispricing-residual-quantile", type=float, default=0.99)
    parser.add_argument("--mispricing-fdr-level", type=float, default=0.01)
    parser.add_argument("--mispricing-confirmation-frames", type=int, default=2)
    parser.add_argument("--mispricing-correction-frames", type=int, default=2)
    parser.add_argument("--mispricing-reference-half-life-seconds", type=float, default=120.0)
    parser.add_argument("--mispricing-reference-min-frames", type=int, default=6)
    parser.add_argument("--mispricing-reference-max-gap-seconds", type=float, default=15.0)
    parser.add_argument(
        "--mispricing-reference-max-raw-smoothed-iv-gap-points",
        type=float,
        default=0.50,
    )
    parser.add_argument("--mispricing-buy-turnover-rate", type=float, default=0.0004504340)
    parser.add_argument("--mispricing-sell-turnover-rate", type=float, default=0.0019204340)
    parser.add_argument("--mispricing-exit-slippage-ticks", type=float, default=1.0)
    parser.add_argument("--mispricing-hedge-slippage-ticks", type=float, default=1.0)
    parser.add_argument("--default-option-tick-size", type=float, default=0.05)
    parser.add_argument(
        "--default-option-lot-size",
        type=int,
        help="Replay fallback only. Live mode uses the date-stamped Dhan master per contract.",
    )
    parser.add_argument(
        "--serve-seconds",
        type=float,
        default=0.0,
        help="Stop after this many seconds; 0 serves until interrupted.",
    )
    parser.add_argument(
        "--data-catalog",
        type=Path,
        default=None,
        help="Override DAT metadata catalogue; defaults to today's verified NSE archive lane",
    )
    parser.add_argument(
        "--trading-date",
        type=date.fromisoformat,
        default=datetime.now(IST).date(),
        help="IST catalogue partition date (required for an archived replay from another day)",
    )
    parser.add_argument(
        "--allow-nonarchive-catalog",
        action="store_true",
        help="Permit a controlled isolated DAT catalogue outside the verified NSE archive",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dataset-id", help="CON-10 DAT dataset ID")
    source.add_argument(
        "--tape",
        type=Path,
        help="legacy tape; DAT adopts and indexes it before SUR ingests",
    )
    parser.add_argument(
        "--replay-speed",
        type=float,
        default=0.0,
        help="replay mode: 0 replays as fast as possible, 1.0 is real time",
    )
    parser.add_argument("--security-master", type=Path)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--spot", type=float)
    parser.add_argument("--strike-window-fraction", type=float, default=0.06)
    parser.add_argument("--max-options", type=int, default=120)
    parser.add_argument("--follow-poll-seconds", type=float, default=0.2)
    return parser


def _metadata_from_mappings(
    mappings: Iterable[DhanInstrumentMapping], *, default_tick_size: float
) -> dict[str, InstrumentMetadata]:
    result: dict[str, InstrumentMetadata] = {}
    for mapping in mappings:
        if mapping.instrument.kind is not InstrumentKind.OPTION:
            continue
        tick_size = (
            float(mapping.tick_size_paise / Decimal("100"))
            if mapping.tick_size_paise is not None and mapping.tick_size_paise > 0
            else default_tick_size
        )
        result[mapping.instrument.canonical] = InstrumentMetadata(
            tick_size=tick_size,
            lot_size=mapping.lot_size,
            source=f"date_stamped_dhan_master:{mapping.as_of_date.isoformat()}",
        )
    return result


def _engine(
    args: argparse.Namespace,
    run_id: str,
    source: str,
    *,
    instrument_metadata: dict[str, InstrumentMetadata] | None = None,
) -> SurfaceEngine:
    policy = StalenessPolicy(
        feed_slow_seconds=args.feed_slow_seconds,
        feed_dead_seconds=args.feed_dead_seconds,
        surface_staleness_seconds=args.surface_staleness_seconds,
        fit_stale_seconds=args.fit_stale_seconds,
    )
    return SurfaceEngine(
        run_id=run_id,
        surface_id=f"anl03-{source}",
        expiries=tuple(date.fromisoformat(value) for value in args.expiry),
        log_moneyness_grid=default_log_moneyness_grid(
            half_width=args.moneyness_half_width, points=args.moneyness_points
        ),
        policy=policy,
        fit_interval_seconds=args.fit_interval_seconds,
        risk_free_rate=args.risk_free_rate,
        min_quotes_per_slice=args.min_quotes_per_slice,
        wall_clock=source == "live",
        mispricing_policy=MispricingPolicy(
            enabled=not args.disable_mispricing,
            cross_fit_folds=args.mispricing_cross_fit_folds,
            quote_max_age_seconds=args.mispricing_quote_max_age_seconds,
            fit_max_age_seconds=args.mispricing_fit_max_age_seconds,
            residual_quantile=args.mispricing_residual_quantile,
            min_residual_history=args.mispricing_min_residual_history,
            fdr_level=args.mispricing_fdr_level,
            confirmation_frames=args.mispricing_confirmation_frames,
            correction_frames=args.mispricing_correction_frames,
            reference_smoothing_half_life_seconds=(args.mispricing_reference_half_life_seconds),
            reference_smoothing_min_frames=args.mispricing_reference_min_frames,
            reference_smoothing_max_gap_seconds=(args.mispricing_reference_max_gap_seconds),
            reference_max_raw_smoothed_iv_gap_points=(
                args.mispricing_reference_max_raw_smoothed_iv_gap_points
            ),
            default_tick_size=args.default_option_tick_size,
            default_lot_size=args.default_option_lot_size,
            buy_turnover_rate=args.mispricing_buy_turnover_rate,
            sell_turnover_rate=args.mispricing_sell_turnover_rate,
            exit_slippage_ticks=args.mispricing_exit_slippage_ticks,
            hedge_slippage_ticks=args.mispricing_hedge_slippage_ticks,
        ),
        instrument_metadata=instrument_metadata or {},
    )


def _summarise(engine: SurfaceEngine) -> dict[str, Any]:
    history = engine.history
    fits = [snapshot for snapshot in history if snapshot.fit_ok]
    failures = [snapshot for snapshot in history if not snapshot.fit_ok]
    durations = sorted(snapshot.fit_duration_seconds for snapshot in fits)
    ages = sorted(
        snapshot.health.feed_age_seconds
        for snapshot in history
        if snapshot.health.feed_age_seconds is not None
    )

    def quantile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
        return values[index]

    surface_ages = sorted(
        snapshot.surface_age_seconds
        for snapshot in fits
        if snapshot.surface_age_seconds is not None
    )
    smoothing_states: set[str] = set()
    for snapshot in fits:
        state = snapshot.diagnostics.get("temporal_smoothing")
        status = state.get("status") if isinstance(state, dict) else None
        smoothing_states.add(str(status).split(":")[0])
    arbitrage_failures = [
        snapshot.sequence
        for snapshot in fits
        if snapshot.arbitrage is not None and not snapshot.arbitrage.get("passed")
    ]
    return {
        "snapshots": len(history),
        "fits_ok": len(fits),
        "fits_failed": len(failures),
        "failure_reasons": sorted({str(item.failure_reason) for item in failures}),
        "fit_duration_p50": quantile(durations, 0.5),
        "fit_duration_p95": quantile(durations, 0.95),
        "fit_duration_max": durations[-1] if durations else None,
        "feed_age_p50": quantile(ages, 0.5),
        "feed_age_p95": quantile(ages, 0.95),
        "feed_age_max": ages[-1] if ages else None,
        "surface_age_p50": quantile(surface_ages, 0.5),
        "surface_age_p95": quantile(surface_ages, 0.95),
        "surface_age_max": surface_ages[-1] if surface_ages else None,
        "temporal_smoothing_states": sorted(smoothing_states),
        "arbitrage_failing_snapshots": arbitrage_failures,
        "instruments_tracked": (history[-1].health.tracked_instrument_count if history else 0),
        "reconnects": history[-1].health.reconnect_count if history else 0,
    }


def _resolve_dataset(
    args: argparse.Namespace,
) -> tuple[DataAccess, DatasetHandle, dict[str, InstrumentMetadata]]:
    mappings = (
        tuple(DhanInstrumentMaster(args.security_master).mappings())
        if args.security_master is not None
        else ()
    )
    catalog_date = mappings[0].as_of_date if mappings else args.trading_date
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=catalog_date,
        allow_nonarchive=args.allow_nonarchive_catalog,
    )
    access = DataAccess(DataCatalog(catalog_path))
    metadata = _metadata_from_mappings(mappings, default_tick_size=args.default_option_tick_size)
    if args.dataset_id is not None:
        return access, access.handle(args.dataset_id), metadata
    if args.tape is not None:
        return (
            access,
            access.adopt_legacy_tape(
                args.tape,
                source_state=LegacySourceState.COMPLETED,
                consumer="SUR-09",
                purpose="eSSVI surface ingestion",
            ),
            metadata,
        )
    if args.security_master is None or args.spot is None:
        raise SystemExit(
            "dataset selection requires --dataset-id, --tape, or both "
            "--security-master and --spot for a DAT request"
        )
    universe = select_chain_universe(
        mappings,
        underlying=args.underlying,
        expiries=[date.fromisoformat(value) for value in args.expiry],
        spot_reference=args.spot,
        strike_window_fraction=args.strike_window_fraction,
        max_options=args.max_options,
    )
    request = DatasetRequest(
        consumer="SUR-09",
        purpose="eSSVI surface ingestion",
        trading_date=universe.instruments[0].as_of_date,
        channels=(DataChannel.STANDARD,),
        instrument_ids=tuple(item.instrument.canonical for item in universe.instruments),
        allow_active=args.mode != "replay",
    )
    return (
        access,
        access.request(request),
        _metadata_from_mappings(
            universe.options,
            default_tick_size=args.default_option_tick_size,
        ),
    )


def _run_replay(
    args: argparse.Namespace,
    access: DataAccess,
    handle: DatasetHandle,
    replay_metadata: dict[str, InstrumentMetadata],
) -> dict[str, Any]:
    if handle.status is DatasetStatus.ACTIVE:
        raise ValueError("replay requires a completed DAT dataset; use follow for active data")
    engine = _engine(
        args,
        run_id=handle.dataset_id,
        source="replay",
        instrument_metadata=replay_metadata,
    )
    state = DashboardState(
        engine,
        title="Shaurya ANL-03 — implied volatility surface (REPLAY)",
        source=f"DAT replay {handle.dataset_id}",
    )
    server, _ = serve_in_background(state, host=args.host, port=args.port)
    print(f"ANL-03 dashboard serving at http://{args.host}:{args.port}/", flush=True)
    started_wall = time.monotonic()
    first_tape: datetime | None = None
    try:
        for row in access.rows(handle):
            stamp = row.receive_ts.astimezone(IST)
            if first_tape is None:
                first_tape = stamp
            if args.replay_speed > 0:
                target = (stamp - first_tape).total_seconds() / args.replay_speed
                drift = target - (time.monotonic() - started_wall)
                if drift > 0:
                    time.sleep(drift)
            engine.ingest(row)
            if engine.due_for_fit(stamp):
                engine.fit(stamp)
        if args.serve_seconds > 0:
            print(
                f"replay exhausted; serving the final state for {args.serve_seconds:.0f}s",
                flush=True,
            )
            time.sleep(args.serve_seconds)
    finally:
        server.shutdown()
    if handle.status not in {DatasetStatus.ACTIVE, DatasetStatus.COMPLETED}:
        raise ValueError(f"surface follow ended with ineligible dataset state {handle.status}")
    summary = _summarise(engine)
    summary["dataset_id"] = handle.dataset_id
    summary["dataset_status"] = str(handle.status)
    return summary


def _run_follow(
    args: argparse.Namespace,
    access: DataAccess,
    handle: DatasetHandle,
    metadata: dict[str, InstrumentMetadata],
) -> dict[str, Any]:
    if args.follow_poll_seconds <= 0:
        raise ValueError("follow-poll-seconds must be positive")
    engine = _engine(
        args,
        run_id=handle.dataset_id,
        source="live",
        instrument_metadata=metadata,
    )
    state = DashboardState(
        engine,
        title="Shaurya ANL-03 — implied volatility surface (DAT FOLLOW)",
        source=f"DAT {handle.dataset_id} · {len(handle.instrument_ids)} instruments",
    )
    server, _ = serve_in_background(state, host=args.host, port=args.port)
    print(f"ANL-03 dashboard serving at http://{args.host}:{args.port}/", flush=True)
    lock = threading.Lock()
    tail = access.follow(handle)
    started = time.monotonic()
    error: BaseException | None = None
    try:
        while args.serve_seconds == 0 or time.monotonic() - started < args.serve_seconds:
            batch = tail.poll()
            with lock:
                for payload in batch.rows:
                    engine.ingest(TapeRow.from_dict(payload))
                now = datetime.now(tz=IST)
                if engine.due_for_fit(now):
                    engine.fit(now)
            if batch.bytes_read == 0:
                latest = access.handle(handle.dataset_id)
                if latest.status is not DatasetStatus.ACTIVE and tail.finished:
                    handle = latest
                    break
            time.sleep(args.follow_poll_seconds)
    except BaseException as exc:  # noqa: BLE001 - reported in the summary
        error = exc
    finally:
        if args.post_stream_seconds > 0:
            print(
                "DAT dataset stopped advancing; serving for "
                f"{args.post_stream_seconds:.0f}s so feed death is observable",
                flush=True,
            )
            time.sleep(args.post_stream_seconds)
            summary_health = engine.sample_health(datetime.now(tz=IST))
            print(json.dumps({"post_stream_health": summary_health.to_dict()}), flush=True)
        server.shutdown()
    summary = _summarise(engine)
    summary["dataset_id"] = handle.dataset_id
    summary["dataset_status"] = str(handle.status)
    summary["storage_format"] = str(handle.storage_format or "legacy_jsonl")
    summary["dataset_digest"] = handle.dataset_digest or handle.tape_sha256
    summary["transport_error"] = type(error).__name__ if error else None
    if error is not None:
        raise error
    return summary


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    access, handle, metadata = _resolve_dataset(args)
    summary = (
        _run_replay(args, access, handle, metadata)
        if args.mode == "replay"
        else _run_follow(args, access, handle, metadata)
    )
    json.dump(summary, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0 if summary["fits_ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
