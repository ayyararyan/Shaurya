# Can forecasting the intraday range let you size the wings?

**Date:** 2026-08-23 · **Status:** exploratory offline analysis · **No gate change, no gate armed, no broker or order path.**
Scripts: `range_forecast_test.py`. Artifacts: `range_forecast_results.json`,
`range_forecast_reverse.json`, `range_forecast_oos_selection.json`.
Reads `TAIL_CLIP_TEST.md` (the H3 defined-risk conversion) and `VRP_FORECAST_TEST.md`.

**Aryan (voice, 14:09):** *"If we have to do this we have to be able to forecast an intraday range.
Is it possible? Because if we can do that then we can select the optimal wings and mostly our
problem should be sorted."*

Sample: **1,025 non-expiry sessions, 2021-02-03 → 2026-05-11**, 09:20 origin (the H3 population).
Untouched holdout: 2025-05-13 onward, 194 sessions. 2 sessions closed exactly at the 09:20 price
and were floored at 0.05 points.

---

## Owner summary

**The range is forecastable. The forecast is the option price. And the range is not the thing that
decides whether the trade pays.**

1. **Yes — the 09:20→15:29 range is forecastable**, out of sample R² **+0.27** against a constant
   (walk-forward over 775 sessions: +0.25), correlation 0.53. But the typical error is **35%** of
   the actual range, which is not the precision "optimal wing selection" implies.
2. **All of that forecastability is already in the ATM implied volatility.** Implied alone gives
   R² +0.2714; implied plus 1/5/22-session past ranges gives +0.2715. **Past ranges add +0.0002.**
   You do not know anything about tomorrow's range that the option seller has not already priced.
3. **The object that actually determines the iron butterfly's P&L is not the range — it is the
   terminal displacement |close − entry|, and that is not forecastable at all.** OOS R² **−0.03**
   (implied), **−0.03** (implied + past), walk-forward **−0.02**. Mean absolute error 252%. This is
   the Merton (1980) structure the project has hit three times now: the diffusion is estimable, the
   terminal position is not.
4. **Sizing the wings by the forecast makes it worse, not better.** Choosing 150 vs 200-point wings
   by the forecast earns **₹134** per session against **₹155** for always using 200-point wings —
   significantly worse (paired p = 0.022) — and an *inverted* control that deliberately uses the
   wrong width earns ₹127, statistically the same. Conditional width just interpolates between the
   two fixed widths. **None of the three clears the ₹160 transaction-cost bar.**

**So: forecasting the range does not sort the problem.** But one thing did turn up, and it runs the
opposite way to the intuition behind the question.

---

## 1. Forecast accuracy (untouched year, 194 sessions)

Targets are in NIFTY points. "Implied" is the ATM implied volatility at 09:20 converted to an
expected range (σS√T · √(8/π)) or expected displacement (σS√T · √(2/π)), then fitted in logs.

| target | mean realised | mean implied | implied only | past only (HAR) | HAR + implied | HAR's increment over implied |
|---|---:|---:|---:|---:|---:|---:|
| **range** (high−low) | 196.2 | 295.3 | **+0.2714** | +0.1649 | **+0.2715** | **+0.0002** |
| **displacement** \|close−entry\| | 104.9 | 147.6 | −0.0377 | −0.1967 | −0.0297 | +0.0077 |

Walk-forward (expanding window, refit every 21 sessions, 775 strictly out-of-sample forecasts):
range R² **+0.251** vs the expanding mean and **+0.431** vs raw implied; displacement **−0.023**
and **−0.014**.

Two things to read off this table.

**The market prices a range 50% wider than the one that arrives** — 295 implied against 196
realised. Used raw, the textbook Brownian range formula scores R² **−1.15**, far worse than a
constant, because it inherits the whole volatility risk premium. It only becomes a useful forecast
after being fitted down by a constant factor — and that constant is the premium, not a forecast.

**Range is forecastable; displacement is not.** The range is a diffusion statistic and behaves like
one. The terminal displacement is where the day finished, which is a drift question. An iron
butterfly at 15:29 pays on the second, not the first.

## 2. Does the forecast let you choose the wings? No.

753 sessions where both 150-point and 200-point flies are priceable, walk-forward forecasts.

