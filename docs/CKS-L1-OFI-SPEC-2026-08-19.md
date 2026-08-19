# Cont–Kukanov–Stoikov level-one OFI → future futures returns — exploratory scan specification

**Scan ID:** `X-CKS-L1-OFI-DAT20-04`
**Status before execution:** frozen exploratory design
**Confirmatory eligible:** `false`
**Frozen at:** 2026-08-19, before the 25-cell outcome table was computed or inspected.

## Plain-language question

Cont, Kukanov and Stoikov's order-flow imbalance is a *best-quote* object. It counts what
happened to the very front of the book — the best bid and the best ask — and turns it into one
signed number: net buying pressure in contracts. The question here is narrow and specific:

> On today's two retained NIFTY futures recordings, how much of the futures mid-price change
> that follows can this single level-one pressure number explain, once we control for how much
> size is actually sitting at the best quotes?

Depth control matters because the same +500 contracts of net pressure means something different
when the touch holds 200 contracts than when it holds 5,000. The scan therefore reports the
variable raw, the depth control alone, the two together, and the depth-scaled version.

This is **not** a rerun of `X-OFI-DAT20-03`. That scan searched 175 price-keyed constructions
across seven depth cutoffs and found its lead in levels 2–10, explicitly *not* in level 1. This
scan builds the canonical CKS level-one event-flow object, which `X-OFI-DAT20-03` did not
construct, and compares the two directly.

## Why this is exploratory

The only permitted tapes are the two `DAT-20` depth-200 recordings from 2026-08-19, about 22
minutes of a single falling session on one front-month NIFTY future. Their price paths and their
OFI outcomes have already been inspected. Nothing produced here may be called confirmed,
tradeable, causal, economic, or representative of another session. `confirmatory_eligible` is
`false` and this scan is not part of `H-SIG21`.

## `ID-CKS-01` Identification limits, stated before the results

Dhan publishes **book snapshots, not order-by-order messages**. Consequences, binding:

- **Gross limit-order arrivals are not identified.** Between two snapshots an addition and a
  removal at the same price net against each other; only the net change is observable.
- **Gross cancellations are not identified.** A fall in displayed quantity at an unchanged best
  price may be a cancellation, an execution, or both.
- Therefore every same-price increase is labelled a **displayed addition** and every same-price
  decrease a **displayed removal**. Neither is called an arrival intensity or a cancellation
  intensity anywhere in the code, the artifacts, or the report.
- The tape's `full` packets carry `cumulative_volume_increment` and a classified `trade_side`.
  These are used only for a **conservative execution-attribution diagnostic**: identified
  executed volume inside an interval is reported next to observed displayed removals, with the
  explicit caveat that vendor trade packets are coalesced, arrive on a different and much slower
  cadence than depth, and carry no level attribution. The residual is reported as
  *unattributed displayed removal*, never as "cancellations".

**Object categories (§7.1 of the working contract).** Best-quote prices and displayed quantities:
*observed*. `e_n`, the window sums, the depth control, and the depth-scaled pressure:
*deterministically derived*. Regression coefficients and R²: *estimated*. Executed-volume split:
*proxy*. Gross arrival and gross cancellation intensities: **unidentified**, and reported as such.

## `STATE-CKS-01` The level-one CKS event increment

For each consecutive pair of valid depth-200 snapshots `(n-1, n)` inside one connection epoch,
with best bid price/quantity `(P^B, q^B)` and best ask price/quantity `(P^A, q^A)`:

```
e_n =  1{P^B_n >= P^B_{n-1}} q^B_n  -  1{P^B_n <= P^B_{n-1}} q^B_{n-1}
     - 1{P^A_n <= P^A_{n-1}} q^A_n  +  1{P^A_n >= P^A_{n-1}} q^A_{n-1}
```

Units are contracts. Sign convention, with worked cases required as tests:

