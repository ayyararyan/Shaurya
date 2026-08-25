# Clipping H3: does the 09:20 short straddle survive being made affordable and safe?

**Date:** 2026-08-23 · **Status:** exploratory offline analysis · **Frozen specification:** `TAIL_CLIP_SPEC.md`
**No broker, credentials, order path, live trading, or Gate A / Gate B change. No gate armed.**
Scripts: `tail_clip_test.py`, `tail_clip_paths.py`. Artifacts: `tail_clip_results.json`,
`tail_clip_panel.csv`, `tail_clip_paths.pkl`.

---

## Owner summary

Aryan's question: H3 (sell the ATM straddle at 09:20 on a non-expiry session, buy it back at 15:29)
screened positive but has two disqualifying problems — the margin is far beyond a ₹10,000 account,
and the tail is catastrophic. Can both be clipped?

**Both are fixed, completely, by buying the wings — and the edge that survives is smaller than the
cost of trading it.**

- **Tail:** bounded by construction. Worst session goes from **−₹26,494 to −₹6,352** (150-point
  iron butterfly). Max drawdown from **−₹90,975 to −₹9,949**.
- **Margin:** the capital at risk falls from roughly **₹1.5–2.5 lakh** of SPAN + exposure on a naked
  straddle to a **median ₹2,539** of defined risk. That is the whole point of a hedged position:
  it is margined on its worst case, and the worst case is now small.
- **Return on capital improves about 16×** — from ~0.26% per session naked to **4.3% per session**
  defined-risk.
- **Year stability improves too, and this was not obvious:** the naked straddle lost money in 2026
  (−₹78/session); **every defined-risk variant is positive in all six years.** Cutting the tail
  removes the single days that ate whole years.
- **But the wings eat about 86% of the gross edge.** On the same sessions the naked straddle earned
  ₹648; the 150-point fly keeps **₹89**. What is left is **below the round-trip cost of eight option
  orders.** Breakeven is a half-spread of **₹0.15 per unit per leg** (₹0.26 at 200-point wings)
  against a realistic NIFTY weekly half-spread of ₹0.25–0.75, and a breakeven brokerage of
  **₹11–20 per order** against roughly ₹20 flat at a discount broker.

**Bottom line:** the wings convert an unaffordable, untradeable edge into an affordable, still
untradeable one. **Action needed from Aryan:** none — this is a screening result on an exploratory
lead. If he wants to push further, the one honest next step is a real quote-based cost study
(bid–ask at 09:20 and 15:29 for ATM and ATM±3), because the entire verdict now rests on a cost
assumption rather than on the edge.

---

## 1. What was tested

Every non-expiry session with a full set of legs at both clocks, 2021-01 → 2026-05.
Entry 09:20, exit 15:29, traded closes, one lot of 75, absolute strikes throughout.

- **S0** — naked short ATM straddle (the H3 incumbent).
- **IF(w)** — iron butterfly: short ATM straddle, long ATM ± 50w. w ∈ {1,2,3,4,5,6,8,10}.
- **IC(b,w)** — iron condor: short ATM ± 50b, long ATM ± 50(b+w). b ∈ {1,2}, w ∈ {2,3,4}.

Registered family = 14 structures. **Bonferroni threshold 0.00357.**

**Reproduction guard (VAL-01): S0 recovers H3 exactly** — mean 2.235224% of entry premium on
N = 1,040, against the published 2.235224% on N = 1,040. Absolute difference **1.1 × 10⁻⁷ pp**.

## 2. Two data limits that decide which cells are usable — found before reading results

**(a) Wide wings are a biased sample.** The archive stores ATM−10…ATM+10 relative to a *rolling*
ATM. If spot moves during the session, a wing struck at 09:20 can fall outside the chain by 15:29 —
so **the sessions with missing wings are exactly the big-move sessions, which are exactly the
straddle seller's losing sessions.** The bias is monotone and severe:

| structure | sessions available | % of 1,040 | S0's mean on *those* sessions |
|---|---:|---:|---:|
| IF(w=1) | 1,033 | 99.3% | ₹485 |
| IF(w=3) | 1,027 | 98.8% | ₹648 |
| IF(w=4) | 1,015 | 97.6% | ₹761 |
| IF(w=6) | 954 | 91.7% | ₹1,102 |
| IF(w=8) | 734 | 70.6% | ₹1,813 |
| IF(w=10) | 176 | 16.9% | **₹2,557** |

S0's true full-sample mean is **₹456**. Anything at w ≥ 5 is measuring a hand-picked set of quiet
days. **All w ≥ 5 cells are discarded.**

