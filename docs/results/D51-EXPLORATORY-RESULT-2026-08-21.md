# D51 same-day exploratory feature selection — 2026-08-21

**Status:** `exploratory_insufficient_sessions`
**Evidence:** Level-3 reproducible machinery; one-session exploratory content only
**Decision:** no stable or promoted cluster/model pair; no signal, confirmation, deployment,
economic-value or order claim.

## Pinned support

- Futures run: `sha-20260821T030335.366578Z-2038e775`
- Futures tape SHA-256: `d28d69c1d8fe627ac8553b02a4d75ee02915797594ff31ffbecd7ebe9beafc88`
- Surface DAT dataset: `sha-20260821T080612.138551Z-9b5bd89e`
- Surface tape SHA-256: `5ab4c881315ea83170bd4d959961d42bca6cbb945014bcfa79d360afeca49a22`
- Exact common futures/surface rows: 7,082
- Common-row fingerprint: `1d7cb84e01360d3778da0798e5bd94cf0051ef2d213b27b0003be364f7057ab7`
- Support: `1787299582562787000` through `1787306982001533000` ns
- Grid: one-second UTC-aligned engineering convention; the frozen ten-second estimand is
  unchanged.
- Walk-forward fold fingerprint: `9d50a6bc3a8b098b37be20de4a92cdf46e5ab58dea54d56e65aba7c0c1fab10e`

The expanding walk-forward produced three disjoint outer tests containing 1,416, 1,416 and 1,418
rows. Training support expanded from 2,712 to 5,544 rows. Every quality gate, correlation map,
representation, transform, configuration choice, early-stopping choice and model fit occurred
inside the applicable training boundary. The outer tests were apply-only.

## Model result

The table reports full outer-test point estimates. “Pooled” is the row-count-weighted MSE across
all 4,250 outer predictions; it is descriptive and carries no dependence-aware inference.

| Model | Fold 1 R² vs zero | Fold 2 | Fold 3 | Pooled R² vs zero | Pooled MSE |
|---|---:|---:|---:|---:|---:|
| Elastic net | 1.920% | 2.991% | 2.877% | 2.456% | 302.469 |
| Shallow boosted tree | -0.999% | 3.004% | -4.780% | -0.225% | 310.784 |
| Training mean | 0.155% | -0.794% | -0.067% | -0.216% | 310.754 |
| Declared simple state | -17.955% | 1.050% | -7.936% | -9.606% | 339.872 |
| Zero return | 0.000% | 0.000% | 0.000% | 0.000% | 310.086 |

Inner validation selected elastic-net `(alpha, l1_ratio)` values `(1, 0.9)`, `(1, 1)` and
`(1, 0.5)`. It selected tree stopping counts 35, 24 and 24; each count was carried unchanged into
the associated outer-training and conditional-usefulness refits.

Elastic net's positive point estimate in all three within-day folds is a lead for future
replication, not a stable forecast finding. The tree's sign changes and the weak baselines reinforce
the need for independent sessions rather than same-day promotion.

## Cluster evidence and hard boundary

- Training folds produced 88, 88 and 90 primary correlation clusters across seven declared
  families.
- The hard gate retained 114 of 220 registered features in every fold. All 96 eSSVI economic
  level/change/velocity/innovation fields fell below the 50% training-coverage requirement after
  4,163 rows were marked stale; only surface-quality diagnostics survived from that source. The
  result therefore does **not** answer whether usable surface economic state adds predictive value.
- The run emitted 5,894 joint cluster/family ablation and grouped-permutation rows, 532 stability
  rows and 100 regime-slice rows.
- 132 cluster/model entries had a positive same-fold conditional delta; 400 were non-positive.
  These are screening counts, not multiplicity-adjusted discoveries.
- Every one of the 532 stability rows has status `exploratory_insufficient_sessions`. Each has only
  one distinct session and one eligible fold for its complete selected model/configuration identity;
  the frozen gates require at least 20 sessions and five eligible folds.
- Past-mirror and cost/latency-adjusted economic guards were unavailable and were preserved as
  `not_supplied`, never imputed as passes.

The largest positive same-fold conditional deltas included 30-second and 5-second displayed-mid
lag clusters, 30-second multi-level CCZ OFI clusters, and one surface support-width cluster. They
are deliberately not called “selected features”: the unit is the complete correlation cluster,
the comparisons have no same-day inference or multiplicity claim, and none clears the stability
contract.

## Reproducibility artifacts

The complete exact-readback artifacts remain in `/tmp/d51-step7-complete` on the execution host;
they total about 1.2 GiB because Step 5 retains rowwise and blockwise paired losses. The compact
summary and interpretation tables are retained beside this report under `docs/results/`; raw tapes,
the 12.5 MB materialization cache and the 1.2 GiB detailed artifacts are deliberately excluded from
Git. Committed CSV copies use LF line endings; the generated values and ordering are unchanged.
Important SHA-256 identities are:

- materialized common-row cache: `08caa48004091b6dfd16a97004381f3230edf1d8c58d7f8f725f3ddea0a68a1d`
- final walk-forward JSON: `c57e586c9578b0a1a12144d76913cb3592e42076a5dc2cb5c4e00c8fd44d3f97`
- final stability-selection JSON: `0f8aba34c6275febc0b6b7d1aa3dc3624fe4d7e79fe652cc3ae47d9277121812`
- committed summary: `0cc53d071f1ebede66215d90d50964f29313246b5957a1a5c0e1a23040792a1a`
- selected model configurations: `291ff5fb1f98ea4885ff54471ee245155cae89825253b87a7433f0381a2852e2`
- model table: `653fd610ebd8f72e17953f7400eb84bc528eb4708462b0fc3883514a1afaf55e`
- gate table: `7460895290587815e198ed637fc57787ab5e0de1b79aa8db9c1adb9445e0ad68`
- cluster table: `a4dc6a7b3b158b0cc27c901d425a1741486cd563af7daf1f3f45ce269cdbe01d`
- ablation table: `9b13db0d179ec8fe149458232a5457ac8e0738cab87468e9c13403b87792781c`
- stability table: `ed233073375142ce78a309d06a959b5fd6aabc2b5852fce79e8a08140cb8de6a`
- regime table: `48c4e4bc763699e2c762b2a5931623702b2613dd3ddcbfe84112fbf6d2aa3e03`

The checkpoint envelope additionally binds the specification version, both source hashes, DAT
dataset identity, common-row fingerprint, walk-forward policy, fold, model/configuration and fold
fingerprint. A mismatched identity fails closed; a matching checkpoint reads back exactly and
resumes without refitting.

Two descriptive cautions matter. First, elastic net lowers pooled squared error while its pooled
absolute error remains worse than zero return (10.797 versus 10.211 ticks) and directional accuracy
is 45.67%; the same-day gain is tail-sensitive rather than broad. Second, stability is keyed by the
complete inner-selected model/configuration identity. Because the selected configuration differs
across the three folds, every stability row has one eligible fold; no model-class-level cross-fold
aggregation is silently substituted.
