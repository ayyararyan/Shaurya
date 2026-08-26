# Gate B: does anything OUTSIDE the price path — volume, open interest, true intraminute OHLC — predict trendiness, direction, or P&L?

**Run date:** 2026-08-23
**Requested by:** Aryan, after every price-path indicator tested on this population came back
null, on the reasoning that volume and open interest are genuinely new information rather
than another re-slice of the same path.
**Task status:** **COMPLETE.** Every requested component ran: ADX and the Dreiss Choppiness
Index rebuilt on real intraminute high/low (A), volume features on the early window (B),
open-interest features (C), put-versus-call volume and OI at matched strikes (D), and the
decision rules the strongest associations imply, priced on real strike-tracked traded
premiums (E). Four components were added because the honest reading required them: a
**measured** quantification of the endogeneity threat rather than a caveat about it (§7), a
**selection audit** on which fires can even carry a trend indicator at the fill minute (§3.4),
a **secular-time-trend** check on the flow features (§7.3), and a **fully-exogenous subgrid**
isolating the only features no intraday path can have caused (§6.4).

**Evidence class:** exploratory association scan on **observed traded prices and observed
exchange flow data**. Not identification-grade, not manuscript-ready. Two of the twenty
features are graded `exogenous`; the rest are explicitly labelled as associations and are
not claimed as predictors anywhere in this document.

No broker, credential, exchange network, or order path was used. No live order exists or is
authorised. No pre-existing script or report was modified; every file listed in §13 is new.

---

## 0. Verdict

> **No. Nothing outside the price path predicts anything here either.** Across a 400-cell
> association grid — 20 features × 5 decision points × 4 targets — run separately on mid-IV
> (N=33) and pooled (N=120): **zero cells survive Bonferroni, zero survive Benjamini–Hochberg,
> in either population.** On the pooled fires **15 of 400 cells reach a raw p<0.05 against
> the 20 expected by chance** — fewer hits than chance. The best-of-grid |rho| is **0.261
> pooled, and the permutation placebo's *median* draw beats it at 0.286** (empirical
> p = 0.76). On mid-IV the observed best of 0.520 lands exactly on the placebo median of
> 0.519 (empirical p = 0.50).

And the single most decisive number in the study, because it needs no multiplicity argument
at all:

> **On days the gate did NOT fire, the same grid produces *stronger* associations than on days
> it did.** Best |rho| against real-premium P&L: pooled fires **0.261** vs pooled controls
> **0.302**; mid-IV fires **0.518** vs mid-IV controls **0.618**. Controls beat fires in six
> of the eight head-to-head target comparisons. Whatever the grid is picking up is a property
> of Indian equity-index option trading days, not of the Gate-B signal.

Four independent readings agree, and none of them depends on the multiplicity correction:

| measurement | what a real non-price-path signal predicts | what the data shows |
|---|---|---|
| raw hits in the 400-cell grid, pooled fires | more than the 20 expected by chance | **15 of 400 — fewer than chance** |
| best-of-grid \|rho\| against its own permutation placebo | observed above the placebo | **0.261 observed vs 0.286 placebo median, p = 0.76** |
| the same grid on control days (gate did not fire) | weaker than on fires | **stronger on controls, 6 of 8 targets** |
| the fully **exogenous** subgrid (09:15 OI snapshots) | some hits | **1 of 40 pooled, 0 of 40 mid-IV, against 2.0 expected** |

**Two things did change and both are worth having.** First, the choppiness/ADX null was
**not** an artefact of the close-only proxy: rebuilt on real intraminute high/low the
indicators shift substantially in *level* (Choppiness 48.2 on true OHLC versus 33.0 on the
proxy at entry+30) but rank-correlate 0.63–0.83 with the old ones and predict exactly as
little — best |rho| 0.261 true-OHLC versus 0.220 close-proxy on pooled fires. The proxy was
biased but it was not what was hiding a signal, because there is no signal to hide. Second,
the endogeneity the brief flagged is **real and large, and is now measured rather than
asserted**: the trend indicators correlate 0.43–0.49 with the absolute spot move over their
own measurement window, i.e. roughly half of what they are is a restatement of how far spot
happened to travel.

**This is a clean null and it is reported as decisively as a positive would have been.**

---

## 1. What is genuinely new here — and a correction to the brief's premise

The brief states that `volume`, `oi`, `open`, `high` and `low` "have never been used by
anything" in this project. That is right in substance and slightly overstated in letter, and
the difference matters for how novel this study actually is. Verified by direct grep over
every pre-existing script:

| column | prior use in this project | used as a signal before? |
|---|---|---|
| `oi` | **none whatsoever** | no |
| `open` | none (`analyze_k2_expiry_vix_rose.py:87` reads a *VIX* open, different data) | no |
| `volume` | tie-breaker in the duplicate-bar sort (`gate_b_common.py`, `gate_b_structure_search.py`); recorded as a liquidity diagnostic column in `analyze_k2_put_pnl.py:154,204-208` | **no** |
| `high`, `low` | `gate_b_exit_grid_real.py:205,209` uses the one-minute range as an **upper bound on the bid-ask spread**; `gate_b_structure_search.py:230-241` caches them for structure pricing | **no — cost estimation only, never a trend or chop indicator** |

So: open interest and the open price are untouched; volume has been used only for
housekeeping and as a printed diagnostic; high/low have been used only to bound a trading
cost. **None of the five has ever entered a predictor, a feature, or a decision rule.** The
brief's premise stands. This study is the first look at them as information.

---

## 2. Data layer, construction, and coverage audit

### 2.1 Source and rebuild

`/Users/maheit/.cache/openclaw/gdrive/.../dhan_fresh_2021_2026/options` — 2,772 one-minute
CSVs, CALL and PUT, WEEK1 expiry, 21 relative strikes, 2021–2026. All 2,772 files were read;
**zero were missing.** Restricted to the 264 dates in the Gate-B path pool this yields
**4,159,521 deduplicated contract-minute bars** across 264 dates and both sides, median 25
distinct absolute strikes per date per side.

Three properties of the source that shape everything downstream, each verified rather than
assumed:

1. **The relative-strike label rolls intraday and is unusable.** On 2022-02-25 the file named
   `ATM+6` carries absolute strikes 16850 → 16800 → 16850 → 16900 → … minute by minute, and
   its `oi` column swings from 16,700 to 567,000 inside one session **purely because it is
   describing different contracts**. Every quantity in this study is keyed on the **absolute**
   strike, never on the label. Any OI series built on the label would be pure noise.
2. **`volume` is per-bar, not cumulative.** The within-day first difference is non-negative
   on only 49.2% of bars, which is impossible for a running total.
3. **`oi` is a per-minute snapshot of that contract's open interest.** Held at absolute-strike
   level it is slow-moving, as open interest should be. Zero bars carry `oi = 0`.

### 2.2 Data-quality audit

| check | result |
|---|---|
| files read / missing | **2,772 / 0** |
| raw rows on the 264 pool dates | 4,159,602 |
| dropped for non-positive close | **0** |
| deduplicated rows | 4,159,521 |
| duplicate contract-minutes (two rel-strike files, same absolute contract) | **81, i.e. 0.002%** |
| …of which volume disagrees | 0.001% of groups |
| OHLC internally consistent (`low ≤ open,close ≤ high`) | **100.0000%** |
| zero-range bars (`high == low`) | 5.44% |
| zero-volume bars | 4.95% |

