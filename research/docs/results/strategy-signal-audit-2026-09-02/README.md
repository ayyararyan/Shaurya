# Strategy and signal reuse audit — 2026-09-02

## Decision

The full Shaurya research archive contains **three reusable forecast signals and two
execution-state diagnostics**, but still no demonstrated profitable strategy after executable
costs. The useful result is a smaller and clearer research stack:

1. forecast near-term futures volatility from recent volatility;
2. add recent futures volume intensity because it contributes information beyond volatility,
   spread and time of day;
3. use the option surface to forecast the magnitude of the next five-minute ATM-straddle move;
4. use call-minus-put movement and L1 imbalance only to adjust urgency or passive-order placement;
5. keep cash as the directional trading decision until a signal survives real fills and costs.

This is a retrospective reuse audit. Every session had appeared somewhere in earlier research,
so none of the results below is a new prospective trading test.

## Signals worth retaining

### 1. Short-horizon volatility persistence — strong risk signal

- **Predictor:** square-root sum of squared NIFTY-futures log-mid returns over the trailing 30
  seconds.
- **Estimand:** the same realised-volatility statistic over the next 5, 10 or 30 seconds, starting
  after a one-second embargo.
- **Data:** raw futures L1 books on 26, 27 and 28 August 2026, reduced to one-second last-book
  observations with at most two seconds of quote carry. The 28 August capture is futures-only and
  starts late, so it is an additional diagnostic rather than a complete-session result.
- **Result:** rank correlations for the 5-second target were 0.198, 0.216 and 0.268. At 10 seconds
  they were 0.230, 0.258 and 0.313; at 30 seconds, 0.229, 0.275 and 0.351. Every session-level
  60-second moving-block confidence interval was above zero.
- **Use:** volatility forecast, position-size throttle, quote-width control and a gate for other
  strategies. This is not directional alpha by itself.

This also agrees with the older 1,270-session histogram study: index-only models had 30–35%
realised-volatility skill in 2026, while rolling-ATM option fields did not improve that task.

### 2. Recent futures volume intensity — incremental risk signal

- **Predictor:** cumulative traded volume over the trailing 10 seconds.
- **Estimand:** forward 30-second realised futures volatility, after the one-second embargo.
- **Baseline:** trailing 30-second volatility, current spread and clock sine/cosine.
- **Protocol:** fit on 26 August and apply unchanged to 27 and 28 August.
- **Result:** adding volume improved MAE skill by 0.182 percentage points on 27 August, with a
  paired block interval of +0.015 to +0.353 points. It improved skill by 1.161 points on 28 August,
  with an interval of +0.844 to +1.471 points. Univariate volume/volatility rank correlations were
  also positive at 5, 10 and 30 seconds on all three raw futures tapes.
- **Use:** retain as a distinct feature in the volatility/risk model. The gain is modest, but it is
  genuinely incremental and replicated.

### 3. Option-surface state — strong predictor of future straddle movement magnitude

- **Predictor:** a causal block containing current, 30-second change and 60-second change for
  option-surface fields, option returns, relative spreads, depth imbalances, ATM straddle level and
  call-put skew.
- **Estimand:** absolute change in the rolling near-expiry ATM straddle, normalised by futures, over
  the next five minutes. Observations with an ATM strike change are excluded.
- **Baseline:** contemporaneous futures spread, microprice displacement, depth imbalance, volume
  intensity, recent volatility, recent return and clock.
- **Protocol:** train on 19 and 21 August; apply the same histogram-gradient-boosting models to 26
  and 27 August. A second test starts the outcome five seconds after the predictor timestamp.
- **Result with five-second embargo:** on 26 August, baseline MAE skill was 3.25% and augmented
  skill was 15.86%, an increment of +12.61 percentage points (paired block interval +9.09 to
  +16.13). On 27 August, baseline skill was 3.94% and augmented skill was 10.34%, an increment of
  +6.40 points (+4.25 to +8.92).
- **Important boundary:** the same option block made forecasts of future *futures realised
  volatility* worse. It predicts repricing magnitude in the ATM straddle, not generic spot
  volatility and not direction.
- **Use:** option-risk alert, no-trade/size gate, inventory hedge urgency and candidate trigger for
  future fixed-contract convexity research. It is not yet option P&L because the target is a
  rolling-ATM midpoint feature.

## Signals useful only for execution

### 4. ATM call-minus-put movement

The predictor is the 30-second change in near-ATM call mid minus the corresponding put change. The
estimand is the subsequent signed futures-mid return. With a five-second target-start embargo,
the 10-second rank correlations were +0.022, +0.095, +0.105 and +0.117 on 19, 21, 26 and 27
August. Adding it to a futures-state Ridge model raised directional AUC from 0.481 to 0.540 on 26
August and from 0.495 to 0.565 on 27 August. Incremental MAE skill was statistically positive only
on 27 August (+0.816 percentage points).

This is a weak price-discovery/state feature, not a trade. Earlier full-history minute tests lost
the effect after a one-minute embargo, and unchanged August execution lost about 2.17 bps per
trade. Use it only to shade an already-authorised order or suppress an adverse entry.

### 5. Futures L1 depth imbalance

