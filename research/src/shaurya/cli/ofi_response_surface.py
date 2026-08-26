"""Run the isolated prospective D49 C8 response-surface scan."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DatasetStatus
from shaurya.contracts.timing import IST
from shaurya.data import DataAccess, DataCatalog, resolve_data_catalog

from shaurya.analytics.ofi_response_surface import (
    FORECAST_CADENCE_SECONDS,
    HORIZONS_SECONDS,
    ResponseSurfaceTracker,
    persist_tracker,
    surface_diagnostics,
)
from shaurya.analytics.rolling_c8 import append_jsonl
from shaurya.cli.rolling_c8 import RollingTapeBuffer
from shaurya.signals.ofi_horserace import build_horserace_observations
from shaurya.signals.reference_prices import build_displayed_mid_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--legacy-producer-pid", type=int, required=True)
    parser.add_argument("--data-catalog", type=Path, required=True)
    parser.add_argument("--trading-date", type=date.fromisoformat, default=datetime.now(IST).date())
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--issue-until", required=True, help="IST HH:MM:SS")
    parser.add_argument("--stop-at", required=True, help="IST HH:MM:SS")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser


def _today_at(raw: str, trading_date: date) -> datetime:
    parsed = datetime.strptime(raw, "%H:%M:%S").time()
    return datetime.combine(trading_date, parsed, tzinfo=IST)


def run(args: argparse.Namespace) -> dict[str, Any]:
    catalog_path = resolve_data_catalog(args.data_catalog, trading_date=args.trading_date)
    access = DataAccess(DataCatalog(catalog_path))
    handle = access.adopt_active_legacy_tape(
        args.tape,
        consumer="ANL-06-C8-RESPONSE-SURFACE",
        purpose="prospective smoothness scan; no dashboard output",
        producer_pid=args.legacy_producer_pid,
    )
    if handle.status is DatasetStatus.INVALIDATED:
        raise ValueError("response-surface scan cannot consume an invalidated dataset")
    issue_until = _today_at(args.issue_until, args.trading_date)
    stop_at = _today_at(args.stop_at, args.trading_date)
    if issue_until >= stop_at:
        raise ValueError("issue-until must precede stop-at")
    tape = RollingTapeBuffer(Path(handle.tape_path))
    tracker = ResponseSurfaceTracker()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    forecast_log = args.artifact_dir / "forecasts.jsonl"
    outcome_log = args.artifact_dir / "outcomes.jsonl"
    while datetime.now(IST) < stop_at:
        tape.poll()
        price_path = build_displayed_mid_path(tape.depth20)
        outcomes = tracker.mature(price_path)
        append_jsonl(outcome_log, outcomes)
        newest = tape.depth200[-1].receive_ts_ns if tape.depth200 else None
        due = newest is not None and (
            tracker.last_forecast_anchor_ts_ns is None
            or newest - tracker.last_forecast_anchor_ts_ns
            >= int(FORECAST_CADENCE_SECONDS * 1_000_000_000)
        )
        issued: list[dict[str, Any]] = []
        if due and datetime.now(IST) <= issue_until:
            observations, _ = build_horserace_observations(
                depth200_states=tape.depth200,
                depth20_states=tape.depth20,
                rows=(),
                tape_index=0,
                run_id=str(handle.dataset_id),
                level_counts=(10,),
                response_horizons=HORIZONS_SECONDS,
                retain_unlabelled=True,
            )
            if observations:
                issued = tracker.issue(observations, forecast_position=len(observations) - 1)
                append_jsonl(forecast_log, issued)
        persist_tracker(tracker, args.state_output, source=tape.source(handle.dataset_id))
        if issued or outcomes:
            print(json.dumps({"at": datetime.now(UTC).isoformat(), "issued": len(issued),
                              "matured": len(outcomes), "pending": len(tracker.pending),
                              "last_receive_ts": tape.last_receive_ts}), flush=True)
        time.sleep(args.poll_seconds)
    payload = tracker.payload(source=tape.source(handle.dataset_id), status="completed")
    payload["smoothness"] = surface_diagnostics(payload["cells"])
    from shaurya.analytics.live_ofi_studies import atomic_write_json
    atomic_write_json(args.artifact_dir / "final.json", payload)
    persist_tracker(
        tracker,
        args.state_output,
        source=tape.source(handle.dataset_id),
        status="completed",
    )
    print(json.dumps(payload["smoothness"], sort_keys=True), flush=True)
    return payload


def main(argv: list[str] | None = None) -> int:
    run(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
