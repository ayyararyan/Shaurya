# Book-state claims (`BK`) — SIG-02

Taxonomy cell: **static book state**. Spread, mid, micro-price, per-level and cumulative
depth, depth imbalance, book slope and curvature, notional within k ticks, order count
versus volume per level, bid/ask asymmetry — and, under `D23`, **queue-ahead at placement**,
which is a book-state object rather than a flow object.

Status: **round 2, updated 2026-08-19.** `BK-01`, `BK-11` and `BK-12` are `Agreed`; other
claims remain `Proposed`. The hazard and directional-predictive tiers still wait for Aryan's
pushback.

**Round-2 literature synthesis:**
[`docs/research/joint-option-quoting-literature-2026-08-19.md`](../research/joint-option-quoting-literature-2026-08-19.md).

---

## 0. Framing: mechanism is a prior on stability, nothing more

Aryan's instruction, adopted: *what* book state influences and *how* is the operative
question; *why* is secondary. This is right, and the precise reason is worth stating once —
a mechanism is not intrinsically valuable, it is **a prior on whether the relationship
survives out of sample**. A relationship with a mechanism is a better bet to persist than an
equally strong relationship without one. That is the entire epistemic content of "why", and
it is why this cell records mechanisms briefly and spends its length on functional form,
magnitude and the decision each object changes.

**One exception, carried from `EF`.** `EF-08` — the permanent/transitory split — is a case
where "why" flips the *sign of the action*: transient pressure is compensated risk to lean
into, permanent information is avoidable harm to flee. Where the mechanism changes the
direction of the trade rather than merely our confidence in it, it stays load-bearing.

## 1. What book state actually influences, ranked by how much it should change our behaviour

The taker literature ranks book state by its directional predictive power. **For us that is
the least important of its uses, and the top three require no forecast at all.**

| Rank | What it influences | Object | Forecast needed? |
|---:|---|---|---|
| 1 | **Whether we can flatten inventory at all** | Fill rate at the offsetting contract | No — accounting + hazard |
| 2 | **Whether our quote fills** | Queue-ahead = displayed depth (`D23`) | No at placement; hazard thereafter |
| 3 | **What it costs to get out** | Far-side cumulative depth profile | No — deterministic |
| 4 | **Whether quoting is viable at all** | Spread against the statutory floor | No — arithmetic |
| 5 | **Which of two games we are playing** | Spread in ticks vs the tick floor | No — regime classification |
| 6 | **Where the price goes next** | Depth imbalance, slope | Yes — contested, crowded |

Ranks 1–5 are computable on tape we already hold, carry **no p-values, no grid and no
multiple-testing exposure**, and can license or kill the strategy before a single predictive
test runs. That is the inversion for this cell, and it parallels `D21`'s inversion of `EF`.

## 2. The finding that reorders everything: the book *is* the hedging instrument

Re-derived from the circulars in the maker report §6.1 and reproducing its ₹919.02/lot
exactly:

- **Futures round trip** at 25,000 index and a 65-unit lot = **₹919.02 per lot = ₹14.14 per
  unit = 14.14 index points.** STT at 0.05% of notional on the sale (from 2026-04-01) is
  ₹12.50 of that ₹14.14.
- **Option statutory round trip** = **0.2371% of premium**.
- Observed at-touch spreads run **0.27%–1.05% of premium, median ≈ 2× the floor**, so a
  front-of-queue maker capturing the full spread on a passive round trip nets, before any
  adverse selection or hedge cost, about **0.237% of premium**.

Now put the two together. Delta-hedging one option unit requires Δ futures units:

| Premium | Δ | Spread capture net of tax | Same, in index points of adverse move | Futures hedge round trip | **Hedge ÷ capture** |
|---:|---:|---:|---:|---:|---:|
| ₹5 | 0.05 | ₹0.0119/unit | 0.237 pts | ₹0.707/unit | **60×** |
| ₹30 | 0.25 | ₹0.0711/unit | 0.285 pts | ₹3.535/unit | **50×** |
| ₹100 | 0.50 | ₹0.2371/unit | 0.474 pts | ₹7.069/unit | **30×** |
| ₹300 | 0.50 | ₹0.7113/unit | 1.423 pts | ₹7.069/unit | **10×** |

*(Deltas illustrative, not measured from our tape. `CON-06`: scenario-based. Rates versioned
to the 2026-04-01 STT and 2026-03-01 transaction-charge circulars and must be re-derived if
either changes.)*

**Two consequences, and they are the substance of this cell.**

