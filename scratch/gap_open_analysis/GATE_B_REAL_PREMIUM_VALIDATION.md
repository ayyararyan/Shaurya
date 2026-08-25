# Gate B reversal CALL: validation on real traded option premiums

**Run date:** 2026-08-23
**Task status:** **COMPLETE.** Every requested component ran: entry-timing distribution (A),
the implied-volatility path at and after entry (B), the real-premium hold-to-close headline
test (C), the full exit grid on real premiums (D), multiple-comparisons and shuffled-label
placebo discipline (E), power (F), and a costed overlay (G).

**Verdict in one line:** on real traded prices, Gate B held to the close **loses 6.1% of
premium per trade on average and 13.5% at the median**, against the +1.8% the Black-Scholes
proxy reported; **not one of the 39 exit rules tested produces a positive mean return**;
and net of costs the trade is worse still. **Gate B cannot be shown to make money on real
prices.** It is **not** fit to be armed with real money on Monday.

**Evidence class:** exploratory / specification check, now on **observed traded prices**
rather than a model-dependent proxy. Not identification-grade and not manuscript-ready, but
materially stronger than everything Gate B has been resting on, because the premium series
is measured rather than modelled and coverage is complete.

No broker, credential, exchange network, or order path was used. No live order exists or is
authorised.

---

## 0. Bottom line for the Monday decision

| question | answer |
|---|---|
| On real traded prices, net of costs, is Gate B fit to be armed with real money on Monday? | **No.** |
| Is that "no" a demonstrated loss, or an absence of evidence? | **Neither, precisely.** The point estimate is negative under **every one of 39 exit rules**, but N=33 cannot resolve a mean smaller than ±23.8 percentage points. The honest statement is the one the brief asked for: **Gate B cannot be shown to make money on real prices.** |
| Did the real-premium test overturn a positive result? | **No — there was never a positive result to overturn.** `GAP_FILL_SIGNAL_MODULE_SPEC.md` already recorded hold-to-close at p=0.82 and called it "not a proven positive edge… the least-bad option among a wide grid". Real prices move that null from +1.8% to −6.1%. |
| Does the gate's own conditioning earn anything? | **No.** The Gate-B hold-to-close mean sits at the **37th percentile** of 5,000 shuffled-label placebo draws. Randomly chosen non-expiry gap-down fill days do about as well. |

---

## 1. Statistical object and claim boundary

The unit is one chronological Gate-B trade: a non-expiry day on which India VIX rose
overnight, NIFTY gapped down, the opening IV bucket was mid (14–18%), and the gap filled at
some minute strictly after 09:17. Entry is one ATM NIFTY CALL at the fill minute, nearest
weekly expiry. **N = 33 fires**, 2021-09-08 to 2026-01-29, out of 56 qualifying mid-IV days.

| Object | Label | Boundary |
|---|---|---|
| Date, minute spot path, prior 15:29 close, opening IV, VIX-rise label, IV bucket | **Observed** | Existing local files |
| Gate membership, gap-fill minute, entry strike, elapsed-minute clock | **Deterministically derived** | No fitting |
| **Minute CALL premium and its implied volatility, for the tracked entry strike** | **Observed** | Dhan one-minute bar closes, strike held fixed and looked up by absolute value |
| Black-Scholes comparison premium | **Model-dependent proxy** | Constant opening IV, exactly as `bs_gap_fill_pnl.py` |
| Volatility leg of the trade | **Scenario-based on observed inputs** | Same contract repriced with observed IV vs IV frozen at entry |
| Clock, horizon, stop, target and cross returns | **Scenario-based** | Mechanical exits on the traded series |
| Summaries, t/Wilcoxon tests | **Estimated** | Finite sample, N=33 |
| Shuffled-label controls | **Placebo** | Gate-B membership permuted within non-expiry gap-down fill days |
| Bid–ask spread and the executable fill | **Unidentified here** | No order book in the dataset; §7 bounds it and states an explicit assumption |
| Slippage beyond the stated spread, partial fills, queue position | **Unidentified here** | Absent from every number below |

**These are one-minute bar closes, not executable fills.** That caveat is priced in §7 and
it is the main remaining gap between these numbers and a live P&L.

### 1.1 The defect being chased, confirmed by direct reading

`bs_gap_fill_pnl.py` line 106 prices every point on the path with
`bs_call(float(r["spot"]), K, T, RISK_FREE_RATE, opening_iv)`. `opening_iv` is set once per
day from `day["opening_iv"]/100.0` and never updated. **Implied volatility is frozen at the
day's opening value for the entire session**, so that construction is structurally incapable
of showing any intraday volatility change. Confirmed by reading the file, and re-confirmed
numerically: a rebuilt constant-IV series reproduces its published numbers exactly (§1.2).

### 1.2 Reproduction guard

`gate_b_common.py` refuses to run unless the published Gate-B artifacts are recovered first:

* the fire set — all 33 dates, entry clocks, strikes and Black-Scholes entry premiums match
  `bs_gap_fill_trades.csv` exactly;
* all three published trailing-stop means from `bs_gap_fill_pnl.py`, within 0.06pp;
* every fixed-clock figure quoted in `GAP_FILL_SIGNAL_MODULE_SPEC.md` — 10:00 −11.9%/p=.013,
  10:30 −13.2%/.006, 11:00 −10.9%/.018, 12:00 −13.1%/.045, 13:00 −13.2%/.044, 14:00
  −7.7%/.282 — and hold-to-close at +1.8%. **All recovered to the decimal.**

