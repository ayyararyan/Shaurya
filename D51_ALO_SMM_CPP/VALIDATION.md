# D51 ALO-SMM package validation

Release: **0.1.1-shadow**  
Validation date: **25 August 2026**.

## Build and safety state

Validated as a C++20 Release build with `ALO_ENABLE_LIVE_ROUTER=OFF`. The source contains the real Kotak place/modify/cancel path for later use, but this release's normal build script compiles the live gate OFF. `mode=live` therefore fails before broker authentication even if a runtime acknowledgement is present.

The AWS build is source-first: `scripts/build_release.sh` rebuilds on the target host with `-O3`, host-native CPU tuning, and IPO/LTO when supported.

## Automated checks

The clean Release build passes:

- `test_surface` — leave-target-strike-out surface/pricing sanity;
- `test_policy` — cold-start and action-selection behavior;
- `test_long_only` — hard nonnegative inventory, including cross-token protection (owning one CE cannot authorize selling another CE strike);
- `test_sfeed_decoder` — native-batch 7208 market-picture/depth decoding and packet-relative depth offsets;
- `test_order_update` — tolerant parsing of the current order-update fields used by the dormant live reconciliation path.

`alo-smm --self-test` passes a direct sell-without-inventory rejection. A negative-control launch with `mode=live` and the normal shadow build fails closed with `LIVE BLOCKED`.

## Shadow-label integrity

The counterfactual fill rule was hardened during final QA. A quote can be labelled from LTP only when cumulative option volume increased **after** the hypothetical order was placed; an old/stale LTP cannot create a fill. Book cross-through remains the other conservative fill condition. This avoids fabricating queue fills from stale prints.

## Inventory and ATM-roll integrity

Inventory is keyed by the exact option token, not merely CE/PE. While any shadow/live inventory exists, the engine pins the quoted strike. If the desired token changes, the dormant live router cancels the old working order and places a new one; it never modifies a working order into a different instrument.

## Current Kotak interface alignment

Checked against the actively maintained official `kotak-neo-python` SDK on 25 August 2026:

- TOTP login + MPIN validation and dynamic post-login order `baseUrl`;
- current post-login order headers: consumer `Authorization`, edit `Sid`, edit `Auth`, form-urlencoded body;
- place/modify/cancel paths and field names used by the current SDK family;
- SFeed `native_batch`, full-depth subscription, and market-picture 7208 decoder;
- order/position WebSocket field names used for partial/complete fill reconciliation;
- static-IP and API-rate assumptions documented in `docs/CURRENT_API_NOTES_2026-08-25.md`.

## Operational checks

- shell scripts pass `bash -n`;
- `prepare_instruments.py` compiles and was exercised on a synthetic Kotak-like derivative master;
- `scripts/preflight_shadow.sh` fails closed on dummy tokens, missing futures token, missing secrets, non-shadow mode, or accidentally exported live acknowledgements;
- the service launches through `scripts/run_shadow.sh`, so each run snapshots non-secret provenance;
- the month bundle excludes `.env`, credentials, logs, build outputs, and raw market data.

## Deliberate live blockers

The live path now parses order updates and can reconcile incremental/partial fills into token-level inventory, but it has **not** been validated against this user's real Kotak account stream or contract notes. Automatic startup broker-position reconciliation, daily/max-loss controls, and the final network-loss/cancel-all validation are deliberately left as mandatory post-shadow tasks in `docs/LIVE_ENABLEMENT_CHECKLIST.md`.

The operator `ALO_LIVE_START_FLAT_ACK` is only an attestation; it is not a substitute for broker-position reconciliation. Do not live-enable this shadow release.
