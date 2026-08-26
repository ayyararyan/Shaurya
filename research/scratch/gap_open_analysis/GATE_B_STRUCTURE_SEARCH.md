# Gate B: which option structure, if any, monetises the directional spot signal?

**Run date:** 2026-08-23
**Requested by:** Aryan. This is the study that `GATE_B_REAL_PREMIUM_VALIDATION.md` §9.8 and
`GATE_B_EARLY_EXIT_SCAN.md` §6.4 both named as the cheapest honest next step: stop varying
the exit on a long at-the-money CALL and vary the **instrument** instead.
**Task status:** **COMPLETE.** Every requested component ran: the spot edge in index points
(A), the break-even hurdle table (B), eleven structure families × seven horizons on real
strike-tracked traded premiums plus a modelled next-weekly arm (C), a trading-time Greek
decomposition (D), capital feasibility at ₹10,000 (E), multiplicity and a 5,000-draw
placebo (F), and power (G). Two components were added because the honest reading required
them: a **signed** best-of-grid placebo (§6.3) and a **censoring audit** (§8).

**Evidence class:** exploratory / instrument search on **observed traded prices**, with one
derived arm (futures) and one modelled arm (next weekly) that are labelled as such
everywhere and never pooled with the traded arms. Not identification-grade, not
manuscript-ready.

No broker, credential, exchange network, or order path was used. No live order exists or is
authorised. No pre-existing script or report was modified; every file listed in §10 is new.

---

## 0. Verdict

> **No structure monetises this signal, and the reason is now measured rather than
> suspected: there is no directional spot edge left to monetise at the moment the trade is
> entered.** Futures — zero theta, zero vega, pure delta, the cheapest possible wrapper and
> never run before on this population — earns a **gross ₹+375 per lot** on the mid-IV N=33
> population and **gross ₹−180** on the pooled N=120, against a round-trip cost of ₹507.
> Net: **−₹132 (p=0.91)** and **−₹694 (p=0.38)**. The clean measurement of the directional
> signal is indistinguishable from zero, and after costs it is negative.

That is the whole result, and everything below is consistent with it. If futures does not
make money, no option structure can rescue the signal, because every option structure is
futures plus a tax. The eleven families were still run in full, because "futures loses"
would not by itself rule out a *convex* structure that pays off on the tail of large moves,
and the hurdle table is the direct test of that possibility. It fails too.

**Zero of the 63 in-budget structure × horizon cells has a positive net mean, in either
population.** Of the 77 real-premium cells, **three** have a positive net mean on mid-IV and
**two** on pooled. Every one of them is a **short-premium** structure held to the close, and
every one needs about **₹1.9 lakh of SPAN margin** — nineteen times Aryan's budget.
§4 shows exactly why they make money, and it is not the direction: on mid-IV the short ATM
put earns **+₹1,058 of theta** against a delta leg of **+₹158**, and on pooled it earns
**+₹1,037 of theta** while its delta leg is **negative** at **−₹73**. It is a decay harvester
wearing the gate as a hat.

Three independent measurements agree, and none of them depends on an option:

| measurement | what a real directional edge predicts | what the data shows |
|---|---|---|
| mean spot move from entry, mid-IV N=33 | positive and growing with horizon | **−15.1 pts at 15m (p=0.015), −21.0 at 30m (p=0.003), +5.2 at the close (p=0.74)** |
| mean spot move from entry, pooled N=120 | positive | **−6.9 pts at 15m (p=0.027), −2.2 at the close (p=0.84)** |
| long futures, hold to close, net of costs | positive | **−₹132 (mid, p=0.91), −₹694 (pooled, p=0.38)** |

**The one thing that is genuinely new and that Aryan should take away:** the reason every
long CALL variant has lost in three consecutive studies is *not* primarily that options are
the wrong wrapper. It is that the underlying move is not there. `GATE_B_EARLY_EXIT_SCAN.md`
§3 established that decay costs −16.07% of premium over a full hold while the spot leg
returns only +3.33%, and the natural inference — which I made, twice — was "remove the decay
and you keep the +3.33%". **That inference is wrong, and this study is what shows it, for a
reason sharper than a size argument.**

The "+3.33% spot leg" is the *full option revaluation* P(S_H,T₀) − P(S₀,T₀), which is delta
**plus gamma**. In rupees it is **+₹711** per lot on mid-IV and **+₹486** on pooled. But
futures — the instrument that removes the theta bill — is **pure delta with no gamma**, and it
earns **+₹375** and **−₹180**. §4.2 shows where the rest went: on the pooled sample the long
ATM call's spot leg of +₹486 decomposes into a delta leg of **−₹92** and a gamma leg of
**+₹596**. **The spot leg is 123% gamma.** And gamma is precisely the thing theta is the price
of. You cannot remove the theta bill and keep the spot leg, because most of the spot leg *is*
what the theta bill was buying. What survives the removal is the delta leg alone. A full unit of
delta — which is what a future is — is worth **−₹161** gross on the pooled population and
**+₹394** on mid-IV before carry (**+₹375** after), against a **₹507** round trip.

---

## 1. (A) The directional spot edge, measured in index points, options entirely aside

Options can obscure a directional edge. Spot cannot. This section prices nothing.

### 1.1 Population and construction

Non-expiry day, NIFTY gapped down, India VIX rose overnight, gap fills at some minute
strictly after 09:17. Entry is the fill minute. "Favourable" means **up**, because the
signal is a reversal-continuation call.

* **mid-IV N=33** — opening IV in the 14–18 bucket. The published Gate B. Gap-fill
  direction hit rate **84.8%** (28/33, binomial p = 6.6×10⁻⁵ against a coin).
* **pooled N=120** — all three opening-IV buckets. Direction hit rate **56.7%** (68/120,
  binomial p = **0.171**), i.e. not distinguishable from a coin.
* Placebo pool: **264** non-expiry gap-down days whose gap fills after 09:17.

These two are reported separately throughout. **They are never pooled into one headline.**
The mid-IV 84.8% was found inside a 21-cell IV × condition scan and carries a Bonferroni-
corrected **p = 0.059** against that scan, so it is suggestive and not established. The
pooled 56.7% is what the same construction gives with no IV filter at all.

The reproduction guard in `gate_b_common.py` ran first and passed: the 33 published fires,
their entry clocks, strikes and Black-Scholes entry premiums are recovered before any new
number is computed.

### 1.2 Where spot actually goes after the fill — mid-IV N=33

All figures **index points** from the entry spot. Median entry spot 22,049, so 100 points is
0.45% of the index.

| horizon | mean held (min) | N | mean | median | Q1 | Q3 | p10 | p90 | up% | p vs 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 15m | 15 | 33 | **−15.1** | −11.5 | −21.5 | +1.4 | −48.3 | +18.5 | 33.3% | **0.0152** |
| 30m | 30 | 33 | **−21.0** | −14.7 | −39.9 | +5.5 | −80.9 | +20.8 | 36.4% | **0.0030** |
| 45m | 45 | 33 | **−16.6** | −13.7 | −37.6 | +6.6 | −76.8 | +44.6 | 30.3% | **0.0362** |
| 60m | 60 | 33 | −11.2 | −11.3 | −33.5 | +4.8 | −63.5 | +62.7 | 33.3% | 0.2158 |
| 90m | 90 | 33 | −17.4 | −12.8 | −43.8 | +3.2 | −89.8 | +66.0 | 30.3% | 0.1144 |
| 120m | 118 | 33 | −21.2 | −16.8 | −52.3 | +5.3 | −108.7 | +60.7 | 33.3% | 0.0669 |
| **close** | 314 | 33 | **+5.2** | −4.5 | −44.9 | +80.8 | −106.4 | +103.6 | **45.5%** | 0.7376 |

### 1.3 Pooled N=120

Median entry spot 22,791.

