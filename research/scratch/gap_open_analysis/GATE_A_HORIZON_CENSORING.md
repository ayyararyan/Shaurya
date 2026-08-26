# Gate A PUT: holding-horizon censoring and the theta hypothesis

**Run date:** 2026-08-22
**Task status:** **COMPLETE.** Every requested component ran: the holding-horizon scan, the
direct theta decomposition, the stop/target grid inside the censored design, the
multiple-comparisons and placebo discipline, the walk-forward, and the power statement.
A strike-tracked real-premium cross-check was added on top of the brief.

**Verdict in one line:** the theta hypothesis is **wrong in the form stated** — calendar
decay costs only about 4 percentage points of premium over the first 30 minutes — and
censoring the trade at 30 minutes **does not beat holding to close**. Stops and targets
inside the censored trade **again fail to beat the plain censored trade** once the size of
the search is accounted for. This is the same failure mode as
`WALKFORWARD_GATE_A_VALIDATION.md`, reproduced on a different exit family.

**Evidence class:** exploratory / specification check on a model-dependent return proxy.
Not identification-grade, not manuscript-ready, not executable-P&L validated. This is the
**third** exit-rule search run on the same 55 trades.

No broker, credential, network, or order path was used. No live order exists or is
authorised.

---

## 1. Statistical object and claim boundary

The unit is one chronological Gate A PUT trade: an expiry day on which India VIX rose
overnight and NIFTY gapped down, entered at 09:17. N = 55, 2021-12-02 to 2026-05-12. The
outcome is the percentage return on a theoretical ATM PUT premium.

| Object | Label | Boundary |
|---|---|---|
| Date, minute spot path, prior 15:29 close, opening IV, VIX-rise label | **Observed** | Existing local files |
| Expiry/gap-down membership, ATM strike, gap-fill minute, elapsed-minute clock | **Deterministically derived** | No fitting |
| Minute PUT premium and return | **Model-dependent proxy** | Black–Scholes, constant opening IV, ATM strike fixed at 09:17 |
| Spot-only / decay-only / cross legs | **Scenario-based** | Counterfactual repricings of the same proxy |
| Censored, stop, target and grid returns | **Scenario-based** | Mechanical exits |
| Summaries, t/Wilcoxon tests, OOF results | **Estimated** | Finite sample, N=55 |
| Shuffled-label controls | **Placebo** | VIX-rise label permuted within expiry-day gap-down paths |
| Strike-tracked minute-bar premiums and their IV | **Observed, partially hydrated** | ATM and ATM±1 only; cross-check status |
| Executable bid/ask fills, spread, slippage, brokerage | **Unidentified here** | Absent from every number below |
| Implied-volatility change inside the Black–Scholes proxy | **Unidentified by construction** | The proxy freezes IV at the opening value — see §3.3 |

The reproduction guard in `gate_a_censoring_common.py` refuses to run unless the published
in-sample numbers are recovered first: the gap-fill-only baseline at +39.0% and all nine
cells of `bs_gate_a_put_stop_take.py` within 0.06 percentage point. It passed.

Exits are located by **elapsed minutes from 09:17**, not by row index. One of the 55 paths
contains a two-minute gap in the minute tape; index-based horizons would have mislocated
its exit.

---

## 2. (A) Holding-horizon scan

Enter at 09:17, exit H minutes later. No stop, no target, no gap-fill exit.

| H | N | mean | median | win rate | sd | t | p vs 0 | Wilcoxon p | mean vs close | p vs close |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 min | 55 | +12.33% | +8.15% | 58.2% | 34.4 | +2.66 | **0.0104** | 0.0203 | −21.23pp | 0.3011 |
| 15 min | 55 | +16.62% | +7.85% | 58.2% | 43.1 | +2.86 | **0.0060** | 0.0208 | −16.93pp | 0.4055 |
| 20 min | 55 | +16.16% | +11.07% | 60.0% | 44.4 | +2.70 | **0.0093** | 0.0212 | −17.40pp | 0.3940 |
| 25 min | 55 | +11.83% | +8.18% | 60.0% | 45.6 | +1.92 | 0.0598 | 0.0938 | −21.73pp | 0.2710 |
| **30 min** | 55 | **+7.91%** | **−3.29%** | **49.1%** | 49.6 | +1.18 | **0.2419** | 0.4458 | −25.64pp | 0.1782 |
| 40 min | 55 | +9.69% | −0.39% | 49.1% | 56.0 | +1.28 | 0.2050 | 0.4974 | −23.87pp | 0.1929 |
| 45 min | 55 | +11.76% | +4.21% | 56.4% | 63.8 | +1.37 | 0.1770 | 0.4712 | −21.80pp | 0.2241 |
| 60 min | 55 | +16.65% | +8.41% | 56.4% | 73.9 | +1.67 | 0.1007 | 0.2988 | −16.91pp | 0.3316 |
| 90 min | 55 | +20.46% | +9.81% | 52.7% | 85.3 | +1.78 | 0.0808 | 0.2761 | −13.10pp | 0.4250 |
| hold to close | 55 | +33.56% | −15.50% | 49.1% | 158.9 | +1.57 | 0.1231 | 0.6744 | — | — |
| gap-fill exit (module spec incumbent) | 55 | +38.98% | −13.37% | 38.2% | 147.3 | +1.96 | 0.0549 | 0.4073 | +5.43pp | 0.4826 |

