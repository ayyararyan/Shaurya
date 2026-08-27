# Reference-price methodology

## 1. Hypothesis

`H-reference-price-001` compares displayed mid, observed last trade, print-derived effective-touch
mid, and displayed L1 microprice as causal reference/state objects.

## 2. Source tests and entry points

`test_microprice.py`, `test_effective_touch.py`, `test_reference_prices.py`, and
`test_d38_acceptance.py`; producers are `signals/{microprice,effective_touch,reference_prices}.py`.

## 3. Input lineage

Depth20 BBO/queues provide displayed mid and microprice. Qualified cumulative-volume increments and
classifier/alignment metadata provide print observations. No order IDs, queue positions, or fills
exist.

## 4. Feature derivation

Verified from code: microprice is `(ask_qty*bid + bid_qty*ask)/(bid_qty+ask_qty)` and queue
imbalance is `(bid_qty-ask_qty)/(bid_qty+ask_qty)` (`microprice.py:71-103`). Effective-touch paths
are causal rolling print-derived bounds. Touch-relative depth is re-keyed into fixed outward tick
bands (`reference_prices.py:263-395`).

## 5. Temporal alignment and leakage

Every path resolves as-of the anchor; undefined effective touch creates no point and never falls
back to displayed mid. Coalesced/degraded/unversioned prints are excluded. Reference coverage is
reported per path.

## 6. Procedure and metrics

Build all four paths side by side, compare coverage and state, then use the same target/model cells
for reference-ladder comparisons. Diagnostics include print location, staleness, coverage,
touch-relative queue imbalance, and microprice tilt.

## 7. Output interpretation

Last trade is observed; displayed mid/microprice are deterministic derivatives; effective touch is
a proxy. A different held-out score is evidence about a measurement choice, not proof of the true
touch or executable price.

## 8. Edge cases and quality checks

Crossed/empty BBO, zero depth, no prints, undefined one-sided touch, stale bounds, coalesced volume,
empty touch bands, and incomplete reference ladders fail or remain missing explicitly.

## 9. Limitations

Undisplayed liquidity is unavailable; effective bounds can be stale; cumulative-volume increments
can coalesce prints; and displayed queues do not establish queue position.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_microprice.py tests/test_effective_touch.py tests/test_reference_prices.py tests/test_d38_acceptance.py
```

## 11. Researcher decisions

Select the primary reference, effective-touch window, staleness tolerance, band widths, and whether
any reference change is confirmatory or exploratory.
