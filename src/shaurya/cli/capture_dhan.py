"""Read-only Dhan live capture CLI for DAT-02 validation and collection."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    DhanInstrumentMaster,
    InstrumentKind,
)
from shaurya.contracts.timing import (
    IST,
    NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS,
    nse_equity_derivatives_session_bounds,
    nse_equity_derivatives_session_seconds,
)
from shaurya.data.access import (
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
)
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import (
    DEPTH200_ELIGIBLE_KINDS,
    OPTION_MAX_DEPTH_LEVELS,
    DhanLiveStream,
    DhanStreamConfig,
    StreamMetrics,
)
from shaurya.data.quality import CollectorQualityAudit, write_quality_audit
from shaurya.data.storage import resolve_data_catalog, resolve_raw_capture_root

SIG21_PROTOCOL_ID = "H-SIG21"
SIG21_REGISTRATION_COMMIT = "f2cf65011d02882191b5cfda566c1024119964d7"
SIG21_REGISTERED_FAMILY_SIZE = 384
SIG21_FULL_SESSION_SECONDS = float(NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS)

OFI_FULL_SESSION_PROTOCOL_ID = "R-OFI-FULLSESSION-2026-08-20"
OFI_FULL_SESSION_SOURCE_SPEC = "docs/OFI-FULL-SESSION-REPLICATION-SPEC-2026-08-20.md"
OFI_FULL_SESSION_SOURCE_AMENDMENT = (
    "docs/OFI-FULL-SESSION-REPLICATION-SPEC-AMENDMENT-1-2026-08-19.md"
)
OFI_FULL_SESSION_REGISTRATION_COMMIT = "af9bec17694b5cf45f1d670113f14b02efb1e418"
OFI_FULL_SESSION_TRADING_DATE = date(2026, 8, 20)
OFI_FULL_SESSION_SECONDS = float(
    nse_equity_derivatives_session_seconds(OFI_FULL_SESSION_TRADING_DATE)
)


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--security-master", required=True, type=Path)
    parser.add_argument("--security-id", required=True)
    parser.add_argument(
        "--expected-symbol",
        required=True,
        help="Safety check: capture aborts unless the master maps the ID to this exact symbol.",
    )
    parser.add_argument("--duration-seconds", type=float, default=180.0)
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
        help="D43 shared append-only DAT catalogue used by every consumer",
    )
    parser.add_argument(
        "--archive-on-close",
        action="store_true",
        help="also create and verify the lossless gzip cold archive before publishing completion",
    )
    parser.add_argument("--no-standard", action="store_true")
    parser.add_argument("--no-depth20", action="store_true")
    parser.add_argument(
        "--enable-depth200",
        action="store_true",
        help="DAT-10: opt-in 200-level deep book, never a default. Dhan allows exactly one "
        "instrument per subscription on this endpoint, which --security-id already satisfies. "
        "D33: futures and equity books only — options are capped at 20 levels.",
    )
    protocol = parser.add_mutually_exclusive_group()
    protocol.add_argument(
        "--sig21-calibration",
        action="store_true",
        help="Enforce the H-SIG21 calibration-only capture contract: depth200 is the signal "
        "source, depth20 is retained only for the later response/control surface, the requested "
        "duration covers at least one full NSE session, and no outcome join is authorised.",
    )
    protocol.add_argument(
        "--ofi-full-session-replication",
        action="store_true",
        help="Enforce the prospective 2026-08-20 OFI replication capture profile: one NIFTY "
        "future on Standard/Full, depth20 and depth200 for at least the 09:15-15:40 regular "
        "session. Requested duration is only a preflight floor; final acceptance must inspect "
        "actual receive timestamps and all three channels.",
    )
    parser.add_argument(
        "--channel-start-stagger-seconds",
        type=float,
        default=0.0,
        help="DAT-20: seconds to wait between bringing up successive channel sockets, so "
        "the concurrent socket count rises in observable single steps.",
    )
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=10.0)
    parser.add_argument("--heartbeat-timeout-seconds", type=float, default=5.0)
    parser.add_argument(
        "--trade-quote-freshness-seconds",
        type=float,
        default=1.0,
        help="Maximum age of the older BBO leg eligible for DAT-14 classification.",
    )
    return parser


def _required_channels(config: DhanStreamConfig) -> set[str]:
    required: set[str] = set()
    if config.enable_standard_feed:
        required.add("standard")
    if config.enable_20_level_depth:
        required.add("depth20")
    if config.enable_200_level_depth:
        required.add("depth200")
    return required


def _validate_depth_tier_scope(
    args: argparse.Namespace, mapping: DhanInstrumentMapping
) -> None:
    """D33: the depth tier follows the instrument class, and options stop at 20 levels."""
    if args.enable_depth200 and mapping.instrument.kind not in DEPTH200_ELIGIBLE_KINDS:
        raise ValueError(
            f"--enable-depth200 rejected for {mapping.trading_symbol!r}: the 200-level ladder "
            "is restricted to futures and equity books (D33); "
            f"{mapping.instrument.kind} instruments are capped at "
            f"{OPTION_MAX_DEPTH_LEVELS} levels"
        )
    if args.sig21_calibration and mapping.instrument.kind is not InstrumentKind.FUTURE:
        raise ValueError(
            "H-SIG21 calibration is registered on the NIFTY front-month future; "
            f"{mapping.trading_symbol!r} is a {mapping.instrument.kind} instrument"
        )
    if args.ofi_full_session_replication and (
        mapping.instrument.kind is not InstrumentKind.FUTURE
        or mapping.instrument.underlying.strip().upper() != "NIFTY"
    ):
        raise ValueError(
            "the OFI full-session replication profile requires a NIFTY future; "
            f"{mapping.trading_symbol!r} maps to "
            f"{mapping.instrument.underlying}/{mapping.instrument.kind}"
        )


def _validate_sig21_protocol(args: argparse.Namespace) -> None:
    if not args.sig21_calibration:
        return
    if not args.enable_depth200:
        raise ValueError("H-SIG21 calibration requires the depth200 signal-source channel")
    if args.no_depth20:
        raise ValueError("H-SIG21 calibration requires depth20 for response/control measurement")
    if args.duration_seconds < SIG21_FULL_SESSION_SECONDS:
        raise ValueError("H-SIG21 calibration must request at least one full NSE session")


def _sig21_protocol_metadata(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.sig21_calibration:
        return None
    return {
        "protocol_id": SIG21_PROTOCOL_ID,
        "sample_role": "calibration_only",
        "signal_source_channel": "depth200",
        "response_control_channel": "depth20",
        "registered_family_size": SIG21_REGISTERED_FAMILY_SIZE,
        "registration_commit": SIG21_REGISTRATION_COMMIT,
        "outcome_join_allowed": False,
    }


def _validate_ofi_full_session_protocol(args: argparse.Namespace) -> None:
    if not args.ofi_full_session_replication:
        return
    if args.no_standard:
        raise ValueError("OFI full-session replication requires the Standard/Full channel")
    if args.no_depth20:
        raise ValueError("OFI full-session replication requires the depth20 channel")
    if not args.enable_depth200:
        raise ValueError("OFI full-session replication requires the depth200 channel")
    if args.duration_seconds < OFI_FULL_SESSION_SECONDS:
        raise ValueError(
            "OFI full-session replication must request at least 23,100 seconds; "
            "duration alone is not final regular-session coverage acceptance"
        )


def _ofi_full_session_protocol_metadata(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.ofi_full_session_replication:
        return None
    regular_open, regular_close = nse_equity_derivatives_session_bounds(
        OFI_FULL_SESSION_TRADING_DATE
    )
    return {
        "protocol_id": OFI_FULL_SESSION_PROTOCOL_ID,
        "source_spec": OFI_FULL_SESSION_SOURCE_SPEC,
        "source_amendment": OFI_FULL_SESSION_SOURCE_AMENDMENT,
        "registration_commit": OFI_FULL_SESSION_REGISTRATION_COMMIT,
        "sample_role": "prospective_full_session_replication",
        "trading_date": OFI_FULL_SESSION_TRADING_DATE.isoformat(),
        "required_channels": ["standard", "depth20", "depth200"],
        "regular_session": {
            "timezone": "Asia/Kolkata",
            "open": regular_open.time().isoformat(),
            "close": regular_close.time().isoformat(),
            "seconds": int((regular_close - regular_open).total_seconds()),
        },
        "duration_is_final_coverage_acceptance": False,
        "final_coverage_acceptance": (
            "actual receive timestamps on every required channel must start no later than "
            "09:15:02 and end no earlier than 15:39:58 IST; analysis clips exactly to the "
            "09:15:00-15:40:00 regular session"
        ),
        "outcome_join_allowed": True,
        "sig21_calibration_eligible": False,
        "order_entry_enabled": False,
    }


async def _capture(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.duration_seconds <= 0:
        raise ValueError("duration-seconds must be positive")
    _validate_sig21_protocol(args)
    _validate_ofi_full_session_protocol(args)
    mapping = DhanInstrumentMaster(args.security_master).find_by_security_id(args.security_id)
    if mapping.trading_symbol != args.expected_symbol:
        raise ValueError(
            f"security-ID identity check failed: expected {args.expected_symbol!r}, "
            f"master has {mapping.trading_symbol!r}"
    )
    _validate_depth_tier_scope(args, mapping)
    output_root = resolve_raw_capture_root(
        args.output_root,
        trading_date=mapping.as_of_date,
        allow_nonarchive=args.allow_nonarchive_output,
    )
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=mapping.as_of_date,
        allow_nonarchive=args.allow_nonarchive_output,
        nonarchive_capture_root=output_root,
    )
    credentials = DhanCredentials.from_env_file(args.credentials)
    metrics = StreamMetrics()
    config = DhanStreamConfig(
        enable_standard_feed=not args.no_standard,
        enable_20_level_depth=not args.no_depth20,
        enable_200_level_depth=args.enable_depth200,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
        trade_quote_freshness_seconds=args.trade_quote_freshness_seconds,
        channel_start_stagger_seconds=args.channel_start_stagger_seconds,
    )
    requested_channels = tuple(
        DataChannel(channel) for channel in sorted(_required_channels(config))
    )
    request = DatasetRequest(
        consumer="DAT-capture",
        purpose=(
            OFI_FULL_SESSION_PROTOCOL_ID
            if args.ofi_full_session_replication
            else SIG21_PROTOCOL_ID
            if args.sig21_calibration
            else "shared live market data"
        ),
        trading_date=mapping.as_of_date,
        channels=requested_channels,
        instrument_ids=(mapping.instrument.canonical,),
        allow_active=True,
    )
    session = DataCaptureSession.create(
        catalog=DataCatalog(catalog_path),
        request=request,
        output_root=output_root,
        fsync_every=100,
    )
    manifest = session.manifest
    writer = session.writer
    stream = DhanLiveStream(
        credentials,
        [mapping],
        session.write,
        run_id=str(manifest.run_id),
        config=config,
        metrics=metrics,
    )
    started = time.monotonic()
    capture_elapsed: float | None = None
    stream_error: BaseException | None = None
    task = asyncio.create_task(stream.run())
    done, _ = await asyncio.wait({task}, timeout=args.duration_seconds)
    capture_elapsed = time.monotonic() - started
    if task not in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        try:
            task.result()
            stream_error = RuntimeError("Dhan stream ended unexpectedly")
        except BaseException as exc:
            stream_error = exc
    total_elapsed = time.monotonic() - started
    snapshot = metrics.snapshot(capture_elapsed)
    snapshot["shutdown_seconds"] = max(total_elapsed - capture_elapsed, 0.0)
    required_channels = _required_channels(config)
    missing_channels = sorted(
        channel for channel in required_channels if metrics.source_packets[channel] == 0
    )
    snapshot.update(
        {
            "run_id": str(manifest.run_id),
            "dataset_id": session.dataset_id,
            "data_catalog": str(DataCatalog(catalog_path).path),
            "instrument_id": mapping.instrument.canonical,
            "dhan_security_id": mapping.security_id,
            "trading_symbol": mapping.trading_symbol,
            "test_configuration": {
                "standard_full_5_level": not args.no_standard,
                "depth20": not args.no_depth20,
                "depth200": args.enable_depth200,
                "instrument_kind": str(mapping.instrument.kind),
                "depth200_eligible_kinds": sorted(str(kind) for kind in DEPTH200_ELIGIBLE_KINDS),
                "option_max_depth_levels": OPTION_MAX_DEPTH_LEVELS,
                "duration_seconds_requested": args.duration_seconds,
                "dat09_decision": False,
                "channel_start_stagger_seconds": args.channel_start_stagger_seconds,
                "channel_start_order": list(stream.channel_start_order),
                "sig21_protocol": _sig21_protocol_metadata(args),
                "ofi_full_session_replication_protocol": (
                    _ofi_full_session_protocol_metadata(args)
                ),
            },
            "stream_error_type": type(stream_error).__name__ if stream_error else None,
            "acceptance": {
                "required_channels": sorted(required_channels),
                "missing_channels": missing_channels,
                "regular_session_timestamp_coverage_required": bool(
                    args.ofi_full_session_replication
                ),
                "duration_only_is_sufficient": not args.ofi_full_session_replication,
            },
        }
    )
    metrics_path = manifest.run_dir / f"capture_metrics_{manifest.run_id}.json"
    _exclusive_json(metrics_path, snapshot)
    manifest.register_existing(metrics_path, kind="capture_metrics")
    audit = CollectorQualityAudit.from_metrics(
        str(manifest.run_id), metrics, recorded_at=datetime.now(IST)
    )
    write_quality_audit(manifest, audit)
    if stream_error:
        handle = session.close(
            invalidation_reason=f"stream failed: {type(stream_error).__name__}",
            archive=args.archive_on_close,
        )
        return 2, {
            **snapshot,
            "run_dir": str(manifest.run_dir),
            "dataset_handle": handle.model_dump(mode="json"),
            "status": "invalidated",
        }
    if writer.rows_written == 0:
        handle = session.close(
            invalidation_reason="capture interval produced zero normalized rows",
            archive=args.archive_on_close,
        )
        return 3, {
            **snapshot,
            "run_dir": str(manifest.run_dir),
            "dataset_handle": handle.model_dump(mode="json"),
            "status": "invalidated",
        }
    if missing_channels:
        handle = session.close(
            invalidation_reason=(
                "enabled channels produced zero source packets: " + ",".join(missing_channels)
            ),
            archive=args.archive_on_close,
        )
        return 4, {
            **snapshot,
            "run_dir": str(manifest.run_dir),
            "dataset_handle": handle.model_dump(mode="json"),
            "status": "invalidated",
        }
    handle = session.close(archive=args.archive_on_close)
    return 0, {
        **snapshot,
        "run_dir": str(manifest.run_dir),
        "dataset_handle": handle.model_dump(mode="json"),
        "status": "completed",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, summary = asyncio.run(_capture(args))
    except DatasetAlreadyActiveError as exc:
        print(
            json.dumps(
                {
                    "status": "reused_active_dataset",
                    "dataset_handle": exc.handle.model_dump(mode="json"),
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    except BaseException as exc:
        # Never print exception text: an upstream networking exception may contain an auth URL.
        print(
            json.dumps({"status": "preflight_failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
