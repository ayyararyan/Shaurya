# Shaurya

Shaurya is one private repository containing two independently runnable Python projects:

```text
Shaurya/
├── data/       # collect, validate, store, catalogue, discover, and replay market data
└── research/   # consume catalogued datasets, compute features, and run alpha research
```

The dependency is deliberately one-way:

```text
Shaurya Data  --->  Shaurya Research
```

`data/` never imports `research/`. Research selects a `DatasetHandle` from Data's append-only
catalogue and reads rows through `DataAccess`; it does not discover raw capture directories or
open broker connections. Each project owns its own `pyproject.toml`, lockfile, source tree,
tests, commands, and dependency environment.

## Quick start

```bash
# Data only
(cd data && uv sync --extra dev && uv run pytest)

# Research (installs the sibling Data package through its declared dependency)
(cd research && uv sync --extra dev && uv run pytest)
```

See [`data/README.md`](data/README.md) for collection, catalogue, validation, and replay commands.
See [`research/README.md`](research/README.md) for dataset-driven analysis and daily reports.

## Repository policy

Raw tapes, compressed datasets, credentials, tokens, certificates, runtime state, and generated
local outputs are not tracked. Live execution, order placement, and strategy execution engines
are outside this repository. Historical research provenance is retained under `research/docs/`
and `research/scratch/`; it is not imported by either runtime package.
