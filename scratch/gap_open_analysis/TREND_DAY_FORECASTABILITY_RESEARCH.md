# Forecasting Intraday Path Quality (Trend vs Chop): What the Literature Knows

**Research date:** 2026-08-23
**Question:** Conditional on information available early in a session, can we forecast whether
the rest of the session will TREND (high net displacement per unit path length — a long option
profits) or CHOP (low displacement per unit path length — theta destroys a long option)?
This is a question about **directional efficiency / path quality**, not about direction and not
about volatility magnitude.

**Motivating result already established on Aryan's data (not re-derived here):** on 120 NIFTY
sessions, sorting by realised straight-line R² of the intraday path gives −21.6% (choppiest
quartile) to +6.8% (smoothest) on a long ATM call, monotone, spread +19.2pp, p=0.022. But
first-30-min R² vs rest-of-session R² has r=+0.134 (p=0.17), and Choppiness Index, ADX,
Kaufman ER and one-timeframing all fail to predict it.

---

## 1. Direct answer

**Short version: yes, but not from the price path — and the literature explains precisely why
the price path cannot work.**

There are two distinct findings, and keeping them apart is the whole point.

### 1a. The price path cannot forecast its own future efficiency. This is a theorem, not bad luck.

Aryan's null (r=+0.134, n.s.) is exactly what continuous-time estimation theory predicts.
For a diffusion `dS/S = μ dt + σ dW` observed over a **fixed calendar span** T:

- The **diffusion** coefficient σ² is estimable to arbitrary precision by sampling more finely
  within T. `Var(σ̂²) → 0` as Δt → 0.
- The **drift** μ is **not** estimable to any better precision by sampling more finely.
  `Var(μ̂) = σ²/T` — it depends *only* on the calendar span, and not at all on sampling frequency.

This is Merton (1980, JFE, ~4,550 citations). Bandi & Phillips (2003, *Econometrica*) restate
it flatly: the drift "is not estimable over a fixed span of time, no matter how frequently the
data are sampled (see Merton (1980))… [whereas] the diffusion function is estimable over a
fixed span of time."

Path quality is a **drift-to-diffusion ratio**. Net displacement over path length, straight-line
R², the Kaufman Efficiency Ratio and the Choppiness Index are all — up to monotone transforms —
estimates of |μ|/σ over the window. The denominator is the estimable part; the numerator is the
inestimable part. **Measuring path quality more finely, or over a longer intraday window, buys
you essentially nothing on the component that actually matters.** A first-30-minute efficiency
reading is a drift estimate over a 30-minute span, which is a nearly worthless drift estimate,
which is why it does not predict the next five hours.

This asymmetry is the documented result the brief asked about, and it is the single most
important thing in this report. Its empirical counterpart is the contrast between the
realised-volatility forecasting literature — Andersen–Bollerslev, Corsi's HAR-RV, and the
whole long-memory RV programme, where out-of-sample R² of 0.4–0.6 is routine — and the
return-predictability literature, where an out-of-sample R² of 0.005 is a publishable result.
A recent clean side-by-side: Fang & Ślepaczuk (arXiv:2606.09478, 2026) run both on the same
high-frequency CSI 300 sample 2005–2023 and report that "regime-aware volatility forecasting
consistently outperforms baseline HARQ models across forecast evaluation metrics… In contrast,
**return predictability remains weak, state-dependent**, and concentrated primarily in
low-volatility regimes."

**Corollary you should act on:** stop trying to forecast smoothness from smoothness. Any
path-derived trendiness statistic is a drift estimator wearing a costume, and it inherits the
drift's inestimability.

### 1b. Something *exogenous to the price path* does forecast it: dealer gamma positioning.

The escape route is to condition on a variable that is **not** an estimate of drift from prices
— a variable that describes the *mechanism* which will convert order flow into price path over
the coming session. Option dealer gamma positioning is that variable, and it is computed from
**option open interest by strike**, which Aryan already has, five years of it, and which is
known **before the session opens**.

The strongest evidence is Baltussen, Da, Lammers & Martens, "Hedging demand and market intraday
momentum," *Journal of Financial Economics* 142 (2021) 377–403 — peer-reviewed, 95 citations,
60+ futures across four asset classes, 1974–2020. Their Table 7 (S&P 500, Jan 1996 – May 2020),
regressing last-half-hour return on rest-of-day return, split by the sign of the **prior day's**
net gamma exposure:

| Prior-day NGE | β (×100) | Newey–West t | R² |
|---|---|---|---|
| NGE_{t−1} ≥ 0 (dealers long gamma) | 0.82 | 1.03 | **0.05%** |
| NGE_{t−1} < 0 (dealers short gamma) | 6.63 | **4.78** | **3.58%** |

Read that again: **the trend-continuation effect is completely absent when dealers are long
gamma, and strongly present when they are short.** An eightfold coefficient difference and a
70× difference in R², switched by a variable observable before the open. That is the
trend-vs-chop conditioning the brief asked for, and it is exactly the structure of Aryan's
quartile result — except the sorting variable is knowable in advance rather than realised.

