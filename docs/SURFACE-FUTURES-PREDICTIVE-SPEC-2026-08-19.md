# eSSVI surface to five-second futures-mid move — frozen exploratory specification

**Scan ID:** `X-SURFACE-FUT5-20260819-06`

**Ledger row:** `SIG-06X`

**Frozen:** 2026-08-19, before implementation and before any joined surface/futures outcome was inspected

**Confirmatory eligible:** `false`

This scan is permanently exploratory because the 2026-08-19 tape, dashboard and surface behaviour
have already been inspected. “Past-only” and “causal timing” below mean absence of look-ahead in
construction. They do **not** identify a causal economic effect. No result may be called confirmed,
economic, tradeable, a strategy, or a signal.

## Claim and estimand

At each successful displayed eSSVI frame anchored at time `t`, ask whether the surface shape known by
`t` helps predict the front NIFTY future's BBO-midpoint change after a 500 ms decision gap. The
primary response, in NIFTY ticks (Rs 0.05), is

`Y_future(t) = [mid_asof(t + 5.5 s) - mid_asof(t + 0.5 s)] / 0.05`.

The descriptive objects are feature-level Pearson and Spearman correlations. The predictive
estimand is chronological held-out OOS R2 against the training-sample mean response, plus the paired
incremental OOS R2 from adding the surface-economic block to the same-sample LOB+OFI model:
`Delta R2 = R2(LOS) - R2(LO)`. All model comparisons use identical target rows.

## DATA — pinned tape, replay and timing

- **DATA-01 — immutable input.** Use only
  `/Users/maheit/Documents/Shaurya/data/live-captures/anl03-live/sha-20260819T063412.584779Z-0a555c5b/tape_sha-20260819T063412.584779Z-0a555c5b.jsonl`,
  expected SHA-256 `f85b4bdb4c6cce15664849dbf7405d89d35b89a258a2834d94acb0004108a28f`,
  5,496,592 rows and 9,149,464,566 bytes. The captured interval is
  2026-08-19 06:34:12.585–10:14:16.499 UTC (about 12:04–15:44 IST). The front target instrument is
  exactly `NSE:NSE_FNO:NIFTY:future:2026-08-25`. No capture, subscription or broker call is allowed.
- **DATA-02 — depth boundary.** This is the Dhan Quote/Full stream. The future rows contain the
  embedded **five-level** book; they are not depth20 or depth200. Every same-sample LOB/OFI result is
  therefore a five-level result.
- **DATA-03 — surface replay parity.** Reuse `SurfaceEngine` unchanged with expiries
  `2026-08-25`, `2026-09-01`, `2026-09-29`; `fit_interval_seconds=5.0`; the existing forward selector,
  risk-free rate, quote filters, eSSVI constraints, no-arbitrage gates, interpolation policy,
  `ESSVITemporalSmoother(half_life_seconds=15, max_history=12)`, and `StalenessPolicy` unchanged.
  The research object is the surface actually emitted/displayed: smoothed when SUR-07 accepts it,
  otherwise the honestly labelled raw fit. Smoothing status and refusal/reset reason remain data.
- **DATA-04 — unit and availability.** One observation is retained per successful fit frame after a
  same-expiry previous successful frame exists and the complete trailing 5 s OFI history exists.
  All predictors use rows with receive time `<= t`. The current future book is the latest valid
  five-level state at or before `t` in the same connection epoch.
- **DATA-05 — response as-of guard.** Each response endpoint uses the last valid front-future BBO at
  or before the requested timestamp. The state age at both endpoints must be `<= 6.0 s`, the existing
  `instrument_dead_seconds` threshold; both endpoint states and the frame anchor must share one
  connection epoch; the future series must extend to at least `t+5.5 s` in that epoch. Missing,
  one-sided, crossed, invalid-depth, sequence-gap, connection-gap, heartbeat-timeout or epoch-crossing
  endpoints are missing, never filled or set to zero.