Current best-level bid/ask quantity imbalance had positive 1-second-embargo rank correlation with
future mid returns at 1 and 5 seconds on all three futures tapes. At one second the correlations
were 0.056, 0.084 and 0.040. The top-minus-bottom-decile move was only 0.025–0.059 bps, however.
Every aggressive execution simulation lost roughly 1.5–2.6 bps per trade before the additional
0.5-bp reserve. Retain imbalance as an order-placement/urgency feature, never as a crossing signal.

## What was downgraded or rejected

- **JEPA:** the earlier headline latent-velocity correlation with contemporaneous 30-second
  surface displacement was about 0.19 on 26/27 August. Starting the target five seconds later cut
  it to about 0.05–0.08, and discovery-day results were near zero. Hard regimes collapsed to one
  state. JEPA currently describes stress; it does not forecast enough to justify more compute.
- **IV and term-structure mean reversion:** apparent 30-second correlations near 0.3–0.45 collapse
  to roughly 0.01–0.09 after a five-second delayed target start and to approximately zero after ten
  seconds. This is one-grid quote adjustment, not durable alpha.
- **Surface curvature:** strong univariate association was redundant after IV lags and basic
  state. Incremental skill intervals crossed zero on 26 and 27 August.
- **OpenEvolve:** its discovery winner retained only +0.271 bps/day at a 1-bp hurdle in validation
  (p=0.438) and was negative at 2 bps or more. Reject.
- **Formula, sparse-phase, regime/jump and baseline tournament:** none survived Holm-corrected
  validation and costs. The sparse-phase final emitted no trades.
- **Paper replications:** quarter-hour phase, low-volatility gating, half-hour option reversal and
  smile-curvature rules did not survive local costs/stability tests.
- **Far put-call parity:** a large midpoint association failed both taker and queue-aware maker
  execution. The maker headline lost 9.896 bps across 33 fills from 203 opportunities; none of 18
  configurations was profitable on both sessions.
- **Delta-hedged volatility carry:** all 18 January configurations were negative before the extra
  reserve; the unchanged February rule also lost. Keep the RV forecaster, discard this trading
  wrapper.
- **Historical option-surface directional alpha:** all candidates were negative at 6 bps over
  1,270 sessions. Rolling moneyness remains a predictor archive, not a fixed-contract P&L archive.
- **Real-tape mining, rolling-gap validation, relative-value mean reversion, opening-gap folklore
  and short-straddle screens:** no cost-aware, stable, executable survivor.

The complete decision inventory is in `strategy_evidence_ledger.csv` and the full machine results
are in the two JSON files beside this report.

## Implications from current research

The literature review was restricted to primary papers and conference records:

- A 2026 order-flow model links persistent flow, rough traded volume, volatility and market impact.
  That mechanism motivated the multiscale volume/volatility audit, which produced the new
  incremental volume signal. Source: [Muhle-Karbe et al.](https://ssrn.com/abstract=6155066).
- Recent public-data evidence finds that dealer net gamma predicts next-bar realised variance,
  while related work links gamma inventory to reversal versus momentum. This is the most valuable
  untested mechanism, but it needs fixed contracts, expiry, strike-level open interest and Greeks;
  rolling-ATM files cannot reconstruct it faithfully. Sources:
  [Ardia and Vaudescal](https://ssrn.com/abstract=7202999),
  [Dim, Eraker and Vilkov](https://ssrn.com/abstract=4692190), and
  [Adams et al.](https://ssrn.com/abstract=5641974).
- The published intraday option-reversal effect did not transfer to this NIFTY archive under the
  tested representation and costs. Source:
  [Beckmeyer et al.](https://ssrn.com/abstract=5081696).
- Hexagon-Net and deep IV-surface ensembles show that richer surface representations can matter.
  Our current four complete surface sessions are far too small for that complexity, and simple
  HGB/PCA baselines already equal or beat JEPA on our targets. Sources:
  [KDD 2025 record](https://doi.org/10.1145/3711896.3736996) and
  [Kelly et al.](https://ssrn.com/abstract=4531181).
- Current realised-volatility foundation-model comparisons do not show a universal deep-model
  advantage; fine-tuning and strong HAR-style baselines matter. That supports improving the simple
  risk model before adding another large architecture. Sources:
  [Goel et al.](https://arxiv.org/abs/2505.11163) and
  [Brini](https://arxiv.org/abs/2607.05291).

## Recommended implementation order

1. Build one small `risk_state` output with predicted 30-second futures volatility, volume shock
   and predicted five-minute straddle displacement.
2. Record it prospectively without trading for at least 20 complete sessions; monitor MAE skill,
   calibration by decile and session-level sign/stability.
3. Use call-minus-put and L1 imbalance only to choose passive versus urgent execution for trades
   authorised by a separate strategy.
4. Add strike, expiry, option bid/ask, cumulative volume and end-of-day open interest to the manual
   capture. Only then run a predeclared dealer-gamma/reversal experiment.
5. Do not spend more compute on JEPA, OpenEvolve or graph/foundation models until the simple model
   has substantially more independent complete sessions and a target that maps to executable P&L.

## Reproduction boundary

- `unified_signal_audit.py` contains the causal feature/target construction, chronological model
  fits, block-bootstrap intervals and bid/ask taker diagnostics.
- `jepa_embargo_audit.py` reloads the already-frozen five JEPA seeds and shifts target starts by
  zero, five and ten seconds; it does not retrain on diagnostic sessions.
- Full JSON contains all tested horizons, sessions and negative controls. No failed result was
  silently removed.
