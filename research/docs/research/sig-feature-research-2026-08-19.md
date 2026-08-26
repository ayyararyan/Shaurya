# What Actually Moves NSE Index Futures and Options?

> ## Corrections and status — added 2026-08-19 by Zen Mario, after review
>
> **This report is retained as written.** Nothing below is edited away; corrections are recorded
> here and inline as marked, so the original reasoning and its defects both stay visible.
>
> **Correction 1 — the feed sees more than §2.2 assumes.** §2.2 treats trades as a proxy
> "unless Dhan packets contain an exchange aggressor flag", and treats displayed-size removal as
> possibly-trade-possibly-cancellation. Checked against our own parser: Dhan response code 4
> carries last traded price, last traded quantity and cumulative volume, and code 5 carries open
> interest. **Trades are therefore observable.** A depth decrease coinciding with a
> cumulative-volume increment is a trade; one without is a cancellation. Only the *aggressor
> side* is unobserved and still needs a tick or Lee-Ready rule. This upgrades story A4
> ("cancellation toxicity is observable only as removal pressure") from unidentified toward
> identified-with-a-caveat. The caveat is real and new: trade fields and 20/200-level depth arrive
> on **different channels with independent packet clocks**, so trade/cancel separation requires
> cross-channel alignment that must itself be measured from tape before it is relied on.
>
> **Correction 2 — the report is written for a taker; Shaurya is a maker (D21).** Almost every
> confirming test below is a directional forecast evaluated against an executable taker markout.
> Aryan decided 2026-08-19 that Shaurya quotes and never crosses the spread. The features largely
> survive; **the targets invert.** The governing question is not "will price move" but
> "conditional on a resting quote being filled, what is the markout, and what was the probability
> of that fill". Order-flow imbalance as a taker signal says lean long; the same imbalance as a
> maker signal says widen or withdraw the bid. §6's economic gate is restated accordingly:
> expected spread capture must exceed adverse selection plus side-specific taxes, fees and hedging
> cost, rather than clearing a half-spread hurdle that is never paid. A dedicated maker-side
> research report was commissioned the same night to address what this report does not.
>
> **Correction 4 — §2.3's queue-position claim over-reaches (D23).** §2.3 item 1 asserts that
> without order IDs there is "no fill probability conditional on rank" and that "'my queue
> position' does not" remain feasible. That conflates two objects. NSE index F&O matches on
> price-time priority, so a maker's **own queue-ahead is bounded, not unidentified**: it equals the
> displayed quantity at placement, is decremented exactly from the front by observed trades, and is
> reduced by cancellations whose aggregate size is observable even though their queue position is
> not — giving hard upper and lower bounds plus a point estimate under a cancellation-position
> model. Queue-conditional arrival, cancellation and trade intensities are likewise estimable from
> level deltas; the queue-reactive fill literature was built for aggregated Level-2 data and never
> required order IDs. What genuinely remains unidentified is narrower than §2.3 states: cancellation
> position within the queue, individual order identity and lifetime, and hidden/iceberg quantity.
> The binding limit is packet coalescing at roughly eight packets per second, which makes the
> add/cancel/trade decomposition under-determined within an interval — so **bound width is an
> empirical quantity to be measured from tape**, not a reason to abandon the object.
>
> **Correction 3 — the bibliography is not yet trustworthy.** A sampled check found roughly one
> entry in seven wrong. Reference 35 has the right journal, year, volume and page range but the
> wrong author and title; the paper actually at that location is Vipul (2005), "Futures and
> options expiration-day effects: The Indian evidence." **No claim may be written into the SIG
> ledger leaning on a citation from this bibliography until that citation has been resolved
> individually.** The arguments stand on their own reasoning; the references do not yet stand on
> theirs.


## A horizon-specific, falsifiable feature-research agenda for Shaurya SIG

**Scope.** NIFTY, BANKNIFTY, FINNIFTY and MIDCPNIFTY futures and options; evidence reviewed through 19 August 2026. “Predicts” below means out-of-sample predictive association unless an identification design warrants a causal claim. The relevant target is an **executable** future price or markout after all costs, not a midquote return.

---

## 1. Executive summary: stories worth testing first

| Rank | Story and supported horizon | Why it is high expected value |
|---:|---|---|
| **1** | **Depth-normalised, multi-level order-flow imbalance (OFI) and queue depletion — 250 ms to 10 s** | Strongest cross-market microstructure prior, exact fit to event/depth data, cheap to construct, and sharply falsifiable. Test whether innovations—not static levels—predict the next executable move beyond spread, volatility and L1 imbalance. |
| **2** | **Cross-contract price discovery: futures versus option-implied forward, then NIFTY/BANKNIFTY/FINNIFTY links — 1 s to 5 min** | Same economic state is quoted in several venues/contracts. Relative staleness and liquidity create testable lead–lag without needing investor labels. Synthetic-forward parity is a better comparator than a stale cash index. |
| **3** | **Joint underlying/vol-surface innovations: level, skew and curvature conditional on signed option flow — 3 s to 15 min** | eSSVI supplies economically meaningful coordinates; Indian evidence links vega-weighted option imbalance to variance-risk-premium changes. The 3 s surface-refresh clock imposes a clean lower horizon. |
| **4** | **Liquidity resilience after depletion/cancellation shocks — 1 s to 2 min** | The tape observes additions, removals, spread/depth recovery and deep-book shape. The economically useful question is not “was depth removed?” but whether replenishment is fast enough for impact to reverse. |
| **5** | **State-dependent impact and Kyle-lambda proxies — 1 s to 30 min** | Impact should rise when depth is thin and volatility/high information risk is high. Separating short-lived from persistent markouts determines whether SIG should mean-revert or follow flow. |
| **6** | **Expiry × time-of-day × moneyness interactions — 1 min to intraday** | NSE’s weekly-expiry architecture, regulatory changes, theta/gamma concentration and pronounced intraday seasonality make unconditional models structurally misspecified. Treat these first as state variables, then ask if residual effects remain. |
| **7** | **Implied–realised variance spread, decomposed into continuous and jump variation — intraday to weeks** | Strong asset-pricing prior and India-specific evidence, but it is a slower risk-premium story, not a seconds-level directional signal. Test forecasts of future variance and variance-carry returns separately. |
| **8** | **Surface statistical reversion versus quote/fitter dislocation — 10 s to 1 day** | Trade only deviations that persist beyond asynchronous quotes, bid–ask bounds, parity and eSSVI smoothing. Most apparent “arbitrage” is likely latency or marking error; the falsification gate is therefore valuable. |
| **9** | **Intraday seasonality and auction/open information assimilation — 1 min to hours** | Robustly documented internationally and partly in India. Its main value is normalization and regime control; any standalone alpha must survive a rolling, post-cost, post-regulation test. |
| **10** | **Futures basis, calendar spread and roll pressure — 5 min to days** | Observable in futures chains and tied to carry, margin and expiry. Predictability is credible only after funding, dividends, spread execution and contract-roll mechanics. |
| **11** | **Global overnight information and opening-gap absorption — open to first 30 min** | Economically compelling, but the specified tape cannot identify the source without GIFT Nifty/global futures and constituent data. Add external data before testing. |
| **12** | **Dealer gamma/charm/vanna, pinning — minutes to expiry day** | Popular practitioner narrative but weakly identified here. Open interest times Greeks does not reveal dealer sign. At most run a low-priority reduced-form strike/OI fingerprint; do not call it dealer positioning. |