- **DATA-06 — controls.** The identical-geometry past mirror is
  `Y_past(t) = [mid_asof(t - 0.5 s) - mid_asof(t - 5.5 s)] / 0.05`. The same-window diagnostic is
  `Y_same(t) = [mid_asof(t) - mid_asof(t - 5.0 s)] / 0.05`. They use the same 6 s age, epoch and
  coverage guards and are reported separately from the future estimand.
- **DATA-07 — exclusions.** No current forward/futures price level enters the surface-economic
  block because it mechanically contains the target market's level. Forward changes are not part of
  the headline. Gross limit additions and cancellations are unidentified under snapshot coalescing.

## SURFACE — exact economic and quality features

For expiry `e`, let the emitted eSSVI slice at `t` have maturity `T_e`, parameters
`theta_e, rho_e, psi_e`, and total variance

`w_e(k) = 0.5 * [theta_e + rho_e psi_e k + sqrt((psi_e k + rho_e theta_e)^2 + theta_e^2(1-rho_e^2))]`.

Require fitted support to contain `k=0`. The exact ATM features are:

- `atm_iv_e = sqrt(theta_e / T_e)`;
- `atm_skew_e = d sigma/dk|0 = rho_e psi_e / (2 sqrt(T_e theta_e))`;
- `atm_curvature_e = d2 sigma/dk2|0 = psi_e^2 (1 - 2 rho_e^2) /
  (4 sqrt(T_e) theta_e^(3/2))`.

Tests compare both analytic derivatives with stable central finite differences strictly inside the
fitted support. The parameter and shape level family per expiry is
`{theta, rho, psi, atm_iv, atm_skew, atm_curvature}`. For every member `x`, also emit the one-frame
change `delta_1f_x = x_t - x_previous` and velocity
`velocity_x_per_second = delta_1f_x / (t - t_previous)`, matching expiry by absolute date.

For each adjacent maturity pair `(2026-08-25,2026-09-01)` and
`(2026-09-01,2026-09-29)`, emit later-minus-earlier differences in
`{atm_iv, atm_skew, atm_curvature}` plus their one-frame changes and per-second velocities. Theta and
ATM IV are deliberately both retained and expected to be collinear; Ridge, cluster-level language
and explicit correlation diagnostics prevent an individual-theta importance claim.

The **SURFACE quality** block is separately identifiable and never silently merged into the economic
headline: weighted R2, weighted RMSE in total variance, total used quote count, each expiry's quote
count and support width, surface age, fit duration, feed/worst-instrument age, stale-instrument count,
packet rate, reconnect count, surface-stale indicator, smoothed indicator, reset indicator,
raw-unsmoothed indicator/reason category, smoothing component count/fallback alpha where available,
and arbitrage-pass/freshness flags. Non-numeric reason categories are one-hot encoded from
training-observed categories only; unseen held-out categories map to an explicit `other` indicator.

## LOB — five-level terminal state at or before t

Let bid/ask prices, quantities and displayed order counts at level `l` be
`b_l,a_l,qb_l,qa_l,nb_l,na_l`, with all five levels required.

- `spread_ticks = (a_1-b_1)/0.05`.
- `microprice_tilt_ticks = [(a_1 qb_1 + b_1 qa_1)/(qb_1+qa_1) - (a_1+b_1)/2]/0.05`;
  zero quantity denominator is missing.
- Per-level quantity imbalance `qi_l=(qb_l-qa_l)/(qb_l+qa_l)`, `l=1,...,5`, and cumulative
  `qi_cum_D=(sum_{l<=D}qb_l-sum_{l<=D}qa_l)/(sum_{l<=D}qb_l+sum_{l<=D}qa_l)` for `D in {1,5}`.
- Bid/ask displayed totals through five levels and their `log1p` transforms.
- Per-level order-count imbalance `oi_l=(nb_l-na_l)/(nb_l+na_l)` and cumulative level-five order
  imbalance; zero denominators are missing.
