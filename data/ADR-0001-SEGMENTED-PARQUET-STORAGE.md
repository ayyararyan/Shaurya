# ADR-0001: segmented Parquet market-event storage

- Status: accepted for implementation
- Date: 2026-08-27
- Scope: newly captured Shaurya Data market events and Data-owned lifecycle metadata

## Context

The version-1 design uses one growing JSONL tape with JSON seek metadata, JSONL manifests and an
append-only JSONL catalogue. It is streamable and auditable but expensive for typed analytical
scans, exposes physical-format assumptions to Research, uses opaque run-directory names, and makes
filtering depend on a custom byte-offset index. A single growing Parquet file is not a safe
replacement: a readable Parquet file requires its footer, and reopening a published file would
violate immutable evidence semantics.

Production data is stored on an SMB archive. SQLite and DuckDB are useful local query engines, but
we have no verified locking, crash-durability, or multi-host writer evidence for one mutable
database file on this share. They are therefore readers/tools, not the system of record.

The evaluated row formats were the existing JSONL, Arrow IPC streams/files, one appendable
Parquet file, and immutable segmented Parquet. JSONL remains the simplest recovery/debug format but
has weak typing, high parse cost, and no column/row-group pruning. Arrow IPC is strongly typed and
fast but has a smaller durable analytics-tool ecosystem and does not solve catalogue publication.
A single Parquet file is unreadable before its footer and would require reopening published
evidence. Segmentation is the only evaluated design that combines typed analytical access with
bounded, immutable publication.

## Decision

New raw market events use Apache Parquet through PyArrow with Zstandard compression. A capture
buffers a bounded batch and writes each segment to a unique `.partial` file. It closes the file,
validates the exact Arrow schema and row count, fsyncs the file, atomically renames it to a final
immutable human-readable name, fsyncs the parent directory where supported, calculates SHA-256,
and only then publishes segment metadata.

The canonical layout is:

```text
YYYY-MM-DD/
  raw/dhan/<scope>/<dataset-name>/
    market-events-000001-091500000000Z-091529999999Z.parquet
  metadata/datasets/
    events/<dataset-id>/<event-sequence>-<event-type>.parquet
    claims/<acquisition-fingerprint>.claim
  indexes/
  derived/
```

`dataset-name` is filesystem-safe and derived from trading date, source, exchange/scope, channels,
capture start time, and an optional bounded suffix. The internal `dataset-id` is collision
resistant and remains metadata, not the primary path. Segment filenames contain monotonic segment
numbers and coverage times. Full hashes never appear in names.

Lifecycle and catalogue history also use atomically published immutable Parquet fragments. Current
state is resolved deterministically by `(event_sequence, recorded_at, event_digest)`. A malformed,
duplicate-sequence, inconsistent, or unsupported event fails closed. Acquisition claims use atomic
exclusive creation and record producer identity; dead local claims may be marked orphaned but are
never silently converted into completed data. Readers do not depend on a mutable pointer file.

## Schema and evolution

Schema `market-event/2.0.0` maps every `TapeRow` field explicitly. Prices use
`decimal128(38, 12)`; quantities, volume, OI, receive sequence, source sequence and raw byte counts
use signed 64-bit integers; connection epochs and order counts use signed 32-bit integers;
timestamps use nanoseconds normalized to UTC; event/source/side/version text remains UTF-8; flags
are a list of UTF-8 values; bids and asks are Arrow lists of structs containing decimal price,
64-bit quantity and 32-bit order count. Nullable fields retain nulls. Row order is global receive
order and sequences must be strictly increasing across segment boundaries.

Additive nullable fields are minor-compatible. A physical type, nullability, unit, ordering, or
semantic change requires a new major schema. Readers reject unsupported versions and never
concatenate incompatible major versions. Legacy JSONL rows retain their original schema semantics.

## Rotation, atomicity, recovery, and memory