**Bottom line.** Start with ranks 1–6. They match the tape, have clear negative controls, and operate at feasible horizons. Treat ranks 7–10 as slower state/carry modules. Defer 11 until external data exist. Set 12 aside as a structural claim: this tape cannot identify it.

---

## 2. What our data can and cannot identify

### 2.1 Directly observable or constructible

For each contract and packet the feed can support best quotes, spread, quoted size, 5/20/200-level shape, and changes in displayed depth. Define

\[
m_t=(a_t+b_t)/2,\qquad I_t^{(1)}={q^b_t-q^a_t\over q^b_t+q^a_t},\qquad
\mu_t={a_tq^b_t+b_tq^a_t\over q^b_t+q^a_t},
\]

where \(\mu\) is the L1 microprice. After re-indexing every update to a price grid, a multi-level OFI can be written

\[
OFI_t^{(L)}=\sum_{\ell=1}^{L}w_\ell
\{\Delta Q^b_{t,\ell}-\Delta Q^a_{t,\ell}\}.
\]

This permits event intensity, additions/removals at displayed price levels, depletion, replenishment, spread transitions, book slope/convexity, markouts and response functions. It also permits cross-contract common-clock panels; option-implied forwards; eSSVI total-variance level/skew/curvature; and realised variance/jump measures from sufficiently clean futures prices.

### 2.2 What is only a proxy

* **[CORRECTED — see Correction 1 above: trades are observable; only the aggressor side is inferred.]**
* **Trades and trade sign.** Unless Dhan packets contain an exchange aggressor flag, quote-based signing (Lee–Ready or tick rules) is an estimated label. Lee and Ready (1991) is foundational, but Ellis, Michaely and O’Hara (2000) find meaningful classification error, especially inside the spread. Features must be reported both with and without inferred trades. A signed removal is not necessarily a trade; it may be a cancellation.
* **Cancellation.** Displayed size disappearing without an identified print is “removal”, not a known cancellation. Additions/removals can measure book pressure and resilience, but not cancellation intent.
* **Kyle lambda.** Regressing price changes on inferred signed flow estimates a reduced-form impact coefficient,
  \(\Delta m_{t,t+h}=\alpha+\lambda_{t,h}\widehat q_t+\epsilon\), not Kyle’s (1985) structural informed-trading parameter. Hasbrouck-style impulse responses likewise measure persistent quote response, not private information itself.
* **“Permanent” impact.** With no fundamental-value observation, permanent means persistent over a declared finite markout (say 5 min or 30 min), not literally permanent.
* **Open interest.** Contract OI measures matched long–short positions. It does not say whether dealers are long or short, nor identify hedging demand.

### 2.3 Inaccessible with the present tape

1. **[CORRECTED — see Correction 4 above: own queue-ahead is bounded, and queue-conditional intensities are estimable.]** **Queue position and lifecycle.** No order IDs means no order-level arrival-to-cancel duration, FIFO rank, fill probability conditional on rank, modification chains, iceberg reconstruction, or rigorous spoofing/layering detection. Event-level queue depletion remains feasible; “my queue position” does not.
2. **Participant identity.** No broker/member/beneficial-owner IDs means no retail/institution/proprietary/dealer classification, inventory, broker herding, informed-versus-noise attribution, or participant-specific execution. The broker-ID literature and Pan–Poteshman buyer-to-open design are not transferable.
3. **Dealer positioning.** Dealer gamma, charm and vanna require signed dealer inventories or a defensible institutional assignment rule. OI×Greek charts are not identification.
4. **Cash-index price discovery.** The published index is a calculated, non-traded value and can be stale relative to futures. Clean futures-versus-cash inference needs constituent quotes/trades and index-weight reconstruction. Those are outside the specified F&O-only universe.
5. **Global information source.** GIFT Nifty, US futures/closes, FX and news are absent. The tape sees the opening response, not which overnight market caused it.
6. **Hidden liquidity and order type.** Displayed depth cannot reveal undisplayed orders, conditional orders, internalisation, broker routing or message-level exchange priority.

These are not inconveniences to be solved by clever features. They are identification failures. Corresponding stories should be set aside or explicitly labelled reduced-form fingerprints.

### 2.4 Measurement gates before any search

* Establish exchange timestamps, Dhan receipt timestamps, packet coalescing and sequence-loss rates. At roughly eight packets per second per instrument, “sub-second” means packet/event horizon, not full exchange message reconstruction.
* Audit whether “200-level” snapshots are atomic and whether unchanged levels are resent. Reconstructing events from asynchronous partial snapshots without this audit creates fictitious cancellations.
* Use bid/ask executable targets and freshness flags; do not forward-fill a stale option quote into parity or an eSSVI fit.
* Split regimes at least at **20 November 2024** (new-contract lot-size transition), **the November 2024 weekly-expiry rationalisation**, and **29 August 2025** (Thursday-to-Tuesday expiry transition). Tick-size bands and later tax changes require additional versioning.

---

## 3. Story-by-story analysis, grouped by horizon

### A. Sub-second/event horizon: one packet to about 1 second

#### A1. Queue imbalance and microprice encode the next depletion side

**Mechanism.** When the bid queue is large relative to the ask, an incoming unit of aggressive flow is more likely to exhaust the ask first; the microprice moves toward that side. This is a near-term state/hazard argument, not a claim about fundamental value. Queue imbalance predicts one-tick moves especially in large-tick assets (Gould and Bonart, 2016); Cartea, Donnelly and Jaimungal (2018) show how imbalance can improve execution strategies.

**Observable.** \(I^{(1)}\), microprice-minus-mid, spread state, recent event intensity, and the next best-price transition. Estimate separately by instrument, contract, tick/price regime, time-to-expiry and spread-in-ticks.

**Confirming test.** In purged walk-forward data, the probability of the next midquote uptick is monotone in imbalance; microprice improves log loss/Brier score over mid, spread and recent return; the effect is strongest for one-tick spreads and decays within a few seconds. An executable version must predict ask-to-future-bid or bid-to-future-ask markouts, not only midquote changes.

**Falsifying test.** The effect vanishes out of sample, reverses across adjacent months, is confined to locked/crossed/stale packets, adds nothing beyond the last price change, or cannot cover one spread plus charges. A long-lived effect over minutes would falsify the proposed *queue-hazard* mechanism even if some correlation remains.

#### A2. Multi-level OFI, rather than static depth, is the sufficient short-run pressure variable

**Mechanism.** Limit additions, cancellations and market orders all alter available liquidity. Cont, Kukanov and Stoikov (2014) find short-interval price changes approximately linear in OFI, with slope inversely related to depth; Eisler, Bouchaud and Kockelkoren (2012) stress that event types have distinct impacts. Deeper levels can contain incremental information (Cao, Hansch and Wang, 2009), but distant displayed size may also be cheap and fleeting.

**Observable.** Grid-aligned \(OFI^{(1)},OFI^{(5)},OFI^{(20)},OFI^{(200)}\), depth-normalised OFI, event-type approximations and markouts at 1, 2, 5 and 10 seconds. Use distance-in-ticks or basis points, not vendor level number, because levels shift when the best price moves.

**Confirming test.** OFI has a stable, monotone sign; \(|\lambda|\) is larger in thin books; multi-level OFI adds out-of-sample information over L1 OFI; and gains saturate at an empirically stable depth. Coefficients scale sensibly when lot/tick regimes change.

