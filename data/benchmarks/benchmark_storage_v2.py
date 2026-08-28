#!/usr/bin/env python3
"""Synthetic JSONL versus segmented-Parquet benchmark; never contacts a broker."""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import time
import tracemalloc
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypeVar

import pyarrow as pa

from shaurya.contracts.artifacts import RunId
from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.data import DataAccess, DataCaptureSession, DataCatalog, SegmentedParquetWriter

T = TypeVar("T")
INSTRUMENT = "NSE:NSE_FNO:NIFTY:future:synthetic"
RUN_ID = "sha-20260827T034500.000000Z-b0b0b0b0"


def row(sequence: int) -> TapeRow:
    event_type = "depth200" if sequence % 20 == 0 else "depth20"
    depth = 200 if event_type == "depth200" else 20
    stamp = datetime(2026, 8, 27, 3, 45, tzinfo=UTC) + timedelta(milliseconds=sequence * 20)
    return TapeRow(
        run_id=RUN_ID,
        receive_sequence=sequence,
        source_sequence=sequence,
        connection_epoch=1,
        source="synthetic",
        event_type=event_type,
        instrument_id=INSTRUMENT,
        broker_security_id="synthetic-1",
        exchange_segment="NSE_FNO",
        exchange_ts=stamp - timedelta(milliseconds=2),
        receive_ts=stamp,
        raw_message_size_bytes=4096,
        update_side="both",
        last_price=25000.123456789012,
        last_quantity=25,
        cumulative_volume=sequence * 25,
        open_interest=100_000,
        bids=tuple(
            DepthLevel(25000.0 - level * 0.05, 100 + level, level + 1) for level in range(depth)
        ),
        asks=tuple(
            DepthLevel(25000.1 + level * 0.05, 120 + level, level + 2) for level in range(depth)
        ),
    )


def measured(operation: Callable[[], T]) -> tuple[T, float, int, int]:
    original_pool = pa.default_memory_pool()
    measured_pool = pa.proxy_memory_pool(original_pool)
    pa.set_memory_pool(measured_pool)
    tracemalloc.start()
    try:
        started = time.perf_counter()
        result = operation()
        seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        arrow_peak = measured_pool.max_memory()
    finally:
        tracemalloc.stop()
        gc.collect()
        pa.set_memory_pool(original_pool)
    return result, seconds, peak, arrow_peak