**(a) Per-fill futures hedging is not expensive — it is arithmetically impossible.** It costs
10× to 60× the entire spread being captured. The maker report established futures market
making is statutorily nonviable; the step it did not take is that this also **removes the
hedge**. Delta cannot be flattened with futures on any per-fill or near-per-fill cadence.

**(b) Therefore the only affordable hedge is another option fill.** Delta must be netted
*inside the option book* — offsetting strikes, both sides of the same contract, or a
portfolio-level futures hedge at a cadence rare enough to amortise 14 index points. Whether
that netting is available is a **fill-rate question at the offsetting contract**, and fill
rate is governed by queue-ahead, displayed depth and spread — **book state**.

So book state is not primarily an information source for us. **It is the hedging
instrument.** That is `BK-01`, and it is why rank 1 above is rank 1.

**The trap this sets, stated now.** Natural netting fails exactly when it is needed. Fills
are a *selected* sample: we are filled on the side the market is moving against. So the
inventory we accumulate is systematically one-sided, and the offsetting fill is least
available precisely when we most need it. **Adverse selection and hedging cost are not two
problems; they are one problem viewed from two sides.**

### 2.1 The hedge cadence — answered

**Aryan's instruction, 2026-08-19:** hedge by quoting both puts and calls; futures block far
too much capital; residual delta will drift slowly and only that needs a futures leg. This
resolves open question 2 of round 1. The cadence is derived below and the answer is
favourable — but **the binding constraint is not the one either of us named.**

Notation: `σ_∞` = the residual delta the quoting policy holds, in index units;
`R` = spread revenue rate (₹/hour); `φ` = the fraction of revenue we are willing to spend
on hedging; futures round trip `= ₹14.139` per index unit.

**The whole answer turns on whether residual delta is a random walk or a steered process.**

**A. Unsteered — fills arrive, we do not lean against them.** Delta random-walks, so
`E|D(T)| ≈ σ_D √T` and hedge cost per hour falls only as `1/√T`:

$$T_{\min}=\left(\frac{14.139\,\sigma_D}{\varphi R}\right)^{2}$$

Under the scenario below, `σ_D ≈ 206` index units/√hour and **`T_min` = 2,223 hours ≈ 346
sessions** at `φ = 0.20`. Futures hedging is not merely expensive here — the required
interval exceeds the life of any position. **Unsteered, futures hedging does not exist as an
option.**

**B. Steered — quote skew leans against accumulated delta.** Residual delta becomes
mean-reverting and bounded at `σ_∞` rather than growing. Hedge cost per hour now falls as
`1/T`, linearly:

$$T_{\min}=\frac{14.139\,\sigma_\infty}{\varphi R}$$

which lands in **hours, not sessions.** This is the whole difference. **The quote-skew
controller is not an optimisation on top of the strategy — it is what makes hedging
affordable at all.**

**Scenario used** (stated, not measured — every figure rescales when `BK-01/H2` and
`BK-11/H1` supply the real ones): premium ₹100, Δ = 0.50, 65-unit lot, 40 one-lot fills per
hour, net spread capture 0.2371% of premium, NIFTY 24,500 at 14% annualised. Gives
32.5 index units of delta per fill, `R` = ₹308/hour = **approximately ₹1,976 per current
6.4167-hour session**, and index
σ = 86.4 points/√hour.

| `σ_∞` | in ATM option lots | Hedge interval at φ=20% | Hedges/session | **Delta noise/session** | **Noise ÷ revenue** |
|---:|---:|---:|---:|---:|---:|
| 4.5 | 0.14 | 1.03 h | 6.3 | ₹985 | **0.5×** |
| 9.0 | 0.28 | 2.06 h | 3.1 | ₹1,971 | **1.0×** |
| 16.2 | 0.50 | 3.73 h | 1.7 | ₹3,558 | **1.8×** |
| 32.5 | 1.00 | 7.45 h | 0.9 | ₹7,115 | **3.6×** |
| 65.0 | 2.00 | 14.91 h | 0.4 | ₹14,231 | **7.2×** |

**C. The finding: the binding constraint is risk, not cost.** Read the last column. Carrying
**one lot** of residual ATM delta produces P&L noise of **approximately 3.6× the entire session's spread
revenue.** The tax was never the thing that would stop us — the delta noise is, and it bites
an order of magnitude earlier.

Setting delta noise equal to revenue gives the tolerance:

$$\sigma_\infty^{\ast}\;=\;\frac{R\sqrt{T_{\text{sess}}}}{\sigma_{\text{index}}}\;\approx\;\mathbf{9\ index\ units}\;=\;\mathbf{0.14\ futures\ lots}\;=\;\mathbf{0.27\ ATM\ option\ lots}$$