**Falsifying test.** Predictability is entirely contemporaneous (timestamp inversion), disappears after current microprice and spread, deep levels worsen every held-out regime, or the apparent effect is generated by snapshot reshuffling. If static imbalance works but innovations do not, the specific OFI mechanism fails.

#### A3. Deep-book slope and curvature reveal latent supply—but may be decorative liquidity

**Mechanism.** A steep/convex same-side book means marginal execution cost grows quickly; asymmetry in slopes may reveal supply/demand or disagreement. Næs and Skjeltorp (2006) and Cao et al. (2009) document information in book shape; Kavajecz and Odders-White (2004) connect depth concentrations to technical levels. Transfer to index derivatives is uncertain because deep orders can be cancelled cheaply.

**Observable.** Cumulative depth as a function of distance from mid; robust slope/convexity, 5-versus-20-versus-200-level concentration, holes, and shape asymmetry. Predict next price transition and future realised impact conditional on L1 state.

**Confirming test.** Shape features add stable incremental forecast value over L1 OFI, especially before large sweeps, and displayed deep liquidity actually survives long enough to affect subsequent execution.

**Falsifying test.** The signal disappears when conditioned on top-five depth, reverses when measured in rupees rather than contracts, or the relevant deep levels vanish before the market approaches them. Then 200-level data are monitoring/liquidity-state data, not directional alpha.

#### A4. “Cancellation toxicity” is observable only as removal pressure, not intent

**Mechanism.** Strategic liquidity suppliers withdraw when adverse selection rises, making same-side depletion self-reinforcing. Empirical cancellation work finds strong state dependence, but rigorous lifecycle/spoofing research uses order histories unavailable here.

**Observable.** Unexplained displayed-size removals, addition/removal ratios by side and distance, burst intensity, and time to replenishment—after excluding identifiable trades as well as possible.

**Confirming test.** Same-side removal bursts precede spread widening and adverse executable markouts beyond OFI; the effect is stronger in high-volatility/near-expiry states and is followed by slow replenishment.

**Falsifying test.** Results vanish when trade-linked removals are excluded, depend on snapshot batching, or removals replenish immediately with no price consequence. Claims about spoofing, trader intent or cancellation lifetime are **unfalsifiable with this feed** and must not be made.

### B. Seconds horizon: about 1–30 seconds

#### B1. Liquidity resilience distinguishes temporary pressure from information

**Mechanism.** A depletion shock may move price temporarily if suppliers refill the book, or persist if flow reveals information/adverse selection. Limit-order-book models (Cont, Stoikov and Talreja, 2010) generate state-dependent transition hazards; the empirical impact literature distinguishes mechanical impact from longer response.

**Observable.** For matched shocks, estimate spread, depth, microprice and price response paths at 1/3/5/10/30/60 seconds. Define recovery half-life and overshoot. Match on instrument, expiry, time of day, spread, volatility, and shock size relative to depth.

**Confirming test.** Fast refill predicts reversal while continued same-sign flow/slow refill predicts persistent markout; response curves are reproducible across days and adjacent contracts.

**Falsifying test.** Recovery measures add nothing beyond the initial price change/OFI, response signs are unstable, or all persistence disappears under non-overlapping event windows. Then “resilience” is description, not a signal.

#### B2. Impact is state-dependent and has temporary and persistent components

**Mechanism.** Kyle (1985) links price impact to information and liquidity; Hasbrouck (1991) estimates information content from dynamic quote/trade responses. In practice, signed-flow persistence and adaptive liquidity make a fixed lambda inadequate (Bouchaud, Farmer and Lillo, 2009).

**Observable.** Estimate local response \(R(h)=E[(m_{t+h}-m_{t-})s_t\mid X_t]\) and \(\lambda(h)\) using inferred sign or OFI, with states for depth, spread, volatility, expiry and time. Compare markouts from 1 second to 30 minutes.

**Confirming test.** Immediate impact increases with size/depth, thinness and volatility; some fraction decays as depth replenishes, while the persistent component is associated with continued flow and cross-contract price confirmation.

**Falsifying test.** Lambda does not scale inversely with depth, cannot forecast post-event markouts, or “permanence” changes arbitrarily with sampling. Never interpret lambda as informed-trader intensity without participant/order data.

#### B3. Futures and option-implied forwards compete to discover the same underlying price

**Mechanism.** Liquidity, leverage and informed trading can make futures or options update first. Option put–call parity yields an implied forward; discrepancies should close as stale quotes update or arbitrageurs trade. US evidence disagrees on how much price discovery occurs in options (Easley, O’Hara and Srinivas, 1998; Chakravarty, Gulen and Mayhew, 2004), partly because datasets and information measures differ.

**Observable.** From synchronized call/put pairs at the same strike and expiry, construct the parity-implied forward using executable bid/ask bounds and current rates/dividends. Compare innovations to the listed future with freshness and liquidity controls. Estimate lead–lag/Hasbrouck information shares cautiously under asynchronous sampling.

**Confirming test.** A deviation reliably closes through movement in the lagging contract, direction and leader are stable conditional on relative spread/depth, and a tradeable bound survives both legs’ bid–ask and charges. Option OFI should forecast the futures update when options lead, and vice versa.

**Falsifying test.** Deviations lie inside executable parity bands; results vanish after quote-age controls; the “leader” merely has more frequent packets; or closure cannot beat multi-leg costs. Comparing futures with the published cash index alone is not a clean test.

#### B4. Surface-factor innovations are driven jointly by underlying moves and option demand

**Mechanism.** No-arbitrage links option prices to the forward, but stochastic volatility, leverage and net buying pressure move implied-vol level, skew and curvature. Cont and da Fonseca (2002) find a low-dimensional surface; Bollen and Whaley (2004) show option demand affects shape. Indian evidence from Chakrabarti and Kotha (2017) links vega-weighted option imbalance to variance-risk-premium changes.

**Observable.** At each valid ~3 s eSSVI refresh, extract total-variance level, slope/skew and curvature innovations by tenor; align futures return/OFI and vega-weighted option OFI in forward-log-moneyness \(k=\log(K/F_T)\). Retain fit residuals and raw quote ages.

**Confirming test.** Surface changes have stable factor structure; negative underlying innovations steepen downside skew; signed, vega-scaled option flow predicts factor changes beyond contemporaneous underlying returns; effects are coherent across neighboring strikes/tenors and exceed eSSVI uncertainty.

**Falsifying test.** “Predictability” is confined to the 3 s refresh boundary, disappears with raw-quote freshness or vega scaling, violates neighboring-tenor coherence, or is only contemporaneous fitting. The fitted surface cannot support a sub-3-second surface claim.

### C. Minutes horizon: about 30 seconds–15 minutes

#### C1. Surface dislocations mean-revert statistically; true arbitrage is much rarer

**Mechanism.** Temporary inventory pressure and asynchronous updates can displace a strike/tenor from a smooth surface. Genuine static arbitrage requires violating executable monotonicity/convexity/calendar bounds, not merely a model residual. Gatheral and Jacquier (2014) show how SVI can be made arbitrage-free; Dumas, Fleming and Whaley (1998) show that flexible smiles need not forecast well out of sample.

**Observable.** Quote residual relative to eSSVI with bid–ask interval, vega, quote age, local liquidity and parity constraints; subsequent raw-quote and fitted-surface changes.

