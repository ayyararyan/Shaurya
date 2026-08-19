# Event-flow claims (`EF`) — SIG-03

Taxonomy cell: **event flow**. Signed trade flow, order-flow imbalance at level 1 and
multi-level, add/cancel/trade arrival intensities per side per level, cancellation rate,
queue-depletion rate, trade-size distribution, message intensity.

Status of this file: **round 1 of the story-by-story debate, opened 2026-08-19.** Claims
below are `Proposed` until Aryan accepts them. Nothing here is tested.

---

## 0. The object, stated precisely before anything is claimed

Two things are routinely conflated and must not be. Under `CON-06` they are different
objects with different identification status and different maker consequences.

- **Queue imbalance** \(I^{(1)}_t=(Q^b_t-Q^a_t)/(Q^b_t+Q^a_t)\) is a **state**. It is a
  book-state feature and belongs to `BK`, not here.
- **Order-flow imbalance (OFI)** is a **flow** — the signed innovation in best-quote depth
  over an interval. Cont, Kukanov and Stoikov (2014) define, per best-quote event \(n\),

  \[
  e_n=\mathbb 1\{P^b_n\ge P^b_{n-1}\}q^b_n-\mathbb 1\{P^b_n\le P^b_{n-1}\}q^b_{n-1}
     -\mathbb 1\{P^a_n\le P^a_{n-1}\}q^a_n+\mathbb 1\{P^a_n\ge P^a_{n-1}\}q^a_{n-1},
  \]

  with \(\mathrm{OFI}_k=\sum_{n\in k}e_n\) over interval \(k\), and
  \(\Delta m_k\approx \beta\,\mathrm{OFI}_k\) with \(\beta\) inversely related to depth.

Sign convention used throughout, fixed once (working contract §15.3):
\(\mathrm{OFI}>0\) is **net buy pressure** — bid side strengthening, ask side depleting.
Maker side \(s=+1\) is a resting **ask** (a sale), \(s=-1\) a resting **bid**.
Markout \(\mathrm{AM}_h=s\,(p_{\mathrm{fill}}-m_{t+h})\); **positive is good for the maker**.

## 1. The maker's governing derivative

For a resting quote at distance \(d\) in state \(x\),

\[
V_s(d,x)=P(\mathrm{fill}\mid d,x)\;\Big[\,E\{\mathrm{AM}_h\mid \mathrm{fill},d,x\}-c\,\Big].
\]

Take the derivative with respect to OFI for a resting **ask**:

\[
\frac{\partial V_{+}}{\partial \mathrm{OFI}}
=\underbrace{\frac{\partial P}{\partial \mathrm{OFI}}}_{>0}\big[E-c\big]
+P\underbrace{\frac{\partial E}{\partial \mathrm{OFI}}}_{<0}.
\]

Buy pressure depletes the ask queue, so it **raises** fill probability; the same buy
pressure means the mid is drifting up, so conditional on being hit the markout is
**worse**. The two channels have opposite signs and the total is **ambiguous a priori**.
This is the precise sense in which OFI is not maker alpha: it trades **fill rate against
fill quality**, and which dominates is an empirical quantity, not a modelling preference.

**The one unambiguous corner, and it is the corner we are in.** As
\(E-c\to 0^{+}\) — the marginal regime the maker report's governing presumption places
liquid NIFTY in — the first term vanishes and \(\partial V_{+}/\partial\mathrm{OFI}<0\)
unconditionally. Where quoting is barely profitable, additional flow into your side is
purely harmful. **This is the formal justification for treating OFI as a withdrawal /
skew gate rather than an entry signal, and it is a derivation, not an assertion.**

The bid side is the mirror: buy pressure grows the bid queue (fill probability falls) but
a bid that *does* fill in a rising market fills well. Same sign on both channels per side,
opposite across sides. A signal with this structure cannot be pure alpha for a maker.

## 2. Three mechanisms, not one

OFI's association with price change has three distinct sources with different maker
consequences. Any test that does not separate them is uninterpretable.

| Mechanism | Nature | Horizon | Maker consequence |
|---|---|---|---|
| **Accounting / mechanical** | The mid *is* a function of queue depletion. Same-window OFI-to-\(\Delta m\) is an identity, not a forecast. | Contemporaneous | None. Must be netted out or it manufactures fake R². |
| **Inventory / liquidity** | Suppliers reprice to manage inventory, then replenish. Transient impact. | Seconds; mean-reverts | The maker is **paid** to absorb this. Lean in. |
| **Information / adverse selection** | Kyle (1985), Glosten–Milgrom (1985): signed flow carries private information. Permanent impact. | Persistent | The maker is **run over**. Withdraw. |

**The entire maker question about OFI reduces to separating mechanism 2 from mechanism 3
in time to cancel.** That is why `SIG-14` (Hasbrouck VAR, permanent vs transitory) is not
an optional robustness check here — it is the load-bearing test, and `EF-08` states it.

## 3. What our feed actually permits — the binding constraint

`DAT-16` establishes that the 20-level depth channel is a **fixed 500 ms snapshot feed at
2.00 bursts/second**, not an event stream. The CKS estimator above is defined over
best-quote *events*. We do not observe events. Three consequences, in increasing severity:

1. **Adds and cancels net inside the window.** \(\Delta D_k=A_k-C_k-T_k\) identifies net
   flow, not the gross components. Eisler, Bouchaud and Kockelkoren (2012) show event
   types carry distinct impact; that decomposition is **partially unavailable to us** and
   bounded rather than point-identified (D23).
