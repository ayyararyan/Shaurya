# Shaurya — Next-Session Prompt

**Prepared:** 2026-08-17, last updated 2026-08-19 ~10:52 IST
**Use on return:** after the 2026-08-19 DAT market-hours session
**Repository:** private `ayyararyan/Shaurya`
**Canonical status ledger:** `TASKS.md`

## START HERE — both commissioned agents have landed and been verified

Nothing is outstanding from the 2026-08-19 ~01:16 IST reset. Both `sig_maker_research` and
`shaurya_dat14_trade_signing` finished, and both were checked independently rather than accepted.
**The DAT-11 through DAT-15 market-hours runs are complete and landed. The open work is the
story-by-story SIG debate and the final DAT-09 strike-band/connection-count owner choice.**

### 1. The maker research report — this is what the next conversation is for

`research/sig-maker-research-2026-08-19.md` (OpenClaw workspace, not this repo). 9,235 words.
Commissioned once **D21** settled that Shaurya quotes and never crosses.

**Verified 2026-08-19:** 23 of 23 peer-reviewed citations resolve correctly against Crossref with
matching author, title, venue, volume and pages — against roughly a one-in-seven error rate in the
first, taker-framed report. Every India-specific fact was checked against the primary circulars
(STT rates from 2026-04-01, transaction charges FA/73061, lot sizes FAOP/70616, the expiry-day
move, the weekly rationalisation, the 50.22% colocation share). The cost arithmetic was
re-derived by hand and reproduces. One unresolved caveat: the report claims to have corrected an
erroneous author list, but that correction is not documented in its body.

Governing conclusion, stated as an inference from market structure and not a measurement:
**presume one-tick at-touch quoting in the liquid NIFTY complex has no viable edge for a
non-colocated retail-feed maker**, overturnable only by fill-conditioned, latency-realistic
evidence. Structural output is **MK-01 – MK-13**, preregistered in four tiers, with **MK-05 as an
explicit kill test** on the liquid contracts before any control-model work is justified.

It corrected an error of mine that must not propagate: STT and transaction charges are
*percentages of premium*, so they **do** scale down with option price — a ₹5 option round trip
costs ~0.24 ticks against ~0.95 ticks at ₹20. Cheap OTM options are not disqualified by tax.

**Next action: resume the story-by-story debate with Aryan.** The debate is the work; the
claim ledger (**D22**) is its output. Do not write ledger claims from the taker report alone, and
resolve each citation as its claim is reached.

### 2. The DAT-14 pre-live build — historical evidence, superseded by section 3

Pushed as `4855778` + `9f96380`; `origin/main` and local HEAD match, tree clean.

**Reproduced from scratch, not accepted:** replaying all five retained tapes through the
classifier gives exactly 21,279 rows and 12 positive-volume print intervals — 3 buy, 8 sell,
1 unclassified, 1 degraded, 5 coalesced — matching the agent's report line for line. Gates
re-run independently: 100 tests under both pytest entry points, strict mypy clean on 30 files,
ruff clean. The `1.0.0` tapes still parse under schema `1.1.0`, which the replay itself proves.

The rule is real: quote rule against the midpoint in decimal arithmetic, tick-rule fallback only
at mid, and explicit degraded `UNCLASSIFIED` for a missing, crossed or stale quote rather than a
silent forward-fill. Alignment never looks forward (`quote.state_receive_ts <= print.receive_ts`),
and a connection gap or reconnect discards the quote state instead of carrying it across.

**Three findings from the verification that the next session should carry forward:**

- **Classification requires a simultaneous depth subscription on the same instrument.** The
  alignment rule deliberately excludes the book bundled with the print itself — correct, since
  that book may already reflect the trade — so the prevailing quote can only come from the
  depth20/depth200 channels. A Quote/Full-only capture classifies nothing. That couples DAT-14
  directly to **DAT-11**'s per-socket instrument ceiling: signing trades costs depth capacity.
- **The evidence base is 12 prints from one instrument in one ~7-minute tape.** The rule is
  well unit-tested, but only the quote-rule path was exercised against real data; the tick-rule
  fallback has never fired outside tests. Treat the dry-run level as genuinely thin.
- **Early coalescing numbers, anecdote not measurement (n=12):** the signed last print covers
  only **63%** of traded volume — 2,210 of 3,510 units — so 37% carries no attributable sign.
  Quote ages at classification ran 58–427 ms against the 1 s freshness bound. Both numbers are
  exactly what **DAT-15** exists to measure properly.

### 3. DAT-11 through DAT-15 market-hours outcomes — landed

- **DAT-11:** exact observed 20-level one-message ceiling is **50**. Fresh 50 worked; 51, 52,
  and 53 failed wholesale. This corrects the prior-day statement that 52 worked.
