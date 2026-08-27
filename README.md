# Shaurya

Shaurya is one private repository containing two independently runnable Python projects and an
independently buildable C++ Execution project scaffold:

```text
Shaurya/
├── data/       # collect, validate, store, catalogue, discover, and replay market data
├── research/   # consume catalogued datasets, compute features, and run alpha research
└── execution/  # resolve, risk-check, reconcile, and ledger broker-neutral order intents
```

The dependency is deliberately one-way:

```text
Shaurya Data  --->  Shaurya Research
      ^
      └--- offline routing export --- Shaurya Execution <--- strategy clients
```

`data/` never imports `research/` or `execution/`. Research selects a `DatasetHandle` from Data's append-only
catalogue and reads rows through `DataAccess`; it does not discover raw capture directories or
open broker connections. Research has no broker or order authority and never imports Execution.
The C++ Execution runtime imports neither Python project; only its offline routing exporter may use
Data's public instrument APIs. Each project owns its own build/dependency environment.

## Quick start

```bash
# Data only
(cd data && uv sync --extra dev && uv run pytest)

# Research (installs the sibling Data package through its declared dependency)
(cd research && uv sync --extra dev && uv run pytest)

# Execution (shadow-only; out-of-tree C++20 build)
cmake -S execution -B /private/tmp/shaurya-execution-build -DCMAKE_BUILD_TYPE=Release
cmake --build /private/tmp/shaurya-execution-build --parallel
ctest --test-dir /private/tmp/shaurya-execution-build --output-on-failure
```

See [`data/README.md`](data/README.md) for collection, catalogue, validation, and replay commands.
See [`research/README.md`](research/README.md) for dataset-driven analysis and daily reports.
See [`execution/README.md`](execution/README.md) for the shadow execution control plane.

## Repository policy

Raw tapes, compressed datasets, credentials, tokens, certificates, runtime state, and generated
local outputs are not tracked. Live order routing is absent from ordinary Execution builds.
Historical research provenance is retained under `research/docs/`
and `research/scratch/`; it is not imported by either runtime package.