2. **OFI is exactly identified only in price-stationary windows.** When the best price does
   not move across a snapshot pair, the depth delta at a fixed price *is* net flow at that
   price and the CKS sign convention needs no sequence information. When the best price
   **moves** within the window, the convention requires knowing the event order, and we see
   only endpoints. **The censoring is therefore concentrated in exactly the informative
   states.** This biases measured OFI predictability *downward* in the states that matter —
   a feature-level selection problem, distinct from the queue-ahead bound width of D23.
   `EF-07` makes it a measured quantity with a carried flag rather than a footnote.
3. **`D27` truncates the admissible horizon from below.** OFI predictability in the
   literature is measured on event-time data at zero latency. Our reaction path is
   500 ms snapshot cadence + transport + decision + `MK-01` cancel acknowledgement. Any
   OFI decay that completes inside that window is **unavailable by construction**, not
   merely hard to capture. This is the strongest single reason to expect the published
   taker OFI result not to transfer, and it is a structural inference, not a measurement.

**A capture-driven ranking that follows immediately.** `DAT-14` measured 36.1% of print
intervals coalesced, with observed last quantities covering only **44.3%** of cumulative
volume — so more than half of traded volume carries no attributable sign. Depth-delta OFI
uses the *complete* quantity change on the depth channel; signed-trade-flow imbalance uses
a sign available for a minority of volume. On **this feed**, OFI should dominate signed
trade flow. That is `EF-05`, and it is a consequence of our own measurement rather than a
preference imported from the literature.

## 4. India / NSE specifics that change the prior

- **Where queue signals work best is where the cost floor bites hardest.** Gould and Bonart
  (2016) find imbalance predicts most strongly in **large-tick** assets. On the maker
  report's own measurement the ₹0.05 tick binds only below roughly ₹21 premium; above that,
  spread is a level, not a floor (elasticity 1.05, R² 0.79). So the large-tick regime where
  `EF-03`-type queue effects should be strongest is precisely the low-premium regime where
  the statutory round trip of ₹0.0474/unit consumes about one full tick. **The regime
  selection is adversarial to us and must be pre-registered as a stratification, not
  discovered** — this is `D26` applied to `EF`.
- **Contested-signal risk.** NSE's April 2023 mode data attribute 50.22% of
  equity-derivatives turnover to colocation. Touch-level OFI is the single most-computed
  quantity in the market, and every colocated participant has it before our snapshot fires.
  Any surviving `EF` edge is therefore more plausibly in *slower, less-contested*
  transforms — multi-level, cross-asset, or resilience-conditioned — than at the touch.
- **Option books are thin.** Multi-level OFI presumes populated depth. A 20-level book on
  an OTM option is largely empty, so `EF-06` must be tested **separately for futures and
  options** and is expected to fail for options — where the informative object is the
  cross-asset version (underlying-futures OFI into option quotes, `XA`).

---

## 5. Claims

| ID | Claim | Status | Depends on |
|---|---|---|---|
| `EF-01` | Contemporaneous sufficiency — a **data-quality gate, not a signal** | Proposed | DAT-14, DAT-16 |
| `EF-02` | OFI predicts future mid beyond the same-window identity, at horizons above the `D27` cadence bound | Proposed | EF-01, D27 |
| `EF-03` | **Maker core:** OFI raises same-side fill probability *and* worsens fill-conditioned markout | Proposed | MK-02, MK-03, EXE-09/10 |
| `EF-04` | **Decision claim:** an OFI-conditioned no-quote/widen gate raises the *lower bound* of maker value | Proposed | EF-03, MK-01, MK-04 |
| `EF-05` | Depth-delta OFI dominates signed-trade-flow imbalance **on this feed** | Proposed | DAT-14 |
| `EF-06` | Multi-level OFI adds over L1 in futures, saturating at a measurable depth; adds nothing in options | Proposed | DAT-13, SIG-10 |
| `EF-07` | OFI identification degrades in price-moving windows, measurably | Proposed | DAT-16, D23 |
| `EF-08` | **Load-bearing:** the permanent/transitory split of OFI impact determines whether the maker leans in or withdraws | Proposed | SIG-14, EF-03 |
| `EF-09` | **Tick-binding gradient (Gould–Bonart):** queue-signal informativeness is monotone decreasing in spread-in-ticks | Proposed | D26, BK cell |
| `EF-10` | The **front-of-queue reference policy** establishes the level against which every gate is measured | Proposed | DAT-14 |

### `EF-01` — Contemporaneous sufficiency is a data-quality gate, not a signal

- **Mechanism.** Mechanical. Over a window in which the best price moved, the move is an
  arithmetic consequence of net signed depth change at the touch. Cont, Kukanov and
  Stoikov (2014) report short-interval price changes approximately linear in OFI with
  slope inversely related to depth.
- **Capture.** Same-window regression of \(\Delta m_k\) on \(\mathrm{OFI}_k\) from
  consecutive depth20 snapshots, per instrument, with depth interacted.
- **Confirming.** High same-window \(R^2\) and \(\hat\beta\) declining in depth with the
  right sign and plausible magnitude.
- **Falsifying.** Low \(R^2\). **A failure here is a verdict on our OFI construction,
  cross-channel alignment or snapshot handling — not a finding about the market.** No `EF`
  claim may be tested until this passes.
- **`CON-06`.** Deterministically derived from observed depth deltas.
- **Explicit prohibition.** This \(R^2\) is never reported as predictive performance and
  never enters `SIG-15`'s OOS comparison. It is an instrument check.