- **DAT-12:** **socket-scoped** at the reproduced 50+50 load. Message two failed on the loaded
  socket and succeeded unchanged on a fresh socket. A 2+2 control accepted both messages, so the
  effect is load-dependent rather than a universal first-message-only rule.
- **DAT-13:** the 200-level skew is a real first-subscription throttle/bias. NIFTY-first and
  BANKNIFTY-first rotations both produced 328 packets for the first future and 2 for every later
  future.
- **DAT-14:** Live verified for two front-month futures/depth20/one 10-minute morning window:
  313 prints, 158 buy/154 sell/1 unclassified, 1 real tick-rule fallback, 1 degraded, 113
  coalesced, and 313/313 version stamps.
- **DAT-15:** Live verified for the retained eight-tape sample (38,572 rows, 482 prints), with a
  healthy-core quote-age median/p95 of 238.7/462.6 ms and 5/320 post-BBO proxy flips. The
  simultaneous depth20/depth200 capture was reconnect-heavy; its cross-tier comparison is a
  stress diagnostic, not a general tier ranking. Options, midday, and a healthy depth200-aligned
  run remain unmeasured.

Canonical details, denominators, identification limits and residual gaps are in `TASKS.md`,
`docs/module-spec/DAT.md`, and `docs/live-evidence/DAT-11-2026-08-19.md` through
`DAT-15-2026-08-19.md`.

## Mandatory restart context

1. Load and follow `OPENCLAW_WORKING_INSTRUCTIONS_REVISED.md` for the new session.
2. Read `README.md` and the entire `TASKS.md` before discussing or changing scope.
3. Treat D1–D24 and the frozen 13-component list as binding. Do not reopen settled design
   choices merely because a different implementation would be easier.
4. Before editing the repository, `git fetch` and compare `HEAD` against `origin/main` — more
   than one process has committed to this clone concurrently before.
5. **Current state as of 2026-08-19 ~10:52 IST**, superseding the 2026-08-17 line that said no
   code had been harvested: real code exists and is pushed. CON contracts, INF packaging, the
   DAT component through DAT-15, and the SUR eSSVI surface stack are implemented, with 106 tests,
   strict mypy clean on 31 package files plus live-analysis scripts, and Ruff clean. Per-component
   specs live in `docs/module-spec/*.md`; `MODULE_SPEC.md` is the index over them.
6. **Market-hours work DAT-11 through DAT-15 completed on 2026-08-19.** Read the dated evidence
   under `docs/live-evidence/` before using the 50-instrument ceiling, socket-scoped reconnect
   result, 200-level throttle, trade-signing evidence, or alignment-error estimates.

## SIG discussion — round 1 held 2026-08-19; both commissioned reports have landed

Held on Telegram ~00:05–00:25 IST. Three framing questions were put: sampling clock, pooling
coordinate, and prediction-horizon set. Aryan's answer to all three was the same — **we do not
know, and only the data can tell us** — recorded as **D20** in `TASKS.md` and written into
`docs/module-spec/SIG.md` under "Measurement design is empirical". All three become swept axes in
`SIG-19`'s trial log and are counted in `SIG-12`'s grid.

**Aryan's instruction, binding on the next session:** no further SIG design decision is taken
until a commissioned literature review lands. A single `sessions_spawn` research agent
(`sig_feature_research`) was started 2026-08-19 ~00:22 IST once the DAT and SUR builds finished,
briefed to survey what actually moves NSE index futures and options — weighted heavily toward
Indian market structure, organised by horizon, reading across viewpoints rather than one school,
and for each candidate story stating what the data would have to show for it to be true and what
would falsify it. Aryan's own worked example of the shape: options can be traded through
volatility arbitrage, or by predicting the forward and hence the option's fair value some seconds
ahead — which of those is real is a data question, not a modelling preference.

**Both reports are now in and verified — see START HERE section 1.** The taker report
(`research/sig-feature-research-2026-08-19.md`) carries four inline corrections and a standing
citation-reliability warning; the maker report supersedes its framing under **D21**. Resume the
story-by-story debate from the maker report. Do not re-derive `SIG-01`–`SIG-20`; this is
sharpening and narrowing, not redesign.

## Queued debate — resolved, see D19

