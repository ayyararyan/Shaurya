# Primary-literature benchmark: five different order-flow objects, and which target each actually wins

**Purpose:** distinguish objects that are routinely conflated, state what the primary literature
finds each is strongest *for*, and compare today's `X-OFI-DAT20-03` / `X-CKS-L1-OFI-DAT20-04` work
honestly against them.

**Sourcing caveat, stated up front.** No web-literature agent was launched (explicitly instructed
not to). Every citation below is recalled from memory and carries author/venue/year so it can be
checked. Titles and years are reported to the precision I hold them; **treat the reference list as
verifiable-but-unverified** and confirm before it goes into any paper.

## The five objects are genuinely different

### 1. Signed trade imbalance (buyer- minus seller-initiated volume)
A **trade-side flow**: classify each execution as buyer- or seller-initiated (Lee & Ready 1991,
*JF*) and sum signed volume. Sees only executions; blind to resting-queue dynamics and to
cancellations.
Canonical results: Kyle (1985, *Econometrica*) and Glosten & Milgrom (1985, *JFE*) give the theory
(price moves linearly in signed order flow via λ / adverse selection); Hasbrouck (1991, *JF*,
"Measuring the Information Content of Stock Trades") shows the trade innovation has a permanent
price impact via a structural VAR; Chordia, Roll & Subrahmanyam (2002, *JFE*) and Chordia &
Subrahmanyam (2004, *JFE*) show order imbalance predicts returns at daily frequency.

### 2. VPIN
Easley, López de Prado & O'Hara (2012, *RFS*, "Flow Toxicity and Liquidity in a High-Frequency
World"). Volume-synchronised probability of informed trading: bucket by **volume, not clock time**,
bulk-classify each bucket's buy/sell split, then average **|V_buy − V_sell| / V**.
Three reasons it is **not** the right sub-second directional comparator: it is **unsigned**, so it
speaks to toxicity and volatility rather than direction; its native resolution is the volume
bucket, i.e. minutes-to-hours, not 0.5–10 s; and Andersen & Bondarenko (2014, *Journal of
Financial Markets*) showed a good deal of its flash-crash predictive claim is an artifact of the
volume clock and bulk classification. VPIN answers "how adversely selected am I about to be", which
is a market-maker risk question, not "which way does the mid go next".

### 3. Exact CKS L1 OFI
Cont, Kukanov & Stoikov (2014, *Journal of Financial Econometrics*, "The Price Impact of Order Book
Events"). The `e_n` object in our spec: a **best-quote event flow** in contracts, counting queue
additions, depletions and price improvements at L1 only.
Headline result: regressing the **contemporaneous** mid-price change on OFI over ~10-second
intervals gives **R² of roughly 65%** on US equities, far above trade-imbalance specifications on
the same data; the relation is **linear**, and the impact coefficient is **inversely proportional
to depth** — which is precisely why our spec scales by `mean_l1_depth_window`.
**The critical caveat, and the one most often lost:** that ~65% is *contemporaneous*, same-interval.
CKS is a price-*impact* / *explanation* result, not a forecasting result. Predictive power at a
strictly future horizon is dramatically smaller.

### 4. Static L1 queue / order-book imbalance
`I = (q^B − q^A) / (q^B + q^A)` — a **state variable**, not a flow. Gould & Bonart (2016, *Market
Microstructure and Liquidity*, "Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order
Book") find it is among the best single predictors of the **direction of the next mid-price move**,
especially for large-tick instruments; Lipton, Pesavento & Sotiropoulos (2013) give the
fill-probability treatment; Stoikov (2018, *Quantitative Finance*, "The Micro-Price") turns it into
an imbalance-weighted fair value that dominates the plain mid.
Strength is concentrated at the **very next event**; it mean-reverts quickly, so it decays fast at
fixed seconds-ahead horizons.

### 5. Multi-level order-flow / depth imbalance
OFI computed level-by-level across the first several levels and combined (usually PCA or a
regression/ML stack). Xu, Gould & Howison (2018, *Market Microstructure and Liquidity*); Cont,
Cucuringu & Zhang (2023, *Quantitative Finance*) on multi-level and cross-impact OFI; Kolm, Turiel &
Westray (2023, *Mathematical Finance*, "Deep Order Flow Imbalance") on multi-horizon forecasting.
Consistent finding: **multi-level OFI subsumes L1 OFI** and is materially stronger for
**seconds-ahead future returns**, with most incremental content in roughly the first ten levels.

## Which object wins which target

| Target | Strongest object in the primary literature |
|---|---|
| Direction of the **next** price move / one tick ahead | **Static L1 queue imbalance**, microprice (Gould–Bonart; Stoikov) |
| **Contemporaneous** mid change over an interval | **Exact CKS L1 OFI** (~65% R², CKS 2014) |
| **Seconds-ahead future** return | **Multi-level OFI** (Cont–Cucuringu–Zhang; Kolm–Turiel–Westray); L1 OFI alone is clearly weaker |
| Permanent impact / information content, minutes to days | **Signed trade imbalance** (Hasbrouck; Chordia et al.) |
| Toxicity / adverse-selection risk | **VPIN** (unsigned; with the Andersen–Bondarenko caveat) |

## Honest comparison with today's results

1. **`X-OFI-DAT20-03`'s central finding is exactly what the literature predicts.** It searched 175
   price-keyed constructions and localised its lead in **levels 2–10, explicitly not level 1**. For
   a *seconds-ahead future return* target, that is the multi-level result of Cont–Cucuringu–Zhang
   and Kolm et al., reproduced independently on a NIFTY future. It is a consistency check passed,
   not an anomaly.

2. **Our target is the one CKS L1 is weakest at.** `X-CKS-L1-OFI-DAT20-04` applies an L1 event-flow
   object — whose famous strength is *contemporaneous explanation* — to *strictly future*
   returns at `h2 ≥ 0.5 s` behind a `Z = 0.5 s` causal gap. A weak forward result would therefore be
   the **expected** outcome under the literature, not a surprise, and must not be presented as
   novel. The one cell that legitimately compares to CKS's 65% is the spec's `VAL-CKS-02`
   **same-window diagnostic**, and the spec is right to forbid ranking it as forecasting power.

3. **The comparison is in any case compromised on this feed, and this dominates everything above.**
   Per amendment `ID-CKS-02`: median displayed spread is **100 ticks (tape A) / 134 ticks (tape B)**,
   and **42–48% of executions print strictly inside the displayed best bid/ask**. CKS's ~65% was
   obtained where L1 *is* the touch and spreads are ~1 tick. Here the displayed L1 is a wide outer
   band, not the touch, so a null result is at least as consistent with **level-1 mis-identification**
   as with the CKS object lacking content. It also gives a clean mechanical explanation for why
   `X-OFI-DAT20-03` found its signal *behind* level 1.

4. **VPIN is not a comparator we should run here** and no VPIN arm is proposed: unsigned, volume-
   clocked, and aimed at toxicity rather than a 0.5–10 s directional target. If toxicity becomes the
   question, it returns as the right tool — for a different question.

5. **The cheapest genuinely informative addition** — if any is wanted, and only as a small, clearly
   labelled robustness calculation on primitives already built — is **static L1 queue imbalance**
   `(q^B − q^A)/(q^B + q^A)` at the window-end snapshot, as one extra single-regressor arm. Both
   quantities are already computed for `l1_depth_end`, so it costs no new machinery, and it tests the
   one distinction the literature is sharpest about: **state (imbalance) versus flow (OFI)**. It
   should be reported as a labelled robustness arm and must not be expanded into a feature tournament.