### `EF-02` — OFI predicts future mid beyond the same-window identity

- **Mechanism.** Inventory repricing and information both leave residual drift after the
  interval in which the flow arrived.
- **Capture.** Strictly-lagged labels only (`SIG-09`). Predict \(m_{t+h}-m_t\) from
  \(\mathrm{OFI}_{\le t}\) at \(h\in\{1,2,5,10,30\}\) s, **excluding horizons below the
  binding feed cadence** and stating the exclusion (`D27`). Control for current microprice
  and spread, because a microprice-derived target regresses a definition on itself
  (`SIG-09`).
- **Confirming.** OOS \(R^2>0\) against a no-change benchmark (Campbell–Thompson) with a
  stable sign, after `SIG-11` dependence-aware inference and `SIG-12` grid control.
- **Falsifying.** All apparent predictability sits at \(h\le\) cadence — i.e. it is
  `EF-01`'s identity leaking through timestamp inversion; or it vanishes after microprice
  and spread controls.
- **`CON-06`.** Estimated.

### `EF-03` — Maker core: OFI moves fill rate and fill quality in opposite directions

- **Mechanism.** §1. Depletion of the far queue raises the probability our resting order
  reaches the front; the same flow is the drift that makes the fill adverse.
- **Capture.** Two separate estimands, never one regression.
  (a) \(\partial P(\mathrm{fill}\mid \text{ask})/\partial\mathrm{OFI}\) from the `EXE-09`
  censored hazard run over `EXE-10`'s **feasible queue paths**, reported as an interval
  \([P_L,P_U]\), never a point.
  (b) \(\partial E[\mathrm{AM}_h\mid\mathrm{fill},\text{ask}]/\partial\mathrm{OFI}\) from
  `ANL-01` markouts, Greek-adjusted for options.
- **Confirming.** (a) > 0 **and** (b) < 0, on both sides with the mirrored signs of §1,
  stable across `VOL-04` regimes (`SIG-16`).
- **Falsifying.** (b) ≈ 0 — OFI is pure volume and harmless, so no gate is warranted; or
  (a) ≈ 0 — either the effect is absent or `EXE-10`'s bounds are too wide to resolve it,
  and **those two must be distinguished by bound width, not assumed apart**.
- **`CON-06`.** Estimated with reported bounds; `EXE-10`'s interval propagates into both
  derivatives (D23).
- **Known confounder to pre-register.** Fills are a selected sample. \(E[\mathrm{AM}]\)
  conditional on fill is not \(E[\mathrm{AM}]\), and the unconditional predictive power of
  OFI **understates** its cost to a maker. Any test that estimates (b) on unconditional
  returns is measuring the wrong object.

### `EF-04` — An OFI-conditioned withdrawal gate raises the lower bound of maker value

- **Mechanism.** §1's marginal-regime corner: where \(E-c\to0^{+}\), \(\partial
  V/\partial\mathrm{OFI}<0\) unconditionally, so suppressing quotes in high same-side OFI
  states removes negative-value fills faster than positive-value ones.
- **Capture.** Replay quoting with and without the gate through `NAT-07`'s deterministic
  C++ replay (`D14`), with `BKT-06` measured decision latency and `MK-01` cancel latency
  injected. Value measured at the **conservative lower bound** of the `EXE-09` fill
  envelope, after `MK-04`'s statutory ledger and peak margin.
- **Confirming.** Lower-bound \(V\) rises, and the gain survives the foregone-fill count.
- **Falsifying.** The gate removes more good fills than bad; or the improvement exists only
  at the point estimate and disappears at the lower bound; or the OFI reading arrives too
  late to cancel — in which case the claim fails on **latency, not on economics**, and that
  distinction must be reported, because the two imply different remedies.
- **`CON-06`.** Scenario-based — it is a counterfactual quoting policy, not realised P&L.

### `EF-05` — Depth-delta OFI dominates signed trade flow on this feed

- **Mechanism.** Not economic — a measurement-coverage argument. `DAT-14`: only 44.3% of
  cumulative volume is sign-attributable; the depth channel's quantity delta is complete.
  Ellis, Michaely and O'Hara document non-trivial classification error even where signs
  exist.
- **Capture.** Matched OOS comparison of the two feature families on identical `EF-03`
  targets, same folds, same grid.
- **Confirming.** OFI wins on OOS log loss for the fill target and markout target.
- **Falsifying.** Signed flow wins or ties despite its coverage gap — which would imply the
  sign carries information the net quantity delta destroys, and would be a genuinely
  informative negative result about netting.
- **`CON-06`.** Deterministically derived (OFI) versus estimated with a versioned
  classifier (`DAT-14` sign).

### `EF-06` — Multi-level OFI adds over L1 in futures, not in options

- **Mechanism.** Cao, Hansch and Wang (2009) find information beyond the touch; Cont,
  Cucuringu and Zhang integrate level-wise OFI. Against this, deep displayed size is cheap
  to post and cheap to cancel.
- **Capture.** Level-wise OFI indexed by **distance in ticks from the touch, never by
  vendor level number**, because level identity shifts when the best price moves. Combined
  per `SIG-10` at cluster level, since level-wise OFIs are strongly collinear and
  individual importances are meaningless.
- **Confirming.** Incremental OOS value over L1 OFI, saturating at a stable depth; and the
  saturation depth is itself reported as a finding.
