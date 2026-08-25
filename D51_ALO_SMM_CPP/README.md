# D51 ALO-SMM
## Adaptive Long-Only Surface Market Maker — C++ Shadow Engine

`D51 ALO-SMM` is a long-only NIFTY-options liquidity engine designed for the Kotak Neo Trade API. It may **buy** passive option inventory and later **sell only inventory already owned**. Negative option inventory is a hard invariant.

This release is intended for a one-month AWS shadow study. It contains real Kotak authentication, SFeed market-data decoding and a live place/modify/cancel router, but the shipped/default build configuration sets the live-enablement compile-time gate **OFF**. The live router implementation remains in the source tree; the executable refuses live mode unless it is deliberately rebuilt and both runtime gates are satisfied.

## Research thesis encoded in the engine

The D51 tape indicated that touching the best bid was adversely selected, while wider passive acquisition around 0.15–0.40 option points behind touch was more promising, especially in ATM puts. A leave-target-strike-out smile/surface was the strongest fair-value signal; option depth imbalance helped local microprice; futures OFI and synthetic-forward displacement were more useful as toxicity/skew context than as standalone directional signals. Those results are treated as priors, not production truth.

The engine therefore learns the spread rather than fixing it. For each `CE/PE × BUY/SELL × offset`, it estimates:

- `P(fill | state, offset)` with online logistic SGD;
- `E(delta-hedged markout | fill, state, offset)` with online ridge/SGD;
- calibration error and realized counterfactual EV with exponentially weighted updates.

Every second the policy scores `OFF/HOLD` and offsets `0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50`. A side is disabled when expected value is not positive enough, surface/feed quality fails, inventory constraints fail, or its rolling counterfactual EV falls through the kill threshold.

## Quick start on Ubuntu/AWS

```bash
unzip D51_ALO_SMM_v0.1.1-shadow-AWS.zip
cd D51_ALO_SMM_CPP
./scripts/bootstrap_ubuntu.sh
./scripts/build_release.sh
cp .env.example /tmp/alo-smm.env
# edit /tmp/alo-smm.env, then install it as root with chmod 600
```

Prepare a real current option chain in `config/instruments.csv` and set the current front NIFTY futures token in `config/alo_smm.json`; the checked-in tokens are deliberately fake examples.

Run a local safety check:

```bash
./build/alo-smm --config config/alo_smm.json --self-test
```

Run shadow mode (the preflight refuses dummy tokens, a zero futures token, missing credentials, live mode, or live acknowledgement variables):

```bash
set -a; source /etc/alo-smm/alo-smm.env; set +a
./scripts/preflight_shadow.sh
./scripts/run_shadow.sh
```

For persistent AWS operation use `systemd/alo-smm.service`; see `docs/AWS_DEPLOYMENT.md`.


## Execution architecture

The hot path is intentionally simple: WebSocket decoding feeds a preallocated SPSC ring; one strategy thread owns books, surface state, models and inventory; a separate statistics thread handles disk output. The dormant live router has its own SPSC queue and persistent HTTP/2-capable REST handle. No disk I/O, JSON parsing or mutex-protected statistics sit in the quote-decision hot path.

Inventory is keyed by the exact instrument token. If ATM moves while inventory exists, the engine pins the held strike; a later live router would cancel/re-place rather than modify an order into another token.

## What is retained each day

No raw full-depth tape is intentionally archived. The engine keeps:

- selected shadow decisions;
- a sampled compact state/action/outcome table;
- conservative counterfactual fill/markout aggregates for **all** quote offsets;
- shadow fills and inventory path;
- feed/surface health metrics;
- online model state.

At month end run `scripts/month_bundle.sh`. That ZIP is the compact dataset needed to judge whether spread/skew learning persisted out of sample.

## Safety model

Live order placement requires all of the following:

1. rebuild with `-DALO_ENABLE_LIVE_ROUTER=ON`;
2. set `mode` to `live`;
3. set the exact live-order acknowledgement environment value;
4. set the separate startup-flat acknowledgement only after broker positions have been reconciled.

The distributed build uses `ALO_ENABLE_LIVE_ROUTER=OFF`. Do **not** rebuild live during the shadow month. Before any later live test, complete `docs/LIVE_ENABLEMENT_CHECKLIST.md`, including reconciliation of actual order/fill events against Kotak contract notes.

## Package map

- `include/alosmm/`, `src/` — C++20 engine
- `config/` — shadow policy and instrument examples
- `scripts/` — build, AWS launch, instrument preparation and month bundle
- `systemd/` — service unit plus optional weekday shadow timer
- `tests/` — surface, decoder, order-update, policy and no-short invariant tests
- `docs/STRATEGY.md` — trading logic
- `docs/MODEL_AND_STATS.md` — learning and retained statistics
- `docs/KOTAK_NEO_SETUP.md` — current API/session/feed assumptions
- `docs/AWS_DEPLOYMENT.md` — deployment
- `docs/OPERATIONS_RUNBOOK.md` — daily operations
- `docs/LIVE_ENABLEMENT_CHECKLIST.md` — deliberately strict later-stage gate
