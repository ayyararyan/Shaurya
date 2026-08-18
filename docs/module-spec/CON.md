# CON — Shared contracts

## Objective

Define the versioned schemas and semantic conventions that keep Python, C++, live capture, replay, risk, execution, and analytics in agreement. Contracts are built before their consumers because late schema drift would invalidate downstream evidence.

## Object and identification ledger

`CON-06` is normative across the module:

| Category | Contract meaning |
|---|---|
| Observed | Present directly in an authoritative source, such as a broker response or feed packet. |
| Deterministically derived | Computed from observed fields without fitting. |
| Estimated | Obtained from a fitted statistical or numerical model. |
| Scenario | Produced under an explicit counterfactual or parameter assumption. |
| Proxy | An imperfect observable or simulation standing in for an unavailable target. |
| Unidentified | Not recoverable from the available data without additional information or assumptions. |

Labels must survive serialization and downstream transformations. An estimated or proxy value never becomes observed merely because it is written to a canonical schema.

## Architecture and contracts

- `CON-01`: snapshot/tape rows used by DAT, SIG, BKT, EXE fill modelling, and NAT replay.
- `CON-02`: append-only execution ledger consumed by ANL and parity-tested replay.
- `CON-03`: surface frames used by SUR, GRK, ANL, and live staleness controls.
- `CON-04`: one config schema consumed by Python and C++, including risk definitions and credential handles.
- `CON-05`: broker-neutral instrument identity with Dhan and Kotak mappings only (D17, D18).
- `CON-06`: object-category labelling.
- `CON-07`: exchange, receive, and decision timestamps in IST with explicit causality.
- `CON-08`: unique run IDs and append-only manifests; invalidated runs remain preserved.
- `CON-09`: strategy-independent opportunity/finding records required by D8.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-CON-01 | Version a snapshot/tape schema containing BBO, full configured depth, timestamps, sequences where available, and explicit quality flags. DAT-14 classified-print rows additionally retain price, last quantity, cumulative-volume increment, the BBO and BBO-leg receive timestamps actually used, quote age/freshness bound, inferred side, classifier/alignment versions, degradation reason, and coalesced flag. | CON-01, DAT-14, D24 | `src/shaurya/contracts/tape.py` | Round-trip/schema/version tests; legacy `1.0.0` load test; canonical tape row |
| REQ-CON-02 | Version an append-only ledger schema covering placement, execution, cancel/reject, cycle P&L, order role, quote/fill prices, age, book state, K, and break-even spread. | CON-02 | `src/shaurya/contracts/ledger.py`; future C++ consumer under EXE-05/NAT | Schema/version/event validation and golden-fixture round trip; canonical ledger row |
| REQ-CON-03 | Version a surface-frame schema carrying parameters, fit diagnostics, age, and staleness. | CON-03 | `src/shaurya/contracts/surface.py`; future C++ consumer under NAT | Schema/version/age/staleness validation and golden-fixture round trip; surface frame |
| REQ-CON-04 | Define one config format consumed by Python and C++, including credential handles and shared limit definitions. | CON-04 | `src/shaurya/contracts/config.py`; future C++ parser under INF-03/NAT | Python accepts/rejects committed golden fixture; same fixture reserved for C++ parity |
| REQ-CON-05 | Define one internal instrument identity with date-stamped Dhan `security_id` and Kotak order-routing token mappings; exclude Kite. | CON-05, D17, D18 | `src/shaurya/contracts/instruments.py` | Dhan/Kotak mapping fixtures; unmapped-ID and stale-date failures |
| REQ-CON-06 | Carry object-category labels through every applicable artifact and transformation. | CON-06 | `src/shaurya/contracts/categories.py`; fields in ledger/surface/finding contracts | Label-preservation and invalid-label tests |
| REQ-CON-07 | Distinguish exchange, receive, and decision timestamps; use IST and reject future-information consumption. | CON-07 | `src/shaurya/contracts/timing.py`; composed into ledger/surface/finding contracts | Causality-violation and timezone tests |
| REQ-CON-08 | Issue unique sortable run IDs and append-only manifests with hashes, lifecycle events, and preserved invalidation state. | CON-08 | `src/shaurya/contracts/artifacts.py` | Collision, append-only, hash, invalidation tests; run manifest |
| REQ-CON-09 | Define a strategy-independent finding record containing window, statistic, magnitude, uncertainty, search context, and object-category label. | CON-09, D8 | `src/shaurya/contracts/findings.py` | Schema/causality/label and golden-fixture tests; finding artifact |

## Outputs and acceptance tests

- Machine-readable versioned schemas plus human-readable field definitions.
- Golden fixtures consumed by both languages where a contract crosses the boundary.
- Backward-incompatible changes require a schema version and release/changelog entry.
- Missing timestamps, mappings, labels, or data-insufficient states are explicit, never coerced to zero.
- Existing live-verified slices (`CON-01`, Dhan slice of `CON-05`, `CON-08`) retain their evidence;
  the CON-01 DAT-14 extension is schema `1.1.0`, accepts retained `1.0.0` rows, and is Dry-run
  verified rather than Live verified. Unfinished slices do not inherit another slice's status.

## Exclusions

- Business logic, model fitting, broker calls, or strategy logic.
- Kite identity or execution (D17).
- Kotak market-data fields (D18); Kotak appears only as order-routing identity.
- Treating a schema as proof that its producer is correct.

## Deferred items

- C++ consumers of the committed ledger, surface, and config golden fixtures remain forward
  implementation under INF-03/NAT/EXE-05; the Python contracts and shared JSON shapes are tested.