That last check also resolved a convention question. The spec's clock figures reproduce
**only** under a *traded-only* convention — a day whose gap fills after the exit clock is
simply not traded. That is therefore the convention the published Gate-B evidence uses, and
§5.2 reports the real-premium comparison under it, like for like.

### 1.3 Data: why coverage is complete this time

The Gate-A cross-check in `GATE_A_HORIZON_CENSORING.md` §6 was thinned to 38–55 of 55 days
because only ATM and ATM±1 option files were hydrated locally, so the tracked strike fell out
of the cache whenever the market moved. That biased its surviving subsample toward small
moves.

For this study the **full ATM−10 … ATM+10 CALL series was staged from Drive** (1,386 files,
10.4 million minute bars, via the rclone Drive-API path because the File-Provider mount
deadlocks on read). The entry strike is therefore quoted through ±500 index points of
movement, which covers every intraday move in the sample.

> **Coverage: 33 of 33 fires priced on real traded premiums, at entry and at 15:29. Nothing
> is missing, so nothing can be missing non-randomly.** This is the single biggest
> methodological improvement over the Gate-A cross-check and it is why this result can be
> read as a verdict rather than as a lower bound.

**Independent validation of the construction.** The Black-Scholes entry premium computed at
the day's opening IV lands within 2.2% of the traded entry premium at the median (median
ratio 1.022, IQR 0.992–1.066; median traded entry 101.2 points, median modelled 101.1). That
agreement confirms the strike, the weekly expiry and the volatility level are all aligned
with the contract actually quoted. The single largest discrepancy, 2024-12-31 at 25.6%, is
not a data error: that trade enters at 14:03, by which time the contract's own IV had risen
from the 17.18 opening value to 23.40; repricing at the observed IV recovers the traded price
to within 1.3%. The outlier is the defect, not a bug.

---

## 2. (A) Gap-fill entry timing

This determines how much of the opening volatility crush the trade is exposed to, so it was
measured rather than assumed.

| statistic | entry clock | minutes after the 09:15 open |
|---|---|---:|
| minimum | **09:18** | 3 |
| Q1 | **09:19** | 4 |
| **median** | **09:43** | **28** |
| Q3 | **10:09** | 54 |
| maximum | **14:04** | 289 |
| mean | 10:15 | 60 |

Cumulative:

| by | fires | share |
|---|---:|---:|
| 09:20 | 10/33 | **30.3%** |
| 09:30 | 15/33 | **45.5%** |
| 09:45 | 18/33 | 54.5% |
| 10:00 | 21/33 | 63.6% |
| 10:30 | 25/33 | 75.8% |
| 11:00 | 28/33 | 84.8% |
| 13:00 | 30/33 | 90.9% |
| 14:30 | 33/33 | 100% |

Full list: 09:18 ×7, 09:19 ×3, 09:21, 09:22, 09:25, 09:28, 09:30, 09:31, 09:43, 09:44, 09:49,
09:53, 09:59, 10:03, 10:04, 10:05, 10:09, 10:33, 10:42, 10:50, 12:50, 12:58, 13:03, 14:03,
14:04.

**Reading:** the distribution is strongly bimodal and front-loaded. Nearly a third of fires
occur within five minutes of the open and 45% within fifteen; a thin tail runs to mid
afternoon. Because the gap-fill condition is checked continuously from 09:18, a shallow gap
fills almost immediately — the seven 09:18 entries are days where the gap was essentially
closed at the first opportunity.

This matters for the next section, and the answer is **not** the one the brief anticipated:
the median entry at 09:43 sits *after* most of the opening crush, so Gate B avoids the worst
of the channel that damaged Gate A. It is hit by a different and larger one instead.

---

## 3. (B) The implied-volatility path at and after entry

All figures are the **observed implied volatility of the actual contract bought**, from the
minute tape. None of it exists inside the Black-Scholes series the project has been using.

### 3.1 Session shape of at-the-money implied volatility on these 33 days

Running-ATM contract, so this does not depend on the tracked strike surviving. 33 days at
every clock.

| clock | mean ATM IV | median | vs 09:17 |
|---|---:|---:|---:|
| 09:15 | 16.03 | 15.77 | +0.28 |
| 09:17 | 15.75 | 15.58 | — |
| 09:20 | 15.41 | 15.52 | −0.34 |
| 09:25 | 15.17 | 15.15 | −0.58 |
| 09:30 | 15.12 | 15.18 | −0.63 |
| 09:45 | 15.07 | 15.05 | −0.68 |
| 10:00 | 14.99 | 14.97 | −0.76 |
| 11:00 | 15.01 | 14.92 | −0.74 |
| 12:00 | 14.90 | 14.71 | −0.85 |
| 13:00 | 14.81 | 14.85 | −0.94 |
| 14:00 | 14.61 | 14.63 | −1.14 |
| 15:00 | 14.05 | 13.68 | −1.70 |
| 15:25 | 13.28 | 13.03 | **−2.47** |

The opening crush is real and visible — about **0.9 vol points lost between 09:15 and
09:30** — but it is only a third of the day's total decline. The surface keeps grinding down
all session and then falls away sharply after 14:00.

### 3.2 The traded contract's own implied volatility, from entry

