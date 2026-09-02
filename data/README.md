# Shaurya Data

Shaurya Data is the independently installable market-data engine. It owns Dhan connectivity,
capture, immutable storage, integrity validation, cataloguing, dataset discovery, and deterministic
replay. New captures use segmented Parquet; legacy JSONL remains read-only. Data has no dependency
on Research and contains no order-placement or live-trading code.

## Documentation

- [`DAT.md`](DAT.md) is the canonical DAT specification and internal architecture.
- [`ADR-0001-SEGMENTED-PARQUET-STORAGE.md`](ADR-0001-SEGMENTED-PARQUET-STORAGE.md)
  records the storage-v2 decision, recovery model, alternatives, and benchmark.
- [`STORAGE_V2_IMPLEMENTATION_PLAN.md`](STORAGE_V2_IMPLEMENTATION_PLAN.md) records the observed
  persistence inventory and migration acceptance criteria.
- [`DAT_01_RECONCILIATION.md`](DAT_01_RECONCILIATION.md) is the supporting decision record for
  the original Dhan-client reconciliation and rejected unsafe paths.

## Install and test

From the repository root, enter the Data project before running its tools so test discovery and
relative script imports stay scoped to Data:

```bash
cd data
uv sync --extra dev
uv run pytest
```

## Dataset interface

Research and other consumers locate data through the public catalogue contract:

```python
from datetime import date
from pathlib import Path

from shaurya.data import DataAccess, DataCatalog

catalog = DataCatalog(Path("/archive/NSE/2026-08-26/metadata/datasets"))
dataset = catalog.get_dataset(trading_date=date(2026, 8, 26))
access = DataAccess(catalog)
validation = access.validate(dataset)  # completed datasets only
rows = access.rows(dataset)            # logical TapeRow stream, any supported format
```

The equivalent CLI commands are:

```bash
uv run shaurya-data catalog list \
  --catalog /archive/NSE/2026-08-26/metadata/datasets

uv run shaurya-data inspect \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --dataset-id ds-example

uv run shaurya-data catalog get \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --date 2026-08-26

uv run shaurya-data validate \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --date 2026-08-26

uv run shaurya-data preview \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --date 2026-08-26 --limit 100

uv run shaurya-data export \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --dataset-id ds-example --limit 1000 --output /private/tmp/preview.csv
```

`inspect` and `preview` are human-oriented. `validate` verifies lifecycle, ordered segment
metadata, hashes, schema, sequence, coverage, and complete logical replay. `replay` emits JSONL only
as an explicit machine export; production capture and metadata do not write JSON/JSONL.

## Storage layout and lifecycle

```text
YYYY-MM-DD/
├── raw/dhan/nifty-future/
│   └── dhan-nifty-future-depth20-depth200-20260827-034500-a1b2c3d4/
│       ├── market-events-000001-034500000000Z-034529999999Z.parquet
│       └── market-events-000002-034530000000Z-034559999999Z.parquet
├── metadata/datasets/
│   ├── events/ds-…/00000001-active.parquet
│   ├── claims/<acquisition-fingerprint>.claim
│   └── operational/ds-…/capture-metrics.parquet
├── indexes/
└── derived/
```

Segments rotate at the first of 50,000 rows, 30 seconds of receive-time span, or 64 MiB estimated
uncompressed data. Row groups default to 10,000 rows. The writer closes and validates a unique
`.partial-*` file, fsyncs it, atomically renames it, hashes it, and only then publishes catalogue
metadata. Active readers see only published closed segments. File presence never implies a
completed dataset: only the catalogue `completed` lifecycle event does.

On restart, `inventory_recovery(dataset_dir, published_segments)` identifies partials for
quarantine and final-but-unpublished orphan files for operator review. Do not put either into
service without footer/schema/count/hash verification and an explicit catalogue event. Failed,
invalidated, cancelled, and orphaned handles retain their terminal reason.

## Direct bounded inspection

When optional tools are installed, a published segment can be inspected without changing it:

```python
import pyarrow.parquet as pq
table = pq.read_table("market-events-000001-034500000000Z-034529999999Z.parquet")
print(table.select(["receive_ts", "instrument_id", "last_price"]).slice(0, 20))

# pandas: table.slice(0, 1000).to_pandas()
# Polars: polars.scan_parquet("market-events-*.parquet").head(1000).collect()
# DuckDB: duckdb.sql("SELECT * FROM 'market-events-*.parquet' LIMIT 1000")
```