and at half that noise, **4.5 index units**. Either way the tolerance is **well under one
lot.** At those tolerances the futures leg costs **approximately ₹395 per session on ₹1,976 gross — 20%,
by construction — at 3 to 6 uses per session.**

**D. Capital, which is the reason Aryan gave and it holds.** SEBI's 2024 framework collects
option premium upfront from buyers, so a long option ties up its premium and nothing more,
while futures and short options carry SPAN plus extreme-loss margin on **notional**. Per lot
at ₹100 premium against ₹1,625,000 futures notional:

| SPAN+ELM (illustrative — `MK-04` must supply the real figure from broker snapshots) | Blocked by futures | Blocked by long option | Ratio |
|---|---:|---:|---:|
| 8% | ₹127,400 | ₹6,500 | **20×** |
| 10% | ₹159,250 | ₹6,500 | **24×** |
| 15% | ₹238,875 | ₹6,500 | **37×** |

Return on **peak margin** is the maker report's stated denominator, so a 20–37× capital
difference is not a side note — it is most of the return.

**Conclusion, and it goes further than the question asked.** Since the tolerance is under one
lot and skew is what holds it there, the routine hedge is **not futures at any cadence** —
it is the quoting policy itself. Futures becomes a **breach valve**: used when skew has
failed to flatten and the residual exceeds tolerance, expected 1–3 times a session, at
roughly ₹127 per 9-unit clip. Planning a *scheduled* futures hedge is the wrong shape.

**Three qualifications, recorded so they are not lost.**

1. **Put/call netting is exact only at the money.** A same-strike long call and long put net
   to `Δc + Δp = 2Δc − 1`, which is zero only at Δc = 0.5. Away from ATM, netting depends on
   the **ratio** of call to put fills, not on merely quoting both. Controlling that ratio is
   precisely what skew does — so "quote both sides" is necessary and not sufficient.
2. **Netting-motivated quotes are not free.** A quote posted only to flatten delta, in a
   contract we would not otherwise quote, buys its netting with adverse-selection exposure.
   It must clear the same `EF-04` gate as any other quote.
3. **The natural netted position has a Greek signature.** Long call plus long put is
   delta-flat but **long gamma, long vega, paying theta** — so systematic buying converts the
   book into a realised-versus-implied volatility position. That is a `VOL`/`GRK` object, not
   a `BK` one, but it means the delta-netting decision silently selects a volatility exposure
   and must be carried there rather than discovered later.

**Also note the delta-normalised direction of travel.** In index points of tolerable adverse
move, the budget *shrinks* for cheap OTM options (0.237 pts at ₹5 versus 1.423 pts at ₹300).
This sharpens rather than contradicts the maker report's correction that cheap options are
not disqualified by tax in tick terms: the percentage burden is flat, but premium-per-delta
is smaller, so the underlying has less room to move against you. Cheap OTM is cheap in
tax and **tight in delta**.

### 2.2 What the joint-quoting literature changes

Aryan confirmed on 2026-08-19 that the **joint quoting configuration is the right primary
decision object** (`D30`). The literature supports that decision while narrowing what “joint”
must mean:

1. **Portfolio marginal risk, not contract inventory.** Stoikov–Sağlam, Guéant, and
   Giannetti–Zhong–Wu show that the correct skew on one option depends on the rest of the book,
   the covariance of residual risks, and the relative liquidity of the available hedges.
2. **Delta is necessary and not sufficient.** Near expiry net gamma matters most; at longer
   tenors net vega does. Baldacci–Bergault–Guéant show that aggregate risk-factor state can make
   a many-option controller tractable, but only under a continuous-delta-hedge assumption that
   Shaurya explicitly rejects.
3. **Aryan's hedge hierarchy has a close empirical analogue.** Hu–Kirilova–Muravyev–Ryu find
   that professional KOSPI 200 option makers primarily reverse inventory through passive option
   orders, with futures a very small reported channel. Their 38–48% five-minute reversal is a
   benchmark to reproduce or reject, not an NSE prior.
4. **Joint control must be centralised in the implementation.** Naik–Yadav's dealer evidence
   warns that decentralised firms can behave contract by contract even when portfolio theory
   says otherwise. One portfolio state and one configuration decision boundary are therefore
   architectural, not cosmetic.

The full paper-by-paper findings, boundaries and claim–evidence ledger are in the linked report.
They register `BK-13`–`BK-15`; they do **not** select an HJB, risk aversion, Greek buckets or
arrival law before data.

## 3. Two different businesses in one chain

The ₹21 premium boundary (`D26`) is not only a stratification variable. It separates two
structurally different market-making problems, and book state is what tells us which one we
are in.

