# D51 — Ten-second futures-mid feature-selection experiment

**Specification ID:** `D51-10S-FEATURE-SELECTION-2026-08-21`  
**Version:** `1.0.0`  
**Status:** Approved and frozen from Aryan's 2026-08-21 instruction  
**Evidence boundary:** Any result using only the 2026-08-21 session is an **exploratory
screening result**, never a stable or confirmatory feature finding.

## 1. Objective and estimand

The experiment asks which compact, stable information clusters add future out-of-sample value
for the front NIFTY futures displayed midpoint over ten seconds.  The single primary target is

\[
y_t = \{m(t+0.5\mathrm{s}+10\mathrm{s})-m(t+0.5\mathrm{s})\}/0.05,
\]

where `m(s)` is the latest usable displayed BBO midpoint as of receive time `s`, within one
connection epoch.  The target is continuous and measured in futures ticks.  It is not an
up/down label and it is not a contemporaneous return.

The 0.5-second gap, displayed-mid reference, receive-time clock and 0.05-rupee futures tick are
existing D39--D41 causal conventions and are not changed here.  A later executable model must
replace the 0.5-second research gap when measured end-to-end response latency is larger; that
would be a meaning-changing specification amendment.

## 2. Frozen requirements

| ID | Requirement |
|---|---|
| `D51-OBJ-01` | Maintain exactly one primary ten-second continuous displayed-mid target, in ticks, after the fixed 0.5-second causal gap. |
| `D51-DATA-01` | Consume retained DAT-derived canonical observations and surface frames. Do not add Dhan clients, sockets, credentials, raw discovery, parsers, order routes or order authority. |
| `D51-CAUSAL-01` | Every feature is available no later than its anchor. As-of joins stay within one connection epoch; target endpoints are strictly later than the anchor. |
| `D51-REG-01` | Publish versioned feature and target registries with stable names, family, object category, source, timing rule and construction. Duplicate names are refused. |
| `D51-X-PRICE-01` | Register trailing displayed-mid returns at 0.5/1/2/5/10/30 seconds, consuming canonical past-return observations. |
| `D51-X-BOOK-01` | Register spread, microprice tilt, five-level quantity/order imbalance, depth totals, average-order-size proxies, and book slope/curvature, consuming the canonical LOB constructor. |
| `D51-X-OFI-01` | Register canonical CCZ depth-scaled average OFI at windows 0.5/1/2/5/10/30 seconds and depths 1/5/10/20/50/100/200, plus predeclared near-minus-far pressure gradients. |
| `D51-X-SURF-01` | Register eSSVI level/shape/term observables, one-frame changes/velocities, past-state EW innovations, and surface quality/freshness fields, consuming canonical surface frames. |
| `D51-X-REGIME-01` | Register causal intraday phase, minutes from open/to close, lag-based realised-move scale, spread and depth state. Time-of-day uses declared session bounds, not a same-day fitted seasonal curve. |
| `D51-X-INT-01` | Register only the predeclared interactions: OFI x spread, OFI x inverse L1 depth, OFI x lagged realised-move scale, and front-expiry skew innovation x OFI. |
| `D51-MISS-01` | Missing or unsupported inputs remain missing. No missing feature is silently converted to zero. |
| `D51-ID-01` | Individual order identity/rank, cancellation position and hidden quantity remain unidentified; average order size remains explicitly named as a proxy. |
| `D51-OOS-01` | Clustering, imputation, scaling, fitting and feature selection occur only inside later training folds. Step 1 constructs no fitted selector or model. |
| `D51-EXP-01` | All 2026-08-21-only empirical output is labelled exploratory/non-confirmatory and cannot establish cross-day stability or promotion. |
| `D51-OUT-01` | Emit deterministic rows carrying anchor, connection epoch, target interval, target value, per-feature values, per-feature availability time and registry version. |

## 3. Model-object and identification ledger

| Object | Category | Source/timing | Boundary |
|---|---|---|---|
| Displayed BBO midpoint | Observed | Retained DAT depth20/full state, receive time | As-of state; not executable fill price. |
| Ten-second target | Deterministically derived | Canonical D39--D41 future-return field | Strictly future; unavailable at the live feature timestamp. |
| Price lags, book state, CCZ OFI | Deterministically derived | Canonical past-only constructors | Snapshot-coalescing limitation `ID-CCZ-01` is inherited. |
| eSSVI observables | Estimated | Canonical surface frame available as of anchor | Inherits surface fit/version/quality and is not observed volatility. |
| EW surface innovation | Deterministically derived from estimated state | Current surface value minus EW mean of strictly earlier frames | No future frame and no same-day outcome enters it. |
| Time/regime fields | Deterministically derived | Anchor and declared session bounds, trailing returns/book | Lagged realised-move scale is descriptive state, not a fitted VOL regime. |
| Average order size | Proxy | Displayed quantity divided by displayed order count | Explicit `proxy` suffix retained. |
| Individual order identity, hidden quantity | Unidentified | Absent from retained aggregated book | Not proxied. |

## 4. Feature construction

The builder consumes `HorseRaceObservation` rows so target, return-lag and multi-depth OFI
semantics remain those of the canonical OFI layer.  It joins the latest usable `BookState` and
latest `FrameDraft` at or before the anchor in the same connection epoch.  The LOB block is
computed by canonical `lob_features`; the surface block is copied from canonical `FrameDraft`
economic and quality maps.

For surface level variable `x`, the EW innovation at frame `j` is

\[
u_j=x_j-\bar x_{j-1},\qquad
\bar x_j=0.2x_j+0.8\bar x_{j-1}.
\]

The first frame has a missing innovation.  Innovations are computed once in strict timestamp
order before as-of joining.  This is a deterministic causal state transformation, not fitted
feature selection.

The multi-depth OFI scalar at `(w,M)` is the canonical CCZ Appendix-A average of the `M`
depth-scaled level flows using one common `Q^{M,w}` denominator.  It is not a cumulative
price-keyed flow.  Required source columns absent from an observation remain missing.

## 5. Missingness and quality

- Missing target: omit the unlabelled research row and count it in diagnostics.
- Missing book or surface as-of join: keep the row; affected features remain `None`.
- Non-finite values: convert to `None`, never zero.
- Stale surface: retain its causal quality/freshness fields; later quality gates decide use.
- Epoch mismatch: never carry the state across a reconnect.

## 6. Explicit exclusions from Step 1

Quality gates, correlation clustering/PCA, imputation, scaling, elastic-net/group-lasso,
boosted trees, stability selection, walk-forward folds, purging/embargo implementation,
importance, ablation, economic selection and empirical fitting are owned by later steps.  No
trade or deployment claim follows from this construction layer.

## 7. Acceptance tests

1. Registry names are unique and contain every frozen family/axis.
2. Target geometry is exactly anchor + 0.5 seconds to anchor + 10.5 seconds.
3. A future surface frame cannot alter an earlier row.
4. A different connection epoch cannot supply book/surface features.
5. Canonical LOB and CCZ source values pass through exactly.
6. EW innovations use only earlier surface frames.
7. Missing inputs stay `None`; interactions propagate missingness.
8. Every non-missing feature availability timestamp is at or before the anchor.

## 8. Completion criterion

Step 1 is complete at evidence level 2 when this specification, registry/construction code,
traceability rows and focused deterministic tests are committed and passing.  No empirical
result is required or claimed at this stage.
