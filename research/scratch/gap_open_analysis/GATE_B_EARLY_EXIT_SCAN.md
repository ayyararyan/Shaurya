# Gate B: fine-grained early-exit scan on the pooled N=120 population

**Run date:** 2026-08-23
**Requested by:** Aryan, who put a specific hypothesis on the table and asked for it to be
tested rather than argued with.
**Task status:** **COMPLETE.** Every requested component ran: the fine exit grid under both
sample conventions (A), the choppiness measurement on spot (B), the decay-versus-delta split
under a trading-time maturity (C), multiplicity and a 5,000-draw best-of-grid placebo (D),
and power (E). Two components were added because the honest reading required them: a
loss-per-minute-held table and a direct test of the give-back mechanism.

**Evidence class:** exploratory / specification check on **observed traded prices**. Not
identification-grade, not manuscript-ready. Coverage is complete — 120 of 120 fires priced
on real strike-tracked traded premiums at every minute from entry to 15:29, zero missing
bars — so nothing here is thinned and nothing can be missing non-randomly.

No broker, credential, exchange network, or order path was used. No live order exists or is
authorised. No existing script or report was modified.

---

## 0. Verdict

> **No. Aryan's hypothesis is not supported.** There is no mid-morning choppy window on
> these 120 days, the favourable drift does not accumulate early and then get given back —
> it accumulates *late*, after 13:00, having been **negative** all morning — and not one of
> the 45 exit variants tested produces a positive mean return.

Stated with the same directness the brief asked for in the other direction: had there been
a clean early-exit window, it would be in section 1 with its numbers. There is not one.

Three separate measurements agree, and they are independent of each other:

| measurement | what Aryan's hypothesis predicts | what the data shows |
|---|---|---|
| directional efficiency of spot inside 10:30–11:30 | collapses relative to the rest of the session | **0.1922 inside vs 0.1854 outside — very slightly *higher*, Welch p = 0.56** |
| cumulative favourable spot drift from entry | positive early, given back later | **negative and significant all morning (−0.08%, p = 0.004 at 09:45), recovering to ≈0 only by the close** |
| P&L of exiting before 11:30 versus holding | early exit wins | **every early exit still loses; the largest gain over the baseline is +6.12pp at p = 0.14, and the placebo says a random label does better in 85% of draws** |

There is a real and correct observation buried inside the hypothesis, and it is worth
separating out: **short holds do lose less money in total.** Hold 5 minutes and you lose
1.49%; hold to the close and you lose 7.61%. But that is not an edge and it is not the
mechanism Aryan described. Section 1.4 shows that per minute held, the short holds bleed
**ten times faster** than the long ones. You lose less because you were in the trade for
less time, not because you dodged anything.

---

## 1. (A) The fine early-exit grid

### 1.1 Population and construction

Non-expiry day, NIFTY gapped down, India VIX rose overnight, and the gap filled at some
minute strictly after 09:17. Entry is one ATM NIFTY CALL at the fill minute, nearest weekly
expiry, strike held fixed and tracked by absolute value through the session. **N = 120**
(low-IV 55, mid-IV 33, high-IV 32), 2021-09-08 to 2026-04-20.

Entry clock: minimum 09:18, **median 09:32**, mean 10:30, maximum 15:07. **72.5% of fires
enter before 10:30**, which matters below.

All returns are on **real strike-tracked traded premiums** — one-minute bar closes for the
contract actually bought. 120/120 fires are priceable at every minute with zero NaN.

### 1.2 The two sample conventions, and why both are reported

A fire whose gap fills *after* a given wall clock cannot use that exit. There are two ways
to handle it and they answer different questions:

* **(i) Full-sample.** The clock cap has already passed at entry, so the position runs to
  the close. N stays at 120 for every variant and the sample composition never changes.