- Average-order-size proxies are `sum qb/sum nb` and `sum qa/sum na` through five levels plus
  `log((1+bid_proxy)/(1+ask_proxy))`. These are displayed-quantity-per-displayed-order proxies, not
  observed order identity or lifetime.
- Book shape uses cumulative quantity. For each side fit the unweighted five-point quadratic
  `distance_l_ticks = beta0 + beta1*log1p(cumulative_quantity_l) + beta2*log1p(cumulative_quantity_l)^2`,
  where distance is outward from that side's best. Emit bid/ask `beta1` slopes, `beta2` curvatures,
  and ask-minus-bid slope/curvature asymmetries. Singular fits are missing.

## OFI — five-level flow over the trailing five seconds

- **OFI-01 canonical CKS L1.** Sum the existing `cks_l1_transition` increment over `(t-5s,t]`.
  The exact sign convention is bid strengthening/ask depletion positive and ask strengthening/bid
  depletion negative. No second CKS formula may be implemented.
- **OFI-02 price-keyed marginal flow.** For consecutive valid five-level snapshots, key quantity by
  absolute price, assign a price the shallowest rank occupied in either endpoint, remove only an
  identified one-level outer-window slide under the existing boundary-churn rule, sign bid changes
  positive and ask changes negative, then sum marginal bands `level_1` and `levels_2_5` over
  `(t-5s,t]`. This is price identity, not naive rank differencing.
- **OFI-03 depth adjustment.** Divide CKS by causal mean half-L1 displayed depth, and each marginal
  band by its causal mean total displayed quantity in that band over snapshots in `(t-5s,t]`.
  Denominator floor is one contract; a band absent from any covered snapshot is missing.
- **OFI-04 robustness windows.** The same objects may be emitted at `{0.5,1,2,10}s` only as
  predeclared robustness. The ranked headline remains the 5 s block; no window is selected from test
  outcomes.

## EST — common sample and chronological prediction

The primary complete-case sample is the intersection of the future target and **all** numeric
features needed by S, quality, L and O at the 5 s lookback. Every primary model is evaluated on
these identical rows:

- **N:** training-mean response benchmark (also report the literal zero/no-price-change RMSE).
- **S:** surface economic block.
- **SQ:** S plus the separately identified quality block.
- **L:** multivariable five-level LOB block.
- **O:** multivariable five-level OFI block.
- **LO:** LOB + OFI.
- **LOS:** LOB + OFI + surface economic.
- **LOSQ:** LOS + quality, separately labelled robustness.

All fitted models are Ridge with an intercept. Numeric standardisation, zero-variance removal,
reason-category vocabulary and transformations are learned on training rows only. Alpha is selected
from `{0,.01,.1,1,10,100}` by lowest mean MSE over three chronological expanding inner folds with a
120 s embargo and deterministic lowest-alpha tie-break. Test outcomes never choose alpha.

Split the single session chronologically: first 70% of eligible rows is training; the next 120
seconds is embargo; the remainder is held out. Report exact clock bounds and support. Split the held-
out interval into chronological halves and report both halves without refitting or retuning.
Negative OOS R2 remains visible. Main inference is paired `LOS-LO` held-out squared-error
improvement; also report S versus L, O and LO and the `LOSQ-LOS` quality increment.

## CORR/ROB — dependence, multiplicity and placebos

- **CORR-01:** For every surface-economic feature report Pearson and Spearman correlation with
  `Y_future`, `Y_past` and `Y_same`, on the identical complete-case geometry. Report full-sample and
  held-out correlations separately. For future rows, also report its signed standardized Ridge
  coefficient and mean absolute held-out contribution in S and LOS where defined.
- **CORR-02:** For each of the three target families, compute correlation p-values using HAC
  covariance with lag 2 fit frames (at least the response overlap) and apply Benjamini-Hochberg FDR
  across the entire declared surface-economic feature family. No iid p-value claim is allowed.
