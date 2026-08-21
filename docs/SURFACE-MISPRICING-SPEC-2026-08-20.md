# Surface-relative executable option-mispricing monitor

- **Requirement:** `REQ-ANL-07` / `ANL-07`
- **Approved by:** Aryan Ayyar, 2026-08-20
- **Status:** frozen implementation specification
- **Authority:** read-only research analytics; no order, signal, or live-execution authority

**Owner amendment 1, 2026-08-20:** the original `market-led` / `surface-led` wording was
misleading because the held-out surface is itself built from market prices. Attribution is now
named `target-option-led` / `reference-market-led` / `mixed`, and every row must expose the signed
endpoint accounting rather than only a categorical label.

**Owner amendment 2, 2026-08-20:** a raw five-second refit is not a sufficiently stable reference
for identifying a target-option opportunity. Every strike-held-out fold must therefore pass the
causal temporal-smoothing and benchmark-stability gates in `MIS-EST-06`--`MIS-EST-09`. The entry
reference is frozen when an episode activates. A disappearing live residual is `CORRECTED` only
when the target executable quote itself closes the frozen entry after-cost gap; a residual closed
by reference movement, mixed movement that misses that target, or benchmark instability is
`INVALIDATED`, not a corrected opportunity.

**Owner-amendment-2 live calibration revision, 2026-08-20 (historical; superseded by owner
amendment 4 below):** the initial 30-second/six-frame
implementation still admitted the same 1 September 24450 CE twice; both episodes then resolved
reference-led without meeting the frozen target test. The binding defaults at that time became one
minute: 60-second half-life, twenty-four-fit cap, twelve consecutive fits/readings, and 0.10
volatility-point smoothed-range, raw-smoothed, and exact-smoothed limits. Any invalidation clears
that contract's reference history and forces a fresh twelve-frame warm-up before re-entry. The two
superseded live episodes remain retained as calibration evidence and are not opportunity results.

**Owner amendment 3, 2026-08-20:** live trace evidence showed that a stable eSSVI fair IV does
not imply a stable rupee fair-band boundary. One episode disappeared when a hard residual bucket
changed and the empirical price uncertainty jumped; another disappeared when the option forward
moved while the target/reference IV residual remained broadly intact. The binding identification
state is therefore the target's **executable implied-volatility residual** against a causally
smoothed strike-held-out fair-IV band. Empirical uncertainty is estimated continuously from
past-only neighbouring observations in log-moneyness and relative-spread space; hard bucket
boundaries are prohibited. The entry executable IV, fair-IV boundary, uncertainty calibration,
and after-cost IV target are frozen at activation. Rupee price edge remains a contemporaneous
execution overlay, never the correction state. Every active and closed row also reports a
frozen-delta, executable-quote markout as an explicitly scenario-based diagnostic rather than a
fill or realised P&L claim.

**Owner amendment 4, 2026-08-21:** the twelve-frame/0.10-volatility-point stability rule is
superseded. Five-second IV can move materially over a minute without making the held-out reference
invalid, so the binding warm-up and stability window is six consecutive frames and the binding
smoothed-range, raw-versus-smoothed, and exact-versus-smoothed agreement tolerance is 0.50
volatility points. The causal 60-second parameter-smoothing half-life, twenty-four-fit cap,
15-second reset gap, exact leave-strike refit, two-frame episode confirmation, uncertainty,
cost, liquidity, and multiplicity gates are unchanged.

**Owner amendment 5, 2026-08-21:** the rolling stability-window gate is removed altogether and
the causal parameter-smoothing half-life is increased from 60 to 120 seconds. The smoother still
requires six accepted raw fits before eligibility, and the current raw-versus-smoothed and exact-
versus-smoothed 0.50-volatility-point agreement checks remain point-in-time robustness gates.
There is no per-contract rolling max-minus-min IV test and no stability-history rebuild after an
episode invalidates. All independent-reference, uncertainty, cost, liquidity, multiplicity,
exact-refit, and two-frame lifecycle gates are unchanged.

