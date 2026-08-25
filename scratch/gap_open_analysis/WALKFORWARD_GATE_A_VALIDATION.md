# Gate A PUT stop/target overlay: walk-forward validation

**Run date:** 2026-08-22  
**Overall task status:** **COMPLETE** — all requested walk-forward, fixed-cell, baseline,
stability, placebo, and power checks were run.  
**Validation verdict:** **UNDERPOWERED TO SAY CONCLUSIVELY.** The adaptive overlay remains
positive and statistically different from zero on 28 out-of-fold trades under all three
prespecified training-selection criteria. However, it does **not** significantly outperform
the gap-fill-only baseline on those same trades, and neither frozen headline cell is
significant on the untouched most-recent eight trades. This is encouraging predictive
evidence, but it is not a clean confirmation of the overlay's incremental edge and is not a
refutation either.

No broker, credential, order-placement, or network path was used. No live order was
authorized or placed.

## 1. Exact statistical object and claim boundary

The unit is one chronological Gate A PUT trade: an expiry day on which India VIX rose
overnight and NIFTY gapped down, with entry at 09:17. The outcome is percentage return on a
theoretical ATM PUT premium. At each minute, exits have the same priority as the source
analysis: stop-loss, then take-profit, then gap-fill; otherwise hold to 15:29.

This is a **predictive validation of a model-dependent return proxy**, not causal evidence
and not executable-P&L validation.

| Object | Label | Construction / boundary |
|---|---|---|
| Date, minute spot path, prior 15:29 close, opening IV, overnight-VIX-rise label | **Observed** | Existing local historical files |
| Expiry/gap-down membership, ATM strike, gap-fill minute, chronological split | **Deterministically derived** | Derived without fitting |
| Minute PUT premium and return | **Model-dependent proxy** | Black–Scholes, constant opening IV, ATM strike at 09:17 |
| Stop/target/grid return | **Scenario-based** | Mechanical exit under the specified threshold |
| OOF summaries, t/Wilcoxon tests, selection shares | **Estimated** | Finite historical sample |
| Shuffled-label control | **Scenario/placebo** | Permuted VIX-rise labels within comparable expiry-gap-down days |
| Executable bid/ask fills, spread, slippage, brokerage, intraday IV path | **Unidentified here** | Not present in this test |

The principal one-sample p-value is the same two-sided one-sample t-test against zero used
by the in-sample script. A two-sided Wilcoxon signed-rank p-value is included as a small-sample
sensitivity check. Comparisons with the baseline use a paired t-test of trade-by-trade return
differences. Inference treats trade dates as independent; with this sample size, that
assumption cannot be stress-tested reliably.

## 2. Protocol and leakage controls

The implementation mirrors `ml_walkforward_put_call.py` exactly:

- Total Gate A PUT sequence: **55 trades**, 2021-12-02 through 2026-05-12.
- Most recent `round(55 × 0.15) = 8` trades held out: **2026-01-06 through
  2026-05-12**. These trades never enter adaptive cell selection.
- Earlier walk-forward pool: **47 trades**.
- Initial expanding-window seed: `round(47 × 0.40) = 19` trades.
- Remaining **28 trades** evaluated in seven consecutive four-trade folds, from
  2023-12-21 through 2025-12-16.
- At every fold, the best of the nine cells is selected using training observations only.
- Selection is repeated separately for training mean, training median, and a Sharpe-like
  ratio (`training mean / training sample standard deviation`).
- Exact score ties are resolved by the declared grid order: smaller stop first, then smaller
  target. No tie-break uses validation outcomes.
- The two fixed cells, -30%/+50% and -30%/+75%, are prespecified in the module spec. They are
  not retuned; they are evaluated once on the final eight trades only.

Reproduction guards first recovered all nine published in-sample means within 0.06
percentage point and recovered the +39.0% baseline before allowing validation to continue.

## 3. Adaptive expanding-window results

Returns are percentage points of theoretical PUT premium return.

| Training selection criterion | OOF N | Mean | 95% CI for mean | Median | Win rate | t-test p | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mean | 28 | **+35.55%** | [+12.16%, +58.94%] | +38.36% | 50.0% | **0.0043** | 0.0133 |
| Median | 28 | **+31.44%** | [+10.37%, +52.51%] | +53.08% | 53.6% | **0.0049** | 0.0074 |
| Sharpe-like | 28 | **+33.78%** | [+12.90%, +54.65%] | +53.08% | 53.6% | **0.0026** | 0.0054 |
| Gap-fill-only baseline, same 28 trades | 28 | +29.41% | — | -7.94% | 35.7% | 0.2255 | 0.8291 |

