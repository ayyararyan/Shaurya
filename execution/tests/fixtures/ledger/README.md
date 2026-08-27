# Ledger fixtures

Ledger tests generate deterministic records beneath `/private/tmp` so filesystem identity,
permissions, locking, truncation, and fsync behavior are exercised rather than mocked.
