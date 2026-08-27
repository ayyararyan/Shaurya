# Section 02 — Strict wire contracts, conformance corpus, and routing snapshot

## Outcome

Implement broker-neutral, schema-versioned contracts shared by the C++ executor and non-C++
clients, plus the only permitted Data-to-Execution seam: an offline Execution-owned exporter that
turns existing public instrument mappings into a deterministic, hash-bound routing snapshot. The
runtime consumes that snapshot read-only and returns `NO ORDER` whenever identity or integrity
cannot be proven.

This section must make no change under `data/` or `research/`, must not import a Dhan or Kotak
transport, and must not make network calls. It depends on Section 01's CMake project, live-negative
gate, frozen authority graph, and test harness. Sections 03–05 and 07 consume these contracts and
must not redefine their wire meaning.

## Tests first

### Test and fixture files to create

- `execution/tests/contracts/contracts_test.cpp`
- `execution/tests/contracts/canonical_json_test.cpp`
- `execution/tests/routing/instrument_resolver_test.cpp`
- `execution/tests/routing/test_routing_exporter.py`
- `execution/contracts/fixtures/v1/valid/`
- `execution/contracts/fixtures/v1/invalid/`
- `execution/contracts/fixtures/v1/golden/`
- `execution/tests/fixtures/routing/`

All conformance fixtures are small, synthetic, non-secret, and frozen. Every fixture has a manifest
entry naming its expected result or stable error code. Duplicate-key invalid fixtures must be raw
JSON bytes, because loading and reserializing them in a permissive parser would erase the defect.

### Contract tests

Write the tests before codecs and domain types. For each of `OrderIntent`, `ExecutionEvent`,
`RiskDecision`, `PositionSnapshot`, and `MarketObservation`, cover:

1. valid parse, canonical serialize, parse-again equality, and byte-identical golden output;
2. rejection of unknown, duplicate, and missing fields;
3. rejection of unsupported schema versions and enum values;
4. rejection of malformed or non-lowercase canonical UUIDs;
5. signed/unsigned overflow, non-integral JSON numbers, floats where integers are required, and
   booleans masquerading as integers;
6. timestamps outside signed 64-bit UTC Unix-nanosecond range and expiry not later than creation;
7. invalid canonical instrument strings, blank identifiers/tags, oversized strings, excessive
   arrays/maps, embedded NUL/control characters, and packets above the contract byte bound;
8. exact action rules for place, modify, and cancel;
9. price/tick and quantity/lot boundary values without binary floating-point conversion;
10. canonical serialization independent of source key order and insignificant input whitespace.

`OrderIntent` action matrices must assert:

- `place` requires side, positive exchange-unit quantity, positive integer `limit_price_paise`,
  product `NRML`, TIF `DAY`, and forbids a target internal order ID;
- `modify` requires those same order terms plus `target_internal_order_id`;
- `cancel` requires the correlation fields, canonical instrument, and target internal order ID, and
  forbids side, quantity, limit price, product, and TIF;
- every action carries creation/expiry times and expiry is strictly later;
- no contract accepts a broker token, broker URL, credential, TOTP, access token, session token, or
  free-form transport body.

Fingerprint golden tests must prove:

- the same semantic intent and intent ID yield the same fingerprint after key reordering;
- transport envelope metadata is not part of the fingerprint;
- `intent_id` is the idempotency key and is excluded from the semantic-payload digest used to
  compare conflicts;
- the same ID with one semantic field changed is a conflict;
- identical semantic payload under a different ID is a new intent, not a duplicate.

### Routing exporter and resolver tests

Start with synthetic same-date NIFTY future and option masters that resolve to the existing
canonical identities. Then cover:

1. deterministic export: repeated runs with identical inputs produce byte-identical snapshot and
   manifest files;
2. requested-universe completeness: every requested canonical ID has exactly one Dhan metadata row
   and one Kotak route, and no unrequested route leaks into the output;
