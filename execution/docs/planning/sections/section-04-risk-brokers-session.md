# Section 04 — Deterministic Risk, Broker Adapters, Reconciliation, and Execution Session

## Outcome and boundaries

This section implements the decision-making and broker-facing center of the shadow-safe Shaurya
Execution project. When complete, a syntactically valid broker-neutral intent can be evaluated by a
deterministic default-deny risk engine, routed through a generic broker interface, reflected in the
order state machine and append-only ledger, reconciled against authoritative broker snapshots, and
run inside an `ExecutionSession`. The ordinary build contains a deterministic paper broker and
Kotak request/response fixtures, but no constructible live transport.

The work is additive under `execution/`. Do not modify `data/` or `research/`. Do not authenticate to
Kotak, contact a broker, read credentials, start remote services, or weaken the compile-time live
gate. Dhan-derived `MarketObservation` messages are the sole market observations used by the paper
path. Kotak order, trade, and position messages are execution evidence only.

Prerequisites are the versioned contracts and routing resolver under `execution/contracts/` and
`execution/include/shaurya/execution/`, plus the ledger, replay/idempotency store, and generic order
FSM. Their public types may be used but their implementations are not duplicated here.

## Tests first

Add the tests to CMake/CTest before implementing production behavior. Prefer injected clocks,
immutable fixtures, deterministic UUIDs, and fake transports; no test may open an Internet socket.

### Risk engine tests

Create `execution/tests/test_risk_engine.cpp` and fixtures under
`execution/tests/fixtures/risk/`. Cover each rule independently and then verify the exact combined
precedence defined below:

- place, modify, and cancel happy paths;
- stale, missing, partial, ambiguous, or hash-invalid routing snapshots;
- unsupported action, side, product, TIF, or order type;
- creation after expiry, expiry at the boundary, and expired intent at evaluation time;
- unavailable session, unhealthy broker, stale observation, invalid quality flags, and clock skew;
- nonpositive quantity, quantity not divisible by lot size, price overflow, and off-tick price;
- per-order quantity, projected exact-instrument position, gross premium, outstanding-order, and
  order-rate limits;
- projected exposure including all working and partially filled orders rather than filled position
  alone;
- exact-token SELL availability: inventory in one option token must not authorize another token;
- enabled delta/gamma/vega limits, missing or stale Greek inputs, and explicitly disabled Greek
  rules;
- daily loss and drawdown at, below, and above their integer-paise boundaries;
- kill switch, reconciliation-required state, duplicate intent, and same-ID/conflicting-payload
  incident;
- deterministic rule order and identical `RiskDecision` bytes for identical immutable inputs;
- a `RiskDecision` and corresponding ledger event for every accepted or rejected parsed intent;
- cancel as a risk-reducing path: a valid known target remains cancellable during a kill or stale
  market-data condition, while place and modify remain blocked.

The test must prove that a rejection never calls a broker mutation and that all before/projected
limits and freshness inputs recorded in `RiskDecision` are the exact values used by the decision.

### Paper broker tests

Create `execution/tests/test_paper_broker.cpp` with canonical observation and broker transcript
fixtures under `execution/tests/fixtures/paper/`. Test:

- deterministic place acknowledgement, modify, cancel, repeated cancel, and unknown target refusal;
- the `d51_proxy_v1` fill model described below for bid/ask crossing and qualifying post-placement
  trade evidence;
- stale last trade, unchanged cumulative volume, volume reset, invalid observation, tied timestamps,
  and observations preceding placement;
- explicit simulated/proxy provenance on every acknowledgement, fill, position, and query result;
- full fills under `d51_proxy_v1` and scripted partial/final fills under the deterministic
  `scripted_v1` fixture model;
- cumulative-fill monotonicity, duplicate scripted updates, rejects, cancel/fill races, and terminal
  behavior;
- query-orders, query-trades/fills, query-positions, and session-health snapshots;
- restart from an immutable fixture snapshot and exact replay/reconciliation results.

Paper events must never contain `broker_confirmed=true`, a real Kotak order ID, or any wording that
could be mistaken for live evidence.

### Dormant Kotak adapter tests

Create `execution/tests/test_kotak_adapter_fixtures.cpp` and sanitized fixtures under
`execution/tests/fixtures/kotak/`. Cover request construction and response/update parsing for place,
modify, cancel, ACK, partial fill, complete fill, cancellation, rejection, malformed bodies, HTTP
failures, duplicate updates, out-of-order updates, queue overflow, and session loss. Assert:

- regular LIMIT, `NRML`, and `DAY` are the only encodable initial order settings;
- broker token, segment, and trading symbol come only from the validated routing result;
- errors expose a bounded category, HTTP status, and correlation ID but never response bodies,
  headers, URLs containing query data, session fields, or tokens;
