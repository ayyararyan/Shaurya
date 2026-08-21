# DAT single-access architecture (D43)

**Status:** binding internal architecture  
**Decision:** `TASKS.md` D43  
**Contracts:** CON-10  
**Implementation:** DAT-19/DAT-22, SUR-09, SIG-23, ANL-08

## Ownership

DAT alone owns:

- Dhan credential loading, REST/WebSocket adapters, subscription limits and capture lifecycle;
- the cross-process acquisition claim and append-only dataset catalogue;
- canonical raw-tape persistence, manifests, hashes, seek indexes and lossless archives;
- deterministic replay, bounded retrieval, growing-file follow and legacy-tape adoption.

SUR, SIG, VOL, BKT and ANL own their transformations and estimators. They do not import Dhan
adapters, parse broker packets, construct capture writers, search run directories, or maintain a
second JSONL transport.

## Request-to-ingestion flow

1. A consumer constructs a strict `DatasetRequest`: trading date, canonical instrument IDs,
   channels, optional coverage, and whether an active dataset is admissible.
2. `DataAccess.request` resolves a compatible catalogue handle. Consumer and purpose are retained
   for audit but excluded from acquisition identity, allowing eSSVI and OFI to share raw data.
3. If acquisition is needed, a DAT capture command claims it under a cross-process lock. A
   compatible live claim fails closed with `DatasetAlreadyActiveError` carrying the existing
   handle; no second broker connection is opened.
4. DAT publishes an active `DatasetHandle` before the first row. Consumers may follow it through
   `DataAccess.follow`.
5. DAT closes the tape and publishes a terminal handle with actual coverage, row/byte counts,
   tape/index/archive locations and hashes. Consumers replay or filter rows through
   `DataAccess.rows`.

An unsatisfied request raises `DatasetUnavailableError`; a consumer cannot bypass that result by
opening Dhan itself. Capture scheduling is a DAT operational concern.

## Physical storage and integrity

- **Archive root:** production uses the verified SMB share at
  `/Volumes/Aryan/NSE/YYYY-MM-DD/`. Raw runs live under `raw/`; the shared lifecycle catalogue
  defaults to `metadata/datasets.jsonl`; `indexes/` and `derived/` are stable companion lanes.
  A missing/wrong mount fails closed, and local paths require the explicit controlled-test gate.
- **Warm canonical copy:** append-only JSONL under the run manifest. This remains the exact raw
  evidence required by D12/SIG-18 and is never replaced with feature-only data.
- **Seek sidecar:** JSON index built while writing, with byte checkpoints, actual coverage,
  channel/instrument row counts and the warm-tape SHA-256. It supports bounded retrieval without
  changing row semantics.
- **Cold copy:** optional gzip archive. Promotion reads the archive back, validates gzip CRC, and
  verifies that decompressed SHA-256 equals the warm tape. The warm copy is not deleted by DAT.
- **Catalogue:** append-only JSONL snapshots of dataset lifecycle under file locking. Published
  tape, index and archive hashes are rechecked at read time; mismatches fail closed.
- **Retention:** permanent. Storage tiering changes location/encoding only, never the underlying
  canonical rows.

## Compatibility

Existing retained tapes are immutable evidence. `DataAccess.adopt_legacy_tape` validates them in
a streaming pass, builds or verifies the seek index, registers a content-addressed handle, and
then exposes the same DAT replay API. No migration rewrites old rows.

The former `surface_dashboard --mode live` spelling remains an alias for DAT `follow`; it no
longer opens a Dhan socket. OFI full-session analysis still runs its frozen estimators on the exact
same canonical tape, but the controller obtains that tape only from a DAT handle.

## Failure semantics

- malformed catalogue records, tapes, indexes or hashes fail closed;
- active handles whose producer PID has died are not returned;
- completed-only requests never resolve an active dataset;
- a row outside the capture's claimed channel or instrument set is rejected before persistence;
- unexpected capture termination leaves a visible active/orphaned lifecycle record and cannot
  be mistaken for a completed dataset.

This architecture changes neither research meaning nor execution authority. DAT returns observed
market data; consumers remain responsible for their existing causal, statistical and labelling
contracts, and no component gains order authority from a dataset handle.
