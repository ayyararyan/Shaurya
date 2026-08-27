# Data sources and lineage

This catalogue describes sources observed in repository code and retained documentation. It did
not contact external services, use credentials, or run a live/broker path. Absolute paths embedded
in old artifacts are host-specific references and were not assumed to exist on this machine.

## Canonical Shaurya Data catalogue and tapes

Research consumes completed dataset handles through the public `shaurya.data` facade. The expected
archive convention documented by the project is `/Volumes/Aryan/NSE/YYYY-MM-DD/{raw,metadata,
indexes,derived}` with a `metadata/datasets.jsonl` catalogue. A usable source requires completed
lifecycle state, manifest and coverage agreement, content SHA-256, a hash-bound seek index, and
full replay row-count agreement. JSONL tape rows carry instrument/channel, receive/exchange timing,
connection epoch, quality flags, book levels, and feed-specific volume fields. Raw evidence is
append-only and is never copied into this catalogue.

The quality-aware post-close memo records one completed 2026-08-26 dataset with 1,935,092 rows and
all 121 requested instruments observed, plus four connection epochs, three localized reconnects,
374 partial-book initialization rows, 16 exchange-time regressions, and unavailable source packet
sequence. Those facts are verified from the existing memo, not replayed in this catalogue. They
therefore support an exploratory result boundary, not a blanket completeness claim.

## Standard / Full channel

Used for BBO/five-level state, option/futures midpoint, displayed spread, microprice, five-level
imbalance, and cumulative-volume-increment activity. It is an aggregate snapshot/event feed. It
does not expose order IDs, queue position, native add/modify/cancel events, or fills. Cumulative
volume increments may represent coalesced activity and are labelled as a proxy, not MBO.

## Depth20

Used for displayed midpoint response labels, reference-price paths, L1/near-book controls, and
some option-chain state. Rows are merged into `BookState` objects by receive time and connection
epoch. Partial/crossed books, invalid quality flags, unavailable endpoints, stale as-of matches,
and epoch crossings are rejected or retained as explicit quality failures.

## Depth200

Used for CCZ multi-level OFI, depth occupancy/activity, and price-keyed deep-book event
construction. The deep-book construction detector treats relocation only as a displayed-liquidity
proxy because anonymous order identity is unavailable. `DAT-20` retained runs validate
construction and short-window activity only; the SIG-21 future-response gate remains without a
located confirmatory result.

## Surface frames

Option quote rows are combined with a causal forward source (traded future preferred; put-call
parity fallback) and fitted into eSSVI frames. Frames carry expiry, support, calibration,
staleness, smoothing, and arbitrage diagnostics. Unsupported cells remain null. The D51 result
documents a separate 2026-08-21 surface dataset whose capture began late; economic surface fields
failed the 50% coverage gate while some quality fields survived. No pre-capture surface state was
fabricated.

## Fixtures and synthetic sources

Files under `research/tests/fixtures` and in-memory synthetic tapes verify contracts, formulas,
causal alignment, and methodology. They are not market evidence. Any output derived solely from
them must identify `source_dataset=synthetic_fixture`.

## Completeness and session conventions

Receive timestamps are stored as instants (often nanoseconds/UTC); market-session labels use IST.
The dated NSE equity-derivatives session helper uses 09:15–15:30 before 2026-08-03 and 09:15–15:40
on/after that date. Requested duration does not establish coverage. Cancelled, `artifact_failed`,
partial, stale, malformed, or merely endpoint-readable captures must never be described as
complete; absence of native source sequence also prevents claims of upstream packet completeness.
