"""Live complete-prefix execution for D38, D39 and D40.

The worker never reads a byte beyond the last newline visible when a cycle starts.  That prefix
is immutable by append-only construction and is identified by byte count and SHA-256.  Successive
prefixes overlap, so their results are explicitly exploratory monitoring views rather than
independent replications.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    BookState,
    build_states,
    parse_receive_ts_ns,
)
from shaurya.signals.effective_touch import (
    EFFECTIVE_TOUCH_WINDOWS_SECONDS,
    PRIMARY_EFFECTIVE_TOUCH_WINDOW,
    EffectiveTouchSeries,
    build_trade_prints,
    effective_touch_coverage,
    effective_touch_metadata,
    print_location_diagnostics,
)
from shaurya.signals.ofi_horserace import (
    HorseRaceTapeInput,
    build_horserace_observations,
)

LIVE_SPECIFICATION: Final = "docs/D38-D39-D40-LIVE-AMENDMENT-2026-08-21.md"
D40_HORIZONS_SECONDS: Final = (10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)
LIVE_RESPONSE_HORIZONS_SECONDS: Final = (
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    30.0,
    45.0,
    60.0,
    90.0,
    120.0,
)
LIVE_LEVEL_COUNTS: Final = (1, 5, 10, 20)


@dataclass(frozen=True, slots=True)
class CompletePrefixSnapshot:
    """One newline-complete immutable prefix and its constructed research objects."""

    dataset_id: str
    tape_path: Path
    prefix_bytes: int
    prefix_sha256: str
    snapshot_at: str
    last_receive_ts: str
    channel_rows: Mapping[str, int]
    full_rows: tuple[dict[str, Any], ...]
    tape: HorseRaceTapeInput

    def provenance(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "tape_path": str(self.tape_path),
            "prefix_bytes": self.prefix_bytes,
            "prefix_sha256": self.prefix_sha256,
            "snapshot_at": self.snapshot_at,
            "last_receive_ts": self.last_receive_ts,
            "channel_rows": dict(self.channel_rows),
            "observations": len(self.tape.observations),
            "sample_role": "growing_prefix_exploration",
            "successive_prefixes_independent": False,
        }


def complete_prefix_offset(path: Path) -> int:
    """Return the byte immediately after the final complete JSONL newline."""

    size = path.stat().st_size
    if size == 0:
        raise ValueError("growing tape is empty")
    chunk_size = 1 << 20
    cursor = size
    with path.open("rb") as handle:
        while cursor > 0:
            start = max(0, cursor - chunk_size)
            handle.seek(start)
            chunk = handle.read(cursor - start)
            newline = chunk.rfind(b"\n")
            if newline >= 0:
                return start + newline + 1
            cursor = start
    raise ValueError("growing tape has no complete JSONL line")


def _append_state(states: list[BookState], state: BookState) -> None:
    if states and (
        states[-1].receive_ts_ns,
        states[-1].connection_epoch,
    ) == (state.receive_ts_ns, state.connection_epoch):
        states[-1] = state
        return
    if states and state.receive_ts_ns < states[-1].receive_ts_ns:
        raise ValueError("book-state capture time moved backwards inside prefix")
    states.append(state)


def snapshot_growing_tape(
    path: Path,
    *,
    dataset_id: str,
    prefix_bytes: int | None = None,
) -> CompletePrefixSnapshot:
    """Construct D38/D39/D40 inputs from one identified complete-line prefix."""

    resolved = path.resolve()
    limit = prefix_bytes if prefix_bytes is not None else complete_prefix_offset(resolved)
    if limit <= 0 or limit > resolved.stat().st_size:
        raise ValueError("prefix byte boundary is outside the tape")
    digest = hashlib.sha256()
    depth200: list[BookState] = []
    depth20: list[BookState] = []
    full_rows: list[dict[str, Any]] = []
    channel_rows = {"full": 0, DEPTH20: 0, DEPTH200: 0}
    run_id: str | None = None
    instrument_id: str | None = None
    last_receive_ts: str | None = None
    last_stamp_ns: int | None = None
    consumed = 0
    with resolved.open("rb") as handle:
        while consumed < limit:
            encoded = handle.readline()
            if not encoded or consumed + len(encoded) > limit or not encoded.endswith(b"\n"):
                raise ValueError("prefix boundary does not end on a complete JSONL row")
            consumed += len(encoded)
            digest.update(encoded)
            loaded: Any = json.loads(encoded)
            if not isinstance(loaded, dict):
                raise ValueError("prefix JSONL row is not an object")
            payload = dict(loaded)
            observed_run = str(payload.get("run_id") or "")
            observed_instrument = str(payload.get("instrument_id") or "")
            if not observed_run or not observed_instrument:
                raise ValueError("prefix row is missing run or instrument identity")
            run_id = run_id or observed_run
            instrument_id = instrument_id or observed_instrument
            if observed_run != run_id or observed_instrument != instrument_id:
                raise ValueError("prefix mixes run or instrument identities")
            raw_ts = payload.get("receive_ts")
            if not isinstance(raw_ts, str):
                raise ValueError("prefix row is missing receive_ts")
            stamp_ns = parse_receive_ts_ns(raw_ts)
            if last_stamp_ns is not None and stamp_ns < last_stamp_ns:
                raise ValueError("prefix receive time moved backwards")
            last_stamp_ns = stamp_ns
            last_receive_ts = raw_ts
            event = payload.get("event_type")
            if event in channel_rows:
                channel_rows[str(event)] += 1
            if event == DEPTH200:
                built = build_states([payload], DEPTH200)
                if built:
                    _append_state(depth200, built[0])
            elif event == DEPTH20:
                built = build_states([payload], DEPTH20)
                if built:
                    _append_state(depth20, built[0])
            elif event == "full":
                full_rows.append(payload)
    if consumed != limit or run_id is None or instrument_id is None or last_receive_ts is None:
        raise ValueError("prefix did not yield a complete identified tape")
    if not depth200 or not depth20 or not full_rows:
        raise ValueError("prefix needs full, depth20 and depth200 support")
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=full_rows,
        tape_index=0,
        run_id=run_id,
        level_counts=LIVE_LEVEL_COUNTS,
        response_horizons=LIVE_RESPONSE_HORIZONS_SECONDS,
    )
    observed_seconds = (
        (depth200[-1].receive_ts_ns - depth200[0].receive_ts_ns) / 1_000_000_000
        if len(depth200) > 1
        else 0.0
    )
    tape = HorseRaceTapeInput(
        tape_index=0,
        run_id=run_id,
        instrument_id=instrument_id,
        tape_sha256=digest.hexdigest(),
        observations=tuple(observations),
        depth200_publications=len(depth200),
        depth20_publications=len(depth20),
        observed_seconds=observed_seconds,
        failures=failures,
    )
    return CompletePrefixSnapshot(
        dataset_id=dataset_id,
        tape_path=resolved,
        prefix_bytes=limit,
        prefix_sha256=digest.hexdigest(),
        snapshot_at=datetime.now(UTC).isoformat(),
        last_receive_ts=last_receive_ts,
        channel_rows=channel_rows,
        full_rows=tuple(full_rows),
        tape=tape,
    )


def build_live_d38(snapshot: CompletePrefixSnapshot, *, anchor_stride: int = 1) -> dict[str, Any]:
    if anchor_stride < 1:
        raise ValueError("anchor_stride must be positive")
    series = build_trade_prints(snapshot.full_rows)
    anchors = [item.receive_ts_ns for item in series.prints][::anchor_stride]
    return {
        "status": "complete",
        "specification_id": "D38 / TOUCH-METRICS-2026-08-20",
        "live_amendment": LIVE_SPECIFICATION,
        "updated_at": datetime.now(UTC).isoformat(),
        "source": snapshot.provenance(),
        "touch_01_print_locations": print_location_diagnostics(series),
        "touch_02_effective_touch": {
            "metadata": effective_touch_metadata(),
            "anchor_stride_prints": anchor_stride,
            "anchors": len(anchors),
            "primary_window_seconds": PRIMARY_EFFECTIVE_TOUCH_WINDOW,
            "by_window": [
                effective_touch_coverage(
                    EffectiveTouchSeries(series.prints, window_seconds=window), anchors
                )
                for window in EFFECTIVE_TOUCH_WINDOWS_SECONDS
            ],
        },
        "confirmatory_eligible": False,
        "order_entry_enabled": False,
    }


def _estimated_competitors(cell: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = cell.get("competitors")
    if not isinstance(raw, list):
        return {}
    return {
        str(item["competitor"]): item
        for item in raw
        if isinstance(item, dict) and item.get("status") == "estimated"
    }


def summarize_d39_cell(cell: Mapping[str, Any]) -> dict[str, Any]:
    estimated = _estimated_competitors(cell)

    def r2(name: str) -> float | None:
        value = estimated.get(name, {}).get("absolute_oos_r2")
        return float(value) if value is not None else None

    c12_increment = estimated.get("C12", {}).get("incremental_oos_r2_over_c2")
    raw_question = cell.get("ofi_question")
    question: Mapping[str, Any] = raw_question if isinstance(raw_question, dict) else {}
    return {
        "reference_price": cell.get("reference_price"),
        "levels": cell.get("levels"),
        "h1_seconds": cell.get("h1_seconds"),
        "h2_seconds": cell.get("h2_seconds"),
        "status": cell.get("status"),
        "train_n": cell.get("train_n"),
        "test_n": cell.get("test_n"),
        "common_test_row_hash": cell.get("common_test_row_hash"),
        "c2_lagged_return_absolute_oos_r2": r2("C2"),
        "c8_ccz_ofi_absolute_oos_r2": r2("C8"),
        "c12_lagged_plus_ofi_absolute_oos_r2": r2("C12"),
        "c12_incremental_oos_r2_over_c2": (
            float(c12_increment) if c12_increment is not None else None
        ),
        "verdict": question.get("verdict"),
    }


def summarize_d40_cell(cell: Mapping[str, Any]) -> dict[str, Any]:
    estimated = _estimated_competitors(cell)
    c8 = estimated.get("C8", {})
    value = c8.get("absolute_oos_r2")
    return {
        "horizon_seconds": float(cell.get("h2_seconds") or 0.0),
        "status": cell.get("status"),
        "absolute_oos_r2": float(value) if value is not None else None,
        "absolute_oos_r2_percent": 100.0 * float(value) if value is not None else None,
        "train_n": cell.get("train_n"),
        "test_n": cell.get("test_n"),
        "common_test_row_hash": cell.get("common_test_row_hash"),
        "selected_ridge_alpha": c8.get("selected_alpha"),
    }


def d40_curve_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: float(row["horizon_seconds"]))
    complete = tuple(
        float(row["horizon_seconds"]) for row in ordered
    ) == D40_HORIZONS_SECONDS and all(row.get("absolute_oos_r2") is not None for row in ordered)
    if not complete:
        return {
            "complete": False,
            "strictly_increasing": None,
            "nondecreasing": None,
            "peak_horizon_seconds": None,
            "peak_absolute_oos_r2": None,
            "first_decline_horizon_seconds": None,
        }
    values = [float(row["absolute_oos_r2"]) for row in ordered]
    peak_index = max(range(len(values)), key=values.__getitem__)
    first_decline = next(
        (
            float(ordered[index]["horizon_seconds"])
            for index in range(1, len(values))
            if values[index] < values[index - 1]
        ),
        None,
    )
    return {
        "complete": True,
        "strictly_increasing": all(
            right > left for left, right in zip(values, values[1:], strict=False)
        ),
        "nondecreasing": all(
            right >= left for left, right in zip(values, values[1:], strict=False)
        ),
        "peak_horizon_seconds": float(ordered[peak_index]["horizon_seconds"]),
        "peak_absolute_oos_r2": values[peak_index],
        "first_decline_horizon_seconds": first_decline,
    }


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial-{os.getpid()}")
    descriptor = os.open(partial, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


class LiveStudyStateWriter:
    """Atomic compact state plus append-only full-cell evidence."""

    def __init__(self, path: Path, artifact_dir: Path, *, run_id: str, dataset_id: str) -> None:
        self.path = path
        self.artifact_dir = artifact_dir
        self.artifact_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state: dict[str, Any] = {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "dataset_id": dataset_id,
            "live_amendment": LIVE_SPECIFICATION,
            "status": "starting",
            "current_stage": "initialising",
            "updated_at": datetime.now(UTC).isoformat(),
            "source": None,
            "d38": {"status": "pending"},
            "d39": {"status": "pending", "completed_cells": 0, "total_cells": 600, "cells": []},
            "d40": {"status": "pending", "completed_cells": 0, "total_cells": 7, "rows": []},
            "last_error": None,
            "confirmatory_eligible": False,
            "order_entry_enabled": False,
            "successive_prefixes_independent": False,
        }
        self._write()

    def _write(self) -> None:
        self.state["updated_at"] = datetime.now(UTC).isoformat()
        atomic_write_json(self.path, self.state)

    def begin_cycle(self, snapshot: CompletePrefixSnapshot, *, cycle: int) -> None:
        self.state.update(
            {
                "status": "running",
                "current_stage": "d38",
                "cycle": cycle,
                "source": snapshot.provenance(),
                "d38": {"status": "running"},
                "d39": {
                    "status": "pending",
                    "completed_cells": 0,
                    "total_cells": 600,
                    "cells": [],
                },
                "d40": {
                    "status": "pending",
                    "completed_cells": 0,
                    "total_cells": 7,
                    "rows": [],
                },
                "last_error": None,
            }
        )
        self._write()

    def publish_d38(self, report: Mapping[str, Any]) -> None:
        self.state["d38"] = dict(report)
        self.state["current_stage"] = "d40"
        self._write()

    def start_cells(self, study: str, *, total: int) -> Path:
        key = "rows" if study == "d40" else "cells"
        self.state[study] = {
            "status": "running",
            "completed_cells": 0,
            "total_cells": total,
            key: [],
        }
        self.state["current_stage"] = study
        path = self.artifact_dir / f"cycle-{self.state.get('cycle', 0)}-{study}-cells.jsonl"
        path.touch(mode=0o600, exist_ok=True)
        self._write()
        return path

    def publish_cell(
        self,
        study: str,
        *,
        cell: Mapping[str, Any],
        summary: Mapping[str, Any],
        completed: int,
        total: int,
        artifact_path: Path,
    ) -> None:
        descriptor = os.open(artifact_path, os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(cell, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        key = "rows" if study == "d40" else "cells"
        section = self.state[study]
        if not isinstance(section, dict):
            raise TypeError(f"{study} state is not an object")
        values = section[key]
        if not isinstance(values, list):
            raise TypeError(f"{study} compact rows are not a list")
        values.append(dict(summary))
        section.update(
            {
                "status": "running" if completed < total else "complete",
                "completed_cells": completed,
                "total_cells": total,
                "last_completed_cell": dict(summary),
                "artifact_path": str(artifact_path),
            }
        )
        if study == "d40":
            section["curve"] = d40_curve_summary(values)
        self._write()

    def complete_study(self, study: str, *, full_artifact_path: Path) -> None:
        section = self.state[study]
        if not isinstance(section, dict):
            raise TypeError(f"{study} state is not an object")
        section["status"] = "complete"
        section["full_artifact_path"] = str(full_artifact_path)
        if study == "d40":
            values = section.get("rows")
            if isinstance(values, list):
                section["curve"] = d40_curve_summary(values)
        self._write()

    def complete_cycle(self) -> None:
        self.state["status"] = "cycle_complete"
        self.state["current_stage"] = "waiting_for_new_prefix"
        self._write()

    def fail(self, exc: BaseException) -> None:
        self.state["status"] = "failed"
        self.state["last_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "at": datetime.now(UTC).isoformat(),
        }
        self._write()
