# Shaurya parity harness

`shaurya-parity-harness` is a hermetic, test-only Section 07 executable. It links the actual
Shaurya execution controls and paper broker. It has no live mode or network transport.

## Attestation

`shaurya-parity-harness version` writes one canonical JSON object followed by one line feed. The
closed object contains `build_sha256`, `client_contract_sha256`, `contract_schema_sha256`,
`executable`, `model_versions`, `protocol_version`, `schema_version`, and `source_commit`. Digests are 64 lowercase hexadecimal
characters and the source commit is 40 lowercase hexadecimal characters. The build digest is
computed from the opened running executable; it is not read from an environment variable or status
file.

## Scenario invocation

```text
shaurya-parity-harness run --fixture ABSOLUTE_FIXTURE --output ABSOLUTE_NONEXISTING_OUTPUT
```

The fixture and output paths must be absolute and lexically normalized. Every path component is
opened without following symbolic links. The fixture and its sibling `MANIFEST.sha256` must be
regular, owned by the invoking user, and not writable by group or other. The manifest is a sorted,
duplicate-free list of lowercase SHA-256 entries in `DIGEST<two spaces>BASENAME` form. The
fixture's entry and bytes must agree. Output is written to a protected temporary inode, synced, and
published by a same-directory no-overwrite hard link with mode `0600`; overwrite is refused.

The fixture is canonical JSON followed by exactly one line feed. Its closed root has:

```text
execution_session_id, mapping_timestamp_ns, mode, model, risk_configuration, routes,
routing_snapshot_digest, scenario_id, schema_version, steps, strategy_id, strategy_run_id,
trading_date
```

`schema_version` is `1.0.0`, `mode` is exactly `shadow`, and `model` is exactly `d51_proxy_v1` or
`scripted_v1`. The risk configuration, routes, strategy-book observations, and order intents use
their current strict Shaurya contracts. The ordered step union is closed:

- `{"book": StrategyBookObservation, "kind": "observation"}`
- `{"intent": OrderIntent, "kind": "intent"}`
- `{"kind": "scripted_updates", "updates": [...]}` where each update has
  `cumulative_filled_quantity`, `intent_id`, `kind`, `timestamp_ns`, and `update_id`
- `{"kind": "safety_stop", "reason": ...}`
- `{"kind": "ipc_loss", "peer_role": "market_publisher" | "strategy_client"}`
- `{"kind": "market_session_cutoff", "timestamp_ns": POSITIVE_MONOTONIC_NS}`
- `{"kind": "restart"}`

Scripted update kinds are `partial_fill`, `fill`, `reject`, `session_loss`, and `ambiguous`.
Scripted updates are accepted only under `scripted_v1`. `d51_proxy_v1` uses the real conservative
paper rule: a later qualifying cross with a volume advance fills the entire remainder. A restart
reopens and verifies the authoritative execution ledger and restores the actual paper snapshot; the
first post-restart observation is baseline-only for a restored working order.

`market_session_cutoff` is a distinct terminal transition. The harness derives the exact
`market_session_cutoff` reason; the fixture cannot supply or alter it. The transition advances the
scenario clock and factually ends with `safety_stopped=true` and `session_ready=false`.

On success the harness writes one canonical JSON result plus one line feed and emits only:

```text
[SHAURYA_PARITY_OK] fixture_sha256=LOWERCASE_SHA256
```

The closed result contains `actions`, `build_sha256`, `contract_schema_sha256`, `events`,
`client_contract_sha256`, `final_state`, `fixture_sha256`, `fills`, `incidents`, `intents`, `inventory`, `model_version`,
`protocol_version`, `scenario_id`, `schema_version`, and `source_commit`. Arrays remain in
authoritative scenario/ledger order; price, quantity, canonical instrument, fill evidence, inventory,
and terminal state are never normalized away.

Each scripted update is applied separately using its own timestamp. `inventory` records a protected
snapshot after every normal step and after every individual scripted update with exact `boundary`,
`step_index`, `substep_index`, and `timestamp_ns` coordinates. `incidents` is an ordered array of typed objects with
`code`, `event_sequence`, `incident_type`, `severity`, and `timestamp_ns`; broker/session loss, IPC
loss, ambiguity, late contradictory rejection, explicit safety stops, and market cutoffs are factual
successful scenario results rather than harness errors.

The canonical [aggregate client contract](../contracts/v1/parity_client_contract.json) binds the
OrderIntent, ExecutionEvent, risk-decision, routing-snapshot, and routing-manifest artifacts plus the
strict StrategyBook, risk-configuration, harness step/result, inventory/incident, and PaperBroker
model semantics. Its exact byte digest is compiled into both `version` and every result.

The manifested corpus contains 17 scenarios and covers all 12 required families: no action, working
ACK, conservative complete fill, duplicate/out-of-order update idempotency, modify, cancel and
partial-fill race, token-change cancel/place, unauthorized and authorized exact-token SELL, reject,
ambiguity, broker/IPC loss, explicit safety stop, restart/no-overfill, and market cutoff.

Any usage, path, manifest, schema, field, correlation, time, live-mode, model, broker, replay, or
output failure exits `2`, writes no result, and emits one bounded non-secret refusal marker to stderr.