Their Table 8 confirms it continuously rather than by sign: interacting scaled NGE with the
rest-of-day return gives a coefficient of **−123.04 (t=−3.42)** — the more negative the dealer
gamma, the stronger the intraday trend persistence — and this survives a difference-in-difference
specification against a shared time trend, and holds using puts only.

**Even more directly on path quality:** Barbon & Buraschi, "Gamma fragility" (Univ. of St. Gallen
/ Imperial working paper, 2020, 29 citations) use **the autocorrelation coefficient ρ of intraday
returns sampled at 5 minutes** as the dependent variable, and state their results "help to
explain both intra-day volatility **and autocorrelation of returns**." Intraday return
autocorrelation is a cleaner, better-behaved measure of exactly the trend-vs-chop axis than
straight-line R² — positive ρ₁ *is* a trend day, negative ρ₁ *is* a chop day. The companion
paper (Barbon, Buraschi, Beckmeyer & Mörke, 2021) states the sign convention explicitly: a large
**negative** aggregate gamma imbalance makes delta-hedging destabilising, a **positive** one makes
it stabilising.

### 1c. The honest caveats, stated up front

1. **The mechanism being real does not make it tradable.** Ahmed (2026, SSRN working paper,
   0 citations) titles his paper "*Mechanism Without Edge*" — he confirms that "positive (negative)
   dealer gamma forecasts mean reversion (momentum)" and then argues the effect is economically
   redundant with what implied volatility already prices. Aryan is buying a long option, so he
   pays the implied-volatility price for the realised volatility he hopes to receive. **The edge,
   if it exists, must be in realised-minus-implied, not in realised alone.**
   The one encouraging piece here is SqueezeMetrics' own claim that GEX beats VIX at forecasting
   realised volatility (see §3), which if true on NIFTY is precisely a long-gamma edge.
2. **The sign convention may be inverted in India.** See §3.4 — this is the largest single risk
   in porting this to NIFTY, and it is testable rather than fatal.
3. **For 0DTE the sign is actively contested.** Aryan trades nearest-weekly, which spends much of
   its life at 0–4 DTE. Brogaard, Han & Won (2023) find 0DTE trading *increases* volatility and
   that "the destabilizing effect of speculative trading outweighs the stabilizing" hedging
   effect. Adams, Fontaine & Ornthanalai (2024) find the opposite — liquidity providers in 0DTE
   produce **volatility attenuation**. Dim, Eraker & Vilkov (2023, 39 citations) link intraday
   net gamma in 0DTEs to underlying **return autocorrelation** specifically. The literature has
   not settled this. Do not assume the S&P-500-all-expiries sign carries to NIFTY weeklies.

### 1d. The second, weaker, but genuinely forecastable route: volatility state

Because volatility *is* forecastable and directional efficiency is not, the productive
decomposition is:

> long-option path payoff = (forecastable volatility state) × (unforecastable directional sign)

and there is direct academic evidence that the trend-following payoff loads on the forecastable
factor. Lundström (2017, Umeå School of Business working paper, 6 citations) tests the Opening
Range Breakout strategy — the canonical "catch the trend day" rule — sorted into **deciles of
daily return volatility**, on long series of crude oil and S&P 500 futures. Result: average daily
ORB return rises approximately monotonically across volatility deciles, with a spread of
**~200 bp/day (crude) and ~150 bp/day (S&P 500)** between the highest and lowest volatility
state, with 95% HAC confidence intervals. Trend-day payoff is a function of volatility state.

This is the academic vindication of Crabel's folklore. Lundström states the folklore precisely
and attributes it: Crabel's (1990) **Contraction–Expansion principle**, in which "daily price
movements seem to alternate between regimes of contraction and expansion… **On expansion days,
prices are characterized by intraday momentum, i.e., trends, whereas prices move randomly on
contraction days.**" Lundström then notes the resemblance to ordinary volatility clustering
(Engle 1982) — which is the point. The forecastable half of Crabel's principle is just the
volatility half.

**The catch, and it is a big one for Aryan specifically:** he is *long* the option. Sorting into
a high-volatility state is only useful if implied volatility has not already repriced it. This is
the vol-crush problem already visible in his Gate B work. So the volatility route must be run as
realised-vs-implied, not realised alone — which loops back to why the gamma variable is the
interesting one, since its claimed value is precisely forecasting realised volatility *better
than the option market's own price does*.

---

## 2. Methods ranked by testability on Aryan's existing archive

Archive assumed: 5 years of NIFTY nearest-weekly option 1-minute bars — open, high, low, close,
iv, volume, oi, strike, spot — for CALL and PUT. No futures tape, no breadth, no further expiries.

### Rank 1 — Net Gamma Exposure (NGE/GEX) from weekly option OI. Fully computable today.