### What this says

1. **The profile is not monotone decreasing in H.** Mean return rises to a peak around
   15–20 minutes, **falls to its minimum at exactly the 30-minute mark Aryan proposed**, then
   climbs again through 45, 60 and 90 minutes to a maximum at the close. A pure theta story
   predicts a monotone decline. This is not that shape.
2. **Short horizons beat zero; they do not beat holding to close.** Every paired difference
   against hold-to-close is **negative** (−13 to −26 percentage points) and none is
   significant (p = 0.18–0.43). The mean is *lower*, not higher, when you censor.
3. **What censoring actually does is cut variance, not raise return.** Standard deviation
   falls from 158.9 at the close to 34.4 at ten minutes. That is the entire source of the
   short-horizon t-statistic. Mean/sd rises from 0.21 (close) to 0.36 (10 min) and 0.39
   (15 min). That is a real and economically meaningful property for position sizing — but
   it is a risk-adjusted argument, and none of the mean-based tests here establish it.
4. **30 minutes is the single worst choice in the 10–30 minute range**, on mean (+7.91%),
   median (−3.29%), win rate (49.1%) and significance (p=0.24). If the trade is to be
   censored at all, the data point to 15–20 minutes, not 30.

Gap-fill timing, for context: 25 of 55 days ever fill after 09:17; 12 within ten minutes,
14 within thirty. So a 30-minute censor keeps most of the population past the point where
the module spec's incumbent exit would already have closed a quarter of them.

Chronological quartile stability of the mean censored return:

| H | Q1 | Q2 | Q3 | Q4 |
|---|---:|---:|---:|---:|
| 15 min | +10.78% | +8.95% | +31.53% | +15.13% |
| 20 min | +18.44% | +7.05% | +27.43% | +11.37% |
| 30 min | +13.39% | −0.49% | +13.89% | +4.63% |
| close | +22.36% | +18.58% | +26.28% | +69.58% |

The short horizons are positive in all four quarters; hold-to-close is larger in all four.
Neither is stable enough at ~14 trades per quartile to support a claim either way.

---

## 3. (B) Direct theta diagnostic

The proxy premium is decomposed exactly, with entry values (S₀, T₀):

```
total(H)      = [P(S_H, T_H) - P(S₀,T₀)] / P(S₀,T₀)
spot_only(H)  = [P(S_H, T₀)  - P(S₀,T₀)] / P(S₀,T₀)     underlying move alone
decay_only(H) = [P(S₀,  T_H) - P(S₀,T₀)] / P(S₀,T₀)     calendar decay alone
cross(H)      = total - spot_only - decay_only          interaction (gamma x theta)
```

Maximum absolute residual across every trade and horizon: 0.0000000000 pp — exact by
construction.

### 3.1 Means, percentage points of entry premium

| H | total | spot-only | decay-only | cross | mean spot move (pts) | p spot-only | p total |
|---|---:|---:|---:|---:|---:|---:|---:|
| 10 min | +12.33% | +13.61% | **−1.33%** | +0.05% | −10.8 | 0.0049 | 0.0104 |
| 15 min | +16.62% | +18.51% | **−2.00%** | +0.12% | −13.1 | 0.0023 | 0.0060 |
| 20 min | +16.16% | +18.66% | **−2.68%** | +0.18% | −12.2 | 0.0029 | 0.0093 |
| 25 min | +11.83% | +14.97% | −3.36% | +0.23% | −8.0 | 0.0181 | 0.0598 |
| **30 min** | +7.91% | +11.65% | **−4.05%** | +0.31% | −3.6 | 0.0870 | 0.2419 |
| 40 min | +9.69% | +14.64% | −5.44% | +0.49% | −6.3 | 0.0574 | 0.2050 |
| 45 min | +11.76% | +17.26% | −6.14% | +0.65% | −6.3 | 0.0490 | 0.1770 |
| 60 min | +16.65% | +23.77% | −8.28% | +1.17% | −10.7 | 0.0202 | 0.1007 |
| 90 min | +20.46% | +31.15% | −12.73% | +2.04% | −16.6 | 0.0084 | 0.0808 |
| close | +33.56% | +67.39% | **−86.88%** | +53.05% | −10.9 | 0.0015 | 0.1231 |

