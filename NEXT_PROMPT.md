# Shaurya — Next-Session Prompt

**Prepared:** 2026-08-17
**Use on return:** 2026-08-18
**Repository:** private `ayyararyan/Shaurya`
**Canonical status ledger:** `TASKS.md`

## Mandatory restart context

1. Load and follow `OPENCLAW_WORKING_INSTRUCTIONS_REVISED.md` for the new session.
2. Read `README.md` and the entire `TASKS.md` before discussing or changing scope.
3. Treat D1–D15 and the frozen 13-component list as binding. Do not reopen settled design
   choices merely because a different implementation would be easier.
4. Current state: design phase complete; INF-01 repository creation complete; no package or
   module code harvested yet. The next formal artifact is `MODULE_SPEC.md`.

## Queued debate — open, not settled, do not resolve solo

Added 2026-08-18 ~16:23 IST, sourced verbatim from Aryan's voice-captured thought at
`~/Documents/OpenClaw/thoughts/2026-08-18.md` (16:20 IST entry, `Action status: unreviewed`).
Aryan asked explicitly to record this and debate it live after the next session reset — do
**not** silently decide it, fold it into an existing task, or start implementing against it
before that conversation happens.

Raw thought, as captured:

> In the Shaurya engineering stack, because volatility surfaces are being implemented, build a
> live dashboard so the surfaces can be seen in real time.
>
> Surface construction can be computationally heavy and may not finish fast enough unless the
> code is deliberately optimized; the surface path therefore needs latency-sensitive engineering,
> not merely a batch/research implementation.

Why this is a genuine open question, not just an addition to `ANL-03` (dashboard/read-only
server) or `SUR-01` (surface interface): `SUR-07` already established that a raw surface takes
~3s to compute and that quoting must consume a temporally smoothed surface, never a
tick-synchronous raw frame — so there is an existing precedent that surface-fitting speed is a
known constraint, not a new discovery. What's actually undecided is:

1. Does "live" here mean a dashboard refreshed on `SUR-07`'s existing smoothed-surface cadence
   (an `ANL-03` scope question), or does it mean surface *fitting itself* needs to be
   latency-engineered — e.g. a C++ fitting path, not just Python research code (a `SUR`
   component-scope question, and arguably a new stable task, not a widening of `SUR-01`)?
2. If the latter, does that change `SUR`'s placement in the build order (currently step 3,
   "mostly harvest from VOLARB... no dependency on broker decisions") or its language split
   (Python-only today; NAT is the only component currently scoped for the live/C++ path)?
3. Per this project's own rule (see below, "any new capability becomes a new stable task ID"),
   this likely wants a new `SUR-0X` and/or `ANL-0X` row once scoped, not a silent edit to
   `SUR-01`/`ANL-03`'s existing text.

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
