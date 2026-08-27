# Synthesized Specification: Shaurya Execution Control Plane

Build `execution/` as Shaurya's third independently runnable project and migrate D51 into its first
shadow client. Data remains the sole market-data plane and Dhan source. Research remains execution-
free. Kotak remains the sole future execution broker, but live routing is default-OFF, unusable in
ordinary builds, and untested against a real account.

Deliver strict versioned OrderIntent, ExecutionEvent, RiskDecision, PositionSnapshot, and
MarketObservation contracts; a date-stamped, hash-protected routing snapshot; a generic C++20
executor with idempotency, FSM, risk, append-only ledger/replay, reconciliation, paper adapter,
dormant Kotak adapter, session composition, and bounded local IPC; and a portable manifest-driven
`kotak` CLI with offline doctor, dry-runs, isolated installer/update/rollback/uninstaller tests, and
one-shot attestation fixtures.

D51 must emit neutral intents and consume execution events through the local contract. The new
shadow route becomes default after frozen parity tests pass. The legacy route remains an explicit
rollback option and live-disabled. D51 surface/model/policy/research code stays in D51.

All parsing is strict and bounded. All approvals/rejections become deterministic decisions and
ledger events. Position mismatch, stale/tampered mapping, stale data, ambiguous submission, session
loss, queue overflow, kill switch, or unreconciled state blocks new orders. Paper evidence can never
be reported as broker-confirmed.

No credential value, private key, TOTP, runtime state, build/cache artifact, raw response body, or
personal absolute path may be committed or logged. Stable credentials remain remote. No real home
installation, broker authentication, order, cloud, or service action is permitted.

Completion requires comprehensive unit, integration, regression, parity, portability, negative-
control, diff, and secret scans; logical commits in both repositories; pushes to the exact `codex/`
branches; and remote-head verification. Data and Research must have zero changed files.