- **Falsifying.** No incremental value; or value disappears when depth is measured in
  rupees rather than contracts; or the deep levels evaporate before price reaches them.
  For **options**, near-empty books are expected to falsify it outright — record that
  expectation now so a null is not retrofitted as a prediction.
- **`CON-06`.** Deterministically derived. Note `DAT-13`: the 200-level channel has a real
  first-subscription throttle, so any depth200 test carries a capture-bias caveat.

### `EF-07` — OFI identification degrades measurably in price-moving windows

- **Mechanism.** §3.2. Endpoint-only observation of a 500 ms window leaves event order
  unresolved whenever the best price moved inside it.
- **Capture.** Run the `EXE-10` feasible-event set \(\mathcal E_k\) for the OFI statistic
  itself, producing \(\mathrm{OFI}_k\in[\mathrm{OFI}_k^L,\mathrm{OFI}_k^U]\). Report bound
  width by price-moved indicator, activity, TOD, tier and instrument.
- **Confirming.** Bound width is systematically larger in price-moving windows.
- **Falsifying.** Width is invariant to price movement — which would mean the netting
  window is not binding at current NSE index-F&O event rates, materially good news.
- **`CON-06`.** Estimated with reported bounds. **Every downstream `EF` result must carry
  the censoring flag**; a point OFI silently substituted for the interval is exactly the
  unlabelled-proxy failure `SIG-07` and `EXE-10` exist to prevent.

### `EF-08` — The permanent/transitory split decides lean-in versus withdraw

- **Mechanism.** §2. Transient inventory pressure is what a maker is *paid* to absorb;
  permanent information impact is what runs a maker over. The same OFI reading implies
  opposite actions depending on which it is.
- **Capture.** Hasbrouck (1991) VAR on (order flow, quote revision) per `SIG-14`; impulse
  response decomposed into permanent and transitory components, estimated **conditional on
  the resilience state** (refill speed after matched shocks) rather than unconditionally.
- **Confirming.** A state-conditional split exists, is stable out of sample and across
  adjacent contracts, and is **observable early enough to act on given `MK-01` cancel
  latency**.
- **Falsifying.** The split is not identifiable at our cadence; or it is identifiable only
  *after* the point at which the quote could still have been cancelled — in which case OFI
  is descriptively interesting and operationally useless, which is a legitimate and
  publishable-internally verdict.
- **`CON-06`.** Estimated.
- **Standing note.** `EF-08` is the claim on which the maker value of the entire event-flow
  cell rests. `EF-03` establishes that OFI hurts; `EF-08` decides whether it is *avoidable*
  harm or *compensated* risk.

### `EF-09` — Queue-signal informativeness is monotone decreasing in spread-in-ticks

- **Mechanism.** Gould and Bonart (2016) find queue imbalance predicts most strongly in
  **large-tick** assets, where the tick is a binding constraint on price competition and
  queueing therefore carries the competition that the price cannot. The maker report's own
  measurement gives us a rare *within-market* version of this: the ₹0.05 tick binds only
  below roughly ₹21 premium; above it, spread is a level (elasticity 1.05, R² 0.79). A
  single option chain therefore spans the large-tick and small-tick regimes **at the same
  instant, in the same underlying, under the same information environment.**
- **Why this is worth more than a correlation.** The prediction is a **gradient, not a
  level** — informativeness must *fall* as spread-in-ticks rises. A gradient is far harder
  to produce by accident than a level, and it tests the tick-binding *mechanism* rather
  than the mere presence of a queue effect.
- **The confound that must be pre-registered, because it is fatal if ignored.**
  Spread-in-ticks is correlated with illiquidity. A negative gradient is equally consistent
  with "queue signals work better in liquid contracts" — nothing to do with the tick.
  The identifying comparison is therefore **contracts matched on depth, order count and
  print activity but differing in premium**, within the same chain and expiry.
- **`CON-06`.** Estimated. Depends on `BK`'s imbalance construction as well as `EF`'s OFI.

### `EF-10` — The front-of-queue reference policy fixes the level

- **Mechanism.** Not a market claim — a **measurement construct**, registered as a claim
  because everything downstream is measured as a difference against it. For every
  `DAT-14`-signed print at the ask, a maker resting at the **front** of the ask queue would
  have sold at the ask. Markout follows with **no queue model at all**.
- **Why it matters operationally.** It **does not depend on `EXE-10`**. It makes the
  maker-side question measurable on tape we are already collecting, months before the
  queue-bound estimator exists.
- **Honest framing, recorded so it is not overclaimed later.** This is *not* a bound.
  Front-of-queue is the most favourable position, which pushes value **up**; never
  cancelling is the worst policy, which pushes value **down**. The two deviations run in
  opposite directions and do not compose into a one-sided bound. It is a well-defined
  reference policy, and its scientific value is that gates are evaluated as **differences**
  against it, which is far more robust than any level.
- **Consequence for `MK-05`.** A negative reference level is **not** by itself the kill
  result. The kill requires a negative reference **and** no gate recovering it (`EF-04`).
- **`CON-06`.** Deterministically derived from observed prints and quotes, given `DAT-14`'s
  versioned classifier.

---

## 6. Hypothesis register

Bound per `METHOD.md` §2. Every axis fixed; `Z` graded for admissibility; `K` in stated
units; ex-ante MDE required before execution. Hypothesis IDs are `<CLAIM>/H<n>`, stable.

**Reaction-path placeholder.** `MK-01` has not measured `R`. Until it does, all
admissibility grading uses declared placeholder arms `R ∈ {500, 900, 1500}` ms
(cadence-only optimistic / central / conservative). Every verdict below is **provisional on
`R`** and is re-graded, not re-run, when `MK-01` lands.

