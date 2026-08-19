# Shaurya — Module Task Ledger

**This file is the single source of truth for the Shaurya module.**
Status lives here and nowhere else. No parallel task lists, no status in chat, no status in
commit messages. If a task is not in this file it is not being worked on.

**Created:** 2026-08-17
**Owner:** Aryan Ayyar
**Location:** `Google Drive/My Drive/Dhandho/shaurya/`

**Next substantive step (updated 2026-08-19 after D32):** begin SIG-21 calibration on the next
full market session. The anomaly/treatment source is **depth200 only**; depth20 is recorded solely
for the later midpoint response and near-book controls and can never enter anomaly construction.
Collect five full post-registration calibration sessions, then create and push the
outcome-independent 384-cell numeric power artifact. The axes and 384-cell family are already
registered and may not be selected from tomorrow's outcomes; calibration determines support and
power, not a more attractive grid. No outcome execution is allowed until the power artifact passes
its gates; the first evaluation then requires 20 later full sessions. `PP` / `SIG-04` remains open
behind `SIG-21`.

---

## 0. How to use this file

- Every task has a **stable ID**. IDs are never reused or renumbered, even if a task is dropped.
- A task's **Status** is one of: `Not started`, `In progress`, `Blocked`, `Implemented`,
  `Tested`, `Dry-run verified`, `Live verified`, `Dropped`.
- `Implemented` means code exists. It does **not** mean tested. These are different rungs and
  are never collapsed into "done".
- **Blocked** tasks must name what blocks them.
- A task is only removed by being marked `Dropped` with a reason. Nothing silently disappears.
- New capability arrives as a new task ID, not by widening an existing one.

---

## 1. Decisions log

Decisions taken 2026-08-17 by voice. These are binding.

