# Clipping H3: defined-risk conversion of the 09:20 short straddle — Frozen Specification

**Date:** 2026-08-23
**Requested by:** Aryan (voice, 13:52 IST): *"H3 shows some kind of promise… but the two big
concerns are, one, the premium/margin will be too high for a straddle, and second the tail risk is
quite high. I want to find a way to clip this — reduce the margin required, and the tail risk, in a
good fashion. How do we do this?"*
**Status:** Exploratory. No Gate A / Gate B change, no gate armed, no broker, no credential, no
order path. Offline analysis only.
**Reads:** `FOLKLORE_BATTERY_SPEC.md` / `FOLKLORE_BATTERY_TEST.md` (H3), and the cached quote set
`folklore_required_quotes_20260823.pkl` (full ATM±10 chain at 09:15 / 09:20 / 15:29, 1,325 dates).

---

## 1. Research question

H3 — sell the ATM straddle at 09:20 on a non-expiry session, buy it back at 15:29 — screened at
+2.235% of entry premium (N=1040, p=0.00146, placebo p=0.0005) with a **catastrophic tail**
(worst session −250.7% of entry premium, max drawdown −773 percentage points) and an
**unaffordable margin** (a naked NIFTY short straddle blocks roughly ₹1.5–2.5 lakh of SPAN +
exposure per lot against a ₹10,000 budget).

Both problems have the same textbook fix: **buy the wings**. Converting the naked straddle into an
iron butterfly (or an iron condor) bounds the loss by construction and collapses the margin to
approximately the bounded loss, because a hedged position is margined on its worst case.

The question this test answers is **not** whether that fixes the tail — it does, by arithmetic.
It is: **does any edge survive after paying for the wings, and is the return on the capital
actually blocked better or worse than the naked version?**

## 2. Prior worth stating before the numbers

The wings are bought, not sold, and they carry the same volatility risk premium the short legs
harvest — with NIFTY put skew, the downside wing is bought at a *higher* implied volatility than
the ATM leg being sold. So the credit falls by more than a risk-neutral calculation would suggest.
`FOLKLORE_BATTERY_TEST.md` H7 already documents that far-OTM buyers lose ~92% of premium on expiry
day. The economically honest expectation is therefore that **the mean shrinks**; the test is
whether it shrinks by less than the capital does.

## 3. Estimand

Per structure, per non-expiry session, per lot (75):

    credit_0920 = (short legs − long legs) priced at the 09:20 traded close
    debit_1529  = the same combination priced at the 15:29 traded close
    PnL         = (credit_0920 − debit_1529) × 75          [rupees]
    max_loss    = (wing_width_points − credit_per_unit) × 75   [rupees, defined risk]
    RoR         = PnL / max_loss                            [return on risk]

`max_loss` is used as the **margin proxy** (object category: *proxy*, §7 of the working contract).
Real NSE SPAN + exposure on a recognised hedged spread is close to, and generally slightly above,
the max loss. No SPAN engine is available offline, so every capital figure in this report is a
proxy and is labelled as one.

## 4. Requirements

### Data

| ID | Requirement |
|---|---|
| DATA-01 | Quotes from `folklore_required_quotes_20260823.pkl` only. Do not re-scan the archive. |
| DATA-02 | Session universe = H3's: **non-expiry sessions** with a full set of required legs at both 09:20 and 15:29. Report N and every dropped session with its reason. |
| DATA-03 | ATM strike = the archive strike closest to the 09:20 spot, resolved on the **absolute** strike. |
| DATA-04 | `spot` must never be read from an arbitrary strike file (2026-08-23 archive audit: 74 files carry BANKNIFTY spot). The cached quote set is snapshot-derived and already clean at these clocks; assert it. |

### Structures

| ID | Requirement |
|---|---|
| STR-00 | **S0** — naked short ATM straddle, the H3 incumbent. Reproduction guard: must recover H3's +2.235% of entry premium on N=1040. |
| STR-01 | **IF(w)** — iron butterfly: short ATM CALL + short ATM PUT, long (ATM+50w) CALL + long (ATM−50w) PUT, for w ∈ {1,2,3,4,5,6,8,10}. |
| STR-02 | **IC(b,w)** — iron condor: short (ATM+50b) CALL and (ATM−50b) PUT, long (ATM+50(b+w)) CALL and (ATM−50(b+w)) PUT, for b ∈ {1,2} and w ∈ {2,3,4}. |
| STR-03 | Every leg of a structure must be present at **both** clocks or the session is dropped for that structure. Never substitute a neighbouring strike. |

### Reported objects

| ID | Requirement |
|---|---|
| OUT-01 | Mean, median, sd, win rate of PnL in **rupees per lot**, and of **RoR**. |
| OUT-02 | One-sample t and Wilcoxon against zero, with a **Bonferroni threshold over the whole registered structure family** stated up front. |
| OUT-03 | **Tail:** worst session, worst five, 1st/99th percentile, max drawdown — in rupees and in units of max loss. The naked straddle's tail is the comparison. |
| OUT-04 | **Capital:** median and 90th-percentile `max_loss` in rupees. State explicitly whether the structure fits a ₹10,000 budget at one lot. |
| OUT-05 | **Breakeven cost.** Round-trip rupees per leg that reduce the mean to zero. A 4-leg structure pays roughly twice the legs of a 2-leg one; this must be visible. |
| OUT-06 | **Year-by-year mean**, because H3's aggregate is carried by 2025 and 2026 is negative. A structure that only works in the same one year is not an improvement. |
| OUT-07 | **Ruin arithmetic.** Given a ₹10,000 account and one lot, the number of consecutive worst-case sessions to ruin, for each structure. |
| ROB-01 | **Stop-loss comparator.** As a separate lever, the naked S0 with an intraday stop at +25%/+50%/+100% of entry premium, minute-by-minute on the combined premium. Reported to show that a stop clips the tail but does **nothing** to the margin, which is the binding constraint. |

### Validation

| ID | Requirement |
|---|---|
| VAL-01 | S0 reproduction of H3 to within 0.01 percentage points. |
| VAL-02 | Assert `max_loss > 0` and `PnL ≥ −max_loss` for every session of every defined-risk structure. A violation means the accounting is wrong, not that the market misbehaved. |
| VAL-03 | Hand-check 2 sessions leg by leg against the cached quotes. |
| VAL-04 | Assert no expiry-day session enters any structure. |

## 5. Explicit exclusions

- No bid–ask, brokerage, STT, or slippage in the headline; OUT-05 gives the cost room instead.
- No SPAN engine — capital is a max-loss proxy (§3).
- No live orders, no paper session, no gate change. This is a screening test on an exploratory
  lead, and H3 itself is a lead, not a finding: it clears its multiplicity threshold in aggregate
  but only 2025 clears individually and 2026 is negative.