### Summary

| ID | Claim | Runs on tape we are collecting now? | Blocking dependency |
|---|---|---|---|
| `EF-01/H1` | EF-01 | **Yes — run first, it gates everything** | — |
| `EF-02/H1` | EF-02 | **Yes** (futures) | — |
| `EF-02/H2` | EF-02 | **Yes** (options) | — |
| `EF-03/H1` | EF-03 | **Yes — reduced form, front-of-queue** | — |
| `EF-03/H2` | EF-03 | No | EXE-10, ANL-01 |
| `EF-04/H1` | EF-04 | **Yes** (nuisance model, declared to stop it becoming a free parameter) | — |
| `EF-04/H2` | EF-04 | **Yes — the decision test** | EF-04/H1, EF-10/H1 |
| `EF-05/H1` | EF-05 | **Yes** | — |
| `EF-06/H1` | EF-06 | **Yes** (futures; depth200 arm carries the DAT-13 caveat) | — |
| `EF-07/H1` | EF-07 | **Yes — pure measurement** | — |
| `EF-08/H1` | EF-08 | **Yes** | — |
| `EF-09/H1` | EF-09 | **Yes — imbalance arm** | — |
| `EF-09/H2` | EF-09 | **Yes — OFI arm** | — |
| `EF-10/H1` | EF-10 | **Yes — best-powered thing we can run** | — |

Twelve of fourteen run on tape alone. **The maker question is measurable now.**

---

### `EF-01/H1` — Contemporaneous instrument gate

| Axis | Binding |
|---|---|
| **X** | Depth-delta OFI at the touch, CKS sign convention over consecutive depth20 snapshots. `CON-06`: deterministically derived |
| **h₁** | 500 ms (one snapshot interval) |
| **f₁** | 2.00 Hz depth20 clock (`DAT-16`) |
| **Y** | Δ mid, in ticks. `CON-06`: observed |
| **h₂** | 500 ms |
| **f₂** | 2.00 Hz, same snapshot pairs |
| **Z** | **0 — deliberately.** Permanently descriptive |
| **Stratum** | NIFTY and BANKNIFTY front-month futures separately; options by `D26` premium band |
| **K** | β in **ticks per 100 contracts of OFI**; same-window R²; and β × median touch depth, which should be O(1) tick if the construction is sound |
| **G contribution** | 7 (2 futures + 5 premium bands) |
| **Confirm** | R² ≥ 0.25, β > 0, and β **decreasing in touch depth** across activity terciles |
| **Falsify** | R² < 0.10. **This is a verdict on our OFI construction, cross-channel alignment or snapshot handling — not on the market.** No other `EF` hypothesis may execute until this passes |
| **Admissibility** | Descriptive, permanent. Never enters an OOS comparison or economic gate |

*Threshold note, flagged as challengeable:* CKS report R² ≈ 0.65 at 10 s with event-level
equity data. 500 ms snapshot netting should reduce this materially, so 0.25 is a judgement
about how much degradation is tolerable, not a literature value.

### `EF-02/H1` — OFI predicts future mid beyond the identity (futures)

| Axis | Binding |
|---|---|
| **X** | Depth-delta OFI, cumulative |
| **h₁** | {1, 2, 5} s |
| **f₁** | 2.00 Hz |
| **Y** | Mid change in ticks, **controlling for microprice−mid and spread-in-ticks at time t** (`SIG-09` anti-tautology: an uncontrolled microprice target regresses a definition on itself) |
| **h₂** | {2, 5, 10, 30} s |
| **f₂** | 2.00 Hz |
| **Z** | {0.5, 1, 2} s |
| **Stratum** | NIFTY, BANKNIFTY front-month futures × TOD buckets (09:15–11:00 / 11:00–14:00 / 14:00–15:40) |
| **K** | OOS R² against no-change (Campbell–Thompson) **and** β in ticks per +1 SD of OFI, SD reported in contracts |
| **G contribution** | 3 × 4 × 3 × 2 × 3 = **216** |
| **MDE** | ≈ 0.0008 OOS R² at t\* ≈ 4.2 for the cell-wide G, N_eff ≈ 23,100 per instrument over 5 sessions. **Recompute per stratum before running** |
| **Confirm** | OOS R² > MDE with a stable sign in ≥ 2 of 3 TOD buckets **and** both instruments |
| **Falsify** | Predictability concentrated at Z = 0.5 s and gone by Z ≥ 1 s — that is `EF-01`'s identity leaking through timestamp inversion, not a forecast |
| **Admissibility** | Z = 0.5 s descriptive; Z ≥ 1 s decision-relevant only under R = 500/900 ms arms |

### `EF-02/H2` — Same, options

As `EF-02/H1` with stratum = `D26` premium bands × DTE {0–2, 3–7, 8–30} d, on the retained
`DAT-09` strike band. **Pre-registered expectation: weaker than futures**, because option
touch depth is thinner and quote updates are surface-driven rather than flow-driven.
G contribution: 3 × 4 × 3 × 5 × 3 = **540** — *this alone nearly triples the cell grid and
is the first place to cut if we narrow* (see open question 5).

### `EF-03/H1` — **Maker core, reduced form: fill rate versus fill quality, at the front of the queue**

The `EF-03` derivative pair, computable **now**, by taking the front-of-queue position as
given. Fill becomes "a signed print occurred at our price"; both derivatives follow from
tape.