3. stale Dhan mapping, stale Kotak mapping, trading-date mismatch, and expiry-roll mismatch;
4. duplicate canonical ID, Dhan security ID, Kotak token, or route tuple;
5. missing Dhan or Kotak side of the join and multiple plausible matches;
6. malformed master columns/rows, unsupported instrument class, invalid expiry, option side,
   strike, lot, tick, token, segment, or trading symbol;
7. partial output pair, pre-existing output, symlink/path traversal, and unsafe file mode;
8. snapshot byte tampering, manifest tampering, wrong digest/length/count/date/version, and renamed or
   substituted snapshot;
9. C++ lookup by canonical ID and by exact Kotak token where required by reconciliation;
10. missing/unverifiable lookup returns a typed `NO_ORDER` refusal and never invents a token,
    trading symbol, segment, tick, or lot;
11. exporter import scan allows Data public facades only and rejects Dhan/Kotak network adapters;
12. a broker-spy integration seam receives zero calls for every exporter/resolver refusal.

Run focused tests from external build and cache locations:

```bash
cmake --build /private/tmp/shaurya-execution-build --parallel
ctest --test-dir /private/tmp/shaurya-execution-build \
  --output-on-failure -R 'contracts|canonical_json|routing'
PYTHONDONTWRITEBYTECODE=1 \
UV_CACHE_DIR=/private/tmp/shaurya-execution-uv-cache \
UV_PROJECT_ENVIRONMENT=/private/tmp/shaurya-execution-routing-venv \
uv run --project execution --frozen pytest -q execution/tests/routing/test_routing_exporter.py
```

If Execution uses no Python project metadata, run the standard-library exporter test with the
declared Python interpreter and explicit `PYTHONPATH` for `data/src`; do not create an in-repository
virtual environment or modify Data packaging merely to run the exporter.

## Contract source layout

Create:

- `execution/contracts/v1/order_intent.schema.json`
- `execution/contracts/v1/execution_event.schema.json`
- `execution/contracts/v1/risk_decision.schema.json`
- `execution/contracts/v1/position_snapshot.schema.json`
- `execution/contracts/v1/market_observation.schema.json`
- `execution/contracts/v1/error_codes.md`
- `execution/include/shaurya/execution/contracts.hpp`
- `execution/include/shaurya/execution/canonical_json.hpp`
- `execution/src/contracts.cpp`
- `execution/src/canonical_json.cpp`
- `execution/docs/CONTRACTS.md`

JSON Schema files are documentation/conformance artifacts, not the sole validator. The C++ parser
must enforce the same rules directly, including duplicate-key rejection before object materialization.
Use an offline, repository-pinned JSON dependency with its license tracked, or a predeclared system
dependency validated at configure time; build and tests must never download it.

Set common bounds centrally and document them: maximum packet/record bytes, maximum identifier and
tag lengths, maximum rule/quality-flag counts, and maximum payload nesting. Every decoder consumes a
byte span with a bound, reports a stable non-secret error code, and returns no partially valid domain
object. Do not include the rejected raw document in errors.

## Common wire rules

- Schema version is the literal `1.0.0`; unsupported versions fail closed.
- All identifiers are nonempty ASCII within declared bounds.
- Intent, event, execution-session, strategy-run, and internal-order IDs use lowercase canonical
  UUID text (`8-4-4-4-12`) and reject braces, uppercase, compact, or whitespace-padded forms.
- `strategy_id` and optional `strategy_tag` use a conservative documented ASCII allowlist.
- Time is UTC Unix nanoseconds encoded as a JSON integer within signed 64-bit range. No local time,
  floating seconds, or timezone string appears on the wire.
- Prices are positive integer paise. Quantities are positive integer exchange units. Cumulative
  volumes and fills are bounded nonnegative integers. Binary floating point is forbidden.
- Canonical instrument ID syntax is exactly the existing Data representation:
  `EXCHANGE:SEGMENT:UNDERLYING:kind[:YYYY-MM-DD][:normalized-strike][:CE|PE]`.
  The initial resolver accepts NSE index futures/options (`NSE_FNO`) only; broader classes require a
  later version rather than an implicit parser expansion.
