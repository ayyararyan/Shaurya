# Shaurya Data

Shaurya Data is the independently installable market-data engine. It owns Dhan connectivity,
capture, immutable tape and manifest storage, integrity validation, indexing, archival,
cataloguing, dataset discovery, and deterministic replay. It has no dependency on Shaurya
Research and contains no order-placement or live-trading code.

## Documentation

- [`DAT.md`](DAT.md) is the canonical DAT specification and internal architecture.
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

catalog = DataCatalog(Path("/Volumes/Aryan/NSE/2026-08-26/metadata/datasets.jsonl"))
dataset = catalog.get_dataset(trading_date=date(2026, 8, 26))
rows = DataAccess(catalog).rows(dataset)
```

The equivalent CLI commands are:

```bash
uv run shaurya-data catalog get \
  --catalog /Volumes/Aryan/NSE/2026-08-26/metadata/datasets.jsonl \
  --date 2026-08-26

uv run shaurya-data validate \
  --catalog /Volumes/Aryan/NSE/2026-08-26/metadata/datasets.jsonl \
  --date 2026-08-26

uv run shaurya-data replay \
  --catalog /Volumes/Aryan/NSE/2026-08-26/metadata/datasets.jsonl \
  --date 2026-08-26 --limit 100
```

Validation streams the complete selected dataset through the existing hash- and index-aware
reader. Replay emits canonical tape rows as JSON Lines.

## Collection

Credential and security-master files must live outside this repository:

```bash
uv run shaurya-dhan-capture \
  --credentials /absolute/external/path/dhan.env \
  --security-master /absolute/external/path/security_id_list.csv \
  --security-id 58072 \
  --expected-symbol NIFTY-AUG2026-FUT
```

For an option-chain capture, use `shaurya-chain-capture --help`. Production capture defaults to
the date-partitioned NSE archive. Use non-archive overrides only for intentional isolated tests.

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
