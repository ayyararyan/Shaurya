# DAT — Market data

## Objective

Own Dhan-only market-data ingestion, broker-neutral identity, historical bars, option-chain validation, data-quality accounting, permanent raw-tape recording, and deterministic replay. DAT supplies the canonical observed input to SIG, BKT, SUR, GRK, VOL, and ANL; it never places orders (D7, D17, D18).

## Object and identification ledger

| Object | Category | Meaning / boundary |
|---|---|---|
| Dhan packet bytes, prices, quantities, per-level order counts, OI, and packet fields | Observed | Observed exactly when present in the wire packet. Bid and ask deep-book sides arrive separately. |
| Receive timestamp and receive-side sequence | Observed locally / deterministically assigned | Establish local arrival order, not exchange event order. |
| Exchange timestamp | Observed when the packet type carries it | Structurally unavailable on several Dhan packet types; absence is explicit, never imputed. |
| Source sequence | Unidentified from current Dhan v2 layouts | The feed exposes no source sequence. Reconnect-boundary gaps and receive continuity are detectable, but silent source loss between packets is not fully identifiable. |
| Joined 20/200-level book | Deterministically derived | Constructed from separately received bid/ask packets and flagged partial until both sides are available. |
| Instrument mapping | Deterministically derived from a date-stamped broker master | Valid only for the master date; refreshed daily when the module is in use. |
| Packet rate, payload size, subscription behaviour | Observed measurement | Valid for the measured instruments/windows; not a universal capacity guarantee. |
| True order identity, queue rank, per-order lifetime, cancellation attribution | Unidentified | Aggregated depth has no order IDs. Per-level order count does not close this boundary. |

Every tape row retains its `CON-06` category and data-quality flags. Missing protocol fields remain missing; no timestamp, source sequence, or order identity is silently proxied.

## Architecture and contracts

- Dhan is the sole receive source. Kotak is order-placement only; Kite is absent (D17, D18).
- Produces `CON-01` canonical tape rows and `CON-08` run manifests; consumes and refreshes `CON-05` instrument identity.
- One tape format serves live capture, research, and deterministic replay. Replay must reproduce ordering and quality semantics, not merely parse the same file.
- Current Python implementation lives in `src/shaurya/data/` and `src/shaurya/contracts/`; the production C++ order path consumes canonical outputs through contracts and does not duplicate Dhan ingestion.
- GCP scaling, where used, applies only to DAT → SIG → BKT → ANL. It does not move EXE/RSK/NAT off their latency-sensitive Kotak/AWS path.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-DAT-01 | Maintain one reconciled market-data-only Dhan client based on Mushin's structure plus Shoshin's retry, pacing, and normalization behaviour; document rejected unsafe/strategy-specific paths. | DAT-01, D7 | `src/shaurya/data/dhan_client.py`; `docs/DAT_01_RECONCILIATION.md` | `tests/test_dhan_client.py`; reconciliation record |
| REQ-DAT-02 | Stream Dhan standard Full/5-level and 20-level feeds with parsing, reconnect/resubscribe, heartbeat, gap semantics, metrics, and per-enabled-channel acceptance. | DAT-02, D16 | `src/shaurya/data/dhan_stream.py`, `src/shaurya/cli/capture_dhan.py` | `tests/test_dhan_stream.py`; capture tape/metrics/manifest |
| REQ-DAT-03 | Fetch bars/coarser historical data and store it under a stable on-disk schema; never describe it as tick history. | DAT-03, D16 | TBD `src/shaurya/data/historical.py`, storage module | Historical schema/round-trip/gap tests; bar store |
| REQ-DAT-04 | Fetch and validate option chains against canonical instrument identity. | DAT-04 | TBD `src/shaurya/data/option_chain.py` | Validation fixtures; option-chain artifact |
| REQ-DAT-05 | Record full configured depth append-only and replay the exact canonical tape deterministically across live, research, and backtest consumers. | DAT-05, D12 | `src/shaurya/data/tape.py`; TBD replay module; `src/shaurya/contracts/tape.py` | `tests/test_contracts_and_tape.py`; replay determinism test; tape artifact |
| REQ-DAT-06 | Surface crossed-book, stale-quote, invalid-depth, and gap counters rather than silently dropping affected rows. | DAT-06 | Metrics in `src/shaurya/data/dhan_stream.py`; TBD audit output | Counter-injection tests; collector-audit artifact |
| REQ-DAT-07 | Refresh Dhan and Kotak instrument masters daily when in use and maintain the mapping layer; Kotak mapping is for routing, not data. | DAT-07, D17, D18 | `src/shaurya/contracts/instruments.py`; TBD master loader | Stale-master and cross-broker mapping tests; dated master manifest |
| REQ-DAT-09 | Record the NSE index-F&O universe (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) under an explicitly tiered depth plan and permanent retention, while leaving the exact strike-band width and final socket plan unset until live capacity work closes. | DAT-09, D12 | Capture configuration; `scripts/dat09_concurrency_probe.py` | Capacity evidence, universe manifest, retention-policy field |
| REQ-DAT-10 | Capture 200-level depth through its distinct endpoint and flat subscription message, preserving up to 200 bid and 200 ask levels. | DAT-10 | `src/shaurya/data/dhan_stream.py`, `src/shaurya/cli/capture_dhan.py` | `tests/test_dhan_stream.py`; 200-level tape and manifest |
| REQ-DAT-11 | Bisect the exact 20-level per-message instrument ceiling with a live read-only binary-search probe. | DAT-11 | `scripts/dat09_concurrency_probe.py` | Dated per-probe acceptance table and exact supported ceiling |
| REQ-DAT-12 | Test whether a fresh socket reconnect resets the one-honoured-message behaviour or whether the limit is account/session scoped. | DAT-12 | `scripts/dat09_concurrency_probe.py` | Reconnect experiment artifact with packet-by-instrument evidence |
| REQ-DAT-13 | Run a 200-level same-liquidity control across comparably liquid instruments to distinguish liquidity from subscription-order throttling. | DAT-13 | `scripts/dat09_concurrency_probe.py` | Controlled packet-count comparison and conclusion |