| Axis | Binding |
|---|---|
| **X** | Depth-delta OFI, signed relative to the quoting side (positive = flow running **into** our resting side) |
| **h₁** | {1, 2} s |
| **f₁** | 2.00 Hz |
| **Y (a)** | Front-of-queue fill intensity: signed-print arrival rate at our price, prints/second. `CON-06`: observed |
| **Y (b)** | Front-of-queue markout `AM_h = s(p_fill − m_{t+h})`, in ticks and ₹/unit. `CON-06`: deterministically derived given `DAT-14`'s versioned sign |
| **h₂** | (a) 5 s forward window; (b) h ∈ {1, 2, 5, 30} s |
| **f₂** | Event clock (per print) |
| **Z** | {1, 2} s |
| **Stratum** | Futures; options by premium band |
| **K** | (a) ∂(prints/s)/∂SD(OFI); (b) ∂AM/∂SD(OFI) in **ticks per SD**, and the implied ∂V/∂OFI = P′[E−c] + PE′ **evaluated at the measured c = ₹0.0474/unit round trip** |
| **G contribution** | 2 × 2 × 4 × 7 = **112** |
| **Confirm** | (a) > 0 **and** (b) < 0, mirrored across sides per §1, stable across `VOL-04` regimes |
| **Falsify** | (b) ≈ 0 within MDE → OFI is pure volume, no gate warranted, `EF-04` is dead. (a) ≈ 0 → the depletion channel is absent at our cadence |
| **Admissibility** | Decision-relevant at Z ≥ R |
| **Limitation, recorded now** | Front-of-queue fills include benign small prints a back-of-queue maker never sees. The measured (b) is therefore **not** the (b) a realistic queue position would face; `EF-03/H2` is what settles that. Do not let H1 stand in for H2 once `EXE-10` exists |

### `EF-03/H2` — Full form, over `EXE-10` feasible queue paths

Identical bindings, with (a) replaced by the `EXE-09` censored-hazard fill probability
**interval** `[P_L, P_U]` run over `EXE-10`'s feasible queue paths, and (b) by `ANL-01`
Greek-adjusted markout. **Status: `Deferred` — `EXE-10` and `ANL-01` are `Not started`.**
Registered now so the eventual test is pre-registered, and so a null from H1 is never
quietly reported as settling H2.

### `EF-04/H1` — OFI conditional-mean structure (nuisance model, declared)

Registered separately and **before** the gate, so that "surprise" is not a researcher
degree of freedom discovered during gate tuning. This is the concrete answer to open
question 1 of round 1.

| Axis | Binding |
|---|---|
| **X** | Lagged OFI, touch depth, print intensity |
| **h₁ / f₁** | 500 ms / 2.00 Hz |
| **Y** | OFI at t |
| **h₂ / f₂** | 500 ms / 2.00 Hz |
| **Z** | 0 (this is a fit, not a forecast claim) |
| **Stratum** | Per instrument × TOD third |
| **K** | AR order p by BIC on a **pre-declared training window (first 60% of collected sessions)**; Σ AR coefficients; OFI **half-life in ms** |
| **Confirm** | p and half-life stable out of sample; residual serially uncorrelated at lag 1 |
| **Falsify** | No stable AR structure → "surprise" is undefinable and `EF-04/H2` must use raw level, which is then explicitly a volume filter |
| **Admissibility** | Descriptive. It is machinery, not a finding |

### `EF-04/H2` — **The decision test: OFI-surprise withdrawal gate versus the reference policy**

| Axis | Binding |
|---|---|
| **X** | OFI surprise = OFI − E[OFI \| history] from `EF-04/H1`'s frozen model, in SD units |
| **h₁** | {0.5, 1, 2} s |
| **f₁** | 2.00 Hz |
| **Policy** | Suppress the resting quote on side s when adverse same-side OFI surprise > τ, τ ∈ {1, 1.5, 2, 3} SD; re-enter below τ/2 |
| **Y** | Δ(cumulative front-of-queue net AM per hour quoted) **versus the `EF-10/H1` reference policy** |
| **h₂** | Per session, and pooled over the collected sessions |
| **f₂** | Daily |
| **Z** | **= R**, the reaction path. Arms R ∈ {500, 900, 1500} ms |
| **Stratum** | Futures; options by premium band |
| **K** | **₹ per lot per hour** improvement; **% of fills foregone**; and the **mean AM of foregone versus retained fills** — the last is what shows the gate cut the right ones rather than simply cutting volume |
| **G contribution** | 3 × 4 × 3 × 7 = **252** |
| **Confirm** | Improvement > 0 at R = 900 ms, roughly monotone in τ over an interior range, **and** foregone fills have materially worse mean AM than retained fills |
| **Falsify — three distinguishable ways, and the distinction is the point** | (i) improvement ≤ 0 at every τ → OFI does not separate toxic from benign fills; (ii) improvement > 0 at R = 500 ms but gone at R = 1500 ms → **fails on latency, not economics** — the remedy is colocation/DMA, not a better signal; (iii) improvement comes entirely from cutting volume, with foregone and retained AM indistinguishable → the gate is a volume filter wearing a signal's clothes |
| **Admissibility** | Decision-relevant by construction |

### `EF-05/H1` — Depth-delta OFI versus signed trade flow, on this feed