- Canonical JSON uses UTF-8, no BOM, lexicographically sorted object keys, minimal separators, and a
  single normalized representation for strings, integers, arrays, and null. Hashes use the exact
  canonical UTF-8 bytes.
- Unknown fields, duplicate fields, invalid UTF-8, nonfinite/floating numbers, and implicit type
  coercions are rejected.

## `OrderIntent` v1

Fields and meaning:

| Field | Rule |
|---|---|
| `schema_version` | Literal `1.0.0` |
| `intent_id` | Unique lowercase UUID idempotency key |
| `strategy_id` | Stable non-broker strategy identifier |
| `strategy_run_id` | Lowercase UUID for one strategy run |
| `execution_session_id` | Lowercase UUID matching the accepting session |
| `created_at_ns` | UTC Unix nanoseconds |
| `expires_at_ns` | Strictly greater than creation |
| `canonical_instrument_id` | Broker-neutral identity |
| `action` | `place`, `modify`, or `cancel` |
| `side` | `BUY` or `SELL` when required; absent for cancel |
| `quantity` | Positive exchange units when required; absent for cancel |
| `limit_price_paise` | Positive integer paise when required; absent for cancel |
| `product` | Literal `NRML` when required; absent for cancel |
| `time_in_force` | Literal `DAY` when required; absent for cancel |
| `target_internal_order_id` | Required for modify/cancel, forbidden for place |
| `strategy_tag` | Optional bounded attribution, never a routing or credential field |

The semantic fingerprint is SHA-256 over canonical JSON of every semantic field except
`intent_id`. Transport arrival time, peer credentials, retry count, and framing metadata live in the
transport envelope and are never fingerprint inputs. Idempotency behavior itself is implemented in
Section 03.

## `ExecutionEvent` v1

Require `schema_version`, `event_id`, `event_type`, `timestamp_ns`, `execution_session_id`, and the
applicable strategy/run/intent/internal-order correlation IDs. Optional correlation fields must be
explicitly absent or null according to each event variant; do not accept arbitrary missing context.
Define closed variants for:

- intent received;
- mapping validated/refused;
- risk approved/rejected;
- submission started;
- broker acknowledged/rejected;
- partially filled/filled;
- cancel requested/cancelled;
- ambiguous submission;
- reconciliation required/completed;
- safety stop;
- session started/stopped.

Broker evidence may include bounded sanitized broker order/update identifiers, exact token, prices,
quantities, and a provenance enum. It may not contain credentials, authentication URLs, raw HTTP
bodies, headers, cookies, or session material. Paper events carry provenance `simulated` or `proxy`;
only future live broker evidence may use `broker_confirmed`.

## `RiskDecision` v1

Require intent ID, decision ID, decision (`approved` or `rejected`), timestamp, exact rule-set
version, configuration digest, ordered `rules_checked`, explicit rejection code/reason, immutable
limits-before and projected-after values, mapping/market/session freshness inputs, and every
deterministic input required for replay. Rule values use typed integer/unit-bearing entries rather
than free-form floating maps. Approved decisions have no rejection reason; rejected decisions name
the first failing rule according to the frozen precedence while retaining outcomes for all rules
that were actually evaluated. Section 04 owns rule evaluation, but may not alter this wire shape.

## `PositionSnapshot` v1

For each canonical instrument and exact resolved broker token, keep three quantities separate:

- strategy-desired position;
- ledger-reconstructed position;
- broker-authoritative position.

Also carry snapshot/session IDs, timestamp, source/provenance, and reconciliation status. A missing
broker quantity is `unknown`, not zero. Do not combine the three meanings into one net field. Section
04 defines readiness and reconciliation from this contract.

## `MarketObservation` v1