| # | Decision | Resolution |
|---|---|---|
| D1 | Module name | **Shaurya.** The name now belongs to the module, not to a strategy. Python package `shaurya`, C++ namespace `shaurya::`. |
| D2 | Fate of the old "Shaurya" name | The existing options market-making strategy is renamed **Market Making** and stays as it is. |
| D3 | First construction step | Do not build yet. First enumerate what components exist and how each would be built from existing code. Then agree the component list. Then construct. |
| D4 | Language for the live engine | **C++**, for speed. Not C. Resolves O2. |
| D5 | Relationship to strategies | **The module is plug-and-play.** It is a dependency that any strategy can plug into — not a fork, not a copy, not a template. Market Making gets refactored to consume it. Resolves O3, and by implication O1. |
| D6 | Name collision | Resolved by renaming the two conflicting things. **Both renames executed 2026-08-17** — see §1.1. Resolves O6. |
| D7 | Broker scope | **Market data:** both **Dhan** (primary — options and order-book data is very rich, consumed live via WebSocket) and **Kotak** must be supported as data-receive sources; the module receives from both. **Order execution:** **Kotak only** — zero brokerage on Kotak's options API makes it the sole order-placement route; Dhan and Kite order placement are not authorised. Order placement must run through a dedicated, latency-sensitive C++ path (reaffirms D4/NAT-03). Resolves O4. **Amended 2026-08-18 by D18 — Kotak dropped as a data-receive source; data ingestion is Dhan-only. Kotak-only order execution is unchanged.** |
| D8 | Design philosophy | **Data leads, strategy follows.** The module must let the data reveal an opportunity before a strategy/model is chosen to exploit it — never propose a model first and tune parameters against data until it looks profitable (the classic overfitting trap). Exploratory/diagnostic tooling is **first-class**, not a lesser citizen of `ANL`/`DAT`/`SUR`, and sits upstream of any strategy-specific fitting. Applies across the whole component list, most directly `DAT`, `ANL`, `SUR`, `BKT`. See README §6, rule 7. |
| D9 | GitHub repo name for the module | Delegated to OpenClaw ("take the best decision you want"). **`ayyararyan/Shaurya`** — reclaims the name D1 already assigned to the module. This breaks the redirect from the old `Shaurya` URL to `Market-Making` (set up in the 2026-08-17 rename), but the repo is private with no external dependents, so consistency with D1 outweighs preserving a bookmark only Aryan uses. |
| D10 | Signal research & validation | **A new component `SIG` is added — agreed by voice 2026-08-17.** Three sub-decisions taken together: (a) **new component, not an extension of `ANL`** — `ANL` is post-trade reporting, `SIG` is pre-strategy discovery, and D8 requires exploratory tooling to be first-class rather than a lesser citizen of `ANL`; (b) **the full validation harness is built now, not deferred** — same override pattern as `VOL`, on the same reasoning: this is general-purpose measurement infrastructure, not a strategy-specific model bet ("validation infrastructure needs to be made fully, there is no doubt about it"); (c) **slotted in now**, ahead of the remaining `RSK → BKT → ANL → NAT → MIG` walk, so that `BKT` and `ANL` are debated with `SIG` already on the table. `SIG` is the machinery D8 was missing: until now "data leads, strategy follows" was a stated philosophy whose only producer of `CON-09` records was `VOL-05`. |
| D11 | Coverage, selection, and interpretability | Agreed by voice 2026-08-17, four parts. (a) **Coverage is defined by taxonomy + measured residual gap**, not by enumerating features — `SIG-01` and `SIG-18` proceed. (b) **Selection pipeline agreed:** cluster → stability selection inside purged/embargoed walk-forward → Model Confidence Set → economic gate, with knockoffs as a confirmation layer — `SIG-10`, `SIG-13`, `SIG-15` proceed. (c) **Black-box models are a yardstick only:** they measure how much signal exists (`SIG-18`); anything promoted to a tradeable strategy must be sparse and interpretable. (d) **Two constraints raised by Aryan that the coverage argument must survive:** no tick-level historical data exists anywhere, and disk space is limited — his position is that at most *features* can be stored, which would make the feature list a forward-only, irreversible commitment decided at capture time. **Resolved the same evening by D12 — the tape is recorded; only its sizing remains open at `DAT-09`.** |
| D12 | Record the raw tape | **Decided by voice 2026-08-17: the raw tape gets recorded.** "I agree on your part of the data — we can record it. I will think about what to do about the storage space, but we should record it." This resolves the conflict flagged in D11(d): a features-only regime would have deleted `SIG-18`, the only test capable of demonstrating coverage, so the coverage argument now stands. **Storage sizing and retention tiering remain Aryan's to settle — `DAT-09` narrows from "tape or features" to "which universe, at which depth tier, kept for how long".** Two supporting facts confirmed the same day: the **Dhan Data API subscription is active** (clearing `DAT-02`'s hard prerequisite), and Dhan offers **5, 20 and 200** depth levels rather than 5/20 only — verified in source, see §7. |
| D13 | Risk architecture | **Agreed by voice 2026-08-17, three parts.** (a) **The binding pre-trade risk gate is a single C++ choke point on the order path** (`RSK-03`); Python holds the same limit definitions from `CON-04` for research and backtest but is explicitly non-authoritative, with a parity suite proving agreement (`RSK-07`). Reason: a check that lives anywhere but the choke point is bypassed by the first code path that forgets to call it. (b) **Limits aggregate at account level across strategies** (`RSK-06`), not per strategy — margin, daily loss and portfolio Greeks are properties of the account, and two strategies each within limits can breach jointly. Accepted tension with D5: this is the one place the module holds cross-strategy state; it must key on account and position, never on strategy identity. (c) **Margin is two distinct objects** — broker-reported (`RSK-04`, `CON-06` **observed**, authoritative for live gating, never overridden) and modelled SPAN-style (`RSK-08`, **estimated**/**scenario**, for ex-ante sizing, margin-constrained backtesting and funding-constraint counterfactuals), the model validated against the observed number rather than assumed correct. **Kill switch split out as `RSK-05`:** trip conditions include data-quality and connectivity events, not only P&L; response is tiered with stop-quoting and cancel-resting automatic but flatten requiring human authorisation; re-arm is manual only. |
| D14 | Backtesting architecture | **Agreed by voice 2026-08-17, three parts.** (a) **The `BKT-03` → `EXE-09` forward reference is confirmed** — backtest execution realism consumes the queue-reactive fill model rather than reimplementing it. `EXE-10`, a labelled queue-ahead estimator, is a prerequisite and its uncertainty propagates into every simulated fill. **Amended by `D23`: own queue-ahead is partially identified with measurable bounds; only individual anonymous-order rank and cancellation position remain unidentified.** (b) **`NAT-07`'s C++ deterministic replay is the authoritative backtester**; the Python event loop exists for research iteration speed and is non-authoritative, with a parity suite (`BKT-05`) proving they agree — sharing a tape *format* is not sharing code. Anything promoted past exploratory must be reproduced in the C++ replay. (c) **Decision latency is injected from measurement, never assumed** (`BKT-06`), applying `CON-07`'s causality rule to replay; **own-order market impact is declared rather than modelled** (`BKT-07`) — Aryan's expected order sizes are small enough that zero own-impact is a reasonable assumption, so every result carries an explicit flag plus a size threshold above which it is labelled unreliable. |
| D15 | Analytics boundary and the live-loop location — **closes D3** | **Agreed by voice 2026-08-17, and with it the component walk is complete.** (a) **Markout and P&L attribution live in `ANL-01`, built once and consumed twice** — `SIG-08` takes markout-conditional-on-fill from `ANL` for adverse-selection measurement rather than reimplementing it, the same pattern as `EXE-09`. `ANL-01`'s P&L must be **decomposed** — delta, gamma, vega, theta, spread capture, adverse selection, fees — never reported gross. (b) **`NAT-03`, the live-loop wiring, happens in the module only, never in Market Making first** — building the live path twice creates a second order route that `MIG-01` then has to retire, the opposite of D5. **Accepted consequence, stated at the time and chosen deliberately:** live order placement now sits behind `INF` → `CON` → `NAT-01/02` → `NAT-03`, so the 2026-08-16 intention of trading live by 09:15 Monday is superseded. Reusability was chosen over the near date. **All twelve original components plus `SIG` are now agreed, so D3 is satisfied and construction may begin.** |
| D16 | Historical tape source for tick-level `VOL` estimators — audit correction | **Confirmed 2026-08-18 by Aryan, resolving a contradiction found in that day's decision-completeness audit.** `DAT-03` genuinely cannot provide tick-level data (bars/coarser only, by its own definition) — so the historical tape `VOL-02`'s kernel/bipower estimators need has to be **built by accumulating `DAT-02`'s live stream, recorded via `DAT-05`**, not sourced from `DAT-03`. `VOL-02`'s task note previously claimed the opposite; corrected below. Testing is gated on enough live tape having accumulated, not on a fixed prerequisite task completing. |
| D17 | Kite — fully dead, including instrument identity | **Confirmed 2026-08-18 by Aryan.** Kite carries no scope anywhere in the module. `CON-05` previously still listed a Kite `instrument_token` mapping as outstanding work — a leftover from before `D7`/`EXE-08` dropped Kite for execution, never scrubbed from `CON-05`. Removed; `CON-05` now scopes to Dhan and Kotak only. |
| D18 | Kotak — data feed dropped, order-placement only | **Decided 2026-08-18 by Aryan, amending `D7`.** The module does not receive Kotak market data. Kotak's role is **order placement only** (place/cancel/modify/status/fills/margin) — never a data-receive source. `DAT-08` (Kotak market-data C++ path) is **dropped** as a direct consequence. This also resolves the audit gap flagged 2026-08-18 about missing Kotak storage sizing: since Kotak was never a data source in the corrected scope, no Kotak-side capture/storage sizing is needed, and the Dhan-only figures already in §7/§7.1 and `DAT-09` were correct by construction, not by oversight. |
| D19 | Live surface dashboard — watching only, closes the queued debate | **Decided 2026-08-18 by Aryan (Telegram, 16:29 IST), resolving the voice thought queued earlier the same day in `NEXT_PROMPT.md`.** Asked directly whether "live" meant a dashboard on whatever cadence the surface fit naturally produces, or a hard latency requirement on the fit itself feeding quoting — Aryan: **"It's only about watching, no worries."** This is squarely `ANL-03` scope (dashboard/read-only server, already harvesting Market Making's `monday_v1/surface_dashboard.py` and `surface_server.py`), refreshed on whatever cadence `SUR-01`'s eSSVI fit and `SUR-07`'s smoothing already produce (~3s raw, smoothed for quoting) — nothing new to build in `SUR`. `SUR.md`'s line that Python remains authoritative for research surface fitting, with any live-order-path implementation separately designated, stands unchanged. **No new `SUR-0X` or `ANL-0X` task created** — `ANL-03` already covers this; its dependency `CON-03` is satisfied (tested 2026-08-18). |
| D20 | SIG's measurement design is empirical, not a spec constant | **Decided 2026-08-19 by Aryan (Telegram, ~00:14 IST), opening the queued SIG discussion.** Asked which sampling clock (event / calendar / volume time), which pooling coordinate (instrument identity vs a stationary delta-moneyness x tenor coordinate), and which prediction horizons `SIG` should be specified against. Aryan's answer to all three: **we do not know, and only the data can tell us — and what it says today may differ from tomorrow.** This is `D8` applied to `SIG`'s own measurement design rather than only to strategy choice. **Nothing is foreclosed by current capture:** `DAT` records the raw event-time tape (`D12`), the maximal-information choice, so clock, pooling and horizon remain fully recoverable decisions at analysis time. **Spec consequence:** each of the three becomes an explicit **swept axis in `SIG-19`'s trial log** and must be counted in `SIG-12`'s multiple-testing grid, never silently fixed. **Accepted cost, stated at the time:** clock x pooling x horizon x feature set inflates the search grid quickly, and Romano-Wolf plus deflated Sharpe will correctly annihilate findings over an unbounded sweep — so the plausible space must be narrowed from theory and evidence *before* the sweep, not by peeking at results. That narrowing is the job of the literature review Aryan commissioned in the same message (see `NEXT_PROMPT.md`); **no further `SIG` design decision is taken until that report lands.** |
| D21 | Shaurya trades as a **maker**, never a taker | **Decided 2026-08-19 by Aryan (Telegram, ~00:54 IST).** Asked whether `SIG`'s primary estimand is taker-side directional prediction or maker-side adverse selection. Answer: **maker, definitively — we do not cross the spread.** His reasoning: at these horizons the activity is making, not taking. **This inverts the target of nearly every candidate story in the SIG research report, which was written for a directional taker.** Consequences: (a) `SIG-08`'s primary target families become fill probability (censored hazard / `EXE-09` intensity) and markout-conditional-on-fill (adverse selection, from `ANL-01`), with directional forecast regression demoted to an input rather than the objective; (b) `SIG-17`'s economic gate is restated — a maker does not need edge exceeding half-spread, it needs expected spread capture exceeding adverse selection plus fees plus hedging cost, which is a different inequality, not a weaker one; (c) `EXE-10`'s bounded queue-ahead estimator becomes load-bearing rather than incidental because maker fill probability depends on queue-ahead. **Amended by `D23`: own queue-ahead is partially identified with reported bounds, while individual anonymous-order rank remains unidentified.** (d) the binding latency is **cancel latency**, not decision latency — the maker's characteristic risk is being picked off on a stale quote. **Standing risk recorded once, not to be re-litigated but not to be forgotten:** quoting from a retail broker's public feed against a market where NSE's April 2023 mode data attribute 50.22% of equity-derivatives turnover to co-location is structurally adverse; what maker edge survives for a non-co-located participant is an open empirical question the maker research report must address directly. |
| D24 | **Trade-direction classification runs on the capture path**, versioned, alongside raw retention | **Decided 2026-08-19 by Aryan (Telegram, ~01:09 IST), as a direct consequence of `D23`.** If queue-ahead bounds, cancellation decomposition and queue-conditional intensities are to be recovered, the buy/sell classification of trades has to happen **as the stream arrives**, not only as an offline research step — his words: if it is not done at the feed level it becomes very hard to decide later. **Accepted, and strengthened by a reason he did not state:** the capture-time sign is the **causally honest** label under `CON-07`, because it uses exactly the quote state the live path actually held. A sign computed later from the assembled tape can silently align a trade with a better-matched quote than the live decision ever had, which is lookahead wearing a reasonable disguise. **Binding qualification: signing at capture is *in addition to* raw retention, never instead of it.** The tape keeps the raw inputs — last traded price, last traded quantity, cumulative-volume increment, the prevailing bid/ask used, and every relevant receive timestamp — plus the inferred side plus a **classifier version stamp**. Reason: Ellis, Michaely and O'Hara document meaningful classification error, and the choice among the quote rule, the tick rule, Lee-Ready and its successors is itself one of `D20`'s swept axes. Storing only the sign would make the classifier an irreversible capture-time commitment — precisely the failure `D12` refused for the tape itself. **Two measurement facts that must be encoded honestly rather than smoothed over:** (i) **"The quote prevailing before the trade" needs a precise, versioned definition**, because trades arrive on the Quote/Full channel while depth arrives on the separate 20- and 200-level channels with independent packet clocks. The alignment rule is written down, tested, and its cross-channel error **measured from tape**, not assumed. (ii) **Dhan reports cumulative volume plus only the *last* traded price and quantity.** When the volume increment exceeds the last traded quantity, several prints coalesced into one packet and the inferred side applies **only to the last observed print**, not to the whole increment. The tape row must carry that flag so downstream signed-flow measures can either exclude or explicitly model coalesced intervals. **Consequences:** new task `DAT-14`; `CON-01` extended with the trade-classification fields; `SIG-03`'s signed-flow features and `SIG-14`'s Hasbrouck decomposition consume the capture-time sign with its version stamp rather than recomputing an unversioned one; `SIG-20`'s bounded-state forward-pass requirement is satisfied by construction for this feature. |
| D23 | Queue priority is **partially identified with measurable bounds**, not unidentified | **Decided 2026-08-19 by Aryan (Telegram, ~01:01 IST), correcting an over-claim in `SIG-07` and in the SIG research report.** His position: the absence of a Level-3 feed does not make queue priority uncomputable. Dhan already gives depth per level, **order counts per level**, and trades (last price, last quantity, cumulative volume); NSE index F&O matches on **price-time priority (FIFO)**, so a matching-algorithm-aware reconstruction recovers much of the queue structure including arrival and cancellation intensities — not identical to Level-3 queue geometry, but close. Do not flag this as uncomputable. **Accepted, with the object distinction made precise (working contract §7.2 — do not conflate related objects):** (a) **Own queue-ahead — the quantity a maker actually needs — is bounded, not unidentified.** At placement it equals the displayed quantity at that price. Trades at that price decrement it exactly from the front and are observable. Cancellations at the level are observable in aggregate (level delta net of additions and trades) but their *position* relative to ours is not, which yields a hard upper and lower bound, plus a point estimate under an explicit cancellation-position model. (b) **Arrival, cancellation and trade intensities conditional on queue size — the actual inputs to the queue-reactive fill model behind `EXE-09` — are estimable from level-by-level deltas.** The Huang-Lehalle-Rosenbaum framework was built for aggregated Level-2 data and never required order IDs. (c) Order counts per level give average order size and tighten the add/cancel decomposition. **What remains genuinely unidentified, unchanged:** the position of a cancellation within the queue; individual order identity and per-order lifetime; and hidden/iceberg quantity, which corrupts queue-ahead directly and cannot be seen at all. **The binding practical limit is packet coalescing, and it is measurable rather than assumed:** at roughly eight packets per second several events net into one observed delta, leaving the decomposition under-determined within an interval. **Bound width is therefore an empirical quantity `EXE-10` must measure and report, not a constant to be asserted.** **Consequences:** `SIG-07` is narrowed — it over-claimed by treating "true queue position" as a single unidentified object, when own-queue-ahead and anonymous-order-rank are different objects with different identification status. `EXE-10` is upgraded from a proxy that is grudgingly accepted to a **bounded estimator whose bounds are measured and propagated**, and its `CON-06` label becomes **estimated, with reported bounds**, rather than an unqualified proxy. Direct precedent: the IEX queue-priority work, where an L2 opportunity hazard was identifiable even though true FIFO rank was not. **Premise amended 2026-08-19 by `DAT-16` — the packet-rate figure in this decision is wrong and the correction is material.** The 20-level depth channel is a **fixed 500 ms snapshot feed at 2.00 bursts/second**, not an ~8 events/second stream; ~8.3 tape rows/second is an encoding artifact of ~4.17 rows per snapshot. The netting window is therefore **500 ms, not ~125 ms**, and `EXE-10`'s measured bound width is correspondingly wider. The bounded-not-unidentified structure of this decision is unaffected; only the width is. Evidence: `docs/live-evidence/DAT-16-2026-08-19.md`. |
| D22 | The claim ledger is a **pre-registered hypothesis set** | **Decided 2026-08-19 by Aryan (Telegram, ~00:54 IST).** The SIG research report's candidate stories are decomposed to **claim level, each with a stable ID**, not left as story-level rows — a single story such as multi-level OFI contains several separately-testable claims with distinct mechanisms, citations, capture requirements and falsifications. Each claim records: the mechanism (why it would move prices, not merely that it correlates), the supporting citations (resolved, not asserted), how it is captured from our own feed, its confirming test, its falsifying test, and its identification status under `CON-06`. **The ledger is the pre-registered hypothesis set that `SIG-19`'s trial log is checked against:** anything tested must appear in the ledger first, and any addition is recorded before results are inspected. This is what keeps `D20`'s swept axes a declared search space rather than a fishing expedition. **Aryan's qualification, binding:** literature seeds the claims but does not settle them — the ledger is held open to what the data actually shows, including mechanisms the literature does not anticipate. |
| D25 | **`EXE` enters the build order, and a far-from-touch Kotak latency probe is authorised in principle** | **Decided 2026-08-19 by Aryan (Telegram, ~10:5x IST), on OpenClaw's finding that the maker report's own Priority-0 gates are unreachable from the current build order.** `MK-01`–`MK-04` are declared gates — "no control-model optimisation is justified until they pass" — yet all four require a live order path through Kotak (submit/ack/cancel latency, fill-calibrated queue bounds, P(fill), broker-reconciled cost ledger), every `EXE` row is Not started, and `EXE` was never named in the agreed build order ("CON first, INF alongside, then SUR+GRK+VOL, DAT, SIG, BKT, NAT, RSK+ANL continuous, MIG last"). **Decided:** (a) `EXE` is written explicitly into the build order after `DAT`, with `EXE-09` and `EXE-10` moved up because `MK-05`, the kill test, is not computable without them; (b) a minimal latency probe — resting orders placed far enough from the touch that they will not fill, measuring submit-to-ack and cancel-to-ack, then cancelled — is **authorised in principle**. **Binding qualifications:** both are scheduled **later this week, explicitly not 2026-08-19**, and the live-order step requires a fresh go from Aryan at the time it runs; authorisation in principle is not authorisation to place an order. |
| D26 | **The ₹21 premium regime split is pre-registered now as a stratification variable** | **Decided 2026-08-19 by Aryan (Telegram, ~10:5x IST).** The maker research found at-touch spread elasticity 1.05 (R² 0.79) with the one-tick floor binding below roughly ₹21 premium, so the spread is a floor in one regime and a level in the other. **Decided:** the split is declared as a stratification variable in `MK-05` and `MK-06` **before results are inspected**, under `D22`'s pre-registration rule. This does **not** choose a regime — which regime is pursued stays with the data (Aryan: "only the data can tell us"). Reason: discovering the split after seeing results is exactly the multiplicity leak `SIG-12` exists to prevent. Declaring it now costs nothing and protects the inference later. |
| D27 | **Admissible strategy speed is bounded below by the slowest relevant feed cadence** | **Decided 2026-08-19 by Aryan (Telegram, ~11:17 IST), on the `DAT-16` finding.** Aryan: "our strategies will be governed by the slowest feed among all level 5, 20, 200 — that's not a problem in itself, we need to know that — that's important to know what is the range at which our data operates so we don't choose strategies that run faster than that." **Decided:** the measured delivery cadence of the feeds a strategy depends on is a **hard lower bound on that strategy's decision horizon**, and a strategy whose edge requires reacting faster than the slowest feed it consumes is **inadmissible by construction**, not merely hard. This does not choose a horizon — `D20` still leaves the horizon set empirical — it **truncates the admissible set from below**. Spec consequences: (i) `SIG-19`'s swept horizon axis must exclude horizons below the binding cadence, and the exclusion must be stated rather than silently unsampled; (ii) `MK-01`'s stale-value budget is measured against the feed clock, not only against order-path latency; (iii) a strategy consuming two tiers inherits the slower of the two. **Immediate gap this exposes:** cadence is measured for depth20 only (2.00/s metronome) and characterised for Quote/Full (1.22–1.66/s, dispersed, not a metronome). The 5-level block inside Quote/Full and the depth200 channel are **unmeasured**. Tracked as `DAT-17` — until it lands, the binding cadence for any multi-tier strategy is unknown, not assumed |
| D28 | **The far depth200 tail is an anomaly-monitoring research object, not discarded because its ordinary event rate is low** | **Decided 2026-08-19 by Aryan (Telegram, ~13:59–14:05 IST), after `DAT-20`.** The reason to retain the far book is not routine fill-probability or cancellation analysis. Its value is that the region is normally quiet, so an unusual addition, removal, relocation, quantity shock, or order-count shock may be informative about later price movement. **Binding distinction:** `DAT-20` Live verifies observability and finds no evidence that its ~400 ms gaps are information loss; it does **not** establish that rare deep events are large, directional, or predictive. That is a new pre-registered signal-research question, `SIG-21`, and must be tested causally against future price horizons under `D20`, `D22`, and `D27`. Low unconditional frequency is therefore a baseline for anomaly detection, not evidence that the far ladder is useless. |
| D29 | **Every hypothesis resolves at a named measurement scale; compute does not choose the inferential family** | **Approved by Aryan 2026-08-19 during the OFI discussion and recorded after the earlier `D28` ID was occupied by the depth200 decision.** The binding method is `docs/sig-claims/METHOD.md`. Before execution, every hypothesis binds `X, h₁, f₁, Y, h₂, f₂, Z` (the causal gap) and stratum, or declares a choice as a swept axis that enters the full grid `G`. Resolution reports effect `K`, calendar span, `N`, effective `N_eff`, `G`, dependence-aware uncertainty, ex-ante MDE and economic/admissibility verdict. A pushed pre-execution commit is the registration clock. `Z=0` is descriptive; `0<Z<R` is unavailable to the realised path; `Z≥R` is decision-relevant, where `R` is the measured feed + transport + decision + acknowledgement bound. Underpowered nulls are `Inconclusive`, not falsified, and results below realised `R` are demoted rather than deleted. Aryan delegated grid size to the method: use as many cells as measurement requires; compute provisioning is a separate engineering issue and never a reason to omit tested arms after inspecting results. |
| D30 | **The primary maker decision object is the joint quoting configuration across the option chain** | **Approved explicitly by Aryan 2026-08-19:** “the joint quoting configuration is the right direction.” Shaurya evaluates simultaneous resting bids and asks across puts and calls against one central portfolio state. Per-quote fill probability and fill-conditioned markout remain separate measurement primitives, but a quote is not promoted independently: its possible fill also changes portfolio delta, maturity-sensitive gamma/vega, flattening capacity, peak margin and residual futures-breach probability. Quote skew/passive option fills are the routine inventory-control mechanism; futures are a breach valve. The configuration is evaluated per unit of peak margin under `SIG-17`. This decision changes the estimand, **not the controller choice**: independent, delta-only joint and delta+gamma/vega joint states remain registered empirical comparisons (`BK-14/H1`). Literature scope and boundaries are in `docs/research/joint-option-quoting-literature-2026-08-19.md`. |
| D31 | **`SIG-21` is activated now, top-down, with the pushed pre-registration as a hard outcome gate** | **Directed by Aryan by voice 2026-08-19 ~14:49 IST.** Proceed with the registration plus construction detector now; update `TASKS.md`, the model specification and dependent documentation before code; commit, push and verify that gate; only then use agents to build the rest of the pipeline. This supersedes the earlier same-day sequencing that put the `PP` / `SIG-04` debate next, without dropping that debate. **No DAT-20 or other future-price response may be inspected before the registering commit is pushed.** The construction detector is deliberately outcome-blind and may use the retained DAT-20 tapes only for parser/event-construction checks and event counts. |
| D32 | **SIG-21's differentiating signal source is the 200-level ladder; depth20 is measurement support, not the treatment** | **Clarified by Aryan by voice 2026-08-19 ~15:41 IST before resetting.** Public top-20 depth is not the research object that differentiates this project. Every SIG-21 anomaly candidate, baseline magnitude and event episode must originate from the Dhan depth200 channel and the price-keyed far ladder. Depth20 remains necessary but has a different role: it supplies the future BBO midpoint response and registered near-book controls such as spread/top-20 depth and OFI. It must never enter the anomaly detector or substitute for missing depth200. Tomorrow's five-session calibration sequence therefore captures both channels for the same NIFTY front-month future, with channel roles written into the capture metrics. **The registered family remains the already-pushed 384 cells.** Calibration may determine support, `N_eff`, critical values and MDE; it may not choose axes/cells after seeing outcomes. The immutable `H-SIG21` registration is unchanged because §§2–3 already encode exactly this separation. |
| — | Futures direction vs option fair value — **declined as a pre-choice** | **2026-08-19.** Asked whether the ledger's primary object should be futures-side directional prediction or option-side fair value, with the other demoted to an intermediate. Aryan declined the framing outright: the question re-asks what `D20` already settled, and pre-choosing the object is exactly the error `D8` forbids. **Both remain fully in scope and open; the data decides which carries opportunity.** Recorded so the question is not raised a third time. |

### 1.1 Renames executed 2026-08-17

Authorised by Aryan by voice ("change it to something else whatever you like"); names chosen by
OpenClaw and applied. Both verified after the fact.

| Was | Now | Notes |
|---|---|---|
| GitHub `ayyararyan/Shaurya` (private) | **`ayyararyan/Market-Making`** | Matches the strategy's new name, the local path `/Users/maheit/Documents/Market-Making`, and `My Drive/Market Making/`. Local `origin` remote updated and verified reachable (`main` at `1a8ad8c`). GitHub redirects the old URL, so nothing breaks. |
| Drive `My Drive/Shaurya/` | **`My Drive/Valour/`** | A personal folder — motto, Mandarin lessons, Finances, and the Momentum research (GRF, herding-mom, india-replication). Nothing to do with trading. "Valour" is the literal meaning of *shaurya*, so the folder keeps its intent and only gives up the string. Drive preserves file IDs across a rename, so existing links still resolve. |

The name **Shaurya** is now unambiguous: it means this module, and nothing else.

### 1.2 What D5 commits us to

Plug-and-play is a stronger requirement than "share some code", and it constrains the design:

- The module is a **versioned, installable package** — a Python distribution and a C++
  library/CMake target. Strategies depend on a pinned version.
- **Dependency direction is one-way and absolute.** Strategies import the module. The module
  never imports from a strategy, never contains strategy-specific branches, and never
  special-cases Market Making.
- Anything strategy-specific that cannot be generalised **stays in the strategy**. Better a
  smaller module than a module with a Market Making shaped hole in it.
- Because strategies pin a version, the module needs a real release and changelog discipline
  from the first commit (INF-09).

This also settles O1 by implication: a thing that plugs into many strategies has to be a
standalone repository and package, not a subdirectory of one strategy. Flagged rather than
buried — say so if you want it to live somewhere else.

**One risk, stated once and then dropped.** Market Making is the only engine with a
broker-verified path, and refactoring it to consume the module puts that at risk. The
mitigation is in MIG-01: refactor strictly behind the existing test suites (91 C++, 144
Python), require green before and after, and never change behaviour in the same commit as a
refactor. Proceeding as decided.

### Resolved

| # | Question | Resolution |
|---|---|---|
| O4 | Broker scope: Kotak only, or Dhan and Kite order placement too? | **Resolved 2026-08-17 by voice — see D7.** Data: Dhan and Kotak both. Order placement: Kotak only. |

### Still open

| # | Question | Recommendation |
|---|---|---|
| O5 | Are all six old strategies to be migrated, or are some dead and left frozen as history? | Migrate opportunistically, not big-bang. Some are probably history. **Deferred 2026-08-17 by voice** — decide per strategy when it is next touched, not now; not a decision to force in the abstract. |

---

## 2. Component list — agreed and frozen

**Agreed 2026-08-17 (D15), closing D3.** Debated one component at a time over the 2026-08-17
sessions. `SIG` was added during the walk; nothing was cut. New capability from here arrives as
a new task ID within a component, not by reopening this list.

| Prefix | Component | One-line purpose |
|---|---|---|
| `INF` | Foundations | Repo, packaging, build, test harness, secrets |
| `CON` | Contracts | Shared schemas both languages agree on |
| `SUR` | Volatility surfaces | eSSVI, SVI, SABR, arbitrage checks |
| `GRK` | Pricing & Greeks | IV inversion, forwards, surface-consistent Greeks |
| `VOL` | Realised vol & forecasting | Estimators and forecast evaluation |
| `DAT` | Market data | Dhan streaming, historical fetch, storage, tape/replay |
| `EXE` | Execution & brokers | Broker interface, Kotak, paper fills, ledger, safety gates |
| `SIG` | Signal research & validation | Feature construction, prediction targets, selection, validation gates (D10) |
| `RSK` | Risk | Limits, sizing, kill switch, margin |
| `BKT` | Backtesting | Event-driven replay, execution realism, walk-forward |
| `ANL` | Analytics & reporting | P&L attribution, markouts, dashboards, alerts |
| `NAT` | Native live engine | The C++ runtime, generalised out of Market Making |
| `MIG` | Migration | Porting existing strategies onto the module |

---

## 3. Tasks

Legend for the **Harvest from** column: this is where working code already exists. The default
approach for every task is *harvest, reconcile, test, generalise* — not write from scratch.

### INF — Foundations

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| INF-01 | Create the standalone repository `shaurya`, holding `python/` and `native/`. **GitHub: `ayyararyan/Shaurya`, private** (D9) | — | — | **Implemented 2026-08-17** — private GitHub repository created from the canonical `README.md` and `TASKS.md`; package/build skeletons remain separately tracked by INF-02/03 |
| INF-02 | Python package skeleton: `pyproject.toml`, `shaurya` package, lint/type config. Must be **installable** — strategies pin a version (D5) | `VOLARB/voltaire`, `Shoshin` (`pyproject.toml`, `uv.lock`) | INF-01 | **Tested 2026-08-18** — retained the existing setuptools package plus strict mypy/Ruff configuration after harvest (current VOLARB is requirements-only; Shoshin's `pyproject.toml` only configures pytest); clean editable and clean-wheel installs both imported matching version `0.1.0` |
| INF-03 | C++ build skeleton: CMake, `shaurya::` namespace, compiler flags. Must export a **consumable CMake target**, not just build in place (D5) | Market Making `native/` | INF-01 | Not started |
| INF-04 | Test harness both sides: pytest + the C++ test-runner pattern already in use | Market Making `native/src/*_tests.cpp`, `VOLARB/voltaire/tests/` | INF-02, INF-03 | Not started |
| INF-05 | Secret-handling policy: config carries a credential *handle*, never a value; secrets live outside the tree at `700`/`600` | Market Making secrets pattern (`~/Documents/Market-Making-Secrets`) | — | **Tested 2026-08-18** — `docs/SECRETS.md` fixes the external-handle/`700`/`600` policy; CON-04 rejects raw credential fields; the harvested Market-Making-Secrets directory/file modes were verified as `700`/`600` without reading values |
| INF-06 | Relocate loose credential files currently sitting inside strategy trees (see §5) | — | INF-05 | **Blocked 2026-08-18** — all 9 listed files were inventoried without reading values: 8 still exist in Drive, but the exact external destination naming/location is not specified, so originals and reader code were left untouched rather than guessing; the ninth (`Market Making/dhan_credentials.env`) is absent and already represented by the pre-existing external `Market-Making-Secrets/dhan.env` mirror. Per-file reader evidence is in `docs/SECRETS.md` |
| INF-07 | `.gitignore` audit: no `.env`, `.pem`, tokens, run state, logs, or data ever tracked | Market Making (already correct) | INF-01 | **Tested 2026-08-18** — Shaurya ignore rules hardened; 0 current/history tracked credential/run/log/generated-data paths and 0 strong secret signatures; Market Making also 0. Drive spot-check found 1 already-tracked data file in Still Water (`data/lstm_dataset.parquet`), reported but not force-removed |
| INF-08 | Resolve the `Shaurya` name collision across GitHub and Drive | — | — | **Done 2026-08-17** — see §1.1 |
| INF-09 | Release discipline: semantic versioning, `CHANGELOG.md`, tagged releases. Required because D5 makes strategies pin a module version | Market Making `MODEL_CHANGELOG.md` | INF-01 | **Tested 2026-08-18** — `CHANGELOG.md`, package `0.1.0`, `__version__`, and release tag `v0.1.0` agree; automated metadata test added. `0.1.0` is the first pre-1.0 minor release because installable/live-data foundations exist while most frozen components remain unimplemented |
| INF-10 | Enforce one-way dependency direction: a CI check that the module never imports from any strategy (D5) | — | INF-04 | Not started |

### CON — Contracts

Do these **first**. Every other component depends on them, and if they move later everything
downstream has to be reworked.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| CON-01 | Snapshot/tape row schema: BBO, depth, timestamps, quality flags | Market Making `surface_snapshots_<run_id>.csv` schema, `monday_v1/snapshot_tape.py` | — | **Live verified 2026-08-18 for the original capture fields; DAT-14 schema `1.1.0` extension Live verified 2026-08-19 at its stated scope.** Schema `1.1.0` adds raw print/quote inputs, both BBO-leg receive times, quote age/bound, versioned side/alignment, degraded reason and coalesced flag while loading retained `1.0.0` rows. The original fields remain live-verified in run `sha-20260818T055709.463701Z-ea8228c8`; two simultaneous Standard+depth20 futures captures wrote 11,691 live `1.1.0` rows, including 313 positive-volume print rows with 313/313 classifier/alignment version stamps. The extension remains unverified for options, healthy depth200 alignment, and other times of day |
| CON-02 | Ledger row schema: placement, execution, cancel/reject, cycle P&L, order role, quote price, order age, book state, K, break-even spread, fill price | Market Making master CSV ledger definition, `native/src/shaurya_ledger.cpp` | — | **Tested 2026-08-18** — broker-neutral versioned row reconciles the Python/C++ master-ledger lifecycle and rejects event rows missing placement, execution, cancel/reject, or cycle-P&L fields |
| CON-03 | Surface frame schema: parameters, fit diagnostics, surface age, staleness flag | Market Making `monday_v1/surface_region.py` | — | **Tested 2026-08-18** — model-agnostic versioned frame carries named parameters/diagnostics, exact age, caller-supplied staleness threshold, consistent flag, causal timing, and category labels |
| CON-04 | Config schema: one format, consumed by both Python and C++ | Market Making `tomorrow.example.json`, `Still_Water/config/runtime_profile.json` | — | **Tested 2026-08-18** — strict versioned JSON/Pydantic root carries external credential handles and caller-supplied unit-explicit risk limits; committed golden fixture is the forward C++ acceptance input for INF-03/NAT |
| CON-05 | **Instrument identity.** Dhan `security_id` and Kotak token are two different ID systems for the same contract (Kite dropped entirely — D17, 2026-08-18). Define one internal instrument representation plus per-broker mapping | `Shoshin/security_id_list.csv`, Market Making `nifty_futures_token.txt`, `Market Making/api-scrip-master.csv` | — | **Tested 2026-08-19; Dhan slice retains Live verified evidence from 2026-08-18.** Broker-neutral identity now has date-stamped Dhan `security_id` and Kotak routing-token mappings, strict Dhan/Kotak master parsers, and same-day bidirectional indexes. Kotak remains routing-only under D18; Kite is absent |
| CON-06 | Object-category labelling convention: observed / derived / estimated / scenario / proxy / unidentified, carried in artifacts | Working contract §7.1 | — | **Tested 2026-08-18** — exact six-value enum plus serializable provenance/assumption/limitation label is carried by ledger, surface, and finding artifacts and rejects unknown categories |
| CON-07 | Time convention: exchange timestamp vs receive timestamp vs decision timestamp; IST throughout; explicit causality rule | Market Making `surface_live.py` (`as_of` causality) | — | **Tested 2026-08-18** — shared IST timing contract distinguishes exchange/receive/decision/additional-source timestamps and rejects any consumed time later than the decision timestamp |
| CON-08 | Run-ID and artifact-manifest convention: append-only, unique per run, invalidated runs preserved and marked | Market Making `surface_run_manifest_<run_id>.json` | — | **Live verified 2026-08-18** — unique sortable run ID, permission-restricted append-only JSONL manifest, artifact hashes, completion/invalidation events; failed diagnostic runs preserved and authoritative run hash-verified |
| CON-09 | **Opportunity/finding schema (D8).** A record of what the data shows, independent of any strategy or ledger entry: window, statistic, magnitude, confidence/significance, object-category label. Exists upstream of any strategy decision — the artifact that lets data lead and strategy follow | New | CON-06, CON-07 | **Tested 2026-08-18** — versioned strategy-independent finding carries causal window, statistic, magnitude/unit, explicit uncertainty, search-grid context, and object label; future-window leakage is rejected |

### SUR — Volatility surfaces

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| SUR-01 | Define one surface interface: `fit`, `evaluate`, `params`, `diagnostics`, `arb_check`. All parameterisations implement it | — | CON-03 | **Tested 2026-08-18** — abstract interface consumes CON-01 tape rows, exposes explicit supported/data-insufficient evaluations, emits strict CON-03 frames, and has a conformance suite |
| SUR-02 | Port eSSVI onto the interface, with tests | `VOLARB/voltaire/src/models/essvi.py` (7.3K, tested) | SUR-01 | **Dry-run verified 2026-08-18** — multi-expiry constrained eSSVI recovered realistic synthetic CON-01 option books, emitted round-trippable CON-03 frames, and passed independent arbitrage gates; real DAT replay/live integration remains pending |
| SUR-03 | Implement SVI — raw, natural, and jump-wings parameterisations, with conversions between them | New | SUR-01 | **Blocked** — deferred until a concrete strategy needs it beyond eSSVI (D8, decided 2026-08-17: no speculative model-building ahead of a data-shown need) |
| SUR-04 | Implement SABR — Hagan expansion plus a note on its known arbitrage failure at low strikes / long maturities | New | SUR-01 | **Blocked** — same reason as SUR-03 (D8, decided 2026-08-17) |
| SUR-05 | No-arbitrage checks: butterfly (implied density non-negative), calendar (total variance non-decreasing in maturity) | New | SUR-01 | **Tested 2026-08-18** — known-valid/invalid fixtures distinguish butterfly and calendar violations; every raw and smoothed eSSVI fit is independently checked on dense declared grids |
| SUR-06 | Fit diagnostics: weighted R², residuals by moneyness bucket, parameter stability across consecutive frames | Market Making `monday_v1/surface_fit.py` | SUR-01 | **Tested 2026-08-18** — CON-03 diagnostics carry weighted R²/RMSE, five moneyness-bucket residual summaries, optimizer/constraint evidence, exclusions, and consecutive-frame parameter changes |
| SUR-07 | Staleness semantics: **the module exposes surface age and a staleness flag as a measurement; each strategy sets its own staleness-tolerance threshold** (decided 2026-08-17). A raw surface takes ~3s to compute, so quoting must consume a temporally smoothed surface, never a tick-synchronous raw frame | Market Making `monday_v1/surface_region.py` | SUR-01, CON-07 | **Tested 2026-08-18** — caller thresholds drive exact age/flag output; raw fits fail closed for quoting, while two-or-more-frame time-decayed smoothing intersects support and rechecks constraints/arbitrage before becoming quote-ready |
| SUR-08 | Interpolation/extrapolation policy in strike and maturity, stated explicitly rather than left to whatever the fitter does | New | SUR-01 | **Tested 2026-08-18** — eSSVI strike interpolation is restricted to observed support, maturity interpolation is linear in total variance on common support, and both strike/maturity extrapolation return explicit data-insufficient results |

### GRK — Pricing & Greeks

**Scope: European exercise only** (decided 2026-08-17 by voice — American/single-stock
support deferred until a strategy concretely needs it, same reasoning as SUR-03/04. Nothing
in the current pipeline, Market Making or VOLARB, trades single-stock options).

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| GRK-01 | Port the Greeks module, with tests. **Internal machinery only, not a strategy-facing API** (decided 2026-08-17 — per-strike inverted-IV Greeks are inconsistent with each other across strikes by construction; only GRK-02's surface-consistent Greeks are exposed to strategies) | `VOLARB/voltaire/src/models/greeks.py` (12K, tested) | — | Not started |
| GRK-02 | Surface-consistent Greeks: computed from the fitted surface, not from per-strike inverted IVs. **The sole strategy-facing Greeks API** (decided 2026-08-17, see GRK-01) | New | GRK-01, SUR-01 | Not started |
| GRK-03 | Forward construction. **Primary method: put-call parity off the ATM strikes within each expiry's own option chain (C − P = F − K); the listed future is used only as a cross-check where one exists** (decided 2026-08-17 — NSE index weeklies have no matching listed future, only monthlies do, so a parity-derived forward generalises across expiries without forcing weeklies to borrow a monthly future's basis) | `VOLARB/voltaire/src/models/proxies.py` | GRK-01 | Not started |
| GRK-04 | Robust IV inversion: bracketing, no-solution and deep-ITM/OTM edge cases, explicit failure rather than a silent NaN. European pricing model only per the scope note above | New | GRK-01 | Not started |

### VOL — Realised volatility & forecasting

**Scope philosophy for this component (decided 2026-08-17 by voice, overriding the general D8
default for VOL specifically): build the full estimator and signal toolkit now rather than
leaving gaps to backfill later** — Aryan's explicit call, distinct from SUR-03/04's
defer-until-needed pattern. Applies to VOL-02 and VOL-05 below; kept scoped to VOL because the
estimators here are general-purpose measurement, not a strategy-specific model bet.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| VOL-01 | Port realised-vol estimators, with tests | `VOLARB/voltaire/src/models/realized_volatility.py` (tested) | — | Not started |
| VOL-02 | Complete the full estimator set now, including realised kernel / bipower: close-to-close, Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang, kernel, bipower. **Not deferred** (decided 2026-08-17; data-source corrected 2026-08-18 by D16 — kernel/bipower are tested against the tick-level tape accumulated live via `DAT-02`/`DAT-05`, never `DAT-03`, which is bars-only by definition and cannot substitute) | Partly VOL-01 | VOL-01, DAT-02 | Not started |
| VOL-03 | Port vol forecasting and define a forecast-evaluation harness (out-of-sample QLIKE and MSE, not in-sample fit) | `VOLARB/voltaire/src/models/volatility_forecasting.py` | VOL-01 | Not started |
| VOL-04 | Regime classification. **Build now, method = HMM** (decided 2026-08-17 — hidden Markov model is the benchmark/standard approach; overrides the D8 defer-by-default treatment other speculative model components got, per the VOL scope philosophy above) | `VOLARB/voltaire/src/models/regime.py` (stub, 136 bytes — effectively new work) | VOL-01 | Not started |
| VOL-05 | **RV-vs-IV comparison / variance risk premium.** Compares VOL-01/02 realised-vol output against the GRK/SUR-fitted implied surface. Not folded into VOL-01/02 (those stay pure underlying-price-process measurement) — this task owns the comparison and emits output in CON-09's opportunity/finding schema (decided 2026-08-17 — in scope now, not deferred, per the VOL scope philosophy above) | New | VOL-01, SUR-01, GRK-02, CON-09 | Not started |

### DAT — Market data

**Priority note (decided 2026-08-17 by voice):** DAT-02 (live Dhan tick/depth streaming) is
elevated ahead of the informal build-order default. No broker API offers tick-level *historical*
data, so the only way to get the intraday tick data VOL-02's kernel/bipower estimators need is
to start collecting it live, now — it's a forward-only data-collection task, not something DAT-03
can backfill. DAT-03 still matters but is limited to coarser historical granularity (bars); it
does not substitute for DAT-02 here.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| DAT-01 | **Reconcile the two Dhan clients into one.** Two independent implementations exist; diff them, choose the canonical one, document what the loser did differently and why it was dropped | `Mushin_Gamma/src/mushin_gamma/dhan_io.py` (13K) and `Shoshin/src/dhan_client.py` (8.4K) | — | **Tested 2026-08-18** — Mushin won as structural base; Shoshin retry/pacing/normalisation merged; exact reconciliation in `docs/DAT_01_RECONCILIATION.md`; Dhan execution methods excluded under D7 |
| DAT-02 | Dhan live streaming: ticks and depth, reconnect, heartbeat, sequence-gap detection. **Elevated priority** (decided 2026-08-17 — see priority note above; this is the only source of tick-level data for VOL-02, so collection needs to start now, not once the rest of DAT is built out) | `Mushin_Gamma/src/mushin_gamma/feed.py`, `Still_Water/src/engine/data_feed.py` | DAT-01 | **Live verified 2026-08-18 — both required channels.** Standard Full (ticks + 5-level) and 20-level parsing, reconnect/resubscribe, heartbeat, source-sequence-gap detector, reconnect-boundary gaps, metrics, and per-enabled-channel acceptance are implemented/tested. Live run `sha-20260818T055709.463701Z-ea8228c8` verified 20-level depth + heartbeat first; after the access token was refreshed, live run `sha-20260818T090544.387358Z-8d9c80fc` verified standard (tick/5-level) + 20-level together in one session, `acceptance.missing_channels: []`, zero reconnects |
| DAT-03 | Historical fetch and local storage against a stable on-disk schema. **Bars/coarser granularity only — no tick-level history available from any broker API** (noted 2026-08-17, see priority note above) | `VOLARB/voltaire/src/data/{historical_fetcher,storage}.py`, `Shoshin/src/data_downloader.py` | CON-01 | **Tested 2026-08-19.** Dhan minute/daily responses normalize into a strict versioned observed-bar schema; immutable `0600` JSONL storage round-trips and surfaces time gaps. It makes no tick-history claim and does not substitute for DAT-02/DAT-05 |
| DAT-04 | Option-chain fetch and validation | `VOLARB/voltaire/src/data/{option_chain_fetcher,validation}.py` (11K validation) | CON-05 | **Tested 2026-08-19.** Versioned observed chain/quote schemas validate every security ID, underlying, expiry, strike and side against the same-date canonical Dhan master; unknown/mismatched IDs, crossed quotes and non-IST timestamps fail closed |
| DAT-05 | Tape recording (append-only) and **deterministic** replay — same tape format consumed by live, backtest, and research. **Full order-book depth, multiple price levels — confirmed 2026-08-17, not BBO/top-of-book only** (BKT-03 execution realism needs it, and Market Making's existing tape already captures this) | Market Making `monday_v1/{snapshot_tape,surface_replay}.py` | CON-01, CON-08 | **Dry-run verified 2026-08-19; append-only writer retains Live verified evidence from 2026-08-18.** Strict replay preserves exact ordered rows/quality flags and rejects mixed runs, corruption, regressions and gaps. Read-only replay validated all 21,279 rows across four non-empty existing live tapes (20,494 depth20, 366 depth200, 419 mixed standard/depth); permanent retention exposes no rolling delete/expiry path |
| DAT-06 | Data-quality counters: crossed book, stale quote, invalid depth, gap count — surfaced, not silently dropped | Market Making `surface_collector_audit_<run_id>.jsonl` | DAT-02 | **Dry-run verified 2026-08-19.** Split-book side age emits `stale_quote`; all flags feed counters; the capture CLI writes a versioned derived audit with crossed/stale/invalid/gap counts present even when zero. Synthetic stale/counter injection and artifact output passed; post-change live audit remains pending the next capture |
| DAT-07 | Instrument-master loader per broker, plus the mapping layer. **Daily refresh cadence** (decided 2026-08-17 — broker tokens, Kotak and Dhan `security_id`, are only guaranteed stable within a trading day, so refresh must happen every day whenever the module is in use, not just periodically/at-startup) | `Market Making/api-scrip-master.csv`, `Shoshin/security_id_list.csv` | CON-05 | **Tested 2026-08-19.** Broker-generic refresh writes one immutable, hash-validated `0600` master+manifest per trading date with permanent retention; Dhan and Kotak parsers/indexes reject stale, duplicate, partial and tampered mappings. Kotak identity is routing-only under D18 |
| DAT-08 | ~~Kotak market-data path in C++ (WebSocket + depth)~~ | Market Making `native/src/shaurya_kotak_ws_*.cpp`, `shaurya_kotak_depth.cpp` (tested) | NAT-01 | **Dropped 2026-08-18 — see D18.** Kotak is order-placement only; the module does not receive Kotak market data. Data ingestion is Dhan-only |
| DAT-09 | **Capture universe, depth tier, and retention window.** D12 settled *that* the raw tape is recorded; this task settles *how much*. Three inputs, in dependency order: (i) **measured delivery rate per instrument per depth tier** — raw row rates were measured live 2026-08-18; DAT-16 later established that 20-level's correct semantic unit is a fixed 2 Hz snapshot burst containing ~4.17 rows, while the depth200 cadence remains characterised only by raw rows; (ii) **measured concurrent-instrument cap** per depth tier — **20-level exact observed per-message ceiling is 50 instruments (DAT-11, 2026-08-19), NOT the documented 5,000/socket; DAT-12 found the reproduced 50+50 second-message failure is socket-scoped and reset by reconnect, while 2+2 succeeds on one socket. DAT-13 resolves the 200-level skew as a first-subscription throttle/bias: the first future received 328 packets versus 2 each later, and dominance rotated with order.** The exact 200-level count cap remains unmeasured; (iii) **universe and retention.** Universe (NSE-only, index F&O only: NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY) decided 2026-08-18 in `GCP_SCALING.md`. Exact depth-tier band width (e.g. ATM±7) explicitly **not decided — illustrative only**, and must be derived against the observed 50/socket ceiling. **Retention decided 2026-08-18 (Aryan, by voice): permanent — once collected, data stays; no rolling deletion/expiry window, since storage cost is immaterial against the GCP credit.** Supersedes the original 60–90-day-rolling proposal | New | DAT-02, DAT-05 | **Implemented and Tested 2026-08-19 at the pre-live level; DAT-11/12/13/16 inputs now Live verified.** Versioned plans enforce same-day masters, the four NSE index underlyings, explicit permanent retention, and unresolved `None` values for exact strike band. Production 20-level capture sends exactly one message/socket and partitions larger explicit selections across connection-labelled sockets with global receive order at the measured 50/socket ceiling. **Still open by binding design:** final strike-band/connection-count choice; 200-level full-rate planning must account for DAT-13's throttle |
| DAT-10 | **200-level deep-book capture.** Separate endpoint (`wss://full-depth-api.dhan.co/`), one instrument per subscription message, ~6.4 KB per book update. A genuinely rare research asset — full visible book on the traded instrument — and cheap at ~45 GB/year for one instrument. Kept as its own task because the endpoint, subscription semantics, and packet parser differ from both `DAT-02` and the 20-level feed | `DhanHQ-py` `fulldepth.py` (reference implementation) | DAT-02, CON-01 | **Live verified 2026-08-18.** Live run `sha-20260818T092355.175225Z-d181b3ff`, NIFTY-Aug2026-FUT: 366 rows in 45s (8.1/s, 8.4/s active span), 3,212 bytes/packet exactly matching the documented layout, full 200 bid + 200 ask levels confirmed independently in the written tape (not just the run summary), one connection, 4/4 heartbeats, zero reconnects. One real bug found and fixed en route: the 200-level endpoint silently drops the batched `InstrumentList` subscription shape reused from DAT-02's 20-level path (connection + heartbeats stay healthy, zero packets ever arrive) — it needs a flat `{RequestCode, ExchangeSegment, SecurityId}` message instead, confirmed against `dhanhq.fulldepth.FullDepth`. Regression test added (`test_depth200_subscribe_uses_flat_message_not_instrument_list`) |
| DAT-11 | **Bisect the exact 20-level per-message instrument ceiling.** 2026-08-18's four live tests pinned it somewhere between 52 (worked) and 206 (rejected outright) but ran out of trading-hours window to narrow it further. Needed to turn "50-80+ connections" into an exact connection-count plan | `scripts/dat09_concurrency_probe.py` (extend with a binary-search loop) | DAT-09 | **Live verified 2026-08-19: exact observed ceiling = 50 instruments per message; solo-row-rate addendum = `not-discriminated`.** Fresh sockets and exactly one message per candidate; NIFTY/BANKNIFTY front futures led every prefix as liquid controls. Counts 2, 27, 40, 46, 49 and 50 were accepted with every selected instrument receiving packets; 51 and 53 were rejected wholesale with zero packets. The tested acceptance table is monotone. This corrects the prior-day claim that 52 worked. Four later fresh-socket solo NIFTY runs delivered 116, 120, 114, and 114 parsed rows in 15 s versus 116 inside the 50-instrument run. Removing 49 instruments did not materially lift the row rate, ruling out shared-socket bandwidth collapse, but parsed rows are not publication events; the requested solo-count test therefore does **not** discriminate a per-instrument cap from a true event rate. DAT-16 separately identifies the actual fixed 500 ms snapshot clock. Dated evidence: `docs/live-evidence/DAT-11-2026-08-19.md` |
| DAT-12 | **Test whether reconnecting a socket resets the "first message only" limit.** 2026-08-18 showed a second subscription message on an already-subscribed socket is silently ignored, pacing or not -- untested whether closing and reopening the connection (same credentials) lets a fresh socket accept a new "first" message, or whether the account/session itself is what's actually capped rather than the individual socket | `scripts/dat09_concurrency_probe.py` | DAT-09 | **Live verified 2026-08-19 — socket-scoped at the reproduced 50+50 load.** On one socket the first disjoint 50-instrument message delivered 5,880 packets across 50/50 instruments, while the second delivered 0 across 0/50. The identical second set alone on a fresh socket delivered 3,862 packets across 50/50. A separate 2+2 run delivered both same-socket messages, so the old blanket phrase “only the first message is honoured” is too broad: the failure is socket-local but load-dependent. Dated evidence: `docs/live-evidence/DAT-12-2026-08-19.md` |
| DAT-13 | **200-level same-liquidity control test.** 2026-08-18's 5-instrument concurrent test (2 futures + 3 option strikes) showed heavy packet-count skew toward the first-subscribed instrument (332 vs 2 packets in 40s) -- not yet disentangled from ordinary liquidity differences between a front-month future and a Sep-expiry 1,250-point-away strike. Rerun with several comparably-liquid instruments (e.g. front-month futures across NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY) to tell a real per-instrument throttle apart from liquidity | `scripts/dat09_concurrency_probe.py` | DAT-09, DAT-10 | **Live verified 2026-08-19 — genuine subscription-order throttle/bias, not ordinary liquidity.** With four front-month index futures, ordering NIFTY first produced 328 NIFTY packets versus 2 each for BANKNIFTY/FINNIFTY/MIDCPNIFTY; rotating BANKNIFTY first produced 328 BANKNIFTY packets versus 2 each for the other three, including NIFTY last. Both runs had all-received=true and 164× max/min skew. Dominance followed first subscription position, not instrument identity. Dated evidence: `docs/live-evidence/DAT-13-2026-08-19.md` |
| DAT-14 | **Trade-direction classification on the capture path (D24).** Classify each observed print buy/sell as the stream arrives, using the quote rule against the prevailing best bid/ask with a tick-rule fallback for at-mid prints, and write the result into the tape row. **Must carry a classifier version stamp** so the rule can be revised and recomputed offline against retained raw inputs — the sign is recorded in addition to, never instead of, last price, last quantity, cumulative-volume increment, the prevailing bid/ask actually used, and their receive timestamps. **Must define, version and test the cross-channel alignment rule** for "the quote prevailing before this trade", since trades arrive on the Quote/Full channel and depth on the separate 20/200-level channels with independent packet clocks; the alignment error is measured from tape, not assumed. **Must flag coalesced intervals** where the cumulative-volume increment exceeds the last traded quantity, because the inferred side then applies only to the last observed print. Bounded-state single forward pass, satisfying `SIG-20` by construction | New; rule from Lee-Ready and the quote/tick-rule literature, with Ellis-Michaely-O'Hara on classification error | CON-01, CON-07, DAT-02 | **Live verified 2026-08-19 for depth20 alignment on two front-month futures in one 10-minute morning window.** Simultaneous Standard+depth20 captures produced 11,691 rows and 313 positive-volume prints: 158 buy, 154 sell, 1 unclassified; 311 quote-rule, **1 live tick-rule fallback**, and 1 degraded (`no_prevailing_quote`). All 313/313 print rows carry classifier/alignment version stamps. Quote age n=312 was 7.4–567.4 ms (median 238.7, p95 462.6) against the 1 s bound. 113/313 (36.1%) intervals were coalesced; observed last quantities covered only 44.3% of cumulative-volume increments. Evidence does not cover options, depth200 selection, other times of day, or stale/crossed degraded causes. Dated evidence: `docs/live-evidence/DAT-14-2026-08-19.md`; DAT-15 remains separate |
| DAT-15 | **Measure the cross-channel alignment error introduced by `DAT-14` (D24).** Using retained tape, quantify how stale the depth-channel quote is at the moment a Quote/Full-channel print arrives, how often that staleness would flip a classification, and how the answer varies by instrument activity, depth tier and time of day. Output is a distribution and a flip-rate, not a single number, and it bounds the reliability of every signed-flow feature downstream. Also reports the frequency and size of coalesced-print intervals | New | DAT-14, DAT-05 | **Live verified 2026-08-19 for the retained eight-tape sample; scope limits explicit.** New reproducible analyzer consumed 38,572 rows and 482 prints. Healthy-core quote age n=323: median 238.7 ms, p95 462.6, max 567.4; post-BBO proxy flipped 5/320 directional comparisons (1.56%). Including a deliberately cross-tier but operationally degraded run: quote age n=480, median 212.1 ms, p95 3.82 s, max 24.16 s; 42/482 degraded and 5/429 proxy flips (1.17%). Coalescing was 206/482 (42.7%); excess unseen volume median 180 units, p95 2,080, max 7,215, and last quantities covered 32.0% of increment volume. Depth/activity/time tables are emitted, but depth200 appears only in the reconnect-heavy run, afternoon has n=12, and midday/options are absent; no general tier/time ranking is claimed. The flip comparator is explicitly a post-print look-ahead **proxy**, not identified truth. Code/tests: `alignment_analysis.py`, CLI, 5 focused tests; dated evidence: `docs/live-evidence/DAT-15-2026-08-19.md` |
| DAT-16 | **Characterise the depth-channel delivery cadence, and distinguish a publication clock from an event rate.** Group depth rows by distinct receive timestamp and measure burst rate, rows per burst, burst-gap distribution and the rate at which the top of book actually changes, so that netting-window width is a measured quantity rather than inferred from a raw packet count | `docs/live-evidence/DAT-16-2026-08-19.md` (analysis over retained DAT-14 tapes) | DAT-14, DAT-15 | **Live verified 2026-08-19 — the 20-level depth channel is a fixed 500 ms snapshot feed, not an event feed.** On both healthy DAT-14 futures tapes: 4,982/4,984 depth rows but **exactly 1,195 distinct receive timestamps each = 2.00 bursts/s**, 4.17 rows per burst, burst gap p05/p50/p95 = 496/501/506 ms. Both BBO legs always share one receive timestamp (leg difference 0.0 ms on every print). Top-of-book price changes only 0.24/s (NIFTY) and 0.67/s (BANKNIFTY). DAT-15's 238.7 ms median quote age plus 258.5 ms median post-print delay sum to 497 ms against the 501 ms cadence — DAT-15 measures **snapshot phase, not cross-channel drift**. Quote/Full is *not* a metronome (1.22–1.66/s, dispersed gaps). Amends `D23`'s packet-rate premise and widens the `EXE-10` netting window to 500 ms. The queued solo test was run concurrently before this correction was visible; its unchanged parsed-row rate rules out shared-socket bandwidth collapse but is `not-discriminated` for cap versus event rate. Found by OpenClaw during DAT-15 verification, not by the run agent. Not verified for depth200, options, other times of day, or reconnect periods; the physical origin of the cadence is unidentified |
| DAT-17 | **Measure the delivery cadence of every depth tier we may consume, so `D27`'s binding bound is known rather than assumed.** `DAT-16` established that depth20 is a fixed 500 ms publication clock (2.00 book states/s, burst-gap p05/p50/p95 496/501/506 ms) and that Quote/Full is *not* a metronome (1.22–1.66 distinct-timestamp updates/s, dispersed gaps). Two tiers remain uncharacterised: **(i) the 5-level depth block carried inside the Full packet** — is it republished on the Quote/Full clock or on its own; and **(ii) the 200-level channel**, whose cadence has never been grouped by receive timestamp and which `DAT-13` showed is additionally subject to a first-subscription throttle, so its effective per-instrument cadence beyond the first instrument may be far worse than its nominal one. Method is `DAT-16`'s and requires no new code: group tape rows by distinct receive timestamp, take successive differences, report burst rate, rows per burst, gap percentiles, and the fraction of bursts carrying a top-of-book price change. **Must also state which tier binds when two are consumed together**, since `D27` makes the slower one govern. Also worth resolving, though it may not be identifiable from tape alone: whether each cadence is a Dhan publication interval, broker-side aggregation, or an NSE-side snapshot — only one of those is negotiable | `docs/live-evidence/DAT-16-2026-08-19.md` (method); existing tapes for depth200; a fresh healthy capture needed for a clean depth200 sample | DAT-16, DAT-10, DAT-13 | **Live verified 2026-08-19 at the stated futures/window scope.** Two independent 600 s NIFTY depth200 runs each produced 4,980 rows / 2,491 exact receive-timestamp bursts = 4.1588–4.1589 bursts/s, 1.999 rows/burst, gap p05/p50/p95 approximately 197/201/401 ms, and zero reconnects or heartbeat timeouts. Depth200 is a quantized, skip-prone approximately 200 ms base clock, not depth20's fixed metronome. A timed four-future socket delivered recurring updates only to position 1 (742 packets / 372 timestamps in 91.003 s); positions 2–4 each emitted one startup bid/ask pair and then remained silent for approximately 89.9 s. **Observed usable recurring depth200 ceiling: 1 instrument/socket.** Retained DAT-14 tapes show the complete 5-level block in 730/730 NIFTY and 993/993 BANKNIFTY Full rows, so it runs on the dispersed Full clock (1.217–1.656/s). Under D27, Full binds Full+depth20 and Full+depth200 (median bound 557–874 ms; p95 guardrail 1,112–1,141 ms), while depth20 binds depth20+first-position-depth200 (501 ms median; 506 ms p95). Later-position depth200 has no finite recurring horizon and is inadmissible. Upstream publication mechanism is **UNIDENTIFIED**. **Provenance caveat, recorded so the evidence is auditable:** two DAT-17 agents ran concurrently by mistake — `673f8911` (11:49:05, 28m22s) spawned by one OpenClaw session and `2033be0d` (11:51:05, 16m44s) spawned by a second session two minutes later, both under the same task name and both against this clone. Both completed and the tree was deduplicated at `b4a2975`. Their overlap briefly raised concurrent Dhan sockets from two to three for approximately 35 s; the authoritative first capture had already completed and was unaffected, no disconnect occurred, and the duplicate tape was excluded. Additionally the `ANL-03` live dashboard held one Quote/Full socket throughout the DAT-17 window — a different endpoint from depth200, so contamination is considered unlikely, but it is stated rather than assumed away. Evidence: `docs/live-evidence/DAT-17-2026-08-19.md` |
| DAT-18 | **Consolidated multi-tier feed interpretation — the standing reading of what our data can and cannot support.** Commissioned by Aryan 2026-08-19 ~12:24 IST on receiving `DAT-17`: "the level wise feed thing needs to be seriously interpreted well", reserved deliberately for the evening session rather than answered on the spot. `DAT-16` and `DAT-17` have now measured all three tiers, and the raw numbers are **not** the interpretation. What is required is the synthesis: given Full/5-level at 1.2–1.7 dispersed updates/s, depth20 as a 501 ms metronome, and depth200 as a ~200 ms quantized but skip-prone clock **available on exactly one instrument per socket**, state which feed layouts are admissible under `D27`, what decision horizons each supports, and — the real question — **what the width-versus-depth trade actually costs in information**. The three tiers are not substitutes: depth200 buys resolution and costs breadth absolutely; depth20 buys breadth and costs a 4x wider blind window; Full buys prints and costs regularity. This is the input to `DAT-09` and it bounds `SIG-19`'s horizon sweep from below. Discussion first, then decisions — Aryan's explicit sequencing | `docs/live-evidence/DAT-16-2026-08-19.md`, `DAT-17-2026-08-19.md`, D27 | DAT-16, DAT-17 | **Not started — scheduled for the evening session of 2026-08-19; the first item, before any decision is taken** |
| DAT-19 | **Storage and retention architecture — how the tape is stored well, not merely stored.** Raised by Aryan 2026-08-19 ~12:24 IST as the third evening decision: the data is about to become big. Concrete measurement forcing it: the `ANL-03` live dashboard writes canonical JSONL at **~40 MB/minute on 452 Quote/Full instruments** — 865 MB in the first 22 minutes, roughly 15 GB for a full session at that width — against `D12`'s decision that the raw tape *is* recorded and `DAT-09`'s not-yet-made sizing choice. Scope: on-disk format and compression, partitioning and file granularity, an index that makes `DAT-05` replay seekable rather than a linear scan, checksums and integrity, cold/warm tiering, and where the bytes physically live. **Constraint that must not be traded away:** `D12` retains the raw tape precisely so `SIG-18` can measure the residual gap between a raw-book model and a feature model — any storage design that lossily summarises the book deletes that test and is a specification change, not an optimisation. Retention is **permanent** per Aryan's 2026-08-18 call; this task is about cost and access, not about deletion | `src/shaurya/data/tape.py` (DAT-05), `CON-01` | DAT-05, DAT-09, D12 | **Not started — scheduled for the evening session of 2026-08-19, after DAT-18** |
| DAT-20 | **Test whether depth200's cadence skips are activity thinning or feed loss (`H-DAT20`).** `DAT-17` characterised depth200 as "a quantized, skip-prone approximately 200 ms base clock". Aryan proposed 2026-08-19 ~13:05 IST that the skips are not a delivery deficiency at all: book activity is concentrated at and near the BBO and genuinely thins with distance, so where depth200 publishes nothing in a ~200 ms window nothing changed, making depth200 a **superset** of depth20 and the Full 5-level block rather than a degraded version. Requires pre-registration under `D22` before any result is seen, then four measurements on one instrument across all three tiers in one wall-clock window: cross-tier agreement at aligned instants (price, quantity and order count, with every disagreement characterised as clock phase or genuine difference); change rate and inter-change time by level index, and the depth beyond which a dedicated socket buys nothing a cheaper tier already delivered — the direct input to `DAT-09`'s width-versus-depth choice; whether depth20 or Full recorded any change inside each skipped depth200 tick, which is the decisive test; and the number of populated levels plus the actual rupee span from mid to the deepest level, measured rather than assumed. **Must not be allowed to over-reach:** H-DAT20 addresses cadence skips on a single subscribed instrument and cannot explain `DAT-17`'s separate four-future finding, so the 1 instrument/socket ceiling is out of scope by construction | `docs/live-evidence/DAT-20-2026-08-19.md`; `src/shaurya/data/depth_thinning_analysis.py`; `scripts/dat20_thinning_vs_loss_analysis.py` | DAT-16, DAT-17, DAT-15, D22, D27 | **Live verified 2026-08-19 on the central claim, at the stated single-instrument/futures-only/one-window scope; `F1`/`F2` `not-discriminated`.** Pre-registration committed at `bc458d4` before the analyser (`fedb2b2`) and before any capture. Two clean 660 s three-tier NIFTY captures (`sha-20260819T073935.092996Z-6ca41203`, `sha-20260819T075057.972093Z-286d5105`), 11,770 and 11,802 rows, one process/one tape/one clock, zero reconnects, zero heartbeat timeouts, 65/65 heartbeats per channel, 4 concurrent sockets held exactly against the budget with sequential bring-up recorded in each metrics artifact. All three tiers reproduced `DAT-16`/`DAT-17`: depth200 4.1625–4.2336/s with gap p05/p50/p95 197/200/401 ms, depth20 1.9908–1.9968/s at p50 500.7 ms, Full 1.21–1.22/s dispersed. **Decisive result — the skips are empty.** Holding span duration fixed at ~400 ms, the rate at which a witness tier shows a state depth200 never published is statistically indistinguishable between spans depth200 published nothing inside and spans it did: **10 of 10 comparisons non-significant across both runs** (smallest p = 0.067; two point the other way). The pre-registered skip-versus-control contrast appeared to fire on the deep ladder (45.0% vs 30.3%, z = 5.23) but that was entirely a window-length confound — a 400 ms skip window versus a 200 ms control window — and it vanishes under duration matching. **Top of book agrees:** level-1 price agreement 98.00%/99.54% against depth20 and 96.46%/99.00% against Full under the phase-tolerant rule, clearing the pre-registered 95% bar in both runs; median missing price points is 0 in every containment direction; all three tiers agree on the spread distribution to within 0.04 rupees at the mean, which rules out depth200 dropping inside levels. **Thinning holds, but not at the touch, and only once measured correctly:** the pre-registered position-keyed change rate *rises* with level index (Spearman +0.41 to +0.91) because a single insertion cascades onto every deeper position — a confound diagnosed from the data and pinned by a regression test — while the price-keyed rate, keyed to the same-side best quote with ladder-window slide excluded, decays as H-DAT20 predicts (Spearman −0.64 to −0.93, both runs, both sides). Activity per price point *peaks a few rupees behind the touch*, not at it, so "concentrated at the BBO" is wrong about "at" and right about "near". **Direct `DAT-09` input: 86.6–99.0% of all book events fall within Rs 20 of the same-side best quote, and Rs 20 is a median of 74–90 occupied levels; beyond that a price point runs at 0.05–0.08/s (bid) and 0.002–0.003/s (ask) against 1.2–2.8/s near the touch.** depth20's 20 levels reach only Rs 7.4–10.1 from mid and capture 57–84%, so the band between depth20's edge and Rs 20 out is real and only depth200 sees it. **Occupancy settled: all 200 levels are always populated with zero padding, and the median span is Rs 136.0–136.8 deepest-bid to deepest-ask — about 3.4x Aryan's ±Rs 20 working assumption and 6.8x the 200-contiguous-tick arithmetic — because only 13.3–18.4% of the 0.05-rupee tick grid inside the span is occupied (median 889–1,299 missing ticks per side, roughly one price point every Rs 0.27–0.38).** One real measurement bug was found and corrected mid-analysis and is disclosed in the evidence doc: the Full packet encodes 5-level prices as binary32 while both depth channels use binary64, so exact float equality initially reported 0/791 price agreement for reasons unrelated to the book; prices are now quantised to 2 dp, which is exact for the 0.05 tick, with regression tests both ways. **Not discriminated:** whether the residual 1–6% (bid) / 6–18% (ask) cross-tier level difference is snapshot phase or content — no channel in this tape carries an exchange timestamp or source sequence, so snapshot-instant alignment is unidentified and `F1`/`F2` cannot be adjudicated; also any skip effect smaller than ~4–6 percentage points, and gaps beyond the observed 603 ms maximum. **Upstream publication mechanism remains UNIDENTIFIED**, unchanged from `DAT-17`. **`DAT-17`'s 1 instrument/socket recurring depth200 ceiling is unaffected and stands unchanged** — DAT-20 tested one subscribed instrument on a dedicated socket, and no evidence bearing on the ceiling was found. Scope: one instrument, futures only, 13:09–13:32 IST midday, median spread Rs 5.00–6.70 with frequently single-lot top levels, no reconnect period, 22 minutes total. Code/tests: `depth_thinning_analysis.py` + 27 focused tests, 3 new `dhan_stream` tests for the sequential `channel_start_stagger_seconds` bring-up, full suite 154 passed. Dated evidence: `docs/live-evidence/DAT-20-2026-08-19.md` |

### EXE — Execution & brokers

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| EXE-01 | Define the broker interface: place, cancel, modify, order status, fills, positions, limits. Mirrored in Python and C++. **D7: only Kotak is implemented against it, but the interface stays broker-shaped, not Kotak-hardcoded** | Market Making `native/include/shaurya_kotak_broker_adapter.hpp`, `monday_v1/kotak_neo.py` | — | Not started |
| EXE-02 | Kotak implementation — the sole order-placement broker (D7). **Preserve the two hard-won wire facts:** every POST body must be one `jData=<url-encoded JSON>` form field, and orders are REST-only (their WebSocket is receive-only). **"Live verified" requires an actual live order placed through the module's own new path** (confirmed 2026-08-17 — passing the ported test/parity suite only earns "Tested"; the code moved into a new namespace/file boundary, so it does not silently inherit Market Making's existing live-verified status) | Market Making `native/src/shaurya_native.cpp`, `shaurya_kotak_session.cpp` — live-verified | EXE-01 | Not started |
| EXE-03 | Paper broker. **Fill model is EXE-09's queue-reactive/intensity framework, not a touch-fill proxy** (decided 2026-08-17 — touch-fill proxies are retired module-wide; this is exactly the assumption that killed VolArb's crossing-the-spread signal). Output still carries CON-06's **proxy** object-category label regardless — a simulated fill is not realised execution however good the model | Market Making `native/src/shaurya_paper.cpp` (superseded — see EXE-09) | EXE-01, EXE-09, CON-06 | Not started |
| EXE-04 | Order-lifecycle state machine: partial fill, cancel race, late fill after cancel, rejection, forced residual exit | Market Making `native/src/shaurya_runtime.cpp` (tested) | EXE-01 | Not started |
| EXE-05 | Ledger writer against CON-02, append-only, one file per run | Market Making `native/src/shaurya_ledger.cpp` | CON-02 | Not started |
| EXE-06 | Live-order safety gates: flat-account preflight, explicit confirmation phrase, **one-time per-session authorisation given before starting live order placement — never re-confirmed per individual order, and never scripted/automated** (confirmed 2026-08-17: manual human confirmation once at session start is the permanent default; no unattended live-authorisation path, since this module will eventually gate live orders for multiple strategies, not just Market Making), refusal of paper-only settings in live mode | Market Making `shaurya_native_cli.cpp` (`--enable-live-orders`) | EXE-04 | Not started |
| EXE-07 | Dhan order placement | `Shoshin/src/live_trader.py` | — | **Dropped 2026-08-17** — see D7. Kotak is the sole order-placement broker; Dhan is data-only. |
| EXE-08 | Kite order placement | `VOLARB/voltaire/src/{auth/kite_auth,data/kite_client}.py`, `VOLARB/voltaire/src/execution/order_manager.py` | — | **Dropped 2026-08-17** — see D7. Kotak is the sole order-placement broker; Kite is out of scope. |
| EXE-09 | **Queue-reactive / intensity-based fill model** — Huang, Lehalle & Rosenbaum's Q-conditioned queue-reactive framework ("Simulating and Analyzing Order Book Data: The Queue-Reactive Model"): order arrival/cancellation/fill modelled as intensities conditioned on queue state, not a naive touch-fill assumption. **Shared machinery, built once — consumed by both EXE-03 (paper broker) and BKT-03 (backtest execution realism), not reimplemented twice** (decided 2026-08-17 — a touch-fill proxy is retired module-wide; this is the standard rigorous alternative) | New | CON-01, CON-06 | Not started |
| EXE-10 | **Bounded queue-ahead estimator** (added 2026-08-17; corrected by `D23`). `EXE-09` is Q-conditioned. At order acceptance own queue-ahead equals displayed quantity exactly; subsequent trades at that price reduce it from the front, while aggregate cancellations yield hard lower/upper bounds because cancellation position is unknown. Estimate the path from level size, per-level order counts and observed trades, report bound width and an explicit cancellation-model point estimate, and propagate all bounds into every `EXE-09` fill. Individual order identity/rank and hidden quantity remain unidentified. Output carries `CON-06` category **estimated, with reported bounds**, never an unqualified proxy | New | EXE-09, SIG-07, CON-06 | Not started |

### SIG — Signal research & validation

**Created 2026-08-17 by voice (D10).** Sits between `DAT` and `BKT`, upstream of every strategy.
Its output artifact is the `CON-09` opportunity/finding record. **The full validation harness is
in scope now, not deferred** — Aryan's explicit call, same override pattern as `VOL`.

**Architectural note — coverage is recomputable only to the extent the tape is retained.**
`DAT-05` stores the *tape*, not features, so in principle any feature omitted today can be
recomputed tomorrow and the feature list is never an irreversible collection decision. **This
holds only where the tape is actually kept** — Aryan flagged 2026-08-17 that disk space is
limited and that storing only features may be forced. Under a features-only regime the feature
list becomes a forward-only commitment fixed at capture time, and every feature not thought of
before recording starts is permanently unavailable, because no tick-level history exists to fall
back on. This is the single decision that determines whether Q1's coverage argument holds.
Tracked as `DAT-09`. Separately and unconditionally, `SIG-07` applies: information the feed never
carried cannot be recovered at any later date, at any storage budget.

**Q2 resolved 2026-08-17 (D11):** selection pipeline and the black-box-as-yardstick division of
labour are agreed. **Q1 resolved in part:** the taxonomy + residual-gap definition of coverage is
agreed; the retention decision it depends on is open at `DAT-09`.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| SIG-01 | **Feature taxonomy and registry.** Coverage is defined as a property of a taxonomy spanning the book-generating process — static book state, event flow, price-path derived, cross-asset, options-specific, time/regime — not as a list of features. Every feature declares its taxonomy cell, its `CON-07` causal timestamp, and its `CON-06` object category | New | CON-06, CON-07 | **Agreed (D11)** — not started |
| SIG-02 | Feature library — **book state**: spread, mid, micro-price, per-level and cumulative depth imbalance, book slope and curvature, notional within k ticks, order-count vs volume per level, bid/ask asymmetry | New | SIG-01, DAT-05 | Not started |
| SIG-03 | Feature library — **event flow**: signed trade flow, order-flow imbalance at level 1 and multi-level, limit/cancel/market arrival intensities per side per level, cancellation rate, queue depletion rate, trade-size distribution, message intensity | New | SIG-01, DAT-05 | Not started |
| SIG-04 | Feature library — **price-path derived**: multi-horizon returns, realised vol (consumes `VOL-01`/`VOL-02`, not reimplemented), variance ratio, micro-price tilt, effective vs quoted spread, high-frequency Kyle's lambda / Amihud | Partly `VOL-01` | SIG-01, VOL-01 | Not started |
| SIG-05 | Feature library — **cross-asset**: underlying order flow into option quotes, NIFTY↔BANKNIFTY, futures-vs-spot basis and lead-lag. Cont–Cucuringu–Zhang cross-impact | New | SIG-01, CON-05 | Not started |
| SIG-06 | Feature library — **options-specific**: implied-vol level/slope/curvature per expiry, term structure, surface velocity, net dealer gamma/vanna/charm exposure, option order flow mapped into delta space, open-interest change | New | SIG-01, SUR-01, GRK-02 | Not started |
| SIG-07 | **Identification boundary for order-level features, corrected by `D23`.** Unidentified from Dhan: individual order identity/rank, per-order lifetime, cancellation position relative to our order, and hidden/iceberg quantity. **Excluded from that boundary:** own queue-ahead is partially identified — exact at acceptance and bounded thereafter — while queue-conditional arrival/cancel/trade intensities are estimated from price-level deltas and order counts. Carry measured bounds under `CON-06`; never silently manufacture the unidentified objects. **Verified against DhanHQ v2 docs; see §7** | Working contract §7, D23 | SIG-01, CON-06, EXE-10 | **Verified — not started** |
| SIG-20 | **Online-computability requirement.** If `DAT-09` resolves toward feature-only or tiered retention, every feature in `SIG-02`–`SIG-06` must be computable in a single forward streaming pass at capture time, with bounded state. This rules out any feature needing a full-day pass, future information, or a same-day refit, and it must be checked per feature at design time rather than discovered at deployment | New | DAT-09, SIG-01 | Not started — applies to the permanent feature tier regardless of how `DAT-09` sizes the tape |
| SIG-08 | **Target and decision-object register.** Each measurement target names its own estimator family: future mid / efficient-price move → forecast regression; fill probability → censored hazard or `EXE-09` intensity model; adverse selection → markout conditional on fill, consuming `ANL-01`. Under `D30`, these per-quote targets feed the primary **joint quoting-configuration** objective against one central portfolio state; they do not share an estimator and no quote is independently promoted | New | CON-09, ANL-01, D30 | Not started |
| SIG-09 | **Label construction.** Strictly-lagged labels only. Ban labels that are deterministic functions of current-book features — regressing micro-price moves on queue imbalance rediscovers the micro-price definition rather than a signal. Contemporaneous impact measurement and predictive measurement are separate, separately labelled objects | New | SIG-08, CON-07 | Not started |
| SIG-10 | **Redundancy structure before selection.** Hierarchical clustering / PCA on the feature correlation matrix; integrated multi-level OFI as the worked precedent. Importance is computed on clusters, never on individual collinear features — collinearity splits credit and destroys individual importance measures | New | SIG-02, SIG-03 | **Agreed (D11)** — not started |
| SIG-11 | **Inference harness.** HAC / Newey–West with lag ≥ overlap, non-overlapping resampling, stationary block bootstrap. Effective sample size reported next to every t-statistic | New | SIG-09 | Not started |
| SIG-12 | **Multiple-testing control over the entire search grid**, not per feature: Romano–Wolf stepwise or Hansen SPA (both handle dependent tests). Grid size recorded in every `CON-09` record — a finding without its search-space size is uninterpretable | New | SIG-11 | Not started |
| SIG-13 | **Selection method.** Stability selection (regularised fit over subsamples, keep by selection frequency) inside purged and embargoed walk-forward cross-validation; per-cluster selection frequency per window is a required output. Knockoff FDR control as the confirmation layer for the surviving set | New | SIG-10, SIG-11 | **Agreed (D11)** — not started |
| SIG-14 | **Contemporaneous vs predictive decomposition:** Hasbrouck VAR on (order flow, quote revision) — impulse response, permanent vs transitory impact. Formally separates "moves with price" from "leads price" | New | SIG-09 | Not started |
| SIG-15 | **Out-of-sample forecast evaluation:** OOS R² against a no-change benchmark (Campbell–Thompson), Diebold–Mariano / Giacomini–White for comparisons, Hansen Model Confidence Set to report the *set* of indistinguishable candidates instead of selecting an argmax | New | SIG-13 | **Agreed (D11)** — not started |
| SIG-16 | **Regime conditioning.** Every result reported conditional on `VOL-04`'s HMM regime. Sign instability across regimes downgrades a finding from signal to regime indicator | New | VOL-04, SIG-15 | Not started |
| SIG-17 | **Configuration-level economic-significance gate (`D21`, `D30`).** Expected maker spread capture across the joint quote set must clear adverse selection, side-specific taxes, fees, passive-flattening loss, portfolio-risk charge and residual futures-breach cost under `EXE-09`, reported per unit of peak margin. The taker half-spread hurdle is inapplicable because Shaurya does not cross. No single quote is promoted independently of the configuration that carries its inventory | New | SIG-15, EXE-09, BK-14/H1 | Not started |
| SIG-18 | **Coverage completeness test.** Measure the out-of-sample gap between a model on the raw level-by-level book state and a model on the engineered feature set; the gap is how much information the features leave on the table. Plus residual diagnostics against time-of-day, regime and raw book slices. An unexplained gap opens a ticket for a missing feature rather than being absorbed | New | SIG-01, SIG-15 | **Agreed (D11)** — not started; unblocked by D12, golden-set curation still sized at `DAT-09` |
| SIG-19 | **Trial log.** Every configuration tested is recorded, and performance is reported as a distribution (combinatorially purged CV, deflated Sharpe) rather than a single out-of-sample number | New | SIG-13 | Not started |
| SIG-21 | **Deep-book anomaly → future-price response (`H-SIG21`).** Test whether rare disturbances in the normally quiet far depth200 ladder forecast later NIFTY-futures mid-price movement. The event definition must be **price-keyed, causal and pre-registered before outcomes are inspected**: additions, removals, displayed-liquidity relocation **proxies**, displayed-quantity shocks and order-count shocks are separated; mechanical level-index cascades and whole-ladder window slides are excluded; unusualness is measured against a past-only baseline conditional on side, distance from the same-side best quote, time of day and liquidity/regime. **Under D32, depth200 is the exclusive anomaly/treatment source; depth20 supplies only Y and near-book controls.** Outcomes are future depth20/BBO mid-price returns at the registered `D27`-admissible gaps and horizons; contemporaneous response is reported separately from predictive response. Use non-overlapping event clusters or dependence-robust inference, matched quiet controls, explicit effective sample size and one `SIG-12` family across every inspected axis. Report the full response distribution, sign, peak timing and reversion — not merely significance. **The two 11-minute `DAT-20` runs are feasibility evidence only and cannot establish predictability.** The discovery sample may establish two-sided informativeness but cannot confirm a newly discovered directional sign; any directional promotion requires a new registration and later held-out tape. | New; motivated by D28 and enabled by DAT-20 | DAT-05, DAT-10, DAT-20, SIG-01/02/04/09/11/12/14/19, D20, D22, D27, D28, D31, D32 | **In progress — registration/construction commit pushed and verified (`f2cf6501`); construction Dry-run verified outcome-blind on both DAT-20 tapes; synthetic response/matching/power/inference/trial-log pipeline Tested; SIG-21 calibration capture profile enforces depth200 source + depth20 measurement support; outcome gate CLOSED pending five new calibration sessions and a pushed numeric power artifact, then 20 later evaluation sessions** |

### RSK — Risk

**Resolved 2026-08-17 by voice (D13).** Three governing calls: the binding gate is a single C++
choke point on the order path with Python explicitly non-authoritative; limits aggregate at
**account level across strategies**, not per strategy; and margin is carried as two distinct
objects — broker-reported (observed, authoritative live) and modelled (estimated, for sizing,
backtesting and research), never the second overriding the first.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| RSK-01 | Reconcile the two risk managers into one. Note the reconciled Python result is the **research/backtest** implementation, not the live gate — see `RSK-03` | `VOLARB/voltaire/src/risk/risk_manager.py` and `Still_Water/src/engine/risk_manager.py` | — | Not started |
| RSK-02 | Position sizing. Sizes against `RSK-08`'s modelled margin, never against `RSK-04`'s broker-reported figure, since the broker number is only available after the fact | `VOLARB/voltaire/src/risk/position_sizing.py` | RSK-01, RSK-08 | Not started |
| RSK-03 | **Limit framework — per-instrument, portfolio-Greek, max daily loss — checked pre-trade, not reported post-hoc. The binding gate is implemented in C++ on the order path** (decided 2026-08-17): a single choke point every order must pass, because a check living anywhere else is bypassed by the first code path that forgets to call it. Python holds the same limit *definitions* from `CON-04` config for research and backtesting but is **explicitly non-authoritative** | New | RSK-01, CON-04, NAT-02 | Not started |
| RSK-04 | **Broker-reported margin — the authoritative live number.** Read from Kotak, carried with `CON-06` category **observed**, and used for live pre-trade gating. **Never overridden by `RSK-08`'s model** (decided 2026-08-17) | Market Making Kotak REST gateway | RSK-01, CON-06 | Not started |
| RSK-05 | **Kill switch** (decided 2026-08-17, split out of the old `RSK-03`). **Trigger set includes data-quality and connectivity events, not only P&L** — stale surface (`SUR-07`), feed disconnect, sequence gap (`DAT-06`), order-reject spike, latency blowout, margin breach, max daily loss. **Tiered response:** (a) stop quoting and (b) cancel resting orders are **automatic**; (c) flatten positions **requires human authorisation**, on the same reasoning as `EXE-06` — flattening into a disordered book is how a risk event becomes a loss event. **Re-arm is manual only**, never automatic after a cooldown: an auto-re-arming kill switch in a quoting loop can oscillate and do more damage than whatever tripped it | New | RSK-03, DAT-06, SUR-07 | Not started |
| RSK-06 | **Account-level risk aggregator across strategies** (decided 2026-08-17). Margin, daily loss and portfolio Greeks are properties of the account, not of a strategy — two strategies each individually within limits can breach jointly. **Accepted tension with D5:** this is the one place the module holds cross-strategy state, which sits closest to the one-way dependency rule. Raised, decided, not to be re-litigated — but the aggregator must key on account and position, never on strategy identity, so no strategy-specific branch enters the module | New | RSK-03 | Not started |
| RSK-07 | **Python↔C++ risk parity suite.** Proves the non-authoritative Python implementation and the binding C++ gate agree on every limit decision. Same pattern and precedent as `NAT-06`'s 8,640-combination sweep | Market Making parity sweep (commit `4b8f293`) | RSK-03, NAT-06 | Not started |
| RSK-08 | **Modelled margin — SPAN-style span/exposure for F&O, plus ELM and additional margins.** Carried with `CON-06` category **estimated**/**scenario**. Enables ex-ante sizing (`RSK-02`), margin-constrained backtesting, and funding-constraint counterfactuals — none of which `RSK-04` can support, since a broker number cannot be backtested. **Validated against `RSK-04`'s observed margin rather than assumed correct**, and re-validated when NSE changes parameters, since the model drifts | New | RSK-04, CON-06 | Not started |

### BKT — Backtesting

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
**Resolved 2026-08-17 by voice (D14), amended by `D23`.** The `BKT-03` → `EXE-09` forward
reference is **confirmed**. `EXE-09` is Q-conditioned, so the bounded own-queue-ahead estimator
(`EXE-10`) is a prerequisite; its measured bounds propagate into replay. Individual anonymous
order rank remains unidentified. The
authoritative backtester is `NAT-07`'s C++ replay, with a Python event loop kept for research
speed and a parity suite between them. Decision latency is injected from measurement; own-order
market impact is declared rather than modelled.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| BKT-01 | Reconcile the two backtest engines into one. The reconciled Python result is the **research-speed, non-authoritative** engine — see `BKT-02` | `VOLARB/voltaire/src/backtesting/engine.py` and `Shoshin/src/backtest.py` (23K) | — | Not started |
| BKT-02 | Event-driven backtester that consumes **the same tape format as live** (CON-01). Different data paths for research and live is how backtests end up lying. **Sharing a format is not sharing code** (decided 2026-08-17): `NAT-07`'s C++ deterministic replay is the **authoritative** backtester, the Python event loop exists for research iteration speed only, and anything promoted past exploratory must be reproduced in the C++ replay before it counts | BKT-01, DAT-05 | CON-01, NAT-07 | Not started |
| BKT-03 | **Execution-realism layer:** queue position, spread crossing, latency, slippage. Not optional — VolArb's crossing-the-spread butterfly signal was killed by exactly this. **Consumes `EXE-09`'s queue-reactive/intensity fill model rather than reimplementing execution realism — confirmed 2026-08-17 in BKT's own round**, together with the `EXE-10` consequence below | `VOLARB` review packet | BKT-02, EXE-09, EXE-10 | Not started |
| BKT-04 | Walk-forward / out-of-sample harness with honest labelling of exploratory vs identification-grade results | `Still_Water/production_engine/models/*walkforward_metrics.json` | BKT-02 | Not started |
| BKT-05 | **Python↔C++ backtest parity suite.** The Python engine and `NAT-07`'s C++ replay must produce identical fills and ledger rows from the same tape. Same pattern as `NAT-06` and `RSK-07` — an authoritative implementation, a non-authoritative research one, and a proof they agree | Market Making parity sweep (commit `4b8f293`) | BKT-02, NAT-07 | Not started |
| BKT-06 | **Decision-latency injection.** Replay must apply the real decision-to-exchange delay, **measured from live runs, never assumed**, or the backtest acts on information it could not have had. This is `CON-07`'s causality rule applied to replay, and it is the quietest way a backtest lies | New | BKT-02, CON-07 | Not started |
| BKT-07 | **Own-order market-impact declaration.** In replay a simulated order does not move the recorded book. **Decision 2026-08-17: do not model it — declare it.** Modelling own-impact faithfully requires a full market simulator and is out of scope; Aryan's expected order sizes are small enough that the zero-impact assumption is reasonable. Every backtest result therefore carries an explicit "no own-impact" flag plus a size threshold above which the result is labelled unreliable. The failure mode is not the assumption, it is the assumption going unstated | New | BKT-02, CON-06 | Not started |

### ANL — Analytics & reporting

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| ANL-01 | **P&L attribution and markout analysis — built once here, consumed twice** (decided 2026-08-17). Markout is fundamentally a ledger-derived measurement off `CON-02`, so it lives in `ANL` and `SIG-08` consumes it for adverse-selection measurement rather than reimplementing it — same pattern as `EXE-09`. **P&L must be decomposed, not reported gross:** delta, gamma, vega and theta P&L, spread capture, adverse selection, and fees. An undecomposed number says you made money without saying whether you were paid for liquidity or run over | Market Making `monday_v1/live_pnl_stats.py`, `replay_cumulative_pnl.py`, `analysis-runs/` | CON-02, GRK-02 | Not started |
| ANL-02 | Reporting: per-run summary, per-day summary | `Shoshin/src/{report,analysis}.py`, `Market Making/analyze_day.py` | ANL-01 | Not started |
| ANL-03 | Dashboard and read-only server, including real-time surface visualization (D19 — watching only, on `SUR`'s existing fit/smoothing cadence, no latency-engineered fit path) | Market Making `monday_v1/{surface_dashboard,surface_server}.py`, `Still_Water/dashboard/` | CON-03 | **Live verified 2026-08-19 for the live surface dashboard only.** Served at `http://127.0.0.1:8765/` (`GET /`, `/api/state`, `/api/history`; no write method implemented), driven first by DAT-05 replay and then by one live Dhan Quote/Full connection: 116 snapshots over 11:27–11:37 IST on 452 NIFTY instruments, 116/116 fits converged, 0 reconnects, feed age p50 4.7 ms / p95 30.8 ms, fit duration p50 0.159 s, `SUR-05` butterfly and calendar passing on all 116. Shows `SUR-07` surface age and staleness, feed age, packet rate, reconnect count and last-update wall clock; a 45 s post-stream window rendered the dead feed unmistakably (status DEAD, 0 packets/s, three named threshold breaches) while the last good surface stayed on screen. Session-long latency traces and a history slider are present; the forward source is chosen per expiry (traded future, else put-call parity) and labelled under §7.1. Scope is the surface dashboard alone — **the ANL-01/ANL-02 P&L, markout and reporting views this row also covers are not built**, and the dashboard has no live reconnect, no observed arbitrage violation, and no non-NIFTY or afternoon coverage. Also measured the Quote/Full instrument ceiling empirically: 402, 1,203, 3,003 and 5,538 instruments on one socket, all covered, so the ceiling is a lower bound of 5,538 rather than the documented 5,000. **Continuing run, started 2026-08-19 12:04 IST on Aryan's instruction to "keep seeing the feed for the rest of the day":** same 452-instrument NIFTY configuration, `--serve-seconds 13200 --post-stream-seconds 900`, so it serves to approximately 15:47 IST and renders the post-close feed death. This run supplies exactly the coverage the 11:27–11:37 window lacked — an afternoon session and a real close — and its tape lands in `data/live-captures/anl03-live/`. Evidence: `docs/live-evidence/ANL-03-2026-08-19.md` |
| ANL-04 | Notifications and alerts | `Shoshin/src/notifier.py`, `Still_Water/src/engine/notifications.py` | — | Not started |
| ANL-05 | **Dashboard visual design.** Raised by Aryan 2026-08-19 ~12:24 IST after watching `ANL-03` run live: "the aesthetics of the dashboard we need to work on" — explicitly filed as **minor but worthy**, and explicitly deferred to the evening session, not done reactively. Scope is presentation only: layout, typography, colour, panel hierarchy, legibility of the health strip, and how the 3D surface reads at a glance. **It must not change what is measured, what is displayed as a number, or any threshold** — `ANL-03`'s staleness thresholds, object labels, arbitrage banner and forward-source table are specification, not decoration, and a redesign that quietly drops one is a specification change requiring approval. Aryan's standing visual taste applies: muted slate, olive/sage, copper/brass, brick, ivory, charcoal, soft borders — no bright AI-looking palettes. The `dataviz` guidance on categorical palettes, stat tiles and dark/light parity is the reference | `ANL-03`'s `src/shaurya/analytics/dashboard.py` (payload + HTML/JS shell) | ANL-03 | **Not started — scheduled for the evening session of 2026-08-19** |

### NAT — Native live engine

The most valuable existing asset. Generalise; do not rewrite.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| NAT-01 | Extract `native/` into the module namespace, stripping Market-Making-specific assumptions | Market Making `native/` (91 passing tests) | INF-03 | Not started |
| NAT-02 | Strategy-agnostic quoting loop: the runtime calls a strategy interface rather than embedding one strategy's logic | Market Making `native/src/shaurya_runtime.cpp` | NAT-01 | Not started |
| NAT-03 | **Wire the Kotak broker adapter into a real live loop.** The adapter exists and the gateway is broker-verified, but they are not connected — `shaurya_live` is paper-only by design today. This is the single concrete blocker between the C++ engine and a live order. **Done in the module only, never in Market Making first** (decided 2026-08-17): building the live path twice would create a second live-order route that `MIG-01` then has to retire, which is the opposite of D5. Market Making gains live capability by consuming the module. **Accepted consequence, recorded deliberately:** live order placement now sits behind `INF` → `CON` → `NAT-01/02` → `NAT-03`, so the 2026-08-16 intention of having the strategy live by 09:15 Monday is superseded. Aryan chose reusability over the near date, with the trade stated | Market Making `native/src/shaurya_kotak_broker_adapter.cpp`, `shaurya_live_cli.cpp` | NAT-02, EXE-01 | Not started |
| NAT-04 | Live order-status and fill polling, plus cancellation-race handling against the real broker | New | NAT-03 | Not started |
| NAT-05 | Broker-report-derived flat-position preflight (today the CLI requires manually supplied counts) | New | NAT-03 | Not started |
| NAT-06 | Python↔C++ numeric parity suite. Precedent: the 8,640-combination price/quantity sweep already run in Market Making, exact agreement | Market Making parity sweep (commit `4b8f293`) | NAT-02 | Not started |
| NAT-07 | Deterministic replay in C++ (the `VAL-07` gap, never implemented in Market Making) | — | NAT-02, DAT-05 | Not started |
| NAT-08 | Failure and alert semantics: distinguish expected exit, unexpected death, completed task, stopped component (the `OPS-04` gap) | — | NAT-02 | Not started |
| NAT-09 | Deployment: EC2 runbook, systemd unit, source-only deploy, remote verification | Market Making `AWS_DEPLOYMENT.md`, `deployment/`, `Still_Water/production_engine/deploy/` | NAT-01 | Not started |

### MIG — Migration

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| MIG-01 | Refactor **Market Making** to consume the module (D5). Method is fixed: work strictly behind the existing test suites (91 C++, 144 Python), require green before **and** after, and never change behaviour in the same commit as a refactor. This is the only engine with a broker-verified path — it does not get destabilised | — | NAT-02 | Not started |
| MIG-02 | Migrate VOLARB — recommended as the *first* migration since most harvested Python came from it, so it is the real test of whether the abstractions hold | — | O5 | Blocked |
| MIG-03 | Decide the fate of Mushin_Gamma, Seshin_Zen, Shoshin, Still_Water, openclaw_zen: migrate or freeze as history | — | O5 | Blocked |

---

## 4. Suggested build order

Not authorised, and subject to the D3 discussion. Recorded so the dependency logic is visible.

1. **CON first.** Contracts are the cheapest thing to get right early and the most expensive to
   change late. Everything in both languages depends on them.
2. **INF alongside CON.** Repo, packaging, test harness, secret policy.
3. **SUR + GRK + VOL.** Mostly harvest from VOLARB. Highest ratio of value to effort, and no
   dependency on broker decisions.
4. **DAT.** Reconcile Dhan, build tape and replay. Unlocks honest backtesting.
5. **SIG.** Needs DAT-05's tape to compute features off, and feeds BKT the candidate signals worth
   backtesting. Placed before BKT deliberately: under D8 there is nothing to backtest until the
   data has shown something.
6. **BKT.** Only meaningful once DAT-05 gives it the same tape live will use.
7. **NAT.** Generalise the C++ engine. Depends on EXE-01, which depends on O4.
8. **RSK + ANL.** Continuous — these grow alongside everything else.
9. **MIG.** Last, one strategy at a time.

---

## 5. Standing security item

Credential-shaped files currently sit **inside** project trees and would be captured by any
repo or sync covering them. Contents have not been read or copied.

- `Dhandho/.env`
- `Dhandho/strategy/VOLARB/voltaire/config/` — `.access_token`, `.encryption_key`,
  `credentials.yaml`, `credentials_local.yaml`
- `Dhandho/strategy/Still_Water/production_engine/.env` and `keys/`
- `Dhandho/strategy/Seshin_Zen/production_engine/.env`
- `My Drive/Market Making/dhan_credentials.env`

Tracked as INF-06. Market Making already solves this correctly by keeping secrets outside the
tree at `700`/`600`; the module adopts that pattern from day one (INF-05).

---

## 6. Current state

| | |
|---|---|
| Design note | Written — `README.md` |
| Task ledger | Written — this file |
| Decisions | D1–D32 taken. **D3 satisfied — component list agreed.** O1, O2, O3, O4, O6 resolved. **O5 still open (deliberately deferred). `DAT-09`'s packet-rate, 20-level exact ceiling (50), reconnect scope, retention, and 200-level skew/throttle inputs are measured as of 2026-08-19. Exact strike-band/universe-to-socket sizing remains a separate owner decision; the exact 200-level instrument-count cap remains unmeasured.** D16–D18 (2026-08-18) closed the three findings from that day's decision-completeness audit: `VOL-02`'s data-source note corrected, Kite dropped from `CON-05`, Kotak dropped as a data source (`DAT-08` dropped). D19 fixed the live-surface dashboard as watching-only; D20–D24 govern empirical SIG axes, maker-only scope, claim-ledger debate, queue bounds, and capture-time trade signing. **D25–D26 put `EXE` into the build order and pre-registered the ₹21 premium-regime split; D27 binds strategy speed to the slowest consumed feed; D28 makes the normally quiet far depth200 tail a pre-registered anomaly-monitoring object; D29 makes hypothesis resolution scale and power binding across cells; D30 approves the joint quoting configuration as the primary maker decision object; D31 activates SIG-21 and makes its pushed registration commit a hard outcome gate; D32 locks depth200 as SIG-21's treatment source and depth20 as response/control measurement only.** `D23`'s packet-rate premise is amended by `DAT-16`. |
| Renames | Done and verified — GitHub `→ Market-Making`, Drive `→ Valour` |
| Component list | **Agreed and frozen 2026-08-17 (D15). 13 components: INF, CON, SUR, GRK, VOL, DAT, EXE, SIG, RSK, BKT, ANL, NAT, MIG.** |
| `MODULE_SPEC.md` | **Drafted 2026-08-18; extended through D32 on 2026-08-19** — root index plus 13 per-component specifications under `docs/module-spec/`; all non-dropped task IDs map to stable `REQ-*` rows with code/test/output targets. `SIG.md` binds D29's hypothesis-resolution method, D30's joint configuration estimand, D31's SIG-21 registration gate and D32's depth200/depth20 role separation; dropped `DAT-08`/`EXE-07/08` intentionally have no requirement |
| Repository | **Created 2026-08-17** — private `ayyararyan/Shaurya`; canonical design artifacts pushed on `main` |
| Code harvested | Dhan clients reconciled from Mushin_Gamma + Shoshin; feed patterns generalized from Mushin_Gamma + Still_Water into the standalone `shaurya` package |
| Tasks in progress | DAT-11/12/13 are Live verified; DAT-14/15/16/17/20 are Live verified at their stated scopes. `DAT-20` establishes reliable deep-book observability and quiet-time skips, not rare-event predictability. **`SIG-21` is the active next task under D31–D32: its registration, construction, synthetic downstream pipeline and depth200-only calibration safeguards are tested, while empirical execution remains gated on five new calibration sessions, a pushed numeric power artifact and 20 later evaluation sessions. No future-price result exists.** The `PP` / `SIG-04` debate remains open behind it. INF-02/05/07/09 are tested; INF-06 is blocked on exact approved destinations for 8 Drive-hosted files. CON-02/03/04/05/06/07/09 are tested; CON-01/08 and the Dhan slice of CON-05 retain live evidence. DAT-03/04/07 are tested; DAT-05/06 are dry-run verified; DAT-08 is dropped; DAT-09 planning/pooling is tested with the final strike-band/connection-count owner choice still open |

### SIG-21 active phase checklist

- [x] Push and remotely verify the immutable `H-SIG21` registration.
- [x] Build and dry-run the outcome-blind depth200 candidate detector.
- [x] Build and test the synthetic response, control, power, inference and trial-log pipeline.
- [x] Lock D32 channel roles and enforce them in the calibration capture profile.
- [ ] Capture calibration sessions 1–5 as separate complete post-registration sessions.
- [ ] Write, push and remotely verify the complete pre-outcome 384-cell power artifact.
- [ ] Capture and analyse 20 later full evaluation sessions for adequately powered cells only.
- [ ] If the discovery sample selects a direction/horizon, register `H-SIG21C-*` before any
  confirmation tape.

**Stop rules:** a missing/partial depth200 source, disabled depth20 measurement support, incomplete
session, failed power gate, accidental outcome inspection, or any attempt to alter the registered
grid after viewing responses stops the affected stage. **Out of scope:** using depth20 as the
anomaly source, reusing DAT-20 outcomes, or treating calibration as a predictive result.

**Immediate next action (D31–D32):** run the enforced `--sig21-calibration` profile for the same
NIFTY front-month future across depth200 and depth20 for five full sessions. Depth200 is the only
candidate/anomaly source; depth20 is retained only for later response and near-book controls. Do
not run response labels or alter the registered 384-cell grid during calibration. After session
five, use only unconditional calibration quantities to create the complete power artifact, push
it, and verify the remote hash before any outcome join. If the numeric gates pass, collect 20
subsequent full evaluation sessions. The retained `DAT-20` tapes remain permanently excluded from
SIG-21 future-return inference. Runbook: `docs/SIG-21-CALIBRATION-RUNBOOK.md`.

**O4 is resolved (D7) — `EXE` is unblocked.** `EXE-07` and `EXE-08` are dropped; `EXE-01`
through `EXE-06` can proceed once `CON` lands. **O5 remains open by design** — `MIG` stays
blocked until each old strategy is decided individually, when it is next touched.

### 6.1 Work log

- **2026-08-19 — D32 locked SIG-21's channel roles before Aryan's reset.** The depth200 ladder is
  the exclusive candidate/anomaly source; depth20 remains only the future-midpoint and near-book
  control surface. Added an enforced `--sig21-calibration` capture profile with protocol metadata,
  full-session duration, depth200-present and depth20-present gates; added a regression proving
  depth20 states cannot enter the anomaly detector; and wrote
  `docs/SIG-21-CALIBRATION-RUNBOOK.md`. Five new focused tests pass and the complete 197-test suite,
  Ruff and strict mypy pass. The registered 384-cell family is unchanged; calibration may estimate
  support and power but may not select a new grid.

- **2026-08-19 — D31 post-registration synthetic pipeline implemented and tested.** After remote
  verification of `f2cf65011d02882191b5cfda566c1024119964d7`, delegated implementation added
  strict as-of depth20 midpoint labels for the registered `Z x h2` grid, separate
  contemporaneous/predictive legs, 11-second episode clustering, primary overlap exclusion,
  outcome-blind quiet-control matching, the exact 384-cell manifest, unconditional-calibration
  power calculations and support gates, HAC/Newey-West, within-session stationary bootstrap,
  Romano-Wolf step-down, directional-promotion protection, and immutable create-once `SIG-19`
  JSONL output. Twenty-eight focused tests and the complete 192-test Python suite pass; Ruff and strict
  mypy pass. `docs/live-evidence/SIG-21-PIPELINE-2026-08-19.md` records the scope and limitations.
  **No real tape, response outcome, numeric power artifact or predictive result was produced.**

- **2026-08-19 — D31 activated SIG-21 top-down; registration and outcome-blind construction
  completed locally.** Updated `TASKS.md`, `MODULE_SPEC.md` and `docs/module-spec/SIG.md` first;
  added `docs/sig-claims/H-SIG21.md`; then implemented
  `src/shaurya/signals/deep_book_anomaly.py`. The detector compares price maps rather than level
  indices, separates eight atomic event types, labels displayed-liquidity relocation as a proxy,
  excludes reconnect/quality contamination and near-complete outer-window slides, and carries an
  expanding empirical baseline that cannot learn from the session being scored. Ten focused tests
  and the complete 164-test Python suite pass; Ruff lint and strict mypy pass. Construction-only
  dry run on the two retained DAT-20 tapes produced 23,110 and 17,692 candidate events respectively
  without reading or joining any future-price outcome. Full evidence and limitations are in
  `docs/live-evidence/SIG-21-CONSTRUCTION-2026-08-19.md`. The registration/construction gate was
  subsequently opened by the pushed and remotely verified commit `f2cf6501`; the distinct numeric
  power gate remains closed.

- **2026-08-19 — D28 and SIG-21 opened from the DAT-20 interpretation correction.** Aryan clarified
  that depth200 is not collected primarily to estimate routine fill/cancellation behaviour in the
  far tail. Its research value is the normally quiet baseline: when unusual far-depth activity does
  appear, measure how price responds over future horizons. Recorded the boundary precisely:
  `DAT-20` proves the channel is reliable enough to observe those events; it does not prove they are
  large or predictive. `SIG-21` is therefore the next task, with D22 pre-registration, D27 horizon
  admissibility, causal past-only anomaly normalisation, dependence-aware inference and a
  multi-session sample/power gate required before any price-response result is inspected.

- **2026-08-18 — D19, live surface dashboard debate closed.** Aryan's voice thought (queued
  ~16:23 IST in `NEXT_PROMPT.md`, not resolved solo per his instruction) asked whether a live
  surface dashboard implies latency-engineering the surface fit itself. Debated live on
  Telegram: asked directly whether this was about watching or about quoting; Aryan answered
  "It's only about watching, no worries." Recorded as D19 — confirms `ANL-03` already covers
  this at `SUR`'s existing cadence, no new task, no change to `SUR`'s Python-only research-fit
  scope.
- **2026-08-18 — DAT-01 / minimal CON-01, CON-05, CON-08 / DAT-02 / DAT-05-lite.** Built an
  installable Python package; reconciled the two Dhan clients; added versioned tape and
  instrument contracts, permission-restricted run manifests, supervised standard + 20-level
  WebSockets, reconnect/resubscribe, application heartbeat, explicit sequence-gap semantics,
  capture metrics, and an append-only JSONL writer. Verification: 17 pytest tests, strict mypy,
  Ruff, wheel + sdist build, clean-wheel install, staged-master mapping check, and a zero-match
  credential-value scan.
- **Authoritative live evidence:** run `sha-20260818T055709.463701Z-ea8228c8`, test instrument
  NIFTY-Aug2026-FUT (`security_id=58072`), 232 separate 20-level side packets in 30.001 seconds
  (**7.733 parsed rows/s** full capture window; 8.238 rows/s active span), 332 bytes each,
  116 bid + 116 ask, one connection, two successful heartbeats, zero reconnects, zero crossed or
  invalid books. Tape: 232 continuous receive sequences, SHA-256
  `54357820155bbda1ed1ccc214a6ea056d1cb08a2bc9dce3015d408c7629b43b3`. These are raw
  **DAT-09 inputs only, not a publication-event rate or sizing decision**. DAT-16 later showed
  that these are ~4.17 same-timestamp rows per fixed 500 ms snapshot. Four earlier diagnostic runs
  remain preserved and explicitly invalidated after acceptance/lifecycle/measurement defects
  were found and fixed.
- **Live blocker (resolved same day):** the staged Dhan JWT expired 2026-08-12. The 20-level
  endpoint still served data, but the standard tick/5-level endpoint closed code 1006
  immediately after subscription; therefore the full DAT-02 live claim was withheld pending a
  refreshed token.
- **2026-08-18, later — token refresh and full DAT-02 live verification.** Aryan supplied a
  fresh Dhan JWT; the credential file at `Market Making/dhan_credentials.env` (both the local
  staged cache and the Drive canonical copy) was updated in place, mode kept at 600, value
  never echoed to any log or committed file. The Drive-staged `Shoshin/security_id_list.csv`
  master turned out to be stale (no NSE row for `security_id 58072`); the run instead pulled
  Dhan's own live public compact master (`https://images.dhan.co/api-data/api-scrip-master.csv`,
  the same source `dhanhq`'s SDK points at) into `data/api-scrip-master.csv` (gitignored, not
  committed — it's a same-day public reference file, not a secret). That confirmed
  `security_id 58072` → `NIFTY-Aug2026-FUT`, NSE FNO, expiry 2026-08-25, matching the earlier
  run exactly.
  - Rerun: `shaurya-dhan-capture` with both channels enabled (no `--no-standard`/`--no-depth20`),
    45s duration. Result: `status: completed`, `acceptance.missing_channels: []` for both
    required channels, 1 connection each, 4/4 heartbeats OK on each channel, zero reconnect
    attempts, zero reconnect errors. 419 total rows (depth20: 362 source packets/86 ws messages;
    standard: 57 source packets/57 ws messages). Combined rate 9.31 packets/s
    (depth20 8.04/s, standard 1.27/s over the same 45s window). Standard message sizes ranged
    12–162 bytes (mixed packet subtypes: ticker/quote/full/depth5/open-interest all arrived in
    one window); depth20 stayed flat at 332 bytes as before.
  - **Quality counters, checked against source, not just reported:** `source_sequence_unavailable`
    was 419/419 (100%) — verified in `dhan_stream.py`'s `SequenceGapDetector` docstring and code:
    "Current Dhan v2 packet layouts expose no source sequence" on any channel, so this is the
    protocol's actual shape, not a parser defect; gap detection instead relies on reconnect
    boundaries and the tape writer's own receive-side sequence (which stayed continuous).
    `exchange_timestamp_missing` (363/419) is the same story at the packet level: only ticker,
    quote and full packets (response codes 2/4/8) carry an exchange timestamp field at all in
    Dhan's wire format — depth5/depth20/open-interest/previous-close/market-status packets
    structurally don't, confirmed by reading `parse_standard_packet`/`parse_deep_packets`
    directly. `crossed_book: 1` and `partial_book: 2` are small, live-market-plausible counts
    (e.g. a book snapshot caught mid-update just after connect), not repeated/systemic. All
    17 existing tests still pass unchanged.
  - Pytest run: `17 passed` after the rerun, unchanged from the DAT-01/DAT-02 build itself —
    confirms the token/master-file change didn't touch or break any tested code path.
  - **DAT-09 evidence, still not a decision:** two independent live measurements now exist for
    one instrument — 20-level alone (7.7–8.2 packets/s, 332 B/packet) and standard+20-level
    together (9.3 packets/s combined, standard adds ~1.3 packets/s at 12–162 B/packet,
    variable by subtype). Sizing, universe and retention are still Aryan's call.
- **2026-08-18, later still — DAT-10 (200-level deep book) built and live-verified.**
  Aryan asked to check the 200-level tier specifically (one instrument per subscription,
  full depth on that instrument) while the market was still open. Extended `dhan_stream.py`
  generically rather than writing a separate module: `parse_deep_packets` already accepted a
  `depth_levels` parameter, so 20-level and 200-level share one parser (identical wire format
  per TASKS.md §7.1 — only the endpoint URL, subscription batching, and depth cap differ).
  Added `DhanStreamConfig.enable_200_level_depth`, the `DEPTH200_URL` endpoint, a single-
  instrument guard in `run()` (raises if more than one instrument is passed with 200-level
  enabled, matching the documented batching rule), and re-keyed the in-memory book cache by
  `(channel, segment, security_id)` instead of `(segment, security_id)` so depth20 and
  depth200 can run on the same instrument simultaneously without one reconnect clearing the
  other's book — required for DAT-09's proposed design of running both tiers on the traded
  instrument at once. CLI got an opt-in `--enable-depth200` flag.
  - **Bug found and fixed before it produced misleading evidence:** the first live attempt
    connected cleanly and heartbeat successfully (4/4 ok) but received **zero data packets**
    for the full 45-second window — not a crash, just silent data loss, the kind of failure
    that's easy to miss if you only check "did it connect." Root-caused by reading Dhan's own
    reference client (`dhanhq.fulldepth.FullDepth.subscribe_instruments`, installed in the
    venv): the 200-level endpoint does not use DAT-02's `{RequestCode, InstrumentCount,
    InstrumentList}` batch envelope at all — it wants a flat `{RequestCode, ExchangeSegment,
    SecurityId}` message. Fixed in `_subscribe`, with a regression test
    (`test_depth200_subscribe_uses_flat_message_not_instrument_list`) added so this can't
    silently regress.
  - **Live evidence after the fix**, run `sha-20260818T092355.175225Z-d181b3ff`,
    NIFTY-Aug2026-FUT: **366 packets in 45.001s (8.13 packets/s full window, 8.37/s active
    span), exactly 3,212 bytes per packet** (matches the documented 200-level layout exactly),
    1,175,592 raw bytes total, one connection, 4/4 heartbeats, zero reconnects. Verified
    independently in the written tape file, not just the run summary: the last complete-book
    row carries genuinely **200 bid levels and 200 ask levels**, sane top-of-book
    (`bid 24241.1 × 195 qty` / `ask 24243.9 × 390 qty`, non-crossed). Quality flags
    (`exchange_timestamp_missing`, `source_sequence_unavailable` both 366/366; `partial_book`
    just the first startup row) are the same already-explained protocol characteristics as
    DAT-02, not new defects. All 23 tests pass (22 → 23 with the new regression test), strict
    mypy and Ruff clean.
  - **DAT-09 now has evidence at all three depth tiers on one instrument**: 5-level not yet
    directly measured live (only documented from the spec), 20-level ~7.7–8.4 parsed rows/s at
    332 B, 200-level ~8.1–8.4 packets/s at 3,212 B. This is still raw input, not a sizing
    decision — Aryan's call remains open.
- **2026-08-18, later still — DAT-09 concurrent-connection cap measured live. Major correction
  to `GCP_SCALING.md` §3's working assumption.** Aryan asked to settle this empirically before
  close. Diagnostic script `scripts/dat09_concurrency_probe.py` (not a production path —
  read-only, no orders) subscribed real NIFTY instruments across three independent live tests
  in the closing 25 minutes of today's session:
  1. **206 instruments (204 near-ATM options across two expiries + 2 futures) on one 20-level
     socket**, sent as 5 batched `RequestCode 23` messages (50/50/50/50/6, back-to-back, no
     delay) — the exact pattern DAT-02's existing code already uses. Result: only the **first**
     message's 50 instruments (indices 0–49) ever received a packet (45/50 — the other 5 look
     like genuine illiquidity, not a delivery failure); **every one of the other 156
     instruments across batches 2–5, including both NIFTY futures, received zero packets in
     40 seconds**, despite the socket, connection, and heartbeats staying completely healthy
     (1 connection, 3/3 heartbeats, zero reconnects, zero errors — 10,108 rows still flowed
     from the 45 instruments that did work, so this is not a dead socket).
  2. **Retest, ruling out "those 50 are just illiquid":** the exact 52 instruments from the
     dead batch (including both futures — the most liquid instruments in the whole universe,
     each individually measured earlier today at 8+ packets/s), resubscribed **alone as the
     only/first message** on a fresh socket. Result: 48/52 received data immediately. Proves
     it is not about which instruments — it's about **subscription-message order**.
  3. **Pacing test, ruling out "just needs a delay between messages":** batch 1 (50) + batch 2
     (the same 50 that failed above) sent as two separate messages on one socket with a
     deliberate **1-second pause** between them. Result: batch 1 → 49/50, batch 2 → **0/50,
     unchanged**. Pacing does not fix it.
  - **Conclusion, three-for-three consistent:** for the 20-level endpoint, **only the first
    `RequestCode 23` subscription message sent on a socket ever delivers data** — a second (or
    third, etc.) message on the same already-subscribed socket is accepted (no error, no
    disconnect) but silently produces nothing. The effective concurrent-instrument cap per
    20-level socket is therefore **~50 (one message's worth), not the documented "5,000
    instruments per socket."** `GCP_SCALING.md`'s explicit assumption ("Multiple subscription
    messages can share one socket") is **wrong as tested** and needs correcting before any
    instrument-count/storage math is trusted.
  - **200-level behaves differently, evidence from the same session:** 5 different instruments
    (2 futures + 3 option strikes) sent as 5 separate single-instrument messages, 50ms apart,
    on one 200-level socket — **all 5 received at least one packet**, though volume was
    heavily skewed toward the first (332 packets vs 2 each for the other four in 40s). So
    200-level does accept more than one subscription message per socket, unlike 20-level, but
    whether that skew reflects genuine per-instrument liquidity or a softer throttle on
    later-subscribed instruments is **not yet disentangled** — needs a same-liquidity control
    test (e.g. several front-month futures across indices, not option strikes of unknown
    relative liquidity).
  - **Test 4, run 2026-08-18 ~15:19 IST, closes the debate.** Aryan asked for the recheck
    before market close. Sent all 206 instruments in **one single** `RequestCode 23` message
    on a fresh socket (no batching at all — the exact variant flagged above as untested).
    Result: **0 of 206 received any packet, including both NIFTY futures** — the same
    instruments that reliably produced 300+ packets each in every smaller test today. A
    206-instrument message is rejected wholesale; it is not that "later" instruments in a
    big message get dropped while earlier ones survive — the whole message produced nothing.
  - **Unifying conclusion across all four tests, high confidence (four consistent live
    results, not one):** the 20-level endpoint enforces a **real per-message instrument-count
    ceiling somewhere between 52 (worked, test 2) and 206 (failed outright, test 4)** —
    exact value not pinned down, no time left in today's session to bisect it — **and**
    separately, **only the first subscription message a socket ever receives is honored**;
    a second message sent afterward is silently ignored regardless of its own size or
    pacing (test 1, test 3). Practically these compound to one rule: **a socket gets exactly
    one shot at exactly one subscription message, and that message must stay under roughly
    ~50–100 instruments or it is rejected entirely.**
  - **Debate closed: Dhan's documented "5 connections × 5,000 instruments" is not what the
    20-level feed actually delivers**, at least not through the `RequestCode 23` /
    `InstrumentList` path tested here (four for four consistent results). Covering
    `GCP_SCALING.md`'s proposed ~4,150-instrument 20-level universe needs on the order of
    **50–80+ separate socket connections** (exact number depends on the still-unmeasured
    true per-message ceiling), not the handful the documentation implied. This is a material
    correction to the DAT/GCP infrastructure plan and should be treated as the working
    assumption going forward. Remaining open, for whenever DAT is actually built out: the
    exact per-message ceiling (bisect between 52 and 206), whether a fresh reconnect can be
    used to issue a "second" subscription (i.e. cycling the socket instead of re-sending on
    the same one), and the 200-level skew-vs-throttle question noted above.
- **2026-08-18 — CON-02/03/04/06/07/09.** Built six versioned Python/Pydantic contracts,
  shared exact object-category and IST causality types, four committed cross-language JSON
  fixtures, and field-level documentation. Harvested CON-02 from Market Making
  `monday_v1/ledger.py` plus `native/{include,src}/shaurya_ledger.*`; CON-03/07 from
  `monday_v1/surface_region.py` and `surface_live.py`; CON-04 from Market Making
  `monday_v1/tomorrow.example.json` plus the safely staged Still_Water
  `production_engine/config/runtime_profile.json`; CON-06 from working-contract §7.1; CON-09
  from D8/REQ-CON-09. Verification: **52/52 pytest tests passed**, including explicit
  future-information rejection and four golden-fixture round trips; strict mypy passed all
  **18 source files**; repository-wide Ruff passed. Native config/ledger/surface consumers
  remain forward work under INF-03/NAT/EXE-05, not part of this Python-contract run.
- **2026-08-18 — INF-02/05/06/07/09.** Reconciled 2 packaging references: VOLARB currently
  has 0 `pyproject.toml`/`uv.lock` files and Shoshin's 2 files add pytest/lock metadata but no
  stronger package, lint, or type convention, so Shaurya retained setuptools plus strict mypy
  and Ruff. Verified 1 clean editable install, 1 clean wheel build/install, and 3 matching
  `0.1.0` version sources (`pyproject.toml`, `shaurya.__version__`, `CHANGELOG.md`). Added the
  external-handle/`700`/`600` policy and audited all 9 INF-06 files without reading values:
  8 exist but remain unmoved because 0 exact external destinations are approved; the 1 absent
  Market Making Drive file is already represented by the pre-existing external `dhan.env`
  mirror. Hardened 11 ignore-pattern classes; Shaurya had 0 current/history tracked
  credential/run/log/generated-data paths and 0 strong secret-signature matches, Market Making
  had 0, and the 2 safely staged strategy Git indexes exposed 1 pre-existing Still Water data
  violation (`data/lstm_dataset.parquet`) and 0 Seshin Zen violations. Verification: **54/54
  pytest tests passed**, strict mypy passed all **18 source files**, and repository-wide Ruff
  passed. Release `v0.1.0` records the first installable pre-1.0 foundation.
- **2026-08-19 — DAT component implementation, offline/synthetic session.** Implemented DAT-03
  historical minute/daily bar normalization and immutable gap-audited storage; DAT-04
  option-chain normalization with fail-closed canonical-master identity checks; full DAT-05
  deterministic replay and permanent append-only retention; DAT-06 stale/crossed/invalid/gap
  flagging plus versioned collector-audit output; DAT-07 daily immutable Dhan/Kotak masters and
  same-day mapping indexes; and DAT-09 permanent NSE-index-F&O planning plus safe multi-socket
  20-level orchestration using exactly one message/socket. Extended CON-05 in place for Kotak
  routing identity rather than inventing a DAT-local schema. Replaced the one-off DAT-09 script
  with credential-handle-only DAT-11 binary search, DAT-12 reconnect comparison, and DAT-13
  same-liquidity 200-level control; all live conclusions remain explicitly pending the
  2026-08-19 market-hours session. No credential file was read and no broker connection was
  opened. DAT itself grew the suite from **54/54 to 77/77 passing tests**; after rebasing the
  concurrently completed SUR work, the final merged suite passed **89/89**, strict mypy passed
  all **30 merged source files**, and repository-wide Ruff passed. Read-only DAT-05 replay also
  validated **21,279 rows across four non-empty existing live tapes**; the known invalid
  zero-row tape remains preserved.

---

## 7. What the Dhan feed actually carries

Verified 2026-08-17 against the DhanHQ v2 documentation (`dhanhq.co/docs/v2/live-market-feed/`
and `/annexure/`), because the answer determines `SIG-07`'s identification boundary and the
`DAT-09` storage arithmetic. Recorded here so it is never re-argued from memory.

**Established:**

- Dhan's documentation describes the feed as **tick-by-tick and event-based**. The observed
  20-level endpoint does not match that description: DAT-16 measures a fixed 500 ms snapshot
  clock. Binary packets remain WebSocket/little-endian with an 8-byte header.
- Up to **5 WebSocket connections × 5,000 instruments** each. Instrument count is not a
  binding constraint.
- Four subscription modes (feed request codes): Ticker (15), Quote (17), Full (21), and
  **Full Market Depth (23)** — the last being the 20-level feed.
- The **Full packet is 163 bytes**: trade data, OI, day OHLC, plus a 100-byte depth block =
  **5 levels × 20 bytes**, each level carrying bid qty, ask qty, **number of bid orders**,
  **number of ask orders**, bid price, ask price.

**What this settles about the disagreement:**

- *The documentation claim does not settle observed semantics.* DAT-16 supersedes the earlier
  inference that 20-level delivery is a raw event stream: on two healthy futures tapes it is a
  fixed 500 ms snapshot feed. Whether aggregation occurs at Dhan, upstream, or exchange is
  unidentified.
- *The order-level limit stands, but `D23` narrows it.* There is no order ID anywhere in the
  packet structure. Individual order identity/rank, per-order lifetime, cancellation position
  relative to our order, and hidden quantity remain **unidentified**. Own queue-ahead is a
  different object: exact at acceptance and bounded thereafter from observed trades and
  aggregate level changes — `SIG-07`/`EXE-10`.
- *Partial recovery worth having:* the per-level **order-count** field is more than plain
  level-2 size. Quantity together with order count yields average order size per level, and
  changes in count between ticks bound the number of adds and cancels at that level. That
  recovers a real fraction of what market-by-order would give, and should be treated as a
  first-class feature family in `SIG-02`/`SIG-03` rather than an afterthought.

### 7.1 The deep-book feeds — verified from source

Aryan stated 2026-08-17 that Dhan offers up to 200 depth levels, with per-tier limits on how
many instruments can be subscribed at once. **Confirmed** against `DhanHQ-py`
(`src/dhanhq/fulldepth.py`, `class FullDepth`). The earlier estimate in this file of "roughly
400–500 bytes per 20-level packet" was wrong and is superseded by the measured layout below.

- **Three depth tiers exist, not two:** 5 (the Full packet, §7 above), **20**, and **200**.
  `depth_level` accepts only 20 or 200; anything else raises.
- **Separate endpoints**, distinct from the main market feed:
  20-level → `wss://depth-api-feed.dhan.co/twentydepth`;
  200-level → `wss://full-depth-api.dhan.co/`. Both use request code 23.
