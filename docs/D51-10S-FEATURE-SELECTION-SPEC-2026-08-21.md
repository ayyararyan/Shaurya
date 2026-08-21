# D51 — Ten-second futures-mid feature-selection experiment

**Specification ID:** `D51-10S-FEATURE-SELECTION-2026-08-21`
**Version:** `1.6.0`
**Status:** Approved, frozen and executed at the one-session exploratory boundary
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
| `D51-OOS-01` | Every learned transform is fit inside explicitly declared training rows only. Targets and held-out rows never enter correlation, threshold, representative or PCA decisions. |
| `D51-EXP-01` | All 2026-08-21-only empirical output is labelled exploratory/non-confirmatory and cannot establish cross-day stability or promotion. |
| `D51-OUT-01` | Emit deterministic rows carrying anchor, connection epoch, target interval, target value, per-feature values, per-feature availability time and registry version. |
| `D51-GATE-01` | Enforce the registered schema, registry version, exact target geometry, finite target/value domains, and per-value availability no later than the anchor. A feature with missing or future availability fails closed. |
| `D51-GATE-02` | Emit separate missingness and validity indicators. Invalid values become missing in the gated view and are never silently zero-filled; source rows remain unchanged. |
| `D51-GATE-03` | Compute coverage, near-constant and deterministic exact/affine duplicate checks from explicitly declared training-row indices only. Keep the first registered duplicate as the canonical representative. |
| `D51-GATE-04` | Gate surface economic features on causal freshness, fit quality, quote/support coverage, stale-state and arbitrage diagnostics. Missing required quality diagnostics fail the surface block closed. |
| `D51-GATE-05` | Emit a deterministic, versioned audit artifact with input fingerprint, resolved policy, eligible/excluded names, training diagnostics, row/feature validity and a stable reason taxonomy. |
| `D51-CLUSTER-01` | On gate-eligible features, estimate pairwise Spearman correlation from pairwise-available declared training observations only. Record the pair count and require at least three paired observations by default; unsupported/zero-rank-variance pairs receive distance one. |
| `D51-CLUSTER-02` | Define distance as `1 - abs(Spearman rho)` and apply deterministic average-linkage hierarchical clustering. Always emit the predeclared sensitivity maps at absolute-correlation cuts 0.85/0.90/0.95; use 0.90 as the predeclared primary map, never an outcome-selected cut. |
| `D51-CLUSTER-03` | Select one deterministic representative per cluster using only a pre-outcome measurement-quality score, then training coverage, then lexical stable naming. No target association or individual importance enters the choice. |
| `D51-CLUSTER-04` | Optionally fit a first-PC representation on complete training cases only. Save ordered members, centers, loadings, complete-case support and the fixed sign convention; application never refits and any missing member leaves the PC missing. |
| `D51-CLUSTER-05` | Emit a versioned reproducible reduction artifact with a training-only fingerprint, pair diagnostics, every sensitivity map, the primary cluster map and any PCA transforms. All later importance is assigned to clusters, not substitutable individual features. |
| `D51-MODEL-01` | Fit one saved preprocessing transform on supplied training rows only: explicit per-feature train median imputation, missing indicators, centering and scaling. Validation/test rows only apply that state; missingness is never interpreted as economic zero. |
| `D51-MODEL-02` | Provide a transparent elastic-net regression with saved intercept, coefficients, ordered transform and deterministic apply. Retain every caller-supplied feature and its missing indicator; correlated predictors are regularised rather than silently discarded. |
| `D51-MODEL-03` | Provide a dependency-light deterministic shallow gradient-boosted regression-tree challenger with bounded depth/leaves, learning rate, minimum leaf size and train-derived deterministic threshold candidates. A supplied validation set may select stopping iteration only; it cannot fit transforms or thresholds. |
| `D51-MODEL-04` | Freeze elastic-net and boosted-tree structural grids before outcomes and expose zero-return, training-mean and declared-state linear baselines under the same finite prediction and regression-metric contracts. |
| `D51-MODEL-05` | Save and deterministically read back complete apply-only model state for both predictive classes, including preprocessing and tree structure. Test rows are apply-only. |
| `D51-IMP-01` | Treat the frozen correlation cluster as the smallest importance unit. Never rank or assign evidence to individual substitutable members; feature-family ablations remove whole declared clusters. |
| `D51-IMP-02` | Measure conditional cluster/family usefulness by retraining the same fixed model/configuration on the same supplied training rows after dropping the whole unit. Define delta OOS R-squared as full minus ablated, so positive means useful. |
| `D51-IMP-03` | Measure grouped permutation importance by jointly permuting every model column representing one cluster in deterministic contiguous evaluation-time blocks. Keep the full fitted model fixed and publish every predeclared repeat/seed. |
| `D51-IMP-04` | Enforce identical ordered evaluation rows for every paired comparison and retain rowwise squared losses plus contiguous block sums/mean differences for later dependence-aware uncertainty. Do not perform inference or stability selection here. |
| `D51-IMP-05` | Emit deterministic read-back-safe artifacts carrying model/config/split/data fingerprints, full cluster membership and representation columns, family, support, full/comparator metrics, delta/direction, paired losses and block-permutation identities. Evaluation targets may score comparisons but never choose clusters, families, models or configurations. |
| `D51-STAB-01` | Consume caller-supplied walk-forward fold results without constructing, reordering or fitting folds. Aggregate selection frequency, median delta OOS R-squared, positive-fold fraction and direction consistency separately for every frozen cluster/model pair. |
| `D51-STAB-02` | Freeze promotion gates before empirical output: at least 20 distinct eligible sessions and five eligible folds; at least 70% positive folds, 70% selection frequency and 70% direction consistency where defined; strictly positive median delta; no one-session dominance; no stronger past mirror; and strictly positive cost/latency-adjusted value when supplied. |
| `D51-STAB-03` | A result with fewer than 20 distinct eligible sessions is labelled `exploratory_insufficient_sessions`; a one-session result can never be stable or promoted. Publish day/session support and volatility, spread and time-phase regime coverage, leave-one-session-out diagnostics and mirror/economic guards. |
| `D51-STAB-04` | Preserve fold/block paired-loss aggregates for later dependence-aware uncertainty, and publish training/evaluation support plus learning-curve diagnostics. Do not compute confidence intervals, p-values or an empirical promotion in this implementation step. |
| `D51-STAB-05` | Provide deterministic training-only contiguous-block elastic-net stability resampling. Save seeds, sampled training indices and configuration; a cluster is selected when any coefficient belonging to any of its model columns or explicit missingness columns is nonzero. Never publish or promote an individual column. |
| `D51-STAB-06` | Emit deterministic exact-readback final cluster-selection and elastic-net-resampling artifacts with stable fingerprints, complete cluster membership and stable reason codes. |
| `D51-WF-01` | Execute the same-day experiment on a UTC-aligned one-second primary engineering grid; use a five-second sensitivity only when support/runtime permits. This sampling convention does not change the ten-second estimand. |
| `D51-WF-02` | Construct deterministic expanding outer folds with strictly chronological tests, purge every training label overlapping the next evaluation boundary, and embargo by `max(120 seconds, Z+h)`. Each row enters at most one outer test. |
| `D51-WF-03` | Put every quality gate, correlation map, representative/PCA state, preprocessing transform, model fit and configuration/early-stopping choice inside the applicable training fold. Inner validation may choose a frozen-grid configuration and stopping count; outer tests remain apply/score-only. |
| `D51-EMP-01` | Compare zero-return, training-mean, declared simple-state, elastic-net and shallow boosted-tree models on identical outer-test rows and publish compact SHA-pinned model/support tables. |
| `D51-EMP-02` | Resolve the completed option-chain/surface source through its explicit DAT handle and publish the exact futures/surface intersection. Never carry a surface frame before its availability or fabricate pre-capture surface values. |
| `D51-EMP-03` | Label the 2026-08-21 result `exploratory_insufficient_sessions`; it cannot make a stability, signal, confirmation, deployment or order claim. |

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
- Stale surface: retain its causal quality/freshness fields in construction; the Step 2 gate
  invalidates economic surface fields while preserving the audit diagnostics.
