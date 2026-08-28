# Daily prospective research automation

## Purpose

`shaurya-research daily` joins the canonical DAT catalogue to the frozen research engine.  It is
an orchestration layer only: capture remains owned by `data/`, statistical evaluation remains
owned by `research/`, and execution is untouched.

The daily contract is:

```text
completed DAT catalogue
        -> deterministic source discovery + full integrity verification
        -> pre-session frozen plan/state
        -> registry-bound feature/target derivation
        -> one unseen outer session
        -> empirical null + multiplicity + robustness gates
        -> append-only evidence ledger
        -> report + snapshot
        -> immutable state intended for the next session
```

## First run

If the research workspace has no state or evidence history, `daily`:

1. finds the latest completed session strictly before `--date`;
2. freezes the selected registry bundle through that session;
3. writes a content-addressed plan under `derived/research/plans/`;
4. derives the complete pre-session source prefix from the catalogue;
5. writes the bootstrap state intended for the unseen evaluation session; and
6. evaluates `--date`.

Automatic bootstrap is refused once the evidence ledger has history.  That prevents an operator
mistake from manufacturing a new state that is inconsistent with prior evidence.

## Subsequent runs

The latest immutable state must be intended for `--date`.  `daily` then locates the exact frozen
plan by the plan hash stored in that state.  It does **not** silently re-plan from the new day's
data.  Newly registered hypotheses therefore cannot contaminate a session that was not frozen for
them prospectively.

A scheduler retry for an evaluation date that already has a published immutable state is a
deterministic no-op.  It returns that state hash and does not append duplicate evidence.

## Warm-up sessions

The v2 policy currently requires five inner training sessions plus one distinct validation
session before an unseen outer fold can be frozen.  Earlier completed sessions are not labelled as
failed hypotheses.  `daily` appends a `daily_warmup_skipped` lineage event, verifies and extends the
source prefix, and writes the immutable state intended for the next session.  Confirmatory evidence
begins automatically once the required prior-session count exists.

## Operator command

From the `research/` directory:

```bash
uv run shaurya-research daily \
  --date 2026-08-28 \
  --next-session 2026-08-31 \
  --catalog /Volumes/Aryan/NSE/catalog \
  --bundle high_frequency
```

The convenience wrapper provides one workspace switch:

```bash
uv run python scripts/run_daily_research.py \
  --date 2026-08-28 \
  --next-session 2026-08-31 \
  --catalog /Volumes/Aryan/NSE/catalog \
  --workspace derived/research
```

## v2 construction boundary

The v2 registries name canonical constructors in `shaurya.data.high_frequency`.  Those functions
have intentionally different signatures, so `research/construction.py` is the only adapter allowed
to supply constructor-specific causal context.

The current adapter executes same-book and same-instrument constructions (book imbalance,
microprice, CCZ OFI, prior move, midpoint volatility, displayed depth/spread) and v2 futures move,
range, raw option markout and spread-change targets.  Cross-instrument parity, synchronized option
surface/ATM-IV, hedged option outcomes, and post-fill features require additional context adapters.
Until those adapters are present, the exact frozen feature/target remains **missing**.  The daily
experiment can therefore account the candidate as insufficient support without substituting a
legacy or approximate formula.

This is deliberate: automatic research should prefer missing evidence to semantically incorrect
evidence.

## Invariants

- Catalogue handles, not filenames, select data.
- Every source is revalidated before and after derivation.
- Evaluation uses a plan frozen strictly before the unseen session.
- The pre-session state must name that exact plan and session.
- A constructor identity never falls back to a different formula.
- Evidence publication is append-only and the existing ledger/state crash-recovery rules remain
  authoritative.
- `data/` capture and `execution/` are not modified by this workflow.