The dedup convention inherited from `gate_b_common.py` is *keep the highest-volume row*,
which for a volume study is upward-biased by construction. **It turns out not to matter:** it
is invoked on 81 of 4.16 million bars. Stated because inheriting it silently would have been
wrong even though the effect is nil.

### 2.3 Population

`gate_b_full_paths.load_full_paths()`, filtered to `vix_rose == 1`. A target needs at least
30 minutes of session remaining after its decision minute, so the latest-filling fires drop
out; **N is reported per cell everywhere** rather than being forced constant.

| population | N at the entry decision | date range |
|---|---:|---|
| **mid-IV fires (published Gate B)** | **33** | 2021-09-08 … 2026-01-29 |
| **pooled fires** (`vix_rose == 1`) | **116** (of 120; 4 fill too late) | 2021-09-08 … 2026-04-20 |
| pooled controls (`vix_rose == 0`) | 142 | 2021-01-05 … 2026-04-17 |
| mid-IV controls | 39 | 2021-01-15 … 2026-04-17 |

Fires surviving each decision point: entry 116, +15m 114, +30m 113, +45m 113, +60m 108.
Mid-IV holds all 33 at every decision point.

**Construction check.** The panel's own hold-to-close return on real strike-tracked traded
premiums is **−6.078% on mid-IV N=33**, reproducing the published Gate-B figure of −6.08% to
three decimals, and **−7.805% on pooled N=116** against the published −7.61% on N=120 (the
0.19pp difference is the four dropped late fires). The `gate_b_common.py` reproduction guard
runs upstream of the path cache and passes.

### 2.4 Feature coverage — the one real gap

| decision | trend/chop features | volume, OI, put/call features |
|---|---:|---:|
| **entry (the fill minute)** | **CHOP 62.9%, ADX 53.4%** | 100% (except `vol_trend`/`oi_trend` 75%) |
| +15m … +60m | 100% | 100% |

ADX(7) needs 15 bars and CHOP needs 8; a 09:18 fill has four. This is a genuine and
consequential gap, audited in §3.4.

### 2.5 Descriptive levels

Gate fires, entry-strike CALL, 09:15 → fill minute (archive units):

| quantity | median | IQR |
|---|---:|---|
| entry-strike CALL volume, 09:15 → fill | 14,381,239 | 5,922,349 – 41,672,100 |
| entry-strike CALL open interest at 09:15 | 3,014,371 | 1,910,850 – 4,624,210 |
| whole-chain volume (CALL+PUT), 09:15 → fill | 219,266,615 | — |
| entry strike's share of chain volume | **12.9%** | — |
| entry-strike OI change, 09:15 → fill | **+50.6%** | — |

Per-minute CALL volume grows 6.4× over the sample (median 19,500 in 2021 → 124,605 in 2026),
which is checked as a confound in §7.3.

---

## 3. (A) ADX and the Choppiness Index, rebuilt on REAL intraminute high/low

### 3.1 What was actually rebuildable, and what was not

**True intraminute high/low for NIFTY spot does not exist in this archive, and no substitute
was fabricated.** Verified directly: the `spot` column is a single snapshot per minute and is
**identical across all 42 option files at every one of 376 minutes tested** (cross-file spot
range = 0.0 points at every minute on 2022-02-25). There is no spot OHLC anywhere.

What does exist is true intraminute OHLC for the **traded option contract**, and that is what
was rebuilt on. This is defensible on its own terms and arguably better than a spot rebuild
would be:

* it is the instrument the trade is actually in;
* the CALL price is monotone increasing in spot, so its intraminute high and low correspond
  to the intraminute spot high and low;
* both the Choppiness Index and the ADX directional ratio are **scale-invariant** — a locally
  constant delta multiplies numerator and denominator alike and cancels — so over a short
  window they approximate the spot-based indicators up to that transform.

The caveat, stated rather than buried: the option's bar range also contains implied-volatility
movement and a minute of decay, and delta drifts over longer windows. So this is a *good*
proxy for real intraminute spot ranges, not an exact one. Both versions are computed and
compared.

Definitions used, unmodified from source:

* **Choppiness (E.W. Dreiss)**: `CHOP = 100 · log10(Σ TR / (max High − min Low)) / log10(n)`,
  n = 14 bars ending at the decision minute, with the pre-window bar supplied so the first
  true range is honest about its gap. ~100 = maximal chop; ~0 = one clean directional move.
* **ADX (Wilder)**: +DM/−DM, Wilder-smoothed at period 7, `DX = 100·|+DI − −DI|/(+DI + −DI)`,
  ADX = Wilder-smoothed DX. Period 7 rather than 14 because 14 would need 29 bars and would
  destroy what little entry-decision coverage exists. `dmi_call` is the raw signed spread
  `+DI − −DI`.

### 3.2 True OHLC versus the close-only proxy — levels and rank agreement

| decision | CHOP, true OHLC | CHOP, close proxy | ADX, true OHLC | ADX, close proxy | Spearman CHOP | Spearman ADX |
|---|---:|---:|---:|---:|---:|---:|
| entry | 39.58 (n=73) | 25.10 | 42.55 (n=62) | 36.06 | 0.708 | 0.715 |
| +15m | 49.02 (n=114) | 36.25 | 36.81 | 29.31 | 0.698 | 0.630 |
| +30m | 48.22 (n=113) | 33.04 | 33.54 | 27.47 | 0.698 | 0.705 |
| +45m | 47.20 (n=113) | 32.48 | 35.07 | 28.64 | 0.782 | 0.719 |
| +60m | 49.39 (n=108) | 33.39 | 35.29 | 27.59 | 0.828 | 0.727 |

**The proxy was materially biased in level and roughly right in rank.** Setting high = low =
close collapses the true range to |Δclose|, which understates the numerator far more than the
denominator, so the close-only Choppiness Index reads about **15 points too low** — it
systematically makes the session look more trending than it is. But the two rank-correlate
0.63–0.83, so a rank-based test on either sees mostly the same ordering of days.

Descriptively, on the true-OHLC version the session is **neutral, not choppy**: at entry+30
the mean CHOP is 48.2, with only **5.3% of fires above the 61.8 "choppy" threshold** and 16.8%
below the 38.2 "trending" one. By entry+60 it is 49.4 with 14.8% above 61.8. This is a
market that is neither trending nor consolidating by Dreiss's own cut-offs.

### 3.3 Did the rebuild change the answer? No.

Best |rho| anywhere in each family's own subgrid:

| population | true-OHLC family (60 cells) | close-only proxy (40 cells) | non-price-path (300 cells) |
|---|---|---|---|
| **pooled fires** | 0.261 (p=0.041), 5 hits vs 3.0 expected | 0.220 (p=0.085), 1 hit vs 2.0 | 0.209 (p=0.025), **9 hits vs 15.0 expected** |
| **mid-IV fires** | 0.518 (p=0.023), 5 hits vs 3.0 | 0.520 (p=0.002), 3 hits vs 2.0 | 0.478 (p=0.005), 16 hits vs 15.0 |
| pooled controls | 0.208, 3 hits vs 3.0 | **0.302**, 5 hits vs 2.0 | 0.236, 14 hits vs 15.0 |
| mid-IV controls | 0.498, 7 hits vs 3.0 | **0.618**, 6 hits vs 2.0 | 0.429, **24 hits vs 15.0** |

