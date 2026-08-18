# Shaurya — Next-Session Prompt

**Prepared:** 2026-08-17, last updated 2026-08-19 ~01:16 IST
**Use on return:** 2026-08-19, including the market-open window from 09:15 IST
**Repository:** private `ayyararyan/Shaurya`
**Canonical status ledger:** `TASKS.md`

## START HERE — session was reset 2026-08-19 ~01:16 IST with two agents still running

**Do these three checks before anything else.**

### 1. The maker research report — this is what the next conversation is for

`sig_maker_research` was commissioned once **D21** settled that Shaurya quotes and never crosses.
The first research report was written for a directional taker, so its targets invert for a maker;
this second report exists to say what a maker should actually do. It writes to
`research/sig-maker-research-2026-08-19.md` in the OpenClaw workspace (not this repo).

- task name: `sig_maker_research`
- run ID: `be2aa0f5-8b0c-4409-b8a5-a47a2653b3d7`
- session key: `agent:main:subagent:5a5747e9-1d95-4154-8bda-5b5cd0747cc8`

It covers quoting theory derived rather than name-dropped, fill probability and queue dynamics
under **D23**, adverse-selection measurement, options-specific making across a shared surface, the
non-co-located maker problem (with explicit permission to conclude no edge exists in some regimes),
NSE maker economics including the STT asymmetry on option sales, and which of the first report's
twelve stories survive the inversion. A mid-flight correction was sent to it carrying D23; confirm
that landed in its section 2.

**When it arrives: read it, verify its citations rather than trusting them** — the first report ran
roughly a one-in-seven citation error rate — **then resume the story-by-story debate with Aryan.**
The debate is the work; the claim ledger (D22) is its output. Do not start writing ledger claims
from the taker report alone.

### 2. The DAT-14 build

`shaurya_dat14_trade_signing` was implementing capture-path trade-direction classification per
**D24**, committing to this clone. Check whether it finished and whether its commits are on
`origin/main`; verify its claims independently rather than accepting its report, and re-check the
ledger row it wrote for an honest evidence level.

- task name: `shaurya_dat14_trade_signing`
- run ID: `abf57826-54b5-4fc5-a563-0d9520d8ce61`
- session key: `agent:main:subagent:cab7a4b6-3730-4aa9-8cdc-26c0d8795945`

### 3. Today's market-hours work — Aryan's explicit instruction

**When the market opens today (2026-08-19), five DAT items need live runs.** Aryan named DAT-15 as
joining the existing list and said both the new items are to be tested and then patched in
accordingly.

- **DAT-11** — bisect the exact 20-level per-message instrument ceiling within the measured 52-206
  band.
- **DAT-12** — does reconnecting a socket reset the first-message-only limit, or is the cap on the
  account?
- **DAT-13** — is the 200-level packet skew a real throttle or just liquidity? Rerun with
  comparably liquid instruments.
- **DAT-14** — live-verify the capture-path classifier against a real session. Tonight's acceptance
  is at best dry-run on retained tape; the Live verified level requires market hours.
- **DAT-15** — measure the cross-channel alignment error: how stale the depth quote is when a print
  lands, how often that staleness would flip a classification, and how it varies by instrument,
  depth tier and time of day. **This bounds the reliability of every signed-flow feature
  downstream**, so it is a measured distribution and flip-rate, never an assumption.

Probes for DAT-11/12/13 are already written and tested. DAT-14/15 depend on what the build agent
landed.

## Mandatory restart context

1. Load and follow `OPENCLAW_WORKING_INSTRUCTIONS_REVISED.md` for the new session.
2. Read `README.md` and the entire `TASKS.md` before discussing or changing scope.
3. Treat D1–D24 and the frozen 13-component list as binding. Do not reopen settled design
   choices merely because a different implementation would be easier.
4. Before editing the repository, `git fetch` and compare `HEAD` against `origin/main` — more
   than one process has committed to this clone concurrently before.
5. **Current state as of 2026-08-19 ~01:16 IST**, superseding the 2026-08-17 line that said no
   code had been harvested: real code exists and is pushed. `origin/main` is at the commit
   recorded below. CON contracts, INF packaging, the full DAT component, and the SUR eSSVI
   surface stack are implemented, with 89 tests, strict mypy clean, ruff clean. Per-component
   specs live in `docs/module-spec/*.md`; `MODULE_SPEC.md` is the index over them.
6. **Market-hours work is listed in START HERE section 3** — DAT-11 through DAT-15. Do not
   attempt any of it outside 09:15–15:30 IST; it is not a reset-session activity.

## SIG discussion — round 1 held 2026-08-19, now waiting on commissioned research

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

On return: read that report first, then resume the SIG discussion from it. Do not re-derive
`SIG-01`–`SIG-20`; this is sharpening and narrowing, not redesign.

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

## First five actions on return

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
