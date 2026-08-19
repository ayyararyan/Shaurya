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
| REQ-DAT-03 | Fetch bars/coarser historical data and store it under a stable on-disk schema; never describe it as tick history. | DAT-03, D16 | `src/shaurya/data/historical.py` | `tests/test_historical.py`; versioned immutable bar store and gap audit |
| REQ-DAT-04 | Fetch and validate option chains against canonical instrument identity. | DAT-04 | `src/shaurya/data/option_chain.py` | `tests/test_option_chain.py`; validated option-chain artifact |
| REQ-DAT-05 | Record full configured depth append-only and replay the exact canonical tape deterministically across live, research, and backtest consumers. | DAT-05, D12 | `src/shaurya/data/tape.py`; `src/shaurya/contracts/tape.py` | `tests/test_contracts_and_tape.py`; deterministic replay of synthetic and existing live tapes |
| REQ-DAT-06 | Surface crossed-book, stale-quote, invalid-depth, and gap counters rather than silently dropping affected rows. | DAT-06 | `src/shaurya/data/dhan_stream.py`; `src/shaurya/data/quality.py`; capture CLI | `tests/test_data_quality.py`; versioned collector-quality artifact |
| REQ-DAT-07 | Refresh Dhan and Kotak instrument masters daily when in use and maintain the mapping layer; Kotak mapping is for routing, not data. | DAT-07, D17, D18 | `src/shaurya/contracts/instruments.py`; `src/shaurya/data/instrument_master.py` | `tests/test_instrument_master.py`; dated hash-validated permanent master manifests |
| REQ-DAT-09 | Record the NSE index-F&O universe (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) under an explicitly tiered depth plan and permanent retention, while leaving the exact strike-band width and final socket plan unset until live capacity work closes. | DAT-09, D12 | `src/shaurya/data/capture.py`; `scripts/dat09_concurrency_probe.py` | `tests/test_capture_universe.py`; capacity evidence, universe plan, permanent-retention field |
| REQ-DAT-10 | Capture 200-level depth through its distinct endpoint and flat subscription message, preserving up to 200 bid and 200 ask levels. | DAT-10 | `src/shaurya/data/dhan_stream.py`, `src/shaurya/cli/capture_dhan.py` | `tests/test_dhan_stream.py`; 200-level tape and manifest |
| REQ-DAT-11 | Bisect the exact 20-level per-message instrument ceiling with a live read-only binary-search probe. | DAT-11 | `scripts/dat09_concurrency_probe.py` | Dated per-probe acceptance table and exact supported ceiling |
| REQ-DAT-12 | Test whether a fresh socket reconnect resets the one-honoured-message behaviour or whether the limit is account/session scoped. | DAT-12 | `scripts/dat09_concurrency_probe.py` | Reconnect experiment artifact with packet-by-instrument evidence |
| REQ-DAT-13 | Run a 200-level same-liquidity control across comparably liquid instruments to distinguish liquidity from subscription-order throttling. | DAT-13 | `scripts/dat09_concurrency_probe.py` | Controlled packet-count comparison and conclusion |
| REQ-DAT-14 | Classify positive-volume Quote/Full prints causally on capture with the versioned quote-mid/tick rule, retain every raw classification input and receive timestamp, version the cross-channel alignment rule, mark stale/missing quotes degraded, and flag coalesced intervals without assigning the sign to unseen volume. | DAT-14, D24 | `src/shaurya/data/trade_direction.py`; `src/shaurya/data/dhan_stream.py`; `src/shaurya/contracts/tape.py` | Pure rule tests; alignment/capture-path tests; legacy-schema replay; retained-tape dry run |
| REQ-DAT-15 | Measure the DAT-14 cross-channel alignment error and coalescing empirically from retained tape as distributions and classification flip rates by activity, depth tier, and time of day; never assume the error is small. | DAT-15, D24 | Future DAT analysis code; intentionally not part of DAT-14 | Distribution/flip-rate artifact; market-hours retained tape; Not implemented |

Dropped task DAT-08 has no requirement: Kotak market-data reception is excluded by D18.

## Current DAT-09 working constraint — measured, not final

- **20-level socket behaviour:** DAT-12 discriminates the reproduced 50+50 failure as **socket-scoped**: the second 50-instrument message failed on the occupied socket and succeeded unchanged on a fresh socket. A 2+2 control accepted both messages on one socket, so the effect is load-dependent rather than a universal first-message-only rule.
- **Measured per-message ceiling:** **50 instruments** in the 2026-08-19 live probe. Fresh one-message sockets accepted every tested count through 50 and rejected 51, 52 and 53 wholesale; the prior-day statement that 52 worked did not reproduce and is superseded by the same-day boundary evidence. This is an observed endpoint constraint, not a broker guarantee across future protocol/account changes.
- **200-level evidence:** multiple subscriptions receive at least minimal packets, but DAT-13's order-rotation control shows a genuine first-subscription throttle/bias. With the same four front-month futures, whichever instrument was sent first received 328 packets and each later instrument received 2; max/min skew was 164× in both orderings. This is not explained by ordinary instrument liquidity.
- **Retention:** permanent. Once captured, raw data is kept; there is no rolling deletion or expiry window.
- **Universe:** NSE index F&O only—NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY. Single-stock depth and BSE deep book are out of current scope. Exact depth-tier strike bands such as ATM±7 remain illustrative, not committed.