- Epoch mismatch: never carry the state across a reconnect.

Step 2 applies hard gates without fitting a predictor or inspecting target association.  Its
default pre-empirical surface policy requires: age at most 480 seconds, non-negative weighted
R-squared, at least one used quote, at least one quote per registered expiry, non-negative
support width, a false stale flag and a passed arbitrage diagnostic.  Every required quality
field must be present.  These conservative domain/support floors are serialized in the gate
artifact; a later empirical run may use a different **predeclared** policy, but may not tune it
against held-out outcomes.

Generic availability-age caps are one second for book/liquidity state and 480 seconds for
surface economic state.  Coverage defaults to 50% of declared training rows.  A feature is
near-constant when its finite training range is at most `1e-12`.  Exact duplicates require an
identical missingness mask and identical values; affine duplicates require at least three
finite training observations and equality to one non-zero affine transform within `1e-12`
relative numerical tolerance.  Duplicate resolution follows registry order and therefore is
deterministic.  These redundancy checks are quality gates, not correlation clustering.

The stable reason taxonomy distinguishes schema/version/target failures, missing and future
availability, staleness, finite/range failure, surface quality/fit/support/arbitrage failure,
training coverage/constancy failure, and exact/affine duplication.  Missingness flags describe
the source observation; validity flags separately describe whether a downstream transform may
consume it.

