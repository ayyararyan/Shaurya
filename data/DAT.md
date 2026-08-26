# DAT — Market data

## Objective

Own the complete Dhan-only market-data access plane: acquisition, broker-neutral identity,
historical bars, option-chain validation, data-quality accounting, permanent lossless raw-tape
storage, catalogue registration, integrity/indexing, deterministic replay and live follow. DAT
supplies the canonical observed input to SIG, BKT, SUR, GRK, VOL, and ANL; it never places orders
(D7, D17, D18, D43).

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
- `CON-10` is the only consumer-facing retrieval boundary: request → dataset handle → DAT
  replay/follow. Compatible active/completed supersets are reused. Consumer identity does not
  create a second acquisition key.
- Only DAT may import broker adapters, read Dhan credentials, open Dhan REST/WebSocket sessions,
  construct subscriptions, write raw tapes or parse/tail raw storage. SUR, SIG, VOL, BKT and ANL
  receive canonical rows through DAT.
- New acquisitions are claimed under a cross-process lock and registered before the socket opens.
  A concurrent compatible request receives the existing active handle and cannot open a duplicate
  socket. Catalogue history is append-only; invalidated data remains registered and preserved.
- Server-backed JSONL is the warm, appendable lossless representation. A sidecar index provides bounded
  time seeking and channel/instrument filtering; a lossless compressed archive is the permanent
  cold representation. Hashes bind tape, index and archive. Moving data between the settled
  `/Volumes/Aryan/NSE/YYYY-MM-DD/` lanes does not change dataset identity or semantics. Archive
  promotion reads the gzip copy back, validates its CRC, and verifies that its decompressed SHA-256
  matches the warm tape; DAT does not delete the warm copy.
- Current Python implementation lives in `src/shaurya/data/` and `src/shaurya/contracts/`; the production C++ order path consumes canonical outputs through contracts and does not duplicate Dhan ingestion.
- GCP scaling, where used, applies only to DAT → SIG → BKT → ANL. It does not move EXE/RSK/NAT off their latency-sensitive Kotak/AWS path.

### Dataset lifecycle and failure semantics

1. A consumer constructs a strict `DatasetRequest` containing the trading date, canonical
   instrument IDs, channels, optional coverage, and whether active data is admissible.
2. `DataAccess.request` resolves a compatible catalogue handle. Consumer and purpose remain in the
   audit record but are excluded from acquisition identity, so multiple consumers can share one
   raw dataset.
3. When acquisition is required, a DAT capture command claims it under a cross-process lock. A
   compatible live claim raises `DatasetAlreadyActiveError` with the existing handle instead of
   opening another broker connection.
4. DAT publishes an active `DatasetHandle` before the first row for consumers using
   `DataAccess.follow`, then publishes a terminal handle with actual coverage, row and byte counts,
   locations, and hashes for `DataAccess.rows`.

An unsatisfied request raises `DatasetUnavailableError`; consumers cannot bypass it by opening
Dhan directly. Malformed catalogue records, tapes, indexes, archives, or hash mismatches fail
closed. Dead producers are excluded from active resolution, completed-only requests never return
active data, and rows outside the claimed channel or instrument set are rejected before
persistence. Unexpected termination remains visible as active/orphaned lifecycle history and
cannot be mistaken for a completed dataset.

Existing tapes remain immutable evidence. `DataAccess.adopt_legacy_tape` validates a tape in a
streaming pass, builds or verifies its seek index, and registers a content-addressed handle without
rewriting old rows. Transport changes do not alter research estimators, causal timing rules, or
execution authority.

## Requirements and traceability

