# Slow market making in NSE index futures and options

## What Shaurya should measure before it quotes through a retail-broker feed

**Research date:** 19 August 2026  
**Universe:** NIFTY, BANKNIFTY, FINNIFTY and MIDCPNIFTY futures and options  
**Decision served:** D21 — Shaurya is a maker and never crosses the spread  
**Companion:** [SIG feature research, 19 August 2026](sig-feature-research-2026-08-19.md)

## Abstract

This report derives a maker-specific research design for NSE index futures and options when market data arrive through a non-colocated retail-broker feed. Inventory models imply covariance- and Greek-aware quote skew; adverse-selection models imply a side-specific spread for the option granted to fast takers. Under NSE price-time priority, displayed depth fixes own initial queue-ahead and subsequent trades deplete it from the front; aggregate cancellations make later queue-ahead bounded rather than point-identified. Queue-conditional order-flow intensities remain estimable from Level-2 deltas and order counts, with packet coalescing determining empirical bound width. Options require a synchronized, uncertainty-banded volatility surface and a decomposition of raw markout into delta, gamma, vega, theta, hedge latency, costs and residual selection. Current NSE taxes, charges, lots, ticks, margin and expiry rules consume economically meaningful ticks and capital. The evidence supports a prior of no viable one-tick at-touch edge in liquid NIFTY for this slow maker, but leaves falsifiable tests for wider quotes, resilience states and less-contested contracts. Deployment is warranted only if conservative out-of-sample quote value remains positive after all costs and peak margin.

## Introduction and status

### Corrections, status and governing claim

The companion report was framed for a directional liquidity taker. Its evidence on order flow, cross-contract price discovery, surfaces and regimes remains useful, but its target does not. For a resting order, a correct directional forecast can make the trade *worse*: the quote is disproportionately executed when the forecasted move runs through it. The primitive outcome is therefore not an unconditional future return. It is the joint distribution of **whether a quote fills** and **what happens after that fill**.

For side (s\in\{-1,+1\}), where (s=+1) denotes a maker sale and (s=-1) a maker purchase, distance (d) from the touch and state (x), the object is

\[
V_s(d,x)=P(\mathrm{fill}\mid d,x)\left[
E\{s(p_{\mathrm{fill}}-m_{t+h})\mid \mathrm{fill},d,x\}
-c_{\mathrm{stat}}-c_{\mathrm{hedge}}-c_{\mathrm{inventory}}-c_{\mathrm{capital}}
\right].
\]

The horizon (h), clock, pooling coordinates and bounded queue-ahead estimator are empirical dimensions under D20/D23, not fixed tuning choices. The decision is to quote only where a conservative lower bound on (V_s) is positive after statutory costs, hedge execution and peak margin. This report supplies measurement claims and falsification gates, not a preselected strategy.

The central conclusion is intentionally severe:

> **Shaurya should presume that one-tick, at-touch quoting in the liquid NIFTY complex has no viable edge for a non-colocated retail-feed maker. The presumption can be overturned only by fill-conditioned, latency-realistic evidence.**

> **CORRECTION 5 (2026-08-19, agreed by Aryan).** The phrase "one-tick" is factually wrong and
> the original is preserved above only as the record of what was written. One-tick spreads do
> not exist in the liquid NIFTY option complex. Measured on the five retained tapes (93 NIFTY
> 2026-09-01 options, 2026-08-18 ~09:38-09:42 IST): median spread is 3 ticks at ₹2-10 premium,
> 4 ticks at ₹10-50, 13 ticks at ₹50-200 and 61 ticks at ₹200-600; a regression of log(spread)
> on log(premium) over the 64 liquid contracts gives elasticity **1.05**, R² **0.79**. Spread is
> very nearly proportional to premium. The tick binds only below roughly ₹21 premium, where the
> statutory round trip of 0.0474 per unit first exceeds one tick.
>
> **The governing claim is restated as: "at-touch quoting *at the prevailing spread*."** The
> report's logic is unaffected — the adverse-selection, latency and cost arguments never depended
> on the spread being one tick — but the stated quantity was wrong, and wrong in Shaurya's
> favour: the real spread is several times larger than the claim assumed. `MK-05`'s kill test must
> be written against the prevailing spread, not against a one-tick hurdle.
>
> Note also that the statutory cost is a **floor, not the level**. Observed ATM spreads run
> 0.27%-1.05% of premium against a 0.2371% statutory round trip — 1.1x to 4.4x the floor, median
> about 2x — and at essentially identical premium the spread varies fourfold (24500PE at ₹315.57
> quotes ₹0.85; 24050CE at ₹323.12 quotes ₹3.40) while the tax is identical. A rival mechanism
> reproduces elasticity ≈1 with no tax at all: if makers quote a fixed implied-vol spread, rupee
> spread = vega × Δσ, and vega correlates with premium across the chain. Which mechanism is real
> is **open** (Aryan, 2026-08-19); the discriminating test needs IV/vega on the capture path,
> because premium and vega decouple only deep ITM, and that is not yet a specified task.
>
> Limitation of the measurement above, stated plainly: about four minutes, one morning, one
> monthly expiry at ~14 DTE, early session. It is a diagnostic, not a measurement.