Decay drag per minute is essentially constant at −0.133% to −0.141% through 90 minutes,
accelerating to −0.234% per minute averaged to the close.

### 3.2 The answer to "is theta eating it?"

**Partly — but not at the horizon Aryan named, and not through the channel he named.**

- **Over the first 30 minutes theta is trivially small.** Calendar decay costs **4.05
  percentage points** of the entry premium. Return dispersion at that horizon is 49.6
  percentage points. Theta is roughly one twelfth of one standard deviation. Only **4.7%**
  of the full session's decay (4.05 of 86.88 points) accrues in the first 30 minutes.
  **Exiting at 30 minutes to escape theta saves almost nothing, because there is almost
  nothing there to save.**
- **Over a full session theta is enormous — and still does not destroy the mean trade.**
  Decay costs 86.88 points, but the spot-only leg earns +67.39 and the convexity cross term
  earns +53.05, so the total mean is +33.56%. Held to close, the mean trade is *not* eaten
  by theta.
- **Where the theta story is genuinely right is the median trade held to close.** Median
  total at close is −15.50% against a median decay leg of −93.89%. For the typical day —
  one without a large move to monetise the gamma — full-session decay does dominate and the
  trade loses. The mean is rescued by a minority of large-move days. So Aryan's instinct is
  right about *why the median Gate A PUT trade held all day loses money*. It is wrong about
  the fix, because 30 minutes is far too early for that mechanism to have bitten.
- **The directional edge does not die after 09:45.** This is the other half of the
  hypothesis and it fails cleanly. The spot-only leg, which is the pure directional bet with
  time frozen, keeps growing: +18.66% at 20 minutes, +11.65% at 30 minutes, +23.77% at 60
  minutes, +31.15% at 90 minutes, **+67.39% at the close (p=0.0015 — the strongest of any
  horizon)**. Of the trades whose spot leg is positive at 20 minutes, 67.6% are still
  positive at the close. Holding past the 09:18–09:45 measurement window is not holding past
  the edge.

Read together, the discriminating test the brief asked for resolves as follows: the total
option return does **not** decay with H, and the spot-driven leg does **not** decay with H
either. The right description is that the trade has a **local dip around 25–40 minutes**
(the spot leg's mean favourable move shrinks from −13.1 index points at 15 minutes to −3.6
at 30 minutes and recovers afterwards), and that increasing dispersion at longer horizons —
not a decaying mean — is what destroys statistical significance.

### 3.3 Identification limit, stated plainly

The Black–Scholes construction **holds implied volatility fixed at the day's opening value**.
An IV-change component therefore does not exist in this decomposition and is **not
identified by it**. `decay_only` is pure calendar decay under a frozen volatility surface,
not "decay plus IV change". §6 measures the missing component directly from traded quotes,
and it turns out to matter more than calendar decay does at these horizons.

---

## 4. (C) Stops and targets inside the censored design

Horizons carried: **H=15** (best t-statistic against zero in the scan), **H=20** (best median
and win rate), and **H=30** (the horizon Aryan specified, carried regardless). Stops
{−15,−20,−25,−30,−40,−50%}, targets {+20,+30,+50,+75,+100%}, each family run with the
gap-fill exit off and on. Exit priority unchanged: stop, then target, then gap-fill.

**Benchmark for every variant is the pure censored baseline at its own horizon** — no stop,
no target, no gap-fill exit:

| censored baseline | N | mean | median | win rate | sd | p vs 0 | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|---:|
| H=15m | 55 | +16.62% | +7.85% | 58.2% | 43.1 | 0.0060 | 0.0208 |
| H=20m | 55 | +16.16% | +11.07% | 60.0% | 44.4 | 0.0093 | 0.0212 |
| H=30m | 55 | +7.91% | −3.29% | 49.1% | 49.6 | 0.2419 | 0.4458 |

