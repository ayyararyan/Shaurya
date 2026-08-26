#!/usr/bin/env python3
# ruff: noqa: E501
"""One-shot, quality-aware post-close research handoff for one Shaurya dataset.

The runner observes only the append-only DAT catalogue while a dataset is active.  It opens the
published tape only after a terminal COMPLETED handle passes lifecycle, manifest, hash, seek-index,
and coverage gates. It derives a replay-side quality audit when no native audit was published,
uses only buffered clean windows, and stores outputs in a separate derived lane. It never imports a
broker client, changes a catalogue record, or invokes D51.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from shaurya.contracts.artifacts import sha256_file
from shaurya.contracts.data import DatasetStatus
from shaurya.data.access import DataAccess, DataCatalog

RUNNER_VERSION = "post-close-alpha-v2-quality-aware"
GRID_SECONDS = 5
HORIZONS_SECONDS = (5, 30)
EMBARGO_SECONDS = 30
STALE_SECONDS = 2
TRADE_WINDOW_SECONDS = 10
RV_WINDOW_SECONDS = 30
MIN_COVERAGE_SECONDS = 3 * 60 * 60
MIN_PANEL_ROWS = 5_000
MIN_TRAIN_ROWS = 3_000
MIN_TEST_ROWS = 1_000
MIN_UNIQUE_TRAIN_TIMES = 300
MIN_UNIQUE_TEST_TIMES = 100
BOOTSTRAP_REPLICATES = 400
BUFFER_SECONDS = (10, 30, 60)
PRIMARY_BUFFER_SECONDS = 30
MIN_CLEAN_WINDOW_SECONDS = 5 * 60
RECEIVE_GAP_SECONDS = 2.0
EXCLUSION_FLAGS = {
    "sequence_gap",
    "duplicate_sequence",
    "sequence_regression",
    "connection_gap",
    "reconnected",
    "heartbeat_timeout",
    "exchange_time_regression",
    "partial_book",
    "crossed_book",
    "stale_quote",
    "invalid_depth",
}
CONTROL_NAMES = (
    "option_log_mid",
    "option_relative_spread",
    "option_microprice_dislocation",
    "option_depth_imbalance",
    "option_return_5s",
    "option_is_call",
    "option_strike_scaled",
    "time_sin",
    "time_cos",
)
FUTURES_NAMES = (
    "futures_log_mid",
    "futures_relative_spread",
    "futures_microprice_dislocation",
    "futures_depth_imbalance",
    "futures_log_trade_intensity_10s",
    "futures_realized_volatility_30s",
)


class GateFailure(RuntimeError):
    pass


@dataclass(slots=True)
class State:
    ts_ns: int
    mid: float
    spread: float
    microprice: float
    imbalance: float


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def append_status(path: Path, phase: str, **details: Any) -> None:
    record = {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "phase": phase,
        **details,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sum_counts(value: Any) -> int:
    if not isinstance(value, dict):
        raise GateFailure("quality counter group is missing or malformed")
    counts = []
    for item in value.values():
        if not isinstance(item, int) or item < 0:
            raise GateFailure("quality counter is not a non-negative integer")
        counts.append(item)
    return sum(counts)


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise GateFailure(f"JSON artifact is not an object: {path.name}")
    return loaded


def manifest_gate(handle: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if handle.manifest_path is None:
        raise GateFailure("completed handle has no manifest path")
    manifest_path = Path(handle.manifest_path)
    if not manifest_path.is_file():
        raise GateFailure("published manifest is missing")
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateFailure(f"manifest JSON is invalid at line {line_number}") from exc
        if not isinstance(event, dict):
            raise GateFailure(f"manifest event {line_number} is not an object")
        if event.get("run_id") != handle.dataset_id:
            raise GateFailure("manifest mixes or misstates run IDs")
        if event.get("manifest_sequence") != line_number:
            raise GateFailure("manifest sequence is not contiguous")
        events.append(event)
    event_types = [str(item.get("event_type")) for item in events]
    if event_types.count("run_started") != 1 or event_types.count("run_completed") != 1:
        raise GateFailure("manifest does not contain exactly one start and one completion")
    if event_types[-1] != "run_completed":
        raise GateFailure("manifest terminal event is not run_completed")
    if any(item in event_types for item in ("run_invalidated", "artifact_failed")):
        raise GateFailure("manifest contains invalidation or failed-artifact evidence")
    completed = events[-1]
    if completed.get("status") != "completed" or int(completed.get("rows", -1)) != handle.rows:
        raise GateFailure("manifest completion summary disagrees with catalog rows")

    artifacts: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_type") != "artifact_closed":
            continue
        name = str(event.get("artifact", ""))
        path = manifest_path.parent / name
        if not path.is_file():
            raise GateFailure(f"registered manifest artifact is missing: {name}")
        if sha256_file(path) != event.get("sha256"):
            raise GateFailure(f"registered manifest artifact hash differs: {name}")
        artifacts[str(event.get("kind"))] = {**event, "path": str(path)}
    tape_event = artifacts.get("market_data_tape")
    if tape_event is None or tape_event.get("sha256") != handle.tape_sha256:
        raise GateFailure("manifest tape registration disagrees with completed handle")
    coverage_event = artifacts.get("chain_coverage")
    if coverage_event is None:
        raise GateFailure("manifest has no registered chain coverage artifact")
    return completed, read_json(Path(coverage_event["path"]))


def completed_dataset_gate(handle: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {
        "completed_at": handle.completed_at,
        "coverage_start": handle.coverage_start,
        "coverage_end": handle.coverage_end,
        "tape_sha256": handle.tape_sha256,
        "index_path": handle.index_path,
        "index_sha256": handle.index_sha256,
    }
    missing = sorted(name for name, value in required.items() if value is None)
    if handle.status is not DatasetStatus.COMPLETED:
        raise GateFailure(f"dataset terminal state is {handle.status}, not completed")
    if handle.invalidation_reason is not None:
        raise GateFailure("completed dataset unexpectedly carries an invalidation reason")
    if missing or handle.rows <= 0 or handle.bytes <= 0:
        raise GateFailure("completed handle lacks terminal evidence: " + ",".join(missing))
    coverage_seconds = (handle.coverage_end - handle.coverage_start).total_seconds()
    if coverage_seconds < MIN_COVERAGE_SECONDS:
        raise GateFailure(f"coverage is only {coverage_seconds:.1f}s; need {MIN_COVERAGE_SECONDS}s")

    tape = Path(handle.tape_path)
    index_path = Path(handle.index_path)
    if not tape.is_file() or not index_path.is_file():
        raise GateFailure("published tape or seek index is missing")
    if tape.stat().st_size != handle.bytes:
        raise GateFailure("published tape byte count disagrees with catalog")
    observed_tape_hash = sha256_file(tape)
    observed_index_hash = sha256_file(index_path)
    if observed_tape_hash != handle.tape_sha256:
        raise GateFailure("published tape SHA-256 differs from catalog")
    if observed_index_hash != handle.index_sha256:
        raise GateFailure("published index SHA-256 differs from catalog")
    index = read_json(index_path)
    if index.get("schema_version") != "1.0.0" or index.get("tape_name") != tape.name:
        raise GateFailure("seek index schema or tape binding is invalid")
    if index.get("tape_sha256") != handle.tape_sha256:
        raise GateFailure("seek index is not bound to the published tape hash")
    if int(index.get("rows", -1)) != handle.rows or int(index.get("bytes", -1)) != handle.bytes:
        raise GateFailure("seek index row/byte counts disagree with catalog")
    if not index.get("receive_time_monotone"):
        raise GateFailure("seek index reports non-monotone receive timestamps")
    if index.get("coverage_start") != handle.coverage_start.isoformat():
        raise GateFailure("seek-index coverage start disagrees with catalog")
    if index.get("coverage_end") != handle.coverage_end.isoformat():
        raise GateFailure("seek-index coverage end disagrees with catalog")
    checkpoints = index.get("checkpoints")
    if (
        not isinstance(checkpoints, list)
        or not checkpoints
        or checkpoints[0].get("row_number") != 1
    ):
        raise GateFailure("seek index has no valid first checkpoint")

    completed, coverage = manifest_gate(handle)
    if completed.get("run_id") != handle.dataset_id:
        raise GateFailure("manifest completion run ID disagrees with catalog")
    if coverage.get("run_id") != handle.dataset_id or int(coverage.get("rows", -1)) != handle.rows:
        raise GateFailure("chain coverage row count or run ID disagrees with catalog")
    if coverage.get("stream_error") is not None:
        raise GateFailure("chain coverage reports a terminal stream error")
    requested = int(coverage.get("requested_instruments", -1))
    covered = int(coverage.get("instruments_with_packets", -1))
    silent = int(coverage.get("instruments_without_packets", -1))
    if requested <= 0 or covered != requested or silent != 0:
        raise GateFailure("chain coverage reports silent or inconsistent instruments")
    return index, coverage


def book_state(row: Any) -> State:
    if not row.bids or not row.asks:
        raise GateFailure("replay encountered a partial book")
    bid = float(row.bids[0].price)
    ask = float(row.asks[0].price)
    if bid <= 0 or ask <= 0 or bid >= ask:
        raise GateFailure("replay encountered an invalid or crossed book")
    bid_q = float(row.bids[0].quantity)
    ask_q = float(row.asks[0].quantity)
    total_top = bid_q + ask_q
    if total_top <= 0:
        raise GateFailure("replay encountered zero top-of-book depth")
    bid_depth = sum(float(level.quantity) for level in row.bids[:5])
    ask_depth = sum(float(level.quantity) for level in row.asks[:5])
    total_depth = bid_depth + ask_depth
    if total_depth <= 0:
        raise GateFailure("replay encountered zero five-level depth")
    return State(
        ts_ns=int(row.receive_ts.timestamp() * 1_000_000_000),
        mid=(bid + ask) / 2.0,
        spread=ask - bid,
        microprice=(ask * bid_q + bid * ask_q) / total_top,
        imbalance=(bid_depth - ask_depth) / total_depth,
    )


def parse_strike(instrument_id: str) -> float:
    parts = instrument_id.split(":")
    try:
        return float(parts[-2])
    except (ValueError, IndexError) as exc:
        raise GateFailure(f"cannot parse option strike: {instrument_id}") from exc


def emit_snapshot(
    grid_ns: int,
    epoch: int,
    futures: State | None,
    options: dict[str, State],
    future_mid_history: deque[tuple[int, float]],
    trade_history: deque[tuple[int, int]],
    snapshots: dict[str, dict[int, dict[str, float]]],
) -> int:
    stale_ns = STALE_SECONDS * 1_000_000_000
    if futures is None or grid_ns - futures.ts_ns > stale_ns:
        return 0
    while (
        future_mid_history
        and future_mid_history[0][0] < grid_ns - RV_WINDOW_SECONDS * 1_000_000_000
    ):
        future_mid_history.popleft()
    while trade_history and trade_history[0][0] < grid_ns - TRADE_WINDOW_SECONDS * 1_000_000_000:
        trade_history.popleft()
    mids = np.asarray(
        [value for stamp, value in future_mid_history if stamp <= grid_ns], dtype=float
    )
    if mids.size < 10 or np.any(mids <= 0):
        return 0
    returns = np.diff(np.log(mids))
    rv = float(np.sqrt(np.sum(returns * returns)))
    intensity = float(sum(value for stamp, value in trade_history if stamp <= grid_ns))
    count = 0
    for instrument, option in options.items():
        if grid_ns - option.ts_ns > stale_ns:
            continue
        snapshots[instrument][grid_ns] = {
            "connection_epoch": epoch,
            "option_mid": option.mid,
            "option_spread": option.spread,
            "option_microprice": option.microprice,
            "option_imbalance": option.imbalance,
            "futures_mid": futures.mid,
            "futures_spread": futures.spread,
            "futures_microprice": futures.microprice,
            "futures_imbalance": futures.imbalance,
            "futures_trade_intensity": intensity,
            "futures_rv": rv,
        }
        count += 1
    return count


def _merge_intervals(intervals: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if end < start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _subtract_intervals(
    start: int, end: int, exclusions: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    cursor = start
    clean: list[tuple[int, int]] = []
    for bad_start, bad_end in _merge_intervals(exclusions):
        bad_start = max(bad_start, start)
        bad_end = min(bad_end, end)
        if bad_end < start or bad_start > end:
            continue
        if bad_start > cursor:
            clean.append((cursor, bad_start))
        cursor = max(cursor, bad_end)
    if cursor < end:
        clean.append((cursor, end))
    return clean


def derive_replay_audit(
    access: DataAccess, handle: Any, coverage: dict[str, Any]
) -> tuple[dict[str, Any], dict[int, list[tuple[int, int, int]]]]:
    """Reconstruct quality facts from records; this is not a collector-native audit."""
    epochs: dict[int, dict[str, Any]] = {}
    quality_counts: Counter[str] = Counter()
    book_invalid_counts: Counter[str] = Counter()
    event_times: dict[int, list[tuple[int, str]]] = defaultdict(list)
    transitions: list[dict[str, Any]] = []
    uncertain_gaps: list[dict[str, Any]] = []
    previous_sequence = 0
    previous_ts_ns: int | None = None
    previous_epoch: int | None = None
    replay_rows = 0

    for row in access.rows(handle):
        replay_rows += 1
        if row.run_id != handle.dataset_id:
            raise GateFailure("replay tape mixes run IDs")
        if row.receive_sequence != previous_sequence + 1:
            raise GateFailure("stored receive sequence is not contiguous")
        ts_ns = int(row.receive_ts.timestamp() * 1_000_000_000)
        epoch = int(row.connection_epoch)
        record = epochs.setdefault(
            epoch,
            {
                "rows": 0,
                "first_sequence": int(row.receive_sequence),
                "last_sequence": int(row.receive_sequence),
                "first_ts_ns": ts_ns,
                "last_ts_ns": ts_ns,
                "connection_ids": set(),
                "quality_counts": Counter(),
            },
        )
        record["rows"] += 1
        record["last_sequence"] = int(row.receive_sequence)
        record["last_ts_ns"] = ts_ns
        record["connection_ids"].add(row.connection_id)
        row_flags = {str(flag) for flag in row.quality_flags}
        for flag in row_flags:
            quality_counts[flag] += 1
            record["quality_counts"][flag] += 1
        exclusion_flags = row_flags.intersection(EXCLUSION_FLAGS)
        for flag in exclusion_flags:
            event_times[epoch].append((ts_ns, f"row_flag:{flag}"))

        invalid_reason: str | None = None
        try:
            book_state(row)
        except GateFailure as exc:
            invalid_reason = str(exc)
            if "partial" in invalid_reason:
                label = "partial_book"
            elif "crossed" in invalid_reason:
                label = "crossed_book"
            elif "depth" in invalid_reason:
                label = "invalid_depth"
            else:
                label = "invalid_book"
            book_invalid_counts[label] += 1
            event_times[epoch].append((ts_ns, f"replay:{label}"))

        if previous_ts_ns is not None:
            gap_seconds = (ts_ns - previous_ts_ns) / 1_000_000_000
            if previous_epoch != epoch:
                transitions.append(
                    {
                        "from_epoch": previous_epoch,
                        "to_epoch": epoch,
                        "previous_sequence": previous_sequence,
                        "sequence": int(row.receive_sequence),
                        "previous_ts_ns": previous_ts_ns,
                        "ts_ns": ts_ns,
                        "gap_seconds": gap_seconds,
                        "first_row_flags": sorted(row_flags),
                    }
                )
            elif gap_seconds > RECEIVE_GAP_SECONDS:
                uncertain_gaps.append(
                    {
                        "epoch": epoch,
                        "previous_sequence": previous_sequence,
                        "sequence": int(row.receive_sequence),
                        "previous_ts_ns": previous_ts_ns,
                        "ts_ns": ts_ns,
                        "gap_seconds": gap_seconds,
                        "interpretation": "no records; source sequence unavailable",
                    }
                )
                event_times[epoch].extend(
                    [
                        (previous_ts_ns, "receive_gap_start"),
                        (ts_ns, "receive_gap_end"),
                    ]
                )
        previous_sequence = int(row.receive_sequence)
        previous_ts_ns = ts_ns
        previous_epoch = epoch

    if replay_rows != handle.rows:
        raise GateFailure(f"audit replay rows {replay_rows} disagree with catalog {handle.rows}")
    observed_connections = len(epochs)
    observed_transitions = len(transitions)
    observed_heartbeats = quality_counts["heartbeat_timeout"]
    summary_connections = int((coverage.get("connections") or {}).get("standard", -1))
    summary_reconnects = int((coverage.get("reconnect_attempts") or {}).get("standard", -1))
    summary_heartbeats = int((coverage.get("heartbeat_timeouts") or {}).get("standard", -1))
    if (summary_connections, summary_reconnects, summary_heartbeats) != (
        observed_connections,
        observed_transitions,
        observed_heartbeats,
    ):
        raise GateFailure("summary reconnect counters do not reconcile to replay evidence")
    for transition in transitions:
        required = {"connection_gap", "heartbeat_timeout", "reconnected"}
        if not required.issubset(transition["first_row_flags"]):
            raise GateFailure("epoch transition lacks expected first-row reconnect evidence")

    serialized_epochs: list[dict[str, Any]] = []
    clean_windows_by_buffer: dict[int, list[tuple[int, int, int]]] = {}
    buffer_summaries: dict[str, Any] = {}
    for epoch, record in sorted(epochs.items()):
        serialized_epochs.append(
            {
                **record,
                "epoch": epoch,
                "connection_ids": sorted(record["connection_ids"]),
                "quality_counts": dict(sorted(record["quality_counts"].items())),
                "duration_seconds": (record["last_ts_ns"] - record["first_ts_ns"]) / 1_000_000_000,
            }
        )
    for buffer_seconds in BUFFER_SECONDS:
        buffer_ns = buffer_seconds * 1_000_000_000
        all_windows: list[tuple[int, int, int]] = []
        epoch_windows: list[dict[str, Any]] = []
        for epoch, record in sorted(epochs.items()):
            start = record["first_ts_ns"]
            end = record["last_ts_ns"]
            exclusions = [(start, start + buffer_ns), (end - buffer_ns, end)]
            exclusions.extend(
                (stamp - buffer_ns, stamp + buffer_ns) for stamp, _ in event_times[epoch]
            )
            windows = [
                window
                for window in _subtract_intervals(start, end, exclusions)
                if window[1] - window[0] >= MIN_CLEAN_WINDOW_SECONDS * 1_000_000_000
            ]
            all_windows.extend((epoch, *window) for window in windows)
            epoch_windows.append(
                {
                    "epoch": epoch,
                    "clean_windows": [list(window) for window in windows],
                    "clean_seconds": sum(end_ - start_ for start_, end_ in windows) / 1_000_000_000,
                }
            )
        clean_windows_by_buffer[buffer_seconds] = all_windows
        buffer_summaries[str(buffer_seconds)] = {
            "buffer_seconds": buffer_seconds,
            "minimum_clean_window_seconds": MIN_CLEAN_WINDOW_SECONDS,
            "epochs": epoch_windows,
            "total_clean_seconds": sum(item[2] - item[1] for item in all_windows) / 1_000_000_000,
        }
    if buffer_summaries[str(PRIMARY_BUFFER_SECONDS)]["total_clean_seconds"] < MIN_COVERAGE_SECONDS:
        raise GateFailure("less than three hours of material clean support remains")

    audit = {
        "audit_origin": "derived_replay_audit_not_collector_native",
        "replay_rows": replay_rows,
        "stored_receive_sequence_contiguous": True,
        "source_sequence_available": quality_counts["source_sequence_unavailable"] == 0,
        "quality_counts": dict(sorted(quality_counts.items())),
        "book_invalid_counts": dict(sorted(book_invalid_counts.items())),
        "epochs": serialized_epochs,
        "confirmed_epoch_transitions": transitions,
        "uncertain_receive_gaps_within_epoch": uncertain_gaps,
        "counter_reconciliation": {
            "summary_connections": summary_connections,
            "observed_epochs": observed_connections,
            "summary_reconnect_attempts": summary_reconnects,
            "observed_epoch_transitions": observed_transitions,
            "summary_heartbeat_timeouts": summary_heartbeats,
            "observed_heartbeat_first_row_flags": observed_heartbeats,
        },
        "window_labels": {
            "clean": "inside one epoch and outside all buffered quality events",
            "excluded": "epoch edges or buffer around reconnect, gap, partial/crossed/stale/invalid book, sequence, or exchange-time-regression evidence",
            "uncertain": "record-free receive gaps; source sequence is unavailable, so upstream loss cannot be tested",
        },
        "buffers": buffer_summaries,
    }
    return audit, clean_windows_by_buffer


def _eligible_for_window(
    stamp: int,
    epoch: int,
    windows: Sequence[tuple[int, int, int]],
) -> bool:
    support_ns = max(RV_WINDOW_SECONDS, max(HORIZONS_SECONDS)) * 1_000_000_000
    return any(
        item_epoch == epoch and start <= stamp - support_ns and stamp + support_ns <= end
        for item_epoch, start, end in windows
    )


def build_panel(
    access: DataAccess,
    handle: Any,
    clean_windows_by_buffer: dict[int, list[tuple[int, int, int]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    futures_id = next((item for item in handle.instrument_ids if ":future:" in item), None)
    option_ids = tuple(item for item in handle.instrument_ids if ":option:" in item)
    option_id_set = set(option_ids)
    if futures_id is None or len(option_ids) < 10:
        raise GateFailure("dataset lacks one future plus a usable option cross-section")
    states: dict[str, State] = {}
    future_mid_history: deque[tuple[int, float]] = deque()
    trade_history: deque[tuple[int, int]] = deque()
    snapshots: dict[str, dict[int, dict[str, float]]] = defaultdict(dict)
    grid_ns: int | None = None
    current_epoch: int | None = None
    grid_step_ns = GRID_SECONDS * 1_000_000_000
    replay_rows = 0
    emitted = 0
    for row in access.rows(handle):
        replay_rows += 1
        epoch = int(row.connection_epoch)
        ts_ns = int(row.receive_ts.timestamp() * 1_000_000_000)
        if current_epoch != epoch:
            current_epoch = epoch
            states.clear()
            future_mid_history.clear()
            trade_history.clear()
            grid_ns = ((ts_ns + grid_step_ns - 1) // grid_step_ns) * grid_step_ns
        assert grid_ns is not None
        while grid_ns < ts_ns:
            emitted += emit_snapshot(
                grid_ns,
                epoch,
                states.get(futures_id),
                {key: value for key, value in states.items() if key in option_id_set},
                future_mid_history,
                trade_history,
                snapshots,
            )
            grid_ns += grid_step_ns
        try:
            state = book_state(row)
        except GateFailure:
            states.pop(row.instrument_id, None)
            continue
        states[row.instrument_id] = state
        if row.instrument_id == futures_id:
            if not future_mid_history or future_mid_history[-1][1] != state.mid:
                future_mid_history.append((ts_ns, state.mid))
            if row.cumulative_volume_increment is not None:
                increment = max(0, int(row.cumulative_volume_increment))
                trade_history.append((ts_ns, increment))
    if replay_rows != handle.rows:
        raise GateFailure(f"panel replay rows {replay_rows} disagree with catalog {handle.rows}")

    panel: list[dict[str, Any]] = []
    step_5 = 5 * 1_000_000_000
    for instrument in option_ids:
        series = snapshots.get(instrument, {})
        strike = parse_strike(instrument)
        is_call = 1.0 if instrument.endswith(":CE") else 0.0
        for stamp in sorted(series):
            current = series[stamp]
            epoch = int(current["connection_epoch"])
            lag = series.get(stamp - step_5)
            if lag is None or int(lag["connection_epoch"]) != epoch or lag["option_mid"] <= 0:
                continue
            outcomes: dict[str, float] = {}
            for horizon in HORIZONS_SECONDS:
                future = series.get(stamp + horizon * 1_000_000_000)
                if future is None or int(future["connection_epoch"]) != epoch:
                    break
                half_spread = max(current["option_spread"] / 2.0, 0.025)
                signed = (future["option_mid"] - current["option_mid"]) / half_spread
                outcomes[f"markout_{horizon}s"] = signed
                outcomes[f"adverse_proxy_{horizon}s"] = abs(signed)
            if len(outcomes) != 2 * len(HORIZONS_SECONDS):
                continue
            eligibility = {
                f"eligible_buffer_{seconds}s": _eligible_for_window(
                    stamp, epoch, clean_windows_by_buffer[seconds]
                )
                for seconds in BUFFER_SECONDS
            }
            if not any(eligibility.values()):
                continue
            seconds_of_day = (stamp // 1_000_000_000) % 86_400
            angle = 2.0 * math.pi * seconds_of_day / 86_400.0
            output_row = {
                "timestamp_ns": stamp,
                "instrument_id": instrument,
                "connection_epoch": epoch,
                **eligibility,
                "option_log_mid": math.log(current["option_mid"]),
                "option_relative_spread": current["option_spread"] / current["option_mid"],
                "option_microprice_dislocation": (
                    current["option_microprice"] - current["option_mid"]
                )
                / current["option_spread"],
                "option_depth_imbalance": current["option_imbalance"],
                "option_return_5s": math.log(current["option_mid"] / lag["option_mid"]),
                "option_is_call": is_call,
                "option_strike_scaled": strike / 25_000.0,
                "time_sin": math.sin(angle),
                "time_cos": math.cos(angle),
                "futures_log_mid": math.log(current["futures_mid"]),
                "futures_relative_spread": current["futures_spread"] / current["futures_mid"],
                "futures_microprice_dislocation": (
                    current["futures_microprice"] - current["futures_mid"]
                )
                / current["futures_spread"],
                "futures_depth_imbalance": current["futures_imbalance"],
                "futures_log_trade_intensity_10s": math.log1p(current["futures_trade_intensity"]),
                "futures_realized_volatility_30s": current["futures_rv"],
                **outcomes,
            }
            ignored = {"instrument_id"}
            if all(
                not isinstance(value, float) or math.isfinite(value)
                for key, value in output_row.items()
                if key not in ignored
            ):
                panel.append(output_row)
    panel.sort(key=lambda item: (item["timestamp_ns"], item["instrument_id"]))
    counts_by_buffer = {
        str(seconds): sum(bool(row[f"eligible_buffer_{seconds}s"]) for row in panel)
        for seconds in BUFFER_SECONDS
    }
    counts_by_epoch_and_buffer = {
        str(epoch): {
            str(seconds): sum(
                int(row["connection_epoch"] == epoch)
                * int(bool(row[f"eligible_buffer_{seconds}s"]))
                for row in panel
            )
            for seconds in BUFFER_SECONDS
        }
        for epoch in sorted({int(row["connection_epoch"]) for row in panel})
    }
    if counts_by_buffer[str(PRIMARY_BUFFER_SECONDS)] < MIN_PANEL_ROWS:
        raise GateFailure("primary clean panel has insufficient rows")
    diagnostics = {
        "replay_rows": replay_rows,
        "grid_seconds": GRID_SECONDS,
        "raw_snapshots": emitted,
        "panel_rows_superset": len(panel),
        "panel_rows_by_buffer": counts_by_buffer,
        "panel_rows_by_epoch_and_buffer": counts_by_epoch_and_buffer,
        "option_instruments": len({item["instrument_id"] for item in panel}),
    }
    return panel, diagnostics


def fit_standardized_ols(
    x_train: np.ndarray, y_train: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x_train - mean) / scale
    design = np.column_stack([np.ones(z.shape[0]), z])
    beta, _, rank, _ = np.linalg.lstsq(design, y_train, rcond=None)
    if rank != design.shape[1]:
        raise GateFailure("estimator design is rank deficient")
    return beta, mean, scale


def predict(beta: np.ndarray, mean: np.ndarray, scale: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(x.shape[0]), (x - mean) / scale]) @ beta


def r2(y: np.ndarray, prediction: np.ndarray) -> float:
    denominator = float(np.sum((y - y.mean()) ** 2))
    return (
        float(1.0 - np.sum((y - prediction) ** 2) / denominator)
        if denominator > 0
        else float("nan")
    )


def hac_standard_errors(
    design: np.ndarray, residuals: np.ndarray, timestamps: np.ndarray, lags: int = 12
) -> np.ndarray:
    unique, inverse = np.unique(timestamps, return_inverse=True)
    scores = np.zeros((unique.size, design.shape[1]), dtype=float)
    np.add.at(scores, inverse, design * residuals[:, None])
    meat = scores.T @ scores
    for lag in range(1, min(lags, unique.size - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)
    bread = np.linalg.pinv(design.T @ design)
    covariance = bread @ meat @ bread
    return np.sqrt(np.maximum(np.diag(covariance), 0.0))


def bootstrap_metric_deltas(
    y: np.ndarray,
    baseline: np.ndarray,
    augmented: np.ndarray,
    timestamps: np.ndarray,
    *,
    seed: int,
) -> dict[str, list[float]]:
    unique = np.unique(timestamps)
    block_width = max(1, 60 // GRID_SECONDS)
    blocks = [unique[index : index + block_width] for index in range(0, unique.size, block_width)]
    indices = [np.flatnonzero(np.isin(timestamps, block)) for block in blocks if block.size]
    rng = np.random.default_rng(seed)
    delta_r2: list[float] = []
    delta_mae: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        chosen = rng.integers(0, len(indices), size=len(indices))
        sample = np.concatenate([indices[item] for item in chosen])
        yy = y[sample]
        base = baseline[sample]
        aug = augmented[sample]
        delta_r2.append(r2(yy, aug) - r2(yy, base))
        delta_mae.append(float(np.mean(np.abs(yy - base)) - np.mean(np.abs(yy - aug))))
    return {
        "delta_oos_r2_ci95": [
            float(np.quantile(delta_r2, 0.025)),
            float(np.quantile(delta_r2, 0.975)),
        ],
        "mae_improvement_ci95": [
            float(np.quantile(delta_mae, 0.025)),
            float(np.quantile(delta_mae, 0.975)),
        ],
    }


def run_models(
    panel: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], np.ndarray]:
    timestamps = np.asarray([item["timestamp_ns"] for item in panel], dtype=np.int64)
    unique_times = np.unique(timestamps)
    boundary = unique_times[int(0.70 * unique_times.size)]
    embargo_end = boundary + EMBARGO_SECONDS * 1_000_000_000
    train = np.flatnonzero(timestamps < boundary)
    embargoed = np.flatnonzero((timestamps >= boundary) & (timestamps <= embargo_end))
    test = np.flatnonzero(timestamps > embargo_end)
    if (
        train.size < MIN_TRAIN_ROWS
        or test.size < MIN_TEST_ROWS
        or np.unique(timestamps[train]).size < MIN_UNIQUE_TRAIN_TIMES
        or np.unique(timestamps[test]).size < MIN_UNIQUE_TEST_TIMES
    ):
        raise GateFailure("chronological embargoed split has insufficient clean train/test support")
    control = np.asarray([[float(item[name]) for name in CONTROL_NAMES] for item in panel])
    augmented = np.asarray(
        [[float(item[name]) for name in CONTROL_NAMES + FUTURES_NAMES] for item in panel]
    )
    target_names = tuple(
        name
        for horizon in HORIZONS_SECONDS
        for name in (f"markout_{horizon}s", f"adverse_proxy_{horizon}s")
    )
    results: list[dict[str, Any]] = []
    for target_number, target_name in enumerate(target_names):
        y = np.asarray([float(item[target_name]) for item in panel])
        beta_b, mean_b, scale_b = fit_standardized_ols(control[train], y[train])
        beta_a, mean_a, scale_a = fit_standardized_ols(augmented[train], y[train])
        pred_b = predict(beta_b, mean_b, scale_b, control[test])
        pred_a = predict(beta_a, mean_a, scale_a, augmented[test])
        design_train = np.column_stack([np.ones(train.size), (augmented[train] - mean_a) / scale_a])
        residual_train = y[train] - design_train @ beta_a
        standard_errors = hac_standard_errors(design_train, residual_train, timestamps[train])
        coefficients = []
        for offset, name in enumerate(CONTROL_NAMES + FUTURES_NAMES, start=1):
            coefficients.append(
                {
                    "feature": name,
                    "standardized_coefficient": float(beta_a[offset]),
                    "hac_se": float(standard_errors[offset]),
                    "ci95": [
                        float(beta_a[offset] - 1.96 * standard_errors[offset]),
                        float(beta_a[offset] + 1.96 * standard_errors[offset]),
                    ],
                }
            )
        base_r2 = r2(y[test], pred_b)
        aug_r2 = r2(y[test], pred_a)
        base_mae = float(np.mean(np.abs(y[test] - pred_b)))
        aug_mae = float(np.mean(np.abs(y[test] - pred_a)))
        uncertainty = bootstrap_metric_deltas(
            y[test], pred_b, pred_a, timestamps[test], seed=20260826 + target_number
        )
        results.append(
            {
                "target": target_name,
                "baseline_oos_r2": base_r2,
                "augmented_oos_r2": aug_r2,
                "delta_oos_r2": aug_r2 - base_r2,
                "baseline_oos_mae": base_mae,
                "augmented_oos_mae": aug_mae,
                "mae_improvement": base_mae - aug_mae,
                **uncertainty,
                "augmented_standardized_coefficients": coefficients,
            }
        )
    split = {
        "method": "single-session chronological 70/30 split",
        "boundary_ts_ns": int(boundary),
        "embargo_seconds": EMBARGO_SECONDS,
        "embargo_end_ts_ns": int(embargo_end),
        "train_rows": int(train.size),
        "embargoed_rows": int(embargoed.size),
        "test_rows": int(test.size),
        "train_unique_grid_times": int(np.unique(timestamps[train]).size),
        "test_unique_grid_times": int(np.unique(timestamps[test]).size),
    }
    roles = np.full(len(panel), "embargoed", dtype=object)
    roles[train] = "train"
    roles[test] = "test"
    return results, split, roles


def write_panel(path: Path, panel: list[dict[str, Any]], roles: np.ndarray) -> str:
    fields = list(panel[0]) + ["sample_role"]
    digest = hashlib.sha256()
    with gzip.open(path, "wt", encoding="utf-8", newline="") as raw:
        writer = csv.DictWriter(raw, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row, role in zip(panel, roles, strict=True):
            output = {**row, "sample_role": str(role)}
            writer.writerow(output)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_memo(metadata: dict[str, Any], results: Sequence[dict[str, Any]]) -> str:
    audit = metadata["quality_audit"]
    primary = audit["buffers"][str(PRIMARY_BUFFER_SECONDS)]
    lines = [
        "# Shaurya post-close futures-to-options research memo",
        "",
        "Status: **exploratory, single-session evidence only**. This is not a claim of true MBO, queue position, fill prediction, causal identification, or tradable alpha.",
        "",
        "## Data and quality",
        "",
        f"- Dataset: `{metadata['dataset_id']}`; immutable tape SHA-256 `{metadata['tape_sha256']}`.",
        f"- Coverage: {metadata['coverage_start']} to {metadata['coverage_end']} ({metadata['coverage_seconds'] / 3600:.2f} hours).",
        f"- Published rows: {metadata['catalog_rows']:,}; primary 30-second-buffer panel rows: {metadata['panel']['panel_rows_by_buffer']['30']:,} across {metadata['panel']['option_instruments']} options.",
        "- Hard gates passed: COMPLETED/no invalidation; tape and index hashes; index binding/counts/coverage; manifest completion and artifact hashes; all 121 requested instruments observed; two full replay row-count checks.",
        f"- The capture was stable for most of the session, but record evidence confirms {len(audit['confirmed_epoch_transitions'])} localized heartbeat-driven reconnect transitions. Their record-free gaps were "
        + ", ".join(f"{item['gap_seconds']:.2f}s" for item in audit["confirmed_epoch_transitions"])
        + ".",
        f"- Stored receive sequence is contiguous. Source sequence is unavailable on {audit['quality_counts'].get('source_sequence_unavailable', 0):,} rows, so upstream packet-loss completeness cannot be established.",
        f"- The replay-derived audit (not a native collector audit) found {audit['book_invalid_counts'].get('partial_book', 0)} partial-book rows, {audit['book_invalid_counts'].get('crossed_book', 0)} crossed books, and {audit['quality_counts'].get('exchange_time_regression', 0)} exchange-time regressions. A 30-second buffer plus 30-second feature/outcome support margin leaves {primary['total_clean_seconds'] / 3600:.2f} hours before panel as-of availability filters.",
        "- Epoch 3 lasted only milliseconds and contributes no clean panel rows; long clean windows remain in epochs 1, 2, and 4. Audit artifacts label clean, excluded, and uncertain record-free windows explicitly.",
        "",
        "## Estimator",
        "",
        "Option-state baseline: log mid, relative spread, microprice dislocation, five-level depth imbalance, lagged 5-second option return, call/put, scaled strike, and time-of-day. The augmented model adds futures log mid, relative spread, microprice dislocation, five-level depth imbalance, a 10-second nonnegative cumulative-volume-increment intensity proxy, and 30-second realized volatility.",
        "",
        "Both are standardized OLS fits on the first 70% of clean grid times and evaluated on the final 30%, separated by a 30-second embargo. Incremental effect size is held-out R-squared and MAE change; 95% uncertainty uses a 60-second moving-block bootstrap (400 replicates). Coefficient intervals are Newey-West/HAC-style intervals over grid-time score aggregates (12 five-second lags).",
        "",
        "Targets are explicit proxies: signed future option-mid displacement in current half-spread units (`markout`) and its absolute magnitude (`adverse_proxy`). They are not realized fills or order-level adverse selection.",
        "",
        "## Held-out incremental results",
        "",
    ]
    for result in results:
        lines.append(
            f"- **{result['target']}**: baseline OOS R2 {result['baseline_oos_r2']:.4f}; augmented {result['augmented_oos_r2']:.4f}; delta {result['delta_oos_r2']:.4f} (95% block-bootstrap CI {result['delta_oos_r2_ci95'][0]:.4f} to {result['delta_oos_r2_ci95'][1]:.4f}). MAE improvement {result['mae_improvement']:.4f} (CI {result['mae_improvement_ci95'][0]:.4f} to {result['mae_improvement_ci95'][1]:.4f})."
        )
    lines.extend(["", "## Buffer robustness", ""])
    for buffer_seconds in BUFFER_SECONDS:
        run = metadata["robustness"][str(buffer_seconds)]
        deltas = ", ".join(
            f"{item['target']} dR2={item['delta_oos_r2']:.4f}" for item in run["results"]
        )
        lines.append(f"- {buffer_seconds}s buffer: {run['panel_rows']:,} rows; {deltas}.")
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "One afternoon and one chronological split cannot establish cross-session stability, causal structure, execution feasibility, or economic value after costs/latency. Dhan standard-feed rows are aggregate snapshots with inferred volume increments—not exchange MBO—and contain no order IDs, queue priority, add/modify/cancel events, or fill observations. Source sequence is unavailable, so contiguous stored receive sequence cannot prove source-packet completeness. Results should be treated as screening evidence requiring preregistered multi-session confirmation.",
            "",
        ]
    )
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> int:
    output = args.output_root / f"post-close-alpha-quality-aware-{args.dataset_id}"
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    status_path = output / "status.jsonl"
    append_status(
        status_path,
        "armed",
        runner_version=RUNNER_VERSION,
        dataset_id=args.dataset_id,
        trigger=(
            "exact COMPLETED catalog handle; immutable tape/index/manifest/coverage verification; "
            "two replay passes; proceed once only if buffered clean support is material"
        ),
        no_rerun=True,
    )
    marker = output / "ONE_SHOT_CONSUMED"
    deadline = time.monotonic() + args.max_wait_seconds
    access = DataAccess(DataCatalog(args.catalog))
    last_state: str | None = None
    try:
        while True:
            handle = access.handle(args.dataset_id)
            state = str(handle.status)
            if state != last_state:
                append_status(status_path, "catalog_state", status=state)
                last_state = state
            if handle.status is DatasetStatus.INVALIDATED:
                raise GateFailure("dataset was invalidated: " + str(handle.invalidation_reason))
            if handle.status is DatasetStatus.COMPLETED:
                break
            if handle.status is not DatasetStatus.ACTIVE:
                raise GateFailure(f"unexpected dataset lifecycle state: {handle.status}")
            if handle.producer_pid is None:
                raise GateFailure("active handle has no producer PID")
            try:
                os.kill(handle.producer_pid, 0)
            except OSError as exc:
                raise GateFailure("producer ended without terminal catalog publication") from exc
            if time.monotonic() >= deadline:
                raise GateFailure("one-shot completion wait expired")
            time.sleep(args.poll_seconds)

        atomic_text(marker, datetime.now().astimezone().isoformat() + "\n")
        append_status(
            status_path, "terminal_handle_observed", completed_at=handle.completed_at.isoformat()
        )
        index, coverage = completed_dataset_gate(handle)
        append_status(
            status_path,
            "immutable_gates_passed",
            tape_sha256=handle.tape_sha256,
            rows=handle.rows,
        )
        quality_audit, clean_windows = derive_replay_audit(access, handle, coverage)
        atomic_text(
            output / "quality_audit.json",
            json.dumps(quality_audit, indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        append_status(
            status_path,
            "replay_quality_audit_passed",
            epochs=len(quality_audit["epochs"]),
            transitions=len(quality_audit["confirmed_epoch_transitions"]),
            primary_clean_seconds=quality_audit["buffers"][str(PRIMARY_BUFFER_SECONDS)][
                "total_clean_seconds"
            ],
        )
        panel_superset, panel_diagnostics = build_panel(access, handle, clean_windows)
        robustness: dict[str, Any] = {}
        primary_panel: list[dict[str, Any]] | None = None
        primary_roles: np.ndarray | None = None
        for buffer_seconds in BUFFER_SECONDS:
            panel = [
                row for row in panel_superset if bool(row[f"eligible_buffer_{buffer_seconds}s"])
            ]
            results, split, roles = run_models(panel)
            robustness[str(buffer_seconds)] = {
                "buffer_seconds": buffer_seconds,
                "panel_rows": len(panel),
                "split": split,
                "results": results,
            }
            if buffer_seconds == PRIMARY_BUFFER_SECONDS:
                primary_panel = panel
                primary_roles = roles
        if primary_panel is None or primary_roles is None:
            raise GateFailure("primary robustness run was not produced")
        results = robustness[str(PRIMARY_BUFFER_SECONDS)]["results"]
        split = robustness[str(PRIMARY_BUFFER_SECONDS)]["split"]
        panel_path = output / "derived_feature_panel.csv.gz"
        panel_hash = write_panel(panel_path, primary_panel, primary_roles)
        metadata = {
            "runner_version": RUNNER_VERSION,
            "research_status": "exploratory_single_session",
            "dataset_id": handle.dataset_id,
            "catalog_path": str(Path(args.catalog).resolve()),
            "tape_sha256": handle.tape_sha256,
            "index_sha256": handle.index_sha256,
            "catalog_rows": handle.rows,
            "catalog_bytes": handle.bytes,
            "coverage_start": handle.coverage_start.isoformat(),
            "coverage_end": handle.coverage_end.isoformat(),
            "coverage_seconds": (handle.coverage_end - handle.coverage_start).total_seconds(),
            "index": index,
            "chain_coverage": coverage,
            "quality_audit": quality_audit,
            "panel": panel_diagnostics,
            "panel_path": str(panel_path.resolve()),
            "panel_sha256": panel_hash,
            "features": {
                "option_state_controls": CONTROL_NAMES,
                "futures_increment": FUTURES_NAMES,
            },
            "targets": [item["target"] for item in results],
            "split": split,
            "estimator": {
                "model": "standardized ordinary least squares",
                "coefficient_uncertainty": "HAC over grid-time score aggregates, 12 lags",
                "incremental_metric_uncertainty": "60-second moving-block bootstrap, 400 replicates",
            },
            "results": results,
            "robustness": robustness,
            "claim_limits": [
                "not true MBO",
                "not queue or fill prediction",
                "not causal",
                "not tradable alpha",
                "single session only",
            ],
        }
        atomic_text(
            output / "research_results.json",
            json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        atomic_text(output / "FINAL_MEMO.md", render_memo(metadata, results))
        append_status(
            status_path,
            "completed",
            panel_rows=len(primary_panel),
            panel_sha256=panel_hash,
        )
        atomic_text(output / "COMPLETED", datetime.now().astimezone().isoformat() + "\n")
        return 0
    except BaseException as exc:
        append_status(status_path, "failed_closed", error_type=type(exc).__name__, reason=str(exc))
        atomic_text(output / "FAILED_CLOSED", f"{type(exc).__name__}: {exc}\n")
        raise


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--dataset-id", required=True)
    value.add_argument("--catalog", required=True, type=Path)
    value.add_argument("--output-root", required=True, type=Path)
    value.add_argument("--poll-seconds", type=float, default=15.0)
    value.add_argument("--max-wait-seconds", type=float, default=7200.0)
    return value


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.poll_seconds <= 0 or args.max_wait_seconds <= 0:
        raise ValueError("poll and max-wait durations must be positive")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