| | **Queue game** (below ~₹21) | **Pricing game** (above ~₹21) |
|---|---|---|
| Spread | 3–4 ticks, tick binding | 13–61 ticks, tick irrelevant |
| Can we price-improve? | Barely — one tick is the whole spread | Yes, freely |
| What determines our fill | **Queue position** | **Our own price** |
| Binding state variable | Queue-ahead, depth, order count | Fair value accuracy |
| Load-bearing component | **`EXE-10`** | **`SUR` / `GRK`** |
| Failure mode | Never reaching the front | Quoting a wrong fair value |

**The sequencing consequence is concrete and immediately useful:** in the pricing regime we
can step in front of the queue at will, so queue position is second-order and **`EXE-10` is
not load-bearing there.** The high-premium regime is therefore tractable *before* `EXE-10`
exists. Against that, high premium means deep ITM or long-dated, which is thin — so the
trade is queue risk for liquidity risk, and which is cheaper is an empirical question
(`BK-05`).

---

## 4. Claims

| ID | Claim | Tier | Status | Forecast needed? |
|---|---|---|---|---|
| `BK-01` | **The book is the hedging instrument** — futures hedging is arithmetically excluded, so delta nets inside the option book and netting is a book-state-governed fill-rate object | Accounting | **Agreed — Aryan 2026-08-19** | No |
| `BK-02` | Queue-ahead at placement is **exactly** displayed depth; the distribution of touch depth is the fill-rate prior, model-free | Accounting | Proposed | No |
| `BK-03` | Exit cost is deterministic from the far-side depth profile; the **exit-cost ÷ spread-capture** ratio decides whether aggressive unwind exists at all | Accounting | Proposed | No |
| `BK-04` | Spread against the statutory floor defines the **adverse-selection budget**, expressible in index points of tolerable adverse underlying move | Accounting | Proposed | No |
| `BK-05` | The tick regime determines **which game** is played, and therefore whether `EXE-10` or `SUR`/`GRK` is the binding dependency | Regime | Proposed | No |
| `BK-06` | Touch-queue **depletion half-life** given depth gives expected time-to-fill, hence staleness exposure | Hazard | Proposed | Rate model |
| `BK-07` | **Replenishment speed** after depletion determines whether a cancelled quote can be re-posted at a comparable queue position | Hazard | Proposed | Rate model |
| `BK-08` | **Order count per level** (hence average order size) tightens `EXE-10`'s add/cancel decomposition and narrows queue-ahead bounds | Hazard | Proposed | No |
| `BK-09` | Depth imbalance predicts the next mid transition — **contested**; `EF-09` governs *where* it works | Predictive | Proposed | Yes |
| `BK-10` | Book slope and curvature matter to us as **exit-cost and impact state**, not as direction | Predictive | Proposed | Partly |
| `BK-11` | **Delta is steered by quote skew, not hedged by futures.** Steering converts the futures cadence from ~346 current sessions to hours, and the binding tolerance (< 1 lot) is set by delta **risk**, not by hedge cost | Accounting/Policy | **Agreed — Aryan 2026-08-19** | No |
| `BK-12` | The primary decision object is the **joint quoting configuration**, while per-quote fill probability and markout remain measurement primitives | Estimand | **Agreed — Aryan 2026-08-19 (`D30`)** | No |
| `BK-13` | Inventory is reversed primarily through **passive option fills**, with aggressive option exits second and futures reserved for residual breaches | Policy/Empirical | Proposed | Yes — channel attribution |
| `BK-14` | A joint controller using portfolio delta plus maturity-sensitive gamma/vega state dominates independent per-contract or delta-only control after costs and peak margin | Policy/Model comparison | Proposed | Yes — causal replay |
| `BK-15` | A low-dimensional Greek state is an adequate local compression of the full inventory vector inside a declared inventory region | Approximation | Proposed | Yes — approximation error |

### `BK-01` — The book is the hedging instrument

- **What it influences.** Inventory flattening capability, which for a maker is the binding
  constraint on position size and holding period.
- **How.** Futures round trip = 14.14 index points/unit versus an option spread capture of
  0.237% of premium; the ratio is 10×–60×. Delta must therefore net within the option book,
  and netting availability = fill probability at the offsetting contract = f(queue-ahead,
  displayed depth, spread) at that contract.
- **Why we care.** It converts hedging from an execution problem into a **quoting** problem.
  The offsetting quote must already be resting, at a queue position that fills, *before* the
  inventory arrives. A maker that reacts to inventory after a fill has already lost.
