# Deep-book methodology

## 1. Hypotheses

`H-deep-book-001` validates outcome-blind price-keyed event construction.
`H-deep-book-002` is the registered two-sided event-to-later-midpoint response question.

## 2. Source tests and entry points

`test_deep_book_anomaly.py`, `test_deep_book_inference.py`, `test_deep_book_response.py`,
`test_sig21_construction_replay.py`, and `test_sig21_exploratory_response.py`; implementation in
`signals/deep_book_{anomaly,construction_grid,inference,response,exploratory_response}.py`.

## 3. Input lineage

Depth200 price/quantity/order-count states construct events; depth20 midpoint paths construct
responses. The immutable registration is `research/docs/sig-claims/H-SIG21.md`. Two older DAT-20
tapes are permitted for construction/exploration only and permanently ineligible for confirmation.

## 4. Feature derivation

Verified from code/docs: price-key maps classify additions/removals and retained-price quantity or
order-count changes; relocation pairs are <=25% quantity-difference proxies. Far distance is >Rs20
from the pre-event same-side best. Responses use gaps 0.5/1s and horizons 1/5/10s with matched quiet
controls. See `../features.csv`.

## 5. Temporal alignment and leakage

Construction schema contains no outcome field. Baselines use completed prior sessions only.
Responses require full right-edge coverage, same epoch, cell-specific nonoverlap, and outcome-blind
matching. Confirmatory claims/tapes outside the permitted registration clock are refused.

## 6. Procedure and metrics

Build all 32 construction cells and full 384 response family; reconcile candidates/exclusions;
report event counts, exposure, distance/time strata, raw and effective N, HAC/bootstrap estimates,
family adjustment, negative controls, selectivity, MDE, and matched-control differences.

## 7. Output interpretation

Construction evidence supports the detector: retained documentation reports 10/10 focused fixtures
and reconciled live-tape candidate counts. It explicitly says candidates are not anomalies and no
price-response result exists. The outcome hypothesis therefore remains `no result located`.

## 8. Edge cases and quality checks

Rank cascades, outer-boundary churn, reconnect/sequence gaps, partial/crossed depth, same-timestamp
bursts, insufficient prior baselines, tape hash mismatch, truncated horizons, overlapping episodes,
unmatched controls, tiny effective N, and forbidden confirmatory requests are explicit.

## 9. Limitations

Order identity is absent; relocation is proxy-only. High event counts precede anomaly thresholds.
The registration requires five calibration plus twenty evaluation sessions and a pushed pre-outcome
power artifact; completion of those gates was not located.

## 10. Reproduction

```bash
cd research
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_deep_book_anomaly.py tests/test_deep_book_inference.py tests/test_deep_book_response.py tests/test_sig21_construction_replay.py tests/test_sig21_exploratory_response.py
```

Use only synthetic/temporary fixtures unless a tape is explicitly authorized for its registered role.

## 11. Researcher decisions

No post-hoc direction is allowed. Researchers must resolve data-gate completion, power, session and
regime support, economic scale, and any amendment before outcome execution.