Everything needed is in the archive: `strike`, `oi`, `iv`, `spot`, and time-to-expiry from the
bar timestamp. Black–Scholes gamma:

```
d1 = [ ln(S/K) + (r + σ²/2)·T ] / (σ·√T)
Γ  = φ(d1) / (S · σ · √T)          where φ(x) = exp(−x²/2)/√(2π)
```
with `S` = spot, `K` = strike, `σ` = the bar's `iv`, `T` = years to expiry, `r` ≈ MIBOR/T-bill.
Γ is the same for a call and a put at the same strike (put–call parity), so the sign is imposed
by the dealer-position assumption, not by the option type's gamma.

Then, following Baltussen et al. eq. (13) and SqueezeMetrics (see §3 for the exact convention
and the sign warning):

```
NGE = Σ_{calls, strikes} Γ_c · OI_c · M · S  −  Σ_{puts, strikes} Γ_p · OI_p · M · S
```
`M` = contract multiplier (100 for SPX; for NIFTY it is the lot size — **which has changed over
the sample and must be handled per-period; verify against your own archive**). Because the main
Baltussen result keys on the **sign** of NGE, a constant multiplier error within a period is
harmless to the primary test and only matters for the continuous-interaction version.

**Tests, in order:**

- **(1a) Direct replication of Baltussen Table 7.** Compute `NGE` at the previous session's
  close. Regress rest-of-day → last-30-min spot return, split on `sign(NGE_{t−1})`. Expect
  β ≈ 0 for NGE ≥ 0 and β strongly positive for NGE < 0. This is a pure spot test — no option
  P&L, no vol-crush confound, no transaction costs. **Run this first**; it is the cleanest
  possible falsification of whether the mechanism exists in NIFTY at all.
- **(1b) The new test nobody has published.** Regress your own realised path-quality label
  (straight-line R², or better ρ₁ below) on `NGE_{t−1}`. This is the direct answer to the
  research question and it is a two-hour job on data you already have.
- **(1c) The money test.** Re-run the long-ATM-call quartile study, but sort by `NGE_{t−1}`
  instead of by realised R². If the −21.6% / +6.8% spread survives an *ex-ante* sort, that is
  the result.

### Rank 2 — Change the label from straight-line R² to 5-minute return autocorrelation ρ₁.

This is a free improvement and it is what the gamma literature actually uses (Barbon & Buraschi).

```
r_i  = log(S_{t_i}) − log(S_{t_{i−1}})        for 5-minute bars i = 1..n
ρ₁   = Σ_{i=2..n} (r_i − r̄)(r_{i−1} − r̄) / Σ_{i=1..n} (r_i − r̄)²
```
ρ₁ > 0 ⇒ trending / high directional efficiency. ρ₁ < 0 ⇒ chop / mean reversion.
Equivalently the Lo–MacKinlay variance ratio `VR(q) = Var(q-period return) / (q · Var(1-period
return))`; VR > 1 ⇒ trending, VR < 1 ⇒ mean-reverting, VR = 1 ⇒ random walk.

Why bother: straight-line R² is dominated by the realised drift magnitude and is therefore a
noisy drift estimator (§1a). ρ₁ and VR are second-moment ratios — they measure the *shape* of the
path while dividing out the drift — so they are statistically far better behaved and are the
quantity the gamma mechanism actually predicts. **Recommend re-running the existing autocorrelation
null (first-30-min vs rest-of-day, r=+0.134) with ρ₁ as the label before concluding it is dead.**

### Rank 3 — Volatility-state conditioning, run as realised-minus-implied.

Sort sessions by a forecastable volatility state and check the long-option payoff. The state
variable must be ex-ante: prior-day realised volatility, a HAR-RV forecast, or the opening ATM IV.

HAR-RV (Corsi), the standard benchmark:
```
RV_t = Σ_i r_{i,t}²      (sum of squared intraday returns)
RV^{(d)} = RV_{t−1};  RV^{(w)} = mean(RV_{t−1..t−5});  RV^{(m)} = mean(RV_{t−1..t−22})
RV_t = c + β_d·RV^{(d)} + β_w·RV^{(w)} + β_m·RV^{(m)} + ε_t
```
Lundström predicts long-option/trend-following payoff increases in the volatility decile. But
**you must run the payoff net of the implied volatility you paid**, i.e. sort on
`E[RV] − IV_open²` rather than `E[RV]`, or the vol-crush effect already documented in Gate B
will eat the entire result. Feasible today: you have `iv` in the archive.

### Rank 4 — Opening Range Breakout, as a *label*, with a volatility-scaled threshold.

Crabel's rule as formalised by Holmberg, Lönnbark & Lundström (2013, *Finance Research Letters*
10, 27–33) and Lundström (2017):

