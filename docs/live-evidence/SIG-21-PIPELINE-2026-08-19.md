# SIG-21 post-registration synthetic pipeline — 2026-08-19

**Scope:** code and synthetic fixtures only. No retained or live tape was opened; no event was
joined to a future midpoint; no empirical power artifact, response estimate or predictive verdict
was produced.

**Sequencing:** implementation began only after the registration/construction commit
`f2cf65011d02882191b5cfda566c1024119964d7` was pushed and the remote hash was verified.

## Implemented boundary

- `src/shaurya/signals/deep_book_response.py`
  - strict pre-event and endpoint as-of depth20 midpoint selection with no forward interpolation;
  - explicit rejection of invalid intermediate quality and connection-epoch paths;
  - separate pre-event-to-`Z` contemporaneous and `Z`-to-`Z+h2` predictive legs;
  - the registered `{0.5 s, 1.0 s} x {1 s, 5 s, 10 s}` endpoint grid;
  - exact-timestamp bursts, 11-second episode clustering and primary overlap exclusion; and
  - outcome-blind nearest quiet-control matching in the registered exact strata, with explicit
    match failures.
- `src/shaurya/signals/deep_book_inference.py`
  - the exact registered 384-cell family manifest and completeness rejection;
  - five calibration-session and 20 later evaluation-session identity/date gates;
  - regime-stability support gates of at least five evaluation sessions and `N_eff >= 100`;
  - conservative two-arm MDE calculations from unconditional calibration quantities only;
  - HAC/Newey-West with lag at least 11 and deterministic within-session stationary bootstrap;
  - two-sided Romano-Wolf max-absolute-t step-down over the complete family;
  - immutable complete-family `SIG-19` rows carrying `N`, `N_eff`, both MDEs and the power-artifact
    SHA-256, written create-once with mode `0600` and `fsync`; and
  - a hard promotion guard requiring a new `H-SIG21C-*` registration and subsequent tape for any
    directional confirmation.

## Verification

- Response and inference fixtures: **28 passed**.
- Complete Python suite: **192 passed**.
- Ruff format check and lint: passed for all SIG-21 files.
- Strict mypy: passed across **45 source files**.
- `git diff --check`: passed.

The fixtures cover causal endpoint alignment, path contamination, episode overlap, outcome-blind
matching failures, exact family identity, sample/regime support, numeric MDE formulas, HAC lag,
session-bounded bootstrap, Romano-Wolf behaviour, complete trial rows, file permissions,
overwrite refusal and directional-promotion sequencing.

## Deliberate limitations and next gate

- This is an execution-ready set of registered primitives, not an empirical SIG-21 result.
- No endpoint staleness cutoff was invented because the registration specifies as-of selection but
  no additional cutoff.
- Matching selects one deterministic nearest eligible control; the registration does not specify
  a caliper or multiple-control assignment.
- Episode inputs must already be partitioned by contract/session.
- HAC observation order and null-centred bootstrap statistics remain caller responsibilities.
- The power calculator consumes a supplied multiplicity critical value and unconditional
  calibration statistics; it never estimates them from joined event outcomes.
- The immutable writer validates the referenced SHA-256 syntax and family consistency but does not
  open or hash the referenced artifact.

The outcome gate remains **CLOSED**. The next admissible work is to collect five full sessions
after the registration commit, create and push the complete outcome-independent numeric power
artifact, and verify its remote hash. Only adequately powered cells may then be evaluated on 20
subsequent full sessions. `VOL-04` regime support and the measured end-to-end reaction path remain
separate dependencies for stability and decision relevance.