## Approved specification change — owner amendment 5

**Requirements affected:** `MIS-EST-06`, `MIS-EST-08`, `MIS-STATE-10`, `MIS-OUT-01`

**Superseded requirement:** 60-second smoothing half-life plus a six-reading rolling smoothed-IV
range no larger than 0.50 volatility points and a six-reading rebuild after invalidation.

**Approved requirement:** 120-second smoothing half-life; no rolling stability window, no rolling
IV-range threshold, and no post-invalidation stability-history rebuild. Six-fit smoother warm-up
and the current 0.50-point raw/exact agreement checks remain.

**Reason:** the EMA already defines the temporal reference. Rejecting its recent movement with a
second rolling range gate adds redundant inertia and can reject a cleanly moving volatility
surface.

**Effect on interpretation:** eligibility depends on a slower causal fair-IV estimate plus current
raw/exact robustness, not on the smoothed reference having remained inside an arbitrary recent
range.

**Effect on outputs/comparability:** current policy reports a 120-second half-life and
`reference_stability_window_enabled=false`; current rows expose smoother component count and
point-in-time eligibility rather than a stability range. Historical frames retain their embedded
older policy and fields.

**Approval:** explicitly approved by Aryan Ayyar on 2026-08-21 with instruction to implement and
update the dashboard immediately.

## Approved specification change — owner amendment 4

**Requirements affected:** `MIS-EST-07`, `MIS-EST-08`, `MIS-EST-09`, `MIS-STATE-10`

**Superseded requirement:** twelve consecutive fits/readings and 0.10-volatility-point
smoothed-range/raw-smoothed/exact-smoothed limits.

**Approved requirement:** six consecutive fits/readings and 0.50-volatility-point
smoothed-range/raw-smoothed/exact-smoothed limits.

**Reason:** one minute of ordinary executable IV movement can exceed 0.10 volatility points, so
the old absolute-range rule rejected a moving but usable reference.

**Effect on interpretation:** the detector admits faster and larger legitimate surface movement;
all independent-reference, execution, statistical, and lifecycle semantics remain unchanged.

**Effect on outputs/comparability:** policy fields and dashboard labels expose the new values;
pre-amendment and post-amendment frames remain distinguishable by their embedded policy.

**Alternative rejected:** retaining twelve frames and merely widening the limit, because the owner
identified the one-minute window itself as the primary defect.

**Approval:** explicitly approved by Aryan Ayyar on 2026-08-21 with instruction to implement and
update the live dashboard immediately.

## 1. Objective and exact object

The monitor identifies and times **confirmed surface-relative executable mispricing** in the
listed index-option chain. It does not claim to observe an unobserved latent true option value.

For contract `i` at fit time `t`, let `sigma_hat(i,t)` be the causally smoothed strike-held-out
eSSVI fair IV and let `u_sigma(i,t)` be an empirically calibrated IV uncertainty width. The
primary fair-IV band is:

```text
sigma_L(i,t) = max(0, sigma_hat(i,t) - u_sigma(i,t))
sigma_U(i,t) = sigma_hat(i,t) + u_sigma(i,t)
```

Invert the executable ask and bid with the same current forward, maturity and rate to obtain
`sigma_A(i,t)` and `sigma_B(i,t)`:

```text
cheap gross IV edge = sigma_L(i,t) - sigma_A(i,t)
rich  gross IV edge = sigma_B(i,t) - sigma_U(i,t)
```

A positive gross IV edge is a **surface dislocation**. Convert `sigma_L` and `sigma_U` to
current Black-76 rupee boundaries only after that classification. It becomes a confirmed
mispricing only after the current rupee edge also clears costs and the multiplicity,
displayed-quantity, exact-refit, and persistence gates below.

## 2. Object and identification ledger