```
ψ^upper_t = P^open_t + ρ ;   ψ^lower_t = P^open_t − ρ        (log prices, ρ in %)
long if price crosses ψ^upper from below; short if it crosses ψ^lower from above; exit at close.
```
Lundström tests ρ ∈ {0.5%, 1.0%, 1.5%, 2.0%}. For NIFTY, scale ρ to prevailing volatility rather
than fixing it. Note the rule contains an implicit chop filter — the threshold exists specifically
to "avoid market noise that does not result in trends" (Crabel via Lundström) — but the threshold
is a *fixed* filter, not a forecast, which is why it does not solve Aryan's problem on its own.
Its use here is as a **cheap, well-defined trend-day label** to cross-check the R²/ρ₁ labels.

### Rank 5 — Zarattini/Aziz/Barbon "Noise Area" (2024, Swiss Finance Institute working paper, 8 citations).

Concept, verified from Scholar snippets: "We define the Noise Area as the space between 2
boundaries. These boundaries are time-of-day [dependent]…" and one goes long above the upper
boundary, short below the lower. It is a volatility-normalised displacement-from-open filter —
i.e. an explicit chop filter, and the closest practitioner-quant analogue to what Aryan wants.
The natural reconstruction, which is what related papers describe, is:

```
σ(τ)   = mean over the past N days of |P(τ)/P(open) − 1|      (τ = time of day)
Upper(τ) = P_open · (1 + m·σ(τ));   Lower(τ) = P_open · (1 − m·σ(τ))
```
**I was unable to retrieve the exact published formula — SSRN is Cloudflare-blocked from this
host (see §6). Treat the above as a reconstruction, not as the paper's specification.**
Testable on Aryan's `spot` series today.

### Rank 6 — Charm and vanna flows. Testable in principle, weakest evidence, most work.

Charm = ∂Δ/∂t, vanna = ∂Δ/∂σ. Both are computable from the same BS inputs already in the archive
and both are plausibly larger than gamma for near-expiry weeklies. But I found **no peer-reviewed
paper establishing that charm/vanna exposure forecasts intraday path quality** — the literature
on them is descriptive and practitioner-driven. Low priority relative to Ranks 1–3.

### Not testable on this archive

Market breadth / advance-decline (no constituent data), the futures basis and the full-term-structure
GEX (no futures tape, no further-dated expiries), and any measure requiring signed order flow or
participant-category open interest (NSE publishes participant-wise OI separately — see §3.4 —
but it is not in this archive).

---

## 3. Dealer gamma exposure in full detail

### 3.1 The exact SqueezeMetrics construction (primary source retrieved)

Source: SqueezeMetrics Research / Prior Analytics LLC, *"Gamma Exposure (GEX)™ — Quantifying
hedge rebalancing in SPX options,"* March 2016, revised December 2017. Retrieved in full from
`https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf` (8 pages).

**The four assumptions**, quoted:
1. "All traded options are facilitated by delta-hedgers."
2. "**Call options are sold by investors; bought by market-makers.**"
3. "**Put options are bought by investors; sold by market-makers.**"
4. "Market-makers hedge precisely to the option delta." (They acknowledge real dealers use
   hedging bands, and use the raw delta anyway.)

**The formula**, quoted verbatim:

> To calculate the GEX (in shares) of all call options at a particular strike price in a contract:
> **GEX = Γ · OI · 100**
> Where Γ is the option's gamma, OI is the open interest in the particular option strike, and 100
> is the adjustment from option contracts to shares of the underlying.
> In the case of put options:
> **GEX = Γ · OI · (−100)**
> The share adjustment is negative here because for market-makers, where calls represent long
> gamma, puts represent short gamma.
> The GEX of a stock (or index) is the summation of GEX at every strike price in every available
> contract.

They note that "when computing for SPX, we denominate GEX in dollars" — i.e. multiply the share
figure by spot.

**The claimed market impact**, quoted:

> "a GEX figure that is positive implies that option market-makers will hedge their positions in
> a fashion that stifles volatility (buying into lows, selling into highs). A GEX figure that is
> negative implies the opposite (selling into lows, buying into highs), thus magnifying market
> volatility. A corollary is that a GEX figure approaching zero will allow the market to move
> naturally and without any particular interference."

**Their claimed effect size** — and note carefully what is and is not claimed. Their headline
number is about **volatility magnitude, not path quality**: 1-day standard deviation of SPX
returns is 0.55% following the highest GEX quartile vs 0.85% following the second-highest. Their
comparison claim against VIX is the interesting one: VIX's lowest and second-lowest quartiles
give 0.51% and 0.66%, i.e. barely distinguishable — "A VIX of 12 means about the same as 15 when
it comes to predicting variance." They also concede VIX correlates 0.85 with the *previous*
month's realised volatility versus 0.75 with the *next* month's.

**Grading:** this is category (b) — a fully specified, testable construction with a claimed effect
size but **no stated sample period, no significance test, no out-of-sample procedure, and it is a
commercial vendor's marketing document.** Its value to Aryan is the formula and the sign
convention, not the evidence. The evidence is Baltussen's.

### 3.2 The academic construction (Baltussen et al. 2021, eq. 13)