### The single most diagnostic result in this study

| horizon | non-baseline variants | mean improvement over that horizon's censored baseline | share that improve at all | best | worst |
|---|---:|---:|---:|---:|---:|
| H=15m | 83 | **−3.27pp** | 12.0% | +0.70pp | −11.38pp |
| H=20m | 83 | **−2.01pp** | 39.8% | +2.95pp | −10.41pp |
| H=30m | 83 | **+5.42pp** | 92.8% | +11.84pp | −2.15pp |

Stops and targets **subtract value at 15 and 20 minutes** and **add value at 30 minutes**.
That asymmetry is not evidence that stops work. It is evidence that the H=30 baseline is
the weak one, and that the overlay is doing nothing more than pulling some exits forward
into the 15–25 minute region where the unaided trade was already better. The arithmetic
confirms it: the best variant found anywhere in the grid earns **+15.10%**, which is *lower*
than simply exiting at 15 minutes with no rules at all (+16.62%).

### The winner

Selected as the smallest p-value against zero across all 252 variants:

**H=30 minutes, −30% stop-loss, +30% take-profit, gap-fill exit active.**

| | N | mean | median | win rate | sd | p vs 0 | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|---:|
| winner | 55 | +15.10% | +31.80% | 63.6% | 29.4 | **0.00035** | — |

Paired, trade by trade, against every simpler rule already on the table:

| incumbent | its mean | its median | its win rate | its sd | winner − incumbent | paired p |
|---|---:|---:|---:|---:|---:|---:|
| plain censored H=15m | +16.62% | +7.85% | 58.2% | 43.1 | **−1.52pp** | 0.7301 |
| plain censored H=20m | +16.16% | +11.07% | 60.0% | 44.4 | **−1.05pp** | 0.8066 |
| plain censored H=30m | +7.91% | −3.29% | 49.1% | 49.6 | +7.19pp | 0.1521 |
| hold to close, no rules | +33.56% | −15.50% | 49.1% | 158.9 | **−18.45pp** | 0.3734 |
| gap-fill exit (module spec) | +38.98% | −13.37% | 38.2% | 147.3 | **−23.88pp** | 0.2135 |

**The winner does not beat a single incumbent on mean return.** It loses to four of the five
and beats only its own weakest-horizon baseline, at p=0.15. Its genuine distinguishing
feature is the same one the horizon scan already showed: a much lower standard deviation
(29.4 versus 43–159) and a much better median and win rate.

---

## 5. (D) Multiple comparisons and placebo discipline

**Total exit rules examined on these same 55 trades in this study: 262** — 252 in the grid
plus the 10 pure holding horizons. These 55 trades had already been searched twice before,
in `bs_gate_a_put_stop_take.py` and `walkforward_gate_a_put_stop_take.py`.

| | count |
|---|---:|
| variants with raw p vs zero < 0.05 | **229 of 252** |
| surviving Bonferroni vs zero (α/252 = 1.98×10⁻⁴) | **0** |
| surviving Benjamini–Hochberg vs zero | 220 |
| variants with raw p vs their censored baseline < 0.05 | 39 of 249 |
| surviving Bonferroni vs baseline | **0** |
| surviving Benjamini–Hochberg vs baseline | **0** |

Benjamini–Hochberg passing 220 of 252 is not reassurance. These 252 tests are near-perfectly
correlated views of one 55-trade sample; FDR control is close to meaningless here. The
Bonferroni and placebo columns are the ones to read.

### Shuffled-label placebo, 5,000 draws

Each draw reassigns the 55 Gate A labels at random among the 118 expiry-day gap-down paths.
This preserves N, expiry-day time decay, PUT direction, chronology and the entire exit
machinery, and destroys only the association with an overnight VIX rise. For every draw the
**best p-value across all 252 variants** is recorded, giving the null distribution of a
best-of-grid search (a Westfall–Young style max-statistic correction).

| test | observed best-of-grid p | placebo median | placebo 5th pct | **empirical best-of-grid p** |
|---|---:|---:|---:|---:|
| vs zero | 0.000354 | 0.060162 | 0.003975 | **0.0056** |
| vs the censored baseline | 0.002555 | 0.013798 | 0.001133 | **0.1224** |

At least one of the 252 variants reaches nominal p<0.05 against zero in **44.6%** of placebo
draws. That is the scale of the problem being corrected for.

