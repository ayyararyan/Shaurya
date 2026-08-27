# High-frequency construction freeze

## Scope and semantic authority

The runtime implementation is `data/src/shaurya/data/high_frequency.py`; canonical Black-76 and
eSSVI primitives are in `data/src/shaurya/data/option_pricing.py`. Exact production identities and
roles are frozen in `research/registries/microstructure_features_v2.yaml`; future-only outcomes are
separate in `microstructure_targets_v2.yaml`. Every persisted derived value carries its exact
`feature_version`, availability timestamp, source timestamps, connection epoch, and an explicit
unavailable reason when missing.

The v1 registries remain unchanged for historical replay. The v2 CCZ constructor intentionally
uses the specification's prior bid quantity when a bid price worsens; the legacy research CCZ
constructor used the new quantity. This correctness difference is versioned rather than silently
changing v1 history. The unrecoverable legacy `surface_centered` generator remains unavailable;
only `option.essvi_leave_atm_residual.v2` is constructible for new rows.

## Common timing and quality rules

- Grain is instrument/option-contract × exact one-second decision timestamp unless the CCZ input
  is a sub-second event transition.
- All source/receive timestamps are at or before the decision timestamp. Windows are left-looking;
  target endpoints are future-only and use a distinct `TargetValue` type.
- Crossed, invalid, stale, future, wrong-expiry, wrong-epoch, incomplete-path, and zero-denominator
  inputs yield missing, never fabricated zero. No forward-fill crosses a reconnect.
- Futures tick is 0.05 index points. Option freshness and futures freshness are each at most one
  second for parity/surface/ATM-IV construction. IST session buckets use Asia/Kolkata.
- Relative states use q33/q67 from `[t-900s,t)`, minimum 120 valid same-epoch observations, linear
  empirical-quantile interpolation. Current and future values cannot move the thresholds.

## Construction map

| Canonical variables | Formula/algorithm | Units and use | Missingness and revalidation |
|---|---|---|---|
| `futures.ccz_ofi_0p5s_m1_average.v1` | Exact CCZ event flow over `(t-0.5s,t]`; one common depth denominator; M=1 average | dimensionless; quarantined directional diagnostic | missing on no event, invalid depth, or epoch break; transportability requires new sessions |
| `futures.order_count_imbalance_cum5.v1`, `futures.quantity_imbalance_cum1.v1`, `futures.quantity_imbalance_cum5.v1` | `(bid-ask)/(bid+ask)` over exact order counts or quantities and registered depth | `[-1,1]`; book state | missing on insufficient depth, stale/invalid book, or zero total |
| `futures.microprice_tilt_ticks.v1`, `option.microprice_shift_l1.v1`, `option.quantity_imbalance_invdepth5.v1` | L1 cross-weighted microprice; option quantity weights `1/l` | ticks, option points, dimensionless | missing on bad BBO/depth/zero denominator; L1 quantity and microprice are redundancy-controlled |
| `parity.exatm_forward_median.v1`, `parity.pairs_exatm.v1`, `parity.range_exatm.v1`, `parity.max_quote_age_seconds.v1` | median `K+CE_mid-PE_mid` over ATM ±1…4 excluding ATM; minimum five fresh pairs | index points/count/seconds; anchor and quality | missing below five pairs; ATM never enters consensus |
| `parity.basis_raw.v1`, `parity.basis_slow_median30_lag1_min10.v1`, `parity.syn_gap.v1`, `parity.pressure.v1`, `parity.fair_quality.v1` | raw basis `M-F`; prior-only 30-row median with min 10; gap `raw-slow`; pressure `-gap`; quality `pressure/(range+0.25)` | index points/scaled pressure | missing propagates; current raw basis is excluded from slow basis |
| `option.essvi_leave_atm_residual.v2`, `option.call_put_surface_residual_diff.v2`, surface quality flags | equal-weight nonlinear least squares in eSSVI total variance using fresh ex-ATM OTM prices; static-arbitrage check; fair-minus-observed ATM price | option points; quote centering | ATM excluded from fit; failed inversion/fit/arbitrage is missing; all V2 statistics require fresh validation |
| `liquidity.l1_total_quantity.v1`, `liquidity.log_l1_depth.v1`, `liquidity.spread_ticks.v1`, `risk.midpoint_vol_{10,30}s.v2` | L1 depth, `log1p(depth)`, spread/0.05, population SD of one-second midpoint changes | contracts/log contracts/ticks/points | volatility needs complete exact path; V2 coefficients are not inherited |
| `futures.prior_mid_move_5s_ticks.v1`, `futures.mid_reversal_pressure_5s.v1`, `state.trend_efficiency_10s.v1` | `(M_t-M_t-5)/0.05`, sign inverse, and path efficiency `abs(endpoint move)/sum abs changes` | ticks/dimensionless | exact same-epoch history required; zero efficiency denominator is missing |
| `state.*.v1`, `gate.*.v1`, `interaction.*.v1` | past-only relative tertiles, fixed trend/IST labels, deterministic conjunctions and sign agreement | categorical/boolean support | no automatic hard veto or independent alpha; missing inputs propagate |
| `option.atm_{ce,pe}_iv.v1`, `option.atm_iv_mid.v1`, IV shocks/difference/surface gap | canonical Black-76 inversion with `r=0.055`, exact time to 15:30 IST; backward shocks ×10,000 | absolute IV or IV basis points | parity range >5, stale quotes/future, inversion failure, and epoch gaps are missing |
| `risk.atm_iv_vov_60s_bp.v1`, `state.atm_iv_vov60_rel.v1`, `gate.atm_iv_reversal_mid_vov.v1` | sample SD (`ddof=1`) of trailing 60 one-second IV shocks, min 40; causal relative tertile; mid-state gate | IV bp and support state | no epoch crossing; adaptive gate must be re-estimated before promotion |
| `postfill.aligned_*_historical.v1` | position sign × CE/PE delta sign × frozen predictor | predictor units; replication only | reconstructed fills are not live fill evidence and carry no automatic toxicity weight |

## Targets and anti-leakage

`target.futures.mid_move_ticks_{1,2,5,10}s.v1` uses displayed midpoint endpoints and 0.05 tick
normalization. `target.futures.range_ticks_{1,2,5,10,30,60}s.v1` requires every one-second point
from `t` through `t+h`. ATM-IV targets use `10,000*(ATMIV[t+h]-ATMIV[t])`. Raw option markouts use
option midpoint changes; hedged markouts subtract beta times the **actual futures midpoint change**,
never change in `F_exatm`. The spread target is `SpreadTicks[t+10]-SpreadTicks[t]`. Registry
validation rejects every `target.*` identity from the feature registry.

## Consumers, evidence, and risks

The explicit bundle `HIGH_FREQUENCY_REGISTRY_BINDING` selects the four v2 registries. Mechanism
heads remain separate: parity/book direction, option surface centering, ATM-IV repricing,
liquidity/range, and historical post-fill replication. Gates route or shrink confidence; they do
not become standalone direction models. Fast OFI, historical parity/order-count agreement, and
reconstructed-fill alignments are quarantined from automatic live weight.

The three cited sessions support construction freeze and shadow evaluation only. Software tests
verify identities, boundaries, missingness, causality, target separation, registry resolution, and
determinism; they are not empirical evidence. Fresh session-level walk-forward results, costs,
fills, capacity, Dhan executability, and broad-regime stability are required before promotion.