**Confirming test.** Large standardized residuals outside bid–ask/model uncertainty revert through the outlying option rather than a wholesale surface move, repeatedly out of sample, and executable multi-leg P&L is positive after charges.

**Falsifying test.** Residuals are inside spreads, caused by stale inputs, removed by leave-one-out fitting, or profits disappear with wide-leg execution. Gonçalves and Guidolin (2006) is a direct warning: apparent surface predictability need not survive trading costs.

#### C2. Cross-index lead–lag reflects differential information arrival, not just overlapping weights

**Mechanism.** BANKNIFTY can respond first to banking news; NIFTY may lead broad risk; FINNIFTY overlaps heavily with financial constituents. Liquidity differences also generate mechanical staleness.

**Observable.** Common-clock innovations and OFI across nearest futures and liquid parity-implied forwards; residualize each return against contemporaneous common factors and account for known index composition overlap. Test 1 s, 5 s, 30 s, 1 min and 5 min.

**Confirming test.** Lagged innovations in one index predict the *residual* executable move of another beyond its own OFI/microprice; leadership switches plausibly with sector news/liquidity and survives equalized sampling intensity.

**Falsifying test.** Lead–lag disappears under refresh-time synchronization, after common-factor/component exposure controls, or after bid–ask costs. A raw correlation is not a cross-index signal.

#### C3. Expiry proximity amplifies flow-to-price and surface sensitivity

**Mechanism.** Near expiry, option gamma and theta rise around the money, liquidity/moneyness migrate, and concentrated trading can amplify hedging and price pressure. Indian studies report expiry effects, but estimates vary by period and market design (Kumar, Sarin and Shastri, 2005; Narang and Vij, 2013). NSE’s later proliferation and subsequent rationalisation of weekly expiries changes the environment.

**Observable.** Interact OFI, depth, moneyness, total variance and time-of-day with continuous time-to-expiry and expiry type. Compare otherwise similar Tuesday/Thursday historical regimes, expiry versus non-expiry days, and weekly versus monthly contracts.

**Confirming test.** Near-ATM flow impact and surface responsiveness rise monotonically as clock time to expiry falls; the effect is localized in moneyness/tenor, persists after seasonality/liquidity controls, and changes coherently after regulatory regime shifts.

**Falsifying test.** “Expiry effect” is fully explained by volume, spread, intraday volatility or scheduled macro announcements; signs do not replicate after the weekly-expiry/weekday changes; or it appears equally in far-dated deep-OTM options. Expiry must initially be a conditioning state, not presumed alpha.

#### C4. Intraday time is a predictable liquidity/volatility state

**Mechanism.** Information accumulated overnight is incorporated near the open; midday activity is quieter; closing/expiry flows may increase activity later. U-shaped volume/volatility patterns are classic (Wood, McInish and Ord, 1985), but India’s pre-open design and derivatives schedule matter.

**Observable.** Minute-of-session profiles of event intensity, spread, depth, OFI variance, realised volatility and surface-fit quality, separately by expiry state and regulation regime.

**Confirming test.** Profiles repeat out of sample and normalize feature distributions/impact estimates; signals calibrated within minute-of-day bins transfer better than unconditional ones.

**Falsifying test.** Patterns are sample-specific, driven entirely by expiry-day composition, or disappear after activity-time transformation. Even a confirmed pattern is primarily a risk/execution control unless it yields net executable returns.

### D. Intraday horizon: roughly 15 minutes to the close

#### D1. The open is an information-assimilation regime, not simply another interval

**Mechanism.** Overnight information and accumulated orders meet discontinuously. NSE’s equity-derivatives pre-open call auction covers index futures, not index options. Indian evidence on the 2010 cash-market pre-open finds improved synchronicity but substantial price discovery continuing into the first 15 continuous minutes (Camilleri and Green, 2015).

**Observable.** Futures pre-open indicative/final prices if present, first continuous futures/options quotes, opening spreads/depth, parity gaps, and 1/5/15/30-minute markouts.

**Confirming test.** Large opening innovations predict elevated but decaying price discovery, wide option parity/surface dispersion that closes as options open, and a distinct impact/resilience function versus midday.

**Falsifying test.** After controlling for gap size and liquidity, opening coefficients equal midday coefficients; or apparent predictability comes from using unavailable/stale option marks. Causal attribution to GIFT/US news is impossible without those data.

#### D2. Implied versus realised variance is a carry/risk-premium state

**Mechanism.** Implied variance is approximately a risk-neutral expectation; expected realised variance is physical. Their difference contains compensation for variance/tail risk plus measurement/model components:
\[
VRP_t(T)=IV_t^{Q}(T)-E_t^{P}[RV_{t,T}].
\]
The ex-post spread \(IV_t-RV_{t,T}\) is not itself the ex-ante premium. Carr and Wu (2009) and Bollerslev, Tauchen and Zhou (2009) establish broad VRP evidence; Sankar, Ramachandran and Lukose (2020) find priced NIFTY variance risk.

**Observable.** Model-free or surface-integrated implied variance where strike coverage permits, eSSVI-based approximation otherwise; futures realised variance forecasts; subsequent delta-hedged option/variance-carry P&L. Measure horizon consistently.

**Confirming test.** A high spread predicts higher variance-selling returns or future variance in the theoretically expected direction out of sample, survives volatility-state and jump controls, and remains after executable hedging/costs.

**Falsifying test.** It only predicts contemporaneous volatility, depends on impossible tail extrapolation, or disappears after crisis/expiry/regime controls and costs. VRP evidence at weekly/quarterly horizons does not license a one-minute return feature.

#### D3. Continuous variance and jumps have different implications

**Mechanism.** Diffusive volatility is persistent; jumps reflect discontinuous news and tail risk. Bipower variation separates continuous and jump components under assumptions (Barndorff-Nielsen and Shephard, 2004); Andersen, Bollerslev and Diebold (2007) show their forecasting roles differ. Indian evidence in Sankar et al. (2020) finds past continuous variance, not jumps, predicts short-term synthetic variance-swap returns.

**Observable.** Noise-robust futures returns, realised variance and bipower/jump estimates at intraday/daily sampling; contemporaneous surface level/skew changes and future variance.

**Confirming test.** Continuous variation shows persistent variance forecasting while detected jumps produce immediate skew/tail repricing but weaker carry prediction; results survive multiple sampling grids and truncation thresholds.

**Falsifying test.** Jumps are merely bid–ask bounce/data gaps, decomposition is unstable across grids, or neither component improves a simple realised-volatility model. Tick data volume does not eliminate microstructure-noise bias.

#### D4. Futures basis and roll deviations reflect carry, pressure and constraints

**Mechanism.** Futures equal spot carry in frictionless markets; funding, dividends, margin demand and roll pressure produce deviations. Near expiry, calendar-spread liquidity and margin treatment change; SEBI’s 2024 framework removed calendar-spread treatment on expiry day because the expiring leg disappears.

**Observable.** Same-underlying futures curve, calendar spreads, implied carry, depth/OFI by expiry, roll volume and convergence. A clean cash basis additionally needs a constituent-reconstructed spot.

**Confirming test.** Abnormal calendar spreads mean-revert or forecast roll flows after explicit funding/dividend/margin bounds; convergence occurs through the predicted leg and survives two-leg costs.