## 6. Correlated-feature reduction (Step 3)

Step 3 consumes the Step-2 gated view and its already-declared training-row indices. It sorts
eligible feature names before all pair and hierarchy operations. For features `i,j`, it ranks
only rows where both values are valid and estimates ordinary average-rank Spearman correlation.
The pair diagnostic records support, correlation, distance and whether support or rank variance
was insufficient. Unsupported pairs use distance one; they cannot merge at any declared cut.

The deterministic average-linkage hierarchy is cut three times:

| Absolute-correlation cut | Distance cut | Role |
|---:|---:|---|
| 0.85 | 0.15 | predeclared sensitivity |
| 0.90 | 0.10 | predeclared primary |
| 0.95 | 0.05 | predeclared sensitivity |

Cluster labels are canonicalized from their representative names rather than library-generated
integer labels. Representative priority is: highest caller-declared pre-outcome measurement
quality, highest valid training coverage, then lexically smallest stable feature name. Missing
quality scores default to an equal zero score. Quality scores supplied for an ineligible feature
are refused.

The optional first-PC representation uses centered raw cluster members and complete training
cases only; it does not impute. The loading sign is fixed so the largest-absolute loading is
positive, with lexical feature order breaking absolute-loading ties. A singleton has loading
`+1`. The apply path consumes saved centers/loadings and returns missing if any member is missing
or invalid. The training fingerprint contains only training values, eligible names and the
predeclared policy: mutation of a target or held-out value cannot change it.

## 7. Predictive model ladder (Step 4)

Step 4 consumes caller-supplied feature rows and targets; it does not construct a fold, inspect
real data or select a winning configuration. Both predictive classes use the same training-only
transform. For each ordered input feature, the transform saves the finite training median,
appends a separately named Boolean missing indicator, then saves the training center and scale of
all resulting columns. A zero-variance column receives scale one rather than being discarded.
Application uses this saved state exactly, so validation/test distribution changes cannot alter
imputation or scaling. The filled numeric value is a modelling transform accompanied by an
explicit missing indicator; it is not an assertion that the missing economic state was zero.

The transparent baseline is cyclic-coordinate elastic-net squared-error regression. Its artifact
saves the complete ordered transform, intercept, coefficient for every transformed column,
convergence state and frozen configuration. Correlated inputs remain present; no model-stage
univariate or correlation deletion is permitted.