| Object | Category | Boundary |
|---|---|---|
| Contract BBO, displayed quantity, receive timestamp | Observed | Latest causal CON-01 row at or before `t`; never forward-filled past the freshness gate. |
| Strike-held-out eSSVI parameters and fair IV | Estimated | The target strike's CE and PE are absent from the reference fit. |
| Temporally smoothed held-out eSSVI | Estimated | Past-and-current raw fold fits only; 120-second half-life, twenty-four-fit cap, six accepted fits before eligibility, no raw fallback. |
| Reference eligibility | Deterministically derived gate | Six-fit smoother warm-up and current raw-versus-smoothed fair-IV agreement; no rolling stability window or max-minus-min IV gate. |
| Executable bid/ask IV | Deterministically derived | Black-76 inversion of the current bid/ask using the same current forward, maturity and rate as the fair IV. |
| Continuous IV uncertainty | Estimated | Past-only distance-weighted empirical tail from same-expiry/type neighbours in continuous log-moneyness and log-relative-spread space; no hard moneyness or liquidity bucket. |
| Black-76 fair price | Estimated | Inherits held-out surface, forward, maturity, rate, and model assumptions. |
| Fair-IV uncertainty band | Estimated | Maximum of the continuous past-only empirical held-out IV residual, forward/asynchrony IV stress and the option-tick-equivalent IV floor. |
| Gross executable IV edge | Deterministically derived | Fair-IV boundary minus executable ask IV for cheap, or executable bid IV minus fair-IV boundary for rich. |
| Gross executable rupee edge | Deterministically derived overlay | Current Black-76 IV-boundary price minus executable quote; never used as the episode correction state. |
| Estimated transaction/exit/hedge cost | Scenario-based | Explicit versioned turnover rates and visible tick assumptions; not realised cost. |
| Net edge and per-lot edge | Scenario-based | Gross edge less estimated costs; lot size comes from the dated master. |
| Frozen-delta markout | Scenario-based proxy | Entry-to-current executable liquidation quote plus a single frozen entry-delta future hedge and explicit estimated costs; excludes fills, queue, dynamic re-hedging, funding and realised hedge execution. |
| Confirmed mispricing | Estimated classification | Requires all gates; means surface-relative, not fundamental truth. |
| Correction duration | Deterministically derived | Valid-frame episode clock; unavailable data is censoring, not correction. |
| IV-gap-close trace | Deterministically derived attribution | Signed executable target-IV and held-out reference-IV contributions from confirmation to close. Both are market-derived; the split identifies the target leg versus the reference cross-section and is not a causal claim. Rupee endpoint accounting remains an overlay. |

## 3. Required inputs

- Latest two-sided option and matching-future CON-01 BBO rows and receive timestamps.
- Contract expiry, strike, CE/PE identity.
- Date-stamped option tick and lot size from the Dhan instrument master; replay may use an
  explicit CLI fallback, which must be labelled as such.
- Current risk-free-rate assumption.
- Existing SUR-02 eSSVI implementation and SUR-05 no-arbitrage gates.
- Explicit fee/slippage policy. Default turnover rates use the schedule verified 2026-08-13;
  every payload exposes the numeric rates and version.

## 4. Causal eligibility gates (`MIS-DATA-*`)

- `MIS-DATA-01`: use only observations received no later than the fit timestamp.
- `MIS-DATA-02`: target and reference quotes must be two-sided, uncrossed, quality-valid, and
  no older than 3 seconds by default.
- `MIS-DATA-03`: the base fit must be no older than 10 seconds and pass butterfly/calendar
  checks.
- `MIS-DATA-04`: the target must lie inside the held-out fit's observed strike support. No
  extrapolated contract may be called mispriced.
- `MIS-DATA-05`: the held-out fit must retain the minimum per-expiry quote support.
- `MIS-DATA-06`: at least one dated lot must be displayed on the relevant executable side;
  unknown lot size or insufficient BBO quantity cannot be actionable.
- `MIS-DATA-07`: both executable bid and ask must admit finite Black-76 IV inversions under the
  same current forward, maturity and rate used by the reference surface.

## 5. Independent fair value (`MIS-EST-*`)