PyArrow is the storage implementation. pandas, Polars, and DuckDB are optional bounded readers,
not catalogue authorities or mutable storage backends.

## Legacy conversion

Legacy JSONL tapes, sidecar indexes, manifests, and archives remain supported through DataAccess
so historical runs stay reproducible. Conversion is explicit and preserves the source:

```bash
# Read-only eligibility and semantic-digest report (default)
uv run shaurya-data legacy-migrate \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --tape /archive/legacy/completed.jsonl --source-state completed

# Write a new Parquet representation; never edits or deletes the JSONL source
uv run shaurya-data legacy-migrate \
  --catalog /archive/NSE/2026-08-26/metadata/datasets \
  --tape /archive/legacy/completed.jsonl --source-state completed \
  --convert --execute --output-root /archive/NSE/2026-08-26/raw
```

Active, torn-tail, failed, cancelled, or invalidated sources cannot be converted into completed
datasets. Rollback disables new acquisition; it does not rewrite either representation.

## Collection

Credential and security-master files must live outside this repository.

**Daily production capture records the configured NIFTY and BANKNIFTY research chains on one
Dhan Standard/Full WebSocket.** The canonical entry point is `shaurya-daily-chain-launch`. The
default chain is the nearest two live expiries, strikes within 6% of live spot, and up to 120
options per underlying; it is intentionally not every exchange-listed strike. Consolidating both
chains on one socket prevents the second chain from consuming another connection slot and evicting
an older capture with Dhan reason code `805`.

Before the session, run the production preflight:

```bash
uv run shaurya-daily-chain-launch --preflight
```

The preflight fails closed unless the credentials file and dated security master exist, the NSE
archive is available, Dhan resolves a positive spot and the requested expiries, and the security
master supplies selected options for every resolved expiry. It prints the resolved spot, expiries,
and selected instrument counts, followed by the exact child commands that would be launched.

Launch production capture with:

```bash
uv run shaurya-daily-chain-launch --launch
```

`--launch` always reruns the same preflight before creating its `chains` tmux window and pins each
underlying's checked spot/expiries into one combined child capture. The child enforces the default
95% instrument coverage floor separately for each underlying: falling below that floor, or ending
with a stream error, invalidates the dataset and returns nonzero instead of silently publishing a
plausible-looking partial chain. Dhan disconnect reason `805` is terminal and recorded rather than
retried, because reconnecting would only evict another account socket. Override the floor only
deliberately with `--minimum-coverage-fraction`.

`--credentials` and `--security-master` both default to this machine's live operational paths and
only need overriding on another host or for a controlled test:

- `--credentials` defaults to `~/Documents/Market-Making-Secrets/dhan.env`.
- `--security-master` defaults to `data/instrument-masters/dhan_instrument_master_<date>.csv`
  for the resolved trading date.
- `--output-root` overrides where captures land; omitted, it falls through to the configured
  NSE archive root (`/Volumes/Aryan/NSE`, or the `SHAURYA_NSE_ARCHIVE_ROOT` environment
  override already honored by every capture command in this package).

Without `--preflight` or `--launch`, the launcher only prints auto-resolving child commands and does
not claim that live spot/expiry or storage checks have passed. `shaurya-dhan-capture` (single
instrument) and `shaurya-chain-capture` (one chain) remain available directly for isolated
diagnostics and controlled tests, but neither is the normal daily entry point.

See [`SECURITY.md`](SECURITY.md) for the credential-handle and file-permission policy.
## High-frequency derived variables

The public `shaurya.data.high_frequency` API constructs the versioned futures, parity, option-book,
leave-ATM eSSVI, ATM-IV, state, gate, interaction, and future-only target families frozen on
2026-08-27. `VersionedFeatureRow` persists the exact feature-version string and causal source
timestamps with every value; `TargetValue` is a separate type and cannot be placed in a feature
row. Invalid, stale, incomplete, or cross-reconnect inputs are explicit missing values, never zero.

Canonical identities, roles, units, clocks, freshness, and validation status are registered in
`research/registries/microstructure_features_v2.yaml` and documented in
`research/hypothesis_feature_research/methodology/high-frequency-constructions.md`. The v1
registries remain frozen for historical replay.
