# Execution contract and routing error codes

All errors are stable, non-secret machine codes. Parsers must not echo rejected documents, broker
responses, authentication material, or filesystem contents.

## JSON and contract errors

| Code | Meaning |
|---|---|
| `packet_too_large` | Input exceeds the declared one-MiB contract bound. |
| `invalid_utf8` | Input is not canonical valid UTF-8. |
| `duplicate_field` | An object contains the same key more than once. |
| `unknown_field` / `missing_field:<name>` | Exact-schema field-set violation. |
| `unsupported_version` | `schema_version` is not `1.0.0`. |
| `integer_required` / `unsigned_integer_required` / `integer_overflow` | Numeric representation or range is invalid. |
| `invalid_uuid` | UUID is not lowercase canonical `8-4-4-4-12` text. |
| `invalid_instrument` | Canonical instrument syntax, date, positive strike, or normalized strike text is invalid. |
| `invalid_expiry` | Intent expiry is not strictly later than creation. |
| `invalid_action`, `invalid_order_fields`, `invalid_cancel_fields`, `invalid_target` | Action variant invariants failed. |
| `secret_field` | Event payload includes a forbidden secret-shaped key. |

## Routing errors

Every routing error is operationally `NO ORDER`.

| Enum | Meaning |
|---|---|
| `Stale` | Snapshot or manifest date differs from the required trading date. |
| `Missing` / `Partial` | Neither file exists, or only one member of the pair exists. |
| `Malformed` / `Unsupported` | Strict schema, canonical encoding, bounds, or version failed. |
| `Duplicate` | Canonical ID, token, or route tuple is not unique and ordered. |
| `Tampered` | Digest, size, filename, universe, provenance, or paired content disagrees. |
| `Unsafe` | Input is not a regular current-user-owned `0600`-equivalent file. |
| `NotFound` | The verified snapshot has no exact requested canonical ID or token. |

## Ledger and replay errors

Ledger errors never include rejected bytes or paths. Append exceptions additionally expose
`NotWritten`, `Uncertain`, or `Durable` and the factual number of bytes written.

| Code family | Meaning |
|---|---|
| `ledger_unsafe_*`, `ledger_identity_changed` | Ownership, permissions, regular-file, hard-link, symlink-ancestor, or device/inode checks failed. |
| `ledger_locked` | Another cooperating writer owns the segment. |
| `ledger_record_size`, `ledger_segment_too_large` | A line or segment exceeded its fixed bound. |
| `ledger_truncated_tail` | A valid prefix is followed by a plausible syntactically incomplete canonical ledger-record prefix. |
| `ledger_invalid_truncated_prefix`, `ledger_missing_final_newline` | The non-newline tail is malformed, unrelated JSON, or complete and is not repairable. |
| `ledger_sequence_mismatch`, `ledger_duplicate_event_id`, `ledger_chain_mismatch`, `ledger_hash_mismatch`, `ledger_noncanonical_record` | Append-only chain evidence is inconsistent. |
| `ledger_write_failed`, `ledger_fsync_failed`, `ledger_injected_failure` | Persistence did not return ordinary success; inspect the durability boundary and verify before action. |
| `replay_*`, `FSM_*` | Verified evidence violates a deterministic reducer or order-lifecycle invariant. |
| `idempotency_*` | A supplied durable intent/safety incident is not correlated to the semantic intent. |
| `repair_*` | Explicit repair preconditions, active-segment exclusion, read-only evidence, copy verification, or durability failed. |
