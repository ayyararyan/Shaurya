"""Follow one DAT tape and publish causal 30-minute rolling C8 forecasts."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from shaurya.analytics.live_ofi_studies import complete_prefix_offset
from shaurya.analytics.rolling_c8 import (
    FORECAST_CADENCE_SECONDS,
    HORIZONS_SECONDS,
    RollingC8Tracker,
    append_jsonl,
    persist_tracker,
)
from shaurya.contracts.data import DatasetStatus
from shaurya.contracts.timing import IST
from shaurya.data.access import DataAccess, DataCatalog
from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    BookState,
    build_states,
    parse_receive_ts_ns,
)
from shaurya.data.storage import resolve_data_catalog
from shaurya.signals.ofi_horserace import build_horserace_observations
from shaurya.signals.reference_prices import build_displayed_mid_path

BUFFER_SECONDS = 31.0 * 60.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-id")
    source.add_argument("--tape", type=Path)
    parser.add_argument("--legacy-producer-pid", type=int)
    parser.add_argument("--data-catalog", type=Path)
    parser.add_argument("--trading-date", type=date.fromisoformat, default=datetime.now(IST).date())
    parser.add_argument("--allow-nonarchive-catalog", action="store_true")
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    return parser


def _complete_last_row(path: Path) -> tuple[int, dict[str, Any]]:
    limit = complete_prefix_offset(path)
    width = 1 << 20
    while width <= max(limit * 2, 1 << 20):
        start = max(0, limit - width)
        with path.open("rb") as handle:
            handle.seek(start)
            chunk = handle.read(limit - start)
        lines = chunk.splitlines()
        if start and lines:
            lines = lines[1:]
        if lines:
            loaded: Any = json.loads(lines[-1])
            if isinstance(loaded, dict):
                return limit, dict(loaded)
        width *= 2
    raise ValueError("unable to read the final complete JSONL row")


def find_start_offset(path: Path, cutoff_ts_ns: int) -> int:
    """Binary-search a sorted JSONL tape for a complete row just before ``cutoff_ts_ns``."""

    limit = complete_prefix_offset(path)
    low, high = 0, limit
    candidate = 0
    for _ in range(40):
        if high - low < 4096:
            break
        probe = (low + high) // 2
        with path.open("rb") as handle:
            handle.seek(probe)
            if probe:
                handle.readline()
            offset = handle.tell()
            encoded = handle.readline()
            next_offset = handle.tell()
        if not encoded or not encoded.endswith(b"\n"):
            high = probe
            continue
        loaded: Any = json.loads(encoded)
        if not isinstance(loaded, dict) or not isinstance(loaded.get("receive_ts"), str):
            raise ValueError("tape row lacks receive_ts")
        stamp = parse_receive_ts_ns(loaded["receive_ts"])
        if stamp < cutoff_ts_ns:
            candidate = offset
            low = next_offset
        else:
            high = probe
    return candidate


def _append_state(states: list[BookState], state: BookState) -> None:
    if states and (
        states[-1].receive_ts_ns,
        states[-1].connection_epoch,
    ) == (state.receive_ts_ns, state.connection_epoch):
        states[-1] = state
    elif not states or state.receive_ts_ns >= states[-1].receive_ts_ns:
        states.append(state)
    else:
        raise ValueError("book-state capture time moved backwards")


class RollingTapeBuffer:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        _, last = _complete_last_row(self.path)
        raw_ts = last.get("receive_ts")
        if not isinstance(raw_ts, str):
            raise ValueError("last tape row has no receive_ts")
        cutoff = parse_receive_ts_ns(raw_ts) - int(BUFFER_SECONDS * 1_000_000_000)
        self.offset = find_start_offset(self.path, cutoff)
        self.depth20: list[BookState] = []
        self.depth200: list[BookState] = []
        self.rows_parsed = 0
        self.last_receive_ts = raw_ts
        self.poll()

    def poll(self) -> int:
        limit = complete_prefix_offset(self.path)
        depth20_rows: list[dict[str, Any]] = []
        depth200_rows: list[dict[str, Any]] = []
        consumed = 0
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            while handle.tell() < limit:
                encoded = handle.readline()
                if not encoded or handle.tell() > limit or not encoded.endswith(b"\n"):
                    break
                loaded: Any = json.loads(encoded)
                if not isinstance(loaded, dict):
                    raise ValueError("tape JSONL row is not an object")
                row = dict(loaded)
                raw_ts = row.get("receive_ts")
                if not isinstance(raw_ts, str):
                    raise ValueError("tape row has no receive_ts")
                self.last_receive_ts = raw_ts
                if row.get("event_type") == DEPTH20:
                    depth20_rows.append(row)
                elif row.get("event_type") == DEPTH200:
                    depth200_rows.append(row)
                consumed += 1
            self.offset = handle.tell()
        for state in build_states(depth20_rows, DEPTH20):
            _append_state(self.depth20, state)
        for state in build_states(depth200_rows, DEPTH200):
            _append_state(self.depth200, state)
        self.rows_parsed += consumed
        newest = max(
            self.depth20[-1].receive_ts_ns if self.depth20 else 0,
            self.depth200[-1].receive_ts_ns if self.depth200 else 0,
        )
        cutoff = newest - int(BUFFER_SECONDS * 1_000_000_000)
        self.depth20 = [state for state in self.depth20 if state.receive_ts_ns >= cutoff]
        self.depth200 = [state for state in self.depth200 if state.receive_ts_ns >= cutoff]
        return consumed

    def source(self, dataset_id: str) -> dict[str, Any]:
        return {
            "dataset_id": dataset_id,
            "tape_path": str(self.path),
            "byte_offset": self.offset,
            "last_receive_ts": self.last_receive_ts,
            "rows_parsed_since_start": self.rows_parsed,
            "depth20_buffered": len(self.depth20),
            "depth200_buffered": len(self.depth200),
        }


def _append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    append_jsonl(path, rows)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            loaded: Any = json.loads(line)
            if isinstance(loaded, dict):
                rows.append(dict(loaded))
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=args.trading_date,
        allow_nonarchive=args.allow_nonarchive_catalog,
    )
    access = DataAccess(DataCatalog(catalog_path))
    if args.dataset_id is not None:
        handle = access.handle(args.dataset_id)
    else:
        if args.legacy_producer_pid is None:
            raise ValueError("active pre-DAT tape requires --legacy-producer-pid")
        handle = access.adopt_active_legacy_tape(
            args.tape,
            consumer="ANL-06-ROLLING-C8-30M",
            purpose="causal 30-minute rolling C8 forecast dashboard",
            producer_pid=args.legacy_producer_pid,
        )
    if handle.status is DatasetStatus.INVALIDATED:
        raise ValueError("rolling C8 cannot consume an invalidated dataset")
    tape = RollingTapeBuffer(Path(handle.tape_path))
    tracker = RollingC8Tracker.load(args.state_output)
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    forecast_log = args.artifact_dir / "forecasts.jsonl"
    outcome_log = args.artifact_dir / "outcomes.jsonl"
    initial_price_path = build_displayed_mid_path(tape.depth20)
    tracker.restore_recent_win_scores(
        _read_jsonl(outcome_log), as_of_ts_ns=initial_price_path.coverage_end_ts_ns
    )
    while True:
        tape.poll()
        price_path = build_displayed_mid_path(tape.depth20)
        outcomes = tracker.mature(price_path)
        _append_rows(outcome_log, outcomes)
        newest = tape.depth200[-1].receive_ts_ns if tape.depth200 else None
        due = newest is not None and (
            tracker.last_forecast_anchor_ts_ns is None
            or newest - tracker.last_forecast_anchor_ts_ns
            >= int(FORECAST_CADENCE_SECONDS * 1_000_000_000)
        )
        issued: list[dict[str, Any]] = []
        if due:
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
                _append_rows(forecast_log, issued)
        persist_tracker(tracker, args.state_output, source=tape.source(handle.dataset_id))
        if issued or outcomes:
            print(
                json.dumps(
                    {
                        "updated_at": datetime.now(UTC).isoformat(),
                        "issued": len(issued),
                        "matured": len(outcomes),
                        "pending": len(tracker.pending),
                        "last_receive_ts": tape.last_receive_ts,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if args.once:
            return tracker.payload(source=tape.source(handle.dataset_id))
        time.sleep(args.poll_seconds)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run(args)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