Read across the rows: the true-OHLC rebuild and the close-only proxy produce statistically
indistinguishable best associations (0.261 vs 0.220 pooled; 0.518 vs 0.520 mid-IV), and on
**both** control populations the discarded close-only proxy produces the *larger* number.
**The earlier choppiness null was not a proxy artefact.** It was a null.

### 3.4 Selection audit — the entry-decision trend results are on a different population

ADX(7) at the fill minute requires 15 bars since 09:15, so it is computable for **62 of 116**
pooled fires and **19 of 33** mid-IV fires. Those are not a random 53%:

| | fires WITH an ADX at entry | fires WITHOUT | Welch p |
|---|---:|---:|---:|
| mean entry minute | **674.5 (11:14)** | **560.0 (09:20)** | **< 0.0001** |
| minutes of session left | 254.5 | 369.0 | **< 0.0001** |
| hold-to-close return, % | −6.64 | −9.15 | 0.77 |

The entry-decision trend subsample fills on average **almost two hours later** than the fires
it excludes. Every entry-decision ADX/CHOP number in this report — including the largest
single |rho| in the mid-IV table, `dmi_call` vs P&L at rho = +0.518 on **N=19** — is measured
on a systematically later-filling population, not on Gate B. That result should not be quoted
as a Gate-B finding under any circumstances, and it is not treated as one below.

---

## 4. (B) Volume features

### 4.1 Construction and decision minutes

Six features, each computed on a **flow window** that ends at its stated decision minute:

| feature | definition | flow window |
|---|---|---|
| `vol_level` | log total volume, entry strike CALL | 09:15→entry, or entry→entry+W |
| `vol_rel` | window volume/minute ÷ **the same contract's own earlier** volume/minute | as above |
| `vol_trend` | OLS slope of per-minute log volume across the window | as above |
| `vol_conc` | Herfindahl of per-minute volume within the window (concentration in time) | as above |
| `vol_share` | entry-strike CALL volume ÷ **whole CALL chain** volume | as above |
| `chain_vol` | log total CALL+PUT chain volume (market-wide activity, strike-exogenous) | as above |

Decision minutes: `entry` = the gap-fill minute (features see only 09:15→fill; this can only
ever yield an **entry filter**). `persist:W` for W ∈ {15, 30, 45, 60} = entry + W (flow
measured on entry→entry+W; this can only ever yield a **stay-in / cut** rule on an open
position).

### 4.2 Results — best |rho| per feature per target

| feature | target | pooled fires | at | mid-IV fires | at | pooled controls |
|---|---|---:|---|---:|---|---:|
| `vol_level` | R² (trendiness) | +0.069 | +60m | +0.275 | +60m | +0.183 |
| `vol_level` | direction | −0.209 | +15m | −0.199 | +15m | +0.124 |
| `vol_level` | **real P&L** | −0.186 | +15m | −0.218 | +15m | +0.130 |
| `vol_rel` | R² | −0.088 | entry | +0.191 | entry | +0.071 |
| `vol_rel` | direction | +0.070 | +45m | +0.284 | entry | +0.141 |
| `vol_rel` | **real P&L** | +0.092 | +45m | +0.367 | entry | +0.145 |
| `vol_trend` | R² | +0.094 | +15m | +0.385 | entry | +0.216 |
| `vol_trend` | direction | +0.104 | +30m | +0.365 | entry | −0.189 |
| `vol_trend` | **real P&L** | +0.094 | +30m | **+0.436** | entry | −0.224 |
| `vol_conc` | R² | −0.151 | +45m | +0.195 | entry | −0.162 |
| `vol_conc` | direction | −0.121 | +30m | −0.325 | +45m | −0.054 |
| `vol_conc` | **real P&L** | −0.113 | +30m | −0.218 | +45m | −0.084 |
| `vol_share` | R² | −0.057 | +30m | −0.163 | +30m | +0.092 |
| `vol_share` | direction | −0.089 | +15m | −0.170 | +15m | −0.071 |
| `vol_share` | **real P&L** | −0.059 | +15m | −0.214 | +15m | +0.053 |
| `chain_vol` | R² | +0.055 | +60m | +0.359 | +45m | +0.169 |
| `chain_vol` | direction | −0.188 | +60m | −0.148 | +45m | +0.168 |
| `chain_vol` | **real P&L** | −0.196 | +60m | −0.207 | +60m | +0.154 |

The volume family contributes **120 cells** in each population. Raw p<0.05 hits: **5 of 120
on pooled fires against 6.0 expected by chance**; 4 of 120 on mid-IV against 6.0; 6 of 120 on
pooled controls against 6.0. **Fewer hits than chance in two of the three, and never more.**
Best |rho| in the family: 0.209 pooled, 0.436 mid-IV, 0.224 controls. Zero Benjamini–Hochberg
survivors anywhere.

### 4.3 What the volume family says

Nothing survives, but the shape of the failure is informative and is worth stating rather
than skipping:

* **Sign instability is total.** `vol_trend` vs P&L is +0.094 pooled, **+0.436** mid-IV, and
  **−0.224** on pooled controls. A feature that flips sign between the parent population and
  its own subgroup, and flips again on controls, is noise.
* **The one directionally consistent volume result is a *negative* one.** `vol_level` and
  `chain_vol` are negatively associated with both direction and P&L on both fire populations
  (−0.186 to −0.209 pooled, −0.199 to −0.218 mid-IV) and **positively** on controls (+0.124
  to +0.154). "Heavier volume in the early window, worse outcome" is the only pattern with
  the same sign in both fire samples and the opposite sign on controls. It is also
  **0.209 at best against a 0.258 detectable threshold** — below what N=116 can resolve — so
  it is reported as a shape, not a finding.
* **The mid-IV `vol_trend` = +0.436 headline dissolves on inspection.** It is at the entry
  decision on **N=26** (`vol_trend` needs 5 bars), p=0.026, and the rule it implies is priced
  in §8: taking only the top tercile gives N=9 trades, +13.7% mean, p=0.42, and the
  shuffled-feature placebo beats it in 7.1% of draws.

---

## 5. (C) Open-interest features

| feature | grade | definition | decision minute |
|---|---|---|---|
| `oi_open` | **exogenous** | entry-strike CALL open interest at **09:15** | any — uses pre-session data only |
| `oi_level` | pre-entry / endogenous | log entry-strike CALL OI at the decision minute | stated per row |
| `oi_chg_open` | pre-entry / endogenous | OI change since 09:15, % | stated per row |
| `oi_trend` | pre-entry / endogenous | OLS slope of OI across the flow window, %/min | stated per row |

| feature | target | pooled fires | at | mid-IV fires | at | pooled controls |
|---|---|---:|---|---:|---|---:|
| `oi_open` | R² | −0.134 | +15m | +0.082 | +45m | +0.033 |
| `oi_open` | direction | −0.172 | +30m | −0.279 | +45m | +0.056 |
| `oi_open` | **real P&L** | −0.162 | +30m | −0.274 | +45m | +0.037 |
| `oi_level` | R² | −0.106 | +30m | −0.108 | +30m | +0.092 |
| `oi_level` | direction | −0.193 | +15m | −0.341 | +45m | +0.056 |
| `oi_level` | **real P&L** | −0.160 | +60m | **−0.374** | +45m | +0.033 |
| `oi_chg_open` | R² | +0.089 | entry | −0.294 | entry | +0.197 |
| `oi_chg_open` | direction | +0.144 | +30m | −0.051 | +30m | +0.068 |
| `oi_chg_open` | **real P&L** | +0.157 | +30m | +0.088 | entry | +0.084 |
| `oi_trend` | R² | −0.131 | +45m | +0.224 | +15m | −0.220 |
| `oi_trend` | direction | −0.194 | entry | −0.355 | entry | −0.136 |
| `oi_trend` | **real P&L** | −0.201 | entry | −0.389 | entry | −0.147 |

