# Risk Rules

This release evaluates one immutable `RiskSnapshot` in a fixed, default-deny sequence. The first
failed rule returns a factual rejection with exact before, projected, and limit evidence; a missing
or malformed input never becomes a permissive default.

1. Validate schema, session, strategy, run, UUID, expiry, and neutral intent shape.
2. Require an active shadow session without kill switch, reconciliation debt, or shutdown.
3. Resolve the exact canonical instrument from the immutable routing snapshot and routing date.
4. Require a fresh observed Dhan market observation and a ready broker-session abstraction.
5. Enforce integer paise tick alignment, exchange-unit lot alignment, and positive quantity.
6. Rebind all working orders and positions to exact canonical instruments and authoritative tokens.
7. Enforce order-rate, per-order, per-instrument, working-plus-held, and gross-exposure limits.
8. For SELL, require available long inventory in the same canonical instrument after working SELLs.
9. Require fresh enabled Greeks and enforce delta, gamma, and vega limits.
10. Enforce realized/unrealized loss and drawdown limits using conservative marks.

Modify excludes the target's remaining quantity before projecting the replacement, and its total
cannot fall below cumulative fills. Cancel is separately risk-reducing: a known nonterminal target
may be cancelled during stale-market or kill conditions, but unknown transport authority requires
reconciliation. Overflow, contradictory broker evidence, queue loss, ambiguous submission, or a
durability failure after a broker attempt activates safety stop and blocks new intents. Full field
definitions and implementation detail are in `RISK_BROKERS_AND_SESSION.md`; focused evidence is
`execution.risk_engine`, `execution.execution_session`, and `execution.reconciliation`.
