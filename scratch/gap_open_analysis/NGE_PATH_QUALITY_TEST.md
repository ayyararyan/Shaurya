# Does ex-ante dealer Net Gamma Exposure predict intraday path quality on NIFTY?

**Run date:** 2026-08-23
**Requested by:** Aryan, after every price-path indicator and every volume/OI feature tested on
this project returned null, on the reasoning of `TREND_DAY_FORECASTABILITY_RESEARCH.md` §1a:
path quality is a drift-to-diffusion ratio, Merton (1980) says the drift is not estimable from
the path at any sampling frequency, and therefore the only escape is a variable that is **not**
a price-path statistic. Dealer gamma positioning, computed from option open interest by strike,
is that variable.
**Task status:** **COMPLETE.** All five briefed tests ran, on the full archive rather than only
the 264-day pool. Six components were added because the honest reading required them: a
**decisive** ex-ante audit of the open-interest snapshot (§1), a days-to-expiry confound test
(§9.1), a sampling-frequency test (§9.2), three attacks on the sign finding one of which lands
(§9.3–9.5), a genuine out-of-sample split and a walk-forward money test (§10), and a targeted
single-statistic permutation test that needs no best-of-grid correction (§11.2).

**Evidence class:** exploratory-to-confirmatory hybrid on **observed exchange open interest and
observed traded prices**. The primary regressor is measured at 09:15 from the previous session's
settled open interest and is **verified**, not assumed, to be ex ante (§1). That makes the
causal direction safe. It does not make the effect large, stable, or tradeable, and it is none
of those three.

No broker, credential, exchange network, or order path was used. No live order exists or is
authorised. No pre-existing script or report was modified; every file listed in §16 is new.

---

## 0. Verdict

> **Yes — weakly, in the direction the literature predicts, and with no money in it.**
>
> On 1,320 NIFTY sessions (2021-01-01 … 2026-05-12), ex-ante dealer gamma predicts the
> 5-minute return autocorrelation ρ₁ with **β = −0.0086, Newey–West t = −2.32, p = 0.021,
> R² = 0.40%** (Spearman ρ = −0.090, p = 0.0011). Higher net dealer gamma ⇒ a more
> mean-reverting session, which is the Barbon–Buraschi / Baltussen sign. It **strengthens**
> under a days-to-expiry control and is **completely untouched** by an implied-volatility
> control. It passes a single-statistic coherent-permutation placebo at **p = 0.004**.
>
> **Every economically meaningful test then fails.**

And the four numbers that settle it, none of which needs a multiplicity argument:

| question | what a tradeable signal looks like | what this is |
|---|---|---|
| **Does the quartile ladder reproduce ex ante?** | the realised-R² ladder's +36.8pp, monotone | **−2.9pp, p = 0.82**, on the identical 120 fires |
| **Does it survive out of sample?** | frozen-weight OOS prediction works | **OOS R² 0.12%, r = +0.055, p = 0.16**, terciles non-monotone |
| **Is it stable across the sample?** | present in both halves | **first half t = −2.38; second half t = −0.92.** Dropping 2023 alone takes β to 37% of full and t to −0.79 |
| **Does a control kill it?** | it should survive obvious confounds | **yes.** Control for where the call/put open interest sits relative to spot and the signs **flip and die**: b_call +0.009 (t = 0.92), b_put −0.003 (t = −0.34) |

**On the sign convention — the brief's crux design point.** Entering gamma-weighted CALL and
PUT open interest as separate regressors with free coefficients returns **b_call < 0 and
b_put > 0** on ρ₁ in every population with N ≥ 264 except expiry days, and at every sampling
frequency from 1 to 15 minutes. That pattern says calls are associated with mean reversion and
puts with momentum, i.e. dealers behave as if **long calls and short puts** — the SqueezeMetrics
/ Baltussen US convention, **not inverted**. The retail-option-selling story does not show up in
the sign. But §9.4 shows the same pattern is largely reproduced by *where the open interest
sits*, so this is a statement about the shape of the NIFTY open-interest distribution, and only
provisionally about a dealer position.

**On Ahmed's critique — and this is the cleanest result in the study.** The answer is **split,
and the split is the finding**:

* On **path shape** (ρ₁), opening implied volatility carries essentially nothing (R² = 0.0016%),
  so the gamma coefficient is unchanged by the control (attenuation **−0.7%**, i.e. none).
  Ahmed's redundancy argument **does not apply** to this channel.
* On **volatility magnitude**, Ahmed is exactly right. Opening IV alone gives R² = 5.5% (9.2% on
  non-expiry days) against gamma's 0.43%; controlling for IV attenuates the gamma coefficient by
  **21% (all sessions) to 53% (non-expiry)** and removes its significance.
* And the decisive version: a **walk-forward** model that genuinely predicts realised
  displacement out of sample (Spearman +0.143, p < 0.0001, OOS R² +0.45%) produces a straddle
  ladder that is **monotone in the wrong direction** — the top predicted-movement quartile
  returns **−4.62%** against an unconditional −1.76%. The forecastable part of the movement is
  already in the price, and over-priced. **Mechanism without edge**, demonstrated rather than
  argued.

**Why this is still worth having.** The research agent found no peer-reviewed NIFTY dealer-gamma
result — only two zero-citation working papers, one on a 28-day sample. This is 1,320 sessions
of five-year NIFTY weekly option data with a verified-ex-ante regressor, a free-coefficient sign
test, a truncation ladder, and a walk-forward money test. **The null is the contribution**, and
so is the sign, and so is the split verdict on Ahmed.

---

## 1. The one thing that must be believed first: is the 09:15 snapshot ex ante?

Everything below rests on the claim that the 09:15 open-interest reading carries the **previous**
session's positioning and cannot contain information from the session being predicted. The brief
asked for this to be stated *and verified*. It is verified, and the verification is decisive.

Full-day open interest was re-read for 252 archive windows (4,852 contract-days, March and
September of 2021, 2023 and 2025), keyed on absolute strike:

| check | result | reading |
|---|---:|---|
| `oi(09:15) == oi(09:16)` | **99.50%** | the value is carried forward, not live |
| `oi(09:15) == oi(09:20)` | 0.82% | it starts updating around 09:17 |
| `oi(09:15) == oi(10:00)` | 0.09% | fully live by mid-morning |
| `oi(09:15) == oi(15:29)` | **0.00%** | nothing survives the session |
| median \|oi(09:15) / oi(**prior** 15:29) − 1\| | **3.73%** | close to the prior session's close |
| median \|oi(09:15) / oi(**own** 15:29) − 1\| | **35.0%** | nowhere near its own close |

The 09:15 figure sits within 3.7% of the previous session's last tick and 35% from its own —
a factor of nine. The residual 3.7% is the difference between the exchange's provisional
15:29 intraday tick and its settled end-of-day figure, which is itself a prior-session quantity.
Across the whole archive (50,693 matched contract-days) the exact-match rate against the prior
15:29 tick is only 1.03%, which is what a settlement revision looks like and **not** what
intraday contamination looks like — intraday contamination would show a *smaller* distance to
the own-session close, and it shows a nine-times-larger one.

Separately, open interest inside a session is not slow: the median contract-day carries **123
distinct open-interest values** and moves 29% from first bar to last. So the 09:15 staleness is
a genuine property of the opening bar, not a property of open interest being sticky.

**Conclusion: the regressor is ex ante by construction and by measurement. There is no leakage
channel.** This is the single strongest methodological property of this study and it is the one
the earlier work on this project could not claim for most of its features.

---

## 2. Construction

### 2.1 Source

`/Users/maheit/.cache/openclaw/gdrive/.../dhan_fresh_2021_2026/options` — 2,772 one-minute CSVs,
CALL and PUT, **WEEK1 expiry only**, relative strikes ATM−10 … ATM+10, 2021–2026. All 2,772 read,
**zero missing**. 20,860,781 raw bars scanned; the 09:15 and 15:29 bars retained →
**109,909 snapshot rows over 1,325 dates**, 23 duplicate contract-minutes (0.02%) resolved by the
project's standard highest-volume rule.

Everything is keyed on the **absolute** `strike`, never on `rel_strike`. The rolling-label defect
documented in `gate_b_flow_common.py` — a file named `ATM+6` carrying four different contracts
inside one session, its `oi` column swinging from 16,700 to 567,000 for that reason alone — is
fatal to any open-interest series built on the label, and is avoided here by construction.

### 2.2 Gamma

`Γ(K) = φ(d₁) / (S·σ·√T)`, `d₁ = [ln(S/K) + (r + σ²/2)T] / (σ√T)`, `r = 6.5%`, `S` = the 09:15
spot, `K` = absolute strike.

**Maturity is TRADING TIME** — 375 minutes per session, 252 sessions per year, counting actual
archive trading dates so holidays are handled by the calendar rather than a weekday rule.
`CORRECTION_GATE_B_VOL_CRUSH.md` retracted a finding on this project once because of a
calendar-time convention; calendar time is carried here only as a declared sensitivity.

