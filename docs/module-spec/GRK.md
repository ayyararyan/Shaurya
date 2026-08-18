# GRK — Pricing and Greeks

## Objective

Provide robust European-option pricing internals, parity-derived forwards, IV inversion, and a single strategy-facing API for surface-consistent Greeks.

## Object and identification ledger

| Object | Category | Boundary |
|---|---|---|
| Option prices, strikes, expiries, and listed futures | Observed | Supplied by DAT with timestamps and identity. |
| Put-call-parity forward | Deterministically derived | Primary forward for each expiry; a listed future is only a cross-check where one exists. |
| Inverted per-strike IV | Estimated numerical solution | Internal machinery; failures must be explicit. |
| Fitted-surface Greeks | Estimated / deterministically derived from an estimated surface | The sole strategy-facing Greeks object. Its surface-estimation status must remain visible. |

Per-strike inverted-IV Greeks are not exposed because they are mutually inconsistent across strikes by construction. American/single-stock exercise effects are outside the identified object.

## Architecture and contracts

- Consumes SUR's `CON-03` surface frame and DAT option-chain observations identified by `CON-05`.
- Produces surface-consistent Greek fields for RSK, SIG, and ANL.
- Python is the specified implementation surface; no duplicate live-path Greek implementation is currently authorised.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-GRK-01 | Port the tested Greeks module as internal machinery only. | GRK-01 | TBD `src/shaurya/greeks/core.py` | Port/regression/reference-value tests |
| REQ-GRK-02 | Expose only Greeks computed consistently from the fitted surface to strategies. | GRK-02 | TBD `src/shaurya/greeks/surface.py` | Cross-strike consistency tests; Greek frame |
| REQ-GRK-03 | Construct the forward from ATM put-call parity within each expiry and use a matching listed future only as a cross-check. | GRK-03 | TBD `src/shaurya/greeks/forwards.py` | Weekly/monthly and cross-check fixtures; forward record |
| REQ-GRK-04 | Implement bracketed European IV inversion with explicit no-solution and deep-ITM/OTM failure handling. | GRK-04 | TBD `src/shaurya/greeks/iv.py` | Round-trip, boundary, no-solution tests; failure record |

## Outputs and acceptance tests

- Expiry-specific forward records with method and optional listed-future discrepancy.
- Surface-consistent Greek frames with source surface/version/timestamp.
- Reference-value, finite-difference, inversion round-trip, and failure-path tests.
- Acceptance rejects silent NaNs and any strategy-facing use of per-strike-IV Greeks.

## Exclusions

- American exercise and single-stock options.
- Treating a listed monthly future as the forward for unmatched weekly expiries.
- A strategy-facing per-strike inverted-IV Greek API.
- Strategy-specific pricing or hedging rules.

## Deferred items

- American/single-stock support is deferred until a concrete strategy requires it; no current GRK task is otherwise deferred.