**Reading:** against zero, the winner survives — an empirical best-of-grid p of 0.0056 is
genuinely small, and it says the Gate A PUT trade with a short censored exit really does earn
something the shuffled label does not. **Against the plain censored trade, it does not
survive**: an empirical best-of-grid p of 0.1224 means a search this large routinely produces
a "significant" improvement over the baseline by chance. The overlay has not earned its
place.

---

## 6. Cross-check: strike-tracked real premiums (secondary, clearly labelled)

The primary evidence above is the Black–Scholes proxy, as required. This section is a
cross-check against **traded minute-bar closes for the actual 09:17 strike, tracked through
the exit**, so it does not repeat the earlier data bug where the labelled "ATM" series rolled
strike mid-session. Only ATM and ATM±1 PUT files are hydrated locally, so days whose running
ATM has rolled two or more strikes drop out — and those are disproportionately the
biggest-mover days, which biases the surviving subsample towards smaller moves. These are
bar closes, not executable fills.

| H | N real | real mean | real median | real win% | real p | proxy mean (same days) | proxy median | proxy p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 min | 55 | +7.90% | +9.31% | 58.2% | 0.0344 | +12.33% | +8.15% | 0.0104 |
| 15 min | 50 | +8.98% | +4.70% | 52.0% | 0.0687 | +15.72% | +6.63% | 0.0096 |
| 20 min | 48 | +7.36% | +3.49% | 54.2% | 0.1587 | +11.63% | +5.81% | 0.0402 |
| 25 min | 46 | +4.39% | +2.29% | 50.0% | 0.4281 | +9.98% | +6.62% | 0.0828 |
| 30 min | 48 | +4.92% | −7.85% | 43.8% | 0.4274 | +10.04% | −0.31% | 0.1280 |
| 45 min | 45 | +0.50% | −5.73% | 42.2% | 0.9484 | +6.23% | +4.21% | 0.3809 |
| 60 min | 38 | −0.66% | −9.59% | 47.4% | 0.9343 | +9.55% | +8.28% | 0.2414 |
| close | 55 | −15.60% | −26.70% | 40.0% | 0.0959 | +33.56% | −15.50% | 0.1231 |

The two series agree closely on *shape* — Spearman ρ = 0.87–0.93 and 85–96% sign agreement
at every horizon — but the proxy is **systematically optimistic by 4 to 7 percentage points
at 10–60 minutes and by 49 points at the close** (paired p = 0.001–0.10).

Two channels, both pushing the same way:

| H | real | proxy | proxy rescaled to the traded entry price | entry-price level channel | IV path / other |
|---|---:|---:|---:|---:|---:|
| 10 min | +7.90% | +12.33% | +10.40% | −1.94pp | −2.49pp |
| 15 min | +8.98% | +15.72% | +13.68% | −2.04pp | −4.70pp |
| 20 min | +7.36% | +11.63% | +10.66% | −0.97pp | −3.31pp |
| 30 min | +4.92% | +10.04% | +9.04% | −1.00pp | −4.12pp |
| 60 min | −0.66% | +9.55% | +7.65% | −1.90pp | −8.31pp |
| close | −15.60% | +33.56% | +28.17% | −5.39pp | −43.77pp |

The proxy prices the 09:17 entry premium below the traded price (median ratio 0.884; median
traded entry 60.1 points versus 50.9 modelled), which mechanically inflates any percentage
return computed on it. That explains roughly a fifth to a half of the short-horizon gap. The
remainder is the intraday volatility path, which the constant-IV proxy cannot see:

| H | N | mean change in the tracked contract's own IV | median | share rising |
|---|---:|---:|---:|---:|
| 10 min | 55 | −0.33 | −0.17 | 43.6% |
| 15 min | 50 | −0.89 | −0.49 | 42.0% |
| 20 min | 48 | −0.89 | −0.91 | 39.6% |
| 30 min | 48 | −1.36 | −0.96 | 37.5% |
| 45 min | 45 | −2.12 | −1.40 | 31.1% |
| 60 min | 38 | −2.98 | −2.01 | 34.2% |

(The close row of that measurement is not reported: implied volatility on an expiring option
at 15:29 is numerically meaningless.)

**This is the one place Aryan's instinct is vindicated, in a different form.** There *is* a
real, systematic premium bleed working against a long expiry-day PUT held through the
morning — but it is **an opening implied-volatility crush (a vega loss), not calendar theta**.
It costs roughly 1 IV point by 20 minutes and 3 by an hour, and it is worth several times
more than calendar decay over the same window. It is invisible to every Black–Scholes number
in this study and in `WALKFORWARD_GATE_A_VALIDATION.md`.