- **Bid and ask arrive as separate packets** (response codes 41 and 51) and are joined on
  `security_id`. A complete book update is therefore two packets, not one.
- **Packet layout:** 12-byte header (`<hBBiI` — message length, response code, exchange
  segment, security ID, row count) followed by N levels of **16 bytes** each, format `<dII` =
  price `float64`, quantity `uint32`, **orders `uint32`**.
  → 20-level = 12 + 320 = **332 bytes per side, 664 bytes per book update**.
  → 200-level = 12 + 3,200 = **3,212 bytes per side, 6,424 bytes per book update** at full
  depth; the row count is variable, so thin books cost proportionally less.
- **Order count per level is present at every depth tier** — reinforcing §7's point that this
  is richer than plain level-2 size data.
- **Subscription batching:** 20-level batches **50 instruments** per subscription message;
  200-level sends **one instrument per message**. Multiple messages go over one socket, so this
  establishes the batching rule, *not* a proven cap on concurrent instruments. The real
  concurrent limit per tier must be established empirically — it is a `DAT-09` input.
- **Segment coverage:** the client's exchange map contains only `NSE_EQ` and `NSE_FNO`. Deep
  book is not available for BSE, MCX, or currency.

**Storage consequences, corrected.** Per-day figures assume a 22,500-second session and an
average of 10 book updates per second per instrument — **the update rate is still an
assumption and only `DAT-02` can measure it.** Compression taken at 8× for columnar
delta-encoded data.

| Tier | Universe | Raw/day | Compressed/year |
|---|---|---|---|
| 5-level Full packet (163 B) | ~250 instruments — chain-wide | 9.2 GB | ~290 GB |
| 20-level (664 B/update) | ~45 — index, futures, ATM±10 on front two expiries | 6.7 GB | ~210 GB |
| 20-level (664 B/update) | ~250 — chain-wide | 37.4 GB | ~1.2 TB |
| 200-level (6,424 B/update) | 1 — the traded instrument | 1.4 GB | ~45 GB |

The natural design is therefore **tiered by depth as well as by retention**: 200-level on the
single instrument actually being traded, 20-level on a narrow core, 5-level chain-wide. That
combination is roughly **500 GB/year compressed**, which is a disk, not a data-engineering
programme. Chain-wide 20-level is the one configuration that gets genuinely expensive.