| offset from entry | N | mean IV | mean ΔIV | median ΔIV | share rising |
|---|---:|---:|---:|---:|---:|
| entry | 33 | 15.22 | — | — | — |
| +10 min | 33 | 15.09 | −0.13 | −0.02 | 48.5% |
| +20 min | 33 | 15.11 | −0.11 | −0.00 | 48.5% |
| +30 min | 33 | 14.97 | −0.26 | −0.31 | 42.4% |
| +45 min | 33 | 14.86 | −0.36 | −0.26 | 30.3% |
| +60 min | 33 | 14.86 | −0.36 | −0.48 | 33.3% |
| +90 min | 31 | 14.63 | −0.35 | −0.50 | 29.0% |
| +120 min | 31 | 14.64 | −0.34 | −0.46 | 25.8% |
| **close** | 33 | **13.69** | **−1.54** | **−2.03** | **18.2%** |

Entry-to-close change: **−1.54 vol points, t = −4.67, p = 0.0001.** Only 6 of 33 trades see
their contract's implied volatility rise between entry and exit.

### 3.3 Does Gate B buy into an inflated IV that then deflates, and what does it cost?

**Yes — but not mainly through the opening crush, and it costs about 8% of the premium.**

Answering the brief's question directly: the contract bought at entry carries a mean implied
volatility of **15.22**, against a mean *opening* IV of 15.92 for the same days. So Gate B
buys **after** roughly 0.7 vol points of the opening crush have already been given up by
someone else. The median entry at 09:43 is late enough to dodge most of that channel.

What it does not dodge is the rest of the day. Repricing the tracked contract at its exit
minute with (a) the observed implied volatility of that minute and (b) implied volatility
frozen at its entry value — both legs using observed spot and observed time to expiry, so the
only difference is the volatility path:

| quantity | mean | median |
|---|---:|---:|
| entry-to-close IV change | −1.54 vol points | −2.03 vol points |
| **volatility leg, premium points** | **−11.65** | **−8.90** |
| **volatility leg, % of the traded entry premium** | **−8.30%** | **−9.54%** |

t = −5.41, **p < 0.0001**, negative on **81.8%** of trades. (Sanity check on the repricing:
Black-Scholes at the observed entry IV misprices the traded entry premium by a median of
−2.26%, IQR −3.10% to −1.70% — small relative to the effect being measured.)

**So the volatility path costs Gate B 8.3% of the entry premium on average, it is highly
significant, and it is invisible to every Black-Scholes number in this project.** It is
almost exactly the size of the entire real-versus-proxy gap measured in §4 (−7.84pp), which
is what one would expect if it is the whole story — and §4 shows it is.

**Correction to the brief's premise.** The brief expected the *opening* IV crush to hit Gate
B harder than Gate A. It does not: Gate B's median entry is late enough to miss most of it.
The defect reaches Gate B through a different door — Gate B's incumbent exit is *hold to the
close*, which means carrying a weekly option through the full-session volatility decline,
including the steep drop after 14:00. Gate A's censored variants held for 10–60 minutes and
lost 0.3–3.0 vol points; Gate B holds for the rest of the day and loses 1.5 vol points on a
contract with far more vega, worth 8.3% of premium. **Same defect, different channel, larger
total bill.**

---

## 4. (C) Hold to close on real premiums versus the Black-Scholes proxy

The headline test. Same 33 trades, same entry, same exit, two premium series.

| series | N | mean | median | win rate | sd | p vs 0 | Wilcoxon p |
|---|---:|---:|---:|---:|---:|---:|---:|
| **REAL traded premium, hold to close** | **33** | **−6.08%** | **−13.46%** | **39.4%** | 47.3 | **0.4660** | 0.3483 |
| Black-Scholes proxy, same 33 days | 33 | **+1.77%** | −4.56% | 42.4% | 44.1 | 0.8194 | 1.0000 |

* **Paired real minus proxy: −7.84 percentage points, median −8.90pp, t = −5.23, p < 0.0001.**
* Agreement on shape: Spearman ρ = **+0.985**, same-sign **97.0%**. The two series rank the
  days almost identically; the proxy is simply and consistently too generous.

The proxy's +1.77% / p=0.8194 reproduces the module spec's published "+1.8%, p=0.82" exactly,
so this is a like-for-like replacement of the number Gate B has been resting on.

### 4.1 Where the 7.84 points go

| channel | contribution |
|---|---:|
| entry-price level error (proxy misprices the entry premium) | **−0.08pp** |
| **implied-volatility path and everything else** | **−7.76pp** |

Unlike the Gate-A cross-check — where the proxy underpriced the entry premium by 11.6% and
that mechanical error explained a fifth to a half of the gap — here the proxy prices the
entry almost perfectly (median BS/real ratio 1.022). **Essentially the entire discrepancy is
the volatility path**, and its size (−7.76pp) matches the directly measured volatility leg
(−8.30%) to within half a percentage point. Two independent measurements of the same thing
agree.

### 4.2 The result split by whether the gate was directionally right

| subset | N | mean | median | win rate | p vs 0 |
|---|---:|---:|---:|---:|---:|
| REAL, true reversal days | 28 | **−2.11%** | −12.16% | 39.3% | 0.8132 |
| REAL, false fires | 5 | −28.32% | −34.03% | 40.0% | 0.2703 |
| BS proxy, true reversal days | 28 | +5.96% | −4.41% | 42.9% | 0.4572 |
| BS proxy, false fires | 5 | −21.73% | −20.73% | 40.0% | 0.4188 |

