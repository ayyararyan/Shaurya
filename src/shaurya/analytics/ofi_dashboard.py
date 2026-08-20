"""ANL-06 dynamic order-flow-imbalance walk-forward dashboard.

This module is deliberately file driven and read-only.  It imports the frozen horse-race
implementation for observation construction, model feature selection, fitting, regularisation,
dependence estimates and collinearity diagnostics.  It contains no broker, credential, socket or
order-path import.

The important state transition is the test-block ratchet.  A timestamp interval is assigned to a
test block once, scored once, and then closed forever.  Older test observations may subsequently
age into an expanding training set, but an observation which has ever entered training is refused
from every later test set.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    BookState,
    build_states,
    parse_receive_ts_ns,
)
from shaurya.signals.deep_book_normal_activity import (
    SplitIndex,
    _r_squared,
    build_depth20_mid_series,
    estimate_mean,
)
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS, OFI_WINDOWS_SECONDS, _mid_return
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND
from shaurya.signals.ofi_horserace import (
    MODEL_ORDER,
    RETURN_HORIZONS_SECONDS,
    HorseRaceObservation,
    _collinearity,
    _fit_score,
    build_horserace_observations,
    evaluate_cells,
    evaluate_same_window,
    model_features,
)

SCAN_ID = "X-OFI-DASHBOARD-2026-08-20"
DESIGN_DOCUMENT = "docs/OFI-DASHBOARD-SPEC-2026-08-20.md"
CELL_COUNT = len(MODEL_ORDER) * len(OFI_WINDOWS_SECONDS) * len(RETURN_HORIZONS_SECONDS)
DEFAULT_TEST_BLOCK_SECONDS = 120.0
DEFAULT_REFIT_CADENCE_SECONDS = 60.0
DEFAULT_MINIMUM_TRAINING_ANCHORS = 600
DEFAULT_MINIMUM_TEST_ANCHORS = 20
DEFAULT_BOOTSTRAP_REPLICATES = 399
GREEN_THRESHOLD = 0.05
CHANCE_EXPECTATION = CELL_COUNT * GREEN_THRESHOLD
COLLINEARITY_CORRELATION_THRESHOLD = 0.995
COLLINEARITY_VIF_THRESHOLD = 100.0

CellStatus = Literal["WARMING", "INSUFFICIENT", "ESTIMATED", "BLOCKED_UNIDENTIFIED"]


def _json_safe(value: Any) -> Any:
    """Convert numpy/scalar non-finites into deterministic JSON values."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _utc_iso_from_ns(stamp_ns: int | None) -> str | None:
    if stamp_ns is None:
        return None
    return datetime.fromtimestamp(stamp_ns / NANOSECONDS_PER_SECOND, tz=UTC).isoformat()


def enforce_response_geometry(
    observations: Sequence[HorseRaceObservation],
    depth20_states: Sequence[BookState],
) -> tuple[list[HorseRaceObservation], int]:
    """Apply the frozen future/past endpoints inside each connection epoch.

    The numerical midpoint-return operation is the canonical helper from
    :mod:`shaurya.signals.deep_book_ofi`; this function only supplies the dashboard's frozen
    endpoints.  In particular, the past mirror ends at ``t-Z`` rather than at ``t``.
    """

    states_by_epoch: dict[int, list[BookState]] = {}
    for state in depth20_states:
        states_by_epoch.setdefault(state.connection_epoch, []).append(state)
    series_by_epoch = {
        epoch: build_depth20_mid_series(states) for epoch, states in states_by_epoch.items()
    }
    gap_ns = int(CAUSAL_GAP_SECONDS * NANOSECONDS_PER_SECOND)
    rebuilt: list[HorseRaceObservation] = []
    excluded = 0
    for observation in observations:
        series = series_by_epoch.get(observation.connection_epoch)
        if series is None:
            excluded += 1
            continue
        future: dict[float, float] = {}
        past: dict[float, float] = {}
        future_start = observation.receive_ts_ns + gap_ns
        past_end = observation.receive_ts_ns - gap_ns
        for horizon in RETURN_HORIZONS_SECONDS:
            width = int(float(horizon) * NANOSECONDS_PER_SECOND)
            forward = _mid_return(series, future_start, future_start + width)
            mirror = _mid_return(series, past_end - width, past_end)
            if forward is not None:
                future[float(horizon)] = forward
            if mirror is not None:
                past[float(horizon)] = mirror
        if not future:
            excluded += 1
            continue
        rebuilt.append(replace(observation, future_ticks=future, past_ticks=past))
    return rebuilt, excluded


