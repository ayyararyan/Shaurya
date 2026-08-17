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

## Aryan's first five questions

Ask these one at a time. Record each answer in `TASKS.md` and, where it changes model meaning or
acceptance criteria, in `MODULE_SPEC.md`. Do not bundle them into one broad approval request.

### Q1 — What must the frozen module specification guarantee?

Beyond restating D1–D15, what properties must `MODULE_SPEC.md` make non-negotiable for Aryan:
economic/statistical object definitions, causality and timing, identification limits, safety
boundaries, required outputs, robustness checks, and the evidence level required for completion?

### Q2 — What semantics must the shared contracts preserve?

For the canonical tape, ledger, surface frame, config, instrument identity, run manifest, and
opportunity/finding record, which meanings and distinctions must remain visible to a researcher
and strategy author? In particular: observed versus derived/estimated/proxy/unidentified,
exchange versus receive versus decision time, data-quality flags, invalidation, and causal
availability.

### Q3 — What should count as Shaurya's first meaningful release outcome?

This does **not** reduce the full frozen scope. It decides the first externally meaningful release
gate: research-ready discovery and deterministic replay, end-to-end paper/shadow execution, or
live-order readiness after all safety gates. What capability should Aryan be able to use before
the first version is called meaningful?

### Q4 — Which existing strategy should be the first real consumer and acceptance test?

Choose the first migration target that proves Shaurya is genuinely plug-and-play rather than a
Market-Making-shaped extraction. Candidates include Market Making (the only broker-verified path),
VOLARB (the richest source of harvested Python research components), or another named strategy.
The choice determines the first real compatibility and migration acceptance tests; it does not
decide the fate of every old strategy.

### Q5 — What initial market-data coverage and retention does Aryan want?

After presenting measured packet rates and storage scenarios, decide the first capture universe,
depth tiers, and retention policy for DAT-09: 5-level chain-wide, 20-level narrow core, 200-level
traded instrument, rolling raw-tape duration, permanent golden days, and permanent derived
features. Do not ask for a final storage choice before the live measurement evidence exists.

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

## After the five questions

Hold the open idea-browsing session. New capability becomes a new stable task ID; it does not
silently widen an existing task. Then draft `MODULE_SPEC.md` and the implementation plan from the
recorded answers and the engineering calls above.