| rule | mean ₹/session | median | win | mean RoR | worst ₹ | clears ₹160 cost bar |
|---|---:|---:|---:|---:|---:|---|
| always 150-point wings | 106.3 | 195.0 | 66.0% | 5.33% | −3,352 | no |
| always 200-point wings | **154.6** | 296.3 | 66.1% | 4.29% | −4,680 | no |
| wider wings when forecast range is high | 133.7 | 232.5 | 66.0% | 4.48% | −4,215 | no |
| wider wings when forecast range is **low** (inverted control) | 127.1 | 225.0 | 66.1% | 5.14% | −4,680 | no |

The conditional rule is **₹21 worse than simply always using the wider wings**, paired p = 0.022,
and it is barely distinguishable from the deliberately-wrong control. The available width menu is
only {150, 200} points because everything at 250 points and wider is destroyed by the archive's
availability bias (`TAIL_CLIP_TEST.md` §2a) — so a wider menu cannot be tested here at all.

## 3. What did turn up — and it points the other way

Sorting sessions by **cushion minus forecast**, `signal = credit (points) − forecast range`, the
registered direction (sell when the cushion is large relative to the forecast) is **null**: top
third minus rest = −₹6, placebo p = 0.54.

**The opposite third is where the money is**, and it is monotone:

| 150-point fly, quintiles of `signal`, low → high | ₹210 | ₹129 | ₹81 | ₹61 | ₹6 |
|---|---:|---:|---:|---:|---:|

Bottom third **₹214** against **₹39** for the rest, difference **+₹175**, Welch p = 0.0005,
**two-sided placebo p = 0.0020** (2,000 shuffles, seed 20260823).

**It is not an implied-volatility sort in disguise.** Sorting by IV alone gives nothing (low ₹60,
mid ₹104, high ₹129, p = 0.24). Double-sorting, the signal still separates *inside* every IV
tercile (+₹73, +₹218, +₹254; p = 0.54, 0.052, 0.003) while IV separates nothing inside signal
terciles (p = 0.56, 0.65, 0.75, all with the wrong sign). Sorting by forecast displacement instead
of range gives nothing (placebo p = 0.51) — it is specifically the range forecast.

**It replicates in the untouched year at 150-point wings:** 76 selected sessions, **₹214 against
₹32**, Welch p = 0.036, win 67.1%, median ₹169 — and the selected third beat the rest in **every
year 2022–2026** (+₹126, +₹386, +₹87, +₹206, +₹538). At ₹214 it clears the ₹160 brokerage bar with
a breakeven half-spread of **₹0.36 per unit per leg**, inside the plausible ₹0.25–0.75 band but at
the optimistic end of it.

**Four reasons to hold this as a lead, not a result:**

1. **It does not replicate at 200-point wings in the untouched year** — +₹45, p = 0.74 — although it
   does on the full walk-forward panel (+₹181, placebo p = 0.018). An effect that survives at one of
   the only two measurable widths and not the other is not yet a property of the trade.
2. **The direction was a post-hoc flip** after the registered direction came back null. Counting
   3 selection tests × 2 directions, Bonferroni is 0.0083; the 150-point cell clears it, the
   200-point cell does not.
3. **The tercile threshold uses the whole panel's distribution**, which is a mild look-ahead. It
   should be an expanding quantile. Related: 2023 contributes only 5 selected sessions, so the
   selection is clustered by regime rather than spread evenly.
4. **No mechanism is established.** `signal` is essentially "credit per unit of implied range", so
   the low third is where you are paid *least* per unit of expected movement — and that being the
   better side is economically backwards on its face. Until there is a reason, this has the same
   shape as several associations in this project that later died (§4 of the topic file).

## 4. Answer to the question as asked

> *"If we can forecast the range then we can select the optimal wings and mostly our problem should
> be sorted."*

**No, on three counts:**

- The range forecast contains no information beyond the option price (+0.0002 of R² from everything
  you know that the market does not).
- The fly's P&L is set by the terminal displacement, which is unforecastable (R² ≈ −0.03).
- Choosing width by the forecast is measurably worse than choosing one width and keeping it.

The one honest thread left is the day-selection signal in §3 — **which is about *when* to put the
trade on, not *how wide* to make it** — and the single test that would settle it is a clean
re-run with an expanding-quantile threshold and a pre-registered direction, on 200-point wings,
alongside the bid–ask study already named as the next step in `TAIL_CLIP_TEST.md`.