**Falsifying test.** Deviations sit within carry/transaction bounds, are driven by stale far-contract quotes, or profits vanish under SPAN/additional margin and roll execution. With no constituent spot, avoid strong cash-basis claims.

#### D5. Pinning and dealer hedging are weak reduced-form hypotheses here

**Mechanism.** A short-gamma dealer may buy rises/sell falls and amplify volatility; a long-gamma dealer does the opposite. Delta changes with time (“charm”) and volatility (“vanna”) can induce hedge flows. Near a large strike, hedging may contribute to price clustering. Ni, Pearson and Poteshman (2005) document US single-stock expiration clustering. Anderegg, Ulmann and Sornette (2022), unusually, reconstruct FX option-market-maker gamma from trade-repository data and find volatility higher under negative gamma. By contrast, Barbon and Buraschi (2021) use an equity-options gamma proxy, while Dim, Eraker and Vilkov (2025) report that US SPX 0DTE market-maker gamma is on average positive; both remain working-paper evidence.

**Observable.** Only a weak fingerprint: distance to strike × public OI × time-to-expiry, local underlying mean reversion/trending, and option/futures OFI. Dealer sign is not observed.

**Confirming test.** Pre-specified high-OI strikes show excess terminal clustering relative to matched placebo strikes, increasing into expiry and robust to tick rounding, strike listing, past price anchoring and endogenous OI; hedge-like futures flow co-moves in the sign predicted by an independently justified position-sign proxy.

**Falsifying test.** Clustering is explained by strike selection/round numbers, appears before OI builds, fails across expiries, or either assumed dealer sign fits ex post. Even a positive result confirms clustering, **not dealer gamma**. Charm/vanna are not separately identifiable. Priority: low.

### E. Daily and above: close-to-close, expiry cycles and weeks

#### E1. Variance risk premium and skew are slow state variables

**Mechanism.** Investors pay to transfer volatility/crash risk, making implied variance and downside skew exceed subsequent physical outcomes on average. Tail-risk compensation can vary with market stress. Jain (2019) finds NIFTY implied volatility contains incremental future-volatility information; Fleming (1998) provides classic international forecast evidence.

**Observable.** Daily surface factors at fixed forward moneyness and tenor; subsequent realised variance, downside semivariance, jumps and delta-hedged option P&L. Roll a constant-maturity surface rather than splice raw expiries.

**Confirming test.** Fixed-tenor level/skew forecast future realised distribution or carry returns beyond HAR-style realised-volatility baselines, with stable direction across regimes and net costs.

**Falsifying test.** Results rely on overlapping returns without corrected inference, raw strike/DTE composition, a single crisis, or disappear after implied-vol level and realised-vol controls. “Skew predicts returns” and “skew prices insurance” are different hypotheses and targets.

#### E2. Weekly expiry architecture creates calendar effects, but regulation changes the treatment

**Mechanism.** Repeated short-dated expiries concentrate trading and risk transfer. Indian research reports expiry-day effects and some improvement in information absorption after weekly options, while newer work argues multiple expiries transmit volatility across indices. The literature spans different rules, so a pooled coefficient is economically uninterpretable.

**Observable.** Day-of-week, time-to-expiry, expiry/not-expiry, weekly/monthly status, and policy regime; outcomes include volume, spread, depth, realised volatility, surface factors and next-day returns.

**Confirming test.** Effects align with economic time-to-expiry rather than weekday labels; when NSE moved expiry from Thursday to Tuesday, the pattern moves with expiry. Discontinuities around November 2024 rationalisation help distinguish expiry concentration from generic weekday seasonality (descriptively, not automatically causally).

**Falsifying test.** A “Thursday effect” remains Thursday after expiry moves Tuesday, or a claimed expiry effect is unchanged for indices whose weekly contracts were discontinued. Such patterns would point to macro-calendar or data-composition stories instead.

#### E3. Global overnight markets explain opening gaps, but current data cannot identify them

**Mechanism.** GIFT Nifty, US equity futures/close, Asian markets, FX and commodities incorporate information while NSE is shut. At the open, domestic futures should jump toward the global information set.

**Observable.** Current tape: opening gap and absorption only. Needed additions: timestamped GIFT Nifty, S&P/Nasdaq futures, USDINR and perhaps sector-relevant global returns.

**Confirming test.** With added data, global innovations forecast signed NSE gap and reduce the residual uncertainty of first-30-minute price discovery; coefficients are stable across daylight-saving and holiday-overlap cases.

**Falsifying test.** Global variables add nothing beyond prior NSE close and domestic open, or apparent lead is calendar/time-zone misalignment. **Set aside until external data are added.**

---

## 4. Where the literature disagrees

1. **Does imbalance reveal information or merely the next mechanical queue event?** Queue models and large-tick evidence support one-tick prediction; impact researchers emphasize persistent correlated flow and adaptive liquidity. The disagreement is mainly about **horizon and estimand**. A 500 ms uptick forecast can be true while offering no 30 s executable return. Resolve with response curves and executable targets, not one coefficient.

2. **How deep is informative?** Cao et al. find incremental deep-book information; other evidence and market practice warn that distant orders are cancellable and strategic. The relevant dispute is not “L1 versus L200” abstractly, but the marginal out-of-sample value after L1–L5, expressed in economic distance and conditioned on survival/replenishment.

3. **Temporary versus permanent impact.** Kyle/Hasbrouck interpretations emphasize information; propagator/liquidity approaches show that persistent order signs can coexist with decaying individual-event impact. With no fundamental value or participant IDs, this dataset can estimate only finite-horizon response. Label the estimand accordingly.

4. **Do options or futures lead?** Easley et al. posit informed options trading; Chakravarty et al. estimate meaningful option price discovery; Pan and Poteshman obtain predictability using proprietary opening-buyer categories. Indian spot–futures studies themselves disagree: some find futures lead, others spot leads. Sampling, stale cash indices, liquidity, crisis period and information-share methodology explain much of the conflict. Our decisive comparison is futures versus fresh executable parity-implied forwards, state-conditioned on relative liquidity.

5. **Is surface motion risk dynamics or net demand?** Stochastic-volatility/leverage models explain co-movement with the underlying; demand-based work finds option imbalance shifts IV. Both may hold. Orthogonalize signed vega flow from underlying return and test whether it forecasts coherent subsequent factor changes rather than contemporaneous quote pressure.

6. **Is surface predictability tradeable?** Surface-factor persistence is widely observed, but Dumas et al. and Gonçalves–Guidolin show flexible fits/predictability can fail out of sample or after wide option costs. Forecast accuracy and strategy profitability must be reported separately.

7. **Are expiry effects structural?** Older Indian studies found price/volume/volatility effects under older settlement and contract designs; later weekly-expiry work studies a radically different market. SEBI’s 2024–25 changes are not nuisance breaks: they alter contract supply, lot size, margins and expiry weekday. Evidence cannot be pooled without regime interactions.

8. **Dealer gamma: stabilizer or destabilizer?** The sign is conditional on dealer inventory. Direct-data FX evidence (Anderegg et al., 2022) supports the mechanism; pinning evidence is primarily US and often single-stock; recent 0DTE work (Dim et al., 2025) disagrees with the common assumption that dealers are always short gamma. Practitioner “GEX” maps and even some academic work (e.g., Barbon and Buraschi, 2021) must assign or proxy position signs. Without signed dealer books, the theory yields opposite predictions and is not identified.