**This is the most important row in the study.** Gate B's headline claim is an 84.8%
directional hit rate (28 true reversals out of 33 fires). On those 28 days where the gate was
*right about the direction*, the CALL still **loses 2.11% on average and 12.16% at the
median, and wins only 39.3% of the time.** Being right about direction is not enough to
overcome the volatility decay and the decay of a held option. The 84.8% number is a statement
about the path of the index, not about the P&L of the trade.

### 4.3 Chronological stability

| quartile | dates | N | mean | median | win rate |
|---|---|---:|---:|---:|---:|
| Q1 | 2021-09-08 … 2023-01-03 | 9 | +10.84% | −6.47% | 44.4% |
| Q2 | 2023-01-04 … 2024-02-20 | 8 | −27.38% | −43.26% | 25.0% |
| Q3 | 2024-03-06 … 2024-09-25 | 8 | +5.08% | +7.06% | 62.5% |
| Q4 | 2024-10-29 … 2026-01-29 | 8 | −14.97% | −22.81% | 25.0% |

No stability whatsoever, and the recent history is the worse half:

| recent slice | N | mean | median | win rate | p |
|---|---:|---:|---:|---:|---:|
| last 8 trades (2024-10-29 →) | 8 | −14.97% | −22.81% | 25.0% | 0.1737 |
| last 12 trades (2024-07-10 →) | 12 | −18.63% | −22.81% | 33.3% | 0.0581 |
| 2025 onward | 4 | −19.40% | −28.19% | 25.0% | — |

At N=8 and N=12 none of this is conclusive, and it should not be quoted as though it were.
It is noted because the decision on the table is to start trading this on Monday, and the
most recent evidence available is the least encouraging part of the sample.

---

## 5. (D) The exit grid on real premiums

39 exit rules, every one valued on the traded series, with stops and targets evaluated on the
same series they are valued on so each rule is executable within it. The benchmark for every
variant is **the plain hold-to-close trade on real premiums** — Gate B's own incumbent exit.

Families: 7 fixed-clock exits + hold-to-close; 7 elapsed-time horizons measured from the fill
(added so Gate B is not judged only on absolute clocks — because fills range from 09:18 to
14:04, a fixed clock is a different holding period on every trade); 4 stop-losses; 4
take-profits; the 4×4 stop-by-target cross.

### 5.1 Full grid