| Requirement | Normative statement | TASKS.md trace | Code target | Test / output target |
|---|---|---|---|---|
| REQ-DAT-01 | Maintain one reconciled market-data-only Dhan client based on Mushin's structure plus Shoshin's retry, pacing, and normalization behaviour; document rejected unsafe/strategy-specific paths. | DAT-01, D7 | `src/shaurya/data/dhan_client.py`; [`DAT_01_RECONCILIATION.md`](DAT_01_RECONCILIATION.md) | `tests/test_dhan_client.py`; reconciliation record |
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
| REQ-DAT-15 | Measure the DAT-14 cross-channel alignment error and coalescing empirically from retained tape as distributions and classification flip rates by activity, depth tier, and time of day; never assume the error is small. | DAT-15, D24 | `src/shaurya/data/alignment_analysis.py`; `scripts/dat15_alignment_analysis.py` | `tests/test_alignment_analysis.py`; dated distribution/flip-rate artifact; Live verified on retained eight-tape sample with explicit coverage limits |
| REQ-DAT-16 | Measure depth delivery by distinct receive-timestamp bursts, rows per burst, burst-gap distribution, and BBO-change rate; never infer event cadence from parsed-row count. | DAT-16, D23 | Retained-tape cadence analysis | `docs/live-evidence/DAT-16-2026-08-19.md`; 500 ms depth20 snapshot cadence live-verified at stated scope |
| REQ-DAT-17 | Measure Full/5-level and depth200 clocks with the DAT-16 method, measure first-versus-later depth200 cadence and usable per-socket capacity, and state D27's binding lower bound for every pair of depth tiers without guessing the upstream mechanism. | DAT-17, D27 | `scripts/dat17_cadence_analysis.py`; `scripts/dat17_depth200_operational_probe.py` | `tests/test_cadence_analysis.py`; `docs/live-evidence/DAT-17-2026-08-19.md`; two 600 s zero-reconnect depth200 tapes and a timed four-future throttle artifact |
| REQ-DAT-18 | Produce the consolidated multi-tier interpretation required for the DAT-09 width-versus-depth decision: admissible layouts, D27 horizon floors, the information gained/lost by Full versus depth20 versus depth200, and explicit separation of measured facts from owner choices. DAT-20's quiet-skip and active-band evidence must amend the earlier implication that depth200 cadence gaps themselves are information loss. | DAT-18, DAT-16, DAT-17, DAT-20, D27, D28 | Dated synthesis under `docs/live-evidence/` and DAT-09 plan update | Evidence-to-claim audit; owner-decision table; no unsupported generalisation beyond measured instruments/windows |
| REQ-DAT-19 | Implement lossless permanent raw-tape storage with stable schema, an append-safe warm JSONL representation, a seekable sidecar index, checksums, a lossless compressed cold archive, catalogue-visible physical locations and explicit retention state. Storage optimisation must preserve the raw level-by-level book needed by SIG-18 and SIG-21; lossy feature-only substitution requires explicit change control. | DAT-19, DAT-05, DAT-09, D12, D28, D42, D43 | `src/shaurya/data/storage.py`; `src/shaurya/data/tape.py`; `src/shaurya/data/access.py` | Daily-layout/mount-failure, round-trip/hash/seek/filter/archive-restore tests; catalogue/index artifacts; production compression/replay benchmark pending |
| REQ-DAT-20 | Pre-register and test whether depth200 cadence gaps represent quiet-book intervals or feed loss by simultaneous single-clock Full, depth20 and depth200 capture; compare cross-tier containment, price-keyed change intensity, duration-matched skip windows and actual occupancy/span. Preserve residual phase-versus-content differences as not discriminated where exchange time/source sequence is unavailable, and do not infer rare-event predictability from feed observability. | DAT-20, D22, D27, D28 | `src/shaurya/data/depth_thinning_analysis.py`; `scripts/dat20_thinning_vs_loss_analysis.py` | `tests/test_depth_thinning_analysis.py`; `docs/live-evidence/DAT-20-2026-08-19.md`; retained three-tier tapes and result artifacts |
| REQ-DAT-21 | Provide a protocol-locked, read-only full-session capture of the same-day NIFTY front-month future on Standard/Full, depth20 and depth200; use the date-versioned NSE F&O clock, prove actual per-channel timestamp coverage rather than requested duration, retain immutable identity/hashes, and keep OFI outcome permission distinct from SIG-21 calibration eligibility. | DAT-21, D27, D33, D36 | `src/shaurya/cli/capture_dhan.py`; full-session controller | Capture-profile and coverage-boundary tests; retained run manifest/metrics/quality/acceptance receipt |
| REQ-DAT-22 | Expose the single DAT gateway for `CON-10` requests. Resolve compatible active/completed dataset supersets from one append-only catalogue; claim new capture under a cross-process lock; return immutable handles; expose validated indexed replay, complete-line live follow and legacy-tape adoption; and reject duplicate compatible acquisition. No downstream module may receive credentials or broker objects. | DAT-22, D43 | `src/shaurya/data/access.py`; `src/shaurya/cli/capture_dhan.py`; `src/shaurya/cli/capture_chain.py` | Contract/catalogue/claim/race/replay/follow/adoption tests; architecture import-boundary test; shared SUR/SIG request integration |