This is an inference from market structure, not a measured result from Shaurya data. Roughly half of NSE equity-derivatives turnover was already attributed to colocated modes in April 2023 ([NSE, primary source](https://archives.nseindia.com/content/fo/fo_mode_of_trading_Apr2023.pdf)). The fastest counterparty observes and cancels before an approximately 8-packet-per-second retail feed can describe the new state. Fast firms need not win every trade for this to matter: Shaurya receives a selected subset of fills, concentrated where its quote has become stale.

### Evidence hierarchy and identification boundary

This report separates four evidence classes:

1. **Peer-reviewed theory and evidence** establish mechanisms and measurement conventions, largely outside India.
2. **Working papers and preprints** supply useful queue and options-control methods but receive weaker weight.
3. **NSE/SEBI primary documents** govern current taxes, contracts, margins and market design.
4. **Broker documentation** describes feed and tariff mechanics; it is not evidence of maker profitability.

The tape identifies displayed prices, quantities and order counts by level, plus last price/quantity, cumulative volume and changes in those aggregates. NSE price-time priority makes own queue-ahead a partially identified object: it starts at displayed quantity, trades at the price consume the front, and aggregate cancellations generate lower and upper paths. Level-by-level additions, cancellations and trades also identify queue-conditional intensity estimates subject to packet coalescing. What remains genuinely unidentified is narrower: which position in a queue cancelled, individual order identity and lifetime, hidden/iceberg quantity, participant type, private information, dealer inventory and signed dealer Greeks. Trade aggressor is not a vendor field; D24 retains a versioned capture-time classification plus raw inputs and an ambiguous/coalesced flag. Independent trade and depth channels make alignment error measurable rather than ignorable.

---

## 1. Quoting theory, derived into observable decisions

### 1.1 Ho–Stoll: inventory creates a reservation-price wedge

In Ho and Stoll’s dealer model, a risk-averse intermediary chooses bid and ask quotes while holding a stochastic inventory. An additional long unit raises exposure to subsequent price moves, so the price at which the dealer is indifferent to another purchase is below the frictionless value; the price at which it is indifferent to a sale is also shifted downward. The quote centre therefore moves *against* inventory. The spread compensates for order-arrival risk, inventory variance and risk aversion.

The operational content is not merely “skew by inventory.” It is:

- a long delta-equivalent inventory lowers both bid and ask centres, making sales more likely and purchases less likely;
- higher conditional variance, longer liquidation horizon or greater risk aversion enlarges the inventory concession;
- correlated inventories must be measured as a portfolio, not contract by contract.

The model needs the efficient price, inventory, conditional return covariance, risk aversion, horizon and arrival processes. Shaurya observes its own positions and can estimate price covariance. It does not observe an efficient price directly, and its arrival process is not exogenous: quotes are filled selectively. A Ho–Stoll-style inventory penalty is usable only after replacing raw inventory with chain-wide Greeks and estimating fill-conditioned outcomes.

### 1.2 Avellaneda–Stoikov: reservation price plus an intensity-dependent spread

Avellaneda and Stoikov (2008) make the trade-off explicit. With midprice (S_t) following diffusion variance σ², exponential utility risk aversion γ, inventory (q), terminal time (T), and Poisson execution intensity declining as (\lambda(\delta)=A e^{-k\delta}), a standard approximation gives

\[
r_t=S_t-q\gamma\sigma^2(T-t)
\]

for the inventory-adjusted reservation price and

\[
\delta^a+\delta^b
\approx \gamma\sigma^2(T-t)+\frac{2}{\gamma}\log\left(1+\frac{\gamma}{k}\right)
\]

for the total optimal spread. Inventory primarily moves the centre; risk and the elasticity of fill intensity determine width. Greater (k) means fills decay quickly with quote distance, making width costly. Higher σ, γ or horizon widens quotes.

Guéant, Lehalle and Fernandez-Tapia (2013) solve the discrete-inventory Hamilton–Jacobi–Bellman system through a linear ordinary differential equation and obtain spectral/closed-form approximations. Guéant (2017) generalises the approach, while Bergault et al. (2021) show that multi-asset approximations yield covariance-aware skew and width. These are important for an option chain because one more option changes a vector of risks, not a scalar inventory.

The state requirements are demanding: a reliable fair value, instantaneous covariance, inventory, fill-intensity curves by side and distance, risk/capital penalty, horizon, fees and latency. Shaurya has inventory and statutory costs; it can estimate covariance and queue-conditional arrival/cancel/trade intensities from Level-2 deltas. Its own fill hazard remains an interval because cancellation position, packet-coalesced event order and hidden quantity are not observed. Most importantly, λ cannot be calibrated from all future trades at a price: it must describe the probability that **our specific FIFO order**, arriving after Kotak and exchange latency, fills. Aggregate flow intensity is an input to that calculation, not a substitute for it.

### 1.3 Copeland–Galai and Glosten–Milgrom: the spread is an adverse-selection filter

Copeland and Galai (1983) interpret a resting quote as a free option granted to informed traders: they execute when the quote is favorable and walk away otherwise. Glosten and Milgrom (1985) formalise sequential trade with informed and uninformed customers. Competitive bid and ask prices are conditional expectations:

\[
b=E[V\mid \text{customer sells}],\qquad
a=E[V\mid \text{customer buys}],
\]

so the spread widens with the probability of informed trading and the informativeness of order direction. This reverses the taker intuition. Strong OFI that predicts an up move is not automatically a reason to bid; it may mean that a bid fill is unlikely while an offer fill is toxic.

These models need trade sign, the distribution of informed signals, informed participation and fundamental value. Dhan supplies no aggressor flag or participant identity, so Shaurya cannot estimate a structural probability of informed trading. It can estimate the reduced-form object that matters: the distribution of future executable markouts conditional on its own side, quote age, inferred fill event and state. “Informed” should therefore be used as an interpretation, not a label in the data.

### 1.4 Synthesis: quote width and skew must include both inventory and selection

A practical approximation is

\[
\text{quote centre}=\widehat{\text{fair value}}
-\underbrace{\nabla_q \mathcal R(q)}_{\text{marginal portfolio-risk concession}}
-\underbrace{\text{side-specific toxicity adjustment}}_{\text{fill-conditioned markout}},
\]

with half-width at least

\[
\text{statutory cost} + \text{hedge cost}
+ \text{surface/latency uncertainty quantile}
+ \text{required return on peak margin}.
\]

Inventory theory and adverse-selection theory are complements. Inventory says which trades improve the book; selection says whether those trades are safe enough to invite. An inventory-reducing offer can still be a bad quote if the underlying is jumping upward and the option surface is stale.

**Table 1** maps the canonical theoretical states to what the Dhan/Kotak environment can actually supply.

**Table 1. Theory-to-data map**

| State needed by theory | Available? | Defensible Shaurya treatment |
|---|---|---|
| Own positions and fills | Yes, from OMS | Reconstruct delta/gamma/vega/theta by strike and tenor |
| Efficient value | No | Synchronized future plus uncertainty-banded, leave-one-out surface; never treat fitted mid as truth |
| Conditional covariance | Estimable | Rolling, regime-specific covariance with stress scenarios |
| Own fill hazard | Estimated with bounds | FIFO queue-ahead bounds, queue-conditional intensities and own-order calibration; propagate intervals |
| Trade aggressor | No direct vendor flag | Retain D24 versioned capture-time classification, raw inputs and ambiguous/coalesced class |
| Own queue-ahead | Partially identified | Exact displayed-book start; FIFO trade depletion; cancellation-position and coalescing bounds |
| Individual order identity/lifetime and cancellation position | No market order IDs | Unidentified; do not silently proxy |
| Participant/informed/dealer identity | No | Do not model or claim structurally |
| End-to-end quote/cancel latency | Measurable from own systems | Instrument every decision, submission, acknowledgement, cancel and fill clock |
| Risk aversion | Not a data primitive | Replace with explicit capital and drawdown constraints; sweep rather than tune to P&L |

---

## 2. Queue dynamics with Level-2 data: what FIFO identifies

### 2.1 The queue-reactive framework uses aggregated book states

Huang, Lehalle and Rosenbaum (2015) model limit additions, cancellations and market orders as intensities conditional on the current queue state. Their empirical database records prices, volume and **number of orders** to five levels whenever the book changes; it does not require market-by-order identities. Queue size is the state, and event counts divided by time spent in that state estimate the corresponding intensity. Cont and de Larrard (2013) likewise map best-queue states into depletion and price-transition probabilities. These are direct precedents for EXE-09, not second-best analogies caused by missing Level 3.

For event type $e\in\{A,C,T\}$—addition, cancellation and trade—and queue state $q$, the basic estimator is

\[
\widehat\lambda_e(q)=\frac{N_e(q)}{\mathcal T(q)},
\]

where $N_e(q)$ counts observed events of type $e$ while the queue is in state $q$, and $\mathcal T(q)$ is exposure time. Shaurya can estimate these queue-conditional arrival, cancellation and trade intensities level by level. Order counts supply average order size and a second state transition alongside quantity. The intensities do not by themselves equal our fill probability: EXE-09 must combine them with our FIFO queue-ahead and quote survival.

The difference from Huang–Lehalle–Rosenbaum is temporal resolution, not the absence of IDs. Their book was recorded whenever its state changed. Dhan packets arrive at roughly eight per second per instrument, so multiple exchange events may net into one delta. Consequently $N_e(q)$ and event order can be interval-censored. That makes intensity and queue paths estimated with measurable bounds; it does not make them unidentified.

### 2.2 FIFO gives an exact start and recursive bounds

NSE stores orders by best price and then time priority ([NSE trading-system description](https://www.nseindia.com/static/products-services/equity-market-trading-system)). Let $Q_0^{ahead}$ be displayed quantity at our price when the exchange accepts a new resting order. Under FIFO,

\[
Q_0^{ahead}=D_0(p),
\]

because every displayed order already at that price precedes us and later additions follow us. This is the exact visible-book starting queue, not a front-versus-back guess. Cancel/replace creates a new timestamp and resets the start; an amendment must never inherit the old queue path.

Thereafter, trades at our price consume the front. If resolved trade quantity is $T_k$ and resolved cancellation quantity is $C_k$ during interval $k$, then visible-book lower and upper bounds evolve as

\[
L_{k+1}=\max\{0,L_k-T_k-C_k\},\qquad
U_{k+1}=\max\{0,U_k-T_k\},
\]

with $L_0=U_0=D_0(p)$. The lower path allocates every cancellation to quantity ahead; the upper allocates every cancellation behind us. Additions at the same price after acceptance do not increase queue-ahead. An explicit cancellation-position model supplies a point estimate between the bounds:

\[
\widehat Q_{k+1}^{ahead}
=\max\{0,\widehat Q_k^{ahead}-T_k-\alpha_k C_k\},
\qquad 0\leq\alpha_k\leq1.
\]

A transparent baseline is random cancellation proportional to displayed quantity ahead; $\alpha_k$ must be labelled and calibrated, not hidden. Huang–Lehalle–Rosenbaum make a related proportional-cancellation assumption for execution probability and explicitly note that lower-priority orders may cancel more often; they say order identifiers would be needed to locate cancellations precisely. That is the residual Level-3 advantage.

These are hard bounds for the **visible FIFO book conditional on resolved events**. Hidden or iceberg quantity can sit ahead without appearing at any tier and therefore violates the visible-book upper bound. It must be carried as an unobserved residual assessed through own-order fill calibration, not wished away.

### 2.3 Packet-coalesced deltas define a feasible event set

For displayed quantity $D_k(p)$, the observed interval identity is

\[
\Delta D_k(p)=A_k-C_k-T_k.
\]

Even when $T_k$ is known, this identifies net additions minus cancellations, not both gross flows: an addition and cancellation can offset inside one packet. The simultaneous change in order count constrains how many orders appeared/disappeared and supplies average order size, so it tightens the feasible set. It still does not reveal event order or cancellation position.

D24 preserves last traded price/quantity, cumulative-volume increment, the prevailing quote used for capture-time trade signing, all receive timestamps, classifier version and an ambiguity flag. When cumulative-volume growth exceeds last-traded quantity, several prints were coalesced and only the last print’s price/side is observed. Unallocated volume must be distributed over feasible price levels as a bound, not assigned wholesale to the last price.

Define $\mathcal E_k$ as all addition/cancellation/trade sequences consistent with quantity delta, order-count delta, observed last trade, cumulative-volume increment, price-level continuity and channel-alignment rules. EXE-10 should run the FIFO recursion over every feasible extreme rather than assert a fixed ambiguity allowance:

\[
L_k=\min_{e\in\mathcal E_{1:k}}Q_k^{ahead}(e),\qquad
U_k=\max_{e\in\mathcal E_{1:k}}Q_k^{ahead}(e).
\]

This formulation cleanly separates four objects:

- **deterministically derived:** initial displayed queue-ahead and FIFO depletion by resolved trades;
- **estimated with bounds:** queue-ahead after aggregate cancellations/coalesced events and queue-conditional intensities;
- **scenario-based:** the point path under a stated cancellation-position/event-order model;
- **unidentified:** individual order identity/lifetime, cancellation location and hidden quantity.

### 2.4 What widens or tightens the bounds

Bound width $W_k=U_k-L_k$ is a primary data-quality outcome. Report it in contracts, as a fraction of displayed queue, and as an indicator that fill status differs across feasible paths. It should be measured by:

- **depth tier:** 200 levels may preserve a price level as it moves outside the top 20 and add consistency checks; 20 levels may have lower packet burden near the touch. If the 200-level channel coalesces more events or arrives later, it can instead widen temporal bounds. The sign is empirical;
- **instrument activity:** more events between packets should widen gross add/cancel and sequence ambiguity; quiet contracts should have narrower paths but fewer events for intensity estimation;
- **time of day and expiry:** the open, news bursts and near-expiry activity should be tested for larger cumulative-volume/LTQ gaps and order-count churn;
- **distance from touch:** deep levels trade less often but can enter/leave the retained tier; tier migration and price shifts can dominate their uncertainty;
- **channel alignment and packet loss:** larger trade-depth receive-time gaps, stale packets or discontinuities expand $\mathcal E_k$;
- **own OMS events:** partial fills and acknowledgement timestamps collapse parts of the feasible path and should tighten the interval.

The comparison should use matched 20- and 200-level observations for the same instruments and times. “More depth is better” is not a premise: the useful tier is the one producing narrower, better-calibrated queue and fill intervals at the quoted price.

### 2.5 Propagation into EXE-09 and empirical validation

EXE-10 should emit `q_ahead_low/base/high`, `bound_width`, feasible-event diagnostics, cancellation-model version, trade/depth alignment confidence, coalesced-trade flags, tier, entry/acknowledgement/amendment times, displayed quantity/order count at entry, and own partial fills. EXE-09 then estimates a fill-probability envelope $[P_L,P_U]$ by running the queue-reactive hazard over feasible queue paths, rather than fitting a single proxy and bootstrapping around it.

Under D23, EXE-10 is therefore **an estimator with reported bounds**, not an unqualified queue-position proxy. That category must propagate into every simulated fill, markout-conditional-on-fill estimate and economic gate.

Queue uncertainty affects fill models nonlinearly. Near depletion, a small $W_k$ can switch predicted fill status, so an unbiased point estimate of queue-ahead need not yield an unbiased fill probability. Report Brier score, log loss and coverage for the entire probability interval by bound-width decile; report the share of quote opportunities whose expected-value interval changes sign. If most economically relevant quotes remain sign-ambiguous, EXE-10 is honest but not decision-useful in that regime.

Validation has two layers:

1. **Tape validation:** check intensity stability and bound-width distributions across tier, instrument, activity, TOD and expiry; stress alternative feasible trade allocation and channel alignment. Queue-reactive Hawkes models may improve event clustering, but cannot locate cancellations or hidden quantity.
2. **Own-order validation:** compare predicted intervals with Kotak acknowledgements, partial/full fills and cancels. Own order IDs do not reveal every market order, but they test interval coverage and calibrate the cancellation-position/hidden-liquidity residual. Small live probes would be strongest and require separate live-trading authorization.

Moallemi and Yuan’s 2017 queue-position working paper remains useful for valuing rank but assumes finer data than this tape. The appropriate conclusion is not “we lack order IDs, so queue modelling is approximate.” It is: **Level-2 identifies the queue-reactive intensities and visible FIFO bounds; packet coalescing determines their measured width; only cancellation location, individual lifetimes and hidden quantity remain irreducible.**

---

## 3. Measuring adverse selection rather than invoking it

### 3.1 Quoted, effective and realized spreads

Let (m_t) be the synchronized midpoint at the fill reference time, (p_f) the fill price, and (s=+1) for maker sell / −1 for maker buy. Then

\[
\begin{aligned}
QS_t &= a_t-b_t,\\
ES_f &=2s(p_f-m_t),\\
PI_f(h)&=2s(m_{t+h}-m_t),\\
RS_f(h)&=2s(p_f-m_{t+h})=ES_f-PI_f(h).
\end{aligned}
\]

Quoted spread is an opportunity set, not revenue. Effective spread measures where the trade occurred relative to the contemporaneous midpoint. Realized spread is the maker’s marked spread after the price response. Define adverse markout per unit as (AM_f(h)=s(m_{t+h}-p_f)), positive when bad for the maker; then (RS_f(h)=-2AM_f(h)).

Huang and Stoll (1997) provide a structural spread-component framework, but its inventory/order-processing/information components require assumptions that are not credible on this feed. The robust use is the accounting identity across horizons. Conrad and Wahal (2020) show that realized spreads fall and price impact rises with horizon; their US-equity evidence is not an NSE estimate, but it demonstrates why D20 must sweep the markout term structure.

Measure at packets and at 250 ms, 1, 3, 10 and 30 seconds; 1, 5, 15 and 30 minutes; and inventory liquidation. Use midpoint, microprice and executable opposite-side prices. Every estimate must be split by quote age and must distinguish decision time, order acknowledgement, last safe cancel time, fill time and hedge time.

### 3.2 Options require a Greek-aware P&L decomposition

Raw option markout confounds several mechanisms. For a surface (C(F,\sigma,t)),

\[
\Delta C\approx \Delta\,\Delta F
+\tfrac12\Gamma(\Delta F)^2
+\mathrm{Vega}\,\Delta\sigma
+\Theta\,\Delta t+\varepsilon.
\]

For every filled option quote, record:

1. **gross option spread/markout** using the raw option book;
2. **delta component** from the synchronized underlying future;
3. **gamma component** from squared underlying movement;
4. **vega/surface component** from coherent level, skew and curvature changes;
5. **theta** over the holding interval;
6. **actual hedge P&L**, including future fill price, delay and fees;
7. **surface-model residual**, with leave-one-out fit uncertainty;
8. **statutory charges and peak margin usage**.

Two hedge counterfactuals are needed. A prompt hedge at the future’s executable price when the option order filled estimates economic selection after a feasible immediate hedge. The actual Kotak hedge isolates additional loss from execution delay. The difference is a hedge-latency estimate, not an observed causal fact, because the counterfactual fill is modelled. The residual after delta/gamma/vega/theta attribution is still not synonymous with “private information”; it is the unexplained fill-conditioned loss.

The right primary outcomes are therefore:

- raw option (AM_h);
- delta-hedged (AM_h) under prompt and actual hedges;
- Greek-attributed P&L and residual;
- total net P&L per fill and per quote opportunity;
- return on **peak margin**, not return on premium.

---

## 4. Options market making is a surface-and-portfolio problem

### 4.1 Why an option maker is different

A futures maker primarily warehouses directional inventory until it offsets or liquidates it. An option maker also warehouses convexity and volatility exposure. Delta changes with the underlying, gamma makes large moves asymmetric, vega connects positions across strikes and tenors, and theta transfers value continuously. A locally delta-neutral book can be catastrophically short gamma or short vega. The minimum unit is a whole NSE lot, so exposures arrive discontinuously.

Stoikov and Sağlam (2009) make the key theoretical distinction. If the underlying can be traded continuously, frictionlessly and without jumps, delta risk can be hedged and option inventory need not drive quotes in the same way as unhedged stock inventory. Once the hedge is discrete or costly, or volatility is stochastic, net delta and higher-order risks return. Baldacci, Bergault and Guéant (2021) formulate option market making under stochastic volatility and use a vega approximation to reduce the otherwise enormous option-chain control problem. The lesson is not that one specific Heston control should be installed. It is that quote decisions must respond to **portfolio marginal risk**.

For portfolio Greek vector (g=(\Delta,\Gamma,\mathcal V,\Theta,\ldots)), a tractable risk proxy is

\[
\mathcal R(g)=\tfrac12 g'\Sigma_g g + \text{stress and concentration penalties}.
\]

The inventory concession for buying or selling option (i) is the change

\[
\Delta\mathcal R_{i,s}=\mathcal R(g+s\,g_i)-\mathcal R(g).
\]

If the portfolio is long vega or gamma, Shaurya should generally make offers more attractive and bids less attractive; if short, reverse. But a risk-reducing fill is not automatically profitable. Toxicity and statutory costs remain separate gates.

### 4.2 Quote from a fitted surface, but treat the surface as uncertain

Quoting each strike independently invites static incoherence and ignores a shared latent state. A fitted, arbitrage-aware total-variance surface supplies a common forward, tenor level, skew and curvature. Cont and da Fonseca (2002) document low-dimensional implied-volatility dynamics; Gatheral and Jacquier (2014) show how SVI can be constrained to avoid butterfly arbitrage. The companion report’s eSSVI architecture is therefore a sensible *coordinate system*.

It is not a truth oracle. Dumas, Fleming and Whaley (1998) show that a flexible smile fit need not forecast out of sample. On this feed, an approximately 3-second surface refresh can contain component quotes that were already old when the fit began. A fast participant sees the future and neighboring strikes change before Shaurya’s surface does. A smooth stale surface is still stale.

Each quote decision should carry:

- future quote age and change since the last surface fit;
- raw option bid/ask age and last trade age;
- surface age and computation completion time;
- leave-one-out residual for the candidate strike;
- fit uncertainty and number/quality of live strikes;
- parity and monotonicity/convexity bands;
- delta-adjusted underlying move since inputs were sampled;
- neighboring-strike and neighboring-tenor innovation;
- end-to-end order/cancel latency quantile.

The fair-value band should include an empirical high quantile of

\[
\Delta\,\Delta F + \tfrac12\Gamma(\Delta F)^2
+\mathcal V\,\Delta\sigma
\]

over the measured time from last trustworthy input through the last moment a cancel can prevent execution. If this band consumes the available spread, do not quote. “Surface stale” should be a hard state, not merely a feature a model may learn to ignore.

### 4.3 Hedging choices

**Underlying future.** The nearest liquid index future is the natural *risk instrument* for delta because it usually has tighter price discovery and adds no vega/gamma. It is not automatically the cheapest transaction: from April 2026, futures-sale STT makes a round trip extremely expensive (worked below). Trade-by-trade rehedging may destroy the option spread, so the data must compare hedge bands, internal delta netting and less frequent passive futures hedges. The future does not hedge gamma, vega or skew, and its own bid–ask, tax, margin and latency matter. D21 forbids crossing, so a hedge cannot be assumed immediate unless a separate passive hedge is actually filled. Reports should show both a prompt executable-hedge counterfactual and the realized passive hedge path.

**Other options.** A neighboring strike or tenor can reduce gamma, vega or skew exposure. It also adds another uncertain queue, another option-premium fee stack, surface basis, margin path and leg risk. A nominally better Greek hedge may be economically inferior after two passive fills. Use options only when the reduction in portfolio stress loss exceeds incremental fill-selection, cost and capital charges under conservative bounds.

**Internal netting.** The cheapest hedge is often an offsetting customer fill elsewhere in the chain, but waiting is itself a risk decision. Estimate the arrival-time distribution of inventory-reducing fills and compare it with the adverse move distribution while waiting. Never credit future internalisation before it occurs.

### 4.4 Spread setting while the underlying moves

For an option with delta Δ, even a small underlying move during stale/cancel latency changes fair value. The minimum half-spread should therefore grow with local delta, gamma, volatility, jump state, surface uncertainty and the tail of measured latency—not only with the option’s own displayed spread. Near-expiry ATM options can become unquotable on a retail feed because gamma makes the fair-value band jump several ticks between packets. Deep OTM options have low delta but can still be toxic when volatility/skew reprices, and their sparse books make exiting inventory difficult.

Quote-side logic must be joint across the chain. If the future rises while call offers remain stale, selling those calls is dangerous; if the fitted surface has not yet updated, the fact that the offer looks rich to the old surface is evidence against it, not for it. Conversely, a coherent local strike residual that persists after fresh future/surface inputs, lies outside executable bands and has benign fill-conditioned markout may justify a wider passive quote. That is a proposition to test, not a presumed surface-arbitrage trade.

---

## 5. The non-colocated maker problem

### 5.1 Why speed changes the fill distribution

Budish, Cramton and Shim (2015) describe continuous-limit-order-book sniping: public news creates a race between stale-quote cancellation and taking. Faster private speed is socially duplicative but privately valuable. Aquilina, Budish and O’Neill (2022), using UK exchange race data, find races concentrated in microseconds and dominated by a handful of firms. Foucault, Hombert and Roşu (2016) model how speed changes news trading; Menkveld and Zoican (2017) show that faster exchange latency can either improve or worsen liquidity depending on the ratio of news to liquidity demand. These are not NSE option estimates, but the mechanism transfers directly.

Gao and Wang (2020) show theoretically that a market maker with latency can still profit when uninformed market-order flow is sufficiently abundant relative to price jumps and the horizon is long enough. That is an existence result under a model, not evidence that this feed meets the conditions. Shaurya’s job is to estimate their empirical analogue: benign fills must pay for stale fills and all costs.

The structural disadvantage is a two-sided selection:

1. when the quote is still favorable to Shaurya, faster competitors remain ahead or improve/cancel, reducing Shaurya’s fill probability;
2. when news makes the quote favorable to the taker, the stale quote is rapidly executed, raising Shaurya’s fill probability.

This is why unconditional spread width or trade volume cannot establish maker edge.

### 5.2 Candidate slow-maker niches

**Table 2** states the possible niches as refutable hypotheses, not recommendations.

**Table 2. Candidate slow-maker niches and kill tests**

| Candidate | Mechanism that could leave edge | Evidence required from Shaurya | What falsifies it | Prior verdict |
|---|---|---|---|---|
| **At-touch liquid NIFTY** | Large benign retail flow might compensate for sniping | Conservative fill bounds; positive realized spread at short and liquidation horizons after all costs; stable across latency tails | Markout turns negative with quote age/OFI jumps; profitability exists only under optimistic cancellation/event sequencing or ignored hidden quantity | **Presume no edge** |
| **Wider, farther-from-touch quotes** | More edge per fill and less exposure to ordinary micro-moves | Net value (V_s(d,x)) peaks at (d>0); fills remain frequent enough; tail losses bounded | Fill probability collapses or fills occur almost exclusively during jumps/sweeps | Plausible test, not established |
| **Far strikes / less liquid expiries** | Fewer fast firms may compete; displayed spreads wider | Wider spread survives stale-surface, exit and hedge costs; fill-conditioned markouts benign | Sparse fills, poor surface fit, large quote-age toxicity, capital trapped | Often a mirage |
| **MIDCPNIFTY / less contested index** | Lower competition could preserve spread | Own-order fill calibration and net return-on-margin exceed NIFTY with matched risk | Larger lot, worse hedge liquidity and jump risk erase gross spread | Uncertain; do not equate illiquidity with edge |
| **Longer holding horizon** | Microsecond advantage may matter less once inventory mean-reverts or earns carry | Realized spread recovers at longer horizons and drawdown/margin path is tolerable | Short-horizon stale loss persists or compounds; longer horizon merely hides inventory risk | Conditional at best |
| **Liquidity-withdrawal states** | Fast makers may retreat, leaving unusually wide compensation | Wide spreads exceed latency uncertainty and adverse markout; recovery is fast enough to exit | Withdrawal signals information; fill-conditioned losses rise more than spread | High-value test, strict gate |
| **Slow information fast firms neglect** | Surface/carry/cross-tenor state may be less latency-sensitive | Signal persists for minutes, changes fair value coherently, and passive fill selection remains benign | Edge is already in quotes or only fills after fast repricing | Possible only at slower horizons |

Three cautions follow. First, quoting farther away does not remove sniping; it changes the jump size needed to reach the quote. Second, illiquidity is simultaneously a source of spread and a cost of exit, hedge and estimation. Third, longer holding horizons do not erase the initial adverse fill. A strategy that appears profitable only after marking to a smoothed surface rather than an executable exit has not demonstrated edge.

### 5.3 Explicit no-quote regimes

Until data overturn the presumption, Shaurya should not quote when:

- the future or candidate option input is older than a state-specific maximum age;
- packet gaps or channel-order ambiguity exceed calibrated limits;
- the underlying moved beyond the option’s latency band since surface sampling;
- spread in ticks is less than conservative statutory + hedge + adverse-markout cost;
- queue bounds are too wide to sign expected value;
- gamma/vega stress or peak margin exceeds limits;
- opening, scheduled-event or near-expiry states have not independently passed the viability gate;
- a cancel is pending or acknowledgement state is uncertain.

These are research stop rules. Threshold values must come from preregistered distributions, not from backtest P&L maximisation.

### 5.4 Where the literature disagrees—and why

The literature does not imply that all speed is harmful or that every slow maker must lose. Budish et al. and Aquilina et al. emphasize stale-quote races and latency rents; Menkveld and Zoican show that lower latency also lets makers refresh faster, which can narrow spreads when ordinary liquidity demand is large relative to news. Gao and Wang obtain positive delayed-maker profits under sufficiently favorable uninformed-flow and horizon conditions. The disagreement is chiefly about the **mix of news jumps, benign liquidity demand, competition and market design**, not the existence of latency. Those primitives must be measured locally.

Option-control results also differ by completeness assumptions. In Stoikov–Sağlam’s frictionless complete-market case, continuous underlying hedging removes inventory dependence; with illiquid hedging, jumps or stochastic volatility, delta/gamma/vega inventory matters. NSE’s tax, lot and passive-only constraints make the incomplete case economically relevant, but they do not select a unique stochastic-volatility model.

Finally, spread decompositions do not uniquely identify “information,” inventory and order processing. Huang–Stoll obtains components under structural restrictions, while modern short-horizon work stresses that correlated order flow can be toxic over a maker’s holding period even without a fundamental private signal. This report therefore uses realized-spread identities and Greek attribution, and labels the remainder “unexplained selection,” not informed trading.

---

## 6. NSE/India-specific maker economics

### 6.1 Statutory cost arithmetic

From 1 April 2026, NSE reports STT of 0.15% of option premium on a sale, 0.05% of futures notional on a sale, and 0.15% of intrinsic value on exercised options borne by the purchaser. The previous rates through 31 March 2026 were 0.10%, 0.02% and 0.125%, respectively ([NSE STT schedule](https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax)). Backtests must version these rates.

Effective 1 March 2026, NSE transaction charges are ₹3,553 per crore of option premium per side (0.03553%) and ₹183 per crore of futures turnover per side (0.00183%), inclusive of IPFT ([NSE circular FA73061](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf)). SEBI turnover fees are ₹10/crore (0.0001%) per side. Stamp duty is charged on purchases: 0.003% of option premium and 0.002% of futures notional ([NSE stamp schedule](https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes)). GST at 18% applies to brokerage, exchange transaction charges and SEBI fees, not to STT or stamp duty.

Kotak Neo states that API orders on eligible Trade Free plans have zero brokerage and zero API charges from 1 November 2025 ([Kotak Neo, broker source](https://www.kotakneo.com/platform/kotak-neo-trade-api/)). Zero brokerage does **not** waive STT, exchange/IPFT charges, SEBI fees, stamp duty, GST, margin, slippage or hedge cost.

Consider buying and later selling one NIFTY option at premium ₹20 per index unit with the current 65-unit lot. Each side turns over ₹1,300.

**Table 3. Worked option round-trip statutory cost, ₹20 premium and 65-unit lot**

| Charge | Buy | Sell |
|---|---:|---:|
| STT (0.15% on sale) | ₹0.0000 | ₹1.9500 |
| NSE/IPFT (0.03553%) | ₹0.4619 | ₹0.4619 |
| SEBI (0.0001%) | ₹0.0013 | ₹0.0013 |
| Stamp (0.003% on buy) | ₹0.0390 | ₹0.0000 |
| GST, assuming zero brokerage | ₹0.0834 | ₹0.0834 |
| **Total** | **₹0.5856** | **₹2.4966** |

The round trip costs about **₹3.082 per lot**, or **₹0.0474 per option unit**—almost one ₹0.05 option tick—before hedge trading, adverse selection and margin return. The same percentage arithmetic applies to other lot sizes; the rupee total scales with lot and premium.

An important correction to a common intuition is needed. Because these charges are primarily percentages of premium, the rupee cost **does** scale down with a cheaper option, while the percentage burden does not disappear. At ₹5 premium, the same approximate 0.237% round-trip statutory rate is ₹0.0119 per unit (0.24 tick); at ₹100 it is ₹0.237 per unit (4.74 ticks). Cheap OTM options are not automatically uneconomic because of STT in tick units. They may be uneconomic because fills are sparse/toxic, fair value is uncertain, exit is costly, and the minimum lot concentrates tail risk. The correct filter computes costs in rupees and ticks for every contract rather than repeating “cheap options are heavily taxed.”

The futures arithmetic is much harsher. At a hypothetical NIFTY futures price of 25,000 and current 65-unit lot, notional is ₹1,625,000. With zero brokerage, a sale costs approximately ₹812.50 STT + ₹29.74 NSE/IPFT + ₹1.63 SEBI + ₹5.65 GST = **₹849.51**. A purchase costs approximately ₹29.74 NSE/IPFT + ₹1.63 SEBI + ₹32.50 stamp + ₹5.65 GST = **₹69.51**. A buy/sell round trip is therefore about **₹919.02 per lot, or 14.14 index points**. At the ₹0.10 tick applicable around 25,000, that is about **141 ticks** before spread, markout and margin. Thus one-tick futures market making and reflexive per-fill futures hedging are statutorily nonviable under these rates unless another leg earns enough to cover the entire tax. This conclusion follows from arithmetic, not from a backtest.

For a maker filled on the offer, sale STT is paid immediately. Later buying back incurs stamp, transaction/SEBI fees and GST. If inventory is instead exercised/assigned, exercise STT and settlement economics require a separate path; Shaurya should normally prevent accidental expiry exposure through explicit cutoffs.

### 6.2 Margin and capital return

NSE initial margin combines SPAN-based risk margin and additional components; index derivatives carry an extreme-loss margin, and short index options face an additional expiry-day tail-risk ELM ([NSE margin page](https://www.nseindia.com/static/products-services/equity-derivatives-margins)). SEBI’s 2024 derivatives framework introduced upfront collection of option premium from buyers and removed calendar-spread treatment on the expiry day because the expiring leg disappears; NSE Clearing also applies an additional 2% ELM to short index options on expiry day ([SEBI master risk chapter](https://www.sebi.gov.in/sebi_data/commondocs/dec-2024/RE_Chapter%205%20-%20Exchange%20Traded%20Derivatives%20FINAL_1_p.pdf); [NSE Clearing circular CMPT64639](https://nsearchives.nseindia.com/content/circulars/CMPT64639.pdf)).

The economically relevant denominator is

\[
\text{return on capital}=\frac{\text{net maker P&L}}{\max_t \{\text{broker margin blocked}_t+\text{premium cash}_t+\text{liquidity buffer}_t\}}.
\]

Peak path matters. A call sale followed seconds later by a hedge may temporarily consume far more margin than the final portfolio. Spread benefits can vanish into expiry. Backtests should replay broker margin snapshots or a conservative SPAN-style scenario after each possible partial fill, not compute margin only on the end-of-bar net position.

### 6.3 Lots and minimum risk per quote

The October 2024 revision created the familiar 75/30/65/120 schedule in the brief for NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY, but it is not the current full schedule. NSE’s October 2025 periodic revision changed NIFTY 75→65, BANKNIFTY 35→30, FINNIFTY 65→60 and MIDCPNIFTY 140→120, with contract-specific transition dates into 2026 ([NSE circular FAOP70616](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf)). As of this report’s 2026 setting, the standard lots are therefore **65, 30, 60 and 120**, subject to the actual contract master.

One option premium point is ₹65/₹30/₹60/₹120 per lot; one ₹0.05 tick is ₹3.25/₹1.50/₹3.00/₹6.00. MIDCPNIFTY’s apparently less-contested market comes with the largest minimum option unit and potentially poorer futures hedge liquidity. Every historical record must join the dated contract master; multiplying 2024 prices by 2026 lots creates false P&L and risk.

### 6.4 Tick size and queue value

NSE index options have a ₹0.05 tick. Index futures use level-dependent ticks under current contract specifications: ₹0.05 up to index level 15,000, ₹0.10 above 15,000 through 30,000, and ₹0.20 above 30,000 ([NSE contract specifications](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications)).

“Large tick” is not a permanent instrument label. In the microstructure sense, a contract is large-tick when the constrained spread is usually one tick and queue priority has material value; it is small-tick when spreads regularly span multiple ticks and price improvement competes with rank. Measure fraction of time at one-tick spread, depth/order counts at touch, queue turnover, short-run volatility in ticks and fill value by rank. Liquid ATM NIFTY options may behave large-tick; far strikes may not. The data must decide by contract × moneyness × DTE × regime.

### 6.5 Maker schemes and expiry architecture

NSE’s current Liquidity Enhancement Scheme page lists Silver options on goods and Electricity futures, not equity index options ([NSE LES, primary source](https://www.nseindia.com/static/market-data/liquidity-enhancement-scheme)). I found no current formal rebate/obligation scheme for NSE index options. Where an LES exists, designated market makers are registered trading members satisfying scheme obligations; a non-member retail client cannot claim designated-maker incentives merely by posting passive orders. Shaurya should model zero rebate unless Kotak supplies a written applicable schedule.

NSE rationalised weekly index derivatives in November 2024 so that only NIFTY retained weekly options; BANKNIFTY, MIDCPNIFTY and FINNIFTY weekly contracts were discontinued ([NSE circular FAOP64506](https://nsearchives.nseindia.com/content/circulars/FAOP64506.pdf)). After the 28 August 2025 transition, index F&O expiries moved from Thursday to Tuesday ([NSE circular FAOP68685](https://nsearchives.nseindia.com/content/circulars/FAOP68685.pdf)). A “Thursday effect” pooled across these breaks is not a stable economic state. Use continuous time-to-expiry, weekly/monthly status and rule-regime IDs.

---

## 7. Inverting the companion report’s twelve stories

The table below addresses the ranked stories exactly as they appeared in the companion report. “Survives” means it remains useful to a maker; it does not mean the original directional mechanism is profitable.

**Table 4. Directional-story inversion for a passive maker**

| Prior rank and story | Survives? | Maker target | How the test changes |
|---|---|---|---|
| **1. Multi-level OFI / queue depletion** | **Yes, but sign inverts by side** | Fill hazard and side-specific adverse markout conditional on queue bounds, not next mid move | Confirm if OFI/depletion monotonically predicts which resting side fills and whether its realized spread worsens beyond spread/volatility. Falsify if it predicts mid moves but adds nothing to (P(fill)) or fill-conditioned value. Deep OFI that only forecasts direction may be useless to quoting. |
| **2. Cross-contract price discovery** | **Yes; promoted as stale-quote defence** | Which option/future is stale and whether a candidate quote can be cancelled before the leader reprices it | Confirm if relative freshness/innovation predicts toxic fills in the lagging contract and a no-quote gate improves lower-bound maker value. Falsify if lead–lag vanishes after synchronized quote age or cannot forecast own-fill markouts. Do not use it to cross the laggard. |
| **3. Joint underlying/surface innovations** | **Yes; core options control** | Fair-value uncertainty, vega/skew pick-off and chain-coherent quote width | Confirm if fresh futures and surface-factor moves explain fill toxicity and required cushion beyond raw option spread. Falsify if fitted factors add nothing after raw-neighbor freshness or only appear at the 3-second fit clock. |
| **4. Liquidity resilience** | **Yes; promoted** | Whether a fill occurs in a temporary depletion that recovers or an information state that continues; expected liquidation cost | Confirm if refill speed after matched shocks predicts realized-spread recovery and exit ability. Falsify if resilience is descriptive only or known only after the quote could no longer be cancelled. |
| **5. State-dependent impact / lambda** | **Yes, with a different dependent variable** | Term structure of fill-conditioned price impact and hedge cost | Confirm if thin/high-vol/near-expiry states have worse maker price impact at fixed quote distance and queue bound. Falsify if lambda predicts unconditional response but not fill selection. Never interpret it as informed participation. |
| **6. Expiry × time × moneyness** | **Yes; risk gate rather than alpha** | Quote viability, gamma/latency band, fill rate, margin and markout by continuous DTE/TOD/moneyness | Confirm if these states shift lower-bound quote value reproducibly across policy regimes. Falsify a weekday story if effects do not move from Thursday to Tuesday or survive matched liquidity controls. |
| **7. Implied–realized variance / jumps** | **Conditional, lower frequency** | Inventory-risk budget, vega/skew width and expected delta-hedged holding return—not immediate direction | Confirm only if the state changes maker inventory P&L or safe width after fill selection and costs. Falsify if a variance-premium forecast cannot survive actual passive entry/exit or merely rationalises holding losing inventory longer. |
| **8. Surface reversion versus quote/fitter dislocation** | **Yes, materially promoted** | Whether a strike can be quoted around a fresh surface with benign selection; leave-one-out residual correction | Confirm if residuals outside bid–ask/model uncertainty generate positive passive fill-conditioned value through movement of the outlier, not the whole surface. Falsify if stale inputs, fit inclusion, hedge costs or wide-leg risk explain it. |
| **9. Intraday seasonality/open** | **Yes as normalization and no-quote control** | Time-varying fill, markout, latency and margin risk | Confirm if within-TOD calibration improves quote-value reliability. Falsify standalone edge if it vanishes after activity/expiry states. The open is more likely a quote-withdrawal regime than alpha. |
| **10. Basis/calendar spread/roll** | **Limited** | Futures fair-value guard, hedge selection and capital/margin state | Confirm if basis/carry deviations affect passive hedge fills or chain inventory value after both-leg costs. Falsify if deviations sit inside execution/funding/margin bands. It is not a reason to quote an option independently. |
| **11. Global overnight/opening gap** | **No with current data; defensive only** | Opening no-quote duration and uncertainty band | Current tape can test only gap-absorption risk, not its source. Confirm a defensive gate if opening fill markouts are adverse. Directional attribution remains unidentified until GIFT/global/FX data are added. |
| **12. Dealer gamma/charm/vanna/pinning** | **No structural survival** | At most reduced-form strike/OI state for maker risk | The maker target does not repair missing dealer sign. A high-OI strike may condition gamma/liquidity, but it cannot identify dealer hedging. Falsify any structural claim if either assumed sign explains outcomes ex post. Keep out of quote logic unless a reduced-form effect replicates. |

The inversion changes priorities. Ranks 2, 3, 4 and 8 become direct stale-value and exit-risk controls. Rank 1 remains important, but chiefly for selection and fill probability rather than alpha. Rank 7 may matter for the inventory book, not quote-by-quote timing. Rank 12 remains unidentified.

---

## 8. What Shaurya should actually do: a preregistered quoting agenda

These are stable claim IDs for D22. Each is a proposition to measure before strategy selection. The first four are gates; no control-model optimisation is justified until they pass.

### Priority 0 — instrumentation and labels

**MK-01 — End-to-end latency defines the stale-value budget.**  
**Mechanism:** fill selection depends on the interval from last trusted market input through decision, Kotak submission, NSE acknowledgement and last effective cancel.  
**Measure:** full empirical distributions and tails of feed age, processing, order acknowledgement, cancel acknowledgement and fill/hedge delay by instrument/TOD/load; delta/gamma/vega fair-value change during each interval.  
**Required evidence:** stable timestamp reconciliation and an uncertainty band narrow enough to compare with spreads.  
**Falsifier/stop:** clocks cannot be reconciled, acknowledgements are missing, or the 95th/99th-percentile fair-value change consumes available spread in a regime. That regime is unquotable.

**MK-02 — Visible FIFO queue-ahead is bounded and may be decision-useful.**  
**Mechanism:** displayed quantity fixes the initial queue; trades at our price consume the front; cancellation position and packet-coalesced event order create the interval. Queue-conditional intensities are estimable from Level-2 deltas/order counts.  
**Measure:** EXE-10 low/base/high (Q^{ahead}), bound width and queue-conditional addition/cancel/trade intensities by tier × instrument × activity × TOD; then EXE-09 fill-probability intervals calibrated against own Kotak partial/full fills.  
**Required evidence:** realized own fills fall inside intervals, intensity estimates are stable enough out of sample, and interval width shrinks enough to sign quote value in some states.  
**Falsifier/stop:** persistent miscalibration or bounds so wide that profitable and unprofitable cases overlap. Do not replace measured bounds with a tuned point path.

**MK-03 — Fill-conditioned markout, not directional accuracy, is the governing label.**  
**Mechanism:** passive fills are selected when a quote becomes favorable to the taker.  
**Measure:** (P(fill)), raw and Greek-adjusted (AM_h), realized spread and actual liquidation P&L across D20 clocks/horizons.  
**Required evidence:** labels agree across midpoint/microprice/executable marks and survive quote-age controls.  
**Falsifier/stop:** only midpoint directional accuracy improves while net maker value does not.

**MK-04 — Costs and capital are contract-state labels, not a final haircut.**  
**Mechanism:** asymmetric STT, premium-linked charges, hedge turnover and margin paths change the quote threshold.  
**Measure:** versioned per-fill statutory ledger, actual Kotak charges, broker margin snapshots after partial fills, peak capital and exercise scenarios.  
**Required evidence:** replay reconciles to broker statements within a preregistered tolerance.  
**Falsifier/stop:** unreconciled cost or margin accounting; no profitability claim is admissible.

### Priority 1 — reject or retain the basic maker opportunity

**MK-05 — At-touch liquid-index quoting is dominated unless benign flow pays for latency.**  
**Mechanism:** queue competition removes benign fills while stale quotes retain toxic fills.  
**Measure:** side/state-specific lower and upper bounds on (V_s(0,x)), including actual latency, all charges and hedge path, for liquid NIFTY/BANKNIFTY futures and ATM options.  
**Required evidence to overturn the no-edge prior:** the conservative lower bound is positive out of sample across adjacent expiries and multiple volatility regimes, with economically meaningful fill count and return on peak margin.  
**Falsifier:** value is positive only under favorable cancellation/event-sequencing paths, ignored hidden quantity, midpoint exits, excluded tail days or optimistic hedge timing. Then switch the regime off.

**MK-06 — A positive quote-distance frontier may exist.**  
**Mechanism:** distance sacrifices fill probability for larger gross edge and fewer ordinary stale fills.  
**Measure:** nonparametric (P(fill\mid d,x)), fill-conditioned markout and (V_s(d,x)) at 0/1/2/3+ ticks or normalized vol distance, with queue bounds.  
**Required evidence:** an interior distance has positive conservative value and adequate fills.  
**Falsifier:** farther fills occur only in jumps/sweeps so markout worsens as fast as spread improves, or probability becomes negligible.

**MK-07 — Quote age has a monotone toxicity curve and should trigger cancellation.**  
**Mechanism:** older quotes embed more unobserved market movement.  
**Measure:** fill rate and adverse markout by quote age, last future move, packet count, surface age and pending-cancel state; use only information available before fill.  
**Required evidence:** a reproducible age threshold where lower-bound value crosses zero.  
**Falsifier:** threshold is unstable or all ages are negative. In the latter case, cancel speed cannot rescue that regime.

### Priority 2 — options-chain control

**MK-08 — Surface freshness is a hard pick-off gate.**  
**Mechanism:** option prices share a moving forward/volatility surface; stale fits make coherent but obsolete quotes.  
**Measure:** fill-conditioned Greek-adjusted markout against raw quote age, fit age, future move since fit, neighboring-strike innovation and leave-one-out residual.  
**Required evidence:** freshness gates materially improve conservative quote value without eliminating all fills.  
**Falsifier:** apparent improvement is just lower event intensity, or fitted surface variables add nothing beyond raw option/future freshness.

**MK-09 — Greek inventory should skew chain quotes by marginal portfolio risk.**  
**Mechanism:** a fill changes correlated delta/gamma/vega exposure across strikes and tenors.  
**Measure:** ex ante (\Delta\mathcal R_{i,s}), subsequent stress P&L, fill rates and opportunity cost for inventory-improving versus inventory-worsening sides. First estimate the curves; only then compare scalar-delta and multi-Greek controls.  
**Required evidence:** marginal-risk ordering predicts tail loss and capital usage out of sample, and modest skew reduces stress without giving away more markout than it saves.  
**Falsifier:** Greek estimates/surface shocks are too unstable, or “risk-reducing” concessions systematically attract more toxic fills than their risk benefit.

**MK-10 — Futures are the default delta hedge; option hedges must beat their incremental frictions.**  
**Mechanism:** futures remove delta cheaply; options can reduce vega/gamma but add another selected passive leg.  
**Measure:** prompt and actual passive-future hedge P&L versus matched option-hedge and internal-netting counterfactuals, including charges, queue uncertainty, margin and stress.  
**Required evidence:** an option hedge has lower total risk-adjusted cost in a prespecified state.  
**Falsifier:** Greek improvement disappears after two-leg execution and margin. Retain future-only hedge plus hard gamma/vega limits.

### Priority 3 — search for defensible slow-maker niches

**MK-11 — Liquidity resilience can identify rare states where wide spreads compensate risk.**  
**Mechanism:** after some depletion shocks, fast liquidity withdraws but the move is temporary and books refill.  
**Measure:** matched response paths of spread/depth/future/surface plus hypothetical quote fills, using only pre-quote state and conservative rank.  
**Required evidence:** a preobservable state predicts both wide compensation and benign realized spread/exit.  
**Falsifier:** resilience is known only after the fill or withdrawal reliably precedes persistent moves.

**MK-12 — “Less contested” contracts must outperform after risk matching, not before.**  
**Mechanism:** far strikes, longer expiries or MIDCPNIFTY may have less speed competition but worse exit and hedge conditions.  
**Measure:** compare conservative value per quote, per fill and per peak-margin rupee across index × DTE × moneyness, matched on delta/gamma/vega, spread in volatility units, event count and holding risk.  
**Required evidence:** repeated positive lower-bound value with enough observations and manageable inventory liquidation.  
**Falsifier:** gross spread advantage is absorbed by sparse/toxic fills, surface uncertainty, larger lots, margin or exit cost.

**MK-13 — Opening and expiry quoting require independent proof.**  
**Mechanism:** information assimilation, gamma and margin tails differ sharply at the open and near Tuesday expiry.  
**Measure:** all MK-01–MK-12 outcomes separately by open window, continuous DTE, moneyness and pre/post rule regime.  
**Required evidence:** positive lower-bound value within that exact state, not pooled-day profitability.  
**Falsifier:** tail latency/markout or margin dominates. Default is no quote.

### Decision sequence

1. Build MK-01–MK-04 labels and reconciliation gates.
2. Run MK-05 as a kill test on the most liquid contracts. A negative result is useful: it prevents expensive model work in a structurally dominated regime.
3. If any state survives, estimate MK-06–MK-08 nonparametrically with purged walk-forward splits and rule-regime separation.
4. Add portfolio controls MK-09–MK-10 only after quote-level economics are positive before inventory concession.
5. Search niches MK-11–MK-13 with multiplicity control and adjacent-expiry replication.
6. Only then choose a control approximation (table, monotone model, GLFT-style approximation or other). Model complexity follows measured opportunity.

For every claim, report quote opportunities, interval fills, observed own fills, realized-spread curves, tail loss, turnover, statutory costs, hedge cost, peak margin, and sensitivity to queue/clock assumptions. A positive mean without a positive conservative lower bound is not deployment evidence.

### Inference and economic-unit protocol

All tests are out of sample with purged walk-forward splits. Overlapping markout horizons create dependent observations, so uncertainty should be computed with day-level block bootstrap or standard errors clustered by trading day; where the same expiry appears across days, a second expiry cluster or expiry-block bootstrap is required. Contract and policy-regime holdouts are stronger than random quote splits. Multiple states/distances in MK-05–MK-13 require a predeclared family and false-discovery control or familywise simultaneous confidence bands. Fill-probability intervals must nest queue-position uncertainty rather than bootstrap only the fitted model.

Report effects in at least four common economic units: rupees per lot, option/future ticks, basis points or volatility points where appropriate, and rupees per peak-margin rupee. Also report per quote opportunity and per observed fill. The deployment statistic is the lower confidence bound of net value under the pessimistic queue model; a statistically precise midpoint-marked gain with negative executable value fails.

---

## 9. Claim–evidence ledger

**Table 5. Claim status and identification boundary**

| Claim ID | Status | Evidence class | What is established | What is not established |
|---|---|---|---|---|
| C-MK-01 | Structural inference | Peer-reviewed latency theory + NSE mode data | A slow maker is exposed to stale-quote selection; colocation is economically material | That every NSE contract/state is unprofitable |
| C-MK-02 | Theory/accounting | Peer-reviewed microstructure | Maker value depends jointly on fill probability and fill-conditioned markout | Shaurya’s empirical function before EXE-09/10 and own fills |
| C-MK-03 | Partial identification | NSE FIFO rule + feed schema + queue literature | Initial visible queue-ahead, trade depletion, queue-conditional intensities and later queue-ahead bounds are recoverable; bound width is measurable | Cancellation position, individual identity/lifetime and hidden quantity |
| C-MK-04 | Theory | Peer-reviewed option-MM work | Chain inventory is multi-Greek and surface-linked | Correct risk penalty or stochastic-volatility model for NSE |
| C-MK-05 | Primary-rule fact | NSE/SEBI | Current STT, transaction charges, lots, expiry/margin rules and no listed index-option LES | Future tariffs or broker-specific unpublished rebates |
| C-MK-06 | Open empirical question | None yet | Candidate slow-maker niches are testable | That wider/less-liquid/longer-horizon quoting has an edge |

---

## 10. Limitations and honest stopping point

India-specific public evidence on high-frequency index-option maker profitability is thin. I found primary rules and international mechanisms, but no credible public study using a retail-broker 20/200-level NSE feed, own passive-order acknowledgements and Greek-attributed markouts. International equity race evidence establishes a danger, not a calibrated NSE loss.

The tape can estimate visible FIFO queue-ahead and queue-conditional order-flow intensities with measured bounds; it cannot identify cancellation position, individual order identity/lifetime, hidden quantity, participant type, dealer positioning or private information. Aggressor side is a versioned D24 capture-time classification, not a direct vendor field, and coalesced intervals remain explicitly ambiguous. Surface Greeks are model outputs. Prompt-hedge P&L is a counterfactual. Historical fill replay cannot prove live fills. Current fee and contract facts can change and must be versioned from circular effective dates.

Accordingly, this report does **not** conclude that Shaurya has a market-making edge. It concludes that a defensible search is possible if the system first measures latency, queue bounds, own fills, Greek-aware markouts, all-in costs and peak margin. If conservative value remains non-positive in liquid at-touch and wider/niche regimes, the correct output of D8 is **do not market make on this feed**. Strategy is not owed a positive answer.

---

## Bibliography

### Peer-reviewed theory and evidence

- Aquilina, Matteo, Eric Budish, and Peter O’Neill (2022), “Quantifying the High-Frequency Trading ‘Arms Race’,” *Quarterly Journal of Economics* 137(1), 493–564. [DOI](https://doi.org/10.1093/qje/qjab032).
- Avellaneda, Marco, and Sasha Stoikov (2008), “High-Frequency Trading in a Limit Order Book,” *Quantitative Finance* 8(3), 217–224. [DOI](https://doi.org/10.1080/14697680701381228).
- Baldacci, Bastien, Philippe Bergault, and Olivier Guéant (2021), “Algorithmic Market Making for Options,” *Quantitative Finance* 21(1), 85–97. [DOI](https://doi.org/10.1080/14697688.2020.1766099).
- Baron, Matthew, Jonathan Brogaard, Björn Hagströmer, and Andrei Kirilenko (2019), “Risk and Return in High-Frequency Trading,” *Journal of Financial and Quantitative Analysis* 54(3), 993–1024. [DOI](https://doi.org/10.1017/S0022109018001096).
- Bergault, Philippe, David Evangelista, Olivier Guéant, and Douglas Vieira (2021), “Closed-Form Approximations in Multi-Asset Market Making,” *Applied Mathematical Finance* 28(2), 101–142. [DOI](https://doi.org/10.1080/1350486X.2021.1949359).
- Budish, Eric, Peter Cramton, and John Shim (2015), “The High-Frequency Trading Arms Race: Frequent Batch Auctions as a Market Design Response,” *Quarterly Journal of Economics* 130(4), 1547–1621. [DOI](https://doi.org/10.1093/qje/qjv027).
- Conrad, Jennifer, and Sunil Wahal (2020), “The Term Structure of Liquidity Provision,” *Journal of Financial Economics* 136(1), 239–259. [DOI](https://doi.org/10.1016/j.jfineco.2019.09.008).
- Cont, Rama, and Adrien de Larrard (2013), “Price Dynamics in a Markovian Limit Order Market,” *SIAM Journal on Financial Mathematics* 4(1), 1–25. [DOI](https://doi.org/10.1137/110856605). See also Geliang Zhang, Hugh Christensen, Guolong Li, and Simon Godsill (2016), “A Correction Note for Price Dynamics in a Markovian Limit Order Market,” *SIAM Journal on Financial Mathematics* 7(1), 152–158. [DOI](https://doi.org/10.1137/16M1057437).
- Cont, Rama, and José da Fonseca (2002), “Dynamics of Implied Volatility Surfaces,” *Quantitative Finance* 2(1), 45–60. [DOI](https://doi.org/10.1088/1469-7688/2/1/304).
- Copeland, Thomas E., and Dan Galai (1983), “Information Effects on the Bid-Ask Spread,” *Journal of Finance* 38(5), 1457–1469. [DOI](https://doi.org/10.1111/j.1540-6261.1983.tb03834.x).
- Dumas, Bernard, Jeff Fleming, and Robert E. Whaley (1998), “Implied Volatility Functions: Empirical Tests,” *Journal of Finance* 53(6), 2059–2106. [DOI](https://doi.org/10.1111/0022-1082.00083).
- Foucault, Thierry, Johan Hombert, and Ioanid Roşu (2016), “News Trading and Speed,” *Journal of Finance* 71(1), 335–382. [DOI](https://doi.org/10.1111/jofi.12302).
- Gao, Xuefeng, and Yunhan Wang (2020), “Optimal Market Making in the Presence of Latency,” *Quantitative Finance* 20(9), 1495–1512. [DOI](https://doi.org/10.1080/14697688.2020.1741670).
- Gatheral, Jim, and Antoine Jacquier (2014), “Arbitrage-Free SVI Volatility Surfaces,” *Quantitative Finance* 14(1), 59–71. [DOI](https://doi.org/10.1080/14697688.2013.819986).
- Glosten, Lawrence R., and Paul R. Milgrom (1985), “Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders,” *Journal of Financial Economics* 14(1), 71–100. [DOI](https://doi.org/10.1016/0304-405X(85)90044-3).
- Guéant, Olivier (2017), “Optimal Market Making,” *Applied Mathematical Finance* 24(2), 112–154. [DOI](https://doi.org/10.1080/1350486X.2017.1342552).
- Guéant, Olivier, Charles-Albert Lehalle, and Joaquin Fernandez-Tapia (2013), “Dealing with the Inventory Risk: A Solution to the Market Making Problem,” *Mathematics and Financial Economics* 7(4), 477–507. [DOI](https://doi.org/10.1007/s11579-012-0087-0).
- Ho, Thomas, and Hans R. Stoll (1981), “Optimal Dealer Pricing under Transactions and Return Uncertainty,” *Journal of Financial Economics* 9(1), 47–73. [DOI](https://doi.org/10.1016/0304-405X(81)90020-9).
- Huang, Roger D., and Hans R. Stoll (1997), “The Components of the Bid-Ask Spread: A General Approach,” *Review of Financial Studies* 10(4), 995–1034. [DOI](https://doi.org/10.1093/rfs/10.4.995).
- Huang, Weibing, Charles-Albert Lehalle, and Mathieu Rosenbaum (2015), “Simulating and Analyzing Order Book Data: The Queue-Reactive Model,” *Journal of the American Statistical Association* 110(509), 107–122. [DOI](https://doi.org/10.1080/01621459.2014.982278).
- Menkveld, Albert J., and Marius A. Zoican (2017), “Need for Speed? Exchange Latency and Liquidity,” *Review of Financial Studies* 30(4), 1188–1228. [DOI](https://doi.org/10.1093/rfs/hhx006).
- Stoikov, Sasha, and Mehmet Sağlam (2009), “Option Market Making under Inventory Risk,” *Review of Derivatives Research* 12(1), 55–79. [DOI](https://doi.org/10.1007/s11147-009-9036-3).

### Working papers and preprints

- Moallemi, Ciamac C., and Kai Yuan (2017), “A Model for Queue Position Valuation in a Limit Order Book,” Columbia Business School working paper / SSRN 2996221. **Working paper, not peer reviewed.** [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2996221).
- Wu, Shanshan, Marcello Rambaldi, Jean-François Muzy, and Emmanuel Bacry (2019), “Queue-Reactive Hawkes Models for the Order Flow,” arXiv:1901.08938. **Preprint.** [arXiv](https://arxiv.org/abs/1901.08938).

### Primary NSE and SEBI sources

- NSE (2023), “Mode of Trading — Equity Derivatives, April 2023.” [PDF](https://archives.nseindia.com/content/fo/fo_mode_of_trading_Apr2023.pdf).
- NSE (2024), “Discontinuation of Weekly Index Derivatives Contracts,” circular NSE/FAOP/64506. [PDF](https://nsearchives.nseindia.com/content/circulars/FAOP64506.pdf).
- NSE Clearing (2024), expiry-day additional ELM, circular NSE/CMPT/64639. [PDF](https://nsearchives.nseindia.com/content/circulars/CMPT64639.pdf).
- NSE (2025), “Change in Expiry Day of Index and Stock Derivatives Contracts,” circular NSE/FAOP/68685. [PDF](https://nsearchives.nseindia.com/content/circulars/FAOP68685.pdf).
- NSE (2025), “Revision in Market Lot of Derivative Contracts on Indices,” circular NSE/FAOP/70616. [PDF](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf).
- NSE (2026), transaction charges, circular NSE/FA/73061. [PDF](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf).
- NSE, “Equity Derivatives — Securities Transaction Tax.” [Current schedule](https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax).
- NSE, “Equity Derivatives — Contract Specifications.” [Current page](https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications).
- NSE, “Equity Derivatives — Margins.” [Current page](https://www.nseindia.com/static/products-services/equity-derivatives-margins).
- NSE, “Stamp Duty.” [Current page](https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes).
- NSE, “Liquidity Enhancement Scheme.” [Current page](https://www.nseindia.com/static/market-data/liquidity-enhancement-scheme).
- NSE, “Trading System,” documenting best-price then time-priority order storage and matching. [Current page](https://www.nseindia.com/static/products-services/equity-market-trading-system).
- SEBI (2024), “Master Circular for Stock Exchanges and Clearing Corporations,” Chapter 5: Exchange Traded Derivatives. [PDF](https://www.sebi.gov.in/sebi_data/commondocs/dec-2024/RE_Chapter%205%20-%20Exchange%20Traded%20Derivatives%20FINAL_1_p.pdf).
- SEBI (2023), regulatory fee circular specifying ₹10 per crore turnover. [PDF](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2023/1690447715047.pdf).

### Broker/feed documentation

- DhanHQ, “Live Market Feed v2.” [Documentation](https://dhanhq.co/docs/v2/live-market-feed/).
- DhanHQ, “Full Market Depth.” [Documentation](https://dhanhq.co/docs/v2/full-market-depth/).
- Kotak Neo, “Trade API.” [Pricing/product page](https://www.kotakneo.com/platform/kotak-neo-trade-api/).

### Reference verification note

Every bibliographic item above was checked against a publisher, journal index, SSRN/arXiv record, or primary NSE/SEBI page for author/title/year/venue. The queue-position and Hawkes items are explicitly labelled non-peer-reviewed. No India-specific maker-profitability paper is cited because none found met the feed, market and identification standard required here.