| variant | N | mean | median | win% | p vs 0 | Δ vs baseline | p vs baseline | BS mean | BS p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| clock exit 10:00 | 33 | −10.76% | −12.63% | 24.2% | 0.0251 | −4.68pp | 0.4943 | −6.10% | 0.2086 |
| clock exit 10:30 | 33 | −12.51% | −15.34% | 30.3% | 0.0033 | −6.44pp | 0.3337 | −9.32% | 0.0337 |
| clock exit 11:00 | 33 | −9.40% | −7.75% | 30.3% | 0.0273 | −3.32pp | 0.6376 | −7.04% | 0.0985 |
| clock exit 12:00 | 33 | −11.14% | −10.87% | 30.3% | 0.0551 | −5.06pp | 0.4329 | −8.91% | 0.1249 |
| clock exit 13:00 | 33 | −12.47% | −13.76% | 33.3% | 0.0461 | −6.39pp | 0.3050 | −10.46% | 0.0870 |
| clock exit 14:00 | 33 | −8.43% | −10.53% | 39.4% | 0.2505 | −2.36pp | 0.6552 | −6.27% | 0.3563 |
| clock exit 15:00 | 33 | −5.07% | −17.80% | 39.4% | 0.5519 | +1.01pp | 0.8047 | −1.75% | 0.8110 |
| **hold to close (baseline)** | **33** | **−6.08%** | **−13.46%** | **39.4%** | **0.4660** | — | — | **+1.77%** | **0.8194** |
| hold 10m after fill | 33 | −6.10% | −3.42% | 36.4% | **0.0117** | −0.02pp | 0.9983 | −5.35% | 0.0187 |
| hold 20m after fill | 33 | −10.83% | −10.80% | 24.2% | **0.0002** | −4.75pp | 0.5595 | −10.22% | 0.0009 |
| hold 30m after fill | 33 | −11.00% | −9.83% | 30.3% | **0.0002** | −4.92pp | 0.5181 | −9.53% | 0.0027 |
| hold 45m after fill | 33 | −9.25% | −11.65% | 27.3% | 0.0071 | −3.17pp | 0.6687 | −7.14% | 0.0391 |
| hold 60m after fill | 33 | −7.92% | −11.14% | 21.2% | 0.0313 | −1.84pp | 0.7907 | −5.94% | 0.1166 |
| hold 90m after fill | 33 | −11.78% | −12.01% | 24.2% | 0.0100 | −5.70pp | 0.3937 | −9.16% | 0.0465 |
| hold 120m after fill | 33 | −13.92% | −10.87% | 21.2% | 0.0037 | −7.84pp | 0.2619 | −11.21% | 0.0202 |
| stop −20% | 33 | −9.10% | −21.01% | 18.2% | 0.0908 | −3.03pp | 0.6493 | −5.71% | 0.3124 |
| stop −30% | 33 | −10.68% | −30.29% | 27.3% | 0.0794 | −4.60pp | 0.4699 | −4.41% | 0.4934 |
| stop −40% | 33 | −7.60% | −16.88% | 33.3% | 0.2838 | −1.52pp | 0.7501 | −0.62% | 0.9302 |
| stop −50% | 33 | −9.31% | −13.97% | 36.4% | 0.2194 | −3.24pp | 0.4877 | −2.98% | 0.6931 |
| target +30% | 33 | −9.74% | −10.87% | 42.4% | 0.1541 | −3.66pp | 0.3239 | −3.66% | 0.5440 |
| target +50% | 33 | −7.15% | −10.87% | 42.4% | 0.3409 | −1.08pp | 0.7290 | −1.43% | 0.8338 |
| **target +75%** | 33 | **−2.17%** | −10.87% | 42.4% | 0.8054 | **+3.91pp** | 0.2480 | +2.43% | 0.7583 |
| target +100% | 33 | −2.93% | −13.46% | 39.4% | 0.7534 | +3.15pp | **0.1053** | +2.79% | 0.7296 |
| stop −20% / target +30% | 33 | −10.49% | −20.88% | 21.2% | 0.0115 | −4.41pp | 0.5460 | −8.58% | 0.0329 |
| stop −20% / target +50% | 33 | −8.89% | −20.88% | 21.2% | 0.0638 | −2.81pp | 0.6988 | −8.12% | 0.0777 |
| stop −20% / target +75% | 33 | −6.31% | −20.88% | 21.2% | 0.2789 | −0.23pp | 0.9753 | −6.06% | 0.2697 |
| stop −20% / target +100% | 33 | −9.10% | −21.01% | 18.2% | 0.0908 | −3.03pp | 0.6493 | −5.71% | 0.3124 |
| stop −30% / target +30% | 33 | −11.78% | −30.25% | 30.3% | 0.0184 | −5.70pp | 0.4190 | −7.92% | 0.1047 |
| stop −30% / target +50% | 33 | −10.19% | −30.25% | 30.3% | 0.0660 | −4.12pp | 0.5571 | −6.57% | 0.2424 |
| stop −30% / target +75% | 33 | −7.62% | −30.25% | 30.3% | 0.2388 | −1.54pp | 0.8307 | −4.02% | 0.5381 |
| stop −30% / target +100% | 33 | −10.68% | −30.29% | 27.3% | 0.0794 | −4.60pp | 0.4699 | −4.41% | 0.4934 |
| stop −40% / target +30% | 33 | −10.43% | −13.97% | 36.4% | 0.0680 | −4.35pp | 0.4511 | −4.95% | 0.3615 |
| stop −40% / target +50% | 33 | −7.70% | −13.97% | 36.4% | 0.2333 | −1.62pp | 0.7723 | −3.25% | 0.5992 |
| stop −40% / target +75% | 33 | −3.39% | −13.97% | 36.4% | 0.6614 | +2.68pp | 0.6467 | +0.05% | 0.9950 |
| stop −40% / target +100% | 33 | −4.95% | −16.88% | 33.3% | 0.5380 | +1.13pp | 0.8267 | +0.41% | 0.9559 |
| stop −50% / target +30% | 33 | −11.41% | −13.46% | 39.4% | 0.0744 | −5.33pp | 0.3522 | −7.31% | 0.2259 |
| stop −50% / target +50% | 33 | −9.42% | −13.46% | 39.4% | 0.1785 | −3.34pp | 0.5450 | −5.61% | 0.4050 |
| stop −50% / target +75% | 33 | −5.11% | −13.46% | 39.4% | 0.5341 | +0.97pp | 0.8671 | −2.31% | 0.7639 |
| stop −50% / target +100% | 33 | −6.67% | −13.97% | 36.4% | 0.4322 | −0.59pp | 0.9072 | −1.95% | 0.8053 |

### The single most diagnostic fact in this study

> **Zero of the 39 variants has a positive mean return on real traded premiums.**

Not the incumbent, not any clock exit, not any holding horizon, not any stop, not any target,
not any of the sixteen crosses. The best of all 39 is a +75% take-profit at **−2.17%**, which
is still a loss and is nowhere near significant (p=0.81). Across the 38 non-baseline
variants the mean change against the baseline is **−2.70pp**, and only **15.8%** improve on
it at all.

Thirteen variants reach nominal p<0.05 against zero. **All thirteen are significant
losses.** The smallest p-value in the entire grid — "hold 30 minutes after fill", p=0.0002 —
identifies the most reliably *loss-making* rule available. Any selection procedure that picks
the smallest p-value, as the Gate-A studies did, would here hand back a rule that loses 11%
per trade with high confidence. That is worth recording as a methodological trap in this
project's own toolkit.

### 5.2 Clock exits under the module spec's own convention

Reported separately because it reproduces the published Black-Scholes numbers exactly, so
the real-versus-proxy comparison is like for like. Here a day whose gap fills after the exit
clock is simply not traded, so N falls.