Consequence: **on traded premiums, the censored trade is materially weaker than the proxy
says.** At Aryan's proposed 30 minutes it is +4.92% mean, −7.85% median, 43.8% win rate,
p=0.43 — indistinguishable from zero. Only the 10-minute horizon reaches nominal significance
(+7.90%, p=0.034), and that is on the fullest subsample rather than a hydration-thinned one.
This subsample is biased small-move, so it is a lower bound rather than a verdict.

---

## 7. (E) Walk-forward

Protocol identical to `walkforward_gate_a_put_stop_take.py`: N=55, most recent
round(55×0.15)=8 trades held out untouched (2026-01-06 to 2026-05-12), 47-trade pool, oldest
round(47×0.40)=19 seeding an expanding window, seven consecutive four-trade folds giving 28
out-of-fold trades.

**A leakage flaw was caught and removed before reporting.** An earlier pass chose the
walk-forward selection family by full-sample smallest p-value, which uses the hold-out to
design the test. Instead, all six families (3 horizons × gap-fill on/off) are run and
reported, and the multiplicity is carried into the placebo. The frozen hold-out rule is
selected using the **47-trade pool only**.

| family | criterion | OOF N | mean | median | win% | p vs 0 | baseline mean | diff | p vs baseline |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| H=15m gap-fill off | mean | 28 | +19.73% | +8.19% | 57.1% | 0.0148 | +19.35% | +0.39pp | 0.5266 |
| H=15m gap-fill off | median | 28 | +11.23% | +9.72% | 60.7% | 0.0235 | +19.35% | −8.12pp | 0.0962 |
| H=15m gap-fill off | Sharpe-like | 28 | +16.22% | +9.72% | 60.7% | 0.0236 | +19.35% | −3.13pp | 0.3034 |
| H=15m gap-fill on | mean | 28 | +19.49% | +0.03% | 50.0% | 0.0155 | +19.35% | +0.15pp | 0.9433 |
| H=15m gap-fill on | median | 28 | +9.15% | +9.72% | 57.1% | 0.0236 | +19.35% | −10.19pp | 0.0733 |
| H=15m gap-fill on | Sharpe-like | 28 | +15.98% | +4.29% | 53.6% | 0.0247 | +19.35% | −3.37pp | 0.3501 |
| H=20m gap-fill off | mean | 28 | +20.42% | +16.36% | 64.3% | 0.0184 | +18.48% | +1.95pp | 0.2436 |
| H=20m gap-fill off | median | 28 | +13.57% | +30.71% | 67.9% | 0.0218 | +18.48% | −4.91pp | 0.2940 |
| H=20m gap-fill off | Sharpe-like | 28 | +14.98% | +18.44% | 60.7% | 0.0534 | +18.48% | −3.49pp | 0.3894 |
| H=20m gap-fill on | mean | 28 | +22.64% | +16.36% | 60.7% | 0.0060 | +18.48% | +4.16pp | 0.0749 |
| H=20m gap-fill on | median | 28 | +14.31% | +23.78% | 64.3% | 0.0087 | +18.48% | −4.16pp | 0.4042 |
| H=20m gap-fill on | Sharpe-like | 28 | +13.57% | +30.71% | 60.7% | 0.0163 | +18.48% | −4.91pp | 0.3481 |
| H=30m gap-fill off | mean | 28 | +16.15% | −0.31% | 50.0% | 0.0777 | +6.28% | +9.87pp | 0.1030 |
| H=30m gap-fill off | median | 28 | +14.07% | +31.63% | 67.9% | 0.0332 | +6.28% | +7.79pp | 0.2610 |
| H=30m gap-fill off | Sharpe-like | 28 | +14.82% | +31.63% | 67.9% | 0.0181 | +6.28% | +8.53pp | 0.2224 |
| **H=30m gap-fill on** | **mean** | 28 | **+20.03%** | +0.00% | 46.4% | **0.0323** | +6.28% | **+13.74pp** | **0.0337** |
| H=30m gap-fill on | median | 28 | +14.44% | +31.14% | 60.7% | 0.0146 | +6.28% | +8.16pp | 0.2362 |
| H=30m gap-fill on | Sharpe-like | 28 | +13.73% | +27.10% | 60.7% | 0.0172 | +6.28% | +7.45pp | 0.2885 |