| Axis | Binding |
|---|---|
| **X** | Arm A: depth-delta OFI. Arm B: `DAT-14`-signed trade-flow imbalance, with its **44.3% volume coverage** carried as a reported attribute, not a footnote |
| **h₁ / f₁** | {1, 2, 5} s / 2.00 Hz |
| **Y** | Both `EF-02/H1`'s mid-move target and `EF-03/H1`'s markout target, **identical folds** |
| **h₂ / f₂ / Z** | Inherited from the target hypothesis |
| **Stratum** | Futures; options by premium band |
| **K** | Paired difference in OOS R² (mid target) and log loss (markout target), with a **paired block bootstrap** CI on the difference |
| **G contribution** | 3 × 2 × 7 = **42** |
| **Confirm** | OFI wins on both targets |
| **Falsify** | Signed flow wins or ties despite the coverage gap — **a genuinely informative negative**, implying the sign carries information the net quantity delta destroys, and that gross-flow decomposition (currently bounded, `D23`) is worth more than we assumed |
| **Admissibility** | Inherited |

### `EF-06/H1` — Multi-level OFI saturation depth

| Axis | Binding |
|---|---|
| **X** | Level-wise OFI **indexed by distance in ticks from the touch, never by vendor level number** (level identity shifts when the best price moves), cumulated over the nearest L tick-buckets, L ∈ {1, 2, 3, 5, 10, 20}; combined at cluster level per `SIG-10` |
| **h₁ / f₁** | 1 s / 2.00 Hz |
| **Y / h₂ / f₂ / Z** | Mid change, 5 s, 2.00 Hz, Z = 1 s |
| **Stratum** | NIFTY, BANKNIFTY futures; options by premium band |
| **K** | **The saturation depth L\*, reported in ticks**, at which incremental OOS R² first falls below MDE — this number is itself the finding |
| **G contribution** | 6 × 7 = **42** |
| **Confirm** | Monotone incremental value up to a stable L\*, reproducible across both instruments |
| **Falsify** | No incremental value over L = 1; or value disappears when depth is measured in **rupees rather than contracts**; or the contributing levels evaporate before price reaches them. **For options, near-empty books are expected to falsify outright — that expectation is registered now so a null cannot be retrofitted as a prediction** |
| **Caveat** | Any depth200 arm carries `DAT-13`'s first-subscription throttle as a known capture bias |

### `EF-07/H1` — OFI censoring width in price-moving windows

| Axis | Binding |
|---|---|
| **X** | Indicator: best price moved within the 500 ms snapshot interval |
| **Y** | OFI bound width W = OFI^U − OFI^L from the `EXE-10`-style feasible-event set `E_k` applied to the OFI statistic itself |
| **h₁ = h₂** | 500 ms; **f₁ = f₂** 2.00 Hz; **Z** = 0 |
| **Stratum** | Instrument × activity tercile × TOD third × tier (depth20, depth200) |
| **K** | **Median W in contracts**, and **W as a % of the point OFI estimate**, by moved/not-moved |
| **G contribution** | Measurement, not inference. Reported with intervals, no multiplicity correction claimed |
| **Confirm** | W materially larger in price-moving windows |
| **Falsify** | W invariant to price movement → the 500 ms netting window is **not binding** at current NSE index-F&O event rates. **This would be materially good news** and would widen the admissible horizon set |
| **Downstream obligation** | Every `EF` result carries the censoring flag. A point OFI silently substituted for the interval is the unlabelled-proxy failure `SIG-07` exists to prevent |

### `EF-08/H1` — Permanent versus transitory split, against cancel latency

The claim on which the maker value of this whole cell rests.

| Axis | Binding |
|---|---|
| **X** | (signed flow, quote revision) bivariate system, Hasbrouck (1991) VAR |
| **h₁ / f₁** | 500 ms bars, 40 lags (= 20 s of history) |
| **Y** | Cumulative impulse response of mid to a unit signed-flow innovation |
| **h₂** | 0.5 s to 60 s |
| **f₂** | 2.00 Hz |
| **Z** | n/a — this is a decomposition, not a forecast |
| **Stratum** | Instrument × `VOL-04` regime × TOD third |
| **K** | **(i)** permanent share = lim R(h) / max R(h); **(ii)** the **half-life of the transitory component in ms**; **(iii)** that half-life **minus the measured reaction path R** — the sign of (iii) is the decision |
| **G contribution** | 2 × 3 × 3 = **18** |
| **Confirm** | Permanent share stable out of sample and across adjacent contracts, **and** transitory half-life > R, i.e. there is still something to react to when we can finally react |
| **Falsify** | Half-life < R → **OFI is descriptively real and operationally useless for us.** This is a legitimate and important verdict, not a failure of the analysis, and would redirect `EF` effort entirely to slower cross-asset transforms |
| **Admissibility** | The result is descriptive; its **comparison to R** is the decision-relevant object |

### `EF-09/H1` — Tick-binding gradient, imbalance arm (Gould–Bonart)

