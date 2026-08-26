# SIG-21 construction-only evidence — 2026-08-19

**Scope:** price-keyed deep-book candidate construction only. No future midpoint, return, label,
matching, power or inference object was read, constructed or joined.

**Status:** the detector is Tested and Dry-run verified on retained live tape for construction.
`SIG-21` as a predictive research task remains In progress; no price-response result exists.

## Registration and implementation boundary

- Binding registration: `docs/sig-claims/H-SIG21.md`.
- Implementation: `src/shaurya/signals/deep_book_anomaly.py`.
- Construction output schema is limited to event identity/time, atomic type, side, actual price,
  optional source price, pre-event same-side distance, magnitude, before/after displayed quantity
  and order count, and `CON-06` category.
- The implementation has no response, return, label, matching, power or inference API.

## Focused verification

Ten fixtures verify:

1. a level-index cascade is one price-keyed addition;
2. quantity and order-count changes remain separate atomic events;
3. matched disappearance/reappearance is labelled a relocation proxy and not double counted;
4. near-complete outer-window churn is excluded;
5. reconnect epochs and invalid quality transitions are rejected whole;
6. the strict `> Rs 20` boundary uses the pre-event same-side best quote;
7. the empirical baseline cannot learn from the session it scores;
8. session-time regressions are rejected; and
9. the public candidate schema has no outcome fields.

Focused result: **10/10 passed**. Full Python result: **164/164 passed**. Ruff lint and strict mypy
pass. Repository-wide Ruff formatting is not a clean baseline: 21 unrelated pre-existing files
would be reformatted; the new SIG-21 files themselves pass the formatter.

## Construction-only retained-tape run

The runner streamed only `event_type == "depth200"`, retained the last merged state in each exact
receive-timestamp burst, and compared consecutive states. Standard/depth20 rows were never passed
to the detector, and no midpoint or post-event alignment was computed.

| | DAT-20 run 1 | DAT-20 run 2 |
|---|---:|---:|
| Run ID | `sha-20260819T073935.092996Z-6ca41203` | `sha-20260819T075057.972093Z-286d5105` |
| depth200 states | 2,718 | 2,764 |
| valid transitions attempted | 2,717 | 2,763 |
| candidate events | 23,110 | 17,692 |
| additions | 6,608 | 5,515 |
| removals | 6,599 | 5,540 |
| quantity increases / decreases | 1,758 / 1,799 | 1,248 / 1,289 |
| order-count increases / decreases | 1,758 / 1,788 | 1,246 / 1,284 |
| relocation-toward proxies | 1,858 | 1,070 |
| relocation-away proxies | 942 | 500 |
| invalid partial-book transitions excluded | 1 | 1 |
| outer-window churn exclusions | 9 | 15 |

## Interpretation and limitations

- These are **candidate price-level events, not anomalies**. High counts are expected before the
  past-only 99.5%/99.9% thresholds are applied.
- The two 11-minute runs cannot populate the registered previous-session baseline, multi-regime
  support, numeric MDE or prediction sample.
- Relocation counts are displayed-liquidity matching proxies. Dhan has no anonymous-order identity,
  so they cannot be interpreted as literal order moves.
- This dry run validates parser compatibility, price-keyed construction, exclusion accounting and
  event support only. It says nothing about sign, response, predictability, admissibility or maker
  profitability.

## Gate state

The registration/construction gate was **OPENED** by pushed commit
`f2cf65011d02882191b5cfda566c1024119964d7`; the remote `main` hash was independently verified to
match. This allowed the synthetic response/power/inference implementation to begin. The separate
future-price outcome gate remains **CLOSED** pending five new calibration sessions, a complete
pushed numeric power artifact, and then 20 later full evaluation sessions.
