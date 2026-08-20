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

## 1. Objective and exact object

The monitor identifies and times **confirmed surface-relative executable mispricing** in the
listed index-option chain. It does not claim to observe an unobserved latent true option value.

For contract `i` at fit time `t`, let `P_hat(i,t)` be a strike-held-out eSSVI price and let
`u(i,t)` be an empirically calibrated uncertainty width. The fair band is:

```text
L(i,t) = max(0, P_hat(i,t) - u(i,t))
U(i,t) = P_hat(i,t) + u(i,t)
```

With executable best ask `A(i,t)` and bid `B(i,t)`:

```text
cheap gross edge = L(i,t) - A(i,t)
rich  gross edge = B(i,t) - U(i,t)
```

A positive gross edge is a **surface dislocation**. It becomes a confirmed mispricing only
after the cost, multiplicity, displayed-quantity, exact-refit, and persistence gates below.

## 2. Object and identification ledger

| Object | Category | Boundary |
|---|---|---|
| Contract BBO, displayed quantity, receive timestamp | Observed | Latest causal CON-01 row at or before `t`; never forward-filled past the freshness gate. |
| Strike-held-out eSSVI parameters and fair IV | Estimated | The target strike's CE and PE are absent from the reference fit. |
| Temporally smoothed held-out eSSVI | Estimated | Past-and-current raw fold fits only; 30-second half-life, twelve-fit cap, six consecutive fits before eligibility, no raw fallback. |
| Reference stability | Deterministically derived gate | Six-frame range of smoothed held-out fair IV and current raw-versus-smoothed fair-IV distance. |
| Black-76 fair price | Estimated | Inherits held-out surface, forward, maturity, rate, and model assumptions. |
| Fair-value uncertainty band | Estimated | Past-only empirical held-out residual plus forward/asynchrony stress and a tick floor. |
| Gross executable edge | Deterministically derived | Fair-band boundary minus executable quote, never midpoint-minus-fit. |
| Estimated transaction/exit/hedge cost | Scenario-based | Explicit versioned turnover rates and visible tick assumptions; not realised cost. |
| Net edge and per-lot edge | Scenario-based | Gross edge less estimated costs; lot size comes from the dated master. |
| Confirmed mispricing | Estimated classification | Requires all gates; means surface-relative, not fundamental truth. |
| Correction duration | Deterministically derived | Valid-frame episode clock; unavailable data is censoring, not correction. |
| Gap-close trace | Deterministically derived attribution | Signed target-option and held-out reference-market contributions from confirmation to close. Both are market movements; the split identifies the traded target leg versus the reference cross-section and is not a causal claim. |

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
  contributing quote as the source/staleness timestamp. The default half-life is 30 seconds and
  at most twelve raw fits are retained.
- `MIS-EST-07`: a fold is in smoothing warm-up until six consecutive accepted raw fits have been
  incorporated. Reset its smoother after a gap above 15 seconds, an instrument-scope change, or
  an expiry-set change. A raw or reset-first fit can populate diagnostics but cannot generate an
  opportunity.
- `MIS-EST-08`: before testing an observation, require six consecutive smoothed fair-IV readings
  for that contract, a maximum-to-minimum range no larger than 0.25 volatility points, and a
  current raw-versus-smoothed fair-IV distance no larger than 0.50 volatility points. All limits
  are payload-visible policy, not hidden constants.
- `MIS-EST-09`: the exact leave-strike raw refit must retain the same direction and its fair IV
  must lie within 0.50 volatility points of the stable fold-smoothed fair IV. The actionable fair
  price and band remain those of the stable smoothed fold; an isolated exact raw refit may confirm
  robustness but may not replace the stable benchmark.

## 6. Uncertainty and multiplicity (`MIS-VAL-*`)

- `MIS-VAL-01`: maintain past-only held-out midpoint-minus-fair-price residuals by absolute
  expiry, moneyness bucket, and relative-spread bucket.
- `MIS-VAL-02`: do not classify a bucket before 100 past residuals by default. Warm-up is an
  explicit status, never zero uncertainty.
- `MIS-VAL-03`: model uncertainty is the empirical 99th percentile of absolute past residuals
  with a one-tick floor.
- `MIS-VAL-04`: forward uncertainty reprices at the future/parity band edges.
- `MIS-VAL-05`: quote-asynchrony uncertainty is delta times the larger of the forward band and
  the past-only 99th-percentile forward movement over the target's quote age.
- `MIS-VAL-06`: total uncertainty is the maximum of the tick, empirical-model, forward, and
  asynchrony widths. This conservative maximum avoids adding overlapping error estimates.
