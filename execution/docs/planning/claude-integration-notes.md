# Independent Review Integration Notes

## Integrated

- Corrected the dependency graph to allow only the offline Execution exporter to use Data's public
  API while keeping runtime and reverse dependencies forbidden.
- Added the exact shadow topology and readiness sequence, with Data as observation authority and no
  implicit Kotak authentication in the new shadow command.
- Added durable pre-call ordering, pre/post broker-call ledger failure behavior, and the
  reconcile-never-resubmit invariant.
- Replaced automatic truncated-tail recovery with fail-closed startup and evidence-preserving
  new-segment repair.
- Made parity mismatches block default migration and completion unless the user later approves.
- Added three-authority position semantics, full order/trade/position reconciliation, operator and
  device audit fields, exact alias behavior, and the requested safety/portability tests.

## Not integrated verbatim

- The plan does not duplicate full schema tables, FSM matrices, and traceability tables because the
  frozen implementation specification in section 01 owns them. The plan now freezes the decisions
  needed to write those tables without becoming implementation code.
- No external CMake fetch is promised. Tool discovery prefers installed or bundled CMake; any
  one-time ephemeral bootstrap is an environment step, never a test-suite network dependency.