- `MIS-EST-01`: deterministically partition each expiry's sorted strikes into five folds.
  Both CE and PE at every held-out strike are excluded together.
- `MIS-EST-02`: fit one constrained eSSVI reference surface per fold on fresh quotes only.
- `MIS-EST-03`: use a matching traded future where present. Otherwise construct a robust
  parity forward as the median of the remaining fresh CE/PE strike-pair forwards, with a
  10th-to-90th percentile/spread band. The held-out target strikes cannot supply the forward.
- `MIS-EST-04`: price each held-out contract with Black-76 using its fair IV, forward,
  maturity, rate, and call/put type.
- `MIS-EST-05`: exact-refit every multiplicity-surviving candidate after excluding only its
  complete strike pair. A fold-screen candidate that fails or changes direction is rejected.
- `MIS-EST-06`: update a separate causal eSSVI parameter smoother for every deterministic
  cross-fit fold. Use the fit decision timestamp as the decay clock while retaining the oldest
  contributing quote as the source/staleness timestamp. The default half-life is 120 seconds and
  at most twenty-four raw fits are retained.
- `MIS-EST-07`: a fold is in smoothing warm-up until six consecutive accepted raw fits have been
  incorporated. Reset its smoother after a gap above 15 seconds, an instrument-scope change, or
  an expiry-set change. A raw or reset-first fit can populate diagnostics but cannot generate an
  opportunity.
- `MIS-EST-08`: before testing an observation, require the fold smoother to contain at least six
  accepted raw fits and require the current raw-versus-smoothed fair-IV distance to be no larger
  than 0.50 volatility points. No rolling per-contract stability window or max-minus-min IV test
  is permitted. The point-in-time agreement limit is payload-visible policy, not a hidden constant.
- `MIS-EST-09`: the exact leave-strike raw refit must retain the same direction and its fair IV
  must lie within 0.50 volatility points of the fold-smoothed fair IV. The actionable fair
  IV and IV band remain those of the smoothed fold; an isolated exact raw refit may confirm
  robustness but may not replace the stable benchmark.
- `MIS-EST-10`: direction is defined in executable IV space: ask IV below the fair-IV lower
  boundary is cheap; bid IV above the fair-IV upper boundary is rich. Mid-IV residuals supply the
  empirical tail probability but can never replace executable-side direction.

## 6. Uncertainty and multiplicity (`MIS-VAL-*`)

- `MIS-VAL-01`: maintain past-only held-out midpoint-IV-minus-fair-IV residual samples separately
  by absolute expiry and CE/PE. Each sample retains continuous log-moneyness and log-relative
  spread. Hard moneyness/spread buckets are prohibited.
- `MIS-VAL-02`: query the nearest 500 past samples by default using standardised Euclidean
  distance with 0.02 log-moneyness and 1.0 log-relative-spread bandwidths. Use Gaussian distance
  weights for the empirical quantile and tail probability. Do not classify before at least 100
  past neighbours; warm-up is explicit, never zero uncertainty.
- `MIS-VAL-03`: empirical model uncertainty is the weighted 99th percentile of absolute IV
  residuals. The payload exposes neighbour count and Kish effective sample size.
- `MIS-VAL-04`: forward uncertainty is the maximum fair-IV-equivalent change obtained by holding
  the central fair price fixed and re-inverting it at the future/parity band edges.
- `MIS-VAL-05`: quote-asynchrony uncertainty converts the existing delta-times-forward-motion
  price stress into an exact local IV-equivalent width.
- `MIS-VAL-06`: the option tick floor is converted to a local IV-equivalent width. Total IV
  uncertainty is the maximum of tick, empirical-model, forward, and asynchrony IV widths. This
  conservative maximum avoids adding overlapping estimates.
- `MIS-VAL-07`: derive a distance-weighted empirical tail probability from the continuous
  past-neighbourhood and apply
  Benjamini-Hochberg at `q=1%` across the current outside-band, positive-net candidates.
