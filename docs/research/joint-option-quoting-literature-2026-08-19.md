# Joint option quoting and portfolio inventory — literature report

**Prepared:** 2026-08-19  
**Scope:** option market making when quotes across puts, calls and strikes are one portfolio
decision, with costly or infrequent futures hedging.  
**Status:** research synthesis. Literature constrains the objects and tests; it does **not**
select Shaurya's controller or establish NSE profitability.

## 1. Answer in one sentence

The best-supported decision object is the **joint quoting configuration**: the quote on contract
`i` should depend on the marginal spread capture and adverse selection of that quote **and** on
how its possible fill changes the risk, liquidity, capital use and future flattening capacity of
the whole option book. The empirical literature also supports Aryan's proposed hierarchy — use
passive option quotes to reverse inventory first and futures mainly for residual breaches — but
the theory warns that delta-only netting can leave material gamma and vega risk.

## 2. What the leading papers actually establish

| Paper | Design and finding | Direct use for Shaurya | Boundary / do not import |
|---|---|---|---|
| [Stoikov & Sağlam (2009), *Option market making under inventory risk*](https://doi.org/10.1007/s11147-009-9036-3) | Solves an option maker's quoting problem under complete and incomplete hedging. With continuous perfect delta hedging, option inventory drops out; with an illiquid underlying, stock and option quotes depend jointly on relative liquidity and net portfolio delta. In incomplete markets, optimal option quotes also depend on net gamma and vega; gamma matters most near expiry and vega at longer maturities. | The closest theoretical foundation for making the **portfolio**, not the contract, the state. It gives the risk-factor ordering: delta first, then maturity-sensitive gamma/vega. It also says the futures quote/hedge response should depend on its liquidity relative to the option book. | Its frictionless/continuous hedge corner is false for Shaurya. It is a structural map, not a calibrated NSE policy. |
| [Guéant (2017), *Optimal market making*](https://doi.org/10.1080/1350486X.2017.1342552) | In multi-asset market making, optimal quotes depend on the entire inventory vector and the assets' covariance. Opposing inventories in correlated assets can offset enough that the single-asset skew is wrong. Closed-form approximations make large books computationally feasible, although linear/affine approximations deteriorate at large inventory. | Replace independent contract penalties with **marginal portfolio risk**. Two positions with equal standalone delta need not have equal value if their covariance with the existing book differs. Use an approximation only inside a declared inventory region and measure its error near the boundary. | Generic multi-asset assets, not NSE options; covariance and fill processes must be estimated from our tape. |
| [Baldacci, Bergault & Guéant (2021), *Algorithmic market making for options*](https://doi.org/10.1080/14697688.2020.1766099) | Models simultaneous market making in many options on one underlying. Under continuous delta hedging and approximately constant vegas, the state collapses from all contract inventories to instantaneous variance plus **aggregate portfolio vega**; the method scales linearly in the number of options. A maker already long vega becomes less willing to buy any positive-vega option. | The important result is **state compression by risk factor**, not by contract identity. A practicable Shaurya controller can carry aggregate delta plus expiry-bucketed gamma/vega instead of a combinatorial inventory vector, then compare that compression with the full-vector yardstick. | It assumes the very thing Shaurya cannot afford: continuous, costless delta hedging. Its vega-only controller cannot be lifted unchanged. |
| [Bergault, Evangelista, Guéant & Vieira (2021), *Closed-form approximations in multi-asset market making*](https://doi.org/10.1080/1350486X.2021.1949359) | Develops closed-form proxy value functions and quotes for finite-horizon and ergodic multi-asset market-making models. The approximations can serve as a fast heuristic, a greedy policy or an initial policy for a richer optimiser. | A credible engineering scaffold if the exact joint action space is too large: use the approximation as a benchmark/controller initialisation, then test against the same replay and economic gate. | Computational tractability is not evidence of edge. Arrival laws, inventory domain and approximation error remain empirical objects. |
| [Giannetti, Zhong & Wu (2004), *Inventory hedging and option market making*](https://doi.org/10.1142/S0219024904002670) | Compares a single-option economy with a multiple-option economy. The usual inverse relation between one contract's inventory and its quote need not survive when several options can form hedge portfolios; the dealer trades combinations, not isolated securities. | Formal support for rejecting a contract-siloed rule such as “long this call, therefore lower only this call's bid.” The correct response may be in another strike, put, or side. | Theoretical conditions for complete hedges do not say those offsetting fills are available at useful queues or prices. `BK-01/H1` remains binding. |
| [Gârleanu, Pedersen & Poteshman (2009), *Demand-Based Option Pricing*](https://doi.org/10.1093/rfs/hhp005) | Demand pressure affects an option in proportion to the variance of its **unhedgeable** part and affects other options in proportion to covariance between their unhedgeable parts. The paper links demand to index-option levels and skew. | Equal delta is not equal hedge value. Cross-contract residual-risk covariance and the surface response to flow belong in the joint state and in the markout tests. | A demand-based equilibrium result, not a high-frequency fill controller. |
| [Muravyev (2016), *Order Flow and Expected Option Returns*](https://doi.org/10.1111/jofi.12380) | Finds that the inventory component of option trade impact is larger than the asymmetric-information component and that past option imbalances predict returns. | Inventory is a first-order explanatory state, not a bookkeeping afterthought; it should interact with EF flow features rather than enter only as a risk cap. | Daily U.S. equity options. It does not establish a 500 ms–minute NSE signal or a maker policy. |
| [Jameson & Wilhelm (1992), *Market Making in the Options Markets and the Costs of Discrete Hedge Rebalancing*](https://doi.org/10.1111/j.1540-6261.1992.tb04409.x) | Discrete rebalancing and volatility uncertainty explain economically significant parts of option spreads. | Confirms that hedge cadence and unhedged volatility risk are part of the spread budget, not a separate after-the-fact expense. | Old CBOE structure and no direct mapping to current NSE rates or latency. |
| [Fournier & Jacobs (2020), *A Tractable Framework for Option Pricing with Dynamic Market Maker Inventory and Wealth*](https://doi.org/10.1017/S0022109019000462) | Models an index-option intermediary with limited capital; inventory risk and dealer wealth alter option prices and the variance risk premium, especially in stressed states. | Evaluate a configuration per **peak margin/wealth consumed**, not raw rupees alone, and let risk tolerance tighten with account state. | An equilibrium pricing model, not an execution model. |

### Closest empirical analogue to Aryan's proposed mechanism

[Hu, Kirilova, Muravyev & Ryu, *Options Market Makers*](https://doi.org/10.2139/ssrn.4633451)
uses account-level KOSPI 200 option and futures data for 43 professional option market makers.
The current working-paper version reports:

- only **4 of 43** makers consistently delta hedge;
- **38%–48%** of an inventory shock reverses within five minutes;
- the reported inventory-reversal channels are principally **passive option orders (28%)**,
  then aggressive option trades (9.5%), with futures contributing only 0.5%; and
- even the delta hedgers mainly use rapid option-inventory rebalancing, adding futures hedges
  around the close and after volatility or inventory spikes.

That is unusually direct evidence for the hierarchy **passive option-book rebalancing first,
futures residual second**. It is not a numerical prior for Shaurya: KOSPI's 2010–2014
professional direct-exchange makers, fee schedule, latency and obligations differ materially
from a current retail-broker NSE path. The percentages are external benchmarks to reproduce or
reject, not thresholds that define success.

### Adversarial boundary

[Naik & Yadav (2003)](https://www.sciencedirect.com/science/article/pii/S0304405X03001156) find that, despite
portfolio-inventory theory, decentralised London dealer firms often placed quotes as if they
managed inventory stock by stock. This is an organisational warning, not a refutation of the
portfolio mathematics: a joint controller fails in practice if position state, limits or quote
ownership remain contract-siloed. Shaurya must therefore have one central portfolio state and one
configuration decision boundary; otherwise the architecture can recreate the inferior
single-contract behaviour even while the research model says “portfolio.”

## 3. Synthesis for Shaurya

### 3.1 The decision object

For a candidate configuration `a` of resting bid/ask quotes across contracts, a useful research
scaffold is

$$
J(a\mid x,q)=
\sum_{i,s}\lambda_{i,s}(a_{i,s}\mid x)
\left[\operatorname{capture}_{i,s}-\operatorname{markout}_{i,s}-\operatorname{cost}_{i,s}\right]
-\frac{\gamma}{2}g(q,a)'\Omega g(q,a)
-C_{\mathrm{breach}}(\Delta)-\kappa M_{\mathrm{peak}}(q,a).
$$

Here `λ` is the bounded fill intensity, `g` is a portfolio-risk representation, `Ω` its
conditional covariance, `C_breach` the futures breach-valve cost, and `M_peak` peak margin. This
is a **comparison scaffold, not an adopted controller**. Every term has a separate measurement
status and uncertainty label; none may be backed out from realised P&L as one residual.

### 3.2 Minimum portfolio state worth testing

1. **Residual delta**, because it controls immediate underlying exposure and the breach valve.
2. **Gamma by short-DTE bucket**, because a delta-flat near-expiry book can change delta fastest.
3. **Vega by tenor bucket**, because aggregate vega is the scalable state in the multi-option
   theory and longer-dated inventory is vega-dominated.
4. **Liquidity/flattening state** of the offsetting quotes: queue-ahead bounds, fill intensity,
   spread and far-side exit cost.
5. **Peak-margin/account state**, because the economically relevant denominator is constrained
   capital, not notional or standalone quote P&L.

The exact buckets and covariance estimator are swept, pre-registered axes under `D29`; this list
does not freeze them.

### 3.3 What changes in the signal-mining programme

- A feature can matter without predicting the mid: it matters if it changes **which quote
  configuration is best** through fill intensity, markout, marginal portfolio risk, future
  flattening capacity or margin.
- Per-quote fill and markout remain indispensable measurement primitives. They are inputs to the
  configuration value, not competing estimands.
- Inventory must interact with EF, BK and later options/surface features. An OFI value against a
  delta-adding side is not equivalent to the same OFI against a delta-reducing side.
- “Natural put/call netting” and “skew-induced netting” must be reported separately. The former is
  a property of the tape/reference policy; the latter is the causal effect of the controller.

## 4. Tests registered from the literature

The binding forms live in `docs/sig-claims/book-state.md`.

1. **Inventory reversal and channel attribution (`BK-13/H1`).** At 1, 5, 15 and 30 minutes,
   measure how much of each inventory shock reverses and attribute it to passive option fills,
   aggressive option exits and futures. Hu et al.'s 38%–48% at five minutes is an external
   comparison, never the verdict boundary.
2. **State-sufficiency comparison (`BK-14/H1`).** In the same causal replay and action set,
   compare independent per-contract control, delta-only joint control, and
   delta+gamma-bucket+vega-bucket joint control. Report economic value per peak margin, tail P&L,
   time-to-flat and futures breaches — not a single Sharpe.
3. **Compression error (`BK-15/H1`).** Compare the low-dimensional Greek state with a richer
   inventory-vector yardstick inside declared inventory regions. If policy disagreement or value
   loss expands at the boundary, shrink the admissible region rather than pretending the
   approximation is global.
4. **Marginal portfolio-risk test.** Conditional on per-quote fill and markout, test whether the
   value of a possible fill varies with its covariance and Greek alignment with the existing
   book. This is the empirical content that distinguishes joint control from relabelled
   independent quoting.

## 5. What the literature does **not** licence

- continuous or costless futures delta hedging;
- independent Poisson fills across contracts;
- a vega-only controller for a near-expiry book;
- ignoring queue position, feed cadence, cancel latency, adverse selection or Indian taxes;
- treating an approximate HJB solution as evidence of profitability; or
- importing KOSPI/U.S. reversal rates as NSE parameters.

The correct conclusion is narrower and stronger: **portfolio-level control is the right object;
its state compression, fill mechanics and economic value are hypotheses for Shaurya's own tape.**

## 6. Claim–evidence ledger

| Claim | Type | Best support | Main assumption | Rival explanation / boundary | Shaurya test |
|---|---|---|---|---|---|
| A quote's value depends on the whole book | Structural | Stoikov–Sağlam; Guéant; Giannetti et al. | Centralised portfolio controller | Contract-siloed implementation | `BK-14/H1` |
| Passive option rebalancing can dominate futures hedging | Empirical benchmark | Hu et al. | Comparable electronic index-option ecology | KOSPI institutional structure | `BK-13/H1` |
| Delta-only netting can leave material risk | Structural | Stoikov–Sağlam; Baldacci et al. | Greeks/covariance estimated causally | At Shaurya's short holding horizon delta may suffice | `BK-14/H1` |
| A low-dimensional risk state can scale across many options | Approximation | Baldacci et al.; Bergault et al. | Local inventory region and stable sensitivities | Approximation fails in tail inventory | `BK-15/H1` |
| Capital state belongs in the objective | Structural | Fournier–Jacobs | Binding capital/wealth constraint | Broker offsets may alter peak-margin mapping | Config-level `SIG-17` gate |

## References

- Baldacci, B., Bergault, P. & Guéant, O. (2021). *Quantitative Finance*, 21(1), 85–97.
- Bergault, P., Evangelista, D., Guéant, O. & Vieira, D. (2021). *Applied Mathematical
  Finance*, 28(2), 101–142.
- Fournier, M. & Jacobs, K. (2020). *Journal of Financial and Quantitative Analysis*, 55(4),
  1117–1162.
- Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009). *Review of Financial Studies*,
  22(10), 4259–4299.
- Giannetti, A., Zhong, F. & Wu, L. (2004). *International Journal of Theoretical and Applied
  Finance*, 7(7), 853–878.
- Guéant, O. (2017). *Applied Mathematical Finance*, 24(2), 112–154.
- Hu, J., Kirilova, A., Muravyev, D. & Ryu, J. (working paper). *Options Market Makers*.
- Jameson, M. & Wilhelm, W. (1992). *Journal of Finance*, 47(2), 765–779.
- Muravyev, D. (2016). *Journal of Finance*, 71(2), 673–708.
- Naik, N. & Yadav, P. (2003). *Journal of Financial Economics*, 69(2), 325–353.
- Stoikov, S. & Sağlam, M. (2009). *Review of Derivatives Research*, 12(1), 55–79.