- the ordinary target has no network transport factory or link path;
- configuring live mode or `SHAURYA_ENABLE_KOTAK_LIVE=ON` fails before any network-capable object is
  created;
- environment variables and misspelled configuration fields cannot override the compile gate.

### Reconciliation and session tests

Create `execution/tests/test_reconciliation.cpp` and `execution/tests/test_execution_session.cpp`.
Test exact startup agreement and every mismatch class for replayed versus broker-authoritative
orders, trades/fills, and positions: missing, extra, duplicate, changed quantity, changed terminal
state, unknown instrument, and unavailable query. Also cover:

- readiness only after routing validation, ledger replay, all three broker queries, and exact
  reconciliation;
- `PositionSnapshot` retaining strategy-desired, ledger-reconstructed, and broker-authoritative
  quantities as distinct values per canonical instrument;
- append-only reconciliation/correction events with no historical ledger rewrite;
- crash recovery before submission, after durable `submission_started`, after broker return, and
  before ACK persistence;
- ledger failure immediately before a broker call sends NO ORDER;
- ledger failure after a broker attempt yields `ambiguous_submission`, safety stop, reconciliation
  requirement, and no retry after timeout or restart;
- order-update queue overflow and broker/session loss producing a deterministic safety stop;
- kill-switch activation, orderly shutdown, and factual cancel-all results for every known working
  order, including failures and unknown outcomes;
- shutdown never swallowing a cancel failure and never clearing uncertain working state;
- no new place/modify authority after any ledger, broker, or reconciliation mismatch.

Use a recording fake ledger and recording fake broker to assert this mandatory sequence for every
mutation: durable `intent_received`, mapping result, durable `RiskDecision`, durable
`submission_started`, exactly one broker attempt, then durable ACK/REJECT or
`ambiguous_submission`.

## Files and interfaces

Create the following production files, adjusting only namespacing boilerplate to the project’s
established convention:

- `execution/include/shaurya/execution/risk.hpp`
- `execution/src/risk.cpp`
- `execution/include/shaurya/execution/broker_adapter.hpp`
- `execution/include/shaurya/execution/paper_broker.hpp`
- `execution/src/paper_broker.cpp`
- `execution/include/shaurya/execution/kotak_adapter.hpp`
- `execution/src/kotak_adapter.cpp`
- `execution/include/shaurya/execution/reconciliation.hpp`
- `execution/src/reconciliation.cpp`
- `execution/include/shaurya/execution/execution_session.hpp`
- `execution/src/execution_session.cpp`

Update `execution/CMakeLists.txt` to build these files and register the four CTest executables. The
ordinary library must compile with a public `SHAURYA_ENABLE_KOTAK_LIVE=0` definition. The protected
project must refuse a request to enable it; do not add a hidden secondary option.

The public API should expose interfaces equivalent in responsibility to:

- `RiskEngine::evaluate(intent, immutable_snapshot) -> RiskDecision`;
- `BrokerAdapter::{place, modify, cancel, query_orders, query_trades, query_positions,
  session_health}`;
- `Reconciler::compare(replayed_state, broker_snapshot) -> ReconciliationResult`;
- `ExecutionSession::{start, accept_observation, accept_intent, accept_broker_update,
  activate_kill_switch, stop}`.

Use value types and injected interfaces for clock, ledger, resolver, and broker dependencies. Do not
place credentials, broker URLs, tokens, or mutable global state in any shared contract.

## Deterministic risk model

Define a strict, versioned non-secret risk configuration. It must carry a schema version, immutable
configuration version/digest, trading date, observation and Greek freshness limits, maximum order
quantity, per-instrument position, gross premium exposure, outstanding orders, order rate and
window, daily loss, drawdown, and optional delta/gamma/vega caps. Limits use signed 64-bit integer
paise or explicitly scaled signed 64-bit Greek units; floating-point values must not enter an
approval decision. Reject unknown, missing, duplicate, negative, or overflowing configuration
fields.

Evaluate place and modify intents in this fixed order:

1. kill switch and reconciliation/readiness state;
2. idempotency status and intent/session/run correlation;
3. current, verified routing mapping and trading date;
4. closed contract allowlist (`LIMIT`, `NRML`, `DAY`) and action shape;
5. creation/expiry and bounded clock-skew checks;
6. broker/session health;
7. observation provenance, quality, and receive/exchange freshness;
8. exact tick, lot, quantity, and per-order size;
9. outstanding-order count and rate window;
10. projected exact-instrument position and exact-token SELL availability;
11. projected gross premium exposure including working remainder;
12. enabled Greek limits, requiring fresh supplied values when enabled;
13. daily loss and drawdown.