**Against zero the censored trade survives out of fold** in 16 of 18 configurations at
nominal 5% (p = 0.0060–0.0534; the two that miss are H=20m gap-fill off Sharpe-selected at
0.0534 and H=30m gap-fill off mean-selected at 0.0777). That is a genuine replication of the
earlier walk-forward's first finding, now on the censored family.

**Against the censored baseline, one configuration out of 18 reaches nominal significance**
(H=30, gap-fill on, mean-selected: +13.74pp, p=0.0337). It fails Bonferroni across the 18
configurations (threshold 0.0028), and — the binding test — the walk-forward placebo:

| | value |
|---|---:|
| observed best OOF p versus baseline | 0.0337 |
| placebo best OOF p versus baseline, median | 0.0630 |
| placebo best OOF p versus baseline, 5th percentile | 0.0081 |
| at least one of 18 configurations beats baseline at p<0.05 by chance | **40.7% of draws** |
| **empirical p for the OOF incremental edge** | **0.2809** |

5,000 shuffled-label draws, each replicating the whole procedure (six families, three
criteria, best-of-set). **The incremental out-of-fold edge is not established.**

Note also that 8 of the 18 configurations have a *negative* mean difference against the
censored baseline, and **every one of the six differences larger than +5pp comes from the
single H=30 family** — the horizon whose unaided baseline is the weak one. Strip that family
out and the remaining twelve configurations average −2.9pp against their own baselines. The
one nominally significant positive is the tail of a distribution centred near zero.

### Untouched most-recent hold-out

Rule frozen on the 47-trade pool only: H=30m, −30% stop, +30% target, gap-fill on (pool
p = 0.00041) — the same rule the full sample picks, which is at least reassuring about
selection stability.

| | N | mean | median | win rate | p vs 0 | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|
| frozen rule | 8 | +12.28% | +34.90% | 62.5% | 0.3955 | 0.1953 |
| censored H=30m baseline, same trades | 8 | −4.20% | −28.60% | 37.5% | 0.8787 | — |
| paired difference | 8 | +16.48pp | — | — | 0.4222 | — |

Directionally encouraging, statistically empty. See §8.

---

## 8. (F) Power — what N=55 and N=8 can and cannot detect

For a two-sided one-sample t-test at 5% size and 80% power:

| N | context | required standardized effect |
|---:|---|---:|
| 55 | full in-sample | 0.385 sd |
| 28 | out-of-fold | 0.549 sd |
| 8 | untouched hold-out | 1.156 sd |

Translated into percentage points of return:

| quantity | sd | detectable at N=55 | at N=28 | at N=8 |
|---|---:|---:|---:|---:|
| censored return, H=15m | 43.1pp | 16.6pp | 23.7pp | 49.8pp |
| censored return, H=20m | 44.4pp | 17.1pp | 24.4pp | 51.4pp |
| censored return, H=30m | 49.6pp | 19.1pp | 27.2pp | 57.3pp |
| incremental effect of an overlay, H=15m (median paired sd 18.6pp) | 18.6pp | 7.1pp | 10.2pp | — |
| incremental effect of an overlay, H=20m (23.7pp) | 23.7pp | 9.1pp | 13.0pp | — |
| incremental effect of an overlay, H=30m (33.0pp) | 33.0pp | 12.7pp | 18.1pp | — |

**What this can detect:** an overlay that adds more than about 7–13 percentage points of
mean return at N=55 would be visible. None does, at H=15 or H=20, where the average overlay
*subtracts* 2–3 points. That is an informative null, not merely an absence of evidence.

**What this cannot detect:** anything smaller. The H=30 overlay's apparent +13.74pp
out-of-fold gain sits *below* the 18.1pp needed for 80% power at N=28 — meaning that if the
effect were real and that size, this test would miss it more often than not, and a
"significant" reading at that magnitude is as likely to be a lucky draw as a true signal.
The eight-trade hold-out requires roughly a 57 percentage-point mean to reach 80% power. It
cannot distinguish a good rule from a bad one and should not be quoted either way.

**What is genuinely underpowered rather than refuted:** the comparison of short horizons
against hold-to-close. Hold-to-close has sd 158.9 and the paired differences are of the same
order, so distinguishing a −20pp mean difference from zero at N=55 is hopeless. The claim
"censoring does not beat holding to close" is therefore **"not shown to beat"**, not "shown
not to beat". What *is* established is that censoring does not beat it *in the observed
mean* — the point estimate is negative, so there is no positive result being missed for lack
of power.

