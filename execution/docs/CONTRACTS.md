# Execution wire contracts

Shaurya Execution v1 uses broker-neutral, strict JSON contracts documented by the five schemas in
`execution/contracts/v1/`. The C++ codec is authoritative at runtime; schemas and fixtures are
portable conformance artifacts, not a substitute for duplicate-key and semantic validation.

## Canonical encoding

- Version is exactly `1.0.0`; object fields are closed and duplicate keys are rejected before
  materialization.
- JSON is UTF-8 with lexicographically ordered object keys, compact separators, deterministic string
  escapes, and integers only. Floating-point JSON numbers are not accepted.
- UUIDs are lowercase canonical text. Timestamps are signed 64-bit UTC Unix nanoseconds. Prices are
  positive integer paise and quantities are positive integer exchange units.
- SHA-256 hashes bind the exact canonical UTF-8 bytes.
- Inputs are bounded to one MiB, nesting to 32 levels, and aggregate array/object membership to
  4,096 entries.

## Canonical instruments

The initial execution boundary accepts NSE index futures and options in the existing Data identity
form:

```text
NSE:NSE_FNO:<UPPERCASE_UNDERLYING>:future:YYYY-MM-DD
NSE:NSE_FNO:<UPPERCASE_UNDERLYING>:option:YYYY-MM-DD:<STRIKE>:CE|PE
```

Strike is positive normalized decimal text. Integer strikes such as `25000` are canonical. A
fractional strike such as `25000.5` is canonical; leading zeros, an empty fraction, repeated decimal
points, or trailing fractional zeros such as `25000.50` are rejected.

## Contract roles

- `OrderIntent` is broker-neutral. Place and modify carry BUY/SELL, quantity, paise limit, `NRML`,
  and `DAY`; modify also targets an internal order UUID. Cancel carries the target and forbids order
  terms. Its semantic fingerprint excludes only `intent_id`.
- `ExecutionEvent` is a closed event union with stable session/order correlation. Its bounded
  payload rejects secret-shaped keys and never contains raw broker transport data.
- `RiskDecision` records a versioned ordered rule evaluation using unit-labelled integer values and
  an exact configuration digest.
- `PositionSnapshot` keeps strategy-desired, ledger-reconstructed, and broker-authoritative
  quantities distinct. Unknown broker quantity is null, never zero.
- `MarketObservation` contains only aggregate observed/proxy data needed for freshness and paper
  fills. It has no order ID, queue priority, or inferred add/modify/cancel semantics.

## Conformance corpus

`execution/contracts/fixtures/v1/manifest.json` enumerates valid, golden, and invalid raw JSON
fixtures and the expected stable error for every invalid case. `execution.contracts` reads this
manifest from the source tree through a CMake-provided compile definition, round-trips every valid
contract, compares golden bytes, and rejects invalid raw inputs without preprocessing.

Routing snapshots are separately date-, provenance-, universe-, length-, filename-, and SHA-256
bound. Both snapshot and manifest must be regular files owned by the effective process user with no
group/other permission bits. Any resolver error means `NO ORDER`; the resolver never guesses.