- `MIS-VAL-07`: derive an empirical tail probability from the past residual bucket and apply
  Benjamini-Hochberg at `q=1%` across the current outside-band, positive-net candidates.

## 7. Economic gate (`MIS-EXEC-*`)

- `MIS-EXEC-01`: cheap uses the current ask; rich uses the current bid. Midpoints are never
  executable prices.
- `MIS-EXEC-02`: estimate direction-specific buy/sell turnover charges at entry and fair-value
  exit, plus visible exit- and hedge-slippage tick floors.
- `MIS-EXEC-03`: require strictly positive after-cost edge and at least one displayed lot.
- `MIS-EXEC-04`: show gross rupees/unit, gross ticks, net rupees/unit, net ticks, and net
  rupees/lot together. A statistical dislocation that is uneconomic remains unconfirmed.

These are observer-only economic calculations. They do not estimate fill probability and do
not authorise either a taker or maker order.

## 8. Episode lifecycle (`MIS-STATE-*`)

```text
ELIGIBLE -> CANDIDATE -> FDR + EXACT CONFIRMED -> PENDING
PENDING -- same direction for 2 valid fits --> ACTIVE
ACTIVE -- frozen entry target gap closed for 2 valid fits --> CORRECTED
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
- `MIS-STATE-06`: for a cheap episode, target contribution is `A_close - A_entry` and reference
  contribution is `L_entry - L_close`; for a rich episode they are `B_entry - B_close` and
  `U_close - U_entry`. Positive values close the gap, negative values widen it, and their signed
  sum must equal `entry_gap - close_gap` to numerical tolerance.
- `MIS-STATE-07`: among positive closing contributions, a >=60% share is labelled
  `target-option-led` or `reference-market-led`; otherwise the trace is `mixed`. The closing gate
  (`inside_uncertainty_band`, `after_cost_edge_nonpositive`, direction reversal, or lost
  qualification) is separately visible. These are endpoint accounts, not causal claims.
- `MIS-STATE-08`: freeze the entry reference boundary, entry executable quote, estimated entry
  cost, and after-cost target gap at activation. A cheap target corrects only after its ask has
  risen by at least the frozen entry net edge; a rich target corrects only after its bid has fallen
  by at least that amount. The test is quote-side identification, not a fill or exit-P&L claim.
- `MIS-STATE-09`: when the ordinary live residual loses qualification for two valid frames but
  `MIS-STATE-08` is not met, close the episode as `INVALIDATED`. Reference-led, mixed, stability-
  lost, multiplicity-lost and exact-confirmation-lost resolutions remain visible but cannot enter
  the corrected-opportunity count or correction-duration sample.

## 9. Required dashboard and API output (`MIS-OUT-*`)

The ANL-03 screen adds a full-width panel below the surface with:

- monitor status, eligibility, tested/outside/FDR/exact/pending/active counts;
- smoothing warm-up/unstable counts and the complete smoothing/stability policy;
- an **Active confirmed** table sorted by net edge;
- a **Recently corrected / invalidated / censored** table preserving outcomes;
- contract, side, executable market price, fair price/band, gross/net ticks, net/lot, IV
  residual, quote age, first/close clock and duration;
- entry gap, signed target-option contribution, signed held-out reference-market contribution,
  net gap closed, frozen target-correction requirement/achievement, categorical attribution,
  corrected/invalidated outcome, closing gate, or censor reason;
- smoothed fair IV, contemporaneous raw fair IV, raw-smoothed IV distance, six-frame smoothed-IV
  range, smoothing component count, and benchmark-stability state.

`/api/state` and `/api/history` must carry the full policy, lifecycle, assumptions and rows.
History playback must show the episode state frozen into that frame rather than today's state.

## 10. Acceptance tests

- Synthetic Black-76 inversion round trip.
- A clean chain warms without producing an active claim.
- A deliberately cheap fresh contract survives fold-screen, BH-FDR, exact strike exclusion,
  one-lot and two-frame gates.
- Returning its ask to fair value closes only after two valid frames and records a
  target-option-led trace with duration from first breach and an exact gap-accounting identity.
- A raw reference jump cannot activate during smoothing warm-up or while either IV-stability limit
  is breached.
- Two fits with the same oldest contributing quote but later decision timestamps are smoothed
  causally rather than falling back to a raw surface.
- A residual that disappears solely because the reference boundary moves is `INVALIDATED`, has no
  correction timestamp, and does not enter the corrected-opportunity duration sample.
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