**Which implied volatility supplies Γ(K).** Γ_call(K) = Γ_put(K) exactly, by put–call parity
(d(C−P)/dS ≡ 1, so the second derivative of the difference is zero). A strike therefore has
**one** gamma, and it should be read off the non-degenerate quote. Primary construction uses the
**out-of-the-money side** — the call for K ≥ ATM, the put for K < ATM. This is not a cosmetic
choice: **7.53% of all 09:15 quotes carry `iv ≤ 0`, and 0.000% of OTM-side quotes do.** Every
degenerate implied volatility in the archive is a deep in-the-money one. Each side using its own
`iv` is carried as a sensitivity (`own`).

**The convention does not drive anything.** Trading vs calendar maturity and OTM vs own-side
implied volatility give day-rankings that agree at Spearman **0.977–0.998** and **0.980–0.982**
respectively, at every chain width. This is expected: Black–Scholes gamma depends on (σ, T)
essentially through σ√T, and re-pairing a vendor implied volatility with a different maturity
rescales that product roughly uniformly. It is a change of units far more than a change of
information, and the cross-sectional ordering of days survives it.

### 2.3 The composite, and what is deliberately NOT imposed

Standard convention, following SqueezeMetrics (2016/2017) and Baltussen et al. (2021) eq. 13:

```
GEX = Σ_K [ Γ(K)·OI_call(K) − Γ(K)·OI_put(K) ] · S² · 0.01
```

reported for comparability with the literature. **`S²·0.01` denominates it as dollar gamma per
1% move.**

**No lot-size multiplier is applied, and this is deliberate.** The NIFTY market lot has changed
over 2021–2026 and the archive carries no lot-size column, so it cannot be verified from the
data this study uses. Rather than hard-code an unverifiable constant, it is omitted and the
consequence is stated: a lot size is a **positive constant within a period**, so it cancels
exactly in (a) the sign of GEX, (b) any rank correlation, (c) any within-period quartile sort,
and (d) the within-year z-scores used throughout. It would matter only to a cross-period
comparison of raw levels, which is never made. `TREND_DAY_FORECASTABILITY_RESEARCH.md` §2 flags
exactly this and reaches the same conclusion.

**Two further regressors, and why the normalised one is primary:**

* `gimb` — **normalised gamma imbalance**, `(Σ Γ·OI_c − Σ Γ·OI_p) / (Σ Γ·OI_c + Σ Γ·OI_p)`,
  bounded in [−1, 1]. Scale-free, and therefore immune to the lot size, to the enormous secular
  growth in NIFTY option open interest, and to the mechanical fact that **Γ ∝ 1/σ** (which makes
  raw gamma-weighted open interest a partial volatility proxy: corr(log Σ Γ·OI_call, prior
  5-session realised vol) = **−0.41**, and −0.47 for puts; for `gimb` it is only +0.07).
* Free coefficients on the two legs — **the design point** — z-scored within year:
  `ρ₁ = a + b_C·z(log Σ Γ·OI_call) + b_P·z(log Σ Γ·OI_put) + ε`.

### 2.4 What the fitted signs mean — spelled out, because it is easy to get backwards

There are **two** mappings composed, and conflating them inverts the conclusion.

1. **Open interest → dealer gamma** (the *position* assumption). US convention: end-users sell
   calls and buy puts, so dealers are long calls and short puts, and dealer gamma ∝ (+OI_c, −OI_p).
2. **Dealer gamma → path** (the *mechanism*). Positive dealer gamma ⇒ delta-hedging buys dips and
   sells rallies ⇒ stabilising ⇒ mean reversion ⇒ **ρ₁ falls**. Negative dealer gamma ⇒
   destabilising ⇒ momentum ⇒ ρ₁ rises.

Composing them, **US convention + mechanism ⇒ b_C < 0 and b_P > 0** — the fitted vector is
*anti-parallel* to the GEX weight vector (+1, −1), not parallel to it.

*(Note for the reader coming from `TREND_DAY_FORECASTABILITY_RESEARCH.md` §3.4, which states the
expectation as "b_C > 0, b_P < 0": that is the sign pattern of the **GEX construction**, mapping
(1) alone. Applied to a regression of ρ₁ it omits the mechanism's negative sign. The table below
avoids the ambiguity entirely by naming what each of the four quadrants implies.)*

| fitted (b_C, b_P) on ρ₁ | what it implies |
|---|---|
| **(−, +)** | US convention holds **and** the mechanism holds: dealers long calls / short puts |
| (+, −) | **Inverted** Indian dealer position — dealers short calls / long puts, the retail-selling story |
| (+, +) or (−, −) | No sign separation: the legs are proxying option-market **size**, not a directional position |

### 2.5 Labels

Computed from the archive `spot` column, 09:15 → 15:29, one-minute closes.

* **`rho1` — primary.** Lag-1 autocorrelation of 5-minute log returns, Barbon & Buraschi's
  measure. ρ₁ > 0 trending, ρ₁ < 0 mean-reverting. Preferred to straight-line R² because it is a
  second-moment ratio that divides out the realised drift, and R² is a noisy drift estimator
  (§1a of the research report).
