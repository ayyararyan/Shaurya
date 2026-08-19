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

---

## Open questions carried into round 2

1. Does `EF-04`'s gate operate on OFI **level** or on OFI **surprise** relative to a
   conditional mean? A level gate withdraws in every busy state and may simply be a
   volume filter wearing a signal's clothes.
2. `EF-03`(a) requires `EXE-10`, which is `Not started`. Is `EF-03` tested on own live
   fills once available, or on replayed queue bounds first? The two have different
   evidence levels and the ledger should say which is required.
3. Whether the ₹21 premium regime split (`D26`) should also stratify every `EF` claim, or
   only the ones where the tick plausibly binds.