9. **Is India “retail dominated” or HFT/proprietary dominated?** Both statements refer to different denominators. SEBI documents millions of individual traders and 93% losing money in FY22–FY24. Yet NSE’s April 2023 mode data attribute 50.22% of turnover to co-location and another 15.57% to algo/DMA, while SEBI’s 2023–24 table attributes 59.7% of derivatives turnover to “Pro.” Headcount, open interest, premium paid and gross turnover are not interchangeable.

---

## 5. India/NSE-specific findings that differ from US-centric priors

### Contract architecture and regulatory breaks

* In late 2024 SEBI limited an exchange to **one weekly index-derivative benchmark**. NSE discontinued weekly BANKNIFTY, MIDCPNIFTY and FINNIFTY contracts and retained NIFTY weekly contracts. Treat pre/post samples as different markets, not merely different dates.
* NSE’s October 2024 circular increased new-contract market lot sizes: NIFTY 25→75, BANKNIFTY 15→30, FINNIFTY 25→65 and MIDCPNIFTY 50→120, phased through expiries. This changes rupee queue depth, retail accessibility and minimum risk per trade. Normalize quantity to notional/vega and include transition flags.
* NSE moved index-derivative expiries from Thursday to **Tuesday**, effective after 28 August 2025. This provides an unusually sharp falsification: genuine expiry effects should move to Tuesday; generic Thursday patterns should not.
* Index futures now have a pre-open call auction, while options do not. Opening futures–options lead–lag therefore partly reflects market design.
* Tick size is contract- and price-regime specific on current NSE specifications. Large-tick queue results from US equities cannot be transferred without stratifying spread/tick state.

### Participation and volume

SEBI’s FY22–FY24 study reports that 93% of individual equity-F&O traders lost money and aggregate individual losses exceeded ₹1.8 lakh crore. This establishes economically important retail participation, not that retail causes every price move. Contract counts also exaggerate India’s global economic share because contracts are small; FIA explicitly recommends premium turnover/value measures for comparison. Feature pooling should therefore use rupee notional, premium and Greeks, not contract counts alone.

NSE mode-of-trading data show a highly electronic market: in April 2023, co-location represented 50.22% of equity-derivatives turnover, DMA 10.43% and “algo” 5.14%. These labels do not map one-for-one into HFT, but they make a key point: the marginal short-horizon counterparty is often fast. A public-feed signal that is real at the exchange may already be competed away before Dhan delivery. Hence latency-aware executable markouts are the primary gate.

### Taxes and charges are part of the return-generating process

For research dated August 2026, current NSE schedules state:

* **STT:** futures sale 0.05% of sale notional; option sale 0.15% of premium; exercised option 0.15% of intrinsic value borne by purchaser. Up to 31 March 2026 the corresponding rates were 0.02%, 0.10% and 0.125%, so historical simulation must version tax rules.
* **Stamp duty:** futures purchase 0.002% of notional; option purchase 0.003% of premium.
* **NSE transaction charge from March 2026:** approximately ₹183/crore on each futures side and ₹3,553/crore of premium on each options side (including the stated IPFT component), plus brokerage, SEBI charge and GST where applicable.

Thus a futures round trip is not symmetric: purchase incurs stamp duty; sale incurs STT; both sides incur spread/slippage and exchange/broker charges. Option exercise is especially asymmetric. Every label should be

\[
\text{net markout}=\text{executable exit}-\text{executable entry}
-\text{side-specific taxes}-\text{fees}-\text{hedging costs}.
\]

A one-tick midquote forecast can be statistically excellent and economically negative. Because tax regimes changed, post-cost performance must be computed under contemporaneous schedules, not today’s fee table retroactively.

### Margins, funding and limits

NSE Clearing uses portfolio/SPAN-style initial margin plus exposure/extreme-loss and other add-ons; option buyers post premium while short options/futures consume risk margin. SEBI’s 2024 measures required upfront collection of option premium, removed calendar-spread benefit on expiry day, increased tail-risk coverage on expiry and strengthened intraday position monitoring. Margin is therefore state-dependent and can force closing/hedging exactly when a paper signal looks strongest. Report return on peak margin, stress-margin consumption and feasible lots, not just return on premium. Position limits and member-level monitoring constrain capacity, but the tick tape cannot show how close a participant is to its constraint.

---

## 6. Recommended narrowing

### 6.1 Clocks

1. **Event time is primary for 250 ms–10 s book stories.** Define targets by next \(N\) packets and by elapsed time; packet rate itself is a state. Event time avoids treating inactive and frantic seconds as equivalent.
2. **Calendar time is primary for execution, parity and the 3 s surface.** Maintain causal snapshots at 250 ms, 1 s, 3 s, 10 s, 30 s, 1 min, 5 min, 15 min and 30 min with explicit quote-age limits. Do not evaluate eSSVI factors below their ~3 s refresh interval.
3. **Volume/notional time is a robustness clock, not the sole clock.** Use rupee-notional or vega turnover rather than contracts, especially across lot-size regimes. If OFI only works in calendar time because high activity mechanically means more events, its mechanism is suspect.
4. **Expiry time is its own clock.** Use seconds/minutes to settlement and fixed maturity buckets, not just integer DTE. Compare clock-time and business-time-to-expiry.

For every signal compare the same target across event, calendar and activity time. A mechanism should say which invariance is expected.

### 6.2 Pooling coordinates

* **Futures:** underlying × expiry rank × time-to-expiry × spread/tick regime. Express depth and flow in notional and relative-to-local-depth units.
* **Options:** pool in forward log-moneyness \(k=\log(K/F_T)\), tenor/clock-to-expiry and option liquidity, using total variance and vega-scaled flow. Pair calls and puts through parity; do not treat raw strikes or call/put labels as stable economic coordinates.
* **Surface:** fixed-tenor level/skew/curvature plus fit uncertainty and quote freshness. Preserve underlying-specific random slopes; do not force BANKNIFTY and MIDCPNIFTY to share coefficients.
* **Hierarchy:** partial pooling over underlying × horizon × expiry regime × time of day × moneyness-tenor bucket. Full pooling hides microstructure differences; no pooling destroys power.
* **Regimes:** at minimum pre/post weekly-expiry rationalisation, lot-size transition, Tuesday-expiry transition, tick bands and tax schedules. Estimate stability, not merely dummies.

### 6.3 Test sequence and minimum falsification protocol

**Stage 0 — measurement.** Timestamp audit, packet-loss/coalescing audit, atomic-snapshot check, crossed/stale quote rules, contract master/tick/lot/tax history, and executable target construction.

**Stage 1 — short-run benchmark.** L1 imbalance/microprice; L1 and multi-level OFI; depth-normalised response at 1/3/10/30 s. Baselines are last return, spread, depth, volatility, event intensity and minute-of-day.

**Stage 2 — mechanism extensions.** Replenishment half-life, shape, cross-contract parity lead–lag, then option-flow/surface factors. Each enters only if it adds held-out value to Stage 1.

**Stage 3 — slower states.** Expiry/intraday interactions, realised/implied variance, jump decomposition and roll/carry. These condition short-run signals before becoming standalone strategies.

For all stages use walk-forward splits by whole day/expiry cycle; purge overlapping labels; embargo adjacent intervals; cluster inference by day/expiry; freeze transformations inside training data; report calibration and economic loss as well as t-statistics; and run reverse-time, stale-quote, random-shift and inactive-contract placebos. Control the false-discovery rate across the feature family. Demand replication across at least two regulatory regimes or explicitly label regime-specific findings.