- `MIS-VAL-08`: uncertainty history is updated only after the current decision. Observations that
  are currently outside the band are excluded so an active dislocation cannot teach the model
  that it is ordinary noise.

## 7. Economic gate (`MIS-EXEC-*`)

- `MIS-EXEC-01`: cheap uses the current ask; rich uses the current bid. Midpoints are never
  executable prices.
- `MIS-EXEC-02`: estimate direction-specific buy/sell turnover charges at entry and fair-value
  exit, plus visible exit- and hedge-slippage tick floors.
- `MIS-EXEC-03`: require strictly positive after-cost edge and at least one displayed lot.
- `MIS-EXEC-04`: show gross rupees/unit, gross ticks, net rupees/unit, net ticks, and net
  rupees/lot together. A statistical dislocation that is uneconomic remains unconfirmed.
- `MIS-EXEC-05`: map the positive after-cost rupee edge at activation into an entry-forward
  executable-IV move. This frozen IV move is the target correction requirement.
- `MIS-EXEC-06`: report a frozen-delta quote markout. Cheap uses current bid minus entry ask minus
  entry Black-76 delta times the forward change; rich uses entry bid minus current ask plus entry
  delta times the forward change. Deduct direction-specific current round-trip turnover and the
  visible slippage floors for the net diagnostic. Label it a scenario proxy, never P&L or fill.

These are observer-only economic calculations. They do not estimate fill probability and do
not authorise either a taker or maker order.

## 8. Episode lifecycle (`MIS-STATE-*`)

```text
ELIGIBLE -> CANDIDATE -> FDR + EXACT CONFIRMED -> PENDING
PENDING -- same direction for 2 valid fits --> ACTIVE
ACTIVE -- frozen entry executable-IV target closed for 2 valid fits --> CORRECTED
ACTIVE -- live qualification lost for 2 valid fits without target correction --> INVALIDATED
ACTIVE -- stale/missing/failed/unsupported --> CENSORED
```

- `MIS-STATE-01`: `first_seen_at` is the first qualifying frame, not the later confirmation.
- `MIS-STATE-02`: direction must remain the same across two consecutive five-second fits.
- `MIS-STATE-03`: correction requires two consecutive valid frames with non-positive net edge.
- `MIS-STATE-04`: missing/stale quote, fit failure, support loss, feed loss, close, or expiry is
  censoring. It is never silently labelled correction.
- `MIS-STATE-05`: duration is `corrected_or_censored_time - first_seen_at`; active rows show a
  live duration.
- `MIS-STATE-06`: for a cheap episode, target contribution is
  `ask_IV_close - ask_IV_entry` and reference contribution is
  `fair_IV_lower_entry - fair_IV_lower_close`; for a rich episode they are
  `bid_IV_entry - bid_IV_close` and `fair_IV_upper_close - fair_IV_upper_entry`. Positive values
  close the IV gap, negative values widen it, and their signed sum must equal
  `entry_IV_gap - close_IV_gap` to numerical tolerance.
- `MIS-STATE-07`: among positive closing contributions, a >=60% share is labelled
  `target-option-led` or `reference-market-led`; otherwise the trace is `mixed`. The closing gate
  (`inside_uncertainty_band`, `after_cost_edge_nonpositive`, direction reversal, or lost
  qualification) is separately visible. These are endpoint accounts, not causal claims.
- `MIS-STATE-08`: freeze the entry fair-IV boundary, executable ask/bid IV, continuous uncertainty
  calibration, and after-cost IV target at activation. A cheap target corrects only after ask IV
  rises by that target; a rich target corrects only after bid IV falls by that target. Absolute
  rupee movement cannot satisfy correction. The test is quote-side IV identification, not a fill
  or exit-P&L claim.
- `MIS-STATE-09`: when the ordinary live residual loses qualification for two valid frames but
  `MIS-STATE-08` is not met, close the episode as `INVALIDATED`. Reference-led, mixed, stability-
  lost, multiplicity-lost and exact-confirmation-lost resolutions remain visible but cannot enter
  the corrected-opportunity count or correction-duration sample.