Carry only what deterministic paper fill and freshness checks require: canonical instrument ID,
optional best bid/ask and last-trade prices in paise, cumulative volume, exchange and receive UTC
nanoseconds, source, provenance, and a closed set of quality flags. Require receive time; express an
unavailable exchange time explicitly. Enforce non-crossed positive quotes unless a quality flag
explicitly marks the observation unusable. This is aggregate/event-driven market evidence, not
order-by-order data: it carries no inferred order ID, queue priority, or add/modify/cancel event.

## Routing exporter

Create:

- `execution/ops/export_routing_snapshot.py`
- `execution/ops/routing_snapshot_schema_v1.json`
- `execution/ops/routing_manifest_schema_v1.json`
- `execution/docs/ROUTING_SNAPSHOTS.md`

The exporter is offline and receives explicit paths for a dated Dhan master, dated Kotak master,
requested-universe file, output snapshot, output manifest, and exact trading date. It imports only
public symbols exposed by `shaurya.contracts` and `shaurya.data`; it must not import Dhan clients,
streams, credentials, capture code, HTTP helpers, or Research.

For every requested canonical ID:

1. parse both masters with the explicit trading date rather than filesystem mtime;
2. construct the existing same-day indexes;
3. require exactly one Kotak route and exactly one Dhan metadata mapping;
4. require canonical identity equality and supported NSE index future/option kind;
5. require positive integral lot size and positive integral tick size in paise;
6. retain Kotak token, Kotak exchange segment, trading symbol, lot, tick, and source provenance;
7. reject the whole export on any missing, duplicate, ambiguous, stale, or malformed item.

Do not guess from trading symbols, nearest expiry, strike proximity, filesystem date, or token
shape. Sort records by canonical ID and define duplicate checks over canonical ID, Kotak token, and
the `(segment, trading_symbol)` route tuple.

The snapshot contains schema version, trading date, normalized source provenance with input SHA-256
digests, requested-universe digest, and the sorted routing records. Avoid nondeterministic current
timestamps and absolute personal paths. The manifest contains its own version, fixed snapshot file
name, trading date, SHA-256, byte length, record count, exporter version, and source digests.

Write the snapshot and manifest to same-directory temporary files, flush/fsync, validate them by
reading back, and install without overwrite. Refuse when only one target exists, either target is a
symlink, the parent is unsafe, or an existing pair differs. Runtime products live outside Git and
use `0600` files in a `0700` directory.

## C++ resolver

Create:

- `execution/include/shaurya/execution/instrument_resolver.hpp`
- `execution/src/instrument_resolver.cpp`
- `execution/include/shaurya/execution/routing_snapshot.hpp`
- `execution/src/routing_snapshot.cpp`

The loader takes explicit snapshot path, manifest path, and expected trading date. Before exposing
any record it validates file type/ownership policy, bounded size, strict manifest schema, file name,
date, byte length, SHA-256, strict snapshot schema, provenance, record count, sorted order, supported
instrument syntax, positive lot/tick, and all uniqueness constraints. It must retain the verified
snapshot digest in memory so risk and ledger events can bind decisions to the exact route set.

Expose read-only operations conceptually equivalent to:

```text
load(snapshot, manifest, expected_date) -> Resolver | RoutingError
resolve(canonical_instrument_id) -> RoutingRecord | NoOrderReason
resolve_token(exact_kotak_token) -> RoutingRecord | NoOrderReason
snapshot_digest() -> Sha256
```

Stable refusal codes must distinguish stale, missing, malformed, duplicate, partial, tampered,
unsupported, and not-found cases, but all are operationally `NO ORDER`. Do not return partial route
data on failure. The resolver contains no broker client and cannot submit anything.

## Completion criteria

This section is complete only when all contract and routing tests pass; valid fixtures round-trip
byte-identically; every invalid fixture fails with its expected non-secret code; exporter output is
reproducible and tamper-evident; resolver refusals make zero broker calls; the default build still
attests `live_router=off`; and this audit is empty:

```bash
git diff --name-only bcb6dea02329f824c82488f29450af0dd0e826ca -- data research
```