Independently derived, and the authors state they "verified the computations of SqueezeMetrics
using OptionMetrics data over the 2002 to 2017 period, yielding virtually identical results."

Their assumptions are identical to SqueezeMetrics' four. Their formula, for a call at strike
`s`, maturity `m`, day `t`:

```
NGE^C_{s,m,t} = Γ^C_{s,m,t} · OI^C_{s,m,t} · 100 · P_t
```
"where Γ is the option's gamma, OI is the option's open interest, and 100 is the adjustment from
option contracts [to shares]"; `P_t` is the index level. Puts enter with the opposite sign.
Aggregate over all strikes and maturities. For the regression version they scale:
`X_t = NGE_t / (market value of the S&P 500)`.

Note their **footnote 8**, which is unusually candid and matters for Aryan: NGE computed this way
"is on average positive for most days," and they attribute this partly to the data — OptionMetrics
covers listed options only, so "our sample misses many long puts and short calls typically done
OTC by institutional investors." The measure is a **proxy for end-user demand under a crude sign
assumption**, not a measurement of dealer books.

### 3.3 What the evidence actually shows — effect sizes and samples

| Claim | Source | Sample | Effect | OOS? |
|---|---|---|---|---|
| Intraday momentum absent when dealers long gamma, strong when short | Baltussen et al. 2021 Tbl 7 | SPX, Jan 1996–May 2020 | β=0.82 (t=1.03), R²=0.05% vs β=6.63 (t=4.78), R²=3.58% | In-sample regression; effect robust across 1974–2020 subperiods for the base momentum result |
| Momentum strengthens continuously as gamma goes more negative | Baltussen et al. 2021 Tbl 8 | same | NGE×r_ROD = −123.04 (t=−3.42); survives diff-in-diff; holds puts-only | In-sample |
| Base intraday momentum (unconditional) | Baltussen et al. 2021 Tbl 6 | 60+ futures, Dec 1974–May 2020 | Sharpe 0.87–1.73; equity index η(r_ROD) 6.86%/yr, SD 3.96%, SR 1.73, hit rate 0.55 | Long multi-decade sample, 4 asset classes; no formal OOS split |
| Gamma imbalance explains intraday **autocorrelation** of returns | Barbon & Buraschi, "Gamma fragility," 2020 (WP, 29 cites) | SPX / US equities | ρ of 5-min intraday returns; sign flips with gamma imbalance | Working paper |
| Negative (positive) gamma imbalance ⇒ destabilising (stabilising) delta hedging at the close | Barbon, Buraschi, Beckmeyer & Mörke 2021 (WP, 11 cites) | US equities, intraday TAQ | directional, sign confirmed | Working paper |
| Positive/negative dealer gamma forecasts mean reversion/momentum — **but no tradable edge** | Ahmed 2026 (SSRN WP, 0 cites) | 5 asset classes incl. NIFTY | mechanism confirmed, argued redundant with IV | Working paper |
| 0DTE trading **increases** volatility; speculation outweighs hedging | Brogaard, Han & Won 2023 (SSRN WP, 21 cites) | SPX 0DTE | directional | Working paper |
| 0DTE liquidity providers **attenuate** volatility | Adams, Fontaine & Ornthanalai 2024 (SSRN WP, 5 cites) | SPX 0DTE | directional, opposite sign | Working paper |
| Pinning to strikes near expiry (a chop mechanism) | Ni, Pearson & Poteshman 2005, *JFE* (204 cites); Golez & Jackwerth 2012, *JFE* (43 cites) | US equities / S&P 500 futures | price clustering at strikes on expiration dates | Peer-reviewed |

### 3.4 The single biggest risk in porting this to NIFTY: the sign may be inverted

Both constructions hard-code **"investors buy puts and sell calls; dealers sell puts and buy
calls."** That assumption is calibrated to the US institutional equity complex, where portfolio
insurance and call overwriting dominate — Baltussen cite Bollen & Whaley (2004) and Gârleanu,
Pedersen & Poteshman (2008) for net long end-user put demand, and a JP Morgan estimate that
"short puts are by far the most dominant positions of option market makers."

**The Indian weekly index option market does not obviously have this structure.** It is
overwhelmingly a retail-dominated, short-dated market, and the well-publicised pattern is heavy
retail *option selling* alongside speculative buying, with prop desks and FIIs on the other side.
If the net end-user position in NIFTY weeklies is short rather than long, **the sign of the
mapping from OI to dealer gamma flips**, and a naive port of the US convention would give you the
correct mechanism with the wrong sign — which would look like a clean null, or worse, a
confidently backwards signal.

**Do not assume; measure.** Concretely:
1. Run test (1a) with the US sign convention *and* with the inverted convention. The Baltussen
   asymmetry is sharp enough (R² 0.05% vs 3.58%) that whichever convention is right should be
   visible.