**(b) Narrow wings are measurement noise.** `close` is the last *traded* price in the minute, not a
quote, so two strikes 50 points apart can be stamped minutes apart. At w = 1 the entire structure is
worth at most ₹50 per unit, and **56 of 1,033 sessions record a loss larger than the structure's own
maximum possible loss** — an impossibility, not a market event. w = 2 has 7. Sessions where the
measured credit exceeded the wing width (a riskless arbitrage, which does not exist) were
quarantined first: 6 at w = 1, 1 at w = 2, **0 everywhere else**. **w = 1 and w = 2 flies are
discarded as unmeasurable with this data.**

**Usable window: IF(w=3), IF(w=4), IC(b=1,w=2), IC(b=1,w=3), IC(b=2,w=2).** Availability ≥ 97.6%,
at most one accounting violation each.

## 3. Headline — the usable structures

Rupees per lot per session. `medML` is the median defined risk = the margin proxy. RoR = P&L / defined risk.

| structure | n | mean ₹ | median ₹ | win | p | medML ₹ | mean RoR | RoR mean/sd | worst ₹ | max DD ₹ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **S0 naked straddle** | 1,040 | **455.7** | 1,170 | 67.3% | 0.00005 | ~150,000–250,000 (SPAN) | ~0.26% | — | **−26,494** | **−90,975** |
| IF(w=3) 150-pt fly | 1,027 | 89.1 | 165 | 64.5% | 0.00007 | **2,539** | **4.27%** | 0.167 | −6,352 | −9,949 |
| IF(w=4) 200-pt fly | 1,015 | 157.6 | 296 | 65.8% | <0.00001 | 4,425 | 4.32% | 0.209 | −6,862 | −13,875 |
| IC(b=1,w=2) | 1,027 | 83.2 | 165 | 64.7% | 0.00001 | 2,239 | 4.68% | 0.184 | −5,561 | −8,216 |
| IC(b=1,w=3) | 1,015 | 149.0 | 266 | 66.4% | <0.00001 | 4,121 | 4.46% | 0.218 | −6,071 | −14,516 |
| IC(b=2,w=2) | 1,015 | 103.2 | 206 | 64.4% | <0.00001 | 3,274 | 3.90% | 0.196 | **−3,698** | −13,639 |

All clear the 0.00357 Bonferroni threshold. **Every defined-risk structure fits a ₹10,000 account at
one lot** on the median session; the naked straddle does not fit at any size.

**The tail is genuinely fixed.** IC(b=2,w=2) has the best of it: worst session −₹3,698 against the
naked −₹26,494, a **7× reduction**, and it is bounded by construction rather than by luck.

## 4. What the wings cost — the matched comparison

Same sessions, same entry minute; the only difference is the two long legs.

| structure | S0 on the same sessions | structure | wings cost | share of gross edge kept |
|---|---:|---:|---:|---:|
| IF(w=3) | ₹648 | ₹89 | **₹559** | **13.8%** |
| IF(w=4) | ₹761 | ₹158 | ₹603 | 20.7% |
| IC(b=1,w=2) | ₹648 | ₹83 | ₹564 | 12.8% |
| IC(b=2,w=2) | ₹761 | ₹103 | ₹658 | 13.6% |

This is the volatility risk premium working against you on the other side of the trade. You sell an
overpriced ATM straddle and you buy overpriced wings — and on NIFTY the downside wing is bought at a
*higher* implied volatility than the ATM leg you sold, because of put skew. `FOLKLORE_BATTERY_TEST.md`
H7 already documents that far-OTM buyers lose ~92% of premium on expiry day; the same premium is what
you pay here for the insurance.

**The trade-off in one line: the wings cost ~86% of the profit and reduce the capital by ~40×.**
On return-on-capital that is a large win; on absolute rupees it is a large loss. Which one matters
depends entirely on costs, which is the next section.

## 5. Where it dies — transaction costs

A four-leg structure pays eight option orders per session (four in, four out) against the naked
straddle's four. The edge that must cover them is one fifth the size.

| structure | legs | mean ₹ | breakeven **half-spread**, ₹ per unit per leg | breakeven **brokerage**, ₹ per order |
|---|---:|---:|---:|---:|
| S0 naked straddle | 2 | 455.7 | **1.52** | 113.9 |
| IF(w=3) | 4 | 89.1 | **0.15** | 11.1 |
| IF(w=4) | 4 | 157.6 | 0.26 | 19.7 |
| IC(b=1,w=2) | 4 | 83.2 | 0.14 | 10.4 |
| IC(b=2,w=2) | 4 | 103.2 | 0.17 | 12.9 |

A NIFTY weekly ATM option typically quotes ₹0.5–1.5 wide, i.e. a half-spread of **₹0.25–0.75**;
the wings are thinner and proportionally wider. Discount brokerage is around **₹20 flat per order**.

**Every defined-risk cell is at or below breakeven on brokerage alone, before a single paisa of
spread.** The naked straddle has ₹1.52 per unit of room — but cannot be funded or survived.
That is the whole result: **the two problems and the edge are the same object, and removing the
problems removes the edge.**

