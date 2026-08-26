# D39 Fixed-Target Competitor Panel — Frozen Specification

**ID:** `D39 / FIXED-TARGET-COMPETITOR-PANEL`

**Frozen from:** Aryan Ayyar's 2026-08-20 review and the complete handoff
`/Users/maheit/.openclaw/workspace/NEXT-SESSION-PROMPT-2026-08-21-D39.md`.

**Primary evaluation sample:** one untouched NIFTY front-month futures session captured from
before the 2026-08-21 open through the dated close.

**Development replay:** Aryan separately authorised an unchanged retrospective replay on the
validated 2026-08-20 late-partial tape. That replay is post-outcome, starts at 09:21:46 rather
than the open, and is permanently exploratory. It cannot alter this specification, validate a
signal, repair the failed 2026-08-20 registered run, or count toward any other registration.

**Order authority:** none. Read-only market data and analysis only.

## 1. Research question and fixed target

For each declared reference price, accumulation window `h1` and future horizon `h2`, the only
target is

`y_t = r(t + Z, t + Z + h2)`, with causal gap `Z = 0.5 seconds`.

The question is fixed: which declared competitor predicts `y_t` best on the same held-out rows?
The past-return mirror remains a leakage/contamination falsifier only. It never ranks a model and
is never treated as evidence of strength.

Receive time is the causal clock. Every predictor is measurable no later than anchor `t`.
Endpoints beyond the last observation are missing, never carried backward as zero.

## 2. Sample partition

Each tape is split chronologically 70/30 with a 120-second embargo. Training rows choose every
parameter, standardisation constant, ridge penalty, majority direction, and correction. Test rows
are scored exactly once. Reconnect epochs may not be bridged by a predictor or response window.

Every estimable competitor in one reference × `M` × `h1` × `h2` cell uses the identical common
train and test rows. `C10` remains in the artifact as `uncovered` if effective-touch support is
insufficient; it is never fabricated and never allowed to shrink the common sample of the
otherwise identified competitors to zero.

## 3. Competitor panel

| ID | Competitor |
|---|---|
| `C0` | unconditional training mean |
| `C1` | training-set majority direction; numeric forecast is that sign times the training mean absolute return |
| `C2` | lagged return over the same declared `h1` ending at `t` |
| `C3` | spread plus `log1p` level-one depth controls |
| `C4` | `C3` plus static level-one queue imbalance |
| `C5` | `C3` plus signed trade imbalance over `h1` |
| `C6` | `C3` plus exact CKS level-one OFI over `h1` |
| `C7` | `C3` plus raw rank-keyed CCZ OFI at levels `1..M` over `h1` |
| `C8` | `C3` plus depth-scaled rank-keyed CCZ OFI at levels `1..M` over `h1` |
| `C9` | `C3` plus simple microprice tilt |
| `C10` | effective-touch-relative queue imbalance, microprice tilt and depth-scaled CCZ OFI |
| `C11` | combined displayed-book panel `C3..C9` |
| `C12` | `C2 + C8`, the direct test of whether OFI adds beyond lagged returns |

`M in {1, 5, 10, 20}`. `M=200` is explicitly deferred because it is hours of additional
compute; it is not silently dropped. Accumulation windows and future horizons are each
`{0.5, 1, 2, 5, 10}` seconds.

`C1` is inherently a direction rule. Its declared numeric magnitude above allows the artifact to
carry R2, MAE and IC for every competitor without inventing a different target or selectively
dropping metrics.

## 4. Reference-price ladder and bid-ask bounce

Run every cell under:

1. `displayed_mid`;
2. `last_trade`;
3. `effective_touch_mid` (proxy; missing when undefined);
4. `microprice`;
5. `trade_sign_corrected = LTP - s * effective_half_spread`, where `s` is the existing
   capture-time trade sign and the effective half-spread is the Roll estimate fitted on training
   prints only;
6. `same_side_print`, whose return endpoints are resolved within the same classified print side.

`BOUNCE-01`: report first-order LTP-return autocorrelation and Roll effective spread for the whole
training sample and each 15-minute bucket. If first-order covariance is non-negative, Roll spread
is unidentified and reported missing rather than forced to zero.

`BOUNCE-02`: construct `trade_sign_corrected` causally using only the training Roll estimate.

`BOUNCE-03`: report `same_side_print` as a lower-support robustness reference.

`BOUNCE-04`: the D38 `last_trade/C8` lead survives bounce only if `C8` has positive absolute OOS
R2 under `trade_sign_corrected`, beats `C2`, and `C12` has positive incremental R2 over `C2`.
Otherwise the D38 headline is retracted explicitly, not silently abandoned.

## 5. Metrics and artifact refusal rule

Every estimated competitor carries, on the identical held-out rows:

- absolute OOS R2 against the training target mean;
- increments over `C0`, `C2`, and `C3`;
- Pearson and Spearman information coefficients with within-tape stationary-block bootstrap;
- sign accuracy and excess over `C1` and over `C2`'s sign accuracy;
- MAE in ticks;
- declared CCZ-style gross and net-of-cost PnL arms;
- past-mirror guard flag.

Absolute OOS R2 is always reported first. The artifact refuses to build if an estimated
competitor lacks a required metric, if common-row identities differ within a cell, or if a
blocked competitor disappears.

## 6. Pre-declared verdict

A candidate is `predictive` only when, in the same cell:

1. absolute OOS R2 is positive;
2. it beats `C2` on absolute OOS R2;
3. `C12` has a strictly positive increment over `C2`;
4. its past-mirror guard is not tripped; and
5. sign accuracy is at least `C1`'s.

Failing only condition 5 is `magnitude_only` and explicitly not tradable. Failing condition 2 or
3 is `subsumed_by_past`. All other failures are `not_predictive`. The original rule stays visible
even if later judged inadequate.

## 7. Required outputs and claim boundary

The artifact records the complete declared grid, all blocked/uncovered cells, tape identity and
hash, exact row identities, split boundaries, feature definitions, fitted training-only
parameters, metrics, bounce diagnostics, verdicts and a concise comparison of `C2`, `C8`, and
`C12`.

The 2026-08-20 replay must carry:

- `sample_role = retrospective_partial_session_exploration`;
- `confirmatory_eligible = false`;
- `registered_replication_eligible = false`;
- `order_entry_enabled = false`;
- opening coverage missed;
- reconnect/gap handling and all quality exclusions.

No result from that replay may change the 2026-08-21 panel, axes, verdict rule, or reference
definitions.

## 8. Acceptance requirements

- `VAL-D39-01`: a future-only synthetic signal is detected and a past-only signal trips the guard.
- `VAL-D39-02`: `C2` uses only returns ending no later than anchor `t`.
- `VAL-D39-03`: `C12` uses the exact union of `C2` and `C8` on identical rows.
- `VAL-D39-04`: every estimated competitor carries every metric and row hashes agree.
- `VAL-BOUNCE-01`: alternating bid/ask prints produce negative AR(1) and a positive Roll spread.
- `VAL-BOUNCE-02`: trade-sign correction removes a hand-worked constant half-spread bounce.
- `VAL-BOUNCE-03`: same-side endpoints never mix buy and sell prints.
- Full pytest, Ruff and strict mypy checks pass before a completion claim.