| variant | N | REAL mean | median | win% | p vs 0 | BS mean | BS p | published in spec |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| clock exit 10:00 | 21 | **−14.41%** | −17.63% | 14.3% | 0.0008 | −11.92% | 0.0126 | −11.9 / .013 ✓ |
| clock exit 10:30 | 25 | **−15.13%** | −16.34% | 24.0% | 0.0009 | −13.23% | 0.0059 | −13.2 / .006 ✓ |
| clock exit 11:00 | 28 | **−12.79%** | −8.81% | 25.0% | 0.0062 | −10.91% | 0.0177 | −10.9 / .018 ✓ |
| clock exit 12:00 | 28 | **−14.84%** | −13.83% | 25.0% | 0.0242 | −13.12% | 0.0445 | −13.1 / .045 ✓ |
| clock exit 13:00 | 30 | **−15.13%** | −16.16% | 30.0% | 0.0235 | −13.18% | 0.0438 | −13.2 / .044 ✓ |
| clock exit 14:00 | 31 | −9.63% | −10.53% | 38.7% | 0.2127 | −7.69% | 0.2817 | −7.7 / .282 ✓ |
| clock exit 15:00 | 33 | −5.07% | −17.80% | 39.4% | 0.5519 | −1.75% | 0.8110 | not quoted |
| hold to close | 33 | **−6.08%** | −13.46% | 39.4% | 0.4660 | +1.77% | 0.8194 | +1.8 / .82 ✓ |

Every published figure recovered. On real premiums each is **2 to 3 percentage points worse**
than the proxy said, and the ordering the spec relied on is unchanged: early exits are worse
than late ones, and hold-to-close remains the least-bad. **The spec's conclusion about the
*ranking* survives contact with real prices. Its conclusion about the *level* does not — the
least-bad option is a loss, not a break-even.**

---

## 6. (E) Multiple comparisons and placebo discipline

**Total exit rules examined in this script: 39.** These 33 trades had already been searched
once before, by `bs_gap_fill_pnl.py` (3 trailing stops) and by the unpersisted clock-exit
scan quoted in the module spec (at least 6 more), so the cumulative search on this sample is
larger than 39.

| test | count |
|---|---:|
| variants with raw p vs zero < 0.05 | **13 of 39** — *all of them losses* |
| surviving Bonferroni vs zero (α/39 = 1.28×10⁻³) | **2** — *both losses* (hold 20m, hold 30m) |
| surviving Benjamini–Hochberg vs zero | 4 — *all losses* |
| variants with raw p vs the baseline < 0.05 | **0 of 38** |
| surviving Bonferroni vs baseline | **0** |
| surviving Benjamini–Hochberg vs baseline | **0** |

**Not one variant beats the plain hold-to-close trade even at a raw, uncorrected 5%.** In the
Gate-A studies the overlay at least reached nominal significance before the placebo killed
it. Here it does not get that far.

### Shuffled-label placebo, 5,000 draws

Each draw reassigns Gate-B membership at random among the **263** non-expiry gap-down days
whose gap fills after 09:17 and which are priceable on real traded premiums (263 of 264 — the
pool is effectively complete). This preserves N, the CALL direction, the gap-fill entry
mechanism, the time-of-day distribution of entries, chronology and the entire exit machinery,
and destroys only the association with an overnight VIX rise and the mid opening-IV bucket.
For every draw the **best p-value across all 39 variants** is recorded — a Westfall–Young
style max-statistic correction.

| test | observed best-of-grid p | placebo median | placebo 5th pct | **empirical best-of-grid p** |
|---|---:|---:|---:|---:|
| vs zero | 0.000199 | 0.015212 | 0.000013 | **0.1164** |
| vs the baseline | 0.105284 | 0.038510 | 0.001304 | **0.7738** |

At least one of the 39 variants reaches nominal p<0.05 against zero in **69.7%** of placebo
draws, and beats its own baseline at p<0.05 in **56.5%** of draws. That is the scale of the
search being corrected for, and it is larger than in the Gate-A studies because the grid is
run on a noisier, all-day return.

**Reading:** neither the best-of-grid result against zero (empirical p = 0.1164) nor against
the baseline (0.7738) survives. And since the observed best-against-zero is a *loss*, even
"surviving" would have meant confirming a reliable way to lose money.

### The gate itself, before any exit search

The more fundamental test. Does Gate-B membership — non-expiry, gap-down, VIX rose, mid-IV
bucket, gap filled — select days that are better than a random non-expiry gap-down fill day?

| | value |
|---|---:|
| observed Gate-B hold-to-close mean on real premiums | **−6.08%** |
| placebo mean of the same statistic | −8.48% |
| placebo 5th / 95th percentile | −20.60% / +3.74% |
| **share of placebo draws at or above the observed value** | **37.1%** |

**Gate B's conditioning earns nothing.** A randomly chosen set of 33 non-expiry gap-down
fill days does better than Gate B in 37% of draws. This is the sharpest contrast with Gate A,
whose defining and repeatedly replicated finding across three separate studies was that
*the Gate-A population itself* carries a positive expected return that shuffled labels do not
reproduce. Gate B has no such property. What Gate B is really selecting for — mid IV and a
VIX rise — adds no measurable value on top of "the gap filled".

Note also that the placebo pool's own mean is **−8.48%**. Buying an ATM CALL at the gap-fill
moment on *any* non-expiry gap-down day and holding it to the close is a losing trade on real
prices. Gate B is a mildly less-bad version of a bad trade.

---

## 7. (F) Power — what N=33 can and cannot detect

For a two-sided one-sample t-test at 5% size and 80% power:

| N | context | required standardized effect |
|---:|---|---:|
| 33 | full sample | 0.503 sd |
| 28 | true-reversal subset | 0.549 sd |
| 5 | false-fire subset | 1.682 sd |