## 6. Year stability — the one place the wings genuinely help

Mean ₹ per session, by year:

| structure | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | negative years |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 naked | 589 | 374 | 243 | 338 | 908 | **−78** | 1 |
| IF(w=3) | 90 | 11 | 39 | 144 | 163 | 85 | **0** |
| IF(w=4) | 139 | 118 | 69 | 245 | 250 | 68 | **0** |
| IC(b=1,w=3) | 118 | 128 | 70 | 242 | 228 | 43 | **0** |
| IC(b=2,w=2) | 90 | 94 | 50 | 158 | 159 | 8 | **0** |

`FOLKLORE_BATTERY_TEST.md` flagged H3 as carried by 2025 with a negative 2026. Truncating the tail
removes that: every defined-risk variant is positive in all six years.

**Do not over-read this.** It is the same underlying edge with the outliers cut off, so lower
year-to-year variance is partly mechanical, not independent confirmation. But it does say the
positive mean is not one year's accident — it is present, small, every year.

## 7. The stop-loss lever, for comparison (ROB-01)

An intraday stop on the *naked* straddle, triggered when the combined premium rises by 25/50/100%
of entry, using the minute path of the **one contract** that was at the money at 09:20.

| variant | n | mean ₹ | win | worst ₹ | max DD ₹ | margin |
|---|---:|---:|---:|---:|---:|---|
| no stop | 1,044 | 400.9 | 67.0% | −26,494 | −90,975 | unchanged |
| stop at +25% | 1,044 | 340.0 | 63.8% | **−14,651** | −56,021 | **unchanged** |
| stop at +50% | 1,044 | 405.7 | 66.4% | −24,019 | −48,304 | **unchanged** |
| stop at +100% | 1,044 | 413.3 | 67.0% | −24,019 | −62,119 | **unchanged** |

A 25% stop roughly halves the worst session and cuts the drawdown by 38%, at a cost of 15% of the
mean. **It does nothing for the margin.** A naked short straddle is margined on its worst case, not
on the trader's intention to exit early — so a stop cannot make this position fit a ₹10,000 account.
**Only the wings do that.** If Aryan's binding constraint is capital, the stop is not an alternative.

**Methodological note worth keeping.** The first version of this comparator read the archive's
`rel_strike == "ATM"` files and produced a mean of +₹2,407 per session with a 92% win rate and
t = 35. That is fiction: the ATM file re-strikes the straddle every minute as spot moves, so it
decays without ever losing. `tail_clip_paths.py` now resolves the 09:20 ATM strike once and follows
that single contract. **Never build an intraday option path from the rolling `rel_strike` label.**

## 8. Position sizing, if it were ever traded

At ₹10,000 and one IF(w=3) lot: median defined risk ₹2,539, but the **maximum** defined risk observed
is **₹6,585**, and the worst realised session was **−₹6,352 — 64% of the account in one day.** Ruin
arithmetic: 1.6 worst-case sessions. Sizing must use the maximum possible loss on the day of entry,
which is known before entering, not the median. One lot is already the ceiling for this account.

## 9. Verification and limits

| check | result |
|---|---|
| **VAL-01** S0 reproduces H3 | mean 2.235224% vs published 2.235224%, N 1,040 vs 1,040, diff 1.1e-07 pp |
| **VAL-02** loss never exceeds defined risk | 0 violations at w ≥ 3; **56 at w=1 and 7 at w=2**, which is why those cells are discarded (§2b) |
| **VAL-04** no expiry sessions | 276 expiry sessions excluded by construction; H3 is the non-expiry arm |
| arbitrage quarantine | credit ≥ wing width: 6 sessions at w=1, 1 at w=2, 0 elsewhere |
| spot integrity | quotes come from the snapshot-derived cache; the 2026-08-23 BANKNIFTY contamination audit found 0 bad rows at 09:15 and 2 at 15:29 across 109,909 |

**Limits.**
- **No bid–ask anywhere in the headline.** §5 gives the cost room instead, and the verdict now rests
  on an assumed spread. A real quote study is the one thing that would settle this.
- **Margin is a max-loss proxy**, not a SPAN calculation. Real SPAN + exposure on a recognised hedged
  spread is close to, and generally slightly above, the max loss. No SPAN engine is available offline.
- **H3 is itself a lead, not a finding** — an aggregate screen that clears its threshold but is
  carried by 2025 in the naked version, from a 15-hypothesis battery.
- Only w ∈ {3,4} and the b ∈ {1,2}, w ∈ {2,3} condors are measurable here. Whether a wider,
  cheaper-per-point wing would keep more of the edge **cannot be answered from this archive** —
  it is precisely the region destroyed by the availability bias in §2a.