| horizon | mean held (min) | N | mean | median | Q1 | Q3 | p10 | p90 | up% | p vs 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 15m | 15 | 120 | **−6.9** | −3.1 | −21.5 | +14.4 | −47.6 | +28.4 | 46.7% | **0.0265** |
| 30m | 30 | 120 | **−9.9** | −2.3 | −37.6 | +22.2 | −79.7 | +38.0 | 47.5% | **0.0179** |
| 45m | 44 | 120 | −9.1 | −6.4 | −37.9 | +18.6 | −74.8 | +50.6 | 44.2% | 0.0501 |
| 60m | 58 | 120 | **−10.2** | −6.6 | −36.7 | +23.9 | −77.2 | +59.9 | 45.0% | **0.0449** |
| 90m | 86 | 120 | **−14.8** | −13.4 | −53.3 | +26.3 | −91.6 | +69.5 | 40.0% | **0.0262** |
| 120m | 113 | 120 | −11.5 | −13.0 | −53.1 | +36.9 | −107.8 | +80.9 | 42.5% | 0.1145 |
| **close** | 298 | 120 | **−2.2** | −16.7 | −70.0 | +63.2 | −120.4 | +130.5 | 44.2% | 0.8384 |

**Reading.** The mean favourable move is **negative at every horizon in both populations**,
significantly so through the first 45 minutes, and returns to approximately zero only by the
close. The index goes *down* after the gap fill and then grinds back. This reproduces
`GATE_B_EARLY_EXIT_SCAN.md` §2.3 exactly, in points rather than percent, and it is the
single fact that dooms every structure in this study.

Note the mid-IV close cell: **mean +5.2 points, median −4.5, up% 45.5, p = 0.74**. This is
the entire directional edge the 84.8% hit rate translates into, and it is 0.02% of the
index. Section 2 sets it against the hurdles.

### 1.4 Excursions — the case for a convex structure, and why it fails

If the terminal move is nil but the *path* is wide, a structure that harvests the excursion
could still work. So the excursions are measured directly.

| | mid-IV N=33 | pooled N=120 |
|---|---:|---:|
| MFE, mean | +59.2 pts | +71.4 pts |
| MFE, median | +33.5 | +48.1 |
| MFE, p90 | +127.7 | +156.1 |
| median minutes to the MFE | 102 | 86 |
| MAE, mean | **−86.5** | **−86.7** |
| MAE, median | −67.9 | −65.7 |
| MAE, p10 | −168.2 | −182.8 |
| median minutes to the MAE | 99 | 84 |

**The adverse excursion is larger than the favourable one in both populations, at the mean
and at the median.** MAE/MFE is 1.46× on mid-IV and 1.21× on pooled. A long structure on
this population sits further underwater than it ever gets above water, and the two happen at
almost the same time of day (102 vs 99 minutes on mid-IV). There is no window in which the
favourable excursion is systematically available first.

### 1.5 How often does spot ever reach +X points, and when?

| threshold | mid-IV: ever reached | n | median min to first touch | mid-IV adverse −X ever reached |
|---|---:|---:|---:|---:|
| +25 | 57.6% | 19 | 51 | **81.8%** |
| +50 | 42.4% | 14 | 158 | 60.6% |
| +75 | 36.4% | 12 | 228 | 48.5% |
| +100 | 27.3% | 9 | 231 | 33.3% |
| +150 | 6.1% | 2 | 348 | 18.2% |
| +200 | 3.0% | 1 | 358 | 9.1% |

| threshold | pooled: ever reached | n | median min to first touch | pooled adverse −X ever reached |
|---|---:|---:|---:|---:|
| +25 | 66.7% | 80 | 29 | **76.7%** |
| +50 | 47.5% | 57 | 73 | 58.3% |
| +75 | 34.2% | 41 | 113 | 46.7% |
| +100 | 27.5% | 33 | 166 | 35.8% |
| +150 | 11.7% | 14 | 206 | 18.3% |
| +200 | 6.7% | 8 | 257 | 8.3% |

**At every threshold in both populations, the adverse level is reached more often than the
favourable one.** On mid-IV the index touches −25 on 81.8% of fires and +25 on 57.6%. This
is the population the 84.8% "direction hit rate" describes; the hit rate is a statement
about whether the reversal eventually happens, not about whether it happens before the
opposite move, and this table is the difference between those two statements.

Also note the timing: on mid-IV the median first touch of +50 is at **158 minutes** and of
+75 at **228 minutes**. Any structure large enough to need those moves must be held most of
the session to get them, which is exactly the holding period that costs the most decay.

---

## 2. (B) The hurdle table — the calculation that matters most

**How many index points must spot move for the structure to break even, set against the
measured distribution of how far spot actually moves?**

