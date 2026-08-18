# Shaurya

**Status:** design note, not a frozen specification.
**Created:** 2026-08-17
**Owner:** Aryan Ayyar
**Task ledger:** [`TASKS.md`](TASKS.md) — the single source of truth for status. This file
explains *what* and *why*; `TASKS.md` tracks *what is done*.
**GCP scaling plan:** [`GCP_SCALING.md`](GCP_SCALING.md) — design note for using the Shunya GCP
credit grant to scale `DAT`/`SIG`/`BKT`/`ANL` to the index-F&O universe (2026-08-18).

> **Naming (decided 2026-08-17).** "Shaurya" is the name of **this module**, and nothing else.
> The options market-making strategy that previously carried the name is now called
> **Market Making** — local path `/Users/maheit/Documents/Market-Making`, GitHub
> `ayyararyan/Market-Making` (renamed from `ayyararyan/Shaurya` on 2026-08-17). The unrelated
> personal Drive folder that also held the name is now `My Drive/Valour/`.

> **Plug-and-play (decided 2026-08-17).** The module is a **dependency**, not a template. Any
> strategy plugs into it; it plugs into nothing. Strategies import the module and pin a version;
> the module never imports from a strategy and never carries strategy-specific branches.
> Market Making gets refactored to consume it. See `TASKS.md` §1.2.

---

## 1. What this is, in plain words

Every strategy in `../strategy/` was built from scratch. Each one re-wrote its own market-data
feed, its own broker client, its own risk checks, its own backtester, its own logging. Six
projects, six copies of the same plumbing, none of it shared, none of it tested once and then
trusted everywhere.

This module ends that. From now on the plumbing is written **once**, tested once, and every new
strategy is a thin layer on top of it. A strategy should be the part that is actually novel —
the signal, the surface, the quoting rule — and nothing else.

Two artifacts, deliberately separated:

| Artifact | Language | Job |
|---|---|---|
| **Research / infrastructure module** | Python | Surface fitting, Greeks, backtesting, data ingestion, analysis, everything that runs offline or at human speed |
| **Live execution engine** | C++ | The order path. Quote, place, cancel, track fills, keep the ledger. Latency-sensitive, must not depend on Python |

The Python side is where a model is *designed and validated*. The C++ side is where a validated
model is *run against a live book*. Anything that touches a real order lives on the C++ side.

**Design philosophy (D8, decided 2026-08-17).** The data leads, not the model. The module does
not propose a strategy and then tune parameters against data until it looks profitable — that is
the overfitting trap that has caused real trouble before. Instead, exploratory and diagnostic
tooling — surfacing what the data actually shows — is a first-class part of the module, upstream
of any strategy-specific fitting. A strategy is chosen once the data has revealed an opportunity,
not proposed first and then fitted to appear as one.

## 2. The "addable" requirement

Aryan's stated design constraint: the module must be **additive**. New capability arrives as a
self-contained feature that plugs into the existing module without editing the core.

Concretely that means each capability is:

- a directory with its own tests,
- registered through a declared interface (not imported ad hoc by strategy code),
- versioned and independently replaceable,
- documented with what it *is* — observed, derived, estimated, scenario, proxy, or unidentified.

The intended workflow: over a month, build features one at a time; each finished feature is
dropped into the module and is immediately available to every strategy, past and future.

## 3. Intended capability set

Stated so far by Aryan, plus the obvious dependencies each one implies.

### 3.1 Volatility surfaces
- **eSSVI** — arbitrage-free extended SSVI parameterisation
- **SABR**
- **SVI** (raw / natural / jump-wings)
- Shared: no-arbitrage checks (butterfly, calendar), fitting diagnostics, interpolation,
  surface-to-Greeks handoff, surface age / staleness semantics

### 3.2 Market data
- **Dhan** live streaming (ticks, depth, option chain) — the sole data-receive source
  (D7, amended 2026-08-18 by D18: Kotak dropped from data, order-placement only)
- Historical fetch + local storage with a stable on-disk schema
- Snapshot tape recording and deterministic replay

### 3.3 Execution
- **Kotak** order placement, cancellation, order-status and fill polling
- Paper / shadow execution with an explicit, documented fill proxy
- Ledger with a fixed schema, append-only

### 3.4 Shared analytics
- Greeks, realised-volatility estimators, position sizing, risk limits, backtest engine,
  P&L and markout attribution, reporting

## 4. What already exists (do not rebuild these from zero)

Real, working code already scattered across the six strategy repos and the Market Making repo. The
first job of this module is to harvest and consolidate, not to write fresh.