| Transition | Contribution | Sign |
|---|---|---|
| Best bid price rises to a new level holding 300 | `+300` | positive — buy pressure |
| Best bid price falls, old level held 300 | `−300` | negative |
| Best bid unchanged, size 200 → 500 | `+300` | positive — displayed addition |
| Best bid unchanged, size 500 → 200 | `−300` | negative — displayed removal |
| Best ask price falls to a new level holding 300 | `−300` | negative — sell pressure |
| Best ask price rises, old level held 300 | `+300` | positive |
| Best ask unchanged, size 200 → 500 | `−300` | negative — displayed addition |
| Best ask unchanged, size 500 → 200 | `+300` | positive — displayed removal |

Bid strengthening and ask depletion are positive; ask strengthening and bid depletion are
negative.

**Validity.** A transition is discarded, with a recorded reason, when either endpoint is not
depth-200, receive time is non-monotone, the connection epoch changes, an invalidating quality
flag is present, either side of either book is empty, or either book is crossed or locked. These
are the same rules `X-OFI-DAT20-03` uses, reused unchanged from
`shaurya.signals.deep_book_ofi._invalid_transition`. The level-one object needs no
outer-window-boundary guard: the vendor window slides at the far edge, never at the touch.

**Clock.** The level-one object is measured on the depth-200 publication clock, the same clock
`X-OFI-DAT20-03` used, so the two scans' observations are directly comparable. The response is
measured on the depth-20 BBO mid series, also unchanged.

## `STATE-CKS-02` Auditable transition decomposition

Every valid transition is classified into eight mutually exclusive, jointly exhaustive
components — four on each side — and each component's signed contribution to `e_n` is
accumulated separately:

| Component | Condition | Contribution to `e_n` |
|---|---|---|
| `bid_price_improvement` | `P^B_n > P^B_{n-1}` | `+q^B_n` |
| `bid_same_price_addition` | `P^B_n = P^B_{n-1}`, `Δq^B > 0` | `+Δq^B` |
| `bid_same_price_removal` | `P^B_n = P^B_{n-1}`, `Δq^B < 0` | `+Δq^B` |
| `bid_price_worsening` | `P^B_n < P^B_{n-1}` | `−q^B_{n-1}` |
| `ask_price_improvement` | `P^A_n < P^A_{n-1}` | `−q^A_n` |
| `ask_same_price_addition` | `P^A_n = P^A_{n-1}`, `Δq^A > 0` | `−Δq^A` |
| `ask_same_price_removal` | `P^A_n = P^A_{n-1}`, `Δq^A < 0` | `−Δq^A` |
| `ask_price_worsening` | `P^A_n > P^A_{n-1}` | `+q^A_{n-1}` |

An exact reconstruction check is required: the eight components must sum to `e_n` for every
transition, enforced in code and in tests.

Reported per tape and pooled: event count per second, absolute contracts per second, signed
contracts per second, and each component's share of total absolute contribution. Zero-change
same-price transitions are counted separately as `no_change` events so the intensities have an
honest denominator.

## `STATE-CKS-03` Accumulation windows

`h1 ∈ {0.5, 1, 2, 5, 10}` seconds. `OFI_{h1}` at snapshot `n` is the sum of `e_m` over every
transition ending in `(t_n − h1, t_n]`. A window is emitted only when its complete past lies
inside one valid connection epoch with no discarded transition in it — the same completeness rule
as `X-OFI-DAT20-03`.

## `EST-CKS-01` Depth control and depth scaling

Both are measured **at or before the OFI window end**. No quantity from the response interval may
enter any right-hand-side variable, and a leakage test asserts this.

- `l1_depth_end` — total displayed size at both best quotes at the window-end snapshot,
  `q^B_n + q^A_n`, in contracts.
- `log1p_l1_depth_end = log(1 + l1_depth_end)` — the depth baseline regressor. `log1p` is used
  because L1 futures depth is right-skewed and strictly non-negative, and `log1p` is finite at
  zero. It is a fixed transform, not a fitted one.
- `mean_l1_depth_window` — the mean of `(q^B + q^A)/2` over the snapshots inside the causal
  window, following CKS's average-depth scaling.
- `cks_pressure_{h1} = OFI_{h1} / max(mean_l1_depth_window, 1.0)`. The floor of one contract
  prevents division by a vanishing denominator; the number of observations that hit the floor is
  counted and reported. Units: contracts of net pressure per contract of resting depth.