**80 cells per population. Raw p<0.05: 2 of 80 pooled against 4.0 expected; 4 of 80 mid-IV
against 4.0; 2 of 80 controls against 4.0. Zero BH survivors.**

### 5.1 The nearest thing in the whole study to a coherent pattern — and why it is not a finding

The **OI-level** pair (`oi_open`, `oi_level`) is the only place where the sign is consistent
across pooled fires, mid-IV fires, *and* reverses on controls, on both the direction and the
P&L targets:

| | pooled fires | mid-IV fires | pooled controls |
|---|---:|---:|---:|
| `oi_open` vs P&L | −0.162 | −0.274 | **+0.037** |
| `oi_level` vs P&L | −0.160 | **−0.374** | **+0.033** |
| `oi_open` vs direction | −0.172 | −0.279 | **+0.056** |
| `oi_level` vs direction | −0.193 | −0.341 | **+0.056** |

Read at face value: *the more open interest already sitting at the strike you are about to
buy, the worse the trade does.* That is a plausible-sounding story — heavy pre-existing open
interest at a strike is a supply of writers, and a strike that dealers are short in size is a
strike that gets defended. **It is not established here, and it should not be repeated as if
it were.** Four reasons, in order of severity:

1. **It is below the resolution of the design.** The largest of these is 0.193 on pooled
   fires against a **0.258** smallest-detectable |rho| at 80% power. On mid-IV the largest is
   0.374 against a **0.471** threshold. Every one of them is inside the noise floor.
2. **`oi_level` is not exogenous.** Only `oi_open` is. And `oi_open` — the clean one — is the
   *weaker* of the pair in both fire populations, which is the wrong ordering if the mechanism
   were real and pre-existing.
3. **The fully exogenous subgrid is empty.** Restricting to the two `exogenous` features
   (`oi_open`, `pcr_oi_open`) gives **40 cells with 1 hit on pooled fires (2.0 expected) and
   0 hits on mid-IV fires (2.0 expected)**, while **mid-IV controls produce 7**. §6.4.
4. **Nothing survives the grid correction.** Best-of-grid permutation p = 0.76 pooled,
   0.50 mid-IV.

This is exactly the kind of pattern that gets promoted to a "mechanism" on a small sample and
then fails out of sample. It is written down here because it is the most interesting shape in
the data and someone should look at it on a larger population, **not** because it is evidence.

---

## 6. (D) Put-versus-call volume and open interest

Five features. `pcr_oi_open` and `pcr_oi` / `pcr_vol` are at the **matched entry strike**
(PUT at K over CALL at K, same absolute strike, both tracked by value); `pcr_oi_chain` and
`pcr_vol_chain` are whole-chain ratios and are strike-exogenous.

| feature | target | pooled fires | at | mid-IV fires | at | pooled controls |
|---|---|---:|---|---:|---|---:|
| `pcr_oi_open` *(exogenous)* | R² | +0.192 | +60m | −0.310 | entry | +0.077 |
| `pcr_oi_open` *(exogenous)* | direction | +0.106 | +60m | +0.210 | +60m | −0.105 |
| `pcr_oi_open` *(exogenous)* | **real P&L** | +0.158 | +60m | −0.061 | +15m | −0.132 |
| `pcr_oi` | R² | +0.119 | +45m | −0.248 | entry | −0.147 |
| `pcr_oi` | direction | +0.064 | +45m | +0.181 | +60m | −0.152 |
| `pcr_oi` | **real P&L** | +0.120 | +60m | +0.244 | +60m | −0.161 |
| `pcr_vol` | R² | +0.139 | +60m | −0.217 | entry | −0.236 |
| `pcr_vol` | direction | +0.181 | +15m | +0.213 | +60m | −0.183 |
| `pcr_vol` | **real P&L** | +0.167 | +15m | +0.091 | +60m | −0.203 |
| `pcr_oi_chain` | R² | +0.083 | +30m | −0.278 | +45m | +0.035 |
| `pcr_oi_chain` | direction | +0.049 | +15m | +0.364 | entry | +0.179 |
| `pcr_oi_chain` | **real P&L** | +0.107 | entry | **+0.475** | +45m | +0.165 |
| `pcr_vol_chain` | R² | +0.149 | entry | +0.161 | +45m | −0.170 |
| `pcr_vol_chain` | direction | +0.113 | +15m | −0.231 | +45m | +0.146 |
| `pcr_vol_chain` | **real P&L** | +0.075 | +15m | −0.389 | +45m | −0.136 |

**100 cells per population. Raw p<0.05: 2 of 100 pooled against 5.0 expected; 8 of 100
mid-IV against 5.0; 6 of 100 controls against 5.0. Zero BH survivors.**

### 6.1 The single strongest NON-price-path association in the study

> **`pcr_oi_chain` at entry+45 versus real strike-tracked CALL P&L to the close, mid-IV N=33:
> Spearman rho = +0.475, p = 0.0052.**
> **Its placebo, on the 36 priceable mid-IV control days: rho = −0.168, p = 0.33 — the
> opposite sign.**

The reading at face value would be: when the whole option chain carries proportionally more
put open interest at entry+45 — nominally a bearish or hedged tilt — the long CALL then does
*better* into the close. Every reason not to believe it:

* **The control days point the other way**, and with 36 observations against 33 they are not
  the less-powered comparison.
* **It does not replicate in the parent population.** The same cell on pooled N=113 is
  **+0.104, p = 0.27** — a quarter of the size, nowhere near significance. A real effect in
  the mid-IV subgroup should leave some trace in the population that contains it.
* **It does not survive the grid.** Mid-IV's best-of-grid |rho| of 0.520 sits exactly on the
  permutation placebo's median of 0.519 (empirical p = 0.495), and this cell is not even the
  maximum.
* **It is `endogenous` grade**: measured on the post-entry window, so it is contaminated by
  the spot path over that window (§7).
* **The rule it implies loses money.** §8.3.
* The related `pcr_oi_chain` vs directional-efficiency cell at entry+30 (rho = +0.478,
  p = 0.0049) has control rho = **−0.275** (N=38, p=0.094), again opposite-signed.

### 6.2 The matched-strike ratios specifically

The brief singled out put-versus-call at matched strikes as the closest available proxy for
positioning. On the matched entry strike, best |rho| against P&L is **+0.167 pooled**
(`pcr_vol`, +15m) and **+0.244 mid-IV** (`pcr_oi`, +60m), against detectable thresholds of
0.258 and 0.471. Both are inside the noise floor and neither reaches raw significance in
the population that matters. **Matched-strike positioning, as measurable here, carries
nothing.**

### 6.3 Sign coherence check

Across the five put/call features × three targets (best cell per pair), pooled fires and
mid-IV fires **agree in sign in 8 of 15 cells** — indistinguishable from the 7.5 expected
by coin flip. Pooled fires and pooled controls agree in **5 of 15**, i.e. they *disagree*
more often than they agree. There is no coherent put/call signal to be sign-stable
about.