| Capability | Where it lives now | Verification level |
|---|---|---|
| eSSVI surface fit | `../strategy/VOLARB/voltaire/src/models/essvi.py` | Implemented + unit-tested |
| Greeks | `../strategy/VOLARB/voltaire/src/models/greeks.py` | Implemented + unit-tested |
| Realised volatility | `../strategy/VOLARB/voltaire/src/models/realized_volatility.py` | Implemented + unit-tested |
| Option-chain fetch, validation, storage | `../strategy/VOLARB/voltaire/src/data/` | Implemented + unit-tested |
| Backtest engine + analytics | `../strategy/VOLARB/voltaire/src/backtesting/` | Implemented + unit-tested |
| Risk manager, position sizing | `../strategy/VOLARB/voltaire/src/risk/` | Implemented + unit-tested |
| Kite (Zerodha) auth + client | `../strategy/VOLARB/voltaire/src/{auth,data}/` | Implemented |
| Dhan I/O + live feed | `../strategy/Mushin_Gamma/src/mushin_gamma/{dhan_io,feed}.py` | Implemented |
| Dhan client (second implementation) | `../strategy/Shoshin/src/dhan_client.py` | Implemented |
| Live execution / risk / features engine | `../strategy/Still_Water/src/engine/` | Implemented, ran in paper |
| EC2 deploy + systemd runbooks | `../strategy/Still_Water/production_engine/deploy/` | Used in production |
| Data downloader, backtest, reporting | `../strategy/Shoshin/src/` | Implemented + tested |

And, outside Dhandho, the most mature code of all — the Market Making repo at
`/Users/maheit/Documents/Market-Making` (GitHub `ayyararyan/Market-Making`):

| Capability | Where | Verification level |
|---|---|---|
| Kotak session load + REST gateway (C++) | `native/include/shaurya_kotak_session.hpp`, `native/src/shaurya_native.cpp` | **Live-verified read-only against the real broker** |
| Kotak broker adapter (C++) | `native/src/shaurya_kotak_broker_adapter.cpp` | Implemented, paper-tested only |
| Kotak market-data WebSocket + depth (C++) | `native/src/shaurya_kotak_ws_*.cpp`, `shaurya_kotak_depth.cpp` | Implemented + tested — **not harvested into Shaurya** (D18, 2026-08-18: module data ingestion is Dhan-only, Kotak is order-placement only) |
| Order-lifecycle runtime, paper fills, ledger (C++) | `native/src/shaurya_{runtime,paper,ledger}.cpp` | Tested (91 C++ tests) |
| Surface estimation / smoothing / dashboard (Python) | `monday_v1/surface_*.py` | Dry-run + saved-tape verified |
| Kotak Neo client (Python) | `monday_v1/kotak_neo.py` | Live-verified |

**This is the single most important fact about the module:** the C++ live engine does not need
to be invented. It already exists, is tested, and its broker path has been proven against the
real Kotak API. The work is to *generalise* it out of Market-Making-specific assumptions into a
reusable engine, not to start over.

Two non-obvious things learned the hard way in that repo, which the module must preserve:
- Every Kotak POST body must be wrapped as a single `jData=<url-encoded JSON>` form field.
  Individually form-encoded fields fail silently with a 404.
- Kotak's WebSocket is receive-only. Orders are REST. The ~12–15 ms typical round-trip is
  Kotak's backend, not something further engineering can remove.

## 5. Proposed shape

```
shaurya/
├── README.md                     # this file
├── TASKS.md                      # the single task ledger
├── MODULE_SPEC.md                # frozen specification (to be written before implementation)
├── python/
│   ├── pyproject.toml
│   ├── shaurya/
│   │   ├── surfaces/             # essvi, sabr, svi, arbitrage checks
│   │   ├── greeks/
│   │   ├── vol/                  # realised vol, forecasting
│   │   ├── data/                 # dhan, kite, storage, replay tapes
│   │   ├── backtest/
│   │   ├── risk/
│   │   ├── analytics/            # pnl, markout, reporting
│   │   └── registry.py           # the plug-in point for new features
│   └── tests/
├── native/
│   ├── CMakeLists.txt
│   ├── include/ src/             # quoting runtime, broker gateways, ledger
│   └── tests/
├── contracts/                    # shared schemas: tape, ledger, surface, config
└── docs/
```

`contracts/` matters more than it looks. It is the only thing that keeps the Python and C++
sides in agreement — one definition of a snapshot row, a ledger row, a surface frame, a config
file, consumed by both. Without it the two engines drift and parity testing becomes guesswork.