The nonlinear challenger is squared-error gradient boosting over deterministic shallow CART
regression trees. Candidate thresholds are fixed quantiles of the transformed training design.
Each tree is bounded by the configured depth, leaf count and minimum leaf observations. Split
gain ties resolve by stable leaf, feature and threshold ordering. When validation rows are
supplied, their only authority is to choose the retained number of trees through predeclared
patience/minimum-improvement rules. Zero retained trees (the training-mean intercept) is valid.
Validation never affects the transform, candidate thresholds, split fitting or leaf values.

The pre-outcome structural grids are:

- elastic net: `alpha in {0.0001, 0.001, 0.01, 0.1, 1.0}` crossed with
  `l1_ratio in {0.1, 0.5, 0.9, 1.0}`;
- boosted trees: `(depth, leaves) in {(1,2), (2,4), (3,8)}`, learning rate in
  `{0.03, 0.05, 0.1}`, and minimum leaf size in `{10,25,50}`.

The grid is an immutable candidate registry, not an outcome-driven selection result. The model
module also exposes zero-return, training-mean and caller-declared state-only ridge baselines, a
common prediction result, and finite MSE/MAE, R-squared, correlation and directional-accuracy
metrics. Model JSON includes every apply-time quantity and uses stable key ordering.

## 8. Conditional out-of-sample usefulness (Step 5)

Step 5 consumes caller-supplied training, optional validation and evaluation rows. It neither
constructs a fold nor selects a model/configuration. A declared `ImportanceClusterDefinition`
records the complete correlated membership, the one or more columns that represent that cluster
in the supplied model rows, and its economic feature family. Representation columns must be a
partition: one model column cannot receive separate credit in two clusters.

For a cluster `g`, the fixed-model retraining estimand is

\[
I_g=R^2_{\mathrm{OOS,full}}-R^2_{\mathrm{OOS,drop}\ g},
\]

where both R-squared values use the training-target mean as the held-out benchmark. Positive
`I_g` means that dropping the complete cluster harmed future held-out fit. Zero and negative
values remain visible. Every drop fit relearns its preprocessing and predictor on the identical
supplied training rows; optional validation can only select boosted-tree stopping iteration under
the Step-4 rule. Evaluation rows and targets are apply/score-only. A family ablation uses the same
operation after removing every whole cluster assigned to that declared family.

Grouped block permutation keeps the full fitted model fixed. In the caller's ordered evaluation
rows, it partitions observations into contiguous blocks of the frozen size, deterministically
permutes equal-length block order, and jointly moves every representation column belonging to one
cluster. The trailing partial block cannot be exchanged with a differently sized block. Seeds are
derived deterministically from the frozen base seed, canonical cluster order and repeat number;
every repeat is published separately rather than searched for a favourable result.

All comparisons require the exact same unique ordered evaluation-row IDs. Their artifact retains
the full and comparator squared loss for every common row, their paired difference, and contiguous
loss-block sums/mean differences. These are uncertainty-ready inputs, not confidence intervals or
claims of independent observations. The artifact also records stable SHA-256 identities for the
resolved configuration, split row IDs, supplied data/targets and fitted full model, plus comparator
model or permuted-input identities as applicable. No impurity importance or SHAP quantity exists in
the Step-5 contract.

## 9. Cluster stability selection and aggregation (Step 6)

Step 6 accepts already-constructed walk-forward results. Each input names one fold, one fixed
model/configuration identity and one complete Step-3 cluster, along with eligible session IDs,
selection state, conditional delta OOS R-squared, optional fitted-effect direction, regime labels,
leave-one-session-out deltas, optional past-mirror and cost/latency-adjusted values, support and
Step-5 paired loss blocks. The aggregator sorts but never constructs, reassigns or refits a fold.
Every final row remains a cluster/model row; evidence is never divided among correlated members.