## `EST-CKS-02` Models

For every cell, five models, all fitted by ordinary least squares through the existing
`fit_ridge(..., penalty=0.0)` path with training-set-only standardisation:

| Model | Regressors |
|---|---|
| `M1` | raw `OFI_{h1}` |
| `M2` | `log1p_l1_depth_end` (causal depth baseline alone) |
| `M3` | `log1p_l1_depth_end` + raw `OFI_{h1}` |
| `M4` | `cks_pressure_{h1}` alone |
| `M4b` | `log1p_l1_depth_end` + `cks_pressure_{h1}` |

**`ROB-CKS-01`** A separately labelled robustness model `R1` adds spread and microprice tilt to
`M3`, reproducing the `X-OFI-DAT20-03` baseline for comparability. It does not redefine the
primary depth-controlled comparison, which is `M3` versus `M2`.

## `OUT-CKS-01` Target and grid

`Y` is the change in the depth-20 best-bid/best-ask midpoint in NIFTY futures ticks (₹0.05),
resolved as-of and coverage-guarded, beginning `Z = 0.5` seconds after the OFI window ends and
running for `h2 ∈ {1, 2, 5, 10, 30}` seconds. The grid is `5 × 5 = 25` cells. **All 25 are
emitted**, including nulls, negatives and failures. No filtering or top-list selection occurs in
the artifacts.

## `VAL-CKS-01` Explanatory-power outputs

Pooled and per tape, for every cell and every model:

- in-sample R² and adjusted R² — descriptive only, never presented as forecasting power;
- held-out out-of-sample R² against the **training** mean, using the same chronological
  within-tape 70/30 split with a 120-second embargo as `X-OFI-DAT20-03`;
- incremental out-of-sample R² of `M3 − M2` (the requested depth-controlled increment) and of
  `M4b − M2`;
- coefficients in ticks per 100 contracts and per training standard deviation;
- coefficient sign agreement across the two tapes and increment positivity in both;
- train / embargo / test sample sizes and the effective support behind each cell.

## `VAL-CKS-02` Dependence, placebos and controls

- Paired squared-error improvement of `M3` over `M2` on the test set, assessed three ways —
  Newey–West with an overlap-sized lag, within-tape stationary block bootstrap, and
  non-overlapping time blocks. All three are reported. No naive standard error is treated as
  valid. A cell is called distinguishable only if all three exceed 1.96, and even then the
  multiplicity of a 25-cell search is stated.
- **Past-return mirror placebo on the complete 25 cells.** The identical models are refitted on
  the already-finished return over the `h2` seconds *ending* at the window end. If the past is
  explained as well as the future, the scan is measuring drift and reaction, not prediction.
- **Same-window diagnostic**: `OFI_{h1}` against the mid change over the same `h1` window,
  descriptive construction check only, never ranked as forecasting performance.
- **Tape-by-tape stability**: every cell refitted inside each recording separately.
- **Explicit comparison to `X-OFI-DAT20-03`**: the level-one CKS increment versus that scan's
  top-10 price-keyed construction and its levels-2–10 localisation, at the matching cells.

Twenty-two minutes of one falling session cannot support strong `p`-value claims. Where a check
is underpowered or undefined, the artifact emits that fact and the report states it. Nothing is
fabricated to fill a cell.

## `OUT-CKS-02` Artifacts and reproducibility

`artifacts/` is gitignored by repository policy and raw tapes are never committed. The scan
therefore commits: this specification, the implementation, the tests, a compact deterministic
committed result summary in the report, the pinned tape SHA-256 digests, the execution commit,
and the exact regeneration command. Running that command on the same tapes at the same commit
must reproduce the artifact byte-for-byte; a deterministic replay check verifies this.

## Explicit exclusions

- No live orders, no order placement, no credentials, no new market-data subscriptions.
- No new tapes; only the two already-retained 2026-08-19 recordings.
- The 175-cell `X-OFI-DAT20-03` grid is **not** rerun, rebranded or re-searched.
- `docs/sig-claims/H-SIG21.md` is not touched. This scan is not its confirmation.