- **`CON-06`.** Scenario-based (the cost arithmetic), consuming observed book state.
- **Falsifier — tested and resolved 2026-08-19, see §2.1.** A portfolio-level cadence at which
  14.14 index points amortises does exist, but **only under steering**: unsteered it is ~346
  sessions, steered it is hours. The claim therefore stands and narrows to its correct form —
  futures hedging is unavailable as a *routine* mechanism and survives only as a breach valve.
  `BK-11` carries the steered form.

### `BK-02` — Queue-ahead at placement is exactly displayed depth

- **What.** Fill probability, before any hazard model.
- **How.** `D23`: under NSE price-time priority, at acceptance `Q₀^ahead = D₀(p)` exactly.
  Deterministic, not estimated. Everything after acceptance is bounded (`EXE-10`); the
  starting point is not.
- **Why we care.** The **distribution** of displayed touch depth across the day and across
  contracts is a model-free prior on how long we queue. If touch depth at the contracts we
  would quote is routinely hundreds of lots, our fill rate is set before we write a line of
  hazard code, and `EXE-10`'s marginal value shrinks accordingly.
- **`CON-06`.** Deterministically derived.

### `BK-03` — Exit cost is deterministic; the ratio to spread capture is the decision

- **What.** The cost of liquidating unwanted inventory aggressively.
- **How.** For cumulative far-side depth `D(δ)` at distance δ from mid, walking `q` units
  costs `∫δ dD` up to `q`. Pure arithmetic on a snapshot — **no forecast, no p-value**.
- **Why we care.** Combined with `BK-01`: if exit cost exceeds spread capture, aggressive
  unwind is unavailable, so exit must be **passive**, which re-exposes us to adverse
  selection and extends holding time. `BK-01` and `BK-03` together say the maker is trapped
  in passivity on both entry and exit — the position can only be opened and closed by
  waiting, never by paying.
- **`CON-06`.** Deterministically derived from the snapshot; **`estimated` once liquidity is
  allowed to move between observation and exit**, and that distinction must be carried.

### `BK-04` — Spread against the floor is the adverse-selection budget

- **What.** Whether a contract is quotable at all, before any signal.
- **How.** Budget = prevailing spread − statutory round trip (0.2371% of premium) − hedge −
  fees. Expressed per unit, and in index points as `budget / Δ`, which is the tolerable
  adverse underlying move conditional on fill.