The frozen promotion rule is conjunctive. A cluster/model row requires at least 20 distinct
eligible sessions and five eligible folds; positive delta in at least 70% of folds; selection in
at least 70% of folds; at least 70% agreement among defined non-zero directions; a strictly
positive median delta; no supplied leave-one-session-out result that turns a positive full-fold
delta non-positive; a supplied past-mirror median no larger than the future median; and a strictly
positive supplied median cost/latency-adjusted value. Optional gates are evaluated whenever their
inputs are supplied and remain explicitly absent otherwise. Any result with fewer than 20 sessions
is `exploratory_insufficient_sessions`, including the hard one-session case. Other failures are
`rejected`; only a row clearing every applicable gate is `promoted`. Promotion here means a stable
research cluster candidate, not a trading, causal or deployment claim.

The final selection table publishes distinct session and fold counts, volatility/spread/time-phase
coverage, leave-one-session-out dominance, mirror/economic summaries, training/evaluation support,
support-indexed learning-curve summaries and the supplied block-loss differences. Block losses are
aggregated by their observation counts and retained fold by fold for later dependence-aware
uncertainty; Step 6 performs no inference.

The companion elastic-net stability path resamples supplied training rows only. It partitions the
caller's row order into contiguous blocks, selects blocks without replacement under every saved
seed, fits the already-frozen Step-4 elastic net, and marks a cluster selected if any coefficient
attached to any cluster model column or its explicit missingness column is nonzero. Artifacts carry
sampled row indices and cluster selection frequencies, not individual coefficients or individual
feature promotion.

## 10. Step 7 same-day nested walk-forward execution

Step 7 freezes a one-second UTC-aligned anchor grid as the primary **engineering sampling
convention** for the 2026-08-21 experiment. It does not change the target, causal gap, horizon,
reference price, unit or estimand. A five-second grid is a predeclared runtime/support
sensitivity, not an outcome-selected replacement.

The controller constructs three deterministic expanding outer folds. Each outer test is strictly
later than its training rows and is used exactly once. Before every validation/test boundary it
removes any training row whose target interval overlaps the boundary and applies an embargo of
`max(120 seconds, Z+h) = 120 seconds`. The final 20% of each purged outer-training prefix supplies
the inner validation block, with the same purge and embargo between inner train and validation.

Generic gates, surface gates, correlation estimation, cluster representatives, preprocessing,
elastic-net fitting, tree split thresholds and configuration selection all live inside the
relevant training fold. Inner validation chooses among the already-frozen Step-4 structural grids
and may choose tree stopping only. The selected stopping count is serialized in the candidate and
carried unchanged into outer-training and Step-5 refits; resetting to the predeclared estimator cap
is invalid. The outer test is apply/score-only. The model table compares zero, training-mean,
declared simple-state, elastic-net and shallow-tree forecasts on common rows.

The exact constructed common rows may be cached as deterministic gzip JSON only after binding the
cache to the trading date, grid, futures SHA, completed surface dataset ID and surface SHA. Cache
publication requires exact in-memory readback and a row-content fingerprint; reuse revalidates all
bindings against the current inputs. This cache changes no row, split or estimand and exists only
to avoid repeating the expensive canonical eSSVI replay after a downstream failure.

The empirical evidence pass applies Steps 5 and 6 to those frozen outer folds and selected model
configurations. It publishes whole-cluster and whole-family retraining ablations, grouped block
permutations, training-only elastic-net block resampling, frozen stability gates/reason codes,
gate and cluster tables, and volatility/spread/time-phase slices. Regime labels are fixed at
`zero`, `low_le_1`, `medium_le_5`, `high_gt_5` for lagged move scale; `tight_le_1`,
`normal_le_2`, `wide_gt_2` for spread ticks; and `open_first_60m`,
`mid_session_60_300m`, `close_after_300m` for minutes from open. Missing states remain explicit.