Translated:

| quantity | sd | detectable at N=33 |
|---|---:|---:|
| hold-to-close return on real premiums | 47.3pp | **23.8pp** |
| incremental effect of an overlay (median paired sd) | 36.4pp | **18.3pp** |

Observed baseline mean **−6.08%**, 95% CI **[−22.86%, +10.70%]** (bootstrap, 10,000 draws:
[−21.78%, +9.66%]).

**What this design can detect:** a trade earning more than about 24 percentage points of
premium per fire, or an overlay adding more than about 18. Nothing in the grid comes close;
the best overlay adds 3.91pp and the best variant still loses.

**What it cannot detect:** anything smaller. The confidence interval on the baseline spans
−23% to +11%, so a genuinely profitable Gate B earning, say, +8% per trade **cannot be ruled
out by this sample.** That is why the verdict is stated as *cannot be shown to make money*
rather than *is shown to lose money*.

**But the asymmetry matters.** Under-power is a reason to withhold a positive conclusion, not
a reason to trade. Every one of 39 point estimates is negative; the volatility drag that
explains why is measured at p<0.0001 and is not itself underpowered; the gate's conditioning
fails against its placebo; and the most recent third of the sample is the worst. There is no
positive result here being missed for want of sample size — there is a consistently negative
one that the sample is too small to *certify*.

---

## 8. (G) Costs

### 8.1 The spread is unidentified; here are bounds

The dataset carries one-minute OHLC bars and no order book, so the true quoted bid–ask spread
is **unidentified**. Two bounds, both measured on the traded contract itself:

| measure | value | direction |
|---|---:|---|
| one-minute high–low range at the **entry** minute, median | **6.65%** of premium (N=33) | upper bound — contains real price movement, badly overstates |
| same at 12:00, median | 3.22% of premium | upper bound |
| Roll (1984) effective spread on one-minute closes, median | **1.17%** of premium (N=18) | lower bound — one-minute aggregation averages away most bid–ask bounce |

That the entry-minute range is twice the midday range is itself informative: the book is
visibly wider at the times Gate B most often fires.

### 8.2 Assumption used, stated explicitly

**A half-spread of 0.35% of premium paid on entry and again on exit — 0.70% round trip.** On
the median traded entry premium of ~101 points that is about 0.35 points a side, roughly 7
ticks of the ₹0.05 tick, which is a reasonable central estimate for a NIFTY weekly ATM option.
A **pessimistic case at 1.00% a side** is carried alongside, because 30% of Gate-B fires enter
before 09:20 when the book is at its widest.

### 8.3 Statutory and brokerage, per lot of 75, both legs

Brokerage ₹20/order × 2; STT 0.100% of premium on the sell leg (post-2024-10-01 rate); NSE
transaction charge 0.03503% each leg; SEBI ₹10/crore; stamp duty 0.003% buy leg; GST 18% on
brokerage plus transaction charges.

| spread assumption | round-trip cost, median trade | in rupees, one lot |
|---|---:|---:|
| statutory only (0% spread) | 0.81% of entry premium | ₹61 |
| **base case (0.35% half-spread)** | **1.51%** | **₹114** |
| pessimistic (1.00% half-spread) | 2.81% | ₹213 |

### 8.4 Net of costs

| variant | spread | N | mean | median | win% | p vs 0 |
|---|---:|---:|---:|---:|---:|---:|
| **hold to close (incumbent)** | 0.35% | 33 | **−7.53%** | −14.58% | 39.4% | 0.3657 |
| hold to close | 1.00% | 33 | **−8.79%** | −15.79% | 39.4% | 0.2890 |
| target +75% (best gross mean) | 0.35% | 33 | −3.64% | −12.05% | 42.4% | 0.6785 |
| target +75% | 1.00% | 33 | −4.92% | −13.27% | 42.4% | 0.5727 |
| target +100% (best vs baseline) | 0.35% | 33 | −4.39% | −14.58% | 39.4% | 0.6362 |
| target +100% | 1.00% | 33 | −5.68% | −15.79% | 39.4% | 0.5391 |
| hold 30m after fill (smallest p) | 0.35% | 33 | −12.43% | −10.91% | 21.2% | <0.0001 |

Aryan trades at most 1–2 lots of 75. Cost is close to proportional in premium, so lot count
barely changes the percentages; the flat ₹40 brokerage is the only fixed component and it is
under 0.6% of a one-lot premium of ₹7,590.

**Net of costs, the incumbent Gate-B trade loses 7.5% to 8.8% of premium per fire — roughly
₹570 to ₹670 on a single lot, before any slippage beyond the assumed spread.** Over 33 fires
in 4.4 years that is about −₹20,000 on one lot; the trade fires roughly 7–8 times a year, so
this is a slow bleed rather than a blow-up, which is exactly the kind of loss that is easy to
mistake for noise while live.

---

## 9. What I think is wrong in the current plan

Stated plainly, as asked.

1. **"Gate B cannot be shown to make money on real prices."** Those are the words the brief
   asked for if they were the honest answer, and they are. Every one of 39 exit rules has a
   negative mean; the incumbent loses 6.1% gross and 7.5% net; and the gate's own conditioning
   does not beat a shuffled label.