### 6.4 The fully exogenous subgrid — the only clean predictive claim available

`oi_open` and `pcr_oi_open` are snapshots taken at 09:15, before any intraday path exists.
Nothing about how the session unfolded can have caused them, so an association here would be
the one genuinely causal-direction-safe result this study could produce.

| population | cells | raw p<0.05 | expected by chance | best cell | rho | p |
|---|---:|---:|---:|---|---:|---:|
| **pooled fires** | 40 | **1** | 2.0 | `pcr_oi_open` / +60m / R² | +0.192 | 0.047 |
| **mid-IV fires** | 40 | **0** | 2.0 | `pcr_oi_open` / entry / R² | −0.310 | 0.079 |
| pooled controls | 40 | 0 | 2.0 | `pcr_oi_open` / +15m / eff | −0.156 | 0.068 |
| mid-IV controls | 40 | **7** | 2.0 | `pcr_oi_open` / +15m / P&L | −0.345 | 0.042 |

**Zero and one hit against two expected, on the fires; seven on the mid-IV controls.** The
cleanest features in the study are the emptiest, and the control days out-hit the fires by
seven to one. If pre-session positioning carried anything about how these particular days
resolve, this is where it would be, and it is not there.

---

## 7. The identification threat, measured rather than caveated

The brief was right to name this as first-order, so it is measured directly instead of
disclaimed.

### 7.1 How endogenous is each feature?

Spearman rho of each feature against the **absolute spot move over its own measurement
window** — i.e. how much of the feature is just a restatement of "spot came here":

| feature | at +15m | at +30m | most endogenous cell |
|---|---:|---:|---:|
| `chop_spotproxy` | **−0.490** | −0.263 | −0.490 |
| `chop_call` | **−0.481** | — | −0.481 |
| `adx_call` | +0.288 | **+0.480** | +0.480 |
| `adx_spotproxy` | +0.376 | +0.431 | +0.431 |
| `pcr_vol_chain` | +0.316 | **+0.406** | +0.406 |
| `vol_trend` | — | — | −0.267 (+60m) |
| `vol_share` | −0.177 | −0.237 | −0.237 |
| `oi_trend` | +0.248 | +0.217 | +0.248 |
| `oi_open` | −0.216 | −0.193 | −0.216 |
| `pcr_oi` | −0.078 | −0.200 | −0.214 (+45m) |
| `vol_level` | +0.056 | +0.022 | +0.056 |

**The trend and chop indicators are roughly half spot-move by construction** (|rho| 0.43–0.49
against the absolute window move). That is not a defect of the indicators — it is what they
are for — but it means any association between them and a *subsequent* spot outcome is
contaminated through simple path continuity, and it is why the entire trend/chop family is
graded `endogenous` at every persist decision.

**The volume-level features are the least endogenous of the lot** (`vol_level` |rho| ≤ 0.06),
which is a genuinely useful finding: total volume at the entry strike is nearly orthogonal to
how far spot moved over the same window. It also predicts nothing.