Long compute stages publish identity-bound recovery checkpoints only after exact artifact
readback. The controller checkpoints walk-forward selection before Step 5, including every
per-fold selected configuration and tree stopping count, then checkpoints each complete
fold/model conditional-usefulness artifact and each fold's elastic-net stability artifact. Every
checkpoint binds the common-row fingerprint, both source identities, resolved walk-forward
configuration, fold fingerprint, model identity and selected configuration. A mismatch fails
closed; an exact match resumes without refitting. Checkpointing changes no model, grid, split,
comparison or final artifact.

The completed surface/option-chain source is resolved by the explicit DAT dataset ID, status and
published tape SHA. Because its capture starts after the futures session, the combined experiment
uses only the exact intersection beginning with the first usable canonical surface frame. No
surface value is synthesized or carried backward.

The only eligible-session ID is `2026-08-21`. Consequently every empirical table and report is
hard-labelled `exploratory_insufficient_sessions`, regardless of point estimates. It supplies no
stability, causal, signal, confirmation, deployment, trading-promotion or order evidence.

## 11. Explicit exclusions through Step 7

Sparse group lasso, dependence-aware inference, confirmatory multi-session selection, costed
trading promotion and deployment remain later work. Step 7 constructs folds and performs the
approved same-day empirical fit, but cannot clear the Step-6 20-session stability gate. PCA remains
available only as the Step-3 cluster representation. No trade or deployment claim follows from
any Step 1--7 interface.

## 12. Acceptance tests

1. Registry names are unique and contain every frozen family/axis.
2. Target geometry is exactly anchor + 0.5 seconds to anchor + 10.5 seconds.
3. A future surface frame cannot alter an earlier row.
4. A different connection epoch cannot supply book/surface features.
5. Canonical LOB and CCZ source values pass through exactly.
6. EW innovations use only earlier surface frames.
7. Missing inputs stay `None`; interactions propagate missingness.
8. Every non-missing feature availability timestamp is at or before the anchor.
9. Deliberate post-anchor availability fails closed and is distinguishable from source
   missingness.
10. Stale, failed, unsupported or quality-incomplete surfaces invalidate economic surface
    fields without invalidating unrelated OFI/book fields.
11. Coverage, constancy and exact/affine duplicate decisions use declared training rows only.
12. Finite/range/schema failures are auditable and two identical inputs produce the same
    fingerprint and eligibility result.
13. Perfect positive and negative rank substitutes enter the same cluster because distance uses
    absolute Spearman correlation.
14. Pairwise missing observations produce explicit support diagnostics; insufficient pairs do
    not create a correlation or merge.
15. Mutating target or held-out feature values cannot alter pair diagnostics, maps,
    representatives, PCA state or the Step-3 training fingerprint.
16. Repeated fits produce identical pair order, canonical cluster IDs, sensitivity maps and
    representatives; singleton clusters remain valid.
17. First-PC center/loadings/sign are learned on complete training rows and applied without
    refitting; missing application members remain missing rather than becoming zero.
18. The artifact declares `cluster` as the only downstream importance unit and contains no
    target-derived importance.
19. The predictive transform learns median, center and scale from training rows only and appends
    a named missing indicator for every input without dropping zero-variance/correlated columns.
20. Elastic net retains correlated predictors, saves all coefficients/intercept/transform state,
    applies deterministically and produces finite predictions under missing input.
21. On a synthetic pure interaction, a depth-bounded boosted-tree challenger materially improves
    held-out squared error over elastic net without using held-out rows for thresholds/transforms.
22. Boosting respects depth/leaves/minimum-leaf bounds and early-stops solely against a supplied
    validation target; repeated fits are byte-for-byte deterministic.
23. Both predictive classes serialize/read back with identical predictions; zero, mean and state
    baselines use the common prediction and metric contracts.
24. No Step-4 test or implementation performs a real-data fit, hyperparameter/model selection,
    cluster importance, ablation, stability selection, fold construction or order-path action.
25. A synthetic known-signal cluster has positive full-minus-drop OOS R-squared while a declared
    noise cluster is near zero.