Defaults are 50,000 rows, 30 seconds of receive-time span, or 64 MiB estimated uncompressed batch
size, whichever arrives first. These bounds cap memory and active-follow delay while avoiding tiny
files. The benchmark records write/read/filter throughput, size, Python-traced memory, isolated
Arrow memory-pool peaks, finalization latency, and follower visibility. The two memory measures are
reported separately rather than pretending either is total process RSS. Defaults may change only
with recorded evidence.

Published segments are never reopened. Same-directory atomic rename turns a fully synced
`.partial` into a final file. A crash before rename leaves a `.partial` file that is not catalogued
and is quarantined by recovery. A crash after final-file rename but before catalogue publication
leaves an orphan final file that recovery inventories but readers ignore until a verified
publication event is written. Completion is a separate lifecycle event and cannot be inferred from
file presence.

## Integrity and identity

Each segment records SHA-256, row/byte counts, sequence bounds, time coverage, instruments,
channels, schema version, and storage version. The dataset digest is SHA-256 over the canonical
ordered segment-metadata records. DataAccess verifies segment hashes and the dataset digest before
completed Research replay. Parquet footer statistics provide pruning; no additional index is
created unless it supplies a measured access benefit.

## Compatibility, migration, and rollback

Version-1 JSONL handles, catalogues, manifests, indexes, gzip archives, and readers remain a
read-only compatibility lane. New capture code cannot instantiate a JSONL writer. Legacy conversion
is explicit, streaming, dry-runnable, resumable, and restricted to verified completed input. It
preserves the original, compares ordered semantic row digests and coverage, and records lineage.
Cancelled, active, torn-tail, failed, invalidated, or merely endpoint-checked input cannot become a
completed Parquet dataset.

Rollback means disabling new acquisition and continuing to read already published Parquet and
legacy JSONL through DataAccess; it never means rewriting or deleting either representation.

## Consequences

The design adds PyArrow and creates more files than a monolithic tape, but it gives bounded loss on
process failure, atomic visibility, column pruning, typed nested depth, format-neutral replay, and
human-operable paths. SMB metadata listing cost is controlled by one dataset event directory and
bounded segment rotation. Mutable-database convenience is intentionally deferred until the actual
archive filesystem is proven safe under concurrent multi-process and multi-host tests.

## Synthetic benchmark evidence

`benchmarks/benchmark_storage_v2.py` ran once on 2026-08-27 with 5,000 deterministic mixed
depth20/depth200 rows, five 1,000-row Parquet segments, Zstandard compression, and all output under
`/private/tmp`. Full and filtered logical row counts matched; an active follower saw all 100 rows
in the first published segment.

| Metric | JSONL | Segmented Parquet |
| --- | ---: | ---: |
| Write rows/s | 2,491 | 1,330 |
| Full logical read rows/s | 8,478 | 855 |
| Filtered logical read rows/s | 8,065 | 7,096 |
| Stored bytes | 19,262,646 | 185,792 |
| Write Python-tracemalloc peak bytes | 133,162 | 18,723,826 |
| Full-read Python-tracemalloc peak bytes | 129,605 | 28,422,901 |
| Filter Python-tracemalloc peak bytes | 147,883 | 9,231,788 |
| Write Arrow-pool peak bytes | 0 | 2,855,488 |
| Full-read Arrow-pool peak bytes | 0 | 3,014,208 |
| Filter Arrow-pool peak bytes | 0 | 3,010,688 |
| Median 499-row finalization | n/a | 20.9 ms |
| 100-row active-follow visibility | n/a | 60.9 ms |

This small Python object-reconstruction benchmark favors streaming JSONL for throughput and
Python-traced memory, while Parquet is about 104 times smaller and exposes typed predicate pruning.
The JSONL writer is flushed and fsynced; Parquet fsyncs each published segment. Arrow-native pool
peaks are reported independently. It supports bounded segmentation and exposes a real memory/CPU
trade-off; it is not a production-load claim or evidence of market-session completeness. The raw
JSON result is intentionally not tracked and can be regenerated with:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python benchmarks/benchmark_storage_v2.py \
  --rows 5000 --output /private/tmp/shaurya-storage-v2-benchmark.json
```