2. **Disarming Gate A and arming Gate B inverts the evidence ordering.** Across three
   independent studies Gate A's replicated finding is that *the Gate-A population itself*
   carries a positive expected return that shuffled labels do not reproduce (empirical
   best-of-grid p = 0.0056 against zero). Gate B's population sits at the **37th percentile of
   its own placebo**. Whatever the case for standing down Gate A, "Gate B is the better bet"
   is not supported by anything in either study. Gate B is the gate with the weakest evidence
   in the project, and this test makes it weaker, not stronger.

3. **The 84.8% hit rate is not a P&L statistic and should stop being quoted as though it
   authorises a trade.** On the 28 fires where the gate was directionally *right*, the CALL
   still loses 2.1% on average, 12.2% at the median, and wins only 39.3% of the time. The
   gate predicts the index path tolerably. It does not predict the option's P&L, because
   volatility decay and time decay eat a correct directional call over a full session.

4. **The spec already said there was no edge, and the plan is to trade it anyway.**
   `GAP_FILL_SIGNAL_MODULE_SPEC.md` records hold-to-close at p=0.82 and states in terms:
   *"This is not a proven positive edge (p=0.82) — it is the least-bad option among a wide
   grid of exit designs, all others being demonstrably worse."* Arming that with real money
   is arming an explicitly documented null. Real prices now move that null to −6.1% gross,
   −7.5% net.

5. **The brief's premise about the opening IV crush is half right, and the half that is wrong
   matters.** Gate B's median entry at 09:43 comes *after* most of the opening crush, so the
   specific Gate-A channel largely misses it. Gate B is instead hit by the full-session
   volatility decline — worth −8.3% of premium at p<0.0001 — precisely *because* its
   prescribed exit is hold-to-close. The recommendation "no fixed-clock exit before 14:00"
   maximises exposure to the very drag that sinks the trade. Correcting the premise does not
   rescue Gate B; it identifies a bigger leak than the one that was suspected.

6. **The smallest-p-value selection rule used elsewhere in this project would, on this
   sample, select a reliable loss-maker.** The grid's minimum p-value is 0.0002 on "hold 30
   minutes after fill", which loses 11% per trade. Selecting on |t| without checking the sign
   is a live hazard in the existing Gate-A machinery too.

7. **Two things I have not established, and will not claim.** First, this is *not* a
   demonstration that Gate B loses money: N=33 cannot resolve a mean smaller than ±24
   percentage points, and a genuinely profitable +8%-per-trade Gate B is inside the confidence
   interval. Second, these are one-minute bar closes, not executable fills; §8 bounds the
   spread but does not measure it, and real slippage on a 09:18 entry could be worse than the
   pessimistic case assumed. Both of these cut against certainty, not in favour of trading —
   an underpowered null and an unmeasured cost are reasons to wait for more evidence, not to
   commit capital on Monday.

8. **What would actually change the verdict.** A positive result on real premiums would have
   to come from somewhere this study did not look: a different instrument (spreads or a
   directional futures/spot position, neither of which pays the volatility drag the way a long
   option does), a different exit family, or more data. If Gate B is to be pursued at all, the
   cheapest honest next step is to test the same 33 signals as a **spot or futures**
   directional trade, where the 84.8% path statistic has a chance of translating into P&L
   without an 8.3% volatility tax. That is a different specification and would need its own
   approval.

---

## 10. Reproducibility

New artifacts only. No existing script, specification, or report was modified. No git commit
or push was performed.

| File | Contents |
|---|---|
| `gate_b_common.py` | Gate-B path construction, traded-premium alignment, exit machinery, reproduction guard |
| `gate_b_real_premium.py` | §2 entry timing, §3 implied-volatility path, §4 hold-to-close headline |
| `gate_b_exit_grid_real.py` | §5 grid, §6 multiplicity and placebo, §7 power, §8 costs |
| `gate_b_paths.pkl` | Cached path construction (264 paths) |
| `gate_b_call_quotes.pkl` | Cached CALL minute bars (10.4M rows) |
| `gate_b_real_premium.csv` | Per-trade real and proxy hold-to-close returns |
| `gate_b_iv_path.csv` | Per-trade implied-volatility path of the traded contract |
| `gate_b_iv_decomposition.csv` | Per-trade volatility leg in points and % of entry premium |
| `gate_b_exit_grid_real.csv` | Full 39-variant grid |
| `gate_b_exit_grid_real_results.json` | Machine-readable results |
| `GATE_B_REAL_PREMIUM_VALIDATION.md` | This report |

Data staging: the full ATM−10…ATM+10 NIFTY weekly CALL minute series (1,386 files) was
staged from Aryan's Drive into the existing local cache at
`~/.cache/openclaw/gdrive/.../dhan_fresh_2021_2026/options/` using the configured `gdrive:`
rclone remote. The Google Drive File-Provider mount fails with `Resource deadlock avoided` on
read, which is the failure mode already documented in `TOOLS.md`; the Drive-API path works.
No exchange or broker network was contacted.

```text
.ml_venv/bin/python -m py_compile gate_b_common.py gate_b_real_premium.py \
    gate_b_exit_grid_real.py
.ml_venv/bin/python gate_b_common.py          # reproduction guard PASSED
.ml_venv/bin/python gate_b_real_premium.py
.ml_venv/bin/python gate_b_exit_grid_real.py
```

All completed successfully. Placebo seed 20260822, 5,000 draws.

**Operational claim: nothing here authorises live use, and this report is evidence against
it.** No live order exists or is authorised.