Added 2026-08-18 ~16:23 IST from Aryan's voice-captured thought, debated live on Telegram the
same evening, and closed as **D19** in `TASKS.md`'s decisions log. Asked directly whether "live"
meant a dashboard on `SUR`'s existing fit/smoothing cadence, or a hard latency requirement on the
fit itself feeding quoting. Aryan: **"It's only about watching, no worries."** `ANL-03` already
covers this (it harvests Market Making's `monday_v1/surface_dashboard.py`/`surface_server.py`);
no new task, no change to `SUR`'s Python-only research-fit scope. See D19 for the full record.

## Do not re-ask settled questions

Aryan has already answered the substance of the five questions previously drafted here. The
documents are the answers:

1. `MODULE_SPEC.md` guarantees come from D1–D15, the full stable-ID task ledger, and the canonical
   working contract. Do not ask Aryan to restate them.
2. Contract semantics are already specified by CON-01–CON-09 plus the timing, identification,
   proxy, risk, replay, and artifact decisions throughout D7–D15.
3. There is no owner choice between a research, paper, or live "MVP". The full frozen module is
   required; evidence levels may rise component by component, but internal sequencing never
   rewrites completion scope.
4. D5/MIG-01 already require Market Making to consume Shaurya. MIG-02 recommends VOLARB as the
   first broader migration, while O5 is deliberately deferred until each old strategy is touched.
5. D12 already decided that the raw tape is recorded. DAT-09 asks only how much, and explicitly
   waits for measured packet rates and capacity before Aryan makes that sizing choice.

At session start, do not interview Aryan. Convert the recorded decisions into formal artifacts and
work. Ask only if implementation exposes a genuinely new meaning-changing choice not answered by
the ledger.

## First five actions on return — ALL COMPLETED, retained as history

These were written on 2026-08-17 and are done: `MODULE_SPEC.md` and the per-component specs in
`docs/module-spec/` exist, the traceability ledger is `TASKS.md`, and the DAT-01/02 read-only
bootstrap is live-verified. Do not re-run them. The live work is START HERE section 3.

1. **Decision-completeness audit.** Map D1–D15 and every non-dropped task into a requirement
   inventory; identify contradictions or genuinely missing meanings without asking Aryan to repeat
   settled answers.
2. **Draft `MODULE_SPEC.md`.** Formalise objective, object/identification ledger, architecture,
   contracts, component requirements, timing/causality, safety gates, outputs, robustness,
   acceptance tests, exclusions, deferred items, and completion criteria using stable IDs.
3. **Create requirements traceability and artifact contracts.** Every frozen task gets a row with
   code/test/output targets; define schemas and semantic invariants for required artifacts before
   implementation.
4. **Write the implementation plan.** Resolve dependency order, harvesting sources, engineering
   work packages, parity gates, and end-to-end acceptance checkpoints. Internal phases must retain
   the full external completion requirement.
5. **Prepare the forward-only data bootstrap.** Specify and, where prerequisites permit, implement
   the read-only DAT-01/02 measurement path needed to observe packet rates, concurrent capacity,
   and storage load. Present evidence before returning DAT-09 to Aryan for a sizing decision.

## Engineering calls already delegated to OpenClaw

Do **not** ask Aryan to decide these unless an implementation constraint would change model
meaning, risk, outputs, or the frozen scope.

### Repository and packaging architecture

- One standalone monorepo with root `contracts/`, `python/`, `native/`, `docs/`, and CI tooling.
- `python/` builds an installable `shaurya` distribution with an explicit plugin registry.
- `native/` builds and exports a consumable CMake target in namespace `shaurya::`.
- Contracts are versioned artifacts consumed by both languages; strategies pin Shaurya releases.
- CI enforces tests, format/lint/type/build gates, Python↔C++ parity where relevant, and the
  one-way dependency rule: Shaurya never imports from a strategy.
- Semantic versioning and a changelog begin with the first implementation commit.

### Implementation sequence and first acceptance chain

1. Write and freeze `MODULE_SPEC.md` with stable requirement IDs and a traceability matrix.
2. Build CON contracts first, with INF packaging/build/test/security foundations alongside them.
3. Start DAT-01/02/06/07 early because tick collection is forward-only; use a measured live
   session to resolve DAT-09 rather than assumptions.
4. The first internal end-to-end acceptance chain is:
   broker event -> canonical tape -> deterministic replay -> strategy interface -> C++ paper
   broker/risk gate -> canonical ledger -> read-only analytics.
5. This internal chain is a sequencing device, not an MVP or scope reduction. All frozen
   components remain required.
6. Harvest, reconcile, test, and generalise existing code; do not rewrite working components from
   zero without evidence that harvesting is infeasible.
7. No live-order path is enabled merely because the chain passes. Live readiness remains gated by
   the full EXE/RSK/NAT requirements and explicit per-session human authorisation.

## After the first five actions

Report the decision-completeness audit and draft artifacts plainly. Raise only genuine unresolved
choices. Then hold the open idea-browsing session; any new capability becomes a new stable task ID
and does not silently widen an existing task.