def cell_key(model: str, h1: float, h2: float) -> str:
    return f"{model}|{h1:g}|{h2:g}"


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Frozen defaults with test-only configurability for hand-worked probes."""

    test_block_seconds: float = DEFAULT_TEST_BLOCK_SECONDS
    refit_cadence_seconds: float = DEFAULT_REFIT_CADENCE_SECONDS
    minimum_training_anchors: int = DEFAULT_MINIMUM_TRAINING_ANCHORS
    minimum_test_anchors: int = DEFAULT_MINIMUM_TEST_ANCHORS
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES
    seed: int = 20260820

    def __post_init__(self) -> None:
        if self.test_block_seconds <= 0 or self.refit_cadence_seconds <= 0:
            raise ValueError("test block and refit cadence must be positive")
        if self.minimum_training_anchors < 2 or self.minimum_test_anchors < 2:
            raise ValueError("training and test support floors must be at least two")
        if self.bootstrap_replicates < 2:
            raise ValueError("bootstrap_replicates must be at least two")


@dataclass(frozen=True, slots=True)
class BlockPartition:
    """One immutable expanding-train / embargo / disjoint-test assignment."""

    block_index: int
    h2_seconds: float
    embargo_seconds: float
    test_start_ts_ns: int
    test_end_ts_ns: int
    train: tuple[int, ...]
    embargoed: tuple[int, ...]
    test: tuple[int, ...]

    def as_split_index(self) -> SplitIndex:
        return SplitIndex(
            train=self.train,
            embargoed=self.embargoed,
            test=self.test,
            embargo_seconds=self.embargo_seconds,
            boundaries=(
                (
                    f"dashboard-block-{self.block_index}",
                    self.test_start_ts_ns - int(self.embargo_seconds * NANOSECONDS_PER_SECOND),
                    self.test_start_ts_ns,
                ),
            ),
        )


class WalkForwardRatchet:
    """Assign disjoint test intervals and enforce the one-way training ratchet."""

    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config
        self.next_test_start_ts_ns: int | None = None
        self.completed_test_intervals: list[tuple[int, int]] = []
        self.training_ever: set[int] = set()
        self.tested_ever: set[int] = set()

    @property
    def max_embargo_seconds(self) -> float:
        return max(
            120.0,
            CAUSAL_GAP_SECONDS + max(float(value) for value in RETURN_HORIZONS_SECONDS),
        )

    def _initial_start(self, observations: Sequence[HorseRaceObservation]) -> int | None:
        if len(observations) < self.config.minimum_training_anchors:
            return None
        ordered = sorted(observations, key=lambda item: item.receive_ts_ns)
        training_edge = ordered[self.config.minimum_training_anchors - 1].receive_ts_ns
        earliest = training_edge + int(self.max_embargo_seconds * NANOSECONDS_PER_SECOND)
        return next((item.receive_ts_ns for item in ordered if item.receive_ts_ns > earliest), None)

    def next_partitions(
        self, observations: Sequence[HorseRaceObservation]
    ) -> tuple[BlockPartition, ...] | None:
        """Return a complete per-horizon block or ``None`` when still warming/incomplete.

        All horizons share the same interval.  A separate partition is emitted because the
        embargo is a cell property and is recorded explicitly as ``max(120, Z+h2)``.
        """

        if not observations:
            return None
        if self.next_test_start_ts_ns is None:
            self.next_test_start_ts_ns = self._initial_start(observations)
        start = self.next_test_start_ts_ns
        if start is None:
            return None
        end = start + int(self.config.test_block_seconds * NANOSECONDS_PER_SECOND)
        longest_response_end = end + int(
            (CAUSAL_GAP_SECONDS + max(RETURN_HORIZONS_SECONDS)) * NANOSECONDS_PER_SECOND
        )
        if max(item.receive_ts_ns for item in observations) < longest_response_end:
            return None
        raw_test = tuple(
            position
            for position, item in enumerate(observations)
            if start <= item.receive_ts_ns < end
        )
        if not raw_test:
            # Advance an empty calendar interval; it can never acquire anchors later because tape
            # time is monotone.  This avoids a permanent stall across a capture gap.
            self.completed_test_intervals.append((start, end))
            self.next_test_start_ts_ns = end
            return self.next_partitions(observations)
        raw_test_set = set(raw_test)
        if raw_test_set & self.training_ever:
            raise AssertionError("one-way ratchet violation: a training anchor re-entered test")
        if raw_test_set & self.tested_ever:
            raise AssertionError("test blocks are not disjoint")
        for old_start, old_end in self.completed_test_intervals:
            if max(start, old_start) < min(end, old_end):
                raise AssertionError("consecutive test intervals overlap")
        block_index = len(self.completed_test_intervals)
        partitions: list[BlockPartition] = []
        training_union: set[int] = set()
        for horizon in RETURN_HORIZONS_SECONDS:
            embargo = max(120.0, CAUSAL_GAP_SECONDS + float(horizon))
            train_end = start - int(embargo * NANOSECONDS_PER_SECOND)
            train = tuple(
                position
                for position, item in enumerate(observations)
                if item.receive_ts_ns <= train_end
            )
            embargoed = tuple(
                position
                for position, item in enumerate(observations)
                if train_end < item.receive_ts_ns < start
            )
            training_union.update(train)
            partitions.append(
                BlockPartition(
                    block_index=block_index,
                    h2_seconds=float(horizon),
                    embargo_seconds=embargo,
                    test_start_ts_ns=start,
                    test_end_ts_ns=end,
                    train=train,
                    embargoed=embargoed,
                    test=raw_test,
                )
            )
        if training_union & raw_test_set:
            raise AssertionError("embargo partition placed an anchor in train and test")
        self.training_ever.update(training_union)
        self.tested_ever.update(raw_test_set)
        self.completed_test_intervals.append((start, end))
        self.next_test_start_ts_ns = end
        return tuple(partitions)


@dataclass(slots=True)
class ScoreAccumulator:
    actual: list[float] = field(default_factory=list)
    predicted: list[float] = field(default_factory=list)
    baseline_predicted: list[float] = field(default_factory=list)
    model_errors: list[float] = field(default_factory=list)
    baseline_errors: list[float] = field(default_factory=list)
    timestamps: list[int] = field(default_factory=list)
    tapes: list[int] = field(default_factory=list)

    def extend(
        self,
        *,
        actual: Sequence[float],
        predicted: Sequence[float],
        baseline_predicted: Sequence[float],
        timestamps: Sequence[int],
        tapes: Sequence[int],
    ) -> None:
        actual_array = np.asarray(actual, dtype=np.float64)
        predicted_array = np.asarray(predicted, dtype=np.float64)
        baseline_array = np.asarray(baseline_predicted, dtype=np.float64)
        self.actual.extend(float(value) for value in actual_array)
        self.predicted.extend(float(value) for value in predicted_array)
        self.baseline_predicted.extend(float(value) for value in baseline_array)
        self.model_errors.extend(float(value) for value in (actual_array - predicted_array) ** 2)
        self.baseline_errors.extend(float(value) for value in (actual_array - baseline_array) ** 2)
        self.timestamps.extend(timestamps)
        self.tapes.extend(tapes)

    def scores(self) -> dict[str, float | int | None]:
        actual = np.asarray(self.actual, dtype=np.float64)
        predicted = np.asarray(self.predicted, dtype=np.float64)
        baseline = np.asarray(self.baseline_predicted, dtype=np.float64)
        zero = np.zeros(actual.shape, dtype=np.float64)
        raw = _r_squared(actual, predicted, zero)
        baseline_r2 = _r_squared(actual, baseline, zero)
        return {
            "n": len(actual),
            "oos_r2_training_mean": raw,
            "baseline_oos_r2_training_mean": baseline_r2,
            "incremental_oos_r2_over_m0": (
                None if raw is None or baseline_r2 is None else raw - baseline_r2
            ),
        }


@dataclass(slots=True)
class CellAccumulator:
    future: ScoreAccumulator = field(default_factory=ScoreAccumulator)
    past: ScoreAccumulator = field(default_factory=ScoreAccumulator)
    blocks_scored: int = 0


@dataclass(frozen=True, slots=True)
class ParsedBatch:
    rows: tuple[dict[str, Any], ...]
    bytes_read: int
    complete_lines: int


class CompleteLineJsonlTail:
    """Read only complete newline-terminated JSON objects from a growing file.

    A partial final line stays in ``_buffer`` until a later poll completes it.  ``torn_lines``
    counts logical lines observed incomplete, not bytes or polling attempts.
    """

    def __init__(self, path: Path, *, chunk_size: int = 1 << 20) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if not path.is_file():
            raise FileNotFoundError(path)
        self.path = path
        self.chunk_size = chunk_size
        self.offset = 0
        self._buffer = b""
        self._partial_counted = False
        self.rows_parsed = 0
        self.malformed_lines = 0
        self.torn_lines = 0

    @property
    def trailing_partial_bytes(self) -> int:
        return len(self._buffer)

    def poll(self, *, max_bytes: int | None = None) -> ParsedBatch:
        size = self.path.stat().st_size
        if size < self.offset:
            raise RuntimeError("followed tape was truncated; refusing to reinterpret it")
        available = size - self.offset
        if max_bytes is not None:
            available = min(available, max_bytes)
        if available <= 0:
            return ParsedBatch((), 0, 0)
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            payload = handle.read(min(available, self.chunk_size))
        self.offset += len(payload)
        prior_partial_was_counted = self._partial_counted
        combined = self._buffer + payload
        pieces = combined.split(b"\n")
        self._buffer = pieces.pop()
        rows: list[dict[str, Any]] = []
        for raw in pieces:
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise TypeError("JSONL row is not an object")
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                self.malformed_lines += 1
                continue
            rows.append(value)
            self.rows_parsed += 1
        if prior_partial_was_counted and pieces:
            # The previously torn logical line completed.  If this same append also began the
            # next line, that new line is a distinct torn line and must be counted below.
            self._partial_counted = False
        reached_current_eof = self.offset == size
        if self._buffer and reached_current_eof and not self._partial_counted:
            self.torn_lines += 1
            self._partial_counted = True
        if not self._buffer:
            self._partial_counted = False
        return ParsedBatch(tuple(rows), len(payload), len(pieces))

    def drain_available(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        while self.offset < self.path.stat().st_size:
            batch = self.poll()
            rows.extend(batch.rows)
            if batch.bytes_read == 0:
                break
        return tuple(rows)


class RefitArtifactSink:
    """Append deterministic all-cell records and write a compact final summary."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.cells_path = directory / "ofi_dashboard_cells.jsonl"
        descriptor = os.open(self.cells_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._handle = os.fdopen(descriptor, "w", encoding="utf-8")
        self.rows_written = 0
        self._closed = False

    def append(self, cells: Sequence[Mapping[str, Any]]) -> None:
        if self._closed:
            raise ValueError("artifact sink is closed")
        if len(cells) != CELL_COUNT:
            raise ValueError(f"each refit must persist exactly {CELL_COUNT} cell rows")
        for cell in cells:
            self._handle.write(
                json.dumps(_json_safe(cell), sort_keys=True, separators=(",", ":")) + "\n"
            )
            self.rows_written += 1
        self._handle.flush()

    def close(self, summary: Mapping[str, Any]) -> dict[str, Any]:
        if not self._closed:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._closed = True
        digest = hashlib.sha256(self.cells_path.read_bytes()).hexdigest()
        compact = {**_json_safe(summary), "cells_sha256": digest, "rows": self.rows_written}
        summary_path = self.directory / "ofi_dashboard_summary.json"
        descriptor = os.open(summary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(compact, sort_keys=True, indent=2) + "\n")
        return compact


def _complete_positions(
    observations: Sequence[HorseRaceObservation],
    candidates: Sequence[int],
    *,
    horizon: float,
    names: Sequence[str],
) -> tuple[int, ...]:
    """Identical future/past geometry and one common complete-case model sample."""

    return tuple(
        position
        for position in candidates
        if horizon in observations[position].future_ticks
        and horizon in observations[position].past_ticks
        and all(
            name in observations[position].features
            and math.isfinite(float(observations[position].features[name]))
            for name in names
        )
    )


def _score_payload(accumulator: ScoreAccumulator) -> dict[str, Any]:
    return accumulator.scores()


def _dependence_payload(
    improvement: Sequence[float],
    timestamps: Sequence[int],
    tapes: Sequence[int],
    *,
    horizon: float,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    estimate = estimate_mean(
        improvement,
        timestamps,
        tapes,
        overlap_seconds=CAUSAL_GAP_SECONDS + horizon,
        replicates=replicates,
        seed=seed,
    )
    payload = asdict(estimate)
    statistic = estimate.newey_west_t
    payload["one_sided_positive_p_value"] = (
        None if statistic is None else 0.5 * math.erfc(statistic / math.sqrt(2.0))
    )
    payload["naive_iid_inference_valid"] = False
    return payload


def _benjamini_hochberg(cells: list[dict[str, Any]]) -> None:
    any_estimated = any(cell.get("status") == "ESTIMATED" for cell in cells)
    candidates = []
    if any_estimated:
        for index, cell in enumerate(cells):
            dependence = cell.get("dependence") or {}
            raw = dependence.get("one_sided_positive_p_value")
            candidates.append((index, 1.0 if raw is None else float(raw)))
    ordered = sorted(candidates, key=lambda item: (item[1], item[0]))
    adjusted: dict[int, float] = {}
    running = 1.0
    total = len(ordered)
    for reverse_rank, (index, value) in enumerate(reversed(ordered), start=1):
        rank = total - reverse_rank + 1
        running = min(running, value * total / rank)
        adjusted[index] = min(1.0, running)
    for index, cell in enumerate(cells):
        q_value = adjusted.get(index)
        cell["bh_fdr_q_value"] = q_value
        cell["bh_fdr_positive_5pct"] = q_value is not None and q_value <= GREEN_THRESHOLD


def _empty_cell(
    *,
    model: str,
    h1: float,
    h2: float,
    status: CellStatus,
    reason: str,
    train_n: int,
    embargoed_n: int,
    test_n: int,
    block_index: int | None,
    embargo_seconds: float,
    trade_identified: bool,
) -> dict[str, Any]:
    names = model_features(model, h1, trade_identified=trade_identified)
    return {
        "scan_id": SCAN_ID,
        "cell_key": cell_key(model, h1, h2),
        "model": model,
        "h1_seconds": h1,
        "h2_seconds": h2,
        "causal_gap_seconds": CAUSAL_GAP_SECONDS,
        "status": status,
        "reason": reason,
        "block_index": block_index,
        "embargo_seconds": embargo_seconds,
        "features": list(names),
        "support": {
            "common_train_n": train_n,
            "embargoed_n": embargoed_n,
            "common_test_n": test_n,
        },
        "block": None,
        "accumulated": None,
        "dependence": None,
        "collinearity": None,
        "coefficient_interpretation": "not estimated",
        "object_categories": {
            "raw_oos_r2": "Estimated",
            "past_mirror_increment": "Estimated (benchmark)",
            "placebo_benchmarked_increment": "Deterministically derived",
            "accumulated_walk_forward_score": "Estimated",
        },
    }


class WalkForwardEvaluator:
    """Fit canonical M0..M6 models on newly ratcheted test blocks."""

    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config
        self.accumulators: dict[str, CellAccumulator] = {}

    def warming_cells(
        self,
        observations: Sequence[HorseRaceObservation],
        *,
        trade_identified: bool,
    ) -> list[dict[str, Any]]:
        cells: list[dict[str, Any]] = []
        for h2 in RETURN_HORIZONS_SECONDS:
            embargo = max(120.0, CAUSAL_GAP_SECONDS + float(h2))
            for h1 in OFI_WINDOWS_SECONDS:
                feature_sets = {
                    model: model_features(model, h1, trade_identified=trade_identified)
                    for model in MODEL_ORDER
                }
                common = tuple(
                    dict.fromkeys(
                        name
                        for model in MODEL_ORDER
                        for name in feature_sets[model]
                        if feature_sets[model]
                    )
                )
                complete = _complete_positions(
                    observations,
                    tuple(range(len(observations))),
                    horizon=float(h2),
                    names=common,
                )
                for model in MODEL_ORDER:
                    status: CellStatus = (
                        "BLOCKED_UNIDENTIFIED"
                        if model == "M2" and not trade_identified
                        else "WARMING"
                    )
                    cells.append(
                        _empty_cell(
                            model=model,
                            h1=float(h1),
                            h2=float(h2),
                            status=status,
                            reason=(
                                "signed trade support is unidentified; no score fabricated"
                                if status == "BLOCKED_UNIDENTIFIED"
                                else "no completed disjoint test block after the warm-up gate"
                            ),
                            train_n=len(complete),
                            embargoed_n=0,
                            test_n=0,
                            block_index=None,
                            embargo_seconds=embargo,
                            trade_identified=trade_identified,
                        )
                    )
        _benjamini_hochberg(cells)
        return cells

    def evaluate_block(
        self,
        observations: Sequence[HorseRaceObservation],
        partitions: Sequence[BlockPartition],
        *,
        trade_identified: bool,
    ) -> list[dict[str, Any]]:
        by_horizon = {partition.h2_seconds: partition for partition in partitions}
        cells: list[dict[str, Any]] = []
        for h2 in RETURN_HORIZONS_SECONDS:
            partition = by_horizon[float(h2)]
            for h1 in OFI_WINDOWS_SECONDS:
                cells.extend(
                    self._evaluate_family(
                        observations,
                        partition,
                        h1=float(h1),
                        h2=float(h2),
                        trade_identified=trade_identified,
                    )
                )
        if len(cells) != CELL_COUNT:
            raise AssertionError(f"full grid required: expected {CELL_COUNT}, got {len(cells)}")
        _benjamini_hochberg(cells)
        for cell in cells:
            dependence = cell.get("dependence") or {}
            p_value = dependence.get("one_sided_positive_p_value")
            accumulated = cell.get("accumulated") or {}
            benchmarked = accumulated.get("placebo_benchmarked_increment")
            future_increment = accumulated.get("future_incremental_oos_r2_over_m0")
            past_increment = accumulated.get("past_incremental_oos_r2_over_m0")
            cell["past_mirror_exceeds_or_equals_future"] = (
                future_increment is not None
                and past_increment is not None
                and past_increment >= future_increment
            )
            cell["green"] = bool(
                benchmarked is not None
                and benchmarked > 0
                and p_value is not None
                and p_value <= GREEN_THRESHOLD
                and not cell["past_mirror_exceeds_or_equals_future"]
            )
        return cells

    def _evaluate_family(
        self,
        observations: Sequence[HorseRaceObservation],
        partition: BlockPartition,
        *,
        h1: float,
        h2: float,
        trade_identified: bool,
    ) -> list[dict[str, Any]]:
        feature_sets = {
            model: model_features(model, h1, trade_identified=trade_identified)
            for model in MODEL_ORDER
        }
        common_names = tuple(
            dict.fromkeys(
                name for model in MODEL_ORDER for name in feature_sets[model] if feature_sets[model]
            )
        )
        train = _complete_positions(observations, partition.train, horizon=h2, names=common_names)
        test = _complete_positions(observations, partition.test, horizon=h2, names=common_names)
        embargoed = _complete_positions(
            observations, partition.embargoed, horizon=h2, names=common_names
        )
        result: list[dict[str, Any]] = []
        if len(train) < self.config.minimum_training_anchors:
            for model in MODEL_ORDER:
                blocked = model == "M2" and not trade_identified
                result.append(
                    _empty_cell(
                        model=model,
                        h1=h1,
                        h2=h2,
                        status="BLOCKED_UNIDENTIFIED" if blocked else "WARMING",
                        reason=(
                            "signed trade support is unidentified; no score fabricated"
                            if blocked
                            else "training support is below the warm-up gate"
                        ),
                        train_n=len(train),
                        embargoed_n=len(embargoed),
                        test_n=len(test),
                        block_index=partition.block_index,
                        embargo_seconds=partition.embargo_seconds,
                        trade_identified=trade_identified,
                    )
                )
            return result
        if len(test) < self.config.minimum_test_anchors:
            for model in MODEL_ORDER:
                blocked = model == "M2" and not trade_identified
                result.append(
                    _empty_cell(
                        model=model,
                        h1=h1,
                        h2=h2,
                        status="BLOCKED_UNIDENTIFIED" if blocked else "INSUFFICIENT",
                        reason=(
                            "signed trade support is unidentified; no score fabricated"
                            if blocked
                            else "test block cannot support the dependence-aware statistic"
                        ),
                        train_n=len(train),
                        embargoed_n=len(embargoed),
                        test_n=len(test),
                        block_index=partition.block_index,
                        embargo_seconds=partition.embargo_seconds,
                        trade_identified=trade_identified,
                    )
                )
            return result

        scores: dict[tuple[str, str], Any] = {}
        for source in ("future", "past"):
            for model in MODEL_ORDER:
                names = feature_sets[model]
                if names:
                    scores[(source, model)] = _fit_score(
                        observations,
                        train,
                        test,
                        model=model,
                        names=names,
                        horizon=h2,
                        source=source,
                    )
        timestamps = [observations[position].receive_ts_ns for position in test]
        # Treat every scored block as a separate bootstrap stratum.  The canonical stationary
        # bootstrap groups by this identifier, so it can never splice the end of one disjoint
        # held-out block to the beginning of another.
        tapes = [
            observations[position].tape_index * 1_000_000 + partition.block_index
            for position in test
        ]
        for model in MODEL_ORDER:
            names = feature_sets[model]
            if not names:
                result.append(
                    _empty_cell(
                        model=model,
                        h1=h1,
                        h2=h2,
                        status="BLOCKED_UNIDENTIFIED",
                        reason="signed trade support is unidentified; no score fabricated",
                        train_n=len(train),
                        embargoed_n=len(embargoed),
                        test_n=len(test),
                        block_index=partition.block_index,
                        embargo_seconds=partition.embargo_seconds,
                        trade_identified=trade_identified,
                    )
                )
                continue
            future = scores[("future", model)]
            future_base = scores[("future", "M0")]
            past = scores[("past", model)]
            past_base = scores[("past", "M0")]
            future_actual = [
                observations[position].future_ticks[h2] - future.target_drift for position in test
            ]
            past_actual = [
                observations[position].past_ticks[h2] - past.target_drift for position in test
            ]
            key = cell_key(model, h1, h2)
            accumulator = self.accumulators.setdefault(key, CellAccumulator())
            accumulator.future.extend(
                actual=future_actual,
                predicted=future.predictions,
                baseline_predicted=future_base.predictions,
                timestamps=timestamps,
                tapes=tapes,
            )
            accumulator.past.extend(
                actual=past_actual,
                predicted=past.predictions,
                baseline_predicted=past_base.predictions,
                timestamps=timestamps,
                tapes=tapes,
            )
            accumulator.blocks_scored += 1
            block_future = _score_payload(
                ScoreAccumulator(
                    actual=list(future_actual),
                    predicted=list(future.predictions),
                    baseline_predicted=list(future_base.predictions),
                )
            )
            block_past = _score_payload(
                ScoreAccumulator(
                    actual=list(past_actual),
                    predicted=list(past.predictions),
                    baseline_predicted=list(past_base.predictions),
                )
            )
            accumulated_future = accumulator.future.scores()
            accumulated_past = accumulator.past.scores()
            future_increment = accumulated_future["incremental_oos_r2_over_m0"]
            past_increment = accumulated_past["incremental_oos_r2_over_m0"]
            block_future_increment = block_future["incremental_oos_r2_over_m0"]
            block_past_increment = block_past["incremental_oos_r2_over_m0"]
            benchmark_improvement = [
                (future_baseline - future_model) - (past_baseline - past_model)
                for future_baseline, future_model, past_baseline, past_model in zip(
                    accumulator.future.baseline_errors,
                    accumulator.future.model_errors,
                    accumulator.past.baseline_errors,
                    accumulator.past.model_errors,
                    strict=True,
                )
            ]
            block_benchmark_improvement = [
                (future_baseline - future_model) - (past_baseline - past_model)
                for future_baseline, future_model, past_baseline, past_model in zip(
                    future_base.errors,
                    future.errors,
                    past_base.errors,
                    past.errors,
                    strict=True,
                )
            ]
            seed = (
                self.config.seed
                + partition.block_index * 100_000
                + int(h2 * 1000)
                + int(h1 * 100)
                + int(model[1])
            )
            dependence = _dependence_payload(
                benchmark_improvement,
                accumulator.future.timestamps,
                accumulator.future.tapes,
                horizon=h2,
                replicates=self.config.bootstrap_replicates,
                seed=seed,
            )
            block_dependence = _dependence_payload(
                block_benchmark_improvement,
                timestamps,
                tapes,
                horizon=h2,
                replicates=self.config.bootstrap_replicates,
                seed=seed + 50_000_000,
            )
            collinearity = _collinearity(observations, train, names[2:])
            unstable = model in {"M4", "M5", "M6"} and (
                float(collinearity.get("max_absolute_correlation") or 0.0)
                >= COLLINEARITY_CORRELATION_THRESHOLD
                or float(collinearity.get("max_vif") or 0.0) >= COLLINEARITY_VIF_THRESHOLD
            )
            model_specific_train = _complete_positions(
                observations, partition.train, horizon=h2, names=names
            )
            model_specific_test = _complete_positions(
                observations, partition.test, horizon=h2, names=names
            )
            model_specific_embargoed = _complete_positions(
                observations, partition.embargoed, horizon=h2, names=names
            )
            model_specific_total = _complete_positions(
                observations,
                tuple(range(len(observations))),
                horizon=h2,
                names=names,
            )
            common_total = _complete_positions(
                observations,
                tuple(range(len(observations))),
                horizon=h2,
                names=common_names,
            )
            result.append(
                {
                    "scan_id": SCAN_ID,
                    "cell_key": key,
                    "model": model,
                    "h1_seconds": h1,
                    "h2_seconds": h2,
                    "causal_gap_seconds": CAUSAL_GAP_SECONDS,
                    "status": "ESTIMATED",
                    "reason": None,
                    "block_index": partition.block_index,
                    "test_interval": {
                        "start_ts_ns": partition.test_start_ts_ns,
                        "end_ts_ns_exclusive": partition.test_end_ts_ns,
                    },
                    "embargo_seconds": partition.embargo_seconds,
                    "features": list(names),
                    "support": {
                        "common_train_n": len(train),
                        "embargoed_n": len(embargoed),
                        "common_test_n": len(test),
                        "common_total_n": len(common_total),
                        "model_total_n_before_common_intersection": len(model_specific_total),
                        "model_train_n_before_common_intersection": len(model_specific_train),
                        "model_embargoed_n_before_common_intersection": len(
                            model_specific_embargoed
                        ),
                        "model_test_n_before_common_intersection": len(model_specific_test),
                        "total_loss_to_common_sample": len(model_specific_total)
                        - len(common_total),
                        "train_loss_to_common_sample": len(model_specific_train) - len(train),
                        "embargoed_loss_to_common_sample": len(model_specific_embargoed)
                        - len(embargoed),
                        "test_loss_to_common_sample": len(model_specific_test) - len(test),
                    },
                    "block": {
                        "future_raw_oos_r2": block_future["oos_r2_training_mean"],
                        "future_incremental_oos_r2_over_m0": block_future_increment,
                        "past_raw_oos_r2": block_past["oos_r2_training_mean"],
                        "past_incremental_oos_r2_over_m0": block_past_increment,
                        "placebo_benchmarked_increment": (
                            None
                            if block_future_increment is None or block_past_increment is None
                            else block_future_increment - block_past_increment
                        ),
                        "test_n": len(test),
                    },
                    "accumulated": {
                        "future_raw_oos_r2": accumulated_future["oos_r2_training_mean"],
                        "future_incremental_oos_r2_over_m0": future_increment,
                        "past_raw_oos_r2": accumulated_past["oos_r2_training_mean"],
                        "past_incremental_oos_r2_over_m0": past_increment,
                        "placebo_benchmarked_increment": (
                            None
                            if future_increment is None or past_increment is None
                            else future_increment - past_increment
                        ),
                        "test_n": accumulated_future["n"],
                        "blocks_scored": accumulator.blocks_scored,
                    },
                    "dependence": dependence,
                    "block_dependence": block_dependence,
                    "selected_alpha": {
                        "future": future.payload["selected_alpha"],
                        "past": past.payload["selected_alpha"],
                    },
                    "training_standardisation": {
                        "future": future.payload["training_standardisation"],
                        "past": past.payload["training_standardisation"],
                    },
                    "coefficients_ticks_per_training_sd": {
                        "future": future.payload["coefficients_ticks_per_training_sd"],
                        "past": past.payload["coefficients_ticks_per_training_sd"],
                    },
                    "fit_diagnostics": {
                        "future": _json_safe(dict(future.payload)),
                        "past": _json_safe(dict(past.payload)),
                    },
                    "collinearity": collinearity,
                    "coefficient_interpretation": (
                        "unstable: individual betas are not interpreted"
                        if unstable
                        else "diagnostic only; predictive coefficients are not causal"
                    ),
                    "object_categories": {
                        "raw_oos_r2": "Estimated",
                        "past_mirror_increment": "Estimated (benchmark)",
                        "placebo_benchmarked_increment": "Deterministically derived",
                        "accumulated_walk_forward_score": "Estimated",
                    },
                }
            )
        return result


def offline_parity_probe(
    observations: Sequence[HorseRaceObservation],
    split: SplitIndex,
    *,
    trade_identified: bool,
    tolerance: float = 1e-12,
    replicates: int = 20,
    seed: int = 20260820,
) -> dict[str, Any]:
    """Compare all dashboard future block scores with the canonical offline evaluator.

    This probe deliberately holds the split fixed.  It tests numerical/model parity, not whether
    the offline 70/30 split and the dashboard's repeated ratchet answer the same estimand.
    """

    canonical = evaluate_cells(
        observations,
        split,
        horizons=RETURN_HORIZONS_SECONDS,
        source="future",
        trade_identified=trade_identified,
        replicates=replicates,
        seed=seed,
    )
    evaluator = WalkForwardEvaluator(
        WalkForwardConfig(
            minimum_training_anchors=2,
            minimum_test_anchors=2,
            bootstrap_replicates=replicates,
            seed=seed,
        )
    )
    dashboard: list[dict[str, Any]] = []
    test_start = min(observations[position].receive_ts_ns for position in split.test)
    test_end = max(observations[position].receive_ts_ns for position in split.test) + 1
    for horizon in RETURN_HORIZONS_SECONDS:
        partition = BlockPartition(
            block_index=0,
            h2_seconds=float(horizon),
            embargo_seconds=max(120.0, CAUSAL_GAP_SECONDS + float(horizon)),
            test_start_ts_ns=test_start,
            test_end_ts_ns=test_end,
            train=split.train,
            embargoed=split.embargoed,
            test=split.test,
        )
        for window in OFI_WINDOWS_SECONDS:
            dashboard.extend(
                evaluator._evaluate_family(
                    observations,
                    partition,
                    h1=float(window),
                    h2=float(horizon),
                    trade_identified=trade_identified,
                )
            )
    canonical_index = {
        cell_key(str(row["model"]), float(row["h1_seconds"]), float(row["h2_seconds"])): row
        for row in canonical
    }
    divergences: list[dict[str, Any]] = []
    for cell in dashboard:
        if cell["status"] == "BLOCKED_UNIDENTIFIED":
            continue
        expected = canonical_index[str(cell["cell_key"])]["oos_r2_training_mean"]
        actual = cell["block"]["future_raw_oos_r2"]
        difference = (
            0.0
            if expected is None and actual is None
            else float("inf")
            if expected is None or actual is None
            else abs(float(expected) - float(actual))
        )
        if difference > tolerance:
            divergences.append(
                {
                    "cell_key": cell["cell_key"],
                    "offline_oos_r2": expected,
                    "dashboard_oos_r2": actual,
                    "absolute_difference": difference,
                }
            )
    maximum = max((float(item["absolute_difference"]) for item in divergences), default=0.0)
    return {
        "tolerance": tolerance,
        "canonical_cells": len(canonical),
        "dashboard_cells": len(dashboard),
        "compared_cells": len(dashboard)
        - sum(cell["status"] == "BLOCKED_UNIDENTIFIED" for cell in dashboard),
        "maximum_absolute_difference": maximum,
        "divergences": divergences,
        "passed": not divergences and len(canonical) == CELL_COUNT and len(dashboard) == CELL_COUNT,
    }


class OfiDashboardEngine:
    """One engine shared by deterministic replay and read-only file follow."""

    def __init__(
        self,
        *,
        run_id: str,
        drive_mode: Literal["replay", "follow"],
        tape_identity: str,
        config: WalkForwardConfig | None = None,
        artifact_sink: RefitArtifactSink | None = None,
    ) -> None:
        self.run_id = run_id
        self.drive_mode = drive_mode
        self.tape_identity = tape_identity
        self.config = config or WalkForwardConfig()
        self.artifact_sink = artifact_sink
        self.ratchet = WalkForwardRatchet(self.config)
        self.evaluator = WalkForwardEvaluator(self.config)
        self.depth200_states: list[BookState] = []
        self.depth20_states: list[BookState] = []
        self.full_rows: list[dict[str, Any]] = []
        self.rows_consumed = 0
        self.current_epoch: int | None = None
        self.last_tape_ts_ns: int | None = None
        self.last_refit_due_ts_ns: int | None = None
        self.last_completed_refit_wall_clock: str | None = None
        self.last_completed_refit_monotonic: float | None = None
        self.refits_completed = 0
        self.refits_skipped = 0
        self.fit_in_progress = False
        self.history: list[dict[str, Any]] = []
        self.cells: list[dict[str, Any]] = self.evaluator.warming_cells((), trade_identified=False)
        self.observations: list[HorseRaceObservation] = []
        self.construction_failures: dict[str, Any] = {}
        self.same_window_diagnostic: list[dict[str, Any]] = []
        self.trade_identified = False
        self.cells_ever_green: set[str] = set()
        self.distinct_leaders: set[str] = set()
        self.current_leader: str | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _append_state(states: list[BookState], state: BookState) -> None:
        if states and (
            states[-1].receive_ts_ns,
            states[-1].connection_epoch,
        ) == (state.receive_ts_ns, state.connection_epoch):
            states[-1] = state
            return
        if states and state.receive_ts_ns < states[-1].receive_ts_ns:
            raise ValueError("capture time moved backwards")
        states.append(state)

    def ingest_dict(self, row: Mapping[str, Any]) -> None:
        """Ingest one parsed tape row; the caller owns complete-line validation."""

        payload = dict(row)
        with self._lock:
            self.rows_consumed += 1
            raw_ts = payload.get("receive_ts")
            if isinstance(raw_ts, str):
                stamp = parse_receive_ts_ns(raw_ts)
                if self.last_tape_ts_ns is not None and stamp < self.last_tape_ts_ns:
                    raise ValueError("tape rows are not monotone in capture time")
                self.last_tape_ts_ns = stamp
            self.current_epoch = int(payload.get("connection_epoch") or 0)
            event = payload.get("event_type")
            if event == DEPTH200:
                built = build_states([payload], DEPTH200)
                if built:
                    self._append_state(self.depth200_states, built[0])
            elif event == DEPTH20:
                built = build_states([payload], DEPTH20)
                if built:
                    self._append_state(self.depth20_states, built[0])
            elif event == "full":
                self.full_rows.append(payload)

    def due_for_refit(self) -> bool:
        with self._lock:
            if self.last_tape_ts_ns is None:
                return False
            if self.last_refit_due_ts_ns is None:
                return True
            cadence_ns = int(self.config.refit_cadence_seconds * NANOSECONDS_PER_SECOND)
            return self.last_tape_ts_ns >= self.last_refit_due_ts_ns + cadence_ns

    def _rebuild_observations(self) -> None:
        observations, failures = build_horserace_observations(
            depth200_states=self.depth200_states,
            depth20_states=self.depth20_states,
            rows=self.full_rows,
            tape_index=0,
            run_id=self.run_id,
        )
        observations, response_epoch_exclusions = enforce_response_geometry(
            observations, self.depth20_states
        )
        failures["response_epoch_or_geometry_excluded"] = response_epoch_exclusions
        self.observations = observations
        self.construction_failures = failures
        self.trade_identified = bool(failures.get("trade_support", {}).get("identified"))

    def refit(self) -> int:
        """Process every newly complete test block, never queueing an overlapping fit."""

        with self._lock:
            if self.fit_in_progress:
                self.refits_skipped += 1
                return 0
            self.fit_in_progress = True
            due_stamp = self.last_tape_ts_ns
        started = time.monotonic()
        snapshots = 0
        try:
            with self._lock:
                self._rebuild_observations()
                while True:
                    partitions = self.ratchet.next_partitions(self.observations)
                    if partitions is None:
                        break
                    self.cells = self.evaluator.evaluate_block(
                        self.observations,
                        partitions,
                        trade_identified=self.trade_identified,
                    )
                    self.same_window_diagnostic = evaluate_same_window(
                        self.observations,
                        partitions[0].as_split_index(),
                        trade_identified=self.trade_identified,
                    )
                    self._record_snapshot(
                        block_index=partitions[0].block_index,
                        tape_refit_ts_ns=partitions[0].test_end_ts_ns,
                    )
                    snapshots += 1
                if snapshots == 0:
                    if not self.ratchet.completed_test_intervals:
                        self.cells = self.evaluator.warming_cells(
                            self.observations, trade_identified=self.trade_identified
                        )
                    self._record_snapshot(block_index=None, tape_refit_ts_ns=due_stamp)
                    snapshots = 1
                self.refits_completed += 1
                self.last_refit_due_ts_ns = due_stamp
                self.last_completed_refit_wall_clock = datetime.now(tz=UTC).isoformat()
                self.last_completed_refit_monotonic = time.monotonic()
        finally:
            elapsed = time.monotonic() - started
            with self._lock:
                overrun = int(elapsed // self.config.refit_cadence_seconds)
                self.refits_skipped += overrun
                self.fit_in_progress = False
        return snapshots

    def _record_snapshot(self, *, block_index: int | None, tape_refit_ts_ns: int | None) -> None:
        self._update_churn()
        deterministic_cells = []
        for cell in self.cells:
            record = {
                **cell,
                "run_id": self.run_id,
                "drive_mode": self.drive_mode,
                "tape_identity": self.tape_identity,
                "refit_index": len(self.history),
                "tape_refit_ts_ns": tape_refit_ts_ns,
            }
            deterministic_cells.append(record)
        if self.artifact_sink is not None:
            self.artifact_sink.append(deterministic_cells)
        self.history.append(
            {
                "index": len(self.history),
                "block_index": block_index,
                "tape_refit_ts_ns": tape_refit_ts_ns,
                "cells": _json_safe(deterministic_cells),
                "honesty": self._honesty_payload(),
                "leader": self._leader_payload(),
            }
        )

    def _update_churn(self) -> None:
        green = [cell for cell in self.cells if cell.get("green")]
        self.cells_ever_green.update(str(cell["cell_key"]) for cell in green)
        # DASH-OUT-01, amended 2026-08-20 (AMENDMENT-1, approved by Aryan).
        # The leader is ranked by future incremental OOS R2 over M0 among cells that PASS the
        # placebo guard. It is deliberately NOT ranked by the placebo-benchmarked increment:
        # future-minus-past rewards a cell whose past mirror collapses, so a badly behaved
        # placebo manufactures a leader. The benchmarked increment remains the guard and stays
        # displayed; it is no longer the sort key.
        eligible = [
            cell
            for cell in self.cells
            if cell.get("status") == "ESTIMATED"
            and cell.get("accumulated", {}).get("future_incremental_oos_r2_over_m0") is not None
            and not cell.get("past_mirror_exceeds_or_equals_future", True)
        ]
        leader = (
            max(
                eligible,
                key=lambda item: (
                    float(item["accumulated"]["future_incremental_oos_r2_over_m0"]),
                    -MODEL_ORDER.index(str(item["model"])),
                    -float(item["h1_seconds"]),
                    -float(item["h2_seconds"]),
                ),
            )
            if eligible
            else None
        )
        self.current_leader = None if leader is None else str(leader["cell_key"])
        if self.current_leader is not None:
            self.distinct_leaders.add(self.current_leader)

    def _leader_payload(self) -> dict[str, Any] | None:
        if self.current_leader is None:
            return None
        return next((cell for cell in self.cells if cell["cell_key"] == self.current_leader), None)

    def _honesty_payload(self) -> dict[str, Any]:
        return {
            "family_cells": CELL_COUNT,
            "positive_benchmarked_at_5pct_now": sum(bool(cell.get("green")) for cell in self.cells),
            "expected_by_chance_at_5pct": CHANCE_EXPECTATION,
            "bh_fdr_positive_5pct": sum(
                bool(cell.get("bh_fdr_positive_5pct")) for cell in self.cells
            ),
            "cells_green_now": sum(bool(cell.get("green")) for cell in self.cells),
            "cells_ever_green": len(self.cells_ever_green),
            "current_leader": self.current_leader,
            "distinct_cells_that_have_led": len(self.distinct_leaders),
            "naive_iid_inference_valid": False,
        }

    def payload(
        self,
        *,
        rows_parsed: int,
        torn_lines: int,
        trailing_partial_bytes: int,
        malformed_lines: int,
    ) -> dict[str, Any]:
        with self._lock:
            fit_age = (
                None
                if self.last_completed_refit_monotonic is None
                else time.monotonic() - self.last_completed_refit_monotonic
            )
            warming = sum(cell["status"] == "WARMING" for cell in self.cells)
            insufficient = sum(cell["status"] == "INSUFFICIENT" for cell in self.cells)
            return cast(
                dict[str, Any],
                _json_safe(
                    {
                        "schema_version": 1,
                        "scan_id": SCAN_ID,
                        "design_document": DESIGN_DOCUMENT,
                        "confirmatory_eligible": False,
                        "read_only": True,
                        "no_socket": True,
                        "no_order_path": True,
                        "evidence_boundary": (
                            "exploratory predictive comparison; not causal, confirmed, tradeable, "
                            "economic, representative, or a signal"
                        ),
                        "drive_mode": self.drive_mode,
                        "tape_identity": self.tape_identity,
                        "run_id": self.run_id,
                        "status_rail": {
                            "anchors_consumed": len(self.observations),
                            "rows_parsed": rows_parsed,
                            "rows_consumed": self.rows_consumed,
                            "torn_lines": torn_lines,
                            "trailing_partial_bytes": trailing_partial_bytes,
                            "malformed_lines": malformed_lines,
                            "current_epoch": self.current_epoch,
                            "fit_age_seconds": fit_age,
                            "refits_completed": self.refits_completed,
                            "refits_skipped": self.refits_skipped,
                            "warming_cells": warming,
                            "insufficient_cells": insufficient,
                            "last_completed_refit_wall_clock": self.last_completed_refit_wall_clock,
                            "last_tape_timestamp": _utc_iso_from_ns(self.last_tape_ts_ns),
                        },
                        "axes": {
                            "models": MODEL_ORDER,
                            "h1_seconds": OFI_WINDOWS_SECONDS,
                            "h2_seconds": RETURN_HORIZONS_SECONDS,
                            "cells": CELL_COUNT,
                        },
                        "config": asdict(self.config),
                        "leader": self._leader_payload(),
                        "honesty": self._honesty_payload(),
                        "cells": self.cells,
                        "construction_failures": self.construction_failures,
                        "trade_model_identified": self.trade_identified,
                        "same_window_diagnostic": {
                            "status": "STRUCTURALLY_SEPARATED",
                            "ranked_with_future_cells": False,
                            "description": (
                                "construction diagnostic only; never enters the leaderboard"
                            ),
                            "cells": self.same_window_diagnostic,
                        },
                        "history_length": len(self.history),
                    }
                ),
            )

    def history_payload(self, index: int) -> dict[str, Any]:
        with self._lock:
            if not self.history:
                raise IndexError("no refits recorded")
            bounded = min(max(index, 0), len(self.history) - 1)
            return cast(dict[str, Any], _json_safe(self.history[bounded]))

    def cells_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scan_id": SCAN_ID,
                "cell_count": len(self.cells),
                "trade_support": _json_safe(self.construction_failures.get("trade_support", {})),
                "cells": _json_safe(self.cells),
            }

    def close_artifacts(self) -> dict[str, Any] | None:
        if self.artifact_sink is None:
            return None
        return self.artifact_sink.close(
            {
                "schema_version": 1,
                "scan_id": SCAN_ID,
                "run_id": self.run_id,
                "drive_mode": self.drive_mode,
                "tape_identity": self.tape_identity,
                "refits_completed": self.refits_completed,
                "refits_skipped": self.refits_skipped,
                "snapshots": len(self.history),
                "cell_count": CELL_COUNT,
                "completed_test_blocks": len(self.ratchet.completed_test_intervals),
                "honesty": self._honesty_payload(),
                "evidence_level": "Dry-run verified when produced by replay",
            }
        )