### 6.4 What can be dropped without material loss

* **Drop order-ID questions:** queue rank, order lifetime, modification chains, spoofing and participant-specific cancellation.
* **Drop participant/dealer attribution:** retail-versus-institution signals, broker herding, inventory and signed dealer gamma/charm/vanna.
* **Drop fitted-surface signals below 3 s.** Raw option quote/OFI work may remain at that horizon.
* **Drop deep-book direction beyond the depth at which incremental walk-forward value saturates.** Retain L200 for stress/liquidity monitoring if useful.
* **Drop daily directional use of instantaneous book state** unless aggregation supplies incremental evidence; microstructure state should decay.
* **Drop minute-horizon VRP claims.** VRP belongs at matched option horizons (days/weeks), while intraday implied-vol changes are surface/liquidity phenomena.
* **Drop “arbitrage” labels for model residuals inside executable bounds.** Call them relative-value residuals until a simultaneous executable portfolio is demonstrated.
* **Drop cash-index and global lead–lag until constituent/GIFT/global data are added.** Do not use a stale published index as proof that futures lead.

The recommended initial SIG search space is therefore compact: **OFI/depth/resilience at 0.25–30 s; parity and cross-index innovation at 1 s–5 min; surface factors and option vega-flow at 3 s–15 min; expiry/intraday states at 1 min–day; and VRP/jumps/carry at day–weeks.**

---

## 7. Full bibliography

### Market microstructure and order books

1. Andersen, T. G., Bollerslev, T. and Diebold, F. X. (2007), “Roughing It Up: Including Jump Components in the Measurement, Modeling, and Forecasting of Return Volatility,” *Review of Economics and Statistics* 89(4), 701–720. https://direct.mit.edu/rest/article/89/4/701/57715/
2. Barndorff-Nielsen, O. E. and Shephard, N. (2004), “Power and Bipower Variation with Stochastic Volatility and Jumps,” *Journal of Financial Econometrics* 2(1), 1–37. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=821712
3. Bouchaud, J.-P., Farmer, J. D. and Lillo, F. (2009), “How Markets Slowly Digest Changes in Supply and Demand,” in *Handbook of Financial Markets: Dynamics and Evolution*. https://arxiv.org/abs/0809.0822
4. Cao, C., Hansch, O. and Wang, X. (2009), “The Information Content of an Open Limit-Order Book,” *Journal of Futures Markets* 29(1), 16–41. https://doi.org/10.1002/fut.20334
5. Cartea, Á., Donnelly, R. and Jaimungal, S. (2018), “Enhancing Trading Strategies with Order Book Signals,” *Applied Mathematical Finance* 25(1), 1–35. https://doi.org/10.1080/1350486X.2018.1434009
6. Cont, R., Kukanov, A. and Stoikov, S. (2014), “The Price Impact of Order Book Events,” *Journal of Financial Econometrics* 12(1), 47–88. https://arxiv.org/abs/1011.6402
7. Cont, R., Stoikov, S. and Talreja, R. (2010), “A Stochastic Model for Order Book Dynamics,” *Operations Research* 58(3), 549–563. https://doi.org/10.1287/opre.1090.0780
8. Eisler, Z., Bouchaud, J.-P. and Kockelkoren, J. (2012), “The Price Impact of Order Book Events,” *Quantitative Finance* 12(9), 1395–1419. https://doi.org/10.1080/14697688.2010.528444
9. Ellis, K., Michaely, R. and O’Hara, M. (2000), “The Accuracy of Trade Classification Rules: Evidence from Nasdaq,” *Journal of Financial and Quantitative Analysis* 35(4), 529–551. https://ideas.repec.org/a/cup/jfinqa/v35y2000i04p529-551_00.html
10. Gould, M. D. and Bonart, J. (2016), “Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book,” working paper. https://arxiv.org/abs/1512.03492
11. Gould, M. D., Porter, M. A., Williams, S., McDonald, M., Fenn, D. J. and Howison, S. D. (2013), “Limit Order Books,” *Quantitative Finance* 13(11), 1709–1742. https://doi.org/10.1080/14697688.2013.803148
12. Hasbrouck, J. (1991), “Measuring the Information Content of Stock Trades,” *Journal of Finance* 46(1), 179–207. https://doi.org/10.1111/j.1540-6261.1991.tb03749.x
13. Kavajecz, K. A. and Odders-White, E. R. (2004), “Technical Analysis and Liquidity Provision,” *Review of Financial Studies* 17(4), 1043–1071. https://doi.org/10.1093/rfs/hhg057
14. Kyle, A. S. (1985), “Continuous Auctions and Insider Trading,” *Econometrica* 53(6), 1315–1335. https://people.stern.nyu.edu/lpederse/courses/LAP/papers/Information%2CFundamental/Kyle85.pdf
15. Lee, C. M. C. and Ready, M. J. (1991), “Inferring Trade Direction from Intraday Data,” *Journal of Finance* 46(2), 733–746. https://doi.org/10.1111/j.1540-6261.1991.tb02683.x
16. Næs, R. and Skjeltorp, J. A. (2006), “Order Book Characteristics and the Volume–Volatility Relation,” *Journal of Financial Markets* 9(4), 408–432. https://doi.org/10.1016/j.finmar.2006.04.001

### Options, volatility and price discovery

17. Bollen, N. P. B. and Whaley, R. E. (2004), “Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?” *Journal of Finance* 59(2), 711–753. https://doi.org/10.1111/j.1540-6261.2004.00647.x
18. Bollerslev, T., Tauchen, G. and Zhou, H. (2009), “Expected Stock Returns and Variance Risk Premia,” *Review of Financial Studies* 22(11), 4463–4492. https://doi.org/10.1093/rfs/hhp008
19. Carr, P. and Wu, L. (2009), “Variance Risk Premiums,” *Review of Financial Studies* 22(3), 1311–1341. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1359527
20. Chakrabarti, G. and Kotha, K. K. (2017), “The Impact of Option Trading on the Variance Risk Premium,” *Multinational Finance Journal* 21(2), 49–90. https://ideas.repec.org/a/mfj/journl/v21y2017i2p49-90.html
21. Chakravarty, S., Gulen, H. and Mayhew, S. (2004), “Informed Trading in Stock and Option Markets,” *Journal of Finance* 59(3), 1235–1257. https://doi.org/10.1111/j.1540-6261.2004.00661.x
22. Cont, R. and da Fonseca, J. (2002), “Dynamics of Implied Volatility Surfaces,” *Quantitative Finance* 2(1), 45–60. https://doi.org/10.1088/1469-7688/2/1/304
23. Dumas, B., Fleming, J. and Whaley, R. E. (1998), “Implied Volatility Functions: Empirical Tests,” *Journal of Finance* 53(6), 2059–2106. https://doi.org/10.1111/0022-1082.00083
24. Easley, D., O’Hara, M. and Srinivas, P. S. (1998), “Option Volume and Stock Prices: Evidence on Where Informed Traders Trade,” *Journal of Finance* 53(2), 431–465. https://doi.org/10.1111/0022-1082.194060
25. Fleming, J. (1998), “The Quality of Market Volatility Forecasts Implied by S&P 100 Index Option Prices,” *Journal of Empirical Finance* 5(4), 317–345. https://doi.org/10.1016/S0927-5398(98)00002-4
26. Gatheral, J. and Jacquier, A. (2014), “Arbitrage-Free SVI Volatility Surfaces,” *Quantitative Finance* 14(1), 59–71. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2033323
27. Gonçalves, S. and Guidolin, M. (2006), “Predictable Dynamics in the S&P 500 Index Options Implied Volatility Surface,” *Journal of Business* 79(3), 1591–1635. https://doi.org/10.1086/500686
28. Jain, S. (2019), “Indian Equity Options: Smile, Risk Premiums, and Efficiency,” *Journal of Futures Markets* 39(2), 150–172. https://doi.org/10.1002/fut.21971
29. Pan, J. and Poteshman, A. M. (2006), “The Information in Option Volume for Future Stock Prices,” *Review of Financial Studies* 19(3), 871–908. https://doi.org/10.1093/rfs/hhj024
30. Sankar, H., Ramachandran, A. and Lukose, P. J. J. (2020), “Dynamics of Variance Risk Premium: Evidence from India,” *International Review of Economics & Finance* 69, 822–836. https://doi.org/10.1016/j.iref.2020.06.010

