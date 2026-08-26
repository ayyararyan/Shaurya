# Shaurya module specification

- **Owner:** Aryan Ayyar
- **Scope authority:** `TASKS.md` decisions D1–D43 and all non-dropped stable task IDs
- **Form:** index plus one specification per frozen component

## Module objective

Shaurya is Aryan Ayyar's reusable Python and C++ trading-infrastructure dependency: shared market data, contracts, research measurement, signal validation, backtesting, execution, risk, analytics, and native runtime are built and tested once so strategies contain only their novel logic. Python owns research and human-speed infrastructure; the latency-sensitive live-order path is authoritative in C++. Every important object remains labelled observed, deterministically derived, estimated, scenario, proxy, or unidentified.

## Architecture at a glance

- **Foundation:** INF supplies packaging, builds, tests, releases, and security; CON supplies the versioned schemas and semantic conventions both languages share.
- **Data access plane:** DAT is the only component allowed to reach Dhan. It owns acquisition,
  permanent raw storage, integrity/indexing, catalogue lookup and replay/follow. Every consumer
  submits a `CON-10` dataset request and receives a DAT dataset handle; compatible active data is
  reused rather than fetched again (D43).
- **Data-to-strategy pipeline:** DAT → SIG → BKT → ANL records/replays market data, discovers and validates interpretable opportunities, tests them with realistic execution, and attributes outcomes. SUR, GRK and VOL also consume DAT handles; none owns broker transport.
- **Live path:** EXE → RSK → NAT supplies the Kotak-only order interface and lifecycle, the non-bypassable account-level C++ risk gate, and the authoritative native runtime/replay.
- **Options and volatility infrastructure:** SUR → GRK → VOL fits and validates surfaces, produces surface-consistent pricing/Greeks, and measures/forecasts realised volatility.
- **Adoption:** MIG moves Market Making onto Shaurya and leaves all other migration choices explicit and per-strategy.

## Dependency rule

D5 is absolute: **strategies import and pin Shaurya; Shaurya never imports a strategy.** Shaurya is a dependency, not a template, fork, or copied codebase. Strategy-specific behaviour remains in the strategy, and Market Making receives the live path by consuming Shaurya rather than by hosting an interim implementation.

D43 is equally absolute inside Shaurya: **components request data from DAT; they do not request it
from Dhan.** Broker credentials/adapters/sockets and raw tape lifecycle terminate at DAT. The
consumer-facing boundary is `DatasetRequest` → `DatasetHandle` → DAT replay/follow rows. A raw
path may be adopted for legacy evidence, but it is opened and validated by DAT rather than parsed
inside SUR, SIG, VOL, BKT or ANL.

## Component specifications

- [INF — Foundations](docs/module-spec/INF.md): standalone packaging, builds, tests, releases, dependency enforcement, and secret safety.
- [CON — Shared contracts](docs/module-spec/CON.md): canonical tape, dataset request/handle, ledger, surface, config, identity, time, manifest, label, and finding schemas.
- [SUR — Volatility surfaces](docs/module-spec/SUR.md): common surface interface, eSSVI, arbitrage checks, diagnostics, staleness, and deferred SVI/SABR.
- [GRK — Pricing and Greeks](docs/module-spec/GRK.md): European pricing internals, parity forwards, robust IV inversion, and surface-consistent Greeks.
- [VOL — Realised volatility and forecasting](docs/module-spec/VOL.md): full estimator toolkit, OOS forecasts, HMM regimes, and RV–IV findings.
- [DAT — Market data](docs/module-spec/DAT.md): sole Dhan access, shared dataset catalogue, live/historical acquisition, lossless storage, indexed retrieval, canonical replay/follow, quality, identity, depth tiers, and capacity evidence.
- [EXE — Execution and brokers](docs/module-spec/EXE.md): broker interface, Kotak execution, lifecycle, ledger, live gates, and labelled queue-reactive fills.
- [SIG — Signal research and validation](docs/module-spec/SIG.md): feature/target registries, dependence-aware inference, selection, coverage, and economic promotion gates.
- [RSK — Risk](docs/module-spec/RSK.md): authoritative C++ pre-trade limits, account aggregation, kill switch, sizing, margin split, and parity.
- [BKT — Backtesting](docs/module-spec/BKT.md): same-tape event replay, measured latency, shared execution realism, walk-forward evaluation, and C++ authority.
- [ANL — Analytics and reporting](docs/module-spec/ANL.md): decomposed P&L, markouts, run/day reports, read-only dashboards, and alerts.
- [NAT — Native live engine](docs/module-spec/NAT.md): strategy-agnostic C++ runtime, Kotak live wiring, deterministic replay, lifecycle semantics, parity, and deployment.
- [MIG — Strategy migration](docs/module-spec/MIG.md): required Market Making migration and explicit per-strategy deferral for the six pre-existing strategies.

## How to read traceability

Each component file contains a requirement table. `REQ-<component>-<nn>` is the specification requirement corresponding to the stable `<component>-<nn>` row in `TASKS.md`; the trace column names that task and any binding decision. Code, test, and output columns identify the intended verification surface. `TBD` is a target placeholder, not an implementation claim. Dropped task IDs remain in `TASKS.md` but intentionally have no requirement. The 13 files collectively cover every non-dropped stable task ID exactly once.

`TASKS.md` remains the sole status ledger. These specifications define required meaning and acceptance; they do not upgrade implementation or verification status.
