# Book-state claims (`BK`) — SIG-02

Taxonomy cell: **static book state**. Spread, mid, micro-price, per-level and cumulative
depth, depth imbalance, book slope and curvature, notional within k ticks, order count
versus volume per level, bid/ask asymmetry — and, under `D23`, **queue-ahead at placement**,
which is a book-state object rather than a flow object.

Status: **round 1, opened 2026-08-19.** Claims are `Proposed`. Hypotheses are bound only for
the accounting and regime tiers; the hazard and predictive tiers wait for Aryan's pushback.

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

**Also note the delta-normalised direction of travel.** In index points of tolerable adverse
move, the budget *shrinks* for cheap OTM options (0.237 pts at ₹5 versus 1.423 pts at ₹300).
This sharpens rather than contradicts the maker report's correction that cheap options are
not disqualified by tax in tick terms: the percentage burden is flat, but premium-per-delta
is smaller, so the underlying has less room to move against you. Cheap OTM is cheap in
tax and **tight in delta**.

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
| `BK-01` | **The book is the hedging instrument** — futures hedging is arithmetically excluded, so delta nets inside the option book and netting is a book-state-governed fill-rate object | Accounting | Proposed | No |
| `BK-02` | Queue-ahead at placement is **exactly** displayed depth; the distribution of touch depth is the fill-rate prior, model-free | Accounting | Proposed | No |
| `BK-03` | Exit cost is deterministic from the far-side depth profile; the **exit-cost ÷ spread-capture** ratio decides whether aggressive unwind exists at all | Accounting | Proposed | No |
| `BK-04` | Spread against the statutory floor defines the **adverse-selection budget**, expressible in index points of tolerable adverse underlying move | Accounting | Proposed | No |
| `BK-05` | The tick regime determines **which game** is played, and therefore whether `EXE-10` or `SUR`/`GRK` is the binding dependency | Regime | Proposed | No |
| `BK-06` | Touch-queue **depletion half-life** given depth gives expected time-to-fill, hence staleness exposure | Hazard | Proposed | Rate model |
| `BK-07` | **Replenishment speed** after depletion determines whether a cancelled quote can be re-posted at a comparable queue position | Hazard | Proposed | Rate model |
| `BK-08` | **Order count per level** (hence average order size) tightens `EXE-10`'s add/cancel decomposition and narrows queue-ahead bounds | Hazard | Proposed | No |
| `BK-09` | Depth imbalance predicts the next mid transition — **contested**; `EF-09` governs *where* it works | Predictive | Proposed | Yes |
| `BK-10` | Book slope and curvature matter to us as **exit-cost and impact state**, not as direction | Predictive | Proposed | Partly |

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
- **Falsifier.** A portfolio-level hedge cadence exists at which 14.14 index points amortises
  below the accumulated spread capture — in which case futures hedging returns, at that
  cadence only, and the claim narrows rather than dies.

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
| **K** | Median and p95 **time-to-flat in seconds**; **peak |delta| per lot quoted**, in index-point equivalents; and **% of quoted intervals in which flattening was unavailable at all** |
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

---

## 6. Open questions for round 2

1. **Does `BK-01` change the estimand?** If the book is the hedging instrument, the maker's
   object may not be per-quote value `V_s(d,x)` at all, but the value of a **joint quoting
   configuration across the chain** — a portfolio of resting quotes whose fills net. That is
   a materially different optimisation and would be a change-control item against `SIG-08`.
2. **What is the minimum viable futures hedge cadence?** 14.14 index points amortises at
   *some* frequency. Computing that frequency bounds how much delta we must be willing to
   carry, and it is arithmetic, not research.
3. Should `BK-05` reorder the build so the **pricing regime is attacked first**, since it
   does not need `EXE-10`? This is a sequencing decision for Aryan, not a modelling one.
4. Is `BK-09` (imbalance → direction) worth any grid at all for us, given that ranks 1–5
   need no forecast and rank 6 is the most colocation-contested quantity in the market?
