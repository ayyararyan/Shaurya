# MIG — Strategy migration

## Objective

Prove Shaurya's plug-and-play boundary by moving Market Making onto the module without behaviour change, while making no blanket commitment to migrate Aryan's six pre-existing strategies.

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Pre/post test results, dependency graph, pinned Shaurya version | Observed | Direct migration evidence. |
| Behavioural equivalence | Deterministically evaluated against declared suites/artifacts | Requires green before/after and comparison; a refactor label alone is not evidence. |
| Future migration value | Unresolved decision | No proxy ranking converts an informal preference into a commitment. |

## Architecture and contracts

- Dependency direction is one way: a strategy imports and pins Shaurya; Shaurya never imports the strategy (D5).
- Strategy-specific logic stays in the strategy. Only general contracts/interfaces cross the boundary.
- MIG produces no new `CON-*` schema. Each migration consumes the already-versioned contracts needed by that strategy and records the pinned Shaurya release.
- Migration commits do not combine refactoring with behaviour changes.
- Market Making is the sole formally required migration. Its source test baselines are 91 C++ and 144 Python tests.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-MIG-01 | Refactor Market Making to consume a pinned Shaurya release, preserving behaviour, keeping 91 C++ and 144 Python tests green before and after, and separating refactor from behaviour change. | MIG-01, D5 | `/Users/maheit/Documents/Market-Making` dependency integration | Before/after suites; dependency audit; migration report |
| REQ-MIG-02 | Treat VOLARB only as an informal “probably next” candidate; migrate it solely if a future per-strategy decision selects it when next touched. | MIG-02, O5 | Deferred strategy integration | Future explicit decision record and migration suite |
| REQ-MIG-03 | Decide separately, when next touched, whether Mushin_Gamma, Seshin_Zen, Shoshin, Still_Water, and openclaw_zen migrate or remain indefinitely on their own code. | MIG-03, O5 | No committed code target | Per-strategy decision record only when triggered |

## Outputs and acceptance tests

- Market Making dependency pin, one-way dependency audit, before/after suite evidence, and behaviour-equivalence migration report.
- Acceptance requires no Shaurya import from Market Making and no Market Making special case inside Shaurya.
- Any future strategy migration gets its own explicit decision and acceptance evidence; no batch-migration status is inferred.

## Exclusions

- A committed migration list for all six pre-existing strategies.
- Big-bang migration.
- Treating VOLARB's “probably next” note as approval or schedule.
- Rewriting or deleting untouched strategies merely to reduce duplication.
- Behaviour changes hidden inside migration commits.

## Deferred items — O5 formal resolution for this artifact

O5 is deliberately deferred per strategy, not resolved into a portfolio-wide migration plan:

- **Formally required:** Market Making only (D5 / MIG-01). It is separate from the six pre-existing strategies named below.
- **Informal candidate only:** VOLARB is “probably next” (MIG-02), with no commitment.
- **No plan unless next touched:** Mushin_Gamma, Seshin_Zen, Shoshin, Still_Water, and openclaw_zen (MIG-03). Any may remain on its own code indefinitely.

No future migration is implied by harvesting source code from a strategy.