* **(ii) Traded-only.** Those fires are simply not traded. N falls as the clock moves
  earlier. **This is the convention the published Gate-B figures use** (it is what
  reproduces `GAP_FILL_SIGNAL_MODULE_SPEC.md`'s numbers to the decimal).

The traded-only convention silently changes the sample as the clock moves earlier, and this
is exactly the confound the brief flagged. It is visible in the "mean entry" column: at
clock 09:30 the surviving 54 trades have a mean entry of **09:19**; at clock 15:00 the
surviving 115 have a mean entry of **10:18**. Early-clock rows are not the same trade
measured earlier — they are a different, shallower-gap, faster-filling population. Any
apparent early-exit advantage under that convention has to be checked against the
full-sample convention before it is believed. Here neither convention produces one, so the
confound turns out not to be load-bearing, but it was not safe to assume that in advance.

### 1.3 The grid

**45 variants: 1 baseline + 12 elapsed holds + 16 wall clocks × 2 conventions.**

**(i) Full-sample convention, N = 120 throughout**

| variant | N | mean | median | win% | sd | p vs 0 | Δ vs base | p vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **hold to close (baseline)** | 120 | **−7.61%** | −13.22% | 38.3% | 45.1 | 0.0672 | — | — |
| hold 5m after fill | 120 | **−1.49%** | −2.30% | 39.2% | 9.5 | 0.0889 | +6.12pp | 0.1380 |
| hold 10m after fill | 120 | −2.28% | −2.36% | 39.2% | 12.9 | 0.0551 | +5.33pp | 0.1984 |
| hold 15m after fill | 120 | −2.61% | −2.04% | 41.7% | 14.1 | 0.0450 | +5.00pp | 0.2245 |
| hold 20m after fill | 120 | −4.88% | −5.29% | 40.0% | 16.5 | **0.0016** | +2.73pp | 0.4969 |
| hold 25m after fill | 120 | −4.92% | −5.85% | 36.7% | 17.7 | **0.0029** | +2.69pp | 0.5058 |
| hold 30m after fill | 120 | −3.77% | −4.62% | 41.7% | 19.7 | 0.0385 | +3.84pp | 0.3411 |
| hold 40m after fill | 120 | −3.74% | −7.47% | 36.7% | 20.8 | 0.0506 | +3.86pp | 0.3313 |
| hold 50m after fill | 120 | −4.76% | −8.96% | 40.8% | 23.2 | 0.0267 | +2.85pp | 0.4609 |
| hold 60m after fill | 120 | −5.10% | −8.47% | 34.2% | 24.3 | 0.0233 | +2.51pp | 0.4901 |
| hold 75m after fill | 120 | **−8.33%** | −12.58% | 39.2% | 24.6 | **0.0003** | −0.72pp | 0.8308 |
| hold 90m after fill | 120 | −7.84% | −11.44% | 33.3% | 28.4 | **0.0030** | −0.24pp | 0.9433 |
| hold 120m after fill | 120 | −6.16% | −10.05% | 36.7% | 33.2 | 0.0441 | +1.44pp | 0.6673 |
| clock 09:30 | 120 | −5.76% | −6.38% | 35.0% | 30.9 | 0.0433 | +1.85pp | 0.5545 |
| clock 09:45 | 120 | −6.40% | −9.55% | 34.2% | 25.8 | 0.0076 | +1.21pp | 0.7171 |
| clock 10:00 | 120 | −4.71% | −5.84% | 35.8% | 26.6 | 0.0547 | +2.90pp | 0.4214 |
| clock 10:15 | 120 | −5.40% | −8.09% | 37.5% | 25.0 | 0.0197 | +2.20pp | 0.5446 |
| clock 10:30 | 120 | −6.18% | −8.57% | 40.0% | 26.2 | 0.0109 | +1.43pp | 0.6894 |
| clock 10:45 | 120 | −6.57% | −8.82% | 38.3% | 26.8 | 0.0083 | +1.04pp | 0.7585 |
| clock 11:00 | 120 | −6.30% | −7.84% | 37.5% | 29.9 | 0.0228 | +1.30pp | 0.6950 |
| clock 11:15 | 120 | −6.21% | −9.65% | 37.5% | 31.4 | 0.0323 | +1.39pp | 0.6710 |
| clock 11:30 | 120 | −5.23% | −6.67% | 40.8% | 33.3 | 0.0882 | +2.38pp | 0.4564 |
| clock 12:00 | 120 | −5.65% | −9.12% | 38.3% | 35.5 | 0.0836 | +1.96pp | 0.5265 |
| clock 12:30 | 120 | −5.56% | −10.94% | 35.8% | 37.3 | 0.1045 | +2.04pp | 0.4899 |
| clock 13:00 | 120 | −5.13% | −11.36% | 40.0% | 37.8 | 0.1393 | +2.48pp | 0.3455 |
| clock 13:30 | 120 | −6.33% | −9.66% | 35.0% | 37.3 | 0.0654 | +1.28pp | 0.6017 |
| clock 14:00 | 120 | −5.38% | −10.83% | 38.3% | 40.4 | 0.1474 | +2.23pp | 0.2943 |
| clock 14:30 | 120 | −4.69% | −9.05% | 42.5% | 42.7 | 0.2313 | +2.91pp | 0.1429 |
| clock 15:00 | 120 | −5.09% | −11.93% | 40.0% | 43.8 | 0.2053 | +2.52pp | 0.0956 |

**(ii) Traded-only convention** (a day whose gap fills after the clock is dropped)

| variant | N | mean | median | win% | sd | p vs 0 | Δ vs base | p vs base | mean entry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| clock 09:30 | 54 | −5.04% | −6.02% | 27.8% | 11.9 | **0.0030** | +4.11pp | 0.5572 | 09:19 |
| clock 09:45 | 67 | −6.89% | −10.25% | 28.4% | 17.2 | **0.0017** | +2.17pp | 0.7184 | 09:22 |
| clock 10:00 | 76 | −6.15% | −7.63% | 30.3% | 21.4 | 0.0145 | +4.57pp | 0.4228 | 09:26 |
| clock 10:15 | 85 | −5.36% | −9.76% | 35.3% | 24.1 | 0.0433 | +3.11pp | 0.5455 | 09:30 |
| clock 10:30 | 87 | −7.33% | −10.49% | 37.9% | 26.2 | 0.0105 | +1.97pp | 0.6900 | 09:31 |
| clock 10:45 | 91 | **−7.87%** | −11.42% | 36.3% | 27.8 | 0.0082 | +1.37pp | 0.7589 | 09:34 |
| clock 11:00 | 92 | −7.80% | −10.10% | 34.8% | 31.7 | 0.0204 | +1.70pp | 0.6955 | 09:35 |
| clock 11:15 | 92 | −7.68% | −13.08% | 34.8% | 33.5 | 0.0304 | +1.82pp | 0.6716 | 09:35 |
| clock 11:30 | 92 | −6.40% | −9.78% | 39.1% | 35.9 | 0.0906 | +3.10pp | 0.4571 | 09:35 |
| clock 12:00 | 94 | −7.13% | −11.17% | 35.1% | 38.1 | 0.0728 | +2.50pp | 0.5271 | 09:37 |
| clock 12:30 | 96 | −7.34% | −12.95% | 31.2% | 40.0 | 0.0753 | +2.56pp | 0.4905 | 09:40 |
| clock 13:00 | 102 | −6.48% | −12.52% | 38.2% | 39.6 | 0.1015 | +2.91pp | 0.3459 | 09:51 |
| clock 13:30 | 108 | −6.70% | −9.66% | 34.3% | 38.5 | 0.0738 | +1.43pp | 0.6019 | 10:03 |
| clock 14:00 | 108 | −5.65% | −11.83% | 38.0% | 42.0 | 0.1647 | +2.47pp | 0.2945 | 10:03 |
| clock 14:30 | 113 | −5.26% | −10.42% | 41.6% | 43.8 | 0.2038 | +3.09pp | 0.1430 | 10:14 |
| clock 15:00 | 115 | −5.47% | −14.39% | 39.1% | 44.6 | 0.1904 | +2.63pp | 0.0956 | 10:18 |

*Δ vs base and p vs base are always paired against hold-to-close **on the same trades**, so
the traded-only rows compare like with like within their own reduced sample.*

### 1.4 Best 8 and worst 5

**Best 8 by mean, across both conventions**

| rank | variant | conv | N | mean | median | win% | p vs 0 | Δ vs base | p vs base |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | hold 5m after fill | both | 120 | −1.49% | −2.30% | 39.2% | 0.0889 | +6.12pp | 0.1380 |
| 2 | hold 10m after fill | both | 120 | −2.28% | −2.36% | 39.2% | 0.0551 | +5.33pp | 0.1984 |
| 3 | hold 15m after fill | both | 120 | −2.61% | −2.04% | 41.7% | 0.0450 | +5.00pp | 0.2245 |
| 4 | hold 40m after fill | both | 120 | −3.74% | −7.47% | 36.7% | 0.0506 | +3.86pp | 0.3313 |
| 5 | hold 30m after fill | both | 120 | −3.77% | −4.62% | 41.7% | 0.0385 | +3.84pp | 0.3411 |
| 6 | clock 14:30 | full | 120 | −4.69% | −9.05% | 42.5% | 0.2313 | +2.91pp | 0.1429 |
| 7 | clock 10:00 | full | 120 | −4.71% | −5.84% | 35.8% | 0.0547 | +2.90pp | 0.4214 |
| 8 | hold 50m after fill | both | 120 | −4.76% | −8.96% | 40.8% | 0.0267 | +2.85pp | 0.4609 |

**Worst 5 by mean**

| variant | conv | N | mean | median | win% | p vs 0 | Δ vs base | p vs base |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| hold 75m after fill | both | 120 | −8.33% | −12.58% | 39.2% | **0.0003** | −0.72pp | 0.8308 |
| clock 10:45 | traded | 91 | −7.87% | −11.42% | 36.3% | 0.0082 | +1.37pp | 0.7589 |
| hold 90m after fill | both | 120 | −7.84% | −11.44% | 33.3% | 0.0030 | −0.24pp | 0.9433 |
| clock 11:00 | traded | 92 | −7.80% | −10.10% | 34.8% | 0.0204 | +1.70pp | 0.6955 |
| clock 11:15 | traded | 92 | −7.68% | −13.08% | 34.8% | 0.0304 | +1.82pp | 0.6716 |

### 1.5 The single most diagnostic facts in section A

> **Zero of the 45 variants has a positive mean return.** Best is −1.49%, worst is −8.33%.
>
> **Not one variant beats hold-to-close at even a raw, uncorrected 5%.** The smallest p
> against the baseline in the entire grid is 0.0956.
>
> **The whole grid fits inside the noise.** The spread from best to worst variant is
> **6.84pp**. The smallest overlay effect this design can detect at 80% power is **9.69pp**.
> Every difference between one exit rule and another in this table is smaller than what the
> sample can resolve. The ordering is not information.

Directly on Aryan's window, full-sample convention:

| group | mean |
|---|---:|
| clock exits at or before 11:30 (9 variants) | **−5.86%** |
| clock exits after 11:30 (7 variants) | **−5.40%** |
| hold to close | −7.61% |

Exiting before the supposed chop is, if anything, marginally worse than exiting after it.
The gap is 0.46pp against a detectable threshold of 9.69pp, so the honest reading is that
the two are indistinguishable.

### 1.6 Loss per minute held — the short holds are smaller bets, not better ones

This is the part that makes the "hold 5m is best" row interpretable. Dividing each
variant's mean loss by the minutes it was actually held:

| variant | mean held (min) | mean | **% per minute held** |
|---|---:|---:|---:|
| hold 5m after fill | 5.0 | −1.49% | **−0.298** |
| hold 10m after fill | 10.0 | −2.28% | −0.228 |
| hold 20m after fill | 20.0 | −4.88% | −0.244 |
| hold 30m after fill | 29.8 | −3.77% | −0.126 |
| hold 60m after fill | 58.4 | −5.10% | −0.087 |
| clock 11:30 (full) | 115.2 | −5.23% | −0.045 |
| clock 13:00 (full) | 171.7 | −5.13% | −0.030 |
| clock 15:00 (full) | 270.6 | −5.09% | −0.019 |
| hold to close | 298.4 | −7.61% | **−0.026** |

The rate of loss is **worst at the shortest horizons** and improves monotonically with
holding time, by a factor of about ten. A five-minute hold is not dodging a later problem;
it is standing in the worst part of the session and then leaving. If the mechanism were
"gains accumulate early and are given back", the per-minute rate would be *positive* early
and negative later. It is negative early and least negative late.

### 1.7 Net of costs

The round trip is paid once regardless of holding period, so a short hold gets no cost
discount. Same cost model as `GATE_B_REAL_PREMIUM_VALIDATION.md` §8 (brokerage ₹20×2, STT
0.100% sell leg, NSE 0.03503% each leg, SEBI ₹10/crore, stamp 0.003% buy leg, GST 18%).

| variant | gross | net @0.35% half-spread | net @1.00% | p (net, 0.35%) |
|---|---:|---:|---:|---:|
| hold 5m after fill | −1.49% | **−2.95%** | −4.24% | **0.0009** |
| hold 10m after fill | −2.28% | −3.73% | −5.02% | 0.0018 |
| hold 15m after fill | −2.61% | −4.07% | −5.35% | 0.0019 |
| hold 30m after fill | −3.77% | −5.21% | −6.49% | 0.0042 |
| clock 10:00 (full) | −4.71% | −6.15% | −7.42% | 0.0121 |
| clock 14:30 (full) | −4.69% | −6.14% | −7.41% | 0.1167 |

**Net of costs the best early exit in the whole scan loses 2.95% of premium per trade at
p = 0.0009.** The p-value here is small because the short-hold return has a small standard
deviation (9.5pp against the baseline's 45.1pp), not because the loss is large — it is a
reliably small loss rather than an unreliably large one. That is still a loss.

---

## 2. (B) The choppiness claim, measured directly on spot

Measured on the **NIFTY spot path only**. No option, so no time decay and no volatility path
can contaminate it. Only days already entered at the bucket start are counted, so every
measured bucket is genuinely post-entry. "Favourable" means **up**, because the trade is a
CALL.

**Directional efficiency = net move over the bucket ÷ total path length walked inside it.**
+1 is a clean one-way rally, 0 is pure chop, −1 is a clean one-way sell-off. This, not low
volatility, is the actual definition of choppiness.

### 2.1 Half-hour buckets

| bucket | N | drift % | median | up% | p | RV % | RV bp/min | path % | signed eff | \|eff\| |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 09:30–10:00 | 56 | +0.006% | +0.024% | 55.4% | 0.830 | 0.210% | **0.70** | 0.907% | +0.0202 | 0.1836 |
| 10:00–10:30 | 76 | −0.016% | −0.002% | 50.0% | 0.442 | 0.173% | 0.58 | 0.738% | −0.0156 | 0.1939 |
| **10:30–11:00** | 87 | −0.014% | −0.011% | 49.4% | 0.498 | 0.157% | 0.52 | 0.662% | −0.0034 | **0.2132** |
| **11:00–11:30** | 92 | +0.016% | +0.007% | 51.1% | 0.249 | 0.137% | 0.46 | 0.585% | +0.0227 | 0.1724 |
| 11:30–12:00 | 92 | −0.006% | +0.008% | 54.3% | 0.696 | 0.127% | **0.42** | 0.539% | −0.0119 | 0.1916 |
| 12:00–12:30 | 96 | +0.005% | +0.003% | 52.1% | 0.765 | 0.130% | 0.43 | 0.551% | −0.0018 | 0.1863 |
| 12:30–13:00 | 96 | +0.015% | +0.007% | 53.1% | 0.417 | 0.133% | 0.44 | 0.566% | +0.0278 | 0.1923 |
| 13:00–13:30 | 102 | +0.007% | +0.006% | 53.9% | 0.556 | 0.131% | 0.44 | 0.559% | +0.0222 | **0.1627** |
| 13:30–14:00 | 108 | +0.014% | +0.006% | 50.9% | 0.440 | 0.135% | 0.45 | 0.568% | +0.0150 | 0.2043 |
| 14:00–14:30 | 108 | +0.004% | +0.006% | 51.9% | 0.781 | 0.147% | 0.49 | 0.626% | +0.0064 | 0.1677 |
| 14:30–15:00 | 113 | +0.013% | +0.000% | 49.6% | 0.378 | 0.155% | 0.52 | 0.633% | +0.0164 | 0.1845 |
| 15:00–15:29 | 116 | +0.000% | −0.006% | 45.7% | 0.984 | 0.137% | 0.47 | 0.567% | −0.0003 | 0.1887 |

*(The 09:15–09:30 bucket is absent: the earliest fire enters at 09:18, so no day is fully
post-entry for it.)*

### 2.2 Is there a mid-morning collapse in directional efficiency? No.

Formal test, one observation per (day, half-hour bucket):

| | inside 10:30–11:30 | outside | difference | Welch p |
|---|---:|---:|---:|---:|
| directional efficiency \|eff\| | **0.1922** (n=179) | 0.1854 (n=963) | **+0.0069** | **0.5615** |
| realised volatility, bp/min | 0.488 | 0.483 | +0.005 | 0.7333 |

**Efficiency inside Aryan's window is very slightly *higher* than outside it, and realised
volatility is identical.** The 10:30–11:00 bucket is in fact the *most* directionally
efficient half-hour of the whole post-entry session (0.2132); the *least* efficient is
13:00–13:30 (0.1627). The whole range across twelve buckets is 0.163–0.213, and none of the
differences are distinguishable from noise.

What the session actually does have is the standard intraday volatility U-shape: realised
volatility falls monotonically from 0.70 bp/min at 09:30–10:00 to 0.42 bp/min at
11:30–12:00, then creeps back up into the close. **The market gets quieter mid-morning, not
choppier.** Quiet and choppy are different things and the efficiency measure separates
them: if the market were turning choppy, path length would stay high while net moves
shrank, and efficiency would fall. Path length shrinks in proportion, so it does not.

### 2.3 Where the favourable drift actually accumulates — the decisive table

Cumulative **spot** return from entry to each wall clock, days entered before that clock:

| clock | N | mean | median | up% | p |
|---|---:|---:|---:|---:|---:|
| 09:30 | 54 | **−0.049%** | −0.023% | 37.0% | **0.0147** |
| 09:45 | 67 | **−0.078%** | −0.059% | 37.3% | **0.0041** |
| 10:00 | 76 | −0.060% | −0.044% | 39.5% | **0.0380** |
| 10:15 | 85 | −0.059% | −0.024% | 41.2% | **0.0263** |
| 10:30 | 87 | −0.069% | −0.073% | 40.2% | **0.0248** |
| 10:45 | 91 | −0.074% | −0.060% | 42.9% | **0.0345** |
| 11:00 | 92 | −0.076% | −0.052% | 41.3% | **0.0390** |
| 11:15 | 92 | −0.074% | −0.084% | 40.2% | 0.0549 |
| 11:30 | 92 | −0.060% | −0.053% | 45.7% | 0.1321 |
| 12:00 | 94 | −0.063% | −0.031% | 43.6% | 0.1551 |
| 12:30 | 96 | −0.058% | −0.069% | 37.5% | 0.1939 |
| 13:00 | 102 | −0.039% | −0.040% | 41.2% | 0.3870 |
| 13:30 | 108 | −0.028% | −0.021% | 41.7% | 0.5253 |
| 14:00 | 108 | −0.015% | −0.031% | 46.3% | 0.7529 |
| 14:30 | 113 | −0.008% | −0.008% | 48.7% | 0.8593 |
| 15:00 | 115 | +0.005% | −0.021% | 46.1% | 0.9113 |
| **15:29** | **120** | **+0.004%** | −0.072% | 44.2% | 0.9291 |

And by elapsed time from entry, all 120 fires, no sample change at all:

| H | cum mean | median | up% | cum p | increment | inc p |
|---|---:|---:|---:|---:|---:|---:|
| 5m | −0.017% | −0.014% | 42.5% | 0.0387 | −0.017% | 0.0387 |
| 10m | −0.024% | −0.009% | 47.5% | 0.0456 | −0.007% | 0.3735 |
| 15m | −0.029% | −0.016% | 46.7% | 0.0382 | −0.005% | 0.5226 |
| 20m | **−0.053%** | −0.026% | 41.7% | **0.0016** | −0.023% | **0.0011** |
| 25m | −0.051% | −0.034% | 44.2% | 0.0057 | +0.001% | 0.8506 |
| 30m | −0.039% | −0.011% | 47.5% | 0.0455 | +0.012% | 0.0850 |
| 40m | −0.029% | −0.023% | 44.2% | 0.1439 | +0.010% | 0.3270 |
| 60m | −0.044% | −0.032% | 45.0% | 0.0545 | −0.005% | 0.6316 |
| 90m | −0.066% | −0.063% | 40.0% | 0.0259 | −0.001% | 0.9441 |
| 120m | −0.051% | −0.072% | 42.5% | 0.1180 | +0.015% | 0.2087 |
| close | **+0.004%** | −0.072% | 44.2% | 0.9291 | **+0.055%** | 0.1503 |

**Answer to the brief's question, unambiguously: the favourable drift accumulates LATE.**
Spot goes *against* the CALL immediately after the gap fill, reaching its worst point around
09:45–11:00 at roughly −0.07% with p-values in the 0.004–0.04 range, and then grinds slowly
back to approximately flat by the close. The largest single favourable increment in the
whole session (+0.055%) is the last one, from 120 minutes to the close.

This is the exact inverse of Aryan's mechanism. If you exit before 11:30 you are locking in
the worst point of the spot path. The reason it does not show as a large P&L penalty is that
by exiting early you have also avoided a large amount of decay — which is section 3.

### 2.4 The give-back test, stated as Aryan's mechanism would predict it

If early gains are given back through a choppy period, trades that are already **up** at an
early clock must reliably lose ground between that clock and the close.

| clock | group | N | mean, clock→close | median | pos% | p |
|---|---|---:|---:|---:|---:|---:|
| 10:00 | up at clock | 23 | −4.02% | −6.91% | 47.8% | 0.6809 |
| 10:00 | down at clock | 53 | −3.46% | −13.48% | 35.8% | 0.6748 |
| 10:30 | up at clock | 33 | −1.57% | −0.77% | 45.5% | 0.8309 |
| 10:30 | down at clock | 54 | −1.45% | −14.64% | 35.2% | 0.8567 |
| 11:00 | up at clock | 32 | −2.69% | −2.75% | 43.8% | 0.6521 |
| 11:00 | down at clock | 60 | −0.34% | −13.87% | 35.0% | 0.9639 |
| 11:30 | up at clock | 36 | −3.66% | −6.37% | 38.9% | 0.5296 |
| 11:30 | down at clock | 56 | −2.50% | −10.23% | 35.7% | 0.7239 |

**No give-back.** Winners at an early clock do drift slightly lower afterwards (−1.6% to
−4.0%) but so do losers (−0.3% to −3.5%), by almost exactly the same amount, and none of
the eight tests is remotely significant. There is no differential penalty for holding a
winner. The whole book decays gently, which is a theta signature, not a chop signature.
*(These eight are conditional diagnostics, not exit rules, and are counted separately from
the 45 grid variants.)*

### 2.5 When does each trade's premium actually peak?

Perfect-hindsight exit, i.e. the best minute available with full foreknowledge:

| statistic | value |
|---|---|
| median peak clock | **12:53** |
| median elapsed minutes to peak | 66.5 |
| share peaking before 11:00 | 37.5% |
| share peaking before 12:00 | 45.8% |
| share peaking at or after 14:00 | **43.3%** |
| deciles of the peak clock | 09:27, 09:41, 10:18, 11:10, **12:53**, 14:05, 14:24, 14:54, 15:12 |
| mean perfect-hindsight peak return | +32.70% |
| mean close return | −7.61% |
| mean giveback from peak to close | 40.31pp |

The peak is spread almost uniformly across the whole session. **More trades peak after 14:00
(43.3%) than before 11:00 (37.5%).** There is no clock at which "the trade is usually about
to turn". The 40.31pp giveback from the hindsight peak is large but it is an upper bound
available only with foreknowledge; it is present at every horizon and is the ordinary
consequence of a high-variance path, not evidence of a specific window.

---

## 3. (C) Decay versus delta, trading-time maturity

Following `CORRECTION_GATE_B_VOL_CRUSH.md`, implied volatility is **not** inverted with a
calendar-time maturity. Here maturity is **trading time**: 375 minutes per session
(09:15–15:30), 252 sessions per year, counting only sessions between the trade date and the
expiry date. Verified by hand on 2021-09-08 (entry 09:18, expiry 2021-09-09): 372 minutes
remaining today + 375 for the expiry session = 747 minutes = 1.992 sessions.

**Note on units.** Because trading time annualises on a 252-session year rather than a
365-day one, these implied volatilities are *lower in level* than market-quoted ones — mean
12.38%, median 10.90% here against ~15% on the calendar convention. That is a change of
units, not of information, and the decomposition below is internally consistent in it.
These numbers are **not** comparable to quoted IVs and should not be quoted as such.

### 3.1 Construction

Implied volatility is inverted **once per trade, from the traded entry premium**, so the
model price at entry equals the traded entry premium exactly (verified: maximum error
2.6 × 10⁻⁸ premium points across all 120 trades). With P(S,T) = BS(S, K, T, r, σ_entry):

```
spot leg  = [P(S_H, T_0) − P(S_0, T_0)] / C0_real     underlying move alone
decay leg = [P(S_0, T_H) − P(S_0, T_0)] / C0_real     trading-time decay alone
cross     = [P(S_H, T_H) − P(S_0, T_0)] / C0_real − spot − decay
residual  = [real_H − P(S_H, T_H)] / C0_real          IV change + BS mis-specification
total     = spot + decay + cross + residual           exact by construction
```

Verified exact: maximum |total − Σ legs| = 0.0000000000pp across every horizon.

`residual` is the only leg that is not model-determined. It is reported, not assumed away.

### 3.2 The split

All figures are percentage points of the traded entry premium, N = 120 at every row.

| horizon | held (min) | total | **spot leg** | **decay leg** | cross | residual | decay/min | p spot | p resid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hold 5m | 5.0 | −1.49% | −1.18% | −0.26% | +0.00% | −0.05% | −0.0526 | 0.1339 | 0.8805 |
| hold 10m | 10.0 | −2.28% | −1.12% | −0.53% | +0.00% | −0.64% | −0.0527 | 0.3188 | 0.0954 |
| hold 15m | 15.0 | −2.61% | −1.44% | −0.79% | +0.01% | −0.39% | −0.0527 | 0.2534 | 0.3430 |
| hold 20m | 20.0 | −4.88% | **−3.69%** | −1.06% | +0.01% | −0.14% | −0.0528 | **0.0163** | 0.7638 |
| hold 25m | 25.0 | −4.92% | −3.39% | −1.32% | +0.02% | −0.22% | −0.0529 | 0.0407 | 0.6621 |
| hold 30m | 29.8 | −3.77% | −2.22% | −1.58% | +0.02% | +0.00% | −0.0529 | 0.2077 | 0.9966 |
| hold 40m | 39.4 | −3.74% | −1.43% | −2.08% | +0.03% | −0.27% | −0.0527 | 0.4211 | 0.6288 |
| hold 50m | 48.9 | −4.76% | −2.35% | −2.57% | +0.05% | +0.11% | −0.0526 | 0.2394 | 0.8546 |
| hold 60m | 58.4 | −5.10% | −2.59% | −3.06% | +0.07% | +0.49% | −0.0525 | 0.2188 | 0.4649 |
| hold 75m | 72.5 | −8.33% | **−4.89%** | −3.80% | +0.11% | +0.25% | −0.0525 | 0.0296 | 0.7235 |
| hold 90m | 86.2 | −7.84% | −4.35% | −4.51% | +0.15% | +0.87% | −0.0523 | 0.0844 | 0.2575 |
| hold 120m | 113.2 | −6.16% | −2.09% | −5.91% | +0.25% | +1.58% | −0.0522 | 0.4755 | 0.0628 |
| clock 09:45 | 106.3 | −6.40% | −0.96% | −5.81% | +0.34% | +0.03% | −0.0546 | 0.6982 | 0.9538 |
| clock 10:00 | 90.0 | −4.71% | +0.41% | −4.86% | +0.22% | −0.48% | −0.0540 | 0.8709 | 0.4247 |
| clock 10:30 | 81.6 | −6.18% | −2.21% | −4.36% | +0.14% | +0.26% | −0.0534 | 0.3473 | 0.7117 |
| clock 11:00 | 92.2 | −6.30% | −2.41% | −4.88% | +0.19% | +0.80% | −0.0529 | 0.3656 | 0.3395 |
| clock 11:30 | 115.2 | −5.23% | −0.81% | −6.04% | +0.27% | +1.35% | −0.0525 | 0.7827 | 0.1154 |
| clock 12:00 | 134.7 | −5.65% | −1.01% | −7.05% | +0.40% | **+2.00%** | −0.0523 | 0.7531 | **0.0166** |
| clock 13:00 | 171.7 | −5.13% | −0.15% | −8.97% | +0.61% | **+3.38%** | −0.0523 | 0.9656 | **0.0001** |
| clock 14:00 | 218.3 | −5.38% | **+0.82%** | −11.45% | +0.88% | **+4.37%** | −0.0525 | 0.8170 | **<0.0001** |
| clock 14:30 | 242.8 | −4.69% | **+2.18%** | −12.78% | +1.07% | **+4.83%** | −0.0526 | 0.5629 | **<0.0001** |
| clock 15:00 | 270.6 | −5.09% | **+3.39%** | −14.39% | +1.31% | +4.59% | −0.0532 | 0.3837 | **<0.0001** |
| **close** | 298.4 | **−7.61%** | **+3.33%** | **−16.07%** | +1.58% | **+3.56%** | −0.0539 | 0.4160 | **0.0001** |

*(The clock rows use the full-sample convention, so their "held minutes" exceed the clock
because late fills run to the close — this is why clock 09:30 shows 136.8 minutes held. The clock rows are abbreviated here; the full set is in `gate_b_early_exit_decay_split.csv`.)*

### 3.3 What the split says

**An early exit wins entirely because it pays less decay, and it wins *despite* capturing a
worse directional move, not because of a better one.**

* **The decay leg is essentially linear at −0.0525% of premium per minute held**, stable to
  the third decimal across every horizon from 5 minutes to the close. That is the whole
  mechanism. Over a full 298-minute hold it comes to **−16.07%**. Over a 5-minute hold it is
  −0.26%. The difference between "hold 5m loses 1.49%" and "hold to close loses 7.61%" is
  15.8pp of decay avoided, offset by 4.5pp of *worse* spot outcome.
* **The spot leg is negative at every short horizon and turns positive only after 14:00.**
  It is −1.18% at 5 minutes, bottoms at −4.89% around 75 minutes (p=0.03, the only spot leg
  reaching nominal significance in either direction, and it is a *loss*), and does not become
  positive until the 14:00 clock. At the close it is **+3.33%**.
* So the money the trade eventually makes on direction — the +3.33% spot leg — is earned
  **after 13:00**, precisely in the period Aryan's rule would have skipped. It is simply not
  enough to pay a −16.07% decay bill.
* The **residual** leg (genuine implied-vol change plus BS mis-specification) is small and
  insignificant at every short horizon, and becomes significantly **positive** at long
  horizons (+3.38% at 13:00, p=0.0001; +3.56% at close, p=0.0001). Under a trading-time
  convention there is **no volatility drag** on this trade — the residual is a modest
  tailwind late in the session. This independently confirms the retraction in
  `CORRECTION_GATE_B_VOL_CRUSH.md`: the −8.3% "volatility leg" in
  `GATE_B_REAL_PREMIUM_VALIDATION.md` §3.3 was the calendar convention mis-labelling decay,
  and under a correct convention it reverses sign. **Time decay is the entire loss
  mechanism, exactly as Aryan said.**

The strategic implication is the opposite of an early exit, and it is worth stating plainly:
if decay is linear in time and the directional payoff arrives late, the fix is not to hold
for less time — it is to **stop paying decay**, i.e. to express the same signal in an
instrument that does not have a theta bill. That is the point already made in
`GATE_B_REAL_PREMIUM_VALIDATION.md` §9.8 and this decomposition strengthens it considerably.

---

## 4. (D) Multiplicity and placebo discipline

### 4.1 Variant count

**45 exit variants were tested in section A**: 1 baseline + 12 elapsed holds + 16 wall
clocks × 2 sample conventions. Separately and not included in that 45: 8 conditional
give-back diagnostics (§2.4), 1 window-efficiency test (§2.2), and the 12-bucket spot
description (§2.1), which is descriptive rather than a hypothesis test.

**Cumulative search on this population is larger than 45.** These same 120 trades were
already searched once by `gate_b_pooled_grid.py` (32 variants) and the mid-IV subset of them
by `gate_b_exit_grid_real.py` (39 variants). The corrections below apply to this script's 45;
the true family-wise burden across the project is heavier still.

### 4.2 Corrections

| test | count |
|---|---:|
| variants with raw p vs zero < 0.05 | **24 of 45** |
| …of which the mean is **negative** (a reliable loss) | **24 of 24** |
| surviving Bonferroni vs zero (α/45 = 1.11×10⁻³) | **1** — *a loss* (hold 75m, −8.33%, p=0.0003) |
| surviving Benjamini–Hochberg vs zero | **11** — *all losses* |
| variants with raw p vs the baseline < 0.05 | **0 of 44** |
| surviving Bonferroni vs baseline | **0** |
| surviving Benjamini–Hochberg vs baseline | **0** |

**Every single one of the 24 nominally significant results is a significant loss.** The one
variant that survives Bonferroni identifies the most reliably loss-making rule in the grid.
This is the same methodological trap flagged in `GATE_B_REAL_PREMIUM_VALIDATION.md` §5.1 and
it reappears here with more force: on this sample, selecting on |t| without checking the
sign hands back "hold 75 minutes and lose 8.3%".

### 4.3 Shuffled-label placebo, 5,000 draws, best-of-grid

Each draw reassigns the pooled Gate-B label at random among the **245** non-expiry gap-down
days whose gap fills after 09:17 and which are priceable on real traded premiums, then
re-runs the entire 45-variant grid and records the **best-of-grid** statistic — a
Westfall–Young style max-statistic correction. This preserves N=120, the CALL direction, the
gap-fill entry mechanism, the entry-time distribution and the whole exit machinery, and
destroys only the association with an overnight VIX rise. Seed 20260823.

| statistic | observed | placebo median | placebo tail | **empirical p** |
|---|---:|---:|---:|---:|
| best-of-grid p vs zero | 0.000314 | 0.001637 | 0.000016 (5th pct) | **0.2388** |
| best-of-grid p vs baseline | 0.095627 | 0.026095 | 0.000928 (5th pct) | **0.8226** |
| best-of-grid **mean return** | **−1.49%** | −0.81% | +0.75% (95th pct) | **0.8470** |

* At least one variant reaches nominal p<0.05 against zero in **97.7%** of placebo draws.
* At least one beats its own baseline at p<0.05 in **66.5%** of draws.

**Reading.** Nothing survives. The third row is the most direct answer to Aryan's question:
the best mean return anywhere in a 45-variant early-exit search on the real Gate-B
population is **−1.49%**, and a randomly relabelled set of 120 days produces a better
best-of-grid mean in **84.7%** of draws — the placebo's *median* best variant (−0.81%) beats
the real data's best variant. Whatever the early-exit search found, a coin-flip label finds
more of it.

**Stated limitation of this placebo, which is weaker here than in the 33-fire study.** The
pooled label is not very selective: 120 of the 245 pool days are actual fires, so a random
draw of 120 contains about 59 real fires on average. The placebo therefore has limited power
to separate the Gate-B population from its own complement. In the 33-fire study the overlap
was 33/263 = 12.5% and the placebo was correspondingly sharper. This does not weaken the
conclusion — the observed statistic is on the *wrong side* of the placebo median, which no
amount of overlap can manufacture — but it is not a strong discriminating test either.

---

## 5. (E) Power — what N=120 can and cannot detect

| quantity | value |
|---|---:|
| baseline hold-to-close | N=120, mean −7.61%, sd 45.1pp |
| 95% confidence interval | **[−15.76%, +0.55%]** |
| standardised effect detectable at 80% power, α=0.05 | 0.258 sd |
| **smallest mean return detectable** | **11.6 percentage points** |
| median paired sd of an early exit vs the baseline | 37.6pp |
| **smallest overlay improvement detectable** | **9.69 percentage points** |

For scale, at N=60 the detectable mean is 16.6pp and at N=30 it is 23.9pp. N=120 is roughly
twice as informative as the published N=33 study, and it is still not a large design.

**What this can detect.** A trade earning more than about 12pp of premium per fire, or an
early-exit rule improving on hold-to-close by more than about 10pp.

**What it cannot detect.** Anything smaller. The largest improvement over the baseline
anywhere in the grid is +6.12pp — below the 9.69pp threshold. **The entire spread of the
grid, best variant to worst, is 6.84pp, which is smaller than the smallest difference this
design can resolve.** So the ranking of exit rules within this table carries no information;
only the fact that all 45 are negative does.

**The honest boundary.** This is not a demonstration that early exits lose. The baseline's
own confidence interval reaches +0.55%, so a marginally break-even Gate B is not excluded.
What is established is:

1. every one of 45 point estimates is negative, gross and net;
2. no variant beats the incumbent at even a raw 5%;
3. the best-of-grid result loses to its own placebo at empirical p = 0.85;
4. the two things Aryan's hypothesis rests on — a mid-morning efficiency collapse, and
   early accumulation of favourable drift — are **measured directly on spot and are absent**,
   with the drift measurement pointing the opposite way at p = 0.004 to 0.04.

Points 1–3 are underpowered. Point 4 is not: it is a direct measurement on 120 days with
complete coverage, it does not depend on the option, and it is the part of the hypothesis
that could most cleanly have been true.

---

## 6. What I think is wrong, in both directions

Stated plainly, as asked. This includes things wrong in the existing work, not only in the
hypothesis.

1. **Aryan's directional intuition about the drift is inverted, and this is the load-bearing
   error.** He expects the trade to make money early and give it back. It loses money early
   (spot −0.05% to −0.08% from entry through 11:00, p = 0.004–0.04) and slowly recovers to
   flat by the close. Exiting before 11:30 crystallises the worst point of the spot path.
   The reason this does not show up as a large P&L penalty is that exiting early also avoids
   decay — the two roughly cancel, which is why every variant in the grid lands between −1.5%
   and −8.3% and none of them is distinguishable from any other.

2. **"Choppy" and "quiet" were being conflated.** The market genuinely does slow down
   mid-morning — realised volatility falls from 0.70 bp/min at 09:30 to 0.42 bp/min by
   11:30, a 40% decline, which is very likely what Aryan is perceiving from screen time.
   But path length falls in proportion, so directional efficiency does not change
   (0.1922 inside 10:30–11:30 vs 0.1854 outside, p = 0.56). A quiet market is not a hostile
   one for a directional position; it is simply a smaller one. What actually hurts is that
   decay keeps accruing at a constant −0.0525%/minute regardless of how much the index moves.
   **The enemy is the clock, not the chop** — and that is Aryan's own theta point, which is
   correct, applied consistently.

3. **Aryan is right about theta and this run strengthens his case, not weakens it.** The
   decay leg is −16.07% of premium over a full hold and is almost perfectly linear in trading
   time. Under the corrected trading-time convention there is **no volatility drag at all** —
   the residual leg is a *positive* +3.56% at the close, p = 0.0001. The "vol crush" story is
   not merely retracted, it reverses sign. Every remaining loss in Gate B is time decay
   plus a directional edge too small to pay for it.

4. **The correct inference from the theta finding is not "hold for less time" — it is "stop
   renting time".** If decay is linear at −0.0525%/min and the directional payoff arrives
   after 13:00, then shortening the hold cuts the cost *and* the payoff, which is what the
   grid shows. The strategy-level fix is a spot or futures expression of the same signal,
   where the +3.33% terminal spot leg is kept and the −16.07% decay bill is not paid. That
   is a different specification requiring its own approval, and it is the single cheapest
   honest next step for Gate B. `GATE_B_REAL_PREMIUM_VALIDATION.md` §9.8 already recommends
   it; this decomposition now gives it a measured magnitude.

5. **A caution about my own section 1.6, aimed at both of us.** "Hold 5 minutes" has the
   best mean *and* a very small p-value net of costs (−2.95%, p = 0.0009). It would be easy
   to read that as a finding. It is not: the small p reflects a small standard deviation
   (9.5pp vs the baseline's 45.1pp), not a real effect, and per minute held it is the
   fastest-bleeding rule in the grid. Any future work on this project should report
   loss-per-unit-time alongside total return whenever holding periods differ across variants,
   or the shortest horizon will always look artificially safe.

6. **The traded-only convention deserves a health warning in the module spec.** The published
   Gate-B clock figures use it, and it changes the population as the clock moves: mean entry
   09:19 at the 09:30 clock versus 10:18 at the 15:00 clock. Here it happens not to matter,
   because both conventions give the same answer. It could easily have mattered, and the spec
   quotes those figures without flagging it.

7. **Two things I have not established and will not claim.** First, this does not prove early
   exits lose — the baseline's confidence interval still touches zero and N=120 cannot resolve
   an effect below about 12pp. Second, these are one-minute bar closes, not executable fills;
   the spread is bounded in `GATE_B_REAL_PREMIUM_VALIDATION.md` §8 but not measured, and a
   five-minute hold pays the same round-trip cost as a full-day hold, so short-horizon rules
   are the most exposed to any cost mis-estimate. Both cut against confidence, not in favour
   of trading.

8. **A negative previous pass is not evidence for a negative new one.** This scan was run to
   test Aryan's hypothesis at a resolution the existing grid did not have, on a sample 3.6×
   larger, with the mechanism measured directly on spot rather than inferred from P&L. Had
   the mid-morning window existed, the efficiency test in §2.2 and the drift table in §2.3
   would have found it independently of any exit rule. They looked and it is not there.

---

## 7. Reproducibility

New artifacts only. No existing script, specification, or report was modified. No git commit
or push was performed. No broker, credential, network, or order path was used.

| File | Contents |
|---|---|
| `gate_b_early_exit_scan.py` | This entire study |
| `GATE_B_EARLY_EXIT_SCAN.md` | This report |
| `gate_b_early_exit_scan_results.json` | Machine-readable results, all sections |
| `gate_b_early_exit_grid.csv` | The 45-variant grid, both conventions |
| `gate_b_early_exit_spot_buckets.csv` | §2.1 half-hour spot buckets |
| `gate_b_early_exit_spot_cumulative.csv` | §2.3 cumulative spot drift by wall clock |
| `gate_b_early_exit_spot_elapsed.csv` | §2.3 spot drift by elapsed time |
| `gate_b_early_exit_premium_path.csv` | Mean real premium return by wall clock |
| `gate_b_early_exit_giveback.csv` | §2.4 give-back test |
| `gate_b_early_exit_bleed_rate.csv` | §1.6 loss per minute held |
| `gate_b_early_exit_decay_split.csv` | §3.2 decay-versus-delta split |

Reused unchanged: `gate_b_common.py` (paths, exit machinery, reproduction guard),
`gate_b_full_paths.py` (264-path full-hydration cache), `gate_b_exit_grid_real.py`
(`bh_reject`, `net_of_costs`, `summarise`), `bs_gap_fill_pnl.py` (`bs_call`,
`RISK_FREE_RATE`).

```text
.ml_venv/bin/python -m py_compile gate_b_early_exit_scan.py
.ml_venv/bin/python gate_b_early_exit_scan.py
```

The reproduction guard in `gate_b_common.py` runs first and passed: the 33 published Gate-B
fires, their entry clocks, strikes and Black-Scholes entry premiums, all three published
trailing-stop means, and every published fixed-clock figure are recovered before any new
result is computed.

**Correctness checks performed on this run, independently of the script's own output:**

| check | result |
|---|---|
| `hold 5m` recomputed from the raw path arrays with no helper | mean −1.4895%, median −2.2979%, win 39.2% — matches |
| `hold to close` recomputed from raw arrays | mean −7.6080%, median −13.2241%, win 38.3% — matches |
| trading-time maturity, hand-verified on 2021-09-08 | 372 min today + 375 min expiry session = 747 min = 1.992 sessions ✓ |
| implied-vol inversion re-prices the traded entry premium | max error **2.6 × 10⁻⁸** premium points over 120 trades |
| decomposition additivity, total = spot + decay + cross + residual | max residual **0.0000000000** pp |
| placebo pool composition | 245 of 264 priceable; all 120 fires inside the pool |

One defect was found and fixed during this run, in this script's own net-of-cost block:
pandas coerced a `None` offset to `NaN` on a mixed-type column, and `NaN is not None`, so
`rule_return` took the elapsed-horizon branch and exited clock variants at the entry minute
— producing net figures *better* than gross, which is impossible. Fixed by reading the
variant from the canonical list rather than from the DataFrame row, and re-run. The grid
itself never used the DataFrame path and was unaffected; the check that caught it was that
two different clock variants returned identical net values.

**Operational claim: nothing here authorises live use.** No live order exists or is
authorised, and this report is further evidence against arming Gate B.
