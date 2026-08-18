# Shaurya — Module Task Ledger

**This file is the single source of truth for the Shaurya module.**
Status lives here and nowhere else. No parallel task lists, no status in chat, no status in
commit messages. If a task is not in this file it is not being worked on.

**Created:** 2026-08-17
**Owner:** Aryan Ayyar
**Location:** `Google Drive/My Drive/Dhandho/shaurya/`

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
| D7 | Broker scope | **Market data:** both **Dhan** (primary — options and order-book data is very rich, consumed live via WebSocket) and **Kotak** must be supported as data-receive sources; the module receives from both. **Order execution:** **Kotak only** — zero brokerage on Kotak's options API makes it the sole order-placement route; Dhan and Kite order placement are not authorised. Order placement must run through a dedicated, latency-sensitive C++ path (reaffirms D4/NAT-03). Resolves O4. |
| D8 | Design philosophy | **Data leads, strategy follows.** The module must let the data reveal an opportunity before a strategy/model is chosen to exploit it — never propose a model first and tune parameters against data until it looks profitable (the classic overfitting trap). Exploratory/diagnostic tooling is **first-class**, not a lesser citizen of `ANL`/`DAT`/`SUR`, and sits upstream of any strategy-specific fitting. Applies across the whole component list, most directly `DAT`, `ANL`, `SUR`, `BKT`. See README §6, rule 7. |
| D9 | GitHub repo name for the module | Delegated to OpenClaw ("take the best decision you want"). **`ayyararyan/Shaurya`** — reclaims the name D1 already assigned to the module. This breaks the redirect from the old `Shaurya` URL to `Market-Making` (set up in the 2026-08-17 rename), but the repo is private with no external dependents, so consistency with D1 outweighs preserving a bookmark only Aryan uses. |
| D10 | Signal research & validation | **A new component `SIG` is added — agreed by voice 2026-08-17.** Three sub-decisions taken together: (a) **new component, not an extension of `ANL`** — `ANL` is post-trade reporting, `SIG` is pre-strategy discovery, and D8 requires exploratory tooling to be first-class rather than a lesser citizen of `ANL`; (b) **the full validation harness is built now, not deferred** — same override pattern as `VOL`, on the same reasoning: this is general-purpose measurement infrastructure, not a strategy-specific model bet ("validation infrastructure needs to be made fully, there is no doubt about it"); (c) **slotted in now**, ahead of the remaining `RSK → BKT → ANL → NAT → MIG` walk, so that `BKT` and `ANL` are debated with `SIG` already on the table. `SIG` is the machinery D8 was missing: until now "data leads, strategy follows" was a stated philosophy whose only producer of `CON-09` records was `VOL-05`. |
| D11 | Coverage, selection, and interpretability | Agreed by voice 2026-08-17, four parts. (a) **Coverage is defined by taxonomy + measured residual gap**, not by enumerating features — `SIG-01` and `SIG-18` proceed. (b) **Selection pipeline agreed:** cluster → stability selection inside purged/embargoed walk-forward → Model Confidence Set → economic gate, with knockoffs as a confirmation layer — `SIG-10`, `SIG-13`, `SIG-15` proceed. (c) **Black-box models are a yardstick only:** they measure how much signal exists (`SIG-18`); anything promoted to a tradeable strategy must be sparse and interpretable. (d) **Two constraints raised by Aryan that the coverage argument must survive:** no tick-level historical data exists anywhere, and disk space is limited — his position is that at most *features* can be stored, which would make the feature list a forward-only, irreversible commitment decided at capture time. **Resolved the same evening by D12 — the tape is recorded; only its sizing remains open at `DAT-09`.** |
| D12 | Record the raw tape | **Decided by voice 2026-08-17: the raw tape gets recorded.** "I agree on your part of the data — we can record it. I will think about what to do about the storage space, but we should record it." This resolves the conflict flagged in D11(d): a features-only regime would have deleted `SIG-18`, the only test capable of demonstrating coverage, so the coverage argument now stands. **Storage sizing and retention tiering remain Aryan's to settle — `DAT-09` narrows from "tape or features" to "which universe, at which depth tier, kept for how long".** Two supporting facts confirmed the same day: the **Dhan Data API subscription is active** (clearing `DAT-02`'s hard prerequisite), and Dhan offers **5, 20 and 200** depth levels rather than 5/20 only — verified in source, see §7. |
| D13 | Risk architecture | **Agreed by voice 2026-08-17, three parts.** (a) **The binding pre-trade risk gate is a single C++ choke point on the order path** (`RSK-03`); Python holds the same limit definitions from `CON-04` for research and backtest but is explicitly non-authoritative, with a parity suite proving agreement (`RSK-07`). Reason: a check that lives anywhere but the choke point is bypassed by the first code path that forgets to call it. (b) **Limits aggregate at account level across strategies** (`RSK-06`), not per strategy — margin, daily loss and portfolio Greeks are properties of the account, and two strategies each within limits can breach jointly. Accepted tension with D5: this is the one place the module holds cross-strategy state; it must key on account and position, never on strategy identity. (c) **Margin is two distinct objects** — broker-reported (`RSK-04`, `CON-06` **observed**, authoritative for live gating, never overridden) and modelled SPAN-style (`RSK-08`, **estimated**/**scenario**, for ex-ante sizing, margin-constrained backtesting and funding-constraint counterfactuals), the model validated against the observed number rather than assumed correct. **Kill switch split out as `RSK-05`:** trip conditions include data-quality and connectivity events, not only P&L; response is tiered with stop-quoting and cancel-resting automatic but flatten requiring human authorisation; re-arm is manual only. |
| D14 | Backtesting architecture | **Agreed by voice 2026-08-17, three parts.** (a) **The `BKT-03` → `EXE-09` forward reference is confirmed** — backtest execution realism consumes the queue-reactive fill model rather than reimplementing it. Consequence accepted: `EXE-09` is Q-conditioned while `SIG-07` makes true queue position unidentified, so **`EXE-10`, a labelled queue-position estimator, is now a prerequisite** and its `estimated`/`proxy` label propagates into every simulated fill. Otherwise the module retires the touch-fill proxy only to replace it with an unlabelled one. (b) **`NAT-07`'s C++ deterministic replay is the authoritative backtester**; the Python event loop exists for research iteration speed and is non-authoritative, with a parity suite (`BKT-05`) proving they agree — sharing a tape *format* is not sharing code. Anything promoted past exploratory must be reproduced in the C++ replay. (c) **Decision latency is injected from measurement, never assumed** (`BKT-06`), applying `CON-07`'s causality rule to replay; **own-order market impact is declared rather than modelled** (`BKT-07`) — Aryan's expected order sizes are small enough that zero own-impact is a reasonable assumption, so every result carries an explicit flag plus a size threshold above which it is labelled unreliable. |
| D15 | Analytics boundary and the live-loop location — **closes D3** | **Agreed by voice 2026-08-17, and with it the component walk is complete.** (a) **Markout and P&L attribution live in `ANL-01`, built once and consumed twice** — `SIG-08` takes markout-conditional-on-fill from `ANL` for adverse-selection measurement rather than reimplementing it, the same pattern as `EXE-09`. `ANL-01`'s P&L must be **decomposed** — delta, gamma, vega, theta, spread capture, adverse selection, fees — never reported gross. (b) **`NAT-03`, the live-loop wiring, happens in the module only, never in Market Making first** — building the live path twice creates a second order route that `MIG-01` then has to retire, the opposite of D5. **Accepted consequence, stated at the time and chosen deliberately:** live order placement now sits behind `INF` → `CON` → `NAT-01/02` → `NAT-03`, so the 2026-08-16 intention of trading live by 09:15 Monday is superseded. Reusability was chosen over the near date. **All twelve original components plus `SIG` are now agreed, so D3 is satisfied and construction may begin.** |
| D16 | Historical tape source for tick-level `VOL` estimators — audit correction | **Confirmed 2026-08-18 by Aryan, resolving a contradiction found in that day's decision-completeness audit.** `DAT-03` genuinely cannot provide tick-level data (bars/coarser only, by its own definition) — so the historical tape `VOL-02`'s kernel/bipower estimators need has to be **built by accumulating `DAT-02`'s live stream, recorded via `DAT-05`**, not sourced from `DAT-03`. `VOL-02`'s task note previously claimed the opposite; corrected below. Testing is gated on enough live tape having accumulated, not on a fixed prerequisite task completing. |
| D17 | Kite — fully dead, including instrument identity | **Confirmed 2026-08-18 by Aryan.** Kite carries no scope anywhere in the module. `CON-05` previously still listed a Kite `instrument_token` mapping as outstanding work — a leftover from before `D7`/`EXE-08` dropped Kite for execution, never scrubbed from `CON-05`. Removed; `CON-05` now scopes to Dhan and Kotak only. |
| D18 | Kotak — data feed dropped, order-placement only | **Decided 2026-08-18 by Aryan, amending `D7`.** The module does not receive Kotak market data. Kotak's role is **order placement only** (place/cancel/modify/status/fills/margin) — never a data-receive source. `DAT-08` (Kotak market-data C++ path) is **dropped** as a direct consequence. This also resolves the audit gap flagged 2026-08-18 about missing Kotak storage sizing: since Kotak was never a data source in the corrected scope, no Kotak-side capture/storage sizing is needed, and the Dhan-only figures already in §7/§7.1 and `DAT-09` were correct by construction, not by oversight. |

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
| INF-02 | Python package skeleton: `pyproject.toml`, `shaurya` package, lint/type config. Must be **installable** — strategies pin a version (D5) | `VOLARB/voltaire`, `Shoshin` (`pyproject.toml`, `uv.lock`) | INF-01 | Not started |
| INF-03 | C++ build skeleton: CMake, `shaurya::` namespace, compiler flags. Must export a **consumable CMake target**, not just build in place (D5) | Market Making `native/` | INF-01 | Not started |
| INF-04 | Test harness both sides: pytest + the C++ test-runner pattern already in use | Market Making `native/src/*_tests.cpp`, `VOLARB/voltaire/tests/` | INF-02, INF-03 | Not started |
| INF-05 | Secret-handling policy: config carries a credential *handle*, never a value; secrets live outside the tree at `700`/`600` | Market Making secrets pattern (`~/Documents/Market-Making-Secrets`) | — | Not started |
| INF-06 | Relocate loose credential files currently sitting inside strategy trees (see §5) | — | INF-05 | Not started |
| INF-07 | `.gitignore` audit: no `.env`, `.pem`, tokens, run state, logs, or data ever tracked | Market Making (already correct) | INF-01 | Not started |
| INF-08 | Resolve the `Shaurya` name collision across GitHub and Drive | — | — | **Done 2026-08-17** — see §1.1 |
| INF-09 | Release discipline: semantic versioning, `CHANGELOG.md`, tagged releases. Required because D5 makes strategies pin a module version | Market Making `MODEL_CHANGELOG.md` | INF-01 | Not started |
| INF-10 | Enforce one-way dependency direction: a CI check that the module never imports from any strategy (D5) | — | INF-04 | Not started |

### CON — Contracts

Do these **first**. Every other component depends on them, and if they move later everything
downstream has to be reworked.

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| CON-01 | Snapshot/tape row schema: BBO, depth, timestamps, quality flags | Market Making `surface_snapshots_<run_id>.csv` schema, `monday_v1/snapshot_tape.py` | — | **Live verified 2026-08-18** — versioned Python contract carried 20-level BBO/depth, receive/exchange timestamps, source/receive sequences, and explicit quality flags in authoritative live run `sha-20260818T055709.463701Z-ea8228c8` |
| CON-02 | Ledger row schema: placement, execution, cancel/reject, cycle P&L, order role, quote price, order age, book state, K, break-even spread, fill price | Market Making master CSV ledger definition, `native/src/shaurya_ledger.cpp` | — | Not started |
| CON-03 | Surface frame schema: parameters, fit diagnostics, surface age, staleness flag | Market Making `monday_v1/surface_region.py` | — | Not started |
| CON-04 | Config schema: one format, consumed by both Python and C++ | Market Making `tomorrow.example.json`, `Still_Water/config/runtime_profile.json` | — | Not started |
| CON-05 | **Instrument identity.** Dhan `security_id`, Kotak token, Kite `instrument_token` are three different ID systems for the same contract. Define one internal instrument representation plus per-broker mapping | `Shoshin/security_id_list.csv`, Market Making `nifty_futures_token.txt`, `Market Making/api-scrip-master.csv` | — | **Implemented 2026-08-18 for the authorised Dhan/DAT minimum; Dhan slice Live verified. Full task incomplete:** broker-neutral identity + date-stamped Dhan `security_id` mapping loaded the staged reference master and mapped live NIFTY-Aug2026-FUT packets; Kotak/Kite mappings remain not implemented |
| CON-06 | Object-category labelling convention: observed / derived / estimated / scenario / proxy / unidentified, carried in artifacts | Working contract §7.1 | — | Not started |
| CON-07 | Time convention: exchange timestamp vs receive timestamp vs decision timestamp; IST throughout; explicit causality rule | Market Making `surface_live.py` (`as_of` causality) | — | Not started |
| CON-08 | Run-ID and artifact-manifest convention: append-only, unique per run, invalidated runs preserved and marked | Market Making `surface_run_manifest_<run_id>.json` | — | **Live verified 2026-08-18** — unique sortable run ID, permission-restricted append-only JSONL manifest, artifact hashes, completion/invalidation events; failed diagnostic runs preserved and authoritative run hash-verified |
| CON-09 | **Opportunity/finding schema (D8).** A record of what the data shows, independent of any strategy or ledger entry: window, statistic, magnitude, confidence/significance, object-category label. Exists upstream of any strategy decision — the artifact that lets data lead and strategy follow | New | CON-06, CON-07 | Not started |

### SUR — Volatility surfaces

| ID | Task | Harvest from | Depends on | Status |
|---|---|---|---|---|
| SUR-01 | Define one surface interface: `fit`, `evaluate`, `params`, `diagnostics`, `arb_check`. All parameterisations implement it | — | CON-03 | Not started |
| SUR-02 | Port eSSVI onto the interface, with tests | `VOLARB/voltaire/src/models/essvi.py` (7.3K, tested) | SUR-01 | Not started |
| SUR-03 | Implement SVI — raw, natural, and jump-wings parameterisations, with conversions between them | New | SUR-01 | **Blocked** — deferred until a concrete strategy needs it beyond eSSVI (D8, decided 2026-08-17: no speculative model-building ahead of a data-shown need) |
| SUR-04 | Implement SABR — Hagan expansion plus a note on its known arbitrage failure at low strikes / long maturities | New | SUR-01 | **Blocked** — same reason as SUR-03 (D8, decided 2026-08-17) |
| SUR-05 | No-arbitrage checks: butterfly (implied density non-negative), calendar (total variance non-decreasing in maturity) | New | SUR-01 | Not started |
| SUR-06 | Fit diagnostics: weighted R², residuals by moneyness bucket, parameter stability across consecutive frames | Market Making `monday_v1/surface_fit.py` | SUR-01 | Not started |
| SUR-07 | Staleness semantics: **the module exposes surface age and a staleness flag as a measurement; each strategy sets its own staleness-tolerance threshold** (decided 2026-08-17). A raw surface takes ~3s to compute, so quoting must consume a temporally smoothed surface, never a tick-synchronous raw frame | Market Making `monday_v1/surface_region.py` | SUR-01, CON-07 | Not started |
| SUR-08 | Interpolation/extrapolation policy in strike and maturity, stated explicitly rather than left to whatever the fitter does | New | SUR-01 | Not started |

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
| VOL-02 | Complete the full estimator set now, including realised kernel / bipower: close-to-close, Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang, kernel, bipower. **Not deferred** (decided 2026-08-17 — gated only on data availability; kernel/bipower can be built and tested against DAT-03 historical tick/quote data, does not require DAT-02 live streaming first) | Partly VOL-01 | VOL-01 | Not started |
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
| DAT-03 | Historical fetch and local storage against a stable on-disk schema. **Bars/coarser granularity only — no tick-level history available from any broker API** (noted 2026-08-17, see priority note above) | `VOLARB/voltaire/src/data/{historical_fetcher,storage}.py`, `Shoshin/src/data_downloader.py` | CON-01 | Not started |
| DAT-04 | Option-chain fetch and validation | `VOLARB/voltaire/src/data/{option_chain_fetcher,validation}.py` (11K validation) | CON-05 | Not started |
| DAT-05 | Tape recording (append-only) and **deterministic** replay — same tape format consumed by live, backtest, and research. **Full order-book depth, multiple price levels — confirmed 2026-08-17, not BBO/top-of-book only** (BKT-03 execution realism needs it, and Market Making's existing tape already captures this) | Market Making `monday_v1/{snapshot_tape,surface_replay}.py` | CON-01, CON-08 | **Not started as the full task.** The explicitly authorised DAT-05-lite append-only writer is **Live verified 2026-08-18** (232-row, 20-level tape; hash and sequence continuity verified); deterministic replay remains unimplemented and out of this run's scope |
| DAT-06 | Data-quality counters: crossed book, stale quote, invalid depth, gap count — surfaced, not silently dropped | Market Making `surface_collector_audit_<run_id>.jsonl` | DAT-02 | Not started |
| DAT-07 | Instrument-master loader per broker, plus the mapping layer. **Daily refresh cadence** (decided 2026-08-17 — broker tokens, Kotak and Dhan `security_id`, are only guaranteed stable within a trading day, so refresh must happen every day whenever the module is in use, not just periodically/at-startup) | `Market Making/api-scrip-master.csv`, `Shoshin/security_id_list.csv` | CON-05 | Not started |
| DAT-08 | Kotak market-data path in C++ (WebSocket + depth), required alongside Dhan — the module receives from both (D7) | Market Making `native/src/shaurya_kotak_ws_*.cpp`, `shaurya_kotak_depth.cpp` (tested) | NAT-01 | Not started |
| DAT-09 | **Capture universe, depth tier, and retention window.** D12 settled *that* the raw tape is recorded; this task settles *how much*. Three inputs, in dependency order: (i) **measured packet rate per instrument per depth tier** — **done, see work log**, all three tiers measured live 2026-08-18; (ii) **measured concurrent-instrument cap** per depth tier — **20-level closed 2026-08-18 after four consistent live tests: real ceiling is one subscription message per socket, that message capped somewhere between 52 and 206 instruments (exact value not pinned down), NOT the documented 5,000/socket. Debate closed — see work log.** 200-level partially done (≥5 concurrent confirmed on one socket, exact cap and skew-vs-throttle question still open); (iii) **universe and retention.** Universe (NSE-only, index F&O only: NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY) decided 2026-08-18 in `GCP_SCALING.md`. Exact depth-tier band width (e.g. ATM±7) explicitly **not decided — illustrative only**, and now has to be re-derived against the real ~50–100/socket ceiling rather than the assumed 5,000. **Retention decided 2026-08-18 (Aryan, by voice): permanent — once collected, data stays; no rolling deletion/expiry window, since storage cost is immaterial against the GCP credit.** Supersedes the original 60–90-day-rolling proposal | New | DAT-02, DAT-05 | **Packet rate, 20-level concurrent-cap, and retention are settled. Still open: exact per-message ceiling (bisect 52–206), 200-level skew question, and the connection-count math this forces for the proposed universe** |
| DAT-10 | **200-level deep-book capture.** Separate endpoint (`wss://full-depth-api.dhan.co/`), one instrument per subscription message, ~6.4 KB per book update. A genuinely rare research asset — full visible book on the traded instrument — and cheap at ~45 GB/year for one instrument. Kept as its own task because the endpoint, subscription semantics, and packet parser differ from both `DAT-02` and the 20-level feed | `DhanHQ-py` `fulldepth.py` (reference implementation) | DAT-02, CON-01 | **Live verified 2026-08-18.** Live run `sha-20260818T092355.175225Z-d181b3ff`, NIFTY-Aug2026-FUT: 366 rows in 45s (8.1/s, 8.4/s active span), 3,212 bytes/packet exactly matching the documented layout, full 200 bid + 200 ask levels confirmed independently in the written tape (not just the run summary), one connection, 4/4 heartbeats, zero reconnects. One real bug found and fixed en route: the 200-level endpoint silently drops the batched `InstrumentList` subscription shape reused from DAT-02's 20-level path (connection + heartbeats stay healthy, zero packets ever arrive) — it needs a flat `{RequestCode, ExchangeSegment, SecurityId}` message instead, confirmed against `dhanhq.fulldepth.FullDepth`. Regression test added (`test_depth200_subscribe_uses_flat_message_not_instrument_list`) |

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
| EXE-10 | **Queue-position estimator** (added 2026-08-17, forced by `SIG-07`). `EXE-09`'s queue-reactive framework is **Q-conditioned** — it models arrival, cancellation and fill intensities conditional on queue position — but `SIG-07` establishes that true queue position is **unidentified** from Dhan's feed, which carries no order IDs at any depth tier. Queue position must therefore be *estimated* from level size, per-level order counts, and observed trades at the level. **Its output carries `CON-06` category `estimated`/`proxy`, and that label propagates into every fill `EXE-09` produces.** Without this the module retires the touch-fill proxy only to replace it with an unlabelled queue-position proxy — the same error with better mathematics | New | EXE-09, SIG-07, CON-06 | Not started |

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
| SIG-07 | **Identification boundary for order-level features.** Declare under `CON-06` which features are **unidentified** from Dhan's feed: individual order identity, true queue position/rank, per-order lifetime, cancellation attribution. Same class of limit as true FIFO rank in the IEX queue-priority work. Never silently proxied. **Verified against the DhanHQ v2 docs 2026-08-17 — see §7** | Working contract §7 | SIG-01, CON-06 | **Verified — not started** |
| SIG-20 | **Online-computability requirement.** If `DAT-09` resolves toward feature-only or tiered retention, every feature in `SIG-02`–`SIG-06` must be computable in a single forward streaming pass at capture time, with bounded state. This rules out any feature needing a full-day pass, future information, or a same-day refit, and it must be checked per feature at design time rather than discovered at deployment | New | DAT-09, SIG-01 | Not started — applies to the permanent feature tier regardless of how `DAT-09` sizes the tape |
| SIG-08 | **Target register.** Each prediction target names its own estimator family and never shares a selection pipeline with another: future mid / efficient-price move → forecast regression; fill probability → censored hazard or `EXE-09` intensity model, **not** a regression; adverse selection → markout conditional on fill, **consuming `ANL-01`'s markout machinery rather than reimplementing it** (decided 2026-08-17) | New | CON-09, ANL-01 | Not started |
| SIG-09 | **Label construction.** Strictly-lagged labels only. Ban labels that are deterministic functions of current-book features — regressing micro-price moves on queue imbalance rediscovers the micro-price definition rather than a signal. Contemporaneous impact measurement and predictive measurement are separate, separately labelled objects | New | SIG-08, CON-07 | Not started |
| SIG-10 | **Redundancy structure before selection.** Hierarchical clustering / PCA on the feature correlation matrix; integrated multi-level OFI as the worked precedent. Importance is computed on clusters, never on individual collinear features — collinearity splits credit and destroys individual importance measures | New | SIG-02, SIG-03 | **Agreed (D11)** — not started |
| SIG-11 | **Inference harness.** HAC / Newey–West with lag ≥ overlap, non-overlapping resampling, stationary block bootstrap. Effective sample size reported next to every t-statistic | New | SIG-09 | Not started |
| SIG-12 | **Multiple-testing control over the entire search grid**, not per feature: Romano–Wolf stepwise or Hansen SPA (both handle dependent tests). Grid size recorded in every `CON-09` record — a finding without its search-space size is uninterpretable | New | SIG-11 | Not started |
| SIG-13 | **Selection method.** Stability selection (regularised fit over subsamples, keep by selection frequency) inside purged and embargoed walk-forward cross-validation; per-cluster selection frequency per window is a required output. Knockoff FDR control as the confirmation layer for the surviving set | New | SIG-10, SIG-11 | **Agreed (D11)** — not started |
| SIG-14 | **Contemporaneous vs predictive decomposition:** Hasbrouck VAR on (order flow, quote revision) — impulse response, permanent vs transitory impact. Formally separates "moves with price" from "leads price" | New | SIG-09 | Not started |
| SIG-15 | **Out-of-sample forecast evaluation:** OOS R² against a no-change benchmark (Campbell–Thompson), Diebold–Mariano / Giacomini–White for comparisons, Hansen Model Confidence Set to report the *set* of indistinguishable candidates instead of selecting an argmax | New | SIG-13 | **Agreed (D11)** — not started |
| SIG-16 | **Regime conditioning.** Every result reported conditional on `VOL-04`'s HMM regime. Sign instability across regimes downgrades a finding from signal to regime indicator | New | VOL-04, SIG-15 | Not started |
| SIG-17 | **Economic-significance gate.** Predicted edge must clear half-spread + fees + adverse selection under `EXE-09`'s fill model before a finding is promoted from statistical to tradeable. This is the gate VolArb's crossing-the-spread signal failed | New | SIG-15, EXE-09 | Not started |
| SIG-18 | **Coverage completeness test.** Measure the out-of-sample gap between a model on the raw level-by-level book state and a model on the engineered feature set; the gap is how much information the features leave on the table. Plus residual diagnostics against time-of-day, regime and raw book slices. An unexplained gap opens a ticket for a missing feature rather than being absorbed | New | SIG-01, SIG-15 | **Agreed (D11)** — not started; unblocked by D12, golden-set curation still sized at `DAT-09` |
| SIG-19 | **Trial log.** Every configuration tested is recorded, and performance is reported as a distribution (combinatorially purged CV, deflated Sharpe) rather than a single out-of-sample number | New | SIG-13 | Not started |

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
**Resolved 2026-08-17 by voice (D14).** The `BKT-03` → `EXE-09` forward reference is **confirmed**,
with a consequence: `EXE-09` is Q-conditioned and `SIG-07` makes true queue position
unidentified, so a labelled queue-position estimator (`EXE-10`) is now a prerequisite. The
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
| ANL-03 | Dashboard and read-only server | Market Making `monday_v1/{surface_dashboard,surface_server}.py`, `Still_Water/dashboard/` | CON-03 | Not started |
| ANL-04 | Notifications and alerts | `Shoshin/src/notifier.py`, `Still_Water/src/engine/notifications.py` | — | Not started |

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
| Decisions | D1–D15 taken. **D3 satisfied — component list agreed.** O1, O2, O3, O4, O6 resolved. **O5 still open (deliberately deferred). `DAT-09` open (retention/universe).** |
| Renames | Done and verified — GitHub `→ Market-Making`, Drive `→ Valour` |
| Component list | **Agreed and frozen 2026-08-17 (D15). 13 components: INF, CON, SUR, GRK, VOL, DAT, EXE, SIG, RSK, BKT, ANL, NAT, MIG.** |
| `MODULE_SPEC.md` | Not started — blocked on the component list |
| Repository | **Created 2026-08-17** — private `ayyararyan/Shaurya`; canonical design artifacts pushed on `main` |
| Code harvested | Dhan clients reconciled from Mushin_Gamma + Shoshin; feed patterns generalized from Mushin_Gamma + Still_Water into the standalone `shaurya` package |
| Tasks in progress | None. DAT-01/DAT-02/DAT-10 and their minimal CON-01/CON-05/CON-08 support are fully live-verified for the authorised scope; DAT-05 (deterministic replay) and the remaining CON/DAT tasks (DAT-03/04/06/07/08) are still not started |

**Immediate next action:** DAT-01/DAT-02/DAT-10's authorised scope is closed out. Next is
either DAT-09 sizing (needs Aryan — live evidence at all three depth tiers is now available
in the work log below) or moving to the next component in build order (SUR/GRK/VOL harvest,
or DAT-03/04/05/06/07 depending on Aryan's priority). NIFTY-Aug2026-FUT was a test instrument
only in every run so far and is not a capture-universe/depth/retention decision.

**O4 is resolved (D7) — `EXE` is unblocked.** `EXE-07` and `EXE-08` are dropped; `EXE-01`
through `EXE-06` can proceed once `CON` lands. **O5 remains open by design** — `MIG` stays
blocked until each old strategy is decided individually, when it is next touched.

### 6.1 Work log

- **2026-08-18 — DAT-01 / minimal CON-01, CON-05, CON-08 / DAT-02 / DAT-05-lite.** Built an
  installable Python package; reconciled the two Dhan clients; added versioned tape and
  instrument contracts, permission-restricted run manifests, supervised standard + 20-level
  WebSockets, reconnect/resubscribe, application heartbeat, explicit sequence-gap semantics,
  capture metrics, and an append-only JSONL writer. Verification: 17 pytest tests, strict mypy,
  Ruff, wheel + sdist build, clean-wheel install, staged-master mapping check, and a zero-match
  credential-value scan.
- **Authoritative live evidence:** run `sha-20260818T055709.463701Z-ea8228c8`, test instrument
  NIFTY-Aug2026-FUT (`security_id=58072`), 232 separate 20-level side packets in 30.001 seconds
  (**7.733 packets/s** full capture window; 8.238 packets/s active packet span), 332 bytes each,
  116 bid + 116 ask, one connection, two successful heartbeats, zero reconnects, zero crossed or
  invalid books. Tape: 232 continuous receive sequences, SHA-256
  `54357820155bbda1ed1ccc214a6ea056d1cb08a2bc9dce3015d408c7629b43b3`. These are raw
  **DAT-09 inputs only, not a sizing recommendation or decision**. Four earlier diagnostic runs
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
    directly measured live (only documented from the spec), 20-level ~7.7–8.4 packets/s at
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

---

## 7. What the Dhan feed actually carries

Verified 2026-08-17 against the DhanHQ v2 documentation (`dhanhq.co/docs/v2/live-market-feed/`
and `/annexure/`), because the answer determines `SIG-07`'s identification boundary and the
`DAT-09` storage arithmetic. Recorded here so it is never re-argued from memory.

**Established:**

- The feed is **tick-by-tick and event-based**, not fixed-interval snapshots — Dhan's own
  wording. Binary packets over WebSocket, little-endian, 8-byte header.
- Up to **5 WebSocket connections × 5,000 instruments** each. Instrument count is not a
  binding constraint.
- Four subscription modes (feed request codes): Ticker (15), Quote (17), Full (21), and
  **Full Market Depth (23)** — the last being the 20-level feed.
- The **Full packet is 163 bytes**: trade data, OI, day OHLC, plus a 100-byte depth block =
  **5 levels × 20 bytes**, each level carrying bid qty, ask qty, **number of bid orders**,
  **number of ask orders**, bid price, ask price.

**What this settles about the disagreement:**

- *Aryan was right* that this is a raw event-driven tick feed. The earlier suggestion that it
  might be fixed-interval snapshots is withdrawn — it is not.
- *The order-level limit stands.* There is no order ID anywhere in the packet structure. The
  feed is aggregated depth (price-level), not market-by-order. True queue position, per-order
  lifetime, and cancellation attribution remain **unidentified** — `SIG-07`.
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