## 6. Working rules for this module

Carried over from the canonical working contract, because a shared module makes violations
expensive — a silent scope reduction here breaks every strategy downstream, not just one.

1. **Nothing enters the module untested.** Harvested code gets tests before it is promoted.
2. **One definition per object.** Two Dhan clients exist today. The module gets exactly one.
3. **Parity is proven, not assumed.** Where Python and C++ implement the same computation,
   there is a numeric parity test, as was done in Market Making (8,640-combination sweep).
4. **Live order paths stay gated.** Paper is the default. Live requires explicit
   per-session authorisation. No exceptions inherited by convenience.
5. **Objects are labelled.** Observed / derived / estimated / scenario / proxy / unidentified.
   A touch-fill proxy is never reported as a realised fill.
6. **Secrets never enter the module tree.** See §8.
7. **Data leads, strategy follows (D8).** Diagnostic and exploratory tooling — surfacing what
   the data shows — is not secondary to strategy-specific fitting; it comes first. A strategy is
   the mechanism chosen to exploit an opportunity the data has already revealed, never a model
   proposed up front and tuned against data until it looks profitable.

## 7. Roadmap

Sequenced so that the earliest steps make later steps cheaper. This is architectural context;
authorisation and live implementation status are recorded only in `TASKS.md`.

**Phase 0 — decide and freeze**
Resolve the open questions in §9, write `MODULE_SPEC.md` with stable requirement IDs, freeze scope.

**Phase 1 — contracts**
Define the shared schemas first: snapshot tape, ledger row, surface frame, config, credential
handle. Everything downstream depends on these being stable.

**Phase 2 — Python core**
Harvest eSSVI, Greeks, realised vol, risk, backtest from VOLARB. Add tests. Then add SVI and
SABR alongside eSSVI behind one common surface interface.

**Phase 3 — data layer**
Reconcile the two Dhan clients into one. Historical fetch, storage, tape recording,
deterministic replay.

**Phase 4 — C++ engine**
Generalise the Market Making native runtime: strategy-agnostic quoting loop, broker interface with
Kotak as the first implementation, ledger, paper/shadow mode. Parity-test against Python.

**Phase 5 — first migration**
Port one existing strategy onto the module end to end. This is the real test of whether the
abstractions hold. Recommend VOLARB, since most of the harvested code came from it.

**Phase 6 — the rest**
Migrate remaining strategies opportunistically, when each is next touched. Not a big-bang rewrite.

## 8. Security note — needs attention before any of this is version-controlled

While surveying the strategy folders, credential-shaped files were found **inside the project
trees**, which means they would be captured by any repository or sync that covers them:

- `../.env` (Dhandho root)
- `../strategy/VOLARB/voltaire/config/` — `.access_token`, `.encryption_key`,
  `credentials.yaml`, `credentials_local.yaml`
- `../strategy/Still_Water/production_engine/{.env, keys/}`
- `../strategy/Seshin_Zen/production_engine/.env`
- `/Users/maheit/Google Drive/My Drive/Market Making/dhan_credentials.env`

Contents were not read or copied. The Market Making repo already solves this correctly — secrets live
outside the tree in `~/Documents/Market-Making-Secrets` at mode `700`/`600`. The module should
adopt the same pattern from day one: a credential *handle* in config, never a credential value,
and no secret file inside the module tree.

## 9. Decisions and open questions

**Decided 2026-08-17 (D1–D7):** the module is named **Shaurya**; the old Shaurya strategy is
renamed **Market Making**; the live engine is **C++**, for speed; the module is **plug-and-play**
and Market Making is refactored to consume it; the name collision is resolved by rename (both
executed); construction does not begin until the component list is agreed; and broker scope is
Dhan-plus-Kotak for data but **Kotak-only for order placement**, routed through a dedicated
latency-sensitive C++ path. **Amended 2026-08-18 (D18):** Kotak dropped as a data-receive
source — market-data ingestion is **Dhan-only**; Kotak remains the sole order-placement broker.

**Still open — one question:** migration ambition (all six old strategies, or leave some frozen
as history) — deliberately deferred, to be decided per strategy when it is next touched.

Full decision log, reasoning, and the executed renames are in
[`TASKS.md`](TASKS.md) §1. That is the status record; this file is not.

---

## 10. Status

Status lives only in [`TASKS.md`](TASKS.md). This README intentionally carries no parallel
task-status summary.