### Expiry, dealer positioning, cross-market and funding constraints

31. Avellaneda, M. and Lipkin, M. D. (2003), “A Market-Induced Mechanism for Stock Pinning,” *Quantitative Finance* 3(6), 417–425. https://doi.org/10.1088/1469-7688/3/6/301
32. Brunnermeier, M. K. and Pedersen, L. H. (2009), “Market Liquidity and Funding Liquidity,” *Review of Financial Studies* 22(6), 2201–2238. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1408432
33. Camilleri, S. J. and Green, C. J. (2015), “The Impact of the Pre-Open Call Auction on the Price Discovery Process in India,” *Research in International Business and Finance* 35, 121–134. https://doi.org/10.1016/j.ribaf.2015.02.007
34. Kumar, R., Sarin, A. and Shastri, K. (2005), “The Impact of Futures and Options Expiration on the Underlying Stocks: Evidence from India,” *Journal of Futures Markets* 25(11), 1045–1065. https://doi.org/10.1002/fut.20188
35. Narang, S. and Vij, M. (2013), “Long-Term Effects of Expiration of Derivatives on Indian Spot Volatility,” *ISRN Economics* 2013, 718538. https://doi.org/10.1155/2013/718538
36. Ni, S. X., Pearson, N. D. and Poteshman, A. M. (2005), “Stock Price Clustering on Option Expiration Dates,” *Journal of Financial Economics* 78(1), 49–87. https://doi.org/10.1016/j.jfineco.2004.08.005
37. Wood, R. A., McInish, T. H. and Ord, J. K. (1985), “An Investigation of Transactions Data for NYSE Stocks,” *Journal of Finance* 40(3), 723–739. https://doi.org/10.1111/j.1540-6261.1985.tb04996.x

### Primary Indian regulatory and market-structure sources

38. Securities and Exchange Board of India (2024), “Study—Analysis of Profits & Losses in the Equity Derivatives Segment (FY22–FY24).” https://www.sebi.gov.in/reports-and-statistics/research/sep-2024/study-analysis-of-profits-and-losses-in-the-equity-derivatives-segment-fy22-fy24-_86905.html
39. SEBI (2024), “Measures to Strengthen Equity Index Derivatives Framework for Increased Investor Protection and Market Stability,” circular dated 1 October 2024. https://www.sebi.gov.in/legal/circulars/oct-2024/measures-to-strengthen-equity-index-derivatives-framework-for-increased-investor-protection-and-market-stability_87208.html
40. SEBI (2024), “Consultation Paper on Measures to Strengthen Index Derivatives Framework,” 30 July 2024. https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1722407296072.pdf
41. SEBI (2024), “Charges Levied by Market Infrastructure Institutions—True to Label,” circular dated 1 July 2024. https://www.sebi.gov.in/legal/circulars/jul-2024/charges-levied-by-market-infrastructure-institutions-true-to-label_84506.html
42. SEBI (2024), *SEBI Bulletin, May 2024*, annexure tables (investor-category turnover and open interest). https://www.sebi.gov.in/sebi_data/commondocs/jun-2024/Annexure%20tables-May2024_p.pdf
43. National Stock Exchange of India (2023), “Mode of Trading—Equity Derivatives, April 2023.” https://archives.nseindia.com/content/fo/fo_mode_of_trading_Apr2023.pdf
44. NSE (2024), “Discontinuation of Weekly Index Derivatives Contracts,” circular FAOP64506, 10 October 2024. https://nsearchives.nseindia.com/content/circulars/FAOP64506.pdf
45. NSE (2024), “Revision in Market Lot of Derivative Contracts on Indices,” circular FAOP64625, 18 October 2024. https://nsearchives.nseindia.com/content/circulars/FAOP64625.pdf
46. NSE (2025), “Revision in Expiry Day of Index and Stock Derivatives Contracts,” circular FAOP68685, 23 June 2025. https://nsearchives.nseindia.com/content/circulars/FAOP68685.pdf
47. NSE (2026), “Contract Specifications—Equity Derivatives.” https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications
48. NSE (2026), “Pre-Open Session—Equity Derivatives.” https://www.nseindia.com/static/products-services/equity-derivatives-pre-open-session
49. NSE (2026), “Securities Transaction Tax—Equity Derivatives.” https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax
50. NSE (2026), “Stamp Duty Rates.” https://www.nseindia.com/static/invest/first-time-investor-stamp-duty-charges-taxes
51. NSE (2026), “Transaction Charges in Equity Derivatives,” circular FA73061. https://nsearchives.nseindia.com/content/circulars/FA73061.pdf
52. NSE (2026), “Margins—Equity Derivatives.” https://www.nseindia.com/static/products-services/equity-derivatives-margins
53. NSE Clearing (2026), “Equity Derivatives—Margins.” https://www.nseclearing.in/risk-management/equity-derivatives/margins
54. Futures Industry Association (2025), “ETD Volume—December 2024.” https://www.fia.org/fia/articles/etd-volume-december-2024
55. Futures Industry Association (2024), “Premium Turnover in Indian Options Hits $150 Billion.” https://www.fia.org/marketvoice/articles/premium-turnover-indian-options-hits-150-billion
56. Anderegg, B., Ulmann, F. and Sornette, D. (2022), “The Impact of Option Hedging on the Spot Market Volatility,” *Journal of International Money and Finance* 124, 102627. https://doi.org/10.1016/j.jimonfin.2022.102627
57. Barbon, A. and Buraschi, A. (2021), “Gamma Fragility,” University of St. Gallen School of Finance Research Paper 2020/05. https://doi.org/10.2139/ssrn.3725454
58. Dim, C., Eraker, B. and Vilkov, G. (2025), “0DTEs: Trading, Gamma Risk and Volatility Propagation,” working paper, revised June 2025. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190

---

### Evidence-quality note

The bibliography deliberately privileges peer-reviewed work and primary SEBI/NSE documents. India-specific high-frequency causal evidence is thin. Several NSE expiry/price-discovery studies use daily or low-frequency samples under superseded rules; they motivate tests but do not establish present-day profitability. I found no credible NSE study with direct signed dealer inventories; no convincing Indian evidence separately identifying charm or vanna hedging; and no public NSE order-ID/broker-ID study transferable to the Dhan snapshot feed. Those absences drive the low ranking of dealer-position and participant-type stories.
