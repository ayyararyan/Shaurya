# Shaurya contract formats

These JSON contracts are the versioned boundary between Shaurya components. Unknown fields
and unsupported schema versions fail closed. Decimal values serialize as JSON strings so a
future C++ consumer can parse them without binary floating-point reinterpretation.

## Shared labelling (`CON-06`)

Every applicable artifact carries `ObjectLabel` records with a named object, its provenance,
and exactly one category:

- `observed`: present directly in an authoritative source;
- `derived`: computed deterministically from observed data without fitting;
- `estimated`: obtained from a fitted statistical or numerical model;
- `scenario`: computed under an explicit assumption or counterfactual parameter;
- `proxy`: an imperfect observable or simulation standing in for a target;
- `unidentified`: not recoverable without more information or assumptions.

Serialization does not upgrade a category. In particular, an estimate or proxy stored in a
canonical artifact does not become observed.

## Shared time convention (`CON-07`)

`CausalTimestamps` distinguishes `exchange_timestamp`, `receive_timestamp`, and
`decision_timestamp`. All supplied timestamps use `Asia/Kolkata` / UTC+05:30. Exchange time
may be `null` when the source protocol does not carry it. Receive time and every additional
`source_timestamp` must be no later than the decision timestamp; violations are rejected.

## Ledger row (`CON-02`)

`LedgerRow` is one append-only lifecycle event. It reconciles the Market Making Python and
C++ master-ledger columns while using broker-neutral identity names. Event types are
`order_placed`, `order_executed`, `cancel_requested`, `rejected`, and `cycle_complete`.
Event-specific required-field checks cover role, quote/order/fill prices, order age, visible
book state, width multiplier K, break-even spread, quantities, reason, and cycle P&L.

## Surface frame (`CON-03`)

`SurfaceFrame` is model-agnostic: named parameter values support eSSVI, SVI, SABR, or a future
registered parameterisation; named JSON diagnostics carry fit status, goodness-of-fit, and
residual/stability outputs. The frame records its source time, exact age at decision time,
the caller-supplied staleness threshold, and a flag that must agree with that threshold.
Parameters are labelled `estimated`; diagnostics are labelled `derived`.

## Configuration (`CON-04`)

`ShauryaConfig` contains only a config ID, external `CredentialHandle` references, and
unit-explicit `RiskLimitDefinition` entries. No credential value, risk threshold, or trading
default is built into the schema. The same committed JSON fixture is the future C++
acceptance input for INF-03/NAT; this run does not create a native parser before that build
skeleton exists.

## Finding record (`CON-09`)

`FindingRecord` describes what the data shows before a strategy or ledger entry exists. It
contains the measurement window, causal decision timing, named statistic and value,
magnitude and unit, explicit confidence/significance information, search-grid context, and
an object label. A finding window ending after its decision time is rejected.

## Golden fixtures

Canonical examples live under `tests/fixtures/contracts/`. Tests parse each fixture,
serialize it, and parse it again. These fixtures are the cross-language inputs when the C++
contract consumers are added.