---

## 9. Bottom line

1. **Theta hypothesis: partly right, but not where it was aimed.** Calendar decay over the
   first 30 minutes is −4.05% of premium — 4.7% of the session's total decay, one twelfth of
   a standard deviation. Exiting at 30 minutes to escape theta saves essentially nothing.
   Theta *does* dominate the **median** trade held to close (−93.89% decay against a −15.50%
   total), so the instinct is correct about the all-day trade. And there is a real
   time-related bleed at short horizons — but §6 shows it is an **opening IV crush**, not
   calendar theta, and it is invisible to the Black–Scholes machinery used throughout this
   project.
2. **The directional edge does not die after 09:45.** The spot-only leg keeps growing to
   +67.4% at the close (p=0.0015, its strongest reading). The 09:18–09:45 measurement window
   was where the edge was *measured*, not where it *ends*.
3. **Censoring at 30 minutes does not beat holding to close.** It is the worst choice in the
   10–30 minute range (+7.91%, median −3.29%, p=0.24). Fifteen to twenty minutes is better
   (+16.6%, p=0.006), but still with a *lower* mean than hold-to-close and a paired
   difference of −17pp at p=0.41. What censoring buys is a fourfold cut in variance, which is
   worth having for sizing but is not what was hypothesised.
4. **Stops and targets do not add anything on top of the censored trade.** They subtract at
   H=15 and H=20 (mean −3.27pp and −2.01pp; only 12% and 40% of variants improve at all).
   They appear to add at H=30 only because H=30 is the weak baseline — and the best variant
   anywhere in the 252-cell grid (+15.10%) still earns less than simply exiting at 15 minutes
   with no rules (+16.62%).
5. **Placebo and walk-forward: beats zero, does not beat the baseline.** Empirical
   best-of-grid p is 0.0056 against zero and 0.1224 against the censored baseline. Out of
   fold, 16 of 18 configurations beat zero; the single configuration that beats the baseline
   has an empirical p of 0.2809 once the search is replicated under shuffled labels. Zero
   variants survive Bonferroni on either test.

**This is another exit-rule search that beats zero and does not beat the baseline.** It is
the third such result on these 55 trades, and it is the same result each time. The
persistent, replicated finding across all three passes is not any exit rule — it is that
**the Gate A PUT population itself carries a positive expected proxy return that shuffled
labels do not reproduce**. Every attempt to improve on the simplest possible version of the
trade has failed, and the failures are now numerous and consistent enough that the sensible
reading is that the exit rule is not where the remaining value is.

**Operational claim: unchanged.** Nothing here authorises live use. The strike-tracked
cross-check in §6 makes the case *weaker* than the proxy suggested, not stronger, and still
excludes spread, slippage and brokerage.

---

## 10. Reproducibility

New artifacts only. No existing script, specification, or report was modified. No git commit
or push was performed.

| File | Contents |
|---|---|
| `gate_a_censoring_common.py` | Path construction, counterfactual premium legs, elapsed-minute horizon exits, reproduction guard |
| `gate_a_horizon_scan.py` | §2 holding-horizon scan |
| `gate_a_theta_decomposition.py` | §3 theta decomposition |
| `gate_a_censored_stops.py` | §4, §5, §7, §8 grid, placebo, walk-forward, power |
| `gate_a_real_premium_crosscheck.py` | §6 strike-tracked real-premium cross-check |
| `gate_a_censoring_paths.pkl` | Cached path construction |
| `gate_a_censored_stops_results.json` | Machine-readable results |
| `gate_a_real_premium_crosscheck.csv` | Per-day real versus proxy returns and IV changes |
| `GATE_A_HORIZON_CENSORING.md` | This report |

Verification performed:

```text
.ml_venv/bin/python -m py_compile gate_a_censoring_common.py gate_a_horizon_scan.py \
    gate_a_theta_decomposition.py gate_a_censored_stops.py gate_a_real_premium_crosscheck.py
.ml_venv/bin/python gate_a_censoring_common.py          # reproduction guard PASSED
.ml_venv/bin/python gate_a_horizon_scan.py
.ml_venv/bin/python gate_a_theta_decomposition.py
.ml_venv/bin/python gate_a_censored_stops.py
.ml_venv/bin/python gate_a_real_premium_crosscheck.py
```

All completed successfully. Placebo seeds: 20260822 (in-sample grid), 20260823
(walk-forward), 5,000 draws each.