26. Redundant substitutes are removed and permuted jointly; no result ranks or allocates credit to
    either individual member.
27. Feature-family ablations remove complete declared clusters and publish the same full-model
    reference metrics.
28. Grouped permutation jointly moves all cluster representation columns in contiguous blocks;
    repeated runs with the same seeds are exactly deterministic.
29. A comparison on differing, reordered or duplicate row IDs fails rather than silently changing
    support; every valid result retains rowwise and contiguous-block paired losses.
30. Mutating evaluation targets can alter scores/data identity but cannot alter the fitted full
    model, resolved configuration or split identity.
31. The complete importance artifact serializes and reads back exactly with its cluster membership,
    support, metrics, deltas, directions, loss blocks and fingerprints intact.
32. A stable synthetic cluster supported by at least 20 distinct sessions and five folds clears
    every frozen gate, with its regime, loss-block, support and learning-curve diagnostics intact.
33. One-session evidence returns `exploratory_insufficient_sessions`, never stable or promoted.
34. An unstable fitted direction, one-session dominance or stronger past mirror independently
    produces a stable reason-coded rejection.
35. Contiguous-block elastic-net resampling is deterministic under saved seeds and selects a
    correlated cluster jointly when any member/model-column coefficient is nonzero; no individual
    coefficient or feature promotion appears in the artifact.
36. Both final Step-6 artifacts serialize and read back exactly, and repeated identical inputs
    produce identical fingerprints and results.
37. Every outer test follows its expanding training prefix, no outer-test row is reused, and both
    outer and inner boundaries satisfy target-overlap purge plus the frozen 120-second embargo.
38. Mutating future/test targets cannot change grid sampling or fold boundaries; outer test rows
    never enter a training index supplied to a gate, reduction, transform or predictor fit.
39. The one-second grid is deterministic and epoch-safe; the five-second sensitivity uses the
    identical implementation with only its declared grid width changed.
40. The walk-forward artifact serializes and reads back exactly, including fold identity,
    configuration, support, metrics, predictions and model fingerprints.
41. The empirical source record contains both input SHA-256 values and exact common support, and
    refuses a non-completed/unpinned DAT surface handle or changed futures tape hash.
42. Every one-session output carries `exploratory_insufficient_sessions` and no promotion/order
    field.
43. The inner-validation-selected boosted-tree stopping count is serialized and used unchanged by
    the corresponding outer-training and conditional-usefulness refits.
44. A materialization cache refuses a changed date, grid, futures SHA, surface dataset ID, surface
    SHA or row fingerprint, and a published cache reads back to rows exactly equal to its source.
45. The empirical output includes exact-readback Step-5 and Step-6 JSON plus model, gate, cluster,
    ablation, stability and regime-slice tables; every stability row retains the hard one-session
    exploratory status and explicit unavailable mirror/economic guards where inputs do not exist.
46. A matching walk-forward or fold/model checkpoint resumes without invoking its fit factory;
    changing any bound data/config/fold/model identity fails closed. No partial checkpoint is
    treated as complete.

## 13. Completion criterion

Steps 1--6 are complete at evidence level 2 when this specification, registry/construction,
gate, correlation-reduction, two-class predictive-model, conditional-cluster-usefulness and
cluster-stability code, traceability rows and focused deterministic tests are committed and
passing. No fold construction, real multi-session result, inference, empirical result, trading
promotion or order authority is required or claimed at this stage.

Step 7 is complete at evidence level 3 when its controller and leakage/split/readback tests pass,
the pinned 2026-08-21 inputs produce compact SHA-pinned artifacts, and the result is documented at
the exact one-session exploratory evidence boundary. This does not make the finding stable or
confirmatory.

The criterion was met on 2026-08-21. The dated empirical record is
`docs/results/D51-EXPLORATORY-RESULT-2026-08-21.md`. Its status is
`exploratory_insufficient_sessions`: no cluster/model pair is stable or promoted, and no signal,
deployment, economic-value or order claim follows.