* `r2_line` — straight-line R² of the minute path (this project's incumbent label).
* `kaufman_er` — Kaufman Efficiency Ratio, |net move| / Σ|steps|.
* `abs_disp_pct` — realised absolute displacement, % of the 09:15 spot.
* Also carried: `vr3` (Lo–MacKinlay variance ratio at q = 3 bars) and `rv_pct`.

**Money variables.** Two, both model-free, both traded bar closes:

* **ATM straddle / CALL / PUT, real traded 09:15 → 15:29**, strike fixed at the 09:15 ATM and
  looked up by absolute value. Available on all 1,312–1,315 sessions. This is new to the project
  and is the money variable on the full population.
* **The Gate-B trade** (buy an ATM CALL at the gap-fill minute, hold to 15:29), priced on real
  strike-tracked traded premiums from `gate_b_full_paths.load_full_paths()`. The
  `gate_b_common.reproduction_guard` runs upstream and **passes** — the fire set, entry clocks,
  strikes, entry premiums, all three published trailing-stop means and all six published
  fixed-clock exits are recovered.

### 2.6 Populations — and a correction to the brief

The brief names the 264-day pool as "the full … pool, all days, gate-irrelevant". **It is not
all days.** The 264-day pool is *non-expiry gap-down sessions whose gap fills after 09:17* — a
triply conditioned set. Since dealer gamma is a market-wide mechanism, the honest primary
population is **every session in the archive**, and that is what is used. The 264-day pool is
reported alongside as the brief's named population. Both appear in the headline.

| population | N | date range |
|---|---:|---|
| **ALL_SESSIONS (primary)** | **1,320** | 2021-01-01 … 2026-05-12 |
| NONEXPIRY | 1,044 | same |
| EXPIRY | 276 | same |
| **POOL264 (the brief's named population)** | **264** | 2021-01-05 … 2026-04-20 |
| FIRES120 (`vix_rose == 1`) | 120 | 2021-01-05 … 2026-04-20 |
| MIDIV33 (published Gate B) | 33 | 2021-09-08 … 2026-01-29 |
| CONTROLS (`vix_rose == 0`) | 144 | 2021-01-05 … 2026-04-17 |

**Note the inverted placebo logic, as briefed.** An effect appearing on control days is
*confirming*, not a failed placebo. In practice the control slices are too small to say anything
either way — at N = 144 the smallest detectable |r| is 0.232 against an effect of ≈0.09 — so
they neither confirm nor refute, and are not used as evidence in either direction.

### 2.7 Descriptives worth having

| quantity | value |
|---|---:|
| ρ₁, mean / median | **−0.0597 / −0.0595** |
| ρ₁, share of sessions positive | **32.9%** |
| straight-line R², mean | 0.437 |
| Kaufman ER, mean | 0.060 |
| absolute displacement, mean | 0.520% |
| gamma imbalance, mean / median | **+0.139 / +0.151** |
| gamma imbalance, share positive | **82.9%** (GEX negative on 17.1% of days) |
| gamma imbalance, lag-1 autocorrelation | 0.132 |
| median strikes in the 09:15 chain | 21 per side |
| median sessions to expiry | 3 |

**Two facts to carry forward.** First, **NIFTY intraday is mean-reverting on 67% of sessions** —
ρ₁ is negative far more often than not, which is itself a useful description of what a long
option is fighting. Second, gamma imbalance is positive on 83% of days, exactly as Baltussen's
candid footnote 8 reports for the S&P, and it **declines monotonically over the sample**
(+0.202 in 2021 → +0.035 in 2026): the put side of the NIFTY weekly chain has been growing
relative to the call side for five years. That secular drift is why within-year standardisation
is used everywhere and why raw-level regressions are not trusted.

---

## 3. Test 1 — path quality on ex-ante NGE

### 3.1 The primary population, N = 1,320

| dependent variable | spec | β | NW t | p | R² |
|---|---|---:|---:|---:|---:|
| **ρ₁** | GEX composite (z, within year) | −0.0029 | −0.75 | 0.453 | 0.04% |
| **ρ₁** | **gamma imbalance (z)** | **−0.0086** | **−2.32** | **0.021** | **0.40%** |
| **ρ₁** | Spearman on raw imbalance | ρ = **−0.090** | — | **0.0011** | 0.81% |
| straight-line R² | gamma imbalance | −0.0037 | −0.44 | 0.657 | 0.02% |
| Kaufman ER | gamma imbalance | +0.0008 | +0.65 | 0.516 | 0.03% |
| abs. displacement | GEX composite | **−0.0400** | **−3.00** | **0.0027** | 0.76% |
| abs. displacement | gamma imbalance | −0.0300 | −2.00 | 0.046 | 0.43% |

**Free coefficients — the design point:**

| dependent variable | b_call | t | p | b_put | t | p | sign | R² |
|---|---:|---:|---:|---:|---:|---:|:--:|---:|
| **ρ₁** | −0.0124 | −1.77 | 0.076 | **+0.0187** | **+2.76** | **0.0058** | **(−,+)** | 0.61% |
| straight-line R² | −0.0034 | −0.21 | 0.833 | +0.0076 | +0.50 | 0.618 | (−,+) | 0.03% |
| Kaufman ER | +0.0020 | +0.93 | 0.355 | −0.0004 | −0.20 | 0.843 | (+,−) | 0.15% |
| abs. displacement | **−0.0797** | **−2.66** | **0.0079** | −0.0146 | −0.54 | 0.588 | (−,−) | 4.03% |

On **non-expiry sessions (N = 1,044)** the ρ₁ result is cleaner still: gamma imbalance
β = −0.0105, t = −2.55, p = 0.011, R² = 0.62%; free coefficients b_call = −0.0173 (t = −2.15,
p = 0.032) and b_put = +0.0201 (t = +2.61, p = 0.0093), **both significant, sign (−,+)**;
Spearman −0.106, p = 0.0006.

### 3.2 Four readings, in order of importance

**(a) The label change was worth it.** ρ₁ carries the association; straight-line R² and the
Kaufman Efficiency Ratio carry **nothing at all** (p = 0.66 and 0.52). The research report's
Rank-2 recommendation — replace R² with ρ₁ because R² is a drift estimator in disguise — is
vindicated on this data. Had this study used the project's incumbent label it would have
returned a flat null and stopped.

**(b) The literature's own composite fails; only its normalised version works.** Standard-
convention GEX gives t = −0.75 on ρ₁; the normalised imbalance gives t = −2.32. The difference
is that GEX is a level difference dominated by days when total chain gamma is large, whereas the
imbalance is a ratio. **The Baltussen/SqueezeMetrics composite, ported literally, is null on
NIFTY path shape.** Anyone reproducing this must normalise.

**(c) The sign is (−, +): the US convention is NOT inverted.** More gamma-weighted call open
interest ⇒ more mean reversion; more put ⇒ more momentum. That is dealers long calls, short
puts. §9 attacks this three ways and one attack lands.

**(d) Two different channels, loading on two different legs.** Path shape (ρ₁) is carried by the
**put** leg (t = +2.76, call leg n.s.); volatility magnitude is carried by the **call** leg
(t = −2.66, put leg n.s.) and its sign pattern is (−,−) — the *scale* quadrant, not the
gamma-position quadrant. So the volatility result is a size effect, not a positioning effect.
This asymmetry is not predicted by anything in the literature and I do not have an explanation
for it. It is reported because it is there.

### 3.3 The sign pattern across every population

15 of 28 population × label cells show (−,+). On ρ₁ specifically:

| population | N | b_call | b_put | sign | matches US convention + mechanism |
|---|---:|---:|---:|:--:|:--:|
| ALL_SESSIONS | 1,320 | −0.0124 | +0.0187 | (−,+) | **yes** |
| NONEXPIRY | 1,044 | −0.0173 | +0.0201 | (−,+) | **yes** |
| POOL264 | 264 | −0.0146 | +0.0082 | (−,+) | yes (n.s.) |
| FIRES120 | 120 | −0.0139 | +0.0174 | (−,+) | yes (n.s.) |
| EXPIRY | 276 | +0.0057 | +0.0137 | (+,+) | no |
| CONTROLS | 144 | −0.0043 | −0.0125 | (−,−) | no |
| MIDIV33 | 33 | +0.0538 | −0.0105 | (+,−) | no |

The three exceptions are the three most special populations: expiry days (where pinning is a
documented independent chop mechanism — Ni, Pearson & Poteshman 2005), and the two smallest
slices, where nothing is significant in either direction and the sign is a coin flip.

**A caution about MIDIV33.** Its Newey–West t-statistics reach −5.38 and +4.34 in the grid. A
five-lag HAC covariance on N = 33 is not trustworthy; classical standard errors on the same
regressions give −1.95 and +2.13. Both are reported in `nge_robustness_results.json`. **No number
from MIDIV33 is quoted as evidence anywhere in this document.**

---

## 4. Test 2 — the money test. Does the quartile ladder reproduce ex ante?

### 4.1 The benchmark first, so the comparison is fair

The realised-path-quality ladder this study is trying to replicate ex ante reproduces cleanly:

| population | series | Q1 → Q4 (sorted on realised R²) | spread | t | p | monotone |
|---|---|---|---:|---:|---:|:--:|
| **FIRES120** | real premiums | **−25.09% → −12.28% → −4.75% → +11.69%** | **+36.78pp** | +3.58 | **0.0009** | **yes** |
| FIRES120 | BS proxy | −14.15% → −6.25% → −1.76% → +17.61% | +31.76pp | +3.03 | 0.0043 | yes |
| POOL264 | real premiums | −16.55% → −20.90% → −4.09% → +9.29% | +25.83pp | +3.28 | 0.0015 | no |
| ALL_SESSIONS | ATM straddle | −20.47% → −14.54% → −1.53% → **+26.18%** | **+46.65pp** | +15.33 | **<1e-15** | **yes** |

*(The published figures are −21.6% to +6.8%, spread +19.2pp, p = 0.022. The structure — monotone,
large, significant — reproduces; the magnitudes differ because the label here is computed on the
whole session from 09:15 rather than from the entry minute, and because the real-premium series
is used rather than the Black–Scholes proxy. Both variants are shown so the difference is
visible rather than hidden.)*

The realised sort is enormous and real. **The whole question is whether an ex-ante variable
recovers any of it.**

### 4.2 It does not

| population | series | sort | Q1 → Q4 | spread | p | Spearman |
|---|---|---|---|---:|---:|---:|
| **FIRES120** | real premiums | **ex-ante imbalance** | +0.13% → −19.79% → −1.52% → −9.26% | **−9.39pp** | **0.463** | −0.049 |
| FIRES120 | real premiums | ex-ante GEX (z) | +2.44% → −8.99% → −6.89% → −16.98% | −19.42pp | 0.105 | −0.197 |
| POOL264 | real premiums | ex-ante imbalance | −2.77% → −14.43% → −9.59% → −5.69% | −2.92pp | 0.739 | −0.047 |
| **ALL_SESSIONS** | **ATM straddle** | **ex-ante imbalance** | −5.76% → −1.62% → −3.22% → +0.23% | **+6.00pp** | 0.047 | **−0.008 (p = 0.76)** |
| ALL_SESSIONS | ATM straddle | ex-ante GEX (z) | −5.34% → −3.81% → −3.06% → +1.84% | +7.18pp | 0.036 | −0.022 (p = 0.42) |
| NONEXPIRY | ATM straddle | ex-ante imbalance | −3.69% → −2.92% → −4.55% → +0.16% | +3.85pp | 0.070 | +0.009 |

**Read as plainly as the brief asked.** On the identical 120 fires where the realised sort gives
a monotone +36.78pp at p = 0.0009, the ex-ante sort gives **−9.39pp at p = 0.46 — wrong sign,
not significant, not monotone.** The ladder does not reproduce.

The one cell that reaches a raw 5% — the full-sample straddle at +6.00pp, p = 0.047 — dies on
three independent counts:

1. **Its Spearman correlation is −0.008 (p = 0.76), i.e. exactly zero.** A monotone-looking
   quartile table with zero rank correlation is a tail artefact, not a ladder.
2. **+6.00pp is below what the design can resolve.** The smallest quartile spread detectable at
   80% power on this series is **8.63pp** (§13). The point estimate is inside the noise floor.
3. **The best-of-grid money placebo returns empirical p = 0.709.** Observed best |spread| across
   the five money jobs is 9.39pp; the coherent-permutation placebo's **median** draw is 12.14pp
   and its 95th percentile is 23.47pp. A randomly rotated gamma series produces a *better* best
   ladder than the real one in 71% of draws.

### 4.3 The strongest available version of the money test also fails

Sorting on the raw imbalance is the brief's specification. The fairer version sorts on the
**model's prediction**, walk-forward: at the open of session *t*, fit the two-leg model on
sessions 1…*t*−1 only, standardise on that history only, predict, sort. 1,067 live sessions,
2022-01-06 → 2026-05-12.

| predicted label | Q1 → Q4 straddle return | spread | p | Spearman | top-quartile rule |
|---|---|---:|---:|---:|---|
| ρ₁ (free legs) | −2.80% → −0.70% → −3.29% → −0.28% | +2.52pp | 0.476 | −0.021 | −0.28%, **+1.49pp** vs unconditional, p = 0.54 |
| ρ₁ (imbalance) | +1.42% → −2.52% → −1.51% → −4.45% | −5.86pp | 0.102 | +0.005 | −4.45%, −2.68pp, p = 0.16 |
| displacement (free legs) | +2.05% → −0.53% → −3.97% → −4.62% | −6.67pp | 0.072 | +0.048 | **−4.62%, −2.86pp**, p = 0.059 |

The best improvement anywhere is **+1.49pp against a smallest-detectable improvement of 9.93pp**,
at p = 0.54. And the fourth row is the interesting one — see §8.3.

### 4.4 Loss per minute, as asked

Holding periods differ between the fixed 09:15→15:29 straddle (374 minutes) and the Gate-B trade
(median 355–357 minutes), so totals are reported with per-minute rates alongside.

| population | series | N | mean | median held (min) | mean %/min | median %/min |
|---|---|---:|---:|---:|---:|---:|
| ALL_SESSIONS | ATM straddle | 1,312 | **−2.59%** | 374 | **−0.0069** | −0.0219 |
| ALL_SESSIONS | ATM CALL | 1,313 | −1.79% | 374 | −0.0048 | −0.0425 |
| POOL264 | Gate-B real | 245 | −8.10% | 355 | −0.0209 | −0.0415 |
| FIRES120 | Gate-B real | 120 | −7.61% | 357 | −0.0197 | −0.0438 |
| MIDIV33 | Gate-B real | 33 | −6.08% | 346 | −0.0093 | −0.0407 |

Per-minute ex-ante ladder on the straddle: −0.0154 → −0.0043 → −0.0086 → **+0.0006** %/min,
spread +0.0160 %/min, p = 0.047 — the same single marginal cell as §4.2, with the same three
objections.

**A by-product worth keeping.** Buying an ATM straddle at the 09:15 traded close and selling at
the 15:29 traded close loses **−2.59% of premium per session** on average across 1,312 sessions
(median −8.19%, win rate 33.6%, 95% CI [−4.73%, −0.46%]). That is a clean, model-free, five-year
statement of what intraday long-optionality costs on NIFTY, and it is new to this project.

---

## 5. Test 3 — Baltussen et al. (2021) Table 7

Regressing the last-half-hour spot return on the rest-of-day return, split by the sign of
ex-ante NGE. Their S&P 500 result, Jan 1996 – May 2020:

| Baltussen, prior-day NGE | β ×100 | NW t | R² |
|---|---:|---:|---:|
| NGE ≥ 0 (dealers long gamma) | 0.82 | 1.03 | 0.05% |
| NGE < 0 (dealers short gamma) | **6.63** | **4.78** | **3.58%** |

NIFTY, same specification:

| population | split | N | β ×100 | NW t | p | R² |
|---|---|---:|---:|---:|---:|---:|
| ALL_SESSIONS | GEX ≥ 0 | 1,094 | **+1.93** | **+2.01** | 0.045 | 0.52% |
| ALL_SESSIONS | GEX < 0 | 226 | −4.00 | −1.35 | 0.177 | 2.42% |
| **NONEXPIRY** | **GEX ≥ 0** | 859 | **+3.00** | **+2.61** | **0.0091** | **1.31%** |
| NONEXPIRY | GEX < 0 | 185 | −4.25 | −1.53 | 0.129 | 2.72% |
| NONEXPIRY | above median imbalance | 522 | +3.48 | +2.37 | 0.018 | 1.63% |
| NONEXPIRY | below median imbalance | 522 | −0.65 | −0.32 | 0.746 | 0.07% |
| POOL264 | GEX ≥ 0 | 190 | +4.23 | +1.40 | 0.163 | 1.88% |
| POOL264 | GEX < 0 | 74 | −1.00 | −0.42 | 0.672 | 0.21% |

Table 8's continuous version (interacting scaled NGE with the rest-of-day return): Baltussen get
**−123.04, t = −3.42**. NIFTY non-expiry gives **+0.141, t = +2.27, p = 0.024** — significant,
and **opposite in sign**.

### 5.1 This contradicts Test 1, and the contradiction is the finding

Test 1 says: higher gamma imbalance ⇒ **lower** ρ₁ ⇒ more mean-reverting. Agrees with Baltussen.
Test 3 says: higher gamma imbalance ⇒ **stronger** last-half-hour continuation. Contradicts
Baltussen, and contradicts Test 1.

Both cannot be a clean reading of one mechanism. Three candidate resolutions, and I cannot
distinguish them with this data:

1. **Both are noise.** R² is 0.40% and 1.31%. Two coefficients this small can point in opposite
   directions without either being real.
2. **They measure different things.** ρ₁ is a whole-session shape statistic averaged over ~74
   five-minute bars. Baltussen's β is a *close-auction* effect: it is specifically about
   end-of-day delta rebalancing into the settlement. A market can be mean-reverting in shape all
   day and still show continuation into the last half hour. Note the negative-gamma leg carries
   the higher R² in both Baltussen (3.58%) and here (2.42–2.72%) — it just fails significance at
   N = 185–226.
3. **The Indian close is structurally different.** NSE has no equivalent of the SPX
   market-on-close auction that Baltussen's mechanism runs through, and NIFTY weekly expiry
   settlement is on a VWAP-style window rather than a single closing print.

**What I will not do is pick the reading that agrees with Test 1.** The honest statement is that
the Baltussen replication **does not replicate**, that its sign is inverted, and that this is
evidence *against* a clean port of the S&P mechanism to NIFTY even though Test 1's sign agrees
with the S&P convention.

---

## 6. Test 4 — truncation sensitivity

The archive is ±10 strikes (±500 points ≈ ±2.2%). The brief's criterion: if the ranking
converges as width grows, truncation is not binding; if not, the measure is not identified.

**The ranking converges. The coefficient does not.**

| width | β on ρ₁ | t | β on displacement | t | Spearman vs ±10 | sign agreement |
|---:|---:|---:|---:|---:|---:|---:|
| ±3 | **−0.0112** | **−3.10** | −0.0433 | −3.12 | 0.925 | 85.5% |
| ±5 | −0.0101 | −2.79 | −0.0400 | −2.78 | 0.963 | 91.4% |
| ±7 | −0.0095 | −2.58 | −0.0380 | −2.57 | 0.985 | 96.5% |
| ±9 | −0.0085 | −2.29 | −0.0331 | −2.21 | **0.998** | **98.6%** |
| ±10 | −0.0086 | −2.32 | −0.0300 | −2.00 | 1.000 | 100% |

**Ranking:** Spearman between consecutive widths reaches 0.998 at ±9 → ±10, with 98.6% sign
agreement. The day-ordering has clearly stabilised. Truncation is **not binding on which days are
high-gamma and which are low**.

**Coefficient:** it declines monotonically as strikes are added — ±3 → ±5 → ±7 → ±9 costs
+9.6%, +6.7%, +10.5% of the ρ₁ coefficient, and only the last step (±9 → ±10) is flat at −1.0%.
That last step is flat mostly because it adds very little: the mean imbalance moves only
0.1365 → 0.1388 and total gamma-weighted open interest rises about 3%.

**The honest reading, stated as a caution rather than a reassurance.** The association is
concentrated near the money and is *diluted* by adding strikes. Two interpretations are open and
this archive cannot separate them:

* **(a) Near-ATM gamma is the real object.** Hedging flow is where gamma is, gamma is at the
  money, and adding far strikes adds open interest that carries almost no gamma but does carry
  noise. On this reading ±3 is the better measure and the ±10 result understates the effect.
* **(b) The measure has not converged and I am extrapolating off the end of the data.** The
  trajectory is monotone downward through ±9. Extrapolated naively, a full-chain measure would
  be **weaker**, not stronger — which would mean the ±10 result is partly an artefact of
  truncation itself, i.e. a near-ATM-gamma effect wearing an NGE label.

I lean to (b) as the conservative default, and note that it compounds with the WEEK1-only
limitation in §15: the true whole-market measure adds both far strikes *and* other expiries,
both of which dilute.

**Convention sensitivities, for completeness.** β on ρ₁ at ±10: OTM-side IV / trading time
−0.0086; OTM-side / calendar −0.0088; own-side / trading −0.0094; own-side / calendar −0.0095.
Nothing here is driven by the maturity or implied-volatility convention.

---

## 7. Test 5 — Ahmed's critique. Incremental to implied volatility, or already priced?

Ahmed (2026) confirms the mechanism and argues it is economically redundant with what implied
volatility already prices. Aryan is a **buyer** of options, so he pays the implied price for the
realised movement he hopes to receive; a fully priced mechanism is not an edge.

### 7.1 The split verdict

| population | label | gamma alone | IV alone | gamma \| IV | attenuation | incremental R² |
|---|---|---|---|---|---:|---:|
| **ALL** | **ρ₁** | β −0.0086, t −2.32, R² 0.40% | t −0.13, **R² 0.0016%** | β −0.0086, **t −2.35, p 0.019** | **−0.7%** | **0.404%** |
| ALL | displacement | β −0.0300, t −2.00, R² 0.43% | t **+5.26**, **R² 5.54%** | β −0.0236, t −1.69, p 0.092 | **21.3%** | 0.263% |
| **NONEXPIRY** | **ρ₁** | β −0.0105, t −2.55, R² 0.62% | t +0.54, R² 0.028% | β −0.0104, **t −2.51, p 0.012** | **+1.1%** | **0.600%** |
| NONEXPIRY | displacement | β −0.0292, t −1.81 | t **+5.36**, **R² 9.21%** | β −0.0138, t −0.88, **p 0.38** | **52.8%** | 0.087% |
| POOL264 | displacement | β −0.1184, t −2.79, R² 3.37% | t +4.60, R² 13.46% | β −0.0874, t −2.21, p 0.028 | 26.1% | 1.80% |

**On path shape, Ahmed's critique does not bite.** Opening implied volatility explains
**0.0016%** of the variance of ρ₁ — it knows essentially nothing about whether a session will
trend or chop. So the gamma coefficient passes through the control **completely unchanged**
(attenuation −0.7%: it very slightly strengthens). Whatever ρ₁ information dealer gamma carries,
the option market is not pricing it.

**On volatility magnitude, Ahmed is right and it is not close.** Opening IV explains 5.5% of the
variance of realised displacement on all sessions and **9.2%** on non-expiry days, against
gamma's 0.43%. Controlling for it removes half the gamma coefficient and all of its significance.
The SqueezeMetrics claim that GEX beats VIX at forecasting realised volatility — which, if true
on NIFTY, would have been precisely the long-gamma edge the research report flagged as the one
encouraging possibility — **is not true here.** Opening ATM implied volatility beats gamma by an
order of magnitude on its own home ground.

### 7.2 Realised minus implied — the variable a buyer actually needs

Defined as realised 5-minute session volatility minus opening ATM implied volatility rescaled to
one trading day.

* Mean realised 0.616%, mean rescaled implied 1.183%, **mean spread −0.567%, positive on only
  2.7% of sessions.**
* Regressed on gamma imbalance: β −0.0092, t −0.52, **p = 0.60.** Nothing.
* Free legs: b_call −0.024 (t −0.61), b_put +0.024 (t +0.65). Nothing.
* Quartile ladder: −0.561 → −0.514 → −0.550 → **−0.643**, Spearman **−0.111, p = 5.5e-5**.
  Higher gamma ⇒ marginally *worse* realised-minus-implied, consistent with the stabilising
  mechanism, but the whole spread is **0.082 percentage points of daily volatility** — trivial.

**The level of that spread is not interpretable and I will not interpret it.** Intraday realised
volatility from 09:15 to 15:29 excludes the overnight gap, while the option's implied volatility
covers calendar time including it; and the archive's implied volatility was inverted by the
vendor under an unknown convention. The comparison is apples to oranges **in level**. Only the
cross-sectional variation is used, and the cross-sectional variation says the gamma signal is
worth 0.08pp of daily vol.

### 7.3 The decisive version of the Ahmed test

§4.3, fourth row, restated because it is the cleanest single demonstration in the study:

> A walk-forward model that **genuinely predicts realised displacement out of sample** — Spearman
> +0.143 (p < 0.0001), OOS R² +0.452%, quartiles monotone +0.4154% → +0.4536% → +0.5008% →
> +0.6192% with spread p < 0.0001 — produces a straddle ladder that runs **+2.05% → −0.53% →
> −3.97% → −4.62%.** The quartile predicted to move most is the quartile where buying
> optionality loses most.

That is Ahmed's thesis demonstrated rather than asserted, and on a genuinely out-of-sample
forecast rather than an in-sample one. **The forecastable part of NIFTY intraday movement is
already in the option price, and over-priced.** Any long-option strategy conditioned on
forecastable volatility on this market is buying the expensive days.

---

## 8. Summary of the five tests

| test | result |
|---|---|
| **1. Path quality on ex-ante NGE** | **Partial pass.** ρ₁: β −0.0086, t −2.32, p 0.021, R² 0.40%. Signs (−, +) = US convention. R², Kaufman ER null. |
| **2. The money test** | **Fail.** Ex-ante ladder −9.39pp (p 0.46) where the realised ladder gives +36.78pp (p 0.0009). Best full-sample cell +6.00pp is below the 8.63pp resolution floor; money placebo p = 0.709. |
| **3. Baltussen Table 7** | **Fail, and inverted.** Momentum present when gamma is POSITIVE (t +2.61) and reversing when negative — the mirror of the S&P result. Table 8 interaction +0.141 vs Baltussen's −123.04. |
| **4. Truncation** | **Ranking converges** (Spearman 0.998 at ±9→±10). **Coefficient does not** — it decays monotonically with width, so the full-chain value is unknown and probably smaller. |
| **5. Ahmed** | **Split.** Path shape survives the IV control intact (attenuation −0.7%). Volatility magnitude is 21–53% subsumed and loses significance. Walk-forward: predicting displacement works and buying it loses. |

---

## 9. The three attacks on the sign finding — and the one that lands

The (−, +) sign pattern is the study's most quotable result, so it was attacked directly.

### 9.1 Days to expiry — does not explain it

Gamma imbalance is mechanically a function of expiry proximity (+0.163 at one session to expiry,
+0.109 at five), and expiry-day pinning is a documented independent chop mechanism. If both
moved with the expiry clock the whole result would be an expiry artefact.

They do not. ρ₁ is essentially flat across the expiry clock (−0.051, −0.064, −0.054, −0.068,
−0.066 at 1–5 sessions), and **controlling for days-to-expiry strengthens the gamma coefficient**:

| label | raw β / t | with DTE fixed effects | within-DTE demeaned | attenuation |
|---|---|---|---|---:|
| **ρ₁** | −0.0086 / −2.32 | **−0.0095 / −2.53 (p 0.012)** | −0.0095 / −2.53 | **−11.0% (it strengthens)** |
| displacement | −0.0300 / −2.00 | −0.0312 / −2.08 | −0.0312 / −2.08 | −3.7% |

Free legs with DTE fixed effects: b_call −0.0136 (t −1.84), b_put **+0.0190 (t +2.75, p 0.006)**,
sign still (−,+). **Not an expiry artefact.**

### 9.2 Sampling frequency — does not explain it

If the association existed only at Barbon & Buraschi's five minutes it would be a property of
that grid, not of the session. ρ₁ was rebuilt at 1, 3, 5, 10, 15 and 30 minutes:

| bars | mean ρ₁ | β on imbalance | t | b_call (t) | b_put (t) | contrast | sign |
|---:|---:|---:|---:|---|---|---:|:--:|
| 1 min | +0.023 | −0.0026 | −1.29 | −0.0024 (−0.67) | +0.0074 (**+1.93**) | +0.0098 | (−,+) |
| 3 min | −0.025 | −0.0062 | **−2.01** | −0.0080 (−1.36) | +0.0134 (**+2.36**) | +0.0214 | (−,+) |
| **5 min** | −0.060 | **−0.0086** | **−2.32** | −0.0124 (−1.77) | **+0.0187 (+2.76)** | +0.0311 | (−,+) |
| **10 min** | −0.046 | **−0.0099** | **−2.31** | −0.0151 (−1.94) | **+0.0219 (+2.80)** | **+0.0370** | (−,+) |
| 15 min | −0.071 | −0.0053 | −1.03 | −0.0105 (−1.14) | +0.0128 (+1.33) | +0.0233 | (−,+) |
| 30 min | −0.088 | +0.0037 | +0.55 | +0.0084 (+0.71) | −0.0015 (−0.12) | −0.0099 | (+,−) |

The sign holds from 1 to 15 minutes, peaks at **10** rather than 5, and only flips at 30 minutes
where there are 12 bars per day and ρ₁ is barely estimable. On non-expiry sessions the put leg is
significant at 1, 3, 5 and 10 minutes (t = 3.15, 2.06, 2.61, 2.69). **Not a five-minute-grid
artefact.**

**One thing that does not corroborate.** The Lo–MacKinlay variance ratio VR(3) — a different
re-expression of the same trend-vs-chop axis — shows **nothing at any frequency**: its best cell
anywhere is 3-minute bars at p = 0.076 (all sessions) and p = 0.066 (non-expiry), and every other
frequency is above 0.19. ρ₁ and VR(q) ought broadly to agree. That they do not means the effect lives
specifically in the **lag-1** autocorrelation and does not extend to the aggregated variance
ratio, which makes it materially weaker evidence than the ρ₁ table alone suggests. Reported
because it cuts against the finding.

### 9.3 Recent returns and recent volatility — explains about a fifth

Call open interest builds above spot and put open interest below it, so the split may encode
where the market has recently been, in which case this is return-conditioned mean reversion — a
long-known effect with nothing to do with dealers.

The legs *are* heavily loaded on recent volatility, and mechanically so: **Γ ∝ 1/σ**, so
gamma-weighted open interest is high when volatility is low. corr(z log Σ Γ·OI_call, prior
5-session realised vol) = **−0.414**; for puts, **−0.465**. The normalised imbalance largely
divides this out (+0.075).

| controls | b_call (t) | b_put (t) | contrast | R² |
|---|---|---|---:|---:|
| none | −0.0124 (−1.77) | +0.0187 (**+2.76**) | +0.0311 | 0.61% |
| prior 1/5/22-session returns | −0.0106 (−1.48) | +0.0191 (**+2.80**) | +0.0297 | 1.72% |
| + prior realised vol, opening IV | −0.0105 (−1.44) | +0.0148 (**+2.14**) | +0.0253 | 2.11% |
| + own lagged ρ₁ | −0.0105 (−1.46) | +0.0149 (**+2.13**) | +0.0255 | 2.49% |

The contrast falls 18% and the put leg stays significant. **Partially explanatory, not fatal.**

### 9.4 Open-interest placement — this one lands, and it is fatal to the causal reading

Gamma weights peak at the money. If the call and put open-interest **distributions** sit at
systematically different distances from spot, the two legs are sampling different parts of the
chain rather than encoding different positions. Measured: call open interest sits at a mean
open-interest-weighted offset of **+3.47 strikes**, put open interest at **−3.22**, each with a
day-to-day standard deviation of about **1.4 strikes**.

Adding those four placement variables (signed and absolute weighted offset, each side) as
controls:

| specification | b_call | t | b_put | t | contrast | sign | R² |
|---|---:|---:|---:|---:|---:|:--:|---:|
| gamma legs alone | −0.0124 | −1.77 | +0.0187 | **+2.76** | **+0.0311** | (−,+) | 0.61% |
| **+ open-interest placement** | **+0.0090** | **+0.92** | **−0.0030** | **−0.34** | **−0.0120** | **(+,−)** | **1.97%** |

**The sign pattern flips, both legs go to nothing, and the placement variables carry three times
the explanatory power the gamma legs did.** Once you know where the standing open interest sits
relative to spot, the gamma-weighted magnitudes tell you nothing further about ρ₁.

**What this does and does not mean.**

* It does **not** mean the ρ₁ association is spurious. The placement variables are themselves
  measured at 09:15 from prior-session open interest, so they are equally ex ante and equally
  legitimate as predictors. Something in the pre-session option chain does carry ρ₁ information.
* It **does** mean the *dealer-position* interpretation is not established. The (−,+) pattern
  that reads as "dealers long calls, short puts" is substantially reproduced by "spot sits at
  such-and-such a distance from where the call and put open interest is piled up". Those are
  different mechanisms with different trading implications, and this design cannot separate them.
* **The placement variables were found by running a control regression, in a study that has
  already run 81 registered tests.** They are a post-hoc discovery inside a large search and are
  reported as a threat to the headline, **not promoted as a finding.** Anyone wanting to use
  them must test them on data this study has not touched.

### 9.5 Is the gamma weighting doing anything at all?

Same two legs, open interest summed with **no gamma weights**: b_call −0.0044 (t −0.74), b_put
+0.0096 (t +1.67), contrast +0.0140, R² 0.25%. Against the gamma-weighted +0.0311 and 0.61%.

So gamma weighting roughly **doubles** both the contrast and the explained variance — it is not
decorative. But the raw open-interest version carries the same sign pattern at about half
strength, which means a good deal of what looks like a *gamma* result is really an *open
interest* result that gamma sharpens.

---

## 10. Stability, out of sample, and walk-forward

### 10.1 The effect is concentrated in one year

| split | N | β on ρ₁ | NW t | classical t | p | sign pattern |
|---|---:|---:|---:|---:|---:|:--:|
| **first half** (2021-01-01 … 2023-09-01) | 660 | **−0.0125** | **−2.30** | −2.38 | **0.022** | (−,+) |
| **second half** (2023-09-04 … 2026-05-12) | 660 | −0.0049 | −0.97 | −0.92 | 0.333 | (−,+) |

By year: 2021 −0.0121 (t −1.43), 2022 −0.0016 (t −0.19), **2023 −0.0320 (t −3.79)**,
2024 −0.0006 (t −0.06), **2025 +0.0069 (t +0.79, wrong sign)**, 2026 −0.0188 (t −1.38).

Leave-one-year-out:

| year dropped | β | t | % of full β |
|---|---:|---:|---:|
| 2021 | −0.0077 | −1.90 | 90% |
| 2022 | −0.0101 | −2.50 | 119% |
| **2023** | **−0.0032** | **−0.79 (p 0.43)** | **37%** |
| 2024 | −0.0104 | −2.49 | 121% |
| 2025 | −0.0121 | −3.01 | 142% |
| 2026 | −0.0078 | −2.06 | 92% |

**Dropping any year except 2023 leaves the result significant. Dropping 2023 destroys it.** One
of six years carries roughly 63% of the five-year coefficient. The sign is negative in five of
six years, which is some comfort, but only one year is individually significant and 2025 points
the other way.

### 10.2 A genuine out-of-sample split fails

Fit the two-leg model on the first half only (b_call −0.0176, b_put +0.0245, contrast +0.0421),
freeze the weights, apply to the second half:

* OOS R² = **+0.118%**
* Pearson(prediction, actual) = **+0.055, p = 0.16**
* Terciles of the frozen prediction: −0.0711 → −0.0507 → −0.0556. **Not monotone.** Spread
  0.0155 in ρ₁ units against an ρ₁ standard deviation of 0.135 — **0.11 sd**.

### 10.3 Walk-forward does slightly better on the label, and still nothing on the money

Expanding-window fit, minimum 250 training sessions, 1,067 live sessions from 2022-01-06:

| predicted label | Spearman | p | OOS R² | label quartiles | monotone |
|---|---:|---:|---:|---|:--:|
| ρ₁ (free legs) | +0.061 | 0.048 | +0.109% | −0.0708 → −0.0645 → −0.0503 → −0.0495 | **yes** |
| ρ₁ (imbalance) | +0.063 | 0.041 | +0.014% | −0.0660 → −0.0656 → −0.0524 → −0.0511 | **yes** |
| displacement (free legs) | **+0.143** | **<1e-5** | **+0.452%** | +0.4154 → +0.4536 → +0.5008 → +0.6192 | **yes** |

So the model **does** carry genuine out-of-sample information about both labels, monotonically —
that is a real positive result and it should not be buried. It is also tiny: the ρ₁ quartile
spread is 0.021 units, 0.16 standard deviations. And it converts to nothing at all in money
(§4.3), or worse than nothing on the volatility channel (§7.3).

---

## 11. Placebos

### 11.1 Best-of-grid, coherent day permutation

Grid: ALL_SESSIONS × 4 labels × 5 chain widths × {GEX composite, gamma imbalance, free call,
free put} = **80 cells**. Statistic: smallest p and largest |t| anywhere in the grid. The
permutation reindexes the **NGE regressor block only** — the labels keep their own dates — so it
destroys the day alignment of dealer gamma and leaves every other feature of both series intact.

The primary permutation is a **circular rotation** by a random offset, not a shuffle. NIFTY
gamma imbalance has lag-1 autocorrelation 0.132 and a strong secular trend; a plain shuffle
destroys both and makes the placebo too easy to beat, which would *overstate* the observed
result. The rotation preserves them. Both are reported; the rotation is the one quoted.

| statistic | observed | rotation placebo median | rotation 5th pct | **empirical p** |
|---|---:|---:|---:|---:|
| best-of-grid p | **4.73e-05** | 0.0433 | 0.0011 | **0.0115** |
| best-of-grid \|t\| | **4.08** | 2.02 | 3.27 (95th) | **0.0115** |
| (random shuffle, same statistic) | — | 0.0612 | 0.0026 | 0.0005 |

At least one cell reaches raw p < 0.05 in **54.9%** of rotation draws, which is why the
correction is necessary.

**This is the first time on this project that a best-of-grid statistic has beaten its own
placebo.** For scale: `GATE_B_VOLUME_OI_STUDY.md` returned empirical p = 0.76, and
`GATE_B_EARLY_EXIT_SCAN.md` returned p = 0.85 — in both cases the placebo's *median* draw beat
the real data. Here the real data sits at the 1.2th percentile of its own placebo.

**Two qualifications that matter.** The winning cell is `w3 / absolute displacement / call leg` —
the **volatility** label, not the path-shape label, and the volatility channel is the one Ahmed's
IV control disposes of (§7.1). And a permutation test rejects *chance alignment*; it says nothing
about the effect living in one year, which §10.1 shows it does.

### 11.2 A targeted single-statistic placebo on ρ₁ — no best-of-grid needed

Because the best-of-grid winner is the wrong label, the ρ₁ claim gets its own test on **one
pre-specified statistic**: the free-coefficient contrast (b_put − b_call) on ρ₁ at the primary
chain width. Positive under the US convention plus mechanism; negative under an inverted Indian
dealer position. One number, no maximisation, no correction required. 5,000 draws.

| population | observed contrast | placebo mean (sd) | 95th pct | **one-sided p** | two-sided p |
|---|---:|---:|---:|---:|---:|
| **ALL_SESSIONS** | **+0.0311** | −0.00025 (0.0126) | +0.0191 | **0.0040** | 0.0124 |
| **NONEXPIRY** | **+0.0374** | +0.00004 (0.0144) | +0.0223 | **0.0036** | 0.0080 |
| first half only | +0.0421 | — | — | **0.0094** | 0.0226 |
| **second half only** | +0.0203 | — | — | **0.1394** | 0.2879 |

The full-sample contrast is **2.5 standard deviations** above its permutation distribution. And
the last row is the honest counterweight: **in the second half of the sample alone, the same
statistic does not reject at all.**

### 11.3 The money placebo

Best |quartile spread| across the five money jobs. Observed **9.39pp**; rotation placebo median
**12.14pp**, 95th percentile 23.47pp; **empirical p = 0.709.** The best ex-ante money ladder
anywhere is worse than the median random rotation. This is the same result as
`GATE_B_EARLY_EXIT_SCAN.md` §4.3 and it is just as decisive.

---

## 12. Multiplicity

### 12.1 Count

**81 hypothesis tests are registered**, and nothing is exempted: 8 composite regressions,
8 imbalance regressions, 16 free-coefficient tests, 16 money-ladder spreads, 7 Baltussen splits,
20 truncation cells, 6 Ahmed tests. Registered per test, not per table.

**The true burden is larger than 81** and is stated rather than hidden. Not counted in the 81:
the 80-cell association grid inside the best-of-grid placebo (its correction is the placebo
itself); the frequency-sensitivity grid (36 cells); the robustness controls (four control sets
× two labels); the walk-forward evaluations (8 cells); the leave-one-year-out (6). Including
everything the search is roughly **150 comparisons**. Bonferroni at 150 would be α = 3.3e-4, and
nothing in this study reaches it.

### 12.2 Corrections on the registered 81

| | count |
|---|---:|
| raw p < 0.05 | **26 of 81** against **4.05 expected by chance** |
| **surviving Bonferroni** (α = 6.17e-4) | **0** |
| surviving Benjamini–Hochberg (threshold p ≤ 0.00275) | **5** |

The five BH survivors:

| family | test | p |
|---|---|---:|
| free legs | POOL264 / displacement / b_call | 0.00076 |
| truncation | ±3 / displacement | 0.00182 |
| truncation | ±3 / ρ₁ | 0.00196 |
| composite | POOL264 / displacement / GEX | 0.00274 |
| composite | ALL_SESSIONS / displacement / GEX | 0.00275 |

**Four of the five are the displacement label**, i.e. the volatility channel that Ahmed's control
disposes of. Only one is ρ₁, and it is at the narrowest chain width.

By family: composite 3 hits of 8 (0.4 expected), imbalance 3 of 8, free 3 of 16, truncation
**10 of 20** (1.0 expected), money 4 of 16, Baltussen 2 of 7, Ahmed 1 of 6. The truncation family
is not 10 independent findings — it is the same regression at five nested widths, and its hits
are almost perfectly collinear (Spearman 0.93–1.00 between widths). Counting it as 20 tests
*understates* the correction that family needs; counted honestly it is closer to two.

**Six-to-one against chance overall, and zero Bonferroni survivors.** That is a real signal that
is nowhere near strong enough to survive family-wise control — which is exactly what a 0.4%-R²
effect looks like.

---

## 13. Power

### 13.1 Association

| population | N | smallest detectable \|r\| at 80% power |
|---|---:|---:|
| **ALL_SESSIONS** | 1,320 | **0.077** |
| NONEXPIRY | 1,044 | 0.087 |
| EXPIRY | 276 | 0.168 |
| POOL264 | 264 | 0.172 |
| CONTROLS | 144 | 0.232 |
| FIRES120 | 120 | 0.253 |
| MIDIV33 | 33 | 0.471 |

**The observed Spearman on ρ₁ is −0.090 against a 0.077 detection floor.** This design can *just
barely* see this effect and nothing smaller. It is the reason the primary population had to be
all 1,320 sessions rather than the briefed 264: at N = 264 the floor is 0.172, twice the effect,
and this study would have returned a null it could not distinguish from a lack of power. **The
single most consequential design decision here was widening the population.**

Equivalently, the probability of detecting an r = 0.09 effect at α = 0.05 is **90.6% at
N = 1,320**, **30.8% at N = 264**, and **16.4% at N = 120**. Roughly **two in three** runs of the
briefed 264-day design would have missed this, and five in six of the Gate-B-fires design.

### 13.2 P&L

| population | series | N | mean | sd | 95% CI | smallest detectable mean | smallest detectable quartile spread |
|---|---|---:|---:|---:|---|---:|---:|
| ALL_SESSIONS | ATM straddle | 1,312 | −2.59% | 39.5pp | [−4.73, −0.46] | **3.05pp** | **8.63pp** |
| ALL_SESSIONS | ATM CALL | 1,313 | −1.79% | 92.4pp | [−6.79, +3.21] | 7.15pp | 20.22pp |
| POOL264 | Gate-B real | 245 | −8.10% | 44.7pp | [−13.69, −2.50] | 8.00pp | 22.66pp |
| FIRES120 | Gate-B real | 120 | −7.61% | 45.1pp | [−15.68, +0.47] | 11.54pp | 32.64pp |
| MIDIV33 | Gate-B real | 33 | −6.08% | 47.3pp | [−22.22, +10.07] | 23.08pp | 66.29pp |

**The money test was underpowered before it started, and this should have been said in advance.**
On FIRES120 the smallest detectable quartile spread is **32.64pp**. The realised-R² sort clears
it (+36.78pp) — barely. Nothing ex ante was ever going to. The full-sample straddle at
N = 1,312 is the only money design here with real resolution (8.63pp), and its observed ex-ante
spread of +6.00pp is below even that.

**What this means for the negative money verdict.** It is a genuine failure to find, not a
demonstration of absence. An ex-ante ladder worth 5pp on the straddle would be invisible to this
design and would still be worth having. The strongest thing that *can* be said is §11.3: the best
observed ladder loses to its own placebo's median, and no amount of low power manufactures that.

---

## 14. What I think is wrong, in both directions — including in my own work

Stated plainly, as asked.

### 14.1 Where I may be understating the result

1. **±3 strikes may be the right measure and I have led with ±10.** The coefficient is 30%
   larger and a full standard error stronger at ±3 (t −3.10 vs −2.32), and the near-ATM reading
   is where the hedging flow actually is. I led with ±10 because it is the widest thing the
   archive supports and because leading with the strongest cell of a five-cell ladder is exactly
   how this project has generated retractions before. But if someone re-runs this with a real
   full chain and finds the effect concentrated within ±3, that would not surprise me and it
   would mean the headline here is too conservative.
2. **WEEK1-only truncation dilutes toward zero, it does not manufacture a signal.** Missing
   monthlies and further weeklies means the regressor is a noisy proxy for whole-market gamma.
   Classical measurement error attenuates coefficients toward zero. The true whole-market
   coefficient is plausibly larger in magnitude than what is reported here.
3. **The out-of-sample tests are harsh in a specific way.** The walk-forward re-estimates the
   within-year standardisation on a truncated history, so early live predictions use a badly
   scaled regressor. A properly specified real-time design with a longer burn-in would do better
   than the 1,067-session version reported.
4. **N = 1,320 sessions is 1,320 sessions, not 1,320 independent observations** of the gamma
   state. Gamma imbalance has lag-1 autocorrelation 0.13 and a strong secular trend; the
   effective sample for the *regressor* is smaller than 1,320, which means the true standard
   errors on the level regressions are wider than Newey–West with five lags reports. This cuts
   against the result, but it is listed here because the *permutation* tests in §11 do not have
   this problem — the circular rotation preserves the autocorrelation exactly — and those are the
   inference I would actually rely on.

### 14.2 Where I think the result is weaker than it looks

1. **§9.4 is, in my judgement, the most important paragraph in this document, and it is bad news
   for the headline.** Controlling for where the standing open interest sits relative to spot
   flips both signs and kills both legs, and the placement variables carry three times the R².
   I do not think the dealer-position interpretation is established. I think something in the
   pre-session option chain predicts ρ₁ and that gamma-weighted net position is at best a
   partial and possibly a misleading parameterisation of it.
2. **The whole thing is 2023.** Drop one year of six and t goes from −2.32 to −0.79. I have seen
   enough single-year effects on this project to expect this one to be a single-year effect.
3. **Test 3 contradicts Test 1 and I cannot resolve it.** The Baltussen replication comes back
   with the opposite sign at t = +2.61 and a Table 8 interaction of the opposite sign at
   t = +2.27. §5.1 offers three readings. I believe reading 1 (both are noise) is the most likely
   and I would not have said so if Test 1 had failed and Test 3 had passed.
4. **VR(3) does not corroborate ρ₁** (§9.2). Two measures of the same axis should agree. They do
   not, and I take that as evidence the ρ₁ result is narrower than "dealer gamma predicts session
   shape".
5. **The best-of-grid placebo passing is less impressive than it reads.** Its winner is the
   volatility label at the narrowest width, and the volatility channel is exactly the one §7
   shows is subsumed by implied volatility. The placebo confirms that *something* non-random is
   in the grid; it does not confirm that the something is the path-shape claim. §11.2 is the test
   that speaks to the path-shape claim, and it splits by half-sample.
6. **I widened the population beyond the brief and that was a search decision.** The brief named
   the 264-day pool as primary. I ran 1,320 sessions because a market-wide mechanism should be
   tested market-wide and because §13.1 shows N = 264 could not have resolved this effect. But
   the honest accounting is that I chose the population after seeing that the narrower one had
   no power, and a reader is entitled to discount for that. Both populations are reported in
   every table so the choice is auditable.
7. **The `POOL264` displacement cells top the BH list and they are the least trustworthy cells
   in the study.** POOL264 is triply conditioned (non-expiry, gap-down, gap fills after 09:17),
   its displacement is mechanically related to whether a gap fills, and its P&L is a
   direction-taking CALL. Nothing about that population is clean, and it should not be the
   headline just because it has the smallest p-value.

### 14.3 What I think is wrong with the surrounding work, not just mine

1. **`TREND_DAY_FORECASTABILITY_RESEARCH.md` §3.4 states the expected sign as "b_C > 0, b_P < 0",
   which is the sign pattern of the GEX construction rather than of the ρ₁ regression** — it
   composes the position assumption without the mechanism's negative sign. Anyone reading that
   line and this study's fitted (−, +) would conclude the Indian convention is *inverted*, which
   is the opposite of what the data say. §2.4 sets it out explicitly for that reason. This is a
   presentational slip in an otherwise careful report, not a substantive error, but it is exactly
   the kind that produces a confidently backwards signal.
2. **The project's incumbent path-quality label is the wrong one and this study is the evidence.**
   Straight-line R² returns p = 0.66 where ρ₁ returns p = 0.021 on the identical days and the
   identical regressor. Every prior null on this project that used R², Choppiness, ADX or the
   Kaufman ER as the label was, on this evidence, using a label with less power than the one it
   should have used. That does not overturn those nulls — the effect found here is far too small
   to have shown up in any of them — but it does mean they are slightly weaker nulls than they
   were reported as.
3. **The 264-day pool has been treated as "the population" across several studies on this project
   and it is not a population, it is a triple conditioning.** §13.1 quantifies the cost: an
   r = 0.09 effect has a 21% chance of detection there. Several of this project's nulls were
   run at that N or smaller.

---

## 15. What could not be tested — no substitutes were fabricated

1. **The chain is truncated at ±10 strikes (±500 points, ≈±2.2%).** §6 measures the consequence
   rather than waving at it: the ranking converges, the coefficient does not, and the trajectory
   points down.
2. **WEEK1 expiry only.** Total market gamma includes monthlies, quarterlies and further-dated
   weeklies, all absent. **This is nearest-weekly NGE, not whole-market NGE.** The interpretive
   cost is specific and worth naming: the omission is *systematic*, not random. It drops exactly
   the slow-moving longer-dated positioning that gives the US measure its low-frequency
   variation, so the measure here is biased toward high-frequency, near-expiry, retail-driven
   positioning. Every statement in this document should be read as being about **nearest-weekly
   dealer gamma**, and the honest expectation is that a whole-market measure would be smoother
   and, because measurement error attenuates, larger in coefficient.
3. **No lot-size multiplier** (§2.3). Cannot be verified from this archive.
4. **No futures tape**, so the futures-basis and full-term-structure GEX of Baltussen's
   construction are unavailable.
5. **No participant-wise open interest.** NSE publishes FII / DII / Pro / Client open interest
   daily and free. That is the direct measurement of the net end-user position, and it would
   settle §9.4 — whether the (−,+) pattern is a dealer position or an open-interest-placement
   artefact — in a way this archive cannot. **This is the single highest-value data acquisition
   this line of work needs**, and it is more valuable than a wider strike chain.
6. **One-minute bar closes, not fills.** Every money number is bar-close to bar-close. No
   bid-ask, no slippage, no impact. `gate_b_exit_grid_real.py` bounds the NIFTY weekly one-minute
   spread using the bar range; nothing in this document is net of costs, and all of it is
   negative gross, so costs would only worsen it.
7. **No spot intraminute high/low exists in this archive** (verified in
   `GATE_B_VOLUME_OI_STUDY.md` §3.1: the `spot` column is identical across all 42 option files at
   every minute). ρ₁ and every other label here are built on minute closes.
8. **No peer-reviewed NIFTY dealer-gamma result exists to check this against.** The research
   agent found only two zero-citation working papers, one on a 28-trading-day sample
   (3 Feb – 13 Mar 2026). There is nothing to replicate and nothing that replicates this. That is
   what makes a careful null here a contribution, and it is also why nothing in this document
   should be trusted until someone reproduces it on independent data.

---

## 16. Reproducibility

All files new; nothing pre-existing was modified. Run in order.

| file | what it is |
|---|---|
| `nge_common.py` | data layer: 09:15/15:29 snapshot extraction, ex-ante audit, trading-time maturity, Black–Scholes gamma, path labels, per-date NGE at five widths × two IV modes × two maturity conventions |
| `nge_stats.py` | OLS with classical and Newey–West standard errors, within-group z-scores, Bonferroni/BH, power |
| `nge_path_quality.py` | the five briefed tests, both placebos, power, multiplicity registry |
| `nge_robustness.py` | days-to-expiry confound, sub-period stability, HAC-vs-classical, targeted ρ₁ placebo, per-minute |
| `nge_robustness2.py` | sampling-frequency sensitivity, leave-one-year-out, out-of-sample split, half-sample placebos |
| `nge_robustness3.py` | the three attacks on the sign finding, full sign table |
| `nge_walkforward.py` | expanding-window real-time money test |
| `nge_open_snapshot.pkl`, `nge_open_snapshot_audit.json` | 109,909-row snapshot cache and its audit |
| `nge_daily.pkl`, `nge_daily_build_diag.json` | per-date NGE and label panel |
| `nge_panel.csv` | the merged analysis panel, 1,320 rows |
| `nge_rho1_frequencies.csv` | ρ₁ and VR(3) at six sampling frequencies |
| `nge_path_quality_results.json` | main results (177 KB) |
| `nge_robustness_results.json`, `nge_robustness2_results.json`, `nge_robustness3_results.json` | robustness |
| `nge_walkforward_results.json` | walk-forward |

Seed 20260823 throughout. Association placebo 2,000 draws, targeted ρ₁ placebo 5,000, money
placebo 2,000. `gate_b_common.reproduction_guard` runs upstream of the Gate-B money series and
passes.

Environment: `.ml_venv/bin/python` (numpy 2.0.2, pandas 2.3.3, scipy 1.13.1). `statsmodels` is
absent from that environment, so OLS, Newey–West, Bonferroni, Benjamini–Hochberg and the power
calculations are hand-implemented in `nge_stats.py` — visibly, and short enough to audit.

**Offline analysis only. No broker, credential, exchange network, or order path was used
anywhere. No live order exists or is authorised.**