- **ROB-01:** Paired held-out model-error improvements report Newey-West/HAC lag 2, a deterministic
  within-session stationary block bootstrap with expected block length 6 frames, and non-overlapping
  10-second calendar-block means. Report all three; do not turn a single threshold crossing into a
  confirmation claim.
- **ROB-02:** The past mirror is mandatory and uses the same split/model/common-row protocol. The
  same-window fit is a construction diagnostic only.
- **ROB-03:** A predeclared lag placebo replaces the current surface economic block with its value
  from at least 300 seconds earlier in the same epoch, without circular wrap, and refits LOS versus
  LO on the resulting same rows. It is a diagnostic, not an alternative selected model.
- **ROB-04 freshness:** primary = every displayed successful surface. Repeat S/SQ/LO/LOS/LOSQ on
  rows with `surface_age_seconds <= 480`, preserving the primary split clock. Also emit a labelled
  core-freshness sensitivity at `<=240s` (half the existing threshold), if both train and test retain
  at least 20 rows. Never refit a different surface or alter thresholds after outcomes.
- **ROB-05:** Report smoothing engagement, raw-unsmoothed reasons, surface-age distribution,
  feature collinearity, common-sample attrition, target as-of ages, failed fits, epoch failures and
  stale-wing risk. Surface-quality apparent gain is judged by `SQ-S` and `LOSQ-LOS`, not folded into
  the surface-economic headline.

## Comparison boundary

The primary comparison is this tape's same-sample five-level S/L/O/LO/LOS horse race. Separately
contextualise against `docs/OFI-HORSERACE-2026-08-19.md` and
`docs/OFI-PREDICTIVE-SCAN-2026-08-19.md`. Those use two different DAT-20 depth200/depth20 tapes and
different anchor clocks; headline R2 values are explicitly non-apples-to-apples and may not be
compared as if they came from one sample.

## OUT/VAL — artifacts and completion gates

- **OUT-01:** Full machine outputs under gitignored `artifacts/surface-futures-predictive/`:
  summary JSON, observation/feature table, correlations, model scores, coefficients/contributions,
  paired inference, robustness/freshness rows, support/attrition and a manifest with source/code/output
  hashes and exact CLI. Writes are deterministic at seed `20260819`.
- **OUT-02:** Commit a compact result summary and compact CSV/table under `docs/results/`, the
  plain-English report `docs/SURFACE-FUTURES-PREDICTIVE-2026-08-19.md`, and frozen-requirement
  traceability `docs/SURFACE-FUTURES-PREDICTIVE-SPEC-COVERAGE-2026-08-19.md`. Hash-pin every ignored
  artifact in the committed summary.
- **VAL-01:** Tests cover exact target timing and cadence, as-of age/epoch/right-edge guards,
  analytic skew/curvature versus finite differences, feature formulas, common complete cases,
  training-only scaling/category/CV, quality isolation, canonical CKS reuse/sign, price-keyed OFI,
  missing denominators, stale filters, past mirror, placebo timing and deterministic output.
- **VAL-02:** Run targeted tests, full Python suite, repository Ruff, strict mypy, compileall,
  `git diff --check`, deterministic replay/hash checks and a staged secret scan. Record counts and
  warnings. `docs/sig-claims/H-SIG21.md` must remain byte-for-byte unchanged.
- **VAL-03:** Update `TASKS.md` row `SIG-06X` and `CHANGELOG.md`. No live system, credential,
  subscription, broker write, order or strategy promotion is in scope.

## Completion criterion

Complete means all identified frozen features, models, correlations, controls, freshness arms,
dependence checks, artifacts, hashes, traceability and verification evidence are produced from the
pinned full tape; appropriate files are committed and pushed; and the isolated repository ends
clean with local `HEAD == origin/main`. Any unsupported quantity remains explicit and makes the
overall status incomplete if required rather than being silently omitted.
