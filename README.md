# Shaurya

Shaurya is a private monorepo for a systematic equity/derivatives trading system. It holds three
independently runnable, independently versioned projects that together cover the full path from
raw market data to (currently shadow-only) order execution:

```text
Shaurya/
├── data/       # collect, validate, store, catalogue, discover, and replay market data
├── research/   # consume catalogued datasets, compute features, and run alpha research
└── execution/  # resolve, risk-check, reconcile, and ledger broker-neutral order intents (C++)
```

Each project owns its own build/dependency environment and can be developed, tested, and versioned
on its own. There is no top-level `src/`, `docs/`, or `build/` directory — documentation and
research/execution artifacts live inside each project (`research/docs/`, `execution/docs/`, etc.).

## Architecture

The dependency graph is deliberately one-way:

```text
Shaurya Data  --->  Shaurya Research
      ^
      └--- offline routing export --- Shaurya Execution <--- strategy clients
```

- **`data/` never imports `research/` or `execution/`.** It is the sole owner of Dhan broker
  connectivity for market data, immutable segmented-Parquet storage and lifecycle metadata,
  integrity validation, legacy replay, and a dataset catalogue. It contains no order-placement or
  live-trading code.
- **`research/` has no broker or order authority and never imports `execution/`.** It selects a
  `DatasetHandle` from Data's append-only catalogue and reads rows through `DataAccess`; it does
  not discover raw capture directories or open broker connections itself.
- **`execution/` (C++) imports neither Python project.** Only its offline routing exporter may use
  Data's public instrument APIs. It is a broker-neutral order control plane: routing, pre-trade
  risk, an order state machine, broker reconciliation, and an append-only execution ledger, plus a
  portable `kotak` operator CLI.

## Repository map

| Path | What's there | Go here when you want to... |
|---|---|---|
| `data/` | Python package `shaurya-data`: Dhan capture, tape/manifest storage, validation, catalogue, replay | Capture, validate, or read market data |
| `data/src/shaurya/data/` | Access, capture, Dhan REST/stream clients, instrument master, option chain, quality, storage, tape, trade-direction modules | Understand or extend the data engine internals |
| `data/src/shaurya/data_cli/` | `shaurya-data`, `shaurya-dhan-capture`, `shaurya-chain-capture`, `shaurya-daily-chain-launch` entry points | Find the CLI implementations |
| `data/src/shaurya/contracts/` | Shared typed schema layer for datasets, tape rows, instruments | Understand the wire/storage contracts Data exposes |
| `data/scripts/` | One-off investigation probes (e.g. `dat09_concurrency_probe.py`, `dat17_depth200_*probe.py`) tied to specific tickets, not general CLI tooling | Reproduce a specific past investigation |
| `research/` | Python package `shaurya` (research): OFI/microstructure signals, vol-surface fitting, hypothesis-driven alpha research, dashboards | Run backtests, feature studies, or the daily research pipeline |
| `research/src/shaurya/signals/` | OFI, microprice, CCZ, deep-book feature computation | Look at or add a microstructure signal |
| `research/src/shaurya/surfaces/` | eSSVI implied-vol surface fitting, arbitrage checks, interpolation | Work on the vol-surface pipeline |
| `research/src/shaurya/analytics/` | Dashboards, live OFI studies, mispricing analysis, post-close alpha research | Find the daily research pipeline / dashboards |
| `research/src/shaurya/research/` | Hypothesis registry, evidence ledger, walk-forward executor, multiplicity control | Work on the research-methodology framework itself |
| `research/registries/` | YAML hypothesis/policy/feature registries consumed at runtime | Inspect or edit the pre-registered hypothesis/feature policies |
| `research/docs/` | Module specs, live-evidence records, results, pre-registered hypothesis ledger (`sig-claims/`), literature notes, legacy docs | Read the canonical spec or history for a research module |
| `research/scratch/` | Ad hoc exploratory scripts and result dumps (e.g. `gap_open_analysis/`) | Look up historical research provenance — not imported by any package |
| `execution/` | C++20 broker-neutral order execution control plane | Work on order routing, risk, the ledger, or the operator CLI |
| `execution/include/shaurya/execution/` | Public headers: ledger, executor, session, risk, IPC protocol, contracts, routing snapshot, instrument resolver | Find the public C++ API surface |
| `execution/src/` | Core implementation: ledger, executor, risk engine, order state machine, IPC transport, Kotak adapter, paper broker, reconciliation, replay/repair, parity harness | Work on execution internals |
| `execution/contracts/` (+ `v1/`) | Versioned JSON wire schemas and conformance fixtures | Check or extend the execution wire contracts |
| `execution/ops/` | The `kotak` portable operator CLI (install, package/verify release, session/remote-doctor/auth-helper tooling) and deployment manifests | Operate or deploy an execution session |
| `execution/ledger/` | Ledger format docs and immutable synthetic fixtures (real runtime ledgers are gitignored) | Understand the ledger's on-disk format |
| `execution/tools/` | Standalone executables (`ledger_repair`, `shaurya_parity_harness`) | Repair a ledger or run parity checks |
| `execution/tests/` | Unit/integration tests for the FSM, ledger, ops CLI, risk policy, routing, contracts, and CMake build config | Find or add execution tests |

