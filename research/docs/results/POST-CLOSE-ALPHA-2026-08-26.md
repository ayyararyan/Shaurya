# Shaurya post-close futures-to-options research memo

Status: **completed, exploratory single-session evidence**. The defensible result is a narrow
incremental association for the 30-second signed option-mid markout. It is not evidence of true
MBO, queue position, fills, causal structure, tradable alpha, or economic value after costs.

## Data integrity and replay quality

- Dataset: `sha-20260826T063840.939559Z-b7c47c19`, immutable `COMPLETED`, no invalidation.
- Coverage: 2026-08-26 06:38:41.232762Z to 10:09:00.975618Z (3.51 hours), 1,935,092
  rows, all 121 requested instruments observed.
- Tape SHA-256: `13f9931bbe9e03c4c11bcabb72f8fed397c86e7284523a3d0797120d6bcaa0e0`.
- Seek-index SHA-256: `97e3eab630c59dc1943edea523605840a8f626539e32e54f4e3cc78badcf8221`.
- Lifecycle, manifest, tape and index hashes, index binding/counts/coverage, and two full replay
  row counts passed. Raw tape, catalog, collector, broker interfaces, and D51 were untouched.

The reconnect summary was not accepted at face value. Source semantics show that its counters
increment only after connection exceptions and heartbeat timeouts. Record replay independently
found four connection epochs and three matching first-post-reconnect rows carrying
`connection_gap`, `heartbeat_timeout`, and `reconnected`. The record-free gaps were 5.62 s,
8.93 s, and 20.59 s. The run was stable for most of the session; these were localized disruptions,
not grounds to characterize the whole capture as unstable.

The replay-derived audit is explicitly not a native collector-quality audit. Stored receive
sequence is contiguous across all rows, but source sequence is unavailable throughout, so upstream
packet-loss completeness cannot be proved. The audit found 374 partial-book rows concentrated at
epoch initialization, 16 exchange-time regressions, no crossed books, and one additional uncertain
3.67-second within-epoch record gap. Buffers around all epoch edges, reconnects, partial/crossed/
stale/invalid books, sequence flags, exchange-time regressions, and record gaps produced:

| Quality buffer | Clean time | Panel rows |
|---:|---:|---:|
| 10 s | 3.29 h | 156,609 |
| 30 s (primary) | 3.17 h | 151,223 |
| 60 s | 2.99 h | 142,577 |

The primary panel has 105,874 rows from epoch 1, 7,357 from epoch 2, and 37,992 from epoch 4.
Epoch 3 lasted eight milliseconds and contributes no clean rows.

## Features and targets

Option-state controls are option log mid, relative spread, microprice displacement, five-level
depth imbalance, lagged five-second return, call/put, scaled strike, and time of day. Incremental
futures features are futures log mid, relative spread, microprice displacement, five-level depth
imbalance, ten-second nonnegative cumulative-volume-increment intensity, and 30-second realized
volatility. “Trade intensity” is therefore a quote-tape volume-change proxy, not transaction MBO.

Targets are precisely:

- `markout_5s` and `markout_30s`: signed future option-mid displacement divided by the current
  option half-spread;
- `adverse_proxy_5s` and `adverse_proxy_30s`: absolute magnitude of those signed displacements.

These are markout/adverse-movement proxies, not realized fill adverse selection.

## Descriptive correlations

On the primary 151,223-row panel, futures features have near-zero Pearson association with signed
markouts: maximum absolute correlation is 0.0041 at 5 s and 0.0071 at 30 s. Associations with
absolute-movement proxies are somewhat larger. Full-panel correlations include futures relative
spread with `adverse_proxy_30s` at -0.0661, volume-increment intensity with
`adverse_proxy_5s` at +0.0425, and realized volatility with `adverse_proxy_5s` at +0.0351.

On the untouched chronological test segment used by the first estimator (44,276 rows), the largest
futures correlations are relative spread with `adverse_proxy_30s` at -0.0841, intensity with
`adverse_proxy_5s`/`adverse_proxy_30s` at +0.0565/+0.0467, and realized volatility with those
targets at +0.0554/+0.0368. Futures microprice and depth imbalance remain small (absolute test
correlation at most 0.0298 and 0.0243). These are univariate descriptions, not predictive
validation or conditional effects.

## Chronological validation

The final estimator is ridge regression with an unpenalized intercept. It uses chronological
60/20/20 train/validation/test partitions with 30-second embargoes, selects the penalty separately
for each baseline and augmented target model using validation MSE, refits on the pre-test
development sample, and applies development-only 0.5/99.5 percentile feature clipping and
standardization. The primary test has 29,235 rows. Uncertainty is clustered at five-second grid
time using a 12-lag HAC interval, with 400 60-second block-reweight replicates as a check.

| Target | Baseline OOS R2 | Augmented OOS R2 | Delta OOS R2 (HAC 95%) | MAE improvement (HAC 95%) |
|---|---:|---:|---:|---:|
| `markout_5s` | 0.00153 | 0.00174 | +0.00021 [-0.00101, +0.00143] | +0.01595 [+0.01229, +0.01961] |
| `adverse_proxy_5s` | 0.08480 | 0.05716 | -0.02764 [-0.05123, -0.00405] | +0.06468 [-0.00731, +0.13667] |
| `markout_30s` | -0.01055 | -0.00436 | +0.00619 [+0.00127, +0.01111] | +0.05516 [+0.02739, +0.08293] |
| `adverse_proxy_30s` | 0.07154 | 0.05464 | -0.01690 [-0.03307, -0.00073] | +0.00807 [-0.12995, +0.14608] |

The 30-second signed result survives stricter quality and tail checks: with a 60-second buffer,
delta OOS R2 is +0.00738 [0.00193, 0.01282]; after development-defined target winsorization it is
+0.00962 [0.00226, 0.01698]. The five-second signed R2 increment remains indistinguishable from
zero. Adding futures features worsens squared-error performance for both absolute-movement proxies,
and their MAE changes are uncertain.

## Conclusion and limits

Futures microstructure adds a small, statistically distinguishable relative error reduction for
the 30-second signed option-mid markout in this one session. The augmented model's absolute OOS R2
is still -0.00436, so it does not beat the test-mean benchmark and does not establish standalone
predictive skill. There is no supportive incremental R2 result at five seconds or for either
absolute adverse-movement proxy.

This is exploratory screening evidence only. One afternoon cannot establish cross-session
stability. Standard-feed rows are aggregate snapshots with no order IDs, queue priority,
add/modify/cancel events, or fills. Source-packet completeness is unverified, and there is no
execution, latency, cost, or capacity analysis. A preregistered multi-session replication would be
required before any stronger conclusion.