| Axis | Binding |
|---|---|
| **X** | Queue imbalance I⁽¹⁾ = (Q^b − Q^a)/(Q^b + Q^a) at the touch (`BK` cell object, consumed here) |
| **h₁** | Instantaneous (state, not flow) |
| **f₁** | 2.00 Hz |
| **Y** | Direction of the next mid transition (binary), capped at 5 s |
| **h₂** | To first transition, 5 s cap |
| **f₂** | Event |
| **Z** | 0.5 s |
| **Stratum — this is the hypothesis** | spread-in-ticks ∈ {1, 2, 3, 4–6, 7–12, 13–30, 31+}, cross-cut with `D26` premium bands {2–10, 10–21, 21–50, 50–200, 200+} |
| **K** | **The gradient**: slope of AUC (or OOS log-loss improvement) on **log(spread in ticks)**. Pre-registered sign: **negative** |
| **G contribution** | 7 × 5 = **35** cells, 1 gradient test per instrument-chain |
| **Confirm** | Gradient < 0, significant, **monotone across ≥ 4 adjacent spread buckets**, present in both NIFTY and BANKNIFTY |
| **Falsify** | Gradient ≥ 0, non-monotone, or — **the fatal confound** — it disappears once **depth, order count and print intensity are held fixed**. Spread-in-ticks correlates with illiquidity, so an uncontrolled negative gradient is equally consistent with "queue signals work better in liquid contracts", which has nothing to do with the tick |
| **Identification** | Compare contracts **matched on depth, order count and print activity but differing in premium**, within the same chain and expiry. This is the whole design: one chain spans both tick regimes at the same instant, in the same underlying, under one information environment |
| **Admissibility** | Descriptive; feeds regime selection under `D26` |

### `EF-09/H2` — Tick-binding gradient, OFI arm

As `EF-09/H1` with X = depth-delta OFI, h₁ = 1 s. Registered separately because `EF-09/H1`
tests the **state** and `EF-09/H2` the **flow**, and §0 forbids conflating them. A gradient
present for imbalance but absent for OFI would be informative: it would say the tick
constrains *queueing* without constraining *flow response*.

### `EF-10/H1` — Front-of-queue reference policy level

| Axis | Binding |
|---|---|
| **X** | None. Unconditional reference policy: always quote at the touch, always at the front, never cancel |
| **Y** | AM_h = s(p_fill − m_{t+h}) per signed print, **net of the ₹0.0474/unit statutory round trip** (`MK-04` ledger, versioned by circular effective date) |
| **h₂** | {1, 2, 5, 30, 60} s |
| **f₂** | Event (per print) |
| **Z** | n/a — policy evaluation |
| **Stratum** | NIFTY, BANKNIFTY futures; options by premium band × DTE bucket |
| **K** | Mean net AM in **ticks and ₹/unit**, with block-bootstrap CI; plus fills/hour, so the level converts to ₹/hour |
| **G contribution** | 5 × 7 = **35** |
| **Ex-ante MDE — and the reason to run this first** | Prints, not snapshots: `DAT-14` gives ~6,025 prints/instrument/day → ~30,125 over 5 sessions, block-bootstrap N_eff assumed ~3,000. SE ≈ σ/55. At **h = 1 s** (σ ≈ 1–2 ticks) SE ≈ ₹0.001–0.002, **negligible against the ₹0.0474 cost floor — decisive within days.** At **h = 60 s** (σ ≈ several ₹) SE ≈ ₹0.09, **larger than the entire cost floor — register h = 60 s as `Deferred`, underpowered, and say so rather than return a spurious null** |
| **Confirm (survival)** | Net AM > 0 in some stratum at a powered horizon |
| **Confirm (kill direction)** | Net AM < 0 at every powered horizon in liquid NIFTY |
| **Interpretation limit, binding** | A negative level is **not** the `MK-05` kill on its own. Front-of-queue overstates value (best position) while never-cancelling understates it (worst policy); the deviations run opposite and do not compose into a bound. The kill requires a negative level **and** `EF-04/H2` failing to recover it |

---

## 7. Declared grid size

| Hypothesis | Arms |
|---|---:|
| `EF-01/H1` | 7 |
| `EF-02/H1` | 216 |
| `EF-02/H2` | 540 |
| `EF-03/H1` | 112 |
| `EF-04/H2` | 252 |
| `EF-05/H1` | 42 |
| `EF-06/H1` | 42 |
| `EF-08/H1` | 18 |
| `EF-09/H1` + `/H2` | 70 |
| `EF-10/H1` | 35 |
| **Cell total `G_EF`** | **1,334** |

`EF-04/H1` and `EF-07/H1` are machinery/measurement and are excluded from the inference
grid; they are reported with intervals and claim no p-values.

At G = 1,334 the Romano–Wolf critical value is roughly |t| ≈ 4.5, implying MDE on OOS
R² ≈ 0.0009 at N_eff ≈ 23,100. Still detectable — but **one feature cell has consumed
1,334 tests, and there are six cells.** `D20` accepted this cost explicitly; §Open
questions 5 proposes we now budget it rather than discover it.

---

## Open questions carried into round 2

1. Does `EF-04`'s gate operate on OFI **level** or on OFI **surprise** relative to a
   conditional mean? A level gate withdraws in every busy state and may simply be a
   volume filter wearing a signal's clothes.
2. `EF-03`(a) requires `EXE-10`, which is `Not started`. Is `EF-03` tested on own live
   fills once available, or on replayed queue bounds first? The two have different
   evidence levels and the ledger should say which is required.
3. Whether the ₹21 premium regime split (`D26`) should also stratify every `EF` claim, or
   only the ones where the tick plausibly binds. — **`EF-09` now makes the split the
   object of study rather than a nuisance stratification, which partly answers this.**
4. `EF-03/H1` resolves round 1's second weakness: the maker derivative pair is measurable
   now in front-of-queue reduced form, without `EXE-10`. Open question is whether a
   confirmed H1 is enough to justify building the gate, or whether H2 must gate it.
5. **Grid budgeting.** `G_EF` = 1,334 from one cell. `EF-02/H2` (options) alone is 540.
   Proposal: a declared per-cell arm budget, spent deliberately, rather than a grid that
   grows until Romano-Wolf annihilates everything. Needs Aryan's call.