Dropped task DAT-08 has no requirement: Kotak market-data reception is excluded by D18.

## Current DAT-09 working constraint — measured, not final

- **20-level socket behaviour:** DAT-12 discriminates the reproduced 50+50 failure as **socket-scoped**: the second 50-instrument message failed on the occupied socket and succeeded unchanged on a fresh socket. A 2+2 control accepted both messages on one socket, so the effect is load-dependent rather than a universal first-message-only rule.
- **Measured per-message ceiling:** **50 instruments** in the 2026-08-19 live probe. Fresh one-message sockets accepted every tested count through 50 and rejected 51, 52 and 53 wholesale; the prior-day statement that 52 worked did not reproduce and is superseded by the same-day boundary evidence. This is an observed endpoint constraint, not a broker guarantee across future protocol/account changes.
- **Measured per-instrument 20-level cadence:** NIFTY-Aug2026-FUT received 116 parsed rows in 15
  seconds inside the 50-instrument subscription, then 116, 120, 114, and 114 in four fresh-socket
  solo runs. Removing 49 instruments did not materially raise the row rate, ruling out shared
  socket bandwidth collapse, but the solo test is `not-discriminated` for cap versus event rate.
  DAT-16 supplies the correct semantic unit: 2.00 same-timestamp snapshot bursts/s, ~4.17 rows per
  burst, and a 500 ms D23 netting bound. Within-window exchange events remain unidentified.
- **200-level evidence:** DAT-17 measured 4.1588–4.1589 receive-timestamp bursts/s on two independent 600 s NIFTY captures, with a 200.5 ms median gap but a 400.8–401.1 ms p95 from skipped base ticks. A timed four-future socket delivered recurring updates only to subscription position 1; positions 2–4 received one startup bid/ask pair and then remained silent for approximately 89.9 s. The observed usable recurring-feed ceiling is therefore **one depth200 instrument per socket**; the exact ceiling for nominal initial-snapshot acknowledgements above four remains unidentified.
- **Retention:** permanent. Once captured, raw data is kept; there is no rolling deletion or expiry window.
- **Universe:** NSE index F&O only—NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY. Single-stock depth and BSE deep book are out of current scope. Exact depth-tier strike bands such as ATM±7 remain illustrative, not committed.

## Outputs and acceptance tests

- Versioned append-only JSONL conforming to `CON-01`, a seek index, optional lossless cold archive,
  one `CON-08` manifest, one `CON-10` dataset handle, hashes, metrics, and quality audit.
- Acceptance is per enabled channel: a connected socket and successful heartbeat with zero packets is a failure, not success.
- Parser fixtures cover standard packet subtypes, separate deep-book sides, partial books, 20/200-level layouts, and the 200-level flat subscription envelope.
- Reconnect tests preserve a visible gap boundary and resubscribe semantics.
- Deterministic replay produces the same ordered rows, quality flags, and consumer-visible events from the same tape.
- Physical placement is now configured at `/Volumes/Aryan/NSE/YYYY-MM-DD/` on the verified
  `//Aryan@172.20.10.38/Aryan` SMB share. Normal live DAT capture defaults to the daily `raw/`
  lane and fails closed if the share is not mounted. A local `--output-root` is rejected unless
  the controlled-test override is also explicit.