## Installation and setup

Each project is installed and tested independently from its own directory.

### Data

Requires Python `>=3.11` and [`uv`](https://docs.astral.sh/uv/) as the dependency manager.

```bash
cd data
uv sync --extra dev
uv run pytest
```

### Research

Requires Python `>=3.11` and `uv`. It declares `shaurya-data` as an editable path dependency
(`../data`), so `data/` must be present as a sibling directory.

```bash
cd research
uv sync --extra dev
uv run pytest
```

### Execution

Requires CMake `>=3.20`, a C++20 toolchain, Git (the build fails without a resolvable 40-hex-char
`HEAD`, used for non-secret source attestation), and a Python executable for parts of the release
tooling.

```bash
cmake -S execution -B /private/tmp/shaurya-execution-build \
  -DCMAKE_BUILD_TYPE=Release -DSHAURYA_ENABLE_LIVE_ROUTER=OFF
cmake --build /private/tmp/shaurya-execution-build --parallel
ctest --test-dir /private/tmp/shaurya-execution-build --output-on-failure
```

The build must happen in an empty, out-of-tree directory. `execution/scripts/validate_integration.sh`
is the release-gate entry point that runs this sequence end to end (accepts `CMAKE_BIN`,
`CTEST_BIN`, `PYTHON_BIN` overrides) and never installs dependencies or touches a broker, AWS, or
SSH.

## Running the main workflows

**Data — resolve, validate, and replay a dataset** (from `data/`, after `uv sync`):

```bash
uv run shaurya-data catalog get --catalog <path/to/datasets> --date 2026-08-26
uv run shaurya-data validate    --catalog <path/to/datasets> --date 2026-08-26
uv run shaurya-data replay      --catalog <path/to/datasets> --date 2026-08-26 --limit 100
```

**Data — live capture** (credential and security-master files must live *outside* the repo; see
`data/SECURITY.md` for the credential-handle and file-permission policy):

```bash
uv run shaurya-dhan-capture \
  --credentials /absolute/external/path/dhan.env \
  --security-master /absolute/external/path/security_id_list.csv \
  --security-id <id> --expected-symbol <symbol>

uv run shaurya-chain-capture --help   # option-chain capture

uv run shaurya-daily-chain-launch \
  --credentials /absolute/external/path/dhan.env \
  --security-master /absolute/external/path/security_id_list.csv \
  --launch   # canonical daily entry point: whole chain, every underlying, every session
```

**Research — daily post-close pipeline** (from `research/`, after `uv sync`):

```bash
uv run shaurya-daily-research --catalog <path/to/datasets> --date 2026-08-26 --output-root <dir>
```

This produces a `FINAL_MEMO.md` report under the given output root. Related research CLIs, each
supporting `--help`:

- `shaurya-research` — hypothesis/evidence/walk-forward research tooling
- `shaurya-ofi-dashboard` / `shaurya-surface-dashboard` — replay or follow live-tape dashboards
  (OFI microstructure / implied-vol surface)
- `shaurya-live-ofi-studies`, `shaurya-rolling-c8`, `shaurya-feature-selection-experiment` —
  specific study runners

`research/scripts/*.py` holds additional one-off study/scan scripts, run directly with
`uv run python scripts/<name>.py`; they are not installed console commands.

**Execution — shadow session**: operated through the `kotak` CLI under `execution/ops/`. See
[`execution/README.md`](execution/README.md) and [`execution/docs/`](execution/docs/) for the
control-plane operations and recovery runbooks — this is not duplicated here because the exact
invocation and safety confirmations are load-bearing and versioned with the C++ code.

## Configuration and credentials

No secret values are stored in this repository. Configuration is supplied via environment
variables or external credential files, referenced here by name only:

**Data:**
- `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` — Dhan API credentials (env var or a `key=value`
  credential file that must be mode `600` or stricter; see `data/dhan_client.py` / `data/SECURITY.md`)
- `SHAURYA_NSE_ARCHIVE_ROOT` — absolute path to the date-partitioned NSE archive

**Research:**
- `SHAURYA_CODE_COMMIT` — optional provenance pin read by some study scripts

**Execution:**
- `SHAURYA_ENABLE_LIVE_ROUTER`, `SHAURYA_ENABLE_KOTAK_LIVE` — CMake build options; see Safety below
- `SHAURYA_SOURCE_REVISION`, `SHAURYA_BUILD_JOBS`, `SHAURYA_EXECUTION_SOURCE_ROOT` — build/CI configuration
- `SHAURYA_SHADOW_LAUNCH`, `SHAURYA_PREPARE` — explicit confirmation markers required by shadow-session commands
- `SHAURYA_PARITY_OK`, `SHAURYA_PARITY_REFUSED`, `SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST`, `SHAURYA_PARITY_SCHEMA_DIGEST`, `SHAURYA_ROUTING_TEST_PYTHON` — parity-harness and routing-test configuration
- `KOTAK_AUTH`, `KOTAK_LIVE`, `KOTAK_INVOCATION_ID`, `KOTAK_PYTHON`, `KOTAK_RESULT`, `KOTAK_SSH_BIN`, `KOTAK_TEST_MODE`, `KOTAK_TOOL_MODE` — `kotak` operator CLI configuration
- `D51_MIGRATION_PARITY` — legacy migration parity marker

## Testing and development

- **Data / Research**: `uv run pytest` from within each project directory. Linting/typing via
  `ruff` and `mypy` (declared as dev dependencies in each `pyproject.toml`).
- **Execution**: `ctest --test-dir <build-dir> --output-on-failure` after the CMake build above.
  Test suites are organized by subsystem under `execution/tests/` (`fsm/`, `ledger/`, `ops/`,
  `policy/`, `routing/`, `contracts/`, `cmake/`).
- Raw tapes, compressed datasets, credentials, tokens, certificates, runtime state, and other
  generated local outputs are not tracked by git (see `.gitignore`).

## Further documentation

- [`data/README.md`](data/README.md), [`data/DAT.md`](data/DAT.md), and
  [`data/SECURITY.md`](data/SECURITY.md) — Data architecture, credential policy, and dataset
  interface.
- [`research/README.md`](research/README.md) and [`research/docs/`](research/docs/) — per-module
  specs (`module-spec/`), pre-registered hypotheses (`sig-claims/`), live-evidence records
  (`live-evidence/`), and curated results (`results/`).
- [`execution/README.md`](execution/README.md) and [`execution/docs/`](execution/docs/),
  including `SHADOW_SAFETY.md` and `LIVE_ENABLEMENT_CHECKLIST.md` — the control-plane
  architecture, shadow-safety model, and operations/recovery runbooks.

## Safety: execution is shadow-only

Execution's ordinary build **contains no live broker transport**. Configuring the build with
`SHAURYA_ENABLE_LIVE_ROUTER=ON` or `SHAURYA_ENABLE_KOTAK_LIVE=ON` is an intentional CMake
`FATAL_ERROR` — there is no supported way to compile a live order router from this repository as
it stands. Shadow sessions require no Kotak credential; shadow fills are simulated or proxy
evidence and are never broker-confirmed. `execution/docs/LIVE_ENABLEMENT_CHECKLIST.md` documents
every item required before any live build could be authorized, and none of them are satisfied by
this shadow branch — enabling live trading requires a separate build, a separate evidence review,
and explicit operator authorization, not a flag flip.

Research is likewise read-only: it opens no broker socket, imports no credential or order path,
and cannot place an order. Nothing in this repository has been validated against live trading
performance; research results should be read as research-stage, not as a trading track record.