`pcr_vol_chain` at +0.406 is the most endogenous of the non-price-path features, and it is one
of the two mid-IV headline cells (§6.1's sibling, rho = −0.389 vs P&L). That association
cannot be separated from the spot path and is labelled an association throughout.

### 7.2 Where endogeneity cannot be ruled out, stated plainly

* Everything at a `persist:W` decision using the entry→entry+W flow window: **cannot be ruled
  out**, quantified above.
* Everything at the `entry` decision using 09:15→fill: contaminated only by the pre-entry
  path, which *is* the gate's own definition, so these are legitimate entry filters.
* `oi_open`, `pcr_oi_open`: **clean.** They are 09:15 snapshots.
* The `entry`-decision trend features carry a *second*, worse problem — the availability
  selection of §3.4 — which is not endogeneity but is at least as disqualifying.

### 7.3 Secular time trend — checked, and it does not manufacture the result

Per-minute option volume grows 6.4× across the sample, so a level feature could correlate
with an outcome purely through calendar time. Spearman rho against calendar order, pooled
fires at the entry decision:

| feature | rho vs time | p |
|---|---:|---:|
| `pcr_oi_chain` | **+0.311** | 0.0007 |
| `pcr_vol_chain` | +0.233 | 0.012 |
| `vol_conc` | +0.208 | 0.025 |
| `oi_level` | +0.122 | 0.19 |
| `vol_level` | **−0.023** | 0.81 |
| `chain_vol` | **−0.005** | 0.96 |

Outcomes also drift mildly: `dir_rest` rho vs time = −0.178 (p = 0.056), `pnl_rest` = −0.146
(p = 0.12).

Two conclusions. **First**, `vol_level` and `chain_vol` are *not* time-contaminated despite
the 6.4× growth, because both are measured over windows of varying length within a session
and window length dominates the secular level. **Second**, `pcr_oi_chain` — the §6.1 headline
— *is* time-trended, but the confound works **against** the observed result: it rises with
time while outcomes fall, which would generate a *negative* spurious association, and the
observed one is +0.475. So time does not explain that cell. It is noise, not a time artefact,
and it is worth having established which.

---

## 8. (E) The decision rules the strongest associations imply, priced on real premiums

The three strongest P&L cells in each population were converted into mechanical rules and
priced on real strike-tracked traded premiums. **12 rule variants** (3 features × 2 tercile
directions × 2 populations). Terciles, not medians, so the rule takes the most extreme third.

* **Entry filter** (decision = fill minute): take the trade only when the feature is in the
  named tercile; compare against taking all fires.
* **Persist / cut** (decision = entry+W): cut the position at the decision minute when the
  feature is in the named tercile, otherwise hold to the close; compared **paired** against
  always-hold on the same days.

### 8.1 The grid, gross and net of costs

Cost model identical to `GATE_B_REAL_PREMIUM_VALIDATION.md` §8, applied at the population's
own **median traded entry premium of ₹118.45**, one lot of 50.

| pop | feature | decision | side | kind | N | mean | median | win% | p vs 0 | Δ vs base | p vs base | held (min) | **%/min** | net @0.35% | net @1.0% |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pooled | `dmi_call` | entry | high | filter | 21 | **+9.07%** | +10.83 | 57.1% | 0.354 | +15.71pp | 0.160 | 237 | +0.038 | **+7.35%** | +5.99% |
| pooled | `dmi_call` | entry | low | filter | 21 | −12.25% | −9.61 | 38.1% | 0.230 | −5.61pp | 0.620 | 297 | −0.041 | −13.87% | −15.09% |
| pooled | `adx_call` | +60m | high | cut | 108 | −2.57% | −9.24 | 41.7% | 0.514 | **+5.56pp** | **0.0147** | 236 | −0.011 | −4.24% | −5.52% |
| pooled | `adx_call` | +60m | low | cut | 108 | −7.51% | −13.31 | 34.3% | 0.069 | +0.61pp | 0.763 | 237 | −0.032 | −9.16% | −10.41% |
| pooled | `oi_trend` | entry | high | filter | 29 | −18.80% | −23.92 | 27.6% | 0.070 | −9.11pp | 0.416 | 365 | −0.052 | −20.39% | −21.57% |
| pooled | `oi_trend` | entry | low | filter | 29 | −3.88% | −2.36 | 44.8% | 0.419 | +5.81pp | 0.393 | 161 | −0.024 | −5.55% | −6.82% |
| mid-IV | `dmi_call` | entry | high | filter | **7** | **+26.10%** | +29.51 | 71.4% | 0.180 | +28.73pp | 0.177 | 256 | +0.102 | **+24.29%** | +22.82% |
| mid-IV | `dmi_call` | entry | low | filter | **7** | −21.07% | −16.88 | 42.9% | 0.171 | −18.45pp | 0.291 | 314 | −0.067 | −22.65% | −23.81% |
| mid-IV | `pcr_oi_chain` | +45m | high | cut | 33 | −8.90% | −13.97 | 42.4% | 0.243 | −2.82pp | 0.405 | 249 | −0.036 | −10.54% | −11.78% |
| mid-IV | `pcr_oi_chain` | +45m | low | cut | 33 | **+0.80%** | −10.87 | 39.4% | 0.902 | +6.87pp | 0.056 | 208 | +0.004 | −0.89% | −2.20% |
| mid-IV | `vol_trend` | entry | high | filter | **9** | +13.71% | +12.09 | 55.6% | 0.419 | +24.93pp | 0.199 | 294 | +0.047 | +11.96% | +10.58% |
| mid-IV | `vol_trend` | entry | low | filter | **9** | −33.77% | −45.81 | 22.2% | 0.068 | −22.56pp | 0.241 | 357 | −0.095 | −35.28% | −36.37% |

Baselines: pooled hold-to-close **−7.81% over 308 minutes (−0.0254%/min)**; mid-IV
**−6.08% over 314 minutes (−0.0194%/min)**.

### 8.2 Reading the grid

**Not one of the twelve rules is significantly positive.** Three have a positive mean; their
p-values against zero are 0.354, 0.180 and 0.419, and two of the three rest on **N = 7 and
N = 9 trades**. The largest, mid-IV `dmi_call` high tercile at +26.10%, is seven trades drawn
from the ADX-availability subsample whose mean fill is 11:14 (§3.4) — it is not a Gate-B
result at all.

**The per-minute column is doing the work the brief asked it to do.** The pooled
`dmi_call` high filter holds 237 minutes against 297 for its own low tercile — the "winning"
side of that filter is systematically the shorter hold, exactly the artefact
`GATE_B_EARLY_EXIT_SCAN.md` §6.5 warned about. The mid-IV `pcr_oi_chain` low-cut rule's
+0.80% is earned over 208 minutes versus the baseline's 314, i.e. it is +0.004%/min against
−0.019%/min, and once costs are charged it is **−0.89%** and negative again.

**Net of costs, ten of the twelve rules lose.** The two that survive at 0.35% half-spread —
+7.35% and +24.29% — are the two `dmi_call` entry filters on N=21 and N=7.

### 8.3 The one raw-significant rule, and its placebo

> Pooled, `adx_call` high tercile → cut at entry+60: **+5.56pp better than holding,
> p = 0.0147** (paired, N=108). This is the only rule in the study that beats its incumbent
> at even a raw 5%.
>
> **The identical rule on the 116 control days — days the gate did not fire — gives
> +4.73pp, p = 0.060.** Eighty-five percent of the effect, on days with no signal at all.

It also still **loses money**: its own mean is −2.57%, −4.24% net. It is the same trap
`GATE_B_EARLY_EXIT_SCAN.md` §4.2 documented — selecting on |t| without checking the sign
returns a rule that loses less, not a rule that wins.

The mid-IV analogue fails the same way and worse: `pcr_oi_chain` **low**-tercile cut gives
+6.87pp (p = 0.056) on the 33 fires, while on the 36 mid-IV control days it is the
**high** tercile that gives **+10.50pp (p = 0.030)** — a bigger effect, on the opposite
tercile, on days the gate did not fire. That is what noise looks like.

### 8.4 Best-of-rules placebo

1,000 draws. Each draw shuffles the feature across days — keeping every trade's realised
P&L, the entry-time distribution and the whole exit machinery exactly as observed, and
destroying only the feature-to-day mapping, i.e. only the thing the rule claims to exploit.
Best-of-family statistic recorded per draw.

| population | statistic | observed | placebo median | placebo 95th | **empirical p** |
|---|---|---:|---:|---:|---:|
| pooled | best rule mean return | +9.07% | +1.00% | +11.39% | **0.092** |
| pooled | best improvement over incumbent | +15.71pp | +8.34pp | +16.92pp | **0.069** |
| mid-IV | best rule mean return | +26.10% | +9.41% | +27.94% | **0.071** |
| mid-IV | best improvement over incumbent | +28.73pp | +14.62pp | +30.54pp | **0.076** |

**Nothing reaches 0.05 and every observed statistic sits inside its own placebo's 95th
percentile.** A randomly shuffled feature produces a best-of-family mean of +9.4% on mid-IV
and +1.0% on pooled purely from the tercile search; the real features produce +26.1% and
+9.1%, which is more but not more than the search itself explains.

---

## 9. Multiplicity and placebo discipline

### 9.1 Variant count

| family | count |
|---|---:|
| association cells, **per population** (20 features × 5 decisions × 4 targets) | **400** |
| populations reported separately (mid-IV, pooled) | 2 |
| control populations run for placebo | 2 |
| decision-rule variants priced on real premiums (§8) | **12** |
| supplementary diagnostics that are re-slices of the same 400, not new tests | §3.2, §3.3, §6.4, §7.1, §7.3 |

**Cumulative search on this population is far larger than 400.** These same days have already
been searched by `gate_b_pooled_grid.py` (32 exit variants), `gate_b_exit_grid_real.py` (39),
`gate_b_early_exit_scan.py` (45) and `gate_b_structure_search.py` (77 structure × horizon
cells). The corrections below apply to this study's 400 + 12; the project-level family-wise
burden is heavier still and no correction here accounts for it.

### 9.2 Corrections on the grid

| population | cells | raw p<0.05 | expected by chance | Bonferroni (α/400 = 1.25×10⁻⁴) | Benjamini–Hochberg | min p | max \|rho\| |
|---|---:|---:|---:|---:|---:|---:|---:|
| **pooled fires** | 400 | **15** | 20.0 | **0** | **0** | 0.0249 | 0.261 |
| **mid-IV fires** | 400 | 24 | 20.0 | **0** | **0** | 0.0019 | 0.520 |
| pooled controls | 400 | 22 | 20.0 | 0 | 0 | 0.0025 | 0.302 |

**Pooled fires produce fewer nominal hits than chance. Nothing survives any correction in any
population.** Mid-IV's 24 against 20 expected is a surplus of four, which for 400 correlated
tests on 33 days is not distinguishable from nothing.

### 9.3 Westfall–Young best-of-grid permutation placebo

5,000 draws, seed 20260823. One permutation of the **day index** per replicate, applied to
the target in every cell, so the severe dependence between cells — all 400 share the same
days, and the features are correlated with one another — is preserved rather than assumed
away. Both a max-|rho| and a **signed** statistic are reported, because a max-|rho| is
sign-blind and on this project a sign-blind selection has already once returned the most
reliably loss-making rule in a grid.

| population | statistic | observed | placebo median | placebo 95th | **empirical p** |
|---|---|---:|---:|---:|---:|
| **pooled fires** | best-of-grid \|rho\| | **0.261** | **0.286** | 0.368 | **0.7594** |
| **pooled fires** | best signed rho vs real P&L | +0.261 | +0.227 | +0.317 | **0.2458** |
| **mid-IV fires** | best-of-grid \|rho\| | **0.520** | **0.519** | 0.654 | **0.4950** |
| **mid-IV fires** | best signed rho vs real P&L | +0.518 | +0.415 | +0.567 | **0.1300** |

**On pooled fires the observed best is on the wrong side of the placebo median** — a randomly
relabelled day set finds a *stronger* best-of-grid association than the real one does, in 76%
of draws. On mid-IV the observed best lands on the placebo median to three decimals.

### 9.4 Control-day placebo — the headline placebo

The identical 400-cell grid on days that gapped down, were not expiry days, and whose gap
filled after 09:17, but on which **the overnight VIX did not rise**, so the gate stood aside:

| target | pooled fires (N≈116) | pooled controls (N≈142) | mid-IV fires (N=33) | mid-IV controls (N=39) | 80%-power \|rho\| |
|---|---:|---:|---:|---:|---|
| straight-line R² (trendiness) | 0.220 | **0.236** | 0.385 | 0.347 | 0.26 / 0.47 |
| directional efficiency | 0.234 | **0.248** | 0.520 | **0.568** | 0.26 / 0.47 |
| direction | 0.250 | 0.236 | 0.500 | **0.581** | 0.26 / 0.47 |
| **real-premium P&L** | 0.261 | **0.302** | 0.518 | **0.618** | 0.26 / 0.47 |

**Controls produce the larger best-|rho| in six of eight comparisons, including both
comparisons against real P&L.** If any of this were a property of the Gate-B
signal it would have to be larger on the fires than on the days the gate rejected. It is
smaller.

### 9.5 A joint test of the whole grid, and why it must be discarded

A max-statistic is blind to many small effects, so the whole p-value distribution was tested
against U(0,1):

| population | KS D | KS p | #p<0.05 | binomial p (excess) | mean \|rho\| | null approx |
|---|---:|---:|---:|---:|---:|---:|
| pooled fires | 0.0856 | **0.0054** | 15/400 | 0.90 | 0.082 | 0.074 |
| mid-IV fires | 0.0769 | **0.0167** | 24/400 | 0.21 | 0.160 | 0.141 |
| pooled controls | 0.0558 | 0.159 | 22/400 | 0.35 | 0.075 | 0.067 |
| **mid-IV controls** | **0.1098** | **0.0001** | **37/400** | **0.0003** | 0.162 | 0.129 |

**This test is invalid here and its rejections must not be read as signal.** The KS statistic
assumes independent p-values; these 400 share the same days and use correlated features, so
the null distribution is not U(0,1) and the test over-rejects. The direction confirms it —
the deviation peaks at p ≈ 0.32–0.51, in the middle of the distribution, not at the small-p
end, and pooled fires have *fewer* p<0.05 than expected while still "rejecting". And the
control group settles it: **the strongest rejection in the table is on mid-IV controls
(p = 0.0001, 37 of 400 hits, binomial p = 0.0003)**, days on which there is definitionally
nothing to find. It is reported in full because running a joint test and then quietly dropping
it when it is inconvenient would be worse than reporting why it fails.

---

## 10. Power — what these designs can and cannot resolve

### 10.1 Association tests

| population | N | smallest \|rho\| at 80% power, raw α=0.05 | …with Bonferroni over 400 tests |
|---|---:|---:|---:|
| **mid-IV fires** | 33 | **0.471** | **0.693** |
| **pooled fires** | 116 | **0.258** | **0.414** |
| pooled controls | 142 | 0.233 | 0.377 |

### 10.2 P&L

| population | N | mean | sd | 95% CI | smallest detectable mean |
|---|---:|---:|---:|---|---:|
| pooled | 116 | −7.80% | 45.8pp | **[−16.15%, +0.54%]** | **11.92pp** |
| mid-IV | 33 | −6.08% | 47.3pp | **[−22.22%, +10.07%]** | **23.08pp** |

### 10.3 What this means for the null

**What the design can detect.** On pooled fires, a rank association of |rho| ≥ 0.26
uncorrected or ≥ 0.41 corrected; a P&L overlay worth more than about 12pp per trade. On
mid-IV, |rho| ≥ 0.47 uncorrected or ≥ 0.69 corrected; 23pp of P&L.

**What it cannot.** Anything smaller. The largest association anywhere in 400 pooled cells is
0.261 — barely at the uncorrected threshold and far below the corrected one. On mid-IV the
largest is 0.520, above the raw threshold and well below the corrected 0.693.

**The honest boundary.** This is **not** a demonstration that volume and open interest are
uninformative about NIFTY intraday option outcomes in general. It is a demonstration that on
**these 33 and 116 days**, at **these five decision minutes**, against **these four targets**,
with **these twenty features**, nothing is detectable above about |rho| 0.26 pooled and 0.47
mid-IV. A weak-but-real effect of |rho| ≈ 0.15 would be entirely invisible here and is not
excluded.

Three things that *are* established and do not depend on power:

1. **Pooled fires produce fewer raw hits than chance** (15 vs 20 of 400). A design cannot be
   under-powered into producing *fewer* false positives than its own null rate.
2. **The control days out-perform the fires** on six of eight best-|rho| comparisons and on
   both against real P&L. This is a like-for-like comparison at *equal or better* N and
   needs no power argument at all.
3. **The fully exogenous subgrid is empty on the fires and full on the controls** (1 and 0
   hits vs 7, against 2.0 expected).

---

## 11. What I think is wrong, in both directions — including in my own work

1. **The brief's premise was very slightly overstated and I have corrected it in §1.** `high`
   and `low` *have* been used once before in this project, in `gate_b_exit_grid_real.py`, as
   an upper bound on the bid-ask spread; `volume` has been used as a dedup tie-breaker and as
   a printed liquidity diagnostic. Neither has ever been a signal, so the substance of the
   brief holds, but "never used by anything" is not literally true and I would rather say so
   than let a small inaccuracy sit in the record.

2. **The most important limitation of this study is one the brief anticipated, and my answer
   to it is partial.** True intraminute high/low for **NIFTY spot** does not exist in this
   archive — verified, the spot column is one snapshot per minute, identical across all 42
   files at every minute tested. I rebuilt ADX and Choppiness on the **option's** true OHLC
   instead, which is the traded instrument and is a monotone transform of spot, and both
   indicators are scale-invariant so the transform largely cancels. That is a real
   improvement over a close-only proxy and it is **not** the same thing as a spot rebuild.
   The option's bar range also contains implied-volatility movement and a minute of decay.
   Anyone wanting a definitive answer on spot choppiness needs a NIFTY index tape with
   intraminute OHLC, which is not here.

3. **My entry-decision trend results are on a different population than Gate B, and I nearly
   reported them as if they were not.** ADX(7) needs 15 bars, so it exists for only 53% of
   fires, and those fires fill on average at **11:14 against 09:20** for the excluded ones,
   p < 0.0001. The largest single |rho| in the mid-IV table — `dmi_call` vs P&L at +0.518 —
   is on **N=19** of a subsample selected on late filling. It is in §3.4 and §8 with that
   warning attached, and it should never be quoted without it. The general lesson for this
   project: **any indicator with a minimum-bar requirement silently selects on entry time on
   this population**, because the entry-clock distribution is heavily right-skewed (median
   09:32, mean 10:30).

4. **I ran a joint KS test that turned out to be invalid, and I have kept it in.** It rejects
   uniformity on both fire populations (p = 0.005, 0.017) and it would be easy to present that
   as diffuse weak signal. It is not: the 400 p-values are severely dependent, the deviation
   peaks in the middle of the distribution rather than at small p, pooled fires have fewer
   than the expected number of p<0.05 while still "rejecting", and **the strongest rejection
   of all is on mid-IV control days** where there is definitionally nothing. §9.5. I am
   reporting a test I could have quietly dropped because dropping it would have been the
   dishonest move.

5. **The `oi_level` / `oi_open` pattern in §5.1 is the one thing here I think is worth
   someone's time, and I have deliberately not promoted it.** It is the only feature pair
   whose sign is consistent across pooled fires *and* mid-IV fires *and* reverses on controls,
   on both direction and P&L, with a readable mechanism (heavy pre-existing open interest at a
   strike = writers defending it). Every one of those correlations is **below the design's
   resolution** (0.193 max against a 0.258 threshold), the exogenous member of the pair is the
   *weaker* one, and the exogenous subgrid is empty. Writing it down as a lead for a larger
   sample is right; writing it up as a mechanism would be exactly the error this project has
   already made once with the "volatility crush".

6. **The endogeneity grading is a judgement call and reasonable people would draw the line
   differently.** I graded the `entry`-decision features as legitimate entry filters on the
   argument that they are contaminated only by the pre-entry path, which is the gate's own
   definition. Someone could argue that even that is circular, because the gate conditions on
   the gap filling and a strike that has just been reached is definitionally a strike spot
   came to. I think my line is defensible, but the §7.1 numbers are there so anyone can move
   it and re-read the tables.

7. **A caution about the two positive rules in §8.1, aimed at anyone skimming.** `dmi_call`
   high tercile shows +9.07% pooled and +26.10% mid-IV, and both survive costs. They are
   **N=21 and N=7**, on the late-filling subsample, at p = 0.35 and p = 0.18, and the
   best-of-rules placebo beats them in 9.2% and 7.1% of draws with a *shuffled* feature. Two
   digits of mean return on seven trades is not evidence; it is what a tercile search on seven
   trades returns.

8. **What I have not established and will not claim.** This does not show that flow data is
   uninformative about NIFTY options. It shows that on this population, at this size, with
   these constructions, nothing is detectable. A |rho| ≈ 0.15 effect would be invisible here.
   Separately, these remain one-minute bar closes and not executable fills; the tercile rules
   in §8 concentrate into 7–33 trades, so their cost sensitivity is worse than the baseline's,
   not better.

9. **A negative previous pass is not evidence for a negative new one, and this study was
   worth running.** The prior was poor and the brief said so. But the failure mode this study
   was designed to rule out — "everything failed because we only ever looked at the price
   path" — is now ruled out with data rather than argued about. The columns were there, they
   have been used, and they are empty. That is a different and more final statement than "we
   never checked".

---

## 12. What could NOT be tested — no substitutes were fabricated

Stated explicitly, as the brief required, rather than proxied:

| wanted | status | why not proxied |
|---|---|---|
| **NIFTY futures volume and open interest** | **not available** — no futures tape exists locally | Option-chain volume is not a futures proxy; the participant mix differs |
| **Market breadth / advance–decline** | **not available anywhere in the archive** | Nothing in an option chain approximates breadth |
| **Option expiries beyond the nearest weekly** | **not available** — WEEK1 only | Term-structure and calendar-flow features are unbuildable |
| **True intraminute NIFTY spot high/low** | **does not exist** — verified, one snapshot per minute, identical across all files | Rebuilt on the traded option's own OHLC instead and labelled as such (§3.1) |
| **Bid–ask spread / order book** | not available — one-minute OHLC only | Bounded, not measured, in `GATE_B_REAL_PREMIUM_VALIDATION.md` §8 |
| **Trade-direction / signed order flow** | not available — `volume` is unsigned | Put/call ratios are the closest available proxy and are reported as such (§6) |
| **Strikes beyond ATM±10** | not staged in the archive | Chain-wide aggregates in §4 and §6 are ATM±10 aggregates, not the true full chain |

The last row is a real limitation on the "chain-wide" features: `chain_vol`, `pcr_oi_chain`
and `pcr_vol_chain` are computed over the 21 staged relative strikes, which is a wide but not
complete chain. They are labelled chain-wide throughout and that is what they mean here.

---

## 13. Reproducibility

New artifacts only. No existing script, specification, or report was modified. No git commit
or push was performed. No broker, credential, network, or order path was used. No subagents
were spawned.

| File | Contents |
|---|---|
| `gate_b_flow_common.py` | Volume / OI / true-OHLC data layer; builds the 4.16M-bar CALL+PUT cache with the §2.2 audit |
| `gate_b_flow_features.py` | The 20 features, 4 targets, 5 decision points, and the endogeneity grading |
| `gate_b_volume_oi_study.py` | The 400-cell grid, multiplicity, Westfall–Young placebo, rules, power |
| `gate_b_flow_supplement.py` | §3.2–3.3, §6.4, §7.1 diagnostics |
| `GATE_B_VOLUME_OI_STUDY.md` | This report |
| `gate_b_flow_quotes.pkl` | The deduplicated minute-bar cache (324 MB) |
| `gate_b_flow_quotes_audit.json` | §2.2 data-quality audit |
| `gate_b_flow_panel.csv` | The feature/target panel, 1,239 rows |
| `gate_b_flow_grid_{pooled_fires,midIV_fires,pooled_controls,midIV_controls}.csv` | The four 400-cell grids |
| `gate_b_flow_rules.csv`, `gate_b_flow_rules_controls.csv` | §8 rules on fires and on controls |
| `gate_b_flow_endogeneity.csv` | §7.1 |
| `gate_b_flow_family_compare.csv` | §3.3 |
| `gate_b_volume_oi_study_results.json`, `gate_b_flow_supplement_results.json` | Machine-readable results |

Reused unchanged: `gate_b_full_paths.py` (264-path full-hydration cache), `gate_b_common.py`
(path construction, exit machinery, reproduction guard).

```text
.ml_venv/bin/python gate_b_flow_common.py        # builds the cache, prints the audit
.ml_venv/bin/python gate_b_flow_features.py      # builds the panel
.ml_venv/bin/python gate_b_volume_oi_study.py    # the study
.ml_venv/bin/python gate_b_flow_supplement.py    # the supplementary diagnostics
```

The `gate_b_common.py` reproduction guard runs upstream of the path cache and passes: the 33
published Gate-B fires, their entry clocks, strikes and Black-Scholes entry premiums, all
three published trailing-stop means and every published fixed-clock figure are recovered
before any new result is computed.

**Independent correctness checks performed on this run:**

* The panel's hold-to-close on real strike-tracked traded premiums reproduces the published
  Gate-B figure: **mid-IV N=33 mean −6.078% vs published −6.08%**.
* Pooled N=116 gives −7.805% against the published −7.61% on N=120; the difference is exactly
  the four fires dropped for having under 30 minutes of session remaining.
* All 2,772 archive files were read with zero missing; OHLC is internally consistent on
  **100.0000%** of 4.16M bars.
* `volume` was verified per-bar and not cumulative (49.2% non-negative first differences).
* The rolling relative-strike label was verified to roll intraday and is nowhere used.
* Spot was verified to be a single snapshot per minute, identical across all files (cross-file
  range 0.0 at every one of 376 minutes tested).