The overlay therefore **survives the adaptive OOF test against zero** under all three
criteria. The median and win-rate improvement relative to the same-trade baseline is also
economically visible. But the overlay-specific incremental mean is not established:

| Criterion | Mean overlay minus baseline | Paired t-test p |
|---|---:|---:|
| Mean-selected | +6.15 percentage points | 0.7857 |
| Median-selected | +2.03 percentage points | 0.9289 |
| Sharpe-selected | +4.37 percentage points | 0.8525 |

Thus the significant OOF return cannot be attributed specifically to the stop/target layer;
the underlying gap-fill-only Gate A trade also has a positive, extremely noisy OOF mean.
The three adaptive results are highly correlated because they use the same 28 trades and
often the same cells. They are robustness views, not three independent confirmations.

### Comparison with the original in-sample grid

The original full-sample headline cells were:

| Fixed cell | In-sample N | Mean | Median | Win rate | t-test p |
|---|---:|---:|---:|---:|---:|
| -30%/+50% | 55 | +25.75% | +50.71% | 58.2% | 0.0001 |
| -30%/+75% | 55 | +31.15% | +75.07% | 50.9% | 0.0001 |

The adaptive OOF means (+31.44% to +35.55%) are not smaller than the in-sample headline
range. That comparison is descriptive, because the OOF strategies switch cells as training
expands, whereas the table above fixes one cell across the full sample.

## 4. Cell-selection stability

| Criterion | Cell selections across 7 folds | Dominant cell share | Cell changes between folds |
|---|---|---:|---:|
| Mean | -30/+75: 5; -30/+100: 2 | 71.4% | 3 of 6 |
| Median | -30/+50: 1; -30/+75: 2; -50/+50: 1; -50/+75: 3 | 42.9% | 4 of 6 |
| Sharpe-like | -30/+50: 2; -30/+75: 5 | 71.4% | 3 of 6 |

Stability is **mixed**. Mean and Sharpe-like selection consistently favor the -30% stop and
choose +75% in five of seven folds, so the grid is not jumping arbitrarily everywhere.
Median selection is unstable: it uses four different cells and changes in four of six fold
transitions. This is evidence that the exact best cell is weakly identified at N=55 even
though the full in-sample grid makes every cell look significant. The stable feature is the
broad +50%/+75% target region, not a uniquely determined cell.

## 5. Untouched most-recent 15%: fixed cells

These eight trades were first isolated, never used for selection, and evaluated only after
the fixed rules had been frozen.

| Rule | N | Mean | 95% CI for mean | Median | Win rate | t-test p | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|---:|
| -30%/+50% | 8 | +17.41% | [-28.64%, +63.44%] | +12.21% | 50.0% | 0.4011 | 0.3125 |
| -30%/+75% | 8 | +9.85% | [-41.20%, +60.90%] | -30.90% | 37.5% | 0.6619 | 0.7422 |
| Gap-fill-only baseline | 8 | +59.00% | — | -55.42% | 37.5% | 0.5115 | 0.9453 |

Paired against the same eight baseline returns, -30%/+50% changes the mean by -41.59
percentage points (p=0.6007) and -30%/+75% changes it by -49.14 points (p=0.5287). Those
negative mean differences arise because the target truncates rare giant winners; they are
far too imprecise to establish harm. The +50% target improves the median markedly but is not
statistically resolved.

**Interpretation:** the final holdout neither confirms nor rejects either frozen cell. Calling
this a failure because p>0.05 would confuse low power with evidence of no effect; calling it
confirmation because both means are positive would ignore the wide intervals.

## 6. Shuffled-label placebo

There are 118 expiry-day gap-down paths with valid construction, 55 of which carry the
observed Gate A/VIX-rise label. The placebo randomly assigns 55 positive labels among these
118 paths. This preserves sample size, expiry-day option decay, PUT direction, chronological
splitting, and the exit machinery while breaking the association with overnight VIX rise.

### One auditable placebo, seed 20260822

