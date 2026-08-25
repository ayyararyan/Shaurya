# D51 ALO-SMM strategy specification

## Objective

Provide selective passive liquidity in the current front-expiry NIFTY ATM call and put while maintaining the hard constraint

`inventory(contract) >= 0`.

The strategy is not a symmetric dealer. At zero inventory the SELL action is impossible. With inventory, SELL competes against HOLD. The purpose of the shadow month is to learn when acquisition/recycling is worth doing, not to maximize quote uptime.

## Fair-value stack

For the currently selected ATM strike `K*`, exclude that strike from the surface fit. Build a synthetic forward from fresh non-target call/put pairs, then fit an SSVI/eSSVI-style per-expiry total-variance slice:

`w(k) = theta/2 * [1 + rho*phi*k + sqrt((phi*k+rho)^2 + 1-rho^2)]`.

The implementation uses robust coordinate descent with warm starts and conservative shape caps. It is intentionally a single-expiry surface slice, not a claim of a globally calibrated multi-expiry eSSVI implementation.

The ATM surface value is the anchor. The reservation value adds a small microprice/underlying-state correction. The policy can only quote when the surface has enough fresh pairs and passes RMSE/parity-dispersion gates.

## Microstructure state

The online feature vector includes:

- leave-target-strike-out surface residual;
- current option spread;
- five-level depth-weighted imbalance;
- L1 microprice shift;
- multi-level futures OFI z-score;
- futures minus synthetic-forward residual z-score after slow basis removal;
- volume/intensity z-score;
- option/futures/surface age;
- surface RMSE and parity dispersion;
- time to expiry;
- option delta;
- current option lots and portfolio delta/vega/gamma.

## Action space

For each option and each side the candidate distances are configurable; shipped defaults are:

`0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50` points.

BUY prices are capped at or below the current best bid. SELL prices are floored at or above the current best ask. If no candidate clears EV/risk/quality thresholds, the action is OFF. When inventory exists, an absent sell quote is the HOLD action.

## Learned action value

Each action owns two online models:

`p_fill = P(conservative passive fill in horizon | state, action)`

`m = E(post-fill delta-hedged markout | fill, state, action)`

and

`raw_EV = p_fill * m`.

The final score subtracts inventory-Greek risk, quote churn and an uncertainty penalty, then adds online calibration. Sides with sufficient observations and persistently poor rolling counterfactual EV are killed automatically.

## Conservative counterfactual fill label

Because Neo SFeed snapshots do not reveal exchange order IDs or exact queue priority, shadow fill labels avoid fabricated queue position.

- BUY fills only if the observed ask reaches/crosses the hypothetical bid, or a **new post-placement trade** occurs at/below the bid.
- SELL fills only if the observed bid reaches/crosses the hypothetical ask, or a new post-placement trade occurs at/above the ask.
- LTP contributes only when cumulative volume increased after the hypothetical order was placed; a stale LTP is ignored.

This deliberately understates some fills. During eventual live testing, realized acknowledgements, partial fills and queue-age data should replace these labels in the fill-hazard model.

## Shadow inventory simulation

Only the selected policy quote affects simulated inventory. Counterfactual labels for unchosen actions train the models but do not alter inventory. A SELL shadow fill is blocked if the inventory ledger does not already contain enough lots.

## Why no unconstrained RL yet

One-day D51 models showed regime instability, especially on the CE acquisition side. End-to-end RL would make it easier to overfit that instability. The current architecture is a constrained contextual decision system with full-information counterfactual updates. Once many independent days exist, its retained data can support walk-forward fitted-Q/offline-RL comparisons without changing the execution engine.
