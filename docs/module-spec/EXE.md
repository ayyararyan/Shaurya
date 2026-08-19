# EXE — Execution and brokers

## Objective

Provide one broker-shaped execution interface, a Kotak-only live implementation, a rigorous paper broker, an append-only ledger, and non-bypassable live safety gates. All real-order actions occur on the dedicated C++ path (D4, D7).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Kotak acknowledgements, order status, fills, positions, and limits | Observed | Observed broker reports; lifecycle races remain visible. |
| Canonical order/ledger state | Deterministically derived from observed events | Must preserve partial fills, cancel races, late fills, rejects, and residual exits. |
| Queue-state intensities | Estimated | Fitted from canonical depth/event data. |
| Own queue-ahead | Estimated, with reported bounds | Exact displayed quantity at acceptance; bounded thereafter from trades, aggregate cancellations, level size and order counts under D23. |
| Paper/backtest fill | Proxy | Never relabelled as realised execution. It inherits the queue-ahead estimate and both bounds. |
| Anonymous-order rank, cancellation position, hidden quantity and individual-order history | Unidentified | No Dhan order IDs/hidden depth; EXE cannot silently manufacture them. |

## Architecture and contracts

- `CON-01` supplies canonical depth/events to the shared fill model.
- `CON-02` is the append-only order ledger written by EXE and consumed by ANL/BKT parity.
- `CON-04` supplies shared configuration and paper/live mode settings.
- `CON-06` carries queue-ahead point estimates, bounds and proxy labels through simulated fills.
- The broker interface is mirrored for research/testing, but the authoritative live-order implementation is C++. Python cannot place or authorise a live order.
- Kotak is the sole execution broker. Orders use REST; Kotak WebSocket is receive-only. Every POST body is one `jData=<url-encoded JSON>` form field.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-EXE-01 | Define broker-shaped place/cancel/modify/status/fills/positions/limits interfaces in Python and C++ without Kotak-hardcoded domain logic. | EXE-01, D7 | TBD native/Python broker interfaces | Shared contract/conformance fixtures |
| REQ-EXE-02 | Implement Kotak as the sole order broker, preserving `jData` POST wrapping and REST-only order routing; require a real order through Shaurya's path for Live verified status. | EXE-02, D7 | TBD `native/src/kotak_*` | Ported tests; read-only broker checks; authorised live-order evidence |
| REQ-EXE-03 | Implement the paper broker with REQ-EXE-09's fill model and label every simulated fill as proxy. | EXE-03, CON-06 | TBD native paper broker | Deterministic fill fixtures; proxy-labelled ledger |
| REQ-EXE-04 | Implement lifecycle states for partial fill, cancel race, late fill after cancel, rejection, and forced residual exit. | EXE-04 | TBD native order state machine | Transition/property/race tests; lifecycle ledger |
| REQ-EXE-05 | Write one append-only `CON-02` ledger per run. | EXE-05 | TBD native ledger writer | Schema, append-only, hash, crash-recovery tests |
| REQ-EXE-06 | Require flat-account preflight, an explicit one-time per-session human confirmation phrase, refusal of paper-only settings in live mode, and no scripted or per-order reauthorisation path. | EXE-06 | TBD native CLI/live gate | Negative safety tests; session-authorisation audit event |
| REQ-EXE-09 | Build one Q-conditioned queue-reactive/intensity fill model consumed by paper execution and backtesting. | EXE-09, D14 | TBD shared execution-realism core | Calibration/replay/property tests; model artifact |
| REQ-EXE-10 | Estimate own queue-ahead from visible level size, order counts and trades: exact at acceptance, hard lower/upper bounds thereafter, plus a point estimate under an explicit cancellation-position model. Report bound width and propagate both bounds into every generated fill. | EXE-10, SIG-07, D14, D23 | TBD queue estimator | Known-scenario/bound/label-propagation tests; bounded queue estimate |

Dropped tasks EXE-07 and EXE-08 have no requirements: Dhan and Kite order placement are outside scope.

## Timing, causality, and safety gates

1. A market event is eligible only after its `CON-07` receive time; decision and send timestamps are recorded separately.
2. Every live order passes the C++ RSK choke point before broker submission. No strategy path may call Kotak around it.
3. Paper is the default. Live mode requires the one-time human session authorisation and flat-account preflight; authorisation is never automated.
4. Broker acknowledgement does not erase cancel/fill races. Late fills remain ledger events and update risk state.
5. A fill-model output is never evidence that a real order would have filled; the proxy and queue-estimation labels persist downstream.

## Outputs and acceptance tests

- Broker conformance fixtures, append-only canonical ledgers, lifecycle audit records, queue-intensity calibration artifacts, and proxy-labelled paper fills.
- Negative tests prove orders cannot bypass authorisation, live-mode config checks, or RSK.
- State-machine tests cover partial fills, reject, cancel race, late fill, and residual exit.
- Python/C++ mirrors consume the same contracts; domain parity is demonstrated through NAT/RSK/BKT suites where applicable.
- Live verification is withheld until an explicitly authorised real order traverses Shaurya's own new path.

## Exclusions

- Dhan or Kite order placement; unattended authorisation; per-order confirmation prompts.
- Kotak market-data reception (D18).
- Touch-fill as a module fill model.
- Unlabelled queue rank or simulated fill.
- Strategy-specific quoting logic.

## Deferred items

- All live execution work remains not started. The broker-verified Market Making source is harvest evidence, not inherited Shaurya Live verified status.
- A live order remains contingent on completed NAT/RSK gates and explicit session authorisation; it is never authorised by this specification alone.