Dropped task DAT-08 has no requirement: Kotak market-data reception is excluded by D18.

## Current DAT-09 working constraint — measured, not final

- **20-level socket behaviour:** only the first subscription message on a socket produced data in the 2026-08-18 tests; later messages were silently ignored even with pacing.
- **Measured per-message band:** **52 instruments worked; 206 instruments failed outright.** The exact ceiling is unknown and must not be invented. Until REQ-DAT-11 closes, this is a measured-not-final operating constraint, not a capacity constant.
- **200-level evidence:** at least five concurrent subscriptions on one socket produced packets, but the first instrument received far more packets. Whether this was ordinary liquidity or a throttle is unresolved.
- **Retention:** permanent. Once captured, raw data is kept; there is no rolling deletion or expiry window.
- **Universe:** NSE index F&O only—NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY. Single-stock depth and BSE deep book are out of current scope. Exact depth-tier strike bands such as ATM±7 remain illustrative, not committed.

## Outputs and acceptance tests

- Versioned append-only JSONL (and later stable columnar storage) conforming to `CON-01`, plus a `CON-08` manifest, hashes, metrics, and quality audit.
- Acceptance is per enabled channel: a connected socket and successful heartbeat with zero packets is a failure, not success.
- Parser fixtures cover standard packet subtypes, separate deep-book sides, partial books, 20/200-level layouts, and the 200-level flat subscription envelope.
- Reconnect tests preserve a visible gap boundary and resubscribe semantics.
- Deterministic replay produces the same ordered rows, quality flags, and consumer-visible events from the same tape.
- Existing evidence remains scoped: DAT-01 is Tested; DAT-02 and DAT-10 are Live verified; DAT-05 is Live verified only for its append-only writer slice, with deterministic replay still unimplemented.

## Exclusions

- Dhan or Kite order placement (D7, D17).
- Kotak market-data ingestion (D18; DAT-08 dropped).
- Tick-history claims for DAT-03 bars.
- True order identity, FIFO rank, per-order lifetime, or cancellation attribution.
- Single-stock order-book capture; BSE deep-book capture; committed SENSEX/BANKEX infrastructure.
- Any invented exact 20-level ceiling, exact connection count, or strike-band width.

## Deferred and open items

- **DAT-11 / 2026-08-19 first task:** bisect the exact 20-level ceiling within the measured 52-worked/206-failed band.
- **DAT-12:** determine whether reconnect resets the first-message-only behaviour.
- **DAT-13:** resolve the 200-level liquidity-versus-throttle skew.
- **DAT-09:** derive the exact depth bands and connection-count plan only after those measurements; retention is already permanently settled.
