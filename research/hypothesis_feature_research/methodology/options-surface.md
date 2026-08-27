# Options-surface methodology

## 1. Hypotheses

`H-options-surface-001` covers causal eSSVI construction/readiness. `H-options-surface-002` covers
read-only IV-residual convergence episodes.

## 2. Source tests and entry points

`test_essvi_surface.py`, `test_surface_interface.py`, `test_surface_arbitrage.py`,
`test_anl03_dashboard.py`, and `test_surface_mispricing.py`; producers in `surfaces/essvi.py`,
`surfaces/arbitrage.py`, `analytics/surface_feed.py`, and `analytics/mispricing.py`.

## 3. Input lineage

Option BBOs supply prices/strikes/expiries; a traded future or put-call parity supplies the forward.
Fit requests and frames retain receive/decision time, support, age, staleness, and diagnostics.

## 4. Feature derivation

Verified eSSVI formula is documented in `../features.csv` and implemented by
`surfaces/essvi.py:_total_variance_array`. ATM shape uses analytic k=0 derivatives. Mispricing
inverts Black-76 to observed IV and compares its residual with a causal smoothed fair IV and
past-only uncertainty.

## 5. Temporal alignment and leakage

Fit requests reject future rows. Unsupported grid cells stay null. The residual currently being
tested does not train its own uncertainty. Mispricing episodes distinguish target movement from
reference-market movement and retain censored/invalidated states.

## 6. Procedure and metrics

Calibrate slices; run butterfly/calendar checks; apply staleness/smoothing readiness; render a
read-only dashboard; then for residual episodes enforce size, warm-up, raw/smoothed agreement,
reference-move, and convergence gates. Metrics include fit diagnostics, support, age, ATM changes,
residual magnitude, and episode outcome.

## 7. Output interpretation

Unit/acceptance tests show the machinery is implemented. Located live-evidence documents are not
independently replayed here. No persisted empirical mispricing episode table was located, so the
convergence hypothesis has `no result located`.

## 8. Edge cases and quality checks

No forward source, insufficient strikes, failed fit, unsupported cells, stale/dead feed, reconnect,
calendar/butterfly violations, missing target quote, reference closure/jump, warm-up, and IV
inversion bounds are explicit.

## 9. Limitations

Surfaces depend on quote and forward quality; a fitted smooth surface need not be economically
correct. No execution/fill/cost path exists, and current tests do not establish cross-session fit
or convergence stability.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_essvi_surface.py tests/test_surface_interface.py tests/test_surface_arbitrage.py tests/test_surface_mispricing.py tests/test_anl03_dashboard.py
```

## 11. Researcher decisions

Choose forward hierarchy, support/staleness thresholds, smoother warm-up, residual economic
threshold, episode benchmark, confirmation horizon, and cross-session evidence requirement.