- Two compatible consumer requests resolve to the same dataset ID; a second capture claim cannot
  open a socket. Replay/follow consumers import DAT only and contain no Dhan credential or adapter
  code.
- Existing evidence remains scoped: DAT-01/03/04/07 are Tested; DAT-02 and DAT-10-17 are Live
  verified at their stated scopes; DAT-20 is Live verified for its central feed-observability
  claim at its stated scope; DAT-05 is Dry-run verified end to end (its writer retains earlier
  live evidence); DAT-06 is Dry-run verified; DAT-09 planning/pooling is Tested. DAT-18 and
  production-volume verification of the new DAT-19/DAT-22 server access plane remain pending.

## Exclusions

- Dhan or Kite order placement (D7, D17).
- Kotak market-data ingestion (D18; DAT-08 dropped).
- Tick-history claims for DAT-03 bars.
- True order identity, FIFO rank, per-order lifetime, or cancellation attribution.
- Single-stock order-book capture; BSE deep-book capture; committed SENSEX/BANKEX infrastructure.
- Any invented exact 20-level ceiling, exact connection count, or strike-band width.

## Deferred and open items

- **DAT-11/12/13:** the 2026-08-19 market-hours probes and DAT-11 solo-rate addendum are complete
  at their stated scopes; see the dated evidence files. The addendum does not alter the measured
  50-instrument per-message ceiling.
- **DAT-09:** derive the exact depth bands and connection-count plan from the completed capacity
  measurements; retention is already permanently settled. The exact 200-level instrument-count
  ceiling remains unmeasured.
- **DAT-15 coverage expansion:** options, midday, and a healthy simultaneous depth200-aligned
  capture remain unmeasured; the existing stressed cross-tier comparison does not identify a
  general depth-tier ranking.
- **DAT-18:** the consolidated feed interpretation remains an owner-discussion item; DAT-20 does
  not silently settle the final width-versus-depth portfolio.
- **DAT-19/DAT-22:** the server-backed lossless catalogue/index/archive/access plane is implemented and
  repository-tested on the settled server/date layout. Production-volume shared follow and
  archive throughput/compression remain separate operational verification; they do not permit
  consumer-owned Dhan access in the interim.

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

**DAT-14 evidence as of 2026-08-19.** Live verified for depth20 alignment on NIFTY and BANKNIFTY
front-month futures in one 10-minute morning window. Two simultaneous Standard+depth20 captures
produced 11,691 rows and 313 positive-volume prints: 158 buy, 154 sell, 1 unclassified; 311
quote-rule, 1 live tick-rule fallback, and 1 degraded because no prevailing quote existed. Every
print row carried both version stamps. Quote age n=312 was 7.4–567.4 ms (median 238.7, p95 462.6)
against the 1 s bound; 113/313 intervals were coalesced and observed last quantities covered only
44.3% of increment volume. The earlier retained-tape dry run remains valid. Live evidence does not
cover options, other times of day, or stale/crossed degraded causes.

**DAT-15 evidence as of 2026-08-19.** Live verified for the retained eight-tape sample: 38,572
rows and 482 positive-volume prints. The healthy-core quote-age distribution has n=323, median
238.7 ms, p95 462.6 ms and max 567.4 ms; the first post-print complete-BBO diagnostic proxy flips
5/320 directional comparisons (1.56%). The all-tape result includes a stressed simultaneous
depth20/depth200 run with 39 reconnect boundaries: quote-age n=480, median 212.1 ms, p95 3.82 s,
max 24.16 s, 42 degraded prints, and 5/429 proxy flips. Coalescing is 206/482, with unseen excess
volume median 180, p95 2,080 and max 7,215 units. The post-print comparator is labelled a proxy:
deep packets lack exchange timestamps/source sequence, so the true exchange-time quote and true
classification error remain unidentified. Depth200 occurs only in the stressed run; afternoon
has n=12; midday and options have no aligned prints. No unsupported general tier/time inference is
made.