Stop at the first rejecting rule, but record all immutable inputs, the ordered rules reached, the
before/projected values, data/session ages, configuration version, and stable rejection code.
Cancels follow a separate risk-reducing path: validate correlation, idempotency, known nonterminal
target, session ability, and quantity already filled; do not require fresh market observations or
unused exposure capacity. If transport health is unknown, approve only a reconciliation-required
cancel attempt and retain uncertainty until query evidence resolves it.

Each decision is a pure function of its arguments. The session captures one immutable snapshot at
intent receipt so concurrent observations or fills cannot change inputs midway through evaluation.

## Broker abstractions and paper behavior

`BrokerAdapter` is generic and keyed by stable internal order ID plus canonical instrument ID.
Mutation results distinguish acknowledged, rejected, and ambiguous; an exception or timeout is not
equivalent to rejection. Query results distinguish authoritative success from unavailable or
partial evidence. Session health distinguishes ready, degraded, lost, and unknown.

Implement two paper models selected by an exact enum in shadow configuration:

- `d51_proxy_v1` preserves the legacy conservative semantics used for parity. A working BUY fills
  completely when a later valid ask is at or below its limit, or a later last trade is at or below
  the limit and cumulative volume advanced after placement. SELL is symmetric using bid at or above
  the limit or a qualifying later trade at or above it. Evidence at or before placement, stale
  observations, or volume resets cannot fill. Fill price is the submitted limit, and evidence is
  labelled `simulated_proxy`.
- `scripted_v1` exists for deterministic state-machine and reconciliation fixtures. It consumes a
  predefined transcript and can produce partial fills, duplicates, reordering, rejection, session
  loss, and ambiguity. It must never be selectable from a normal operator shadow manifest.

Paper place, modify, and cancel operations produce stable synthetic broker correlation IDs derived
from session sequence, not random or Kotak-shaped IDs. Broker state is queryable and deterministic.
No paper component may construct an HTTP client or import Kotak transport code.

The dormant Kotak adapter contains only strict request builders and parsers required by fixtures.
It converts already-resolved routing details at the final adapter boundary. Preserve current
endpoint/header/rate/static-IP verification, real-account update capture, startup reconciliation,
exact-token SELL checks, cancel-race validation, and contract-note reconciliation as explicit live
blockers; do not encode unverified provider behavior as a completed guarantee.

## Position authority and reconciliation

Maintain three quantities for every canonical instrument:

- strategy-desired position, reported by the strategy and never treated as execution evidence;
- ledger-reconstructed position, calculated from accepted execution events;
- broker-authoritative position, returned by the active broker adapter.

Reconciliation compares complete order, trade/fill, and position sets, including absence. Exact
agreement is required; an empty or unavailable query is not agreement unless the adapter explicitly
attests an authoritative empty result. Any mismatch emits a reconciliation incident, activates the
safety stop, preserves all three snapshots, and blocks place/modify. Corrections are new ledger
events applied by replay; prior records are never edited.

For the paper broker, startup state comes from a deterministic snapshot fixture or its reconstructed
in-memory state. For the dormant Kotak adapter, define the required query response contracts but use
only sanitized fixtures. A start-flat acknowledgement is never accepted as reconciliation.

## ExecutionSession orchestration

`ExecutionSession::start` validates configuration and routing, opens and verifies the ledger,
replays state, obtains authoritative broker orders/trades/positions, reconciles them, and becomes
ready only after exact agreement. It then accepts fresh Dhan-derived observations and parsed
strategy intents. It does not acquire market data, authenticate, launch strategies, or manage AWS.

For an intent, the session owns correlation, idempotency, immutable risk snapshot capture, ledger
ordering, resolver invocation, broker mutation, FSM updates, and outward events. A malformed wire
message is rejected by the contract/IPC layer; a parsed but semantically refused intent receives a
`RiskDecision` and `risk_rejected` event. Duplicate same-ID/same-fingerprint requests replay their
recorded outcome without another broker call. Same-ID/different-fingerprint requests are incidents.

Shutdown first revokes new place/modify authority, records `session_stopping`, attempts cancellation
of each nonterminal working order once subject to the rate limiter, records a factual outcome per
order, reconciles, flushes the ledger, and records `session_stopped` only if that record is durable.
Unknown cancellation outcomes remain uncertain; they are never converted to cancelled locally.

## Completion evidence

This section is complete only when all new CTests pass in an ordinary Release build, the live-enable
negative configure test passes, source and fixture scans find no response-body logging or secret
fields, and no network endpoint was contacted. Record exact test counts and skipped live validation
for the final integration report.