- **Why we care.** It converts an abstract question ("is there edge?") into a checkable one
  ("does the underlying move more than 0.3–1.4 index points against us, conditional on
  fill, within the markout horizon?"). `EF-10/H1` measures exactly the left-hand side.
- **`CON-06`.** Scenario-based; versioned to circular effective dates per `MK-04`.

### `BK-05` — The tick regime selects the binding dependency

- **What.** Which component gates progress, and therefore what we build next.
- **How.** §3. Below the tick boundary, price improvement is unavailable and fills are
  queue-determined; above it, price improvement is free and fills are price-determined.
- **Why we care.** It is the only claim in this cell that changes the **build order**. If
  the pricing regime is viable, `SUR`/`GRK` gate progress and `EXE-10` does not.
- **`CON-06`.** Deterministically derived (regime classification from observed spread).

### `BK-11` — Delta is steered, not hedged — **Agreed (Aryan, 2026-08-19)**

- **What it influences.** Whether the strategy has a hedging mechanism at all, the size it
  can carry, and its return on peak margin.
- **How.** §2.1. Unsteered residual delta random-walks and the affordable futures cadence is
  ~346 current sessions — no mechanism. Steered by quote skew across the put/call book, residual
  delta is bounded and the cadence collapses to hours. The tolerance is set by **delta risk**
  (P&L noise of 3.6× session revenue at one lot of residual ATM delta), not by hedge cost,
  and lands under one lot: `σ*_∞ ≈ 9` index units for noise ≈ revenue, ≈ 4.5 for half.
- **Why we care.** It moves delta management out of `EXE` and into the **quoting policy**,
  and it makes the skew controller a **first-order requirement rather than a refinement.**
  It also fixes the futures leg's role: breach valve, 1–3 uses per session, not a schedule.
- **`CON-06`.** Scenario-based arithmetic over observed cost and margin schedules; `σ_∞` and
  `σ_D` are **estimated and currently unmeasured** — `BK-01/H2` and `BK-11/H1`.
- **Falsifier.** Quote skew cannot in practice hold `σ_∞` below ~9 index units — because
  fills are selected and arrive precisely on the side that worsens delta (§2's trap). Then
  neither steering nor futures works at the required tolerance, and **the maker cannot carry
  inventory at all**, which is a kill result at the strategy level, not a parameter problem.

### `BK-12` — Joint configuration is the primary object — **Agreed (`D30`)**

- **What.** A simultaneous set of put/call bid and ask quotes, conditional on one central
  portfolio state; not a collection of independently optimal orders.
- **How.** Each possible fill contributes its own capture, cost, fill intensity and conditional
  markout, but also changes residual delta, gamma/vega, flattening capacity, breach probability
  and peak margin of the full book.
- **Why we care.** Independent quote selection can accept individually positive quotes whose
  joint fills produce an unhedgeable book, or reject a low standalone-value quote that cheaply
  neutralises portfolio risk. Per-quote estimates remain necessary inputs; separability is what
  is rejected.
- **Status.** Estimand decision, not a statistical claim. The choice of controller remains open.

### `BK-13` – `BK-15`

Seeded by the joint-quoting literature and registered before execution. These are empirical
claims about Shaurya's own tape and replay, not conclusions imported from KOSPI, U.S. options or
continuous-hedging models. Their bound tests follow below.

### `BK-06` – `BK-10`

Mechanisms and capture paths drafted; **hypotheses deliberately not bound in round 1**,
pending Aryan's pushback on §1's ranking. `BK-09` in particular must not be bound before
`EF-09` reports, since `EF-09`'s gradient decides the strata in which `BK-09` is worth
testing at all.

---

## 5. Hypotheses — accounting and regime tiers

All five are **deterministic computations on retained tape**. They claim no p-values and
contribute **zero** to `SIG-12`'s grid. They should run before anything inferential in this
cell.

### `BK-01/H1` — Netting availability

| Axis | Binding |
|---|---|
| **X** | Displayed depth, order count and spread at the **offsetting** contract, at the instant of a hypothetical fill |
| **h₁ / f₁** | Instantaneous / 2.00 Hz depth20 |
| **Y** | Time-to-offsetting-fill under the `EF-10/H1` front-of-queue reference policy, and the delta accumulated in the interim |
| **h₂ / f₂** | Event (per offsetting print) / event clock |
| **Z** | n/a — policy evaluation |
| **Stratum** | Premium band × DTE bucket × moneyness; same-contract-both-sides versus offsetting-strike |
| **K** | Median and p95 **time-to-flat in seconds**; **peak absolute delta per lot quoted**, in index-point equivalents; and **% of quoted intervals in which flattening was unavailable at all** |
| **Verdict rule** | Descriptive; feeds `RSK` position sizing directly |
| **Why it runs first** | If p95 time-to-flat is minutes, the strategy carries overnight-scale delta on a spread capture of 0.237% of premium, and no signal work is justified until sizing accounts for it |

### `BK-02/H1` — Touch-depth distribution as the fill-rate prior

X: displayed depth at best bid and ask, plus order count. Y: none — this is a distribution,
not a relation. Stratum: contract × TOD third × premium band. **K:** median, p10, p90 of
touch depth **in lots**, and `median touch depth ÷ median print size` = the **model-free
expected number of prints to clear the queue ahead of us.** That single ratio is the
headline. `CON-06`: deterministically derived.

### `BK-03/H1` — Exit cost curve and the exit-cost ÷ capture ratio

X: far-side cumulative depth profile. Y: `∫δ dD` for q ∈ {1, 2, 5, 10} lots, in ticks and
in % of premium. **K:** the ratio **exit cost ÷ spread capture** at each q; the claim's
operative threshold is 1.0. Stratum: premium band × DTE × TOD. Reports the **fraction of the
session in which the ratio exceeds 1**, i.e. aggressive exit is unavailable. `CON-06`:
deterministically derived on the snapshot; flagged `estimated` if evaluated at a lag.

### `BK-04/H1` — Adverse-selection budget, measured rather than assumed

X: prevailing spread. Y: budget per unit and in index points (`budget / Δ`, Δ from `GRK`).
Stratum: premium band × DTE × moneyside. **K:** the **distribution** of the budget, not its
mean — the decision object is the fraction of quoting time in which the budget exceeds the
`EF-10/H1` measured adverse markout. Directly pairs with `EF-10/H1`: **`BK-04/H1` measures
what we are paid, `EF-10/H1` measures what we lose, and their difference is the strategy.**

### `BK-05/H1` — Regime classification and its stability

X: spread in ticks and premium. Y: regime label {tick-bound, tick-free}. **K:** the **premium
at which the tick ceases to bind**, estimated as the breakpoint in a regression of
log(spread) on log(premium) — the maker report's elasticity-1.05 result predicts ≈₹21, and
this re-estimates it **on our own tape rather than on one four-minute diagnostic window**.
Plus regime **persistence**: the fraction of the session a contract stays in one regime, and
transition frequency. Stratum: expiry × DTE. `CON-06`: estimated. Confirming: a clean
breakpoint within a stated interval of ₹21, stable across days. Falsifying: no breakpoint, or
the boundary moves materially day to day — in which case the regime split is not a usable
gate and `D26`'s stratification survives while `BK-05`'s build-order consequence does not.

### `BK-01/H2` — Unsteered delta-accumulation volatility `σ_D`

The input that decides whether §2.1 case A or case B applies. **Runs on tape now**, via the
`EF-10/H1` front-of-queue reference policy, which generates a synthetic fill stream with no
steering by construction.

X: the `EF-10/H1` fill stream. Y: cumulative signed delta of the resulting book, in index
units. h₂: {1 min, 5 min, 15 min, 1 h, 1 session}. f₂: event. Stratum: single-contract,
same-strike put+call pair, and full quoted chain — **the three cases isolate how much netting
comes free from quoting both sides before any skew is applied.** **K:** `σ_D` in index
units/√hour, plus the **variance ratio** `Var(D(kT))/(k·Var(D(T)))` — a ratio below 1 is
direct evidence of natural mean reversion, above 1 of trending (selected) fills. `CON-06`:
estimated. **The variance ratio is the headline**: it measures how much of Aryan's netting
intuition holds *before* the skew controller exists.

### `BK-11/H1` — Achievable steered residual `σ_∞`

Requires a skew rule, so **not tape-only**. Registered now so the eventual test is
pre-registered.

X: a declared skew rule (widen the delta-adding side by `k` ticks per unit of residual
delta, `k` swept). Y: stationary distribution of residual delta under `NAT-07` replay.
**K:** `σ_∞` in index units and ATM-lot equivalents; the **fraction of session time above the
9-unit tolerance**; foregone spread revenue from skewing; and the implied futures breach-valve
frequency. Confirm: `σ_∞ ≤ 9` index units at a skew intensity whose revenue cost is under the
approximately ₹395/session the futures leg would otherwise cost. Falsify: no skew intensity achieves the
tolerance without destroying more revenue than it saves — **`BK-11`'s kill branch.**
Dependencies: `EF-10/H1`, `BK-01/H2`, `NAT-07`.

### `BK-13/H1` — Inventory reversal and hedge-channel attribution

| Axis | Binding |
|---|---|
| **X** | A signed option-inventory shock created by a fill under the declared joint quoting configuration; magnitude recorded in option lots, delta units and Greek vector |
| **h₁ / f₁** | Instantaneous fill event / canonical fill clock |
| **Y** | Fraction of the shock reversed, and attribution of the reversal to passive option fills, aggressive option exits, and futures |
| **h₂ / f₂** | `{1, 5, 15, 30}` minutes / event ledger sampled at each horizon |
| **Z** | `0` from fill completion; descriptive inventory dynamics, not a price forecast |
| **Stratum** | Premium band × DTE bucket × initial absolute-delta bucket × volatility regime × selected/adverse fill side |
| **K** | Median and p10/p90 reversal fraction at each horizon; channel shares summing to 100%; time-to-50%-reversal; peak-margin and realised cost per unit reversed |
| **External benchmark** | Hu et al.'s 38–48% five-minute reversal and passive-option dominance are reported beside, never used as a verdict threshold |
| **Confirm / falsify** | Confirm `BK-13` only if passive option fills are the largest reversal channel **and** their all-in loss is below the futures alternative. Falsify if futures or aggressive exits dominate after identical attribution rules; report regime-specific reversals rather than averaging them away. |
| **Dependencies** | `CON-02`, `ANL-01`, `BK-11/H1`, `NAT-07`; Live claims require broker-reconciled fills |

### `BK-14/H1` — Does portfolio state improve the quoting policy?

This is a pre-registered **paired policy comparison**, so the timing axes describe the common
decision/reward protocol rather than a predictor regression.

| Axis | Binding |
|---|---|
| **X** | Controller class: `{independent per-contract, joint delta-only, joint delta + DTE-bucketed gamma + tenor-bucketed vega}`; identical eligible quote set, fill model, latency, costs and risk limits |
| **h₁ / f₁** | Portfolio state at every admissible 500 ms decision point / 2.00 Hz binding depth20 clock |
| **Y** | Configuration value and risk realised after the decision |
| **h₂ / f₂** | `{5 s, 60 s, time-to-flat, full session}` / event ledger, with overlapping short-horizon inference handled under `METHOD.md` |
| **Z** | At least realised end-to-end response bound `R`; arms below eventual `R` are descriptive/demoted, not deleted |
| **Stratum** | Premium regime × DTE × volatility regime × starting residual-delta bucket |
| **K** | Net ₹ per unit peak margin; p95/p99 drawdown; tail Greek exposure; median/p95 time-to-flat; futures breaches/session; foregone spread; paired differences with dependence-aware intervals |
| **Grid / power** | Every controller, bucket definition, risk-aversion value and horizon enters one declared `G`; ex-ante MDE is stated for the primary K before replay |
| **Confirm / falsify** | Confirm only if the expanded joint state improves the pre-registered primary economic K and does not merely exchange mean P&L for worse tail risk. Delta-only wins if the expanded state has no economically resolvable gain; independent control wins if joint state adds no resolvable gain. `Inconclusive` if MDE is too wide. |
| **Dependencies** | `BK-11/H1`, `GRK`, `SUR`, `EXE-09/10`, `NAT-07`, configuration-level `SIG-17` |

### `BK-15/H1` — Low-dimensional state-compression error

X: inventory representation `{full contract vector, delta-only, delta + DTE-gamma buckets +
tenor-vega buckets}` evaluated against the **same fixed value/policy yardstick**. h₁/f₁: state at
each 500 ms decision point / 2.00 Hz. Y: value-function error and configuration disagreement
against the full-vector yardstick. h₂/f₂: one decision and `{5 s, 60 s}` realised consequences /
event ledger. Z: at least `R` for economic consequences. Stratum: norm of inventory vector × DTE
× volatility regime. **K:** median and p95 absolute value error, fraction of decisions choosing a
different configuration, and economic regret per peak-margin unit. All Greek bucketings and
inventory-region cutoffs enter `G` before execution. Confirm only **locally** where p95 regret is
below the ex-ante tolerance; if error grows outside that region, shrink the admissible state space
rather than asserting a global approximation. Dependencies: `BK-14/H1`, `GRK`, `SUR`, `NAT-07`.

---

## 5.1 Change control — the estimand moves to chain level

**Requirement affected:** `SIG-08` (target register), `REQ-SIG-08`.
**Current requirement:** maker-side targets are fill probability and markout-conditional-on-fill
for **a quote**, `V_s(d,x)` per resting order.
**Approved change (`D30`):** the primary decision object becomes the **joint quoting configuration
across the chain** — a set of simultaneously resting quotes on puts and calls whose fills net
delta — with per-quote value retained as a component, not the objective.
**Why it appears necessary:** `BK-01` and `BK-11`. If futures cannot hedge and delta must net
inside the option book, the value of any single quote is not separable from the quotes resting
alongside it: the same fill is good or bad depending on the inventory the rest of the
configuration is carrying. Optimising quotes one at a time optimises the wrong object.
**Effect on interpretation:** fill-conditioned markout stays the measurement primitive; the
optimisation moves up a level. `EF-03`/`EF-04` are unaffected as *measurements* and become
inputs rather than objectives.
**Effect on outputs:** `SIG-17`'s economic gate is evaluated per configuration per unit of peak
margin, not per quote.
**Alternatives considered:** keep the per-quote estimand and treat inventory as an exogenous
state variable. Rejected — inventory is endogenous to our own configuration, so treating it as
exogenous assumes away the thing `BK-11` says is binding.
**Status:** **Approved explicitly by Aryan on 2026-08-19:** “the joint quoting configuration is
the right direction.” Recorded as `D30`; no longer provisional.

---

## 6. Open questions for round 2

1. ~~**Does `BK-01` change the estimand?**~~ **Answered: yes (`D30`).** The primary object is a
   joint quoting configuration; per-quote fill and markout remain measurement primitives.
2. ~~**What is the minimum viable futures hedge cadence?**~~ **Answered in §2.1
   (2026-08-19).** Unsteered ~346 current sessions; steered, hours — and the binding constraint is
   delta *risk* at a tolerance under one lot, not hedge cost. Routine futures hedging is the
   wrong shape; the futures leg is a breach valve. Remaining open sub-question: can skew
   actually hold `σ_∞` under 9 index units against *selected* fills? That is `BK-11/H1`, and
   it is the strategy-level kill branch.
3. Should `BK-05` reorder the build so the **pricing regime is attacked first**, since it
   does not need `EXE-10`? This is a sequencing decision for Aryan, not a modelling one.
4. Is `BK-09` (imbalance → direction) worth any grid at all for us, given that ranks 1–5
   need no forecast and rank 6 is the most colocation-contested quantity in the market?
5. **Does the netted book's Greek signature reprice the strategy?** Long call plus
   long put is delta-flat but long gamma, long vega, short theta. Delta-netting therefore
   selects a realised-versus-implied volatility exposure by side effect. Belongs to `VOL`/`GRK`,
   but it must be picked up there rather than discovered in live P&L.