## Outputs and acceptance tests

- Versioned append-only JSONL (and later stable columnar storage) conforming to `CON-01`, plus a `CON-08` manifest, hashes, metrics, and quality audit.
- Acceptance is per enabled channel: a connected socket and successful heartbeat with zero packets is a failure, not success.
- Parser fixtures cover standard packet subtypes, separate deep-book sides, partial books, 20/200-level layouts, and the 200-level flat subscription envelope.
- Reconnect tests preserve a visible gap boundary and resubscribe semantics.
- Deterministic replay produces the same ordered rows, quality flags, and consumer-visible events from the same tape.
- Existing evidence remains scoped: DAT-01/03/04/07 are Tested; DAT-02 and DAT-10-13 are Live verified; DAT-05 is Dry-run verified end to end (its writer retains earlier live evidence); DAT-06 is Dry-run verified; DAT-09 planning/pooling is Tested.

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

## Trade-direction classification at capture (D24)

Decided 2026-08-19. Buy/sell classification of observed prints happens **on the capture path**, as
packets arrive, and is written into the tape row.

**Why at capture rather than offline.** The capture-time sign is the causally honest label under
CON-07: it uses exactly the quote state the live path held. A sign computed later from the
assembled tape can align a trade with a better-matched quote than the live decision ever had, which
is lookahead. It is also required in real time by any maker logic that reacts to signed flow, and it
satisfies SIG-20's bounded-state forward-pass requirement by construction.

**Signing at capture never replaces raw retention.** The tape row carries all of: last traded price,
last traded quantity, the cumulative-volume increment, the prevailing best bid and ask actually used
for the classification, the relevant receive timestamps, the inferred side, and a **classifier
version stamp**. The classifier may therefore be revised and recomputed offline, and the revised
sign compared against the capture-time one. Storing only the sign would make the classification rule
an irreversible capture-time commitment — the same failure D12 refused for the tape itself. The
choice among quote rule, tick rule and successors is one of D20's swept axes and must remain open.

**Two limitations are encoded, not smoothed over.**

1. *Cross-channel alignment.* Prints arrive on the Quote/Full channel; depth arrives on the separate
   20- and 200-level channels with independent packet clocks. "The quote prevailing before this
   trade" therefore needs an explicit, versioned, tested definition, and the error it introduces is
   measured from retained tape by DAT-15 rather than assumed small.
2. *Coalesced prints.* Dhan reports cumulative volume plus only the **last** traded price and
   quantity. When the volume increment exceeds the last traded quantity, several prints were
   collapsed into one packet and the inferred side applies only to the last observed print. The row
   carries a coalesced flag with the increment and last quantity, so downstream signed-flow measures
   can exclude or explicitly model those intervals instead of attributing one sign to unseen volume.

**Implemented rule versions and alignment semantics.** Classifier
`quote-mid-tick-v1` uses the quote rule first and the tick rule only for an exact midpoint print;
without a prior differing price the explicit result is `unclassified`. Alignment
`latest-complete-depth-before-print-v1` admits a 20- or 200-level channel only after both BBO sides
have been received in its current connection epoch. For each print it selects the complete candidate
whose composite state was updated most recently at or before the print receive time, with channel
name as the deterministic tie-break. The quote's composite receive timestamp is the later BBO-leg
timestamp, while freshness age is conservatively measured from the older leg; both leg timestamps,
the composite timestamp, selected depth tier, age, and configured bound are retained. A crossed,
missing, or older-than-bound quote remains in the raw fields when available but yields a degraded
`unclassified` result. The Full packet's bundled five-level book is not eligible for its own print,
and reconnect boundaries clear the affected depth candidate. The default freshness bound is 1,000
ms and is configurable on the capture CLI; every classified row records the bound actually used.

Only a positive cumulative-volume increment is treated as a newly observed print. The first
cumulative-volume observation establishes a baseline because pre-capture volume is unknown, and an
unchanged snapshot is not re-signed. The state retained per instrument is constant-sized: latest
complete quotes by depth tier, cumulative-volume baseline, current trade price, and prior differing
trade price.

**Downstream consumers.** SIG-03's signed-flow features and SIG-14's Hasbrouck decomposition consume
the capture-time sign together with its version stamp. D23's queue-ahead bounds depend on separating
trades from cancellations at a level, which is exactly what the signed, flagged print record makes
possible.

**Evidence as of 2026-08-19.** Live verified for depth20 alignment on NIFTY and BANKNIFTY
front-month futures in one 10-minute morning window. Two simultaneous Standard+depth20 captures
produced 11,691 rows and 313 positive-volume prints: 158 buy, 154 sell, 1 unclassified; 311
quote-rule, 1 live tick-rule fallback, and 1 degraded because no prevailing quote existed. Every
print row carried both version stamps. Quote age n=312 was 7.4–567.4 ms (median 238.7, p95 462.6)
against the 1 s bound; 113/313 intervals were coalesced and observed last quantities covered only
44.3% of increment volume. The earlier retained-tape dry run remains valid. Live evidence does not
cover options, depth200 selection, other times of day, or stale/crossed degraded causes. DAT-15's
error-distribution/flip-rate study remains a separate requirement.
