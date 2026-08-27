# Risk, broker adapters, reconciliation, and sessions

Section 04 supplies the ordinary, shadow-safe decision and broker boundary. The
`shaurya_execution_controls` library is compiled publicly with
`SHAURYA_ENABLE_KOTAK_LIVE=0`. Configuring `SHAURYA_ENABLE_KOTAK_LIVE=ON` is a fatal configure-time
refusal. The Kotak component contains canonical fixture request builders, bounded sanitized response
parsers, and a deterministic update queue only; there is no socket, HTTP client, credential type,
URL, authentication flow, or live transport factory.

## Deterministic risk

`RiskConfiguration::parse` accepts one closed, integer-only JSON shape. It rejects duplicate,
unknown, missing, negative, overflowing, or semantically inconsistent values and verifies the
declared SHA-256 digest against `canonical_payload()`. Direct construction applies the same equality
check and never rewrites a supplied digest. `maximum_mapping_age_ns` is a distinct canonical field;
routing freshness therefore cannot silently inherit the market-observation freshness limit.

`RiskEngine` consumes that immutable configuration, a parsed `OrderIntent`, and one captured
`RiskSnapshot`. Rules run in fixed order and stop on the first failure. The decision records the
ordered rules reached, exact before/projected/limit values, receive and exchange freshness ages,
configuration digest, and a deterministic decision UUID. Place and modify require matching
session/strategy/run correlation, readiness, a current verified route, `LIMIT`/`NRML`/`DAY` shape,
healthy broker session, fresh Dhan observation, exact tick/lot, authoritative broker positions,
bounded held-plus-working exposure, exact-token SELL inventory, enabled fresh Greeks, and
loss/drawdown room. Every authoritative runtime order/position is rebound through the current
resolver and rejected on canonical/token, provenance, shape, or uniqueness mismatch. Gross
position marks use the maximum valid bid, ask, and last trade for conservative absolute exposure.
Modify projections exclude the old target remainder and apply only
`new_total_quantity - cumulative_filled_quantity`; equality or a total below cumulative fills is
rejected before broker work. Cancels use a separate risk-reducing path and remain possible during kill/stale-market
conditions for a known nonterminal target; unknown transport health marks the attempt
reconciliation-required.

## Broker boundary and paper evidence

`BrokerAdapter` distinguishes acknowledged, rejected, and ambiguous mutations. Queries distinguish
authoritative empty results from partial or unavailable evidence, and health is one of ready,
degraded, lost, or unknown. The session validates bounded broker identifiers, error categories,
provenance, and mutation correlation at this boundary. No exception or timeout is treated as a
rejection. Modify acknowledgement is accepted only when its quantity and limit price exactly echo
the requested terms; cancel acknowledgement is terminal only with explicit terminal confirmation.

`PaperBroker` uses stable `paper-NNNNNNNN` correlations and provenance `simulated_proxy` throughout.
The normal `d51_proxy_v1` model fills at the submitted limit only on later valid crossing quote
evidence or later crossing trade evidence with advanced cumulative volume. Placement-time evidence,
stale/unusable observations, and volume-reset observations cannot fill. The `scripted_v1` model is
constructor-guarded for fixtures and supports monotonic partial/final fills, duplicates, rejection,
ambiguity, and session loss. Overfills and chronology regressions are rejected, never clamped. A
validated `PaperBrokerSnapshot` preserves requests, orders, fills, positions, per-instrument marks,
checked fill cashflows, peak equity, model, health, and sequence so restart tests reproduce exact
P&L and drawdown state. Long positions mark conservatively at bid and shorts at ask, with last trade
only as a fallback; missing marks or arithmetic overflow make P&L unavailable rather than zero. It
is not a live or broker-confirmed model.

## Reconciliation and session ordering

`Reconciler` validates and compares complete authoritative order, fill, and position sets, including
absence, duplicates, terminal state, quantities, instrument identity, broker-source provenance, and
the known instrument universe. Partial or unavailable queries are mismatches. Its strictly
round-tripped `PositionSnapshot` retains strategy-desired, ledger-reconstructed, and
broker-authoritative quantities separately; broker absence is never silently converted to zero.

`ExecutionLedgerSessionAdapter` opens or creates the Section 03 ledger, including descriptor-rooted
`*_at` construction, verifies and replays it, and
exposes reconstructed state to `ExecutionSession`. The session rebuilds its `IdempotencyStore` and
order FSM from that state. It becomes ready only after routing validation, three authoritative
queries, exact reconciliation, a durable `reconciliation_completed`, and a durable
`session_started` event. Every mutation follows this ordering:

1. durable `intent_received`;
2. mapping result;
3. durable risk decision;
4. durable `submission_started`/`modify_requested`/`cancel_requested` in `prepare_intent`, producing
   a move-only session- and authority-generation-bound capability;
5. exactly one broker attempt;
6. durable acknowledgement/rejection, or an ambiguity safety stop.

A pre-attempt ledger failure sends no order. Durable place/modify attempt timestamps are replayed
into the active rate window (including rejected or ambiguous calls; cancels are excluded), so a
restart cannot reset rate authority. Completed approved and rejected outcomes, including the exact
immutable `RiskDecision` and normalized broker disposition, are reconstructed at the session
boundary for zero-call duplicate replay. A post-attempt durability failure or ambiguous result
revokes authority and requires reconciliation. Same-ID/same-fingerprint requests replay without a
broker call; conflicts are durably recorded and activate the safety stop. Broker updates enter a
bounded FIFO; duplicate IDs require identical typed evidence and queue overflow or conflicting
duplicates stop the session. Broker update sequence and fingerprints are independent of ledger
sequence and survive replay. Every applied update is validated through the shared order FSM and
recorded as a closed `ExecutionEvent` payload. Shutdown durably records `session_stopping`, revokes
authority before factual cancel attempts, and accounts for every authoritative working order.
Cancellation attempts are bounded by
the configured rate and absolute deadline; each unattempted order receives correlated durable
`reconciliation_required` evidence. A refusal is counted only after that exact evidence is durable;
otherwise `cancellation_accounting_complete` is false while shutdown continues accounting for later
known orders. Cancellation completeness is false and the terminal state stays
`uncertain` if any working order was not attempted or terminally confirmed, even when a later broker
query otherwise agrees with the ledger. Exact shutdown reconciliation additionally requires broker
session health re-sampled as `Ready` after the authoritative orders, trades, and positions queries;
degraded, lost, and unknown sessions remain uncertain.
Unknown outcomes are never converted into local cancellation.

## Verification

CTest labels the five focused executables `section04;controls`: `risk_engine`, `paper_broker`,
`kotak_adapter_fixtures`, `reconciliation`, and `execution_session`. Live provider validation,
authentication, endpoints, static-IP behavior, real-account updates, and contract-note reconciliation
remain deliberately unperformed blockers.