The hurdle is computed **per trade**: each leg's implied volatility is held at its own entry
value (inverted from that leg's own traded entry price, so the observed smile is respected),
trading time is advanced from entry to the horizon, and the root of
`structure value at horizon = entry cost (+ transaction costs)` is solved in spot. Every
structure here is long delta, so the root is unique. "P(clear)" is the share of trades whose
**actual** spot move at that horizon reached **that trade's own** hurdle — it is not a
model probability.

Options settle on the index, so their hurdle is a spot move directly. **Futures are closed at
a futures price, not at spot**, so the futures leg is valued at `S × F/S(horizon)` — see §9.6,
where the first run of this script got that wrong.

### 2.1 Hold to close — mid-IV N=33

Median absolute terminal spot move on this population: **73.3 points**. Mean signed terminal
move: **+5.2 points**.

| structure | N | hurdle gross (pts) | hurdle net (pts) | P(clear) gross | P(clear) net | capital (mid-IV median) |
|---|---:|---:|---:|---:|---:|---|
| **long NIFTY futures** | 33 | **+0.3** | **+7.2** | **45.5%** | **42.4%** | ₹1.98 L |
| long deep ITM call ~0.85δ | 31 | +14.1 | +17.4 | 35.5% | 35.5% | ₹22,095 |
| long ITM call ~0.70δ | 33 | +23.7 | +25.5 | 39.4% | 39.4% | ₹14,531 |
| long ATM call | 33 | **+34.6** | **+37.0** | 36.4% | 36.4% | ₹7,590 |
| long OTM call ~0.30δ | 33 | **+49.1** | **+53.5** | 33.3% | 33.3% | ₹3,514 |
| bull call spread 1 strike | 33 | +5.4 | **+41.8** | 42.4% | 33.3% | ₹1,901 |
| bull call spread 2 strikes | 33 | +9.6 | +28.1 | 42.4% | 39.4% | ₹3,514 |
| bull call spread 3 strikes | 33 | +13.5 | +28.2 | 42.4% | 39.4% | ₹4,733 |
| short OTM put ~0.25δ | 33 | **−52.9** | **−48.4** | **75.8%** | **75.8%** | ₹1.92 L |
| short ATM put | 33 | −30.7 | −27.8 | 66.7% | 60.6% | ₹1.85 L |
| risk reversal +0.30c/−0.25p | 33 | +3.0 | +8.1 | 42.4% | 42.4% | ₹1.96 L |

### 2.2 Hold to close — pooled N=120

Median absolute terminal move **69.6 points**; mean signed terminal move **−2.2 points**.

| structure | N | hurdle gross (pts) | hurdle net (pts) | P(clear) gross | P(clear) net |
|---|---:|---:|---:|---:|---:|
| **long NIFTY futures** | 120 | **+0.3** | **+7.4** | **44.2%** | **43.3%** |
| long deep ITM call ~0.85δ | 108 | +14.0 | +17.6 | 35.2% | 33.3% |
| long ITM call ~0.70δ | 118 | +23.1 | +26.1 | 39.0% | 38.1% |
| long ATM call | 120 | +33.2 | +36.1 | 36.7% | 36.7% |
| long OTM call ~0.30δ | 119 | +49.1 | +52.9 | 33.6% | 32.8% |
| bull call spread 1 strike | 120 | +6.1 | **+43.1** | 43.3% | **30.8%** |
| bull call spread 2 strikes | 119 | +9.6 | +28.6 | 43.7% | 37.0% |
| bull call spread 3 strikes | 119 | +13.0 | +26.6 | 42.0% | 38.7% |
| short OTM put ~0.25δ | 114 | −49.4 | −45.3 | **67.5%** | **65.8%** |
| short ATM put | 120 | −28.7 | −25.3 | 58.3% | 55.0% |
| risk reversal +0.30c/−0.25p | 113 | +3.8 | +8.9 | 40.7% | 40.7% |

### 2.3 Thirty minutes, both populations — where the hurdle is cheapest

| structure | mid: hurdle net | mid: P(clear) net | pooled: hurdle net | pooled: P(clear) net |
|---|---:|---:|---:|---:|
| long NIFTY futures | +7.0 | 24.2% | +7.1 | 39.2% |
| long deep ITM call ~0.85δ | +5.3 | 33.3% | +5.7 | 40.2% |
| long ITM call ~0.70δ | +5.4 | 27.3% | +5.8 | 40.8% |
| long ATM call | +6.1 | 27.3% | +6.4 | 40.0% |
| long OTM call ~0.30δ | +8.6 | 24.2% | +8.7 | 38.3% |
| bull call spread 1 strike | **+37.2** | **0.0%** | **+42.7** | **10.0%** |
| bull call spread 2 strikes | +18.7 | 6.1% | +20.8 | 23.3% |
| bull call spread 3 strikes | +13.3 | 9.1% | +14.3 | 29.2% |
| short OTM put ~0.25δ | +0.4 | 36.4% | +0.2 | 46.2% |
| short ATM put | +0.7 | 36.4% | +0.7 | 47.5% |

### 2.4 What the hurdle table says, in order of importance

**(i) The futures hurdle is the smallest number in the entire study, and it is still not
cleared.** Gross **+0.3 points** — that is only the intraday decay of the cost of carry, and
it is as close to a free instrument as exists. Net of costs it is **+7.2 points**, which is
just the ₹507 round trip expressed in index points (507/75 = 6.76). Against a distribution
whose mean terminal move is +5.2 points on mid-IV and −2.2 on pooled, a 7-point hurdle is
already binding. **P(clear) net at the close is 42.4% on mid-IV and 43.3% on pooled.** The
cheapest possible expression of this signal is a coin flip that costs you 7 points to enter.

Internal consistency check: futures P(clear) **gross** at the close is **45.5%** on mid-IV,
which is *identical* to the independently computed "up%" in §1.2. It has to be — a gross
futures break-even is a zero spot move — and it is, which is a check on the whole hurdle
machinery.

**(ii) Buying a long option multiplies the hurdle by five to fifteen times.** A long ATM call
held to the close needs **+34.6 points** on mid-IV where the mean move is +5.2. That is a
**6.6× hurdle**, and it is why every long-CALL exit rule in three studies has lost. Going
further out of the money makes it strictly worse (+49.1 points, cleared 33.3% of the time),
because an OTM call buys more gamma per rupee but needs more points to pay for the same time.
Going in the money makes it better (+14.1 points for 0.85δ) but never below the futures
hurdle, and costs ₹22,845 of capital to do it.

**(iii) The bull call spread is the trap of this study, and its hurdle is where the trap is
visible.** Its *gross* hurdle is tiny — **+5.4 points** on mid-IV, second only to futures —
because the debit is small and the structure barely decays. Its *net* hurdle is **+41.8
points**, the second largest in the table. The reason is that a one-strike-wide ATM spread
has a net delta of about **0.11**, so the ₹249 round-trip cost (3.3 index points of premium)
requires roughly **30 points of spot** to earn back. **A cheap structure is not a cheap
trade.** At 30 minutes the one-strike spread's net hurdle is **+37.2 points and it is cleared
on 0 of 33 mid-IV fires and 12 of 120 pooled fires.** Aryan's budget points directly at these
structures and they are the worst cost-per-unit-delta in the entire table.

**(iv) The only structures whose hurdle the market reliably clears are the ones with a
negative hurdle.** The short OTM put can afford spot to *fall* 52.9 points and still break
even, and 75.8% of mid-IV fires clear that. That is not a directional edge — it is the
statement that a 0.25-delta put sold with a session to run usually expires worthless. §4
confirms it: the money is theta, not delta.

---

## 3. (C) Structure ranking — P&L in rupees per lot of 75

Rupees per lot is the primary metric here, because a percentage cannot compare a ₹8,550
debit against a ₹1.9 lakh margin position against a credit structure — the denominators are
different objects. §3.4 gives the percentage tie-back for the long-premium arms.

Every leg is priced from the **one-minute bar close of the actual contract, looked up by
absolute strike**. No labelled-ATM series. Costs: half-spread 0.35% of premium with a floor
of 0.25 index points per leg per side (the floor matters — a proportional spread badly
understates the cost of a cheap OTM weekly, which is exactly where a false positive would
be manufactured); brokerage ₹20 per order; STT 0.10% on option sells and 0.02% on futures
sells; NSE 0.03503% (options) / 0.00173% (futures) each side; stamp on the buy side; SEBI
₹10/crore; GST 18% on brokerage and transaction charges. Multi-leg structures pay these
**once per leg**. The pessimistic column uses a 1.00% half-spread with a 0.75-point floor,
and 1.00 point on futures.

### 3.1 Hold to close, real traded premiums — mid-IV N=33

| structure | N | cov | gross ₹ | **net ₹** | net median | win% | p vs 0 | 95% CI | net pess ₹ | capital ₹ | fits ₹10k? |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|:--:|
| **short ATM put** | 33 | 100% | +1,074 | **+953** | +1,794 | 69.7% | 0.1408 | [−332, +2,237] | +841 | 187,435 | **no** |
| **short OTM put ~0.25δ** | 33 | 100% | +762 | **+669** | +929 | **75.8%** | **0.0474** | [+8, +1,331] | +593 | 192,396 | **no** |
| risk reversal | 33 | 100% | +312 | +127 | −359 | 39.4% | 0.8266 | [−1,041, +1,295] | −27 | 198,177 | no |
| **long NIFTY futures** | 33 | 100% | **+375** | **−132** | −784 | 42.4% | 0.9103 | [−2,507, +2,243] | −245 | 198,443 | no |
| bull call spread 1 strike | 33 | 100% | −6 | −255 | −323 | 36.4% | **0.0362** | [−493, −17] | −489 | 1,901 | **YES** |
| bull call spread 2 strikes | 33 | 100% | −20 | −259 | −195 | 36.4% | 0.2555 | [−714, +197] | −480 | 3,514 | **YES** |
| bull call spread 3 strikes | 33 | 100% | −32 | −264 | −407 | 39.4% | 0.4108 | [−910, +381] | −477 | 4,733 | **YES** |
| long OTM call ~0.30δ | 33 | 100% | −449 | −543 | −1,151 | 33.3% | 0.1305 | [−1,255, +170] | −620 | 3,514 | **YES** |
| long ITM call ~0.70δ | 33 | 100% | −457 | −643 | −1,780 | 39.4% | 0.4727 | [−2,445, +1,159] | −848 | 14,531 | no |
| long ATM call *(incumbent)* | 33 | 100% | −550 | −681 | −1,642 | 39.4% | 0.3070 | [−2,018, +655] | −807 | 7,590 | **YES** |
| long deep ITM call ~0.85δ | 31 | 94% | −768 | −1,029 | −1,814 | 35.5% | 0.3118 | [−3,071, +1,013] | −1,344 | 22,095 | no |

### 3.2 Hold to close, real traded premiums — pooled N=120

| structure | N | cov | gross ₹ | **net ₹** | net median | win% | p vs 0 | 95% CI | net pess ₹ | fits ₹10k? |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|:--:|
| **short ATM put** | 120 | 100% | +412 | **+287** | +603 | 60.8% | 0.4971 | [−548, +1,122] | +172 | no |
| **short OTM put ~0.25δ** | 114 | 95% | +136 | **+43** | +448 | 64.0% | 0.8403 | [−383, +470] | −34 | no |
| long OTM call ~0.30δ | 119 | 99% | −332 | −427 | −951 | 32.8% | 0.0581 | [−869, +15] | −507 | **YES** |
| bull call spread 1 strike | 120 | 100% | −75 | −327 | −352 | 30.8% | **0.0000** | [−437, −217] | −563 | **YES** |
| bull call spread 2 strikes | 119 | 99% | −124 | −364 | −413 | 37.8% | **0.0012** | [−582, −147] | −588 | **YES** |
| bull call spread 3 strikes | 119 | 99% | −179 | −413 | −464 | 39.5% | **0.0108** | [−729, −97] | −629 | **YES** |
| risk reversal | 113 | 94% | −366 | −551 | −613 | 38.9% | 0.0792 | [−1,167, +65] | −705 | no |
| **long NIFTY futures** | 120 | 100% | **−180** | **−694** | −1,791 | 43.3% | 0.3823 | [−2,261, +873] | −807 | no |
| long ATM call *(incumbent)* | 120 | 100% | −564 | −696 | −1,481 | 38.3% | 0.0980 | [−1,523, +130] | −823 | **YES** |
| long ITM call ~0.70δ | 118 | 98% | −860 | −1,045 | −1,592 | 39.8% | **0.0448** | [−2,065, −25] | −1,248 | no |
| long deep ITM call ~0.85δ | 108 | 90% | −1,773 | **−2,027** | −1,872 | 36.1% | **0.0008** | [−3,191, −863] | −2,333 | no |

**The deep-ITM and risk-reversal rows on the pooled sample are censoring artifacts and must
not be read at face value.** See §8; the corrected figures are −₹753 and −₹198, still
negative.

### 3.3 The full grid, counted

| | mid-IV N=33 | pooled N=120 |
|---|---:|---:|
| cells tested (11 families × 7 horizons, + 10 families × 7 on the modelled next weekly) | 147 | 147 |
| …priced on **real traded premiums** | 77 | 77 |
| …**model-based** (next weekly; the archive is WEEK1 only) | 70 | 70 |
| cells with a **positive net mean** | **5** | **3** |
| …of those, on real traded premiums | **3** | **2** |
| …of those, **affordable at ₹10,000** | **0** | **0** |
| **in-budget cells with a positive net mean, out of 63** | **0 / 63** | **0 / 63** |

The five positive mid-IV cells are: short ATM put @ close (+₹953), short OTM put @ close
(+₹669), short OTM put @ close *[next weekly, modelled]* (+₹357), short ATM put @ close
*[next weekly, modelled]* (+₹335), risk reversal @ close (+₹127). Every one is short
premium, held to the close, and needs about ₹1.9 lakh.

### 3.4 Percentage tie-back to the published Gate-B numbers

Percent of entry debit, hold to close, so these can be checked against existing reports.

| structure | mid-IV gross % | mid-IV net % | pooled gross % | pooled net % |
|---|---:|---:|---:|---:|
| **long ATM call** *(the published trade)* | **−6.08%** | −7.59% | **−7.61%** | −9.08% |
| long ITM call ~0.70δ | −2.82% | −4.06% | −6.01% | −7.23% |
| long deep ITM call ~0.85δ | −2.67% | −3.78% | −6.46% | −7.54% |
| long OTM call ~0.30δ | −11.58% | −14.35% | −10.75% | −13.48% |
| bull call spread 1 strike | −1.23% | **−14.45%** | −4.49% | **−17.78%** |
| bull call spread 2 strikes | −1.83% | −8.74% | −4.32% | −11.26% |
| bull call spread 3 strikes | −2.25% | −7.15% | −4.76% | −9.69% |

**−6.08% and −7.61% reproduce `CORRECTION_GATE_B_VOL_CRUSH.md` and
`GATE_B_EARLY_EXIT_SCAN.md` §1.3 to the second decimal**, independently, through a different
code path. That is the strongest single check in this report that the pricing machinery here
is the same machinery that produced the published figures.

The bull-call-spread rows are the clearest statement of the cost trap in percentage terms:
gross −1.23% becomes net **−14.45%**, a 13-point cost drag on a structure that costs ₹1,886.
The moment the metric is rupees rather than percent it becomes obvious why — ₹249 of cost on
₹1,886 of capital is 13%, and on the ₹8,550 ATM call the same order of cost is 1.5%.

---

## 4. (D) Greek decomposition under a trading-time maturity

Maturity is **trading time** everywhere: 375 minutes per session (09:15–15:30), 252 sessions
per year, counting only sessions between the trade date and the expiry date. Hand-verified
on the first fire, 2021-09-08, entry 09:18, expiry 2021-09-09: 372 minutes remaining today +
375 for the expiry session = **747 minutes**, matching `GATE_B_EARLY_EXIT_SCAN.md` §3.
Implied volatilities under this convention are **lower in level** than market-quoted ones and
are **not** comparable to the calendar-convention numbers in
`GATE_B_REAL_PREMIUM_VALIDATION.md`. That is the whole point of
`CORRECTION_GATE_B_VOL_CRUSH.md`.

Each leg's **exit** implied volatility is re-inverted from its own traded exit price at the
trading-time maturity remaining, so the vega leg is **measured, not assumed**. The residual
carries higher-order terms, cross terms and Black-Scholes mis-specification, and is reported
rather than assumed away.

### 4.1 Hold to close, rupees per lot — mid-IV N=33 (mean 314 minutes held)

| structure | N | realised | delta | gamma | theta | vega | residual | γ+θ carry | p carry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| long ATM call | 33 | −550 | +240 | +496 | **−1,283** | +163 | −166 | **−787** | <0.001 |
| long ITM call ~0.70δ | 33 | −457 | +256 | +420 | −1,216 | +262 | −179 | −797 | <0.001 |
| long deep ITM call ~0.85δ | 31 | −768 | −208 | +271 | −962 | +433 | −302 | −690 | <0.001 |
| long OTM call ~0.30δ | 33 | −449 | +180 | +429 | −1,050 | +171 | −179 | −621 | <0.001 |
| bull call spread 1 strike | 33 | −6 | +9 | +8 | −39 | +1 | +15 | −31 | <0.001 |
| bull call spread 2 strikes | 33 | −20 | +27 | +46 | −127 | +9 | +26 | −81 | <0.001 |
| bull call spread 3 strikes | 33 | −32 | +55 | +105 | −247 | +30 | +26 | −142 | <0.001 |
| **short OTM put ~0.25δ** | 33 | **+762** | +79 | −353 | **+934** | +53 | +49 | +581 | <0.001 |
| **short ATM put** | 33 | **+1,074** | +158 | −448 | **+1,058** | +303 | +4 | +610 | <0.001 |
| risk reversal | 33 | +312 | +259 | +77 | −117 | +223 | −130 | −40 | <0.001 |
| **long NIFTY futures** | 33 | **+375** | **+394** | **0** | **0** | **0** | −19 | 0 | — |

### 4.2 Hold to close — pooled N=120 (mean 298 minutes held)

| structure | N | realised | delta | gamma | theta | vega | residual | γ+θ carry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| long ATM call | 120 | −564 | **−92** | +596 | **−1,309** | +404 | −163 | −713 |
| long ITM call ~0.70δ | 118 | −860 | −408 | +472 | −1,235 | +567 | −255 | −763 |
| long deep ITM call ~0.85δ | 108 | −1,773 | −1,472 | +284 | −945 | +657 | −297 | −661 |
| long OTM call ~0.30δ | 119 | −332 | +65 | +491 | −1,061 | +365 | −192 | −569 |
| bull call spread 1 strike | 120 | −75 | −39 | +0 | −38 | −22 | +24 | −38 |
| bull call spread 2 strikes | 119 | −124 | −53 | +25 | −115 | −12 | +32 | −90 |
| bull call spread 3 strikes | 119 | −179 | −70 | +69 | −219 | +2 | +39 | −150 |
| **short OTM put ~0.25δ** | 114 | **+136** | **−291** | −369 | **+867** | −190 | +120 | +498 |
| **short ATM put** | 120 | **+412** | **−73** | −564 | **+1,037** | −94 | +106 | +474 |
| risk reversal | 113 | −366 | −468 | +71 | −152 | +234 | −51 | −81 |
| **long NIFTY futures** | 120 | **−180** | **−161** | **0** | **0** | **0** | −19 | 0 |

### 4.3 What the decomposition says

**(i) Futures is the clean measurement, and it says the signal is worth ₹394 gross on
mid-IV and −₹161 on pooled.** Its decomposition is trivial by construction — delta only,
plus a −₹19 residual which is the intraday decay of the cost of carry — and that is the
point. **₹394 per lot on a ₹16.5 lakh notional, before a ₹507 round trip.** Everything else
in these tables is that number, taxed.

**(ii) Aryan's theta hypothesis is confirmed again, at a fourth measurement.** For the long
ATM call the theta leg is **−₹1,283** on mid-IV and **−₹1,309** on pooled, against a delta
leg of +₹240 and −₹92. The gamma-theta carry is negative for every long-premium structure at
p < 0.001, and positive for every short-premium one. **The enemy is the clock**, as
`GATE_B_EARLY_EXIT_SCAN.md` §6.2 put it.

**(iii) But removing theta does not produce a profit, and this is the new finding.** The
natural reading of "theta is −₹1,283 and delta is +₹240" is that an instrument with no theta
earns +₹240. It earns **+₹394 gross, −₹132 net**. The long call's positive delta leg is not a
profit waiting to be liberated — it is smaller than the cost of the trade that would
liberate it. Two studies' worth of "express this in futures instead" ends here, measured.

**(iv) The short puts are not monetising the signal. They are monetising the calendar.**
Short ATM put, mid-IV: realised **+₹1,074** = delta **+₹158** + gamma −₹448 + theta
**+₹1,058** + vega +₹303. Theta is 98% of the realised P&L. On the pooled sample the delta
leg is **negative** (−₹73) and the structure still makes **+₹412**, because theta is
**+₹1,037**. **A structure that makes money while its directional leg loses money is not
evidence for the direction signal.** It is a short-volatility carry trade that happens to have
been switched on by a gate. That gate could be replaced by a coin and the theta would still
be collected — which is precisely what the placebo in §6.3 finds.

**(v) The bull call spreads are Greek-neutral to the point of being uninformative.** Every
leg — delta, gamma, theta, vega — is single or double digits in rupees. A one-strike spread
transfers about ₹75 of total Greek exposure per lot. That is the structural reason its cost
hurdle is 30 points of spot: it is barely a position at all, and the transaction cost does
not shrink to match.

---

## 5. (E) Capital feasibility at ₹10,000, and the out-of-budget winners

Lot size **75**. Budget **₹10,000**. Margin for naked short options and futures is taken at
**12% of notional**, which is an **assumption carried through the study, not a measurement
from this dataset** — it is the central case for SPAN + exposure on a NIFTY lot at an Indian
broker and it lands at ₹1.85–1.98 lakh, consistent with the ₹1.5–2.5 lakh band the brief
specified. Debit structures require the debit; a fully covered debit spread is treated as its
debit, which is generous to the spread and does not change any conclusion.

| structure | capital kind | median ₹ | Q1 | Q3 | max | share of fires affordable at ₹10k | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| bull call spread 1 strike | debit | **1,886** | 1,785 | 1,995 | 2,471 | **100.0%** | AVAILABLE |
| bull call spread 2 strikes | debit | **3,488** | 3,242 | 3,723 | 4,444 | **100.0%** | AVAILABLE |
| long OTM call ~0.30δ | debit | **3,690** | 2,771 | 4,826 | 11,302 | **99.6%** | AVAILABLE |
| bull call spread 3 strikes | debit | **4,804** | 4,297 | 5,212 | 6,236 | **100.0%** | AVAILABLE |
| long ATM call | debit | **8,550** | 6,540 | 11,304 | 26,310 | **64.3%** | AVAILABLE |
| long ITM call ~0.70δ | debit | 14,897 | 11,096 | 19,680 | 34,852 | 19.1% | OUT OF BUDGET |
| long deep ITM call ~0.85δ | debit | 22,845 | 16,583 | 29,729 | 45,945 | 4.6% | OUT OF BUDGET |
| short ATM put | margin | **185,176** | 153,534 | 211,227 | 232,230 | **0.0%** | OUT OF BUDGET |
| short OTM put ~0.25δ | margin | **192,023** | 157,372 | 217,071 | 234,840 | **0.0%** | OUT OF BUDGET |
| risk reversal | margin | 195,634 | 159,755 | 222,106 | 236,711 | 0.0% | OUT OF BUDGET |
| **long NIFTY futures** | margin | **195,776** | 159,623 | 220,825 | 237,060 | **0.0%** | OUT OF BUDGET |

*This table is computed on the full 264-day pool, so its medians differ by a few percent from
the population-specific capital columns in §2.1 and §3.1. Nothing turns on the difference.*

### 5.1 The out-of-budget winners, flagged explicitly as the brief requires

**There are two, and they should be reported honestly and then not acted on.**

| | short ATM put, hold to close | short OTM put ~0.25δ, hold to close |
|---|---|---|
| mid-IV N=33, net | **+₹953** per lot, p = 0.1408, win 69.7% | **+₹669** per lot, p = **0.0474**, win **75.8%** |
| mid-IV total over 33 fires, 4.5 years | **+₹31,433** | **+₹22,093** |
| pooled N=120, net | +₹287, p = 0.4971 | +₹43, p = 0.8403 |
| capital required | **₹185,176** | **₹192,023** |
| **capital as a multiple of the ₹10,000 budget** | **18.5×** | **19.2×** |
| return on capital, mid-IV, per fire | +0.51% | +0.35% |
| net under the pessimistic cost model | +₹841 | +₹593 |

**This is a legitimate result and it is worth stating plainly: the only structures in a
147-cell search that made money need about twenty times the money Aryan has.** But three
things must be said in the same breath, and they are why this is not a recommendation:

1. **They do not monetise the signal.** §4.3(iv): the short ATM put's realised P&L is 98%
   theta, and on the pooled sample its delta leg is *negative*. Selling a put has nothing to
   do with the gap-fill direction call.
2. **Neither survives multiplicity, and neither beats its own placebo.** §6. The short OTM
   put's raw p = 0.047 sits against a Bonferroni threshold of 3.4×10⁻⁴, and the signed
   best-of-grid placebo puts the *best cell in the entire grid* at empirical p = **0.109**
   (mid) and **0.160** (pooled).
3. **They collapse out of sample-of-convenience.** Going from the 33-fire mid-IV population
   to the 120-fire pooled one, the short ATM put falls from +₹953 to +₹287 and the short OTM
   put from +₹669 to +₹43. A real effect should not lose 93% of its size when the sample
   quadruples.

**And a fourth, which is the one that matters for risk, and which the mean conceals.** A
naked short put on a gap-down-plus-VIX-up day is short volatility into a market that has just
moved and whose implied volatility has just risen. §1.5 shows the index reaches −100 points on
33.3% of mid-IV fires. The realised single-day losses in the short-ATM-put arm:

| | worst day | 2nd worst | 3rd worst | mean | sd |
|---|---|---|---|---:|---:|
| mid-IV N=33 | **−₹10,330** (2023-01-04, −198 pts) | −₹4,623 (2023-07-24, −116) | −₹4,141 (2024-07-10, −109) | +₹953 | ₹3,623 |
| pooled N=120 | **−₹23,441** (2026-03-11, −448 pts) | −₹12,988 (2026-01-23, −266) | −₹10,330 (2023-01-04, −198) | +₹287 | ₹4,620 |

**One day in this sample lost ₹23,441 on a single lot** — 2.3× the entire budget and 82× the
pooled mean gain. (2026-03-11 is the −448-point day; §8 shows it is also the one day censored
out of the long-OTM-call, 2-strike and 3-strike spread arms, so it is a real and identified
outlier, not a data error.) On the mid-IV population, **three days like 2023-01-04 would erase
the entire 4.5-year profit of ₹31,433**, and the arm only has 33 fires in it. **Do not read this table as "get more capital and sell puts".**

### 5.2 The in-budget picture

**Zero of 63 in-budget cells has a positive net mean, in either population.** The
least-negative in-budget results:

| population | best in-budget cell | net ₹ | p | capital |
|---|---|---:|---:|---:|
| mid-IV N=33 | bull call spread 1 strike @ close | **−255** | 0.0362 | ₹1,886 |
| mid-IV N=33 | bull call spread 2 strikes @ close | −259 | 0.2555 | ₹3,488 |
| mid-IV N=33 | bull call spread 3 strikes @ close | −264 | 0.4108 | ₹4,804 |
| pooled N=120 | bull call spread 1 strike @ 15m | **−284** | <0.0001 | ₹1,898 |
| pooled N=120 | long OTM call ~0.30δ @ 15m | −294 | <0.0001 | ₹3,750 |

The mid-IV "best" cell has p = 0.0362 — **a nominally significant loss**, which is the same
selection trap flagged in `GATE_B_REAL_PREMIUM_VALIDATION.md` §9.6 and
`GATE_B_EARLY_EXIT_SCAN.md` §4.2. Ranking on |t| without checking the sign would hand back
"buy a one-strike bull call spread and reliably lose ₹255".

**What this means for Aryan concretely.** At ₹10,000 he can afford exactly the wrong half of
the instrument ladder: the structures whose cost-per-unit-delta is highest. The structure
this study identifies as least bad — futures, gross +₹375 on mid-IV — requires ₹1.96 lakh.
The gap between "the edge is real" and "you can trade it" is not the issue here, because the
edge is not real either; but if it ever became real, this table is the constraint that would
still bind.

---

## 6. (F) Multiplicity and the shuffled-label placebo

### 6.1 Search size

**147 structure × horizon cells per population, 294 in total.** 77 per population on real
traded premiums, 70 model-based. **Cumulative search on this population is far larger than
147:** `gate_b_exit_grid_real.py` searched 39 exit variants on the mid-IV 33,
`gate_b_pooled_grid.py` 32 on the pooled 120, `gate_b_early_exit_scan.py` 45, and the IV
subgroup scan 21 cells. The corrections below apply to this script's 147; the project-wide
family-wise burden is heavier still and no correction here accounts for it.

### 6.2 Corrections against zero

| test | mid-IV N=33 | pooled N=120 |
|---|---:|---:|
| cells with raw p < 0.05 | **110 of 147** | **126 of 147** |
| …of which the mean is **positive** | **1** | **0** |
| …of which the mean is **negative** (a reliable loss) | **109** | **126** |
| surviving Bonferroni (α/147 = 3.40×10⁻⁴) | **42** | **58** |
| …**positive** among Bonferroni survivors | **0** | **0** |
| surviving Benjamini–Hochberg | **102** | **122** |
| …**positive** among BH survivors | **0** | **0** |
| smallest-p cell | bull call spread 1 strike *[next weekly]* @ 15m, **−₹401**, p < 10⁻⁵ | same cell, **−₹378**, p < 10⁻⁵ |

**Every single Bonferroni and BH survivor in both populations is a loss.** The single cell
with the smallest p-value in a 147-cell search is a structure that reliably loses ₹401. This
is now the third study in this project where selecting on |t| would select a loss-maker.

### 6.3 The shuffled-label placebo, 5,000 draws, seed 20260823

Each draw reassigns the gate label at random among the **264** non-expiry gap-down days whose
gap fills after 09:17, preserving N, the entry mechanism, the entry-time distribution,
chronology and the whole structure/exit machinery, and destroying only the association with
the gate condition.

**The min-p best-of-grid statistic is degenerate on this grid and I am reporting that rather
than quoting it as if it were informative.** Observed best-of-grid p and placebo median
best-of-grid p both round to 0.00000, and **a random label reaches p < 0.05 somewhere in the
grid in 100.0% of draws**. The reason is structural: min-p is won by whichever cell has the
smallest variance, and on this grid the lowest-variance cells are the bull call spreads,
which are reliable *losses*. A max-|t| correction cannot discriminate here. Empirical
best-of-grid p came out 0.2884 (mid) and 0.8028 (pooled) — both null — but the statistic is
not doing useful work either way.

So a **signed** best-of-grid statistic was added: the **largest cell mean** across all 147
cells, which is the statistic that actually answers "what is the best P&L a search of this
size finds on this population".

| statistic | mid-IV N=33 | pooled N=120 |
|---|---|---|
| observed best cell | short ATM put @ close | short ATM put @ close |
| observed best-of-grid **mean** | **+₹953** | **+₹287** |
| placebo best-of-grid mean, **median** | +₹172 | **+₹0** |
| placebo best-of-grid mean, **95th pct** | +₹1,321 | +₹494 |
| **empirical p** | **0.1094** | **0.1602** |

**Reading: the best structure found anywhere in a 147-cell search does not beat what a random
relabelling of the same days finds, at 5%.** A coin-flip gate produces a best-of-grid mean
above +₹953 in 10.9% of draws on a sample of 33, and above +₹287 in 16.0% of draws on a
sample of 120. That is the disciplined version of the §5.1 result and it is why the
out-of-budget winners are reported and then set aside.

### 6.4 Gate conditioning on the incumbent trade

Long ATM call, hold to close, net rupees:

| | mid-IV N=33 | pooled N=120 |
|---|---:|---:|
| observed | −₹681 | −₹696 |
| placebo mean | −₹836 | −₹831 |
| placebo 5th / 95th | −₹1,945 / +₹319 | −₹1,300 / −₹359 |
| share of random labels at or above observed | **40.1%** | **31.6%** |

The gate is worth about ₹150 per trade against a random label and lands at the 40th/32nd
percentile of its own placebo — i.e. it is on the better side of random by an amount that is
nowhere near significance. This reproduces the direction of
`GATE_B_REAL_PREMIUM_VALIDATION.md` §7's "37th percentile of its own placebo" finding.

### 6.5 Stated weakness of this placebo

On the pooled arm, 120 of 264 pool days are genuine fires, so a random draw of 120 contains
about 55 real fires on average, and the placebo has limited power to separate the population
from its complement. On the mid-IV arm the overlap is 33/264 = 12.5% and the placebo is
correspondingly sharper. Neither observed statistic is on the significant side of its
placebo, and the pooled one is *below* its placebo median on the headline cell, which no
amount of overlap can manufacture — but this is not a strongly discriminating test on the
pooled arm and should not be quoted as one.

---

## 7. (G) Power — what these designs can and cannot detect

| quantity | mid-IV N=33 | pooled N=120 |
|---|---:|---:|
| standardised effect detectable at α=0.05, 80% power | **0.503 sd** | **0.258 sd** |
| long ATM call, hold to close: sd | ₹3,769 | ₹4,572 |
| → **smallest detectable mean, ATM call** | **₹1,896** | **₹1,179** |
| long futures, hold to close: sd | ₹6,698 | ₹8,670 |
| → **smallest detectable mean, futures** | **₹3,369** | **₹2,235** |
| observed ATM-call mean (bootstrap 95% CI, 10,000 draws) | −₹681 [−₹1,931, +₹574] | −₹696 [−₹1,489, +₹133] |
| observed futures mean | −₹132 | −₹694 |

**This is the honest boundary of the whole study and it must be read before anything else in
it is believed.**

**Futures is the least powerful arm in the design, not the most.** Its standard deviation is
₹6,698 on 33 fires and ₹8,670 on 120 — nearly twice the ATM call's — because a long option
truncates the downside and a future does not. So the smallest futures effect this design can
detect at 80% power is **₹3,369 per lot on mid-IV and ₹2,235 on pooled**. A genuinely
profitable futures expression of this signal earning, say, **₹1,500 per lot** would be
**invisible** to this test. **This study does not demonstrate that futures loses money on
Gate B.** What it establishes is narrower and should be stated exactly:

1. the point estimate is **−₹132** (mid) and **−₹694** (pooled), both negative net;
2. gross, before any cost, it is **+₹375** and **−₹180**, so even with zero friction the
   mid-IV point estimate is under ₹400 per lot;
3. the direct spot measurement underneath it — §1.2, which does not depend on the option,
   the future, the cost model or the margin assumption — is **negative at every horizon in
   both populations** and significantly so through 45 minutes.

Points 1–2 are underpowered. **Point 3 is not.** It is a direct measurement of the index on
33 and 120 days with complete coverage, and it is the part of the premise that could most
cleanly have been true.

For scale, to detect a ₹500-per-lot futures edge at 80% power on this variance would need
roughly **N ≈ 2,400 fires**. At the observed fire rate (120 fires in 264 candidate days over
about 4.5 years) that is **on the order of 90 years of data**. This is not a design problem
that more careful analysis fixes.

---

## 8. Added component: the censoring audit — a real bias I found in my own numbers

The local minute archive stores option files by **relative** strike, ATM−10 … ATM+10 of the
**running** at-the-money. A structure whose entry strike sits several strikes from spot
therefore drops **out** of the hydrated band as soon as spot travels far enough, and becomes
unpriceable at the exit. **That censoring is not random — it is triggered by exactly the
large favourable moves this study is trying to measure.**

Hold-to-close, pooled N=120, listing every arm that lost any day:

| arm | priced n | mean ΔS on priced days | **censored n** | **mean ΔS on censored days** | censored days' ΔS |
|---|---:|---:|---:|---:|---|
| long deep ITM call ~0.85δ | 108 | **−23.2** | **12** | **+187.4** | +41, +55, +73, +135, +152, +207, +213, +217, +228, +254, +263, +411 |
| risk reversal | 113 | −12.4 | 7 | +162.7 | −448, +213, +217, +228, +254, +263, +411 |
| short OTM put ~0.25δ | 114 | −16.2 | 6 | **+264.4** | +213, +217, +228, +254, +263, +411 |
| long ITM call ~0.70δ | 118 | −7.6 | 2 | +319.4 | +228, +411 |
| long OTM call / bcs2 / bcs3 | 119 | +1.6 | 1 | −447.6 | −448 |
| long ATM call, bcs1, short ATM put, **futures** | 120 | −2.2 | **0** | — | — |

**All twelve days dropped from the deep-ITM arm are up-days, and all six dropped from the
short-OTM-put arm are the six largest up-days in the sample.** The deep-ITM arm's
priced subsample has a mean move of −23.2 points against −2.2 for the full population. That
is not a small distortion; it is the reason the deep-ITM row in §3.2 reads −₹2,027, worse
than everything else in the table.

### 8.1 Bounding it

Re-pricing **only the censored legs** with Black-Scholes at that leg's own entry implied
volatility and the trading-time maturity remaining — **a model fill, not tape, labelled as
such** — gives:

| arm | traded-only gross ₹ | **BS-filled gross ₹** | bias ₹ | BS-filled **net** ₹ | BS-filled net p |
|---|---:|---:|---:|---:|---:|
| long deep ITM call ~0.85δ | −1,773 | **−477** | **+1,295** | **−753** | 0.26 |
| risk reversal | −366 | **−10** | +356 | **−198** | 0.61 |
| short OTM put ~0.25δ | +136 | **+373** | +236 | **+279** | 0.18 |
| long ITM call ~0.70δ | −860 | −558 | +302 | −748 | 0.15 |
| bull call spread 2 strikes | −124 | −110 | +13 | −352 | <0.001 |
| bull call spread 3 strikes | −179 | −175 | +4 | −410 | 0.01 |
| long OTM call ~0.30δ | −332 | −383 | −50 | −477 | 0.03 |
| *(all other arms, mid-IV and pooled)* | *unchanged* | *unchanged* | **0** | | |

**The direction of the bias is against the long structures and against the short put, i.e. my
§3.2 table understates them.** Corrected: deep ITM goes from −₹2,027 to −₹753 and its
p-value from 0.0008 to 0.26 — **the "deep ITM is catastrophically the worst" reading in
§3.2 is an artifact and should be discarded.** The short OTM put improves from +₹43 to
+₹279, still nowhere near significance.

**What survives the correction, and this is the point:** every long-premium structure is
still negative, no structure becomes significant, and **the four arms with a positive net
mean anywhere are unchanged** — long ATM call, bull call spread 1 strike, short ATM put and
**futures all have 100% coverage on both populations and are not censored at all.** The
verdict in §0 rests on uncensored arms. The censored arms are reported with both numbers and
neither is used to support a conclusion.

### 8.2 What cannot be computed and is therefore labelled unidentified

* **The next-weekly arm is a model scenario, not a measurement.** The archive contains
  **WEEK1 contracts only** (verified: all 2,772 manifest rows are `expiry_flag=WEEK,
  expiry_code=1`). The 70 next-weekly cells per population re-price the same strikes at a
  maturity five sessions longer using the WEEK1 entry implied volatility. That means (a) the
  weekly IV **term structure is assumed flat**, which it is not, and (b) the arm's implied
  volatility cannot change between entry and exit **by construction**, so its residual leg is
  identically zero and it can express no volatility effect at all. It is reported separately,
  never pooled with the traded arms, and it produces no positive result anyway. **Whether a
  next-weekly expiry helps is, on this archive, unidentified.**
* **The futures leg is derived, not observed.** No futures tape exists in the local archive.
  `F = S·exp(0.02·τ)` with τ in calendar years to the monthly expiry. Real NIFTY basis
  fluctuates around fair carry; a deterministic carry model makes the futures P&L essentially
  the spot P&L plus a −₹19 carry-decay term. **This is the largest single modelling
  assumption in the study and it sits underneath the headline verdict.** It biases the level
  of the futures result by an unknown amount that is almost certainly small relative to the
  ₹6,698 standard deviation, but it is an assumption and not a measurement.
* **The 12%-of-notional margin is an assumption**, stated as such in §5 and in the script.
  Nothing in this dataset measures SPAN. Every conclusion that depends on it is a
  *feasibility* statement, not a P&L statement, and none of the P&L results depend on it.

---

## 9. What I think is wrong, in both directions — including in my own work

1. **The premise this study was built on — "remove the theta bill and keep the +3.33% spot
   leg" — is wrong, and it was my own previous report's recommendation, made twice.**
   `GATE_B_EARLY_EXIT_SCAN.md` §3.3 and §6.4 and `GATE_B_REAL_PREMIUM_VALIDATION.md` §9.8 all
   concluded that the fix was a futures or spot expression of the same signal. **The error is
   not a size error, it is a category error, and it is worth being precise about because the
   same reasoning will reappear.**

   The decomposition's "spot leg" is the full option revaluation P(S_H,T₀) − P(S₀,T₀). That
   quantity is **delta plus gamma**. Futures is **delta only**. So the spot leg is not the
   futures P&L and never was, and the two are not close:

   | | mid-IV N=33 | pooled N=120 |
   |---|---:|---:|
   | option "spot leg", exact repricing, ₹/lot | **+711** | **+486** |
   | …of which delta (§4) | +240 | **−92** |
   | …of which gamma (§4) | **+496** | **+596** |
   | long futures, gross, ₹/lot | **+375** | **−180** |

   **On the pooled population the spot leg is +₹486 while its delta component is −₹92: the
   leg is 123% gamma.** Gamma is exactly what theta is the price of — they are the two sides
   of the same trade. So "remove the theta bill and keep the spot leg" asks to keep the good
   half of a matched pair and discard the bill for it, which is not an available transaction
   in any market. What actually survives removing theta is the delta leg alone, and the delta
   leg is **negative** on 120 fires.

   A secondary and more ordinary error compounded it: the +3.33% was **percentage-normalised**
   by an entry debit that the alternative instrument does not have, so it could not be compared
   across instruments at all. The general lesson, which `GATE_B_EARLY_EXIT_SCAN.md` §6.5
   half-stated and did not apply: **a decomposition normalised by a denominator that differs
   across the alternatives being ranked cannot rank them** — and separately, **a Greek leg is
   not a strategy, because Greeks come in bundles that the market prices jointly.**

   **This is the single most important thing in this report, and it is a correction to my own
   prior work, not to Aryan's.**

2. **Aryan is still right about theta, and this is now four independent confirmations.** The
   theta leg is −₹1,283 per lot on the mid-IV long ATM call at p < 0.001, gamma-theta carry
   is negative for every long-premium structure and positive for every short one, and under
   the corrected trading-time convention there is no volatility drag anywhere. Nothing here
   walks that back.

3. **What is wrong with the "84.8% hit rate" is now measurable rather than rhetorical.**
   `GATE_B_REAL_PREMIUM_VALIDATION.md` §9.3 said the hit rate "is not a P&L statistic".
   §1.5 above says *why*, in points: on the same 33 fires, the index touches **−25 points on
   81.8%** of them and +25 on 57.6%; MAE is 1.46× MFE. The gate predicts that a reversal
   eventually happens. It does not predict that it happens **before** the opposite move, and
   for a position with a stop, a margin call, or a human watching it, those are entirely
   different claims. The 84.8% number and the −86.5-point mean adverse excursion are not in
   conflict; they are answers to different questions, and only one of them is the trading
   question.

4. **I made a real error in the first run of this script and it was in the headline
   number.** `breakeven_move` valued a futures leg at the horizon as **spot**, while valuing
   it at entry as a **futures price**. The root-finder therefore returned the entire
   cost-of-carry **basis** as a hurdle: the first run reported a futures gross hurdle of
   **+18.7 points** on mid-IV and +19.0 on pooled, when the correct answer is **+0.3**. That
   is the single most important cell in the study and it was wrong by a factor of sixty. It
   was caught because a futures gross break-even *must* be a zero spot move, so P(clear)
   gross *must* equal the "up%" in §1.2 — 45.5% — and in the first run it did not (39.4%).
   After the fix it does, exactly. The fix is in `gate_b_structure_search.py:carry_mult` and
   `breakeven_move(..., fut_mult)`; the P&L was never affected, only the hurdle. **Anyone
   reading the first-run log `run1.log` should discard its futures hurdle rows.** The general
   lesson: a derived instrument needs its price function used on **both** ends of every
   calculation it appears in, and the cheapest guard is an identity that must hold exactly.

5. **My §3.2 pooled table contains a censoring artifact that I would have reported as a
   finding if I had not checked.** "Deep ITM call loses ₹2,027, p = 0.0008, the worst
   structure in the study" is a sentence I nearly wrote. It is false: the arm is missing the
   twelve largest up-days because they moved the strike out of the archive's ±10-strike
   hydration band, and corrected it loses ₹753 at p = 0.26. §8 exists because the delta leg
   in §4.2 (−₹1,472 for a 0.85-delta structure when the population mean move is −2.2 points)
   was arithmetically impossible and had to be chased. **Any future work on this archive must
   check coverage against the size of the move, not just the coverage percentage** — 90%
   coverage sounds benign and was not.

6. **The bull call spread is the most dangerous structure in this table for someone with
   ₹10,000, and the danger is invisible in percentage terms.** Its gross return is the best
   of any long structure (−1.23% on mid-IV), it costs ₹1,886, it fits the budget with room to
   spare, and it is the obvious thing to reach for. Net it returns −14.45%, because a ₹249
   round trip against a net delta of 0.11 needs 30 points of spot to clear. **Cheap structures
   have the worst cost-per-unit-delta**, and a budget constraint pushes directly toward them.
   If Aryan takes one practical thing from this report other than the verdict, it should be
   this.

7. **Two things I have not established and will not claim.** First, **this is not a
   demonstration that futures loses money on Gate B.** §7: the design cannot resolve a futures
   effect below ₹3,369 (mid) or ₹2,235 (pooled) per lot, and a genuinely profitable ₹1,500
   edge would be invisible. The negative point estimate is weak evidence; the negative
   **spot** measurement in §1.2 is much stronger evidence, and it is the one to rely on.
   Second, **these are one-minute bar closes, not executable fills.** The half-spread is
   bounded by the base and pessimistic cost models and is not measured. Structures with more
   legs and cheaper legs are the most exposed to a cost mis-estimate, and those are exactly
   the in-budget ones. Both cut against confidence, not in favour of trading.

8. **A negative previous pass is not evidence for a negative new one, and this run was
   genuinely capable of overturning the incumbent.** Futures had never been run on this
   population. Had there been a directional edge, futures would have shown it with no theta,
   no vega and no strike selection to argue about, and §2 would lead with a cleared hurdle
   instead of an uncleared one. The instrument ladder was run in full — deep ITM, ITM, ATM,
   OTM, three spread widths, two short puts, a risk reversal, on the nearest weekly and on a
   modelled next weekly, at seven horizons each, on both populations. Nothing was dropped to
   make the answer come out. The answer came out anyway.

9. **What would actually change the verdict.** Not another exit rule, not another structure,
   and not a different expiry — those are now searched to the point where the multiplicity
   burden exceeds the information content. It would take either (a) a **different entry**,
   because §1.2 says the edge is not present at the gap-fill minute, which is a different
   signal and a different specification; or (b) a **conditioning variable that separates the
   fires which move from those which do not**, tested prospectively rather than found in the
   same 264 days that have now been searched several hundred times. **The one thing that
   would not help is more capital**, because §5.1's out-of-budget winners do not monetise the
   signal either.

---

## 10. Reproducibility

New artifacts only. No pre-existing script, specification, or report was modified. No git
commit or push was performed. No broker, credential, network, or order path was used.

| File | Contents | Status |
|---|---|---|
| `gate_b_structure_search.py` | The main study, sections A–G | pre-existing from this task; **patched twice, see §9.4 and §6.3** |
| `gate_b_structure_search.py.orig` | The as-received script, before both patches | new |
| `GATE_B_STRUCTURE_SEARCH.md` | This report | new |
| `gate_b_structure_search_results.json` | Machine-readable, all sections | new |
| `gate_b_structure_hurdles.csv` | §2, all 77 real-premium cells × 2 populations | new |
| `gate_b_structure_ranking.csv` | §3, all 147 cells × 2 populations | new |
| `gate_b_structure_decomposition.csv` | §4, Greek split | new |
| `gate_b_structure_capital.csv` | §5, capital feasibility | new |
| `gate_b_structure_censoring.py` / `.csv` | §8, the censoring audit | new |
| `verify_structure_search.py` | Independent recomputation of six headline quantities | new |
| `gate_b_structure_quotes.pkl` | CALL+PUT minute cache, 4,159,602 bars over 264 dates | new cache |
| `run1.log`, `run2.log` | Pre-fix and post-fix console output | new |

Reused unchanged: `gate_b_common.py`, `gate_b_full_paths.py`, `bs_gap_fill_pnl.py`.

```text
.ml_venv/bin/python -m py_compile gate_b_structure_search.py
.ml_venv/bin/python gate_b_structure_search.py          # ~9 min after the quote cache exists
.ml_venv/bin/python gate_b_structure_censoring.py
.ml_venv/bin/python verify_structure_search.py
```

### 10.1 Changes made to the as-received script, and why

The script had never been executed. It ran to completion on the first attempt with **no
runtime errors**; both changes below are correctness fixes found by auditing the output, not
fixes to make it run. Neither narrows the specification, drops a structure family, or shrinks
a grid — the cell count is 147 per population before and after.

1. **`carry_mult()` extracted; `breakeven_move()` gained `fut_mult`.** §9.4. The futures leg
   is now valued at the horizon as `S × F/S(horizon)` instead of as `S`. Affects the futures
   hurdle rows and `cleared_gross`/`cleared_net` for futures only. All P&L is unchanged
   (verified: §3 tables are bit-identical between `run1.log` and `run2.log`, as is all of
   section A).
2. **`best_of_grid_mean()` added and reported in section F.** §6.3, an **addition**. The
   pre-existing min-p best-of-grid placebo turned out degenerate on this grid and the signed
   statistic was needed to say anything honest about multiplicity. The original min-p
   statistic is still computed and still reported.

### 10.2 Correctness checks performed independently of the script's own output

`verify_structure_search.py` recomputes each of these from the raw path and quote caches
without reusing the study's evaluation code:

| check | expected | got |
|---|---|---|
| trading-time maturity, first fire 2021-09-08 09:18 → expiry 2021-09-09 | 747 minutes | **747** ✓ |
| mid-IV mean terminal spot move × 75 | should bound futures gross | **+₹394** vs futures gross **+₹375** (difference = −₹19 carry decay) ✓ |
| pooled mean terminal spot move × 75 | as above | **−₹161** vs futures gross **−₹180** ✓ |
| futures gross P&L, independently recomputed | matches §3 | mid **+₹375**, pooled **−₹180** ✓ exact |
| futures gross break-even spot move, independently recomputed | ≈0 | **+0.257 / +0.272 pts** vs script's +0.3 ✓ |
| futures round-trip cost, hand-built from the statutory rates | matches gross − net | **₹519** at S=22,049 vs implied ₹507 at the actual median ✓ |
| futures P(clear) gross at close **must** equal §1.2 up% | 45.5% / 44.2% | **45.5% / 44.2%** ✓ exact |
| long ATM call, hold to close, % of entry premium | published −6.08% / −7.61% | **−6.08% / −7.61%** ✓ exact |
| reproduction guard on the 33 published fires | pass | **PASSED** |

The last two are the load-bearing ones: the study reproduces the published Gate-B headline
figures to the second decimal through an independent code path, and the futures hurdle
satisfies an identity it could only satisfy if the hurdle machinery is correct.