def benchmark(count: int, root: Path) -> dict[str, Any]:
    rows = tuple(row(sequence) for sequence in range(1, count + 1))
    jsonl = root / "market-events.jsonl"
    parquet_root = root / "parquet"

    def write_jsonl() -> None:
        with jsonl.open("w", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item.to_dict(), separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    _, json_write, json_peak, json_arrow_peak = measured(write_jsonl)

    def write_parquet() -> tuple[Any, ...]:
        writer = SegmentedParquetWriter(parquet_root, dataset_id=RUN_ID, max_rows=1_000)
        for item in rows:
            writer.write(item)
        return writer.close()

    segments, parquet_write, parquet_peak, parquet_arrow_peak = measured(write_parquet)

    def read_jsonl() -> int:
        with jsonl.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if json.loads(line))

    json_count, json_read, json_read_peak, json_read_arrow_peak = measured(read_jsonl)

    def read_parquet() -> int:
        from shaurya.data import iter_parquet_rows

        return sum(1 for segment in segments for _ in iter_parquet_rows(Path(segment.path)))

    parquet_count, parquet_read, parquet_read_peak, parquet_read_arrow_peak = measured(read_parquet)
    midpoint = rows[count // 2].receive_ts

    def filter_jsonl() -> int:
        with jsonl.open("r", encoding="utf-8") as handle:
            matches = 0
            for line in handle:
                record = json.loads(line)
                if (
                    datetime.fromisoformat(record["receive_ts"]) >= midpoint
                    and record["event_type"] == "depth200"
                ):
                    matches += 1
            return matches

    json_filtered, json_filter, json_filter_peak, json_filter_arrow_peak = measured(filter_jsonl)

    def filter_parquet() -> int:
        from shaurya.data import iter_parquet_rows

        return sum(
            1
            for segment in segments
            for _ in iter_parquet_rows(
                Path(segment.path), start=midpoint, channels=(DataChannel.DEPTH200,)
            )
        )

    parquet_filtered, parquet_filter, parquet_filter_peak, parquet_filter_arrow_peak = measured(
        filter_parquet
    )

    finalization_samples: list[float] = []
    for sample in range(5):
        writer = SegmentedParquetWriter(
            root / f"finalize-{sample}", dataset_id=RUN_ID, max_rows=500
        )
        for item in rows[:499]:
            writer.write(item)
        started = time.perf_counter()
        writer.close()
        finalization_samples.append(time.perf_counter() - started)

    catalog = DataCatalog(root / "catalog")
    request = DatasetRequest(
        consumer="BENCHMARK",
        purpose="active-follow visibility",
        trading_date=date(2026, 8, 27),
        channels=(DataChannel.DEPTH20, DataChannel.DEPTH200),
        instrument_ids=(INSTRUMENT,),
    )
    session = DataCaptureSession.create(
        catalog=catalog,
        request=request,
        output_root=root / "active",
        run_id=RunId(RUN_ID),
        segment_max_rows=100,
        segment_max_seconds=3600,
    )
    follower = DataAccess(catalog).follow(session.handle)
    for item in rows[:99]:
        session.write(item)
    started = time.perf_counter()
    session.write(rows[99])
    visible = follower.poll().complete_lines
    visibility_delay = time.perf_counter() - started
    session.close()

    def throughput(seconds: float) -> float:
        return count / seconds

    return {
        "schema_version": "1.0.0",
        "synthetic_rows": count,
        "jsonl": {
            "write_rows_per_second": throughput(json_write),
            "read_rows_per_second": throughput(json_read),
            "filtered_rows_per_second": throughput(json_filter),
            "bytes": jsonl.stat().st_size,
            "write_python_tracemalloc_peak_bytes": json_peak,
            "write_arrow_pool_peak_bytes": json_arrow_peak,
            "read_python_tracemalloc_peak_bytes": json_read_peak,
            "read_arrow_pool_peak_bytes": json_read_arrow_peak,
            "filter_python_tracemalloc_peak_bytes": json_filter_peak,
            "filter_arrow_pool_peak_bytes": json_filter_arrow_peak,
        },
        "segmented_parquet": {
            "write_rows_per_second": throughput(parquet_write),
            "read_rows_per_second": throughput(parquet_read),
            "filtered_rows_per_second": throughput(parquet_filter),
            "bytes": sum(segment.bytes for segment in segments),
            "segments": len(segments),
            "write_python_tracemalloc_peak_bytes": parquet_peak,
            "write_arrow_pool_peak_bytes": parquet_arrow_peak,
            "read_python_tracemalloc_peak_bytes": parquet_read_peak,
            "read_arrow_pool_peak_bytes": parquet_read_arrow_peak,
            "filter_python_tracemalloc_peak_bytes": parquet_filter_peak,
            "filter_arrow_pool_peak_bytes": parquet_filter_arrow_peak,
            "median_segment_finalization_ms": statistics.median(finalization_samples) * 1_000,
            "active_follow_visibility_ms": visibility_delay * 1_000,
        },
        "checks": {
            "full_read_counts_equal": json_count == parquet_count == count,
            "filtered_read_counts_equal": json_filtered == parquet_filtered,
            "active_follow_rows": visible,
            "memory_measurement": "Python tracemalloc plus isolated Arrow memory-pool peaks",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=5_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rows < 1_000:
        raise ValueError("benchmark requires at least 1,000 rows")
    with TemporaryDirectory(prefix="shaurya-storage-v2-", dir="/private/tmp") as temporary:
        result = benchmark(args.rows, Path(temporary))
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
