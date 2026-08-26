# Correction: the Gate B "volatility crush" is a calendar-time measurement artifact

**Date:** 2026-08-23. **Raised by:** Aryan ("your assumption about vol. crush is wrong
completely. Theta I may agree."). **Verified by:** main session, independently.

## The claim being retracted

`GATE_B_REAL_PREMIUM_VALIDATION.md` §3 reports at-the-money implied volatility falling from
16.0 at the open to 13.3 by 15:25, entry-to-close IV falling on 27 of 33 trades, and attributes
−8.3% of premium to a "volatility leg". That mechanism is **withdrawn**.

## Why it is wrong

`gate_b_common.py:186` computes time to expiry as

    T0 = (expiry_dt - entry_dt).total_seconds() / (365.0 * 24 * 3600)

i.e. **calendar time**, running continuously through nights and weekends. Price variance accrues
only in trading time. Implied volatility inverted under a calendar-time convention therefore
declines mechanically across a session and jumps back overnight, with no change in true
volatility. The effect scales inversely with maturity, and Gate B's options have a **median 2.26
calendar days to expiry**, so the bias is large.

## Quantification (all 33 fires)

Under constant trading-time variance, sigma_close/sigma_entry = sqrt((D_close/D_entry) x
(T_entry/T_close)), where D is trading sessions remaining and T is calendar years remaining.

| quantity | mean | median |
|---|---:|---:|
| Observed IV change, entry to close | −10.11% | −10.97% |
| **Predicted by the calendar convention alone** | **−12.32%** | −9.64% |
| Residual (genuine volatility change) | +2.21% | −0.79% |

Residual against zero: **t-p = 0.379**, negative on 17 of 33. **There is no detectable genuine
volatility decline in Gate B.** The convention accounts for the whole of it.

## What replaces it

The loss mechanism is **time decay**, as Aryan said. The calendar-time convention under-charges
theta within a session and deposits the remainder into an apparent IV decline. Same money,
wrong label. A long ~2-day ATM CALL held from mid-morning to the close pays a full session of
decay.

## What does NOT change

The P&L is computed from **traded entry price to traded exit price** and is model-free. It does
not depend on the IV decomposition in any way.

* N=33 hold-to-close: mean −6.08%, median −13.46%, win 39.4%, **p=0.47** (not significant)
* N=120 pooled across IV buckets: mean −7.61%, median −13.22%, win 38.3%, p=0.067
* Real premiums below the constant-IV Black-Scholes proxy by 7.84pp, p=0.00001, on 28 of 33 days

## Scope of the contamination

**Gate B only.** Gate A trades same-day-expiry options: between a 09:17 entry and a 15:30 same-day
expiry there is no overnight period, so calendar time and trading time coincide and this artifact
cannot arise. `GATE_A_HORIZON_CENSORING.md`'s opening-crush finding is not affected by this defect.

## Required follow-up

Any future IV work in this project must invert with a **trading-time** (or business-time) maturity
convention, or state explicitly that quoted implied volatilities are calendar-convention and are
not comparable across times of day.
