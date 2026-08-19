# Hypothesis testing method — binding on all of SIG

**Status:** adopted 2026-08-19 on Aryan's instruction; recorded as `D29`. Governs every `SIG` claim, every
`MK-*` gate, and every empirical statement the module makes about the market. Not
OFI-specific.

---

## 1. Why the claim ledger was not enough

`D22` gave us **claims** — directional propositions such as "OFI worsens fill-conditioned
markout". A claim is not testable. "OFI worsens markout" has no horizon, no clock, no
stratum, no effect size, and therefore no possible falsifier: any null can be answered with
"you measured it at the wrong horizon."

A claim is now a **family**. The testable atom is a **hypothesis**: one fully bound
instance of a claim in which every measurement axis is fixed to a concrete value before the
data are inspected. `D20` says the clock, pooling coordinate and horizon are empirical and
swept — this method is what makes a *sweep* a declared search space rather than a fishing
expedition, because each point in the sweep is a separately registered hypothesis and the
count of them is `SIG-12`'s grid size `G`.

```
Claim (EF-03)  →  Hypotheses (H-EF-03.1 … H-EF-03.k)  →  Trial log entries (SIG-19)
 directional        fully bound, pre-registered            executed, with results
```

## 2. The eight axes every hypothesis must bind

An unbound axis is not an omission — it is a **swept axis**, and it multiplies `G`. State
which it is. Silence is not permitted.

| # | Axis | Meaning | Failure if left implicit |
|---|---|---|---|
| 1 | **X** | Predictor: definition, construction, `CON-06` category | Feature drift between runs |
| 2 | **h₁** | Horizon over which X is accumulated | "OFI" means nothing without a window |
| 3 | **f₁** | Clock/frequency on which X is sampled | `D20`'s clock axis silently fixed |
| 4 | **Y** | Response: definition, `CON-06` category | Mid vs microprice vs executable mark are different objects |
| 5 | **h₂** | Horizon over which Y is measured | Overlap and `N_eff` uncomputable |
| 6 | **f₂** | Clock on which Y is sampled | Asynchronous-sampling bias |
| 7 | **Z** | **Causal gap** — elapsed time from the end of X's window to the start of Y's | `Z=0` is an identity, not a forecast. This is where leakage lives. |
| 8 | **Stratum** | Pooling coordinate: instrument, premium band, spread-in-ticks, DTE, TOD, `VOL-04` regime | Pooled estimates hide sign reversals |

### 2.1 Z is the admissibility axis

`Z` is not a nuisance parameter. It decides whether a result can ever be traded.

- **Z = 0** — contemporaneous. Permanently **descriptive**. May be used as an instrument
  check. May never enter an OOS comparison or an economic gate.
- **0 < Z < R** where `R` is the measured reaction path — **descriptive only**. The
  information exists but arrives too late to act on.
- **Z ≥ R** — **decision-relevant**.

`R` = feed cadence (`D27`, currently 500 ms for depth20) + transport + decision +
`MK-01` order/cancel acknowledgement. `R` is **measured, never assumed**. Until `MK-01`
lands, hypotheses must state the placeholder `R` they used and be re-graded when the real
number arrives. A hypothesis whose `Z` falls below the eventual measured `R` is
**demoted to descriptive, not deleted** — the measurement stays, the tradeability claim
goes.

## 3. The effect object: what "influences" is allowed to mean

"X influences Y" is not a permitted conclusion. The permitted conclusion states a
**magnitude with units on both sides**:

- **K** — effect size in **natural units** (e.g. ticks of mid per 100 contracts of OFI;
  ₹ per lot; basis points of premium), *and* in **standardised units** (change in Y per
  +1 SD of X), with a dependence-aware confidence interval per `SIG-11`.
- **N** and **N_eff** — raw and effective sample size, the latter accounting for overlap
  and autocorrelation. `N_eff` sits next to every t-statistic (`SIG-11`).
- **G** — the declared search-grid size the result must survive (`SIG-12`).
- **MDE** — the ex-ante minimum detectable effect (§5).

## 4. The mandatory resolution statement

A hypothesis is **resolved** only when this sentence can be completed with no blanks. If
any field is missing the hypothesis is still open, regardless of how suggestive the output
looked.

> Over **[sample: dates, instruments, session windows]** comprising **N = [...]**
> observations (**N_eff = [...]**), a **+1 SD = [K_x] [units]** change in **X = [...]**,
> accumulated over horizon **h₁ = [...]** on clock **f₁ = [...]**, is associated with a
> **K = [value] ± [CI] [units]** change in **Y = [...]**, measured over horizon
> **h₂ = [...]** on clock **f₂ = [...]**, beginning **Z = [...]** after the end of X's
> window, within stratum **[...]**.
> Search grid **G = [...]**; Romano–Wolf adjusted **p = [...]**. Ex-ante **MDE = [...]**.
> Admissibility: **decision-relevant** (Z ≥ measured R = [...] ms) / **descriptive only**.
> **Verdict: Confirmed / Falsified / Inconclusive.**

Worked example of the shape (illustrative, not a result):