- `MIS-STATE-10`: invalidation does not reset the fold smoother or create a contract-specific
  re-warm requirement. A contract may become pending again only by satisfying every ordinary
  current eligibility, statistical, economic, exact-refit and two-frame persistence gate.

## 9. Required dashboard and API output (`MIS-OUT-*`)

The ANL-03 screen adds a full-width panel below the surface with:

- monitor status, eligibility, tested/outside/FDR/exact/pending/active counts;
- smoothing warm-up/reference-rejection counts and the complete smoothing/agreement policy,
  including an explicit `stability window: off` disclosure;
- an **Active confirmed** table sorted by net edge;
- a **Recently corrected / invalidated / censored** table preserving outcomes;
- contract, side, executable market price, fair price/band, gross/net ticks, net/lot, IV
  residual, quote age, first/close clock and duration;
- entry gap, signed target-option contribution, signed held-out reference-market contribution,
  all primarily in IV points, net IV gap closed, frozen target-correction
  requirement/achievement, categorical attribution,
  corrected/invalidated outcome, closing gate, or censor reason;
- continuous uncertainty neighbour count/effective sample size and empirical, forward,
  asynchrony, tick-equivalent and total IV widths;
- current gross/net rupee execution overlay and frozen-delta gross/net markout per unit and lot;
- smoothed fair IV, contemporaneous raw fair IV, raw-smoothed IV distance, smoothing component
  count, and point-in-time reference-eligibility state. No rolling stability range is shown.

`/api/state` and `/api/history` must carry the full policy, lifecycle, assumptions and rows.
History playback must show the episode state frozen into that frame rather than today's state.

## 10. Acceptance tests

- Synthetic Black-76 inversion round trip.
- A clean chain warms without producing an active claim.
- A deliberately cheap fresh contract survives fold-screen, BH-FDR, exact strike exclusion,
  one-lot and two-frame gates.
- Returning its ask to fair value closes only after two valid frames and records a
  target-option-led IV trace with duration from first breach and an exact IV-gap identity.
- A pure forward move that changes option prices but leaves executable IV unchanged cannot satisfy
  target correction.
- Target executable-IV convergence can satisfy correction even when a simultaneous forward move
  makes the absolute option price fall.
- Crossing the former hard relative-spread bucket boundary cannot discontinuously change the
  empirical uncertainty estimate; neighbour and effective sample sizes remain visible.
- Frozen-delta markout arithmetic is sign-correct for cheap and rich episodes and is labelled as a
  scenario proxy.
- A raw reference jump cannot activate during smoothing warm-up or while the current raw-smoothed
  or exact-smoothed agreement limit is breached.
- Two fits with the same oldest contributing quote but later decision timestamps are smoothed
  causally rather than falling back to a raw surface.
- A residual that disappears solely because the reference boundary moves is `INVALIDATED`, has no
  correction timestamp, and does not enter the corrected-opportunity duration sample.
- Invalidation does not impose a separate rolling-history rebuild; ordinary two-frame confirmation
  and all current qualification gates still apply before reactivation.
- A displayed quantity below one lot never becomes actionable.
- A missing target quote censors an active episode rather than calling it corrected.
- Base-fit/arbitrage/support failure paths remain explicit.
- Dashboard payload/history/rendering expose both tables and the complete policy.
- Source audit proves no order/execution dependency.
- Focused tests, full pytest, Ruff, strict mypy, and compileall pass.

## 11. Explicit exclusions and evidence level

- No claim of latent fundamental value, arbitrage, profitability, fill, or causality.
- No unsupported strike or maturity extrapolation.
- No order placement, strategy influence, alert-to-order bridge, or live authorisation.
- No promotion from Tested/Dry-run verified to Live verified until a real live chain has run
  through warm-up, produced (or validly produced zero) classifications, and payload semantics
  have been checked against retained rows.