| Strategy | N | Mean | Median | Win rate | t-test p |
|---|---:|---:|---:|---:|---:|
| OOF, mean-selected | 28 | +11.60% | -12.90% | 32.1% | 0.2593 |
| OOF, median-selected | 28 | +2.34% | -8.52% | 35.7% | 0.7747 |
| OOF, Sharpe-selected | 28 | +8.91% | -12.90% | 32.1% | 0.3709 |
| OOF baseline, same trades | 28 | -5.11% | -24.54% | 25.0% | 0.7914 |
| Fixed -30/+50, final 8 | 8 | +29.89% | +55.36% | 62.5% | 0.1492 |
| Fixed -30/+75, final 8 | 8 | +24.43% | +23.04% | 50.0% | 0.3028 |

This single random control produces attractive-looking fixed-cell means and medians despite
having no Gate A label information. That illustrates how untrustworthy eight-trade point
estimates are.

### 5,000 label permutations

| Reported test | Share with nominal p<0.05 by chance | Empirical probability of placebo p no larger than observed p |
|---|---:|---:|
| OOF mean-selected | 5.8% | **0.0030** |
| OOF median-selected | 4.2% | **0.0022** |
| OOF Sharpe-selected | 6.0% | **0.0020** |
| Fixed -30/+50, final 8 | 14.8% | 0.6421 |
| Fixed -30/+75, final 8 | 10.8% | 0.8098 |

At least one of the five reported tests has nominal p<0.05 in **25.1%** of shuffled-label
replications. This is the relevant warning against reading one small-sample p-value in
isolation. Conversely, the observed adaptive OOF p-values are unusually small relative to
the shuffled-label distribution (empirical probabilities 0.20%-0.30%), which strengthens
the evidence that the positive adaptive OOF result is not a routine grid-selection accident.
It does not solve the lack of incremental significance versus the baseline or the executable
premium limitation.

The elevated nominal rejection rates for the fixed eight-trade tests (10.8%-14.8%, not 5%)
also show that the t reference distribution is poorly calibrated under this chronological
selection and heavy-tailed return machinery.

## 7. Statistical power

For a two-sided one-sample t-test at 5% size and 80% power:

- **N=28 OOF trades** requires a standardized mean effect of approximately **0.55 standard
  deviations**. With observed adaptive-return standard deviations of 54-60 percentage
  points, this means only a roughly 30-33 percentage-point mean is reliably detectable.
- **N=8 untouched trades** requires approximately **1.16 standard deviations**. For the two
  fixed cells' observed standard deviations of 55 and 61 points, this corresponds to mean
  effects of roughly **64 and 71 percentage points**.

The held-out slice therefore cannot distinguish a plausible moderate edge from noise. It
can detect only an enormous effect. The OOF sample has more information but still detects
only large effects, and the paired overlay-versus-baseline difference is much noisier than
the overlay return itself.

## 8. Bottom line and next evidentiary gate

1. **Against zero:** the adaptive stop/target strategy survives chronological OOF validation
   on 28 trades under mean, median, and Sharpe-like training selection.
2. **Against the economically relevant baseline:** no incremental mean advantage is
   established; all paired p-values are 0.79-0.93.
3. **Frozen headline rules on the untouched eight:** inconclusive and severely underpowered.
4. **Grid stability:** the -30% stop with +50%/+75% target region is fairly persistent under
   mean/Sharpe selection, but the exact median-best cell jumps around.
5. **Operational claim:** unchanged. Black–Scholes proxy returns without spreads, slippage,
   brokerage, strike-tracked executable quotes, or an intraday IV path do not authorize live
   use.

The honest verdict is therefore **promising OOF evidence, but an overall underpowered test of
the overlay's incremental value**. More chronological Gate A trades or genuinely prospective
paper trades are required before promotion to an operationally validated rule.

## 9. Reproducibility

New artifacts only:

- `walkforward_gate_a_put_stop_take.py` — full analysis, reproduction assertions, placebo,
  and power calculations.
- `WALKFORWARD_GATE_A_VALIDATION.md` — this report.

Verification performed:

```text
.ml_venv/bin/python -m py_compile walkforward_gate_a_put_stop_take.py
.ml_venv/bin/python walkforward_gate_a_put_stop_take.py
```

Both completed successfully. The existing scripts and specifications were not modified.
No git commit or push was performed.
