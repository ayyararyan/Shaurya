# INF — Foundations

## Objective

Provide the installable, buildable, testable, releasable, and secret-safe foundation on which every other Shaurya component depends. INF makes Shaurya a standalone versioned dependency rather than a source-tree template (D5, D9).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Repository, release tag, package metadata, build result, test result | Observed | Directly inspectable project state. |
| Credential handle and file permissions | Observed | The handle and permissions may be inspected; credential values must never enter artifacts or logs. |
| “Safe to release” result | Deterministically derived | Produced from the declared CI, test, dependency-direction, and secret-scan gates; it is not inferred from a passing unit-test subset. |
| Secret value | Deliberately unobserved by Shaurya | Shaurya receives only an external handle. No proxy is permitted. |

INF introduces no estimated trading object. Its central identification boundary is security-related: possession of a credential handle is not evidence that a credential value is safe, valid, or authorised for live orders.

## Architecture and contracts

- One standalone monorepo contains the installable Python distribution and exported `shaurya::` CMake target.
- Strategies pin releases and import Shaurya; Shaurya never imports a strategy (D5).
- `CON-04` carries credential handles and shared runtime configuration, never secret values.
- Python and C++ have independent build/test tooling under one CI policy. Cross-language parity belongs to the relevant domain component, not INF.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-INF-01 | Maintain the standalone private Shaurya repository containing Python and native trees. | INF-01, D9 | Repository root | Remote/branch/privacy verification record |
| REQ-INF-02 | Provide an installable `shaurya` Python distribution with lint and type configuration so strategies can pin a release. | INF-02, D5 | `pyproject.toml`, `src/shaurya/` | Clean-wheel install; lint/type/package tests |
| REQ-INF-03 | Provide a C++ build skeleton in namespace `shaurya::` that exports a consumable CMake target. | INF-03, D4, D5 | `native/CMakeLists.txt`, `native/include/`, `native/src/` | Configure/build/install/consumer-project test |
| REQ-INF-04 | Provide pytest and C++ test-runner harnesses. | INF-04 | `tests/`, `native/tests/` | CI test reports for both languages |
| REQ-INF-05 | Represent credentials only by external handles; require secret locations and files to use restrictive permissions. | INF-05 | `CON-04` config validation; security docs | Permission and redaction tests; secret-policy artifact |
| REQ-INF-06 | Relocate identified credential-shaped files out of strategy trees without reading or committing their values. | INF-06 | External secret locations; migration runbook | Path/permission audit with value-redacted output |
| REQ-INF-07 | Prevent tracking of environments, keys, tokens, run state, logs, and data. | INF-07 | `.gitignore`, CI secret scan | Tracked-file audit and zero-match secret scan |
| REQ-INF-08 | Preserve the executed naming resolution: Shaurya denotes only this module. | INF-08, D1, D2, D6 | Repository/package metadata | Name/remote/path audit output |
| REQ-INF-09 | Use semantic versioning, a changelog, and tagged releases from the first implementation release. | INF-09, D5 | `CHANGELOG.md`, release tooling | Tag/package-version consistency test |
| REQ-INF-10 | Enforce in CI that Shaurya never imports from or branches on a strategy. | INF-10, D5 | CI dependency scanner | Deliberate-violation fixture rejected by CI |

## Outputs and acceptance tests

- Installable Python wheel/sdist and consumable CMake package.
- Reproducible Python and C++ test reports.
- Release tag, changelog entry, and package versions that agree.
- CI proves the one-way dependency rule and rejects tracked secret-shaped material.
- Acceptance requires verification of the exact private remote, branch, commit, and push; “built locally” is not “released.”

## Exclusions

- Strategy-specific code, configuration branches, or deployment assumptions.
- Credential values inside the repository.
- Live-order authorisation; INF can validate security posture but cannot grant trading authority.
- Domain parity logic owned by SUR/GRK/RSK/BKT/NAT.

## Deferred items

- INF-02 through INF-07, INF-09, and INF-10 remain implementation work. No design decision is deferred.