2. Better: drop the assumption entirely and estimate the sign. Fit
   `ρ₁(day t) = a + b · |NGE|_{t−1} · sign_convention + ε` under both conventions and let the
   data pick. Or treat the call and put legs as **separate regressors with free coefficients**
   rather than imposing +1/−1 — this is strictly more general and is the cleanest fix:
   ```
   ρ₁,t = a + b_C · (Σ Γ·OI)_calls,t−1 + b_P · (Σ Γ·OI)_puts,t−1 + ε
   ```
   If the US convention is right you should recover `b_C > 0, b_P < 0`. If India inverts, you get
   the opposite. If neither, the mechanism is absent. This single regression is the highest
   information-per-unit-effort test in this entire report.
3. NSE publishes participant-wise open interest (FII / DII / Pro / Client) daily. That is not in
   Aryan's archive but it is free and it would let the sign be pinned down directly rather than
   inferred. Worth acquiring.

### 3.5 Truncation caveat

SqueezeMetrics and Baltussen both sum "**every strike price in every available contract**" —
all expiries. Aryan has **nearest-weekly only**. In NIFTY, near-dated weeklies carry a large
share of total gamma, so the truncated measure is probably a decent proxy, but it is a proxy,
and the omission is systematic rather than random (it drops precisely the slow-moving monthly
and quarterly positioning that gives the US measure its low-frequency variation). This weakens
the measure but does not invalidate it — and it is a reason to prefer sign-based tests over
level-based ones.

---

## 4. Evidence-graded source table

### (a) Peer-reviewed, or working papers with a stated sample and result