> Over 2026-08-20 to 2026-08-26, NIFTY front-month future, 09:30–15:00, N = 180,000
> snapshot pairs (N_eff = 18,000), a +1 SD = 340-contract change in depth-delta OFI
> accumulated over h₁ = 1 s on the f₁ = 2 Hz depth20 clock is associated with a
> K = +0.021 ± 0.006 ticks change in mid, measured over h₂ = 5 s on the f₂ = 2 Hz clock,
> beginning Z = 0.5 s after the end of X's window, within the spread = 1 tick stratum.
> G = 180; Romano–Wolf adjusted p = 0.004. Ex-ante MDE = 0.011 ticks.
> Admissibility: descriptive only (Z = 500 ms < placeholder R = 900 ms).
> **Verdict: Confirmed, descriptive.**

## 5. Power is declared before running, not discovered after

**Every hypothesis carries an ex-ante MDE computed from the planned sample.** Without it,
"we found nothing" is uninterpretable and a null silently becomes a falsification.

`MDE` ≈ the effect size detectable at the post-multiplicity critical value `t*`:

$$R^2_{\min}\approx \frac{t^{*2}}{N_{\text{eff}}},\qquad
|K|_{\min}\approx t^{*}\cdot \mathrm{SE}(K),\qquad
\mathrm{SE}(\bar Y)\approx \frac{\sigma_Y}{\sqrt{N_{\text{eff}}}}$$

with `t*` raised for the declared `G` (Romano–Wolf), and `N_eff` reduced for overlap
(≈ N × f₂ / h₂ for overlapping windows) and for serial dependence.

**Planning figures for the accumulating tape** (assumptions stated; recompute per
hypothesis, do not reuse these):

- Current NSE F&O session 09:15–15:40 = 23,100 s. depth20 at the `DAT-16` measured 2.00
  bursts/s → **46,200 snapshots per instrument per day**; 5 sessions → 231,000.
- A target at h₂ = 5 s sampled every 0.5 s overlaps 10-fold → **N_eff ≈ 23,100** per
  instrument over 5 days.
- At `G = 200`, `t* ≈ 4.0` → **MDE on OOS R² ≈ 0.00069**. At `G = 20`,
  `t* ≈ 3.2` → ≈ 0.00044. Five days is therefore ample for *statistical* detection of small R².
- Markout hypotheses are counted in **prints, not snapshots**. `DAT-14` observed 313 prints
  in a 10-minute two-future window → ~6,025 prints/instrument/day → ~30,125 over 5 days,
  with block-bootstrap `N_eff` materially lower (assume ~3,000 pending measurement).
- **Power collapses with markout horizon, and this is the binding planning fact.** With
  `N_eff ≈ 3,000`, `SE(mean markout) ≈ σ/55`. At h = 1 s, σ ≈ 1–2 ticks → SE ≈ ₹0.001–0.002,
  tiny against the ₹0.0474/unit statutory round trip. At h = 60 s, σ is several rupees →
  SE ≈ ₹0.09, **larger than the entire cost floor**. So short-horizon markout hypotheses
  resolve within days; 60-second markout hypotheses need weeks and must say so up front
  rather than return a spurious null.

A hypothesis whose MDE exceeds any economically meaningful `K` is **not run**. It is
registered as `Deferred — underpowered at current sample`, with the sample size that would
change that.

## 6. Verdicts

| Verdict | Condition |
|---|---|
| **Confirmed** | Sign as pre-registered, `\|K\|` ≥ MDE, survives the `SIG-11` inference harness and `SIG-12` multiplicity control over the declared `G`, stable across `SIG-16` regimes |
| **Falsified** | Pre-registered falsifier fired, **and** the test was adequately powered (`MDE` < the effect size the claim needs to be economically relevant) |
| **Inconclusive** | `\|K\|` < MDE, or the sign is unstable across strata, or an instrument gate (`EF-01`-type) failed |
| **Demoted** | Confirmed but `Z < R` — real, not tradeable |
| **Deferred** | Not run: underpowered, or a dependency (`EXE-10`, `ANL-01`, `MK-01`) does not exist yet |

**`Inconclusive` is a first-class outcome.** An underpowered null reported as a
falsification is a scope reduction in disguise — it retires a claim without evidence.

## 7. Pre-registration is enforced by commit order, not by intention

A hypothesis is pre-registered when its row exists in a **pushed commit** whose timestamp
precedes the first execution of its test. Git gives us a tamper-evident clock; use it.

- The `SIG-19` trial log records, per execution: hypothesis ID, **the commit hash in which
  it was registered**, the code commit executed, the tape date range, and the result.
- A test executed against a hypothesis with no prior registering commit is recorded as
  **exploratory** and can never be promoted to Confirmed. It may motivate a new
  registration, which must then be tested on **held-out or subsequently-collected tape**.
- Amending a registered hypothesis creates a **new ID**. The old one stays with its
  original text. Nothing is edited into agreement with its result.

## 8. Standing prohibitions

1. No `Z = 0` result in an OOS comparison or economic gate.
2. No pooled estimate without the stratified version alongside it.
3. No t-statistic without `N_eff` beside it, and no finding without `G`.
4. No point estimate for a partially identified object — `EXE-10`'s queue bounds and
   `EF-07`'s OFI censoring interval propagate, they do not collapse (`D23`, `SIG-07`).
5. No verdict of Falsified without the power statement that licenses it.
6. No hypothesis added to the grid after results are inspected, for any reason.