| Source | Year | Venue / status | What it establishes |
|---|---|---|---|
| Merton, "On estimating the expected return on the market" | 1980 | *JFE*, ~4,550 cites | **The drift/diffusion estimation asymmetry.** Variance estimable by finer sampling; drift is not, at any frequency, over a fixed span. |
| Bandi & Phillips, "Fully nonparametric estimation of scalar diffusion models" | 2003 | *Econometrica*, 477 cites | Restates Merton flatly: drift "not estimable over a fixed span of time, no matter how frequently the data are sampled." |
| Baltussen, Da, Lammers & Martens, "Hedging demand and market intraday momentum" | 2021 | *Journal of Financial Economics* 142:377–403, 95 cites | **The core result.** Prior-day dealer gamma sign switches intraday momentum on and off. Full text retrieved (pure.eur.nl). |
| Gao, Han, Li & Zhou, "Market intraday momentum" | 2018 | *JFE*, 315 cites | Establishes the base intraday momentum effect (first half-hour → last half-hour) that Baltussen conditions. |
| Ni, Pearson & Poteshman, "Stock price clustering on option expiration dates" | 2005 | *JFE*, 204 cites | Option positioning pins prices to strikes near expiry — a documented *chop* mechanism. |
| Golez & Jackwerth, "Pinning in the S&P 500 futures" | 2012 | *JFE*, 43 cites | Pinning at the index-futures level. |
| Holmberg, Lönnbark & Lundström, "Assessing the profitability of intraday opening range breakout strategies" | 2013 | *Finance Research Letters* 10:27–33 | ORB returns exceed trading costs on crude oil over a long series — **but significantly positive only in the 2001–2011 subperiod, i.e. not robust across time.** |
| Lundström, "Day trading returns across volatility states" | 2017 | Umeå SBE WP, 6 cites | **ORB returns rise ~monotonically across volatility deciles**; ~200 bp/day (crude), ~150 bp/day (S&P 500) top-vs-bottom decile, 95% HAC CIs. Formalises Crabel's C-E principle. Full text retrieved. |
| Barbon & Buraschi, "Gamma fragility" | 2020 | St. Gallen / Imperial WP, 29 cites | Gamma imbalance explains **intraday return autocorrelation** — the closest published result to Aryan's exact question. |
| Barbon, Buraschi, Beckmeyer & Mörke, "The role of leveraged ETFs and option market imbalances on end-of-day price dynamics" | 2021 | WP, 11–13 cites | Sign convention: negative gamma imbalance ⇒ destabilising hedging. |
| Dim, Eraker & Vilkov, "0DTEs: trading, gamma risk and volatility propagation" | 2023 | WP, 39 cites | Links intraday net gamma in 0DTEs to underlying return autocorrelation. Uses intraday OI by trader type. |
| Brogaard, Han & Won, "Does 0DTE options trading increase volatility?" | 2023 | WP, 21 cites | 0DTE **increases** volatility; speculation dominates hedging. |
| Adams, Fontaine & Ornthanalai, "The market for 0DTE: liquidity providers in volatility attenuation" | 2024 | WP, 5–8 cites | 0DTE liquidity provision **attenuates** volatility. Contradicts the above. |
| Fang & Ślepaczuk, "Volatility forecasting and return prediction under market regimes" | 2026 | arXiv:2606.09478 | Same sample, both tasks: regime-aware volatility forecasting works; **return predictability "remains weak, state-dependent."** Clean empirical statement of the asymmetry. |
| "Structural limits of OHLCV-based intraday signals in MNQ futures: a systematic falsification study" | 2026 | arXiv:2605.04004 | **14 intraday signal families, 947 days of 5-min MNQ data 2021–2025, walk-forward OOS. None passed.** Max gross return 0.07–1.50 pts/trade vs 2-pt friction. Includes positive controls proving the framework can detect real edge. A rigorous documented null. |
| Fang, Qin & Jacobsen, "Technical market indicators: an overview" | 2014 | *J. Behavioral & Experimental Finance*, 42–84 cites | Survey of the technical-indicator evidence base. (Abstract not retrievable from this host; cited for the survey's existence and its well-known conclusion that most indicator claims lack support.) |
| Dew-Becker & Giglio, "The decline of the variance risk premium" | 2025 | WP, 10 cites | Uses net S&P 500 dealer gamma exposure; relevant to whether the gamma effect is already priced. |
| Chhimwal, Pandey & Pandey, "Effect of multiple index derivative expiry on volatility, volume, and connectedness" | 2025 | *Review of Derivatives Research* | India-specific: 1-min intraday data for Nifty 50 and Bank Nifty around weekly expiries. Closest peer-reviewed India work found. |

### (b) Specific, testable rule — no adequate evidence

| Source | Rule | Evidence status |
|---|---|---|
| SqueezeMetrics GEX white paper (2016/2017) | `GEX = Γ·OI·100` for calls, `Γ·OI·(−100)` for puts, summed over all strikes and expiries | Formula fully specified and verified against Baltussen. **Effect claims have no stated sample, no test statistic, no OOS.** Vendor marketing document. |
| Crabel (1990), Contraction–Expansion principle / ORB / NR7 | Days alternate between contraction and expansion regimes; expansion days trend, contraction days are random. Trade breakouts of `P_open ± ρ`. | Rule is precise. The *conditioning claim* (that you can tell which regime you are in ex ante) has no evidence in Crabel. Lundström (2017) supplies the only real test I found, and what he validates is the **volatility-state** version, not a path-shape version. |
| Zarattini, Aziz & Barbon (2024), "Noise Area" | Time-of-day-dependent volatility-scaled boundaries around the open; trade only outside them | SFI working paper, 8 citations, has a stated backtest. **Exact formula not retrievable — SSRN blocked (see §6).** Two follow-up papers exist (Paz 2026 OOS evaluation; Maróy 2025 parameter optimisation), both also SSRN-blocked. |
| Steidlmayer / Market Profile — initial balance, range extension, elongated profiles | A narrow initial balance with early range extension marks a trend day | **No adequate evidence found.** Notably, La Manna (2026, SSRN) claims to offer "the first formal empirical treatment of Market Profile concepts" and states that "no study has empirically tested whether profile shape [predicts]…" — i.e. a practitioner claiming the evidence base is empty. Treat all Market Profile trend-day rules as untested. |
| Raschke, *Street Smarts* — trend day identification | Various first-hour rules | **Could not verify from a primary source in this session** (see §6). Do not act on my paraphrase. |

### (c) Discarded

Searches on "choppiness index," "trend day," "ADX trend strength" and similar return overwhelmingly
content-marketing material from broker and charting-platform blogs: indicator definitions restated,
illustrative cherry-picked charts, no samples, no statistics, no out-of-sample tests. I have not
listed any of it. Similarly discarded: the large recent tail of 0-citation SSRN and predatory-journal
"deep learning predicts intraday direction" papers, which typically report in-sample accuracy on
tiny samples. Two are named in §6 only because they are India-specific and Aryan may encounter them.

---

## 5. What the literature says is NOT possible, and why

This section is the most actionable part of the report, because it tells Aryan what to stop doing.

1. **You cannot forecast path efficiency from the path.** Merton (1980) / Bandi & Phillips (2003).
   Path quality is a drift-to-diffusion ratio; the drift is not estimable over a fixed span at any
   sampling frequency. Aryan's r=+0.134 between first-30-min R² and rest-of-day R² is not a failure
   of measurement or of indicator choice — it is the predicted result. **Refining the indicator
   will not fix it.** Choppiness Index, ADX, Kaufman ER and one-timeframing are all monotone
   re-expressions of the same inestimable quantity, which is precisely why all four failed
   together rather than one succeeding.

2. **The volatility/drift asymmetry is a documented result** — this was the specific question in the
   brief, and the answer is yes, emphatically, and it is stronger than "documented": it is a
   theorem with a 45-year-old canonical citation, plus an entire empirical literature (HAR-RV and
   descendants) on one side and a famously barren one on the other. Fang & Ślepaczuk (2026)
   demonstrate both halves on a single high-frequency sample.

3. **OHLCV-derived intraday momentum signals do not survive costs.** arXiv:2605.04004 (2026):
   14 signal families, 947 days of 5-minute MNQ futures, walk-forward OOS, minimum |t|=2.0,
   ≥30 trades, positive net of a 2-point round-trip. **Zero passed.** Gross returns 0.07–1.50
   points/trade against 2 points of friction. The study includes two positive controls that *do*
   pass, which is what makes it credible rather than merely underpowered. This is a direct,
   rigorous, recent confirmation that the family of methods Aryan has been testing is a known dead
   end — and it is a useful precedent for how to write up his own null.

4. **The base intraday momentum effect is real but is not a path-quality forecast.** Gao et al.
   (2018) and Baltussen et al. (2021) forecast the *sign* of the last 30 minutes from the sign of
   the rest of the day. That is directional continuation, not a statement that the path in between
   will be efficient. Do not conflate them.

5. **A confirmed mechanism is not a confirmed edge.** Ahmed (2026) argues the dealer-gamma effect
   is economically redundant with implied volatility. Holmberg et al. (2013) found ORB profitable
   only in one subperiod, i.e. not robust across time. Both are warnings that the correct outcome
   of Aryan's Rank-1 test could easily be "the mechanism is present in the spot path and still does
   not pay after the option's implied volatility and the bid-ask."

6. **The 0DTE sign is unresolved in the literature.** Brogaard/Han/Won vs Adams/Fontaine/Ornthanalai
   reach opposite conclusions on whether very-short-dated option activity amplifies or attenuates
   volatility. Since NIFTY weeklies live near expiry, Aryan should treat the sign as an empirical
   question in his own data rather than importing it.

7. **Market Profile trend-day rules have no evidence base at all** — asserted not by a critic but by
   a practitioner-author (La Manna 2026) attempting to build one.

---

## 6. What I could not determine

**Tooling limits encountered, stated so the gaps are auditable:**

- **SSRN is entirely inaccessible from this host** (Cloudflare 403 on both abstract pages and
  `Delivery.cfm` PDF links, with and without a Scholar referer). This is the largest gap. It cost
  me the full text of: Barbon & Buraschi "Gamma fragility"; Zarattini/Aziz/Barbon "Beat the Market"
  (and thus the exact Noise Area formula); all four 0DTE working papers; and Ahmed's "Mechanism
  Without Edge." For these I have **only Google Scholar snippets and titles** — the effect
  directions I report for them are from snippet text, and none of their effect *sizes* are verified.
- **General web search is effectively unavailable.** DuckDuckGo (lite and html endpoints) and
  Mojeek serve captchas; Brave and Ecosia return 403; Google and Yahoo require JavaScript; Bing
  silently truncates multi-word queries to the first term; every public SearXNG instance tried was
  rate-limited or down. Working paths were Google Scholar (HTML scrape), the OpenAlex API, the
  arXiv API, and direct URL fetches. **This is why the practitioner-canon section is the thinnest
  part of the report** — that material lives on the open web, not in indexed literature.
- `codex exec` was present at `/Users/maheit/.local/bin/codex` but I did not establish that it has
  independent web search; I did not pursue it further once Scholar and OpenAlex were working.

**Substantive questions I could not answer:**

1. **Whether the US dealer-position sign convention holds in NIFTY weeklies.** This is the pivotal
   unknown (§3.4). I found no study establishing the net end-user option position in Indian index
   weeklies. It is resolvable from data — NSE participant-wise OI, or the free-coefficient
   regression in §3.4 — and it should be resolved *before* any GEX signal is trusted.
2. **The exact Zarattini Noise Area specification.** §2 Rank 5 gives a reconstruction, explicitly
   flagged as such.
3. **Toby Crabel's and Linda Raschke's actual published rules and any claimed hit rates.** I could
   verify Crabel's Contraction–Expansion principle only *through* Lundström's academic restatement,
   and could not verify Raschke's trend-day rules from any primary source. I have deliberately not
   paraphrased them from memory. If these matter, they need the physical books.
4. **Whether charm or vanna forecasts intraday path quality.** No peer-reviewed evidence found in
   either direction — this is an open question, not a null.
5. **Any peer-reviewed NIFTY-specific dealer-gamma result.** What exists is two 0-citation SSRN
   working papers: Sharma, Sharma & Kalra, "A regime-adaptive deep learning framework for intraday
   market direction forecasting using option chain microstructure signals" (uses GEX and
   "expiry-week gamma pinning" on Nifty option chains — but on a **~28-trading-day sample,
   3 Feb–13 Mar 2026**, which is far too short to support its claims), and Kalita, "Gamma and
   psychology: behavioral dynamics of the Indian options market" (2025). Both are named here for
   completeness and neither should be relied upon. **The gap this leaves is also the opportunity:
   testing dealer gamma against intraday path quality on five years of NIFTY weeklies appears to
   be genuinely unpublished work.**
6. **Effect sizes for the Fang/Qin/Jacobsen indicator survey** — the paper is real and well-cited
   but both the Edinburgh PDF (403) and the OpenAlex abstract field were unavailable, so I cite it
   only for its existence and general thrust, not for a specific number.
